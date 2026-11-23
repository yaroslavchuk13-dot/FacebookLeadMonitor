// Run: node --test tests/js/
// Runs the background monitor against a fake chrome.* API and a fake server (fetch).
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

// --- fake chrome API -------------------------------------------------------------------

const fake = {
  store: {},
  alarms: new Map(),
  tabs: new Map(),
  nextTabId: 1,
  navigations: [], // URLs opened in the monitor tab
  pageResult: null, // what the content script "returns" for the next parse
  badge: "",
  updatedListeners: new Set(),
  requests: [], // { path, body }
  serverUp: true,
};

globalThis.chrome = {
  storage: {
    local: {
      get: async (key) => ({ [key]: structuredClone(fake.store[key]) }),
      set: async (items) => Object.assign(fake.store, structuredClone(items)),
    },
  },
  alarms: {
    create: async (name, info) => fake.alarms.set(name, info),
    clear: async (name) => fake.alarms.delete(name),
    get: async (name) => fake.alarms.get(name),
  },
  tabs: {
    get: async (id) => {
      if (!fake.tabs.has(id)) throw new Error("No tab with id");
      return fake.tabs.get(id);
    },
    create: async ({ url }) => {
      const tab = { id: fake.nextTabId++, url };
      fake.tabs.set(tab.id, tab);
      return tab;
    },
    update: async (id, { url }) => {
      const tab = fake.tabs.get(id);
      tab.url = url;
      fake.navigations.push(url);
      setTimeout(() => {
        for (const listener of fake.updatedListeners) listener(id, { status: "complete" }, tab);
      }, 0);
      return tab;
    },
    onUpdated: {
      addListener: (fn) => fake.updatedListeners.add(fn),
      removeListener: (fn) => fake.updatedListeners.delete(fn),
    },
  },
  scripting: {
    executeScript: async ({ func }) => (func ? [{ result: structuredClone(fake.pageResult) }] : []),
  },
  action: {
    setBadgeText: async ({ text }) => {
      fake.badge = text;
    },
    setBadgeBackgroundColor: async () => {},
  },
};

globalThis.fetch = async (url, init) => {
  if (!fake.serverUp) throw new TypeError("Failed to fetch");
  const path = new URL(url).pathname;
  if (path === "/api/control") {
    const control = { paused: fake.paused, profile_check: fake.profileCheck };
    return { ok: true, status: 200, json: async () => control };
  }
  const body = JSON.parse(init.body);
  fake.requests.push({ path, body });
  if (path === "/api/profile_result") fake.profileCheck = null; // the server closes the check
  const json = path === "/api/posts" ? { accepted: body.posts.length, rejected: 0 } : { ok: true };
  return { ok: true, status: 200, json: async () => json };
};

const {
  ALARM_NAME,
  resumeIfRunning,
  runTick,
  startMonitor,
  stopByUser,
  stopMonitor,
  timing,
  watchdog,
  WATCHDOG_ALARM,
} = await import(
  "../../extension/background/monitor.js"
);
Object.assign(timing, { renderWaitMinMs: 0, renderWaitMaxMs: 0, emptyFeedRetryMs: 0 });

// --- helpers ---------------------------------------------------------------------------

const SETTINGS = { token: "t", port: 8765, groupIds: ["aaa", "bbb"] };
const post = (n) => ({
  group_id: "aaa",
  post_url: `https://www.facebook.com/groups/aaa/posts/${n}/`,
  text: `post ${n}`,
});
const okPage = (...posts) => ({ status: "ok", posts, skipped: 0 });
const monitor = () => fake.store.monitor;
const postRequests = () => fake.requests.filter((r) => r.path === "/api/posts");
const alertRequests = () => fake.requests.filter((r) => r.path === "/api/alert");

beforeEach(() => {
  Object.assign(fake, {
    store: { settings: structuredClone(SETTINGS), monitor: { running: true } },
    alarms: new Map(),
    tabs: new Map(),
    nextTabId: 1,
    navigations: [],
    pageResult: okPage(),
    badge: "",
    requests: [],
    serverUp: true,
    paused: false,
    profileCheck: null,
  });
});

// --- tests -----------------------------------------------------------------------------

test("start requires token and groups", async () => {
  fake.store.settings = { token: "", port: 8765, groupIds: ["aaa"] };
  assert.equal((await startMonitor()).ok, false);
  fake.store.settings = { token: "t", port: 8765, groupIds: [] };
  assert.equal((await startMonitor()).ok, false);
});

