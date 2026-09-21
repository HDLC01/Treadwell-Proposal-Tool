"use strict";
/* EXECUTE the tab memory — the module, and each page's own opening-tab decision.
 *
 * WHY EXECUTED, NOT GREPPED. "The page remembers its tab" is a claim about behaviour with two
 * halves, and a source assertion can see neither: that a control WRITES the fragment, and that a
 * reload READS it back and lands on the same pane. A regex over markup cannot tell a wired control
 * from a dead one — that is exactly how a dead button shipped green in this repo — and it certainly
 * cannot tell you that a remembered tab which no longer exists falls back instead of painting an
 * empty pane. So every decision below is the shipped function, lifted by name out of the shipped
 * file and run against a fake window whose `location.hash` a scenario sets.
 *
 * REAL: frontend/js/tab-memo.js, required rather than stubbed. The pages call `pick`, `read` and
 * `write` for their answers, so a module that disagreed with the pages here would agree with
 * nothing in production.
 *
 * WHAT IS OUT OF REACH. The `<script src="/js/tab-memo.js">` tag. Nothing executed here can see a
 * missing script tag — the pages guard on `typeof window !== "undefined" && window.TWTabMemo` and
 * degrade to exactly the behaviour they had before, silently — so the tags are asserted from the
 * markup in test_tabs_survive_a_reload.py instead. That split is deliberate and it is the same one
 * library.js already takes for its own <script> ordering.
 *
 * Usage: node tab-memo-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
// Line endings normalised on read: git hands these files out with CRLF on a Windows checkout and
// LF in CI, and the anchors below are multiline. library-ui-harness.js records what the split
// costs a source-matching harness — CI green, a developer's machine red, on the same commit.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const M = require(path.join(ROOT, "js", "tab-memo.js"));

/** One `function name(...) { ... }`, braces balanced, at any indentation. */
function lift(src, name, whose) {
  const m = new RegExp("(^|\\n)[ \\t]*(?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) {
    throw new Error(name + "() is gone from " + whose + " — rewrite this harness, don't stub it");
  }
  const start = m.index + (m[1] ? m[1].length : 0);
  const open = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(start, i + 1);
  }
  throw new Error("unbalanced braces reading " + name + " out of " + whose);
}

/** One `var NAME = ...;` / `let NAME = ...;` declaration, as shipped. Lifted rather than retyped:
 *  a harness that restated the default would pass just as happily against a page that shipped a
 *  different one, which is the whole thing these scenarios are about. */
function decl(src, kw, name, whose) {
  const re = new RegExp("(^|\\n)[ \\t]*" + kw + " " + name + " = [^\\n]*;", "m");
  const m = re.exec(src);
  if (!m) throw new Error(kw + " " + name + " is gone from " + whose + " — rewrite this harness");
  return m[0];
}

/** A window whose address bar a scenario can read back. `replaceState` updates it the way a
 *  browser does, so "the write is a no-op when nothing changed" is answerable here. */
function makeWin(hash, opts) {
  opts = opts || {};
  const win = {
    writes: 0,
    location: { pathname: opts.pathname || "/page.html", search: opts.search || "",
                hash: hash || "" },
    history: {
      replaceState(_a, _b, url) {
        win.writes += 1;
        if (opts.throwOnWrite) throw new Error("SecurityError: sandboxed");
        const u = String(url);
        const h = u.indexOf("#");
        win.location.hash = h < 0 ? "" : u.slice(h);
        const rest = h < 0 ? u : u.slice(0, h);
        const q = rest.indexOf("?");
        win.location.search = q < 0 ? "" : rest.slice(q);
        win.location.pathname = q < 0 ? rest : rest.slice(0, q);
      },
    },
  };
  win.TWTabMemo = opts.noModule ? undefined : M;
  return win;
}

/** The smallest DOM these renderers touch: getElementById, one `hidden` flag and one attribute
 *  bag per id. Unknown ids answer null, so a function reaching for an element the page does not
 *  declare throws here instead of writing to nothing in production. */
