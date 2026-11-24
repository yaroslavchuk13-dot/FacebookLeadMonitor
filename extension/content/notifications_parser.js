// Reads facebook.com/notifications: which groups got new posts ("X posted in Group Y").
// Classic content script; exposes FLM.extractNotificationItems (pure, unit-tested) and
// FLM.parseNotifications. Only group ids and opaque keys leave the page — no names, no text.
(() => {
  const GROUP_RE = /\/groups\/([^/?#]+)/;
  // Relative time lines ("3m", "19h", "2w", "Just now", "5 minutes ago") change every minute:
  // they are removed before hashing, otherwise every notification would look new each time.
  const TIME_LINE_RE =
    /^(?:just now|now|щойно|только что|\d{1,3}\s?(?:s|m|h|d|w|y|mo|secs?|mins?|minutes?|hrs?|hours?|days?|weeks?|months?|years?|хв|год|дн|тиж|міс|р|мин|ч|д|нед|мес|г)\.?(?:\s+(?:ago|тому|назад))?)$/i;
  // Facebook updates ONE notification per group ("Group: new post…") instead of adding new ones,
  // so the notification id alone does not change — the key includes the text as well.

  function stableText(text) {
    return String(text ?? "")
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line && !TIME_LINE_RE.test(line) && !/^(?:unread|mark as read|непрочитане)$/i.test(line))
      .join("\n");
  }
  const ROW_SELECTOR = '[role="row"], [role="listitem"], [role="gridcell"], li';

  /** 32-bit FNV-1a as hex: the notification text is hashed, never sent. */
  function fnv1a(text) {
    let hash = 0x811c9dc5;
    for (let i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash.toString(16).padStart(8, "0");
  }

  /**
   * items: [{ href, text }] of links on the notifications page.
   * Returns [{ key, groupId }]: key changes when a notification is new or updated
   * ("John and 4 others posted" -> "John and 5 others posted").
   */
  function extractNotificationItems(items) {
    const result = [];
    const seen = new Set();
    for (const { href, text } of items ?? []) {
      let url;
      try {
        url = new URL(href, "https://www.facebook.com");
      } catch {
        continue;
      }
      if (!/(^|\.)facebook\.com$/i.test(url.hostname)) continue;
      const match = url.pathname.match(GROUP_RE);
      if (!match) continue;
      const groupId = decodeURIComponent(match[1]);
      const notifId = url.searchParams.get("notif_id") ?? "";
      const key = `${groupId}:${notifId}:${fnv1a(stableText(text))}`;
      if (seen.has(key)) continue;
      seen.add(key);
      result.push({ key, groupId });
    }
    return result;
  }

  /** Reads the notification list of the open page. */
  function parseNotifications() {
    const root = document.querySelector('[role="main"]') ?? document.body;
    const links = [...root.querySelectorAll('a[href*="/groups/"]')].map((a) => ({
      href: a.getAttribute("href"),
      text: (a.closest(ROW_SELECTOR) ?? a).innerText,
    }));
    return { status: "ok", items: extractNotificationItems(links), links: links.length };
  }

  globalThis.FLM = Object.assign(globalThis.FLM ?? {}, { extractNotificationItems, parseNotifications });
})();
