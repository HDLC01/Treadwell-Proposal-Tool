"use strict";
/* Run step 5's project-folder chooser FOR REAL — the ranking rule, the radio group it renders,
 * the filter, and the Upload button's state — out of frontend/js/dropbox.js.
 *
 * WHY EXECUTED, NOT GREPPED. Every way this can be wrong is invisible to a source assertion:
 *
 *   * The preselect rule is arithmetic over two scores. A grep proves DBX_MIN_LEAD is
 *     mentioned; only running it proves 0.90-against-0.80 arms nothing while
 *     0.90-against-0.40 arms the top row — and that is the difference between one extra
 *     click and an estimate filed into another customer's job.
 *   * "The create option cannot be filtered away" is a claim about a string built by one
 *     function and a filter applied by another. Moving the push() one line up into the
 *     filtered array reads perfectly well and dead-ends step 5.
 *   * The button's label and its disabled flag are set in a helper the radio handler calls.
 *     Whether clicking a row actually reaches that helper is behaviour.
 *   * ESCAPING. esc() being present in the file says nothing about whether the folder NAME
 *     went through it. A Dropbox folder is named by whoever made it.
 *
 * Usage: node dropbox-picker-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);

// CRLF normalised on read: this harness matches the page's SOURCE TEXT and git hands these files
// out with CRLF on a Windows checkout, where a `$`-anchored pattern would find `\r` and miss.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const src = read(path.join(ROOT, "js", "dropbox.js"));

/** Lift a named function out of the page's IIFE (two-space indent), braces balanced. */
function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from dropbox.js — rewrite this harness, don't stub it");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name + "()");
}
function grab(re, what) {
  const m = re.exec(src);
  if (!m) throw new Error(what + " is gone from dropbox.js — rewrite this harness");
  return m[0];
}

// ── a DOM small enough to read, real enough to hold the controls ─────────────
// The chooser writes its rows as an innerHTML string and then queries them, so the nodes the
// change handlers get are built out of the page's OWN output. A hand-built fixture could agree
// with the handler and disagree with what renders.
const UNESC = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" };
const unesc = (s) => String(s).replace(/&(?:amp|lt|gt|quot|#39);/g, (m) => UNESC[m]);

function parseRadios(html) {
  const out = [];
  const re = /<input([^>]*)>/g;
  let m;
  while ((m = re.exec(html))) {
    const attrs = m[1];
    const cls = (/class="([^"]*)"/.exec(attrs) || [, ""])[1];
    if (cls.indexOf("dbx-radio") < 0) continue;
    const node = {
      className: cls,
      value: unesc((/value="([^"]*)"/.exec(attrs) || [, ""])[1]),
      checked: /\schecked(?=[\s>])|\schecked$/.test(attrs + " "),
      isNew: /data-new="1"/.test(attrs),
      dataset: {}, listeners: {},
      addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); },
    };
    out.push(node);
  }
  // A browser lets exactly one radio in a name group be checked; the group's `check()` below
  // enforces that, so a "two rows preselected" bug shows up as a report and not as a crash.
  out.forEach((n) => {
    n.check = function () {
      out.forEach((o) => { o.checked = (o === n); });
      (n.listeners.change || []).forEach((f) => f({ target: n }));
    };
  });
  return out;
}

/** The radio-group container: an innerHTML string plus the nodes materialised from it, cached
 *  per rendered string so a handler attached to a node is the node that gets clicked, and
 *  invalidated the moment innerHTML is replaced — exactly like a real re-render. */
function foldersNode() {
  let html = "";
  let cache = null;
  return {
    get innerHTML() { return html; },
    set innerHTML(v) { html = String(v); cache = null; },
    _radios() {
      if (!cache) cache = parseRadios(html);
      return cache;
    },
    querySelectorAll(sel) { return sel === ".dbx-radio" ? this._radios() : []; },
  };
}

function control(extra) {
  return Object.assign({
    listeners: {},
    addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); },
    fire(k, ev) {
      if (this.disabled) return false;
      (this.listeners[k] || []).forEach((f) => f(ev || {}));
      return true;
    },
  }, extra || {});
}

