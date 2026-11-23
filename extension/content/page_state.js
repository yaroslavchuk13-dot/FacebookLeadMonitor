// Detects pages where monitoring must stop (checkpoint, login form, captcha).
// Classic content script (see post_links.js); exposes FLM.classifyPage and FLM.pageState.
(() => {
  /**
   * Pure classification, unit-tested in Node.
   * info: { path, hasPasswordField, hasCaptcha }
   * Returns "checkpoint" | "login_required" | "ok".
   */
  function classifyPage(info) {
    const path = String(info?.path ?? "").toLowerCase();
    if (path.startsWith("/checkpoint") || path.includes("/checkpoint/") || info?.hasCaptcha) {
      return "checkpoint";
    }
    if (path.startsWith("/login") || path.startsWith("/recover") || info?.hasPasswordField) {
      return "login_required";
    }
    return "ok";
  }

  /** Reads the current page and classifies it. */
  function pageState() {
    return classifyPage({
      path: location.pathname,
      hasPasswordField: Boolean(document.querySelector('input[type="password"], input[name="pass"]')),
      hasCaptcha: Boolean(
        document.querySelector('iframe[src*="captcha"], iframe[src*="recaptcha"], #captcha'),
      ),
    });
  }

  globalThis.FLM = Object.assign(globalThis.FLM ?? {}, { classifyPage, pageState });
})();
