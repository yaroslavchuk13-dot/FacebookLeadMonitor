// Pure helpers for links and text found on a Facebook group page.
// Content scripts cannot be ES modules, so this is a classic script that puts
// its functions on globalThis.FLM (shared with feed_parser.js in the same tab).
(() => {
  const FB = "https://www.facebook.com";
  const FB_HOSTS = new Set(["facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com"]);
  const ID_RE = /^[A-Za-z0-9._-]+$/;
  const POST_ID_RE = /^[A-Za-z0-9]+$/; // numeric id or "pfbid..."

  // First path segments that are never a user name.
  const RESERVED = new Set([
    "groups", "watch", "events", "photo", "photo.php", "photos", "hashtag", "stories",
    "permalink.php", "story.php", "sharer", "sharer.php", "marketplace", "pages", "reel",
    "reels", "gaming", "help", "settings", "notifications", "messages", "friends", "login",
    "checkpoint", "privacy", "policies", "ads", "business", "search", "bookmarks", "l.php",
  ]);

  /** Parses an href (absolute or relative) into a URL on facebook.com, or null. */
  function toFacebookUrl(href) {
    if (!href || href === "#") return null;
    let url;
    try {
      url = new URL(href, FB);
    } catch {
      return null;
    }
    return FB_HOSTS.has(url.hostname.toLowerCase()) ? url : null;
  }

  /**
   * Canonical post URL: https://www.facebook.com/groups/<groupId>/posts/<postId>/
   * Understands /groups/x/posts/ID, /groups/x/permalink/ID, permalink.php?story_fbid=ID,
   * ?multi_permalinks=ID. Returns null if the href is not a post link.
   */
  function canonicalPostUrl(href, groupId) {
    const url = toFacebookUrl(href);
    if (!url || !groupId) return null;
    const parts = url.pathname.split("/").filter(Boolean);

    let postId = null;
    if (parts[0] === "groups" && (parts[2] === "posts" || parts[2] === "permalink")) {
      postId = parts[3];
    } else if (parts[0] === "permalink.php" || parts[0] === "story.php") {
      postId = url.searchParams.get("story_fbid");
    } else if (url.searchParams.has("multi_permalinks")) {
      postId = url.searchParams.get("multi_permalinks").split(",")[0];
    }
    if (!postId || !POST_ID_RE.test(postId)) return null;
    return `${FB}/groups/${encodeURIComponent(groupId)}/posts/${postId}/`;
  }

  /**
   * Canonical author profile URL, without tracking parameters, or null.
   *   /groups/g/user/123/      -> https://www.facebook.com/profile.php?id=123
   *   /profile.php?id=123&...  -> https://www.facebook.com/profile.php?id=123
   *   /ivan.petrenko?__cft__=  -> https://www.facebook.com/ivan.petrenko
   */
  function canonicalProfileUrl(href) {
    const url = toFacebookUrl(href);
    if (!url) return null;
    const parts = url.pathname.split("/").filter(Boolean);

    if (parts[0] === "groups" && parts[2] === "user" && /^\d+$/.test(parts[3] ?? "")) {
      return `${FB}/profile.php?id=${parts[3]}`;
    }
    if (parts[0] === "profile.php") {
      const id = url.searchParams.get("id");
      return id && /^\d+$/.test(id) ? `${FB}/profile.php?id=${id}` : null;
    }
    if (parts.length === 1 && !RESERVED.has(parts[0].toLowerCase()) && ID_RE.test(parts[0])) {
      return `${FB}/${parts[0]}`;
    }
    return null;
  }

  // Button labels in the Facebook UI (English / Ukrainian / Russian).
  const SEE_MORE_WORDS = ["See more", "Детальніше", "Показати більше", "Більше", "Ещё", "Еще", "Читать дальше"];
  // Shown at the end of an expanded post; must never be clicked, only removed from text.
  const SEE_LESS_WORDS = ["See less", "Показати менше", "Згорнути", "Показать меньше", "Свернуть"];
  const SEE_ORIGINAL_WORDS = ["See original", "Показати оригінал", "Переглянути оригінал", "Показать оригинал"];
  const TRANSLATION_FOOTER_WORDS = [
    ...SEE_ORIGINAL_WORDS,
    "Rate this translation", "See translation",
    "Оцініть цей переклад", "Переглянути переклад", "Показати переклад",
    "Оцените этот перевод", "Показать перевод", "Посмотреть перевод",
  ];

  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const exactWordsRe = (words) => new RegExp(`^(?:${words.map(escapeRe).join("|")})$`, "i");
  const SEE_MORE_BUTTON_RE = exactWordsRe(SEE_MORE_WORDS);
  const SEE_ORIGINAL_BUTTON_RE = exactWordsRe(SEE_ORIGINAL_WORDS);

  // "See more" / "See less" text glued to the end of a post.
  const TOGGLE_WORDS = [...SEE_MORE_WORDS, ...SEE_LESS_WORDS];
  const SEE_MORE_RE = new RegExp(`(?:…|\\.\\.\\.)?\\s*(?:${TOGGLE_WORDS.map(escapeRe).join("|")})\\s*$`, "i");
  // A line made only of translation controls: "Показать оригинал · Оцените этот перевод".
  const TRANSLATION_LINE_RE = new RegExp(
    `^(?:\\s*(?:${TRANSLATION_FOOTER_WORDS.map(escapeRe).join("|")})\\s*[·•]?)+$`,
    "i",
  );

  const buttonLabel = (text) => String(text ?? "").replace(/\s+/g, " ").trim();
  /** True for the "See more" / "Ещё" button that expands a truncated post. */
  const isSeeMoreButton = (text) => SEE_MORE_BUTTON_RE.test(buttonLabel(text));
  /** True for the "See original" button of an auto-translated post. */
  const isSeeOriginalButton = (text) => SEE_ORIGINAL_BUTTON_RE.test(buttonLabel(text));

  /** Normalizes post text: trims lines, collapses blank lines, drops "See more" and translation controls. */
  function cleanText(text) {
    return String(text ?? "")
      .replace(/ /g, " ")
      .split("\n")
      .map((line) => line.replace(/[ \t]+/g, " ").trim())
      .filter((line) => !TRANSLATION_LINE_RE.test(line))
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim()
      .replace(SEE_MORE_RE, "")
      .trim();
  }

  /** 32-bit FNV-1a hash as 8 hex chars (stable across runs, no crypto needed). */
  function fnv1a(text, seed = 0x811c9dc5) {
    let hash = seed;
    for (let i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash.toString(16).padStart(8, "0");
  }

  /**
   * Used when Facebook did not reveal the post link: a stable group URL derived from
   * author + text, so the same post always gets the same URL (deduplication works).
   */
  function fallbackPostUrl(groupId, authorKey, text) {
    const key = `${authorKey ?? ""}\n${String(text ?? "").toLowerCase().replace(/\s+/g, " ").trim()}`;
    const id = fnv1a(key) + fnv1a(key, 0x2c9277b5);
    return `${FB}/groups/${encodeURIComponent(groupId)}/?flm_post=${id}`;
  }

  const api = {
    canonicalPostUrl,
    canonicalProfileUrl,
    cleanText,
    fallbackPostUrl,
    isSeeMoreButton,
    isSeeOriginalButton,
  };
  globalThis.FLM = Object.assign(globalThis.FLM ?? {}, { postLinks: api });
})();
