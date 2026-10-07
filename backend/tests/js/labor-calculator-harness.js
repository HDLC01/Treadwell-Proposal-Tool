"use strict";
/* EXECUTE the Labor Calculator tab's Travel section: the shipped code out of library.js.
 *
 * The block from `// ── the Labor Calculator tab` to `// ── view switch` is taken whole and run
 * against a fake DOM, a fake fetch and the real library-core.js (money) and bid-model.js
 * (travelSeed). Nothing is restated: a source assertion cannot tell a rate box that saves from one
 * that does not, which is exactly how the Defaults tab's Markup inputs shipped with no handler.
 *
 * Usage: node labor-calculator-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const src = read(path.join(ROOT, "js", "library.js"));
const L = require(path.join(ROOT, "js", "library-core.js"));
const B = require(path.join(ROOT, "js", "bid-model.js"));

const START = "  // ── the Labor Calculator tab (Hanz, 2026-10-05)";
const END = "  // ── view switch ";
const a = src.indexOf(START);
const b = src.indexOf(END);
if (a < 0 || b < a) {
  throw new Error("the Labor Calculator block is gone from library.js -- rewrite this harness");
}
const BLOCK = src.slice(a, b);

const clone = (v) => JSON.parse(JSON.stringify(v));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function make(opts) {
  const els = {};
  ["labcalc-body", "labcalc-ro", "labcalc-alert", "labcalc-tryout"].forEach((id) => {
    els[id] = { id, innerHTML: "", textContent: "", hidden: false };
  });
  const puts = [];
  const calcPuts = [];
  const rec = { fetches: [] };
  const GLOBAL_MARKUP = clone(opts.globalMarkup || []);
  const fetchStub = async (url, init) => {
    rec.fetches.push(url);
    if (String(url).indexOf("/api/library/labor-calc") === 0) {
      if ((init || {}).method === "PUT") {
        const body = JSON.parse(init.body);
        calcPuts.push({ url: url, body: body });
        if (opts.calcPutStatus === 403) return { ok: false, status: 403, json: async () => ({}) };
        if (opts.calcPutStatus === 400) {
          return { ok: false, status: 400, json: async () => ({ detail: "calc refused" }) };
        }
        if (body.mode === "none") return { ok: true, status: 200, json: async () => ({ ok: true, row: null }) };
        const line = decodeURIComponent(url.split("/").pop());
        return { ok: true, status: 200, json: async () => ({ ok: true, row: Object.assign(
          { line_id: line, crew: null, sf_per_day: null, guys: null, days: null, rate: null }, body,
          { hours_per_day: body.hours_per_day || 8 }) }) };
      }
      if (opts.calcReadFails) throw new Error("no table");
      return { ok: true, status: 200, json: async () => ({ ok: true, calc: clone(opts.calc || []) }) };
    }
    if ((init || {}).method === "PUT") {
      const body = JSON.parse(init.body);
      puts.push(body);
      if (opts.putStatus === 403) return { ok: false, status: 403, json: async () => ({}) };
      if (opts.putStatus === 400) {
        return { ok: false, status: 400, json: async () => ({ detail: "the server said no" }) };
      }
      return { ok: true, status: 200, json: async () => ({ ok: true, rule: Object.assign({ id: "n1" }, body) }) };
    }
    if (opts.readFails) throw new Error("down");
    return { ok: true, status: 200, json: async () => ({ ok: true, rules: clone(opts.rules || []) }) };
  };
  const body = BLOCK + "\nreturn { renderLabCalc: renderLabCalc, saveTravelRate: saveTravelRate, " +
    "travelFigure: travelFigure, rules: function () { return TRAVEL_RULES; }, " +
    "calcEdit: calcEdit, renderTryIt: renderTryIt, calcProblem: calcProblem, " +
    "setTry: function (v) { CALC_TRY_SF = v; }, calc: function () { return CALC; }, " +
    "saved: function () { return CALC_SAVED; } };";
  const scope = new Function("$", "esc", "api", "L", "LABOR", "ADMIN", "GLOBAL_MARKUP", "window", body);
  const api = scope((id) => els[id] || null, esc, fetchStub, L, clone(opts.labor || []),
                    opts.admin !== false, GLOBAL_MARKUP, { TWBidModel: B });
  return { api, els, puts, calcPuts, rec, GLOBAL_MARKUP };
}

const settle = () => new Promise((r) => setImmediate(r));
const input = (key, value) => ({
  value: value,
  getAttribute: (k) => (k === "data-travel-rate" ? key : null),
});
const RULE = (key, formula, extra) => Object.assign({ id: "r-" + key, layout: "global",
  line_key: key, formula: formula, applies: true, notes: "" }, extra || {});

(async () => {
  const out = {};

  // ── an admin sees the stored rates in boxes, and the Travel row's rate off the Labor tab ──────
  {
    const s = make({ rules: [RULE("travel_lodging", "80", { notes: "kept note" })],
                     labor: [{ id: "travel", name: "Travel", rate: "41.50", unit: "hours" }],
                     globalMarkup: [{ id: "r-travel_lodging", line_key: "travel_lodging", formula: "80" }] });
    s.api.renderLabCalc();
    const loadingFirst = s.els["labcalc-body"].innerHTML;
    await settle();
    const html = s.els["labcalc-body"].innerHTML;
    out.admin = {
      loadingFirst: loadingFirst,
      readOnce: s.rec.fetches.filter((u) => u.indexOf("/api/markup") === 0).length,
      lodgingBox: /data-travel-rate="travel_lodging" value="80"/.test(html),
      perDiemBoxEmptyWithShippedPlaceholder:
        /data-travel-rate="travel_per_diem" value="" placeholder="45"/.test(html),
      // Rate and unit are two columns since 2026-10-06 (the Labor tab's own Rate | Unit), so the
      // dollars line up down one edge; the figure is still the Labor tab's Travel row, per hour.
      travelLaborRow: /Travel Labor<\/td><td class="n[^"]*">\$41\.50<\/td><td>per hour<\/td>/.test(html),
      seventyMiles: html.indexOf("70 miles or more") !== -1,
      insideMarkups: html.indexOf("before GP") !== -1,
      roHidden: s.els["labcalc-ro"].hidden,
    };

    // saving keeps the filed note and files the whole row on the GLOBAL layout
    const box = input("travel_per_diem", "55");
    await s.api.saveTravelRate(box);
    const lodgingBox = input("travel_lodging", "$90");
    await s.api.saveTravelRate(lodgingBox);
    out.saved = {
      puts: s.puts,
      alert: s.els["labcalc-alert"].textContent,
      cached: s.api.rules()["travel_per_diem"].formula,
      defaultsTabCopy: s.GLOBAL_MARKUP.map((g) => [g.line_key, g.formula]),
    };

    // the same value again, and a blank, send nothing
    const before = s.puts.length;
    await s.api.saveTravelRate(input("travel_per_diem", "55"));
    await s.api.saveTravelRate(input("travel_per_diem", ""));
    out.noops = { sent: s.puts.length - before, alert: s.els["labcalc-alert"].textContent };

    // refused in words, nothing sent, the box put back
    const bad = [];
    for (const v of ["abc", "0", "-5", "70 a night", "7e1"]) {
      const bx = input("travel_lodging", v);
      const n = s.puts.length;
      await s.api.saveTravelRate(bx);
      bad.push({ v: v, sent: s.puts.length - n, back: bx.value, alert: s.els["labcalc-alert"].textContent });
    }
    out.refused = bad;
  }

  // ── a refused save (403 / 400) puts the old figure back and says so ──────────────────────────
  {
    const s = make({ rules: [RULE("travel_lodging", "80")], putStatus: 403 });
    s.api.renderLabCalc(); await settle();
    const bx = input("travel_lodging", "99");
    await s.api.saveTravelRate(bx);
    const s4 = make({ rules: [RULE("travel_lodging", "80")], putStatus: 400 });
    s4.api.renderLabCalc(); await settle();
    const bx4 = input("travel_lodging", "99");
    await s4.api.saveTravelRate(bx4);
    out.refusedByServer = { back403: bx.value, alert403: s.els["labcalc-alert"].textContent,
                            back400: bx4.value, alert400: s4.els["labcalc-alert"].textContent,
                            cacheKept: s.api.rules()["travel_lodging"].formula };
  }

  // ── a non-admin sees the figures as text, with no boxes ──────────────────────────────────────
  {
    const s = make({ admin: false, rules: [RULE("travel_lodging", "80")] });
    s.api.renderLabCalc(); await settle();
    const html = s.els["labcalc-body"].innerHTML;
    out.nonAdmin = { boxes: (html.match(/data-travel-rate/g) || []).length,
                     showsLodging: /\$80\.00<\/td><td>per night<\/td>/.test(html),
                     showsShippedPerDiem: /\$45\.00<\/td><td>per day<\/td>/.test(html),
                     roShown: s.els["labcalc-ro"].hidden === false };
  }

  // ── the markup read going down is said out loud and invents no rate ──────────────────────────
  {
    const s = make({ readFails: true });
    s.api.renderLabCalc(); await settle();
    const html = s.els["labcalc-body"].innerHTML;
    out.readFails = { said: html.indexOf("Could not read the saved figures") !== -1,
                      boxesEmpty: /data-travel-rate="travel_lodging" value=""/.test(html) };
  }

  // ── filed-but-off and non-numeric rules read as not filed ────────────────────────────────────
  {
    const s = make({});
    out.figure = [s.api.travelFigure(RULE("travel_lodging", "70")),
                  s.api.travelFigure(RULE("travel_lodging", "$70.5")),
                  s.api.travelFigure(RULE("travel_lodging", "70", { applies: false })),
                  s.api.travelFigure(RULE("travel_lodging", "IF(1,2,3)")),
                  s.api.travelFigure(null)];
  }

  // ── THE PER-LINE MODES (B7b): picking, saving, the Try-it box, and an absent table ────────────
  const sel = (id, value) => ({ value: value,
    getAttribute: (k) => (k === "data-lcalc-mode" ? id : null) });
  const box = (id, f, value) => ({ value: value,
    getAttribute: (k) => (k === "data-lcalc" ? id : k === "data-f" ? f : null) });
  {
    const s = make({ rules: [RULE("labor_rate", "40")],
                      calc: [{ line_id: "mockup", mode: "fixed", guys: 3, days: 0.5, hours_per_day: 8, rate: null,
                               crew: null, sf_per_day: null }],
                      labor: [{ id: "u1", name: "Sealer", rate: 30, unit: "days", favorite: true },
                              { id: "u2", name: "Not a default", rate: 30, unit: "days", favorite: false },
                              { id: "u3", name: "Hours thing", rate: 30, unit: "hours", favorite: true },
                              { id: "travel", name: "Travel", rate: 33, unit: "hours", favorite: true }] });
    s.api.renderLabCalc(); await settle();
    const html = s.els["labcalc-body"].innerHTML;
    out.calcLines = (html.match(/data-lcalc-row="([^"]+)"/g) || []).map((m) => m.split('"')[1]);
    out.calcLoaded = { mockupFixed: /data-lcalc-mode="mockup"[\s\S]*?<option value="fixed" selected/.test(html),
                        companyRateShown: html.indexOf("$40.00 an hour") !== -1 };

    // THE LAYOUT HANZ SCREENSHOTTED, 2026-10-06 ("fix these ui"): three sections, each a heading
    // over its own card; plain tables; money in the page's .money box; no style attributes and no
    // class this page has no rule for (ghostlink, mkin and labcalc-h were borrowed by name from
    // markup.html and drew as bare browser defaults).
    s.api.renderTryIt();
    const all = html + s.els["labcalc-tryout"].innerHTML;
    out.layout = {
      sections: (html.match(/<div class="admin-section"><h2>([^<]+)<\/h2>/g) || [])
        .map((m) => m.replace(/.*<h2>|<\/h2>/g, "")),
      cards: (html.match(/<div class="card">/g) || []).length,
      itemsTable: all.indexOf("items-table") !== -1,
      inlineStyles: all.match(/style="[^"]*"/g) || [],
      unruledClasses: all.match(/class="[^"]*\b(ghostlink|mkin|labcalc-h)\b[^"]*"/g) || [],
      capsStatus: (all.match(/class="builtin"/g) || []).length,
      travelInMoneyBox: /<span class="money"><span>\$<\/span><input[^>]*data-travel-rate="travel_lodging"/.test(html),
      lineRateInMoneyBox: /<span class="money"><span>\$<\/span><input[^>]*data-lcalc="mockup" data-f="rate"/.test(html),
      editRateIsGhostButton: /<button class="btn ghost sm" type="button" data-labcalc-goto-labor>/.test(html),
      notSetOnceAcross: /data-lcalc-row="jointfill"[^]*?<td colspan="3"><span class="dash">Left blank on a new estimate<\/span><\/td><\/tr>/.test(html),
      tryBand: /<div class="areaband"><label for="labcalc-try-sf">Job SF<\/label><input id="labcalc-try-sf"[^>]*data-tryit-sf/.test(html),
    };

    // a SAVED fixed line shows in Try it with its cost: 3 guys x 0.5 days x $40 x 8h = $480
    s.api.renderTryIt();
    out.tryFixed = { hasMockup: s.els["labcalc-tryout"].innerHTML.indexOf("Mock-up") !== -1,
                     total: /data-tryit-total>\$480\.00</.test(s.els["labcalc-tryout"].innerHTML) };

    // pick From SF on Polishing: incomplete, so it is said in words and NOTHING is sent
    await s.api.calcEdit(sel("polishing", "sf"));
    out.sfIncomplete = { sent: s.calcPuts.length, alert: s.els["labcalc-alert"].textContent };
    await s.api.calcEdit(box("polishing", "crew", "3"));
    await s.api.calcEdit(box("polishing", "sf_per_day", "2,500"));
    await s.api.calcEdit(box("polishing", "hours_per_day", "10"));
    out.sfSaved = { puts: s.calcPuts.map((p) => p.body), alert: s.els["labcalc-alert"].textContent,
                    url: s.calcPuts[0].url };

    // Try it: 12,000 SF -> ceil(12000/2500) = 5 days; 3x5x$40x10h = $6,000; plus mock-up $480
    const putsBefore = s.calcPuts.length;
    s.api.setTry("12000"); s.api.renderTryIt();
    const t = s.els["labcalc-tryout"].innerHTML;
    out.trySf = { days5: /Polishing<\/td><td class="n">3<\/td><td class="n">5<\/td><td class="n">10<\/td>/.test(t),
                  total: /data-tryit-total>\$6,480\.00</.test(t), changedNothing: s.calcPuts.length === putsBefore };
    s.api.setTry("12501"); s.api.renderTryIt();
    out.tryRoundsUp = /Polishing<\/td><td class="n">3<\/td><td class="n">6<\/td>/.test(s.els["labcalc-tryout"].innerHTML);

    // back to Not set clears it on the server
    await s.api.calcEdit(sel("polishing", ""));
    out.cleared = { last: s.calcPuts[s.calcPuts.length - 1].body, savedGone: !("polishing" in s.api.saved()) };
  }
  // refused saves put the line back
  {
    const s = make({ calcPutStatus: 403 });
    s.api.renderLabCalc(); await settle();
    await s.api.calcEdit(sel("mockup", "fixed"));
    await s.api.calcEdit(box("mockup", "guys", "2"));
    await s.api.calcEdit(box("mockup", "days", "1"));
    out.calc403 = { alert: s.els["labcalc-alert"].textContent, kept: "mockup" in s.api.calc() };
  }
  // an absent table: the read fails, every line reads Not set, the tab still draws
  {
    const s = make({ calcReadFails: true });
    s.api.renderLabCalc(); await settle();
    const html = s.els["labcalc-body"].innerHTML;
    out.calcAbsent = { drew: html.indexOf('data-lcalc-row="polishing"') !== -1,
                       notSet: html.indexOf("Left blank on a new estimate") !== -1,
                       travelStill: html.indexOf("Lodging") !== -1,
                       tryEmpty: s.els["labcalc-tryout"].innerHTML.indexOf("No line has a mode saved") !== -1,
                       tryEmptyDesigned: /^<div class="lines-empty">No line has a mode saved/.test(
                         s.els["labcalc-tryout"].innerHTML) };
  }
  // a non-admin sees no controls
  {
    const s = make({ admin: false, calc: [{ line_id: "mockup", mode: "fixed", guys: 3, days: 1, hours_per_day: 10, rate: null }] });
    s.api.renderLabCalc(); await settle();
    const html = s.els["labcalc-body"].innerHTML;
    out.calcNonAdmin = { controls: (html.match(/data-lcalc="/g) || []).length +
                                   (html.match(/data-lcalc-mode/g) || []).length };
  }

  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
