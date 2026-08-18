"""Minimal local web UI for NikitAI, built on the Agent class.

Run with: uvicorn nikitai.web:app --reload

Every route except ``/login``, ``/logout``, and the ``/static`` assets is gated
behind a session cookie; unauthenticated API calls get a 401 and unauthenticated
page requests are redirected to ``/login``. See :mod:`nikitai.web_auth` for the
single-user config.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import web_auth
from .agent import AgentResponse
from .orchestrator import Orchestrator

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="NikitAI")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_orchestrator: Orchestrator | None = None


def _is_public(path: str) -> bool:
    return path in {"/login", "/logout"} or path.startswith("/static")


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if _is_public(path) or web_auth.is_authenticated(request):
        return await call_next(request)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


app.add_middleware(
    SessionMiddleware,
    secret_key=web_auth.secret_key(),
    max_age=web_auth.session_ttl(),
    same_site="lax",
    https_only=web_auth.https_only(),
)


def get_agent() -> Orchestrator:
    """Returns the single in-memory Orchestrator for this local, single-user session."""
    global _orchestrator
    if _orchestrator is None:
        try:
            _orchestrator = Orchestrator()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _orchestrator


class LoginRequest(BaseModel):
    username: str
    password: str


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


@app.get("/login")
def login_page(request: Request):
    if web_auth.is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC_DIR / "login.html")


@app.post("/login")
def login(request: Request, payload: LoginRequest) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    if web_auth.login_blocked(ip):
        raise HTTPException(status_code=429, detail="Too many failed login attempts")
    if not web_auth.is_configured():
        raise HTTPException(status_code=403, detail="Server authentication is not configured")
    if payload.username != web_auth.username() or not web_auth.verify_password(payload.password):
        web_auth.record_failed_login(ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    web_auth.clear_failed_logins(ip)
    request.session["authenticated"] = True
    request.session["username"] = payload.username
    request.session["expires"] = time.time() + web_auth.session_ttl()
    return JSONResponse({"ok": True})


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


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
