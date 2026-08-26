"""Top-level NikitAI orchestrator that routes messages to domain sub-agents.

"NikitAI" is the orchestrator; each domain is handled by a sub-agent backed by
the generalized :class:`~nikitai.agent.Agent`. Sub-agent configurations live under
:mod:`nikitai.subagents` (Organiser = Outlook, Platform Nerd = home infra,
Trainer = Garmin health/fitness).

Flow:
- ``send()`` runs a cheap classification call to pick a registered sub-agent, then
  dispatches the message to that sub-agent's ``Agent.send()``. If the classifier is
  unsure, it asks the user to clarify rather than guessing.
- Sticky routing: if a sub-agent is mid-confirmation (a PendingConfirmation is live),
  the next ``send()`` skips classification and routes the message straight back to
  that sub-agent, which resolves it by strict pattern matching
  (``Agent.resolve_pending_reply``). Non-replies are implicit cancels and fall
  through to normal classification.
- Last-active fallback: if classification returns "unclear" (or an unregistered key),
  and a sub-agent was used most recently (``_last_active_key``), the message goes to
  that sub-agent instead of the clarification prompt. This catches conversational
  replies like "yes" that arrive before any tool call has raised a PendingConfirmation.
  A confidently classified registered key always wins over the fallback.
- ``confirm()`` is routed back to the exact sub-agent instance that produced the
  pending confirmation (never re-classified), via a pending_id -> sub-agent map.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import anthropic

from .agent import Agent, AgentResponse
from .subagents.home_wizard import home_wizard_agent_config
from .subagents.organiser import outlook_agent_config
from .subagents.platform_nerd import platform_nerd_agent_config
from .subagents.trainer import trainer_agent_config

# Last-resort router model if NIKITAI_ROUTER_MODEL is not set.
# A cheap/fast model is preferred here since routing is a tiny classification.
# Routing/classification is an orchestrator-level concern, not core Agent infra, so
# this lives here rather than in agent.py.
DEFAULT_ROUTER_MODEL = "claude-haiku-4-5"


def resolve_router_model() -> str:
    """Resolve the orchestrator's routing model.

    Order: ``NIKITAI_ROUTER_MODEL`` → :data:`DEFAULT_ROUTER_MODEL`.
    Resolved per call so tests and runtime env changes are honored.
    """
    return os.environ.get("NIKITAI_ROUTER_MODEL") or DEFAULT_ROUTER_MODEL


@dataclass(frozen=True)
class SubAgentSpec:
    """A registered domain sub-agent.

    ``config_factory`` returns kwargs matching :func:`outlook_agent_config`'s shape,
    i.e. ``system_prompt``/``tool_definitions``/``tool_dispatcher``/
    ``confirmation_required_tools``, ready to spread into ``Agent(**config)``.
    """

    key: str
    display_name: str
    description: str
    config_factory: Callable[[], dict[str, Any]]


# ── Sub-agent registry ───────────────────────────────────────────────────────
# All fully-implemented sub-agents belong here; each factory has exactly one
# canonical import path (its own subagents module) and resolves its model via
# agent.resolve_model("<SPECIFIC>_MODEL", "<hardcoded_default>").
SUB_AGENT_REGISTRY: dict[str, SubAgentSpec] = {
    "organiser": SubAgentSpec(
        key="organiser",
        display_name="NikitAI Organiser",
        description="Outlook email and calendar: reading, searching, sending mail, "
        "managing mail folders, and creating/listing calendar events.",
        config_factory=outlook_agent_config,
    ),
    "platform_nerd": SubAgentSpec(
        key="platform_nerd",
        display_name="NikitAI Platform Nerd",
        description="home network configuration, self-hosting, Raspberry Pi, and "
        "general networking/infrastructure questions.",
        config_factory=platform_nerd_agent_config,
    ),
    "trainer": SubAgentSpec(
        key="trainer",
        display_name="NikitAI Trainer",
        description="fitness, workouts, sleep, recovery, and general health/training "
        "questions based on Garmin Connect data.",
        config_factory=trainer_agent_config,
    ),
    "home_wizard": SubAgentSpec(
        key="home_wizard",
        display_name="NikitAI Home Wizard",
        description="smart home automation — currently lighting control: turning lights "
        "on/off, dimming, changing colour.",
        config_factory=home_wizard_agent_config,
    ),
}


def _build_router_prompt(registry: dict[str, SubAgentSpec]) -> str:
    lines = [
        "You are a router for NikitAI, a personal assistant made of specialized "
        "sub-agents. Classify the user's message into exactly one sub-agent by its key.",
        "",
        "Available sub-agents:",
    ]
    for spec in registry.values():
        lines.append(f'- "{spec.key}" ({spec.display_name}): {spec.description}')
    lines += [
        "",
        'If the message does not clearly belong to any sub-agent, answer "unclear".',
        "Respond with ONLY the single lowercase key (or the word unclear) and nothing else.",
    ]
    return "\n".join(lines)


class Orchestrator:
    """Routes user messages to registered domain sub-agents.

    One :class:`Agent` is lazily constructed per registered sub-agent on first use
    (mirroring the previous single-agent lazy init), so authentication and client
    setup only happen for sub-agents that are actually exercised.
    """

    def __init__(self, registry: dict[str, SubAgentSpec] | None = None) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.registry = registry if registry is not None else SUB_AGENT_REGISTRY
        self._agents: dict[str, Agent] = {}
        # Maps a pending confirmation id to the sub-agent key that produced it, so
        # confirm() never has to re-classify.
        self._pending_routes: dict[str, str] = {}
        # Key of the most recently used sub-agent. Distinct from _pending_routes: used
        # as a fallback when the classifier returns "unclear", so off-topic replies
        # (e.g. a bare conversational "yes" before any tool call has fired) stay with
        # the sub-agent that was already in conversation.
        self._last_active_key: str | None = None

    # ── Public API ───────────────────────────────────────────────────────────

    def send(self, user_text: str) -> AgentResponse:
        # Sticky-pending routing: if a sub-agent is mid-confirmation, its reply goes
        # straight back to it without re-classifying. The sub-agent resolves it by
        # strict pattern matching; if the message isn't a confirmation reply it is an
        # implicit cancel, and we fall through to normal classification. Separate from
        # the last-active fallback below; they chain in practice but serve different
        # phases of the confirmation UX.
        active = self._active_pending()
        if active is not None:
            pending_id, key = active
            response = self._get_agent(key).resolve_pending_reply(pending_id, user_text)
            self._pending_routes.pop(pending_id, None)
            if response is not None:
                self._last_active_key = key
                self._track_pending(key, response)
                return response

        key = self._classify(user_text)
        if key not in self.registry:
            # Last-active fallback: an "unclear" (or unregistered) reply stays with the
            # most recently used sub-agent — e.g. a bare conversational "yes" to a
            # "shall I proceed?" that arrives before any tool call has raised a
            # PendingConfirmation. A simple "was there a last-active key" check, no LLM
            # call. A confidently classified registered key above would already have
            # won; this branch only runs when classification found no clear domain.
            if self._last_active_key is None:
                return AgentResponse(text=self._clarify_text())
            key = self._last_active_key

        agent = self._get_agent(key)
        response = agent.send(user_text)
        self._last_active_key = key
        self._track_pending(key, response)
        return response

    def confirm(self, pending_id: str, approved: bool) -> AgentResponse:
        key = self._pending_routes.get(pending_id)
        if key is None:
            return AgentResponse(error=f"Unknown confirmation id: {pending_id!r}")

        agent = self._get_agent(key)
        response = agent.confirm(pending_id, approved)
        # This pending id is now resolved; drop it and record any follow-on pending.
        self._pending_routes.pop(pending_id, None)
        self._track_pending(key, response)
        return response

    def stream_send(self, user_text: str):
        """Streaming counterpart to :meth:`send`, yielding ``(kind, payload)`` events.

        Mirrors ``send()`` routing exactly (sticky-pending, classification,
        last-active fallback) and then delegates to the sub-agent's
        :meth:`~nikitai.agent.Agent.stream_send`, which emits ``("text", chunk)``
        events followed by a terminal ``("done", AgentResponse)``.
        """
        active = self._active_pending()
        if active is not None:
            pending_id, key = active
            response = self._get_agent(key).resolve_pending_reply(pending_id, user_text)
            self._pending_routes.pop(pending_id, None)
            if response is not None:
                self._last_active_key = key
                self._track_pending(key, response)
                yield "done", response
                return

        key = self._classify(user_text)
        if key not in self.registry:
            if self._last_active_key is None:
                yield "done", AgentResponse(text=self._clarify_text())
                return
            key = self._last_active_key

        agent = self._get_agent(key)
        self._last_active_key = key
        for kind, payload in agent.stream_send(user_text):
            if kind == "done":
                self._track_pending(key, payload)
            yield kind, payload

    def stream_confirm(self, pending_id: str, approved: bool):
        """Streaming counterpart to :meth:`confirm`."""
        key = self._pending_routes.get(pending_id)
        if key is None:
            yield "done", AgentResponse(error=f"Unknown confirmation id: {pending_id!r}")
            return

        agent = self._get_agent(key)
        for kind, payload in agent.stream_confirm(pending_id, approved):
            if kind == "done":
                self._pending_routes.pop(pending_id, None)
                self._track_pending(key, payload)
            yield kind, payload

    # ── Internals ────────────────────────────────────────────────────────────

    def _get_agent(self, key: str) -> Agent:
        agent = self._agents.get(key)
        if agent is None:
            agent = Agent(**self.registry[key].config_factory())
            self._agents[key] = agent
        return agent

    def _active_pending(self) -> tuple[str, str] | None:
        """Return the active (pending_id, sub-agent key), or None if none is pending.

        The orchestrator runs one live turn at a time in a single-user session, so at
        most one confirmation is active; the first route is returned defensively.
        """
        for pending_id, key in self._pending_routes.items():
            return pending_id, key
        return None

    def _track_pending(self, key: str, response: AgentResponse) -> None:
        if response.pending is not None:
            self._pending_routes[response.pending.id] = key

    def _classify(self, user_text: str) -> str:
        """Return a registered sub-agent key, or "unclear"."""
        try:
            result = self.client.messages.create(
                model=resolve_router_model(),
                max_tokens=16,
                system=_build_router_prompt(self.registry),
                messages=[{"role": "user", "content": user_text}],
            )
        except anthropic.APIError:
            return "unclear"

        answer = "".join(
            block.text for block in result.content if getattr(block, "type", None) == "text"
        )
        return answer.strip().strip('"').lower()

    def _clarify_text(self) -> str:
        active = ", ".join(spec.display_name for spec in self.registry.values())
        return (
            "I'm not sure which area your request relates to. Right now I can help "
            f"through: {active}. Could you clarify what you'd like to do?"
        )
