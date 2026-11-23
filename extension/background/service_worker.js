// Background service worker: wires Chrome events to the monitor.
import { ALARM_NAME, resumeIfRunning, runTick, startMonitor, stopMonitor } from "./monitor.js";

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) runTick();
});

chrome.runtime.onStartup.addListener(() => {
  resumeIfRunning();
});

// Messages from the popup: { type: "monitor:start" | "monitor:stop" }.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;
  const handlers = {
    "monitor:start": () => startMonitor(),
    "monitor:stop": () => stopMonitor().then(() => ({ ok: true })),
  };
  const handler = handlers[message?.type];
  if (!handler) return false;
  handler()
    .then(sendResponse)
    .catch((err) => sendResponse({ ok: false, error: err.message }));
  return true; // async response
});