test("a tick visits the group, sends posts and schedules the next visit", async () => {
  fake.pageResult = okPage(post(1), post(2));
  await runTick();

  assert.deepEqual(fake.navigations, [
    "https://www.facebook.com/groups/aaa/?sorting_setting=CHRONOLOGICAL",
  ]);
  assert.equal(postRequests().length, 1);
  assert.equal(postRequests()[0].body.posts.length, 2);
  assert.equal(monitor().postsSent, 2);
  assert.equal(monitor().lastRun.status, "ok");
  assert.equal(monitor().lastIndex, 0);

  const alarm = fake.alarms.get(ALARM_NAME);
  assert.ok(alarm.delayInMinutes >= 0.75 && alarm.delayInMinutes <= 1, String(alarm.delayInMinutes));
  assert.ok(monitor().nextRunAt > Date.now());
});

test("groups are visited in turn and the same tab is reused", async () => {
  await runTick();
  await runTick();
  await runTick();
  assert.deepEqual(
    fake.navigations.map((u) => new URL(u).pathname),
    ["/groups/aaa/", "/groups/bbb/", "/groups/aaa/"],
  );
  assert.equal(fake.tabs.size, 1);
});

test("a closed monitor tab is reopened", async () => {
  await runTick();
  fake.tabs.clear(); // user closed the tab
  await runTick();
  assert.equal(fake.tabs.size, 1);
  assert.equal(monitor().lastRun.status, "ok");
});

test("posts wait in the outbox while the server is down", async () => {
  fake.serverUp = false;
  fake.pageResult = okPage(post(1));
  await runTick();
  assert.equal(fake.store.outbox.length, 1);
  assert.equal(monitor().postsSent, 0);
  assert.match(monitor().lastRun.error, /Сервер недоступний/);
  assert.ok(fake.alarms.has(ALARM_NAME), "keeps running");

  fake.serverUp = true;
  fake.pageResult = okPage(post(1), post(2)); // post 1 again: no duplicate
  await runTick();
  assert.equal(postRequests().at(-1).body.posts.length, 2);
  assert.deepEqual(fake.store.outbox, []);
  assert.equal(monitor().postsSent, 2);
});

for (const kind of ["checkpoint", "login_required"]) {
  test(`${kind} stops monitoring and raises an alert`, async () => {
    fake.alarms.set(ALARM_NAME, { delayInMinutes: 1 });
    fake.pageResult = { status: kind, posts: [] };
    await runTick();

    assert.equal(monitor().running, false);
    assert.equal(monitor().alert.kind, kind);
    assert.equal(fake.alarms.has(ALARM_NAME), false);
    assert.equal(fake.badge, "!");
    assert.equal(alertRequests().length, 1);
    assert.equal(alertRequests()[0].body.stopped, true);
    assert.equal(alertRequests()[0].body.kind, kind);
  });
}

test("a broken group alerts once, not on every cycle, and the loop continues", async () => {
  fake.store.settings.groupIds = ["aaa"];
  fake.pageResult = { status: "no_feed", posts: [] };
  await runTick();
  await runTick();
  assert.equal(alertRequests().length, 1);
  assert.equal(alertRequests()[0].body.kind, "no_feed");
  assert.equal(monitor().running, true);

  fake.pageResult = okPage();
  await runTick(); // recovered
  fake.pageResult = { status: "no_feed", posts: [] };
  await runTick(); // broken again -> new alert
  assert.equal(alertRequests().length, 2);
});

test("stop clears the alarm and nothing runs afterwards", async () => {
  fake.alarms.set(ALARM_NAME, { delayInMinutes: 1 });
  await stopMonitor();
  assert.equal(monitor().running, false);
  assert.equal(fake.alarms.has(ALARM_NAME), false);
  await runTick();
  assert.deepEqual(fake.navigations, []);
});

// --- watchdog / recovery -----------------------------------------------------------------

const waitFor = async (check) => {
  for (let i = 0; i < 100 && !check(); i += 1) await new Promise((r) => setTimeout(r, 5));
};

test("start creates the watchdog, stop removes it", async () => {
  fake.store.monitor = { running: false };
  assert.equal((await startMonitor()).ok, true);
  assert.ok(fake.alarms.get(WATCHDOG_ALARM).periodInMinutes > 0);
  await waitFor(() => fake.alarms.has(ALARM_NAME)); // first visit finished
  await stopMonitor();
  assert.equal(fake.alarms.has(WATCHDOG_ALARM), false);
  assert.equal(monitor().currentVisit, null);
});

