"use strict";
/* Run the Notification Sending page's ROSTER half for real, both cards, out of
 * frontend/js/notifications.js: the team floor and the person x CRM-step matrix.
 *
 * WHY EXECUTED, NOT GREPPED. Every claim here is about what the page DOES with a kind and a
 * state, and each one is invisible to a source read:
 *
 *   * "An inherited cell looks different from an explicit one." A grep proves the string
 *     "inherited" appears somewhere. Only rendering the grid proves that a green cell which came
 *     from the team list carries a different class, a different word and a different aria-label
 *     from one somebody set. That misreading is the main risk this feature carries, so it is the
 *     thing most worth executing.
 *   * "A click writes the right state." mxNext is a three-valued decision over two booleans, and
 *     `wantOn ? "on" : "off"` reads perfectly well while being unable to ever clear a cell. Only
 *     the request body says which.
 *   * "The columns come from the API." A hardcoded step list would render identically until the
 *     portal learned a tenth step. Only feeding a different list through proves it.
 *   * "The column warns when it reaches nobody." That is a computation over three inputs and it
 *     must agree with the resolver, not with the count of green pixels.
 *   * The cells are re-wired on every paint, from freshly generated HTML, so "does a click after
 *     a repaint still send the right PUT" is a question about handlers on new nodes.
 *
 * Names and initials come from the REAL crm-core.js, so a person looks the same here as on a CRM
 * card. The api stub keeps a little store, so the page's own reload after a mutation reports what
 * actually survived, which is the real worry ("did I just take them off everything?").
 *
 * Usage: node notify-matrix-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);

// CRLF normalised on read: git hands these files out with CRLF on a Windows checkout and every
// `^  const ...$` pattern below would find a trailing \r and miss. (notify-tabs-harness.js carries
// the same note; CI checks out LF and stays green either way.)
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const src = read(path.join(ROOT, "js", "notifications.js"));
const C = require(path.join(ROOT, "js", "crm-core.js"));

/** Lift a named function out of the page's IIFE (two-space indent), braces balanced. `async`
 *  included: load/toggle/addEmail/removeOne/toggleCell are all async, and dropping the keyword
 *  would turn an awaited fetch into a synchronous call that throws. */
function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from notifications.js, rewrite this harness rather than stubbing it");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name + "()");
}

/** Lift a top-level `const`/`let` declaration, however many lines and brackets it spans. GROUPS is
 *  an array of objects and MX_LABEL a map, and both must come from the PAGE since their copy is
 *  half of what is being tested. Reads to the first `;` outside any bracket. */
function decl(name) {
  const m = new RegExp("\\n  (?:const|let) " + name + "\\b").exec(src);
  if (!m) throw new Error(name + " is gone from notifications.js, rewrite this harness");
  let depth = 0;
  for (let j = m.index; j < src.length; j++) {
    const ch = src[j];
    if ("([{".indexOf(ch) >= 0) depth++;
    else if (")]}".indexOf(ch) >= 0) depth--;
    else if (ch === ";" && depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unterminated declaration reading " + name);
}

// ── a DOM small enough to read, real enough to hold the controls ──────────────
/** The chips the page just wrote, materialised out of its OWN output string. The page sets
 *  innerHTML and then queries the result, so the objects the handlers receive have to come from
 *  that string: a hand-built fixture could agree with the handler and disagree with what renders. */
function parseChips(html) {
  const parts = String(html).split('<span class="chip');
  const out = [];
  for (let i = 1; i < parts.length; i++) {
    const full = '<span class="chip' + parts[i];
    const open = full.slice(0, full.indexOf(">") + 1);
    const node = {
      html: full,
      className: (/class="([^"]*)"/.exec(open) || ["", ""])[1],
      dataset: {}, style: {}, listeners: {},
      email: (/<span class="em">([^<]*)</.exec(full) || ["", ""])[1],
      also: (/<span class="also">([^<]*)</.exec(full) || ["", null])[1],
      // The IDENTITY colour. A roster chip carries the shared avatar so a person looks the same
      // here as on a CRM card; the matrix cells deliberately do NOT, because colour there is the
      // state. Reported so the two cannot quietly swap.
      avatarHtml: (/<span class="tw-av[^>]*>/.exec(full) || [null])[0],
      addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); },
      _fire(k, ev) { (this.listeners[k] || []).forEach((f) => f(ev)); },
    };
    let a;
    const ra = /data-([a-z-]+)="([^"]*)"/g;
    while ((a = ra.exec(open))) {
      node.dataset[a[1].replace(/-([a-z])/g, (s, c) => c.toUpperCase())] = a[2];
    }
    const hasX = full.indexOf('<button class="x"') >= 0;
    node.x = hasX ? {
      listeners: {},
      addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); },
      /** A real x click BUBBLES to the chip, and the chip's own handler guards on
       *  `e.target.classList.contains("x")` while the x calls stopPropagation(). Modelled rather
       *  than short-circuited: with either guard missing, removing somebody would also toggle
       *  them, and a harness that fired only the x listener could not see it. */
      click() {
        const ev = { stopped: false, stopPropagation() { this.stopped = true; },
                     target: { classList: { contains: (c) => c === "x" } } };
        (this.listeners.click || []).forEach((f) => f(ev));
        if (!ev.stopped) node._fire("click", ev);
      },
    } : null;
    node.querySelector = (sel) => (sel === ".x" ? node.x
      : sel === ".em" ? { textContent: node.email } : null);
    node.click = () => node._fire("click", { target: { classList: { contains: () => false } } });
    out.push(node);
  }
  return out;
}

