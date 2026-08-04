"""Minimal local web UI for NikitAI, built on the Agent class.

Run with: uvicorn nikitai.web:app --reload
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .agent import Agent, AgentResponse

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="NikitAI")

_agent: Agent | None = None


def get_agent() -> Agent:
    """Returns the single in-memory Agent for this local, single-user session."""
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent


class MessageRequest(BaseModel):
    text: str


class ConfirmRequest(BaseModel):
    pending_id: str
    approved: bool


def _serialize(response: AgentResponse) -> dict[str, Any]:
    return {
        "text": response.text,
        "error": response.error,
        "pending": (
            {
                "id": response.pending.id,
                "tool_name": response.pending.tool_name,
                "tool_input": response.pending.tool_input,
            }
            if response.pending is not None
            else None
        ),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/message")
def post_message(payload: MessageRequest, agent: Agent = Depends(get_agent)) -> dict[str, Any]:
    return _serialize(agent.send(payload.text))


@app.post("/confirm")
def post_confirm(payload: ConfirmRequest, agent: Agent = Depends(get_agent)) -> dict[str, Any]:
    return _serialize(agent.confirm(payload.pending_id, payload.approved))
