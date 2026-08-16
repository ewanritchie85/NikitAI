"""Minimal local web UI for NikitAI, built on the Agent class.

Run with: uvicorn nikitai.web:app --reload
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
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


def _sse(payload: dict[str, Any]) -> str:
    """Serialize one streaming event to an SSE frame (event: kind + JSON data)."""
    return f"event: {payload['kind']}\ndata: {json.dumps(payload['data'])}\n\n"


def _stream_response(events) -> StreamingResponse:
    """Wrap a ``(kind, payload)`` event generator as an SSE stream.

    Text deltas stream immediately so the UI can render them as they arrive;
    the final ``done`` event carries the full serialized AgentResponse.
    """

    def generate():
        try:
            for kind, payload in events:
                if kind == "text":
                    yield _sse({"kind": "text", "data": {"delta": payload}})
                elif kind == "done":
                    yield _sse({"kind": "done", "data": _serialize(payload)})
        except Exception as exc:  # noqa: BLE001
            yield _sse({"kind": "done", "data": _serialize(AgentResponse(error=str(exc)))})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/message/stream")
def post_message_stream(
    payload: MessageRequest, agent: Orchestrator = Depends(get_agent)
) -> StreamingResponse:
    return _stream_response(agent.stream_send(payload.text))


@app.post("/confirm")
def post_confirm(
    payload: ConfirmRequest, agent: Orchestrator = Depends(get_agent)
) -> dict[str, Any]:
    try:
        return _serialize(agent.confirm(payload.pending_id, payload.approved))
    except Exception as exc:
        return _serialize(AgentResponse(error=str(exc)))


@app.post("/confirm/stream")
def post_confirm_stream(
    payload: ConfirmRequest, agent: Orchestrator = Depends(get_agent)
) -> StreamingResponse:
    return _stream_response(agent.stream_confirm(payload.pending_id, payload.approved))
