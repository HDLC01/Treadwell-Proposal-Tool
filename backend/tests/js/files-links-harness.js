"use strict";
/* STEP 5's LUMP SUMS LIST OPENS ANOTHER PROPOSAL ON ITS DRAFT READ AHEAD (review of the wizard
 * cross-fade, 2026-10-30), RUN rather than read.
 *
 * Hanz, 2026-10-29: "when I transfer tabs with multiple proposals it flashes white as well". A plain
 * link to /done.html?d=<other> loaded the other proposal's Files page on THIS proposal's blob, and
 * shared.js initDraftSync then read the other draft and reloaded the page; a reload gets no
 * cross-fade, so the empty first frame showed. The Proposal step's tab strip already avoids it by
 * reading the other draft ahead (TW.prefetchDraft) so the page that opens boots on it once. The
 * Files list now does the same: idle read-ahead of every other name, a read on hover / focus, and on
 * the click a read, a save, a wait of 1.2 s at most, then location.assign (still a real load).
 *
 * What runs is done.js's own code, lifted by name: money, paintReadyProposals, proposalName,
 * paintFilesProposals, refreshFilesProposals, wireFilesLinks, openFilesLink and the records
 * filesProposals / filesLinks, over a small DOM (parent links, closest, querySelectorAll,
 * getAttribute) and a stub TW / window whose clock, idle callback and reads each scenario drives.
 * paintRowFiles (each line's own buttons) is a no-op here: files-row-downloads-harness.js runs it.
 *
 * Usage: node files-links-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const SRC = L.read(path.join(ROOT, "js", "done.js"));
const NL = String.fromCharCode(10);
const where = { indent: "  ", where: "done.js" };
const FNS = ["money", "paintReadyProposals", "proposalName", "paintFilesProposals", "refreshFilesProposals",
             "wireFilesLinks", "openFilesLink"].map((n) => L.liftSource(SRC, n, where));
const RECORDS = ["filesProposals", "filesLinks"].map((n) => L.grabConst(SRC, n, where));

class El {
  constructor(tag, id) {
    this.tagName = String(tag).toUpperCase();
    this.id = id || "";
    this.children = [];
    this.parentNode = null;
    this.className = "";
    this.hidden = false;
    this.href = undefined;
    this.style = {};
    this.listeners = {};
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
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  getAttribute(k) { return k === "href" ? (this.href === undefined ? null : String(this.href)) : null; }
  setAttribute() {}
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
  /** "a.rv-prop-nm" only, the one selector done.js asks for. */
  _is(sel) {
    if (sel !== "a.rv-prop-nm") throw new Error("the harness reads only a.rv-prop-nm, not " + sel);
    return this.tagName === "A" && this.className.split(/\s+/).indexOf("rv-prop-nm") >= 0;
  }
  closest(sel) { for (let e = this; e; e = e.parentNode) if (e._is && e._is(sel)) return e; return null; }
  querySelectorAll(sel) {
    const out = [];
    const walk = (e) => e.children.forEach((c) => { if (c._is(sel)) out.push(c); walk(c); });
    walk(this);
    return out;
  }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join("") : this._text; }
  set textContent(v) { this.children.forEach((c) => { c.parentNode = null; }); this.children = []; this._text = String(v); }
}

const VIEW = { parent_id: "P1", group_id: null, members: [
  { id: "P1", display_label: "Breakroom", index: 1, is_parent: true, lump_sum: 20000, document_total: "$20,000.00" },
  { id: "C2", display_label: "Polish Room 2", index: 2, lump_sum: 15000.5, document_total: "$15,000.50" },
  { id: "C3", display_label: "Kitchen & Bath", index: 3, lump_sum: null, document_total: null },
] };

function deferred() {
  let resolve;
  const p = new Promise((a) => { resolve = a; });
  return { p, resolve };
}

/** One Files page of proposal `id`. `o.reads` answers TW.prefetchDraft: "hang" never settles,
 *  "manual" waits for `release(id)`, anything else resolves true at once. */