function makeDom() {
  return {
    "dbx-folders": foldersNode(),
    "dbx-folder-field": { style: {} },
    "dbx-folder-note": { textContent: "" },
    "dbx-search": control({ value: "" }),
    // A real button: `disabled` is the guard the whole "nothing is preselected" rule rests on,
    // and control()'s fire() refuses to click a disabled one, like a browser.
    "dbx-go": control({ disabled: true, textContent: "Create folder & upload" }),
  };
}

/** Build a live scope holding the REAL functions over one shared state object. */
function build() {
  const nodes = makeDom();
  const source = [
    grab(/^  const DBX_MIN_SCORE = .*$/m, "DBX_MIN_SCORE"),
    grab(/^  const DBX_MIN_LEAD = .*$/m, "DBX_MIN_LEAD"),
    fn("dbxState"),
    "  const DBX = dbxState();",          // the page's own module state, same identifier
    fn("dbxPreselect"), fn("dbxMatches"), fn("dbxVisible"), fn("dbxChosenFolder"),
    fn("dbxFolderRow"), fn("dbxNewRow"), fn("dbxFoldersHtml"), fn("dbxNote"),
    fn("dbxGoLabel"), fn("dbxGoDisabled"), fn("dbxSyncGo"), fn("dbxChoose"),
    fn("dbxWireRadios"), fn("dbxRenderFolders"), fn("dbxBeginLoad"), fn("dbxApply"),
    fn("dbxWireSearch"),
  ].join("\n");

  const scope = new Function("$", "esc",
    '"use strict";\n' + source + "\n"
    + "return { DBX, dbxPreselect, dbxBeginLoad, dbxApply, dbxRenderFolders, dbxWireSearch,\n"
    + "         dbxGoLabel, dbxGoDisabled, dbxNote };");

  // The page's own esc(), lifted rather than retyped: an escaping test that supplies its own
  // escaper proves nothing about the one that ships.
  const escSrc = grab(/^  function esc\(s\).*$/m, "esc()");
  const esc = new Function('"use strict";' + escSrc + "\nreturn esc;")();

  const s = scope((id) => nodes[id] || null, esc);
  s.nodes = nodes;
  s.dbxWireSearch();                       // once, exactly as the page does it

  // ── the chooser, driven the way a person drives it ─────────────────────────
  /** Choose a destination and let one response land, which is the page's own sequence:
   *  dbxBeginLoad → render (the loading state) → dbxApply(response) → render. */
  s.load = (resp, opts) => {
    const o = opts || {};
    if (o.previous) s.DBX.previous = o.previous;      // as the draft restore sets it
    s.dbxBeginLoad(s.DBX, o.dest || "gyp", o.destLabel || "Gyp Estimates");
    s.dbxRenderFolders(s.DBX);
    s.loadingSnap = s.snap();
    s.dbxApply(resp);
    return s;
  };
  s.radios = () => nodes["dbx-folders"].querySelectorAll(".dbx-radio");
  s.pick = (i) => {
    const r = s.radios()[i];
    if (!r) throw new Error("no radio at index " + i);
    r.check();
  };
  s.pickNew = () => {
    const r = s.radios().filter((x) => x.isNew)[0];
    if (!r) throw new Error("the create-a-new-folder row is not rendered at all");
    r.check();
  };
  s.typeFilter = (v) => {
    nodes["dbx-search"].value = v;
    nodes["dbx-search"].fire("input");
  };
  s.snap = () => {
    const html = nodes["dbx-folders"].innerHTML;
    const radios = s.radios();
    return {
      html,
      choice: s.DBX.choice,
      // Row names as RENDERED, so an unescaped name shows up here as markup.
      names: (html.match(/class="dbx-folder-name">([\s\S]*?)<\/span>/g) || [])
        .map((m) => m.replace(/^class="dbx-folder-name">/, "").replace(/<\/span>$/, "")),
      parents: (html.match(/class="dbx-folder-parent">([\s\S]*?)<\/span>/g) || [])
        .map((m) => m.replace(/^class="dbx-folder-parent">/, "").replace(/<\/span>$/, "")),
      titles: (html.match(/<label class="dbx-folder[^"]*" title="([^"]*)"/g) || [])
        .map((m) => m.replace(/^.*title="/, "").replace(/"$/, "")),
      radioValues: radios.map((r) => r.value),
      checked: radios.filter((r) => r.checked).map((r) => r.value),
      checkedCount: radios.filter((r) => r.checked).length,
      newRowCount: radios.filter((r) => r.isNew).length,
      badges: (html.match(/class="dbx-badge">[^<]*</g) || [])
        .map((m) => m.replace(/^class="dbx-badge">/, "").replace(/<$/, "")),
      fieldShown: nodes["dbx-folder-field"].style.display !== "none",
      note: nodes["dbx-folder-note"].textContent,
      goDisabled: nodes["dbx-go"].disabled,
      goLabel: nodes["dbx-go"].textContent,
    };
  };
  return s;
}

// ── fixtures ────────────────────────────────────────────────────────────────
const P = "/2023 Treadwell Team Folder/Estimating/$Commercial Sales Estimates";
const F = (name, parent, score) => ({ name, parent, score, path: P + "/" + parent + "/" + name });

// The case the whole rule exists for, in both directions. Same three folders, only the runner-up's
// score differs — so anything that reports the same verdict for both has stopped reading the lead.
const CLEAR = [F("26.06.12 Trabon Office Polish", "*Kyle", 0.9),
               F("26.02.03 Traband Warehouse", "*Kyle", 0.4),
               F("25.11.20 Tribeca Lofts", "*RJ", 0.2)];
const CONTESTED = [F("26.06.12 Trabon Office Polish", "*Kyle", 0.9),
                   F("26.08.02 Trabon Group HQ", "*Kyle", 0.8),
                   F("25.11.20 Tribeca Lofts", "*RJ", 0.2)];
const SUGGEST = "26.08.20 Trabon Group";

const out = {};

// ── the ranking rule, as the page renders it ────────────────────────────────
{
  const s = build();
  s.load({ ok: true, folders: CLEAR, suggested_new_name: SUGGEST, previous_path: null });
  out.clearWinner = s.snap();
  out.loadingState = s.loadingSnap;
}
{
  const s = build();
  s.load({ ok: true, folders: CONTESTED, suggested_new_name: SUGGEST, previous_path: null });
  out.contested = s.snap();
  // ...and it becomes usable the moment a human picks one, through the page's own handler.
  s.pick(1);
  out.contestedAfterPick = s.snap();
  out.contestedRadioValue = s.radios()[1].value;
}
// A lone candidate has no runner-up to be clear of, so the score alone decides — and a weak
// lone candidate must still arm nothing.
{
  const s = build();
  s.load({ ok: true, folders: [F("26.06.12 Trabon Office Polish", "*Kyle", 0.9)],
           suggested_new_name: SUGGEST });
  out.loneStrong = s.snap();
}
{
  const s = build();
  s.load({ ok: true, folders: [F("26.06.12 Trabon Office Polish", "*Kyle", 0.55)],
           suggested_new_name: SUGGEST });
  out.loneWeak = s.snap();
}
// Strong AND clear, but under the floor: 0.71 over 0.10 is a wide lead between two bad guesses.
{
  const s = build();
  s.load({ ok: true, folders: [F("26.01.02 Some Other Job", "*Kyle", 0.71),
                               F("25.09.09 Another Job", "*RJ", 0.1)],
           suggested_new_name: SUGGEST });
  out.underFloor = s.snap();
}

// ── previous_path beats the score ───────────────────────────────────────────
// Where this project was filed last time is a fact; a similarity score is a guess. The top row
// here is a runaway winner (0.95 vs 0.2) so the only thing that can move the selection off it
// is the previous path being preferred.
{
  const s = build();
  const folders = [F("26.06.12 Trabon Office Polish", "*Kyle", 0.95),
                   F("26.08.02 Trabon Group HQ", "*Kyle", 0.2)];
  s.load({ ok: true, folders, suggested_new_name: SUGGEST, previous_path: folders[1].path });
  out.previousWins = s.snap();
  out.previousPath = folders[1].path;
  out.topPath = folders[0].path;
}
// A previous_path Dropbox no longer lists (the folder was renamed or moved) must fall back to
// the score rule rather than preselect a row that isn't there.
{
  const s = build();
  s.load({ ok: true, folders: CLEAR, suggested_new_name: SUGGEST,
           previous_path: P + "/*Kyle/26.01.01 Folder That Moved" });
  out.previousGone = s.snap();
  out.clearTopPath = CLEAR[0].path;
}
// The draft's own remembered folder, restored locally before any response arrives. Same
// precedence, reached the way a revisit reaches it.
{
  const s = build();
  s.load({ ok: true, folders: CONTESTED, suggested_new_name: SUGGEST },
          { previous: CONTESTED[2].path });
  out.restoredFromDraft = s.snap();
  out.restoredPath = CONTESTED[2].path;
}

// ── the filter ──────────────────────────────────────────────────────────────
{
  const s = build();
  s.load({ ok: true, folders: CONTESTED, suggested_new_name: SUGGEST });
  s.typeFilter("trabon");
  out.filterNarrowed = s.snap();
  s.typeFilter("*rj");                       // the PARENT is visible text too
  out.filterByParent = s.snap();
  s.typeFilter("zzzz nothing");              // nothing matches — the create row is all that's left
  out.filterNoMatch = s.snap();
  s.typeFilter("");
  out.filterCleared = s.snap();
}
// A choice made before typing keeps its name in the note while the filter hides its row —
// otherwise the button says "File into this folder" and no folder is on screen.
{
  const s = build();
  s.load({ ok: true, folders: CLEAR, suggested_new_name: SUGGEST });
  s.typeFilter("tribeca");
  out.filterHidesChoice = s.snap();
}

// ── the degraded paths: step 5 must never dead-end ──────────────────────────
{
  const s = build();
  s.load({ ok: false, folders: [], error: "Dropbox is unreachable (503)",
           suggested_new_name: SUGGEST });
  out.errorResponse = s.snap();
}
{
  const s = build();
  s.load({ ok: true, folders: [], suggested_new_name: SUGGEST });
  out.emptyCategory = s.snap();
}
// A response with no folders key at all, which is what a mangled/empty body looks like.
{
  const s = build();
  s.load({});
  out.junkResponse = s.snap();
}
// Nothing chosen in the destination select: the whole field stays hidden and Upload is dead.
{
  const s = build();
  s.dbxBeginLoad(s.DBX, "", "");
  s.dbxRenderFolders(s.DBX);
  out.noDestination = s.snap();
}

// ── the parent line, which only earns its space when it says something ──────
// Gyp Estimates has no per-person subfolders, so every candidate's parent IS the destination the
// estimator just picked. Repeating it on 80 rows is noise; "in *Kyle" is the whole reason the
// line exists.
{
  const s = build();
  s.load({ ok: true,
           folders: [{ name: "26.06.12 Trabon Office Polish", parent: "Gyp Estimates", score: 0.4,
                       path: "/2023 .../Gyp Estimates/26.06.12 Trabon Office Polish" },
                     { name: "26.05.01 Elmwood Gyp", parent: "*Kyle", score: 0.3,
                       path: "/2023 .../*Kyle/26.05.01 Elmwood Gyp" }],
           suggested_new_name: SUGGEST },
          { dest: "gyp", destLabel: "Gyp Estimates" });
  out.parentSameAsDest = s.snap();
}

// ── the create option, chosen deliberately ──────────────────────────────────
{
  const s = build();
  s.load({ ok: true, folders: CONTESTED, suggested_new_name: SUGGEST });
  s.pickNew();
  out.pickedNew = s.snap();
  out.suggested = SUGGEST;
}

// ── escaping: a Dropbox folder is named by whoever made it ──────────────────
{
  const s = build();
  const nasty = '<img src=x onerror=alert(1)>';
  const folders = [{ name: nasty, parent: '"><script>alert(2)</script>',
                     path: P + "/" + nasty, score: 0.9 },
                   F("26.02.03 Traband Warehouse", "*Kyle", 0.4)];
  s.load({ ok: true, folders, suggested_new_name: '<b>26.08.20</b>' });
  out.escaping = s.snap();
  out.nastyName = nasty;
}

console.log(JSON.stringify(out));
