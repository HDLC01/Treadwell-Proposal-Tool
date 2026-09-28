// The proposal's own typeface for the Proposal Review editor, loaded from behind the login.
/*
 * Hanz, 2026-09-26: "why are the fonts and font sizes still not fixed?" The page's CSS (.tw-page in
 * styles.css) and every run of the .docx name "Zetta Serif Book", but nothing ever LOADED it: there
 * was no @font-face anywhere, so on any machine without the font installed the editor drew Georgia
 * while the PDF (LibreOffice in the container, font mounted from the host) printed Zetta Serif.
 * Georgia is wider, so the editor also wrapped, shrank and clipped boxes the PDF does not.
 *
 * LICENSED, SO THE APP SERVES IT ONLY BEHIND THE LOGIN, and neither git nor the image carries it:
 * the server mounts it (backend/proposal_fonts.py, whose docstring also says what that leaves open).
 * The files come from /api/proposal-font/<name>, which the same auth middleware as every staff
 * /api route gates (backend/proposal_fonts.py). They are
 * fetched here with the staff bearer token and handed to the FontFace API as BYTES:
 *   * a CSS url() font load cannot carry the Authorization header, so it would 401;
 *   * a blob: URL would be refused by nginx's CSP, which says `font-src 'self'`;
 *   * a FontFace built from an ArrayBuffer makes no fetch of its own, so font-src never applies.
 * The one request this file makes is a same-origin fetch, which `connect-src 'self'` allows.
 *
 * FAMILY NAMES AND DESCRIPTORS ARE THE FILES' OWN, read out of their `name` and `OS/2` tables:
 *   Zetta Serif-Book.otf   family (nameID 1, Windows) "Zetta Serif Book", usWeightClass 345, upright
 *   Zetta Serif.otf        family (nameID 1, Windows) "Zetta Serif",      usWeightClass 400, upright
 * "Zetta Serif Book" is the name the .docx runs carry and what LibreOffice's fontconfig matches.
 * Neither file has a bold or an italic face: LibreOffice synthesises the bold lead-ins, and so does
 * the browser (font-synthesis defaults to weight and style) as long as the face is registered as
 * what it really is. Registering it as bold would switch the synthesis off and print lead-ins in
 * the regular weight. test_proposal_fonts.py reads both tables out of the binaries and checks this.
 *
 * WHEN IT IS IN, the page re-measures: proposal-review.js registers its refit with whenLoaded(),
 * which runs it ONCE, after both faces have been added (or after the one that could be).
 *
 * FAILURE IS SILENT TO THE USER. Offline, a 401 from a lapsed session, bytes the browser refuses:
 * the page keeps the CSS fallback exactly as it drew before this file existed, the refit never
 * runs, and the console gets ONE warning.
 */
(function (root) {
  "use strict";

  // Bump when a font file on the server changes. The responses are cached for a year
  // (Cache-Control: private, immutable), so this query string is the only thing that moves a
  // browser off the old bytes. test_proposal_fonts.py pins the files' hashes against it.
  const VERSION = "1";

  const FACES = [
    { name: "zetta-serif-book", family: "Zetta Serif Book",
      descriptors: { style: "normal", weight: "345" } },
    { name: "zetta-serif", family: "Zetta Serif",
      descriptors: { style: "normal", weight: "400" } },
  ];

  let phase = "idle";          // idle -> loading -> loaded | failed
  let loading = null;          // the one load, shared by every caller
  const waiting = [];

  function warn(msg) {
    try { root.console.warn("[proposal font] " + msg + " The editor is using its fallback serif."); }
    catch (_) { /* no console: nothing to say it to */ }
  }

  function reason(err) {
    return err && err.message ? err.message : String(err);
  }

  function apiBase() {
    try {
      if (root.TW && typeof root.TW.resolveApiBase === "function") return root.TW.resolveApiBase() || "";
    } catch (_) { /* fall through to same-origin */ }
    return "";
  }

  function token() {
    try {
      return root.TWAuth && typeof root.TWAuth.token === "function" ? root.TWAuth.token() : null;
    } catch (_) { return null; }
  }

  // Called as methods of `root` (root.fetch, root.document.fonts.add), never detached: a detached
  // window.fetch throws "Illegal invocation" in Chromium.
  async function loadFace(face, tok) {
    const res = await root.fetch(apiBase() + "/api/proposal-font/" + face.name + "?v=" + VERSION,
                                 { headers: { Authorization: "Bearer " + tok },
                                   credentials: "same-origin" });
    if (!res || !res.ok) throw new Error("HTTP " + (res ? res.status : "no response"));
    const ff = new root.FontFace(face.family, await res.arrayBuffer(),
                                 Object.assign({}, face.descriptors));
    await ff.load();
    root.document.fonts.add(ff);
  }

  async function loadAll() {
    // tokenReady, not ready: this only wants to START FETCHING, and the token exists a whole /api/me
    // round trip before `ready` settles (see auth.js). Neither settles without a signed-in
    // @wetreadwell.com session, and then there is nothing to fetch with anyway.
    const auth = root.TWAuth;
    const gate = auth && (auth.tokenReady || auth.ready);
    if (gate && typeof gate.then === "function") await gate;
    if (typeof root.FontFace !== "function" || !root.document || !root.document.fonts
        || typeof root.fetch !== "function") {
      throw new Error("This browser cannot register a font from bytes.");
    }
    const tok = token();
    if (!tok) throw new Error("No sign-in token.");
    const failed = (await Promise.all(FACES.map(face =>
      loadFace(face, tok).then(() => null, err => face.family + " (" + reason(err) + ")"))))
      .filter(Boolean);
    if (failed.length) warn("Not loaded: " + failed.join(", ") + ".");
    return failed.length < FACES.length;
  }

  function run(fn) {
    try { fn(); } catch (err) {
      try { root.console.error("[proposal font] refit after the font loaded failed:", err); } catch (_) {}
    }
  }

  /** Start the load (once). Resolves true when at least one face is in document.fonts. */
  function start() {
    if (!loading) {
      phase = "loading";
      loading = loadAll().catch(err => { warn(reason(err)); return false; }).then(ok => {
        phase = ok ? "loaded" : "failed";
        const due = waiting.splice(0);
        if (ok) due.forEach(run);
        return ok;
      });
    }
    return loading;
  }

  /** Run `fn` once, after the faces are registered. Never runs it if the load failed. Starts the
   *  load if nothing has yet. */
  function whenLoaded(fn) {
    if (typeof fn === "function") {
      if (phase === "loaded") Promise.resolve().then(() => run(fn));
      else if (phase !== "failed") waiting.push(fn);
    }
    return start();
  }

  root.TWProposalFonts = { VERSION: VERSION, FACES: FACES, start: start, whenLoaded: whenLoaded };
})(typeof window !== "undefined" ? window : this);
