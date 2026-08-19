"use strict";
/* Run the Notification Sending page's ROSTER half for real — both groups — out of
 * frontend/js/notifications.js.
 *
 * WHY EXECUTED, NOT GREPPED. The claims are all about what the page does with a kind, and every
 * one of them is invisible to a source read:
 *
 *   * "Both groups paint, and a deposit row is in the deposit group and NOT in the team group."
 *     A grep proves the word "deposit" appears. Only running load() over a mixed roster proves
 *     the rows were split by it — and the bug being fixed here was a page that dropped one kind
 *     on the floor while looking perfectly reasonable.
 *   * "Adding from the deposit field sends kind: deposit." The proxy DEFAULTS a missing kind to
 *     general, so a dropped or transposed field creates the wrong sort of row and reports success.
 *     Only the request body says which.
 *   * "A toggle targets its own row." Ids come out of freshly generated HTML and the handlers are
 *     re-wired on every paint; `data-id` on the wrong chip is a silent cross-wire.
 *   * "The same address on both lists renders once per group and each × removes only its row."
 *     That is two rows with two ids, and the only way to see it is to click one and look at what
 *     survives.
 *
 * The api stub keeps a real little store, so a DELETE is followed by the page's own reload and the
 * harness can report what is STILL on screen — which is the actual worry ("did I just remove them
 * from both?"), not the request in isolation.
 *
 * Usage: node deposit-roster-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);

// CRLF normalised on read: git hands these files out with CRLF on a Windows checkout and every
// `^  const …$` pattern below would find a trailing \r and miss. (notify-tabs-harness.js carries
// the same note — CI checks out LF and stays green either way.)
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const src = read(path.join(ROOT, "js", "notifications.js"));
const C = require(path.join(ROOT, "js", "crm-core.js"));

/** Lift a named function out of the page's IIFE (two-space indent), braces balanced. `async`
 *  included — load/toggle/addEmail/removeOne are all async, and dropping the keyword would turn
 *  an awaited fetch into a synchronous call that throws. */
function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from notifications.js — rewrite this harness, don't stub it");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name + "()");
}

/** Lift a top-level `const`/`let` declaration, however many lines and brackets it spans — GROUPS
 *  is an array of two objects and must come from the PAGE, since its copy and its ids are half of
 *  what is being tested. Reads to the first `;` outside any bracket. */
function decl(name) {
  const m = new RegExp("\\n  (?:const|let) " + name + "\\b").exec(src);
  if (!m) throw new Error(name + " is gone from notifications.js — rewrite this harness");
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
 *  innerHTML and then queries the result, so the objects the click handlers receive have to come
 *  from that string — a hand-built fixture could agree with the handler and disagree with what
 *  renders. */
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
      /** A real × click BUBBLES to the chip, and the chip's own handler guards on
       *  `e.target.classList.contains("x")` while the × calls stopPropagation(). Modelled rather
       *  than short-circuited: with either guard missing, removing somebody would also toggle
       *  them, and a harness that fired only the × listener could not see it. */
      click() {
        const ev = { stopped: false, stopPropagation() { this.stopped = true; },
                     target: { classList: { contains: (c) => c === "x" } } };
        (this.listeners.click || []).forEach((f) => f(ev));
        if (!ev.stopped) node._fire("click", ev);
      },
    } : null;
    node.querySelector = (sel) => (sel === ".x" ? node.x
      : sel === ".em" ? { textContent: node.email } : null);
    // A click on the chip body: the target is the chip, which carries no "x" class.
    node.click = () => node._fire("click", { target: { classList: { contains: () => false } } });
    out.push(node);
  }
  return out;
}

/** A chips wrapper: innerHTML in, queryable chips out, cache dropped the moment it is replaced —
 *  exactly like a real re-render, so a handler attached to a node is the node that gets clicked. */