/** One matrix cell, out of the rendered table. The class list, the glyph, the aria-label and the
 *  data attributes are all read back from the page's own markup, because "does an inherited cell
 *  look different" is a question about exactly those four things. */
function parseCells(html) {
  const out = [];
  const re = /<button type="button" class="(mx-cell[^"]*)"([^>]*)>\s*<span class="mx-g"[^>]*>([^<]*)<\/span>/g;
  let m;
  while ((m = re.exec(html))) {
    const attrs = m[2];
    const node = {
      className: m[1], glyph: m[3], dataset: {}, listeners: {},
      disabled: /\sdisabled(?=[\s>])/.test(attrs),
      ariaPressed: (/aria-pressed="([^"]*)"/.exec(attrs) || ["", ""])[1],
      ariaLabel: (/aria-label="([^"]*)"/.exec(attrs) || ["", ""])[1],
      addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); },
      click() { if (this.disabled) return false; (this.listeners.click || []).forEach((f) => f({})); return true; },
    };
    let a;
    const ra = /data-([a-z-]+)="([^"]*)"/g;
    while ((a = ra.exec(attrs))) {
      node.dataset[a[1].replace(/-([a-z])/g, (s, c) => c.toUpperCase())] = a[2];
    }
    out.push(node);
  }
  return out;
}

/** A node whose parsed children are cached per rendered string and dropped the moment innerHTML is
 *  replaced, exactly like a real re-render, so a handler attached to a node is the node clicked. */
