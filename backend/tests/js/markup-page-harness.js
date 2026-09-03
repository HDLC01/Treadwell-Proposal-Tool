"use strict";
/* RUN the Markup page — frontend/js/markup.js, the whole IIFE — and report the nodes it produced.
 *
 * WHY EXECUTED, NOT GREPPED. A source assertion cannot catch an unbound identifier, and that is
 * not hypothetical here: on 2026-08-12 the CRM board went down on production with
 * `ReferenceError: STAGE_CREATED is not defined` while every test was green, because every test
 * read the renderer's TEXT and none of them ran it. So this file executes markup.js with only the
 * names the page itself binds in scope, against a DOM stub, and reports the DOM that came out.
 *
 * WHAT IS REAL. markup-core.js (required, not stubbed) — the preview figures below are the real
 * engine's, so nothing here can pass against a stand-in that disagrees with what prices a bid.
 * markup.html too: the element ids the stub answers to are read OUT OF THE PAGE, so a renderer
 * reaching for an id the markup does not declare throws instead of quietly writing to nothing.
 *
 * DELIBERATELY NOT jsdom, for the reason board-render-harness.js and doc-editor-harness.js give:
 * a full DOM lets a missing import hide behind a global. The tree below is parsed back out of the
 * page's OWN innerHTML, so every assertion is against nodes markup.js actually built.
 *
 * THE THREE ROW STATES ARE THE POINT. backend/markup.py exists to keep `applies=false` ("this
 * line does not exist on this tab" — Gyp's hard-bid cell is EMPTY) apart from `formula='0'` ("it
 * exists and prices to nothing"), and this harness renders both on one page so a collapse of the
 * two fails here rather than on a bid.
 *
 * Usage: node markup-page-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
// Line endings normalised on read: git hands these files out with CRLF on a Windows checkout and
// LF in CI, and library-ui-harness.js records what that costs a source-matching harness.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const SRC = read(path.join(ROOT, "js", "markup.js"));
const PAGE = read(path.join(ROOT, "markup.html"));
const CORE = require(path.join(ROOT, "js", "markup-core.js"));

// The ids markup.html actually declares. The stub answers to these and no others, so
// `$("mk-brokn")` is a thrown TypeError here instead of a note that never appears in production.
const PAGE_IDS = new Set(
  [...PAGE.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1])
);

// ── a very small HTML reader ─────────────────────────────────────────────────
// Enough to walk what the page renders, with parent links so closest() is real.
// Genuinely void elements only. `path` and `circle` are NOT here: icon() writes them with real
// closing tags, and treating them as void made every `</circle>` pop the svg's parent instead —
// which silently slid the row's cells one column left and made the assertions read the wrong cell.
const VOID = new Set(["input", "br", "img", "hr", "meta", "link"]);
const ENT = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'",
              "&mdash;": "—", "&nbsp;": " " };
const unesc = (s) =>
  String(s).replace(/&(?:amp|lt|gt|quot|#39|mdash|nbsp);/g, (m) => ENT[m]);

function attrsOf(raw) {
  const out = {};
  for (const m of raw.matchAll(/([\w:-]+)(?:="([^"]*)")?/g)) {
    if (!m[1]) continue;
    out[m[1]] = m[2] === undefined ? "" : unesc(m[2]);
  }
  return out;
}

function node(tag, attrs) {
  const n = {
    tag, attrs: attrs || {}, children: [], parent: null,
    get className() { return this.attrs.class || ""; },
    get classes() { return this.className.split(/\s+/).filter(Boolean); },
    hasClass(c) { return this.classes.includes(c); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    get hidden() { return Object.prototype.hasOwnProperty.call(this.attrs, "hidden"); },
    set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; },
    classList: {
      add(c) { const s = new Set(n.classes); s.add(c); n.attrs.class = [...s].join(" "); },
      remove(c) { n.attrs.class = n.classes.filter((x) => x !== c).join(" "); },
      contains(c) { return n.hasClass(c); },
    },
    /** The element's own text, entities decoded, whitespace collapsed. The decode matters: the
     *  absent and downstream previews render an `&mdash;`, and a test looking for "no figure"
     *  has to see the same character a reader would. */
    get text() {
      let out = "";
      const walk = (x) => {
        if (typeof x === "string") { out += unesc(x); return; }
        x.children.forEach(walk);
      };
      this.children.forEach(walk);
      return out.replace(/\s+/g, " ").trim();
    },
    get value() { return this.attrs.value === undefined ? "" : this.attrs.value; },
    set value(v) { this.attrs.value = String(v); },
    /** Only the two selector shapes markup.js's handlers use. Anything else is a harness bug and
     *  says so rather than silently matching nothing. */
    closest(sel) {
      const attr = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(sel);
      const id = /^#([\w-]+)$/.exec(sel);
      if (!attr && !id) throw new Error("harness closest() cannot read selector " + sel);
      let cur = this;
      while (cur) {
        if (id && cur.attrs.id === id[1]) return cur;
        if (attr && Object.prototype.hasOwnProperty.call(cur.attrs, attr[1]) &&
            (attr[2] === undefined || cur.attrs[attr[1]] === attr[2])) return cur;
        cur = cur.parent;
      }
      return null;
    },
    focus() { DOC.activeElement = this; },
    setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; },
  };
  n.selectionStart = null;
  n.selectionEnd = null;
  return n;
}

