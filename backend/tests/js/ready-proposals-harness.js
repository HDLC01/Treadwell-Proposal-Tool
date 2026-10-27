"use strict";
/* THE "READY TO GENERATE" CARD OF A PROJECT WITH SEVERAL PROPOSALS (Hanz, 2026-10-27), RUN rather than read.
 *
 * On the Files page's pre-generate card the LUMP SUM row of a draft that is one of several proposals made from one
 * estimate (Create Multiple Proposals) lists every proposal: its name and its own figure, this one marked "(this one)"
 * and carrying the figure the card already shows, one without a figure "not priced yet", and NO total. A draft with no
 * proposals keeps today's single figure exactly.
 *
 * What runs here is done.js's own code: paintReadyProposals, lifted by name, and the pre-generate card's figure
 * statements from `const _rvPp = ` through the readyProposals IIFE, lifted verbatim (the same anchor
 * files-lump-sum-harness.js lifts), over a small DOM with a stub TW whose readProposals answers what each scenario says.
 *
 * Usage: node ready-proposals-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const SRC = L.read(path.join(ROOT, "js", "done.js"));

const PAINT = L.liftSource(SRC, "paintReadyProposals", { indent: "  ", where: "done.js" });
const CARD = (function () {
  const start = SRC.indexOf("const _rvPp = ");
  const head = SRC.indexOf("(async function readyProposals()", start);
  if (start < 0 || head < 0) throw new Error("the #rv-lump card or its readyProposals IIFE is gone from done.js");
  const body = L.balanced(SRC, SRC.indexOf("{", head));
  const end = SRC.indexOf(";", body);
  return SRC.slice(start, end + 1);
})();

class El {
  constructor(tag, id) {
    this.tagName = String(tag).toUpperCase();
    this.id = id || "";
    this.children = [];
    this.className = "";
    this._text = "";
    const self = this;
    this.classList = {
      remove: (c) => { self.className = self.className.split(/\s+/).filter((x) => x && x !== c).join(" "); },
      contains: (c) => self.className.split(/\s+/).indexOf(c) >= 0,
    };
  }
  appendChild(c) { this.children.push(c); return c; }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join("") : this._text; }
  set textContent(v) { this.children = []; this._text = String(v); }
}

async function card(o) {
  const lump = new El("div", "rv-lump");
  lump.className = "val money";
  lump._text = "—";
  const document = { getElementById: (id) => (id === "rv-lump" ? lump : null), createElement: (t) => new El(t) };
  const asked = [];
  const TW = {
    getState: () => o.st,
    getDraftId: () => o.id,
    readProposals: async (pid) => { asked.push(pid); if (o.throws) throw new Error("x"); return o.view === undefined ? null : JSON.parse(JSON.stringify(o.view)); },
  };
  const money = (s) => { const n = Number(String(s == null ? "" : s).replace(/[$,\s]/g, "")); return s && isFinite(n) ? n : null; };
  new Function("TW", "state", "document", "money", '"use strict";\n' + PAINT + "\n" + CARD)(TW, o.st, document, money);
  for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
  const list = lump.children.filter((c) => c.className === "rv-props")[0];
  return {
    asked,
    text: lump.textContent,
    money: lump.classList.contains("money"),
    rows: list ? list.children.map((li) => ({
      current: li.className.split(" ").indexOf("current") >= 0,
      parts: li.children.map((c) => [c.className, c.textContent]),
    })) : null,
    note: (lump.children.filter((c) => c.className === "rv-props-note")[0] || { textContent: null }).textContent,
  };
}

const VIEW = { parent_id: "P1", group_id: "G1", members: [
  { id: "P1", label: "Base Bid 1", display_label: "Breakroom", sheet_label: "Breakroom", index: 1, is_parent: true, lump_sum: 20000 },
  { id: "C2", label: "Base Bid 2", display_label: "Room 2", sheet_label: "Room 2", index: 2, is_parent: false, lump_sum: 15000.5 },
  { id: "C3", label: "Kitchen", display_label: "Kitchen", sheet_label: "Polish", index: 3, is_parent: false, lump_sum: null },
] };
const DOC = (t) => ({ project_name: "Acme", lump_sum_display: "$1.00", proposal_payload: { values: { total_formatted: t } } });

(async () => {
  const out = {};
  // The child's page: its own line carries the card's figure (the saved document's total, not the server's 15000.5).
  out.child = await card({ id: "C2", st: DOC("$15,999.00"), view: VIEW });
  // The parent's page.
  out.parent = await card({ id: "P1", st: DOC("$20,000.00"), view: VIEW });
  // On its own (one member), no list, a refusal, a throw, or this draft not among them: the single figure as today.
  out.alone = await card({ id: "S1", st: DOC("$7,447.00"), view: { parent_id: "S1", members: [{ id: "S1", label: "", index: 1, is_parent: true, lump_sum: 7447 }] } });
  out.noList = await card({ id: "S1", st: DOC("$7,447.00"), view: null });
  out.throws = await card({ id: "S1", st: DOC("$7,447.00"), throws: true });
  out.notAmong = await card({ id: "X9", st: DOC("$7,447.00"), view: VIEW });
  out.display = await card({ id: "S1", st: { lump_sum_display: "$5,000.00" }, view: null });
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
