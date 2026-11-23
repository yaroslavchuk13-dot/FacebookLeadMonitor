// Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addToOutbox,
  nextGroupIndex,
  PAUSE_MAX_SEC,
  PAUSE_MIN_SEC,
  randomPauseSec,
} from "../../extension/lib/scheduler.js";
import "../../extension/content/page_state.js"; // classic script: fills globalThis.FLM

test("pause stays within 45..60 seconds", () => {
  assert.equal(randomPauseSec(() => 0), PAUSE_MIN_SEC);
  assert.equal(randomPauseSec(() => 0.9999999), PAUSE_MAX_SEC);
  assert.equal(randomPauseSec(() => 1), PAUSE_MAX_SEC); // defensive
  for (let i = 0; i < 1000; i += 1) {
    const sec = randomPauseSec();
    assert.ok(Number.isInteger(sec) && sec >= 45 && sec <= 60, String(sec));
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
