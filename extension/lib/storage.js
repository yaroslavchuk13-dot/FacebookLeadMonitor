// Settings and monitor state in chrome.storage.local, shared by popup and background.

export const DEFAULT_SETTINGS = { token: "", port: 8765, groupIds: [] };

export const DEFAULT_MONITOR = {
  running: false,
  lastIndex: -1, // index of the last visited group
  tabId: null, // the tab the monitor uses for Facebook
  nextRunAt: null, // ms timestamp of the next visit
  lastRun: null, // { groupId, at, status, found, sent, error }
  postsSent: 0,
  groupFailures: {}, // groupId -> consecutive failures (to avoid repeated alerts)
  alert: null, // { kind, message, at } — shown in the popup until the next start
};

export async function loadSettings() {
  const { settings } = await chrome.storage.local.get("settings");
  return { ...DEFAULT_SETTINGS, ...settings };
}

export async function saveSettings(settings) {
  await chrome.storage.local.set({ settings });
}

export async function loadMonitor() {
  const { monitor } = await chrome.storage.local.get("monitor");
  return { ...DEFAULT_MONITOR, ...monitor };
}

/** Merges `patch` into the stored monitor state and returns the new state. */
export async function updateMonitor(patch) {
  const monitor = { ...(await loadMonitor()), ...patch };
  await chrome.storage.local.set({ monitor });
  return monitor;
}

export async function loadOutbox() {
  const { outbox } = await chrome.storage.local.get("outbox");
  return outbox ?? [];
}

export async function saveOutbox(outbox) {
  await chrome.storage.local.set({ outbox });
}
