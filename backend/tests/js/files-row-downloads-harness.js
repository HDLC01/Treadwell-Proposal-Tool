"use strict";
/* EACH LINE OF STEP 5's LIST DOWNLOADS ITS OWN PROPOSAL (Hanz, 2026-10-29), RUN rather than read.
 *
 * "each lump sum should have a download button ... it should be aligned to the row". On step 5 of a
 * project with several proposals every line of the Lump sums list carries PDF / .docx / .xlsx:
 *   * this one's line presses the big buttons' own downloadAs, under the same names;
 *   * another one's line builds THAT proposal's files from ITS saved document (GET /api/draft/{its
 *     id}, then POST /api/draft/{its id}/documents with the draft_version read), and saves them
 *     under "<project>_<its name>";
 *   * a proposal never built has its buttons off and says why.
 *
 * What runs is done.js's own code, lifted by name (money, proposalName, portalErrMsg, paintLumpSum,
 * paintReadyProposals, paintFilesProposals, refreshFilesProposals, paintRowFiles, downloadOther,
 * fileStem, builtAt, freshDocuments, and the records filesProposals / ROW_FILES / rowFiles /
 * checkedDocument), plus showPostGenerate's download wiring verbatim (from the info-sheet link to the
 * cover-letter note: the nested downloadAs, the three big buttons, and the line that hands
 * downloadAs to the list), over a small DOM and a stub TW/fetch that log every request.
 *
 * Usage: node files-row-downloads-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const SRC = L.read(path.join(ROOT, "js", "done.js"));
const TWPRICE = require(path.join(ROOT, "js", "price-lines-core.js"));
const NL = String.fromCharCode(10);
const where = { indent: "  ", where: "done.js" };

const FNS = ["money", "proposalName", "portalErrMsg", "paintLumpSum", "paintReadyProposals",
             "paintFilesProposals", "refreshFilesProposals", "paintRowFiles", "downloadOther", "fileStem",
             "builtAt", "freshDocuments"].map((n) => L.liftSource(SRC, n, where));
const RECORDS = ["filesProposals", "ROW_FILES", "rowFiles", "checkedDocument"]
  .map((n) => L.grabConst(SRC, n, where));
const WIRING = (function () {
  const start = SRC.indexOf("function showPostGenerate(result) {");
  const from = SRC.indexOf("// Carry the draft across", start);
  const to = SRC.indexOf("// NO SEPARATE COVER-LETTER DOWNLOAD", from);
  if (start < 0 || from < 0 || to < 0) throw new Error("showPostGenerate's download wiring moved in done.js");
  return SRC.slice(from, to);
})();

class El {
  constructor(tag, id, log) {
    this.tagName = String(tag).toUpperCase();
    this.id = id || "";
    this.children = [];
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.href = undefined;
    this.style = {};
    this.attrs = {};
    this.listeners = {};
    this._text = "";
    this._log = log;
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
  removeChild() {}
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
  click() { if (this.tagName === "A" && this._log) this._log.saved.push(this.download); }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join("") : this._text; }
  set textContent(v) { this.children = []; this._text = String(v); }
  set innerHTML(v) { this.children = []; this._text = String(v); }
}

const VIEW = { parent_id: "P1", group_id: "G1", members: [
  { id: "P1", label: "Base Bid 1", display_label: "Breakroom", sheet_label: "Breakroom", index: 1, is_parent: true,
    lump_sum: 20000, document_total: "$20,000.00" },
  { id: "C2", label: "Base Bid 2", display_label: "Polish Room 2", sheet_label: "Polish Room 2", index: 2, is_parent: false,
    lump_sum: 15000.5, document_total: "$15,000.50" },
  { id: "C3", label: "Kitchen", display_label: "Kitchen", sheet_label: "Kitchen", index: 3, is_parent: false,
    lump_sum: 9100, document_total: null },
] };
const PP = (total, extra) => Object.assign({ work_type: "epoxy", audience: "Direct",
                                             values: { project_name: "Acme Plant", total_formatted: total } }, extra || {});
// THIS page: C2, "Polish Room 2", its document at $15,000.50.
const ST = { project_name: "Acme Plant", work_type: "epoxy", audience: "Direct",
             scope_group: { id: "G1", label: "Polish Room 2" }, proposal_payload: PP("$15,000.50") };
// The server's rows. P1 is the parent; its document prints $20,000.00.
const ROWS = () => ({
  C2: { data: JSON.parse(JSON.stringify(ST)), updated_at: "v-C2" },
  P1: { data: { project_name: "Acme Plant", proposal_payload: PP("$20,000.00") }, updated_at: "v-P1" },
  C3: { data: { project_name: "Acme Plant" }, updated_at: "v-C3" },
});
const RENDER = (id, total) => ({ work_type: "epoxy", render_id: "K-" + id, document_total: total,
                                 xlsx_download_url: "/api/file/" + id + "X", docx_download_url: "/api/file/" + id,
                                 pdf_download_url: "/api/file/" + id + "/pdf" });

/** One step-5 page of C2 (or `o.id`), the card painted and wired as showPostGenerate does. */
async function page(o) {
  o = o || {};
  const log = { reqs: [], saved: [], asked: [], confirms: [], busy: [] };
  const rows = Object.assign(ROWS(), o.rows || {});
  const nodes = {};
  ["lump-row", "lump-sum", "lump-key", "which-proposal", "revisions-which", "send-which", "project-line",
   "dl-xlsx", "dl-docx", "dl-pdf"].forEach((id) => { nodes[id] = new El("p", id, log); });
  nodes["lump-row"].hidden = true;
  nodes["lump-sum"]._text = "—";
  const document = { getElementById: (id) => nodes[id] || null, createElement: (t) => new El(t, "", log),
                     body: new El("body", "", log) };
  const st = JSON.parse(JSON.stringify(o.st || ST));
  const view = o.view || VIEW;
  let pressed = null;
  const TW = {
    getState: () => st,
    getDraftId: () => o.id || "C2",
    flushState: async () => { log.reqs.push("flush"); return true; },
    setLocalState: (p) => { Object.assign(st, p); },
    setState: (p) => { log.reqs.push("setState"); Object.assign(st, p); },
    readServerRow: async () => { log.reqs.push("read own"); const r = rows[o.id || "C2"]; return { data: r.data, version: r.updated_at }; },
    readProposals: async (id) => { log.asked.push(id); return JSON.parse(JSON.stringify(view)); },
    postJSON: async (p, body) => {
      log.reqs.push("post " + p + " " + JSON.stringify(body));
      if (pressed) log.busy.push([pressed.textContent, pressed.disabled]);
      if (o.postFails) throw new Error("POST " + p + " → 409: {\"detail\":\"Not built — this proposal was saved again.\"}");
      const id = decodeURIComponent(p.split("/")[3]);
      const total = (o.renderTotals && o.renderTotals[id]) || rows[id].data.proposal_payload.values.total_formatted;
      return RENDER(id, total);
    },
    resolveApiBase: () => "",
    absoluteUrl: (u) => u,
    authHeaders: () => ({ Authorization: "Bearer t" }),
    confirmDanger: (q) => { log.confirms.push(q.title); return Promise.resolve(o.confirm !== false); },
  };
  const fetch = async (url) => {
    log.reqs.push("get " + url);
    const m = /^\/api\/draft\/([^/]+)$/.exec(url);
    if (m) {
      if (o.readFails) return { ok: false, status: 503, json: async () => ({}) };
      const r = rows[decodeURIComponent(m[1])];
      return { ok: !!r, status: r ? 200 : 404, json: async () => JSON.parse(JSON.stringify(Object.assign({ ok: true }, r))) };
    }
    const bad = o.fileFails && url.indexOf(o.fileFails) >= 0;
    return { ok: !bad, status: bad ? 500 : 200, statusText: bad ? "Internal Server Error" : "OK",
             arrayBuffer: async () => new ArrayBuffer(3) };
  };
  const code = '"use strict";' + NL + RECORDS.join(NL) + NL + FNS.join(NL) + NL
    + "function wire(result) {" + NL + WIRING + NL + "}" + NL
    + "return { wire, paintLumpSum, refreshFilesProposals, rowFiles };";
  const api = new Function("TW", "document", "state", "fetch", "Blob", "URL", "setTimeout", "icon", "console",
                           "TWPrice", "window", "coverLetterCheck", code)(
    TW, document, st, fetch, class { constructor() {} }, { createObjectURL: () => "blob:1", revokeObjectURL() {} },
    () => 0, () => "", { error() {} }, TWPRICE, { confirm: () => true }, async () => ({ enabled: false }));
  // showPostGenerate's order: the figure, the list, then the buttons.
  api.paintLumpSum();
  api.refreshFilesProposals();
  api.wire({ pdf_download_url: "/api/file/OLD/pdf" });
  await settle();
  const lines = () => {
    const list = nodes["lump-sum"].children.filter((c) => c.className === "rv-props")[0];
    return list ? list.children : [];
  };
  const rowOf = (id) => {
    const i = view.members.findIndex((m) => m.id === id);
    return lines()[i];
  };
  const btn = (id, label) => {
    const li = rowOf(id);
    const box = li && li.children.filter((c) => c.className === "rv-prop-dl")[0];
    return box ? box.children.filter((b) => b.textContent === label)[0] : null;
  };
  const press = async (b) => {
    pressed = b;
    for (const fn of b.listeners.click || []) await fn();
    await settle();
    pressed = null;
    // The pressed button itself once the press is over (a repaint may have replaced its line).
    log.after = [b.textContent, b.disabled];
  };
  return {
    log, nodes, api,
    snap: () => lines().map((li) => {
      const box = li.children.filter((c) => c.className === "rv-prop-dl")[0];
      const msg = li.children.filter((c) => c.className === "rv-prop-msg")[0];
      return {
        name: li.children[0].textContent,
        last: li.children.indexOf(box) === li.children.length - 2 && li.children.indexOf(msg) === li.children.length - 1,
        buttons: box ? box.children.map((b) => ({ label: b.textContent, disabled: b.disabled, type: b.type,
                                                  cls: b.className, aria: b.attrs["aria-label"] || null,
                                                  wired: (b.listeners.click || []).length })) : null,
        msg: msg && !msg.hidden ? msg.textContent : null,
      };
    }),
    btn, press,
    /** Press one of the three big buttons at the top. */
    top: (id) => press(nodes[id]),
    reset: () => { log.after = null; log.reqs.length = 0; log.saved.length = 0; log.asked.length = 0; log.confirms.length = 0; log.busy.length = 0; },
  };
}

