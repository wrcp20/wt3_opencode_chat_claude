const resetBtn = document.querySelector("#resetBtn");
const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const sendBtn = document.querySelector("#sendBtn");
const messagesEl = document.querySelector("#messages");
const emptyState = document.querySelector("#emptyState");
const statusBadge = document.querySelector("#statusBadge");
const queueBadge = document.querySelector("#queueBadge");
const modelSelect = document.querySelector("#modelSelect");

function authHeaders() {
  const token = window.localStorage.getItem("claude_api_token") || "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}

let history = [];
let isStreaming = false;

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderMarkdown(text) {
  return escapeHtml(text)
    .replace(/```([\s\S]*?)```/g, (_, code) => `<pre><code>${code.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>")
    .replace(/^[-*] (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>")
    .split("\n\n")
    .map((block) => {
      const trimmed = block.trim();
      if (!trimmed) return "";
      if (/^<(h[1-3]|ul|pre|blockquote)/.test(trimmed)) return trimmed;
      return `<p>${trimmed.replaceAll("\n", "<br>")}</p>`;
    })
    .join("");
}

function addMessage(role, content, streaming = false) {
  if (emptyState) {
    emptyState.remove();
  }

  const item = document.createElement("article");
  item.className = `message ${role}`;

  const badge = document.createElement("span");
  badge.className = "message-role";
  badge.textContent = role === "assistant" ? "Claude" : "Tu";

  const body = document.createElement("div");
  body.className = "message-content";
  body.innerHTML = streaming ? '<div class="typing">...</div>' : role === "assistant" ? renderMarkdown(content) : `<p>${escapeHtml(content)}</p>`;

  item.append(badge, body);
  messagesEl.appendChild(item);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return body;
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    if (response.status === 401) {
      statusBadge.textContent = "backend requiere token";
      statusBadge.classList.remove("ok");
      queueBadge.textContent = "queue: ?";
      return;
    }
    const payload = await response.json();
    statusBadge.textContent = payload.ready ? `${payload.model} listo` : payload.warming ? `${payload.model} calentando` : `${payload.model} offline`;
    statusBadge.classList.toggle("ok", Boolean(payload.ready));
    queueBadge.textContent = `queue: ${payload.queue}`;

    if (!modelSelect.options.length) {
      for (const model of payload.allowed_models || []) {
        const option = document.createElement("option");
        option.value = model;
        option.textContent = model;
        option.selected = model === payload.model;
        modelSelect.appendChild(option);
      }
    } else {
      modelSelect.value = payload.model;
    }
  } catch {
    statusBadge.textContent = "servidor offline";
    statusBadge.classList.remove("ok");
  }
}

async function resetConversation(model = modelSelect.value || undefined) {
  history = [];
  messagesEl.innerHTML = '<div id="emptyState" class="empty-state">Nueva conversacion lista.</div>';
  await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(model ? { model } : {}),
  });
  await refreshStatus();
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message || isStreaming) {
    return;
  }

  history.push({ role: "user", content: message });
  addMessage("user", message);
  const assistantBubble = addMessage("assistant", "", true);
  messageInput.value = "";
  isStreaming = true;
  sendBtn.disabled = true;
  let assistantText = "";

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ messages: history, model: modelSelect.value }),
    });

    if (!response.ok || !response.body) {
      const error = await response.json().catch(() => ({ detail: "request failed" }));
      assistantBubble.textContent = error.detail || "request failed";
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) {
          continue;
        }
        const data = line.slice(6).trim();
        if (data === "[DONE]") {
          continue;
        }
        const eventPayload = JSON.parse(data);
        if (eventPayload.type === "text") {
          assistantText += eventPayload.text;
          assistantBubble.innerHTML = renderMarkdown(assistantText);
        }
        if (eventPayload.type === "error") {
          assistantBubble.textContent = eventPayload.error;
        }
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    }

    if (assistantText) {
      history.push({ role: "assistant", content: assistantText });
    }
  } catch (error) {
    assistantBubble.textContent = error instanceof Error ? error.message : "request failed";
  } finally {
    isStreaming = false;
    sendBtn.disabled = false;
    await refreshStatus();
    messageInput.focus();
  }
});

resetBtn.addEventListener("click", async () => {
  await resetConversation();
  messageInput.focus();
});

modelSelect.addEventListener("change", async () => {
  await resetConversation(modelSelect.value);
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

refreshStatus();
window.setInterval(refreshStatus, 5000);