function parse(html) {
  const root = node("#root", {});
  let cur = root;
  const re = /<\/?([a-zA-Z][\w:-]*)((?:"[^"]*"|[^>])*?)(\/?)>/g;
  let last = 0;
  let m;
  while ((m = re.exec(html))) {
    if (m.index > last) {
      const txt = html.slice(last, m.index);
      if (txt.trim() || /\s/.test(txt)) cur.children.push(txt);
    }
    last = re.lastIndex;
    const tag = m[1].toLowerCase();
    if (m[0][1] === "/") {
      // Close to the NEAREST matching ancestor rather than blindly popping one level, so an
      // unbalanced tag cannot quietly re-parent the rest of the table.
      let up = cur;
      while (up && up.tag !== tag) up = up.parent;
      cur = up && up.parent ? up.parent : cur;
      continue;
    }
    const el = node(tag, attrsOf(m[2]));
    el.parent = cur;
    cur.children.push(el);
    if (!VOID.has(tag) && !m[3]) cur = el;
  }
  if (html.length > last) {
    const txt = html.slice(last);
    if (txt) cur.children.push(txt);
  }
  return root;
}

function all(root, pred) {
  const out = [];
  const walk = (x) => {
    if (typeof x === "string") return;
    if (pred(x)) out.push(x);
    x.children.forEach(walk);
  };
  walk(root);
  return out;
}
const byClass = (root, c) => all(root, (n) => n.hasClass(c));
const byTag = (root, t) => all(root, (n) => n.tag === t);
const byAttr = (root, a, v) =>
  all(root, (n) => Object.prototype.hasOwnProperty.call(n.attrs, a) &&
                   (v === undefined || n.attrs[a] === v));

// ── the DOM stub ─────────────────────────────────────────────────────────────
let DOC = null;

function makeDoc() {
  const nodes = {};
  const containers = {};

  const mk = (id) => {
    const el = {
      id, _html: "", textContent: "", _hidden: false, tree: parse(""),
      listeners: {},
      addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); },
      setAttribute(k, v) { (this.attrs = this.attrs || {})[k] = v; },
      getAttribute(k) { return (this.attrs || {})[k] || null; },
      get hidden() { return this._hidden; },
      set hidden(v) { this._hidden = !!v; },
      get innerHTML() { return this._html; },
      set innerHTML(v) { this._html = String(v); this.tree = parse(this._html); },
      fire(k, target) { (this.listeners[k] || []).forEach((f) => f({ target })); },
    };
    containers[id] = el;
    return el;
  };

  const doc = {
    activeElement: null,
    getElementById(id) {
      if (!PAGE_IDS.has(id)) {
        throw new Error("markup.js asked for #" + id + ", which markup.html does not declare");
      }
      return (nodes[id] = nodes[id] || mk(id));
    },
    /** Searched across every container the page has painted, newest tree each time — which is
     *  what makes the focus-restore assertion honest: the node handed back is the one the LAST
     *  render built, not the one that was focused before it. */
    querySelector(sel) {
      const attr = /^\[([\w-]+)="([^"]*)"\]$/.exec(sel);
      if (!attr) throw new Error("harness querySelector() cannot read " + sel);
      for (const id of Object.keys(containers)) {
        const hit = byAttr(containers[id].tree, attr[1], attr[2]);
        if (hit.length) return hit[0];
      }
      return null;
    },
    containers,
  };
  DOC = doc;
  return doc;
}

