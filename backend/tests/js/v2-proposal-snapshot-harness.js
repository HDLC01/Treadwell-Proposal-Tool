"use strict";
/* THE DRAFTS A v2 ESTIMATE HANDS THE PROPOSAL STEP, built by the real model.
 *
 * Sheets phase 4 (the Proposal step reads the v2 base, options and deducts). The Proposal step prices from `priced_tabs`
 * (rebuildPricing), `tab_opts` and `base_tab_id`, and a v2 estimate writes all three in one place: js/bid-model.js
 * composePricingSnapshot. So the drafts here are NOT typed by hand. Each is a bid built the way the estimate page builds one
 * (copySection, activateSection, pickBase, polishBid, priceTabs) and saved through composePricingSnapshot, then the patches
 * pickBase and the Sheets panel answer are laid over it, exactly as TW.setState merges them.
 *
 *   polish     the job is Polish. Polish is the base ($33,798). A cheaper Polish copy ("Polish 400 Grit") is on the proposal as
 *              a DEDUCT, an Epoxy sheet as a TOTAL ($28,086) and a Seal sheet as a TOTAL ($4,159).
 *   epoxy      the same bid with the Epoxy sheet made the base: Polish is demoted to an option (on, a total), the Polish copy is
 *              now DEARER than the base so its Deduct reads as an Add, and the job type follows the base.
 *   combined   Epoxy and Polish together as the base ($61,884); the job type is "combo" and the base id is null.
 *   copy       the Polish copy made the base ($29,955); the job stays Polish, and the root is demoted to an option.
 *
 * The prices are the engine's, with the same fixed material per role the other v2 harnesses use (polish 10,000, epoxy 8,000,
 * seal 1,500), so a figure here is a figure the engine answers, never one this file made up. `hand` repeats each sheet's total
 * as the model priced it, for a test to set beside what the page printed.
 *
 * Usage:   node v2-proposal-snapshot-harness.js <frontend-dir>   ->  one line of JSON { scenario: { state, hand } }
 *          or  require("./v2-proposal-snapshot-harness.js").build(B)  from another harness, with the model already loaded.
 */
const path = require("path");

const clone = (v) => JSON.parse(JSON.stringify(v));

const MATS = { polish: 10000, epoxy: 8000, seal: 1500 };
const CTX = { material: (e) => MATS[e.role], remodel_rate: null };

/** What the page prices the sections at, as the draft the Proposal step opens. `patch` is what pickBase answered (work_type,
 *  base_tab_id, tab_opts) and is merged over the save the way TW.setState merges. */
function build(B) {
  function root() {
    const m = B.freshModel();
    m.takeoff = [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 10000, unit: "SF" }];
    m.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 }];
    return m;
  }
  function save(model, tabOpts, patch) {
    const bid = B.polishBid(model, "Polish", CTX);
    const bids = B.priceTabs(model, CTX);
    const snap = B.composePricingSnapshot(model, { bid: bid, bids: bids, tabOpts: tabOpts });
    const hand = { Polish: bid.total };
    Object.keys(bids).forEach((k) => { hand[k] = bids[k].total; });
    return { state: Object.assign({}, patch || {}, snap), hand: hand };
  }

  // the bid: Polish root, a cheaper copy of it, an Epoxy sheet and a Seal sheet, all options
  let m = root();
  const copy = B.copySection(m, "Polish", {});
  m = copy.model;
  m.tabs.Copy1.takeoff[0].assembly_name = "Polish 400 Grit";
  m.tabs.Copy1.takeoff[0].measurement = 6000;
  m.tabs.Copy1.labor[0].days = 3;
  m = B.activateSection(m, "Epoxy", "option", { rules: [] });
  m.tabs.Epoxy.takeoff = [{ assembly_id: "e1", assembly_name: "Flake", measurement: 4000, unit: "SF" },
                          { assembly_id: "e2", assembly_name: "Cove", measurement: 300, unit: "LF" }];
  m.tabs.Epoxy.labor = [{ id: "installing", label: "Installing", guys: 3, days: 4, rate: 33 }];
  m = B.activateSection(m, "Seal", "option", {});

  // the copy starts off the proposal; the estimator turns it on as a Deduct (what the panel's switch and its Add / Deduct pair write)
  const opts0 = B.tabOptPatch({ tab_opts: copy.patch.tab_opts }, "Copy1", { is_option: true, show: true, price_mode: "deduct" }).tab_opts;
  const polish = save(m, opts0, { work_type: "polish" });

  const out = { polish: polish };
  [["epoxy", ["Epoxy"]], ["combined", ["Epoxy", "Polish"]], ["copy", ["Copy1"]]].forEach(function (pair) {
    const made = B.pickBase(m, pair[1], { state: { tab_opts: polish.state.tab_opts } });
    const opts = Object.assign({}, polish.state.tab_opts, made.patch.tab_opts || {});
    const s = save(made.model, opts, made.patch);
    s.state.tab_opts = clone(s.state.tab_opts);
    out[pair[0]] = s;
  });
  return clone(out);
}

module.exports = { build: build, MATS: MATS };

if (require.main === module) {
  const B = require(path.join(path.resolve(process.argv[2]), "js", "bid-model.js"));
  console.log(JSON.stringify(build(B)));
}
