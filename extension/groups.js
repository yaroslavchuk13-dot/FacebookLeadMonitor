// Parsing of Facebook group links entered by the user. Pure functions, no chrome.* API.

const FACEBOOK_HOSTS = new Set([
  "facebook.com",
  "www.facebook.com",
  "m.facebook.com",
  "web.facebook.com",
]);
const GROUP_ID_RE = /^[A-Za-z0-9._-]+$/;

/**
 * Extracts the group id (numeric id or slug) from a group link.
 * Returns null if the text is not a Facebook group link.
 *   "https://www.facebook.com/groups/123/?ref=share" -> "123"
 *   "facebook.com/groups/kyiv.plumbers/posts/9"     -> "kyiv.plumbers"
 */
export function parseGroupId(text) {
  let raw = String(text ?? "").trim();
  if (!raw) return null;
  if (!/^https?:\/\//i.test(raw)) raw = "https://" + raw;

  let url;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (!FACEBOOK_HOSTS.has(url.hostname.toLowerCase())) return null;

  const parts = url.pathname.split("/").filter(Boolean);
  if (parts.length < 2 || parts[0].toLowerCase() !== "groups") return null;
  const id = decodeURIComponent(parts[1]);
  return GROUP_ID_RE.test(id) ? id : null;
}

/** Canonical group URL with the newest posts first. */
export function groupFeedUrl(groupId) {
  return `https://www.facebook.com/groups/${encodeURIComponent(groupId)}/?sorting_setting=CHRONOLOGICAL`;
}

/**
 * Parses a multi-line text (one link per line).
 * Returns { groupIds: unique ids in input order, invalidLines: lines that are not group links }.
 */
export function parseGroupList(text) {
  const groupIds = [];
  const invalidLines = [];
  for (const line of String(text ?? "").split(/\r?\n/)) {
    if (!line.trim()) continue;
    const id = parseGroupId(line);
    if (id === null) invalidLines.push(line.trim());
    else if (!groupIds.includes(id)) groupIds.push(id);
  }
  return { groupIds, invalidLines };
}
