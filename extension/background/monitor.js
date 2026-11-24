// Monitor loop: continuous round of the groups (each checked at least every 2.5 min) -> server.
// Stops completely on a checkpoint / login page — no attempts to bypass it.
import { groupFeedUrl } from "../lib/groups.js";
import {
  addToOutbox,
  BACKUP_VISIT_MS,
  GROUP_TARGET_MS,
  DEEP_SCROLL_STEPS,
  needsDeepScan,
  NORMAL_SCROLL_STEPS,
  NOTIFICATIONS_INTERVAL_MS,
  pickBackupGroup,
  queueFromNotifications,
  SEEN_NOTIFICATIONS_LIMIT,
} from "../lib/scheduler.js";
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
const NOTIFICATIONS_SCRIPTS = ["content/page_state.js", "content/notifications_parser.js"];
const NOTIFICATIONS_URL = "https://www.facebook.com/notifications";
// Waits inside one visit (tests set them to 0).
export const timing = {
  pageLoadTimeoutMs: 45000,
  renderWaitMinMs: 2000, // let Facebook render the feed after "load"
  renderWaitMaxMs: 3500,
  emptyFeedRetryMs: 3000,
  // Continuous loop: a short pause between visits; every group is checked at least this often.
  stepGapMinMs: 2000,
  stepGapMaxMs: 4000,
  groupTargetMs: GROUP_TARGET_MS,
  pausedPollMs: 30000, // /pause in Telegram: check the pause flag this often
  errorPauseMs: 10000,
  singleStep: false, // tests: one step per runTick()
  notificationsIntervalMs: NOTIFICATIONS_INTERVAL_MS,
  backupVisitMs: BACKUP_VISIT_MS,
  failedRetryMs: 10 * 60 * 1000,
  maxQueuePerTick: 3, // groups with new posts visited in one step (keeps the step short)
  queueGapMinMs: 3000, // short pause between those visits
  queueGapMaxMs: 6000,
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
 * Runs every minute while monitoring. If the loop is not running in this service worker
 * (it was restarted), start it again.
 */
export async function watchdog() {
  const monitor = await loadMonitor();
  if (!monitor.running || busy) return;
  console.warn("Monitor loop was lost — restarting it");
  runTick();
}

/**
 * Entry point for the alarm, the watchdog and "start". Runs the continuous loop: one step,
 * a pause of a few seconds, the next step... until monitoring stops. Never throws.
 */
export async function runTick() {
  if (busy) return;
  busy = true;
  try {
    while ((await loadMonitor()).running) {
      // Safety net: if this worker dies mid-loop, the alarm starts the loop again in a minute.
      await chrome.alarms.create(ALARM_NAME, { delayInMinutes: 1 });
      let pauseMs;
      try {
        pauseMs = await tick();
      } catch (err) {
        console.error("Monitor step failed", err);
        await updateMonitor({ currentVisit: null });
        pauseMs = timing.errorPauseMs;
      }
      if (!(await loadMonitor()).running) break;
      const gap = pauseMs ?? randomBetween(timing.stepGapMinMs, timing.stepGapMaxMs);
      await updateMonitor({ nextRunAt: Date.now() + gap });
      if (timing.singleStep) break;
      await sleep(gap);
    }
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

/**
 * One step of the continuous loop. Priorities:
 *   1. a group not checked for GROUP_TARGET_MS (2.5 min) — the oldest first (never visited first)
 *   2. author profile for the scam check (only when all groups are fresh)
 *   3. otherwise the group checked longest ago — the loop never idles
 * Facebook notifications are used only if enabled (NOTIFICATIONS_INTERVAL_MS), off by default.
 * Returns the pause before the next step in ms, or undefined for the normal short pause.
 */
async function tick() {
  const monitor = await loadMonitor();
  if (!monitor.running) return undefined;
  const settings = await loadSettings();
  if (!settings.groupIds.length) {
    await stopMonitor({ kind: "error", message: "Список груп порожній.", at: Date.now() });
    return undefined;
  }

  const control = await getControl(settings);
  if (control.paused) {
    // /pause in Telegram: do not open Facebook, just check again later.
    await updateMonitor({ lastRun: { groupId: null, at: Date.now(), status: "paused", found: 0, sent: 0 } });
    return timing.pausedPollMs;
  }

  const now = Date.now();
  if (now - (monitor.lastNotificationsCheck ?? 0) >= timing.notificationsIntervalMs) {
    if (await checkNotifications(settings, monitor)) await drainQueue(settings);
    return undefined;
  }
  if ((monitor.notifyQueue ?? []).some((id) => settings.groupIds.includes(id))) {
    await drainQueue(settings);
    return undefined;
  }
  const pick = (targetMs) => pickBackupGroup(
    settings.groupIds, monitor.groupLastVisit, now, targetMs, monitor.groupRetryAt,
  );
  const due = pick(timing.groupTargetMs);
  if (due) {
    await visitAndDeliver(settings, monitor, due);
    return undefined;
  }
  if (control.profileCheck) {
    await checkProfile(settings, monitor, control.profileCheck);
    return undefined;
  }
  const oldest = pick(0);
  if (oldest) {
    await visitAndDeliver(settings, monitor, oldest);
    return undefined;
  }
  return timing.errorPauseMs; // every group failed recently: wait a little
}

/**
 * Opens facebook.com/notifications and queues groups that got new posts.
 * Returns false if monitoring stopped (by the user or because of a checkpoint).
 */
async function checkNotifications(settings, monitor) {
  await updateMonitor({ currentVisit: { groupId: "сповіщення Facebook", startedAt: Date.now() }, nextRunAt: null });
  const visit = await visitNotifications(monitor.tabId);
  const current = await loadMonitor();
  if (!current.running) return false;

  if (STOP_STATES.has(visit.status)) {
    const alert = { kind: visit.status, message: STOP_MESSAGES[visit.status], at: Date.now() };
    await updateMonitor({ tabId: visit.tabId, currentVisit: null, lastNotificationsCheck: Date.now() });
    await sendAlert(settings, { kind: alert.kind, message: alert.message, stopped: true });
    await stopMonitor(alert);
    return false;
  }

  const items = visit.status === "ok" ? visit.items : [];
  const { queue, seen } = queueFromNotifications(
    items, settings.groupIds, current.notifyQueue, current.seenNotifications,
    SEEN_NOTIFICATIONS_LIMIT, current.groupAliases,
  );
  const queuedNow = queue.length - (current.notifyQueue ?? []).length;
  await updateMonitor({
    tabId: visit.tabId,
    currentVisit: null,
    lastNotificationsCheck: Date.now(),
    notifyQueue: queue,
    seenNotifications: seen,
    notificationsInfo: {
      at: Date.now(),
      status: visit.status,
      found: items.length,
      queued: queuedNow,
      error: visit.error ?? null,
    },
  });
  return true;
}

/**
 * Visits queued groups (new posts from notifications) one after another, without the long
 * pause — a few seconds between them, at most MAX_QUEUE_PER_TICK per step.
 */
async function drainQueue(settings) {
  for (let i = 0; i < timing.maxQueuePerTick; i += 1) {
    const monitor = await loadMonitor();
    if (!monitor.running) return;
    const groupId = (monitor.notifyQueue ?? []).find((id) => settings.groupIds.includes(id));
    if (!groupId) return;
    if (i > 0) await sleep(randomBetween(timing.queueGapMinMs, timing.queueGapMaxMs));
    await visitAndDeliver(settings, monitor, groupId);
  }
}

/** Visits one group, sends its posts to the server, updates the state (no scheduling). */
async function visitAndDeliver(settings, monitor, groupId) {
  // After a break (night, PC off) the first visit scrolls deeper to catch up.
  const deep = needsDeepScan(monitor.groupLastVisit?.[groupId]);
  await updateMonitor({ currentVisit: { groupId, startedAt: Date.now(), deep }, nextRunAt: null });
  const visit = await visitGroup(groupId, monitor.tabId, deep ? DEEP_SCROLL_STEPS : NORMAL_SCROLL_STEPS);

  monitor = await loadMonitor();
  if (!monitor.running) return; // stopped by the user while we were visiting
  const queue = (monitor.notifyQueue ?? []).filter((id) => id !== groupId);

  if (STOP_STATES.has(visit.status)) {
    const alert = { kind: visit.status, message: STOP_MESSAGES[visit.status], at: Date.now() };
    await updateMonitor({ tabId: visit.tabId, currentVisit: null, lastRun: runInfo(groupId, visit) });
    await sendAlert(settings, { kind: alert.kind, message: alert.message, group_id: groupId, stopped: true });
    await stopMonitor(alert);
    return;
  }

  const failures = { ...monitor.groupFailures };
  const lastVisits = { ...monitor.groupLastVisit };
  const retryAt = { ...monitor.groupRetryAt };
  const aliases = { ...monitor.groupAliases };
  if (visit.status === "ok") {
    delete failures[groupId];
    delete retryAt[groupId];
    lastVisits[groupId] = Date.now();
    if (visit.numericGroupId && visit.numericGroupId !== groupId) aliases[visit.numericGroupId] = groupId;
  } else {
    failures[groupId] = (failures[groupId] ?? 0) + 1;
    retryAt[groupId] = Date.now() + timing.failedRetryMs; // not again and again right now
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
    notifyQueue: queue,
    groupFailures: failures,
    groupLastVisit: lastVisits,
    groupRetryAt: retryAt,
    groupAliases: aliases,
    currentVisit: null,
    postsSent: monitor.postsSent + delivery.sent,
    lastRun: runInfo(groupId, visit, delivery),
  });
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


// --- visiting a group --------------------------------------------------------------

/** Opens the group in the monitor tab and parses it. Returns { status, tabId, posts?, error? }. */
async function visitGroup(groupId, tabId, scrollSteps = NORMAL_SCROLL_STEPS) {
  let tab;
  try {
    tab = await ensureTab(tabId);
    await navigateAndWait(tab.id, groupFeedUrl(groupId));
    await sleep(randomBetween(timing.renderWaitMinMs, timing.renderWaitMaxMs));

    let result = await parseTab(tab.id, scrollSteps);
    if (result.status === "ok" && result.posts.length === 0) {
      await sleep(timing.emptyFeedRetryMs); // feed may still be loading
      result = await parseTab(tab.id, NORMAL_SCROLL_STEPS);
    }
    return { ...result, tabId: tab.id };
  } catch (err) {
    return { status: "error", error: err.message, tabId: tab?.id ?? null };
  }
}

/** Opens the notifications page. Returns { status, tabId, items?, error? }. */
async function visitNotifications(tabId) {
  let tab;
  try {
    tab = await ensureTab(tabId);
    await navigateAndWait(tab.id, NOTIFICATIONS_URL);
    await sleep(randomBetween(timing.renderWaitMinMs, timing.renderWaitMaxMs));
    const target = { tabId: tab.id };
    await chrome.scripting.executeScript({ target, files: NOTIFICATIONS_SCRIPTS });
    const [{ result }] = await chrome.scripting.executeScript({
      target,
      func: () => {
        const state = globalThis.FLM.pageState();
        if (state !== "ok") return { status: state, items: [] };
        return globalThis.FLM.parseNotifications();
      },
    });
    return { ...result, tabId: tab.id };
  } catch (err) {
    return { status: "error", error: err.message, items: [], tabId: tab?.id ?? null };
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

async function parseTab(tabId, scrollSteps) {
  const target = { tabId };
  await chrome.scripting.executeScript({ target, files: CONTENT_SCRIPTS });
  const [{ result }] = await chrome.scripting.executeScript({
    target,
    args: [scrollSteps],
    func: async (steps) => {
      const state = globalThis.FLM.pageState();
      if (state !== "ok") return { status: state, posts: [] };
      return globalThis.FLM.parseFeed({ scrollSteps: steps });
    },
  });
  return result;
}

async function setBadge(text, color) {
  await chrome.action.setBadgeText({ text });
  if (text) await chrome.action.setBadgeBackgroundColor({ color });
}
