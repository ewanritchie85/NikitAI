"""Top-level NikitAI orchestrator that routes messages to domain sub-agents.

"NikitAI" is the orchestrator; each domain is handled by a sub-agent backed by
the generalized :class:`~nikitai.agent.Agent`. Sub-agent configurations live under
:mod:`nikitai.subagents` (Organiser = Outlook, Platform Nerd = home infra). The
Trainer (Garmin) sub-agent has a reserved registry slot but is not yet implemented.

Flow:
- ``send()`` runs a cheap classification call to pick a registered sub-agent, then
  dispatches the message to that sub-agent's ``Agent.send()``. If the classifier is
  unsure, it asks the user to clarify rather than guessing.
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
from .subagents.organiser import outlook_agent_config
from .subagents.platform_nerd import platform_nerd_agent_config

# Last-resort router model if neither NIKITAI_ROUTER_MODEL nor NIKITAI_DEFAULT_MODEL
# is set. A cheap/fast model is preferred here since routing is a tiny classification.
# Routing/classification is an orchestrator-level concern, not core Agent infra, so
# this lives here rather than in agent.py.
DEFAULT_ROUTER_MODEL = "claude-haiku-4-5"


def resolve_router_model() -> str:
    """Resolve the orchestrator's routing model.

    Order: ``NIKITAI_ROUTER_MODEL`` → ``NIKITAI_DEFAULT_MODEL`` →
    :data:`DEFAULT_ROUTER_MODEL`. Resolved per call so tests and runtime env changes
    are honored without needing to reimport the module.
    """
    return (
        os.environ.get("NIKITAI_ROUTER_MODEL")
        or os.environ.get("NIKITAI_DEFAULT_MODEL")
        or DEFAULT_ROUTER_MODEL
    )


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
# Only fully-implemented sub-agents belong here. Reserved future slots are shown
# as commented placeholders so it's obvious where they plug in — do NOT add them
# to the live registry until their config factories (prompt + tools + dispatcher)
# actually exist.
#
# Future, not yet implemented. Its config_factory will resolve its model via
# agent.resolve_model("NIKITAI_TRAINER_MODEL"), which falls back to
# NIKITAI_DEFAULT_MODEL — matching outlook_agent_config().
#   "trainer": SubAgentSpec(
#       key="trainer",
#       display_name="NikitAI Trainer",
#       description="Garmin health/fitness data and coaching.",
#       config_factory=trainer_agent_config,  # TODO: not built yet
#   ),
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

    # ── Public API ───────────────────────────────────────────────────────────

    def send(self, user_text: str) -> AgentResponse:
        key = self._classify(user_text)
        if key not in self.registry:
            return AgentResponse(text=self._clarify_text())

        agent = self._get_agent(key)
        response = agent.send(user_text)
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

    # ── Internals ────────────────────────────────────────────────────────────

    def _get_agent(self, key: str) -> Agent:
        agent = self._agents.get(key)
        if agent is None:
            agent = Agent(**self.registry[key].config_factory())
            self._agents[key] = agent
        return agent

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