function chipsNode() {
  let html = "", cache = null;
  return {
    get innerHTML() { return html; },
    set innerHTML(v) { html = String(v); cache = null; },
    querySelectorAll(sel) {
      if (sel !== ".chip") return [];
      if (!cache) cache = parseChips(html);
      return cache;
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

/** Every id the page reaches for. Supplied by hand — which is exactly why the report also carries
 *  the ids render() actually WROTE, so a group whose markup never made it onto the page cannot
 *  pass by resolving here. */
function makeDom(groups) {
  const nodes = {
    root: (function () {
      let html = "";
      return { get innerHTML() { return html; }, set innerHTML(v) { html = String(v); } };
    })(),
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
    nodes[g.chips] = chipsNode();
    nodes[g.input] = control({ value: "" });
    nodes[g.btn] = control({ disabled: false, textContent: "Add" });
    nodes[g.alert] = { className: "", textContent: "" };
  });
  return nodes;
}

// ── the page's roster half, wired to a store that answers like the API ────────
const SOURCE = [
  decl("ROSTER"), decl("DEPOSIT_EXTRAS"), decl("GROUPS"), decl("kindOf"), decl("listFor"),
  decl("onList"), fn("alertOf"), fn("rosterCardHtml"), fn("render"), fn("paintGroup"),
  fn("load"), fn("toggle"), fn("addEmail"), fn("removeOne"), fn("peopleFor"),
].join("\n");

/** Build a live scope over the real functions, sharing one set of module vars.
 *
 *  The per-project half is INJECTED, not lifted: render() wires those controls too, and
 *  notify-tabs-harness.js already runs them for real. Stubbing them here keeps this harness
 *  about the rosters while still exercising the whole of render(). */
function build(opts) {
  const o = opts || {};
  const rows = (o.rows || []).map((r) => Object.assign({}, r));
  const calls = [];
  const dialogs = [];
  let nextId = 100;
  let failOn = o.failOn || null;                     // e.g. "POST" → that verb rejects

  const api = (p, init) => {
    const method = (init || {}).method || "GET";
    const body = (init || {}).body ? JSON.parse(init.body) : null;
    calls.push({ path: p, method, body });
    if (failOn === method || (method === "GET" && o.loadFails)) {
      return Promise.resolve({ ok: false, status: 500,
                               json: () => Promise.resolve({ error: "boom" }) });
    }
    if (method === "GET") {
      return Promise.resolve({ ok: true,
        json: () => Promise.resolve({ ok: true, recipients: rows.map((r) => Object.assign({}, r)) }) });
    }
    // The store, so the page's own reload after a mutation shows what really survived.
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
  const admin = o.admin !== false;
  const scope = new Function(
    "$", "esc", "avatar", "nameOf", "api", "TW", "ADMIN", "renderProjects", "OVERRIDES",
    "PP_TABS", "PP_IDS", "PP_TAB", "PP_TAB_KEY", "ssSet", "ppGoto",
    '"use strict";\n' + SOURCE + "\n" +
    "return { render, load, paintGroup, peopleFor, GROUPS, kindOf, onList,\n" +
    "         roster: () => ROSTER, deposits: () => DEPOSIT_EXTRAS };");

  let dom = null;
  const s = scope(
    (id) => (dom ? dom[id] : null) || null,
    esc, C.avatarHtml, C.nameOf, api, TW, admin,
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
  s.pressEnter = (kind) => dom[s.group(kind).input].fire("keydown",
    { key: "Enter", preventDefault() {} });
  s.setFail = (verb) => { failOn = verb; };
  return s;
}

/** What a chip actually says, which is what the reader gets. */
const chipOf = (c) => ({
  id: c.dataset.id, kind: c.dataset.kind, email: c.email, on: /\bon\b/.test(c.className),
  also: c.also, removable: !!c.x, coloured: !!c.avatarHtml,
});
const chipsOf = (s, kind) => s.chips(kind).map(chipOf);
const tick = () => new Promise((r) => setTimeout(r, 0));

// ── fixtures ────────────────────────────────────────────────────────────────
// The production shape as of 2026-08-19: two general rows, one of them off, plus kylene@ as an
// enabled DEPOSIT row — the row that was live and invisible, which is why this card exists.
const MIXED = [
  { id: 1, email: "hanz@wetreadwell.com", kind: "general", enabled: true },
  { id: 2, email: "kyle.loseke@wetreadwell.com", kind: "general", enabled: false },
  { id: 3, email: "kylene@wetreadwell.com", kind: "deposit", enabled: true },
];
// The same address on BOTH lists: legal (the row key is kind + email) and it means "everything,
// deposits included". Two rows, two ids.
const BOTH = [
  { id: 1, email: "hanz@wetreadwell.com", kind: "general", enabled: true },
  { id: 9, email: "hanz@wetreadwell.com", kind: "deposit", enabled: true },
  { id: 2, email: "kyle.loseke@wetreadwell.com", kind: "general", enabled: true },
];

const out = {};

(async () => {
  // ── both cards render, out of the page's own render() ───────────────────────
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
      kind: g.kind, other: g.other, chips: g.chips, input: g.input, btn: g.btn, alert: g.alert,
      lbl: g.lbl, intro: g.intro, empty: g.empty, what: g.what, also: g.also,
      addLbl: g.addLbl, removeTitle: g.removeTitle, removeBefore: g.removeBefore,
      removeAlso: g.removeAlso,
    }));

    // ── the split, run for real ───────────────────────────────────────────────
    await s.load();
    out.mixed = {
      general: chipsOf(s, "general"),
      deposit: chipsOf(s, "deposit"),
      roster: s.roster(),
      deposits: s.deposits(),
      // The per-project strip's people, from the page's own peopleFor().
      peopleFor: s.peopleFor("p1").map((p) => p.email),
      getCalls: s.calls.filter((c) => c.method === "GET").length,
    };
  }

  // ── a non-admin sees both lists and can change neither ─────────────────────
  {
    const s = build({ rows: MIXED, admin: false });
    s.render();
    await s.load();
    out.staff = {
      html: s.dom.root.innerHTML,
      general: chipsOf(s, "general"),
      deposit: chipsOf(s, "deposit"),
      generalListeners: s.chips("general").map((c) => Object.keys(c.listeners).length),
    };
  }

  // ── a toggle on a deposit row hits the same endpoint as a general one ───────
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    const kyle = s.chips("general").filter((c) => c.email.indexOf("kyle") === 0)[0];
    kyle.click();                                  // general, off → on
    await tick();
    out.generalToggle = s.calls.filter((c) => c.method === "PATCH").pop();
    const kylene = s.chips("deposit")[0];
    kylene.click();                                // deposit, on → off
    await tick();
    out.depositToggle = s.calls.filter((c) => c.method === "PATCH").pop();
    out.afterToggles = {
      general: chipsOf(s, "general"),
      deposit: chipsOf(s, "deposit"),
      patches: s.calls.filter((c) => c.method === "PATCH"),
      // The per-project card is repainted after a roster change, because the effective
      // per-project states move with the base.
      projectRenders: s.projectRenders,
    };
  }

  // ── adding, from each field ────────────────────────────────────────────────
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.type("deposit", "  Newdep@Wetreadwell.com ");
    s.clickAdd("deposit");
    await tick(); await tick();
    out.addDeposit = {
      post: s.calls.filter((c) => c.method === "POST").pop(),
      inputCleared: s.dom[s.group("deposit").input].value === "",
      alert: s.alertText("deposit"),
      otherAlert: s.alertText("general"),
      deposit: chipsOf(s, "deposit"),
      general: chipsOf(s, "general"),
      btnLabel: s.dom[s.group("deposit").btn].textContent,
      btnDisabled: s.dom[s.group("deposit").btn].disabled,
    };

    s.type("general", "newteam@wetreadwell.com");
    s.clickAdd("general");
    await tick(); await tick();
    out.addGeneral = {
      post: s.calls.filter((c) => c.method === "POST").pop(),
      alert: s.alertText("general"),
      general: chipsOf(s, "general"),
      deposit: chipsOf(s, "deposit"),
    };
  }

  // Enter in the deposit field is the same code path, and the field it was typed into is still
  // what decides the kind.
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.type("deposit", "enter@wetreadwell.com");
    s.pressEnter("deposit");
    await tick(); await tick();
    out.addByEnter = s.calls.filter((c) => c.method === "POST").pop();
  }

  // An empty field asks for an address on ITS OWN card and sends nothing.
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.clickAdd("deposit");
    await tick();
    out.addEmpty = { posts: s.calls.filter((c) => c.method === "POST").length,
                     deposit: s.alertText("deposit"), general: s.alertText("general") };
  }

  // A failed add reports on the card it was typed into, and nowhere else.
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.setFail("POST");
    s.type("deposit", "nope@wetreadwell.com");
    s.clickAdd("deposit");
    await tick(); await tick();
    out.addFails = { deposit: s.alertText("deposit"), general: s.alertText("general"),
                     btnLabel: s.dom[s.group("deposit").btn].textContent,
                     btnDisabled: s.dom[s.group("deposit").btn].disabled };
  }

  // ── the same address on both lists ─────────────────────────────────────────
  {
    const s = build({ rows: BOTH });
    s.render();
    await s.load();
    out.both = { general: chipsOf(s, "general"), deposit: chipsOf(s, "deposit") };

    // Remove the DEPOSIT row. The dialog has to say the other one stays, and the reload has to
    // show that it did.
    const dep = s.chips("deposit")[0];
    dep.x.click();
    await tick(); await tick();
    out.bothRemoveDeposit = {
      dialog: s.dialogs[s.dialogs.length - 1],
      deletes: s.calls.filter((c) => c.method === "DELETE"),
      general: chipsOf(s, "general"),
      deposit: chipsOf(s, "deposit"),
      depositHtml: s.chipsHtml("deposit"),
      // The chip click must NOT have fired as well, or removing somebody also toggles them.
      patches: s.calls.filter((c) => c.method === "PATCH").length,
    };
  }
  {
    // And the other direction: removing the TEAM row leaves the deposit row standing.
    const s = build({ rows: BOTH });
    s.render();
    await s.load();
    const gen = s.chips("general").filter((c) => c.email.indexOf("hanz") === 0)[0];
    gen.x.click();
    await tick(); await tick();
    out.bothRemoveGeneral = {
      dialog: s.dialogs[s.dialogs.length - 1],
      deletes: s.calls.filter((c) => c.method === "DELETE"),
      general: chipsOf(s, "general"),
      deposit: chipsOf(s, "deposit"),
    };
  }
  {
    // Declining the dialog sends nothing at all.
    const s = build({ rows: BOTH, confirm: false });
    s.render();
    await s.load();
    s.chips("deposit")[0].x.click();
    await tick(); await tick();
    out.declined = { deletes: s.calls.filter((c) => c.method === "DELETE").length,
                     deposit: chipsOf(s, "deposit") };
  }

  // Removing somebody who is on ONE list only gets the plain question, not the reassurance.
  {
    const s = build({ rows: MIXED });
    s.render();
    await s.load();
    s.chips("deposit")[0].x.click();
    await tick(); await tick();
    out.removeOnlyRow = { dialog: s.dialogs[s.dialogs.length - 1],
                          deposit: chipsOf(s, "deposit"),
                          depositHtml: s.chipsHtml("deposit"),
                          general: chipsOf(s, "general") };
  }

  // ── the empty states ───────────────────────────────────────────────────────
  {
    const s = build({ rows: MIXED.filter((r) => r.kind !== "deposit") });
    s.render();
    await s.load();
    out.emptyDeposit = { deposit: s.chipsHtml("deposit"), general: chipsOf(s, "general"),
                         chips: chipsOf(s, "deposit").length };

    const t = build({ rows: [] });
    t.render();
    await t.load();
    out.emptyBoth = { deposit: t.chipsHtml("deposit"), general: t.chipsHtml("general") };

    const n = build({ rows: MIXED.filter((r) => r.kind !== "deposit"), admin: false });
    n.render();
    await n.load();
    out.emptyDepositStaff = n.chipsHtml("deposit");
  }

  // ── a row whose kind the page does not recognise ───────────────────────────
  // The portal's own resolver buckets anything that is not "deposit" as general, and a row this
  // page silently dropped is the whole bug. So: visible, on the team card.
  {
    const s = build({ rows: [
      { id: 1, email: "nokind@wetreadwell.com", enabled: true },
      { id: 2, email: "future@wetreadwell.com", kind: "invoice", enabled: true },
      { id: 3, email: "kylene@wetreadwell.com", kind: "deposit", enabled: true },
    ] });
    s.render();
    await s.load();
    out.unknownKind = { general: chipsOf(s, "general").map((c) => c.email),
                        deposit: chipsOf(s, "deposit").map((c) => c.email) };
  }

  // ── one failed fetch must not look like half a working page ────────────────
  {
    const s = build({ rows: MIXED, loadFails: true });
    s.render();
    await s.load();
    out.loadFails = { general: s.chipsHtml("general"), deposit: s.chipsHtml("deposit") };
  }

  console.log(JSON.stringify(out));
})().catch((e) => {
  console.error(e && e.stack || String(e));
  process.exit(1);
});
