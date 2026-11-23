// Parses posts from an open Facebook group page. Classic script (see post_links.js),
// injected together with post_links.js; exposes globalThis.FLM.parseFeed().
(() => {
  const ARTICLE = '[role="article"]';
  const FEED = '[role="feed"]';
  const MESSAGE = '[data-ad-preview="message"], [data-ad-comet-preview="message"]';
  const AUTHOR_LINKS = "h2 a[href], h3 a[href], h4 a[href], strong a[href]";
  const AUTHOR_HEADINGS = "h2, h3, h4, strong";
  const NOT_TEXT = '[role="button"], a, h2, h3, h4, strong';
  const MAX_TEXT_LENGTH = 10000;
  const HOVER_WAIT_MS = 400;
  const MAX_CLICKS_PER_PASS = 15;
  const CLICK_PAUSE_MIN_MS = 250; // human-like pause between button clicks
  const CLICK_PAUSE_MAX_MS = 600;
  const AFTER_CLICKS_WAIT_MS = 800; // let Facebook re-render the expanded text
  const SCROLL_SCREENS = 2; // Facebook loads more posts only while the page is scrolled
  const SCROLL_PAUSE_MIN_MS = 1200;
  const SCROLL_PAUSE_MAX_MS = 2000;

  const { canonicalPostUrl, canonicalProfileUrl, cleanText, isSeeMoreButton, isSeeOriginalButton } =
    globalThis.FLM.postLinks;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const randomBetween = (min, max) => min + Math.floor(Math.random() * (max - min + 1));

  function groupIdFromLocation() {
    const parts = location.pathname.split("/").filter(Boolean);
    return parts[0] === "groups" && parts[1] ? decodeURIComponent(parts[1]) : null;
  }

  function groupName() {
    const h1 = document.querySelector('[role="main"] h1') ?? document.querySelector("h1");
    return cleanText(h1?.innerText).split("\n")[0] || null;
  }

  /** True if `el` belongs to `root` itself, not to a nested article (a comment). */
  function isOwn(el, root) {
    const nearest = el.closest(ARTICLE);
    return nearest === null || nearest === root;
  }

  const own = (root, selector) => [...root.querySelectorAll(selector)].filter((el) => isOwn(el, root));

  /** Posts are top-level articles; comments are articles nested inside them. */
  function postElements(feed) {
    const articles = [...feed.querySelectorAll(ARTICLE)].filter(
      (a) => !a.parentElement?.closest(ARTICLE),
    );
    if (articles.length) return articles;
    // Fallback for layouts without role="article".
    return [...feed.children].filter((el) => el.innerText?.trim());
  }

  function findPostUrl(post, groupId) {
    for (const a of own(post, "a[href]")) {
      const url = canonicalPostUrl(a.getAttribute("href"), groupId);
      if (url) return url;
    }
    return null;
  }

  /**
   * Facebook often fills the timestamp link's href only on mouse hover.
   * Simulate hover on links without a real href, then read again.
   */
  async function revealLazyLinks(posts) {
    const touched = [];
    for (const post of posts) {
      for (const a of own(post, 'a[href="#"], a:not([href])').slice(0, 5)) {
        a.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
        a.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
        touched.push(a);
      }
    }
    if (!touched.length) return;
    await sleep(HOVER_WAIT_MS);
    for (const a of touched) a.dispatchEvent(new MouseEvent("mouseout", { bubbles: true }));
  }

  function findAuthor(post) {
    for (const a of own(post, AUTHOR_LINKS)) {
      const url = canonicalProfileUrl(a.getAttribute("href"));
      const name = cleanText(a.innerText).split("\n")[0];
      if (url && name) return { name, url };
    }
    // Anonymous post: a name in the header, but no profile link.
    const heading = own(post, AUTHOR_HEADINGS)[0];
    const name = cleanText(heading?.innerText).split("\n")[0];
    return { name: name || null, url: null };
  }

  function findText(post) {
    let blocks = own(post, MESSAGE);
    if (!blocks.length) {
      // Fallback: innermost dir="auto" blocks that are not buttons, links or headers.
      blocks = own(post, '[dir="auto"]').filter(
        (el) => !el.querySelector('[dir="auto"]') && !el.closest(NOT_TEXT),
      );
    }
    const parts = [...new Set(blocks.map((el) => cleanText(el.innerText)).filter(Boolean))];
    return cleanText(parts.join("\n")).slice(0, MAX_TEXT_LENGTH);
  }

  /** Scrolls down a couple of screens so Facebook loads more posts, then back to the top. */
  async function loadMorePosts() {
    for (let i = 0; i < SCROLL_SCREENS; i += 1) {
      window.scrollBy({ top: window.innerHeight * 0.9, behavior: "smooth" });
      await sleep(randomBetween(SCROLL_PAUSE_MIN_MS, SCROLL_PAUSE_MAX_MS));
    }
    window.scrollTo({ top: 0 });
  }

  /**
   * Clicks the buttons accepted by `isTarget` inside posts (not in comments).
   * Returns how many were clicked.
   */
  async function clickButtons(posts, isTarget) {
    const buttons = posts
      .flatMap((post) => own(post, '[role="button"]'))
      .filter((b) => isTarget(b.innerText))
      .slice(0, MAX_CLICKS_PER_PASS);
    for (const button of buttons) {
      button.click();
      await sleep(randomBetween(CLICK_PAUSE_MIN_MS, CLICK_PAUSE_MAX_MS));
    }
    if (buttons.length) await sleep(AFTER_CLICKS_WAIT_MS);
    return buttons.length;
  }

  /**
   * Shows the author's original text instead of Facebook's auto-translation,
   * then expands truncated posts ("See more" / "Ещё").
   */
  async function expandPosts(posts) {
    const originals = await clickButtons(posts, isSeeOriginalButton);
    const seeMore = await clickButtons(posts, isSeeMoreButton);
    return { originals, seeMore };
  }

  /**
   * Returns { status, groupId, groupName, posts, skipped }.
   * status: "ok" | "not_group" | "no_feed". Posts match the server's FacebookPost model.
   */
  async function parseFeed() {
    const groupId = groupIdFromLocation();
    if (!groupId) return { status: "not_group", groupId: null, groupName: null, posts: [], skipped: 0 };

    const feed = document.querySelector(FEED);
    if (!feed) return { status: "no_feed", groupId, groupName: groupName(), posts: [], skipped: 0 };

    await loadMorePosts();
    const elements = postElements(feed);
    const expanded = await expandPosts(elements);
    const missingUrl = elements.filter((el) => !findPostUrl(el, groupId));
    await revealLazyLinks(missingUrl);

    const posts = [];
    const seen = new Set();
    let skipped = 0; // ads, loading placeholders, photo-only posts, repeats
    for (const el of elements) {
      const postUrl = findPostUrl(el, groupId);
      const text = findText(el);
      if (!postUrl || !text || seen.has(postUrl)) {
        skipped += 1;
        continue;
      }
      seen.add(postUrl);
      const author = findAuthor(el);
      posts.push({
        group_id: groupId,
        group_name: groupName(),
        post_url: postUrl,
        author_name: author.name,
        author_profile_url: author.url,
        text,
      });
    }
    // expanded: how many "See original" / "See more" buttons were clicked.
    return { status: "ok", groupId, groupName: groupName(), posts, skipped, expanded };
  }

  globalThis.FLM = Object.assign(globalThis.FLM ?? {}, { parseFeed });
})();