function makeDoc(ids) {
  const els = {};
  ids.forEach((id) => {
    els[id] = { id, hidden: false, attrs: {},
                setAttribute(k, v) { this.attrs[k] = String(v); },
                getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k)
                  ? this.attrs[k] : null; } };
  });
  return { els, getElementById: (id) => els[id] || null };
}

/** A synthetic click target whose `closest` answers one attribute selector and nothing else --
 *  enough to drive a delegated listener's `e.target.closest("[data-foo]")` dispatch without a
 *  real DOM. Every OTHER selector answers null, so a listener with several `t.closest(...)`
 *  guards ahead of the one under test falls through every one of them undisturbed. */
function fakeTarget(attr, value) {
  return {
    closest(sel) {
      return sel === "[" + attr + "]"
        ? { getAttribute: (k) => (k === attr ? value : null) }
        : null;
    },
  };
}

/** One `<ownerExpr>.addEventListener("<event>", function (...) { ... })` callback, braces
 *  balanced, wrapped into a standalone function expression so it can be CALLED -- the shipped
 *  listener itself, not a description of it. Mirrors `lift()` above, for a listener that has no
 *  name of its own to search for.
 *
 *  Scans past any occurrence of the needle that is not actually followed by a function
 *  expression -- library.js also mentions this exact call in a comment, above the real one. */
function liftListener(src, ownerExpr, event, whose) {
  const needle = ownerExpr + '.addEventListener("' + event + '", ';
  let at = -1;
  let fnStart = -1;
  for (let from = 0; ; ) {
    const found = src.indexOf(needle, from);
    if (found < 0) break;
    const j = found + needle.length;
    const asyncHere = src.slice(j, j + 6) === "async ";
    const k = asyncHere ? j + 6 : j;
    if (src.slice(k, k + 8) === "function") { at = found; fnStart = k; break; }
    from = found + needle.length;
  }
  if (at < 0) {
    throw new Error("the " + event + " listener on " + ownerExpr + " is gone from " + whose +
      " -- rewrite this harness, don't stub it");
  }
  const isAsync = src.slice(at + needle.length, fnStart) === "async ";
  const parenOpen = src.indexOf("(", fnStart);
  const parenClose = src.indexOf(")", parenOpen);
  const params = src.slice(parenOpen + 1, parenClose);
  const braceOpen = src.indexOf("{", parenClose);
  let depth = 0, braceClose = -1;
  for (let j = braceOpen; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) { braceClose = j; break; }
  }
  if (braceClose < 0) {
    throw new Error("unbalanced braces reading the " + event + " listener on " + ownerExpr +
      " in " + whose);
  }
  return (isAsync ? "async " : "") + "function(" + params + ") " +
    src.slice(braceOpen, braceClose + 1);
}

const out = {};

// ── 1. the module itself ─────────────────────────────────────────────────────
{
  out.parse = {
    both: M.parse("#tab=defaults&wt=epoxy"),
    empty: M.parse(""),
    bare: M.parse("#"),
    noEquals: M.parse("#tab"),
    // A hand-typed or truncated escape. One bad pair must not cost the other its value, and it
    // must not throw: decodeURIComponent("%E0%A4%A") is a URIError.
    broken: M.parse("#tab=%E0%A4%A&wt=gyp"),
    encoded: M.parse("#sheet=" + encodeURIComponent("Gyp (GWorx SC190)")),
  };
  out.stringify = {
    two: M.stringify({ tab: "items", wt: "seal" }),
    // Empty means the key is GONE, and an empty object means no fragment at all rather than a
    // bare "#" — which is a scroll target in its own right.
    dropsEmpty: M.stringify({ tab: "items", wt: "" }),
    nothing: M.stringify({}),
    spaces: M.stringify({ sheet: "Epoxy blank" }),
  };
  out.pick = {
    known: M.pick("vendors", ["items", "asm", "vendors"], "asm"),
    // The safety rule: a tab that no longer exists falls back rather than showing an empty pane.
    gone: M.pick("rooms", ["items", "asm", "vendors"], "asm"),
    absent: M.pick("", ["items", "asm"], "asm"),
    noneOnOffer: M.pick("items", [], "asm"),
  };

  // A window whose location THROWS on read — a sandboxed frame. read() must answer "" and write()
  // must answer false, because a tab that switches without being remembered is still a tab that
  // switched.
  const hostile = { get location() { throw new Error("SecurityError"); },
                    history: { replaceState() {} } };
  out.hostile = { read: M.read(hostile, "tab"), write: M.write(hostile, { tab: "items" }) };
  out.throwingWrite = M.write(makeWin("", { throwOnWrite: true }), { tab: "items" });

  // The merge, the no-op and the delete, in one walk.
  const w = makeWin("", { pathname: "/library.html", search: "?d=abc-123" });
  M.write(w, { tab: "defaults" });
  M.write(w, { wt: "gyp" });
  const afterTwo = w.location.hash;
  const writesAfterTwo = w.writes;
  M.write(w, { wt: "gyp" });                       // same value again
  const noopWrites = w.writes - writesAfterTwo;
  M.write(w, { wt: "" });                          // and now drop it
  out.merge = { afterTwo, noopWrites, afterDrop: w.location.hash,
                keptSearch: w.location.search, keptPath: w.location.pathname };
}

