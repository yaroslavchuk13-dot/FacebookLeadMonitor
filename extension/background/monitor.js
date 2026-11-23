// Monitor loop: visits one group per tick, sends new posts, then schedules the next tick.
// Stops completely on a checkpoint / login page — no attempts to bypass it.
import { groupFeedUrl } from "../lib/groups.js";
import { addToOutbox, nextGroupIndex, randomPauseSec } from "../lib/scheduler.js";
import {
  loadMonitor,
  loadOutbox,
  loadSettings,
  saveOutbox,
  updateMonitor,
} from "../lib/storage.js";
import { getControl, sendAlert, sendPosts, sendProfileResult } from "./server_api.js";

export const ALARM_NAME = "monitor-tick";
// Restarts the loop if Chrome dropped the tick alarm (extension reload, service worker restart).
export const WATCHDOG_ALARM = "monitor-watchdog";
const WATCHDOG_PERIOD_MIN = 1;

const CONTENT_SCRIPTS = ["content/post_links.js", "content/page_state.js", "content/feed_parser.js"];
const PROFILE_SCRIPTS = ["content/page_state.js", "content/profile_parser.js"];
// Waits inside one visit (tests set them to 0).
export const timing = {
  pageLoadTimeoutMs: 45000,
  renderWaitMinMs: 4000, // let Facebook render the feed after "load"
  renderWaitMaxMs: 7000,
  emptyFeedRetryMs: 5000,
};
const STOP_STATES = new Set(["checkpoint", "login_required"]);

const STOP_MESSAGES = {
  checkpoint: "Facebook показав перевірку безпеки (checkpoint). Моніторинг зупинено — пройдіть перевірку вручну.",
  login_required: "Facebook просить увійти в акаунт. Моніторинг зупинено — увійдіть і запустіть знову.",
};

let busy = false; // one tick at a time inside this service worker

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const randomBetween = (min, max) => min + Math.floor(Math.random() * (max - min + 1));

// --- public API ------------------------------------------------------------------

export async function startMonitor() {
  const settings = await loadSettings();
  if (!settings.token) return { ok: false, error: "Спершу вкажіть і збережіть токен." };
  if (!settings.groupIds.length) return { ok: false, error: "Спершу додайте і збережіть групи." };

  await updateMonitor({ running: true, alert: null, groupFailures: {}, currentVisit: null });
  await setBadge("ON", "#1a7f37");
  await chrome.alarms.create(WATCHDOG_ALARM, { periodInMinutes: WATCHDOG_PERIOD_MIN });
  await sendAlert(settings, {
    kind: "started",
    message: `Моніторинг запущено (груп: ${settings.groupIds.length}).`,
  });
  runTick(); // first visit right away, do not wait for it
  return { ok: true };
}

/** "Stop" button: stop and tell the server (so it does not report the silence as a problem). */
export async function stopByUser() {
  await stopMonitor();
  await sendAlert(await loadSettings(), {
    kind: "stopped",
    message: "Моніторинг зупинено вручну (кнопка «Стоп» у розширенні).",
    stopped: true,
  });
}

export async function stopMonitor(alert = null) {
  await chrome.alarms.clear(ALARM_NAME);
  await chrome.alarms.clear(WATCHDOG_ALARM);
  await updateMonitor({
    running: false,
    nextRunAt: null,
    currentVisit: null,
    ...(alert ? { alert } : {}),
  });
  await setBadge(alert ? "!" : "", "#c62828");
}

/**
 * Runs every minute while monitoring. If no visit is in progress and no next visit
 * is scheduled, the loop was lost (service worker restart) — start the next visit now.
 */
export async function watchdog() {
  const monitor = await loadMonitor();
  if (!monitor.running || busy) return;
  if (await chrome.alarms.get(ALARM_NAME)) return;
  console.warn("Monitor loop was lost — restarting it");
  runTick();
}

/** Entry point for the alarm and for "start". Never throws. */
export async function runTick() {
  if (busy) return;
  busy = true;
  try {
    await tick();
  } catch (err) {
    console.error("Monitor tick failed", err);
    await updateMonitor({ currentVisit: null });
    await scheduleNext(); // keep going after unexpected errors
  } finally {
    busy = false;
  }
}

/**
 * Called whenever the service worker starts (browser start, extension reload/update):
 * if monitoring was running, make sure the watchdog is there — it resumes the loop.
 */