function page(o) {
  const log = [];
  const nodes = {};
  ["lump-row", "lump-sum", "lump-key", "which-proposal", "revisions-which", "send-which"]
    .forEach((id) => { nodes[id] = new El(id === "lump-row" ? "div" : "p", id); });
  nodes["lump-sum"]._text = "$15,000.50";
  const document = { getElementById: (id) => nodes[id] || null, createElement: (t) => new El(t) };
  const pending = {};
  const TW = {
    getState: () => ({}),
    getDraftId: () => o.id,
    readProposals: () => Promise.resolve(JSON.parse(JSON.stringify(VIEW))),
    flushState: () => { log.push("flush"); return Promise.resolve(true); },
  };
  if (!o.noPrefetch) {
    TW.prefetchDraft = (pid) => {
      log.push("read:" + pid);
      if (o.reads === "hang") return new Promise(() => {});
      if (o.reads === "manual") { pending[pid] = pending[pid] || deferred(); return pending[pid].p; }
      return Promise.resolve(true);
    };
  }
  let now = 0;
  const timers = [];
  const idle = [];
  const window = {
    location: { assign: (h) => log.push("assign:" + h) },
    requestIdleCallback: (f) => { idle.push(f); },
  };
  const setTimeout = (f, ms) => { timers.push({ at: now + (ms || 0), f }); return timers.length; };
  const code = '"use strict";' + NL + RECORDS.join(NL) + NL + FNS.join(NL) + NL
    + "function paintRowFiles() {}" + NL
    + "return { refreshFilesProposals };";
  const api = new Function("TW", "document", "window", "setTimeout", code)(TW, document, window, setTimeout);
  const links = () => nodes["lump-sum"].querySelectorAll("a.rv-prop-nm");
  const link = (pid) => links().filter((a) => a.getAttribute("href") === "/done.html?d=" + encodeURIComponent(pid))[0];
  const fire = (type, target, extra) => {
    const e = Object.assign({ type, target, button: 0, defaultPrevented: false,
                              preventDefault() { this.defaultPrevented = true; } }, extra || {});
    (nodes["lump-sum"].listeners[type] || []).forEach((h) => h(e));
    return e;
  };
  return {
    log, idle, nodes, links, link, fire,
    refresh: () => api.refreshFilesProposals(),
    release: (pid) => { if (pending[pid]) pending[pid].resolve(true); },
    advance(ms) {
      now += ms;
      timers.filter((t) => t.at <= now && !t.ran).forEach((t) => { t.ran = true; t.f(); });
    },
    listenerCount: (type) => (nodes["lump-sum"].listeners[type] || []).length,
  };
}

const settle = async () => { for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r)); };

(async () => {
  const out = {};

  // 1. The list is drawn: every other name is read at idle, never this one, and only once a page.
  {
    const p = page({ id: "C2" });
    p.refresh(); await settle();
    const linked = p.links().length;
    const queued = p.idle.length === 1;
    const nothingYet = p.log.length === 0;
    p.idle.splice(0).forEach((f) => f());
    const others = p.log.slice();
    p.refresh(); await settle();             // a download repaints the list
    out.idle = { linked: linked === 2, queued, nothingYet,
                 readsOthers: JSON.stringify(others) === JSON.stringify(["read:P1", "read:C3"]),
                 once: p.idle.length === 0,
                 oneListener: p.listenerCount("click") === 1 && p.listenerCount("pointerover") === 1
                   && p.listenerCount("focusin") === 1 };
  }

  // 2. The click: read, save, wait for the read, then the real load of that proposal's Files page.
  {
    const p = page({ id: "C2", reads: "manual" });
    p.refresh(); await settle();
    const a = p.link("C3");
    const e = p.fire("click", a.children.length ? a.children[0] : a);
    await settle();
    const before = p.log.slice();
    p.release("C3"); await settle();
    out.click = {
      prevented: e.defaultPrevented === true,
      readFirst: before[0] === "read:C3",
      flushedFirst: before.indexOf("flush") > 0,
      waitedForRead: before.every((x) => x.indexOf("assign:") !== 0),
      assigned: p.log[p.log.length - 1] === "assign:/done.html?d=C3",
      onceOnly: p.log.filter((x) => x.indexOf("assign:") === 0).length === 1,
    };
  }

  // 3. A read that never answers holds the click 1.2 s at most; a second click meanwhile is ignored.
  {
    const p = page({ id: "C2", reads: "hang" });
    p.refresh(); await settle();
    p.fire("click", p.link("P1"));
    await settle();
    p.fire("click", p.link("P1"));
    await settle();
    p.advance(1199); await settle();
    const heldAt1199 = !p.log.some((x) => x.indexOf("assign:") === 0);
    p.advance(1); await settle();
    out.cap = { heldAt1199,
                assignedAt1200: p.log.filter((x) => x === "assign:/done.html?d=P1").length === 1,
                secondClickIgnored: p.log.filter((x) => x === "flush").length === 1 };
  }

  // 4. A click with a modifier (a new tab or window) is the browser's.
  {
    const p = page({ id: "C2" });
    p.refresh(); await settle();
    const results = ["ctrlKey", "metaKey", "shiftKey", "altKey"].map((k) => p.fire("click", p.link("P1"), { [k]: true }));
    const middle = p.fire("click", p.link("P1"), { button: 1 });
    await settle();
    out.modifier = { untouched: results.concat([middle]).every((e) => !e.defaultPrevented)
                       && !p.log.some((x) => x.indexOf("assign:") === 0) };
  }

  // 5. A pointer or the keyboard on a name reads that one now.
  {
    const p = page({ id: "C2" });
    p.refresh(); await settle();
    p.fire("pointerover", p.link("C3"));
    p.fire("focusin", p.link("P1"));
    p.fire("pointerover", p.nodes["lump-sum"]);           // not on a name
    out.hover = { reads: JSON.stringify(p.log) === JSON.stringify(["read:C3", "read:P1"]) };
  }

  // 6. A page without the read-ahead (an older shared.js) leaves the plain link alone.
  {
    const p = page({ id: "C2", noPrefetch: true });
    p.refresh(); await settle();
    const e = p.fire("click", p.link("P1"));
    out.plain = { linksStill: p.links().length === 2, notPrevented: !e.defaultPrevented && p.log.length === 0 };
  }

  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ error: String((e && e.stack) || e) })); process.exitCode = 1; });