function htmlNode(parsers) {
  let html = "", cache = null;
  return {
    get innerHTML() { return html; },
    set innerHTML(v) { html = String(v); cache = null; },
    querySelectorAll(sel) {
      if (!parsers[sel]) return [];
      if (!cache) cache = {};
      if (!cache[sel]) cache[sel] = parsers[sel](html);
      return cache[sel];
    },
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

/** Every id the page reaches for. Supplied by hand, which is exactly why the report also carries
 *  the ids render() actually WROTE: a card whose markup never made it onto the page cannot pass by
 *  resolving here. */
function makeDom(groups) {
  const nodes = {
    root: (function () {
      let html = "";
      return { get innerHTML() { return html; }, set innerHTML(v) { html = String(v); } };
    })(),
    "mx-grid": htmlNode({ ".mx-cell": parseCells }),
    "mx-legend": htmlNode({ ".mx-cell": parseCells }),
    "mx-alert": { className: "", textContent: "" },
    "pp-search": control({ value: "" }),
    "pp-tabs": control({ querySelectorAll: () => [] }),
    "pp-alert": { className: "", textContent: "" },
    "pp-list": { innerHTML: "", querySelectorAll: () => [] },
    "pp-pager": { hidden: false },
    "pp-pgn": { textContent: "" },
    "pp-prev": control({ disabled: false }),
    "pp-next": control({ disabled: false }),
  };
  groups.forEach((g) => {
    nodes[g.chips] = htmlNode({ ".chip": parseChips });
    nodes[g.input] = control({ value: "" });
    nodes[g.btn] = control({ disabled: false, textContent: "Add" });
    nodes[g.alert] = { className: "", textContent: "" };
  });
  return nodes;
}

// ── the page's roster half, wired to a store that answers like the API ────────
const SOURCE = [
  decl("ROSTER"), decl("STEPS"), decl("CELLS"), decl("INERT"), decl("RAW"), decl("GROUPS"),
  decl("stepIds"), decl("kindOf"), decl("stepsOfRow"), decl("listFor"), decl("onList"),
  decl("MX_LABEL"), decl("stepLabel"),
  fn("alertOf"), fn("rosterCardHtml"), fn("matrixCardHtml"), fn("mxAlert"), fn("render"),
  fn("paintGroup"), fn("mxPeople"), fn("mxCell"), fn("mxNext"), fn("mxColumn"),
  fn("paintLegend"), fn("paintMatrix"), fn("toggleCell"),
  fn("repaintGroups"), fn("load"), fn("toggle"), fn("addEmail"), fn("removeOne"), fn("peopleFor"),
].join("\n");

/** The nine steps the portal serves today, in the portal's order. Kept here as a FIXTURE, not as
 *  the page's source of truth: the page renders whatever the API hands it, and `altSteps` below
 *  proves that by handing it something else. */
const STEP_LIST = [
  // `required` is the portal's flag for a step that may not be left reaching nobody, because its
  // email is also the delivery-FAILURE alert. Served, not hardcoded here, like everything else
  // about the vocabulary.
  { id: "sent", label: "Proposal sent", required: true,
    hint: "The proposal was emailed to the customer, including when a delivery failed." },
  { id: "viewed", label: "Proposal opened", hint: "The customer opened the proposal." },
  { id: "question", label: "Customer question", hint: "The customer asked a question." },
  { id: "status_change", label: "Customer status", hint: "Delayed, not moving forward, or back on." },
  { id: "approved", label: "Proposal approved", hint: "The customer approved and signed." },
  { id: "deposit_submitted", label: "Deposit sent", hint: "ACH details, or a check on the way." },
  { id: "deposit_received", label: "Deposit received", hint: "Staff marked the deposit received." },
  { id: "contacts", label: "Project contacts", hint: "The customer submitted their contacts." },
  { id: "feedback", label: "Portal feedback", hint: "Feedback about the portal itself." },
];

function build(opts) {
  const o = opts || {};
  const rows = (o.rows || []).map((r) => Object.assign({}, r));
  const steps = o.steps || STEP_LIST;
  const calls = [];
  const dialogs = [];
  let nextId = 100;
  let failOn = o.failOn || null;                     // e.g. "POST" -> that verb rejects

  const api = (p, init) => {
    const method = (init || {}).method || "GET";
    const body = (init || {}).body ? JSON.parse(init.body) : null;
    calls.push({ path: p, method, body });
    if (failOn === method || (method === "GET" && o.loadFails)) {
      return Promise.resolve({ ok: false, status: 500,
                               json: () => Promise.resolve({ error: "boom" }) });
    }
    if (method === "GET") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(
        { ok: true, steps: steps.map((x) => Object.assign({}, x)),
          recipients: rows.map((r) => Object.assign({}, r)) }) });
    }
    // The store, so the page's own reload after a mutation shows what really survived.
    if (method === "PUT" && String(p).indexOf("/notify-recipients/step") >= 0) {
      // The portal REFUSES a write that would leave a required column reaching nobody (only
      // `sent` is one today). Modelled rather than assumed, because the claim under test is what
      // the page does with that answer: the message it prints and the cell it snaps back.
      if (o.refuse) {
        return Promise.resolve({ ok: false, status: 400,
                                 json: () => Promise.resolve({ ok: false,
                                                               error: "would_silence_step",
                                                               step: body.step }) });
      }
      const i = rows.findIndex((r) => String(r.email).toLowerCase() === body.email
                                   && r.kind === body.step);
      if (body.state === "inherit") { if (i >= 0) rows.splice(i, 1); }
      else if (i >= 0) rows[i].enabled = body.state === "on";
      else rows.push({ id: nextId++, email: body.email, kind: body.step,
                       enabled: body.state === "on" });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    }
    const id = decodeURIComponent(String(p).split("/").pop());
    if (method === "DELETE") {
      const i = rows.findIndex((r) => String(r.id) === id);
      if (i >= 0) rows.splice(i, 1);
    } else if (method === "PATCH") {
      const row = rows.filter((r) => String(r.id) === id)[0];
      if (row) row.enabled = !!body.enabled;
    } else if (method === "POST") {
      rows.push({ id: nextId++, email: body.email, kind: body.kind, enabled: false });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
  };

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const TW = {
    confirmDanger: (cfg) => { dialogs.push(cfg); return Promise.resolve(o.confirm !== false); },
  };
  const scope = new Function(
    "$", "esc", "avatar", "plainAvatar", "nameOf", "api", "TW", "ADMIN", "renderProjects",
    "OVERRIDES", "PP_TABS", "PP_IDS", "PP_TAB", "PP_TAB_KEY", "ssSet", "ppGoto",
    '"use strict";\n' + SOURCE + "\n" +
    "return { render, load, paintGroup, paintMatrix, peopleFor, GROUPS, kindOf, onList,\n" +
    "         mxPeople, mxCell, mxNext, mxColumn, MX_LABEL, stepsOfRow,\n" +
    "         roster: () => ROSTER, steps: () => STEPS, cells: () => JSON.parse(JSON.stringify(CELLS)) };");

  let dom = null;
  const s = scope(
    (id) => (dom ? dom[id] : null) || null,
    esc, C.avatarHtml,
    (who) => '<span class="nt-av">' + (C.initialsOf(who) || "-") + "</span>",
    C.nameOf, api, TW, o.admin !== false,
    () => { s.projectRenders++; },
    o.overrides || {},
    [["active", "Active"], ["won", "Won"], ["lost", "Lost"], ["test", "Test"]],
    ["active", "won", "lost", "test"], "active", "tw_notify_pp_tab", () => {}, () => {});
  dom = makeDom(s.GROUPS);
  s.projectRenders = 0;
  s.dom = dom;
  s.calls = calls;
  s.dialogs = dialogs;
  s.rows = rows;
  s.group = (kind) => s.GROUPS.filter((g) => g.kind === kind)[0];
  s.chips = (kind) => dom[s.group(kind).chips].querySelectorAll(".chip");
  s.chipsHtml = (kind) => dom[s.group(kind).chips].innerHTML;
  s.alertText = (kind) => dom[s.group(kind).alert].textContent;
  s.type = (kind, v) => { dom[s.group(kind).input].value = v; };
  s.clickAdd = (kind) => dom[s.group(kind).btn].fire("click");
  s.setFail = (verb) => { failOn = verb; };
  s.grid = () => dom["mx-grid"].innerHTML;
  s.cellNodes = () => dom["mx-grid"].querySelectorAll(".mx-cell");
  s.cellAt = (email, step) => s.cellNodes().filter(
    (c) => String(c.dataset.email).toLowerCase() === String(email).toLowerCase()
        && c.dataset.step === step)[0] || { dataset: {}, _missing: true, click() { return false; } };
  s.mxAlertText = () => dom["mx-alert"].textContent;
  return s;
}