const settle = async () => { for (let i = 0; i < 12; i++) await new Promise((r) => setTimeout(r, 0)); };
const take = (log) => JSON.parse(JSON.stringify({ reqs: log.reqs, saved: log.saved, asked: log.asked,
                                                   confirms: log.confirms, busy: log.busy,
                                                   pressed: log.after || null }));

(async () => {
  const out = {};

  // The list as painted: three lines, each with its three buttons; Kitchen never built.
  {
    const p = await page();
    out.lines = p.snap();
  }

  // THIS line's buttons against the big buttons: the same requests, the same file name.
  {
    out.same = {};
    for (const [top, label] of [["dl-pdf", "PDF"], ["dl-docx", ".docx"], ["dl-xlsx", ".xlsx"]]) {
      const p = await page();
      p.reset();
      await p.top(top);
      const big = take(p.log);
      p.reset();
      await p.press(p.btn("C2", label));
      out.same[label] = { big, row: take(p.log) };
    }
    // Before the wiring has run, this line's buttons do nothing (no second builder).
    const p = await page();
    p.api.rowFiles.mine = null;
    p.reset();
    await p.press(p.btn("C2", "PDF"));
    out.unwired = take(p.log);
  }

  // ANOTHER line (Breakroom, P1): its own document, its own id, its own name.
  {
    out.other = {};
    for (const label of ["PDF", ".docx", ".xlsx"]) {
      const p = await page();
      p.reset();
      await p.press(p.btn("P1", label));
      out.other[label] = Object.assign(take(p.log), { after: p.snap()[0] });
    }
  }

  // Its document was saved again at another figure after the list was read: nothing is built.
  {
    const p = await page({ rows: { P1: { data: { project_name: "Acme Plant", proposal_payload: PP("$21,000.00") },
                                         updated_at: "v-P1b" } } });
    p.reset();
    await p.press(p.btn("P1", "PDF"));
    out.moved = Object.assign(take(p.log), { after: p.snap()[0] });
  }

  // The render answers another figure than the line's: nothing is saved.
  {
    const p = await page({ renderTotals: { P1: "$19,000.00" } });
    p.reset();
    await p.press(p.btn("P1", "PDF"));
    out.renderMoved = Object.assign(take(p.log), { after: p.snap()[0] });
  }

  // A price line with a figure of his own on P1's document: asked first; Cancel builds nothing.
  {
    const warned = { P1: { data: { project_name: "Acme Plant", proposal_payload: PP("$20,000.00",
      { price_warnings: [{ says: "$9,999", estimate: "$4,757" }] }) }, updated_at: "v-P1" } };
    const p = await page({ rows: warned, confirm: false });
    p.reset();
    await p.press(p.btn("P1", "PDF"));
    out.cancel = Object.assign(take(p.log), { after: p.snap()[0] });
    const q = await page({ rows: warned, confirm: true });
    q.reset();
    await q.press(q.btn("P1", ".xlsx"));
    out.xlsxNotAsked = take(q.log);
  }

  // Failures: the file does not come back; the build is refused (409); the read fails.
  {
    const p = await page({ fileFails: "/api/file/P1" });
    p.reset();
    await p.press(p.btn("P1", "PDF"));
    out.fileFails = Object.assign(take(p.log), { after: p.snap()[0] });
    // The message stays through a repaint (the next download reads the list again).
    p.api.refreshFilesProposals(); await settle();
    out.fileFailsRepainted = p.snap()[0];
    const q = await page({ postFails: true });
    q.reset();
    await q.press(q.btn("P1", ".docx"));
    out.postFails = Object.assign(take(q.log), { after: q.snap()[0] });
    const r = await page({ readFails: true });
    r.reset();
    await r.press(r.btn("P1", ".xlsx"));
    out.readFails = Object.assign(take(r.log), { after: r.snap()[0] });
  }

  // Kitchen (C3), never built: pressing does nothing at all.
  {
    const p = await page();
    p.reset();
    await p.press(p.btn("C3", "PDF"));
    out.neverBuilt = take(p.log);
  }

  // A one-proposal project: no list, no line buttons, the single figure as it was.
  {
    const one = { parent_id: "S1", group_id: null, members: [
      { id: "S1", label: "", display_label: "", sheet_label: "Epoxy", index: 1, is_parent: true, lump_sum: 7447,
        document_total: "$7,447.00" }] };
    const p = await page({ id: "S1", view: one, st: { project_name: "Acme Plant", work_type: "epoxy",
                                                      proposal_payload: PP("$7,447.00") } });
    out.single = { lines: p.snap(), text: p.nodes["lump-sum"].textContent, key: p.nodes["lump-key"].textContent,
                   children: p.nodes["lump-sum"].children.length };
  }

  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
