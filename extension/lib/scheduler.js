// Pure scheduling helpers for the background monitor (no chrome.* API, unit-tested).

// Pause between two page visits (30 s is the shortest Chrome alarm).
export const PAUSE_MIN_SEC = 30;
export const PAUSE_MAX_SEC = 40;

// Facebook notifications ("X posted in Group Y") are checked this often; a group with a new
// post is visited right after. Every group is also visited as a backup this often.
export const NOTIFICATIONS_INTERVAL_MS = 90 * 1000;
export const BACKUP_VISIT_MS = 60 * 60 * 1000;
export const SEEN_NOTIFICATIONS_LIMIT = 500;

/**
 * The group for the backup round: never visited first (in list order), otherwise the one
 * visited longest ago if that was BACKUP_VISIT_MS or more ago; null if all are fresh.
 */
export function pickBackupGroup(
  groupIds, lastVisits, now = Date.now(), intervalMs = BACKUP_VISIT_MS, retryAt = {},
) {
  let oldest = null;
  for (const id of groupIds ?? []) {
    if (retryAt?.[id] > now) continue; // failed recently: wait before retrying
    const last = lastVisits?.[id];
    if (!Number.isFinite(last)) return id;
    if (now - last >= intervalMs && (oldest === null || last < lastVisits[oldest])) oldest = id;
  }
  return oldest;
}

/**
 * New notifications -> groups to visit. Only groups from the settings; keys already seen are
 * skipped. Returns { queue, seen } (seen is capped, newest kept).
 */
export function queueFromNotifications(items, groupIds, queue, seen, limit = SEEN_NOTIFICATIONS_LIMIT) {
  const watched = new Set(groupIds ?? []);
  const seenSet = new Set(seen ?? []);
  const newQueue = [...(queue ?? [])];
  const newSeen = [...(seen ?? [])];
  for (const { key, groupId } of items ?? []) {
    if (seenSet.has(key)) continue;
    seenSet.add(key);
    newSeen.push(key);
    if (watched.has(groupId) && !newQueue.includes(groupId)) newQueue.push(groupId);
  }
  return { queue: newQueue, seen: newSeen.slice(-limit) };
}

// Posts waiting to be delivered while the local server is unreachable.
export const OUTBOX_LIMIT = 500;

// How far a group visit scrolls. After a break (night, PC off) the first visit goes deeper
// so posts published meanwhile are not missed.
export const NORMAL_SCROLL_STEPS = 6; // ~10-15 newest posts
export const DEEP_SCROLL_STEPS = 25; // ~40-50 posts
export const DEEP_SCAN_AFTER_MS = 3 * 60 * 60 * 1000;

/** True if the group was never visited or not for a long time. */
export function needsDeepScan(lastVisitMs, now = Date.now()) {
  return !Number.isFinite(lastVisitMs) || now - lastVisitMs > DEEP_SCAN_AFTER_MS;
}

/** How many of the groups are already caught up after a break: { done, total }. */
export function catchUpProgress(groupIds, lastVisits, now = Date.now()) {
  const done = groupIds.filter((id) => !needsDeepScan(lastVisits?.[id], now)).length;
  return { done, total: groupIds.length };
}

/** Random whole number of seconds in [PAUSE_MIN_SEC, PAUSE_MAX_SEC]. */
export function randomPauseSec(random = Math.random) {
  const span = PAUSE_MAX_SEC - PAUSE_MIN_SEC + 1;
  return PAUSE_MIN_SEC + Math.min(span - 1, Math.floor(random() * span));
}

/** Round-robin: index of the group to visit after `lastIndex`, or -1 if there are no groups. */
export function nextGroupIndex(groupCount, lastIndex) {
  if (!Number.isInteger(groupCount) || groupCount <= 0) return -1;
  if (!Number.isInteger(lastIndex) || lastIndex < 0) return 0;
  return (lastIndex + 1) % groupCount;
}

/**
 * Adds posts to the outbox without duplicates (by post_url).
 * When the limit is exceeded the oldest posts are dropped.
 */
export function addToOutbox(outbox, posts, limit = OUTBOX_LIMIT) {
  const byUrl = new Map((outbox ?? []).map((p) => [p.post_url, p]));
  for (const post of posts ?? []) {
    byUrl.delete(post.post_url); // re-insert to move it to the end (newest)
    byUrl.set(post.post_url, post);
  }
  const all = [...byUrl.values()];
  return all.length > limit ? all.slice(all.length - limit) : all;
}
