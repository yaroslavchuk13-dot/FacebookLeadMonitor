// Requests to the local Python server (http://127.0.0.1:<port>).

const TIMEOUT_MS = 10000;
const MAX_POSTS_PER_REQUEST = 100; // must match the server limit

async function post(settings, path, body) {
  const response = await fetch(`http://127.0.0.1:${settings.port}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Extension-Token": settings.token },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (response.status === 401) throw new Error("невірний токен");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

/** Sends all posts in chunks. Throws if the server is unreachable or rejects the token. */
export async function sendPosts(settings, posts) {
  let accepted = 0;
  for (let i = 0; i < posts.length; i += MAX_POSTS_PER_REQUEST) {
    const result = await post(settings, "/api/posts", { posts: posts.slice(i, i + MAX_POSTS_PER_REQUEST) });
    accepted += result.accepted;
  }
  return accepted;
}

/**
 * Asks the server what to do: paused (/pause in Telegram) and the next author profile
 * to check ({ id, profile_url } or null). Unreachable server -> not paused, no profile.
 */
export async function getControl(settings) {
  const none = { paused: false, profileCheck: null };
  try {
    const response = await fetch(`http://127.0.0.1:${settings.port}/api/control`, {
      headers: { "X-Extension-Token": settings.token },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) return none;
    const data = await response.json();
    const check = data.profile_check;
    const valid = check && Number.isInteger(check.id) && /^https:\/\/www\.facebook\.com\//.test(check.profile_url);
    return { paused: Boolean(data.paused), profileCheck: valid ? check : null };
  } catch {
    return none;
  }
}

/** Sends the profile check result (numbers/flags only). Best effort. */
export async function sendProfileResult(settings, checkId, profile) {
  try {
    await post(settings, "/api/profile_result", { check_id: checkId, profile });
    return true;
  } catch {
    return false;
  }
}

/** Best effort: an alert must never break the monitor loop. */
export async function sendAlert(settings, alert) {
  try {
    await post(settings, "/api/alert", alert);
    return true;
  } catch {
    return false;
  }
}
