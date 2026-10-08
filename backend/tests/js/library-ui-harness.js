"use strict";
/* Execute the REAL render functions out of frontend/js/library.js and report what they produce.
 *
 * WHY EXECUTED. Batch 6 rebuilt both tables — the Items row went from 7 columns to 8 with a
 * different set, and the assembly line dropped Role and gained two. Every interesting way that
 * can be wrong is invisible to a source assertion:
 *
 *   * `refreshNumbers()` writes the computed cells BY POSITION (tds[4], tds[5]). Those indexes
 *     live in a different function from the row that renderPanel builds, so a column added ahead
 *     of them writes the quantity into the waste box. The only honest check is to render a row
 *     and compare where the qty cell actually landed with the index the updater uses.
 *   * `buy_qty` must be in the numeric-coercion list or the model holds the string "5" and the
 *     next multiplication concatenates. Grepping for the field name would match its own
 *     declaration.
 *   * The Vendors tab renders inputs for an admin and plain text for everybody else. A grep for
 *     "ADMIN" proves the variable is mentioned, not that a non-admin gets no editable field.
 *   * The material picker resolves typed text to an id. "Does it search?" is behaviour.
 *
 * The pricing comes from the REAL library-core.js, so nothing here can pass against a stub that
 * disagrees with the engine.
 *
 * Usage: node library-ui-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");            // js/icons.js is evaluated, not stubbed — see dialogChecks()

const ROOT = path.resolve(process.argv[2]);

// Line endings normalised on read, because this harness matches the page's SOURCE TEXT and git
// hands these files out with CRLF on a Windows checkout. The `grab()` patterns below are
// multiline-anchored (`/^  var DIVISIONS = \[[^\]]*\];$/m`), and on CRLF the character before the
// newline is `\r`, not `;` — so every one of them misses and the whole file reports "the harness
// itself failed" while CI, which checks out LF, stays perfectly green. Found the moment a
// `git checkout --` restored this file mid-session.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const src = read(path.join(ROOT, "js", "library.js"));
const html = read(path.join(ROOT, "library.html"));
const L = require(path.join(ROOT, "js", "library-core.js"));
// The REAL nameOf, for the same reason the pricing is real: the Assemblies rail sorts and labels
// by who created an assembly through TWCrm.nameOf, which is the app's one email→display-name
// convention. A stub here could agree with this file and disagree with the CRM board.
const CRM = require(path.join(ROOT, "js", "crm-core.js"));
// The REAL vocabulary (js/work-types.js), for the same reason: the page's WORK_TYPES, its
// appliesToWorkType and the three Takeoff conditions it lists are read off it, so a made-up copy here would
// agree with the page by construction and prove nothing. Handed to the scope as `WT`, the page's own alias.
const WT = require(path.join(ROOT, "js", "work-types.js"));

/** Lift a named function out of the page's IIFE (two-space indent), braces balanced.
 *
 *  `async` is optional in the pattern because confirmItemPatch awaits TW.confirmDanger. Without
 *  that the lift throws "confirmItemPatch() is gone", which reads as a deleted function rather
 *  than an unmatched keyword and sends the next reader looking in the wrong file. */
function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from library.js — rewrite this harness, don't stub it");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}
function grab(re, what) {
  const m = re.exec(src);
  if (!m) throw new Error(what + " is gone from library.js — rewrite this harness");
  return m[0];
}

/** The body of one `$("id").addEventListener("event", function (e) { … })`, braces balanced.
 *
 *  SOURCE TEXT, AND SAID OUT LOUD BECAUSE THIS FILE IS OTHERWISE EXECUTED. The page's listeners
 *  are top-level wiring inside its IIFE, not functions, so `fn()` cannot reach them and neither
 *  can any scenario here — the same reason confirmDanger's dialog and the bulk modal are verified
 *  in a browser. What this is for is narrow and worth having: proving a listener calls the
 *  repaint and NOT one of the two neighbouring helpers that also repaint and additionally move
 *  the caret. That is a wiring mistake, not a logic one, and a wiring mistake is exactly the kind
 *  a source assertion can see. It cannot tell you the body runs, so nothing that has a testable
 *  decision in it belongs here — pull that out into a named function instead, the way
 *  placeNewAssembly was. */
function listenerBody(id, ev) {
  const m = new RegExp('\\$\\("' + id + '"\\)\\.addEventListener\\("' + ev
    + '", function \\(e\\) \\{').exec(src);
  if (!m) {
    throw new Error("the " + id + " " + ev + " listener is gone from library.js — rewrite this "
      + "harness, don't stub it");
  }
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(i, j + 1);
  }
  throw new Error("unbalanced braces reading the " + id + " listener");
}

// ── a DOM stub, only as much as these functions touch ────────────────────────
function makeDom() {
  const nodes = {};
  // EVERY focus() ANY RENDERER CALLS, in order, and nothing clears it.
  //
  // Recorded because a render that moves the caret is a keyboard bug no clicking test can reach:
  // an estimator who tabs Unit → Condition → Sort and picks a key is still inside that select,
  // and a renderer that focuses the search box (which clearAsmFilters legitimately does) throws
  // them out of the pass they were making. An empty list after a render is the assertion.
  const focused = [];
  // Backing store for classList, one Set per element -- so `.on` set by one render is still
  // there for the next one to read (renderPanel's favourite star toggles the same button across
  // repeated calls, the way #f-clear's `[hidden]` already persists across renders via the plain
  // `hidden` property below).
  const classSets = {};
  const el = (id) => (nodes[id] = nodes[id] || {
    id, innerHTML: "", textContent: "", hidden: false, value: "", title: "",
    focus() { focused.push(this.id); },
    // Same shape as tableFromHtml's row stub below -- one Set per element, add/remove/toggle/has.
    classList: {
      add: (c) => (classSets[id] = classSets[id] || new Set()).add(c),
      remove: (c) => classSets[id] && classSets[id].delete(c),
      toggle: (c, on) => (on ? el(id).classList.add(c) : el(id).classList.remove(c)),
      has: (c) => !!classSets[id] && classSets[id].has(c),
    },
    // Attributes a renderer sets directly (aria-pressed, aria-label) rather than through one of
    // the named properties above. Read back by the same name so a test can assert either.
    attrs: {},
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    // Filled in on demand by tests that need to walk a rendered table.
    rows: null,
    querySelectorAll(sel) {
      if (sel !== "[data-line]") return [];
      if (!this.rows) this.rows = tableFromHtml(this.innerHTML);
      return this.rows;
    },
  });
  return { el, nodes, focused };
}

/** Turn rendered table HTML into the minimum object graph `refreshNumbers` walks.
 *
 *  Built FROM renderPanel's own output rather than hand-written, which is the whole point: the
 *  updater addresses cells by position on a table that function produced, and a hand-made fixture
 *  could agree with the updater while disagreeing with the page. Recorded per cell index so a
 *  transposition — the exact bug that reached staging — shows up as content in the wrong slot. */
function tableFromHtml(html) {
  const rows = html.split("</tr>").filter((r) => /data-line=/.test(r));
  return rows.map((rowHtml) => {
    const cells = rowHtml.split("<td").slice(1).map((c) => ({
      initial: c, written: null,
      set innerHTML(v) { this.written = v; },
      get innerHTML() { return this.written === null ? this.initial : this.written; },
    }));
    const classes = new Set((/class="([^"]*)"/.exec(rowHtml.split(">")[0]) || ["", ""])[1]
      .split(/\s+/).filter(Boolean));
    return {
      cells,
      classList: {
        add: (c) => classes.add(c), remove: (c) => classes.delete(c),
        toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
        has: (c) => classes.has(c),
      },
      querySelectorAll: (sel) => (sel === "td" ? cells : []),
      getAttribute: (k) => (k === "data-line"
        ? (/data-line="(\d+)"/.exec(rowHtml) || [0, "0"])[1] : null),
    };
  });
}

/** The Division cell, cut out of a rendered row.
 *
 *  Ends at the closing tag of the strip's own div, which is the LAST </div> before the next <td>:
 *  a lazy `[\s\S]*?</div>` would stop at the first one and, if the chip markup ever grows a nested
 *  div, silently report half the chips as missing. */
function divisionCellOf(rowHtml) {
  const i = rowHtml.indexOf('<div class="division-chips"');
  if (i === -1) return "";
  const j = rowHtml.indexOf("<td", i);
  return rowHtml.slice(i, j === -1 ? rowHtml.length : j);
}

/** Turn the REAL rendered division cell into inputs a test can toggle.
 *
 *  Parsed from divisionPick's own output rather than hand-written, for the reason tableFromHtml
 *  gives: the handler queries `input[data-f="divisions"]:checked` off the row, so a renamed
 *  attribute or a lost `checked` has to break this. The row object answers only the two things
 *  onItemEdit asks it for.
 *
 *  Toggling is the browser's job, not the handler's — a label wrapping a checkbox flips it before
 *  `change` fires — so `toggle()` flips the input first and then calls the handler, which is the
 *  order a click produces. */
function chipRowFromHtml(itemId, cellHtml) {
  const tags = cellHtml.match(/<input[^>]*data-f="divisions"[^>]*>/g) || [];
  if (!tags.length) {
    throw new Error("no input[data-f=\"divisions\"] in the division cell — the save contract moved "
      + "and onItemEdit's own selector cannot find the chips either");
  }
  const inputs = tags.map((tag) => ({
    tag,
    div: (/data-div="([^"]*)"/.exec(tag) || ["", ""])[1],
    checked: / checked>/.test(tag) || / checked /.test(tag),
    type: (/type="([^"]*)"/.exec(tag) || ["", ""])[1],
    ariaLabel: (/aria-label="([^"]*)"/.exec(tag) || ["", ""])[1],
    getAttribute(k) { return k === "data-f" ? "divisions" : k === "data-div" ? this.div : null; },
  }));
  const row = {
    inputs,
    getAttribute: (k) => (k === "data-item" ? itemId : null),
    querySelectorAll(sel) {
      if (sel !== 'input[data-f="divisions"]:checked') {
        throw new Error("the handler asked for " + sel + ", which this row does not model");
      }
      return inputs.filter((x) => x.checked);
    },
  };
  inputs.forEach((inp) => { inp.closest = (sel) => (sel === "[data-item]" ? row : null); });
  return row;
}

/** A document stub that records what `paintDates` looked for and what it wrote.
 *
 *  Deliberately NOT a DOM emulator. It answers one question — does the repaint address a selector
 *  the rendered row actually carries, and does it write the dates markup? — and the harness feeds
 *  it the class list taken from the real renderItems output, so a renamed cell breaks the test. */
function makeDocument(presentSelectors) {
  const writes = [];
  return {
    writes,
    querySelector(sel) {
      if (presentSelectors.indexOf(sel) === -1) return null;
      return { set innerHTML(v) { writes.push({ sel, html: v }); } };
    },
  };
}

const dom = makeDom();
const scope = new Function("L", "$", "TW", "state", "document", "CRM", "WT", `
  "use strict";
  var ITEMS = state.ITEMS, ASMS = state.ASMS, VENDORS = state.VENDORS;
  // New-this-session records, read by renderItems (the Save button) and renderPanel (#asm-save).
  var FRESH = state.FRESH || { items: {}, assemblies: {} };
  var DIVISION_REFS = state.DIVISION_REFS || [], UNIT_REFS = state.UNIT_REFS || [];
  var VENDOR_USE = state.VENDOR_USE, DIVISION_USE = state.DIVISION_USE || {}, UNIT_USE = state.UNIT_USE || {};
  var ADMIN = state.ADMIN;
  // The Markup page's Global lines. Declared here rather than lifted because the page fills it
  // from its own fetch inside load(), which this sandbox does not run -- a test hands it in.
  var GLOBAL_MARKUP = state.GLOBAL_MARKUP || [];
  // The filed Fees + Textura row (the Defaults tab's own always-listed row), handed in the same way.
  var FEES_RULE = state.FEES_RULE || null;
  // THE NETWORK for saveFeesDefault: what would have been sent, and what the server "answers".
  var FEES_CALLS = [];
  async function api(path, opts) {
    FEES_CALLS.push({ path: path, opts: opts });
    var r = state.FEES_RESPONSE || { status: 200, body: null };
    var body = r.body || (opts && opts.body ? { ok: true, rule: JSON.parse(opts.body) } : {});
    return { status: r.status, ok: r.status < 400, json: async function () { return body; } };
  }
  // The Takeoff conditions' STORED answers, handed in the same way. Only the overrides live
  // here: what a new estimate ships answering comes from the REAL bid-model below, so a
  // fixture cannot make this page agree with itself about an answer the bid does not hold.
  // Reassigned by setConditionDefault, so tests read it back through condDefaultsNow().
  var COND_DEFAULTS = state.COND_DEFAULTS || [];
  // THE NETWORK, AND ONLY THE NETWORK -- the same split the labor stubs below take. Everything
  // on the way to the request is the page's code: the optimistic flip, the repaint and the
  // put-it-back on a refusal.
  var COND_CALLS = [];
  var COND_FAIL = state.COND_FAIL || false;
  async function putConditionDefault(key, body) {
    COND_CALLS.push(Object.assign({ key: key }, body));
    if (COND_FAIL) throw new Error("the server said no");
    return { ok: true };
  }
  // THE WORK-TYPE WRITE, same split again: everything before the request is the page's own code.
  // This one is the half that did not exist until 2026-09-21 -- library.py stored
  // default_work_types from the day the column landed and library.js only ever read it, so every
  // row sat at [] and all five chips above the table rendered one identical list.
  var WT_CALLS = [];
  var WT_FAIL = state.WT_FAIL || false;
  async function patchWorkTypes(kind, id, list) {
    WT_CALLS.push({ kind: kind, id: id, list: list });
    if (WT_FAIL) throw new Error("the server said no");
    return { ok: true };
  }
  // The estimate's shared module, which the page reaches through the window object. Declared
  // rather than
  // stubbed away: takeoffConditionDefaults must read freshModel's REAL answers -- joint filler
  // ships on, dye ships off -- so a fixture that made those up would prove nothing about what a
  // new estimate actually opens with.
  var window = state.window || {};
  var openId = state.openId;
  // Which line's item picker is showing its results. pickerFor() reads it, so a test can render
  // the closed state (null, the default) or the open one by passing state.pickerOpen.
  var pickerOpen = state.pickerOpen === undefined ? null : state.pickerOpen;
  ${grab(/^  var DIVISIONS = \[[^\]]*\];$/m, "DIVISIONS")}
  ${grab(/^  var UNITS = \[[^\]]*\];$/m, "UNITS")}
  var DEFAULT_DIVISIONS = DIVISIONS.slice();
  // The hardcoded literal above is the FALLBACK. On a loaded page load() replaces it with the
  // Administration tab's list, so a test that wants to prove a curated division reaches the chips
  // passes that list in here — built by the real assignment out of load(), not restated.
  if (state.DIVISIONS) DIVISIONS = state.DIVISIONS;
  ${grab(/^  var esc = function[\s\S]*?\n  \};$/m, "esc")}
  ${fn("current")}
  ${fn("itemOf")}
  // THE THREE RESERVED IDS (joint filler kit, remove-existing, dye) AND THE CONDITION EACH IS,
  // lifted BEFORE every function that asks about them (renderItems, itemResultsHtml,
  // takeoffConditionDefaults, defaultCandidates, removeDefault). A lifted function reaching for a
  // helper this scope does not have dies on a ReferenceError that reds every scenario in this
  // file at once.
  ${grab(/^  var RESERVED_ITEM_CONDITION = WT\.reservedItems\(\);$/m, "the RESERVED_ITEM_CONDITION declaration")}
  ${fn("isReservedItem")}
  // Lifted because renderPanel calls it. A lifted function that reaches for a helper this scope
  // does not have dies with a ReferenceError, which takes every test in test_library_ui.py red at
  // once with no hint of the real cause — so a new helper and its lift belong in one commit.
  ${fn("asmUnit")}
  ${fn("byId")}
  ${fn("adoptSaved")}
  ${fn("pick")}
  ${fn("itemDivisions")}
  ${fn("namesWithItemExtras")}
  ${fn("divisionNames")}
  ${fn("unitNames")}
  ${fn("qtyText")}
  ${fn("orderAmount")}
  ${fn("optionsHtml")}
  ${fn("divisionPick")}
  ${fn("vendorNames")}
  ${fn("similarNames")}
  ${fn("dupeHtml")}
  // BEFORE which calls it on both the Added and the Edited line. This is the exact
  // hazard the note above describes: byHtml arrived with the who-created/who-edited columns on
  // 2026-09-04, and without this lift datesHtml raises a ReferenceError that reds every scenario
  // in this file rather than the one test about names. The History column STAYED -- only its
  // price line came out on 2026-09-18.
  ${fn("byHtml")}
  ${fn("datesHtml")}
  ${fn("paintDates")}
  // NO defaultSwitch LIFT ANY MORE. It was lifted here on 2026-09-16 because renderItems drew
  // a default toggle in the Items and Assemblies tabs; that toggle is gone, because defaults
  // are owned by the Defaults tab alone now and two places to set one flag is a precedence
  // question nobody wants to answer. fn() THROWS on a name it cannot find, so leaving the
  // dead lift here reddened all 156 scenarios in this file at once -- which is the failure
  // mode the comment above it was written to warn about, arriving from the opposite side.
  // LIFTED, not stubbed, and it has to be lifted BEFORE the three renderers that call it.
  // renderItems, renderRefSection and renderPanel each ask icon() for a glyph now; leaving it
  // out is a ReferenceError that kills every scenario in this file at once.
  ${fn("icon")}
  ${fn("itemSaveButtonHtml")}
  ${fn("renderItems")}
  // THE DEFAULTS TAB'S OWN RENDERERS, lifted so they are EXECUTED rather than read. A source-text
  // assertion cannot catch an unbound identifier, and this repo has taken production down that
  // way once already. takeoffConditionDefaults goes first: renderDefaultTakeoff calls it.
  ${fn("takeoffConditionDefaults")}
  // defaultRowActions BEFORE renderDefaultTakeoff, which calls it for every row. The
  // Defaults tab is administrative now -- each row carries Edit and Delete -- so the
  // renderer no longer just prints names.
  ${fn("defaultRowActions")}
  // takeoffDefaultGroups BEFORE renderDefaultTakeoff, which now calls it for the whole list.
  // The Takeoff defaults are grouped under sub-headings rather than carrying a Kind column,
  // and the grouping is a separate function precisely so a test can execute it and read the
  // groups back as data instead of regex-matching headings out of the rendered HTML.
  // THE WORK-TYPE FILTER, lifted BEFORE the two renderers that call it. A default now says
  // which of the five sheet tabs it belongs to, and an EMPTY list means every one -- which
  // is what every row set before the column existed carries, so nothing anybody already
  // configured disappears the day the tabs arrive. The declarations come from library.js so
  // a renamed list cannot pass as a working one.
  ${grab(/^  var WORK_TYPES = WT\.tabKeys\(\);$/m, "the WORK_TYPES declaration")}
  ${grab(/^  var DEFAULT_WT = .*$/m, "the DEFAULT_WT declaration")}
  ${fn("appliesToWorkType")}
  ${fn("workTypeLabel")}
  // workTypeCell BEFORE takeoffDefaultGroups, which calls it for every assembly and material
  // row. Missing, this is a ReferenceError that reds every scenario in this file at once with
  // nothing pointing at the cause -- which is how it announced itself when the column landed.
  ${fn("workTypeCell")}
  // NO conditionPriceCell OR conditionRowActions LIFT ANY MORE. Both came out of library.js on
  // 2026-10-01, when Hanz asked for joint filler, remove-existing and dye to be "exactly like
  // materials": their tag and their own Add/Remove went, and fn() THROWS on a name it cannot
  // find, so a stale lift here would red every scenario in this file at once.
  // materialDefaultRow BEFORE takeoffDefaultGroups, which draws EVERY Materials row through it --
  // an ordinary favorited material and the three condition materials alike.
  // defaultSlider (the Defaults tab's starting-state slider) BEFORE both: every row they draw asks
  // it for its slider cell, so a missing lift is a ReferenceError that reds this whole file.
  ${fn("defaultSlider")}
  ${fn("materialDefaultRow")}
  ${fn("conditionDefaultRow")}
  ${fn("feesFigure")}
  ${fn("feesDefaultRow")}
  ${fn("saveFeesDefault")}
  ${fn("takeoffDefaultGroups")}
  ${fn("renderDefaultTakeoff")}
  // AFTER the renderer it repaints and after the network stub it awaits. This is the handler the
  // select presses, lifted so a test CHANGES the answer rather than reading that a box exists --
  // a markup assertion cannot tell a wired control from a dead one, and this page has shipped a
  // dead one behind a green test twice.
  ${fn("setConditionDefault")}
  // THE CHIP'S HANDLER, lifted so a test PRESSES it. Named setRowWorkType in library.js and not
  // setWorkType, because this scope already exports a setWorkType that switches which work type
  // the TAB is showing -- two things by one name in one file is how a test drives the wrong one.
  ${fn("setRowWorkType")}
  // THE ADD-A-DEFAULT PATH, lifted so it is EXECUTED. It shipped on 2026-09-17 as two
  // buttons and a search box with nothing bound to any of them, and the only test over it
  // regex-matched the markup for data-add-default="..." -- which the dead buttons satisfied
  // perfectly. The declarations come from library.js rather than being restated here, so a
  // renamed flag cannot pass as a working one.
  ${grab(/^  var DEFAULT_Q = "";$/m, "the DEFAULT_Q declaration")}
  ${grab(/^  var DEFAULT_MAX = \d+;$/m, "the DEFAULT_MAX declaration")}
  ${grab(/^  var DEFAULT_BROWSE = false;$/m, "the DEFAULT_BROWSE declaration")}
  ${fn("defaultCandidates")}
  ${fn("renderDefaultSearch")}
  ${fn("setDefaultQuery")}
  ${fn("placeDefaultSearch")}
  ${fn("closeDefaultSearch")}
  ${fn("onDefaultSearchKey")}
  ${fn("openDefaultBrowse")}
  // ── THE LABOR DEFAULTS, LIFTED AND EXECUTED ────────────────────────────────────────────────
  // "+ Add a labor line" shipped as markup with no handler at all, and Hanz reported it twice as
  // "the add labor line does not work". It passed every test this file had, because the only one
  // over it matched the pane for data-add-default="labor" -- which a dead button satisfies
  // perfectly. Everything below is lifted so a test presses the thing rather than reading it.
  //
  // LABOR is handed in the way GLOBAL_MARKUP is: the page fills it from its own fetch inside
  // load(), which this sandbox does not run. The declaration beside it is LIFTED from
  // library.js rather than restated -- "hours" and "days" are the units the estimate can actually
  // price, so a harness that typed its own list here would keep passing after the page grew a
  // third one that nothing prices.
  var LABOR = state.LABOR || [];
  ${grab(/^  var LABOR_UNITS = \[[^\]]*\];$/m, "the LABOR_UNITS declaration")}
  // The status line the failure paths write to. LIFTED, not stubbed, so a test reads the words an
  // estimator would, and stubbing a one-line function is just restating that line.
  ${grab(/^  var alertEl = \$\("alert"\);$/m, "the alertEl declaration")}
  ${fn("say")}
  // THE NETWORK, AND ONLY THE NETWORK. Everything on the way to a request is the page's own code
  // -- the validation, the body it builds, the optimistic removal and the put-it-back. The same
  // split this file already takes with patchSoon: what a test needs to see is the body that WOULD
  // go and whether a refusal is handled, and neither of those needs a socket.
  var LABOR_CALLS = [];
  var LABOR_FAIL = state.LABOR_FAIL || {};
  var LABOR_SEQ = 0;
  async function post(kind, body) {
    LABOR_CALLS.push({ op: "POST", kind: kind, body: body });
    if (LABOR_FAIL.post) throw new Error("the server said no");
    LABOR_SEQ++;
    return { ok: true, row: Object.assign({ id: "new" + LABOR_SEQ, guys_auto: false, sort: 0,
                                            notes: null, owner_email: null, favorite: false },
                                           body) };
  }
  async function del(kind, id) {
    LABOR_CALLS.push({ op: "DELETE", kind: kind, id: id });
    if (LABOR_FAIL.del) throw new Error("the server said no");
  }
  async function patchLabor(id, body) {
    LABOR_CALLS.push({ op: "PATCH", id: id, body: body });
    if (LABOR_FAIL.patch) throw new Error("the server said no");
    return { ok: true, row: Object.assign({ id: id, guys_auto: false }, body) };
  }
  // BOTH BEFORE the renderer that calls them for every row it draws. A lifted function reaching
  // for a helper this scope does not have dies on a ReferenceError that reds every scenario in
  // this file at once with nothing pointing at the cause -- five times in one session.
  ${fn("laborRowActions")}
  ${fn("renderDefaultLabor")}
  // Travel's own write: it PATCHes the reserved row back to the shipped rate rather than deleting
  // the one id anything can address Travel by.
  ${fn("resetTravelDefault")}
  // ── THE LABOR TAB ITSELF, 2026-09-24 -- LIFTED AND EXECUTED ────────────────────────────────
  // A labor TYPE is created and edited here now, on its own tab, a peer to Items and Assemblies
  // rather than a form on the Defaults tab. workTypeCell and byId are ALREADY lifted above this
  // point (workTypeCell by takeoffDefaultGroups' own block, byId by the items save path) --
  // reached here, not restated. patchSoon is STUBBED further down (QUEUED.push, no network) --
  // hoisted, so it resolves for these too despite sitting textually after them.
  ${grab(/^  var NUMERIC_LABOR_FIELDS = \[[^\]]*\];$/m, "the NUMERIC_LABOR_FIELDS declaration")}
  ${grab(/^  var laborMoreOpen = \{\};$/m, "the laborMoreOpen declaration")}
  ${fn("onLaborEdit")}
  ${fn("toggleLaborMore")}
  ${fn("focusLaborRow")}
  // WHERE A MATERIAL'S Edit LANDS. The router called it for a month before it existed; lifting it
  // is what makes a missing definition red here instead of a ReferenceError in a browser.
  // clearFilters is what it calls when the Items tab's own search is hiding the row, and it is
  // hoisted like every other lifted declaration, so its place below renderFilterBar is fine.
  ${fn("focusItemRow")}
  ${fn("clearFilters")}
  ${fn("renderLabor")}
  // THE TAB'S TWO WRITES, pulled out of the click listener so they run here. removeLaborLine
  // drops a queued edit for the row it deleted, so the two stores it clears are LIFTED from
  // library.js rather than declared -- patchSoon is stubbed in this scope and never fills them,
  // which is why a scenario seeds one by hand through setPending.
  ${grab(/^  var timers = \{\};$/m, "the timers declaration")}
  ${grab(/^  var pendingPatch = \{\};$/m, "the pendingPatch declaration")}
  ${fn("addLaborLine")}
  ${fn("removeLaborLine")}
  // setDefault's OWN NETWORK, stubbed the same way post/del/patchLabor are above -- captured so a
  // test can see the write it WOULD have sent, never a real socket. Sits beside them rather than
  // where setDefault itself is defined, matching the "NETWORK, AND ONLY THE NETWORK" grouping the
  // comment over post/del/patchLabor already promises.
  async function patchDefault(kind, id, on) {
    LABOR_CALLS.push({ op: "PATCH_DEFAULT", kind: kind, id: id, on: !!on });
    if (LABOR_FAIL.patchDefault) throw new Error("the server said no");
  }
  // paint()'s OWN EIGHT CALLEES ARE ALL ALREADY LIFTED by this point -- renderItems,
  // renderFilterBar, renderVendors, renderList and renderPanel by the items/assemblies save
  // paths above, renderLabor just above, renderDefaultTakeoff and renderDefaultLabor by the
  // Defaults tab's own block. Lifting the REAL paint() rather than a hand-rolled stand-in is what
  // makes setDefault's optimistic-flip-then-repaint testable at all: a fake paint() that called
  // only SOME of the eight would pass a test that happened to check the one it called and prove
  // nothing about the seven it did not.
  ${fn("paint")}
  // THE MAKE-DEFAULT TOGGLE ITSELF, EXECUTED -- never lifted before this change, because nothing
  // in this harness had exercised the optimistic-flip-then-repaint round trip end to end. This is
  // the function the historical incident was about: for a day the Labor arm of
  // openDefaultAdd was markup with no handler, and every test over it matched the pane for the
  // right data-attribute -- which a dead button carries perfectly. setDefault is the write a
  // working Add or Remove press actually reaches, on all three kinds now, so it is executed here
  // rather than assumed from the markup around it.
  ${fn("setDefault")}
  // THE STARTING-STATE SLIDER'S OWN NETWORK, stubbed like patchDefault above, and its handler
  // lifted so a test PRESSES it: a reserved id goes to the condition default, everything else to
  // the row's default_on.
  async function patchDefaultOn(kind, id, on) {
    LABOR_CALLS.push({ op: "PATCH_DEFAULT_ON", kind: kind, id: id, on: !!on });
    if (LABOR_FAIL.patchDefaultOn) throw new Error("the server said no");
  }
  ${fn("setDefaultOn")}
  // THE REMOVE BUTTON'S ROUTER, AFTER BOTH SAVERS IT CALLS. A reserved id's Remove writes the
  // condition default (setConditionDefault); every other row's writes its favorite (setDefault).
  // (No backticks in these comments: this whole block is one template literal.)
  ${fn("removeDefault")}
  // AFTER BOTH ARMS IT CALLS. This is the routing the Add buttons press, pulled out of the page's
  // anonymous click listener precisely so it can be reached from here -- the same move
  // placeNewAssembly made, and for the same reason.
  ${fn("openDefaultAdd")}
  ${fn("adminList")}
  ${fn("usageFor")}
  ${fn("singular")}
  ${fn("renderRefSection")}
  ${fn("renderVendors")}
  // The Items tab's own search. itemQuery is settable from state so a test can render the
  // filtered view; on the page it is a plain variable that nothing serialises, which is the whole
  // point of it (the dropdown filters deleted on 2026-08-19 were being saved to the server).
  var itemQuery = state.itemQuery === undefined ? "" : state.itemQuery;
  // The facets. The DECLARATION is lifted out of library.js rather than restated, so a fourth
  // facet added there without a default here cannot pass as an empty object.
  ${grab(/^  var FILTERS = \{[^}]*\};$/m, "the FILTERS declaration")}
  if (state.FILTERS) FILTERS = Object.assign(FILTERS, state.FILTERS);
  var filterBarSig = "";
  // EVERY ONE OF THESE IS CALLED BY SOMETHING ALREADY LIFTED. renderItems asks anyFilterActive
  // and filterSummary; visibleItems asks matchesFilters; itemMatches asks parseQuery and
  // termHits. Miss one and the whole file dies on a ReferenceError rather than failing a test.
  ${fn("anyFilterActive")}
  ${fn("parseQuery")}
  ${fn("termHits")}
  ${fn("numberHits")}
  ${fn("conditionHits")}
  ${fn("conditionPhrase")}
  ${fn("matchesFilters")}
  ${fn("filterSummary")}
  ${fn("renderFilterBar")}
  ${fn("visibleItems")}
  ${fn("nameKey")}
  ${fn("duplicateName")}
  // The name a BRAND NEW row is created under. Separate from duplicateName because the first
  // candidate differs: a copy of "Densifier" must never be called "Densifier", and a new material
  // wants the bare "New material" whenever it is free.
  ${fn("nameTaken")}
  ${fn("newMaterialName")}
  ${fn("newRefName")}
  ${fn("itemMatches")}
  // The Assemblies tab's search and its two facets. Lifted here rather than beside renderList
  // because they are the SAME grammar the item box uses - asmTermHits calls termHits, asmMatches
  // calls parseQuery - and this is where that grammar is already in scope.
  //
  // EVERY ONE OF THESE IS REACHED FROM renderList, lifted at the bottom of this block:
  // visibleAssemblies asks asmMatchesFilters (asks asmConditionHits, asmUnit) and asmMatches
  // (asks asmTermHits, parseQuery, termHits, L.findItem); the tail asks anyAsmFilterActive,
  // asmFilterSummary and renderAsmFilterBar. Miss one and every test in test_library_ui.py dies
  // on a ReferenceError with nothing pointing at the cause.
  var asmQuery = state.asmQuery === undefined ? "" : state.asmQuery;
  ${grab(/^  var ASM_FILTERS = \{[^}]*\};$/m, "the ASM_FILTERS declaration")}
  if (state.ASM_FILTERS) ASM_FILTERS = Object.assign(ASM_FILTERS, state.ASM_FILTERS);
  // THE DEFAULT IS LIFTED, not restated. "name" being the default is the decision that keeps the
  // rail looking exactly as it did before this control existed, and a harness that hardcoded
  // "name" here would pass just as happily against a page that shipped with "new".
  ${grab(/^  var ASM_SORT = "[a-z]+";$/m, "the ASM_SORT declaration")}
  if (state.ASM_SORT) ASM_SORT = state.ASM_SORT;
  ${fn("anyAsmFilterActive")}
  ${fn("asmConditionHits")}
  ${fn("asmMatchesFilters")}
  ${fn("asmTermHits")}
  ${fn("asmMatches")}
  ${fn("asmFilterSummary")}
  // THE SORT. Every one of these is reached from visibleAssemblies or renderList, so a missing
  // lift is a ReferenceError that takes every test in test_library_ui.py red at once with nothing
  // pointing at the cause: visibleAssemblies asks sortAssemblies (asks asmSortValue, which asks
  // asmVendorTally, asmOwnerName and asmUnit); renderList asks asmSortLabel (asks asmVendorLabel,
  // asmOwnerName, asmUnit and TW.fmtBizDate).
  ${fn("asmVendorTally")}
  ${fn("asmVendorLabel")}
  ${fn("asmOwnerName")}
  ${fn("asmSortValue")}
  ${fn("sortAssemblies")}
  // Not reached from a renderer — it is the create path's one decision, pulled out of the page's
  // anonymous click listener precisely so it CAN be reached from here.
  ${fn("placeNewAssembly")}
  ${fn("asmSortLabel")}
  ${fn("visibleAssemblies")}
  ${fn("renderAsmFilterBar")}
  // BULK ADD. The modal itself is out of reach here — this DOM stub has no createElement, no focus
  // and no checkbox — so every decision it makes lives in one of these four and is tested directly.
  // Same position this harness already takes with confirmDanger.
  ${grab(/^  var BULK_MAX_LINES = \d+;$/m, "the BULK_MAX_LINES declaration")}
  ${fn("bulkCandidates")}
  ${fn("bulkSelectAllState")}
  ${fn("bulkLinesFor")}
  ${fn("bulkAddRoom")}
  ${fn("itemResultsHtml")}
  ${fn("lineForSave")}
  ${fn("pickerFor")}
  ${fn("itemByName")}
  ${fn("renderList")}
  ${fn("renderPanel")}
  ${fn("refreshNumbers")}
  ${grab(/^  var NUMERIC_ITEM_FIELDS = \[[^\]]*\];$/m, "NUMERIC_ITEM_FIELDS")}
  ${grab(/^  var SERVER_OWNED_ITEM_FIELDS = \[[^\]]*\];$/m, "SERVER_OWNED_ITEM_FIELDS")}
  // The real handler, with only the network stubbed. Everything it touches on the way to the
  // model — the coercion list, the duplicate hint, the queued body — is the code the page runs.
  var QUEUED = [];
  function patchSoon(kind, id, body) { QUEUED.push({ kind: kind, id: id, body: body }); }
  // The pre-edit snapshot the confirmation dialog quotes and Cancel restores from. LIFTED, not
  // stubbed: onItemEdit calls rememberItem on every keystroke, so a stub here would be testing a
  // different function from the one that ships. The DIALOG itself is not reachable from this
  // scope — it fires at flush time inside the real patchSoon, which is stubbed here and exercised
  // in saveScope below, and that split is the whole reason the dialog was not put in onItemEdit.
  var itemBefore = {};
  // LIFTED, not restated: onItemEdit's first line reads the first of these and its snapshot line
  // writes the second, so a rename in library.js has to break this file rather than quietly
  // leave the guard untested.
  ${grab(/^  var itemConfirmOpen = null;$/m, "the itemConfirmOpen declaration")}
  ${grab(/^  var itemLastField = \{\};$/m, "the itemLastField declaration")}
  ${fn("snapshotItem")}
  ${fn("rememberItem")}
  ${fn("onItemEdit")}
  // Test glue, and the only piece in this file: load() replaces DIVISIONS with the Administration
  // tab list, and a test of "an added division reaches the filter chips" has to be able to do the
  // same thing to a scope that is ALREADY built, or renderFilterBar has nothing to notice.
  return { setDivisions: function (list) { DIVISIONS = list; }, renderFilterBar, parseQuery, matchesFilters, anyFilterActive, filterSummary,
           numberHits, FILTERS,
           renderItems, datesHtml, byHtml, renderVendors, renderPanel, renderList, refreshNumbers,
           pickerFor, itemByName, similarNames, pick, adoptSaved,
           onItemEdit, QUEUED, NUMERIC_ITEM_FIELDS, SERVER_OWNED_ITEM_FIELDS, ITEMS, VENDORS,
           itemMatches, itemResultsHtml, lineForSave, visibleItems, duplicateName, nameKey,
           asmQuery, ASM_FILTERS, anyAsmFilterActive, asmMatches, asmMatchesFilters,
           asmConditionHits, asmTermHits, asmFilterSummary, visibleAssemblies,
           renderAsmFilterBar,
           ASM_SORT, asmVendorTally, asmVendorLabel, asmOwnerName, asmSortValue,
           sortAssemblies, asmSortLabel, placeNewAssembly,
           // THE ARRAY ITSELF, not a copy, so a test can put a row into the model the renderer
           // reads and then render — which is the only way to prove the prepend and the
           // pass-through default work together rather than each in isolation.
           ASMS,
           newMaterialName, newRefName,
           bulkCandidates, bulkSelectAllState, bulkLinesFor, bulkAddRoom, BULK_MAX_LINES,
           // The Defaults tab's Takeoff list, EXECUTED rather than read. GLOBAL_MARKUP is handed
           // in so a test can supply the Markup page's answer without a second fetch stub.
           renderDefaultTakeoff, takeoffConditionDefaults, takeoffDefaultGroups,
           feesDefaultRow, saveFeesDefault, FEES_CALLS,
           feesRuleNow: function () { return FEES_RULE; },
           // THE CONDITIONS, EXECUTED. conditionPriceCell draws one row's priced cell;
           // setConditionDefault is what BOTH directions call now -- Remove on a listed row and
           // Add on a removed one. COND_CALLS is what would have gone to the server, and
           // condDefaultsNow reads the list BACK -- the handler reassigns it (a new array, not a
           // splice), so a test handed the value itself would be reading the one from before the
           // press it is testing.
           setConditionDefault, COND_CALLS,
           // THE MATERIAL ROW'S OWN PIECES, so a condition row can be compared with what a material
           // row is drawn from rather than with a copy of it typed into this file.
           materialDefaultRow, conditionDefaultRow, defaultRowActions, removeDefault, isReservedItem,
           RESERVED_ITEM_CONDITION, focusItemRow,
           itemQueryNow: function () { return itemQuery; },
           condDefaultsNow: function () { return COND_DEFAULTS; },
           setCondDefaults: function (c) { COND_DEFAULTS = c; },
           // THE ADD PATH, EXECUTED. A test that only read the markup could not tell a
           // wired button from a dead one, and for two days could not.
           defaultCandidates, renderDefaultSearch, setDefaultQuery, openDefaultBrowse,
           placeDefaultSearch, closeDefaultSearch, onDefaultSearchKey,
           appliesToWorkType, workTypeLabel, WORK_TYPES,
           // THE PER-ROW CHIPS, EXECUTED. workTypeCell draws them, setRowWorkType is what a press
           // runs, and WT_CALLS is the body that would have gone to the server -- the three
           // together are the difference between a filter that works and five chips over a column
           // nothing could write. Note the two different work-type setters: setWorkType below
           // moves the TAB, setRowWorkType scopes a ROW.
           workTypeCell, setRowWorkType, WT_CALLS,
           setWorkType: function (wt) { DEFAULT_WT = wt; },
           workTypeNow: function () { return DEFAULT_WT; },
           // THE LABOR DEFAULTS, EXECUTED. The add button had no handler for a day and this
           // file could not tell: a source assertion cannot separate a wired control from a
           // dead one, which is exactly how it shipped green.
           renderDefaultLabor, resetTravelDefault, laborRowActions,
           LABOR_UNITS,
           LABOR_CALLS,
           setDefault, setDefaultOn, defaultSlider, paint,
           openDefaultAdd,
           // THE LABOR TAB ITSELF, EXECUTED -- creation, editing and the delete guard, on the
           // tab this whole change was for. QUEUED is already exposed above, beside onItemEdit --
           // the same capture array, shared by every kind that calls patchSoon.
           onLaborEdit, toggleLaborMore, focusLaborRow, renderLabor, NUMERIC_LABOR_FIELDS,
           addLaborLine, removeLaborLine,
           setPending: function (k, v) { pendingPatch[k] = v; },
           pendingNow: function () { return pendingPatch; },
           // GETTERS, because the delete handler REASSIGNS LABOR (filter, not splice) -- a test
           // handed the value itself would be reading the one from before the press it is
           // testing.
           laborNow: function () { return LABOR; },
           laborMoreOpenNow: function () { return laborMoreOpen; },
           setGlobalMarkup: function (g) { GLOBAL_MARKUP = g; },
           snapshotOf: function (id) { return itemBefore[id]; } };
`);

// Two materials: a legacy pack-of-one and a five-gallon pail, so the pack column has something to
// be wrong about. Coverage, waste and roundup live on the MATERIAL now (Hanz, 2026-09-21: "for
// the materials, we must have coverage per unit, waste factor, roundup... And then it gets pulled
// in to assemblies instead of it being in assemblies") — set here, on ITEMS. The ASMS lines below
// carry deliberately WRONG, disagreeing values: if priceLine ever reads a line's own numbers
// instead of the material's, the two quantity labels these fixtures drive flip to the other
// line's shape rather than quietly matching by coincidence.
const ITEMS = [
  { id: "i1", name: "OPF", category: "Epoxy", unit: "Gal", buy_qty: 1, unit_cost: 85.3827,
    coverage: 275, waste_pct: 5, roundup: true, vendor: "Sherwin-Williams", notes: "",
    created_at: "2026-08-01T14:30:00Z", cost_updated_at: null },
  { id: "i2", name: "OPF Primer", category: "Polished Concrete", unit: "Gallon", buy_qty: 5,
    unit_cost: 426.91, coverage: 275, waste_pct: 0, roundup: false, vendor: "Gone Supply Co",
    notes: "", created_at: "2026-08-02T09:00:00Z", cost_updated_at: "2026-08-14T21:15:00Z" },
];
const ASMS = [{
  id: "a1", name: "MACRO Flake", unit: "SF",
  lines: [
    { role: "1st BC", item_id: "i1", coverage: 999, waste_pct: 0, roundup: false, note: "" },
    { role: "", item_id: "i2", coverage: 999, waste_pct: 99, roundup: true, note: "" },
  ],
}];
const VENDORS = [{ id: "v1", name: "Sherwin-Williams", notes: "KC branch" },
                 { id: "v2", name: "Sika", notes: "" }];

function build(overrides, docSelectors) {
  const d = makeDom();
  const st = Object.assign({
    ITEMS: JSON.parse(JSON.stringify(ITEMS)),
    ASMS: JSON.parse(JSON.stringify(ASMS)),
    VENDORS: JSON.parse(JSON.stringify(VENDORS)),
    DIVISION_REFS: [{ id: "d1", name: "Polished Concrete", notes: "" },
                    { id: "d2", name: "Epoxy", notes: "" },
                    { id: "d3", name: "Gypsum Underlayment", notes: "" }],
    UNIT_REFS: [{ id: "u1", name: "Gallon", notes: "" },
                { id: "u2", name: "Kit", notes: "" },
                { id: "u3", name: "Bag", notes: "" }],
    VENDOR_USE: { "sherwin-williams": 1, sika: 0 },
    DIVISION_USE: { epoxy: 1, "polished concrete": 1 },
    UNIT_USE: { gal: 1, gallon: 1 },
    ADMIN: false, openId: "a1",
  }, overrides || {});
  // Marked rather than formatted, so an assertion cannot pass by accident on a date that happens
  // to read the same in UTC and in Central. The dev box clock runs ~13 hours ahead of Chicago and
  // these are project dates: the ONLY correct renderer is TW's, and this proves the page reached
  // for it rather than for `new Date(...).toLocaleDateString()`.
  const TW = Object.assign({ fmtBizDateTime: (iso) => "BIZ(" + iso + ")",
                             fmtBizDate: (iso) => "BIZDAY(" + iso + ")" },
                           // A scenario that presses a delete answers its dialog through this --
                           // the Labor tab's removeLaborLine asks TW.confirmDanger first.
                           st.TW || {});
  const doc = makeDocument(docSelectors || []);
  const api = scope(L, d.el, TW, st, doc, CRM, WT);
  d.el("area").value = "2875";
  return { api, dom: d, st, doc };
}

const out = {};

// ── Items: the columns Hanz asked for, and the ones he asked to lose ─────────
{
  const { api, dom: d } = build();
  api.renderItems();
  const row = d.nodes["items-body"].innerHTML.split("</tr>")[0];
  out.items = {
    // Present. The division cell is now a chip strip (see out.divisions below); the checkbox
    // markup this used to pin was replaced on 2026-08-24 at Hanz's request.
    hasDivisionChips: /class="division-chips"/.test(row) && /data-f="divisions"/.test(row),
    divisionOptions: divisionCellOf(row)
      .split('data-div="').slice(1).map((o) => o.split('"')[0]),
    hasBuyQty: /data-f="buy_qty"/.test(row),
    hasUnitDropdown: /<select data-f="unit"/.test(row),
    unitOptions: (row.match(/<select data-f="unit"[\s\S]*?<\/select>/) || [""])[0]
      .split("<option").slice(1).map((o) => (/>([^<]*)</.exec(o) || ["", ""])[1]),
    hasVendorDropdown: /<select data-f="vendor"/.test(row),
    costWearsADollarSign: /<span class="money"><span>\$<\/span><input data-f="unit_cost"/.test(row),
    // Back, 2026-09-22: coverage, waste and roundup moved from the assembly line onto the
    // material — see the ITEMS/ASMS comment above. The material name is also no longer a bare
    // text box (see nameOffersAutosuggest below).
    hasCoverage: /data-f="coverage"/.test(d.nodes["items-body"].innerHTML),
    hasWaste: /data-f="waste_pct"/.test(d.nodes["items-body"].innerHTML),
    hasRoundupCheckbox: /type="checkbox" data-f="roundup"/.test(d.nodes["items-body"].innerHTML),
    nameOffersAutosuggest: /data-f="name"[^>]*list="dl-materials"/.test(row),
    datalistFilled: /value="OPF"/.test(d.nodes["dl-materials"].innerHTML) &&
      /value="OPF Primer"/.test(d.nodes["dl-materials"].innerHTML),
    count: d.nodes["n-items"].textContent,
  };
  // A legacy unit ("Gal") is not on the offered list and must survive being rendered.
  const legacyUnitSelect = (row.match(/<select data-f="unit"[\s\S]*?<\/select>/) || [""])[0];
  out.items.legacyUnitKept = /<option value="Gal" selected>Gal<\/option>/.test(legacyUnitSelect);
  // Same for a vendor that has left the list: the item still records where it came from.
  const secondRow = d.nodes["items-body"].innerHTML.split("</tr>")[1];
  const vendSel = (secondRow.match(/<select data-f="vendor"[\s\S]*?<\/select>/) || [""])[0];
  out.items.offListVendorKept = /<option value="Gone Supply Co" selected>/.test(vendSel);
  out.items.offListVendorNotDuplicated =
    (vendSel.match(/<option value="Gone Supply Co"/g) || []).length === 1;
}

// ── EXECUTED: the division chips ─────────────────────────────────────────────
// Hanz, 2026-08-24: "For the [divisions] can we have it in just one row? Also instead of a
// checkbox please pick a better UI that allows a material to have multiple divisions but they show
// up in one row." Three stacked checkbox labels made every row three lines tall.
//
// EXECUTED, because every interesting failure here is invisible to a grep:
//   * "two divisions render as on" is about which inputs carry `checked`, which depends on
//     itemDivisions, the case-folding, and the legacy `category` fallback all agreeing.
//   * "toggling one leaves the other alone" runs the REAL onItemEdit against a row parsed from the
//     REAL rendered markup, so a renamed attribute breaks the selector rather than the assertion.
//   * "one line for three" is a width fact. The old control was `flex-wrap:wrap` too — it stacked
//     because the box was 170px. Asserting `display:flex` alone would have passed on the bug.
{
  const twoDivs = build({ ITEMS: [{ id: "i1", name: "OPF", divisions: ["Epoxy", "polished concrete"],
    unit: "Gallon", buy_qty: 5, unit_cost: 100, coverage: 275, vendor: "Sika",
    created_at: "2026-08-01T14:30:00Z", cost_updated_at: null }] });
  twoDivs.api.renderItems();
  const cell = divisionCellOf(twoDivs.dom.nodes["items-body"].innerHTML.split("</tr>")[0]);
  const chips = (cell.match(/<label class="dchip"[\s\S]*?<\/label>/g) || []);
  const inputTags = cell.match(/<input[^>]*data-f="divisions"[^>]*>/g) || [];

  out.divisions = {
    // MULTI-SELECT, AND IT LOOKS IT: two chips on at once, each an independent checkbox inside a
    // group. Nothing here is a radio, and nothing here is a select.
    group: /<div class="division-chips" role="group" aria-label="Divisions">/.test(cell),
    chipCount: chips.length,
    onOff: inputTags.map((t) => [(/data-div="([^"]*)"/.exec(t) || ["", ""])[1], / checked>/.test(t)]),
    noRadios: !/type="radio"/.test(cell),
    // KEYBOARD AND SCREEN READER: a real checkbox, so Tab and Space and the announced state come
    // for free. Each carries its own accessible name, so "checked, Epoxy" is what gets read out
    // rather than "checked" on an unnamed box.
    everyChipIsACheckbox: inputTags.length > 0 && inputTags.every((t) => /type="checkbox"/.test(t)),
    everyChipHasAnAccessibleName: inputTags.length > 0 && inputTags.every((t) => {
      const div = (/data-div="([^"]*)"/.exec(t) || ["", ""])[1];
      return (/aria-label="([^"]*)"/.exec(t) || ["", ""])[1] === div;
    }),
    // The state mark must not end up in that name, which is why it is hidden from the tree.
    markIsHiddenFromTheTree: /<span class="dchip-mark" aria-hidden="true">/.test(cell),
    // The full name is always available even when the visible text is clipped.
    everyChipCarriesItsFullNameInATitle: chips.length > 0 && chips.every((c) => {
      const t = (/<label class="dchip" title="([^"]*)"/.exec(c) || ["", ""])[1];
      return t === (/data-div="([^"]*)"/.exec(c) || ["", "x"])[1];
    }),
    // THE SAVE CONTRACT IS UNCHANGED: still data-f="divisions" + data-div="NAME" on the input.
    // The length guard matters — `every` on an empty list is true, so a renamed attribute would
    // pass this while onItemEdit's own selector found nothing.
    contractUnchanged: inputTags.length === 3 &&
      inputTags.every((t) => /data-f="divisions"/.test(t) && /data-div="/.test(t)),
  };

  // A DIVISION ADDED ON THE ADMINISTRATION TAB reaches the chips. The step that turns the fetched
  // refs into the offered list is LIFTED OUT OF load() rather than restated here, so deleting it
  // there breaks this instead of leaving a test that agrees with itself.
  const REFS = [{ id: "d1", name: "Polished Concrete", notes: "" },
                { id: "d2", name: "Epoxy", notes: "" },
                { id: "d3", name: "Gypsum Underlayment", notes: "" },
                { id: "d4", name: "Sealer & Traffic Coatings", notes: "" }];
  const offeredList = new Function("DIVISION_REFS", "DEFAULT_DIVISIONS", `
    "use strict";
    var DIVISIONS;
    ${grab(/^\s*DIVISIONS = \(DIVISION_REFS\.length \?[^\n]*$/m, "the DIVISIONS assignment in load()")}
    return DIVISIONS;
  `);
  const custom = build({
    DIVISION_REFS: REFS,
    DIVISIONS: offeredList(REFS, ["Polished Concrete", "Epoxy", "Gypsum Underlayment"]),
    ITEMS: [{ id: "i1", name: "OPF", divisions: ["Sealer & Traffic Coatings"], unit: "Gallon",
              buy_qty: 1, unit_cost: 1, coverage: 275, vendor: "", created_at: null,
              cost_updated_at: null }],
  });
  custom.api.renderItems();
  const customCell = divisionCellOf(custom.dom.nodes["items-body"].innerHTML.split("</tr>")[0]);
  out.divisions.customIsOffered =
    (customCell.match(/data-div="([^"]*)"/g) || []).map((m) => m.slice(10, -1));
  // Escaped, not injected — a division name is free text somebody typed on the Administration tab.
  out.divisions.customIsEscaped = /data-div="Sealer &amp; Traffic Coatings"/.test(customCell) &&
    !/data-div="Sealer & Traffic/.test(customCell);
  out.divisions.customRendersAsOn = / checked>/.test(
    (customCell.match(/<input[^>]*data-div="Sealer &amp; Traffic Coatings"[^>]*>/) || [""])[0]);
  // And a name only an OLD ITEM holds, which is not on any list at all: still offered, still
  // correctable. A division can be deleted from the Administration tab without rewriting items.
  const orphan = build({
    ITEMS: [{ id: "i1", name: "OPF", divisions: ["Terrazzo Restoration Systems"], unit: "Gallon",
              buy_qty: 1, unit_cost: 1, coverage: 275, vendor: "", created_at: null,
              cost_updated_at: null }],
  });
  orphan.api.renderItems();
  const orphanCell = divisionCellOf(orphan.dom.nodes["items-body"].innerHTML.split("</tr>")[0]);
  out.divisions.offListItemValueStillOffered =
    (orphanCell.match(/data-div="([^"]*)"/g) || []).map((m) => m.slice(10, -1));

  // TOGGLING ONE LEAVES THE OTHERS ALONE. The browser flips the box, then the handler reads the
  // row — the same order a click on the label produces.
  const row = chipRowFromHtml("i1", cell);
  const target = row.inputs.filter((x) => x.div === "Epoxy")[0];
  target.checked = false;
  twoDivs.api.onItemEdit({ target: target });
  out.divisions.afterTurningEpoxyOff = {
    model: twoDivs.api.ITEMS[0].divisions.slice(),
    category: twoDivs.api.ITEMS[0].category,
    queued: twoDivs.api.QUEUED.map((q) => q.kind + " " + JSON.stringify(q.body)),
  };
  // And back on, plus a third: two selected at once is legal and stays legal.
  target.checked = true;
  row.inputs.filter((x) => x.div === "Gypsum Underlayment")[0].checked = true;
  twoDivs.api.onItemEdit({ target: target });
  out.divisions.afterTurningTwoMoreOn = twoDivs.api.ITEMS[0].divisions.slice();
  // Emptying it is allowed: a material can be waiting to be filed.
  row.inputs.forEach((x) => { x.checked = false; });
  twoDivs.api.onItemEdit({ target: row.inputs[0] });
  out.divisions.canBeEmptied = twoDivs.api.ITEMS[0].divisions.length === 0 &&
    twoDivs.api.QUEUED[twoDivs.api.QUEUED.length - 1].body.divisions.length === 0;

  // ── ONE ROW. The width facts, read off the real stylesheet ─────────────────
  const rule = (sel) => (new RegExp(sel.replace(/[.>*+?^${}()|[\]\\]/g, "\\$&") +
    "\\s*\\{[^}]*\\}").exec(html) || [""])[0];
  const strip = rule(".division-chips");
  const face = rule(".dchip-f");
  const px = (re, s) => Number((re.exec(s) || [0, 0])[1]);
  const stripMin = px(/min-width:(\d+)px/, strip);
  const stripMax = px(/max-width:(\d+)px/, strip);
  const fontPx = px(/font:\s*\d+\s+([\d.]+)px/, face);
  const padParts = ((/padding:([^;]+);/.exec(face) || ["", "0"])[1]).trim().split(/\s+/)
    .map((v) => parseFloat(v));
  const padX = padParts.length >= 4 ? padParts[1] + padParts[3]
             : padParts.length === 2 ? padParts[1] * 2 : padParts[0] * 2;
  const innerGap = px(/gap:(\d+)px/, face);
  const markW = px(/width:(\d+)px/, rule(".dchip-mark"));
  const stripGap = px(/gap:(\d+)px/, strip);
  // 0.55em per character. A UI sans at this size averages nearer 0.52em over mixed-case text, so
  // this over-estimates slightly on purpose: the question is whether the column has room to spare,
  // and a floor-value estimate would let a too-narrow column pass and wrap in the browser.
  const chipWidth = (name) => name.length * fontPx * 0.55 + padX + innerGap + markW + 2;
  const three = ["Polished Concrete", "Epoxy", "Gypsum Underlayment"];
  const needFor = (names) => names.reduce((s, n) => s + chipWidth(n), 0) +
    stripGap * Math.max(0, names.length - 1);
  out.divisions.width = {
    fontPx: fontPx, stripMin: stripMin, stripMax: stripMax,
    // Side by side, not stacked, and a name never breaks across two lines.
    stripIsAFlexRow: /display:flex/.test(strip) && /flex-wrap:wrap/.test(strip),
    chipIsInline: /display:inline-flex/.test(face) && /white-space:nowrap/.test(face),
    // The three real divisions fit on ONE line.
    neededForThree: Math.round(needFor(three)),
    threeFitOnOneLine: needFor(three) <= stripMin,
    // Six and ten WRAP rather than widen the table: the column is capped, so the strip grows
    // downwards. Two lines at six, four at ten.
    neededForSix: Math.round(needFor(three.concat(three))),
    sixWraps: needFor(three.concat(three)) > stripMax,
    tenWraps: needFor(three.concat(three, three, ["Sealer"])) > stripMax,
    cappedSoTheTableCannotStretch: stripMax > 0 && stripMax < needFor(three.concat(three)),
    // A long custom name keeps enough of itself to stay distinct from the next one along.
    textClampChars: px(/max-width:(\d+)ch/, rule(".dchip-t")),
    textClampEllipsises: /text-overflow:ellipsis/.test(rule(".dchip-t")),
  };

  // ── the state is not colour alone, and the input is still operable ─────────
  const onFace = rule(".dchip > input:checked + .dchip-f");
  const hiddenInput = rule(".dchip > input");
  out.divisions.state = {
    // The pill fills in when it is on, the way the CRM drawer's notification chips do.
    onHasItsOwnFill: /background:/.test(onFace) && /border-color:/.test(onFace),
    // SHAPE, not just hue: the mark differs between the two states, so the on chips can be counted
    // by somebody who cannot separate the green from the grey.
    offMark: (/content:"([^"]*)"/.exec(rule(".dchip-mark::before")) || ["", ""])[1],
    onMark: (/content:"([^"]*)"/.exec(
      rule(".dchip > input:checked + .dchip-f .dchip-mark::before")) || ["", ""])[1],
    // Hidden from sight, NOT from the keyboard. display:none or visibility:hidden would take the
    // control out of the tab order and leave Space nothing to press.
    inputIsClippedNotRemoved: /clip-path:inset\(50%\)/.test(hiddenInput) &&
      !/display:none|visibility:hidden/.test(hiddenInput),
    focusRingOnTheFace: /outline:/.test(rule(".dchip > input:focus-visible + .dchip-f")),
    // The control the old markup used is gone, along with its stacking box.
    oldCheckboxStyleGone: !/\.division-picks/.test(html) && !/class="division-picks"/.test(src),
  };
}

// ── the price date lands on screen without a reload ──────────────────────────
{
  // The selector list is taken from what renderItems ACTUALLY emits, so renaming the cell's class
  // breaks this rather than quietly making the repaint a no-op.
  const rendered = build();
  rendered.api.renderItems();
  const cellClass = /<td class="([a-z]+)">\s*<div class="dates"/.exec(
    rendered.dom.nodes["items-body"].innerHTML);
  const sel = '[data-item="i1"] .' + (cellClass ? cellClass[1] : "MISSING");

  const b = build({}, [sel]);
  // The server replies to a cost PATCH with the row it stored: same updated_at bump, plus a
  // cost_updated_at that only it can decide.
  b.api.adoptSaved("items", { id: "i1", updated_at: "2026-08-15T00:00:01Z",
                              cost_updated_at: "2026-08-15T00:00:01Z" });
  const wrote = b.doc.writes;
  out.priceDate = {
    cellClass: cellClass ? cellClass[1] : null,
    modelAdopted: b.api.ITEMS[0].cost_updated_at,
    repainted: wrote.length === 1,
    repaintedSelector: wrote.length ? wrote[0].sel : null,
    repaintShowsTheNewDate: wrote.length
      ? /BIZ\(2026-08-15T00:00:01Z\)/.test(wrote[0].html) : false,
    repaintDroppedTheNeverLine: wrote.length
      ? !/not since we started tracking/.test(wrote[0].html) : false,
  };

  // REVERSED on 2026-09-04, deliberately, and this is the reasoning so nobody "fixes" it back.
  //
  // This used to assert that a patch which did not change the cost must NOT repaint, and that was
  // right while the cell held only `created_at` and `cost_updated_at` — `updated_at` moved on
  // every write and changed nothing on screen, so repainting was pure churn.
  //
  // The cell now carries "Edited <updated_at> by <updated_by>", so `updated_at` is exactly what
  // one of its three lines quotes. Suppressing the repaint would leave the Edited line showing the
  // PREVIOUS edit time and the previous editor until F5 — the identical failure the price date had
  // one column over, which is what the original version of this scenario was written to catch.
  //
  // What must still hold is that the repaint is DRIVEN BY A CHANGE, not fired unconditionally:
  // `sameStampNoRepaint` below is the half that keeps the churn honest.
  const quiet = build({}, [sel]);
  quiet.api.adoptSaved("items", { id: "i1", updated_at: "2026-08-15T00:00:02Z",
                                  cost_updated_at: null });
  out.priceDate.costlessPatchStillRepaints = quiet.doc.writes.length === 1;
  out.priceDate.costlessRepaintKeepsNeverLine = quiet.doc.writes.length
    ? /not since we started tracking/.test(quiet.doc.writes[0].html) : false;

  // A reply that moved NOTHING must still not repaint. Same stamps in, no write out — this is the
  // assertion that stops the reversal above becoming "repaint on every reply".
  const same = build({}, [sel]);
  const before = same.api.ITEMS[0];
  same.api.adoptSaved("items", { id: "i1", updated_at: before.updated_at,
                                 cost_updated_at: before.cost_updated_at,
                                 updated_by: before.updated_by });
  out.priceDate.sameStampNoRepaint = same.doc.writes.length === 0;

  // A reply that omits updated_by entirely must not blank a name we already hold.
  const partial = build({}, [sel]);
  partial.api.ITEMS[0].updated_by = "hanz@wetreadwell.com";
  partial.api.adoptSaved("items", { id: "i1", updated_at: "2026-08-15T00:00:04Z",
                                    cost_updated_at: null });
  out.priceDate.missingEditorDoesNotBlankIt =
    partial.api.ITEMS[0].updated_by === "hanz@wetreadwell.com";
  out.priceDate.quietPatchStillBumpedVersion =
    quiet.api.ITEMS[0].updated_at === "2026-08-15T00:00:02Z";

  // An assembly save must never reach into the items table.
  const asm = build({}, [sel]);
  asm.api.adoptSaved("assemblies", { id: "a1", updated_at: "2026-08-15T00:00:03Z" });
  out.priceDate.assemblySaveDoesNotRepaintItems = asm.doc.writes.length === 0;
}

// ── the vendor dropdown offers more than the curated list ────────────────────
{
  // No curated vendors at all — a fresh install, or before an admin has got to it. The estimator
  // must still be able to record where a material came from, or a dropdown replaces a text box
  // with nothing in it and only two people in the company can fix that.
  const bare = build({ VENDORS: [] });
  bare.api.renderItems();
  const rows = bare.dom.nodes["items-body"].innerHTML;
  const sel = (i) =>
    (rows.split("</tr>")[i].match(/<select data-f="vendor"[\s\S]*?<\/select>/) || [""])[0];
  // Same supplier, two spellings on two items: the curated one wins and the other is not offered
  // back, or the list would re-create the duplication it exists to end.
  const messy = build({
    VENDORS: [{ id: "v1", name: "Sherwin-Williams", notes: "" }],
    ITEMS: JSON.parse(JSON.stringify(ITEMS)).map((it, i) =>
      Object.assign(it, { vendor: i === 0 ? "sherwin-williams" : "Gone Supply Co" })),
  });
  messy.api.renderItems();
  const messyOpts = (messy.dom.nodes["items-body"].innerHTML
    .match(/<select data-f="vendor"[\s\S]*?<\/select>/) || [""])[0]
    .split("<option").slice(1).map((o) => (/value="([^"]*)"/.exec(o) || ["", ""])[1]);
  out.vendorOptions = {
    withNoCuratedList: [0, 1].map((i) => /<option value="Sherwin-Williams"/.test(sel(i)) ||
      /<option value="Gone Supply Co"/.test(sel(i))),
    messyOpts,
    curatedSpellingWins: messyOpts.indexOf("Sherwin-Williams") !== -1 &&
      messyOpts.indexOf("sherwin-williams") === -1,
    uncuratedStillOffered: messyOpts.indexOf("Gone Supply Co") !== -1,
  };
}

// ── the duplicate hint ───────────────────────────────────────────────────────
{
  const { api } = build();
  out.dupes = {
    // "OPF" is a prefix of "OPF Primer" — the exact way one product gets entered twice.
    onSimilar: api.similarNames("OPF Prim", "i1"),
    // Never itself, or every row would accuse itself of being a duplicate the moment it was typed.
    notItself: api.similarNames("OPF", "i1").indexOf("OPF") === -1,
    // Two characters is not yet a name.
    quietWhileTyping: api.similarNames("OP", "zz"),
    unrelated: api.similarNames("Sika Level 125", "zz"),
  };
}

// ── the dates: NO SCENARIO ANY MORE ──────────────────────────────────
//
// The History column came off the Items table on 2026-09-18 ("too much clutter"), and
// datesHtml/byHtml/paintDates drew only into it. The COLUMNS are still stored and still
// returned -- the Added and Price-updated sorts order by them, and those scenarios are
// further down this file, untouched. What went is the rendering nobody reads.

// ── authorship: NO SCENARIO ANY MORE ────────────────────────────────
//
// It asserted who filed and who edited a material, drawn by datesHtml into the History
// column -- and that column came off the Items table on 2026-09-18. owner_email and
// updated_by are still stored and still returned; nothing on screen prints them now.

// ── the editor is adopted off the reply, not left until F5 ───────────────────
// The same failure the price date had one column over: an ordinary edit moves updated_at and
// updated_by but leaves cost_updated_at alone, so a repaint gated on the price date alone would
// leave the Edited line quoting the PREVIOUS editor until a reload.
{
  // The selector comes from what renderItems ACTUALLY emits, same as the price-date scenario, so
  // renaming the cell's class breaks this rather than quietly making the repaint a no-op.
  const rendered = build();
  rendered.api.renderItems();
  const cellClass = /<td class="([a-z]+)">\s*<div class="dates"/.exec(
    rendered.dom.nodes["items-body"].innerHTML);
  const sel = '[data-item="i1"] .' + (cellClass ? cellClass[1] : "MISSING");

  const b = build({}, [sel]);
  b.api.ITEMS[0].created_at = "2026-08-02T09:00:00Z";
  b.api.ITEMS[0].updated_at = "2026-08-02T09:00:00Z";
  b.api.ITEMS[0].updated_by = "";

  // Somebody else's edit comes back on the reply to our own PATCH.
  b.api.adoptSaved("items", {
    id: "i1",
    updated_at: "2026-09-04T18:00:00Z",
    cost_updated_at: b.api.ITEMS[0].cost_updated_at,
    updated_by: "hanz@wetreadwell.com",
  });

  out.adoptEditor = {
    editorAdopted: b.api.ITEMS[0].updated_by === "hanz@wetreadwell.com",
    repainted: b.doc.writes.length === 1,
    // The repaint carries the new NAME, so this is the whole round trip and not just a redraw.
    repaintNamesTheEditor: b.doc.writes.length
      ? /by <b>Hanz<\/b>/.test(b.doc.writes[0].html) : false,
    // And it stopped saying the row was untouched.
    repaintDroppedNotEditedSince: b.doc.writes.length
      ? !/not edited since/.test(b.doc.writes[0].html) : false,
  };

  // THE EDITOR ALONE, with both dates held still. Added because a mutation run proved the
  // scenario above could not see the editor branch's repaint at all: it moved updated_at too, so
  // deleting the branch's `moved = true` still repainted via the date and every test stayed green.
  // The two columns are stamped in the same write in practice, which is exactly why a test that
  // moves both cannot tell which one is driving.
  // The row must ALREADY read as edited, or holding the dates still makes it "not edited since"
  // and the Edited line correctly names nobody — which is the row contradicting the scenario, not
  // the code failing. Distinct created_at and updated_at up front; only updated_by moves.
  const only = build({}, [sel]);
  only.api.ITEMS[0].created_at = "2026-08-02T09:00:00Z";
  only.api.ITEMS[0].updated_at = "2026-09-01T16:00:00Z";
  only.api.ITEMS[0].updated_by = "";
  only.doc.writes.length = 0;
  only.api.adoptSaved("items", {
    id: "i1",
    updated_at: "2026-09-01T16:00:00Z",
    cost_updated_at: only.api.ITEMS[0].cost_updated_at,
    updated_by: "kyle.loseke@wetreadwell.com",
  });
  out.adoptEditor.editorAloneRepaints = only.doc.writes.length === 1;
  out.adoptEditor.editorAloneNamesTheEditor = only.doc.writes.length
    ? /by <b>Kyle Loseke<\/b>/.test(only.doc.writes[0].html) : false;
}

// ── Vendors: admin edits, everybody else reads ───────────────────────────────
{
  const plain = build({ ADMIN: false });
  plain.api.renderVendors();
  const asUser = plain.dom.nodes["divisions-body"].innerHTML +
    plain.dom.nodes["units-body"].innerHTML + plain.dom.nodes["vendors-body"].innerHTML;
  const admin = build({ ADMIN: true });
  admin.api.renderVendors();
  const asAdmin = admin.dom.nodes["divisions-body"].innerHTML +
    admin.dom.nodes["units-body"].innerHTML + admin.dom.nodes["vendors-body"].innerHTML;
  out.vendors = {
    userGetsNoInputs: !/<input/.test(asUser),
    userGetsNoDeleteButton: !/data-del-ref/.test(asUser),
    userStillSeesTheNames: /Polished Concrete/.test(asUser) && /Gallon/.test(asUser) &&
      /Sherwin-Williams/.test(asUser) && /Sika/.test(asUser),
    userToldWhoToAsk: plain.dom.nodes["vendors-ro"].hidden === false,
    userNotOfferedAddButtons: !/data-add-ref/.test(asUser),
    adminGetsInputs: /<input data-rf="name"/.test(asAdmin) && /<input data-rf="notes"/.test(asAdmin),
    adminGetsDelete: /data-del-ref="vendors"/.test(asAdmin) &&
      /data-del-ref="divisions"/.test(asAdmin) && /data-del-ref="units"/.test(asAdmin),
    adminNotShownTheReadOnlyNote: admin.dom.nodes["vendors-ro"].hidden === true,
    adminOfferedAdd: true,
    // How many materials name each vendor, so a delete can say what it affects.
    usageShown: /<td class="n">1<\/td>/.test(asAdmin),
    sectionOrder: ["divisions-body", "units-body", "vendors-body"].every((id) => !!admin.dom.nodes[id]),
  };
}

// ── the assembly line: Role gone, waste and roundup in, picker searchable ────
{
  const { api, dom: d } = build();
  api.renderPanel();
  const body = d.nodes["lines-body"].innerHTML;
  const firstRow = body.split("</tr>")[0];
  const tds = firstRow.split("<td").slice(1);
  const qtyIdx = tds.findIndex((t) => /class="qty"/.test(t));
  const costIdx = tds.findIndex((t, i) => i > qtyIdx && /class="qty"/.test(t));
  out.lines = {
    roleColumnGone: !/data-lf="role"/.test(body),
    // Coverage, waste and roundup are pulled in from the material now (Hanz, 2026-09-22) — no
    // editable input or checkbox anywhere in the table, on either row.
    noEditableWasteOnTheLine: !/data-lf="waste_pct"/.test(body),
    noEditableRoundupOnTheLine: !/type="checkbox" data-lf="roundup"/.test(body),
    // Both rows must show THEIR OWN material's numbers even though the fixture's ASMS lines
    // (above) carry deliberately wrong ones — proof the material wins over a disagreeing line.
    firstRowCoverage: (/<td class="n cov derived"><div class="line-primary">([^<]*)</
      .exec(firstRow) || ["", ""])[1],
    firstRowWaste: (/<td class="n derived"><div class="line-primary">([^<]*)</
      .exec(firstRow) || ["", ""])[1],
    firstRowRoundup: (/<td class="ru derived"><div class="line-primary">([^<]*)</
      .exec(firstRow) || ["", ""])[1],
    secondRowCoverage: (/<td class="n cov derived"><div class="line-primary">([^<]*)</
      .exec(body.split("</tr>")[1]) || ["", ""])[1],
    secondRowWaste: (/<td class="n derived"><div class="line-primary">([^<]*)</
      .exec(body.split("</tr>")[1]) || ["", ""])[1],
    secondRowRoundup: (/<td class="ru derived"><div class="line-primary">([^<]*)</
      .exec(body.split("</tr>")[1]) || ["", ""])[1],
    // A search box with autofill, not a <select>: the list is going to get long.
    pickerIsSearchable: /<div class="item-picker">/.test(firstRow) &&
      /data-lf="item_search"/.test(firstRow),
    // ONE LINE ITEM, ONE ROW. No filter dropdowns and no "Divisions" label inside the row — those
    // belong to the header, and having them in the cell made one line item a tall block.
    pickerHasNoInRowFilters: !/item_division_filter|item_vendor_filter/.test(body) &&
      !/<span>Divisions<\/span>/.test(body),
    // Closed, the box shows the chosen item rather than an open list of candidates.
    pickerShowsTheCurrentMaterial: /data-lf="item_search" value="OPF"/.test(firstRow),
    pickerStartsClosed: !/class="item-results"/.test(body),
    rowCount: (body.match(/<tr/g) || []).length,
    pickerIsNotASelect: !/<select data-lf="item_id"/.test(body),
    rowCellsTopAligned: /\.lines td \{ vertical-align:top; \}/.test(html),
    primaryLineCount: (firstRow.match(/class="line-primary/g) || []).length,
    deleteControlAligned: /\.lines td > \.icon \{[^}]*min-height:32px/.test(html),
    tdCount: tds.length,
    qtyIdx, costIdx,
    // The two modes, rendered: whole packs vs the fraction.
    firstQtyLabel: (/<span class="qty">([^<]*)</.exec(tds[qtyIdx]) || ["", ""])[1],
    secondQtyLabel: (/<span class="qty">([^<]*)</
      .exec(body.split("</tr>")[1].split("<td").slice(1)[qtyIdx]) || ["", ""])[1],
  };

  // THE POSITIONAL CONTRACT. refreshNumbers writes tds[QTY_TD] / tds[COST_TD] on a table
  // renderPanel built, and the two functions never see each other. Lifted from the source and
  // compared with where the cells actually landed.
  const rn = fn("refreshNumbers");
  const qm = /var QTY_TD = (\d+), COST_TD = (\d+);/.exec(rn);
  out.lines.updaterIndexes = qm ? [Number(qm[1]), Number(qm[2])] : null;
  out.lines.indexesAgree = !!qm && Number(qm[1]) === qtyIdx && Number(qm[2]) === costIdx;
  // The empty-state placeholder has to span the columns that now exist.
  const empty = build({ ASMS: [{ id: "a1", name: "Bare", unit: "SF", lines: [] }] });
  empty.api.renderPanel();
  out.lines.placeholderColspan = Number(
    (/colspan="(\d+)"/.exec(empty.dom.nodes["lines-body"].innerHTML) || [0, 0])[1]);
}

// ── EXECUTED: one row per line item, and a search that looks at three fields ─
// Hanz, 2026-08-19: "divisions should be a label up top like before not on the row. Make one line
// item, one row." The previous picker rendered an always-open panel — search box, a Divisions
// label, two filter selects, twelve results — inside every ITEMS cell, so one line was a tall
// block. These run the real matcher and the real renderer rather than reading the source.
{
  const { api } = build();
  // The fixtures differ in BOTH fields the search now reaches: i1 is Epoxy / Sherwin-Williams,
  // i2 is Polished Concrete / Gone Supply Co. A matcher that only read `name` would answer these
  // identically, since both names begin "OPF".
  const names = (q) => api.ITEMS.filter((it) => api.itemMatches(it, q)).map((it) => it.name);
  out.itemSearch = {
    byName: names("primer"),
    byDivision: names("polished"),
    byVendor: names("sherwin"),
    // "combination of those" — a division word AND a name word, which must narrow rather than
    // find nothing. This is the case a single-field matcher gets wrong.
    byCombination: names("polished primer"),
    caseInsensitive: names("SHERWIN"),
    blankFindsEverything: names("").length,
    nonsenseFindsNothing: names("zzz not a material"),
  };

  // The results markup, from the real builder: every row names its division and vendor, so a match
  // on something other than the name is never a mystery.
  const openLine = { item_id: "i1", _item_search: "polished" };
  const resultsHtml = api.itemResultsHtml(openLine);
  out.itemSearch.resultNamesDivisionAndVendor =
    /Polished Concrete &middot; Gone Supply Co/.test(resultsHtml);
  out.itemSearch.resultsAreButtonsKeyedByItemId = /data-pick-item="i2"/.test(resultsHtml);
  out.itemSearch.emptySearchSaysSo =
    /No items match that search/.test(api.itemResultsHtml({ _item_search: "zzzz" }));

  // CLOSED: the box shows the chosen item and emits no list, so the row is one row high.
  const closed = api.pickerFor({ item_id: "i1", _item_search: "polished" }, 0);
  // OPEN: the same line, with its picker open, gains the floating list — and nothing else.
  const openApi = build({ pickerOpen: 0 }).api;
  const opened = openApi.pickerFor({ item_id: "i1", _item_search: "polished" }, 0);
  out.itemSearch.closedShowsTheItem = /value="OPF"/.test(closed);
  out.itemSearch.closedHasNoResults = !/item-results/.test(closed);
  out.itemSearch.openShowsResults = /class="item-results"/.test(opened);
  // Open, the box holds the QUERY, not the item name — otherwise 30 characters must be deleted
  // before three can be typed.
  out.itemSearch.openShowsTheQuery = /value="polished"/.test(opened);
  // A different line's picker being open must not open this one's.
  out.itemSearch.onlyTheOpenLineExpands =
    !/item-results/.test(openApi.pickerFor({ item_id: "i2" }, 1));

  // The transient query rides on the line while typing; the SAVE must not carry it.
  out.itemSearch.savePayloadIsClean = Object.keys(
    api.lineForSave({ item_id: "i1", coverage: 275, waste_pct: 5, roundup: true,
                      _item_search: "polished", _division_filter: "Epoxy" })).sort();
}

// ── EXECUTED: the live updater, on the table renderPanel actually built ──────
// The earlier version of this check regex-scraped `var QTY_TD = 4, COST_TD = 5;` out of the source
// and compared the numbers with the rendered column positions. Both agreed — and the two writes
// were transposed, so the constants were right and the content went into the wrong cells. That
// version reached staging. This one runs the function.
{
  const { api, dom: d } = build();
  api.renderPanel();
  const rows = d.nodes["lines-body"].querySelectorAll("[data-line]");
  // Nothing has been written yet: refreshNumbers is what fires on a keystroke.
  const before = rows.map((r) => r.cells.map((c) => c.written));
  api.refreshNumbers();
  const first = rows[0].cells.map((c) => c.written);
  const second = rows[1].cells.map((c) => c.written);
  out.liveUpdate = {
    untouchedBefore: before.every((r) => r.every((c) => c === null)),
    // Cell 4 is Quantity, cell 5 is Cost — per the <thead> the page ships.
    qtyCellGotTheQuantity: /class="qty">11 Gal</.test(first[5] || ""),
    costCellGotTheMoney: /class="qty">\$939/.test(first[6] || ""),
    // …and neither got the other's content, which is the transposition, stated directly.
    qtyCellHasNoDollarAmount: !/\$[\d,]+\.\d\d</.test(first[5] || ""),
    costCellHasNoUnitLabel: !/>1?1 Gal</.test(first[6] || ""),
    // The columns a user types in must not be written at all, or the input under the caret dies.
    inputCellsUntouched: [0, 1, 2, 3, 4].every((i) => first[i] === null),
    deleteCellUntouched: first[7] === null,
    // The fractional row shows its own working, not the rounded one's.
    secondRowQty: (/class="qty">([^<]*)</.exec(second[5] || "") || ["", ""])[1],
    secondRowWorking: (/class="calc mono">([^<]*)</.exec(second[6] || "") || ["", ""])[1],
    totalWritten: d.nodes["t-total"].textContent,
    perUnitWritten: d.nodes["t-unit"].textContent,
  };

  // THE ASSEMBLY'S UNIT REACHES ALL THREE LABELS, and the arithmetic is untouched by it.
  //
  // The field was persisted and read by the Polish beta long before it had an editor, so every
  // assembly said SF and the rail's "$1.497/SF" was a guess that happened to be right. These two
  // scenarios are the same fixture and the same numbers with only `unit` changed — so a divergence
  // in `total`/`perUnit` between them would mean the relabel had started changing prices.
  {
    const lf = build({ ASMS: [{ id: "a1", name: "Cove Base", unit: "LF", lines: [
      { item_id: "i1", coverage: 275, waste_pct: 5, roundup: true }] }] });
    lf.api.renderPanel();
    const sf = build({ ASMS: [{ id: "a1", name: "Floor", unit: "SF", lines: [
      { item_id: "i1", coverage: 275, waste_pct: 5, roundup: true }] }] });
    sf.api.renderPanel();
    const bare = build({ ASMS: [{ id: "a1", name: "Legacy", unit: "sqft", lines: [
      { item_id: "i1", coverage: 275, waste_pct: 5, roundup: true }] }] });
    bare.api.renderPanel();
    out.assemblyUnit = {
      lfPerUnitLabel: lf.dom.nodes["t-unit-k"].textContent,
      lfAreaLabel: lf.dom.nodes["area-k"].textContent,
      lfAreaSuffix: lf.dom.nodes["area-u"].textContent,
      lfSelectSynced: lf.dom.nodes["asm-unit"].value,
      sfPerUnitLabel: sf.dom.nodes["t-unit-k"].textContent,
      sfAreaLabel: sf.dom.nodes["area-k"].textContent,
      sfAreaSuffix: sf.dom.nodes["area-u"].textContent,
      // An off-list legacy value reads as SF rather than being echoed into the label, so the words
      // still describe the arithmetic that actually ran.
      legacyReadsAsSf: bare.dom.nodes["area-u"].textContent,
      legacySelectSynced: bare.dom.nodes["asm-unit"].value,
      // Identical money on both, which is the point: this is a label, not a calculation.
      lfTotal: lf.dom.nodes["t-total"].textContent,
      sfTotal: sf.dom.nodes["t-total"].textContent,
      lfPerUnit: lf.dom.nodes["t-unit"].textContent,
      sfPerUnit: sf.dom.nodes["t-unit"].textContent,
    };
  }

  // A broken line must be reported in the Quantity cell and cleared out of the Cost cell.
  const broken = build({ ASMS: [{ id: "a1", name: "Broken", unit: "SF", lines: [
    { item_id: "deleted-material", coverage: 275, waste_pct: 5, roundup: true }] }] });
  broken.api.renderPanel();
  const brows = broken.dom.nodes["lines-body"].querySelectorAll("[data-line]");
  broken.api.refreshNumbers();
  const bcells = brows[0].cells.map((c) => c.written);
  out.liveUpdate.brokenSaysSoInTheQtyCell = /Item removed/.test(bcells[5] || "");
  out.liveUpdate.brokenCostCellCleared = bcells[6] === "—";
  out.liveUpdate.brokenCostCellClearedInsideAlignment = /line-primary/.test(bcells[6] || "") &&
    !/\$|Item removed|Needs/.test(bcells[6] || "");
  out.liveUpdate.brokenRowFlagged = brows[0].classList.has("broken");
}

// ── EXECUTED: the item edit handler, not just its field list ─────────────────
// The earlier check read the NUMERIC_ITEM_FIELDS array literal. Deleting the ternary that CONSULTS
// it left the array intact, so the test passed while every typed number went into the model as a
// string. That also reached staging.
{
  // `keep` lets two consecutive edits share one cell — required to observe the hint being REMOVED.
  // A fresh cell per call made "the hint went away" true no matter what the handler did.
  function edit(api, dom, itemId, field, raw, keep) {
    const cell = keep || { hint: null,
      querySelector: (sel) => (sel === ".dupe" ? cell.hint : null),
      insertAdjacentHTML: (_where, html) => { cell.hint = { textContent: html, remove() { cell.hint = null; } }; } };
    api.onItemEdit({ target: {
      getAttribute: (k) => (k === "data-f" ? field : null),
      value: raw,
      parentNode: cell,
      closest: (sel) => (sel === "[data-item]"
        ? { getAttribute: () => itemId } : null),
    } });
    return cell;
  }
  const { api, dom: d } = build();
  api.renderItems();
  edit(api, d, "i1", "buy_qty", "5");
  edit(api, d, "i1", "unit_cost", "$1,200.50");
  edit(api, d, "i1", "coverage", " 275 ");
  edit(api, d, "i1", "vendor", "Sika");
  const it = api.ITEMS[0];
  out.itemEdit = {
    // Numbers, not strings: "5" divides by luck and concatenates the first time anything multiplies.
    buyQtyType: typeof it.buy_qty, buyQty: it.buy_qty,
    costType: typeof it.unit_cost, cost: it.unit_cost,
    coverageType: typeof it.coverage, coverage: it.coverage,
    // Text stays text.
    vendorType: typeof it.vendor, vendor: it.vendor,
    // Every edit is queued for the server as typed, in field-level bodies.
    queued: api.QUEUED.map((q) => q.kind + ":" + Object.keys(q.body).join(",")),
    queuedRaw: api.QUEUED.map((q) => Object.values(q.body)[0]),
  };
  // The duplicate hint appears and disappears through the same handler, in ONE cell — the same
  // field being typed in, which is the only way "it was removed" can fail.
  const cell = edit(api, d, "i1", "name", "OPF Primer II");
  out.itemEdit.hintShown = !!cell.hint && /Already in the list/.test(cell.hint.textContent);
  edit(api, d, "i1", "name", "Totally Different Product", cell);
  out.itemEdit.hintRemovedWhenNoLongerSimilar = !cell.hint;
  edit(api, d, "i1", "name", "OPF Primer III", cell);
  out.itemEdit.hintNotDuplicatedOnRetype =
    !!cell.hint && (String(cell.hint.textContent).match(/Already in the list/g) || []).length === 1;
}

// ── EXECUTED: the debounced save, and what a 409 does to a queued edit ───────
// Its own scope, because this needs the REAL patchSoon while the block above needs it stubbed.
// Driven by a hand-cranked clock so the race is deterministic: type → PATCH in flight → keep
// typing (re-arming the timer) → 409 lands → the repaint empties the buffer.
async function conflictChecks() {
  const saveScope = new Function("api", "clock", "hooks", "state", "TW", "L", "document", `
    "use strict";
    var timers = {};
    var pendingPatch = {};
    // Declared here rather than grab()bed, exactly like its two siblings above: this scope owns
    // the save machinery's state so a scenario can drive it. flush() reads it to refuse a second
    // PATCH while one is on the wire.
    var inFlight = {};
    var takenP = {};
    var FRESH = state.FRESH || { items: {}, assemblies: {} };
    var ASMS = state.ASMS, ITEMS = state.ITEMS, VENDORS = state.VENDORS;
    var setTimeout = clock.setTimeout, clearTimeout = clock.clearTimeout;
    function saving(m) { hooks.saving.push(m); }
    function say(m) { hooks.said.push(m); }
    function renderList() { hooks.renders.push("list"); }
    function renderPanel() { hooks.renders.push("panel"); }
    function renderItems() { hooks.renders.push("items"); }
    function paintDates() {}
    function datesHtml() { return ""; }
    ${grab(/^  var esc = function[\s\S]*?\n  \};$/m, "esc")}
    // The item-change confirmation, REAL, because this is the scope that has the real patchSoon —
    // and the dialog fires from inside the flush, after the payload has been coalesced.
    // TW is a parameter so a test can answer Yes or No and read back what it was asked.
    var itemBefore = {};
    // WHICH ROW'S DIALOG IS ON SCREEN, and where the caret was when it opened. Both are lifted
    // rather than restated: the guard at the top of onItemEdit reads the first, and the whole
    // bypass this file now probes for is a re-entry that happens while it is set.
    ${grab(/^  var itemConfirmOpen = null;$/m, "the itemConfirmOpen declaration")}
    ${grab(/^  var itemLastField = \{\};$/m, "the itemLastField declaration")}
    ${grab(/^  var SERVER_OWNED_ITEM_FIELDS = \[[^\]]*\];$/m, "SERVER_OWNED_ITEM_FIELDS")}
    ${grab(/^  var NUMERIC_ITEM_FIELDS = \[[^\]]*\];$/m, "NUMERIC_ITEM_FIELDS")}
    ${grab(/^  var ITEM_FIELD_LABELS = \{[\s\S]*?\n  \};$/m, "ITEM_FIELD_LABELS")}
    ${fn("itemOf")}
    ${fn("snapshotItem")}
    ${fn("rememberItem")}
    ${fn("shownValue")}
    ${fn("rowHasFocus")}
    ${fn("refocusItemField")}
    // CALLED BY BOTH confirmItemPatch AND forgetItem, so leaving it out is a ReferenceError that
    // kills every scenario in this file at once rather than failing one assertion.
    ${fn("endItemRound")}
    ${fn("confirmItemPatch")}
    ${fn("byId")}
    ${fn("adoptSaved")}
    ${fn("adoptConflict")}
    ${fn("arm")}
    ${fn("requeueFailed")}
    ${fn("flush")}
    ${fn("forgetItem")}
    ${fn("flushItemRow")}
    ${fn("saveNow")}
    ${fn("flushAllPending")}
    ${fn("savePending")}
    ${fn("onItemRowFocusOut")}
    ${fn("patchSoon")}
    // THE REAL onItemEdit, in THIS scope, on top of the REAL patchSoon. The first scope in this
    // file runs it against a stubbed patchSoon, which is what made the bypass invisible: the
    // re-entrant keystroke the dialog's own focus move produces has to reach the real queue and
    // the real timer for the probe below to mean anything. similarNames/dupeHtml come with it
    // because the name branch calls them.
    ${fn("similarNames")}
    ${fn("dupeHtml")}
    ${fn("onItemEdit")}
    return { patchSoon: patchSoon, adoptConflict: adoptConflict,
             rememberItem: rememberItem, onItemEdit: onItemEdit,
             onItemRowFocusOut: onItemRowFocusOut, flushItemRow: flushItemRow,
             saveNow: saveNow, fresh: function () { return FRESH; },
             flushAllPending: flushAllPending, savePending: savePending,
             forgetItem: forgetItem,
             confirmOpen: function () { return itemConfirmOpen; },
             snapshotOf: function (id) { return itemBefore[id]; },
             armed: function () { return Object.keys(timers).length; },
             pending: function () { return Object.keys(pendingPatch).length; },
             // Empties the buffer WITHOUT disarming, which is the state the empty-payload guard
             // exists for. adoptConflict no longer produces it — that is the point of the fix —
             // so the guard is defence for the next code path that empties this buffer, and a
             // test of it has to construct the state deliberately rather than pretend otherwise.
             dropBuffer: function () { pendingPatch = {}; } };
  `);

  /** Just enough DOM for the row-leave rules: one item row per id, one focusable control per
   *  field, and an activeElement a test can move.
   *
   *  Purpose-built rather than a DOM emulator, and it THROWS on a selector it does not model —
   *  the two questions the page asks it ("does this row hold the focus", "where do I put the
   *  caret back") are asked through selectors renderItems' own output has to carry, so a renamed
   *  attribute must break this file loudly rather than quietly answer null. */
  function makeRowDom(itemIds, fields) {
    const rows = {};
    const doc = {
      activeElement: null,
      rows,
      querySelector(sel) {
        let m = /^\[data-item="([^"]+)"\]$/.exec(sel);
        if (m) return rows[m[1]] || null;
        m = /^\[data-item="([^"]+)"\] \[data-f="([^"]+)"\]$/.exec(sel);
        if (m) return (rows[m[1]] || { cells: {} }).cells[m[2]] || null;
        throw new Error("the page asked document for " + sel + ", which this stub does not model "
          + "— the row/field selector moved and rowHasFocus cannot find anything either");
      },
    };
    itemIds.forEach((id) => {
      const cells = {};
      const row = {
        id, cells,
        getAttribute: (k) => (k === "data-item" ? id : null),
        contains: (el) => !!el && Object.keys(cells).some((f) => cells[f] === el),
      };
      fields.forEach((f) => {
        cells[f] = {
          field: f, value: "", focused: 0,
          getAttribute: (k) => (k === "data-f" ? f : null),
          closest: (sel) => (sel === "[data-item]" ? row : null),
          // A cell has no parentNode/querySelector: the name branch of onItemEdit is not exercised
          // here, and a stub that silently answered it would hide that.
          focus() { doc.activeElement = this; this.focused++; },
        };
      });
      rows[id] = row;
    });
    return doc;
  }

  function run409(fix, answer) {
    const hooks = { saving: [], said: [], renders: [], requests: [], bodies: [], errors: [],
                    asked: [], dialogs: [], onDialogOpen: null, autoReply: null };
    // THE DIALOG IS A DEFERRED, NOT A RESOLVED PROMISE, and that is the whole point of this
    // rework. The old stub was `async (opts) => answer !== false`, which settles on the next
    // microtask — so no test could ever run code in the window while the dialog is OPEN, which is
    // exactly the window the focus-steal bypass lived in. `onDialogOpen` fires SYNCHRONOUSLY at
    // the moment the real helper appends its overlay and moves the focus, which is the moment the
    // page used to re-enter onItemEdit.
    //
    // `answer`: undefined/true = Yes, false = Cancel, "throw" = the dialog itself blew up,
    // "manual" = the test resolves it by hand off hooks.dialogs.
    // Whether SOME OTHER dialog is on screen — the delete confirmation a row's own Remove button
    // opens. Answerable from a test, because the hazard is that dialog's focus move firing the
    // focusout this page saves on.
    let othersOpen = 0;
    const TW = {
      modalOpen: () => othersOpen > 0,
      openAnotherDialog: () => { othersOpen += 1; },
      closeAnotherDialog: () => { othersOpen -= 1; },
      confirmDanger: (opts) => {
        hooks.asked.push(opts);
        return new Promise((resolve, reject) => {
          const d = { opts, resolve, reject };
          hooks.dialogs.push(d);
          if (hooks.onDialogOpen) hooks.onDialogOpen(d);
          if (answer === "throw") Promise.resolve().then(() => reject(new Error("dialog blew up")));
          else if (answer !== "manual") Promise.resolve().then(() => resolve(answer !== false));
        });
      },
    };
    let due = [];
    // Handles start at 1, as every browser's do — a 0 handle would make `if (timers[key])` skip,
    // which is a condition the real page never meets and would fake a pass here.
    const clock = {
      setTimeout: (fn2) => { due.push({ fn: fn2, live: true }); return due.length; },
      clearTimeout: (id) => { if (due[id - 1]) due[id - 1].live = false; },
    };
    let release;
    const inflight = new Promise((r) => { release = r; });
    const api = (path, opts) => {
      hooks.requests.push(((opts || {}).method || "GET") + " " + path);
      // A SCENARIO THAT DOES NOT CARE ABOUT THE RACE answers immediately. Held requests are the
      // point of the 409 scenarios and a deadlock in every other one: a mutation that opens one
      // more dialog than expected leaves a flush awaiting a reply the test was never going to
      // release, node's event loop empties, and the harness exits 0 having printed nothing — which
      // reads as "the harness itself failed" instead of naming the assertion that broke.
      if (hooks.autoReply) {
        hooks.bodies.push(String((opts || {}).body || ""));
        return Promise.resolve(hooks.autoReply);
      }
      // EVERY BODY, kept separately from the request line so the bypass probe can assert on what
      // was actually SENT rather than on how many times we sent something. "Cancel stopped the
      // dialog" and "the rejected number never left the browser" are different claims.
      hooks.bodies.push(String((opts || {}).body || ""));
      return inflight;
    };
    // a1 USES i1 and i2: the item-change confirmation only asks about a material some assembly
    // prices from, so a fixture with no lines would never see the dialog these scenarios drive.
    const state = { ASMS: [{ id: "a1", name: "MACRO", unit: "SF",
                             lines: [{ item_id: "i1" }, { item_id: "i2" }], updated_at: "T1" }],
                    ITEMS: [{ id: "i1", name: "Densifier", unit: "Gallon", unit_cost: 42,
                              buy_qty: 5, vendor: "Sika", divisions: ["Polished Concrete"],
                              updated_at: "T1", cost_updated_at: "STAMP-1" },
                            { id: "i2", name: "Hardener", unit: "Gallon", unit_cost: 10,
                              buy_qty: 1, vendor: "Sika", divisions: [],
                              updated_at: "T1", cost_updated_at: "STAMP-1" }],
                    VENDORS: [] };
    const doc = makeRowDom(["i1", "i2"], ["name", "unit_cost", "vendor", "buy_qty", "unit"]);
    const s = saveScope(api, clock, hooks, state, TW, L, doc);
    return { hooks, clock, s, state, release, doc, TW, fire: async () => {
      const now = due; due = [];
      for (const t of now) {
        if (!t.live) continue;
        try {
          // BOUNDED. The timer callback hands its promise back, and a flush can legitimately sit
          // on a request this scenario has not released — but it can also sit on a DIALOG nobody
          // is going to answer, which is what a change that asks one more time than expected
          // produces. Unbounded, that stops the whole harness and it prints nothing; bounded, it
          // becomes a line in hooks.errors that the scenario's own `errors == []` catches.
          let stuck = false;
          await Promise.race([
            Promise.resolve(t.fn()),
            new Promise((r) => global.setTimeout(() => { stuck = true; r(); }, 250)),
          ]);
          if (stuck) hooks.errors.push("a flush never settled — an unanswered dialog or a reply "
            + "this scenario never released");
        } catch (e) { hooks.errors.push(String(e)); }
      }
    }, cancelledCount: () => due.filter((t) => !t.live).length,
      // The methods the page's own paths are driven through, so no scenario below hand-rolls an
      // event shape the real handlers do not receive.
      type: (id, field, value) => {
        const cell = doc.rows[id].cells[field];
        cell.value = value;
        doc.activeElement = cell;
        s.onItemEdit({ target: cell });
      },
      // …and the browser's own blur→change, which is what a .focus() elsewhere provokes: the
      // input reports `change` with the value it still holds.
      synthChange: (id, field) => s.onItemEdit({ target: doc.rows[id].cells[field] }),
      // Returns the flush's promise so a scenario can await it. The rejection has to be reachable:
      // a dialog that throws rejects this chain, and an unawaited rejection kills node with an
      // unhandled-rejection exit instead of failing the assertion that cares.
      leaveRow: (id, field, to) => {
        doc.activeElement = to || null;
        return Promise.resolve(
          s.onItemRowFocusOut({ target: doc.rows[id].cells[field], relatedTarget: to || null })
        ).catch((e) => { hooks.errors.push(String(e)); });
      },
      // Every value that reached the wire, flattened, so "58 was never sent" is one assertion
      // rather than a walk over request bodies.
      sentValues: () => hooks.bodies.map((b) => {
        try { return JSON.parse(b); } catch (e) { return b; }
      }) };
  }

  // Scenario: the 409 arrives while a newer keystroke is already queued.
  const c = run409();
  c.s.patchSoon("assemblies", "a1", { name: "A" });
  const firing = c.fire();                       // the timer callback starts and awaits api()
  await new Promise((r) => setTimeout(r, 0));
  c.s.patchSoon("assemblies", "a1", { name: "AB" });   // …the user keeps typing: timer re-armed
  const armedBeforeConflict = c.s.armed();
  c.release({ status: 409, json: async () => ({ error: "changed", assembly:
    { id: "a1", name: "B's version", unit: "SF", lines: [], updated_at: "T2" } }) });
  await firing;
  const afterConflict = { pending: c.s.pending(), cancelled: c.cancelledCount() };
  await c.fire();                                 // whatever is still armed gets its turn
  out.conflict = {
    armedBeforeConflict,
    bufferEmptied: afterConflict.pending === 0,
    // THE FIX: the re-armed timer is disarmed too. Leaving it armed meant it fired 600ms later on
    // an empty buffer and threw before the try block — a dropped write with nothing on screen.
    timerDisarmed: afterConflict.cancelled === 1,
    noSecondRequest: c.hooks.requests.length === 1,
    noUnhandledError: c.hooks.errors.length === 0,
    screenRepainted: c.hooks.renders.join(",") === "list,panel",
    toldTheUser: c.hooks.said.some((m) => /changed/i.test(String(m))),
  };

  // ── EXECUTED: the Save button on a NEW material / assembly (Hanz, 2026-10-05) ────────
  // The row exists server-side from the create POST; what the button sends is what was typed over
  // the placeholder. Nobody should have to click off the row for it to go.
  {
    const ok = { status: 200, ok: true, json: async () => ({}) };
    // New material, typed into, Save pressed: ONE PATCH, the "Save this change?" question, no wait.
    const a = run409();
    a.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item:
      { id: "i1", updated_at: "T2", cost_updated_at: "STAMP-1" } }) };
    a.s.fresh().items.i1 = true;
    a.type("i1", "unit_cost", "50");
    const timersArmedByTyping = a.s.armed();
    const stillNew = await a.s.saveNow("items", "i1");
    // Nothing typed on a new row: the press only retires the button, and sends nothing.
    const b = run409();
    b.s.fresh().items.i2 = true;
    const stillNewB = await b.s.saveNow("items", "i2");
    // Cancel on the question keeps the row "new", so the button stays for another try.
    const c2 = run409(undefined, false);
    c2.s.fresh().items.i1 = "new";
    c2.hooks.autoReply = ok;
    c2.type("i1", "unit_cost", "77");
    const stillNewC = await c2.s.saveNow("items", "i1");
    // A new ASSEMBLY: no dialog, one PATCH carrying the version it edited, flag cleared.
    const d2 = run409();
    d2.hooks.autoReply = { status: 200, ok: true, json: async () => ({ assembly:
      { id: "a1", updated_at: "T2", name: "Fresh", lines: [] } }) };
    d2.s.fresh().assemblies.a1 = true;
    d2.s.patchSoon("assemblies", "a1", { name: "Fresh" });
    const stillNewD = await d2.s.saveNow("assemblies", "a1");
    out.saveNew = {
      itemQuestionAsked: a.hooks.asked.length === 1,
      itemOnePatch: a.hooks.requests.length === 1 && /PATCH \/api\/library\/items\/i1/.test(a.hooks.requests[0]),
      itemSentTheTypedCost: /50/.test(a.hooks.bodies[0] || ""),
      itemDebounceDisarmed: timersArmedByTyping >= 0 && a.s.armed() === 0,
      itemNoLongerNew: stillNew === false && !a.s.fresh().items.i1,
      untouchedRowSendsNothing: b.hooks.requests.length === 0,
      untouchedRowNoLongerNew: stillNewB === false,
      cancelKeepsItNew: stillNewC === true && c2.hooks.requests.length === 0,
      asmOnePatch: d2.hooks.requests.length === 1 && /PATCH \/api\/library\/assemblies\/a1/.test(d2.hooks.requests[0]),
      asmDeclaredItsVersion: /"expected_updated_at":"T1"/.test(d2.hooks.bodies[0] || ""),
      asmNoLongerNew: stillNewD === false && !d2.s.fresh().assemblies.a1,
      noErrors: [a, b, c2, d2].every((x) => x.hooks.errors.length === 0),
    };
  }

  // ── EXECUTED: Save on ANY edited row (Hanz, 2026-10-05, B3b) ────────────────────────
  {
    const okItem = { status: 200, ok: true, json: async () => ({ item:
      { id: "i1", updated_at: "T2", cost_updated_at: "STAMP-1" } }) };
    const tick = () => new Promise((r) => setTimeout(r, 0));
    // 1. A SAVED row, edited: marked unsaved by the edit itself, one PATCH + one question on Save,
    //    mark lifted only after the reply.
    const a = run409();
    const markedBefore = !a.s.fresh().items.i1;
    a.hooks.autoReply = okItem;
    a.type("i1", "unit_cost", "50");
    const markedAfterTyping = !!a.s.fresh().items.i1;
    const savedFlag = await a.s.saveNow("items", "i1");
    // 2. Server refuses: the mark stays and saveNow says so.
    const f = run409();
    f.hooks.autoReply = { status: 500, ok: true === false, json: async () => ({ detail: "nope" }) };
    f.type("i1", "unit_cost", "51");
    const failedStill = await f.s.saveNow("items", "i1");
    const failedMarkKept = !!f.s.fresh().items.i1;
    // 2b. Press Save AGAIN after the failure: it must re-send (not retire the button over a value
    //     the server never got), and once the server accepts, clear.
    const reqsAfterFirst = f.hooks.requests.length;
    const secondStill = await f.s.saveNow("items", "i1");
    const secondResent =f.hooks.requests.length === reqsAfterFirst + 1 && secondStill === true &&
      !!f.s.fresh().items.i1;
    f.hooks.autoReply = okItem;
    const thirdStill = await f.s.saveNow("items", "i1");
    const thirdClears = thirdStill === false && !f.s.fresh().items.i1 &&
      f.hooks.requests.length === reqsAfterFirst + 2;
    // 3. THE RACE: a flush already took the payload and is parked on the dialog. Empty buffer
    //    must NOT read as saved.
    const r = run409(undefined, "manual");
    r.hooks.autoReply = okItem;
    r.type("i1", "unit_cost", "52");
    const flushing = r.s.flushItemRow("i1");
    await tick();
    const bufferEmptyWhileAsking = r.s.pending() === 0 && r.hooks.dialogs.length === 1;
    let pressDone = false;
    const press = r.s.saveNow("items", "i1").then((v) => { pressDone = true; return v; });
    await tick(); await tick();
    const pressWaited = pressDone === false && !!r.s.fresh().items.i1;
    r.hooks.dialogs[0].resolve(true);
    await flushing;
    const pressResult = await press;
    // 4. Typing while a save is on the wire keeps the mark when the earlier save is confirmed.
    const w = run409();
    w.s.patchSoon("assemblies", "a1", { name: "A" });
    const firing = w.fire();
    await tick();
    w.s.patchSoon("assemblies", "a1", { name: "AB" });
    w.release({ status: 200, ok: true, json: async () => ({ assembly:
      { id: "a1", updated_at: "T2", name: "A", lines: [] } }) });
    await firing;
    const newerEditKeepsMark = !!w.s.fresh().assemblies.a1;
    // 5. An edited saved ASSEMBLY: Save sends one PATCH carrying its version, clears on confirm.
    const d = run409();
    d.hooks.autoReply = { status: 200, ok: true, json: async () => ({ assembly:
      { id: "a1", updated_at: "T2", name: "Fresh", lines: [] } }) };
    d.s.patchSoon("assemblies", "a1", { name: "Fresh" });
    const asmMarked = !!d.s.fresh().assemblies.a1;
    const asmStill = await d.s.saveNow("assemblies", "a1");
    // 6. Leaving: flushAllPending sends what is queued; savePending is the beforeunload test.
    const l = run409();
    l.hooks.autoReply = { status: 200, ok: true, json: async () => ({ assembly:
      { id: "a1", updated_at: "T2", name: "Z", lines: [] } }) };
    l.s.patchSoon("assemblies", "a1", { name: "Z" });
    const pendingBeforeLeave = l.s.savePending();
    l.s.flushAllPending();
    const pendingWhileInFlight = l.s.savePending();
    await tick(); await tick();
    const pendingAfter = l.s.savePending();
    // 7. A dialog answered No on a SAVED row drops the mark; on a NEW row it stays.
    const n = run409(undefined, false);
    n.type("i1", "unit_cost", "77");
    await n.s.saveNow("items", "i1");
    const cancelledSavedRowClean = !n.s.fresh().items.i1;
    out.saveEdited = {
      notMarkedBeforeEdit: markedBefore,
      markedByTheEdit: markedAfterTyping,
      confirmedSaveClears: savedFlag === false && !a.s.fresh().items.i1,
      onePatchOneQuestion: a.hooks.requests.length === 1 && a.hooks.asked.length === 1,
      failedKeepsMark: failedStill === true && failedMarkKept,
      secondPressResends: secondResent,
      thirdPressClearsOnConfirm: thirdClears,
      bufferEmptyWhileAsking,
      pressWaitedForTheDialog: pressWaited,
      pressThenConfirmed: pressResult === false && !r.s.fresh().items.i1 && r.hooks.requests.length === 1,
      newerEditKeepsMark,
      asmMarked,
      asmSavedAndCleared: asmStill === false && !d.s.fresh().assemblies.a1 &&
        d.hooks.requests.length === 1 && /"expected_updated_at":"T1"/.test(d.hooks.bodies[0] || ""),
      leaveWarnsWhilePending: pendingBeforeLeave === true && pendingWhileInFlight === true,
      leaveFlushSent: l.hooks.requests.length === 1,
      leaveSettled: pendingAfter === false,
      cancelledSavedRowClean,
      noErrors: [a, f, r, w, d, l, n].every((x) => x.hooks.errors.length === 0),
    };
  }

  // ── EXECUTED: a second save cannot go out while the first is on the wire ────
  // THE RACE THIS PREVENTS IS AGAINST OURSELVES, not another person.
  //
  // Every successful PATCH bumps `updated_at`, and an assembly save declares the version it edited.
  // So before the in-flight guard: save #1 leaves, save #2's timer fires 600ms later and reads the
  // SAME `updated_at` (adoptSaved has not run yet), goes out, and the server correctly calls it
  // stale. `adoptConflict` then replaced the model, dropped the buffer and blamed a person who does
  // not exist. With the bulk picker that could discard a whole batch of lines.
  //
  // NOTE WHY THE SCENARIO ABOVE DID NOT CATCH IT: it calls fire() a second time only AFTER release,
  // so a second flush never begins mid-flight and the guard is never reached. This one fires while
  // the first request is still awaiting, which is the only shape that exercises it.
  {
    const c = run409();
    c.s.patchSoon("assemblies", "a1", { name: "A" });
    const firing = c.fire();                     // #1 leaves and awaits api()
    await new Promise((r) => setTimeout(r, 0));
    c.s.patchSoon("assemblies", "a1", { name: "AB" });
    await c.fire();                              // #2 tries WHILE #1 is on the wire
    const midFlight = { requests: c.hooks.requests.length, pending: c.s.pending(),
                        armed: c.s.armed() };
    // #1 succeeds and hands back a NEW version stamp.
    c.release({ status: 200, ok: true, json: async () => ({ assembly:
      { id: "a1", name: "A", unit: "SF", lines: [], updated_at: "T2" } }) });
    await firing;
    await c.fire();                              // now #2 gets its turn
    out.inFlight = {
      // Only ONE request while the first was open — the second waited instead of racing.
      onlyOneWhileOpen: midFlight.requests === 1,
      // …and it WAITED rather than being dropped: the edit was still on screen and unsaved.
      editStillQueued: midFlight.pending > 0,
      stillArmed: midFlight.armed,
      // Both saves eventually reach the server.
      bothEventuallySent: c.hooks.requests.length === 2,
      // AND THE POINT OF ALL OF IT: the second save carries the version the first one produced,
      // so it cannot 409 against our own write.
      secondCarriedTheNewVersion: (function () {
        var bodies = c.sentValues();
        var last = bodies[bodies.length - 1] || {};
        return last.expected_updated_at;
      })(),
      firstCarriedTheOldVersion: (function () {
        var bodies = c.sentValues();
        return (bodies[0] || {}).expected_updated_at;
      })(),
      noUnhandledError: c.hooks.errors.length === 0,
    };
  }

  // A LOCK THAT IS NEVER RELEASED WOULD BE WORSE THAN THE BUG. flush returns early on a 409 and on
  // any non-ok status, so the release lives in a `finally` — this proves a record still saves after
  // one of those early returns rather than being silenced for the rest of the session.
  {
    const c = run409();
    c.s.patchSoon("assemblies", "a1", { name: "A" });
    const firing = c.fire();
    await new Promise((r) => setTimeout(r, 0));
    c.release({ status: 500, ok: false, json: async () => ({ error: "boom" }) });
    await firing;
    c.s.patchSoon("assemblies", "a1", { name: "B" });
    await c.fire();
    out.inFlight.savesAgainAfterAFailure = c.hooks.requests.length === 2;
  }

  // And the belt to that brace: a timer that fires with nothing queued must be a quiet no-op,
  // not a TypeError thrown outside the try.
  const d2 = run409();
  d2.s.patchSoon("assemblies", "a1", { name: "A" });
  d2.s.dropBuffer();          // armed, with nothing left to send
  await d2.fire();
  out.conflict.emptyTimerIsQuiet = d2.hooks.errors.length === 0;
  out.conflict.emptyTimerSendsNothing = d2.hooks.requests.length === 0;
  // An ASSEMBLY save is never confirmed. Read off the run above rather than asserted in its own
  // scenario, because that run is a realistic assembly edit — two keystrokes, a conflict, a
  // repaint — and if the dialog had leaked out of the items branch it would have fired in it.
  out.conflict.neverAskedAboutAnAssembly = c.hooks.asked.length === 0
    && d2.hooks.asked.length === 0;

  // ── the confirmation in front of an ITEM save ──────────────────────────────
  // Hanz, 2026-08-25: items "will be connected to many assemblies and an accidental change could
  // alter the pricing." Driven through the REAL patchSoon, because the design decision under test
  // is WHERE the question is asked — at flush time, on the payload after 600ms of coalescing, not
  // on the keystroke. A test that called confirmItemPatch directly would pass with the call site
  // deleted.
  const settle = () => new Promise((r) => setTimeout(r, 0));

  async function itemRun(answer, edit, payload) {
    const c = run409(undefined, answer);
    const it = c.state.ITEMS[0];
    c.s.rememberItem(it);            // what onItemEdit does on the first keystroke of a round
    edit(it);                        // …and the model really is updated live, before the save
    c.s.patchSoon("items", "i1", payload);
    const firing = c.fire();
    await settle();
    c.release({ status: 200, ok: true,
                json: async () => ({ item: { id: "i1", name: it.name, updated_at: "T2" } }) });
    await firing;
    return { c, it };
  }

  // YES: it asks once, quotes the field that moved, and the payload goes.
  {
    const { c, it } = await itemRun(true, (x) => { x.unit_cost = 58; }, { unit_cost: "58" });
    out.itemConfirm = {
      asked: c.hooks.asked.length,
      title: (c.hooks.asked[0] || {}).title,
      name: (c.hooks.asked[0] || {}).name,
      detail: (c.hooks.asked[0] || {}).detail,
      confirmText: (c.hooks.asked[0] || {}).confirmText,
      tone: (c.hooks.asked[0] || {}).tone,
      requests: c.hooks.requests,
      costAfter: it.unit_cost,
      errors: c.hooks.errors,
    };
  }

  // TWO FIELDS IN ONE PAUSE: still one dialog, and it lists both. This is the whole reason the
  // question is asked at flush time rather than in onItemEdit.
  {
    const { c } = await itemRun(true, (x) => { x.unit_cost = 58; x.vendor = "Euclid"; },
                                { unit_cost: "58", vendor: "Euclid" });
    out.itemConfirmTwoFields = {
      asked: c.hooks.asked.length,
      title: (c.hooks.asked[0] || {}).title,
      detail: (c.hooks.asked[0] || {}).detail,
    };
  }

  // NO: nothing is sent, and the model goes back to what it said. Leaving the edit on screen with
  // the server never told is worse than the accidental change this dialog exists to catch.
  {
    const c = run409(undefined, false);
    const it = c.state.ITEMS[0];
    c.s.rememberItem(it);
    it.unit_cost = 999;
    it.vendor = "Wrong Co";
    c.s.patchSoon("items", "i1", { unit_cost: "999", vendor: "Wrong Co" });
    // Resolved BEFORE the flush, deliberately. A Cancel is supposed to send nothing, so nothing
    // should ever await this — but if the dialog stops appearing (which is what a broken snapshot
    // does: "before" mutates with the edit, the fields compare equal, and no question is asked)
    // the save proceeds and awaits a promise that would otherwise never settle. That turns a
    // detectable bug into a hung harness and 56 tests failing with no reason attached.
    c.release({ status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) });
    await c.fire();
    await settle();
    out.itemCancel = {
      asked: c.hooks.asked.length,
      requests: c.hooks.requests,
      costAfter: it.unit_cost,
      vendorAfter: it.vendor,
      repainted: c.hooks.renders.join(","),
      neverSaidSaving: c.hooks.saving.every((m) => !/Saving/.test(String(m))),
      errors: c.hooks.errors,
    };
  }

  // A DIVISION toggle is an ARRAY field, and the snapshot has to have copied it rather than
  // referenced it — otherwise "before" mutated along with the edit and Cancel would restore the
  // very value it was meant to undo, silently and with the dialog still saying it worked.
  {
    const c = run409(undefined, false);
    const it = c.state.ITEMS[0];
    c.s.rememberItem(it);
    it.divisions.push("Epoxy");                 // toggled on, in place, as onItemEdit does
    c.s.patchSoon("items", "i1", { divisions: ["Polished Concrete", "Epoxy"] });
    // Resolved BEFORE the flush, deliberately. A Cancel is supposed to send nothing, so nothing
    // should ever await this — but if the dialog stops appearing (which is what a broken snapshot
    // does: "before" mutates with the edit, the fields compare equal, and no question is asked)
    // the save proceeds and awaits a promise that would otherwise never settle. That turns a
    // detectable bug into a hung harness and 56 tests failing with no reason attached.
    c.release({ status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) });
    await c.fire();
    await settle();
    out.itemCancelArray = {
      asked: c.hooks.asked.length,
      detail: (c.hooks.asked[0] || {}).detail,
      divisionsAfter: it.divisions.slice(),
    };
  }

  // TYPED AND TYPED BACK: no dialog. patchSoon MERGES a row's fields across the quiet period, so a
  // value changed and then restored arrives identical to where it started. Asking about that is
  // how an estimator learns to dismiss the dialog without reading it, which costs more than it
  // ever saves.
  {
    const { c } = await itemRun(true, (x) => { x.unit_cost = 42; }, { unit_cost: "42" });
    out.itemNoChange = { asked: c.hooks.asked.length, requests: c.hooks.requests };
  }

  // A MATERIAL NO ASSEMBLY USES (a brand-new row, say): saves with no question. The same edit on
  // i1 above is asked about because a1 uses i1; here a1's lines are emptied first.
  {
    const c = run409(undefined, true);
    c.state.ASMS[0].lines = [];
    const it = c.state.ITEMS[0];
    c.s.rememberItem(it);
    it.unit_cost = 58;
    c.s.patchSoon("items", "i1", { unit_cost: "58" });
    const firing = c.fire();
    await settle();
    c.release({ status: 200, ok: true,
                json: async () => ({ item: { id: "i1", name: it.name, updated_at: "T2" } }) });
    await firing;
    out.itemUnused = { asked: c.hooks.asked.length, requests: c.hooks.requests, errors: c.hooks.errors };
  }

  // ══ THE BYPASS PROBE ═══════════════════════════════════════════════════════
  // The defect this whole block exists for, EXECUTED rather than reasoned about.
  //
  // The dialog's own focus move blurs the input the estimator was typing in. A blurred input with
  // an uncommitted value fires `change`, `change` is bound to #items-body, so the page re-entered
  // onItemEdit WHILE ITS OWN DIALOG WAS OPEN — took a fresh snapshot of the already-edited model,
  // queued a second patch, and 600ms later found before == after and sent the rejected number
  // with no dialog at all. Cancel put 42 back on screen; 58 was in the database.
  //
  // Everything below is driven through the REAL onItemEdit on the REAL patchSoon, and the
  // re-entrant keystroke is fired from inside the dialog-open hook — which is the only ordering
  // that can catch this and the reason the old resolved-promise stub could not.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    const it = c.state.ITEMS[0];
    const reentries = [];
    c.hooks.onDialogOpen = (d) => {
      // What .focus() on anything else provokes: the cost input reports `change`, still holding
      // "58", and it bubbles to the tbody listener.
      c.synthChange("i1", "unit_cost");
      reentries.push({ armed: c.s.armed(), pending: c.s.pending(),
                       // The SNAPSHOT still has to hold 42. Before the fix the re-entry found it
                       // already deleted, took a fresh one off the edited model, and every later
                       // comparison then agreed that 58 was where the row had started.
                       snapshotCost: (c.s.snapshotOf("i1") || {}).unit_cost,
                       open: c.s.confirmOpen() });
      d.resolve(false);
    };
    c.type("i1", "unit_cost", "58");            // 42 → 58, model updated live as the page does
    const modelMidEdit = it.unit_cost;
    c.leaveRow("i1", "unit_cost", null);        // focus leaves the row → flush + ask
    await settle(); await settle();
    // Anything the re-entry managed to arm gets its turn, twice, so a deferred timer cannot hide.
    await c.fire(); await settle();
    await c.fire(); await settle();
    out.itemBypass = {
      modelMidEdit,
      asked: c.hooks.asked.length,
      // THE ONE THAT MATTERS: no request body ever carried the rejected number.
      sent: c.sentValues(),
      requests: c.hooks.requests,
      costAfter: it.unit_cost,
      // The re-entrant event must be DISCARDED, not merged: no fresh snapshot, nothing queued,
      // no timer re-armed behind the dialog.
      reentries,
      confirmOpenAfter: c.s.confirmOpen(),
      pendingAfter: c.s.pending(),
      errors: c.hooks.errors,
    };
  }

  // A SECOND ROW'S FLUSH WAITS FOR THE OPEN DIALOG rather than stacking a second one on top of it.
  // Two of these modals at once is one trapping the focus the other one needs, over a question
  // that names neither row clearly.
  //
  // DRIVEN THROUGH patchSoon, NOT THROUGH A KEYSTROKE, and that is not a shortcut: with the guard
  // in place, typing into a second row while a dialog is open is unreachable — the overlay traps
  // the input on the page and onItemEdit discards anything that gets past it. The reachable state
  // is an ARMED TIMER left over from a previous round, which is exactly what a deferred flush
  // leaves behind, so that is what this constructs.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "x" } }) };
    // Every dialog after the first answers itself, so the queue really drains.
    c.hooks.onDialogOpen = (d) => { if (c.hooks.dialogs.length > 1) d.resolve(true); };
    const first = c.state.ITEMS[0], second = c.state.ITEMS[1];
    c.s.rememberItem(second);
    second.unit_cost = 77;
    c.s.patchSoon("items", "i2", { unit_cost: "77" });
    // …and now row one is left, which opens row one's dialog.
    c.type("i1", "unit_cost", "58");
    c.leaveRow("i1", "unit_cost", null);
    await settle();
    const whileOpen = { asked: c.hooks.asked.length, forRow: (c.hooks.asked[0] || {}).name };
    // Row two's timer comes due WITH that dialog still on screen.
    await c.fire(); await settle();
    const secondAsked = c.hooks.asked.length;
    const secondDeferred = c.s.pending();
    const secondRearmed = c.s.armed();
    // Row one is answered; row two's re-armed timer then gets its turn.
    c.hooks.dialogs[0].resolve(true);
    await settle(); await settle();
    await c.fire(); await settle(); await settle();
    out.itemDialogQueue = {
      whileOpen,
      // Still ONE dialog while the first was open…
      askedWhileOpen: secondAsked,
      secondStillQueued: secondDeferred >= 1,
      secondRearmed: secondRearmed >= 1,
      // …and the second row's question does get asked once the first is answered.
      askedInTheEnd: c.hooks.asked.length,
      secondAskedAbout: (c.hooks.asked[1] || {}).name,
      firstCost: first.unit_cost,
      secondCost: second.unit_cost,
      errors: c.hooks.errors,
    };
  }

  // A THROWN DIALOG IS A CANCEL, NOT A DROPPED WRITE. Without the try/catch the rejection escapes
  // the flush: the payload has already been taken out of pendingPatch, the snapshot has been
  // consumed, itemConfirmOpen is left set — so onItemEdit's guard silently swallows every
  // subsequent keystroke on the page and nothing is ever saved again, with no error on screen.
  {
    const c = run409(undefined, "throw");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    const it = c.state.ITEMS[0];
    c.type("i1", "unit_cost", "58");
    // AWAITED, so a rejection that escapes confirmItemPatch lands in hooks.errors instead of
    // killing node with an unhandled rejection and taking every other scenario with it.
    await c.leaveRow("i1", "unit_cost", null);
    await settle(); await settle();
    await c.fire(); await settle();
    out.itemDialogThrew = {
      asked: c.hooks.asked.length,
      requests: c.hooks.requests,
      sent: c.sentValues(),
      costAfter: it.unit_cost,
      // The page is still usable: the flag is down and a later edit is still asked about.
      confirmOpenAfter: c.s.confirmOpen(),
      // The rejection was HANDLED, not left to become an unhandled rejection.
      errors: c.hooks.errors,
    };
  }

  // CANCEL DOES NOT RESTORE THE SERVER'S OWN STAMPS. `updated_at` and `cost_updated_at` are the
  // server's to decide — adoptSaved takes them off a successful write — so putting the snapshot's
  // copy back discards what the server just told us and the Dates cell goes on quoting a price
  // date the database has already moved past.
  {
    const c = run409(undefined, "manual");
    const it = c.state.ITEMS[0];
    c.type("i1", "unit_cost", "58");
    // The server's answer to an EARLIER write lands while the snapshot is held, exactly as it
    // does on the page: adoptSaved is what moves these two, and it can land at any point during
    // the round the snapshot spans.
    it.updated_at = "T9";
    it.cost_updated_at = "STAMP-9";
    const stampsBefore = { updated_at: it.updated_at, cost_updated_at: it.cost_updated_at };
    c.hooks.onDialogOpen = (d) => d.resolve(false);
    c.leaveRow("i1", "unit_cost", null);
    await settle(); await settle();
    out.itemCancelStamps = {
      asked: c.hooks.asked.length,
      costAfter: it.unit_cost,
      stampsBefore,
      stampsAfter: { updated_at: it.updated_at, cost_updated_at: it.cost_updated_at },
      errors: c.hooks.errors,
      // AND THE CARET GOES BACK to the field the refused edit was typed into. The row was rebuilt
      // by the repaint above, so this is the NEW input being focused, not the one they left.
      refocused: c.doc.rows.i1.cells.unit_cost.focused,
      focusedElsewhere: Object.keys(c.doc.rows.i1.cells)
        .filter((f) => f !== "unit_cost" && c.doc.rows.i1.cells[f].focused > 0),
    };
  }

  // ROW-LEAVE TIMING. Hanz, 2026-08-27: the dialog fires when focus leaves the row, not on a
  // typing pause. While the row is being worked in, the flush re-defers; the moment focus lands
  // outside it, the row's edits go in one question.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    c.hooks.onDialogOpen = (d) => d.resolve(true);
    c.type("i1", "unit_cost", "58");
    // The 600ms timer comes due with the focus still in the row.
    await c.fire(); await settle();
    const duringTyping = { asked: c.hooks.asked.length, requests: c.hooks.requests.length,
                           stillQueued: c.s.pending(), rearmed: c.s.armed() };
    await c.fire(); await settle();               // and again: it keeps deferring, it does not fire
    const afterASecondPause = { asked: c.hooks.asked.length, requests: c.hooks.requests.length };
    // Tabbing to another cell IN THE SAME ROW is not leaving it — edits accumulate.
    c.type("i1", "vendor", "Euclid");
    c.leaveRow("i1", "vendor", c.doc.rows.i1.cells.name);
    await settle();
    const insideTheRow = { asked: c.hooks.asked.length };
    // …and now out of the row altogether.
    c.leaveRow("i1", "name", c.doc.rows.i2.cells.unit_cost);
    await settle(); await settle(); await settle();
    out.itemRowLeave = {
      duringTyping,
      afterASecondPause,
      insideTheRow,
      askedOnLeaving: c.hooks.asked.length,
      // ONE question, listing BOTH fields — which is the interruption this design removes.
      detail: (c.hooks.asked[0] || {}).detail,
      sent: c.sentValues(),
      errors: c.hooks.errors,
    };
  }

  // A DIALOG SOMEBODY ELSE PUT UP holds the save back too. The route in is the row's own Remove
  // button: clicking it leaves the focus inside the row, so nothing flushes — and then the delete
  // confirmation focuses ITS Cancel button, which blurs that button and fires the focusout this
  // page saves on. Without asking shared.js whether a modal is up, "Remove this material?" gets
  // "Save this change?" stacked on top of it.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    c.hooks.onDialogOpen = (d) => d.resolve(true);
    c.type("i1", "unit_cost", "58");
    // Reaching for that row's Remove button: still inside the row, so nothing has flushed yet.
    c.TW.openAnotherDialog();
    // …and the delete dialog's own .focus() blurs the button, out of the row.
    await c.leaveRow("i1", "unit_cost", null);
    await settle(); await settle();
    const whileTheOtherIsOpen = { asked: c.hooks.asked.length, queued: c.s.pending(),
                                  rearmed: c.s.armed() };
    // The estimator cancels the delete; the save question is asked then, on its own.
    c.TW.closeAnotherDialog();
    await c.fire(); await settle(); await settle();
    out.itemOtherModal = {
      whileTheOtherIsOpen,
      askedAfterItClosed: c.hooks.asked.length,
      sent: c.sentValues(),
      errors: c.hooks.errors,
    };
  }

  // A DELETED ROW'S QUEUE DIES WITH IT. Far more likely now the save waits for the row to be
  // left: typing a cost and then reaching for that row's Remove button never leaves the row, so
  // the edit is still queued when the material stops existing.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    c.hooks.onDialogOpen = (d) => d.resolve(true);
    c.type("i1", "unit_cost", "58");
    const queuedBefore = c.s.pending();
    c.s.forgetItem("i1");
    const queuedAfter = c.s.pending();
    const snapshotAfter = c.s.snapshotOf("i1");
    await c.fire(); await settle(); await settle();
    out.itemForgotten = {
      queuedBefore, queuedAfter,
      snapshotDropped: snapshotAfter === undefined,
      // Nothing asked and nothing sent: there is no row left to ask about.
      asked: c.hooks.asked.length,
      requests: c.hooks.requests,
      errors: c.hooks.errors,
      // …and the delete path really calls it. The handler it lives in is a 200-line click
      // listener this harness cannot lift, so the call site is checked in the source — weaker than
      // the assertions above, and paired with them rather than standing alone.
      calledOnDelete: /await del\("items", di\);\s*\n\s*\/\/[^\n]*\n\s*forgetItem\(di\);/.test(src),
    };
  }

  // WHAT THE DIALOG IS ASKED FOR. Two opt-ins that exist only for this caller, and both are about
  // the bypass rather than about looks: focusing the dialog itself means a stray SPACE cannot
  // press Cancel, and requiring an explicit answer means clicking the next cell cannot silently
  // revert a deliberate edit.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    c.hooks.onDialogOpen = (d) => d.resolve(true);
    c.type("i1", "unit_cost", "58");
    c.leaveRow("i1", "unit_cost", null);
    await settle(); await settle();
    out.itemAskedOpts = c.hooks.asked[0] || {};
  }
}

// ── B. the Items tab's own search box ───────────────────────────────────────
// One box, no dropdowns: the division/vendor dropdowns that used to sit in the assembly picker
// were deleted on 2026-08-19 partly because their state was being persisted to the server. This
// one reuses itemMatches, the SAME matcher the picker searches with, so the two boxes on this page
// cannot disagree about what a query finds.
{
  const all = build();
  all.api.renderItems();
  const hit = build({ itemQuery: "opf primer" });
  hit.api.renderItems();
  const miss = build({ itemQuery: "nothing like this" });
  miss.api.renderItems();
  const rowsIn = (d) => (d.nodes["items-body"].innerHTML.match(/data-item=/g) || []).length;
  out.itemsSearch = {
    unfiltered: rowsIn(all.dom),
    filtered: rowsIn(hit.dom),
    missed: rowsIn(miss.dom),
    // The tab badge counts what Treadwell HAS, not what is on screen. A badge that fell as
    // somebody typed would read as materials being deleted.
    badgeWhileFiltering: all.dom.nodes["n-items"].textContent === hit.dom.nodes["n-items"].textContent,
    hits: hit.dom.nodes["item-hits"].textContent,
    hitsHiddenWhenNotFiltering: all.dom.nodes["item-hits"].hidden,
    noMatchShown: miss.dom.nodes["items-nomatch"].hidden === false,
    noMatchHiddenOnAHit: hit.dom.nodes["items-nomatch"].hidden,
    // "No materials yet" offers an Add button. It must not stand in for a bad search, or the
    // answer to a typo is an invitation to create a duplicate.
    emptyPanelStaysHidden: miss.dom.nodes["items-empty"].hidden,
    sameMatcherAsThePicker:
      JSON.stringify(hit.api.visibleItems().map((x) => x.id))
      === JSON.stringify(all.api.ITEMS.filter((x) => all.api.itemMatches(x, "opf primer")).map((x) => x.id)),
  };
}

// ── B2. the Assemblies tab: the same box, plus a unit and a condition ───────
// Four assemblies and a third material, LOCAL to this block: the module fixtures are two items
// and one assembly, and growing them would move the row counts, the badge and the datalist that
// every scenario above asserts on.
//
// The set is chosen so each control has something to be wrong about — a2 is the only LF one, a3 is
// the only broken one (its material has no coverage), a4 is the only empty one, and a1 is the only
// one that contains "OPF Primer".
{
  const ITEMS4 = [
    { id: "i1", name: "OPF", category: "Epoxy", unit: "Gal", buy_qty: 1, unit_cost: 85.3827,
      coverage: 275, vendor: "Sherwin-Williams", notes: "" },
    { id: "i2", name: "OPF Primer", category: "Polished Concrete", unit: "Gallon", buy_qty: 5,
      unit_cost: 426.91, coverage: 275, vendor: "Gone Supply Co", notes: "" },
    { id: "i3", name: "Joint Filler", category: "Polished Concrete", unit: "Kit", buy_qty: 1,
      unit_cost: 500, coverage: null, vendor: "Sika", notes: "" },
  ];
  const ASMS4 = [
    { id: "a1", name: "MACRO Flake", unit: "SF", lines: [
      { role: "1st BC", item_id: "i1", coverage: 275, waste_pct: 5, roundup: true, note: "" },
      { role: "", item_id: "i2", coverage: 275, waste_pct: 0, roundup: false, note: "" }] },
    { id: "a2", name: "Cove Base", unit: "LF", lines: [
      { role: "", item_id: "i1", coverage: 275, waste_pct: 0, roundup: true, note: "" }] },
    // Its only material has no coverage and the line does not supply one, so priceAssembly counts
    // it as a fault: this is the row the "Has lines to fix" facet has to find.
    { id: "a3", name: "Saw Cut Fill", unit: "SF", lines: [
      { role: "", item_id: "i3", coverage: null, waste_pct: 0, roundup: true, note: "" }] },
    { id: "a4", name: "Densify Only", unit: "SF", lines: [] },
  ];
  const four = (over) => {
    const b = build(Object.assign({
      ITEMS: JSON.parse(JSON.stringify(ITEMS4)),
      ASMS: JSON.parse(JSON.stringify(ASMS4)),
    }, over || {}));
    b.api.renderList();
    return b;
  };
  // Read every node through these, never off .nodes directly. makeDom creates a node the first
  // time it is ASKED for, so a render that skips a node leaves it absent - and `.hidden` on
  // undefined throws a TypeError out of the harness, which reports a broken invariant as a broken
  // harness. Absent comes back as null instead, and the assertion that cares fails with its own
  // message. (Reading .nodes[id] does not create it; only el(id) does.)
  const has = (d, id) => Object.prototype.hasOwnProperty.call(d.nodes, id);
  const hid = (d, id) => (has(d, id) ? d.nodes[id].hidden : null);
  const txt = (d, id) => (has(d, id) ? d.nodes[id].textContent : null);
  const val = (d, id) => (has(d, id) ? d.nodes[id].value : null);
  const html = (d, id) => (has(d, id) ? d.nodes[id].innerHTML : "");
  const rowsIn = (d) => (html(d, "asm-list").match(/data-open=/g) || []).length;
  const idsIn = (d) => (html(d, "asm-list").match(/data-open="([^"]+)"/g) || [])
    .map((m) => m.slice(11, -1));

  const all = four();
  const hit = four({ asmQuery: "macro" });
  const inside = four({ asmQuery: "primer" });
  const negated = four({ asmQuery: "-primer" });
  const miss = four({ asmQuery: "nothing like this" });
  const lf = four({ ASM_FILTERS: { unit: "LF" } });
  const broken = four({ ASM_FILTERS: { condition: "broken" } });
  const unpriced = four({ ASM_FILTERS: { condition: "unpriced" } });
  const noLines = four({ ASM_FILTERS: { condition: "no_lines" } });
  const agree = four({ asmQuery: "flake", ASM_FILTERS: { unit: "SF" } });
  const disagree = four({ asmQuery: "flake", ASM_FILTERS: { unit: "LF" } });
  const combined = four({ asmQuery: "zzz", ASM_FILTERS: { unit: "LF", condition: "broken" } });
  const none = four({ ASMS: [] });

  out.asmSearch = {
    unfiltered: rowsIn(all.dom),
    filtered: idsIn(hit.dom),
    missed: rowsIn(miss.dom),
    // The point of this box over the item one: it searches the MATERIALS inside each assembly, so
    // "which systems use that primer?" is answerable without opening all of them.
    reachesInside: idsIn(inside.dom),
    // Per TERM, not per haystack. OR-ing the haystacks would make `-primer` mean "some line has no
    // primer in it" — true of a1 — and a1 is exactly the one it has to drop.
    negationIsPerTerm: idsIn(negated.dom),
    unitFacet: idsIn(lf.dom),
    brokenFacet: idsIn(broken.dom),
    unpricedFacet: idsIn(unpriced.dom),
    noLinesFacet: idsIn(noLines.dom),
    // AND across controls, the way the items tab reads.
    queryAndUnitAgree: idsIn(agree.dom),
    queryAndUnitDisagree: rowsIn(disagree.dom),
    // The badge counts what Treadwell HAS. A number that fell as somebody typed would read as
    // assemblies being deleted.
    badgeWhileFiltering: txt(all.dom, "n-asm") === txt(hit.dom, "n-asm"),
    badge: txt(all.dom, "n-asm"),
    hits: txt(hit.dom, "asm-hits"),
    hitsHiddenWhenNotFiltering: hid(all.dom, "asm-hits"),
    noMatchShown: hid(miss.dom, "asm-nomatch") === false,
    noMatchHiddenOnAHit: hid(hit.dom, "asm-nomatch"),
    noMatchWhy: txt(miss.dom, "asm-nomatch-why"),
    combinedWhy: txt(combined.dom, "asm-nomatch-why"),
    // The rail STAYS — the no-match state lives inside it, so hiding the card would hide the
    // message explaining why it is empty.
    railStaysOpenOnNoMatch: hid(miss.dom, "asm-rail"),
    // "+ New assembly" goes with the rows: left up, a typo is answered with an invitation to build
    // the assembly the search just failed to find.
    addRowHiddenOnNoMatch: hid(miss.dom, "asm-addrow"),
    addRowShownOnAHit: hid(hit.dom, "asm-addrow"),
    // THE REASON the no-match state got a node of its own. `#asm-empty` is "add some items first"
    // / "no assemblies yet" and renderPanel owns it; renderList must not touch it, or the two
    // fight over one caption. Untouched means the id was never even created in the stub.
    neverTouchesTheEmptyPanel: has(miss.dom, "asm-empty"),
    clearShownWhileFiltering: hid(hit.dom, "fa-clear"),
    clearHiddenWhenNotFiltering: hid(all.dom, "fa-clear"),
    unitSelectSynced: val(lf.dom, "fa-unit"),
    conditionSelectSynced: val(broken.dom, "fa-condition"),
    barShownWithAssemblies: hid(all.dom, "asm-filterbar"),
    // Nothing to filter is not a filter bar.
    barHiddenWithNoAssemblies: hid(none.dom, "asm-filterbar"),
    // A filtered-out row cannot be the highlighted one, but the PANEL is renderPanel's business —
    // narrowing the rail must not close the assembly somebody is editing.
    currentMarkedWhenShown: /aria-current/.test(html(all.dom, "asm-list")),
    noCurrentWhenOpenOneIsFiltered: /aria-current/.test(html(lf.dom, "asm-list")),
  };
}

// ── B3. the Assemblies tab: six ways to order the rail ──────────────────────
// Hanz, 2026-09-04: "in the assemblies we must be able to sort by vendor, scope or worktype,
// unit, who created it."
//
// SIX FIXTURES, LOCAL TO THIS BLOCK for the reason B2's four are: the module set is one assembly
// and two materials, and growing it would move every row count, badge and datalist asserted
// above. Each one is here to make a specific way of being wrong visible:
//
//   s1  three Sherwin lines and one Ardex — FREQUENCY has to beat alphabet, or an assembly that
//       is three coats of Sherwin product files under the one Ardex patch on it.
//   s5  one Sika line then one Sherwin line — a 1-1 tie, listed Sika first, so "first line wins"
//       and "insertion order" both answer Sika and only the alphabetical rule answers Sherwin.
//   s6  "Sherwin-Williams", "sherwin-williams" and one Sika — `vendor` is FREE TEXT on an item,
//       so two spellings of one supplier must not split the vote three ways.
//   s3  no lines at all, and s4 one line whose material has no supplier — two different routes
//       to "No vendor", and s3 is also the only unpriced row.
//   s2  the only per-LF one, the only one with no category, and the newest.
//   s2/s6 `will@` and `will.baker@` — the ONE pair whose order flips between the raw address and
//       the display name (raw sorts "will.baker@" first, "Will" before "Will Baker" as names),
//       which is what makes "sorted by who created it, not by their email" a real assertion.
{
  const ITEMS6 = [
    { id: "i1", name: "OPF", category: "Epoxy", unit: "Gal", buy_qty: 1, unit_cost: 85.3827,
      coverage: 275, vendor: "Sherwin-Williams", notes: "" },
    { id: "i2", name: "OPF Primer", category: "Epoxy", unit: "Gallon", buy_qty: 5,
      unit_cost: 426.91, coverage: 275, vendor: "Ardex", notes: "" },
    { id: "i3", name: "Joint Filler", category: "Polished Concrete", unit: "Kit", buy_qty: 1,
      unit_cost: 500, coverage: 775, vendor: "Sika", notes: "" },
    // A real material that nobody has named a supplier for. It is not a vendor called "".
    { id: "i4", name: "Unbranded Bag", category: "Gypsum Underlayment", unit: "Bag", buy_qty: 1,
      unit_cost: 22, coverage: 90, vendor: "", notes: "" },
    // The same supplier, typed in lowercase by whoever entered this row.
    { id: "i5", name: "Second Sherwin Coat", category: "Epoxy", unit: "Gal", buy_qty: 1,
      unit_cost: 90, coverage: 275, vendor: "sherwin-williams", notes: "" },
  ];
  const ln = (id) => ({ role: "", item_id: id, coverage: null, waste_pct: 0, roundup: true,
                        note: "" });
  // DELIBERATELY NOT IN NAME ORDER. The live page gets this array from list_assemblies(), which
  // does `.order("name")`, so a fixture in name order could not tell a pass-through apart from a
  // client-side name sort — and which of those two the default is decides whether a
  // just-created assembly stays at the top of the rail.
  const ASMS6 = [
    { id: "s1", name: "MACRO Flake", unit: "SF", category: "Epoxy",
      created_at: "2026-08-01T14:30:00Z", owner_email: "kyle.loseke@wetreadwell.com",
      lines: [ln("i1"), ln("i1"), ln("i2")] },
    { id: "s2", name: "Cove Base", unit: "LF", category: "",
      created_at: "2026-08-20T09:00:00Z", owner_email: "will@wetreadwell.com",
      lines: [ln("i3")] },
    { id: "s3", name: "Densify Only", unit: "SF", category: "Polished Concrete",
      created_at: "2026-08-10T12:00:00Z", owner_email: "", lines: [] },
    { id: "s4", name: "Bag Pour", unit: "SF", category: "Gypsum Underlayment",
      created_at: "2026-08-05T08:00:00Z", owner_email: "hanz@wetreadwell.com",
      lines: [ln("i4")] },
    { id: "s5", name: "Tie Break", unit: "SF", category: "Epoxy",
      created_at: "2026-08-02T10:00:00Z", owner_email: "kyle.loseke@wetreadwell.com",
      lines: [ln("i3"), ln("i1")] },
    { id: "s6", name: "Case Fold", unit: "SF", category: "Epoxy",
      created_at: "2026-08-03T11:00:00Z", owner_email: "will.baker@wetreadwell.com",
      lines: [ln("i1"), ln("i5"), ln("i3")] },
  ];
  const six = (over) => {
    const b = build(Object.assign({
      ITEMS: JSON.parse(JSON.stringify(ITEMS6)),
      ASMS: JSON.parse(JSON.stringify(ASMS6)),
      openId: "s1",
    }, over || {}));
    b.api.renderList();
    return b;
  };
  const has = (d, id) => Object.prototype.hasOwnProperty.call(d.nodes, id);
  const hid = (d, id) => (has(d, id) ? d.nodes[id].hidden : null);
  const txt = (d, id) => (has(d, id) ? d.nodes[id].textContent : null);
  const val = (d, id) => (has(d, id) ? d.nodes[id].value : null);
  const listOf = (d) => (has(d, "asm-list") ? d.nodes["asm-list"].innerHTML : "");
  // THE RENDERED ORDER, off the real rows, not the return of a sort function. renderList could
  // sort and then loop over something else; only reading the markup rules that out.
  const idsIn = (d) => (listOf(d).match(/data-open="([^"]+)"/g) || []).map((m) => m.slice(11, -1));
  // EVERY `.am` LINE of each row, in order, keyed by id — so a label is checked against the row
  // that owns it rather than against a blob of the whole rail, and so its LINE is part of the
  // assertion. The sort label is a second .am rather than a suffix on the first, because on a
  // 272px rail "3 lines · $1.099/SF · Sherwin-Williams +1 more" wraps and leaves those rows a
  // line taller than their neighbours. An array of one therefore means "this sort adds nothing",
  // which is a claim about layout that counting separators could not make.
  const metaIn = (d) => {
    const outp = {};
    listOf(d).split("</button>").forEach((row) => {
      const id = (/data-open="([^"]+)"/.exec(row) || [])[1];
      if (id) outp[id] = (row.match(/<span class="am">([\s\S]*?)<\/span>/g) || [])
        .map((m) => m.slice('<span class="am">'.length, -"</span>".length));
    });
    return outp;
  };

  const byName = six();
  const byNew = six({ ASM_SORT: "new" });
  const byScope = six({ ASM_SORT: "scope" });
  const byUnit = six({ ASM_SORT: "unit" });
  const byVendor = six({ ASM_SORT: "vendor" });
  const byOwner = six({ ASM_SORT: "owner" });
  const sortedAndFiltered = six({ ASM_SORT: "vendor", ASM_FILTERS: { unit: "SF" } });

  // NOT MUTATING THE MODEL. visibleAssemblies hands ASMS itself back when nothing is filtered, so
  // a sort in place would silently reorder the array current(), load()'s first pick and the
  // delete's fallback openId all read.
  const probe = six();
  const arr = [{ id: "z", name: "Zeta", lines: [], created_at: "2026-01-01T00:00:00Z" },
               { id: "a", name: "Alpha", lines: [], created_at: "2026-02-01T00:00:00Z" }];
  const reordered = probe.api.sortAssemblies(arr, "new", []);

  out.asmSort = {
    // ── the default is the SERVER's order, passed through ────────────────────
    // list_assemblies() does `.order("name")`, so this IS name A-Z on a loaded page and the tab
    // looks exactly as it did before the control existed. It also has to be a pass-through rather
    // than a client-side name sort, or the unshift that puts a brand-new assembly at the top of
    // the rail is undone by the very next render.
    defaultKey: byName.api.ASM_SORT,
    defaultIsTheArrayOrder: idsIn(byName.dom),
    namePassesTheArrayThrough: probe.api.sortAssemblies(arr, "name", []) === arr,

    // ── the five orderings ──────────────────────────────────────────────────
    newest: idsIn(byNew.dom),
    scope: idsIn(byScope.dom),
    unit: idsIn(byUnit.dom),
    vendor: idsIn(byVendor.dom),
    owner: idsIn(byOwner.dom),

    // ── the derived vendor ──────────────────────────────────────────────────
    // Read as {primary, others} straight off the real helper as well as off the rendered label,
    // because the count is what the "+N more" is built from and a wrong tally with a right label
    // is not a thing that can happen by accident twice.
    tallyFrequencyBeatsAlphabet: probe.api.asmVendorTally(ASMS6[0], ITEMS6),
    tallyTieGoesAlphabetical: probe.api.asmVendorTally(ASMS6[4], ITEMS6),
    tallyFoldsTheSpelling: probe.api.asmVendorTally(ASMS6[5], ITEMS6),
    tallyNoLines: probe.api.asmVendorTally(ASMS6[2], ITEMS6),
    tallyItemWithNoVendor: probe.api.asmVendorTally(ASMS6[3], ITEMS6),
    vendorLabels: metaIn(byVendor.dom),

    // ── who created it, as a NAME ───────────────────────────────────────────
    ownerLabels: metaIn(byOwner.dom),
    // The whole rail under the author sort. An address anywhere in it fails, which no ordering
    // assertion can promise on its own.
    noAddressInTheRail: /@/.test(listOf(byOwner.dom)),

    // ── the row says what it was ordered by, and only then ──────────────────
    nameLabels: metaIn(byName.dom),
    scopeLabels: metaIn(byScope.dom),
    unitLabels: metaIn(byUnit.dom),
    newLabels: metaIn(byNew.dom),

    // ── it composes with the filters, and is not one of them ────────────────
    filteredThenSorted: idsIn(sortedAndFiltered.dom),
    hitsWhileSortedAndFiltered: txt(sortedAndFiltered.dom, "asm-hits"),
    // A sort narrows nothing: no hits count, no no-match panel, nothing to Clear.
    hitsHiddenWhenOnlySorted: hid(byVendor.dom, "asm-hits"),
    noMatchHiddenWhenOnlySorted: hid(byVendor.dom, "asm-nomatch"),
    clearHiddenWhenOnlySorted: hid(byVendor.dom, "fa-clear"),
    railShownWhenOnlySorted: hid(byVendor.dom, "asm-rail"),
    badgeUnmovedBySorting: txt(byVendor.dom, "n-asm"),

    // ── the control comes back showing the key it is on ─────────────────────
    sortSelectSynced: val(byVendor.dom, "fa-sort"),
    sortSelectSyncedToDefault: val(byName.dom, "fa-sort"),

    // ── the keyboard ────────────────────────────────────────────────────────
    // NOTHING is focused by a render. An estimator tabbing Unit -> Condition -> Sort and picking
    // a key is still in that select; a renderer that focused the search box (which
    // clearAsmFilters legitimately does, which is why the sort must not route through it) would
    // throw them out of the pass they were making. No click ever finds this.
    renderTouchesNoFocus: byVendor.dom.focused.slice(),
    // …and the recorder is not simply broken: this proves a focus() DOES land when called.
    focusProbeWorks: (() => {
      const k = six({ ASM_SORT: "owner" });
      k.dom.el("asm-q").focus();
      return k.dom.focused.slice();
    })(),
    // THE OTHER HALF, and it is a source read rather than an execution — the listener is
    // top-level wiring this harness cannot reach (see listenerBody). The live hazard is routing
    // the sort through clearAsmFilters to share the repaint: that function ends with
    // `$("asm-q").focus()`, which is right for a button that just vanished and wrong for a select
    // the estimator is standing in. The executed half above cannot see it, because it measures
    // what renderList does, not what the listener does.
    sortListenerBody: listenerBody("fa-sort", "change"),

    // ── the model is untouched ──────────────────────────────────────────────
    doesNotMutateTheModel: arr.map((x) => x.id).join(","),
    returnsANewArray: reordered !== arr,
    reorderedCopy: reordered.map((x) => x.id).join(","),

    // ── a brand-new assembly lands at the FRONT, and shows there ────────────
    // Both halves in one scenario, against the real model: placeNewAssembly puts it into the ASMS
    // the renderer reads, and then renderList draws the rail. Under the DEFAULT sort, which is
    // where an estimator who just pressed the button actually is.
    newAssemblyIsFirst: (() => {
      const b = six();
      b.api.placeNewAssembly(b.api.ASMS, {
        id: "new1", name: "New assembly", unit: "SF", category: "",
        // Latest of the six, the way the server stamps it, so "Newest first" agrees.
        created_at: "2026-09-04T15:00:00Z", owner_email: "kyle.loseke@wetreadwell.com",
        lines: [],
      });
      b.api.renderList();
      return idsIn(b.dom);
    })(),
    // …and it stays first when the estimator has chosen the sort that makes it permanent.
    newAssemblyIsFirstUnderNewest: (() => {
      const b = six({ ASM_SORT: "new" });
      b.api.placeNewAssembly(b.api.ASMS, {
        id: "new1", name: "New assembly", unit: "SF", category: "",
        created_at: "2026-09-04T15:00:00Z", owner_email: "kyle.loseke@wetreadwell.com",
        lines: [],
      });
      b.api.renderList();
      return idsIn(b.dom);
    })(),
    // The row it creates is directly under the button, which is the rail's first row — so the
    // ordering of those two nodes in the markup is part of this behaviour, not decoration. Read
    // off the same source the createAction block reads.
    buttonIsAboveTheRowItCreates: (() => {
      const i = html.indexOf('id="asm-rail"');
      const rail = html.slice(i, html.indexOf("</section>", i));
      return rail.indexOf('id="asm-addrow"') < rail.indexOf('id="asm-list"');
    })(),

    // ── the page actually loads the file nameOf comes out of ────────────────
    // THE ONE THING THIS HARNESS CANNOT OTHERWISE NOTICE. It `require`s crm-core.js straight off
    // disk, so every author assertion above stays green on a page that never loads it — and the
    // real failure is a LATE one rather than a loud one: `var CRM = window.TWCrm` leaves CRM
    // undefined quietly, so the tab renders and then throws the first time somebody sorts by who
    // created an assembly. A missing <script> is only visible in the markup.
    crmCoreLoadedBeforeThePageScript: (() => {
      const crm = html.indexOf('src="/js/crm-core.js"');
      const lib = html.indexOf('src="/js/library.js"');
      return crm !== -1 && lib !== -1 && crm < lib;
    })(),

    // ── the six keys the markup offers ──────────────────────────────────────
    optionValues: (() => {
      const i = html.indexOf('id="fa-sort"');
      const j = html.indexOf("</select>", i);
      return (html.slice(i, j).match(/value="([^"]*)"/g) || []).map((m) => m.slice(7, -1));
    })(),
    optionLabels: (() => {
      const i = html.indexOf('id="fa-sort"');
      const j = html.indexOf("</select>", i);
      return (html.slice(i, j).match(/>([^<>]+)<\/option>/g) || [])
        .map((m) => m.slice(1, -"</option>".length));
    })(),
    // The select is inside the filter bar, so `#asm-filterbar[hidden]` has to actually hide it —
    // and a class `display` declaration beats a bare `hidden` attribute. This page's escape hatch
    // is the `!important` rule; four live instances of that bug have existed in this codebase.
    hiddenBeatsAnyDisplayRule: /\[hidden\]\s*\{\s*display:none\s*!important/.test(html),
    // Clear filters clears FILTERS. An ordering hides nothing, so there is nothing to restore,
    // and reshuffling the list from a button labelled Clear filters is the least predictable
    // thing this tab could do. Asserted on the function's source because clearAsmFilters is
    // page wiring rather than a lifted function — the ordering itself is executed everywhere else
    // in this block.
    clearDoesNotResetTheSort: !/ASM_SORT\s*=/.test(fn("clearAsmFilters")),
  };
}

// ── D. the name a copy gets ─────────────────────────────────────────────────
{
  const plain = build().api;
  const crowded = build({ ITEMS: [
    { id: "x1", name: "Densifier", unit: "Gallon", divisions: [] },
    { id: "x2", name: "Densifier (2)", unit: "Gallon", divisions: [] },
    { id: "x3", name: "densifier(3)", unit: "Gallon", divisions: [] },
  ] }).api;
  out.duplicateName = {
    first: plain.duplicateName("Densifier"),
    // The "(n)" comes off the stem first, or a copy of a copy is "Densifier (2) (2)".
    ofACopy: plain.duplicateName("Densifier (2)"),
    // Skips both taken numbers — and the third is taken in a DIFFERENT spelling, which only
    // counts because the comparison goes through nameKey. The server strips punctuation the same
    // way, so a counter matching exact strings would hand back a name the save then refuses.
    skipsTaken: crowded.duplicateName("Densifier"),
    blank: plain.duplicateName(""),
  };

  // ── and the name a NEW row is created under ────────────────────────────────
  // "+ Add material" posted the literal "New material". `create_item` refuses a duplicate name
  // with a 400, so the second press of that button was dead: "Couldn't add that material. "New
  // material" is already in the library." — with nothing on screen explaining that the fix is to
  // go and rename the first one.
  const free = build({ ITEMS: [{ id: "y1", name: "OPF", unit: "Gallon", divisions: [] }] }).api;
  const taken = build({ ITEMS: [
    { id: "y1", name: "New material", unit: "Gallon", divisions: [] },
  ] }).api;
  const takenTwice = build({ ITEMS: [
    { id: "y1", name: "New material", unit: "Gallon", divisions: [] },
    { id: "y2", name: "new  material (2)", unit: "Gallon", divisions: [] },
  ] }).api;
  out.newMaterialName = {
    // Bare stem while it is free: "New material (2)" as the FIRST material would be absurd.
    whenFree: free.newMaterialName("New material"),
    whenTaken: taken.newMaterialName("New material"),
    // Taken in another spelling counts, because the server's own block strips punctuation and
    // spacing the same way — otherwise the button offers a name the save then refuses.
    whenTwoTaken: takenTwice.newMaterialName("New material"),
    blank: free.newMaterialName(""),
    // The Administration tab has the identical literal default, checked against ITS OWN list.
    refWhenFree: free.newRefName("vendors"),
    refWhenTaken: build({ VENDORS: [{ id: "v9", name: "New vendor", notes: "" }] })
      .api.newRefName("vendors"),
    refDivision: build({ DIVISION_REFS: [{ id: "d9", name: "New division", notes: "" }] })
      .api.newRefName("divisions"),
    // A material named "New vendor" must not stop the Vendors tab adding one: the two lists are
    // unique within themselves, not against each other.
    refIgnoresItems: build({
      ITEMS: [{ id: "y1", name: "New vendor", unit: "Gallon", divisions: [] }],
      VENDORS: [],
    }).api.newRefName("vendors"),
  };
}

// ── F. the shared dialog's two opt-ins, EXECUTED out of shared.js ───────────
// Nothing in this repo has ever executed confirmDanger, and that is the second half of why the
// bypass survived review: `noBtn.focus()` is one line inside a requestAnimationFrame and reads as
// an accessibility nicety rather than as the thing that fires a `change` event on whatever the
// estimator was typing in.
//
// Both opt-ins default OFF, so the other callers on this page and the twenty elsewhere in the
// frontend get byte-identical behaviour — which is asserted here rather than assumed, by running
// the SAME function with no options and reading back what it focused and what it listened for.
async function dialogChecks() {
  const sharedSrc = read(path.join(ROOT, "shared.js"));
  const m = /\n  function confirmDanger\s*\(/.exec(sharedSrc);
  if (!m) throw new Error("confirmDanger() is gone from shared.js — rewrite this harness");
  const start = sharedSrc.indexOf("{", m.index + m[0].length - 1);
  let depth = 0, end = -1;
  for (let j = start; j < sharedSrc.length; j++) {
    if (sharedSrc[j] === "{") depth++;
    else if (sharedSrc[j] === "}" && --depth === 0) { end = j + 1; break; }
  }
  const confirmSrc = sharedSrc.slice(m.index, end);

  /** The narrowest DOM the real dialog touches: createElement, one appendChild, querySelector
   *  over the markup it just wrote, and a focus() that records who got it.
   *
   *  Elements are objects rather than parsed HTML because the only questions asked here are "what
   *  did it focus" and "what did it listen for" — but `innerHTML` is really assigned and really
   *  queried, so a renamed internal class breaks the lift rather than passing. */
  function fakeDialogDom() {
    const focused = [];
    const mk = (tag) => {
      const node = {
        tag, className: "", innerHTML: "", textContent: "", children: [], attrs: {},
        listeners: {},
        setAttribute(k, v) { this.attrs[k] = v; },
        getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
        appendChild(c) { this.children.push(c); return c; },
        append(...cs) { this.children.push(...cs); },
        remove() { this.removed = true; },
        addEventListener(ev, fn2) { (this.listeners[ev] = this.listeners[ev] || []).push(fn2); },
        removeEventListener() {},
        focus() { focused.push(this); doc.activeElement = this; },
        classList: { add() {}, remove() {} },
        querySelector(sel) {
          // The dialog writes its own markup and then reads it back by class. Modelled by class
          // name so a rename in that template is a null here and a loud failure, not a pass.
          const known = {
            ".tw-dlg-ic": "ic", ".tw-dlg-h": "h", ".tw-dlg-m": "m", ".tw-dlg-d": "d",
            ".tw-dlg-no": "no", ".tw-dlg-go": "go",
          };
          if (!(sel in known)) {
            throw new Error("the dialog asked for " + sel + ", which this stub does not model");
          }
          this._parts = this._parts || {};
          if (!this._parts[sel]) {
            const part = mk("div");
            part.role = known[sel];
            this._parts[sel] = part;
          }
          return this._parts[sel];
        },
      };
      return node;
    };
    const body = mk("body");
    const doc = {
      activeElement: null,
      body,
      focused,
      docListeners: {},
      createElement: (t) => mk(t),
      createTextNode: (t) => ({ text: t }),
      addEventListener(ev, fn2) {
        (this.docListeners[ev] = this.docListeners[ev] || []).push(fn2);
      },
      removeEventListener() {},
    };
    return doc;
  }

  function sharedGrab(re, what) {
    const m = re.exec(sharedSrc);
    if (!m) throw new Error(what + " is gone from shared.js — rewrite this harness");
    return m[0];
  }

  // TWIcon is the REAL js/icons.js, evaluated once here, because the dialog's glyph now comes out
  // of that table rather than being a character typed into shared.js. Stubbing it would make
  // "the icon slot cannot be filled with caller markup" a claim about the stub.
  const iconsCtx = { window: {} };
  vm.createContext(iconsCtx);
  vm.runInContext(read(path.join(ROOT, "js", "icons.js")), iconsCtx, { filename: "icons.js" });
  const TWIcon = iconsCtx.window.TWIcon;

  const runDialog = new Function("document", "requestAnimationFrame", "setTimeout",
    "injectModalCss", "TWIcon", "opts", `
    "use strict";
    // The dialog keeps a count of how many of itself are on screen, for callers that must not put
    // a second question on top of one being asked. LIFTED, not restated: it lives outside
    // confirmDanger, and without it every call in here throws a ReferenceError inside the promise
    // executor — which surfaces as a rejected promise and an empty overlay rather than as an error.
    ${sharedGrab(/^  let openModals = 0;$/m, "the openModals counter")}
    ${sharedGrab(/^  function modalOpen\(\) \{[^\n]*$/m, "modalOpen()")}
    // Lifted for the same reason: confirmDanger calls it, so a missing icon() is a ReferenceError
    // inside the promise executor rather than a failing assertion.
    ${sharedGrab(/^  function icon\(name, size\) \{[\s\S]*?^  \}$/m, "icon()")}
    ${confirmSrc}
    // A FACTORY, not one call, so a scenario can put two dialogs up in ONE scope and watch the
    // counter. That is the whole reason it is a count and not a boolean: with a flag, the first of
    // two overlapping dialogs closing would report the second one gone.
    return { open: confirmDanger, modalOpen: modalOpen, first: opts && confirmDanger(opts) };
  `);

  function askWith(opts) {
    const doc = fakeDialogDom();
    // The control the page's focus is really on when the dialog goes up. It records who focused
    // it, so "the dialog handed the focus back to a stale element" is a fact rather than a guess.
    const prev = { role: "prev", focused: 0,
                   focus() { this.focused++; doc.activeElement = this; } };
    doc.activeElement = prev;
    const frames = [];
    const later = [];
    const built = runDialog(doc, (fn2) => frames.push(fn2),
      (fn2) => { later.push(fn2); return 1; }, () => {}, TWIcon, opts);
    const promise = built.first;
    frames.forEach((f) => f());                     // the rAF the real helper focuses inside
    // NO SILENT FALLBACK. An empty body means the helper threw inside its own promise executor —
    // a lifted identifier it needs that this scope does not have — and a stub object standing in
    // for the dialog would report that as "it stopped setting tabindex".
    if (!doc.body.children.length) {
      throw new Error("confirmDanger appended no overlay: it threw inside its promise executor, "
        + "most likely on an identifier declared outside the function and not lifted here");
    }
    const ov = doc.body.children[0];
    const dlg = ov.children[0];
    const focusedRole = doc.focused[0] === dlg ? "dialog" : ((doc.focused[0] || {}).role || null);
    return { doc, ov, dlg, promise, focusedRole, prev, modalOpen: built.modalOpen,
             openAnother: (o) => built.open(o),
             // The teardown timer, run on demand: this is where the helper restores the focus it
             // took, which is the piece the row-leave design has to be able to opt out of.
             settle: () => later.forEach((f) => f()),
             icon: () => (dlg._parts || {})[".tw-dlg-ic"],
             fire: (ev, e) => (ov.listeners[ev] || []).forEach((h) => h(e)),
             backdropListens: Object.keys(ov.listeners || {}) };
  }

  /** What the dialog answered, or the fact that it never did.
   *
   *  A promise that never settles is a HANG, and a hung harness prints nothing at all — which
   *  reports as "the harness itself failed" and sends the next reader to this file instead of to
   *  the assertion that broke. A real answer resolves on a microtask, so it always wins the race
   *  against a sentinel scheduled on the next turn of the loop. */
  const answered = (p) =>
    Promise.race([p, new Promise((r) => setImmediate(() => r("never answered")))]);

  const plainAsk = askWith({ title: "Remove this material?", name: "OPF" });
  const optedIn = askWith({ tone: "warn", title: "Save this change?", name: "Densifier",
                            focus: "container", dismiss: "explicit" });
  out.confirmFocus = {
    // DEFAULT, unchanged for every other caller: the No button takes the focus, and a mousedown
    // on the backdrop cancels.
    defaultFocusesCancel: plainAsk.focusedRole === "no",
    defaultHasBackdropCancel: plainAsk.backdropListens.indexOf("mousedown") !== -1,
    // OPTED IN: the dialog element itself takes the focus, so SPACE cannot press a button that
    // was never focused…
    optedInFocusesTheDialog: optedIn.focusedRole === "dialog",
    optedInDialogIsFocusable: optedIn.dlg.getAttribute("tabindex") === "-1",
    // …and the backdrop is inert, so clicking the next cell cannot answer the question.
    optedInHasNoBackdropCancel: optedIn.backdropListens.indexOf("mousedown") === -1,
    // Escape still works in BOTH — an inert backdrop must not mean an unclosable dialog.
    bothTrapTheKeyboard: (plainAsk.doc.docListeners.keydown || []).length === 1 &&
      (optedIn.doc.docListeners.keydown || []).length === 1,
    // The default caller's own defaults are untouched by the new options existing.
    defaultTabindexAbsent: plainAsk.dlg.getAttribute("tabindex") === null,
  };
  // A BACKDROP MOUSEDOWN on the default dialog still cancels it, and on the opted-in one does
  // nothing at all. Both proved by what the promise resolves to, not by a listener count.
  const backdropDefault = askWith({ title: "x", name: "y" });
  backdropDefault.fire("mousedown", { target: backdropDefault.ov });
  out.confirmFocus.defaultBackdropCancels = (await answered(backdropDefault.promise)) === false;

  // ESCAPE CANCELS the opted-in dialog too — an inert backdrop must not mean a trapped estimator.
  const escaped = askWith({ focus: "container", dismiss: "explicit", title: "x", name: "y" });
  (escaped.doc.docListeners.keydown || []).forEach((h) =>
    h({ key: "Escape", preventDefault() {} }));
  out.confirmFocus.escapeStillCancels = (await answered(escaped.promise)) === false;

  // FOCUS RESTORATION. The default caller wants the focus put back where it was — its dialog went
  // up over a live element. The row-leave caller does NOT: focus had already left the row before
  // the question was asked, so `prevFocus` is whatever the browser parked on mid-transition, and
  // handing the focus back to it 170ms later would yank the caret out of wherever the estimator
  // actually went and out of the field confirmItemPatch just restored.
  const restoreDefault = askWith({ title: "x", name: "y" });
  (restoreDefault.doc.docListeners.keydown || []).forEach((h) =>
    h({ key: "Escape", preventDefault() {} }));
  restoreDefault.settle();
  out.confirmFocus.defaultRestoresTheFocus = restoreDefault.prev.focused === 1;

  const restoreOpted = askWith({ focus: "container", dismiss: "explicit", title: "x", name: "y" });
  (restoreOpted.doc.docListeners.keydown || []).forEach((h) =>
    h({ key: "Escape", preventDefault() {} }));
  restoreOpted.settle();
  out.confirmFocus.optedInLeavesTheFocusAlone = restoreOpted.prev.focused === 0;

  // THE MODAL COUNTER, which the Items page reads to avoid stacking a save question on top of a
  // delete confirmation. Two dialogs in ONE scope, because a boolean would report the second one
  // gone the moment the first closed — and that is the case the Items page is exposed to, since
  // the delete dialog's own focus move is what triggers the save it must not ask about yet.
  {
    const counter = askWith({ title: "Remove this material?", name: "OPF" });
    const afterOne = counter.modalOpen();
    const second = counter.openAnother({ title: "And another", name: "OPF" });
    const afterTwo = counter.modalOpen();
    // Close the FIRST one only — through its own Cancel BUTTON, not Escape. Both dialogs listen
    // for Escape on `document`, so an Escape here would close both and this would be measuring
    // nothing. (That both answer one Escape is the shared helper's own long-standing behaviour and
    // not something this change touches.)
    const noBtn = counter.dlg.querySelector(".tw-dlg-no");
    (noBtn.listeners.click || []).forEach((h) => h({}));
    const afterClosingOne = counter.modalOpen();
    // Read BEFORE the second one is closed, or "the other dialog is still waiting" measures
    // nothing: one of them really was answered and the other really was not.
    const firstAnswered = (await answered(counter.promise)) === false;
    const secondStillWaiting = (await answered(second)) === "never answered";
    // …and then the other one, which has to bring the count back to nothing. Without the
    // decrement the Items page would never save again: every flush from here on would defer
    // against a modal that is not on screen.
    const secondDlg = counter.doc.body.children[1].children[0];
    (secondDlg.querySelector(".tw-dlg-no").listeners.click || []).forEach((h) => h({}));
    out.confirmModalCount = {
      beforeAny: false,          // no dialog has been opened in this scope before askWith
      afterOne, afterTwo, afterClosingOne,
      afterClosingBoth: counter.modalOpen(),
      firstAnswered, secondStillWaiting,
    };
  }

  // THE ICON. Until 2026-09-15 the slot was filled with textContent and `icon` was a typed
  // character — the warn tone defaulting to a WASTEBASKET, which is the wrong picture over "Save
  // this change?". `icon` is a js/icons.js NAME now, so the three things worth proving changed
  // with it: every dialog draws an <svg> rather than an emoji, a NAME reaches the right glyph, and
  // a caller's string still cannot become markup — because it is looked up in a table and never
  // concatenated into the output. `iconSvg` is unchanged and still takes literal markup.
  const svgAsk = askWith({ tone: "warn", title: "Save this change?", name: "Densifier",
                           focus: "container", dismiss: "explicit",
                           iconSvg: '<svg class="ic"><path d="M1 1"></path></svg>' });
  const warnDefault = askWith({ tone: "warn", title: "Remove this vendor?", name: "Sika" });
  const namedAsk = askWith({ tone: "warn", title: "x", name: "y", icon: "pencil" });
  // A name nothing will ever match, shaped like an injection attempt. The slot carries
  // customer-typed project and vendor names elsewhere in this dialog, so "a caller's icon string
  // cannot reach the DOM" has to hold for a hostile one, not just an unknown one.
  const HOSTILE = '"><img src=x onerror=alert(1)>';
  const hostileAsk = askWith({ tone: "warn", title: "x", name: "y", icon: HOSTILE });
  const drawn = (a) => (a.icon() || {}).innerHTML || "";
  const EMOJI = /[\u{1F000}-\u{1FAFF}←-➿️]/u;
  out.confirmIcon = {
    svgReachesTheSlot: /<svg class="ic">/.test(drawn(svgAsk)),
    // …and it is not ALSO written as text, which would draw the markup as a literal string.
    svgNotWrittenAsText: !/svg/.test((svgAsk.icon() || {}).textContent || ""),
    // Both tone defaults are DRAWN, and neither is a typed glyph any more.
    warnDefaultIsDrawn: /^<svg /.test(drawn(warnDefault)) && !EMOJI.test(drawn(warnDefault)),
    dangerDefaultIsDrawn: /^<svg /.test(drawn(plainAsk)) && !EMOJI.test(drawn(plainAsk)),
    // The name picks the right glyph: icons.js's own pencil, character for character.
    namedIconIsThatGlyph: drawn(namedAsk) === TWIcon("pencil", 26),
    // An unknown name draws an EMPTY box of the right size rather than throwing or guessing…
    unknownIconDrawsAnEmptyBox: /^<svg [^>]*><\/svg>$/.test(drawn(hostileAsk)),
    // …and no fragment of what the caller passed appears anywhere in the slot.
    hostileIconNeverReachesTheDom:
      drawn(hostileAsk).indexOf("img") === -1 && drawn(hostileAsk).indexOf("onerror") === -1
      && ((hostileAsk.icon() || {}).textContent || "").indexOf("img") === -1,
  };
}

// ── E. a line nobody has filled in is not a broken line ─────────────────────
// "Item removed" is what a line says when its material was DELETED. A line added ten seconds ago
// says the same thing today, in the same amber, on a row flagged broken — which is a fault report
// about the estimator not having finished typing yet.
{
  const blank = build({
    ASMS: [{ id: "b1", name: "Test", unit: "SF", updated_at: "T1",
             lines: [{ role: "", item_id: "", coverage: null, waste_pct: 5, roundup: true }] }],
    openId: "b1",
  });
  blank.api.renderPanel();
  blank.api.refreshNumbers();
  const row = blank.dom.nodes["lines-body"].rows[0];
  out.blankLine = {
    qtyCell: row.cells[5].innerHTML,
    saysPick: /Pick a material/.test(row.cells[5].innerHTML),
    saysRemoved: /Item removed/.test(row.cells[5].innerHTML),
    flaggedBroken: row.classList.has("broken"),
  };
  // …while a line pointing at a material that really is gone still says so, and still is.
  const gone = build({
    ASMS: [{ id: "b2", name: "Test", unit: "SF", updated_at: "T1",
             lines: [{ role: "", item_id: "deleted-one", coverage: 275, waste_pct: 5, roundup: true }] }],
    openId: "b2",
  });
  gone.api.renderPanel();
  gone.api.refreshNumbers();
  const grow = gone.dom.nodes["lines-body"].rows[0];
  out.removedLine = {
    saysRemoved: /Item removed/.test(grow.cells[5].innerHTML),
    flaggedBroken: grow.classList.has("broken"),
  };
}

// ── the picker resolves typed text to a material ─────────────────────────────
{
  const { api } = build();
  out.picker = {
    exact: (api.itemByName("OPF Primer") || {}).id,
    caseInsensitive: (api.itemByName("opf primer") || {}).id,
    trimmed: (api.itemByName("  OPF  ") || {}).id,
    // Never a "closest" guess: silently picking the wrong primer is worse than saying no.
    partialRefused: api.itemByName("OPF Pri"),
    unknownRefused: api.itemByName("Nonsense"),
    blank: api.itemByName(""),
  };
}

// ── the numeric coercion list ────────────────────────────────────────────────
out.numericFields = build().api.NUMERIC_ITEM_FIELDS;

// The real declaration, evaluated — same idiom as numericFields above. Added because a mutation
// run proved nothing caught `updated_by` being dropped from this list: the field would still
// render, and the only symptom would be a Cancel quietly putting back an editor the server had
// already replaced. Executing the whole Cancel path here would cost a dialog scenario; pinning the
// membership costs one line and fails on exactly the mutation that was getting through.
out.serverOwnedItemFields = build().api.SERVER_OWNED_ITEM_FIELDS;

// ── EXECUTED: where the create controls live ────────────────────────────────
// Hanz, 2026-08-27: "I dont like the New assembly button up top." It sat in a .tabaction wrapper
// at the right-hand end of the tab strip, beside Administration and about 1300px from the rail it
// appends a row to. The rule is one rule in five places: a create control sits inside the same
// container as the rows it adds to. WHICH END of that container varies, and each end was asked
// for — the three administration lists at the foot, materials at the top (2026-08-28), and
// assemblies at the top since 2026-09-04 ("Move the assembly button up top and when a new
// assembly is added it should append up top not below").
//
// THE PROPERTY THAT DID NOT CHANGE is the one worth keeping a test on: it is not in the tab
// strip. That is where the 1300px came from.
//
// Read off the real markup and driven through the real renderList, because "it moved" is a
// structural fact a source grep for the id would answer identically before and after.
{
  const between = (open, close, from) => {
    const i = html.indexOf(open, from || 0);
    if (i === -1) return "";
    const j = html.indexOf(close, i);
    return html.slice(i, j === -1 ? html.length : j);
  };
  const tabStrip = between('<div class="views"', "</div>");
  const rail = between('id="asm-rail"', "</section>");

  out.createAction = {
    // GONE FROM THE HEADER. The id itself is retired, so a later edit cannot quietly put it back
    // by re-using the wrapper.
    // Every button left in the strip is a tab. A create control here is exactly what was
    // removed, so anything that is not role="tab" fails this.
    // The class and its rule, not the word: the comment left where the button used to sit names
    // the old wrapper on purpose, so the next reader knows what moved and why.
    goneFromTheTabStrip: !/asm-new-top/.test(html) && !/class="tabaction"/.test(html) &&
      !/\.tabaction\s*\{/.test(html) &&
      (tabStrip.match(/<button/g) || []).length ===
      (tabStrip.match(/role="tab"/g) || []).length,
    // IN THE RAIL CARD — the property the August move was about, and the one that must not
    // regress whichever end it sits at.
    inTheRail: /id="asm-new-2"/.test(rail),
    // AT THE TOP OF IT, before the list rather than after (Hanz, 2026-09-04). Asserted as an
    // ordering rather than as "the id is present", because the two placements are the same
    // markup in a different order and nothing else can tell them apart.
    atTheTopOfTheRail: rail.indexOf('id="asm-new-2"') < rail.indexOf('id="asm-list"'),
    // …and the no-match caption stayed BELOW the list. It is a sentence about the rows that are
    // not there, so it belongs where they would have been; carried up with the button it would
    // sit above an empty list, between the create control and nothing.
    noMatchStillUnderTheList:
      rail.indexOf('id="asm-list"') < rail.indexOf('id="asm-nomatch"'),
    // THE HAIRLINE FOLLOWS THE ROW. `.addrow` draws a border-top, which separates it from rows
    // ABOVE it; at the head of the rail that line lands on the card's own edge and the button
    // bleeds into the first assembly under it. Scoped by id, not by a second class, because the
    // addrow/addbtn literal counts below are what prove this page has one way to say "add
    // another".
    railAddRowFlipsItsBorder: /#asm-addrow \{[^}]*border-top:0[^}]*border-bottom:1px solid/
      .test(html),
    // The same shape in all four places, so the page has ONE way of saying "add another".
    addRowCount: (html.match(/class="addrow"/g) || []).length,
    addBtnCount: (html.match(/class="addbtn"/g) || []).length,
    // Materials moved to the TOP of its card (Hanz, 2026-08-28) — it was getting lost below the
    // horizontal scrollbar and a full table of rows. Still inside the same card as the table;
    // just above it instead of after it. The three administration lists are unchanged, at the
    // foot of theirs.
    materialsAddRowInTheCard: /id="items-addrow"/.test(html) &&
      html.indexOf('id="items-addrow"') < html.indexOf('<tbody id="items-body">'),
    adminAddRows: ["divisions", "units", "vendors"].every((k) =>
      new RegExp('class="addrow" data-addrow-ref="' + k + '"').test(html)),
    // renderRefSection hides those three for a non-admin by that same attribute, so moving the
    // wrapper must not have dropped the hook the permission check hangs on.
    adminAddRowsStillHideable: ["divisions", "units", "vendors"].every((k) =>
      new RegExp('data-addrow-ref="' + k + '"').test(html)),
    // The old below-the-grid wrapper is gone rather than left hidden.
    oldNewRowWrapperGone: !/asm-newrow/.test(html),
  };

  // THE RAIL IS WHAT HIDES, not the list inside it. Hiding only #asm-list would leave the create
  // button alone in an empty card while the "No assemblies yet" panel offered a second one.
  const some = build();
  some.api.renderList();
  const none = build({ ASMS: [] });
  none.api.renderList();
  out.createAction.railShownWithAssemblies = some.dom.nodes["asm-rail"].hidden === false;
  out.createAction.railHiddenWithNone = none.dom.nodes["asm-rail"].hidden === true;
  out.createAction.countStillPainted = some.dom.nodes["n-asm"].textContent;

  // AND THE MATERIALS ADD ROW follows its table. Under "No materials yet" it would be the second
  // Add button in one card; under "Nothing matches that" it would answer a typo with an
  // invitation to create the duplicate the search just failed to find.
  const rows = build();
  rows.api.renderItems();
  const bare = build({ ITEMS: [] });
  bare.api.renderItems();
  const nohits = build({ itemQuery: "nothing like this" });
  nohits.api.renderItems();
  out.createAction.itemsAddRowWithRows = rows.dom.nodes["items-addrow"].hidden === false;
  out.createAction.itemsAddRowWhenEmpty = bare.dom.nodes["items-addrow"].hidden === true;
  out.createAction.itemsAddRowOnNoMatch = nohits.dom.nodes["items-addrow"].hidden === true;
}

// ── EXECUTED: the glyphs are drawn, not typed ───────────────────────────────
// House rule, and not a matter of taste: an emoji is rendered by whatever font the machine has, so
// the delete control is a different picture on Kyle's Windows box than on a phone, it cannot take
// the row's colour on hover, and it ignores every size and stroke token on the page. This page
// shipped with 🗑 in three renderers and ⧉ in a fourth.
//
// The SECOND half is the part a grep would miss. An <svg> inside a <button> becomes the click
// target, and every one of these handlers reads its data- attribute off the element that was
// pressed — so the button goes dead over most of its own area unless something stops that.
{
  const b = build({ ADMIN: true });
  b.api.renderItems();
  b.api.renderVendors();
  b.api.renderPanel();
  const itemRow = b.dom.nodes["items-body"].innerHTML.split("</tr>")[0];
  const refRow = b.dom.nodes["divisions-body"].innerHTML.split("</tr>")[0];
  const lineRow = b.dom.nodes["lines-body"].innerHTML.split("</tr>")[0];
  const everywhere = itemRow + refRow + lineRow + html;
  const glyphs = (itemRow + refRow + lineRow).match(/<svg[^>]*class="ic"[^>]*>/g) || [];

  const rule = (sel) => (new RegExp(sel.replace(/[.>*+?^${}()|[\]\\]/g, "\\$&") +
    "\\s*\\{[^}]*\\}").exec(html) || [""])[0];

  out.icons = {
    // No emoji left anywhere the estimator looks: the three renderers, and the page's own markup.
    // Ranges are the pictographs and the dingbats; the tick inside a division chip is CSS content
    // keyed off :checked and is a typographic mark, not a picture, so it is excluded by range.
    noEmojiInRenderedRows: !/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}]/u
      .test(itemRow + refRow + lineRow),
    // The two specific characters this page used.
    oldGlyphsGone: !/🗑/.test(everywhere) && !/⧉/.test(everywhere),
    // Every control that had one now has a real vector in its place.
    glyphCount: glyphs.length,
    // Lucide's geometry, so these sit beside the sidebar's and the drawer's without arguing.
    allAreLucideShaped: glyphs.length > 0 && glyphs.every((g) =>
      /viewBox="0 0 24 24"/.test(g) && /fill="none"/.test(g) &&
      /stroke="currentColor"/.test(g) && /stroke-width="2"/.test(g) &&
      /stroke-linecap="round"/.test(g)),
    // Decorative: the button already carries the accessible name, so the glyph must not add a
    // second one for a screen reader to read out after it.
    allHiddenFromTheTree: glyphs.length > 0 && glyphs.every((g) => /aria-hidden="true"/.test(g)),
    // The buttons kept their names and their save contract.
    deleteStillNamed: /aria-label="Remove OPF"/.test(itemRow),
    duplicateStillNamed: /aria-label="Duplicate OPF"/.test(itemRow),
    contractUnchanged: /data-dupe-item="i1"/.test(itemRow) && /data-del-item="i1"/.test(itemRow) &&
      /data-del-ref="divisions"/.test(refRow) && /data-del-line="0"/.test(lineRow),
    // THE PRESS STILL LANDS ON THE BUTTON. Two independent answers, because either alone is one
    // tidy-up away from a control that looks fine and does nothing.
    glyphIsNotAClickTarget: /pointer-events:none/.test(rule(".icon svg, .addbtn svg")),
    handlersResolveByClosest: ["data-dupe-item", "data-del-item", "data-del-ref", "data-del-line"]
      .every((a) => src.indexOf('t.closest("[' + a + ']")') !== -1),
  };
}

// ── the page wears the app's own warm palette ───────────────────────────────
// Settled 2026-08-25 after three rejected attempts, and this page was the one screen still
// disagreeing: --surf:#f4f4f5 and --red:#c8102e are a cool grey and a brighter red than the brand
// uses anywhere else, so beside any other Treadwell screen it read as somebody else's product.
{
  const root = (/:root \{ color-scheme: only light;[\s\S]*?\n\s*--r-lg[^}]*\}/.exec(html) ||
                /:root \{ color-scheme: only light;[^}]*\}/.exec(html) || [""])[0];
  const val = (name) => ((new RegExp("--" + name + ":\\s*([^;]+);").exec(root)) || ["", ""])[1].trim();
  out.palette = {
    red: val("red"), redDark: val("red-dark"), redTint: val("red-tint"),
    surf: val("surf"), surfLow: val("surf-low"), ink: val("ink"), inkV: val("ink-v"),
    // ONE type stack. Headings, buttons and totals were set in system-ui while the prose beside
    // them was Inter, so a number and the sentence explaining it were different faces.
    uiStack: val("ui"),
    systemUiLeftInAFontShorthand: /font:[^;]*system-ui/.test(html.replace(/--ui:[^;]+;/, "")),
    // ONE radius scale. There were five, assigned by whichever value the last person typed.
    radiiDeclared: ["r-lg", "r-md", "r-sm"].map(val),
    hardcodedRadii: (html.match(/border-radius:\s*\d+px/g) || [])
      .filter((r) => !/999px/.test(r)),
  };

  // THE CLIPPING TRAP, guarded. The card clips so a full-bleed table head and the add row keep
  // the rounded corners — and any overflow other than `visible` is a clipping context, so the
  // panel holding the item picker has to opt back out or the results list is cut off at the card
  // edge. That bug shipped once already; .tw-nolimit exists because of it.
  const rule2 = (sel) => (new RegExp(sel.replace(/[.>*+?^${}()|[\]\\]/g, "\\$&") +
    "\\s*\\{[^}]*\\}").exec(html) || [""])[0];
  const cardRule = rule2(".card");
  out.palette.cardClips = /overflow:hidden/.test(cardRule);
  out.palette.panelOptsOutOfClipping = /overflow:visible/.test(rule2(".card.apanel"));
  // …and the picker still lives inside that panel, so the opt-out is protecting the right box.
  out.palette.pickerIsInsideThePanel =
    html.indexOf('id="asm-panel"') < html.indexOf('class="tw-nolimit"');
}

// ── the inline style attributes the renderers used to emit ──────────────────
// The house rule is classes, not style attributes, and this page was the worst offender: eight on
// the assembly header row alone, plus a width on every field the three renderers produced.
{
  const b = build({ ADMIN: true });
  b.api.renderItems();
  b.api.renderVendors();
  b.api.renderPanel();
  const rendered = b.dom.nodes["items-body"].innerHTML + b.dom.nodes["divisions-body"].innerHTML +
    b.dom.nodes["units-body"].innerHTML + b.dom.nodes["vendors-body"].innerHTML +
    b.dom.nodes["lines-body"].innerHTML;
  out.inlineStyles = {
    inRenderedMarkup: (rendered.match(/style="[^"]*"/g) || []),
    inThePage: (html.match(/style="[^"]*"/g) || []),
    // The fields still have their widths, they are just wearing them as classes now.
    nameFieldStillSized: /class="cell-name"/.test(rendered),
    costFieldStillSized: /cell-cost/.test(rendered),
  };
}

// ── EXECUTED: bulk add, the four decisions ──────────────────────────────────
// Will wants a dozen materials in one go instead of twelve searches (Hanz, 2026-08-28). The modal
// is not reachable from this stub — no createElement, no focus, no checkbox — so the decisions were
// written as pure functions and are exercised here directly, against the REAL priceLine.
{
  const { api } = build();
  const ids = (list) => list.map((it) => it.id);
  const NO_F = { divisions: [], vendor: "", condition: "" };

  // i1 = OPF / Epoxy / Sherwin-Williams / pack of 1, i2 = OPF Primer / Polished Concrete /
  // Gone Supply Co / pack of 5. Both carry coverage 275, so `seededCoverage` reading [275, 275]
  // is the fixture, not a copied value — the differing PACK size is what makes the priced
  // quantities differ and prove the seed reached each line separately.
  const lines = api.bulkLinesFor(["i1", "i2"], api.ITEMS);
  const priced = lines.map((ln) => L.priceLine(ln, api.ITEMS, 2875));

  // An item with NO coverage of its own must still land, and must still say so honestly.
  const noCov = api.bulkLinesFor(["nocov"], api.ITEMS.concat(
    [{ id: "nocov", name: "Mystery", unit: "Gal", buy_qty: 1, unit_cost: 10, coverage: null,
       divisions: ["Epoxy"], vendor: "" }]));
  const noCovPriced = L.priceLine(noCov[0], api.ITEMS.concat(
    [{ id: "nocov", name: "Mystery", unit: "Gal", buy_qty: 1, unit_cost: 10, coverage: null,
       divisions: ["Epoxy"], vendor: "" }]), 2875);

  out.bulkAdd = {
    // SEARCH — the same matcher as the other two boxes on the page.
    findsByName: ids(api.bulkCandidates(api.ITEMS, "primer", NO_F)),
    findsByVendor: ids(api.bulkCandidates(api.ITEMS, "vendor:sherwin", NO_F)),
    negationWorks: ids(api.bulkCandidates(api.ITEMS, "-primer", NO_F)),
    emptyQueryShowsAll: api.bulkCandidates(api.ITEMS, "", NO_F).length,

    // FACETS — the MODAL's own, passed in. The Items tab's FILTERS must be untouched by this.
    ownFacetNarrows: ids(api.bulkCandidates(api.ITEMS, "",
      { divisions: ["Epoxy"], vendor: "", condition: "" })),
    itemsTabFiltersUnmoved: JSON.stringify(api.FILTERS),

    // TRI-STATE — over what is SHOWN, not the whole library.
    allNone: api.bulkSelectAllState(["i1", "i2"], {}),
    allSome: api.bulkSelectAllState(["i1", "i2"], { i1: true }),
    allAll: api.bulkSelectAllState(["i1", "i2"], { i1: true, i2: true }),
    // Narrowing the search must not untick what is already chosen, nor claim "all" wrongly.
    allOfTheShownOnes: api.bulkSelectAllState(["i2"], { i1: true, i2: true }),
    emptyListIsNone: api.bulkSelectAllState([], { i1: true }),

    // LINES — shape, defaults, and the coverage seed.
    lineCount: lines.length,
    lineKeys: Object.keys(lines[0]).sort(),
    seededCoverage: lines.map((ln) => ln.coverage),
    defaultWaste: lines.map((ln) => ln.waste_pct),
    defaultRoundup: lines.map((ln) => ln.roundup),
    // THE POINT: they price immediately. A missing coverage seed would make these no_coverage,
    // which priceAssembly counts as BROKEN — twelve amber rows on a twelve-material add.
    allPriceable: priced.every((r) => r.ok && r.priced),
    noneReportNoCoverage: priced.every((r) => r.reason !== "no_coverage"),
    firstQty: priced[0].qty,
    // An unknown id is dropped rather than becoming a blank line.
    unknownIdDropped: api.bulkLinesFor(["i1", "ghost"], api.ITEMS).length,
    // An item with no coverage still lands, and reports honestly rather than being refused.
    noCoverageItemStillLands: noCov.length,
    noCoverageItemSaysSo: noCovPriced.reason,

    // ROOM — the 60-line cap, answered before the click.
    maxIsTheServersCap: api.BULK_MAX_LINES,
    roomOnEmpty: api.bulkAddRoom({ lines: [] }, 5),
    roomAt59: api.bulkAddRoom({ lines: new Array(59).fill({}) }, 1),
    roomAt59Over: api.bulkAddRoom({ lines: new Array(59).fill({}) }, 2),
    roomAt60: api.bulkAddRoom({ lines: new Array(60).fill({}) }, 1),
    roomAt61: api.bulkAddRoom({ lines: new Array(61).fill({}) }, 1),
  };
}

// ── EXECUTED: the advanced search grammar ───────────────────────────────────
// Hanz, 2026-08-27: "For the Items and Assemblies under the Items Tab, we must have filters and an
// advanced search." The matcher was a substring test over one haystack; a bare word still behaves
// exactly that way, which is what keeps the assembly picker working, and everything below is new
// on top of it.
//
// EXECUTED against the REAL parser and the REAL fixture materials, because every interesting
// failure is a parsing fact. A grep for "vendor:" would match the regex that reads it.
{
  const { api } = build();
  const names = (q) => api.ITEMS.filter((it) => api.itemMatches(it, q)).map((it) => it.name);

  out.advSearch = {
    // The old behaviour, unchanged. i1 is OPF / Epoxy / Sherwin-Williams, i2 is OPF Primer /
    // Polished Concrete / Gone Supply Co, so a matcher reading only `name` answers these the same.
    bareWordStillSearchesEverything: names("sherwin"),
    bareWordsStillNarrow: names("polished primer"),

    // FIELD SCOPING. "opf" is in both names, so scoping is the only way to tell these apart by
    // vendor, and a scoped term must NOT fall back to the whole haystack when it misses.
    scopedToVendor: names("vendor:sherwin"),
    scopedToName: names("name:primer"),
    scopedToDivision: names("division:epoxy"),
    scopedToUnit: names("unit:gal"),
    // The scope really is a scope: "epoxy" is a DIVISION on i1, so asking for it as a NAME finds
    // nothing. This is the assertion that fails if a scoped term quietly searches everything.
    scopeIsNotAFallback: names("name:epoxy"),
    aliasesAgree: [names("div:epoxy"), names("supplier:sherwin"), names("material:primer")],

    // NUMBERS. i1 costs 85.3827, i2 costs 426.91; packs are 1 and 5.
    costGreaterThan: names("cost:>100"),
    costLessThan: names("cost:<100"),
    costAtLeast: names("cost:>=426.91"),
    costExactly: names("cost:426.91"),
    packExactly: names("pack:5"),
    priceIsAnAliasOfCost: names("price:>100"),
    // Written the way it is written on the invoice.
    toleratesDollarAndComma: names("cost:<$1,000"),

    // NEGATION.
    negatedBareWord: names("-sherwin"),
    negatedScoped: names("-division:epoxy"),
    negationCombinesWithTheRest: names("opf -epoxy"),

    // PHRASES. Two bare words narrow independently, so "opf primer" as separate terms matches a
    // material called "Primer OPF" too; quoted, it is one string in one order.
    phraseIsOneString: names('"opf primer"'),
    phraseInAScope: names('vendor:"gone supply"'),

    // HONEST ABOUT NOTHING. A term the parser cannot make sense of must match NOTHING, never
    // everything: a dropped term hands the full list back and reads as the search being ignored,
    // which is worse than a blank table because it looks like it worked.
    nonsenseNumberFindsNothing: names("cost:abc"),
    unknownFieldIsSearchedLiterally: names("colour:red"),
    // …and a material with NO cost is not a material costing nothing, so it fails every
    // comparison rather than sorting under cost:<1.
    absentCostIsNotZero: api.numberHits(null, "<1"),
    absentCostFailsGreaterThan: api.numberHits(null, ">1"),
    blankIsNotZero: api.numberHits("", "=0"),

    // Still kind while somebody is typing: a scope with nothing after the colon is not yet a term.
    halfTypedScopeShowsEverything: names("vendor:").length,
    blankStillFindsEverything: names("").length,
    // The parse itself, so a change of shape is visible rather than inferred from a match count.
    parsed: api.parseQuery('vendor:"gone supply" cost:>100 -epoxy loose'),
  };
}

// ── EXECUTED: the facets ────────────────────────────────────────────────────
// Three, and each earns its place off a column that already exists. Division and vendor narrow
// what somebody could already find by typing; CONDITION answers the question no search can, which
// is what in this list is not safe to price a bid from.
//
// There is no waste-factor or Roundup? facet because neither is a property of a material: both
// live on an assembly LINE (_clean_lines in backend/library.py). This block proves the fixture
// items carry no such field, so a later reader does not spend an afternoon looking for one.
{
  const FIXTURES = [
    { id: "p1", name: "Priced", divisions: ["Epoxy"], unit: "Gallon", buy_qty: 5,
      unit_cost: 100, coverage: 275, vendor: "Sika", created_at: null,
      cost_updated_at: "2026-08-14T21:15:00Z" },
    { id: "p2", name: "No cost", divisions: ["Epoxy"], unit: "Gallon", buy_qty: 1,
      unit_cost: null, coverage: 275, vendor: "Sika", created_at: null, cost_updated_at: null },
    { id: "p3", name: "Unfiled", divisions: [], unit: "Gallon", buy_qty: 1, unit_cost: 12,
      coverage: 275, vendor: "", created_at: null, cost_updated_at: null },
    { id: "p4", name: "Gyp bag", divisions: ["Gypsum Underlayment"], unit: "Bag", buy_qty: 1,
      unit_cost: 30, coverage: 100, vendor: "Sherwin-Williams", created_at: null,
      cost_updated_at: "2026-08-01T00:00:00Z" },
  ];
  const shown = (filters, q) => {
    const b = build(Object.assign({ ITEMS: JSON.parse(JSON.stringify(FIXTURES)) },
      { FILTERS: Object.assign({ divisions: [], vendor: "", condition: "" }, filters || {}) },
      q === undefined ? {} : { itemQuery: q }));
    return b.api.visibleItems().map((x) => x.name);
  };

  out.facets = {
    // No facet, no query: the list is handed back untouched, not a copy through the filter.
    nothingOnShowsEverything: shown({}).length,

    // DIVISION: ORs within itself, because "epoxy or gypsum" is the question actually asked.
    oneDivision: shown({ divisions: ["Epoxy"] }),
    twoDivisionsOr: shown({ divisions: ["Epoxy", "Gypsum Underlayment"] }),
    divisionIsCaseInsensitive: shown({ divisions: ["ePoXy"] }),

    // VENDOR: an exact match on the value the dropdown offered, not a substring, or picking
    // "Sika" would also pull in a "Sika Distribution Co" that is a different account.
    oneVendor: shown({ vendor: "Sika" }),
    vendorIsCaseInsensitive: shown({ vendor: "sika" }),

    // CONDITION.
    missingACost: shown({ condition: "no_cost" }),
    // ...but not the reserved row that has no material cost by design.
    missingACostWithRemoveExisting: (function () {
      const items = JSON.parse(JSON.stringify(FIXTURES)).concat([{ id: "remove-existing-jf",
        name: "Remove existing joint filler", unit: "SF", buy_qty: 1, unit_cost: null,
        divisions: [], vendor: "" }]);
      const b = build({ ITEMS: items,
                        FILTERS: { divisions: [], vendor: "", condition: "no_cost" } });
      return b.api.visibleItems().map((x) => x.name);
    })(),
    notInAnyDivision: shown({ condition: "no_division" }),
    noVendor: shown({ condition: "no_vendor" }),
    priceNeverRecorded: shown({ condition: "no_price_date" }),

    // ACROSS facets it is AND, so two of them narrow rather than widen.
    facetsAnd: shown({ divisions: ["Epoxy"], condition: "no_cost" }),
    // …and the text box ANDs with them too.
    textAndsWithFacets: shown({ divisions: ["Epoxy"] }, "cost:>50"),
    // A combination nothing satisfies gives nothing, rather than falling back to a wider answer.
    impossibleCombination: shown({ divisions: ["Gypsum Underlayment"], vendor: "Sika" }),
  };

  // The facets are the ITEMS TAB'S, not the matcher's. The assembly line picker searches with
  // itemMatches and must NOT inherit a bar it cannot see — a line quietly unable to find a
  // material because of a filter set on another tab would be unexplainable from where it happens.
  const filtered = build({
    ITEMS: JSON.parse(JSON.stringify(FIXTURES)),
    FILTERS: { divisions: ["Epoxy"], vendor: "", condition: "" },
  });
  out.facets.pickerIgnoresTheFacets =
    /data-pick-item="p4"/.test(filtered.api.itemResultsHtml({ _item_search: "gyp" }));
  out.facets.tabStillObeysThem = filtered.api.visibleItems().map((x) => x.name);

  // No item carries a waste factor or a roundup flag, so neither could be a facet here.
  out.facets.itemsHaveNoWasteOrRoundup = FIXTURES.every(
    (f) => f.waste_pct === undefined && f.roundup === undefined);
}

// ── EXECUTED: the filter survives what re-renders the list ──────────────────
// "The filter state must survive the things that re-render the list - an edit, a save, a tab
// switch back - or it will read as the filter randomly clearing itself."
//
// Two mechanisms, and both are tested because either alone is not enough. The STATE lives in
// plain variables rather than in the DOM, and the CONTROLS live outside the tbody renderItems
// replaces. The third hazard is renderFilterBar itself, which paint() calls on every edit: if it
// rewrote its markup each time it would drop the focus of anybody tabbing the chips, so it only
// writes when the offered values have actually changed.
{
  const b = build({ FILTERS: { divisions: ["Epoxy"], vendor: "Sika", condition: "no_cost" } });

  b.api.renderFilterBar();
  const firstChips = b.dom.nodes["f-divisions"].innerHTML;

  /** Count WRITES to innerHTML, not the value that ends up there.
   *
   *  The first version of this compared the markup before and after and passed against a
   *  renderFilterBar that rebuilt unconditionally - because rebuilding from the same FILTERS
   *  produces a byte-identical string. In a browser that write still destroys every node in the
   *  strip and takes the focus with it, which is the entire bug being guarded against. So the
   *  question is whether the assignment happened, and only a spy can answer it. */
  function countWrites(node) {
    var held = node.innerHTML, n = 0;
    Object.defineProperty(node, "innerHTML", {
      configurable: true,
      get: function () { return held; },
      set: function (v) { n++; held = v; },
    });
    return function () { return n; };
  }
  const chipWrites = countWrites(b.dom.nodes["f-divisions"]);
  const vendorWrites = countWrites(b.dom.nodes["f-vendor"]);

  // An edit and a save both go through renderItems, and paint() calls renderFilterBar after it.
  b.api.renderItems();
  b.api.renderFilterBar();
  b.api.renderItems();
  b.api.renderFilterBar();

  out.filterState = {
    // The chips came back with the active division still on.
    rebuiltFromTheModel: /data-fdiv="Epoxy"[^>]*checked/.test(firstChips),
    // …and were NOT written again on the repeat passes, which is what would cost the focus.
    chipWritesOnRepaint: chipWrites(),
    vendorWritesOnRepaint: vendorWrites(),
    // The selects still say what the model says.
    vendorHeld: b.dom.nodes["f-vendor"].value,
    conditionHeld: b.dom.nodes["f-condition"].value,
    clearOffered: b.dom.nodes["f-clear"].hidden === false,
    // The state is not read back off the DOM at all, so nothing renderItems does can lose it.
    modelHeld: JSON.stringify(b.api.FILTERS),
  };

  // …but an admin ADDING a division must rebuild the strip, or the new value is unfilterable
  // until somebody reloads. Same spy, and here it has to fire exactly once.
  const grown = build({ FILTERS: { divisions: ["Epoxy"], vendor: "", condition: "" } });
  grown.api.renderFilterBar();
  const grownWrites = countWrites(grown.dom.nodes["f-divisions"]);
  grown.api.renderFilterBar();
  out.filterState.quietWhenNothingChanged = grownWrites();
  grown.api.setDivisions(["Polished Concrete", "Epoxy", "Gypsum Underlayment",
                          "Sealer & Traffic Coatings"]);
  grown.api.renderFilterBar();
  const after = grown.dom.nodes["f-divisions"].innerHTML;
  out.filterState.writesAfterANewDivision = grownWrites();
  out.filterState.newDivisionAppears = /data-fdiv="Sealer &amp; Traffic Coatings"/.test(after);
  out.filterState.rebuildKeptTheActiveOne = /data-fdiv="Epoxy"[^>]*checked/.test(after);
  // Free text somebody typed on the Administration tab, escaped rather than injected.
  out.filterState.customIsEscaped = !/data-fdiv="Sealer & Traffic/.test(after);

  // With nothing on, the Clear button is not offered.
  const idle = build();
  idle.api.renderFilterBar();
  out.filterState.clearHiddenWhenIdle = idle.dom.nodes["f-clear"].hidden === true;
}

// ── EXECUTED: the empty state says what it left out ─────────────────────────
// "Empty state: say what was filtered out and offer the way back, do not show a blank rail."
{
  const gone = build({
    FILTERS: { divisions: ["Gypsum Underlayment"], vendor: "Sika", condition: "no_cost" },
    itemQuery: "primer",
  });
  gone.api.renderItems();
  const hit = build({ itemQuery: "primer" });
  hit.api.renderItems();
  // A FACET with an empty search box still counts as filtering. The line this replaced read only
  // itemQuery, so narrowing to a division nothing is filed under produced a blank table with the
  // add row gone and no panel at all.
  const facetOnly = build({ FILTERS: { divisions: ["Nothing Is In Here"], vendor: "", condition: "" } });
  facetOnly.api.renderItems();

  out.filterEmpty = {
    panelShown: gone.dom.nodes["items-nomatch"].hidden === false,
    why: gone.dom.nodes["items-nomatch-why"].textContent,
    // Every active constraint is named, not just the text.
    namesTheQuery: /"primer"/.test(gone.dom.nodes["items-nomatch-why"].textContent),
    namesTheDivision: /Gypsum Underlayment/.test(gone.dom.nodes["items-nomatch-why"].textContent),
    namesTheVendor: /Sika/.test(gone.dom.nodes["items-nomatch-why"].textContent),
    namesTheCondition: /no cost recorded/.test(gone.dom.nodes["items-nomatch-why"].textContent),
    // The way back is offered in the panel as well as the bar, and both press the same handler.
    clearOfferedInThePanel:
      (html.match(/data-clear-filters/g) || []).length === 2 &&
      /id="items-nomatch"[\s\S]*?data-clear-filters/.test(html),
    // A facet alone opens the panel.
    facetAloneOpensThePanel: facetOnly.dom.nodes["items-nomatch"].hidden === false,
    facetAloneExplainsItself: facetOnly.dom.nodes["items-nomatch-why"].textContent,
    // A hit shows the count, not the panel.
    hitHidesThePanel: hit.dom.nodes["items-nomatch"].hidden === true,
    hits: hit.dom.nodes["item-hits"].textContent,
    // The blank rail this replaces: no rows AND no add row, so the panel is the only thing left
    // to explain the screen.
    addRowGoneWhenNothingMatches: gone.dom.nodes["items-addrow"].hidden === true,
    // The tab badge still counts what Treadwell HAS.
    badgeIsStillTheTotal: gone.dom.nodes["n-items"].textContent,
  };
}

// ── the keyboard, and where the controls sit in the markup ──────────────────
{
  const between = (open, close) => {
    const i = html.indexOf(open);
    const j = html.indexOf(close, i);
    return i === -1 ? "" : html.slice(i, j === -1 ? html.length : j);
  };
  out.filterKeyboard = {
    // Escape clears the box. type="search" has a native clear affordance in Chromium but it is a
    // mouse target, and Escape is not wired to it the same way everywhere.
    escapeClears: /if \(e\.key !== "Escape" \|\| !String\(itemQuery\)\.trim\(\)\) return;/.test(src),
    // Every facet control is a real focusable control rather than a div with a click handler.
    divisionsAreCheckboxes: /<input type="checkbox" data-fdiv=/.test(
      (() => { const b = build(); b.api.renderFilterBar(); return b.dom.nodes["f-divisions"].innerHTML; })()),
    vendorIsASelect: /<select id="f-vendor">/.test(html),
    conditionIsASelect: /<select id="f-condition">/.test(html),
    // Named for a screen reader: the chip strip is a group with a label, and the two selects have
    // real <label for> rather than a placeholder standing in for one.
    chipStripIsALabelledGroup:
      /<span class="fchips" id="f-divisions" role="group"\s+aria-labelledby="f-div-label">/
        .test(html.replace(/\r\n/g, "\n")),
    selectsHaveLabels: /<label class="flabel" for="f-vendor">/.test(html) &&
      /<label class="flabel" for="f-condition">/.test(html),
    // THE SYNTAX HINT IS GONE, at Hanz's request on 2026-08-27, and these probes now guard its
    // ABSENCE rather than its presence. He is the person who uses this page every day; a line of
    // grammar help under the box was explaining his own tool to him.
    //
    // The GRAMMAR is untouched - see out.advSearch, which parses all five forms the deleted line
    // used to advertise. Only the on-screen sentence went.
    tipsGone: !/id="search-tips"/.test(html) && !/class="searchtips"/.test(html) &&
      !/Narrow it:/.test(html),
    // NOTHING ORPHANED. The input pointed aria-describedby at that paragraph's id; left behind it
    // is a reference to an element that does not exist, which a screen reader reads as nothing at
    // all rather than as a fault anybody would notice.
    noOrphanedDescribedBy: !/aria-describedby/.test(html),
    searchFieldStillNamed: /<input id="item-q"[\s\S]{0,240}?aria-label="Search materials"/.test(html),
    // The rules and the only <code> on the page went with it, rather than being left as dead
    // stylesheet for the next reader to wonder about.
    searchtipsCssGone: !/\.searchtips/.test(html) && !/<code/.test(html),
    // …and the row closed up. The bar spaces itself with `gap` on the grid, so deleting a child
    // removes its space too - there is no empty container left holding a margin open.
    barClosedUp: /\.filterbar \{[^}]*display:grid[^}]*\}/.test(html) &&
      !/<p class="searchtips"/.test(html) && !/class="filterbar"[^>]*>\s*<\/div>/.test(html),
    // THE COMPOSITION AFTER THE DELETION. The sentence was doing the separating between the search
    // box and the facets; without it the bar's row gap equalled a facet's own label-to-control
    // gap and the two rows read as one block. Each step has to be bigger than the one it
    // contains, so the ORDERING is what is asserted rather than three magic numbers.
    spacingHierarchy: (() => {
      const px = (re) => Number((re.exec(html) || [0, 0])[1]);
      const inFacet = px(/\.facet \{[^}]*gap:(\d+)px/);
      const betweenRows = px(/\.filterbar \{[^}]*gap:(\d+)px/);
      const toTheTable = px(/\.filterbar \{ margin:0 0 (\d+)px/);
      return { inFacet, betweenRows, toTheTable,
               ordered: inFacet > 0 && inFacet < betweenRows && betweenRows < toTheTable };
    })(),
    // THE CONTROLS ARE OUTSIDE THE TBODY renderItems replaces. This is the structural half of the
    // survives-a-re-render answer, and it is a fact about the markup rather than about a variable.
    controlsOutsideTheRenderedBody:
      html.indexOf('id="f-divisions"') < html.indexOf('<tbody id="items-body">') &&
      html.indexOf('id="item-q"') < html.indexOf('<tbody id="items-body">'),
    // And the bar is not a fifth card.
    barIsNotACard: !/class="card[^"]*"[^>]*>\s*<div class="filterbar"/.test(html) &&
      !/class="filterbar card"/.test(html),
  };
}

// ── the Defaults tab's Takeoff list, EXECUTED ────────────────────────────────
{
  const { api, dom: d } = build({
    // THE REAL MODULE, required rather than faked: the whole claim is that this list reads the
    // answers a new estimate opens with, so a made-up freshModel would prove the opposite.
    window: { TWBidModel: require(path.join(ROOT, "js", "bid-model.js")) },
    ITEMS: [{ id: "i1", name: "Densifier", unit: "Pail", unit_cost: 100, favorite: true },
            { id: "i2", name: "Not a default", unit: "Gal", unit_cost: 50, favorite: false }],
    ASMS: [{ id: "a1", name: "Polish 800", unit: "SF", favorite: true,
             lines: [{ item_id: "i1" }, { item_id: "i2" }] },
           { id: "a2", name: "Also not", unit: "SF", favorite: false, lines: [] }],
    // ALL THREE SWITCHED ON, BY OVERRIDE, because from 2026-09-19 all three SHIP off and a
    // listed row is what "on" means -- so a fixture without these renders no condition rows at
    // all and every assertion below would be reading an empty table. What the tool ships is
    // asserted separately, in shippedOffMeansUnlisted, against a fixture with no overrides.
    COND_DEFAULTS: [{ key: "joint_filler", on: true }, { key: "dye", on: true },
                    { key: "remove_existing_jf", on: true }],
    // AN ADMIN, because a condition's Remove is an admin's only (the PUT is _require_admin).
    ADMIN: true,
  });
  // WITH ITS REAL id AND line_key, because the row now carries an editable control and the
  // control is keyed by id -- an idless fixture would render a box that writes nowhere and
  // still pass a test that only looked for the box.
  api.setGlobalMarkup([{ id: "mk-bond-1", line_key: "bond", layout: "global",
                         label: "bond", formula: "1%" }]);
  api.renderDefaultTakeoff();
  const h = d.nodes["default-takeoff-body"].innerHTML;
  out.defaultsTakeoffList = {
    rowCount: (h.match(/<tr>/g) || []).length,
    // THE GROUPS, taken from the function rather than scraped out of the HTML -- the point
    // of separating it was that a test could read them as data. The rendered headings are
    // checked too, because a grouping nothing draws is not a grouping.
    groupTitles: api.takeoffDefaultGroups().map((g) => g.title),
    groupCounts: api.takeoffDefaultGroups().map((g) => g.rows.length),
    renderedHeadings: (h.match(/<th scope="colgroup"[^>]*>([^<]*)<\/th>/g) || [])
      .map((s) => s.replace(/<[^>]*>/g, "")),
    // NO KIND COLUMN ANY MORE. A heading over every group said it already, on every row.
    noKindColumn: !/<td>(Assembly|Material|Condition|Markup)<\/td>/.test(h),
    // AN EMPTY GROUP DRAWS NOTHING, rather than a heading over blank space.
    noEmptyGroups: api.takeoffDefaultGroups().every((g) => g.rows.length > 0),
    // ONLY THE SWITCHED-ON ONES. A list that showed everything would make the switch decorative.
    namesTheDefaults: /Polish 800/.test(h) && /Densifier/.test(h),
    skipsTheRest: !/Not a default/.test(h) && !/Also not/.test(h),
    // Bond appears, and says it is not editable here -- one home per line, which markup.py
    // enforces and this page must not quietly become a second one of.
    // BOND IS STILL HERE and is now EDITABLE -- Hanz, 2026-09-18, asked for no read-only
    // rows. The box writes the markup_rules row BY ID, so it is a second DOOR on one home
    // rather than a second home: markup.py enforces one home per line because two places
    // to set one price disagree the first time somebody changes one, and that is a wrong
    // bid. The id being on the control is what makes it the same row.
    showsBond: /bond/.test(h) && /data-markup-formula=/.test(h),
    bondIsEditableNotReadOnly: !/Read only/.test(h) && /data-markup-formula="/.test(h),
    bondStillSaysWhereItLives: /Markup/.test(h),
    saysWhereBondLives: /Global tab/.test(h),
    // BOND CARRIES NO CONTROL, read off the RENDERED row rather than sliced out of the
    // renderer's source. The source version split on "GLOBAL_MARKUP" and then on "});" and
    // broke the moment the function was regrouped -- it was asserting on punctuation. What
    // actually matters is that the drawn row offers nothing to press: one home per line,
    // and the rate lives on the Markup page.
    // BOND'S ROW, SLICED ROBUSTLY. The old form split on /<tr>/ with a lookahead, which
    // stopped finding the row once group headings (<tr class="grouphead">) joined the table.
    //
    // THE RULE CHANGED SHAPE, NOT STRENGTH. Bond used to carry no control at all; it now
    // carries one, because Hanz asked for no read-only rows. What must still hold is that
    // the control edits the MARKUP ROW, identified by id -- a second DOOR on one home. A
    // control writing a library-local field would be a second HOME, and two homes for one
    // rate disagree the first time somebody changes one, which is a wrong bid.
    bondControlTargetsTheMarkupRule: (function () {
      var rows = h.split("</tr>");
      var row = "";
      for (var i = 0; i < rows.length; i++) {
        if (/bond/i.test(rows[i])) { row = rows[i]; break; }
      }
      return row !== "" && /data-markup-formula="[^"]+"/.test(row) &&
        !/data-def-(edit|off|add)/.test(row);
    })(),
    // ── THE CONDITIONS ARE MATERIALS, 2026-10-01 ─────────────────────────────────────────
    // Hanz, twice before: "don't put in a hard coded or built in line items", then "I told you
    // to remove the built-in and keep and make everything editable in the takeoff." And on
    // 2026-10-01, of joint filler, remove-existing and dye: "make these 3 as materials", then
    // "All 3 exactly like materials". These read the RENDERED row, not the renderer's source,
    // because a regex over markup cannot tell a wired control from a dead one -- which is exactly
    // how the Labor add button shipped green on this same tab. The change is DRIVEN in
    // conditionDefaults below.
    //
    // KEYED BY THE RESERVED ROW'S ID, the way every material row is keyed by its own.
    conditionsAreListedWhenOn: ["joint-filler-kit", "remove-existing-jf", "dye"].every((id) =>
      h.indexOf('data-def-off="items" data-def-id="' + id + '"') !== -1),
    // The chip is gone from the conditions, and gone from the whole table: the Labor tab's
    // Travel row is the only "Built in" left in this page, and it is a different renderer.
    noBuiltInChip: !/Built in/.test(h),
    // ── AND THE YES/NO IS GONE ────────────────────────────────────────────────────────────
    // Hanz, 2026-09-19: "remove these yes and no what are these for?" Asserted as the ABSENCE
    // of the control anywhere in the table, not just on one row -- a select that survived on a
    // single condition is the same complaint again.
    noYesNoSelect: !/data-cond-key=/.test(h) && !/<option value="yes"/.test(h),
    // ── THE COLUMN SAYS WHAT THE LINE COSTS, IN A MATERIAL'S WORDS ─────────────────────────
    // "$X per <unit>", as every material row above says it. These figures are the REAL
    // RATES.JOINT_FILLER_KIT_COST and RATES.DYE_PER_SF, reached through the real module (this
    // fixture has no reserved rows, so the fallback is what prices) -- the page reads them rather
    // than restating them, so a rate that moved in bid-model has to move here too.
    jointFillerShowsItsKitPrice: /\$500\.00 per kit · 1 per 3,500 SF/.test(h),
    jointFillerSaysWhatTheKitCovers: /1 per 3,500 SF/.test(h),
    dyeShowsItsRate: /\$0\.14 per SF a coat · 2 coats</.test(h),
    // AND THE ONE WITH NO PRICE SAYS SO rather than showing an invented $0.00, which would read
    // as free. It is a labor modifier and the Labor step is where it is priced.
    removeExistingSaysItHasNoMaterialCost: /<td>No material cost<\/td>/.test(h),
    // ── NO TAG ─────────────────────────────────────────────────────────────────────────────
    // "writes Polish!E29 · not in a new bid" was the one thing these rows carried that no
    // material row does. Asserted against the whole table, and against both halves of it: the
    // cell, and the on/off sentence.
    noWritesPolishTag: !/writes Polish!/.test(h) && !/Polish!/.test(h),
    noInABidSentence: !/in a new bid/.test(h) && !/in every new bid/.test(h),
    cellIsNotAnInput: !/data-cond-cell/.test(h) && !/value="Polish!E29"/.test(h),
    // ── AND THEY LIVE UNDER MATERIALS, DRAWN BY THE MATERIAL ROW'S OWN CODE ────────────────
    // Sliced out of the RENDERED table between the Materials heading and whatever heading follows
    // it, so a row that merely exists somewhere cannot pass this.
    conditionsSitUnderMaterials: (function () {
      var after = h.split(/<tr class="grouphead">[^]*?Materials<\/th><\/tr>/)[1] || "";
      var section = after.split('<tr class="grouphead">')[0];
      return ["joint-filler-kit", "remove-existing-jf", "dye"].every(function (id) {
        return section.indexOf('data-def-id="' + id + '"') !== -1;
      });
    })(),
    // THE SAME Edit AND Remove, CHARACTER FOR CHARACTER: each condition row's actions cell is
    // exactly what defaultRowActions draws for a material with that id and name -- not a
    // lookalike, and not a copy typed into this file.
    conditionsCarryTheMaterialButtons: api.takeoffDefaultGroups()[1].rows.slice(1)
      .every(function (r, i) {
        var id = ["joint-filler-kit", "remove-existing-jf", "dye"][i];
        return r.actions === api.defaultRowActions("items", id, r.name) &&
               h.indexOf("<td>" + r.name + "</td><td>" + r.how + '</td><td class="rowon">' +
                         r.slider + '</td><td class="rowact">' + r.actions + "</td>") !== -1;
      }) && api.takeoffDefaultGroups()[1].rows.length === 4,
    // …AND THE SAME ROW SHAPE AS THE MATERIAL ABOVE THEM: name, a sentence escaped like any
    // other, and the actions. No rawHow -- nothing in these rows builds its own control any more.
    conditionsAreTheMaterialRowShape: api.takeoffDefaultGroups()[1].rows.every(function (r) {
      // `slider` is the Defaults tab's starting-state slider, the one column every row now has.
      return Object.keys(r).sort().join(",") === "actions,how,name,slider";
    }),
    // AN Edit ON EVERY ONE, which there was not while they had their own row code: it opens the
    // row on the Items tab, where all three are reserved library rows now (focusItemRow is
    // DRIVEN in reservedRows below).
    conditionsCarryEdit: ["joint-filler-kit", "remove-existing-jf", "dye"].every((id) =>
      h.indexOf('data-def-edit="items" data-def-id="' + id + '">Edit</button>') !== -1),
    // THE OLD CONDITION-ONLY ATTRIBUTES ARE GONE, from the table and from the page's source --
    // a second attribute meaning Remove is a second place for the router to forget.
    noConditionOnlyButtons: !/data-cond-off/.test(h) && !/data-def-add="conditions"/.test(h) &&
      !/data-cond-off/.test(src),
    // THE CHIP IS GONE. "Every new bid" sat where the buttons now are, and it was the thing
    // there was nothing to press on.
    noEveryNewBidChip: !/Every new bid/.test(h),
    // NO CONDITIONS HEADING LEFT, because the three of them are the only rows it ever held.
    noConditionsHeading: !/>Conditions</.test(h),
    // THE BUTTONS ARE ROUTED. Read off the SOURCE and labelled as such: the page's click
    // delegation is one long async handler that is not lifted here, so this is the same level of
    // proof the material Edit/Remove pair has -- the markup above is executed, the routing is
    // read, and what Remove calls (removeDefault) is DRIVEN end to end in conditionDefaults.
    removeIsRoutedToTheSaver:
      /removeDefault\(\s*offBtn\.getAttribute\("data-def-off"\),\s*offBtn\.getAttribute\("data-def-id"\)\s*\)/
        .test(src),
    // AND THE WAY ON IS ROUTED TOO: a "conditions" hit in the add search reaches the same saver
    // with true. Without this arm a removed condition could never be restored, and it would be
    // invisible, because the hit renders identically whether or not the router knows the kind.
    addIsRoutedToTheSaver:
      /addKind === "conditions"[\s\S]{0,140}setConditionDefault\([\s\S]{0,80}?,\s*true\)/
        .test(src),
    // THE LISTENER THE SELECT NEEDED IS GONE WITH IT. A `change` handler whose only arm reads
    // data-cond-key would now be waiting on an attribute this page never renders -- dead wiring
    // that reads exactly like live wiring.
    noStaleChangeListener: !/getAttribute\("data-cond-key"\)/.test(src),
  };

  // ── WHAT THE TOOL SHIPS, against a fixture that overrides NOTHING ──────────────────────────
  // The scenario above switches all three on so there are rows to read; this is the other half,
  // and it is the half that pins Hanz's pricing decision. All three ship OFF from 2026-09-19 --
  // joint filler moved, because since 2026-09-18 it carries a real $500 kit per 3,500 sq ft and
  // shipping it on added $2,500 to a 17,500 SF bid nobody had asked for.
  //
  // READ THROUGH THE REAL freshModel, not typed here, so a literal that moved back in
  // bid-model reds this rather than passing against a restated copy.
  {
    const bareModel = require(path.join(ROOT, "js", "bid-model.js"));
    const bare = build({
      window: { TWBidModel: bareModel },
      ITEMS: [], ASMS: [], ADMIN: true,
    });
    bare.api.renderDefaultTakeoff();
    const bh = bare.dom.nodes["default-takeoff-body"].innerHTML;
    bare.api.openDefaultBrowse();
    const browse = bare.dom.nodes["default-hits"].innerHTML;
    out.defaultsShippedConditions = {
      // NONE OF THE THREE IS LISTED WHILE IT IS OFF -- a material that is not a default is not
      // on this list either. 2026-10-01 reverses 2026-09-21 here, at Hanz's word ("All 3 exactly
      // like materials"). This fixture has no items, assemblies or markup, so the table is EMPTY
      // rather than merely missing three names.
      // ALL THREE LISTED, as defaults, with nothing stored (Hanz, 2026-10-01): each the
      // material row's Edit + Remove, keyed by its reserved row. Listed is not ON -- every new
      // bid still starts with all three switched off (noneOfThemOn).
      noneListedWhileOff: ["joint-filler-kit", "remove-existing-jf", "dye"].every((id) =>
        bh.indexOf('data-def-off="items" data-def-id="' + id + '"') !== -1) &&
        !/data-def-add=/.test(bh),
      // …and the add browse offers NONE of them: they are on the list already.
      eachIsOfferedByTheAddSearch: !/data-def-add="conditions"/.test(browse),
      // The three keys the page offers, read off the function rather than the markup, so this
      // still says something when nothing is listed.
      offersTheThree: bare.api.takeoffConditionDefaults().map((c) => c.key).sort().join(","),
      // ...in the order the Takeoff step asks them, and the keys bid-model writes workbook cells for:
      // the three agreements test_the_condition_vocabulary_is_the_same_three_on_both_sides holds.
      offeredInOrder: bare.api.takeoffConditionDefaults().map((c) => c.key),
      cellKeys: Object.keys(bareModel.CONDITION_CELLS),
      noneOfThemOn: bare.api.takeoffConditionDefaults().every((c) => c.on === false),
      // EACH KEY IS ITS RESERVED ROW, BOTH WAYS. takeoffConditionDefaults names the row each key
      // is and RESERVED_ITEM_CONDITION maps the row back; a rename on one side only would list a
      // row whose Remove turns off a different condition, or none.
      keysAndRowsAgree: bare.api.takeoffConditionDefaults().every((c) =>
        bare.api.RESERVED_ITEM_CONDITION[c.item_id] === c.key) &&
        Object.keys(bare.api.RESERVED_ITEM_CONDITION).length === 3,
    };
  }

  // THE WORK-TYPE FILTER IS A THIN WRAPPER OVER THE ONE VOCABULARY (js/work-types.js appliesTo), run through the
  // page's own lifted function: an empty list is every tab, a list is those tabs, and asking it about a JOB
  // TYPE ("combo" has no tab of its own) throws instead of quietly answering "no".
  {
    const wt = api.appliesToWorkType;
    const answer = (row, tab) => { try { return wt(row, tab); } catch (e) { return "threw: " + e.message; } };
    out.defaultsWorkTypeFilter = {
      tabs: api.WORK_TYPES,
      none: answer({}, "gyp"), empty: answer({ default_work_types: [] }, "seal"),
      scopedIn: answer({ default_work_types: ["epoxy", "seal"] }, "seal"),
      scopedOut: answer({ default_work_types: ["epoxy", "seal"] }, "polish"),
      noRow: answer(null, "polish"),
      combo: answer({ default_work_types: [] }, "combo"),
    };
  }

  // THE ADD PATH, DRIVEN. Every assertion here fails against the 2026-09-17 shipping code,
  // where the button had no handler and DEFAULT_Q was never assigned: the box stayed hidden
  // whatever you did, so a default could not be made at all once the row switch came off.
  api.openDefaultBrowse();
  const browse = d.nodes["default-hits"].innerHTML;
  api.setDefaultQuery("Also");
  const typed = d.nodes["default-hits"].innerHTML;
  api.setDefaultQuery("");
  const cleared = d.nodes["default-hits"].innerHTML;
  out.defaultsAddPath = {
    // BROWSE OFFERS THE LIBRARY WITHOUT BEING NAMED. This is the whole point of the
    // button: the search needs you to know the name, and setting defaults up is when you
    // do not. Only the rows that are NOT already defaults, or it would offer them twice.
    browseOffersNonDefaults: /Not a default/.test(browse) && /Also not/.test(browse),
    browseSkipsExistingDefaults: !/Polish 800/.test(browse) && !/Densifier/.test(browse),
    browseRowsAreAddButtons: /data-def-add="items"/.test(browse) &&
                             /data-def-add="assemblies"/.test(browse),
    // TYPING STILL NARROWS. Browse must not have replaced the search.
    typingFilters: /Also not/.test(typed) && !/Not a default/.test(typed),
    // AND CLEARING GOES BACK TO THE LIST, not to nothing -- emptying the box mid-session
    // used to leave you staring at a hidden panel with no way to reopen it.
    clearingReturnsToBrowse: /Not a default/.test(cleared) && /Also not/.test(cleared),
    // THE CARET LANDS IN THE BOX, so the button leads somewhere you can type.
    focusesTheSearch: d.focused[d.focused.length - 1] === "default-q",
  };
}

// ── the Labor defaults: the button Hanz pressed, DRIVEN ──────────────────────
//
// Every assertion in here fails against the code that was on staging on 2026-09-17, where
// "+ Add a labor line" had no handler, the renderer drew exactly one hardcoded row out of
// travelSeed(), and nothing anywhere stored a custom labor line.
async function laborChecks() {
  const seed = (extra) => Object.assign({
    // THE REAL MODULE, for the reason the Takeoff scenario gives: Travel has to come out of
    // travelSeed or this proves nothing about what a new estimate opens holding.
    window: { TWBidModel: require(path.join(ROOT, "js", "bid-model.js")) },
    // One default and one not, because the Takeoff arm of the router opens a BROWSE list of
    // what is not already a default -- a library where everything is one offers nothing, and
    // an empty box would read as the button being dead, which is the bug under test.
    ITEMS: [{ id: "i1", name: "Densifier", unit: "Pail", unit_cost: 100, favorite: true },
            { id: "i2", name: "Not a default", unit: "Gal", unit_cost: 50, favorite: false }],
    ASMS: [{ id: "a1", name: "Polish 800", unit: "SF", favorite: true, lines: [{ item_id: "i1" }] }],
    // THREE STORED LINES, NOT ONE, and the count is the whole point. With a single row
    // "un-favorited the right one" and "un-favorited ALL of them" cannot disagree -- mutate
    // setDefault to wipe the list and a one-row fixture stays green. Two survivors are what
    // make the removal specific, and they are named so the assertion can say which.
    //
    // ALL THREE `favorite: true`, 2026-09-24. Before that column existed, existence in this
    // table WAS "default" -- now a labor type can exist on the Labor tab without being one, and
    // these three are meant to represent lines that already ARE defaults, the same way the
    // ITEMS/ASMS fixture rows above mark theirs explicitly rather than leaving it implicit.
    LABOR: [{ id: "L1", name: "Prevailing wage", rate: 58.25, unit: "hours", guys_auto: false,
              sort: 0, notes: null, owner_email: "kyle@wetreadwell.com", favorite: true },
            { id: "L2", name: "Supervisor", rate: 62.00, unit: "hours", guys_auto: false,
              sort: 1, notes: null, owner_email: "kyle@wetreadwell.com", favorite: true },
            { id: "L3", name: "Mobilization", rate: 450.00, unit: "days", guys_auto: false,
              sort: 2, notes: null, owner_email: "kyle@wetreadwell.com", favorite: true }],
    ADMIN: true,
  }, extra || {});
  const rowsOf = (h) => h.split("</tr>").filter((r) => /<tr/.test(r));
// ── INLINE SEARCH: each "+ Add a ... default" opens the box above ITS OWN table ─────────────
// Hanz, 2026-10-05. A tiny tree stands in for the DOM: two sections, each with a .tw table whose
// parent is the card, and ONE #default-search that insertBefore() moves between the cards.
{
  const { api, dom: d } = build(seed({ LABOR: [{ id: "L9", name: "Rigging", rate: 40,
    unit: "hours", guys_auto: false, favorite: false }] }));
  const mkCard = (name) => {
    const card = { name, kids: [], addBtn: { focus() { d.focused.push(name + "-add"); } },
      querySelector(sel) { return sel === "[data-add-default]" ? this.addBtn : null; },
      insertBefore(n) { if (n.parentNode) n.parentNode.kids = n.parentNode.kids.filter((k) => k !== n);
        n.parentNode = this; this.kids.push(n); } };
    const tw = { parentNode: card };
    d.nodes["default-" + name] = { querySelector: (sel) => (sel === ".tw" ? tw : null) };
    return card;
  };
  const takeoff = mkCard("takeoff"), labor = mkCard("labor");
  const wrap = d.el("default-search");
  wrap.parentNode = takeoff; wrap.hidden = true;
  const q = d.el("default-q");
  const where = () => (wrap.parentNode === takeoff ? "takeoff" : wrap.parentNode === labor ? "labor" : "?");
  const res = {};
  api.openDefaultAdd("labor");
  res.laborOpensAboveLabor = where() === "labor" && wrap.hidden === false;
  res.focusInBox = d.focused[d.focused.length - 1] === "default-q";
  res.laborResultsRendered = /Rigging/.test(d.nodes["default-hits"].innerHTML);
  api.openDefaultAdd("takeoff");
  res.onlyOneOpenAndItMoved = where() === "takeoff" && wrap.hidden === false &&
    takeoff.kids.length === 1 && labor.kids.length === 0;
  api.setDefaultQuery("zzz"); q.value = "zzz";
  api.openDefaultAdd("labor");
  res.movingToAnotherSectionClearsTheQuery = q.value === "" && where() === "labor";
  // ESCAPE closes it, forgets the query and hands focus back to the opener
  q.value = "abc"; api.setDefaultQuery("abc");
  let stopped = false;
  const handled = api.onDefaultSearchKey({ key: "Escape", stopPropagation() { stopped = true; } });
  res.escapeCloses = handled === true && stopped && wrap.hidden === true && q.value === "" &&
    d.nodes["default-hits"].hidden === true && d.focused[d.focused.length - 1] === "labor-add";
  res.otherKeysIgnored = api.onDefaultSearchKey({ key: "a" }) === false;
  // CANCEL is the same close
  api.openDefaultAdd("takeoff");
  api.closeDefaultSearch();
  res.cancelCloses = wrap.hidden === true && d.nodes["default-hits"].hidden === true;
  // THE PAGE WIRES BOTH, as source (a listener body cannot be run from here)
  res.listenersWired = /closest\("\[data-def-search-close\]"\)\) \{ closeDefaultSearch\(\); return; \}/.test(src) &&
    /addEventListener\("keydown", onDefaultSearchKey\)/.test(src);
  out.defaultsInlineSearch = res;
}


  // THE LIST: Travel built in, the favorited lines beside it, each with the controls it should
  // have. Edit now sends an admin to the Labor tab (data-def-edit="labor"), the same attribute
  // and the same click-router branch a favorited item or assembly default already uses -- see
  // renderLabor's own scenarios in laborTabChecks() for what that tab does with the press.
  {
    const { api, dom: d } = build(seed());
    api.renderDefaultLabor();
    const h = d.nodes["default-labor-body"].innerHTML;
    const rows = rowsOf(h);
    out.laborDefaultsList = {
      rowCount: rows.length,
      // Travel FIRST, and on the rate the tool ships with -- this fixture's LABOR holds NO row
      // with the reserved id, which is the state any database is in before the seed row is
      // inserted.
      travelIsFirst: /Travel/.test(rows[0] || ""),
      travelShowsTheShippedRate: /\$33\.00/.test(rows[0] || ""),
      // NO "BUILT IN" CHIP. Hanz, twice: "don't put in a hard coded or built in line items", and
      // then on this very row: "again this too how can we edit this?".
      noBuiltInChip: !/Built in/.test(rows[0] || ""),
      // AND NO CONTROLS EITHER, while there is no row to address. An Edit here would send an
      // admin to a Labor tab row that does not exist -- worse than the chip it replaced, not
      // better. The scenarios below are where the controls appear.
      travelCarriesNoControls: !/data-def-edit="labor"/.test(rows[0] || "") &&
        !/data-labor-reset/.test(rows[0] || ""),
      // The favorited line, which the old renderer could not draw at all.
      listsTheStoredLine: /Prevailing wage/.test(rows[1] || ""),
      storedLineShowsItsRate: /\$58\.25/.test(rows[1] || ""),
      storedLineSaysPerHour: /\/ hr/.test(rows[1] || ""),
      // THE SAME PAIR A FAVORITED ITEM OR ASSEMBLY DEFAULT ALREADY CARRIES -- defaultRowActions,
      // not a labor-specific button. Edit says which tab and which row; Remove is "stop being a
      // default", never a delete.
      storedLineCanBeEdited: /data-def-edit="labor" data-def-id="L1"/.test(rows[1] || ""),
      storedLineCanBeRemoved: /data-def-off="labor" data-def-id="L1"/.test(rows[1] || ""),
      addRowOfferedToAnAdmin: d.nodes["default-labor-addrow"].hidden === false,
    };
  }

  // A LABOR TYPE THAT IS NOT YET A DEFAULT DOES NOT SHOW HERE. This is the counter-example the
  // `favorite` filter exists for: before it, existence in this table was the whole story and
  // every labor type Treadwell had typed showed up on this tab, defaults and non-defaults alike.
  {
    const { api, dom: d } = build(seed({
      LABOR: [{ id: "L1", name: "Prevailing wage", rate: 58.25, unit: "hours",
                guys_auto: false, favorite: true },
              { id: "L9", name: "Not a default yet", rate: 999, unit: "hours",
                guys_auto: false, favorite: false }],
    }));
    api.renderDefaultLabor();
    const h = d.nodes["default-labor-body"].innerHTML;
    out.laborNonFavoriteHiddenFromDefaultsTab = {
      favoritedLineShown: /Prevailing wage/.test(h),
      nonFavoritedLineHidden: !/Not a default yet/.test(h),
    };
  }

  // ── TRAVEL IS EDITABLE, 2026-09-19 ─────────────────────────────────────────
  //
  // The row carrying the reserved id `travel` is seeded by both schema files. Everything below
  // is what an admin sees once it exists, and every one of these fails against the renderer that
  // drew `<span class="builtin">Built in</span>` and nothing else.
  const TRAVEL_EDITED = { id: "travel", name: "Travel", rate: 41.50, unit: "hours",
                          guys_auto: true, sort: -1, notes: null,
                          owner_email: "hanz@wetreadwell.com" };
  const TRAVEL_SHIPPED = { id: "travel", name: "Travel", rate: 33.00, unit: "hours",
                           guys_auto: true, sort: -1, notes: null, owner_email: null };

  // THE EDITED ROW: one Travel line, showing the STORED rate, with Edit and Reset.
  {
    const { api, dom: d } = build(seed({ LABOR: [TRAVEL_EDITED,
      { id: "L1", name: "Prevailing wage", rate: 58.25, unit: "hours", guys_auto: false,
        favorite: true }] }));
    api.renderDefaultLabor();
    const h = d.nodes["default-labor-body"].innerHTML;
    const rows = rowsOf(h);
    out.laborTravelStored = {
      // ONE Travel row, not two. The stored row is drawn THROUGH travelSeed and then excluded
      // from the custom list -- left in, an admin would see the same name twice, each with its
      // own controls, and no way to tell which one prices a bid.
      travelRowCount: rows.filter((r) => /Travel/.test(r)).length,
      rowCount: rows.length,
      // The stored rate, NOT the shipped one. This is the assertion that fails if the row is
      // stored, listed, edited -- and ignored.
      showsTheStoredRate: /\$41\.50/.test(rows[0] || ""),
      doesNotShowTheShippedRate: !/\$33\.00/.test(h),
      // EDIT NOW SENDS AN ADMIN TO THE LABOR TAB, 2026-09-24 -- the same data-def-edit="labor"
      // attribute and the same click-router branch a favorited item or assembly default already
      // uses, not a bespoke data-labor-edit any more.
      canBeEdited: /data-def-edit="labor" data-def-id="travel"/.test(rows[0] || ""),
      // RESET, NOT REMOVE. Removing Travel is not a thing that can happen -- freshModel() seeds
      // it into every new bid -- so the word on the button is the word for what it does.
      offersReset: /data-labor-reset="travel"/.test(rows[0] || ""),
      // REMOVE IS OFFERED NOW (2026-10-06): the same Edit + Remove pair as every labor default.
      // Remove is favorite=false on the row, not a delete.
      offersRemove: /data-def-off="labor" data-def-id="travel"/.test(rows[0] || ""),
      resetSaysReset: />Reset</.test(rows[0] || ""),
      // The favorited line is untouched by any of it.
      stillListsTheCustomLine: /Prevailing wage/.test(h),
    };
  }

  // TRAVEL AS A DEFAULT LIKE ANY OTHER (2026-10-06): Remove = favorite=false (a PATCH on the row,
  // never a delete), a removed Travel is off the Defaults list and offered back by the "add a
  // labor default" browse, and the work-type sub-tabs filter it.
  {
    const withTravel = (extra) => Object.assign({ id: "travel", name: "Travel", rate: 33,
      unit: "hours", guys_auto: true, sort: -1, notes: null, owner_email: null }, extra || {});
    const calls = (h) => h.api.LABOR_CALLS;
    // Remove, executed: the row is dropped from the list and favorite=false is what is sent.
    const r1 = build(seed({ LABOR: [withTravel({ favorite: true })] }));
    r1.api.renderDefaultLabor();
    const before = r1.dom.nodes["default-labor-body"].innerHTML;
    r1.api.LABOR_CALLS.length = 0;
    await r1.api.setDefault("labor", "travel", false);
    const gone = r1.dom.nodes["default-labor-body"].innerHTML;
    const delCalls = r1.api.LABOR_CALLS.filter((c) => c.op === "DELETE");
    // Not a default -> not offered as a row; the browse offers it back.
    r1.api.setWorkType("polish");
    r1.api.openDefaultBrowse && r1.api.openDefaultBrowse();
    const cand = r1.api.defaultCandidates().rows.filter((c) => c.kind === "labor" && c.id === "travel");
    // Work-type sub-tabs: scoped to epoxy, Travel is on the Epoxy tab and not on the Polish tab.
    const r2 = build(seed({ LABOR: [withTravel({ favorite: true, default_work_types: ["epoxy"] })] }));
    r2.api.setWorkType("polish"); r2.api.renderDefaultLabor();
    const onPolish = /Travel/.test(r2.dom.nodes["default-labor-body"].innerHTML);
    r2.api.setWorkType("epoxy"); r2.api.renderDefaultLabor();
    const onEpoxy = /Travel/.test(r2.dom.nodes["default-labor-body"].innerHTML);
    // favorite absent/null with no work types: listed on every tab, as before.
    const r3 = build(seed({ LABOR: [withTravel({ favorite: null })] }));
    r3.api.setWorkType("gyp"); r3.api.renderDefaultLabor();
    const legacyOnGyp = /Travel/.test(r3.dom.nodes["default-labor-body"].innerHTML);
    out.travelAsDefault = {
      listedBefore: /Travel/.test(before),
      removeIsFavoriteFalse: calls(r1).some((c) => c.op === "PATCH_DEFAULT" && c.kind === "labor" &&
        c.id === "travel" && c.on === false),
      noDelete: delCalls.length === 0,
      goneAfterRemove: !/Travel/.test(gone),
      offeredBack: cand.length === 1,
      onPolish, onEpoxy, legacyOnGyp,
    };
  }

  // THE UNEDITED ROW: editable, but nothing to reset it TO, so no Reset button at all. A control
  // that would change nothing is a control that reads as broken the moment somebody presses it.
  {
    const { api, dom: d } = build(seed({ LABOR: [TRAVEL_SHIPPED] }));
    api.renderDefaultLabor();
    const h = d.nodes["default-labor-body"].innerHTML;
    out.laborTravelUnedited = {
      canBeEdited: /data-def-edit="labor" data-def-id="travel"/.test(h),
      noResetOffered: !/data-labor-reset/.test(h),
      showsTheShippedRate: /\$33\.00/.test(h),
    };
  }
  // …and a RENAME alone brings Reset back, because the Labor tab's row writes the name too and a
  // renamed Travel with the shipped rate would otherwise have no way home.
  {
    const { api, dom: d } = build(seed({
      LABOR: [Object.assign({}, TRAVEL_SHIPPED, { name: "Drive time" })] }));
    api.renderDefaultLabor();
    const h = d.nodes["default-labor-body"].innerHTML;
    out.laborTravelRenamed = {
      showsTheStoredName: /Drive time/.test(h),
      offersReset: /data-labor-reset/.test(h),
    };
  }

  // EDITING TRAVEL NOW HAPPENS ON THE LABOR TAB, 2026-09-24 -- see laborTabChecks() for
  // onLaborEdit patching the reserved id through the same debounced path every other row uses,
  // and for the delete icon withheld specifically for it. This scenario, and the one that used to
  // sit here driving a Defaults-tab form (openLaborForm("travel") -> submitLaborForm()), retired
  // together: there is no longer a form on this tab for Travel's own row to open.

  // RESET PUTS THE SHIPPED RATE BACK -- as a PATCH, and deliberately NOT as a DELETE. A soft
  // delete would also read correctly on screen (list_labor stops answering, travelSeed falls
  // back) but it takes the only id anything can address Travel by with it: LibraryLaborIn has no
  // id field and create_labor mints a uuid, both on purpose, so nothing on this page could ever
  // make the row again. One press would cost the editability permanently.
  {
    const { api, dom: d } = build(seed({ LABOR: [TRAVEL_EDITED] }));
    api.renderDefaultLabor();
    await api.resetTravelDefault();
    const h = d.nodes["default-labor-body"].innerHTML;
    out.laborTravelReset = {
      op: (api.LABOR_CALLS[0] || {}).op,
      neverDeletes: api.LABOR_CALLS.every(function (c) { return c.op !== "DELETE"; }),
      sentToTravel: (api.LABOR_CALLS[0] || {}).id === "travel",
      // The SHIPPED figures, read out of travelSeed rather than typed on this page -- the second
      // copy of Travel's rate is exactly what drifted within a day the last time it existed.
      body: (api.LABOR_CALLS[0] || {}).body,
      showsTheShippedRate: /\$33\.00/.test(h),
      // The button retires itself: there is nothing left to reset.
      resetGoneAfterwards: !/data-labor-reset/.test(h),
      stillEditable: /data-def-edit="labor" data-def-id="travel"/.test(h),
      // THE ROW SURVIVES. It is what keeps Travel editable tomorrow.
      rowStillInTheModel: api.laborNow().some(function (r) { return r.id === "travel"; }),
      travelStillListed: /Travel/.test(h),
    };
  }

  // A REFUSED RESET PUTS IT BACK AND SAYS WHY, like both writes beside it. A rate that looks
  // reset and returns on the next reload is worse than one that refuses out loud.
  {
    const { api, dom: d } = build(seed({ LABOR: [TRAVEL_EDITED], LABOR_FAIL: { patch: true } }));
    api.renderDefaultLabor();
    await api.resetTravelDefault();
    const h = d.nodes["default-labor-body"].innerHTML;
    out.laborTravelResetFails = {
      putTheStoredRateBack: /\$41\.50/.test(h),
      notLeftOnTheShippedRate: !/\$33\.00/.test(h),
      saidSo: /Couldn't reset/.test(d.nodes["alert"].textContent),
      saysWhy: /the server said no/.test(d.nodes["alert"].textContent),
      rowStillInTheModel: api.laborNow().length === 1,
      rateStillInTheModel: (api.laborNow()[0] || {}).rate,
      // And the way back is still on screen rather than having retired itself on a write that
      // did not happen.
      resetStillOffered: /data-labor-reset/.test(h),
    };
  }

  // NOT FOR A NON-ADMIN, even with the row stored. The writes are admin-only on the server, so
  // neither control is offered -- the rule the rest of this page already follows.
  {
    const { api, dom: d } = build(seed({ LABOR: [TRAVEL_EDITED], ADMIN: false }));
    api.renderDefaultLabor();
    const h = d.nodes["default-labor-body"].innerHTML;
    out.laborTravelReadOnly = {
      stillListsTravel: /Travel/.test(h),
      showsTheStoredRate: /\$41\.50/.test(h),
      noControls: !/data-def-edit="labor"/.test(h) && !/data-labor-reset/.test(h),
    };
  }

  // THE BUTTON'S OWN ROUTING, EXECUTED, 2026-09-24 -- BOTH ARMS OPEN THE SAME BROWSE NOW. This is
  // the historical incident's exact shape one level down: for a day the Labor arm of this router
  // was markup with no handler, and the only test over it matched the pane for the right
  // data-attribute, which a dead button carries perfectly. Today's risk is the mirror image --
  // the labor arm quietly reverting to nothing, or the takeoff arm losing its own behaviour on
  // the way past -- so both are driven and neither is assumed from the other passing.
  {
    const { api, dom: d } = build(seed({
      LABOR: [{ id: "L1", name: "Prevailing wage", rate: 58.25, unit: "hours",
                guys_auto: false, favorite: true },
              { id: "L9", name: "Rigging", rate: 40, unit: "hours",
                guys_auto: false, favorite: false }],
    }));
    api.renderDefaultLabor();
    api.openDefaultAdd("labor");
    const afterLabor = d.nodes["default-hits"].innerHTML;
    const { api: api2, dom: d2 } = build(seed());
    api2.renderDefaultLabor();
    api2.openDefaultAdd("takeoff");
    out.laborAddButtonRouting = {
      // THE LABOR ARM OPENS THE SHARED BROWSE, and the un-favorited labor type is in it -- the
      // same box the Takeoff button opens, not a labor-only picker of its own.
      laborOpensBrowse: /data-def-add="labor"/.test(afterLabor) && /Rigging/.test(afterLabor),
      // AND STILL OFFERS THE OTHER TWO KINDS, unchanged. One router now opens one shared list
      // for all three, and this is the assertion that a labor-only filter did not creep in on
      // the way to collapsing the two arms.
      laborBrowseStillOffersItemsAndAssemblies: (function () {
        // AN ASSEMBLY THAT IS NOT YET A DEFAULT, so the browse has one to offer -- seed()'s only
        // assembly is already a default, and a browse of nothing cannot show the kind is still in.
        const { api: a4, dom: d4 } = build(seed({ ASMS: seed().ASMS.concat([
          { id: "a2", name: "Seal coat", unit: "SF", favorite: false, lines: [] }]) }));
        a4.openDefaultAdd("labor");
        const hh = d4.nodes["default-hits"].innerHTML;
        return /data-def-add="items"/.test(hh) && /data-def-add="assemblies"/.test(hh);
      })(),
      takeoffOpensBrowse: /data-def-add=/.test(d2.nodes["default-hits"].innerHTML),
      // A THIRD CATEGORY OPENS NOTHING rather than falling through to one of these two.
      unknownOpensNothing: (function () {
        const { api: a3, dom: d3 } = build(seed());
        a3.renderDefaultLabor();
        a3.openDefaultAdd("something-else");
        return !((d3.nodes["default-hits"] || {}).innerHTML || "");
      })(),
      // THE LINE THIS FILE CANNOT RUN: the page's click listener is top-level wiring inside its
      // IIFE, so no scenario here can reach it. Read as SOURCE, which is the narrow case this
      // harness's own doc allows -- a listener that calls the wrong helper is a wiring mistake,
      // and a wiring mistake is exactly what a source assertion can see.
      listenerCallsTheRouter:
        /addDef\) \{\s*openDefaultAdd\(addDef\.getAttribute\("data-add-default"\)\);/.test(src),
      // THE NEW LABOR TAB'S OWN THREE, each dispatching to the function tested in
      // laborTabChecks() below -- the same wiring-mistake shape the router check above guards,
      // asked of the tab where a labor TYPE is actually made and unmade now.
      listenerWiresTheLaborTab:
        /closest\("\[data-add-labor\]"\)\) \{ await addLaborLine\(\); return; \}/.test(src) &&
        /closest\("\[data-del-labor\]"\);\s*if \(delLab\) \{ await removeLaborLine\(delLab\.getAttribute\("data-del-labor"\)\);/.test(src) &&
        /data-labor-more-toggle[\s\S]{0,120}toggleLaborMore\(/.test(src) &&
        // The two edit listeners on the table, both events, for the reason onItemEdit's give: a
        // text box reports `input`, a select and a checkbox only promise `change`.
        /\$\("labor-body"\)\.addEventListener\("input", onLaborEdit\)/.test(src) &&
        /\$\("labor-body"\)\.addEventListener\("change", onLaborEdit\)/.test(src),
    };
  }

  // THE SHARED SEARCH RETURNS LABOR TOO, 2026-09-24 -- defaultCandidates() itself, EXECUTED. The
  // design's own words: "the same search-and-browse mechanism Items/Assemblies already use
  // there". Travel is checked absent on purpose -- it is not opted into a bid the way a
  // favorited default is, so offering it here would be a second, misleading way to "add" a line
  // that is on every bid regardless of anything this box could do to it.
  {
    const { api } = build(seed({
      LABOR: [{ id: "L1", name: "Prevailing wage", rate: 58.25, unit: "hours",
                guys_auto: false, favorite: true },
              { id: "L9", name: "Rigging", rate: 40, unit: "hours",
                guys_auto: false, favorite: false },
              { id: "travel", name: "Travel", rate: 33, unit: "hours",
                guys_auto: true, favorite: true }],   // a Travel that IS a default is listed, never offered again
    }));
    api.setDefaultQuery("rig");
    const hits = api.defaultCandidates().rows;
    // AND THE WHOLE BROWSE, not just a search: "rig" cannot match the favorited line or Travel,
    // so asking only it whether they are offered would be a question with one possible answer.
    api.setDefaultQuery("");
    api.openDefaultBrowse();
    const all = api.defaultCandidates().rows;
    out.defaultCandidatesIncludeLabor = {
      findsTheUnfavoritedLaborType: hits.some((r) => r.kind === "labor" && r.id === "L9"),
      labelledLabor: (hits.find((r) => r.id === "L9") || {}).what,
      // THE FAVORITED ONE IS NOT OFFERED AGAIN -- it is already a default, the same rule
      // ITEMS/ASMS already follow for their own favorited rows.
      browseOffersIt: all.some((r) => r.kind === "labor" && r.id === "L9"),
      favoritedLaborNotOffered: !all.some((r) => r.id === "L1"),
      travelNeverOffered: !all.some((r) => r.id === "travel"),
    };
  }

  // NOT FOR EVERYBODY. Every write to library_labor is admin-only on the server -- `favorite`
  // included, because making a line a default is a PATCH to /api/library/labor -- so a non-admin
  // is handed neither the row pair nor the Add button, and the shared browse offers them no labor
  // to add. The list itself stays readable: what a new bid opens holding is worth seeing either way.
  {
    const { api, dom: d } = build(seed({ ADMIN: false,
      LABOR: seed().LABOR.concat([{ id: "L9", name: "Rigging", rate: 40, unit: "hours",
                                     guys_auto: false, favorite: false }]) }));
    api.renderDefaultLabor();
    const h = d.nodes["default-labor-body"].innerHTML;
    api.openDefaultBrowse();
    const hits = api.defaultCandidates().rows;
    out.laborDefaultsReadOnly = {
      stillListsTheLine: /Prevailing wage/.test(h),
      noRowControls: !/data-def-edit="labor"/.test(h) && !/data-def-off="labor"/.test(h),
      addRowHidden: d.nodes["default-labor-addrow"].hidden === true,
      noLaborToAdd: !hits.some((r) => r.kind === "labor"),
      // AND ONLY THE LABOR IS WITHHELD. Favoriting a material is not admin-gated on the server,
      // so a non-admin's browse still offers one -- a gate on the whole list would be a new rule.
      stillOffersAMaterial: hits.some((r) => r.kind === "items"),
    };
  }

  // A RATE THAT ARRIVES AS A STRING still reads as money. numeric(10,2) commonly serialises as
  // "41.00" and not 41.00, and there is no guarantee which this endpoint hands back -- a row that
  // showed an em dash where the rate goes would read as a line nobody had priced yet.
  {
    const { api, dom: d } = build(seed({
      LABOR: [{ id: "L2", name: "Night differential", rate: "41.00", unit: "days",
                guys_auto: true, favorite: true }],
    }));
    api.renderDefaultLabor();
    const h = d.nodes["default-labor-body"].innerHTML;
    out.laborStringRate = {
      readsAsMoney: /\$41\.00/.test(h),
      notTheRawString: !/>41\.00</.test(h),
      // And guys_auto is explained rather than left blank, the same way Travel's is.
      guysAutoIsExplained: /Night differential[\s\S]*?Man-days come off the crew rows/.test(h),
    };
  }

  // MAKING A LABOR LINE A DEFAULT, AND TAKING IT BACK OFF -- setDefault on the labor kind,
  // EXECUTED, through the real paint(). Add is `favorite: true` and Remove is `favorite: false`:
  // the same one-field PATCH an item or an assembly default sends, and REMOVE IS NOT A DELETE --
  // the line stays in the catalog and on the Labor tab, it just stops being on a new bid.
  {
    const { api, dom: d } = build(seed({
      LABOR: seed().LABOR.concat([{ id: "L9", name: "Rigging", rate: 40, unit: "hours",
                                     guys_auto: false, favorite: false }]) }));
    api.renderDefaultLabor();
    const before = d.nodes["default-labor-body"].innerHTML;
    await api.setDefault("labor", "L9", true);
    const added = d.nodes["default-labor-body"].innerHTML;
    const addCall = api.LABOR_CALLS[api.LABOR_CALLS.length - 1] || {};
    await api.setDefault("labor", "L1", false);
    const removed = d.nodes["default-labor-body"].innerHTML;
    const offCall = api.LABOR_CALLS[api.LABOR_CALLS.length - 1] || {};
    out.laborMakeDefault = {
      notListedBefore: !/Rigging/.test(before),
      listedAfterAdd: /Rigging/.test(added),
      addCall: addCall,
      goneAfterRemove: !/Prevailing wage/.test(removed),
      offCall: offCall,
      // THE OTHER THREE STAY -- the specific removal a one-row fixture could not show.
      othersStay: /Supervisor/.test(removed) && /Mobilization/.test(removed) &&
        /Rigging/.test(removed) && /Travel/.test(removed),
      stillInTheCatalog: api.laborNow().map((r) => r.id),
      // Read defensively: a setDefault that never repainted leaves no Labor table at all, and
      // that has to fail THIS assertion rather than crash every scenario in the file.
      stillOnTheLaborTab: /data-labor="L1"/.test((d.nodes["labor-body"] || {}).innerHTML || ""),
      noDeleteSent: !api.LABOR_CALLS.some((c) => c.op === "DELETE"),
    };
  }
  // A REFUSED DEFAULT WRITE PUTS IT BACK AND SAYS SO -- setDefault's own argument.
  {
    const { api, dom: d } = build(seed({ LABOR_FAIL: { patchDefault: true } }));
    api.renderDefaultLabor();
    await api.setDefault("labor", "L1", false);
    out.laborMakeDefaultFails = {
      putBackOnTheList: /Prevailing wage/.test(d.nodes["default-labor-body"].innerHTML),
      stillAFavorite: (api.laborNow().find((r) => r.id === "L1") || {}).favorite === true,
      saidSo: /Couldn't save that/.test((d.nodes["alert"] || {}).textContent || ""),
    };
  }

  // PER WORK TYPE. A labor default's scope is its own `default_work_types`, pressed on the Labor
  // tab's chips; the Defaults tab lists it under the work types it applies to and nowhere else.
  // The press repaints BOTH tables, because the Defaults tab is filtered by exactly this field and
  // a tab switch does not repaint it.
  {
    const { api, dom: d } = build(seed());
    const chipFocus = [];
    d.el("labor-body").querySelector = (sel) => ({ focus() { chipFocus.push(sel); } });
    api.renderLabor();
    api.renderDefaultLabor();
    const shownFirst = /Prevailing wage/.test(d.nodes["default-labor-body"].innerHTML);
    await api.setRowWorkType("labor", "L1", "gyp", true);
    const polishAfterPress = d.nodes["default-labor-body"].innerHTML;
    const tabAfterPress = d.nodes["labor-body"].innerHTML;
    api.setWorkType("gyp");
    api.renderDefaultLabor();
    const gyp = d.nodes["default-labor-body"].innerHTML;
    out.laborPerWorkType = {
      shownFirst: shownFirst,
      wtCall: api.WT_CALLS[0],
      defaultsRepaintedByThePress: !/Prevailing wage/.test(polishAfterPress),
      onItsOwnWorkType: /Prevailing wage/.test(gyp),
      unscopedStayEverywhere: /Supervisor/.test(polishAfterPress) && /Supervisor/.test(gyp),
      travelOnBoth: /Travel/.test(polishAfterPress) && /Travel/.test(gyp),
      chipShowsPressed:
        /aria-pressed="true" data-wt-toggle="labor" data-wt-id="L1" data-wt="gyp"/.test(tabAfterPress),
      focusBackOnTheChip:
        chipFocus[chipFocus.length - 1] === '[data-wt-toggle="labor"][data-wt-id="L1"][data-wt="gyp"]',
    };
  }

  // THE ENDPOINT HAVING A BAD AFTERNOON -- which on production today is not an outage at all,
  // because library_labor is on staging and is not there yet. No custom rows is the honest
  // answer, and it must not cost the tab anything else.
  {
    const { api, dom: d } = build(seed({ LABOR: [] }));
    api.renderDefaultLabor();
    api.setGlobalMarkup([]);
    api.renderDefaultTakeoff();
    const h = d.nodes["default-labor-body"].innerHTML;
    out.laborEndpointEmpty = {
      travelStillListed: /Travel/.test(h),
      noCustomRows: !/data-labor-edit/.test(h),
      // The rest of the tab is untouched by it.
      takeoffStillRenders: /Polish 800/.test(d.nodes["default-takeoff-body"].innerHTML),
      // The empty state stays down, because Travel is a line.
      emptyStateStaysHidden: d.nodes["default-labor-empty"].hidden === true,
      // And the first line can still be typed.
      canStillAdd: d.nodes["default-labor-addrow"].hidden === false,
    };
  }

  // THE WORK-TYPE TABS, DRIVEN. Five tabs narrow one list, and the load-bearing rule is that an
  // EMPTY default_work_types means EVERY tab -- which is what every row set before the column
  // existed carries. Get that backwards and everybody's existing defaults vanish on deploy.
  {
    const { api, dom: d } = build(seed({
      ITEMS: [{ id: "i1", name: "Everywhere densifier", unit: "Pail", unit_cost: 100,
                favorite: true },
              { id: "i2", name: "Epoxy only primer", unit: "Gal", unit_cost: 50,
                favorite: true, default_work_types: ["epoxy"] }],
      ASMS: [{ id: "a1", name: "Polish only 800", unit: "SF", favorite: true, lines: [],
               default_work_types: ["polish"] }],
      // BOTH DEFAULTS (`favorite: true`): the Defaults tab lists only a line somebody made one,
      // so an unmarked row here would vanish from every tab and prove nothing about the filter.
      LABOR: [{ id: "L1", name: "Everywhere wage", rate: 58.25, unit: "hours", guys_auto: false,
                sort: 0, notes: null, owner_email: "k@w.dev", favorite: true },
              { id: "L2", name: "Gyp only crew", rate: 62, unit: "hours", guys_auto: false,
                sort: 1, notes: null, owner_email: "k@w.dev", default_work_types: ["gyp"],
                favorite: true }],
    }));
    const look = (wt) => {
      api.setWorkType(wt);
      api.renderDefaultTakeoff();
      api.renderDefaultLabor();
      return { takeoff: d.nodes["default-takeoff-body"].innerHTML,
               labor: d.nodes["default-labor-body"].innerHTML };
    };
    const polish = look("polish"), epoxy = look("epoxy"), gyp = look("gyp");
    out.workTypeTabs = {
      tabsAreTheSheetTabs: api.WORK_TYPES,
      comboIsNotATab: api.WORK_TYPES.indexOf("combo") === -1,
      // AN UNNARROWED ROW IS ON EVERY TAB. This is the assertion that protects what is already set.
      unnarrowedOnAll: /Everywhere densifier/.test(polish.takeoff) &&
                       /Everywhere densifier/.test(epoxy.takeoff) &&
                       /Everywhere densifier/.test(gyp.takeoff),
      unnarrowedLaborOnAll: /Everywhere wage/.test(polish.labor) &&
                            /Everywhere wage/.test(epoxy.labor) &&
                            /Everywhere wage/.test(gyp.labor),
      // A NARROWED ROW IS ON ITS OWN TAB AND NOWHERE ELSE.
      epoxyOnlyOnEpoxy: /Epoxy only primer/.test(epoxy.takeoff) &&
                        !/Epoxy only primer/.test(polish.takeoff) &&
                        !/Epoxy only primer/.test(gyp.takeoff),
      polishOnlyOnPolish: /Polish only 800/.test(polish.takeoff) &&
                          !/Polish only 800/.test(epoxy.takeoff),
      gypLaborOnlyOnGyp: /Gyp only crew/.test(gyp.labor) &&
                         !/Gyp only crew/.test(polish.labor),
      // TRAVEL IS NEVER FILTERED OUT: every bid is seeded with it whatever tab it sits on.
      travelOnEveryTab: /Travel/.test(polish.labor) && /Travel/.test(epoxy.labor) &&
                        /Travel/.test(gyp.labor),
    };
  }
}

// ── EXECUTED: the Labor tab itself, 2026-09-30 ───────────────────────────────
// Hanz, 2026-09-22: "we dont have a tab for labor like the items and assemblies so we add a tab
// like that for all default labor then if we want it to be a default we add it to 'Default items
// & Assemblies'". So this tab is the whole catalog -- every line, default or not -- and a line
// made here is NOT a default until the Defaults tab makes it one. Every scenario runs the page's
// own renderLabor / onLaborEdit / addLaborLine / removeLaborLine; only the network is stubbed.
async function laborTabChecks() {
  const lines = () => JSON.parse(JSON.stringify([
    { id: "travel", name: "Travel", rate: 41.5, unit: "hours", guys_auto: true, sort: -1,
      notes: null, owner_email: null, favorite: true },
    { id: "L1", name: "Prevailing wage", rate: 58.25, unit: "hours", guys_auto: false, sort: 0,
      notes: "Davis-Bacon jobs", owner_email: "kyle@wetreadwell.com", favorite: true },
    { id: "L9", name: "Rigging", rate: 40, unit: "days", guys_auto: false, sort: 1,
      notes: null, owner_email: "kyle@wetreadwell.com", favorite: false },
  ]));
  const seed = (extra) => Object.assign({
    window: { TWBidModel: require(path.join(ROOT, "js", "bid-model.js")) },
    ITEMS: [{ id: "i1", name: "Densifier", unit: "Pail", unit_cost: 100, favorite: true }],
    ASMS: [{ id: "a1", name: "Polish 800", unit: "SF", favorite: true, lines: [{ item_id: "i1" }] }],
    LABOR: lines(),
    ADMIN: true,
  }, extra || {});
  const rowsOf = (h) => h.split("</tr>").filter((r) => /<tr/.test(r));
  const rowOf = (h, id) => rowsOf(h).find((r) => r.indexOf('data-labor="' + id + '"') !== -1) || "";
  const idsIn = (h) => rowsOf(h).map((r) => (/data-labor="([^"]+)"/.exec(r) || [])[1]);

  // THE CATALOG, FOR AN ADMIN: every line, whether or not it is a default, each editable in place.
  {
    const { api, dom: d } = build(seed());
    api.renderLabor();
    const h = d.nodes["labor-body"].innerHTML;
    const unitSelect = (rowOf(h, "L1").match(/<select data-f="unit"[\s\S]*?<\/select>/) || [""])[0];
    out.laborTab = {
      ids: idsIn(h),
      nameIsEditable: /data-f="name" class="cell-name" value="Rigging"/.test(rowOf(h, "L9")),
      rateIsEditable: /data-f="rate" class="num cell-rate" value="40"/.test(rowOf(h, "L9")),
      notesAreEditable: /data-f="notes" class="cell-note" value="Davis-Bacon jobs"/.test(rowOf(h, "L1")),
      unitOptions: (unitSelect.match(/<option value="[^"]*"/g) || []).map((s) => s.split('"')[1]),
      daysSelectedOnADayLine: /<option value="days" selected>/.test(rowOf(h, "L9")),
      customLinesCanBeDeleted: /data-del-labor="L1"/.test(rowOf(h, "L1")) &&
        /data-del-labor="L9"/.test(rowOf(h, "L9")),
      travelCannotBeDeleted: !/data-del-labor/.test(rowOf(h, "travel")),
      travelRateIsEditable: /data-f="rate" class="num cell-rate" value="41.5"/.test(rowOf(h, "travel")),
      travelHasChips: (rowOf(h, "travel").match(/data-wt-toggle="labor" data-wt-id="travel"/g) || []).length === 5 &&
        /All work types/.test(rowOf(h, "travel")) && !/Every estimate/.test(rowOf(h, "travel")),
      customLinesHaveChips: /data-wt-toggle="labor" data-wt-id="L9"/.test(rowOf(h, "L9")),
      moreStartsShut: !/class="labor-more"/.test(h),
      // LS1 (Hanz, 2026-10-09): the Travel row is DRAWN "Travel Labor" by the same rule the Defaults tab
      // and the estimate use; the stored name is untouched (no write).
      travelNameDrawn: /data-f="name" class="cell-name" value="Travel Labor"/.test(rowOf(h, "travel")),
      badge: d.nodes["n-labor"].textContent,
      emptyHidden: d.nodes["labor-empty"].hidden === true,
      addShown: d.nodes["labor-addrow"].hidden === false,
      readOnlyNoteHidden: d.nodes["labor-ro"].hidden === true,
    };
  }

  // A NON-ADMIN READS IT AND IS HANDED NOTHING THAT WOULD 403 -- every write to library_labor is
  // `_require_admin`, the same rule the Administration lists render text for.
  {
    const { api, dom: d } = build(seed({ ADMIN: false }));
    api.renderLabor();
    const h = d.nodes["labor-body"].innerHTML;
    out.laborTabReadOnly = {
      listsEveryLine: idsIn(h),
      showsTheRates: /\$58\.25 \/ hr/.test(h) && /\$40\.00 \/ day/.test(h),
      noInputs: !/<input/.test(h) && !/<select/.test(h),
      noControls: !/data-del-labor/.test(h) && !/data-labor-more-toggle/.test(h) &&
        !/data-wt-toggle/.test(h),
      addHidden: d.nodes["labor-addrow"].hidden === true,
      saysWhy: d.nodes["labor-ro"].hidden === false,
    };
  }

  // NOTHING IN THE CATALOG: the empty state, whose own button is an admin's like the top one.
  {
    const run = (admin) => {
      const { api, dom: d } = build(seed({ ADMIN: admin, LABOR: [] }));
      const first = { hidden: false };
      d.el("labor-empty").querySelector = (sel) => (sel === "[data-add-labor]" ? first : null);
      api.renderLabor();
      return { emptyShown: d.nodes["labor-empty"].hidden === false,
               topAddHidden: d.nodes["labor-addrow"].hidden === true,
               firstAddHidden: first.hidden, badge: d.nodes["n-labor"].textContent };
    };
    out.laborTabEmpty = { admin: run(true), nonAdmin: run(false) };
  }

  // ADD: a POST that names no `favorite`, the new row first on the tab and NOT on the Defaults
  // tab, and the caret in its name box.
  {
    const { api, dom: d } = build(seed());
    const asked = [];
    d.el("labor-body").querySelector = (sel) => {
      asked.push(sel);
      return { focus() { d.focused.push("q:" + sel); }, select() {} };
    };
    api.renderDefaultLabor();
    await api.addLaborLine();
    const call = api.LABOR_CALLS[0] || {};
    out.laborTabAdd = {
      callCount: api.LABOR_CALLS.length,
      op: call.op, kind: call.kind, body: call.body,
      sendsNoFavorite: !Object.prototype.hasOwnProperty.call(call.body || {}, "favorite"),
      firstInTheModel: (api.laborNow()[0] || {}).id,
      firstOnTheTab: idsIn(d.nodes["labor-body"].innerHTML)[0],
      notOnTheDefaultsTab: !/New labor line/.test(d.nodes["default-labor-body"].innerHTML),
      badge: d.nodes["n-labor"].textContent,
      caretInTheNewName: d.focused.indexOf('q:[data-labor="new1"] input[data-f="name"]') !== -1,
    };
  }
  {
    const { api, dom: d } = build(seed({ LABOR_FAIL: { post: true } }));
    await api.addLaborLine();
    out.laborTabAddFails = {
      saidWhy: /Couldn't add that labor line\. the server said no/.test(d.nodes["alert"].textContent),
      nothingAdded: api.laborNow().map((r) => r.id),
    };
  }

  // EDIT IN PLACE: each field queues a PATCH of the row it came from, never a POST; the Labor tab
  // is NOT redrawn under the caret; the Defaults tab IS, because it shows the same row.
  {
    const { api, dom: d } = build(seed());
    const ev = (id, f, value, checked) => ({ target: {
      getAttribute: (k) => (k === "data-f" ? f : null),
      closest: (sel) => (sel === "[data-labor]" ? { getAttribute: () => id } : null),
      value: value, checked: !!checked } });
    api.renderLabor();
    api.renderDefaultLabor();
    const tabBefore = d.nodes["labor-body"].innerHTML;
    api.onLaborEdit(ev("L1", "rate", "61"));
    api.onLaborEdit(ev("L1", "name", "Prevailing wage KS"));
    api.onLaborEdit(ev("travel", "rate", "37.25"));
    api.onLaborEdit(ev("L9", "guys_auto", "on", true));
    api.onLaborEdit(ev("L9", "unit", "hours"));
    api.onLaborEdit(ev("L9", "sort", "4"));
    const q = api.QUEUED.filter((c) => c.kind === "labor");
    const defaults = d.nodes["default-labor-body"].innerHTML;
    const L1 = api.laborNow().find((r) => r.id === "L1") || {};
    const L9 = api.laborNow().find((r) => r.id === "L9") || {};
    out.laborTabEdit = {
      queued: q.map((c) => ({ id: c.id, body: c.body })),
      modelTakesTheNumber: L1.rate === 61 && L9.sort === 4,
      modelTakesTheCheckbox: L9.guys_auto === true,
      noPostOrDelete: api.LABOR_CALLS.length === 0,
      noFavoriteInAnyBody: q.every((c) => !Object.prototype.hasOwnProperty.call(c.body, "favorite")),
      tabNotRedrawnUnderTheCaret: d.nodes["labor-body"].innerHTML === tabBefore,
      defaultsTabShowsTheNewName: /Prevailing wage KS/.test(defaults) && /\$61\.00/.test(defaults),
      defaultsTabShowsTravelsNewRate: /\$37\.25/.test(defaults),
      notADefaultStaysOff: !/Rigging/.test(defaults),
    };
  }

  // RENAME RELABELS. The row is not redrawn under the caret, so its buttons must be told the new
  // name or a screen reader keeps saying "Remove New labor line" for a line called Rigging.
  {
    const { api } = build(seed());
    const btn = (label, expanded) => { const a = { "aria-label": label, "aria-expanded": expanded };
      return { getAttribute: (k) => (k in a ? a[k] : null), setAttribute: (k, v) => { a[k] = v; } }; };
    const more = btn("Show more fields for Rigging", "false");
    const del = btn("Remove Rigging", null);
    const row = { getAttribute: () => "L9", querySelector: (sel) =>
      (sel === "[data-labor-more-toggle]" ? more : sel === "[data-del-labor]" ? del : null) };
    api.onLaborEdit({ target: { getAttribute: (k) => (k === "data-f" ? "name" : null),
      closest: (sel) => (sel === "[data-labor]" ? row : null), value: "Crane hire" } });
    const open = btn("Show more fields for Crane hire", "true");
    row.querySelector = (sel) => (sel === "[data-labor-more-toggle]" ? open : null);
    api.onLaborEdit({ target: { getAttribute: (k) => (k === "data-f" ? "name" : null),
      closest: (sel) => (sel === "[data-labor]" ? row : null), value: "Boom lift" } });
    out.laborRenameRelabels = { more: more.getAttribute("aria-label"),
      del: del.getAttribute("aria-label"), openMore: open.getAttribute("aria-label") };
  }

  // MORE: guys_auto and the position open under their own row, and the focus comes back to the
  // toggle the redraw replaced. Opening it saves nothing.
  {
    const { api, dom: d } = build(seed());
    d.el("labor-body").querySelector = (sel) => ({ focus() { d.focused.push(sel); } });
    api.renderLabor();
    api.toggleLaborMore("L1");
    const open = d.nodes["labor-body"].innerHTML;
    const focusAfterOpen = d.focused[d.focused.length - 1];
    api.toggleLaborMore("L1");
    const shut = d.nodes["labor-body"].innerHTML;
    out.laborTabMore = {
      opensUnderItsRow: /data-labor="L1" class="labor-more"/.test(open),
      onlyThatRow: (open.match(/class="labor-more"/g) || []).length === 1,
      hasGuysAuto: /type="checkbox" data-f="guys_auto"/.test(open),
      hasPosition: /data-f="sort" class="num" value="0"/.test(open),
      saysLess: /aria-expanded="true"[^>]*>Less</.test(open),
      focusBackOnTheToggle: focusAfterOpen === '[data-labor-more-toggle="L1"]',
      shutsAgain: !/class="labor-more"/.test(shut),
      savesNothing: api.QUEUED.length === 0 && api.LABOR_CALLS.length === 0,
    };
  }

  // DELETE: asked first, a soft DELETE of that one row, its queued edit dropped, the rest kept --
  // and Travel refused before anybody is even asked.
  {
    const asked = [];
    const { api, dom: d } = build(seed({
      TW: { confirmDanger: (o) => { asked.push(o); return Promise.resolve(true); } } }));
    api.setPending("labor:L9", { rate: "44" });
    await api.removeLaborLine("travel");
    await api.removeLaborLine("L9");
    out.laborTabDelete = {
      askedOnce: asked.length,
      askedAboutThatLine: (asked[0] || {}).name,
      calls: api.LABOR_CALLS,
      left: api.laborNow().map((r) => r.id),
      goneFromTheTab: !/data-labor="L9"/.test(d.nodes["labor-body"].innerHTML),
      queuedEditDropped: !Object.prototype.hasOwnProperty.call(api.pendingNow(), "labor:L9"),
    };
  }
  {
    const { api } = build(seed({ TW: { confirmDanger: () => Promise.resolve(false) } }));
    await api.removeLaborLine("L1");
    out.laborTabDeleteCancelled = { calls: api.LABOR_CALLS.length,
                                    left: api.laborNow().map((r) => r.id) };
  }
  {
    const { api, dom: d } = build(seed({ LABOR_FAIL: { del: true },
                                         TW: { confirmDanger: () => Promise.resolve(true) } }));
    await api.removeLaborLine("L1");
    out.laborTabDeleteFails = {
      left: api.laborNow().map((r) => r.id),
      saidWhy: /Couldn't remove that labor line\. the server said no/.test(d.nodes["alert"].textContent),
    };
  }

  // EDIT ON A LABOR DEFAULT LANDS HERE: focusLaborRow puts the caret in that row's name box.
  {
    const { api, dom: d } = build(seed());
    d.el("labor-body").querySelector = (sel) => ({ focus() { d.focused.push(sel); } });
    api.focusLaborRow("L1");
    out.laborTabFocus = {
      focused: d.focused[d.focused.length - 1],
      routerSendsEditHere:
        /ek === "labor"\) \{ showView\("labor"\); paint\(\); focusLaborRow\(eid\); \}/.test(src),
    };
  }
}

// ── the page's own copy ──────────────────────────────────────────────────────
out.page = {
  title: /<title>([^<]*)</.exec(html)[1],
  h1: /<h1>([^<]*)</.exec(html)[1],
  materialHeaderNamesTheManufacturer:
    /Materials <span[^>]*>\(how the manufacturer names it\)<\/span>/.test(html),
  // REMOVED 2026-08-27 at Hanz's request, and this probe is kept pointing at the deleted
  // sentence on purpose: it must stay false. He uses this tab daily and did not need the pack
  // convention explained to him in a paragraph above it.
  itemsIntro: /Items are entered as we buy them/.test(html),
  // The other two panes keep theirs. They were asked for by name, they were not what he
  // screenshotted, and neither is a tab anybody lives in.
  assembliesIntro: /Assemblies are how we estimate them/.test(html),
  adminIntro: /Administration lists\./.test(html),
  // The class survives the deletion because two panes still use it. A stylesheet rule with no
  // remaining caller is the thing to delete; this is not one.
  paneintroStillUsed: (html.match(/class="paneintro"/g) || []).length,
  coveragePerUnitHeader: /Coverage per Unit/.test(html),
  wasteHeader: /Waste Factor/.test(html),
  roundupHeader: /Roundup\?/.test(html),
  vendorsTab: /id="tab-vendors"/.test(html),
  // The fourth tab, and WHERE it sits: Hanz asked for it beside Administration, so the order in
  // the strip is part of the ask rather than incidental.
  defaultsTab: /id="tab-defaults"/.test(html),
  defaultsTabLabel: (/id="tab-defaults"[^>]*>([^<]*)</.exec(html) || [])[1] || "",
  defaultsTabIsLast: html.indexOf('id="tab-defaults"') > html.indexOf('id="tab-vendors"'),
  defaultsPaneStartsHidden: /<section id="pane-defaults"[^>]*\shidden/.test(html),
  // IT SAYS IT IS EMPTY RATHER THAN LOOKING BROKEN. A tab that opens onto nothing reads as a bug;
  // one that explains it has not been built reads as a decision.
  defaultsPaneExplainsItself: /Nothing set yet/.test(html),
  // TWO CATEGORIES, AND WHICH TWO. Hanz asked for takeoff and labor -- the estimate's own steps,
  // not the library's Items/Assemblies split, which is a different question with its own tabs.
  defaultsCategories: (function () {
    var pane = (html.split('id="pane-defaults"')[1] || "").split("</section>")[0];
    return {
      takeoff: /id="default-takeoff"/.test(pane),
      labor: /id="default-labor"/.test(pane),
      headings: (pane.match(/<h2>([^<]*)<\/h2>/g) || []).map(function (h) {
        return h.replace(/<\/?h2>/g, "");
      }),
      // The same container the Administration lists use, which is what was asked for.
      usesAdminGrid: /class="admin-grid"/.test(pane),
      // A WAY IN, not a filter. Hanz asked for it "for when entering the defaults", so the
      // placeholder has to read as adding rather than narrowing -- the same box worded the other
      // way is a different feature that happens to look identical.
      search: /id="default-q"/.test(pane),
      searchIsForAdding:
        /placeholder="Search materials, assemblies and labor lines to add"/.test(pane),
      // THE BOX STARTS IN THE TAKEOFF CARD, ABOVE ITS TABLE, and is hidden until a button opens
      // it (Hanz, 2026-10-05: not up by the work-type tabs). It used to sit above the admin-grid.
      searchAboveTheLists: pane.indexOf('id="default-q"') > pane.indexOf('class="admin-grid"') &&
        pane.indexOf('id="default-q"') < pane.indexOf('id="default-takeoff-body"') &&
        /<div id="default-search" hidden>/.test(pane) &&
        pane.indexOf('id="default-q"') > pane.indexOf('data-add-default="takeoff"') &&
        pane.indexOf('id="default-q"') < pane.indexOf('data-add-default="labor"') &&
        /data-def-search-close/.test(pane),
      // THE RESULTS BOX LIVES WITH THE ROWS, not with the input. It shipped as a
      // <span class="hits"> inside .itemsearch -- a flex ROW -- so the list of things you were
      // about to add rendered beside the search box, clear of the table it was adding to.
      // Hanz asked for it "within the line item instead of up above". Position is the whole
      // fix, so position is what is asserted.
      resultsInsideTakeoffSection: (function () {
        var sec = (pane.split('id="default-takeoff"')[1] || "").split('class="admin-section"')[0];
        return sec.indexOf('id="default-hits"') !== -1;
      })(),
      resultsFollowTheAddButton:
        pane.indexOf('data-add-default="takeoff"') < pane.indexOf('id="default-hits"'),
      resultsNotBesideTheSearchInput:
        pane.indexOf('id="default-hits"') > pane.indexOf('class="admin-grid"'),
      onlyOneResultsBox: (pane.match(/id="default-hits"/g) || []).length === 1,
      // BOTH ADD CONTROLS SIT ABOVE THEIR TABLES. Hanz, 2026-09-17: "all buttons should be at
      // the top". They were underneath, so the more defaults you had set the further you had
      // to scroll past them to reach the control that sets one. Position again, so position
      // is what is asserted -- nothing about the markup itself changed.
      takeoffAddIsAboveTheTable:
        pane.indexOf('data-add-default="takeoff"') < pane.indexOf('id="default-takeoff-body"'),
      laborAddIsAboveTheTable:
        pane.indexOf('data-add-default="labor"') < pane.indexOf('id="default-labor-body"'),
      // and the picker still opens with the button rather than at the far end of the list
      resultsStillFollowTheirButton:
        pane.indexOf('data-add-default="takeoff"') < pane.indexOf('id="default-hits"') &&
        pane.indexOf('id="default-hits"') < pane.indexOf('id="default-takeoff-body"'),
      // AN ADD BUTTON IN EACH, on the same .addrow the Administration lists use. Labor's is not
      // optional: labor lines are not library rows, so there is nothing to switch on and nothing
      // for the search to return -- typing here is the only way one gets made.
      addButtons: (pane.match(/data-add-default="[a-z]+"/g) || [])
        .map(function (m) { return m.replace(/.*="|"$/g, ""); }),
      addUsesTheAdminPattern: (pane.match(/class="addrow"/g) || []).length === 2 &&
        (pane.match(/class="addbtn"/g) || []).length === 2,
      // Labor has a table to put Travel in, and an empty state that hides once it is there.
      laborTable: /id="default-labor-body"/.test(pane),
      laborEmptyState: /id="default-labor-empty"/.test(pane),
      sectionCount: (pane.match(/class="admin-section"/g) || []).length,
    };
  })(),
  noCoverageSfHeader: !/Coverage \(SF\)/.test(html),
  noRoleHeader: !/<th[^>]*>Role<\/th>/.test(html),
  // THE LABOR TAB, 2026-09-30: where it sits in the strip, and what its pane holds.
  laborTab: (function () {
    var pane = (html.split('<section id="pane-labor"')[1] || "").split("</section>")[0];
    return {
      tab: /id="tab-labor"[^>]*aria-controls="pane-labor"/.test(html),
      label: (/id="tab-labor"[^>]*>([^<]*)</.exec(html) || [])[1] || "",
      badge: /id="n-labor"/.test(html),
      afterAssemblies: html.indexOf('id="tab-labor"') > html.indexOf('id="tab-asm"'),
      beforeAdministration: html.indexOf('id="tab-labor"') < html.indexOf('id="tab-vendors"'),
      paneStartsHidden: /<section id="pane-labor"[^>]*\shidden/.test(html),
      headers: (pane.match(/<th[^>]*>([^<]*)<\/th>/g) || []).map(function (t) {
        let s = t, prev;
        do { prev = s; s = s.replace(/<[^>]+>/g, ""); } while (s !== prev);
        return s;
      }),
      body: /id="labor-body"/.test(pane),
      emptyState: /id="labor-empty"[^>]*hidden/.test(pane),
      addButtons: (pane.match(/data-add-labor>/g) || []).length,
      addRowIsAbove: pane.indexOf('id="labor-addrow"') < pane.indexOf('id="labor-body"'),
      readOnlyNoteStartsHidden: /id="labor-ro"[^>]*hidden/.test(pane),
      saysItIsNotADefault: /not on any\s+new bid until you add it under/.test(pane),
    };
  })(),
};


// ── the conditions, CHANGED rather than read ─────────────────────────────────
//
// Every assertion here fails against the code that was on staging before 2026-09-18, where the
// three conditions rendered a "Built in" chip and there was nothing to press at all.
async function conditionChecks() {
  const seed = (extra) => Object.assign({
    // THE REAL MODULE. The whole claim is that this list shows what a new estimate opens
    // ANSWERING, so a made-up freshModel would prove the opposite of what it looks like it proves.
    window: { TWBidModel: require(path.join(ROOT, "js", "bid-model.js")) },
    // ONE NON-FAVOURITE LIBRARY ROW, so the browse list has something in it that is NOT a
    // condition -- a browse offering only the three would pass "offers the conditions" against a
    // list that had stopped offering the library.
    ITEMS: [{ id: "i9", name: "Not a default", unit: "Gal", unit_cost: 50, favorite: false }],
    ASMS: [],
    // AN ADMIN: Add and Remove on these rows are an admin's only (the PUT is _require_admin).
    // The non-admin view is its own scenario below.
    ADMIN: true,
  }, extra || {});
  // Which reserved row each condition IS -- the row the material button is keyed by.
  const ROW = { joint_filler: "joint-filler-kit", remove_existing_jf: "remove-existing-jf",
                dye: "dye" };

  // LISTED MEANS ON THE DEFAULTS TAB (Hanz, 2026-10-01: "Everything that is in the defaults ...
  // appear as grayed out options that can be enabled or not") -- the material's own Remove, keyed
  // by the condition's reserved row. Not listed means not in the table at all.
  const listed = (html, key) =>
    html.indexOf('data-def-off="items" data-def-id="' + ROW[key] + '"') !== -1;
  const absent = (html, key) => html.indexOf('data-def-id="' + ROW[key] + '"') === -1 &&
    html.indexOf('data-def-id="' + key + '"') === -1;
  // OFFERED BY THE ADD SEARCH, as the hit that puts this condition back on the list.
  const offered = (html, key) =>
    html.indexOf('data-def-add="conditions" data-def-id="' + key + '">') !== -1;
  const OFF_THE_LIST = (key) => ({ key: key, on: false, listed: false });

  // 1. NOTHING STORED: all three listed, as defaults, each with Edit and Remove.
  const shipped = build(seed({}));
  shipped.api.renderDefaultTakeoff();
  const shippedHtml = shipped.dom.nodes["default-takeoff-body"].innerHTML;

  // 2. ONE TAKEN OFF: that one is not drawn, the two nobody touched still are.
  const stored = build(seed({ COND_DEFAULTS: [OFF_THE_LIST("joint_filler")] }));
  stored.api.renderDefaultTakeoff();
  const storedHtml = stored.dom.nodes["default-takeoff-body"].innerHTML;

  // 3. REMOVE, DRIVEN through removeDefault with the attributes the button itself carries.
  //    Starts from an `on: true` row, so the press can be seen to leave the answer alone.
  const live = build(seed({ COND_DEFAULTS: [{ key: "joint_filler", on: true, listed: true }] }));
  live.api.renderDefaultTakeoff();
  const beforeHtml = live.dom.nodes["default-takeoff-body"].innerHTML;
  await live.api.removeDefault("items", "joint-filler-kit");
  const afterHtml = live.dom.nodes["default-takeoff-body"].innerHTML;
  live.api.openDefaultBrowse();
  const afterRemoveBrowse = live.dom.nodes["default-hits"].innerHTML;

  // 4. AND BACK ON: found in the add search, added by the id the RENDERED hit carries.
  const adding = build(seed({ COND_DEFAULTS: [OFF_THE_LIST("dye")] }));
  adding.api.renderDefaultTakeoff();
  const beforeAddHtml = adding.dom.nodes["default-takeoff-body"].innerHTML;
  adding.api.setDefaultQuery("dye");
  const dyeHits = adding.dom.nodes["default-hits"].innerHTML;
  const dyeHitId = (/data-def-add="conditions" data-def-id="([^"]+)"/.exec(dyeHits) || [])[1];
  await adding.api.setConditionDefault(dyeHitId, true);
  const afterAddHtml = adding.dom.nodes["default-takeoff-body"].innerHTML;
  adding.api.setDefaultQuery("dye");
  const dyeHitsAfterAdd = adding.dom.nodes["default-hits"].innerHTML;

  // 5. THE BROWSE, with all three off the list: all three offered, FIRST, beside the library.
  const browsing = build(seed({ COND_DEFAULTS: [OFF_THE_LIST("joint_filler"),
    OFF_THE_LIST("remove_existing_jf"), OFF_THE_LIST("dye")] }));
  browsing.api.openDefaultBrowse();
  const browseHtml = browsing.dom.nodes["default-hits"].innerHTML;
  const browseRows = browsing.api.defaultCandidates().rows.map((r) => r.kind + ":" + r.id);

  // 6. …and with all three listed (nothing stored): none offered, they are on the list already.
  const allListed = build(seed({}));
  allListed.api.openDefaultBrowse();
  const allListedBrowse = allListed.dom.nodes["default-hits"].innerHTML;

  // 7. A REFUSED SAVE PUTS IT BACK.
  const failing = build(seed({ COND_FAIL: true }));
  failing.api.renderDefaultTakeoff();
  await failing.api.removeDefault("items", "joint-filler-kit");
  const failedHtml = failing.dom.nodes["default-takeoff-body"].innerHTML;

  // 8. THE OTHER FOUR WORK TYPES DO NOT LIST THEM, and do not offer them.
  const sealTab = build(seed({ COND_DEFAULTS: [OFF_THE_LIST("dye")] }));
  sealTab.api.setWorkType("seal");
  sealTab.api.renderDefaultTakeoff();
  const sealHtml = sealTab.dom.nodes["default-takeoff-body"].innerHTML;
  sealTab.api.openDefaultBrowse();
  const sealBrowse = sealTab.dom.nodes["default-hits"].innerHTML;

  // 9. A NON-ADMIN sees the listed ones with Edit only, and is offered none to add.
  const viewer = build(seed({ ADMIN: false, COND_DEFAULTS: [OFF_THE_LIST("dye")] }));
  viewer.api.renderDefaultTakeoff();
  const viewerHtml = viewer.dom.nodes["default-takeoff-body"].innerHTML;
  viewer.api.openDefaultBrowse();
  const viewerBrowse = viewer.dom.nodes["default-hits"].innerHTML;

  // 10. TYPED TEXT ON THE ROW IS ESCAPED: an admin's name and unit for the kit.
  const hostile = build(seed({ ITEMS: [
    { id: "joint-filler-kit", name: "<b>Kit</b>", unit: "<img src=x>", buy_qty: 1,
      unit_cost: 500, coverage: 3500, waste_pct: 0, roundup: true, favorite: false }] }));
  hostile.api.renderDefaultTakeoff();
  const hostileHtml = hostile.dom.nodes["default-takeoff-body"].innerHTML;

  // 11. AN ORDINARY MATERIAL'S Remove IS UNTOUCHED: still its `favorite`, never a condition.
  const plain = build(seed({ ITEMS: [{ id: "i1", name: "Densifier", unit: "Pail",
                                       unit_cost: 100, favorite: true }] }));
  plain.api.renderDefaultTakeoff();
  await plain.api.removeDefault("items", "i1");

  out.conditionDefaults = {
    // NOTHING STORED: all three listed, each the material row's Edit + Remove, no Off note.
    allListedByDefault: ["joint_filler", "remove_existing_jf", "dye"].every((k) =>
      listed(shippedHtml, k)) && !/data-def-add=/.test(shippedHtml) &&
      !/a new bid starts without it/.test(shippedHtml),
    // ONE OFF THE LIST: not drawn; the two nobody touched still listed.
    storedOverrideWins: absent(storedHtml, "joint_filler"),
    untouchedOnesKeepShipped: listed(storedHtml, "dye") && listed(storedHtml, "remove_existing_jf"),

    // REMOVE: the row leaves, the write is `listed: false`, and the stored `on` is kept.
    startsListed: listed(beforeHtml, "joint_filler"),
    removeTakesTheRowOff: absent(afterHtml, "joint_filler") && !/Joint filler/.test(afterHtml),
    wroteTheServer: JSON.stringify(live.api.COND_CALLS) ===
      JSON.stringify([{ key: "joint_filler", listed: false, on: false }]),
    didNotWriteTheFavorite: !live.api.LABOR_CALLS.some((c) => c.op === "PATCH_DEFAULT"),
    keepsOneRowPerCondition: live.api.condDefaultsNow().length === 1,
    // A STORED `on: true` (an earlier version of this tab's Add wrote one) IS CLEARED by the press,
    // or the removed condition would still open switched on, and priced, on every new bid.
    keepsTheStoredOn: (function () {
      const r = live.api.condDefaultsNow()[0];
      return r.key === "joint_filler" && r.on === false && r.listed === false;
    })(),
    removedOneIsOfferedByTheAddSearch: offered(afterRemoveBrowse, "joint_filler"),

    // ADD BACK.
    startsOffAndUnlisted: absent(beforeAddHtml, "dye") && !/Dye/.test(beforeAddHtml),
    searchFindsIt: dyeHitId === "dye" && /Dye<span class="k">Material<\/span>/.test(dyeHits),
    addPutsTheRowOnTheList: listed(afterAddHtml, "dye"),
    addWroteTheServer: JSON.stringify(adding.api.COND_CALLS) ===
      JSON.stringify([{ key: "dye", listed: true, on: false }]),
    addedRowIsPriced: /\$0\.14 per SF a coat/.test(afterAddHtml),
    addedOneIsNoLongerOffered: !offered(dyeHitsAfterAdd, "dye"),

    // THE BROWSE.
    browseOffersAllThreeWhileOff: ["joint_filler", "remove_existing_jf", "dye"]
      .every((k) => offered(browseHtml, k)) &&
      browseRows.slice(0, 3).every((r) => r.indexOf("conditions:") === 0),
    andStillOffersTheLibrary: /data-def-add="items" data-def-id="i9"/.test(browseHtml),
    browseSkipsAConditionAlreadyOn: ["joint_filler", "remove_existing_jf", "dye"]
      .every((k) => !offered(allListedBrowse, k)),
    // THE TYPED SEARCH MATCHES THE CONDITION'S LABEL TOO: the kit's row renamed to something
    // without the word in it is still found by "joint".
    searchByLabelFindsBoth: (function () {
      const s = build(seed({ COND_DEFAULTS: [OFF_THE_LIST("joint_filler"),
        OFF_THE_LIST("remove_existing_jf"), OFF_THE_LIST("dye")], ITEMS: [
        { id: "i9", name: "Not a default", unit: "Gal", unit_cost: 50, favorite: false },
        { id: "joint-filler-kit", name: "Our 10 gal kit", unit: "Kit", buy_qty: 1,
          unit_cost: 500, coverage: 3500, waste_pct: 0, roundup: true, favorite: false }] }));
      s.api.setDefaultQuery("joint");
      const sh = s.dom.nodes["default-hits"].innerHTML;
      return offered(sh, "joint_filler") && /Our 10 gal kit<span class="k">/.test(sh) &&
        offered(sh, "remove_existing_jf") && !offered(sh, "dye");
    })(),

    notOnOtherWorkTypes: !/data-def-id="(joint-filler-kit|remove-existing-jf|dye)"/.test(sealHtml) &&
      !/data-def-add="conditions"/.test(sealBrowse),
    viewerGetsEditOnly: listedForViewer(viewerHtml) && !/data-def-off="items" data-def-id="(joint-filler-kit|remove-existing-jf|dye)"/.test(viewerHtml) &&
      !/data-def-add="conditions"/.test(viewerBrowse),
    offRowEscapesTypedText: !/<img src=x>/.test(hostileHtml) && !/<b>Kit<\/b>/.test(hostileHtml) &&
      /&lt;img src=x&gt;/.test(hostileHtml) && listed(hostileHtml, "joint_filler"),

    // The refusal.
    refusedSavePutsItBack: listed(failedHtml, "joint_filler"),
    refusedSaveSaysSo: /Couldn't save that/.test(failing.dom.nodes["alert"].textContent || ""),
    refusedSaveDropsTheOptimisticRow: failing.api.condDefaultsNow().length === 0,

    ordinaryRemoveStillWritesTheFavorite:
      JSON.stringify(plain.api.LABOR_CALLS) ===
        JSON.stringify([{ op: "PATCH_DEFAULT", kind: "items", id: "i1", on: false }]) &&
      plain.api.COND_CALLS.length === 0,
  };
  // A non-admin's listed rows: the kit and remove-existing (dye is off the list), Edit only.
  function listedForViewer(html) {
    return ["joint-filler-kit", "remove-existing-jf"].every((id) =>
      html.indexOf('data-def-edit="items" data-def-id="' + id + '">Edit</button>') !== -1) &&
      html.indexOf('data-def-id="dye"') === -1;
  }

  // ── THE WORK-TYPE STRIP STILL FILTERS, WITH NO ROW-LEVEL CHIPS LEFT ──────────────────────
  // Hanz, 2026-09-22: "remove the worktype section because this is not looking good" -- the
  // per-row chips (and the column) came out of this table one day after they were fixed. What
  // this scenario proves is that the READER survived the writer's removal: appliesToWorkType
  // still filters takeoffDefaultGroups correctly when default_work_types is set the way the API
  // sets it, with nothing in this table able to press a chip any more.
  const stripSeed = {
    window: { TWBidModel: require(path.join(ROOT, "js", "bid-model.js")) },
    ITEMS: [
      { id: "i1", name: "Densifier", unit: "Pail", unit_cost: 100, favorite: true,
        default_work_types: [] },
      { id: "i2", name: "Gyp primer", unit: "Gal", unit_cost: 50, favorite: true,
        default_work_types: ["gyp"] },
    ],
    ASMS: [],
  };
  const strip = build(stripSeed);
  strip.api.setWorkType("polish");
  strip.api.renderDefaultTakeoff();
  const stripPolish = strip.dom.nodes["default-takeoff-body"].innerHTML;
  strip.api.setWorkType("gyp");
  strip.api.renderDefaultTakeoff();
  const stripGyp = strip.dom.nodes["default-takeoff-body"].innerHTML;

  out.stripStillFilters = {
    scopedRowIsAbsentFromPolish: !/Gyp primer/.test(stripPolish),
    scopedRowIsPresentOnGyp: /Gyp primer/.test(stripGyp),
    unscopedRowIsOnEveryTab: /Densifier/.test(stripPolish) && /Densifier/.test(stripGyp),
    noChipMarkupAnywhereInTheTable: !/data-wt-toggle/.test(stripPolish) &&
      !/data-wt-toggle/.test(stripGyp),
  };
}

// ── The three reserved rows: Items-tab rows with no Remove ──────────────────
//
// Hanz: "joint filler and die should be library items so that we are able to edit them as well",
// and on 2026-10-01, of all three Takeoff conditions: "All 3 exactly like materials" -- which is
// why remove-existing joined them. All three are RESERVED library_items rows (backend/library.py's
// RESERVED_ITEM_IDS), seeded by the schema files. On this page each is an ordinary Items-tab row
// for EDITING and never for removing, is never offered as an assembly line, and the Defaults tab's
// rows for them quote whatever the rows say. Everything here is the page's own code, executed.
{
  const RESERVED = [
    { id: "joint-filler-kit", name: "Joint filler, 10 gal kit", unit: "Kit", buy_qty: 1,
      unit_cost: 500, coverage: 3500, waste_pct: 0, roundup: true, favorite: false },
    { id: "dye", name: "Dye, per coat", unit: "SF", buy_qty: 1,
      unit_cost: 0.14, coverage: 1, waste_pct: 0, roundup: false, favorite: false },
    // REMOVE EXISTING BUYS NOTHING: no cost and no coverage, as both schema files seed it.
    { id: "remove-existing-jf", name: "Remove existing joint filler", unit: "SF", buy_qty: 1,
      unit_cost: null, coverage: null, waste_pct: 0, roundup: false, favorite: false },
  ];
  const withReserved = () => JSON.parse(JSON.stringify(ITEMS.concat(RESERVED)));
  const bid = { TWBidModel: require(path.join(ROOT, "js", "bid-model.js")) };
  const rowOf = (html, id) => (html.split("</tr>").filter((r) =>
    r.indexOf('data-item="' + id + '"') !== -1)[0] || "");
  const condPriced = (api, key) => (api.takeoffConditionDefaults()
    .filter((c) => c.key === key)[0] || {}).priced;

  // 1. THE ITEMS TAB: all three rows are there to edit, none can be removed, and an ordinary row
  //    beside them keeps its Remove -- so "no Remove" is scoped to the three ids, not the table.
  const t = build({ ITEMS: withReserved(), window: bid });
  t.api.renderItems();
  const tab = t.dom.nodes["items-body"].innerHTML;
  const kitRow = rowOf(tab, "joint-filler-kit");
  const dyeRow = rowOf(tab, "dye");
  const remRow = rowOf(tab, "remove-existing-jf");

  // 2. EDITED THROUGH THE ITEMS TAB'S OWN HANDLER, and the Defaults tab moves with it. Coverage
  //    and cost on the kit, cost on dye -- the same onItemEdit every other material row takes.
  const e = build({ ITEMS: withReserved(), window: bid });
  e.api.renderItems();
  const before = { kit: condPriced(e.api, "joint_filler"), dye: condPriced(e.api, "dye"),
                   rem: condPriced(e.api, "remove_existing_jf") };
  const edit = (id, field, raw) => e.api.onItemEdit({ target: {
    getAttribute: (k) => (k === "data-f" ? field : null), value: raw,
    parentNode: { querySelector: () => null, insertAdjacentHTML: () => {} },
    closest: (sel) => (sel === "[data-item]" ? { getAttribute: () => id } : null) } });
  edit("joint-filler-kit", "coverage", "2000");
  edit("joint-filler-kit", "unit_cost", "650");
  edit("dye", "unit_cost", "0.2");
  const after = { kit: condPriced(e.api, "joint_filler"), dye: condPriced(e.api, "dye"),
                  rem: condPriced(e.api, "remove_existing_jf") };

  // 3. NO ROW AT ALL (a database the seed has not reached): the shipped figures, as before.
  const none = build({ window: bid });
  const missing = { kit: condPriced(none.api, "joint_filler"), dye: condPriced(none.api, "dye"),
                    rem: condPriced(none.api, "remove_existing_jf") };

  // 4. NEVER AN ASSEMBLY LINE -- searched for by words that match the reserved rows' own names,
  //    beside an ordinary material that must still turn up. And in the add-a-default search they
  //    are offered ONLY as their condition, never as an ordinary material whose `favorite` a press
  //    would flip.
  const s = build({ ITEMS: withReserved(), window: bid });
  const pickedAll = s.api.itemResultsHtml({ _item_search: "" });
  const pickedByName = s.api.itemResultsHtml({ _item_search: "joint" }) +
    s.api.itemResultsHtml({ _item_search: "dye" }) +
    s.api.itemResultsHtml({ _item_search: "remove" });
  s.api.setDefaultQuery("o");
  const defaults = s.api.defaultCandidates().rows.map((r) => r.kind + ":" + r.id);
  // BROWSE WITH A FULL LIBRARY: ten ordinary un-favorited materials, nothing typed. The cap is
  // DEFAULT_MAX rows, and all of them are ordinary materials: the three conditions are never
  // offered here (they are always on the list), and never as their reserved rows.
  const many = withReserved().concat(Array.from({ length: 10 }, (_, k) => ({
    id: "m" + k, name: "Material " + k, unit: "Gal", buy_qty: 1, unit_cost: 10,
    coverage: 100, favorite: false, divisions: [] })));
  const full = build({ ITEMS: many, window: bid });
  full.api.openDefaultBrowse();
  const browseFull = full.api.defaultCandidates().rows.map((r) => r.kind + ":" + r.id);

  // 5. THE DEFAULTS TAB, ON, WITH THE ROWS THERE: each is listed under the row's OWN name, and its
  //    Edit goes to that row.
  const on = build({ ITEMS: withReserved(), window: bid,
                     COND_DEFAULTS: [{ key: "joint_filler", on: true }, { key: "dye", on: true },
                                     { key: "remove_existing_jf", on: true }] });
  on.api.renderDefaultTakeoff();
  const onHtml = on.dom.nodes["default-takeoff-body"].innerHTML;

  // 6. EDIT LANDS ON THE ROW. focusItemRow is what the Edit router calls; driven against the
  //    REAL rendered Items table, through a querySelector that can only find what renderItems
  //    drew. Once plainly, and once with the Items tab's own search hiding the row -- a search
  //    outlives a tab switch, so an Edit pressed an hour after somebody typed "OPF" must still
  //    land.
  const findIn = (d) => (sel) => {
    const m = /^\[data-item="([^"]+)"\] input\[data-f="name"\]$/.exec(sel);
    const html = d.nodes["items-body"].innerHTML;
    if (!m || html.indexOf('<tr data-item="' + m[1] + '"') === -1) return null;
    return { focus() { d.focused.push("item:" + m[1]); }, scrollIntoView() {} };
  };
  const f1 = build({ ITEMS: withReserved(), window: bid });
  f1.api.renderItems();
  f1.dom.el("items-body").querySelector = findIn(f1.dom);
  f1.api.focusItemRow("dye");
  const f2 = build({ ITEMS: withReserved(), window: bid, itemQuery: "OPF" });
  f2.api.renderItems();
  const hiddenFirst = rowOf(f2.dom.nodes["items-body"].innerHTML, "remove-existing-jf") === "";
  f2.dom.el("items-body").querySelector = findIn(f2.dom);
  f2.api.focusItemRow("remove-existing-jf");

  out.reservedRows = {
    allThreeOnTheItemsTab: !!kitRow && !!dyeRow && !!remRow,
    kitRowIsEditable: /data-f="coverage"/.test(kitRow) && /data-f="unit_cost"/.test(kitRow) &&
      /data-f="waste_pct"/.test(kitRow) && /data-f="roundup"/.test(kitRow),
    kitHasNoRemove: !/data-del-item/.test(kitRow),
    dyeHasNoRemove: !/data-del-item/.test(dyeRow),
    removeExistingHasNoRemove: !/data-del-item/.test(remRow),
    // ITS COST CELL SAYS IT HAS NONE, and offers no box to type one into -- while its name, the
    // cell an admin might actually change, stays editable like the other two.
    removeExistingSaysNoMaterialCost: /<span class="builtin">No material cost<\/span>/.test(remRow) &&
      !/data-f="unit_cost"/.test(remRow),
    removeExistingNameIsEditable: /<input data-f="name"[^>]*value="Remove existing joint filler"/
      .test(remRow),
    // …and only it: the two priced rows keep their cost box.
    pricedRowsKeepTheirCostBox: /data-f="unit_cost"/.test(dyeRow) && /data-f="unit_cost"/.test(kitRow) &&
      (tab.match(/No material cost/g) || []).length === 1,
    ordinaryRowKeepsRemove: /data-del-item="i1"/.test(rowOf(tab, "i1")),
    before: before, after: after, missing: missing,
    queued: e.api.QUEUED.filter((q) => q.id === "joint-filler-kit" || q.id === "dye")
      .map((q) => q.id + " " + JSON.stringify(q.body)),
    notInTheLinePicker:
      !/data-pick-item="(dye|joint-filler-kit|remove-existing-jf)"/.test(pickedAll + pickedByName),
    ordinaryStillInThePicker: /data-pick-item="i1"/.test(pickedAll),
    // The bulk-add list filters on the same predicate, inline in the modal code this stub cannot
    // open -- so the predicate itself is asserted for all three ids, and against an ordinary one.
    reservedPredicate: ["joint-filler-kit", "remove-existing-jf", "dye", "i1"]
      .map((id) => s.api.isReservedItem(id)),
    defaults: defaults,
    browseFull: browseFull,
    // LISTED UNDER THE ROW'S OWN NAME, the name an admin edits on the Items tab.
    listedUnderTheirRowNames: ["Joint filler, 10 gal kit", "Remove existing joint filler",
                               "Dye, per coat"].every((n) => onHtml.indexOf("<td>" + n + "</td>") !== -1),
    // THE KIT'S UNIT IS THE ROW'S, not a word typed on this page.
    kitPricedPerTheRowsUnit: /\$500\.00 per Kit · 1 per 3,500 SF/.test(onHtml),
    editButtonsPointAtTheRows: ["joint-filler-kit", "remove-existing-jf", "dye"].every((id) =>
      onHtml.indexOf('data-def-edit="items" data-def-id="' + id + '"') !== -1),
    editRouterLandsOnTheItemsRow:
      /else \{ showView\("items"\); paint\(\); focusItemRow\(eid\); \}/.test(src),
    focusPlain: f1.dom.focused[f1.dom.focused.length - 1],
    focusHiddenFirst: hiddenFirst,
    focusThroughASearch: f2.dom.focused[f2.dom.focused.length - 1],
    searchWasCleared: f2.api.itemQueryNow() === "",
  };
}

// ── The Save button is drawn only for a row created on this page and not yet saved ──
{
  const { api, dom: d } = build({ FRESH: { items: { i2: true }, assemblies: { a2: true } } });
  api.renderItems();
  const html = d.nodes["items-body"].innerHTML;
  const rows = html.split("</tr>");
  const rowOf = (id) => rows.find((r) => r.indexOf('data-item="' + id + '"') !== -1) || "";
  const had = (r) => /data-save-new="items"/.test(r);
  out.saveButton = {
    onTheNewRow: had(rowOf("i2")) && /data-save-id="i2"/.test(rowOf("i2")),
    notOnASavedRow: !had(rowOf("i1")),
    exactlyOne: (html.match(/data-save-new="items"/g) || []).length === 1,
  };
  const fresh = build({ FRESH: { items: {}, assemblies: { a1: true } }, openId: "a1" });
  fresh.api.renderPanel();
  const saved = build({ FRESH: { items: {}, assemblies: {} }, openId: "a1" });
  saved.api.renderPanel();
  out.saveButton.asmShownWhenNew = fresh.dom.nodes["asm-save"].hidden === false;
  out.saveButton.asmHiddenWhenSaved = saved.dom.nodes["asm-save"].hidden === true;
}

// ── EXECUTED: one edit to ANY field of a material row puts Save in the row's PINNED cell ──
// Hanz, 2026-10-06: "the save button only pops up when we click away". It was inserted on the first
// keystroke all along, into .rowact -- the last column of a table about 1,990px wide, so it sat off
// screen to the right. It now goes into .rowsave, which library.html pins to the scroller's right
// edge. Measured in a real browser at 1366 and 390 (see the commit); this proves the wiring.
//
// THE REAL CHAIN, one event per field and nothing after it: onItemEdit, then patchSoon, then
// showUnsaved, then the cell. No blur, no focusout, no timer fired -- the timers are captured and
// never run, and flush is a recorder, so a Save that only appeared once the row was left would
// show up here as a flush and no button. The row the handler edits is cut out of the REAL
// renderItems output, so a cell renamed or dropped there breaks this too.
//
// Each field gets a fresh scope: patchSoon only shows the button on the FIRST unsaved edit of a
// row, so a shared scope would let the first field pass for all nine.
function itemRowDoc(rowHtml, id) {
  const cells = rowHtml.split("<td").slice(1).map((c) => {
    const open = c.slice(0, c.indexOf(">"));
    const cell = {
      cls: ((/class="([^"]*)"/.exec(open) || ["", ""])[1]).split(/\s+/).filter(Boolean),
      html: c.slice(c.indexOf(">") + 1).replace(/<\/td>\s*$/, ""),
      firstChild: null,
      querySelector(sel) {
        if (sel === "[data-save-new]") return /data-save-new=/.test(this.html) ? { parentNode: this } : null;
        if (sel === ".dupe") return null;
        throw new Error("a cell was asked for " + sel + ", which this stub does not model");
      },
      insertBefore(node) { this.html = node.outerHTML + this.html; },
      insertAdjacentHTML(_where, h) { this.html += h; },
      removeChild() { this.html = this.html.replace(/<button[^>]*data-save-new=[\s\S]*?<\/button>/, ""); },
    };
    return cell;
  });
  const doc = {
    cells,
    createElement() { return { set innerHTML(h) { this.firstChild = { outerHTML: h }; } }; },
    querySelector(sel) {
      let m = /^#items-body \[data-item="([^"]+)"\] \.([\w-]+)$/.exec(sel);
      if (m) return m[1] === id ? cells.find((c) => c.cls.indexOf(m[2]) !== -1) || null : null;
      m = /^#items-body \[data-item="([^"]+)"\] \[data-save-new\]$/.exec(sel);
      if (m) {
        const c = m[1] === id ? cells.find((x) => /data-save-new=/.test(x.html)) : null;
        return c ? { parentNode: c } : null;
      }
      throw new Error("the page asked document for " + sel + ", which this stub does not model");
    },
  };
  return doc;
}
{
  const visScope = new Function("L", "TW", "state", "document", "clock", "hooks", `
    "use strict";
    var ITEMS = state.ITEMS, ASMS = state.ASMS, VENDORS = state.VENDORS;
    var FRESH = { items: {}, assemblies: {} };
    var openId = null;
    var timers = {};
    var pendingPatch = {};
    var setTimeout = clock.setTimeout, clearTimeout = clock.clearTimeout;
    var $ = function () { return null; };
    // RECORDERS. flush is what a timer or a focusout would reach; renderItems is the repaint that
    // would throw the caret out of the field being typed in. Neither may run.
    function flush() { hooks.flushed.push(Array.prototype.slice.call(arguments)); }
    function renderItems() { hooks.repaints.push("items"); }
    function renderList() {}
    function renderPanel() {}
    ${grab(/^  var esc = function[\s\S]*?\n  \};$/m, "esc")}
    var itemBefore = {};
    ${grab(/^  var itemConfirmOpen = null;$/m, "the itemConfirmOpen declaration")}
    ${grab(/^  var itemLastField = \{\};$/m, "the itemLastField declaration")}
    ${grab(/^  var SERVER_OWNED_ITEM_FIELDS = \[[^\]]*\];$/m, "SERVER_OWNED_ITEM_FIELDS")}
    ${grab(/^  var NUMERIC_ITEM_FIELDS = \[[^\]]*\];$/m, "NUMERIC_ITEM_FIELDS")}
    ${fn("itemOf")}
    ${fn("snapshotItem")}
    ${fn("rememberItem")}
    ${fn("similarNames")}
    ${fn("dupeHtml")}
    ${fn("arm")}
    ${fn("patchSoon")}
    ${fn("itemSaveButtonHtml")}
    ${fn("showUnsaved")}
    ${fn("hideUnsaved")}
    ${fn("onItemEdit")}
    return { onItemEdit: onItemEdit, hideUnsaved: hideUnsaved,
             pending: function () { return Object.keys(pendingPatch); } };
  `);

  const { api: rapi, dom: rd } = build();
  rapi.renderItems();
  const rowHtml = rd.nodes["items-body"].innerHTML.split("</tr>")
    .find((r) => r.indexOf('data-item="i1"') !== -1) || "";

  // What one estimator action does to each kind of control. Text boxes report input; a select, the
  // checkbox and a division chip report change -- both events reach the same handler.
  const ACTIONS = {
    name: (t) => { t.value = "OPF II"; return "input"; },
    buy_qty: (t) => { t.value = "2"; return "input"; },
    coverage: (t) => { t.value = "300"; return "input"; },
    waste_pct: (t) => { t.value = "7"; return "input"; },
    unit_cost: (t) => { t.value = "90"; return "input"; },
    unit: (t) => { t.value = "Kit"; return "change"; },
    vendor: (t) => { t.value = "Sika"; return "change"; },
    roundup: (t) => { t.checked = !t.checked; return "change"; },
    divisions: null,   // driven through the real chip markup below
  };
  const fields = {};
  // EVERY data-f IN THE RENDERED ROW, not a list typed here: a tenth editable column added to
  // renderItems lands in this loop and fails until it is given an action above.
  const inRow = Array.from(new Set((rowHtml.match(/data-f="[^"]+"/g) || [])
    .map((s) => s.slice(8, -1))));
  for (const f of inRow) {
    const hooks = { flushed: [], repaints: [] };
    const clock = { setTimeout: () => 1, clearTimeout: () => {} };
    const doc = itemRowDoc(rowHtml, "i1");
    const st = { ITEMS: JSON.parse(JSON.stringify(ITEMS)), ASMS: JSON.parse(JSON.stringify(ASMS)),
                 VENDORS: JSON.parse(JSON.stringify(VENDORS)) };
    const s = visScope(L, {}, st, doc, clock, hooks);
    const cell = doc.cells.find((c) => c.html.indexOf('data-f="' + f + '"') !== -1);
    let ev = "none";
    const rowStub = { getAttribute: (k) => (k === "data-item" ? "i1" : null) };
    if (f === "divisions") {
      const chips = chipRowFromHtml("i1", cell.html);
      const off = chips.inputs.find((x) => !x.checked) || chips.inputs[0];
      off.checked = !off.checked;
      ev = "change";
      s.onItemEdit({ type: ev, target: off });
    } else if (ACTIONS[f]) {
      const tag = (new RegExp('<(input|select)[^>]*data-f="' + f + '"[^>]*>').exec(cell.html) || [""])[0];
      const target = { value: "", checked: / checked/.test(tag), parentNode: cell,
                       getAttribute: (k) => (k === "data-f" ? f : null),
                       closest: (sel) => (sel === "[data-item]" ? rowStub : null) };
      ev = ACTIONS[f](target);
      s.onItemEdit({ type: ev, target: target });
    }
    const holders = doc.cells.filter((c) => /data-save-new="items"/.test(c.html));
    const holder = holders[0];
    fields[f] = {
      event: ev,
      shown: !!holder,
      inPinnedCell: !!holder && holder.cls.indexOf("rowsave") !== -1,
      forThisRow: !!holder && /data-save-id="i1"/.test(holder.html),
      exactlyOne: holders.length === 1,
      notInActionCell: !doc.cells.some((c) => c.cls.indexOf("rowact") !== -1 &&
                                             /data-save-new=/.test(c.html)),
      queued: s.pending().indexOf("items:i1") !== -1,
      nothingFlushed: hooks.flushed.length === 0,
      noRepaint: hooks.repaints.length === 0,
    };
    // …and it leaves the cell EMPTY again, not whitespace: :empty is what keeps the column zero wide.
    if (f === "unit_cost") {
      s.hideUnsaved("items", "i1");
      // Guarded: a row with no pinned cell is a FAILED assertion, not a crash of the whole file.
      fields[f].emptyAfterHide =
        (doc.cells.find((c) => c.cls.indexOf("rowsave") !== -1) || { html: null }).html === "";
    }
  }
  // The header must carry the column too, or every cell after History sits under the wrong heading.
  // Comments cut out with indexOf, not a regex replace: a single-pass /<!--.*?-->/ strip is the
  // pattern CodeQL flags (js/incomplete-multi-character-sanitization) even on our own page source.
  const dropComments = (s) => {
    let out = "", at = 0;
    for (;;) {
      const open = s.indexOf("<!--", at);
      if (open === -1) return out + s.slice(at);
      out += s.slice(at, open);
      const close = s.indexOf("-->", open + 4);
      if (close === -1) return out;
      at = close + 3;
    }
  };
  const tableHtml = dropComments(html.slice(html.indexOf('<table class="items-table">'),
                               html.indexOf("</table>", html.indexOf('<table class="items-table">'))));
  const cleanRow = itemRowDoc(rowHtml, "i1");
  out.saveVisible = {
    fieldsInRow: inRow,
    fields: fields,
    cleanRowCellEmpty: (cleanRow.cells.find((c) => c.cls.indexOf("rowsave") !== -1) || {}).html === "",
    headerCells: (tableHtml.match(/<th[\s>]/g) || []).length,
    rowCells: cleanRow.cells.length,
    headerHasPinnedColumn: /<th class="rowsave"><\/th>\s*<th class="w-act"><\/th>/.test(tableHtml),
    cssPinsTheCell: /td\.rowsave \{ position:sticky; right:0; \}/.test(html),
    cssZeroWideWhenEmpty: /\.rowsave \{ padding:0; \}/.test(html) &&
      /td\.rowsave:not\(:empty\) \{[^}]*background:var\(--card\)/.test(html),
  };
}

// â”€â”€ the Defaults tab's starting-state SLIDER, EXECUTED â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// A slider that is only markup is the dead-control failure this page has shipped before: so each
// press below goes through the page's own setDefaultOn, and what it wrote is read back.
async function sliderChecks() {
  const B = require(path.join(ROOT, "js", "bid-model.js"));
  const seed = (extra) => Object.assign({
    window: { TWBidModel: B },
    ITEMS: [{ id: "i1", name: "Densifier", unit: "Pail", unit_cost: 100, favorite: true }],
    ASMS: [{ id: "a1", name: "Polish 800", unit: "SF", favorite: true, lines: [] },
           { id: "a2", name: "Cove", unit: "LF", favorite: true, default_on: false, lines: [] }],
    LABOR: [{ id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true,
              favorite: true, default_on: true },
            { id: "l1", name: "Grinding", rate: 40, unit: "days", favorite: true,
              default_on: false }],
    COND_DEFAULTS: [{ key: "dye", on: false, listed: true }],
    ADMIN: true,
  }, extra || {});
  const sw = (html, kind, id) => {
    const m = new RegExp('<span class="mw-sw( on)?" data-def-on="' + kind + '" data-def-on-id="' +
      id + '" role="switch" tabindex="0" aria-checked="(true|false)"').exec(html);
    return m ? m[2] : null;
  };
  const takeoff = (b) => { b.api.renderDefaultTakeoff(); return b.dom.nodes["default-takeoff-body"].innerHTML; };
  const labor = (b) => { b.api.renderDefaultLabor(); return b.dom.nodes["default-labor-body"].innerHTML; };

  // 1. WHAT IS DRAWN: absent default_on reads ON, an explicit false reads OFF, on all three kinds.
  const a = build(seed({}));
  const html0 = takeoff(a), lab0 = labor(a);
  const drawn = {
    asmAbsentIsOn: sw(html0, "assemblies", "a1"), asmFalseIsOff: sw(html0, "assemblies", "a2"),
    itemAbsentIsOn: sw(html0, "items", "i1"),
    travelOn: sw(lab0, "labor", "travel"), laborOff: sw(lab0, "labor", "l1"),
    // The three condition materials carry one too, answering with the stored starting answer.
    dyeOff: sw(html0, "items", "dye"),
  };

  // 2. THE PRESS WRITES default_on -- and not `favorite`.
  const p = build(seed({}));
  await p.api.setDefaultOn("assemblies", "a1", false);
  const afterAsm = sw(takeoff(p), "assemblies", "a1");
  const asmCalls = JSON.stringify(p.api.LABOR_CALLS);
  await p.api.setDefaultOn("labor", "l1", true);
  const afterLabor = sw(labor(p), "labor", "l1");

  // 3. A REFUSED SAVE PUTS IT BACK.
  const f = build(seed({ LABOR_FAIL: { patchDefaultOn: true } }));
  await f.api.setDefaultOn("assemblies", "a1", false);
  const afterRefused = sw(takeoff(f), "assemblies", "a1");

  // 4. A CONDITION MATERIAL'S SLIDER IS THE CONDITION DEFAULT: one write, `on` only.
  const c = build(seed({}));
  await c.api.setDefaultOn("items", "dye", true);
  const condCalls = JSON.stringify(c.api.COND_CALLS);
  const dyeAfter = sw(takeoff(c), "items", "dye");
  const noItemWrite = !c.api.LABOR_CALLS.some((x) => x.op === "PATCH_DEFAULT_ON");
  const cf = build(seed({ COND_FAIL: true }));
  await cf.api.setDefaultOn("items", "dye", true);
  const dyeRefused = sw(takeoff(cf), "items", "dye");

  // 5. A NON-ADMIN READS THE STATE AS WORDS, never a switch that would 403.
  const v = build(seed({ ADMIN: false }));
  const vHtml = takeoff(v), vLab = labor(v);
  const viewer = {
    // Labor (a PATCH the server refuses a non-admin) and the condition materials (a PUT it
    // refuses) show words; items and assemblies stay switches, exactly like their Remove button.
    noLaborSwitches: !/data-def-on=/.test(vLab),
    noConditionSwitch: sw(vHtml, "items", "dye") === null,
    laborSaysOff: /<td class="rowon"><span class="wtall">Off<\/span>/.test(vLab),
    dyeSaysOff: /<td class="rowon"><span class="wtall">Off<\/span>/.test(vHtml),
    asmStillSwitch: sw(vHtml, "assemblies", "a1") === "true",
  };

  out.defaultSlider = {
    drawn: drawn, afterAsm: afterAsm, asmCalls: asmCalls, afterLabor: afterLabor,
    afterRefused: afterRefused, condCalls: condCalls, dyeAfter: dyeAfter,
    noItemWrite: noItemWrite, dyeRefused: dyeRefused, viewer: viewer,
  };
}

// ── the Fees + Textura default row on the Defaults tab (Hanz, 2026-10-06), EXECUTED ──────────────
async function feesChecks() {
  const B = require(path.join(ROOT, "js", "bid-model.js"));
  const mk = (state) => build(Object.assign({ window: { TWBidModel: B }, ADMIN: true }, state));
  // 1. Always listed in the Markup group, empty box when nothing is filed (= $0).
  const none = mk({});
  const row0 = none.api.feesDefaultRow();
  const groupsNone = none.api.takeoffDefaultGroups().map((g) => g.title);
  // 2. Typing a figure PUTs the markup row for line fees_textura, notes carried, and keeps the rule.
  const a = mk({ FEES_RULE: { id: "r1", layout: "global", line_key: "fees_textura", formula: "100",
                              applies: true, notes: "kept" } });
  const box = { value: "$1,250", getAttribute: () => "1" };
  await a.api.saveFeesDefault(box);
  const sent = a.api.FEES_CALLS.map((c) => ({ path: c.path, method: c.opts.method,
                                              body: JSON.parse(c.opts.body) }));
  // 3. A blank box files $0; junk is refused and nothing is sent.
  const b = mk({ FEES_RULE: { layout: "global", line_key: "fees_textura", formula: "100", applies: true } });
  await b.api.saveFeesDefault({ value: "", getAttribute: () => "1" });
  const blankSent = b.api.FEES_CALLS.map((c) => JSON.parse(c.opts.body).formula);
  const c2 = mk({});
  const junk = { value: "abc", getAttribute: () => "1" };
  await c2.api.saveFeesDefault(junk);
  // 4. A 403 puts the old figure back.
  const d403 = mk({ FEES_RULE: { layout: "global", line_key: "fees_textura", formula: "100", applies: true },
                    FEES_RESPONSE: { status: 403 } });
  const box403 = { value: "300", getAttribute: () => "1" };
  await d403.api.saveFeesDefault(box403);
  // 5. A viewer gets text, not a box.
  const viewer = mk({ ADMIN: false, FEES_RULE: { layout: "global", line_key: "fees_textura",
                                                 formula: "250", applies: true } });
  out.feesDefaultRow = {
    listedWithNothingFiled: groupsNone.indexOf("Markup") >= 0,
    emptyBox: /data-fees-default="1" value=""/.test(row0.how),
    name: row0.name,
    sent: sent, ruleAfter: a.api.feesRuleNow() && a.api.feesRuleNow().formula,
    boxAfter: box.value,
    blankSent: blankSent,
    junkSent: c2.api.FEES_CALLS.length, junkBox: junk.value,
    refusedBox: box403.value, refusedRule: d403.api.feesRuleNow().formula,
    viewerHasBox: /<input/.test(viewer.api.feesDefaultRow().how),
    viewerText: viewer.api.feesDefaultRow().how,
  };
}

// A WATCHDOG, because the alternative failure mode is silence. These scenarios await dialogs and
// held requests, so a change that opens one more dialog than a test answers leaves a flush waiting
// forever: node's loop empties, the process exits 0, and nothing is printed — which the fixture
// reports as "the harness itself failed" with no line number and no clue. A pending timer keeps
// the loop alive long enough to say what actually happened.
const watchdog = setTimeout(() => {
  console.error("A SCENARIO NEVER SETTLED. Something is awaiting a dialog nobody answered or a "
    + "request nobody released — most likely a change that asks one MORE time than the scenario "
    + "expects. Look at the scenario you touched, not at this file.");
  process.exit(1);
}, 30000);

Promise.all([conflictChecks(), dialogChecks(), laborChecks(), laborTabChecks(),
             conditionChecks(), sliderChecks(), feesChecks()]).then(
  () => { clearTimeout(watchdog); console.log(JSON.stringify(out)); },
  (err) => { clearTimeout(watchdog); console.error(err); process.exit(1); });