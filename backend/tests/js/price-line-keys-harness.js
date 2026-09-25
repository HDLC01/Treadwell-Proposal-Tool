"use strict";
/* A PRICE line's saved words and the lines typed around it follow THEIR line — RUN, not read.
 *
 * The Proposal step keys a price line's edited words (price_overrides.lines / .lines2) and the lines
 * the estimator typed above and below it (.before / .after) by the line: "option:<tab id>", that
 * option's own tax rows "option:<tab id>:sales_tax" / ":remodel" / ":total", or "manual:<i>" by
 * position. Both keys are reused on the Estimate step: a deleted copy's id goes to the next copy,
 * and removing a manual price line moves every later line up one. So this lifts the two places that
 * delete a line — deleteTab and the manual row's remove button inside renderPriceLines — out of
 * estimate-review.js verbatim and drives them against a draft, then reads the draft back.
 *
 * Usage: node price-line-keys-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(process.argv[2], "js", "estimate-review.js"), "utf8")
  .replace(/\r\n/g, "\n");

/** One top-level `function name(...) { ... }`, braces balanced. */
function lift(name) {
  const m = new RegExp("\\n(?:async )?function " + name + "\\s*\\(").exec(SRC);
  if (!m) throw new Error(name + "() is gone from estimate-review.js — rewrite this harness, don't stub it");
  const open = SRC.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(m.index + 1, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

// ── the few elements renderPriceLines builds ─────────────────────────────────
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.style = {};
                     this.dataset = {}; this._l = {}; this.value = ""; }
  appendChild(c) { this.children.push(c); return c; }
  set innerHTML(html) {
    this.children = [];
    for (const m of String(html).matchAll(/<(input|button)\b([^>]*)>/g)) {
      const el = new El(m[1]);
      for (const a of m[2].matchAll(/([\w-]+)="([^"]*)"/g)) {
        if (a[1].startsWith("data-")) el.dataset[a[1].slice(5)] = a[2];
        if (a[1] === "value") el.value = a[2];
      }
      this.children.push(el);
    }
  }
  querySelectorAll(sel) { return sel === "input" ? this.children.filter((c) => c.tagName === "INPUT") : []; }
  querySelector(sel) {
    const m = /^\[data-act="(\w+)"\]$/.exec(sel);
    return m ? this.children.find((c) => c.dataset.act === m[1]) || null : null;
  }
  addEventListener(type, f) { (this._l[type] = this._l[type] || []).push(f); }
  fire(type) { (this._l[type] || []).forEach((f) => f({ target: this })); }
}

function draft() {
  return {
    tab_copies: [{ id: "Copy1" }, { id: "Copy10" }], tab_labels: {}, tab_notes: {}, tab_opts: {},
    lock_overrides: {}, base_tab_id: null,
    price_lines: [{ label: "Mockup", amount: 100 }, { label: "Night work", amount: 200 },
                  { label: "Extra coat", amount: 300 }],
    price_overrides: {
      options: { Copy1: { label: "old" } },
      manual: [{ label: "L0" }, { label: "L1" }, { label: "L2" }],
      lines: { "manual:0": "$100 – Mockup, as agreed", "manual:2": "$300 – Extra coat, frozen" },
      lines2: { "manual:1": "⟦amount⟧ – Night work, Saturdays", "option:Copy1": "⟦amount⟧ – Quartz ⟦tax⟧",
                "option:Copy1:total": "⟦amount⟧ – Total for the quartz", "option:Copy10": "⟦amount⟧ – kept" },
      before: { "manual:2": ["above the extra coat"], "option:Copy1": [""] },
      after: { "manual:0": ["under the mockup"], "manual:1": ["under night work"],
               "option:Copy1": ["Test again 123"], "option:Copy1:sales_tax": ["x"],
               "option:Copy10": ["under copy 10"], base: ["under the base"] },
    },
  };
}

const out = {};

// 1. REMOVE the second manual price line.
{
  const state = draft();
  const saved = [];
  const els = { "cb-pricelines": new El("div"), "cb-pricelines-head": new El("div") };
  const document = { getElementById: (id) => els[id] || null, createElement: (t) => new El(t),
                     querySelectorAll: () => [] };
  const TW = { setState: (s) => { saved.push(JSON.parse(JSON.stringify(s.price_overrides || null))); } };
  const api = new Function("state", "document", "TW", [
    "let PRICE_LINES = state.price_lines.slice();",
    lift("reKeyPriceLineOverrides"), lift("persistPriceLines"), lift("renderPriceLines"),
    "return { renderPriceLines, lines: () => PRICE_LINES };",
  ].join("\n"))(state, document, TW);
  api.renderPriceLines();
  const rows = els["cb-pricelines"].children;
  rows[1].querySelector('[data-act="rm"]').fire("click");
  out.manual = { pov: JSON.parse(JSON.stringify(state.price_overrides)),
                 saved: saved[saved.length - 1], labels: api.lines().map((p) => p.label) };
}

// 2. DELETE the copy tab "Copy1" (and not "Copy10", whose id starts the same way).
{
  const state = draft();
  const saved = [];
  const TW = { confirmDanger: async () => true,
               setState: (s) => { saved.push(JSON.parse(JSON.stringify(s.price_overrides || null))); } };
  const deleteTab = new Function("state", "TW", "HF", [
    "const BASE_ROLE = {}; const sheets = ['Epoxy', 'Polish'];",
    "const cellValues = {}; const sheetCache = {}; let activeSheet = 'Epoxy';",
    "const labelFor = (id) => id; const buildTabs = () => {}; const renderTabs = () => {};",
    "const showSheet = () => {}; const defaultBaseSheet = () => 'Epoxy';",
    lift("reKeyPriceLineOverrides"), lift("deleteTab"),
    "return deleteTab;",
  ].join("\n"))(state, TW, { removeSheet: () => {} });
  deleteTab("Copy1").then(() => {
    out.tab = { pov: JSON.parse(JSON.stringify(state.price_overrides)), saved: saved[saved.length - 1],
                copies: state.tab_copies.map((c) => c.id) };
    console.log(JSON.stringify(out));
  });
}