// ── the run ──────────────────────────────────────────────────────────────────
const LAYOUTS = ["polish", "seal", "epoxy", "leveling", "gyp"];
const LINE_KEYS = ["gp", "hard_bid", "super_pto", "soft_costs", "bond"];

const tick = () => new Promise((r) => setImmediate(r));
const drain = async () => { for (let i = 0; i < 16; i++) await tick(); };

function rule(layout, line_key, extra) {
  return Object.assign({
    id: layout + "-" + line_key, layout, line_key,
    formula: "16%", applies: true, notes: "", sort: 0,
    owner_email: "hanz@wetreadwell.com", created_at: null, updated_at: null,
  }, extra || {});
}

function build(opts) {
  const o = opts || {};
  const doc = makeDoc();
  const requests = [];
  const confirms = [];

  const fetchStub = async (url, init) => {
    const u = String(url);
    const method = ((init || {}).method || "GET").toUpperCase();
    requests.push({ method, url: u, body: (init || {}).body ? JSON.parse(init.body) : null });
    if (method === "GET") {
      if (o.listStatus && o.listStatus !== 200) {
        return { ok: false, status: o.listStatus, json: async () => ({ detail: "nope" }) };
      }
      return {
        ok: true, status: 200,
        json: async () => ({ ok: true, rules: (o.rules || []).map((r) => Object.assign({}, r)),
                             layouts: o.layouts || LAYOUTS, line_keys: o.line_keys || LINE_KEYS }),
      };
    }
    if (method === "PUT") {
      const status = o.putStatus || 200;
      const body = JSON.parse(init.body);
      if (status !== 200) {
        return { ok: false, status, json: async () => ({ detail: o.putDetail || "refused" }) };
      }
      return { ok: true, status: 200,
               json: async () => ({ ok: true, rule: rule(body.layout, body.line_key, {
                 formula: body.applies ? body.formula : null,
                 applies: body.applies !== false, notes: body.notes || "" }) }) };
    }
    if (method === "DELETE") {
      const status = o.deleteStatus || 200;
      return { ok: status === 200, status,
               json: async () => ({ ok: status === 200, deleted: "x" }) };
    }
    throw new Error("unexpected " + method + " " + u);
  };

  const TW = {
    resolveApiBase: () => "",
    authHeaders: (h) => Object.assign({}, h || {}),
    confirmDanger: async (opt) => { confirms.push(opt); return o.confirm !== false; },
  };

  const win = {
    TWMarkup: CORE,
    TWAuth: {
      ready: Promise.resolve(),
      user: () => ({ role: o.role === undefined ? "admin" : o.role }),
    },
  };

  const run = new Function("window", "document", "TW", "fetch", "console", SRC);
  run(win, doc, TW, fetchStub, console);

  const chain = () => doc.containers["mk-chain"];
  const tabs = () => doc.containers["mk-tabs"];

  /** One row's whole rendered shape — every assertion in test_markup_page.py reads this. */
  const rowSnap = (r) => {
    const cells = r.children.filter((c) => typeof c !== "string");
    const formula = cells[1], applies = cells[2], explain = cells[3], prev = cells[4];
    return {
      line: r.getAttribute("data-row"),
      absentClass: r.hasClass("absent"),
      label: cells[0] ? cells[0].text : "",
      // The formula cell, in full: what it says, whether it is an editable box, and the caption.
      formulaText: formula ? formula.text : "",
      inputs: formula ? byTag(formula, "input").map((i) => ({
        value: i.value, placeholder: i.attrs.placeholder || "",
        cls: i.className, focusKey: i.attrs["data-focus"] || "",
        ariaLabel: i.attrs["aria-label"] || "",
      })) : [],
      errmsg: formula ? byClass(formula, "errmsg").map((e) => ({ text: e.text, hidden: e.hidden })) : [],
      buttons: formula ? byTag(formula, "button").map((b) => ({
        text: b.text, drop: b.attrs["data-drop"] || "", type: b.attrs.type || "" })) : [],
      appliesText: applies ? applies.text : "",
      switches: applies ? byAttr(applies, "role", "switch").map((s) => ({
        tag: s.tag, type: s.attrs.type || "", checked: s.attrs["aria-checked"],
        tabindex: s.attrs.tabindex === undefined ? null : s.attrs.tabindex,
        ariaLabel: s.attrs["aria-label"] || "", focusKey: s.attrs["data-focus"] || "",
      })) : [],
      explain: explain ? explain.text : "",
      preview: prev ? prev.text : "",
      previewClasses: prev ? prev.children.filter((c) => typeof c !== "string")
        .map((c) => c.className) : [],
    };
  };

  const snap = () => {
    const t = chain().tree;
    const rows = byClass(t, "mkrow").filter((r) => r.getAttribute("data-row"));
    const grand = byClass(t, "grand")[0] || null;
    return {
      tabs: byTag(tabs().tree, "button").map((b) => ({
        layout: b.attrs["data-layout"], label: b.text, selected: b.attrs["aria-selected"],
        role: b.attrs.role, type: b.attrs.type || "",
      })),
      rows: rows.map(rowSnap),
      rowOrder: rows.map((r) => r.getAttribute("data-row")),
      grand: grand ? { explain: byClass(grand, "explain").map((e) => e.text)[0] || "",
                       preview: byClass(grand, "prev").map((p) => p.text)[0] || "",
                       classes: byClass(grand, "prev").length
                         ? byClass(grand, "prev")[0].children.filter((c) => typeof c !== "string")
                             .map((c) => c.className) : [] } : null,
      // Everything the chain rendered, as text — used to prove a $0.00 never appears where a
      // line could not be priced.
      chainText: byClass(t, "mkrow").map((r) => r.text).join(" | "),
      inputCount: byTag(t, "input").length,
      switchCount: byAttr(t, "role", "switch").length,
      buttonCount: byTag(t, "button").length,
      stateText: byClass(t, "state").map((s) => s.text).join(" "),
      retry: !!byAttr(t, "id", "mk-retry").length,
      // Read through getElementById, not the container map: an id the page has not touched yet
      // should read as its empty starting state, not blow the harness up.
      ro: { hidden: doc.getElementById("mk-ro").hidden },
      fallback: { hidden: doc.getElementById("mk-fallback").hidden,
                  text: doc.getElementById("mk-fallback").textContent },
      broken: { hidden: doc.getElementById("mk-broken").hidden,
                line: doc.getElementById("mk-broken-line").textContent,
                rest: doc.getElementById("mk-broken-rest").textContent },
      alert: doc.getElementById("alert").textContent,
      foot: doc.getElementById("mk-foot").textContent,
    };
  };

  const find = (sel) => doc.querySelector(sel);
  const byId = (id) => {
    for (const c of Object.keys(doc.containers)) {
      const hit = byAttr(doc.containers[c].tree, "id", id);
      if (hit.length) return hit[0];
    }
    return null;
  };
  const clickTab = (layout) => tabs().fire("click", find('[data-focus="tab-' + layout + '"]'));
  const clickIn = (focusKey, type) => chain().fire(type || "click", find('[data-focus="' + focusKey + '"]'));

  return { doc, requests, confirms, snap, find, byId, clickTab, clickIn, chain, tabs };
}

