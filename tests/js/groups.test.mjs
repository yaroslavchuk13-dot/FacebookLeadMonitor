// Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import { groupFeedUrl, parseGroupId, parseGroupList } from "../../extension/groups.js";

test("parses numeric and slug group ids", () => {
  assert.equal(parseGroupId("https://www.facebook.com/groups/123456789/"), "123456789");
  assert.equal(parseGroupId("https://www.facebook.com/groups/kyiv.plumbers/?ref=share"), "kyiv.plumbers");
  assert.equal(parseGroupId("https://m.facebook.com/groups/123/posts/456/"), "123");
  assert.equal(parseGroupId("  facebook.com/groups/abc_def-1  "), "abc_def-1");
  assert.equal(parseGroupId("HTTPS://WWW.FACEBOOK.COM/groups/777"), "777");
});

test("rejects non-group or foreign links", () => {
  for (const bad of [
    "",
    "hello",
    "https://www.facebook.com/profile.php?id=1",
    "https://www.facebook.com/groups/",
    "https://evil.com/groups/123/",
    "https://facebook.com.evil.com/groups/123/",
    "https://www.facebook.com/groups/bad%20id/",
  ]) {
    assert.equal(parseGroupId(bad), null, bad);
  }
});

test("feed url uses chronological sorting", () => {
  assert.equal(
    groupFeedUrl("123"),
    "https://www.facebook.com/groups/123/?sorting_setting=CHRONOLOGICAL",
  );
});

test("parses list: skips blanks, removes duplicates, reports invalid lines", () => {
  const text = [
    "https://www.facebook.com/groups/111/",
    "",
    "https://www.facebook.com/groups/111/?ref=x",
    "not a link",
    "https://www.facebook.com/groups/222/",
  ].join("\r\n");
  assert.deepEqual(parseGroupList(text), {
    groupIds: ["111", "222"],
    invalidLines: ["not a link"],
  });
});