// ── 2. Items and Assemblies: four tabs, and five work types inside one of them ─
{
  const src = read(path.join(ROOT, "js", "library.js"));
  const ids = ["tab-items", "tab-asm", "tab-vendors", "tab-defaults",
               "pane-items", "pane-asm", "pane-vendors", "pane-defaults",
               "wt-polish", "wt-seal", "wt-epoxy", "wt-leveling", "wt-gyp"];
  const body = [
    decl(src, "var", "view", "library.js"),
    decl(src, "var", "WORK_TYPES", "library.js"),
    decl(src, "var", "DEFAULT_WT", "library.js"),
    // PANES and TAB_OF sit together; TAB_OF wraps onto a second line, so it is taken whole.
    /(^|\n) {2}var PANES = \[[^\]]*\];/.exec(src)[0],
    /(^|\n) {2}var TAB_OF = \{[\s\S]*?\};/.exec(src)[0],
    lift(src, "showView", "library.js"),
    lift(src, "setWorkType", "library.js"),
    lift(src, "restoreView", "library.js"),
    // The work-type strip's write lives inside document's own delegated click listener
    // (library.js's onClick, around the "[data-work-type]" branch), not inside a named function
    // -- lifted whole so the WIRING is what runs (does a click still call TWTabMemo.write),
    // not a restatement of it.
    "const __onWtClick = " + liftListener(src, "document", "click", "library.js") + ";",
    "return { showView, setWorkType, restoreView, onWtClick: __onWtClick, view: () => view," +
      " wt: () => DEFAULT_WT, PANES, WORK_TYPES };",
  ].join("\n");
  const scope = new Function("window", "document", "$",
    "renderDefaultTakeoff", "renderDefaultLabor", "renderDefaultSearch", body);
  const noop = () => {};
  const run = (hash) => {
    const win = makeWin(hash, { pathname: "/library.html" });
    const doc = makeDoc(ids);
    const api = scope(win, doc, doc.getElementById, noop, noop, noop);
    return { win, doc, api };
  };

  // A fresh open: nothing remembered, so the page's OWN default — and the fragment now says so,
  // which is what makes the URL shareable.
  {
    const { win, doc, api } = run("");
    api.restoreView();
    out.libFresh = { view: api.view(), hash: win.location.hash,
                     selected: api.PANES.filter((p) => doc.els["tab-" + p].attrs["aria-selected"] === "true"),
                     shown: api.PANES.filter((p) => !doc.els["pane-" + p].hidden) };
  }
  // The reported bug: reloaded on Defaults, opens on Defaults.
  {
    const { doc, api } = run("#tab=defaults");
    api.restoreView();
    out.libRestored = { view: api.view(),
                        shown: api.PANES.filter((p) => !doc.els["pane-" + p].hidden),
                        selected: api.PANES.filter((p) => doc.els["tab-" + p].attrs["aria-selected"] === "true") };
  }
  // One level down: the right tab AND the right work type.
  {
    const { doc, api } = run("#tab=defaults&wt=gyp");
    api.restoreView();
    out.libWorkType = { view: api.view(), wt: api.wt(),
                        strip: api.WORK_TYPES.filter((k) => doc.els["wt-" + k].attrs["aria-selected"] === "true") };
  }
  // A tab that does not exist, and a work type that does not: both fall back, and neither leaves
  // an empty pane behind.
  {
    const { doc, api } = run("#tab=rooms&wt=terrazzo");
    api.restoreView();
    out.libUnknown = { view: api.view(), wt: api.wt(),
                       shown: api.PANES.filter((p) => !doc.els["pane-" + p].hidden) };
  }
  // And the other half: switching a tab records it. showView's write is afterTab; the
  // work-type strip's is a SEPARATE write inside document's own click listener, so it is driven
  // through THAT REAL LISTENER -- onWtClick, lifted whole above -- instead of calling M.write()
  // by hand. Calling M.write() ourselves would prove M.write() works, which four other tests
  // already prove, and nothing about whether the page's own listener still calls it.
  {
    const { win, api } = run("");
    api.showView("vendors");
    const afterTab = win.location.hash;
    api.onWtClick({ target: fakeTarget("data-work-type", "epoxy") });
    out.libWrites = { afterTab, afterWt: win.location.hash };
  }
  // Without the module the page behaves exactly as it did before this feature existed.
  {
    const win = makeWin("#tab=defaults", { noModule: true });
    const doc = makeDoc(ids);
    const api = scope(win, doc, doc.getElementById, noop, noop, noop);
    api.restoreView();
    out.libNoModule = { view: api.view(), hash: win.location.hash };
  }
}

