"use strict";
/* STEP 5 FILES OF A PROJECT WITH SEVERAL PROPOSALS (Hanz, 2026-10-29), RUN rather than read.
 *
 * "could we also show multiple lump sums here? before we send out" and "show the sheet names in the
 * 5. Files section as well". On the generated card of a draft that is one of several proposals made
 * from one estimate, the LUMP SUM column lists every proposal (its sheet's name, its own figure, this
 * one marked, no total, another one's name a link to its own Files page), the header names this
 * proposal by its sheet, the Sent versions card says whose versions they are, and the Send card names
 * the proposals its one email is for. A one-proposal project stays exactly as it was.
 *
 * What runs here is done.js's own code, lifted by name: money, paintLumpSum, paintReadyProposals,
 * proposalName, paintFilesProposals, refreshFilesProposals and its `filesProposals` record, and the
 * head of showPostGenerate (from its first line to the info-sheet link) verbatim, over a small DOM
 * with a stub TW whose readProposals answers what each scenario says.
 *
 * Usage: node files-proposals-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const SRC = L.read(path.join(ROOT, "js", "done.js"));

const FNS = ["money", "paintLumpSum", "paintReadyProposals", "proposalName", "paintFilesProposals",
             "refreshFilesProposals"].map((n) => L.liftSource(SRC, n, { indent: "  ", where: "done.js" }));
const RECORD = L.grabConst(SRC, "filesProposals", { indent: "  ", where: "done.js" });
const HEAD = (function () {
  const start = SRC.indexOf("function showPostGenerate(result) {");
  const end = SRC.indexOf("// Carry the draft across", start);
  if (start < 0 || end < 0) throw new Error("the head of showPostGenerate is gone from done.js");
  return SRC.slice(SRC.indexOf("{", start) + 1, end);
})();

class El {
  constructor(tag, id) {
    this.tagName = String(tag).toUpperCase();
    this.id = id || "";
    this.children = [];
    this.className = "";
    this.hidden = false;
    this.href = undefined;
    this.style = {};
    this._text = "";
    const self = this;
    const has = (c) => self.className.split(/\s+/).indexOf(c) >= 0;
    this.classList = {
      contains: has,
      remove: (c) => { self.className = self.className.split(/\s+/).filter((x) => x && x !== c).join(" "); },
      add: (c) => { if (!has(c)) self.className = (self.className + " " + c).trim(); },
      toggle: (c, on) => { if (on) self.classList.add(c); else self.classList.remove(c); return !!on; },
    };
  }
  appendChild(c) { this.children.push(c); return c; }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join("") : this._text; }
  set textContent(v) { this.children = []; this._text = String(v); }
}

/** One page: the generated card's elements as done.html has them, and the lifted code bound to them. */
function page(o) {
  const nodes = {};
  ["lump-row", "lump-sum", "lump-key", "which-proposal", "revisions-which", "send-which", "project-line"]
    .forEach((id) => { nodes[id] = new El(id === "lump-row" ? "div" : "p", id); });
  nodes["lump-row"].className = "fp-money";
  nodes["lump-row"].hidden = true;                       // as done.html ships it
  nodes["lump-sum"].className = "fp-money-v";
  nodes["lump-sum"]._text = "—";
  nodes["lump-key"]._text = "Lump sum";
  ["which-proposal", "revisions-which", "send-which"].forEach((id) => { nodes[id].hidden = true; });
  const document = { getElementById: (id) => nodes[id] || null, createElement: (t) => new El(t) };
  const asked = [];
  let st = JSON.parse(JSON.stringify(o.st));
  let answers = (o.answers || []).slice();
  const TW = {
    getState: () => st,
    getDraftId: () => o.id,
    readProposals: (pid) => {
      asked.push(pid);
      const a = answers.length > 1 ? answers.shift() : answers[0];
      if (a && a.throws) return Promise.reject(new Error("offline"));
      if (a && a.wait) return a.wait.then(() => JSON.parse(JSON.stringify(a.view)));
      return Promise.resolve(a === undefined || a === null ? null : JSON.parse(JSON.stringify(a)));
    },
  };
  const postEl = { style: { display: "none" } };
  const code = '"use strict";\n' + RECORD + "\n" + FNS.join("\n")
    + "\nreturn { paintLumpSum, refreshFilesProposals, head: function (result) {" + HEAD + "} };";
  const api = new Function("TW", "document", "state", "postEl", code)(TW, document, st, postEl);
  return {
    nodes, asked,
    setState: (s) => { st = JSON.parse(JSON.stringify(s)); },
    setAnswers: (a) => { answers = a.slice(); },
    /** showPostGenerate's arrival: the card as a regenerate, or the page Send all comes back to, paints it. */
    arrive: () => api.head({}),
    /** What downloadAs does after it built fresh files. */
    download: () => { api.paintLumpSum(); api.refreshFilesProposals(); },
  };
}

const settle = async () => { for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0)); };

function snap(p) {
  const n = p.nodes;
  const val = n["lump-sum"];
  const list = val.children.filter((c) => c.className === "rv-props")[0];
  return {
    asked: p.asked.slice(),
    rowHidden: n["lump-row"].hidden,
    rowClass: n["lump-row"].className,
    key: n["lump-key"].textContent,
    text: val.textContent,
    rows: list ? list.children.map((li) => ({
      current: li.className.split(" ").indexOf("current") >= 0,
      parts: li.children.map((c) => [c.tagName, c.className, c.textContent, c.href === undefined ? null : c.href]),
    })) : null,
    note: (val.children.filter((c) => c.className === "rv-props-note")[0] || { textContent: null }).textContent,
    which: n["which-proposal"].hidden ? null : n["which-proposal"].textContent,
    whichName: n["which-proposal"].children.length ? n["which-proposal"].children[0].textContent : null,
    revWhich: n["revisions-which"].hidden ? null : n["revisions-which"].textContent,
    sendWhich: n["send-which"].hidden ? null : n["send-which"].textContent,
    project: n["project-line"].textContent,
  };
}

