// THE CELL MAPS OF KYLE'S ESTIMATE WORKBOOK. Data only: no arithmetic, no DOM, no fetch.
//
// WHAT THIS FILE IS. For each of the eleven tabs of backend/templates/estimate_sheet_5.7.xlsx that price a
// job (Epoxy, Polish, Seal, Seal (+Jnts), Epoxy blank, Leveling and the five Gyp tabs) it names the cells at
// the edges of the markup chain: where a job's material, labor, tooling, travel, fees and contingency come
// IN, the answers to the job questions (local, taxable, prevailing wage, remodel tax, hard bid), and where
// the bid comes OUT (sub-total, gross profit, super and PTO, soft costs, taxes, bond, total). Every entry
// also carries what the template holds in that cell today: the formula text (`formula`) or the constant
// (`value`).
//
// WHO READS IT.
//   - backend/tests/js/workbook-oracle.js types numbers into the `inputs`, `rates` and `flags` cells of the
//     real workbook, in the same engine the Estimate Review page runs, and records what comes out of the
//     `outputs` cells. The recorded answers are backend/tests/fixtures/oracle/<slug>.json.
//   - backend/tests/test_workbook_formula_pins.py reads every entry back out of the template and fails when
//     the formula or the constant in the template is not the one written here.
//   - Phases 8 to 17 of the v2 estimating program add the rates and the rules (the GP ladders, the shipping
//     tiers, the odd rules of docs/kyle-workbook-odd-rules.md) to THIS module, and the bid engine reads it.
//
// THE GROUPS of one tab's map
//   flags    The five job questions. Each is a Yes/No cell (flagWords says which words). Some tabs keep their
//            own answer, others read it from another tab, and the entry says which.
//   inputs   The boundary. The oracle OVERWRITES these cells with a plain number, so the chain starts after
//            them; the formula written here is what the takeoff would have put there. A case that does not
//            name an input writes 0.
//   rates    Cells the oracle may overwrite with a rate. A case that does not name one leaves the cell as
//            the template has it (its formula, or its constant).
//   fixed    Constants the chain reads and the oracle never writes: the template's own rates (shipping, burden,
//            super and PTO, soft costs). Recorded once per tab rather than in every case.
//   outputs  Answers read back out of the chain, in every case.
//   ladders  Which output cells step up or down with some other number: where the edges of a gross profit
//            ladder, a shipping tier or a hard-bid threshold live. `on` names the input or output the cell
//            steps on; `needs` names a flag that has to be on for the step to show.
//
// SHARED LAYOUTS. Several tabs are one layout copied. Those maps are `extend`ed from the tab they copy and
// state only what differs. test_workbook_formula_pins.py checks every entry of every map against the
// template, and checks the `families` list at the bottom (which entries differ between copies, and why)
// against the template too, so a difference nobody wrote down fails.
(function (root, factory) {
  var api = factory();
  root.TWBidProfiles = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var GROUPS = ["flags", "inputs", "rates", "fixed", "outputs"];

  /** An entry for a cell that holds a formula: what the template has there, as text. */
  function f(addr, formula) { return { addr: addr, formula: formula }; }
  /** An entry for a cell that holds a constant (null for an empty cell). */
  function c(addr, value) { return { addr: addr, value: value }; }

  /** A copy of `base` with the entries named in `patch` replaced. A patch that names an entry the base does
   *  not have throws: a typo here would otherwise add a cell nobody reads. */
  function extend(base, patch) {
    var has = Object.prototype.hasOwnProperty;
    Object.keys(patch).forEach(function (g) {
      if (GROUPS.indexOf(g) < 0) throw new Error("bid-profiles: " + g + " is not a group of a map");
    });
    var groups = GROUPS.map(function (g) {
      var own = patch[g] || {};
      Object.keys(own).forEach(function (name) {
        if (!has.call(base[g], name)) throw new Error("bid-profiles: " + g + "." + name + " is not in the map it extends");
      });
      return [g, Object.fromEntries(Object.keys(base[g]).map(function (name) {
        return [name, has.call(own, name) ? own[name] : base[g][name]];
      }))];
    });
    return Object.assign({ ladders: base.ladders }, Object.fromEntries(groups));
  }

  function deepFreeze(o) {
    if (o && typeof o === "object" && !Object.isFrozen(o)) {
      Object.freeze(o);
      Object.keys(o).forEach(function (k) { deepFreeze(o[k]); });
    }
    return o;
  }

  // Base maps. Each is one layout of Kyle's workbook; the tabs that share a layout are derived from it below.
  var EPOXY = {
    flags: {
      local:          c("B4", "Yes"),
      taxable:        c("B6", "Yes"),
      prevailingWage: c("D5", "No"),
      remodel:        c("D6", "No"),
      hardBid:        c("B5", "No"),
    },
    inputs: {
      material:    f("D40", "=ROUNDUP(SUM(D18:D39),0)"),
      labor:       f("D53", "=ROUNDUP(SUM(D47:D52),0)"),
      travelLabor: f("D52", "=(A52*B52*C52)"),
      tooling:     f("D62", "=SUM(D58:D61)"),
      travel:      f("D68", "=SUM(D65:D67)"),
      fees:        f("D83", "=ROUNDUP(B83*C83,0)"),
      contingency: c("D77", 0),
      sf:          c("E20", 0),
    },
    rates: {
      laborRate:   c("C47", 33),
      travelRate:  c("C52", 33),
      lodgingRate: c("C65", 70),
      perDiemRate: c("C66", 45),
      remodelPct:  f("B81", "=IF(D6=\"yes\",0.1,0)"),
      bondPct:     c("B84", 0),
    },
    fixed: {
      dayHours:  c("E45", "8 hour days"),
      burdenPct: c("C55", 0.12),
      superPct:  c("B75", 0.03),
      softPct:   c("B76", 0.13),
    },
    outputs: {
      shipPct:       f("B42", "=0.05+IF(D40<=5000,0.1,IF(D40<=10000,0.06,0.04))"),
      shipping:      f("D42", "=ROUNDUP(D40*B42,0)"),
      materialTotal: f("D43", "=SUM(D40:D42)"),
      escPct:        f("C54", "=IF(D5=\"Yes\",5%,0)"),
      escalation:    f("D54", "=ROUNDUP((D53*C54),0)"),
      burden:        f("D55", "=ROUNDUP((D53+D54)*C55,0)"),
      lodgingQty:    f("B65", "=IF(B4=\"No\",((D53-D52)/C47)/8)"),
      lodging:       f("D65", "=ROUNDUP(B65*C65,0)"),
      perDiemQty:    f("B66", "=B65"),
      perDiem:       f("D66", "=ROUNDUP(B66*C66,0)"),
      subTotal:      f("D70", "=ROUNDUP(SUM(D43,D53:D55,D62,D68),0)"),
      gpPct:         f("B73", "=IF(D70<6500,0.52,IF(D70<15000,0.45,IF(D70<22500,0.35,IF(D70<32500,0.32,0.3))))"),
      gp:            f("D73", "=ROUNDUP(SUM(D70,D80,D83)/(1-B73),0)-ROUNDUP(SUM(D70,D80),0)"),
      hardBidPct:    f("B74", "=IF(B5=\"yes\",IF(D70>=60000,-0.04,IF(B4=\"yes\",IF(D70>=13000,-0.025,0))))"),
      hardBid:       f("D74", "=ROUNDUP(SUM(D70,D73)*B74,0)"),
      superPto:      f("D75", "=ROUNDUP(SUM(D70:D74,D77,D80,D83)*B75,0)"),
      softCosts:     f("D76", "=(ROUNDUP(SUM(D70:D75,D77,D80,D83)*B76,0))+0"),
      salesTaxPct:   f("B80", "=IF($B$6=\"no\",0,0.09475)"),
      salesTax:      f("D80", "=ROUNDUP(SUM(D43)*B80,0)"),
      remodelTax:    f("D81", "=ROUNDUP(SUM(D53:D55,D62,D68,D73:D77,D83)*B81,0)"),
      taxes:         f("D82", "=SUM(D80:D81)"),
      bond:          f("D84", "=ROUNDUP(SUM(D70,D73,D74,D75:D77,D80,D81:D83)*B84,0)"),
      feesAndBond:   f("D85", "=ROUNDUP(SUM(D83:D84),0)"),
      total:         f("D88", "=SUM(D70,D73:D77,D82,D85)"),
      perSf:         f("C88", "=D88/C87"),
    },
    ladders: [
      { cell: "shipPct", on: "material" },
      { cell: "gpPct", on: "subTotal" },
      { cell: "hardBidPct", on: "subTotal", needs: "hardBid" }
    ],
  };
  var POLISH = {
    flags: {
      local:          c("B4", "Yes"),
      taxable:        f("B6", "=Epoxy!B6"),
      prevailingWage: f("D5", "=Epoxy!D5"),
      remodel:        f("D6", "=Epoxy!D6"),
      hardBid:        c("B5", "No"),
    },
    inputs: {
      material:    f("D31", "=ROUNDUP(SUM(D17:D30),0)"),
      labor:       f("D45", "=ROUNDUP(SUM(D37:D44),0)"),
      travelLabor: f("D44", "=(A44*B44*C44)"),
      tooling:     f("D55", "=SUM(D50:D54)"),
      travel:      f("D61", "=SUM(D58:D60)"),
      fees:        f("D77", "=ROUNDUP(B77*C77,0)"),
      contingency: c("D71", 0),
      sf:          c("E18", 0),
    },
    rates: {
      laborRate:   c("C37", 33),
      travelRate:  c("C44", 33),
      lodgingRate: c("C58", 70),
      perDiemRate: c("C59", 45),
      remodelPct:  f("B75", "=IF(D6=\"yes\",0.1,0)"),
      bondPct:     c("B78", 0),
    },
    fixed: {
      dayHours:  c("E35", "8 hour days"),
      shipPct:   c("B32", 0.02),
      burdenPct: c("C47", 0.12),
      superPct:  c("B69", 0.027),
      softPct:   c("B70", 0.16),
    },
    outputs: {
      shipping:      f("D32", "=ROUNDUP(D31*B32,0)"),
      materialTotal: f("D33", "=SUM(D31:D32)"),
      escPct:        f("C46", "=IF(D5=\"Yes\",5%,0)"),
      escalation:    f("D46", "=ROUNDUP((D45*C46),0)"),
      burden:        f("D47", "=ROUNDUP((D45+D46)*C47,0)"),
      lodgingQty:    f("B58", "=IF(B4=\"No\",((D45-D44)/C37)/8)"),
      lodging:       f("D58", "=ROUNDUP(B58*C58,0)"),
      perDiemQty:    f("B59", "=B58"),
      perDiem:       f("D59", "=ROUNDUP(B59*C59,0)"),
      subTotal:      f("D64", "=ROUNDUP(SUM(D33,D45:D47,D55,D61),0)"),
      gpPct:         f("B67", "=IF(D64<6500,0.52,IF(D64<15000,0.45,IF(D64<22500,0.35,IF(D64<32500,0.32,0.3))))"),
      gp:            f("D67", "=ROUNDUP(SUM(D64,D74,D77)/(1-B67),0)-ROUNDUP(SUM(D64,D74,D77),0)"),
      hardBidPct:    f("B68", "=IF(B5=\"yes\",IF(D64>=60000,-0.04,IF(B4=\"yes\",IF(D64>=13000,-0.025,0))))"),
      hardBid:       f("D68", "=ROUNDUP(SUM(D64,D67)*B68,0)"),
      superPto:      f("D69", "=ROUNDUP(SUM(D64:D68,D71,D74,D77)*B69,0)"),
      softCosts:     f("D70", "=(ROUNDUP(SUM(D64:D69,D71,D74,D77)*B70,0))+0"),
      salesTaxPct:   f("B74", "=IF($B$6=\"no\",0,0.09475)"),
      salesTax:      f("D74", "=ROUNDUP(SUM(D33)*B74,0)"),
      remodelTax:    f("D75", "=ROUNDUP(SUM(D45:D47,D55,D61,D67:D71,D77)*B75,0)"),
      taxes:         f("D76", "=SUM(D74:D75)"),
      bond:          f("D78", "=ROUNDUP(SUM(D64,D67,D68,D69:D71,D74,D75:D77)*B78,0)"),
      feesAndBond:   f("D79", "=ROUNDUP(SUM(D77:D78),0)"),
      total:         f("D82", "=SUM(D64,D67:D71,D76,D79)"),
      perSf:         f("C82", "=D82/C81"),
    },
    ladders: [
      { cell: "gpPct", on: "subTotal" },
      { cell: "hardBidPct", on: "subTotal", needs: "hardBid" }
    ],
  };
  var EPOXY_BLANK = {
    flags: {
      local:          f("B4", "=Epoxy!B4"),
      taxable:        f("B6", "=Epoxy!B6"),
      prevailingWage: f("D5", "=Epoxy!D5"),
      remodel:        f("D6", "=Epoxy!D6"),
      hardBid:        c("B5", "No"),
    },
    inputs: {
      material:    f("D37", "=ROUNDUP(SUM(D18:D36),0)"),
      overage:     f("D38", "=ROUNDUP(SUM(D18:D20,D21:D28,D29:D32,D33:D36)*B38,0)"),
      labor:       f("D50", "=ROUNDUP(SUM(D44:D49),0)"),
      travelLabor: f("D49", "=(A49*B49*C49)"),
      tooling:     f("D59", "=SUM(D55:D58)"),
      travel:      f("D65", "=SUM(D62:D64)"),
      fees:        f("D80", "=ROUNDUP(B80*C80,0)"),
      contingency: c("D74", 0),
      sf:          c("E20", 0),
    },
    rates: {
      overagePct:  c("B38", 0.06),
      laborRate:   c("C44", 33),
      travelRate:  c("C49", 33),
      lodgingRate: c("C62", 70),
      perDiemRate: c("C63", 45),
      remodelPct:  f("B78", "=IF(D6=\"yes\",0.1,0)"),
      bondPct:     c("B81", 0),
    },
    fixed: {
      dayHours:  c("E42", "8 hour days"),
      burdenPct: c("C52", 0.12),
      superPct:  c("B72", 0.03),
      softPct:   c("B73", 0.13),
    },
    outputs: {
      shipPct:       f("B39", "=(0.05+IF(D37<=5000,0.1,IF(D37<=10000,0.06,0.04)))"),
      shipping:      f("D39", "=ROUNDUP(D37*B39,0)"),
      materialTotal: f("D40", "=SUM(D37:D39)"),
      escPct:        f("C51", "=IF(D5=\"Yes\",5%,0)"),
      escalation:    f("D51", "=ROUNDUP((D50*C51),0)"),
      burden:        f("D52", "=ROUNDUP((D50+D51)*C52,0)"),
      lodgingQty:    f("B62", "=IF(B4=\"No\",((D50-D49)/C44)/8)"),
      lodging:       f("D62", "=ROUNDUP(B62*C62,0)"),
      perDiemQty:    f("B63", "=B62"),
      perDiem:       f("D63", "=ROUNDUP(B63*C63,0)"),
      subTotal:      f("D67", "=ROUNDUP(SUM(D40,D50:D52,D59,D65),0)"),
      gpPct:         f("B70", "=IF(D67<6500,0.52,IF(D67<15000,0.45,IF(D67<22500,0.35,IF(D67<32500,0.32,0.3))))"),
      gp:            f("D70", "=ROUNDUP(SUM(D67,D77,D80)/(1-B70),0)-ROUNDUP(SUM(D67,D77,D80),0)"),
      hardBidPct:    f("B71", "=IF(B5=\"yes\",IF(D67>=60000,-0.04,IF(B4=\"yes\",IF(D67>=13000,-0.025,0))))"),
      hardBid:       f("D71", "=ROUNDUP(SUM(D67,D70)*B71,0)"),
      superPto:      f("D72", "=ROUNDUP(SUM(D67:D71,D74,D77,D80)*B72,0)"),
      softCosts:     f("D73", "=(ROUNDUP(SUM(D67:D72,D74,D77,D80)*B73,0))+0"),
      salesTaxPct:   f("B77", "=IF($B$6=\"no\",0,0.09475)"),
      salesTax:      f("D77", "=ROUNDUP(SUM(D40)*B77,0)"),
      remodelTax:    f("D78", "=ROUNDUP(SUM(D50:D52,D59,D65,D70:D74,D80)*B78,0)"),
      taxes:         f("D79", "=SUM(D77:D78)"),
      bond:          f("D81", "=ROUNDUP(SUM(D67,D70,D71,D72:D74,D77,D78:D80)*B81,0)"),
      feesAndBond:   f("D82", "=ROUNDUP(SUM(D80:D81),0)"),
      total:         f("D85", "=SUM(D67,D70:D74,D79,D82)"),
      perSf:         f("C85", "=D85/C84"),
    },
    ladders: [
      { cell: "shipPct", on: "material" },
      { cell: "gpPct", on: "subTotal" },
      { cell: "hardBidPct", on: "subTotal", needs: "hardBid" }
    ],
  };
  var LEVELING = {
    flags: {
      local:          c("B4", "Yes"),
      taxable:        c("B6", "Yes"),
      prevailingWage: f("D5", "=Epoxy!D5"),
      remodel:        f("D6", "=Epoxy!D6"),
      hardBid:        c("B5", "No"),
    },
    inputs: {
      material:    f("D37", "=ROUNDUP(SUM(D18:D36),0)"),
      overage:     f("D38", "=ROUNDUP(SUM(D21:D27)*B38,0)"),
      labor:       f("D49", "=ROUNDUP(SUM(D44:D48),0)"),
      travelLabor: f("D48", "=A48*B48*C48"),
      tooling:     f("D58", "=SUM(D54:D57)"),
      travel:      f("D64", "=SUM(D61:D63)"),
      fees:        f("D79", "=ROUNDUP(B79*C79,0)"),
      contingency: c("D73", 0),
      sf:          c("E20", 0),
    },
    rates: {
      overagePct:  c("B38", 0),
      laborRate:   c("C44", 33.66),
      travelRate:  c("C48", 33.66),
      travelHours: c("B48", 1),
      lodgingRate: c("C61", 70),
      perDiemRate: c("C62", 45),
      remodelPct:  f("B77", "=IF(D6=\"yes\",0.1,0)"),
      bondPct:     c("B80", 0),
    },
    fixed: {
      dayHours:  c("E42", "10 hour days"),
      burdenPct: c("C51", 0.12),
      superPct:  c("B71", 0.03),
      softPct:   c("B72", 0.13),
    },
    outputs: {
      shipPct:       f("B39", "=0.05+IF(D37<=5000,0.1,IF(D37<=10000,0.06,0.04))"),
      shipping:      f("D39", "=ROUNDUP(D37*B39,0)"),
      materialTotal: f("D40", "=SUM(D37:D39)"),
      escPct:        f("C50", "=IF(D5=\"Yes\",5%,0)"),
      escalation:    f("D50", "=ROUNDUP((D49*C50),0)"),
      burden:        f("D51", "=ROUNDUP((D49+D50)*C51,0)"),
      lodgingQty:    f("B61", "=IF(B4=\"No\",((D49-D48)/C44)/8)"),
      lodging:       f("D61", "=ROUNDUP(B61*C61,0)"),
      perDiemQty:    f("B62", "=B61"),
      perDiem:       f("D62", "=ROUNDUP(B62*C62,0)"),
      subTotal:      f("D66", "=ROUNDUP(SUM(D40,D49,D58,D64,D51),0)"),
      gpPct:         f("B69", "=IF(D66<6500,0.52,IF(D66<15000,0.45,IF(D66<22500,0.35,IF(D66<32500,0.32,0.3))))"),
      gp:            f("D69", "=ROUNDUP(SUM(D66,D76,D79)/(1-B69),0)-ROUNDUP(SUM(D66,D76,D79,),0)"),
      hardBidPct:    f("B70", "=IF(B5=\"yes\",IF(D66>=60000,-0.04,IF(B4=\"yes\",IF(D66>=13000,-0.025,0))))"),
      hardBid:       f("D70", "=ROUNDUP(SUM(D66,D69)*B70,0)"),
      superPto:      f("D71", "=ROUNDUP(SUM(D66:D70,D73,D76,D79)*B71,0)"),
      softCosts:     f("D72", "=(ROUNDUP(SUM(D66:D71,D73,D76,D79)*B72,0))+0"),
      salesTaxPct:   f("B76", "=IF($B$6=\"no\",0,0.09475)"),
      salesTax:      f("D76", "=ROUNDUP(SUM(D40)*B76,0)"),
      remodelTax:    f("D77", "=ROUNDUP(SUM(D49:D51,D58,D64,D69:D73,D79)*B77,0)"),
      taxes:         f("D78", "=SUM(D76:D77)"),
      bond:          f("D80", "=ROUNDUP(SUM(D66,D69,D70,D71:D73,D76,D77:D79)*B80,0)"),
      feesAndBond:   f("D81", "=ROUNDUP(SUM(D79:D80),0)"),
      total:         f("D84", "=SUM(D66,D69:D73,D78,D81)"),
      perSf:         f("C84", "=D84/C83"),
    },
    ladders: [
      { cell: "shipPct", on: "material" },
      { cell: "gpPct", on: "subTotal" },
      { cell: "hardBidPct", on: "subTotal", needs: "hardBid" }
    ],
  };
  var GYP = {
    flags: {
      local:          c("B5", "Yes"),
      taxable:        c("B8", "Yes"),
      prevailingWage: f("D7", "=Epoxy!D5"),
      remodel:        f("D8", "=Epoxy!D6"),
      hardBid:        c("B7", "No"),
    },
    inputs: {
      gyp:           f("E23", "=B23*D23"),
      extras:        f("E27", "=B27*D27"),
      sand:          f("E33", "=B33*D33"),
      soundMat:      f("E36", "=B36*D36"),
      soundMatRolls: f("B36", "=ROUNDUP(IF(A36=O37,(F24/Q37),IF(A36=O38,(F24/Q38),IF(A36=O39,(F24/Q39),IF(A36=O40,(F24/Q40),IF(A36=O42,(F24/Q42),IF(A36=O43,(F24/Q43),IF(A36=O44,(F24/Q44),\"none\")))))))*(1+G20),0)"),
      labor:         f("E52", "=ROUNDUP(SUM(E45:E51),0)"),
      travelLabor:   f("E51", "=A51*B51*C51"),
      tooling:       f("E61", "=SUM(E57:E60)"),
      travel:        f("E67", "=SUM(E64:E66)"),
      fees:          f("E82", "=ROUNDUP(B82*D82,0)"),
      contingency:   c("E76", 0),
      sf:            f("B43", "=F22"),
    },
    rates: {
      laborRate:   c("C45", 33.66),
      travelRate:  c("C51", 33.66),
      lodgingRate: c("C64", 70),
      perDiemRate: c("C65", 45),
      remodelPct:  f("B80", "=IF(D8=\"yes\",0.1,0)"),
      bondPct:     c("B83", 0),
    },
    fixed: {
      dayHours:     c("F43", "10 hour days"),
      escPctMat:    c("B39", 0.08),
      shipGypPct:   c("B40", 0.2),
      shipOtherPct: c("D40", 0.1),
      escPct:       c("C53", 0.05),
      burdenPct:    c("C54", 0.12),
      hardBidPct:   c("B73", null),
      superPct:     c("B74", 0.041),
      truckload:    f("H36", "=IF(A36=O37,280,IF(A36=O38,208,IF(A36=O39,208,IF(A36=O40,260,IF(A36=O42,384,IF(A36=O43,384,IF(A36=O44,384,\"error\")))))))"),
    },
    outputs: {
      materialSubTotal:   f("E38", "=ROUNDUP(SUM(E20:E37),0)"),
      materialEscalation: f("E39", "=ROUNDUP(SUM(E23:E31,E35:E37)*B39,0)"),
      shipping:           f("E40", "=(ROUNDUP(SUM(E20:E26)*B40,0))+(ROUNDUP(((SUM(E27:E31,IF(B36<H36,(SUM(E35:E37)),0)))*D40),0))"),
      materialTotal:      f("E41", "=SUM(E38:E40)"),
      escalation:         f("E53", "=ROUNDUP(((E52)*C53),0)"),
      burden:             f("E54", "=ROUNDUP((E52+E53)*C54,0)"),
      lodgingQty:         f("B64", "=IF(B5=\"No\",((E52-E51)/C46)/10)"),
      lodging:            f("E64", "=ROUNDUP(B64*C64,0)"),
      perDiemQty:         f("B65", "=B64"),
      perDiem:            f("E65", "=ROUNDUP(B65*C65,0)"),
      subTotal:           f("E69", "=ROUNDUP(SUM(E41,E52:E54,E61,E67),0)"),
      gpPct:              f("B72", "=IF(E69<15000,0.45,IF(E69<25000,0.4,IF(E69<50000,0.35,IF(E69<75000,0.33,IF(E69<100000,0.28,IF(E69<150000,0.26,0.24))))))"),
      gp:                 f("E72", "=ROUNDUP(SUM(E69,E79,E82)/(1-B72),0)-ROUNDUP(SUM(E69,E79,E82),0)"),
      hardBid:            f("E73", "=ROUNDUP(SUM(E69,E72)*B73,0)"),
      superPto:           f("E74", "=ROUNDUP(SUM(E69:E73,E76,E79,E82)*B74,0)"),
      softPct:            f("B75", "=IF(OR(B5=\"Yes\",B5=\"No\"),IF(B5=\"Yes\",0.09,0.1) - IF(E69>334900,0.05,IF(E69>234450,0.035,0)),\"error\")"),
      softCosts:          f("E75", "=(ROUNDUP(SUM(E69:E74,E76,E79,E82)*B75,0))+0"),
      salesTaxPct:        f("B79", "=IF($B$8=\"no\",0,0.09475)"),
      salesTax:           f("E79", "=ROUNDUP(SUM(E41)*B79,0)"),
      remodelTax:         f("E80", "=ROUNDUP(SUM(E52:E54,E61,E67,E72:E76,E82)*B80,0)"),
      taxes:              f("E81", "=SUM(E79:E80)"),
      bond:               f("E83", "=ROUNDUP(SUM(E69,E72,E73,E74:E76,E79,E80:E82)*B83,0)"),
      feesAndBond:        f("E84", "=ROUNDUP(SUM(E82:E83),0)"),
      total:              f("E87", "=SUM(E69,E72:E76,E81,E84)"),
      perSf:              f("C87", "=E87/C86"),
    },
    ladders: [
      { cell: "gpPct", on: "subTotal" },
      { cell: "softPct", on: "subTotal" }
    ],
  };

  // Derived maps: only what differs from the tab each one is built on is written down.
  var SEAL = extend(POLISH, {
    flags: {
      taxable: f("B6", "=Polish!B6"),
    },
    outputs: {
      gpPct: f("B67", "=IF(D64<6500,0.52,IF(D64<15000,0.45,IF(D64<22500,0.35,IF(D64<32500,0.32,IF(D64<42500,0.3,0.28)))))"),
    },
  });
  var SEAL_JNTS = extend(SEAL, {
    flags: {
      local: f("B4", "=Seal!B4"),
      taxable: f("B6", "=Seal!B6"),
      prevailingWage: f("D5", "=Seal!D5"),
      remodel: f("D6", "=Seal!D6"),
      hardBid: f("B5", "=Seal!B5"),
    },
    inputs: {
      sf: f("E18", "=Seal!E18"),
    },
    rates: {
      laborRate: f("C37", "=Seal!C37"),
      travelRate: f("C44", "=Seal!C44"),
      remodelPct: f("B75", "=Seal!B75"),
      bondPct: f("B78", "=Seal!B78"),
    },
    fixed: {
      burdenPct: f("C47", "=Seal!C47"),
    },
  });
  var GYP_N12ULTRA = extend(GYP, {
    flags: {
      local: f("B5", "='Gyp (USG 1-8\")'!B5"),
      taxable: f("B8", "='Gyp (USG 1-8\")'!B8"),
      prevailingWage: f("D7", "='Gyp (USG 1-8\")'!D7"),
      remodel: f("D8", "='Gyp (USG 1-8\")'!D8"),
    },
    fixed: {
      escPct: f("C53", "='Gyp (USG 1-8\")'!C53"),
    },
  });
  var GYP_N25 = extend(GYP, {
    flags: {
      local: f("B5", "='Gyp (USG 1-8\")'!B5"),
      taxable: f("B8", "='Gyp (USG 1-8\")'!B8"),
      prevailingWage: f("D7", "='Gyp (USG 1-8\")'!D7"),
      remodel: f("D8", "='Gyp (USG 1-8\")'!D8"),
    },
    fixed: {
      escPct: f("C53", "='Gyp (USG 1-8\")'!C53"),
    },
  });
  var GYP_GWORX = extend(GYP, {
    flags: {
      local: f("B5", "='Gyp (USG 1-8\")'!B5"),
      taxable: f("B8", "='Gyp (USG 1-8\")'!B8"),
      prevailingWage: f("D7", "='Gyp (USG 1-8\")'!D7"),
      remodel: f("D8", "='Gyp (USG 1-8\")'!D8"),
    },
    fixed: {
      escPct: f("C53", "='Gyp (USG 1-8\")'!C53"),
    },
  });
  var GYP_FR = extend(GYP, {
    inputs: {
      soundMatRolls: f("B36", "=ROUNDUP(IF(A36=N37,(F24/P37),IF(A36=N38,(F24/P38),IF(A36=N39,(F24/P39),IF(A36=N42,(F24/P42),IF(A36=N43,(F24/P43),IF(A36=N44,(F24/P44),\"none\"))))))*(1+G20),0)"),
    },
    fixed: {
      escPct: f("C53", "='Gyp (USG 1-8\")'!C53"),
      truckload: c("H36", 448),
    },
    outputs: {
      gp: f("E72", "=ROUNDUP(SUM(E69,E79,E82)/(1-B72),0)-ROUNDUP(SUM(E69,E79,E82,),0)"),
    },
  });

  // ── the eleven priced tabs, in the order the oracle records them ──
  var T_GYP_FIRST = "Gyp (USG 1-8\")";
  var T_GYP_N12 = "Gyp (USG N12ULTRA)";
  var T_GYP_N25 = "Gyp (USG N25 1-4\")";
  var T_GYP_GW = "Gyp (GWorx SC190)";
  var T_GYP_FR = "Gyp (FR)";

  var TABS = [
    // [tab id in the workbook, golden file name, layout family, map]
    ["Epoxy", "epoxy", "epoxy", EPOXY],
    ["Polish", "polish", "polish", POLISH],
    ["Seal", "seal", "polish", SEAL],
    ["Seal (+Jnts)", "seal-jnts", "polish", SEAL_JNTS],
    ["Epoxy blank", "epoxy-blank", "epoxy-blank", EPOXY_BLANK],
    ["Leveling", "leveling", "leveling", LEVELING],
    [T_GYP_FIRST, "gyp-usg-1-8", "gyp", GYP],
    [T_GYP_N12, "gyp-usg-n12ultra", "gyp", GYP_N12ULTRA],
    [T_GYP_N25, "gyp-usg-n25-1-4", "gyp", GYP_N25],
    [T_GYP_GW, "gyp-gworx-sc190", "gyp", GYP_GWORX],
    [T_GYP_FR, "gyp-fr", "gyp", GYP_FR]
  ];

  var priced = [];
  var sheets = {};
  TABS.forEach(function (t) {
    priced.push(t[0]);
    sheets[t[0]] = {
      slug: t[1], family: t[2],
      flags: t[3].flags, inputs: t[3].inputs, rates: t[3].rates, fixed: t[3].fixed,
      outputs: t[3].outputs, ladders: t[3].ladders
    };
  });

  // ── where copies of a layout differ from the tab they copy, and why ──
  // kind "mirror": the member's cell is the formula `=<base tab>!<same address>`, it reads the base tab.
  // kind "differs": the member's cell holds something else; the reason says what.
  // Every other entry of the map must be identical in the member and the base, formula text and constants.
  // test_workbook_formula_pins.py enforces both halves against the template.
  var families = {
    gyp: {
      base: T_GYP_FIRST,
      members: [T_GYP_N12, T_GYP_N25, T_GYP_GW, T_GYP_FR],
      deltas: [
        { sheets: [T_GYP_N12, T_GYP_N25, T_GYP_GW, T_GYP_FR], cells: ["fixed.escPct"], kind: "mirror",
          why: "the 5% labor escalation is typed once, on the first Gyp tab; the other four read it from there" },
        { sheets: [T_GYP_N12, T_GYP_N25, T_GYP_GW],
          cells: ["flags.local", "flags.taxable", "flags.prevailingWage", "flags.remodel"], kind: "mirror",
          why: "these three tabs follow the first Gyp tab's answers; Gyp (FR) keeps its own" },
        { sheets: [T_GYP_FR], cells: ["inputs.soundMatRolls"], kind: "differs",
          why: "the sound-mat table sits one column further left on this tab, so the formula points at other cells" },
        { sheets: [T_GYP_FR], cells: ["fixed.truckload"], kind: "differs",
          why: "a typed 448 rolls to a truckload where the other tabs look the figure up by product" },
        { sheets: [T_GYP_FR], cells: ["outputs.gp"], kind: "differs",
          why: "the same sum with a stray empty argument at the end, SUM(a,b,c,); it does not change the number" }
      ]
    },
    seal: {
      base: "Seal",
      members: ["Seal (+Jnts)"],
      deltas: [
        { sheets: ["Seal (+Jnts)"],
          cells: ["flags.local", "flags.taxable", "flags.prevailingWage", "flags.remodel", "flags.hardBid",
                  "inputs.sf", "rates.laborRate", "rates.travelRate", "rates.remodelPct", "rates.bondPct",
                  "fixed.burdenPct"],
          kind: "mirror",
          why: "Seal (+Jnts) is the Seal tab priced again with joints: every answer and rate it needs is read from Seal" }
      ]
    },
    polishSeal: {
      base: "Polish",
      members: ["Seal"],
      deltas: [
        { sheets: ["Seal"], cells: ["flags.taxable"], kind: "mirror",
          why: "Seal reads the Taxable answer from the Polish tab (Polish reads it from Epoxy)" },
        { sheets: ["Seal"], cells: ["outputs.gpPct"], kind: "differs",
          why: "Seal's gross profit ladder has one more rung: 30% up to 42,500 and 28% from there" }
      ]
    }
  };

  return deepFreeze({
    version: 1,
    flagWords: { on: "Yes", off: "No" },
    priced: priced,
    sheets: sheets,
    families: families
  });
});
