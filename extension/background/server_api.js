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

/** Best effort: an alert must never break the monitor loop. */
export async function sendAlert(settings, alert) {
  try {
    await post(settings, "/api/alert", alert);
    return true;
  } catch {
    return false;
  }
}
