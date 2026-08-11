"""Minimal local web UI for NikitAI, built on the Agent class.

Run with: uvicorn nikitai.web:app --reload
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import AgentResponse
from .orchestrator import Orchestrator

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="NikitAI")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_orchestrator: Orchestrator | None = None


def get_agent() -> Orchestrator:
    """Returns the single in-memory Orchestrator for this local, single-user session."""
    global _orchestrator
    if _orchestrator is None:
        try:
            _orchestrator = Orchestrator()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _orchestrator


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
def post_message(
    payload: MessageRequest, agent: Orchestrator = Depends(get_agent)
) -> dict[str, Any]:
    try:
        return _serialize(agent.send(payload.text))
    except Exception as exc:
        return _serialize(AgentResponse(error=str(exc)))


@app.post("/confirm")
def post_confirm(
    payload: ConfirmRequest, agent: Orchestrator = Depends(get_agent)
) -> dict[str, Any]:
    try:
        return _serialize(agent.confirm(payload.pending_id, payload.approved))
    except Exception as exc:
        return _serialize(AgentResponse(error=str(exc)))