// ── 3. the Markup page: one tab per sheet layout, and the list comes from the API
{
  const src = read(path.join(ROOT, "js", "markup.js"));
  const body = [lift(src, "openingLayout", "markup.js"), "return { openingLayout };"].join("\n");
  const scope = new Function("window", body);
  const LAYOUTS = ["epoxy", "polish", "seal", "gyp", "global"];
  out.markup = {
    fresh: scope(makeWin("")).openingLayout(LAYOUTS),
    remembered: scope(makeWin("#tab=gyp")).openingLayout(LAYOUTS),
    // A layout this server does not serve — `combo` is refused by markup.py by name, and an older
    // link can name anything. Neither may leave the page with no tab selected.
    refused: scope(makeWin("#tab=combo")).openingLayout(LAYOUTS),
    noneAtAll: scope(makeWin("#tab=gyp")).openingLayout([]),
    noModule: scope(makeWin("#tab=gyp", { noModule: true })).openingLayout(LAYOUTS),
  };

  // The write half: the REAL #mk-tabs click listener, lifted whole -- not window.TWTabMemo.write()
  // called by hand. The opening-tab scenarios above prove openingLayout() works and prove
  // nothing about whether a tab click still records one.
  const clickBody = [
    decl(src, "var", "LAYOUT", "markup.js"),
    "const __onTabClick = " + liftListener(src, '$("mk-tabs")', "click", "markup.js") + ";",
    "return { onTabClick: __onTabClick, layout: () => LAYOUT };",
  ].join("\n");
  const clickScope = new Function("window", "say", "render", clickBody);
  {
    const win = makeWin("", { pathname: "/markup.html" });
    const noop = () => {};
    const api = clickScope(win, noop, noop);
    api.onTabClick({ target: fakeTarget("data-layout", "gyp") });
    out.markupWrites = { afterTab: win.location.hash, layout: api.layout() };
  }
}

