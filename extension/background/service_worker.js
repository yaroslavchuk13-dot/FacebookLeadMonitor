// Background service worker: wires Chrome events to the monitor.
import {
  ALARM_NAME,
  resumeIfRunning,
  runTick,
  startMonitor,
  stopMonitor,
  watchdog,
  WATCHDOG_ALARM,
} from "./monitor.js";

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) runTick();
  if (alarm.name === WATCHDOG_ALARM) watchdog();
});

// Every service worker start (browser start, extension reload or update):
// make sure a running monitor keeps going.
resumeIfRunning();
// These listeners make Chrome start the service worker on browser start / extension
// update even if no alarm survived; the call above then does the work.
chrome.runtime.onStartup.addListener(() => {});
chrome.runtime.onInstalled.addListener(() => {});

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
