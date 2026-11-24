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
  const SCROLL_STEPS = 6; // read, scroll, read... Facebook renders only posts near the screen
  const MAX_HOVER_PER_POST = 6;
  const SCROLL_PAUSE_MIN_MS = 1200;
  const SCROLL_PAUSE_MAX_MS = 2000;
  // aria-label of comment articles: "Comment by …" / "Коментар від …" / "Комментарий от …"
  const COMMENT_LABEL_RE = /comment|коментар|комментар/i;

  const {
    canonicalPostUrl,
    canonicalProfileUrl,
    cleanText,
    fallbackPostUrl,
    isSeeMoreButton,
    isSeeOriginalButton,
  } = globalThis.FLM.postLinks;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const randomBetween = (min, max) => min + Math.floor(Math.random() * (max - min + 1));

  function groupIdFromLocation() {
    const parts = location.pathname.split("/").filter(Boolean);
    return parts[0] === "groups" && parts[1] ? decodeURIComponent(parts[1]) : null;
  }

  /**
   * The numeric group id: notifications always use it, while a group link may use a name
   * ("/groups/firestoppersuk/"). Facebook embeds it in the page data as "groupID":"123…".
   */
  function numericGroupId(groupId) {
    if (/^\d+$/.test(groupId)) return groupId;
    const html = document.documentElement.innerHTML;
    const embedded = html.match(/"group(?:ID|_id|Id)"\s*:\s*"(\d{6,})"/);
    if (embedded) return embedded[1];
    // Fallback: the most frequent numeric group id among the links of the page.
    const counts = new Map();
    for (const a of document.querySelectorAll('a[href*="/groups/"]')) {
      const id = a.getAttribute("href").match(/\/groups\/(\d{6,})/)?.[1];
      if (id) counts.set(id, (counts.get(id) ?? 0) + 1);
    }
    return [...counts].sort((x, y) => y[1] - x[1])[0]?.[0] ?? null;
  }

  function groupName() {
    const h1 = document.querySelector('[role="main"] h1') ?? document.querySelector("h1");
    return cleanText(h1?.innerText).split("\n")[0] || null;
  }

  /**
   * True if `el` belongs to the post itself, not to a comment.
   * root is either the post's article, or a feed unit whose articles are all comments.
   */
  function isOwn(el, root) {
    const nearest = el.closest(ARTICLE);
    if (root.matches(ARTICLE)) return nearest === root;
    return nearest === null || !root.contains(nearest);
  }

  const own = (root, selector) => [...root.querySelectorAll(selector)].filter((el) => isOwn(el, root));

  const topLevelArticles = (container) =>
    [...container.querySelectorAll(ARTICLE)].filter((a) => !a.parentElement?.closest(ARTICLE));

  const isCommentArticle = (article) => COMMENT_LABEL_RE.test(article.getAttribute("aria-label") ?? "");

  /**
   * Facebook marks comments with role="article"; the post itself may or may not be one.
   * Returns the element that holds the post (its article, or the whole feed unit).
   */
  function postRoot(unit) {
    if (unit.matches(ARTICLE)) return unit;
    const articles = topLevelArticles(unit);
    const withMessage = articles.find((a) => a.querySelector(MESSAGE));
    if (withMessage) return withMessage; // the post is an article
    if (unit.querySelector(MESSAGE)) return unit; // post text outside articles -> articles are comments
    const textOutsideArticles = [...unit.querySelectorAll('[dir="auto"]')].some((el) => !el.closest(ARTICLE));
    if (textOutsideArticles) return unit;
    const candidates = articles.filter((a) => !isCommentArticle(a));
    return candidates.length === 1 ? candidates[0] : unit;
  }

  /** One post per feed unit (direct child of the feed). */
  function postElements(feed) {
    const units = [...feed.children].filter((el) => el.innerText?.trim());
    const articles = topLevelArticles(feed);
    if (units.length <= 1 && articles.length > 1) return articles; // unusual wrapper layout
    return units.map(postRoot);
  }

  function findPostUrl(post, groupId) {
    for (const a of own(post, "a[href]")) {
      const url = canonicalPostUrl(a.getAttribute("href"), groupId);
      if (url) return url;
    }
    return null;
  }

  // Real timestamp texts only (Facebook may scramble the visible text, e.g. "4Sozq"):
  // "4h", "5 days ago", "Yesterday at 10:15", "21 November at 14:00", "Щойно", "Вчера в 10:15",
  // "Monday, 24 November 2026 at 13:40".
  const TIME_HINT_RE = new RegExp(
    [
      "^(?:just now|now|щойно|только что|зараз)$",
      "^\\d{1,2}\\s?(?:s|m|h|d|w|y|secs?|mins?|minutes?|hrs?|hours?|days?|weeks?|wks?|mo|months?|years?|yrs?|" +
        "сек\\w*|хв\\w*|мин\\w*|год\\w*|ч|час\\w*|дн\\w*|д|тиж\\w*|нед\\w*|міс\\w*|мес\\w*)\\.?(?:\\s+(?:ago|тому|назад))?$",
      "^(?:an?|one)\\s+(?:minute|hour|day|week|month|year)s?\\s+ago$",
      "\\b(?:yesterday|today|вчора|вчера|сьогодні|сегодня)\\b",
      "\\b(?:at|о|об|в)\\s+\\d{1,2}[:.]\\d{2}",
      "\\b\\d{1,2}\\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|січ|лют|бер|квіт|трав|черв|лип|серп|верес|жовт|листоп|груд|янв|фев|мар|апр|мая|июн|июл|авг|сен|окт|ноя|дек)",
      "\\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\\w*\\s+\\d{1,2}\\b",
    ].join("|"),
    "i",
  );
  const MAX_TIME_TEXT = 80;
  const TOOLTIP_WAIT_MS = 700;

  /** Text of elements referenced by aria-labelledby (Facebook keeps the full date there). */
  function labelledByText(el) {
    const ids = el.getAttribute("aria-labelledby");
    if (!ids) return "";
    return ids.split(/\s+/).map((id) => document.getElementById(id)?.innerText ?? "").join(" ");
  }

  /** Every place where a timestamp element may keep its text. */
  function timeTextCandidates(el) {
    return [
      el.getAttribute("aria-label"),
      el.getAttribute("title"),
      labelledByText(el),
      el.querySelector("abbr[title]")?.getAttribute("title"),
      el.innerText,
    ]
      .map((t) => cleanText(t).split("\n")[0])
      .filter(Boolean);
  }

  function timeLabel(el) {
    return timeTextCandidates(el).find((t) => t.length <= MAX_TIME_TEXT && TIME_HINT_RE.test(t)) ?? null;
  }

  const postLinkElements = (post, groupId) =>
    own(post, "a[href]").filter((a) => canonicalPostUrl(a.getAttribute("href"), groupId));

  /** Hovers the timestamp and reads the tooltip Facebook shows ("Monday, 24 November 2026 at 13:40"). */
  async function tooltipTime(el) {
    hover(el);
    await sleep(TOOLTIP_WAIT_MS);
    const tip = [...document.querySelectorAll('[role="tooltip"]')]
      .map((t) => cleanText(t.innerText).split("\n")[0])
      .find((t) => t.length <= MAX_TIME_TEXT && TIME_HINT_RE.test(t));
    unhover(el);
    return tip ?? null;
  }

  /** Text of the post's timestamp (parsed into a date by the server), or null. */
  async function findPostedText(post, groupId) {
    // The timestamp is the link that points to the post itself.
    const links = postLinkElements(post, groupId);
    for (const a of links) {
      const text = timeLabel(a);
      if (text) return text;
    }
    // A link-like element with a time-like label (href not revealed yet).
    for (const el of own(post, '[aria-label], a, [role="link"]')) {
      if (canonicalProfileUrl(el.getAttribute("href"))) continue; // author name
      const text = timeLabel(el);
      if (text && !/\b(?:comment|like|share|reply)/i.test(text)) return text;
    }
    // Visible text is scrambled: read the tooltip of the timestamp link.
    for (const a of links.slice(0, 2)) {
      const text = await tooltipTime(a);
      if (text) return text;
    }
    return null;
  }

  /** Links that may become the post link on hover (the timestamp): not author, not hashtag. */
  function hoverCandidates(post) {
    return own(post, 'a, [role="link"]')
      .filter((el) => {
        const href = el.getAttribute("href");
        if (!href || href === "#") return true;
        if (canonicalProfileUrl(href)) return false; // author / mentions: would open hover cards
        return !/\/(hashtag|stories|reel|photo|watch)\b/.test(href);
      })
      .slice(0, MAX_HOVER_PER_POST);
  }

  /**
   * Facebook fills the timestamp link's href only on mouse hover.
   * Simulate hover on candidate links, then read again.
   */
  function hover(el) {
    for (const type of ["pointerover", "pointerenter", "mouseover", "mouseenter"]) {
      el.dispatchEvent(new MouseEvent(type, { bubbles: type.endsWith("over"), view: window }));
    }
    el.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
  }

  function unhover(el) {
    for (const type of ["pointerout", "pointerleave", "mouseout", "mouseleave"]) {
      el.dispatchEvent(new MouseEvent(type, { bubbles: type.endsWith("out"), view: window }));
    }
    el.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  }

  async function revealLazyLinks(posts) {
    const touched = posts.flatMap(hoverCandidates);
    if (!touched.length) return;
    touched.forEach(hover);
    await sleep(HOVER_WAIT_MS);
    touched.forEach(unhover);
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
   * Reads the posts that are rendered right now and adds new ones to `state.found`.
   * Facebook unloads posts far from the screen, so this runs at every scroll step.
   */
  async function collectVisible(feed, groupId, state) {
    const roots = postElements(feed).filter((root) => !state.done.has(root) && findText(root));
    if (!roots.length) return;

    const expanded = await expandPosts(roots);
    state.expanded.originals += expanded.originals;
    state.expanded.seeMore += expanded.seeMore;
    await revealLazyLinks(roots.filter((root) => !findPostUrl(root, groupId)));

    for (const root of roots) {
      const text = findText(root);
      if (!text) continue;
      const author = findAuthor(root);
      const realUrl = findPostUrl(root, groupId);
      // No post link found: keep the post anyway, with a stable group link (dedup by text).
      const postUrl = realUrl ?? fallbackPostUrl(groupId, author.url ?? author.name, text);
      state.done.add(root);
      if (state.found.has(postUrl)) continue;
      state.found.set(postUrl, {
        group_id: groupId,
        group_name: groupName(),
        post_url: postUrl,
        link_found: Boolean(realUrl), // for the popup only; the server ignores it
        posted_text: await findPostedText(root, groupId),
        author_name: author.name,
        author_profile_url: author.url,
        text,
      });
    }
  }

  /**
   * Returns { status, groupId, groupName, posts, expanded }.
   * status: "ok" | "not_group" | "no_feed". Posts match the server's FacebookPost model.
   */
  async function parseFeed(options = {}) {
    const scrollSteps = Number.isInteger(options.scrollSteps) ? options.scrollSteps : SCROLL_STEPS;
    const groupId = groupIdFromLocation();
    if (!groupId) return { status: "not_group", groupId: null, groupName: null, posts: [] };

    const feed = document.querySelector(FEED);
    if (!feed) return { status: "no_feed", groupId, groupName: groupName(), posts: [] };

    const state = { found: new Map(), done: new WeakSet(), expanded: { originals: 0, seeMore: 0 } };
    window.scrollTo({ top: 0 });
    for (let step = 0; step <= scrollSteps; step += 1) {
      await collectVisible(feed, groupId, state);
      if (step === scrollSteps) break;
      // Instant scroll: "smooth" does not move a tab that is not visible (the monitor tab).
      window.scrollBy(0, Math.round(window.innerHeight * 0.85));
      await sleep(randomBetween(SCROLL_PAUSE_MIN_MS, SCROLL_PAUSE_MAX_MS));
    }
    window.scrollTo({ top: 0 });
    // expanded: how many "See original" / "See more" buttons were clicked.
    return {
      status: "ok",
      groupId,
      numericGroupId: numericGroupId(groupId),
      groupName: groupName(),
      posts: [...state.found.values()],
      expanded: state.expanded,
    };
  }

  /**
   * Structure-only report of the current feed, for debugging the parser on real pages.
   * Contains counts and link shapes only — no names, no post text.
   */
  function diagnoseFeed() {
    const groupId = groupIdFromLocation();
    const feed = document.querySelector(FEED);
    const lines = [
      `FLM diagnostics | lang=${document.documentElement.lang} | visible=${document.visibilityState}` +
        ` | scrollY=${Math.round(window.scrollY)} | group=${groupId ? "yes" : "no"} | feed=${feed ? "yes" : "no"}`,
    ];
    if (!feed) return lines.join("\n");

    const units = [...feed.children];
    lines.push(`feed children=${units.length} | articles in feed=${feed.querySelectorAll(ARTICLE).length}` +
      ` | top-level articles=${topLevelArticles(feed).length}`);
    units.slice(0, 30).forEach((unit, i) => {
      const root = postRoot(unit);
      const articles = topLevelArticles(unit);
      const links = own(root, "a[href]").map((a) => a.getAttribute("href"));
      const postLinks = links.filter((h) => canonicalPostUrl(h, groupId)).length;
      const hashLinks = links.filter((h) => h === "#").length;
      // Every link-like element: shape of href, +L if it has aria-label (timestamps usually do).
      const linkShapes = [...new Set(own(root, 'a, [role="link"]').map((el) => {
        const tag = el.tagName === "A" ? "" : `${el.tagName.toLowerCase()}:`;
        const label = el.hasAttribute("aria-label") ? "+L" : "";
        return `${tag}${linkShape(el.getAttribute("href"))}${label}`;
      }))].slice(0, 10).join(" ");
      // Where the timestamp keeps its text: aria-label | title | aria-labelledby | abbr | visible text.
      const timeEl = postLinkElements(root, groupId)[0];
      const timeDiag = timeEl
        ? `${timeEl.hasAttribute("aria-labelledby") ? "labelledby " : ""}` +
          timeTextCandidates(timeEl).map((t) => JSON.stringify(t.slice(0, 40))).join(" | ")
        : "no post link";
      lines.push(
        `#${i} textLen=${(unit.innerText ?? "").trim().length}` +
          ` root=${root === unit ? "unit" : "article"}` +
          ` articles=${unit.querySelectorAll(ARTICLE).length}/top=${articles.length}/comments=${articles.filter(isCommentArticle).length}` +
          ` msg=${unit.querySelectorAll(MESSAGE).length}/own=${own(root, MESSAGE).length}` +
          ` posinset=${unit.querySelector("[aria-posinset]") ? "y" : "n"}` +
          ` postLinks=${postLinks} hash=${hashLinks} ownText=${findText(root).length}` +
          ` author=${findAuthor(root).url ? "link" : findAuthor(root).name ? "name" : "none"}` +
          ` links=[${linkShapes}]` +
          ` time=[${timeDiag}]`,
      );
    });
    return lines.join("\n");
  }

  /** "/groups/123/posts/456/?x" -> "/groups/N/posts/N/" (ids hidden, shape kept). */
  function linkShape(href) {
    if (href === null) return "(no-href)";
    if (!href || href === "#") return "#";
    if (canonicalProfileUrl(href) && !href.includes("/groups/")) return "/<profile>"; // hide user names
    try {
      const url = new URL(href, location.origin);
      const path = url.pathname.replace(/\d+/g, "N").replace(/\/pfbid\w+/g, "/pfbid");
      const parts = path.split("/").filter(Boolean);
      const shape = parts.length === 1 && !parts[0].includes(".") ? "/<name>" : path;
      const params = [...url.searchParams.keys()].filter((k) => !k.startsWith("__")).join(",");
      return params ? `${shape}?${params}` : shape;
    } catch {
      return "?";
    }
  }

  globalThis.FLM = Object.assign(globalThis.FLM ?? {}, { parseFeed, diagnoseFeed });
})();