// ── 4. the cadence editor: one tab per customer email ────────────────────────
{
  const src = read(path.join(ROOT, "js", "followup-settings.js"));
  const body = [lift(src, "openingEmail", "followup-settings.js"), "return { openingEmail };"]
    .join("\n");
  const scope = new Function("window", body);
  const KEYS = ["sent", "not_viewed", "next_steps", "second_nudge", "checkin", "deposit_nudge"];
  out.cadence = {
    fresh: scope(makeWin("")).openingEmail(KEYS, "not_viewed"),
    remembered: scope(makeWin("#tab=deposit_nudge")).openingEmail(KEYS, "not_viewed"),
    // An email the portal stopped offering. The editor must not open writing into a template
    // nobody can see.
    retired: scope(makeWin("#tab=old_nudge")).openingEmail(KEYS, "not_viewed"),
    noModule: scope(makeWin("#tab=checkin", { noModule: true })).openingEmail(KEYS, "not_viewed"),
  };

  // The write half: the REAL #tabs click listener, lifted whole -- same gap as markup's tab
  // strip, and the same reason a call to window.TWTabMemo.write() by hand would not find it.
  const clickBody = [
    decl(src, "var", "KEY", "followup-settings.js"),
    "const __onTabClick = " + liftListener(src, '$("tabs")', "click", "followup-settings.js") + ";",
    "return { onTabClick: __onTabClick, key: () => KEY };",
  ].join("\n");
  const clickScope = new Function("window", "collect", "paintTabs", "fillTemplate",
    "schedulePreview", clickBody);
  {
    const win = makeWin("", { pathname: "/followup-settings.html" });
    const noop = () => {};
    const api = clickScope(win, noop, noop, noop, noop);
    api.onTabClick({ target: fakeTarget("data-key", "deposit_nudge") });
    out.cadenceWrites = { afterTab: win.location.hash, key: api.key() };
  }
}

// ── 5. the Polish beta: three steps ──────────────────────────────────────────
{
  const src = read(path.join(ROOT, "js", "polish-estimate.js"));
  const body = [
    /(^|\n) {2}var STEPS = \[[\s\S]*?\n {2}\];/.exec(src)[0],
    decl(src, "var", "at", "polish-estimate.js"),
    lift(src, "stepKeys", "polish-estimate.js"),
    lift(src, "openingStep", "polish-estimate.js"),
    lift(src, "go", "polish-estimate.js"),
    "return { openingStep, go, at: () => at, STEPS };",
  ].join("\n");
  // paintRail and renderPanel are the page's own renderers and are not what this is about; the
  // decision is which index `go` lands on and what it records.
  const scope = new Function("window", "paintRail", "renderPanel", body);
  const build = (hash) => {
    const win = makeWin(hash, { pathname: "/polish-estimate.html", search: "?d=proj-1" });
    win.scrollTo = () => {};
    return { win, api: scope(win, () => {}, () => {}) };
  };
  const step = (hash) => build(hash).api.openingStep(0);
  out.polish = {
    fresh: step(""),
    remembered: step("#step=review"),
    // BY KEY, never by number: a link that said "step 2" would mean something else the day a step
    // is added, and a removed step would leave `at` pointing past the end of PANELS.
    retired: step("#step=materials"),
    numeric: step("#step=2"),
    noModule: build("#step=labor").api.openingStep(0) === 0 ? "fell back" : "read it anyway",
  };
  {
    const { win, api } = build("");
    api.go(2);
    const afterGo = win.location.hash;
    // CLAMPED, AND DOWNWARD FROM Review, so the step recorded is provably the step SHOWN rather
    // than the one asked for. Clamping upward proves nothing here: go(99) lands on Review, which
    // is where the URL already said, so a write taken before the clamp would read as correct.
    api.go(-1);
    out.polishWrites = { afterGo, afterClamp: win.location.hash, at: api.at(),
                         keptDraft: win.location.search };
  }
  {
    const win = makeWin("#step=labor", { noModule: true });
    win.scrollTo = () => {};
    out.polish.noModule = scope(win, () => {}, () => {}).openingStep(0);
  }
}