const VIEW = { parent_id: "P1", group_id: "G1", members: [
  { id: "P1", label: "Base Bid 1", display_label: "Breakroom", sheet_label: "Breakroom", index: 1, is_parent: true,
    lump_sum: 20000, document_total: "$20,000.00" },
  { id: "C2", label: "Base Bid 2", display_label: "Polish Room 2", sheet_label: "Polish Room 2", index: 2, is_parent: false,
    lump_sum: 15000.5, document_total: "$15,000.50" },
  { id: "C3", label: "Kitchen", display_label: "Kitchen", sheet_label: "Kitchen", index: 3, is_parent: false,
    lump_sum: null, document_total: null },
] };
const ST = (total, extra) => Object.assign({ project_name: "Acme Plant", work_type: "epoxy", audience: "Direct",
                                             lump_sum_display: "$1.00",
                                             proposal_payload: { values: { total_formatted: total } } }, extra || {});
const GROUP = { scope_group: { id: "G1", label: "Polish Room 2" } };

(async () => {
  const out = {};

  // A one-proposal project: the answer is its own row alone. And the same draft with no answer at all.
  {
    const p = page({ id: "S1", st: ST("$7,447.00"), answers: [{ parent_id: "S1", group_id: null, members: [
      { id: "S1", label: "", display_label: "", sheet_label: "Epoxy", index: 1, is_parent: true, lump_sum: 7447 }] }] });
    p.arrive(); await settle();
    out.single = snap(p);
    const q = page({ id: "S1", st: ST("$7,447.00"), answers: [null] });
    q.arrive(); await settle();
    out.singleNoList = snap(q);
  }

  // Three proposals, on the child's page, the project's Send all button showing.
  {
    const p = page({ id: "C2", st: ST("$15,999.00", GROUP), answers: [VIEW] });
    p.arrive(); await settle();
    out.three = snap(p);
  }

  // A project split into scopes (#711), this estimate then given Create Multiple Proposals: the
  // group's other scope (Office) is sent by Send all too, so it is listed and named after the strip.
  // And Office's own page, whose strip is itself alone.
  {
    const SCOPED = Object.assign(JSON.parse(JSON.stringify(VIEW)), { group_others: [
      { id: "S9", label: "Office", lump_sum: 5000, document_total: "$5,100.00" }] });
    const p = page({ id: "C2", st: ST("$15,999.00", GROUP), answers: [SCOPED] });
    p.arrive(); await settle();
    out.scoped = snap(p);
    const ALONE = { parent_id: "S9", group_id: "G1", members: [
      { id: "S9", label: "Office", display_label: "Office", sheet_label: "Epoxy", index: 1, is_parent: true,
        lump_sum: 5000, document_total: "$5,100.00" }],
      group_others: VIEW.members.map((m) => ({ id: m.id, label: m.display_label, lump_sum: m.lump_sum,
                                               document_total: m.document_total })) };
    const q = page({ id: "S9", st: ST("$5,100.00", { scope_group: { id: "G1", label: "Office" } }), answers: [ALONE] });
    q.arrive(); await settle();
    out.scopeAlone = snap(q);
  }

  // The same page with no figure of its own on the card (paintLumpSum hid the row) and no group.
  {
    const p = page({ id: "C3", st: { project_name: "Acme Plant", work_type: "epoxy" }, answers: [VIEW] });
    p.arrive(); await settle();
    out.unpriced = snap(p);
  }

  // A regenerate / the page Send all comes back to after building: the card arrives again and the
  // list carries the new figures. Then a download, after which the read fails: the list stays.
  {
    const p = page({ id: "P1", st: ST("$20,000.00", GROUP), answers: [VIEW] });
    p.arrive(); await settle();
    out.before = snap(p);
    const NEXT = JSON.parse(JSON.stringify(VIEW));
    NEXT.members[0].document_total = "$21,500.00";
    NEXT.members[2].lump_sum = 9100;
    NEXT.members[2].document_total = "$9,100.00";
    p.setState(ST("$21,500.00", GROUP));
    p.setAnswers([NEXT]);
    p.arrive(); await settle();
    out.after = snap(p);
    p.setAnswers([{ throws: true }]);
    p.download(); await settle();
    out.readFails = snap(p);
  }

  // Two reads in flight: the older one answering last is dropped.
  {
    let release;
    const slow = new Promise((r) => { release = r; });
    const OLD = JSON.parse(JSON.stringify(VIEW));
    OLD.members[2].document_total = "$1.00";
    const p = page({ id: "C2", st: ST("$15,999.00"), answers: [{ wait: slow, view: OLD }, VIEW] });
    p.arrive();
    p.download(); await settle();
    release(); await settle();
    out.late = snap(p);
  }

  // A project that WAS several proposals and is one again (the others deleted) between two reads.
  {
    const p = page({ id: "P1", st: ST("$20,000.00"), answers: [VIEW] });
    p.arrive(); await settle();
    p.setAnswers([{ parent_id: "P1", group_id: null, members: [{ id: "P1", label: "", index: 1, lump_sum: 20000 }] }]);
    p.download(); await settle();
    out.backToOne = snap(p);
  }

  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