/** The column headers, as rendered: the label, whether it is drawn as quiet, and whether it
 *  carries the "nobody is told" warning. Three separate facts, because the warning being on the
 *  RIGHT column is the claim, not that one exists somewhere. */
function heads(html) {
  const out = [];
  const re = /<th class="(mx-head[^"]*)" title="[^"]*"><span class="mx-h">([^<]*)<\/span>([\s\S]*?)<\/th>/g;
  let m;
  while ((m = re.exec(html))) {
    out.push({ label: m[2], quiet: m[1].indexOf("mx-quiet") >= 0,
               warn: m[3].indexOf("mx-warn") >= 0, req: m[3].indexOf("mx-req") >= 0 });
  }
  return out;
}

/** What a cell actually says, which is what the reader gets. */
const cellOf = (c) => ({
  email: c.dataset && c.dataset.email, step: c.dataset && c.dataset.step,
  state: c.dataset && c.dataset.state, next: c.dataset && c.dataset.next,
  on: c.dataset && c.dataset.on, floor: c.dataset && c.dataset.floor,
  cls: c.className, glyph: c.glyph, pressed: c.ariaPressed, label: c.ariaLabel,
  disabled: c.disabled, missing: !!c._missing,
});
const chipOf = (c) => ({
  id: c.dataset.id, kind: c.dataset.kind, email: c.email, on: /\bon\b/.test(c.className),
  also: c.also, removable: !!c.x, coloured: !!c.avatarHtml,
});
const tick = () => new Promise((r) => setTimeout(r, 0));

// ── fixtures ────────────────────────────────────────────────────────────────
// The production shape as of 2026-08-21, MIGRATED: three general rows, one of them off, plus
// kylene@ on the two money steps (she was a single `kind='deposit'` row before the widening),
// plus one suppression: Kyle does not want the "proposal opened" email.
const MIXED = [
  { id: 1, email: "hanz@wetreadwell.com", kind: "general", enabled: true },
  { id: 2, email: "kyle.loseke@wetreadwell.com", kind: "general", enabled: true },
  { id: 3, email: "will@wetreadwell.com", kind: "general", enabled: false },
  { id: 4, email: "kylene@wetreadwell.com", kind: "deposit_submitted", enabled: true },
  { id: 5, email: "kylene@wetreadwell.com", kind: "deposit_received", enabled: true },
  { id: 6, email: "kyle.loseke@wetreadwell.com", kind: "viewed", enabled: false },
];
// The un-migrated shape: kylene@ still on the single legacy 'deposit' row. The portal fans it out
// to both money steps at resolve time, so the grid has to as well or it would show her switched
// off for emails she is in fact getting.
const LEGACY = [
  { id: 1, email: "hanz@wetreadwell.com", kind: "general", enabled: true },
  { id: 2, email: "kylene@wetreadwell.com", kind: "deposit", enabled: true },
];
// The same row switched OFF, which is what every address ever typed into the old Deposit-alerts
// card and never turned green looks like: adding has ALWAYS created the row off. Under the old
// vocabulary that meant "not on the deposit list" and nothing more, so the portal's resolver skips
// it rather than reading it as a suppression, and the grid has to agree.
const LEGACY_OFF = [
  { id: 1, email: "hanz@wetreadwell.com", kind: "general", enabled: true },
  { id: 2, email: "kylene@wetreadwell.com", kind: "deposit", enabled: false },
];

const out = {};

