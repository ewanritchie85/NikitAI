"""Claude-powered, domain-agnostic assistant agent driven by injected tool config.

The :class:`Agent` is parameterized by a system prompt, tool definitions, a tool
dispatcher, and the set of confirmation-gated tools. It contains no domain-specific
content — sub-agent configurations (Outlook, Platform Nerd, etc.) live under
:mod:`nikitai.subagents`, and routing/classification concerns live in
:mod:`nikitai.orchestrator`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import anthropic

from .auth import get_access_token

# Last-resort model if neither a sub-agent's specific override nor the shared
# NIKITAI_DEFAULT_MODEL is set in the environment.
DEFAULT_MODEL = "claude-sonnet-5"

# Default timezone used when building a system prompt's current-time anchor.
UK_TIMEZONE = ZoneInfo("Europe/London")

# Signature of a tool dispatcher: (tool_name, inputs, token) -> (result_str, refreshed_token).
ToolDispatcher = Callable[[str, dict[str, Any], str], "tuple[str, str | None]"]


def resolve_model(specific_env_var: str) -> str:
    """Resolve a sub-agent's model with a clear precedence chain.

    Order: the sub-agent's own override (``specific_env_var``) →
    ``NIKITAI_DEFAULT_MODEL`` → hardcoded :data:`DEFAULT_MODEL`. This lets each
    sub-agent pick a model appropriate to its workload while sharing one default.
    """
    return (
        os.environ.get(specific_env_var) or os.environ.get("NIKITAI_DEFAULT_MODEL") or DEFAULT_MODEL
    )


def build_system_prompt(template: str, tz: ZoneInfo = UK_TIMEZONE) -> str:
    """Fill a system-prompt template's ``{now}`` with the current localized datetime.

    Domain-agnostic: any sub-agent whose prompt wants a current-time anchor can
    reuse this instead of duplicating the Europe/London formatting logic.
    """
    now = datetime.now(tz)
    formatted_now = f"{now.strftime('%A, %-d %B %Y, %H:%M')} {now.tzname()}"
    return template.format(now=formatted_now)


@dataclass
class PendingConfirmation:
    """A tool call awaiting external approval before `Agent.confirm()` runs it."""

    id: str
    tool_name: str
    tool_input: dict[str, Any]


@dataclass
class AgentResponse:
    """Result of `Agent.send()`/`Agent.confirm()`.

    `text` may accompany `pending` (narration before the tool call); `error` is
    mutually exclusive with the other two.
    """

    text: str | None = None
    pending: PendingConfirmation | None = None
    error: str | None = None


# Strict, deterministic reply phrases for resolving a pending confirmation — no LLM
# judgment call involved. Anything that is not an exact normalized match is treated
# as "not a confirmation reply" (see classify_confirmation_reply).
_CONFIRMATION_AFFIRMATIONS: frozenset[str] = frozenset(
    {
        "y",
        "yes",
        "yeah",
        "yea",
        "yep",
        "yup",
        "sure",
        "ok",
        "okay",
        "go",
        "go ahead",
        "go for it",
        "do it",
        "please",
        "please do",
        "yes please",
        "confirm",
        "confirmed",
        "proceed",
        "affirmative",
        "agreed",
        "sounds good",
        "sounds right",
        "approve",
        "approved",
    }
)

_CONFIRMATION_NEGATIONS: frozenset[str] = frozenset(
    {
        "n",
        "no",
        "nope",
        "nah",
        "cancel",
        "cancel it",
        "decline",
        "declined",
        "abort",
        "dont",
        "don't",
        "do not",
        "no thanks",
        "no thank you",
        "stop",
        "never mind",
        "nevermind",
        "forget it",
        "deny",
        "denied",
        "not now",
    }
)


def classify_confirmation_reply(text: str) -> str:
    """Classify a user reply to a pending confirmation as "affirm", "negate", or "other".

    Strict and deterministic: the text is lowercased, stripped, and shorn of trailing
    punctuation, then compared exactly against curated phrase sets. No LLM is involved.
    Anything that is not an exact match — including compound messages like
    "yes, and also check my logs" — returns "other", so the caller treats it as an
    implicit cancel and re-routes through normal classification.
    """
    normalized = text.strip().lower().rstrip(".!?")
    if normalized in _CONFIRMATION_AFFIRMATIONS:
        return "affirm"
    if normalized in _CONFIRMATION_NEGATIONS:
        return "negate"
    return "other"


@dataclass
class _PendingToolUse:
    """Internal state needed to resume a paused conversation turn after confirmation."""

    assistant_content: list[Any]
    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any]
    completed_results: list[dict[str, str]]
    remaining_blocks: list[Any]


class Agent:
    """Drives a Claude conversation with tool use, independent of any UI or domain.

    The agent is parameterized by a system prompt, tool definitions, a tool
    dispatcher, and the set of tools that require confirmation, so the same class
    can back multiple sub-agents (Outlook, home infra logs, Garmin, etc.).

    Callers interact only through `send()` and `confirm()`; neither blocks on
    terminal input, so this class can be driven by a CLI, a web backend, etc.
    """

    def __init__(
        self,
        system_prompt: str,
        tool_definitions: list[dict],
        tool_dispatcher: ToolDispatcher,
        confirmation_required_tools: set[str],
        model: str = DEFAULT_MODEL,
    ) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.token = get_access_token()
        self.messages: list[dict] = []
        self._pending: dict[str, _PendingToolUse] = {}
        self.system_prompt = system_prompt
        self.tools = tool_definitions
        self.tool_dispatcher = tool_dispatcher
        self.confirmation_required_tools = confirmation_required_tools
        self.model = model

    def send(self, user_text: str) -> AgentResponse:
        self.messages.append({"role": "user", "content": user_text})
        return self._run_loop()

    def stream_send(self, user_text: str):
        """Stream a user turn, yielding ``(kind, payload)`` events.

        Yields ``("text", chunk)`` for each text delta as it arrives, then a
        single terminal ``("done", AgentResponse)``. Multi-turn tool loops
        stream each assistant text block in turn, so a reply that narrates,
        runs tools, and narrates again appears progressively. A terminal
        ``done`` is always emitted (text, pending, or error) so callers can
        finalize the UI deterministically.
        """
        self.messages.append({"role": "user", "content": user_text})
        yield from self._stream_loop()

    def stream_confirm(self, pending_id: str, approved: bool):
        """Stream the follow-up to a confirmation, yielding the same event shape
        as :meth:`stream_send`. The narration before the pending tool call was
        already shown to the user, so only the post-approval turn is streamed.
        """
        pending = self._pending.pop(pending_id, None)
        if pending is None:
            yield "done", AgentResponse(error=f"Unknown confirmation id: {pending_id!r}")
            return

        if approved:
            result_str, new_token = self.tool_dispatcher(
                pending.tool_name, pending.tool_input, self.token
            )
            if new_token:
                self.token = new_token
        else:
            result_str = "User declined to run this action."

        results = [
            *pending.completed_results,
            {"type": "tool_result", "tool_use_id": pending.tool_use_id, "content": result_str},
        ]

        outcome = self._process_blocks(pending.remaining_blocks, pending.assistant_content, results)
        if isinstance(outcome, PendingConfirmation):
            yield "done", AgentResponse(pending=outcome)
            return

        self.messages.append({"role": "assistant", "content": pending.assistant_content})
        self.messages.append({"role": "user", "content": outcome})
        yield from self._stream_loop()

    def stream_resolve_pending_reply(self, pending_id: str, user_text: str):
        """Streaming variant of :meth:`resolve_pending_reply`.

        Yields nothing when the message is not a confirmation reply (so the
        caller falls through to normal classification), otherwise streams the
        resolution exactly like :meth:`stream_confirm`.
        """
        if pending_id not in self._pending:
            return
        decision = classify_confirmation_reply(user_text)
        if decision == "other":
            self._pending.pop(pending_id, None)
            return
        yield from self.stream_confirm(pending_id, approved=(decision == "affirm"))

    def confirm(self, pending_id: str, approved: bool) -> AgentResponse:
        pending = self._pending.pop(pending_id, None)
        if pending is None:
            return AgentResponse(error=f"Unknown confirmation id: {pending_id!r}")

        if approved:
            result_str, new_token = self.tool_dispatcher(
                pending.tool_name, pending.tool_input, self.token
            )
            if new_token:
                self.token = new_token
        else:
            result_str = "User declined to run this action."

        results = [
            *pending.completed_results,
            {"type": "tool_result", "tool_use_id": pending.tool_use_id, "content": result_str},
        ]

        outcome = self._process_blocks(pending.remaining_blocks, pending.assistant_content, results)
        if isinstance(outcome, PendingConfirmation):
            return AgentResponse(pending=outcome)

        self.messages.append({"role": "assistant", "content": pending.assistant_content})
        self.messages.append({"role": "user", "content": outcome})
        return self._run_loop()

    def resolve_pending_reply(self, pending_id: str, user_text: str) -> AgentResponse | None:
        """Resolve a pending confirmation from a free-text user reply, with no LLM call.

        The orchestrator routes the user's message here verbatim ("sticky routing")
        instead of re-classifying it, and the decision is strict pattern matching:

        - clear affirmation -> ``confirm(pending_id, approved=True)``: execute it
        - clear negation    -> ``confirm(pending_id, approved=False)``: cancel it
        - anything else     -> drop the pending state and return ``None`` (implicit
          cancel), so the caller can hand the message back to normal classification.

        Returns ``None`` when the message is not a confirmation reply, or when
        ``pending_id`` is no longer pending.
        """
        if pending_id not in self._pending:
            return None
        decision = classify_confirmation_reply(user_text)
        if decision == "other":
            self._pending.pop(pending_id, None)
            return None
        return self.confirm(pending_id, approved=(decision == "affirm"))

    def _run_loop(self) -> AgentResponse:
        while True:
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=self.system_prompt,
                    tools=self.tools,
                    messages=self.messages,
                )
            except anthropic.APIError as exc:
                return AgentResponse(error=str(exc))

            tool_use_blocks = [block for block in response.content if block.type == "tool_use"]
            outcome = self._process_blocks(tool_use_blocks, response.content, [])

            assistant_text = "".join(
                block.text for block in response.content if block.type == "text"
            )

            if isinstance(outcome, PendingConfirmation):
                return AgentResponse(text=assistant_text or None, pending=outcome)

            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                self.messages.append({"role": "user", "content": outcome})
                continue  # loop back to let Claude process tool results

            return AgentResponse(text=assistant_text)

    def _stream_loop(self):
        """Streaming counterpart to :meth:`_run_loop`.

        Yields ``("text", chunk)`` as each text delta arrives, and ends with a
        single ``("done", AgentResponse)``. Tool-use iterations re-enter the
        loop internally (tools run synchronously); only assistant *text* is
        streamed out, so a long tool-bound turn never blocks the UI silently —
        whatever text Claude emits before/after tool calls appears as it is
        produced.
        """
        while True:
            try:
                with self.client.messages.stream(
                    model=self.model,
                    max_tokens=4096,
                    system=self.system_prompt,
                    tools=self.tools,
                    messages=self.messages,
                ) as stream:
                    text_parts: list[str] = []
                    for chunk in stream.text_stream:
                        text_parts.append(chunk)
                        yield "text", chunk
                    response = stream.get_final_message()
            except anthropic.APIError as exc:
                yield "done", AgentResponse(error=str(exc))
                return

            tool_use_blocks = [block for block in response.content if block.type == "tool_use"]
            outcome = self._process_blocks(tool_use_blocks, response.content, [])

            assistant_text = "".join(text_parts)

            if isinstance(outcome, PendingConfirmation):
                yield "done", AgentResponse(text=assistant_text or None, pending=outcome)
                return

            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                self.messages.append({"role": "user", "content": outcome})
                continue

            yield "done", AgentResponse(text=assistant_text)
            return

    def _process_blocks(
        self,
        blocks: list[Any],
        assistant_content: list[Any],
        results: list[dict[str, str]],
    ) -> list[dict[str, str]] | PendingConfirmation:
        """Executes tool_use blocks in order, pausing at the first one needing confirmation."""
        for index, block in enumerate(blocks):
            if block.name in self.confirmation_required_tools:
                pending_id = uuid.uuid4().hex
                self._pending[pending_id] = _PendingToolUse(
                    assistant_content=assistant_content,
                    tool_use_id=block.id,
                    tool_name=block.name,
                    tool_input=block.input,
                    completed_results=results,
                    remaining_blocks=blocks[index + 1 :],
                )
                return PendingConfirmation(
                    id=pending_id, tool_name=block.name, tool_input=block.input
                )

            result_str, new_token = self.tool_dispatcher(block.name, block.input, self.token)
            if new_token:
                self.token = new_token
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_str})
        return results
