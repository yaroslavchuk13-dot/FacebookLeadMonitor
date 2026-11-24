// Reads an author's profile page and returns numbers/flags only (no names, no text, no photos).
// Classic content script; exposes FLM.extractProfileSignals (pure, unit-tested) and FLM.parseProfile.
(() => {
  const UNAVAILABLE_RE =
    /this content isn't available|this page isn't available|content isn.t available right now|цей вміст (?:зараз )?недоступний|ця сторінка недоступна|этот контент сейчас недоступен|страница недоступна/i;
  const LOCKED_RE =
    /locked (?:his|her|their) profile|profile is locked|заблокував(?:ла)? свій профіль|закрив(?:ла)? свій профіль|закрыл(?:а)? свой профиль/i;
  const PAGE_RE = /(?:^|\n)\s*(?:Page|Сторінка|Страница)\s*·/i;
  // "350 friends" (not "12 mutual friends": a word between number and "friends" does not match)
  const FRIENDS_RE = /(\d[\d,.]*\s?[KkКк]?)\s*(?:friends|друз(?:ів|і|я|ей))(?![\w])/i;
  const FOLLOWERS_RE = /(\d[\d,.]*\s?[KkКкMм]?)\s*(?:followers|підписник\w*|подписчик\w*)/i;
  const JOINED_RE =
    /(?:joined facebook in|joined|member since|приєднал\w* до facebook|на facebook з|присоединил\w* к facebook)[^\d\n]{0,20}((?:19|20)\d{2})/i;
  // The profile info block: "Intro" (old layout) or "Personal details" / "Education" / "Work" (new).
  const INTRO_HEADING_RE =
    /(?:^|\n)\s*(?:Intro|Personal details|Education|Work|Інформація|Коротко|Особисті дані|Особисті відомості|Освіта|Робота|Информация|Личные данные|Образование|Работа)\s*(?:\n|$)/i;
  const INTRO_LINE_RE =
    /^(?:lives in|from|works at|worked at|studied at|studies at|went to|goes to|married|in a relationship|single|engaged|живе в|з міста|родом з|працює|працював|навча\w*|живет в|из города|работает|работал|учил\w*|учится)\b/i;
  // "Education" lists schools as plain lines: count the line right after the heading as an item.
  const EDUCATION_HEADING_RE = /^(?:Education|Освіта|Образование)$/i;

  /** "1.2K" -> 1200, "1,234" -> 1234, "350" -> 350. */
  function parseCount(raw) {
    const text = String(raw).trim().toLowerCase().replace(/\s/g, "");
    const multiplier = /[kк]$/.test(text) ? 1000 : /[mм]$/.test(text) ? 1000000 : 1;
    const number = text.replace(/[kкmм]$/, "");
    const value = multiplier === 1 ? Number(number.replace(/[,.]/g, "")) : Number(number.replace(",", "."));
    return Number.isFinite(value) ? Math.round(value * multiplier) : null;
  }

  /** avatarHref: URL of the main profile picture, if found. */
  function hasRealPhoto(avatarHref) {
    if (!avatarHref) return null;
    if (/rsrc\.php|\/static\.|default|silhouette/i.test(avatarHref)) return false;
    if (/scontent|fbcdn\.net\/v\//i.test(avatarHref)) return true;
    return null;
  }

  function extractProfileSignals(text, avatarHref) {
    const body = String(text ?? "");
    if (!body.trim() || UNAVAILABLE_RE.test(body)) return { status: "unavailable" };

    const friends = body.match(FRIENDS_RE);
    const followers = body.match(FOLLOWERS_RE);
    const joined = body.match(JOINED_RE);
    let introItems = null;
    if (INTRO_HEADING_RE.test(body)) {
      const lines = body.split("\n").map((line) => line.trim()).filter(Boolean);
      introItems = lines.filter((line) => INTRO_LINE_RE.test(line)).length;
      const educationAt = lines.findIndex((line) => EDUCATION_HEADING_RE.test(line));
      if (educationAt >= 0 && lines[educationAt + 1] && !INTRO_LINE_RE.test(lines[educationAt + 1])) {
        introItems += 1; // a school listed under "Education"
      }
    }
    return {
      status: "ok",
      has_photo: hasRealPhoto(avatarHref),
      friends: friends ? parseCount(friends[1]) : null,
      followers: followers ? parseCount(followers[1]) : null,
      joined_year: joined ? Number(joined[1]) : null,
      intro_items: introItems,
      is_locked: LOCKED_RE.test(body),
      is_page: PAGE_RE.test(body),
    };
  }

  /** The main profile picture: the first <image> inside an <svg> in the page header. */
  function findAvatarHref(main) {
    const labelled = main.querySelector('[aria-label*="profile picture" i] image, [aria-label*="фото профілю" i] image');
    const image = labelled ?? main.querySelector("svg image");
    return image?.getAttribute("xlink:href") ?? image?.getAttribute("href") ?? null;
  }

  function parseProfile() {
    const main = document.querySelector('[role="main"]') ?? document.body;
    return extractProfileSignals(main.innerText, findAvatarHref(main));
  }

  globalThis.FLM = Object.assign(globalThis.FLM ?? {}, { extractProfileSignals, parseProfile });
})();
