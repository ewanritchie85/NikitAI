"""Unit tests for nikitai.web."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from nikitai import web
from nikitai.agent import AgentResponse, PendingConfirmation


def _client_with_agent(mock_agent) -> TestClient:
    web.app.dependency_overrides[web.get_agent] = lambda: mock_agent
    return TestClient(web.app)


def teardown_function() -> None:
    web.app.dependency_overrides.clear()


def test_index_serves_html():
    client = _client_with_agent(MagicMock())

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "NikitAI" in response.text


def test_index_uses_vendored_markdown_libs():
    client = _client_with_agent(MagicMock())

    response = client.get("/")

    # markdown parser + sanitizer are served locally (offline-safe), not from a CDN.
    assert "/static/vendor/marked.min.js" in response.text
    assert "/static/vendor/purify.min.js" in response.text
    assert "cdn.jsdelivr.net" not in response.text


def test_vendored_markdown_libs_are_served():
    client = _client_with_agent(MagicMock())

    marked = client.get("/static/vendor/marked.min.js")
    purify = client.get("/static/vendor/purify.min.js")

    assert marked.status_code == 200
    assert "marked" in marked.text.lower()
    assert purify.status_code == 200
    assert "dompurify" in purify.text.lower()


def test_script_runs_assistant_markdown_through_parser_and_sanitizer():
    client = _client_with_agent(MagicMock())

    script = client.get("/static/script.js")

    assert script.status_code == 200
    assert "renderMarkdown" in script.text
    assert "DOMPurify.sanitize(marked.parse(text))" in script.text


def test_script_adds_copy_button_to_code_blocks():
    client = _client_with_agent(MagicMock())

    script = client.get("/static/script.js")

    assert script.status_code == 200
    assert "addCopyButtons" in script.text
    assert ".code-copy-btn" in script.text
    assert "navigator.clipboard" in script.text
    # Delegated handler on the chat container so dynamically inserted blocks work too.
    assert 'messagesEl.addEventListener("click"' in script.text


def test_script_consumes_sse_stream_incrementally():
    client = _client_with_agent(MagicMock())

    script = client.get("/static/script.js")

    assert script.status_code == 200
    # The UI reads the /message/stream and /confirm/stream SSE endpoints instead of
    # waiting on a single JSON body, so text renders as it arrives.
    assert 'fetch("/message/stream"' in script.text
    assert 'fetch("/confirm/stream"' in script.text
    assert "getReader()" in script.text
    assert "handleStreamEvent(div, event, payload)" in script.text


def test_message_returns_text_reply():
    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(text="Hi there!")
    client = _client_with_agent(mock_agent)

    response = client.post("/message", json={"text": "hello"})

    mock_agent.send.assert_called_once_with("hello")
    assert response.status_code == 200
    assert response.json() == {"text": "Hi there!", "error": None, "pending": None}


def test_message_returns_pending_confirmation():
    mock_agent = MagicMock()
    pending = PendingConfirmation(
        id="p1",
        tool_name="send_email",
        tool_input={"to": "a@b.com", "subject": "Hi", "body": "Hello"},
    )
    mock_agent.send.return_value = AgentResponse(pending=pending)
    client = _client_with_agent(mock_agent)

    response = client.post("/message", json={"text": "email bob"})

    assert response.json() == {
        "text": None,
        "error": None,
        "pending": {
            "id": "p1",
            "tool_name": "send_email",
            "tool_input": {"to": "a@b.com", "subject": "Hi", "body": "Hello"},
        },
    }


def test_message_returns_error():
    mock_agent = MagicMock()
    mock_agent.send.return_value = AgentResponse(error="Unknown confirmation id: 'x'")
    client = _client_with_agent(mock_agent)

    response = client.post("/message", json={"text": "hello"})

    assert response.json() == {
        "text": None,
        "error": "Unknown confirmation id: 'x'",
        "pending": None,
    }


def test_confirm_approved_calls_agent_and_returns_text():
    mock_agent = MagicMock()
    mock_agent.confirm.return_value = AgentResponse(text="Sent it!")
    client = _client_with_agent(mock_agent)

    response = client.post("/confirm", json={"pending_id": "p1", "approved": True})

    mock_agent.confirm.assert_called_once_with("p1", True)
    assert response.json() == {"text": "Sent it!", "error": None, "pending": None}


def test_confirm_declined_calls_agent_with_false():
    mock_agent = MagicMock()
    mock_agent.confirm.return_value = AgentResponse(text="Okay, not sending.")
    client = _client_with_agent(mock_agent)

    response = client.post("/confirm", json={"pending_id": "p1", "approved": False})

    mock_agent.confirm.assert_called_once_with("p1", False)
    assert response.json()["text"] == "Okay, not sending."


def test_get_agent_lazily_creates_and_caches_orchestrator(monkeypatch):
    monkeypatch.setattr(web, "_orchestrator", None)
    mock_orchestrator_cls = MagicMock()
    monkeypatch.setattr(web, "Orchestrator", mock_orchestrator_cls)

    first = web.get_agent()
    second = web.get_agent()

    mock_orchestrator_cls.assert_called_once_with()
    assert first is second


# ── streaming endpoints (SSE) ────────────────────────────────────────────────


def test_message_stream_returns_sse_text_events_in_order():
    mock_agent = MagicMock()
    mock_agent.stream_send.return_value = iter(
        [
            ("text", "Hel"),
            ("text", "lo!"),
            ("done", AgentResponse(text="Hello!")),
        ]
    )
    client = _client_with_agent(mock_agent)

    response = client.post("/message/stream", json={"text": "hello"})

    mock_agent.stream_send.assert_called_once_with("hello")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert 'event: text\ndata: {"delta": "Hel"}' in body
    assert 'event: text\ndata: {"delta": "lo!"}' in body
    assert "event: done" in body
    assert '"text": "Hello!"' in body


def test_message_stream_done_carries_pending_and_error_shape():
    mock_agent = MagicMock()
    pending = PendingConfirmation(id="p1", tool_name="send_email", tool_input={"to": "a@b.com"})
    mock_agent.stream_send.return_value = iter(
        [("done", AgentResponse(text="ok", pending=pending))]
    )
    client = _client_with_agent(mock_agent)

    response = client.post("/message/stream", json={"text": "email bob"})

    body = response.text
    assert "event: done" in body
    assert '"pending"' in body
    assert '"tool_name": "send_email"' in body
    assert '"id": "p1"' in body


def test_message_stream_generator_error_emits_done_error_event():
    mock_agent = MagicMock()
    mock_agent.stream_send.return_value = iter(
        [("text", "partial"), ("done", AgentResponse(error="boom"))]
    )
    client = _client_with_agent(mock_agent)

    response = client.post("/message/stream", json={"text": "hello"})

    assert '"error": "boom"' in response.text


def test_confirm_stream_forwards_events():
    mock_agent = MagicMock()
    mock_agent.stream_confirm.return_value = iter(
        [("text", "Sen"), ("text", "t!"), ("done", AgentResponse(text="Sent!"))]
    )
    client = _client_with_agent(mock_agent)

    response = client.post("/confirm/stream", json={"pending_id": "p1", "approved": True})

    mock_agent.stream_confirm.assert_called_once_with("p1", True)
    assert 'event: text\ndata: {"delta": "Sen"}' in response.text
    assert '"text": "Sent!"' in response.text