// ── 6. the estimate sheet: sixteen worksheet tabs plus the estimator's copies ──
{
  const src = read(path.join(ROOT, "js", "estimate-review.js"));
  const body = [
    /(^|\n)const GYP_BASE = [^\n]*;/.exec(src)[0],
    lift(src, "defaultBaseSheet", "estimate-review.js"),
    lift(src, "openingSheet", "estimate-review.js"),
    "return { openingSheet, defaultBaseSheet };",
  ].join("\n");
  const scope = new Function("window", "state", "tabs", body);
  const TABS = [{ id: "Epoxy" }, { id: "Polish" }, { id: "Leveling" }, { id: "Copy1" }];
  const at = (hash, st, tabsIn) =>
    scope(makeWin(hash, { pathname: "/estimate-review.html", search: "?d=proj-1" }),
          st || { work_type: "epoxy" }, tabsIn || TABS).openingSheet();
  out.sheet = {
    fresh: at(""),
    freshPolish: at("", { work_type: "polish" }),
    remembered: at("#sheet=Leveling"),
    // A COPY IS A REAL TAB. Its id is a copy id and the page must come back to it.
    copy: at("#sheet=Copy1"),
    // …and the day somebody deletes that copy, an old link must open the base bid rather than
    // "Failed to load Copy1" over an empty grid.
    deletedCopy: at("#sheet=Copy1", null, [{ id: "Epoxy" }, { id: "Polish" }]),
    gypFallback: at("#sheet=Copy9", { work_type: "gyp" }),
    noModule: scope(makeWin("#sheet=Leveling", { noModule: true }), { work_type: "epoxy" }, TABS)
      .openingSheet(),
  };
}

// ── 7. the CRM board's drawer: which project is open ─────────────────────────
{
  const src = read(path.join(ROOT, "js", "portal.js"));
  const body = [lift(src, "markDrawerInUrl", "portal.js"), "return { markDrawerInUrl };"].join("\n");
  const scope = new Function("location", "history", "URLSearchParams", body);
  const drive = (search, hash, pid) => {
    const win = makeWin(hash, { pathname: "/portal.html", search });
    scope(win.location, win.history, URLSearchParams).markDrawerInUrl(pid);
    return { search: win.location.search, hash: win.location.hash,
             path: win.location.pathname, writes: win.writes };
  };
  // AND THE CLOSE PATH THROUGH THE REAL closeDrawer, not through markDrawerInUrl directly: the
  // question "does closing take it back out" is about the WIRING, and calling the helper by hand
  // would answer it whatever closeDrawer did. It is small enough to run — it clears three module
  // variables, drops a class and asks syncScrim — so there is no reason to settle for a source
  // read here. (openDetail is not: it is async and fetches, and drawer-render-harness.js is what
  // runs that one. Its call site is read from the source in the test file, and says so.)
  const closeBody = [
    lift(src, "markDrawerInUrl", "portal.js"),
    lift(src, "closeDrawer", "portal.js"),
    "return { closeDrawer, pid: () => CUR_PID, sec: () => ACTIVE_SEC, sig: () => DRAWER_SIG };",
  ].join("\n");
  const closeScope = new Function("location", "history", "URLSearchParams", "$", "syncScrim",
                                  "CUR_PID", "ACTIVE_SEC", "DRAWER_SIG", closeBody);
  {
    const win = makeWin("", { pathname: "/portal.html", search: "?open=p-42" });
    const el = { classList: { remove() {} } };
    const api = closeScope(win.location, win.history, URLSearchParams, () => el, () => {},
                           "p-42", "chat", "sig");
    api.closeDrawer();
    out.drawerClose = { search: win.location.search, pid: api.pid(), sec: api.sec(),
                        sig: api.sig() };
  }
  out.drawer = {
    opened: drive("", "", "p-42"),
    // Whatever else is already in the query stays: the board is reached from links that carry
    // their own parameters.
    keepsOthers: drive("?est=kyle%40wetreadwell.com", "", "p-42"),
    closed: drive("?open=p-42", "", null),
    // Closing a drawer that was never in the URL writes nothing at all.
    closedTwice: drive("", "", null),
    // `sec` is deliberately NOT written — defaultSection routes a fresh open by what needs a
    // human — but a deep link that carries one is left alone.
    leavesSecAlone: drive("?open=p-1&sec=chat", "", "p-42"),
    // Opening a drawer must not cost library.js's or markup's or the estimate sheet's own
    // fragment its value. Every scenario above starts from an empty hash, so a mutation dropping
    // `+ location.hash` from markDrawerInUrl's replaceState call would leave every one of them
    // green -- the fragment it would have dropped was already empty.
    keepsTheFragment: drive("", "#sheet=Copy1", "p-77"),
  };
}

process.stdout.write(JSON.stringify(out) + "\n");
