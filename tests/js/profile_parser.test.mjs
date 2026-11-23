// Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import "../../extension/content/profile_parser.js"; // classic script: fills globalThis.FLM

const { extractProfileSignals } = globalThis.FLM;
const PHOTO = "https://scontent-lhr8-1.xx.fbcdn.net/v/t39.30808-1/photo.jpg";
const DEFAULT = "https://static.xx.fbcdn.net/rsrc.php/v3/yo/r/default.png";

test("normal person profile", () => {
  const text = [
    "Ivan Petrenko",
    "1.2K friends",
    "Intro",
    "Works at Fire Protection Ltd",
    "Lives in London, United Kingdom",
    "From Kyiv, Ukraine",
    "Joined Facebook in 2013",
  ].join("\n");
  assert.deepEqual(extractProfileSignals(text, PHOTO), {
    status: "ok",
    has_photo: true,
    friends: 1200,
    followers: null,
    joined_year: 2013,
    intro_items: 3,
    is_locked: false,
    is_page: false,
  });
});

test("suspicious profile: default avatar, few friends, empty intro", () => {
  const s = extractProfileSignals("Jobs London UK\n7 friends\nIntro\nNo intro to show", DEFAULT);
  assert.equal(s.has_photo, false);
  assert.equal(s.friends, 7);
  assert.equal(s.intro_items, 0);
});

test("mutual friends are not the friend count", () => {
  assert.equal(extractProfileSignals("12 mutual friends", PHOTO).friends, null);
  assert.equal(extractProfileSignals("350 friends • 12 mutual", PHOTO).friends, 350);
  assert.equal(extractProfileSignals("1,234 друзів", PHOTO).friends, 1234);
});

test("no Intro section -> intro unknown (not 'empty')", () => {
  assert.equal(extractProfileSignals("Ivan\n300 friends", PHOTO).intro_items, null);
});

test("unavailable, locked, business page", () => {
  assert.deepEqual(extractProfileSignals("This content isn't available right now", null), { status: "unavailable" });
  assert.deepEqual(extractProfileSignals("", null), { status: "unavailable" });
  assert.equal(extractProfileSignals("Ivan locked his profile", PHOTO).is_locked, true);
  const page = extractProfileSignals("DBS Fire Ltd\nPage · Construction company\n2.5K followers", PHOTO);
  assert.equal(page.is_page, true);
  assert.equal(page.followers, 2500);
});

test("unknown avatar url -> photo unknown", () => {
  assert.equal(extractProfileSignals("Ivan\n300 friends", null).has_photo, null);
  assert.equal(extractProfileSignals("Ivan\n300 friends", "https://example.com/x.png").has_photo, null);
});
