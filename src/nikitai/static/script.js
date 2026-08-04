const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("text-input");
const sendButton = document.getElementById("send-button");

function appendMessage(text, cssClass) {
  const div = document.createElement("div");
  div.className = "msg " + cssClass;
  if (cssClass === "assistant") {
    div.innerHTML = DOMPurify.sanitize(marked.parse(text));
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

async function resolvePending(pendingId, approved, container) {
  container.querySelectorAll("button").forEach((btn) => { btn.disabled = true; });
  container.remove();
  showTypingIndicator();

  try {
    const res = await fetch("/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pending_id: pendingId, approved: approved }),
    });
    if (!res.ok) {
      appendMessage("Something went wrong (" + res.status + "). Check the server logs.", "error");
      return;
    }
    const data = await res.json();
    renderResponse(data);
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

  try {
    const res = await fetch("/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    });
    if (!res.ok) {
      appendMessage("Something went wrong (" + res.status + "). Check the server logs.", "error");
      return;
    }
    const data = await res.json();
    renderResponse(data);
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