export async function resumeIfRunning() {
  const monitor = await loadMonitor();
  if (!monitor.running) return;
  await setBadge("ON", "#1a7f37");
  if (!(await chrome.alarms.get(WATCHDOG_ALARM))) {
    await chrome.alarms.create(WATCHDOG_ALARM, { periodInMinutes: WATCHDOG_PERIOD_MIN });
  }
}

// --- one tick ------------------------------------------------------------------------

async function tick() {
  let monitor = await loadMonitor();
  if (!monitor.running) return;
  const settings = await loadSettings();
  if (!settings.groupIds.length) {
    await stopMonitor({ kind: "error", message: "Список груп порожній.", at: Date.now() });
    return;
  }

  const control = await getControl(settings);
  if (control.paused) {
    // /pause in Telegram: do not open Facebook, just check again later.
    await updateMonitor({ lastRun: { groupId: null, at: Date.now(), status: "paused", found: 0, sent: 0 } });
    await scheduleNext();
    return;
  }
  if (control.profileCheck) {
    // A new lead waits for the author scam check: this cycle opens the profile instead of a group.
    await checkProfile(settings, monitor, control.profileCheck);
    return;
  }

  const index = nextGroupIndex(settings.groupIds.length, monitor.lastIndex);
  const groupId = settings.groupIds[index];
  await updateMonitor({ currentVisit: { groupId, startedAt: Date.now() }, nextRunAt: null });
  const visit = await visitGroup(groupId, monitor.tabId);

  monitor = await loadMonitor();
  if (!monitor.running) return; // stopped by the user while we were visiting

  if (STOP_STATES.has(visit.status)) {
    const alert = { kind: visit.status, message: STOP_MESSAGES[visit.status], at: Date.now() };
    await updateMonitor({
      tabId: visit.tabId,
      lastIndex: index,
      currentVisit: null,
      lastRun: runInfo(groupId, visit),
    });
    await sendAlert(settings, { kind: alert.kind, message: alert.message, group_id: groupId, stopped: true });
    await stopMonitor(alert);
    return;
  }

  const failures = { ...monitor.groupFailures };
  if (visit.status === "ok") {
    delete failures[groupId];
  } else {
    failures[groupId] = (failures[groupId] ?? 0) + 1;
    if (failures[groupId] === 1) {
      // Alert only on the first failure in a row, not on every cycle.
      const message = visit.status === "no_feed"
        ? `Не вдалося знайти стрічку групи ${groupId} (немає доступу або змінилася сторінка).`
        : `Помилка під час перевірки групи ${groupId}: ${visit.error ?? visit.status}`;
      await sendAlert(settings, { kind: visit.status === "no_feed" ? "no_feed" : "error", message, group_id: groupId });
    }
  }

  const delivery = await deliver(settings, visit.posts ?? []);
  await updateMonitor({
    tabId: visit.tabId,
    lastIndex: index,
    groupFailures: failures,
    currentVisit: null,
    postsSent: monitor.postsSent + delivery.sent,
    lastRun: runInfo(groupId, visit, delivery),
  });
  await scheduleNext();
}

/** Opens the author's profile, sends numbers/flags to the server (scam check). */
async function checkProfile(settings, monitor, check) {
  await updateMonitor({ currentVisit: { groupId: "профіль автора", startedAt: Date.now() }, nextRunAt: null });
  const visit = await visitProfile(check.profile_url, monitor.tabId);

  if (!(await loadMonitor()).running) return; // stopped by the user meanwhile
  const lastRun = {
    groupId: null,
    groupName: "Перевірка автора",
    at: Date.now(),
    status: visit.status,
    found: 0,
    sent: 0,
    error: visit.error ?? null,
  };
  if (STOP_STATES.has(visit.status)) {
    const alert = { kind: visit.status, message: STOP_MESSAGES[visit.status], at: Date.now() };
    await updateMonitor({ tabId: visit.tabId, currentVisit: null, lastRun });
    await sendAlert(settings, { kind: alert.kind, message: alert.message, stopped: true });
    await stopMonitor(alert);
    return;
  }
  const profile = visit.status === "ok" ? visit.profile : { status: "error" };
  await sendProfileResult(settings, check.id, profile);
  await updateMonitor({ tabId: visit.tabId, currentVisit: null, lastRun });
  await scheduleNext();
}

