// Popup: monitor control and status, settings, parsing test.
import { parseGroupId, parseGroupList } from "../lib/groups.js";
import { loadMonitor, loadOutbox, loadSettings, saveSettings } from "../lib/storage.js";

const TEST_SCRIPTS = ["content/post_links.js", "content/feed_parser.js"];
const PREVIEW_POSTS = 5;
const PREVIEW_TEXT_LENGTH = 120;
const REQUEST_TIMEOUT_MS = 3000;

const STATUS_TEXT = {
  ok: "ok",
  no_feed: "стрічку не знайдено",
  not_group: "це не сторінка групи",
  checkpoint: "checkpoint",
  login_required: "потрібен вхід",
  error: "помилка",
};

const SKIP_REASONS = {
  no_link_no_text: "немає ні посилання, ні тексту (реклама / заглушка?)",
  no_link: "не знайдено посилання на допис",
  no_text: "немає тексту (лише фото / відео?)",
  duplicate: "повтор",
};

const $ = (id) => document.getElementById(id);

function showMessage(id, text, kind = "") {
  const el = $(id);
  el.textContent = text;
  el.className = `message ${kind}`;
}

const formatTime = (ms) => new Date(ms).toLocaleTimeString("uk-UA");

// --- monitor ---------------------------------------------------------------------------

let currentMonitor = null;
let outboxSize = 0;

function renderMonitor() {
  const m = currentMonitor;
  if (!m) return;
  const state = $("monitor-state");
  state.textContent = m.running ? "● Працює" : "○ Зупинено";
  state.className = `state ${m.running ? "running" : "stopped"}`;
  $("start").disabled = m.running;
  $("stop").disabled = !m.running;

  const lines = [];
  if (m.lastRun) {
    const r = m.lastRun;
    lines.push(`Остання група: ${r.groupId} о ${formatTime(r.at)}`);
    lines.push(`Результат: ${STATUS_TEXT[r.status] ?? r.status}, знайдено ${r.found}, надіслано ${r.sent}`);
    if (r.error) lines.push(`⚠ ${r.error}`);
  }
  if (m.running && m.nextRunAt) {
    const sec = Math.max(0, Math.round((m.nextRunAt - Date.now()) / 1000));
    lines.push(sec > 0 ? `Наступна перевірка через ${sec} с` : "Перевіряю групу…");
  }
  lines.push(`Усього надіслано: ${m.postsSent}`);
  if (outboxSize) lines.push(`Чекають відправки (сервер недоступний): ${outboxSize}`);
  $("monitor-details").textContent = lines.join("\n");

  $("monitor-alert").textContent = m.alert
    ? `⛔ ${m.alert.message}\n(${formatTime(m.alert.at)})`
    : "";
}

async function refreshMonitor() {
  currentMonitor = await loadMonitor();
  outboxSize = (await loadOutbox()).length;
  renderMonitor();
}

async function sendCommand(type) {
  showMessage("monitor-message", "");
  const response = await chrome.runtime.sendMessage({ type });
  if (!response?.ok) showMessage("monitor-message", response?.error ?? "Невідома помилка", "error");
}

// --- settings --------------------------------------------------------------------------

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

function fillForm(settings) {
  $("token").value = settings.token;
  $("port").value = settings.port;
  $("groups").value = settings.groupIds.map((id) => `https://www.facebook.com/groups/${id}/`).join("\n");
}

async function onSave() {
  const { settings, errors } = readForm();
  if (errors.length) return showMessage("status", errors.join("\n"), "error");
  await saveSettings(settings);
  fillForm(settings); // show the normalized list
  showMessage("status", `Збережено. Груп: ${settings.groupIds.length}.`, "ok");
}

async function onCheck() {
  const { settings, errors } = readForm();
  if (errors.length) return showMessage("status", errors.join("\n"), "error");
  const base = `http://127.0.0.1:${settings.port}`;
  showMessage("status", "Перевіряю…");
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
    if (auth.status === 401) return showMessage("status", "Сервер працює, але токен невірний.", "error");
    if (!auth.ok) throw new Error(`HTTP ${auth.status}`);
    showMessage("status", "З'єднання є, токен правильний ✓", "ok");
  } catch (err) {
    showMessage("status", `Сервер недоступний (${err.message}).\nЗапустіть: python -m lead_monitor.server`, "error");
  }
}

// --- parsing test ----------------------------------------------------------------------

async function onParseTab() {
  const preview = $("preview");
  preview.textContent = "";
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || parseGroupId(tab.url) === null) {
    return showMessage("status", "Відкрийте сторінку Facebook-групи в поточній вкладці.", "error");
  }
  preview.textContent = "Розбираю сторінку…";
  try {
    const target = { tabId: tab.id };
    await chrome.scripting.executeScript({ target, files: TEST_SCRIPTS });
    const [{ result }] = await chrome.scripting.executeScript({
      target,
      func: () => globalThis.FLM.parseFeed(),
    });
    if (result.status !== "ok") {
      preview.textContent = `Стрічку не знайдено (${result.status}). Прокрутіть сторінку і спробуйте ще.`;
      return;
    }
    const header = `Група: ${result.groupName ?? result.groupId}\nДописів: ${result.posts.length}, пропущено: ${result.skipped}`;
    const posts = result.posts.slice(0, PREVIEW_POSTS).map((p) => {
      const author = p.author_name ?? "(анонімно)";
      const profile = p.author_profile_url ? "" : " [без профілю]";
      const text = p.text.replace(/\s+/g, " ").slice(0, PREVIEW_TEXT_LENGTH);
      return `👤 ${author}${profile}\n${text}\n🔗 ${p.post_url}`;
    });
    const skipped = (result.skippedDetails ?? []).map((s, i) => {
      const links = s.links.length ? `\n   посилання: ${s.links.join("  ")}` : "";
      return `${i + 1}. ${SKIP_REASONS[s.reason] ?? s.reason}\n   «${s.preview || "порожній блок"}»${links}`;
    });
    const skippedBlock = skipped.length ? [`── Пропущено (${skipped.length}) ──`, ...skipped] : [];
    preview.textContent = [header, ...posts, ...skippedBlock].join("\n\n");
  } catch (err) {
    preview.textContent = `Помилка розбору: ${err.message}`;
  }
}

// --- init ------------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  const settings = await loadSettings();
  fillForm(settings);
  // Open settings automatically until the extension is configured.
  $("settings-section").open = !settings.token || !settings.groupIds.length;

  $("start").addEventListener("click", () => sendCommand("monitor:start"));
  $("stop").addEventListener("click", () => sendCommand("monitor:stop"));
  $("save").addEventListener("click", onSave);
  $("check").addEventListener("click", onCheck);
  $("parse-tab").addEventListener("click", onParseTab);

  await refreshMonitor();
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && (changes.monitor || changes.outbox)) refreshMonitor();
  });
  setInterval(renderMonitor, 1000); // countdown to the next visit
});