test("watchdog restarts a lost loop (no tick alarm)", async () => {
  await watchdog();
  await waitFor(() => fake.alarms.has(ALARM_NAME));
  assert.equal(fake.navigations.length, 1);
  assert.equal(monitor().currentVisit, null);
  assert.ok(monitor().nextRunAt > Date.now());
});

test("watchdog does nothing while the next visit is scheduled", async () => {
  fake.alarms.set(ALARM_NAME, { delayInMinutes: 1 });
  await watchdog();
  assert.deepEqual(fake.navigations, []);
});

test("watchdog does nothing when monitoring is stopped", async () => {
  fake.store.monitor = { running: false };
  await watchdog();
  assert.deepEqual(fake.navigations, []);
});

test("service worker restart re-creates the watchdog for a running monitor", async () => {
  await resumeIfRunning();
  assert.ok(fake.alarms.has(WATCHDOG_ALARM));
  fake.store.monitor = { running: false };
  fake.alarms.clear();
  await resumeIfRunning();
  assert.equal(fake.alarms.has(WATCHDOG_ALARM), false);
});

test("last run keeps the group name for the popup", async () => {
  fake.pageResult = { ...okPage(), groupName: "Firestoppers UK Work" };
  await runTick();
  assert.equal(monitor().lastRun.groupName, "Firestoppers UK Work");
});

// --- pause from Telegram / start-stop notifications ----------------------------------------

test("paused from Telegram: no Facebook visit, next check is scheduled", async () => {
  fake.paused = true;
  await runTick();
  assert.deepEqual(fake.navigations, []);
  assert.equal(monitor().lastRun.status, "paused");
  assert.ok(fake.alarms.has(ALARM_NAME));

  fake.paused = false; // /resume
  await runTick();
  assert.equal(fake.navigations.length, 1);
});

test("start and stop are reported to the server", async () => {
  fake.store.monitor = { running: false };
  await startMonitor();
  await waitFor(() => fake.alarms.has(ALARM_NAME));
  await stopByUser();
  const kinds = alertRequests().map((r) => r.body.kind);
  assert.deepEqual(kinds, ["started", "stopped"]);
  assert.equal(alertRequests()[1].body.stopped, true);
  assert.equal(monitor().running, false);
});

// --- author profile check (scam check) -----------------------------------------------------

const PROFILE_URL = "https://www.facebook.com/profile.php?id=42";

test("a queued profile check is done instead of a group visit", async () => {
  fake.profileCheck = { id: 7, profile_url: PROFILE_URL };
  fake.pageResult = { status: "ok", profile: { status: "ok", has_photo: true, friends: 300 } };
  await runTick();
  assert.deepEqual(fake.navigations, [PROFILE_URL]);
  const result = fake.requests.find((r) => r.path === "/api/profile_result");
  assert.deepEqual(result.body, { check_id: 7, profile: { status: "ok", has_photo: true, friends: 300 } });
  assert.equal(monitor().lastRun.groupName, "Перевірка автора");
  assert.ok(fake.alarms.has(ALARM_NAME));

  fake.pageResult = okPage();
  await runTick(); // no more checks -> back to groups
  assert.equal(new URL(fake.navigations[1]).pathname, "/groups/aaa/");
});

test("checkpoint on a profile stops monitoring", async () => {
  fake.profileCheck = { id: 8, profile_url: PROFILE_URL };
  fake.pageResult = { status: "checkpoint" };
  await runTick();
  assert.equal(monitor().running, false);
  assert.equal(alertRequests()[0].body.kind, "checkpoint");
  assert.equal(fake.requests.some((r) => r.path === "/api/profile_result"), false);
});

test("a profile that fails to open is reported as an error", async () => {
  fake.profileCheck = { id: 9, profile_url: PROFILE_URL };
  fake.pageResult = null; // executeScript gives nothing -> exception inside the visit
  await runTick();
  const result = fake.requests.find((r) => r.path === "/api/profile_result");
  assert.deepEqual(result.body, { check_id: 9, profile: { status: "error" } });
  assert.equal(monitor().running, true);
});

test("a profile url outside facebook.com is ignored", async () => {
  fake.profileCheck = { id: 10, profile_url: "https://evil.example.com/x" };
  await runTick();
  assert.equal(new URL(fake.navigations[0]).pathname, "/groups/aaa/");
});