(async () => {
  // ── the page renders three cards, out of its own render() ───────────────────
  {
    const s = build({ rows: MIXED });
    s.render();
    const html = s.dom.root.innerHTML;
    out.render = {
      html,
      ids: (html.match(/id="([\w-]+)"/g) || []).map((m) => m.slice(4, -1)),
      cards: (html.match(/<div class="card">/g) || []).length,
      labels: (html.match(/<div class="lbl">([^<]*)</g) || []).map((m) => m.slice(17, -1)),
    };
    out.groups = s.GROUPS.map((g) => ({
      kind: g.kind, chips: g.chips, input: g.input, btn: g.btn, alert: g.alert,
      lbl: g.lbl, intro: g.intro, empty: g.empty, what: g.what, also: g.also,
      removeTitle: g.removeTitle, removeBefore: g.removeBefore, removeAlso: g.removeAlso,
    }));
    out.labelMap = s.MX_LABEL;

    await s.load();
    out.loaded = {
      steps: s.steps().map((x) => x.id),
      roster: s.roster(),
      cells: s.cells(),
      people: s.mxPeople(),
      chips: chipOf ? s.chips("general").map(chipOf) : null,
      grid: s.grid(),
      cellCount: s.cellNodes().length,
      legend: s.dom["mx-legend"].innerHTML,
      legendCells: s.dom["mx-legend"].querySelectorAll(".mx-cell").map((c) => c.className),
    };
    // Every cell in the grid, by (person, step), as the page rendered it.
    out.cells = {};
    s.cellNodes().forEach((c) => {
      out.cells[c.dataset.email + "|" + c.dataset.step] = cellOf(c);
    });
    out.columns = s.steps().map((st) => s.mxColumn(st.id));
  }

  // ── the four states, side by side on ONE column ─────────────────────────────
  // hanz: on the team, nothing set        -> inherited
  // kyle: on the team, explicit off       -> off
  // will: on the team but switched off    -> none
  // kylene: not on the team, explicit on  -> on   (on the money steps)
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    out.fourStates = {
      viewed: ["hanz@wetreadwell.com", "kyle.loseke@wetreadwell.com", "will@wetreadwell.com",
               "kylene@wetreadwell.com"].map((e) => cellOf(s.cellAt(e, "viewed"))),
      depositReceived: ["hanz@wetreadwell.com", "kylene@wetreadwell.com"]
        .map((e) => cellOf(s.cellAt(e, "deposit_received"))),
    };
  }

  // ── a click on each of the four states ─────────────────────────────────────
  {
    // INHERITED -> off. The one that has to write a row rather than delete one, because "off"
    // has to outrank the floor and only a stored row can.
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.cellAt("hanz@wetreadwell.com", "approved").click();
    await tick(); await tick();
    out.clickInherited = {
      put: s.calls.filter((c) => c.method === "PUT").pop(),
      after: cellOf(s.cellAt("hanz@wetreadwell.com", "approved")),
      // The rest of Hanz's row is untouched: a suppression is one step, not a person.
      elsewhere: cellOf(s.cellAt("hanz@wetreadwell.com", "sent")),
      cells: s.cells(),
      rows: s.rows.filter((r) => r.kind === "approved"),
    };
  }
  {
    // EXPLICIT OFF -> inherit. Back to following the team list, NOT an explicit on: an accumulated
    // row that happens to agree with the floor is a row that stops agreeing the day somebody is
    // taken off the team.
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.cellAt("kyle.loseke@wetreadwell.com", "viewed").click();
    await tick(); await tick();
    out.clickOff = {
      put: s.calls.filter((c) => c.method === "PUT").pop(),
      after: cellOf(s.cellAt("kyle.loseke@wetreadwell.com", "viewed")),
      cells: s.cells(),
      rows: s.rows.filter((r) => r.kind === "viewed"),
    };
  }
  {
    // NONE -> on. This is how a deposit-only person is created, and how somebody not on the team
    // is given exactly one moment.
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.cellAt("will@wetreadwell.com", "contacts").click();
    await tick(); await tick();
    out.clickNone = {
      put: s.calls.filter((c) => c.method === "PUT").pop(),
      after: cellOf(s.cellAt("will@wetreadwell.com", "contacts")),
      cells: s.cells(),
    };
  }
  {
    // EXPLICIT ON, for somebody off the floor -> inherit, which leaves them at none.
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.cellAt("kylene@wetreadwell.com", "deposit_received").click();
    await tick(); await tick();
    out.clickOn = {
      put: s.calls.filter((c) => c.method === "PUT").pop(),
      after: cellOf(s.cellAt("kylene@wetreadwell.com", "deposit_received")),
      // Her OTHER money step is untouched, which is the two-rows-not-one property.
      other: cellOf(s.cellAt("kylene@wetreadwell.com", "deposit_submitted")),
      cells: s.cells(),
      // She still has a row, so she is still on the grid rather than vanishing mid-edit.
      people: s.mxPeople().map((p) => p.email),
    };
  }

  // ── a whole column switched off says so ───────────────────────────────────
  {
    const s = build({ rows: [
      { id: 1, email: "hanz@wetreadwell.com", kind: "general", enabled: true },
      { id: 2, email: "kyle.loseke@wetreadwell.com", kind: "general", enabled: true },
    ] });
    s.render();
    await s.load();
    out.beforeSilence = { columns: s.steps().map((st) => s.mxColumn(st.id).silent),
                          warns: (s.grid().match(/mx-warn/g) || []).length,
                          heads: heads(s.grid()) };
    s.cellAt("hanz@wetreadwell.com", "viewed").click();
    await tick(); await tick();
    s.cellAt("kyle.loseke@wetreadwell.com", "viewed").click();
    await tick(); await tick();
    out.afterSilence = {
      column: s.mxColumn("viewed"),
      others: s.steps().filter((st) => st.id !== "viewed").map((st) => s.mxColumn(st.id).silent),
      warns: (s.grid().match(/mx-warn/g) || []).length,
      // The warning has to be ON the right column, so report which header carries it.
      heads: heads(s.grid()),
      quiet: heads(s.grid()).filter((h) => h.quiet).map((h) => h.label),
      warned: heads(s.grid()).filter((h) => h.warn).map((h) => h.label),
      gridHead: s.grid().slice(0, s.grid().indexOf("</thead>") + 8),
    };
  }

  // ── the columns come from the API, not from this page ─────────────────────
  {
    const s = build({ rows: MIXED, steps: [
      { id: "sent", label: "Proposal sent", hint: "Emailed to the customer." },
      { id: "invoice_issued", label: "Invoice issued", hint: "A step this page has never seen." },
    ] });
    s.render();
    await s.load();
    out.altSteps = {
      steps: s.steps().map((x) => x.id),
      heads: heads(s.grid()).map((h) => h.label),
      cellsPerRow: s.cellNodes().length / s.mxPeople().length,
      // kylene@'s deposit rows name steps this list does not carry, so they are not step rows
      // here. She must still be VISIBLE somewhere rather than dropped, which is the whole
      // lesson of the row that was live and invisible.
      people: s.mxPeople().map((p) => p.email),
      chips: s.chips("general").map((c) => c.email),
    };
    const put = s.cellAt("hanz@wetreadwell.com", "invoice_issued");
    put.click();
    await tick(); await tick();
    out.altStepPut = s.calls.filter((c) => c.method === "PUT").pop();
  }
  {
    // No step list at all: a broken payload must say so rather than render an empty grid that
    // reads as "nobody is notified about anything".
    const s = build({ rows: MIXED, steps: [] });
    s.render();
    await s.load();
    out.noSteps = { grid: s.grid(), cells: s.cellNodes().length };
  }

  // ── the legacy 'deposit' row still lights both money cells ────────────────
  {
    const s = build({ rows: LEGACY });
    s.render();
    await s.load();
    out.legacy = {
      cells: s.cells(),
      submitted: cellOf(s.cellAt("kylene@wetreadwell.com", "deposit_submitted")),
      received: cellOf(s.cellAt("kylene@wetreadwell.com", "deposit_received")),
      approved: cellOf(s.cellAt("kylene@wetreadwell.com", "approved")),
      // And she must NOT be sitting on the team card looking like floor membership she does not
      // have. stepsOfRow is what decides that.
      chips: s.chips("general").map((c) => c.email),
      stepsOfRow: s.stepsOfRow({ email: "x", kind: "deposit" }),
    };
  }

  // ── a row whose kind nothing recognises ──────────────────────────────────
  // The portal's resolver buckets anything it does not know as the floor, and a row this page
  // silently dropped is the original bug. So: visible, on the team card.
  {
    const s = build({ rows: [
      { id: 1, email: "nokind@wetreadwell.com", enabled: true },
      { id: 2, email: "future@wetreadwell.com", kind: "invoice_issued", enabled: true },
      { id: 3, email: "kylene@wetreadwell.com", kind: "deposit_received", enabled: true },
    ] });
    s.render();
    await s.load();
    out.unknownKind = {
      chips: s.chips("general").map((c) => c.email),
      people: s.mxPeople().map((p) => p.email),
      cells: s.cells(),
    };
  }

  // ── the floor moves, and every inherited cell moves with it ───────────────
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    const will = s.chips("general").filter((c) => c.email.indexOf("will") === 0)[0];
    out.floorMove = { before: cellOf(s.cellAt("will@wetreadwell.com", "sent")) };
    will.click();                                    // off -> on, on the team card
    await tick(); await tick();
    out.floorMove.after = cellOf(s.cellAt("will@wetreadwell.com", "sent"));
    out.floorMove.patch = s.calls.filter((c) => c.method === "PATCH").pop();
    // Kyle's explicit off is NOT disturbed by somebody else's floor change.
    out.floorMove.kyle = cellOf(s.cellAt("kyle.loseke@wetreadwell.com", "viewed"));
  }

  // ── the team card knows a person carries step exceptions ─────────────────
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    out.exceptionLabel = {
      chips: s.chips("general").map(chipOf),
      onList: {
        kyleGeneral: s.onList("general", "kyle.loseke@wetreadwell.com"),
        kyleSteps: s.onList("step", "kyle.loseke@wetreadwell.com"),
        hanzSteps: s.onList("step", "hanz@wetreadwell.com"),
        kyleneGeneral: s.onList("general", "kylene@wetreadwell.com"),
      },
    };
    // Removing Kyle from the team must warn that his step settings survive.
    const kyle = s.chips("general").filter((c) => c.email.indexOf("kyle.") === 0)[0];
    kyle.x.click();
    await tick(); await tick();
    out.removeWarns = {
      dialog: s.dialogs[s.dialogs.length - 1],
      deletes: s.calls.filter((c) => c.method === "DELETE"),
      chips: s.chips("general").map((c) => c.email),
      people: s.mxPeople().map((p) => p.email),
      // His suppression row is still there, and now reads as "not on the team" rather than "off".
      viewed: cellOf(s.cellAt("kyle.loseke@wetreadwell.com", "viewed")),
      patches: s.calls.filter((c) => c.method === "PATCH").length,
    };
  }
  {
    // Somebody with NO step rows gets the plain question, not the reassurance.
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    const hanz = s.chips("general").filter((c) => c.email.indexOf("hanz") === 0)[0];
    hanz.x.click();
    await tick(); await tick();
    out.removePlain = { dialog: s.dialogs[s.dialogs.length - 1] };
  }

  // ── adding somebody still lands on the team, switched off ────────────────
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.type("general", "  NewTeam@Wetreadwell.com ");
    s.clickAdd("general");
    await tick(); await tick();
    out.add = {
      post: s.calls.filter((c) => c.method === "POST").pop(),
      alert: s.alertText("general"),
      chips: s.chips("general").map(chipOf),
      // A brand new person is off, so their whole matrix row is "none": adding somebody must
      // never start sending.
      row: s.steps().map((st) => cellOf(s.cellAt("newteam@wetreadwell.com", st.id)).state),
    };
  }

  // ── a non-admin sees the grid and can change nothing ────────────────────
  {
    const s = build({ rows: MIXED, admin: false });
    s.render();
    await s.load();
    out.staff = {
      html: s.dom.root.innerHTML,
      cellsDisabled: s.cellNodes().map((c) => c.disabled),
      cellListeners: s.cellNodes().map((c) => Object.keys(c.listeners).length),
      fired: s.cellAt("hanz@wetreadwell.com", "viewed").click(),
      puts: s.calls.filter((c) => c.method === "PUT").length,
      grid: s.grid(),
    };
  }

  // ── a failed write says so and leaves the grid telling the truth ────────
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.setFail("PUT");
    s.cellAt("hanz@wetreadwell.com", "approved").click();
    await tick(); await tick();
    out.putFails = {
      alert: s.mxAlertText(),
      cell: cellOf(s.cellAt("hanz@wetreadwell.com", "approved")),
      cells: s.cells(),
      // The roster card must not report somebody else's failure.
      groupAlert: s.alertText("general"),
    };
  }

  // ── one failed fetch must not look like half a working page ─────────────
  {
    const s = build({ rows: MIXED, loadFails: true });
    s.render();
    await s.load();
    out.loadFails = { general: s.chipsHtml("general"), grid: s.grid() };
  }

  // ── the empty roster ────────────────────────────────────────────────────
  {
    const s = build({ rows: [] });
    s.render();
    await s.load();
    out.empty = { general: s.chipsHtml("general"), grid: s.grid(),
                  cells: s.cellNodes().length };
  }

  // ── 13 people by 9 steps, the size this has to survive ─────────────────
  {
    const many = [];
    for (let i = 1; i <= 13; i++) {
      many.push({ id: i, email: "person" + (i < 10 ? "0" + i : i) + "@wetreadwell.com",
                  kind: "general", enabled: i % 3 !== 0 });
    }
    const s = build({ rows: many });
    s.render();
    await s.load();
    out.thirteen = {
      people: s.mxPeople().length,
      cells: s.cellNodes().length,
      rows: (s.grid().match(/<tr>/g) || []).length,
      heads: (s.grid().match(/class="mx-head/g) || []).length,
      states: s.cellNodes().reduce((a, c) => {
        a[c.dataset.state] = (a[c.dataset.state] || 0) + 1;
        return a;
      }, {}),
      // The name column is sticky and the grid scrolls inside its own box, so the page itself
      // never scrolls sideways. Both class hooks have to be in the markup for that to be true.
      sticky: s.grid().indexOf('class="mx-who"') >= 0,
    };
    out.thirteenScroll = s.dom.root.innerHTML.indexOf('class="mx-scroll"') >= 0;
  }

  // ── claims carried over from the deposit-roster card this matrix replaced ──
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    // A chip carries the enabled state it was given, and the identity colour.
    out.chipState = s.chips("general").map(chipOf);
    // The per-project strip paints from the TEAM list only. Kylene holds two step rows and no
    // team row, so she must be absent: a per-project override is stored with no step attached,
    // and switching her on there would sign her up for approvals and replies too.
    out.perProject = { people: s.peopleFor("p1").map((x) => x.email),
                       copy: s.dom.root.innerHTML };
    // Each toggle targets its OWN row. Ids come out of freshly generated HTML and the handlers are
    // re-wired on every paint, so a data-id on the wrong chip is a silent cross-wire.
    s.chips("general").filter((c) => c.email.indexOf("hanz") === 0)[0].click();
    await tick(); await tick();
    const first = s.calls.filter((c) => c.method === "PATCH").pop();
    s.chips("general").filter((c) => c.email.indexOf("will") === 0)[0].click();
    await tick(); await tick();
    const second = s.calls.filter((c) => c.method === "PATCH").pop();
    out.ownRow = { first: first, second: second,
                   chips: s.chips("general").map(chipOf),
                   // A roster change repaints the per-project card, because the effective
                   // per-project states move with the floor.
                   projectRenders: s.projectRenders };
  }
  {
    // Enter in the add field is the same path as its button.
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.type("general", "enter@wetreadwell.com");
    s.dom[s.group("general").input].fire("keydown", { key: "Enter", preventDefault() {} });
    await tick(); await tick();
    out.addByEnter = s.calls.filter((c) => c.method === "POST").pop();
  }
  {
    // An empty field asks for an address and sends nothing.
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.clickAdd("general");
    await tick();
    out.addEmpty = { posts: s.calls.filter((c) => c.method === "POST").length,
                     alert: s.alertText("general"), mx: s.mxAlertText() };
  }
  {
    // A failed add reports on the card it was typed into, and leaves the button usable.
    const s = build({ rows: MIXED, failOn: "POST" });
    s.render();
    await s.load();
    s.type("general", "nope@wetreadwell.com");
    s.clickAdd("general");
    await tick(); await tick();
    out.addFails = { alert: s.alertText("general"), mx: s.mxAlertText(),
                     btnLabel: s.dom[s.group("general").btn].textContent,
                     btnDisabled: s.dom[s.group("general").btn].disabled };
  }
  {
    // Declining the remove dialog sends nothing at all.
    const s = build({ rows: MIXED, confirm: false });
    s.render();
    await s.load();
    s.chips("general")[0].x.click();
    await tick(); await tick();
    out.declined = { deletes: s.calls.filter((c) => c.method === "DELETE").length,
                     chips: s.chips("general").map((c) => c.email) };
  }

  {
    // A DORMANT legacy 'deposit' row: no cells, and she does not vanish either.
    const s = build({ rows: LEGACY_OFF });
    s.render();
    await s.load();
    out.legacyOff = {
      cells: s.cells(),
      chips: s.chips("general").map((c) => c.email),
      people: s.mxPeople().map((p) => p.email),
      submitted: cellOf(s.cellAt("kylene@wetreadwell.com", "deposit_submitted")),
      received: cellOf(s.cellAt("kylene@wetreadwell.com", "deposit_received")),
      // The columns must not count her either, which is the resolver's answer too.
      column: s.mxColumn("deposit_received"),
    };
    // And a click on one of those grey cells opts her in for real.
    s.cellAt("kylene@wetreadwell.com", "deposit_received").click();
    await tick(); await tick();
    out.legacyOffClick = {
      put: s.calls.filter((c) => c.method === "PUT").pop(),
      cell: cellOf(s.cellAt("kylene@wetreadwell.com", "deposit_received")),
    };
  }
  {
    // The column that may not be emptied says so, on the column, before anybody tries.
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    out.required = {
      heads: heads(s.grid()).map((h) => ({ label: h.label, req: h.req, warn: h.warn })),
      copy: s.dom.root.innerHTML.indexOf("One column cannot be emptied") >= 0,
    };
  }
  {
    // The server refuses the click. The page has to say why, in words, and snap the cell back.
    const s = build({ rows: MIXED, refuse: true });
    s.render();
    await s.load();
    const before = cellOf(s.cellAt("hanz@wetreadwell.com", "sent"));
    s.cellAt("hanz@wetreadwell.com", "sent").click();
    await tick(); await tick();
    out.refused = {
      before: before,
      after: cellOf(s.cellAt("hanz@wetreadwell.com", "sent")),
      alert: s.mxAlertText(),
      cells: s.cells(),
      groupAlert: s.alertText("general"),
    };
  }

  console.log(JSON.stringify(out));
})().catch((e) => {
  console.error((e && e.stack) || String(e));
  process.exit(1);
});
