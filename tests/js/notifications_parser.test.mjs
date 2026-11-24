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
  assert.deepEqual(items.map((i) => i.groupId), ["652491913033241", "1679476032884106", "481463709745206"]);
  assert.equal(new Set(items.map((i) => i.key)).size, 3);
});

test("Facebook updates one notification per group: same notif_id, new text -> new key", () => {
  // Real case (24.11.2026): the "Fire bobik" notification kept its id when a new post appeared.
  const before = extractNotificationItems([
    { href: "/groups/1208315175188424/?notif_id=777", text: 'Fire bobik: "Facebook Yarik krasavchik"\n19h' },
  ]);
  const after = extractNotificationItems([
    { href: "/groups/1208315175188424/?notif_id=777", text: 'Fire bobik: "HIRING EXPERIENCED FIRESTOPPERS"\n1m' },
  ]);
  assert.notEqual(before[0].key, after[0].key);
});

test("only the relative time changed -> same key (no re-visit every minute)", () => {
  const href = "/groups/1/?notif_id=5";
  const [a] = extractNotificationItems([{ href, text: 'Fire bobik: "HIRING"\n1m' }]);
  const [b] = extractNotificationItems([{ href, text: 'Fire bobik: "HIRING"\n3m' }]);
  const [c] = extractNotificationItems([{ href, text: 'Fire bobik: "HIRING"\n2 hours ago\nUnread' }]);
  assert.equal(a.key, b.key);
  assert.equal(a.key, c.key);
});

test("the key does not contain the notification text", () => {
  const [item] = extractNotificationItems([{ href: "/groups/1/", text: "John and 4 others posted in G" }]);
  assert.equal(item.groupId, "1");
  assert.ok(!item.key.includes("John"));
});

test("non-group and foreign links are ignored, duplicates removed", () => {
  const items = extractNotificationItems([
    { href: "/profile.php?id=5", text: "x" },
    { href: "/watch/", text: "x" },
    { href: "https://evil.example.com/groups/1/?notif_id=9", text: "x" },
    { href: "/groups/1/?notif_id=7", text: "x" },
    { href: "/groups/1/?notif_id=7", text: "x" },
  ]);
  assert.deepEqual(items.map((i) => i.groupId), ["1"]);
});
