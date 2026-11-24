// Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import "../../extension/content/notifications_parser.js"; // classic script: fills globalThis.FLM

const { extractNotificationItems } = globalThis.FLM;

test("group post notifications give group ids", () => {
  const items = extractNotificationItems([
    { href: "/groups/652491913033241/posts/1664606208488/?notif_id=111&notif_t=group_activity", text: "A posted" },
    { href: "https://www.facebook.com/groups/1679476032884106/permalink/2408/?notif_id=222", text: "B posted" },
    { href: "/groups/481463709745206/?notif_id=333&notif_t=group_highlights", text: "C and 5 others posted" },
  ]);
  assert.deepEqual(items, [
    { key: "n:111", groupId: "652491913033241" },
    { key: "n:222", groupId: "1679476032884106" },
    { key: "n:333", groupId: "481463709745206" },
  ]);
});

test("without notif_id the key follows the text (updated notification -> new key)", () => {
  const [a] = extractNotificationItems([{ href: "/groups/1/", text: "John and 4 others posted in G" }]);
  const [b] = extractNotificationItems([{ href: "/groups/1/", text: "John and 5 others posted in G" }]);
  assert.equal(a.groupId, "1");
  assert.notEqual(a.key, b.key);
  assert.ok(!a.key.includes("John"), "text is hashed, not stored");
});

test("non-group and foreign links are ignored, duplicates removed", () => {
  const items = extractNotificationItems([
    { href: "/profile.php?id=5", text: "x" },
    { href: "/watch/", text: "x" },
    { href: "https://evil.example.com/groups/1/?notif_id=9", text: "x" },
    { href: "/groups/1/?notif_id=7", text: "x" },
    { href: "/groups/1/posts/2/?notif_id=7", text: "x" },
    { href: "::bad::", text: "x" },
  ]);
  assert.deepEqual(items, [{ key: "n:7", groupId: "1" }]);
});
