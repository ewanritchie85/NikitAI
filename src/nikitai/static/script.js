const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("text-input");
const sendButton = document.getElementById("send-button");

function renderMarkdown(text) {
  // markdown → HTML, then sanitized before touching the DOM (model output is
  // untrusted). Returns null when the parser libs failed to load, so callers can
  // degrade to plain text instead of throwing.
  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
    return null;
  }
  return DOMPurify.sanitize(marked.parse(text));
}

const COPY_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';

function addCopyButtons(container) {
  // Small copy button on each fenced code block. Inserted post-sanitize so the raw
  // button markup never touches DOMPurify; the code's textContent is unaffected.
  container.querySelectorAll("pre > code").forEach((code) => {
    const pre = code.parentElement;
    if (pre.querySelector(".code-copy-btn")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "code-copy-btn";
    btn.setAttribute("aria-label", "Copy code");
    btn.title = "Copy code";
    btn.innerHTML = COPY_ICON;
    pre.appendChild(btn);
  });
}

function copyText(text) {
  // navigator.clipboard needs a secure context (HTTPS or localhost); fall back to
  // the classic execCommand path for plain-HTTP LAN access (e.g. Pi hosting).
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).then(
      () => true,
      () => false
    );
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (err) {
    ok = false;
  }
  document.body.removeChild(ta);
  return Promise.resolve(ok);
}

function flashCopyFeedback(btn, label) {
  clearTimeout(btn._copyTimer);
  btn.classList.add("copied");
  btn.textContent = label;
  btn._copyTimer = setTimeout(() => {
    btn.classList.remove("copied");
    btn.innerHTML = COPY_ICON;
  }, 1500);
}

function appendMessage(text, cssClass) {
  const div = document.createElement("div");
  div.className = "msg " + cssClass;
  if (cssClass === "assistant") {
    const rendered = renderMarkdown(text);
    div.innerHTML = rendered !== null ? rendered : text;
    if (rendered === null) div.textContent = text;
    if (rendered !== null) addCopyButtons(div);
  } else {
    div.textContent = text;
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function showTypingIndicator() {
  hideTypingIndicator();
  const div = document.createElement("div");
  div.id = "typing-indicator";
  div.className = "msg assistant typing-indicator";
  div.innerHTML = "<span></span><span></span><span></span>";
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function hideTypingIndicator() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

function appendPending(pending) {
  const container = document.createElement("div");
  container.className = "pending";

  const title = document.createElement("div");
  title.className = "pending-title";
  title.textContent = "Confirm action: " + pending.tool_name;
  container.appendChild(title);

  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(pending.tool_input, null, 2);
  container.appendChild(pre);

  const buttons = document.createElement("div");
  buttons.className = "pending-buttons";

  const approveBtn = document.createElement("button");
  approveBtn.className = "btn btn-approve";
  approveBtn.textContent = "Approve";
  approveBtn.onclick = () => resolvePending(pending.id, true, container);

  const denyBtn = document.createElement("button");
  denyBtn.className = "btn btn-deny";
  denyBtn.textContent = "Deny";
  denyBtn.onclick = () => resolvePending(pending.id, false, container);

  buttons.appendChild(approveBtn);
  buttons.appendChild(denyBtn);
  container.appendChild(buttons);

  messagesEl.appendChild(container);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderResponse(data) {
  if (data.text) {
    appendMessage(data.text, "assistant");
  }
  if (data.error) {
    appendMessage(data.error, "error");
  }
  if (data.pending) {
    appendPending(data.pending);
  }
}

function createStreamingMessage() {
  // An empty assistant bubble that text deltas are appended into as they arrive.
  const div = document.createElement("div");
  div.className = "msg assistant streaming";
  messagesEl.appendChild(div);
  return div;
}

function updateStreamingMessage(div, text) {
  // Plain-text fill while streaming (fast, no re-parse per delta); markdown is
  // rendered once on the terminal "done" event.
  div.textContent = text;
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function finalizeStreamingMessage(div, text) {
  const rendered = renderMarkdown(text);
  div.innerHTML = rendered !== null ? rendered : text;
  div.classList.remove("streaming");
  if (rendered === null) div.textContent = text;
  if (rendered !== null) addCopyButtons(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function handleStreamEvent(div, event, data) {
  if (event === "text") {
    div.dataset.streamText = (div.dataset.streamText || "") + data.delta;
    updateStreamingMessage(div, div.dataset.streamText);
  } else if (event === "done") {
    const hadStreamed = Boolean(div.dataset.streamText);
    const streamed = div.dataset.streamText || "";
    if (hadStreamed) {
      // Finalize whatever streamed, even if it ends in an error, so no half-filled
      // bubble lingers (the "streaming" marker is removed either way).
      delete div.dataset.streamText;
      finalizeStreamingMessage(div, data.text || streamed);
      if (data.error) {
        appendMessage(data.error, "error");
      }
    } else if (data.text) {
      appendMessage(data.text, "assistant");
    } else if (data.error) {
      appendMessage(data.error, "error");
    }
    if (data.pending) {
      appendPending(data.pending);
    }
    if (!hadStreamed && !data.text && !data.error && !data.pending) {
      div.remove();  // nothing to show — drop the empty streaming bubble
    }
  }
}

async function consumeStream(response, div) {
  // Reads the SSE body incrementally (text/event-stream over fetch) so each
  // text delta renders as it arrives instead of waiting for the full reply.
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (!data) continue;
      let payload;
      try {
        payload = JSON.parse(data);
      } catch (err) {
        continue;
      }
      handleStreamEvent(div, event, payload);
    }
  }
}

async function resolvePending(pendingId, approved, container) {
  container.querySelectorAll("button").forEach((btn) => { btn.disabled = true; });
  container.remove();
  const div = createStreamingMessage();

  try {
    const res = await fetch("/confirm/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pending_id: pendingId, approved: approved }),
    });
    if (!res.ok || !res.body) {
      appendMessage("Something went wrong (" + res.status + "). Check the server logs.", "error");
      return;
    }
    await consumeStream(res, div);
  } catch (err) {
    appendMessage("Something went wrong (" + err + "). Check the server logs.", "error");
  } finally {
    hideTypingIndicator();
  }
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;

  appendMessage(text, "user");
  inputEl.value = "";
  inputEl.disabled = true;
  sendButton.disabled = true;
  showTypingIndicator();
  const div = createStreamingMessage();

  try {
    const res = await fetch("/message/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    });
    if (!res.ok || !res.body) {
      appendMessage("Something went wrong (" + res.status + "). Check the server logs.", "error");
      return;
    }
    await consumeStream(res, div);
  } catch (err) {
    appendMessage("Something went wrong (" + err + "). Check the server logs.", "error");
  } finally {
    hideTypingIndicator();
    inputEl.disabled = false;
    sendButton.disabled = false;
    inputEl.focus();
  }
}

sendButton.addEventListener("click", sendMessage);
inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter") sendMessage();
});

// Event delegation on the chat container: copy buttons work no matter when (or how)
// a code block was inserted, and one listener covers every block in the session.
messagesEl.addEventListener("click", (event) => {
  const btn = event.target.closest(".code-copy-btn");
  if (!btn) return;
  const code = btn.closest("pre")?.querySelector("code");
  if (!code) return;
  copyText(code.textContent).then((ok) => {
    flashCopyFeedback(btn, ok ? "Copied!" : "Failed");
  });
});