function runInfo(groupId, visit, delivery = { sent: 0, error: null }) {
  return {
    groupId,
    groupName: visit.groupName ?? null,
    at: Date.now(),
    status: visit.status,
    found: visit.posts?.length ?? 0,
    sent: delivery.sent,
    error: visit.error ?? delivery.error,
  };
}

/** Puts posts into the outbox and tries to send the whole outbox. */
async function deliver(settings, posts) {
  const outbox = addToOutbox(await loadOutbox(), posts);
  if (!outbox.length) return { sent: 0, error: null };
  try {
    await sendPosts(settings, outbox);
    await saveOutbox([]);
    return { sent: outbox.length, error: null };
  } catch (err) {
    await saveOutbox(outbox); // retry on the next tick
    return { sent: 0, error: `Сервер недоступний: ${err.message}. У черзі: ${outbox.length}` };
  }
}

async function scheduleNext() {
  const monitor = await loadMonitor();
  if (!monitor.running) return;
  const pauseSec = randomPauseSec();
  await chrome.alarms.create(ALARM_NAME, { delayInMinutes: pauseSec / 60 });
  await updateMonitor({ nextRunAt: Date.now() + pauseSec * 1000 });
}

// --- visiting a group --------------------------------------------------------------

/** Opens the group in the monitor tab and parses it. Returns { status, tabId, posts?, error? }. */
async function visitGroup(groupId, tabId) {
  let tab;
  try {
    tab = await ensureTab(tabId);
    await navigateAndWait(tab.id, groupFeedUrl(groupId));
    await sleep(randomBetween(timing.renderWaitMinMs, timing.renderWaitMaxMs));

    let result = await parseTab(tab.id);
    if (result.status === "ok" && result.posts.length === 0) {
      await sleep(timing.emptyFeedRetryMs); // feed may still be loading
      result = await parseTab(tab.id);
    }
    return { ...result, tabId: tab.id };
  } catch (err) {
    return { status: "error", error: err.message, tabId: tab?.id ?? null };
  }
}

/** Opens a profile in the monitor tab. Returns { status, tabId, profile?, error? }. */
async function visitProfile(profileUrl, tabId) {
  let tab;
  try {
    tab = await ensureTab(tabId);
    await navigateAndWait(tab.id, profileUrl);
    await sleep(randomBetween(timing.renderWaitMinMs, timing.renderWaitMaxMs));
    const target = { tabId: tab.id };
    await chrome.scripting.executeScript({ target, files: PROFILE_SCRIPTS });
    const [{ result }] = await chrome.scripting.executeScript({
      target,
      func: () => {
        const state = globalThis.FLM.pageState();
        if (state !== "ok") return { status: state };
        return { status: "ok", profile: globalThis.FLM.parseProfile() };
      },
    });
    return { ...result, tabId: tab.id };
  } catch (err) {
    return { status: "error", error: err.message, tabId: tab?.id ?? null };
  }
}

/** Reuses the monitor tab if it still exists, otherwise opens a new pinned background tab. */
async function ensureTab(tabId) {
  if (tabId !== null) {
    try {
      return await chrome.tabs.get(tabId);
    } catch {
      // the user closed it — open a new one
    }
  }
  return chrome.tabs.create({ url: "about:blank", active: false, pinned: true });
}

function navigateAndWait(tabId, url) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error(`сторінка не завантажилась за ${timing.pageLoadTimeoutMs / 1000} с`));
    }, timing.pageLoadTimeoutMs);

    function listener(updatedId, changeInfo, tab) {
      if (updatedId !== tabId || changeInfo.status !== "complete") return;
      if (!tab.url || tab.url === "about:blank") return;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }

    chrome.tabs.onUpdated.addListener(listener); // before navigating, to not miss "complete"
    chrome.tabs.update(tabId, { url }).catch((err) => {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      reject(err);
    });
  });
}

async function parseTab(tabId) {
  const target = { tabId };
  await chrome.scripting.executeScript({ target, files: CONTENT_SCRIPTS });
  const [{ result }] = await chrome.scripting.executeScript({
    target,
    func: async () => {
      const state = globalThis.FLM.pageState();
      if (state !== "ok") return { status: state, posts: [] };
      return globalThis.FLM.parseFeed();
    },
  });
  return result;
}

async function setBadge(text, color) {
  await chrome.action.setBadgeText({ text });
  if (text) await chrome.action.setBadgeBackgroundColor({ color });
}
