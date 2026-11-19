// Settings popup: token, server port, list of groups.
import { parseGroupList } from "../lib/groups.js";

const DEFAULT_SETTINGS = { token: "", port: 8765, groupIds: [] };
const REQUEST_TIMEOUT_MS = 3000;

const $ = (id) => document.getElementById(id);

function showStatus(text, kind = "") {
  const el = $("status");
  el.textContent = text;
  el.className = kind;
}

async function loadSettings() {
  const { settings } = await chrome.storage.local.get("settings");
  return { ...DEFAULT_SETTINGS, ...settings };
}

function readForm() {
  const token = $("token").value.trim();
  const port = Number($("port").value);
  const { groupIds, invalidLines } = parseGroupList($("groups").value);

  const errors = [];
  if (!token) errors.push("Вкажіть токен.");
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    errors.push("Порт має бути числом від 1024 до 65535.");
  }
  if (invalidLines.length) {
    errors.push("Не схоже на посилання на групу:\n" + invalidLines.join("\n"));
  }
  return { settings: { token, port, groupIds }, errors };
}

async function onSave() {
  const { settings, errors } = readForm();
  if (errors.length) return showStatus(errors.join("\n"), "error");
  await chrome.storage.local.set({ settings });
  fillForm(settings); // show the normalized list
  showStatus(`Збережено. Груп: ${settings.groupIds.length}.`, "ok");
}

async function onCheck() {
  const { settings, errors } = readForm();
  if (errors.length) return showStatus(errors.join("\n"), "error");
  const base = `http://127.0.0.1:${settings.port}`;
  showStatus("Перевіряю…");
  try {
    const health = await fetch(`${base}/health`, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
    if (!health.ok) throw new Error(`HTTP ${health.status}`);

    // An empty batch checks the token without sending any data.
    const auth = await fetch(`${base}/api/posts`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Extension-Token": settings.token },
      body: JSON.stringify({ posts: [] }),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (auth.status === 401) return showStatus("Сервер працює, але токен невірний.", "error");
    if (!auth.ok) throw new Error(`HTTP ${auth.status}`);
    showStatus("З'єднання є, токен правильний ✓", "ok");
  } catch (err) {
    showStatus(`Сервер недоступний (${err.message}).\nЗапустіть: python -m lead_monitor.server`, "error");
  }
}

function fillForm(settings) {
  $("token").value = settings.token;
  $("port").value = settings.port;
  $("groups").value = settings.groupIds
    .map((id) => `https://www.facebook.com/groups/${id}/`)
    .join("\n");
}

document.addEventListener("DOMContentLoaded", async () => {
  fillForm(await loadSettings());
  $("save").addEventListener("click", onSave);
  $("check").addEventListener("click", onCheck);
});
