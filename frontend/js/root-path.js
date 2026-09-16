/**
 * Make the bare domain look like /portal.html to everything that reads the URL.
 *
 * WHY THIS FILE EXISTS. `main.py:_root` serves portal.html's own bytes at "/" instead of
 * answering 307 -> /portal.html. The redirect was a whole round trip before the first byte of
 * the page moved, on the request every member of staff makes to open this app, and it could
 * never be amortised: a 307 carries no Cache-Control, so browsers re-fetch it every time.
 *
 * Serving at the root costs exactly one thing, and this is it. After a 307 the browser's
 * `location.pathname` was "/portal.html". Served at "/" it is "/", and auth.js reads that
 * string three times:
 *
 *   * `const path = location.pathname.toLowerCase()` at the top of its IIFE,
 *   * `DENIED_PAGES[path] || DENIED_PAGES[location.pathname]`, the per-role page refusal,
 *   * `location.pathname.toLowerCase().endsWith(href.toLowerCase())` in navItem(), which is
 *     what highlights the row you are standing on in the sidebar.
 *
 * The third is the dangerous one, because it fails SILENTLY: "/" does not end with
 * "/portal.html", so the Active Projects row would simply stop lighting up. No error, no blank
 * page, nothing to investigate — the kind of regression that ships and lives for months.
 *
 * Rewriting the address bar here means all three see the string they saw before.
 *
 * THE QUERY STRING IS DROPPED ON PURPOSE, and that is not tidiness. A 307 to "/portal.html"
 * carried no query either, and shared.js adopts a `?d=<uuid>` it finds in the URL — so
 * preserving one would take "/?d=…", the link the old intake form left in browser history, and
 * reopen that draft under whatever the estimator did next. The hash is kept, because a 307
 * keeps the fragment.
 *
 * A SEPARATE FILE, NOT AN INLINE <script>, because the CSP this app is served under forbids
 * inline script — and a CSP violation is not a build error, it is a tag the browser silently
 * declines to run. backend/tests/test_frontend_js_parses.py enforces that rule, and caught this
 * exact tag when it was written inline.
 *
 * LOADED ONLY BY portal.html, and this is why it cannot live in auth.js despite auth.js owning
 * HOME_PAGE and being loaded everywhere: "/?new=1" and "/?edit=1" serve the INTAKE form, also
 * at pathname "/". A guard that fired for every page would relabel the intake screen as the
 * board — breaking its own sidebar state and putting a URL in the address bar that is not the
 * page you are looking at. Which page is being served at the root is knowledge the page has and
 * auth.js does not.
 *
 * It must execute BEFORE auth.js, which captures the pathname into a const the moment it runs.
 * portal.html loads this first in its script block for that reason.
 */
(function () {
  if (location.pathname === "/") {
    history.replaceState(null, "", "/portal.html" + location.hash);
  }
})();