async function main() {
  const out = {};

  // ═══ 1. day one on Polish: nothing filed, every line on its built-in ══════
  {
    const s = build({ rules: [] });
    await drain();
    out.dayOnePolish = s.snap();
    out.dayOneRequests = s.requests.map((r) => r.method + " " + r.url);
  }

  // ═══ 2. the poisoned vocabulary: a `combo` the API must never be able to
  //        put on screen, and a line_key CHAIN has never heard of ════════════
  {
    const s = build({ layouts: ["polish", "combo", "seal", "epoxy", "leveling", "gyp"],
                      line_keys: LINE_KEYS.concat(["escalation"]) });
    await drain();
    out.poisoned = s.snap();
  }

  // ═══ 3. Gyp: hard_bid ABSENT (the built-in default) beside a genuine ZERO
  //        filed on bond. The two states on one screen, which is the whole
  //        reason markup.py stores them differently. ═══════════════════════
  {
    const s = build({ rules: [rule("gyp", "bond", { formula: "0", applies: true }),
                              rule("gyp", "gp", { formula: "30%" })] });
    await drain();
    s.clickTab("gyp");
    await drain();
    out.gyp = s.snap();
  }

  // ═══ 4. an ABSENT row filed explicitly (applies=false, formula null) ══════
  {
    const s = build({ rules: [rule("polish", "hard_bid", { applies: false, formula: null })] });
    await drain();
    out.filedAbsent = s.snap();

    // AND THE WAY BACK MUST ACTUALLY WORK FROM HERE. An off row has no box to type in, so this
    // button is its only exit -- one that painted and did nothing would be a worse corner than no
    // button at all. Clicked for real, through the page's own delegated [data-drop] handler.
    s.clickIn("d-hard_bid");
    await drain();
    out.filedAbsentDrop = { confirm: s.confirms[0] || null,
                            deletes: s.requests.filter((r) => r.method === "DELETE")
                              .map((r) => r.url),
                            after: s.snap() };
  }

  // ═══ 5. an invalid formula: the cascade, and never a $0.00 ════════════════
  {
    const s = build({ rules: [rule("polish", "hard_bid",
      { formula: "IF(hard_bid_on, ROUNDUP((subtoal+gp)*-4%), 0" })] });
    await drain();
    out.invalid = s.snap();
  }

  // ═══ 6. a formula that PARSES and evaluates to Kyle's "error" sentinel ════
  //        A string is not a number, so it is unpriceable — not zero.
  {
    const s = build({ rules: [rule("polish", "soft_costs", { formula: '"error"' })] });
    await drain();
    out.sentinel = s.snap();
  }

  // ═══ 7. a non-admin ══════════════════════════════════════════════════════
  {
    const s = build({ role: "estimator",
                      rules: [rule("polish", "soft_costs", { formula: "16%" }),
                              rule("gyp", "hard_bid", { applies: false, formula: null })] });
    await drain();
    out.nonAdminPolish = s.snap();
    s.clickTab("gyp");
    await drain();
    out.nonAdminGyp = s.snap();
    out.nonAdminRequests = s.requests.map((r) => r.method);
  }

  // ═══ 8. typing is not scolded; blur is where it is judged ════════════════
  {
    const s = build({ rules: [] });
    await drain();
    const box = s.find('[data-focus="f-soft_costs"]');
    box.value = "16";                                  // mid-word
    s.chain().fire("input", box);
    out.midWord = { errmsg: s.snap().rows.find((r) => r.line === "soft_costs").errmsg,
                    puts: s.requests.filter((r) => r.method === "PUT").length };

    // …now leave the box with something unreadable.
    const bad = s.find('[data-focus="f-soft_costs"]');
    bad.value = "16% *";
    s.chain().fire("focusout", bad);
    await drain();
    out.badOnBlur = s.snap();
    out.badOnBlurPuts = s.requests.filter((r) => r.method === "PUT").length;

    // …and again with a formula that reads.
    const good = s.find('[data-focus="f-soft_costs"]');
    good.value = "18%";
    s.chain().fire("focusout", good);
    await drain();
    out.goodOnBlur = s.snap();
    out.goodOnBlurBody = (s.requests.filter((r) => r.method === "PUT")[0] || {}).body || null;
  }

  // ═══ 9. the switch: off files applies=false with NO formula, and switching back ON
  //         with an empty box posts nothing the backend would have to refuse ════════
  {
    const s = build({ rules: [rule("polish", "soft_costs", { formula: "16%" })] });
    await drain();
    s.clickIn("a-soft_costs");
    await drain();
    out.switchedOff = s.snap();
    out.switchedOffBody = (s.requests.filter((r) => r.method === "PUT")[0] || {}).body || null;

    // …and back on. The row is now ABSENT with no formula stored, so there is nothing to run.
    s.clickIn("a-soft_costs");
    await drain();
    out.switchedBackOn = s.snap();
    out.switchOnEmpty = {
      puts: s.requests.filter((r) => r.method === "PUT").length,
      alert: s.snap().alert,
      focused: s.doc.activeElement ? s.doc.activeElement.getAttribute("data-focus") : null,
    };
  }

  // ═══ 10. focus survives a re-render ══════════════════════════════════════
  {
    const s = build({ rules: [rule("polish", "gp", { formula: "MARKUP(30%)" })] });
    await drain();
    const box = s.find('[data-focus="f-gp"]');
    box.focus();
    box.setSelectionRange(3, 5);
    const before = s.doc.activeElement;
    // A save on a DIFFERENT row repaints the whole table under the caret.
    s.clickIn("a-soft_costs");
    await drain();
    const after = s.doc.activeElement;
    out.focus = {
      beforeKey: before ? before.getAttribute("data-focus") : null,
      afterKey: after ? after.getAttribute("data-focus") : null,
      sameNode: before === after,
      selection: after ? [after.selectionStart, after.selectionEnd] : null,
    };
  }

  // ═══ 11. stop overriding: the wording, and the request ═══════════════════
  {
    const s = build({ rules: [rule("polish", "soft_costs", { formula: "16%" })] });
    await drain();
    s.clickIn("d-soft_costs");
    await drain();
    out.drop = { confirm: s.confirms[0] || null,
                 deletes: s.requests.filter((r) => r.method === "DELETE").map((r) => r.url),
                 after: s.snap() };

    const n = build({ rules: [rule("polish", "soft_costs", { formula: "16%" })], confirm: false });
    await drain();
    n.clickIn("d-soft_costs");
    await drain();
    out.dropCancelled = { deletes: n.requests.filter((r) => r.method === "DELETE").length };

    const g = build({ rules: [rule("polish", "soft_costs", { formula: "16%" })],
                      deleteStatus: 404 });
    await drain();
    g.clickIn("d-soft_costs");
    await drain();
    out.dropGone = { alert: g.snap().alert,
                     gets: g.requests.filter((r) => r.method === "GET").length };
  }

  // ═══ 12. a 403 from the server locks the page rather than lying ══════════
  {
    const s = build({ rules: [], putStatus: 403 });
    await drain();
    const box = s.find('[data-focus="f-soft_costs"]');
    box.value = "18%";
    s.chain().fire("focusout", box);
    await drain();
    out.forbidden = s.snap();
  }

  // ═══ 13. the list itself failing gets a designed state, not an empty box ═══════
  {
    const s = build({ listStatus: 500 });
    await drain();
    out.loadFailed = s.snap();
    const retry = s.byId("mk-retry");
    out.loadFailedRetry = !!retry;
    if (retry) {
      s.chain().fire("click", retry);
      await drain();
      out.loadFailedRetryGets = s.requests.filter((r) => r.method === "GET").length;
    }
  }

  console.log(JSON.stringify(out));
}

main().catch((e) => { console.error((e && e.stack) || String(e)); process.exit(1); });
