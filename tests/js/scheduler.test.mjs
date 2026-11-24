// Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addToOutbox,
  catchUpProgress,
  needsDeepScan,
  pickBackupGroup,
  queueFromNotifications,
  nextGroupIndex,
  PAUSE_MAX_SEC,
  PAUSE_MIN_SEC,
  randomPauseSec,
} from "../../extension/lib/scheduler.js";
import "../../extension/content/page_state.js"; // classic script: fills globalThis.FLM

test("pause stays within 30..40 seconds", () => {
  assert.equal(randomPauseSec(() => 0), PAUSE_MIN_SEC);
  assert.equal(randomPauseSec(() => 0.9999999), PAUSE_MAX_SEC);
  assert.equal(randomPauseSec(() => 1), PAUSE_MAX_SEC); // defensive
  for (let i = 0; i < 1000; i += 1) {
    const sec = randomPauseSec();
    assert.ok(Number.isInteger(sec) && sec >= 30 && sec <= 40, String(sec));
  }
});

test("groups are visited round-robin", () => {
  assert.equal(nextGroupIndex(3, -1), 0);
  assert.equal(nextGroupIndex(3, undefined), 0);
  assert.equal(nextGroupIndex(3, 0), 1);
  assert.equal(nextGroupIndex(3, 2), 0);
  assert.equal(nextGroupIndex(2, 5), 0); // list got shorter
  assert.equal(nextGroupIndex(0, 0), -1);
});

test("outbox removes duplicates and keeps the newest posts", () => {
  const p = (n) => ({ post_url: `u${n}`, text: `t${n}` });
  assert.deepEqual(addToOutbox([], [p(1), p(2)]), [p(1), p(2)]);
  assert.deepEqual(addToOutbox([p(1), p(2)], [p(1)]).map((x) => x.post_url), ["u2", "u1"]);
  assert.deepEqual(addToOutbox([p(1), p(2)], [p(3)], 2).map((x) => x.post_url), ["u2", "u3"]);
  assert.deepEqual(addToOutbox(undefined, undefined), []);
});

test("page classification", () => {
  const { classifyPage } = globalThis.FLM;
  assert.equal(classifyPage({ path: "/groups/123/" }), "ok");
  assert.equal(classifyPage({ path: "/checkpoint/828281030927956/" }), "checkpoint");
  assert.equal(classifyPage({ path: "/groups/1/", hasCaptcha: true }), "checkpoint");
  assert.equal(classifyPage({ path: "/login/?next=x" }), "login_required");
  assert.equal(classifyPage({ path: "/groups/1/", hasPasswordField: true }), "login_required");
  assert.equal(classifyPage({}), "ok");
});

test("deep scan after a break of more than 3 hours", () => {
  const now = Date.UTC(2026, 10, 25, 9, 0);
  assert.equal(needsDeepScan(undefined, now), true);
  assert.equal(needsDeepScan(now - 60 * 60 * 1000, now), false);
  assert.equal(needsDeepScan(now - 10 * 60 * 60 * 1000, now), true);
  const visits = { a: now - 1000, b: now - 10 * 60 * 60 * 1000 };
  assert.deepEqual(catchUpProgress(["a", "b", "c"], visits, now), { done: 1, total: 3 });
  assert.deepEqual(catchUpProgress([], undefined, now), { done: 0, total: 0 });
});

test("backup round: never visited first, then the oldest after an hour, failed ones wait", () => {
  const now = Date.UTC(2026, 10, 25, 12, 0);
  const hour = 60 * 60 * 1000;
  assert.equal(pickBackupGroup(["a", "b"], {}, now), "a");
  assert.equal(pickBackupGroup(["a", "b"], { a: now }, now), "b");
  assert.equal(pickBackupGroup(["a", "b"], { a: now, b: now - 5000 }, now), null);
  assert.equal(pickBackupGroup(["a", "b"], { a: now - 2 * hour, b: now - 3 * hour }, now), "b");
  assert.equal(pickBackupGroup(["a"], {}, now, hour, { a: now + 1000 }), null);
});

test("notifications queue only watched groups, once per key", () => {
  const items = [{ key: "n:1", groupId: "a" }, { key: "n:2", groupId: "x" }, { key: "n:3", groupId: "a" }];
  const first = queueFromNotifications(items, ["a", "b"], [], []);
  assert.deepEqual(first, { queue: ["a"], seen: ["n:1", "n:2", "n:3"] });
  const again = queueFromNotifications(items, ["a", "b"], [], first.seen);
  assert.deepEqual(again.queue, []);
  const capped = queueFromNotifications([{ key: "n:9", groupId: "b" }], ["b"], [], ["k1", "k2"], 2);
  assert.deepEqual(capped.seen, ["k2", "n:9"]);
});

test("freshly notified groups go to the front of the queue", () => {
  const result = queueFromNotifications([{ key: "n", groupId: "c" }], ["a", "b", "c"], ["a", "b"], []);
  assert.deepEqual(result.queue, ["c", "a", "b"]);
  const again = queueFromNotifications([{ key: "m", groupId: "b" }], ["a", "b", "c"], ["c", "a", "b"], []);
  assert.deepEqual(again.queue, ["b", "c", "a"]);
});
