/**
 * Runs frontend/js/root-path.js — the guard that rewrites the address bar when the bare domain
 * serves portal.html's bytes — against a stubbed `location` and `history`, and reports where
 * each starting URL ends up.
 *
 * EXECUTED, NOT GREPPED, for the reason test_board_renders.js exists: the claim being made is
 * that "every location.pathname consumer sees exactly what it saw when a 307 got you here",
 * and a regex over the file cannot tell you whether the expression inside it produces
 * "/portal.html". A typo, a dropped concatenation, or a guard that fires on the wrong path all
 * read fine as source.
 *
 * Deliberately not jsdom: the point is that this script touches nothing but `location` and
 * `history`, so anything else it reaches for should be a ReferenceError here.
 *
 * argv[2] = path to frontend/js/root-path.js
 * argv[3] = path to frontend/portal.html   (for the load-order report only)
 * stdout  = one line of JSON: { loadOrder, cases: [{ from, pathname, search, hash, replaced }] }
 */
const fs = require("fs");
const vm = require("vm");

const script = fs.readFileSync(process.argv[2], "utf8");

// The order the page's scripts EXECUTE in. Classic <script src> tags run in document order, so
// this list is what decides whether the guard has already rewritten the pathname by the time
// auth.js reads it. Comments are stripped first: this file's own comment names /auth.js, and a
// comment must not be able to masquerade as a tag.
const html = fs.readFileSync(process.argv[3], "utf8").replace(/<!--[\s\S]*?-->/g, "");
const loadOrder = [...html.matchAll(/<script[^>]*\bsrc="([^"]+)"/gi)].map((m) => m[1]);

function run(from) {
  const u = new URL("https://proposals.wetreadwell.com" + from);
  const loc = {
    pathname: u.pathname,
    search: u.search,
    hash: u.hash,
    origin: u.origin,
    href: u.href,
  };
  const calls = [];
  const sandbox = {
    location: loc,
    history: {
      replaceState(state, title, url) {
        calls.push(url);
        // Apply it the way a browser would, so `pathname` afterwards is what auth.js reads.
        const next = new URL(url, loc.origin);
        loc.pathname = next.pathname;
        loc.search = next.search;
        loc.hash = next.hash;
        loc.href = next.href;
      },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox, { timeout: 2000 });
  return {
    from,
    pathname: loc.pathname,
    search: loc.search,
    hash: loc.hash,
    replaced: calls,
    // auth.js:221 decides which sidebar row is highlighted with exactly this expression.
    // Reported per case so the Python side can assert the consequence rather than restate
    // the rule: "/" does NOT end with "/portal.html", which is the bug the guard prevents.
    sidebarActive: loc.pathname.toLowerCase().endsWith("/portal.html"),
    // …and this is the same expression against the pathname the server now hands over, i.e.
    // what auth.js would have read if the guard were not there.
    sidebarActiveWithoutGuard: new URL("https://x" + from).pathname.toLowerCase()
      .endsWith("/portal.html"),
  };
}

const cases = [
  "/",                       // the bare domain — the whole reason this exists
  "/?utm_source=email",      // a shared link's query, which the 307 also dropped
  "/?d=00000000-0000-0000-0000-000000000000",  // an old draft link in history
  "/#drawer",                // a fragment, which a 307 DOES carry over
  "/portal.html",            // arriving the ordinary way: must be a no-op
  "/portal.html?open=abc",   // portal.js reads ?open — it must survive
  "/projects.html",          // any other page: must be untouched
];

console.log(JSON.stringify({ loadOrder, cases: cases.map(run) }));
