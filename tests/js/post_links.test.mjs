// Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import "../../extension/content/post_links.js"; // classic script: fills globalThis.FLM

const { canonicalPostUrl, canonicalProfileUrl, cleanText } = globalThis.FLM.postLinks;
const POST = "https://www.facebook.com/groups/g1/posts/";

test("post url from different link shapes", () => {
  const cases = [
    ["/groups/g1/posts/123456/?__cft__[0]=abc&__tn__=R", "123456"],
    ["https://www.facebook.com/groups/999/permalink/777/", "777"],
    ["https://m.facebook.com/groups/g1/posts/pfbid0AbC123/", "pfbid0AbC123"],
    ["/permalink.php?story_fbid=555&id=1", "555"],
    ["/groups/g1/?multi_permalinks=888,999", "888"],
  ];
  for (const [href, postId] of cases) {
    assert.equal(canonicalPostUrl(href, "g1"), `${POST}${postId}/`, href);
  }
});

test("non-post links are ignored", () => {
  for (const href of [
    "#",
    "",
    null,
    "/groups/g1/",
    "/groups/g1/user/123/",
    "/groups/g1/posts/",
    "/groups/g1/posts/12%2034/",
    "https://evil.com/groups/g1/posts/1/",
    "/photo/?fbid=1",
  ]) {
    assert.equal(canonicalPostUrl(href, "g1"), null, String(href));
  }
  assert.equal(canonicalPostUrl("/groups/g1/posts/1/", ""), null);
});

test("profile url from different link shapes", () => {
  assert.equal(
    canonicalProfileUrl("/groups/g1/user/100012345/?__cft__[0]=x"),
    "https://www.facebook.com/profile.php?id=100012345",
  );
  assert.equal(
    canonicalProfileUrl("https://www.facebook.com/profile.php?id=42&__tn__=R"),
    "https://www.facebook.com/profile.php?id=42",
  );
  assert.equal(
    canonicalProfileUrl("https://www.facebook.com/ivan.petrenko?__cft__[0]=x"),
    "https://www.facebook.com/ivan.petrenko",
  );
});

test("non-profile links are ignored", () => {
  for (const href of [
    "/groups/g1/",
    "/groups/g1/posts/1/",
    "/hashtag/plumber",
    "/watch/",
    "/profile.php",
    "/ivan/photos",
    "https://evil.com/ivan",
    "#",
  ]) {
    assert.equal(canonicalProfileUrl(href), null, href);
  }
});

test("text is cleaned", () => {
  assert.equal(cleanText("  Шукаю   сантехніка \n\n\n\n Київ  "), "Шукаю сантехніка\n\nКиїв");
  assert.equal(cleanText("Потрібен майстер… See more"), "Потрібен майстер");
  assert.equal(cleanText("Потрібен майстер... Детальніше"), "Потрібен майстер");
  assert.equal(cleanText("a b"), "a b");
  assert.equal(cleanText(null), "");
});

test("see more / see original buttons are recognized (en/uk/ru)", () => {
  const { isSeeMoreButton, isSeeOriginalButton } = globalThis.FLM.postLinks;
  for (const label of ["See more", "Ещё", "Еще", " Детальніше ", "Показати більше", "see MORE"]) {
    assert.equal(isSeeMoreButton(label), true, label);
  }
  for (const label of ["See more comments", "Ещё 5 комментариев", "Нравится", "", null]) {
    assert.equal(isSeeMoreButton(label), false, String(label));
  }
  for (const label of ["Показать оригинал", "See original", "Показати оригінал"]) {
    assert.equal(isSeeOriginalButton(label), true, label);
  }
  assert.equal(isSeeOriginalButton("Оцените этот перевод"), false);
});

test("translation controls are removed from text", () => {
  assert.equal(
    cleanText("ПОЖАР DBS СЕГОДНЯ\nОдин текст\nПоказать оригинал · Оцените этот перевод"),
    "ПОЖАР DBS СЕГОДНЯ\nОдин текст",
  );
  assert.equal(cleanText("Need a plumber\nSee translation"), "Need a plumber");
  assert.equal(cleanText("Од... Ещё"), "Од");
  // A normal sentence that merely contains the words is kept.
  assert.equal(cleanText("Please see original drawings"), "Please see original drawings");
});

test("'see less' is removed from expanded text and never treated as 'see more'", () => {
  const { isSeeMoreButton } = globalThis.FLM.postLinks;
  assert.equal(cleanText("Or 07700000000\nThank you! Показать меньше"), "Or 07700000000\nThank you!");
  assert.equal(cleanText("Thank you! See less"), "Thank you!");
  assert.equal(cleanText("Дякую! Згорнути"), "Дякую!");
  for (const label of ["See less", "Показать меньше", "Згорнути"]) {
    assert.equal(isSeeMoreButton(label), false, label);
  }
});

test("fallback post url is stable and ignores case/spacing", () => {
  const { fallbackPostUrl } = globalThis.FLM.postLinks;
  const a = fallbackPostUrl("g1", "https://www.facebook.com/x", "Need  fire\nstoppers");
  const b = fallbackPostUrl("g1", "https://www.facebook.com/x", "need fire stoppers");
  assert.equal(a, b);
  assert.match(a, /^https:\/\/www\.facebook\.com\/groups\/g1\/\?flm_post=[0-9a-f]{16}$/);
  assert.notEqual(a, fallbackPostUrl("g1", "https://www.facebook.com/y", "need fire stoppers"));
  assert.notEqual(a, fallbackPostUrl("g1", "https://www.facebook.com/x", "need plumbers"));
  // not mistaken for a real post link
  assert.equal(canonicalPostUrl(a, "g1"), null);
});
