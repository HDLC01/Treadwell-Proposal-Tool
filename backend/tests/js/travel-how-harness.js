// The Labor step's "how this is worked out" note, run on the real engine (bid-model.js).
// Wording cases the staging review found: a far job with Travel Labor switched off, and the note
// after the miles are cleared. The distance fills Travel Labor's hours again (2026-10-20), so a far
// answer writes the 5 hours of a 150 mile job here by itself, the cleared miles take them back, and
// what is left to word is a bid SAVED while the distance wrote the hours (2026-10-06 to 10-12): its
// figure and the old `hours_seed` marker with no distance behind them. The freshModel() bids below
// carry the OLDER Travel row (on auto, the man-days): an answer applied in a session puts that row on
// the crew's size (2026-10-20 audit), so a bid SAVED on the older row is built by taking the crew marker
// off the row the answer fills (`savedFar`). `crewBid` is the row a far answer fills on a
// NEW bid (guys on the crew's size), and `handBid` is the 2026-10-20 audit's remove-existing case:
// the how-note and the Lodging hint must give the same nights, and no man-days for the Travel guys.
const path = require("path");
const B = require(path.join(process.argv[2], "js", "bid-model.js"));

function far(miles) {
  const M = B.freshModel();
  M.labor[0].guys = 3; M.labor[0].days = 5;
  B.applyDistance(M, { miles: miles, source: "typed" });
  return M;
}

/** A bid SAVED on the older man-days auto: the hours the distance wrote, the old `hours_seed` marker, and no crew marker. */
function savedFar(miles) {
  const M = far(miles);
  M.labor.forEach((r) => { if (r.id === "travel") delete r.guys_follow; });
  B.syncAutoGuys(M);
  return M;
}

const off = far(150);
off.labor.forEach((r) => { if (r.id === "travel") r.enabled = false; });
const offHow = B.travelHow(off);

const cleared = far(150);
B.clearDistance(cleared);
const clearedHow = B.travelHow(cleared);

// The saved bid: the figure the distance wrote and its marker, and no distance stored.
const earlier = savedFar(150);
delete earlier.distance;
const earlierHow = B.travelHow(earlier);

// The same bid with its distance still on it, as saved (the older words), and the shipped row an answer was just applied to (the crew's words).
const still = savedFar(150);
const stillHow = B.travelHow(still);
const answered = far(150);
const answeredHow = B.travelHow(answered);

// A bid priced by Polish rev 2 counts auto Lodging and Per Diem the sheet's way (from labor dollars), so a crew with a
// prevailing-wage row owes more nights than it has man-days. The note has to say what the cost box and the bid charge.
function mixed(profile) {
  const M = B.freshModel();
  if (profile) M.profile = profile;
  M.takeoff = [{ assembly_id: "a", assembly_name: "Polish - S&P", measurement: 10000, unit: "SF" }];
  M.labor = [{ id: "a", label: "A", guys: 2, days: 5, rate: 33 }, { id: "b", label: "B", guys: 2, days: 5, rate: 66 }];
  M.travel = { lodging: { enabled: true, qty_auto: true, rate: 100 }, per_diem: { enabled: true, qty_auto: true, rate: 50 } };
  return M;
}
const rev2 = mixed("polish-rev2@1"), legacy = mixed();
const rev2Charge = B.travelCosts(rev2.travel, rev2.labor, B.travelOpts(rev2, B.ROOT_TAB));
const legacyCharge = B.travelCosts(legacy.travel, legacy.labor, B.travelOpts(legacy, B.ROOT_TAB));

// A NEW bid: the Travel row opens empty and off auto, so a far answer puts its guys on the crew's size (4 guys, 5 days of Polishing).
const crewBid = (() => {
  const M = B.freshModel();
  M.labor = [{ id: "polishing", label: "Polishing", guys: 4, days: 5, rate: 33 },
             { id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours", guys_auto: false }];
  M.travel = { lodging: { label: "Lodging", enabled: false, qty: "", qty_auto: false, rate: 70 },
               per_diem: { label: "Per Diem", enabled: false, qty: "", qty_auto: false, rate: 45 } };
  B.applyDistance(M, { miles: 150, source: "typed" });
  B.syncAutoGuys(M);
  return M;
})();
const crewHow = B.travelHow(crewBid);

// THE AUDIT'S REMOVE-EXISTING CASE: a bid priced the sheet's way (polish-rev3), Polishing 3 guys x 5 days and Joint filler 3 guys x 2
// days with Remove existing joint filler on (a fourth hand on that line), far, Lodging and Per Diem TYPED (10 nights and 10 days, the estimator's own).
// Guys x days is 21; the sheet's nights count the fourth hand's two days as well, 23. The crew is 4 (3 + the hand). `following` leaves the two lines
// blank instead, as a new bid opens them: a far answer then puts them on the sheet's count (2026-10-20, Hanz: "Fill them automatically").
function handBid(local, following) {
  const M = B.freshModel();
  M.profile = "polish-rev3@1";
  M.takeoff = [{ assembly_id: "a", assembly_name: "Polish - S&P", measurement: 10000, unit: "SF" }];
  M.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
             { id: "jointfill", label: "Joint filler", guys: 3, days: 2, rate: 33 },
             { id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours", guys_auto: false }];
  Object.assign(M.conditions, { joint_filler: true, remove_existing_jf: true });
  M.travel = following
    ? { lodging: { label: "Lodging", enabled: false, qty: "", qty_auto: false, rate: 70 },
        per_diem: { label: "Per Diem", enabled: false, qty: "", qty_auto: false, rate: 45 } }
    : { lodging: { label: "Lodging", enabled: false, qty: "10", qty_auto: false, qty_typed: true, rate: 70 },
        per_diem: { label: "Per Diem", enabled: false, qty: "10", qty_auto: false, qty_typed: true, rate: 45 } };
  B.applyDistance(M, { miles: local ? 30 : 150, source: "typed" });
  B.syncAutoGuys(M);
  return M;
}
const hand = handBid();
const handHow = B.travelHow(hand);
const handTrvOpts = B.travelOpts(hand, B.ROOT_TAB);
// ...the same with the nights ON AUTO (an older bid's lines, saved before 2026-10-12: auto and NO marker): the nights line explains the sheet's count, and the Travel
// guys still say no man-days.
const handAuto = handBid();
["lodging", "per_diem"].forEach((k) => { const l = handAuto.travel[k]; l.qty_auto = true; delete l.qty_typed; delete l.qty_follow; });
B.syncAutoGuys(handAuto);
const handAutoHow = B.travelHow(handAuto);
// ...and the lines a far answer FILLED (the new bid's, left blank until the answer): they follow the sheet's count, in Kyle's words, and say so once.
const handFollowing = handBid(false, true);
const handFollowingHow = B.travelHow(handFollowing);

console.log(JSON.stringify({
  crewBid: { text: crewHow.text, lines: crewHow.lines, guys: crewBid.labor[1].guys, follow: crewBid.labor[1].guys_follow },
  handBid: { lines: handHow.lines, text: handHow.text, crew: B.crewSize(hand), travelGuys: hand.labor[2].guys,
             lodgingHint: B.lodgingHint(hand, B.ROOT_TAB, false, hand.labor), perDiemHint: B.lodgingHint(hand, B.ROOT_TAB, false, hand.labor),
             sheetNights: B.travelQty({ qty_auto: true }, hand.labor, handTrvOpts), manDays: B.travelManDays(hand.labor),
             guysHint: B.travelGuysHint(hand, hand.labor[2], hand.labor) },
  handAuto: { lines: handAutoHow.lines, lodgingHint: B.lodgingHint(handAuto, B.ROOT_TAB, true, handAuto.labor) },
  handFollowing: { lines: handFollowingHow.lines, lodging: handFollowing.travel.lodging, perDiem: handFollowing.travel.per_diem,
                   lodgingHint: B.travelQtyHint(handFollowing, B.ROOT_TAB, "lodging", handFollowing.travel.lodging, handFollowing.labor),
                   perDiemHint: B.travelQtyHint(handFollowing, B.ROOT_TAB, "per_diem", handFollowing.travel.per_diem, handFollowing.labor),
                   charge: B.travelCosts(handFollowing.travel, handFollowing.labor, B.travelOpts(handFollowing, B.ROOT_TAB)) },
  rev2: { lines: B.travelHow(rev2).lines, charge: rev2Charge },
  legacy: { lines: B.travelHow(legacy).lines, charge: legacyCharge },
  travelOff: { text: offHow.text, hand: offHow.hand },
  cleared: { text: clearedHow.text },
  earlier: { text: earlierHow.text },
  withMiles: { text: stillHow.text },
  answered: { text: answeredHow.text, lines: answeredHow.lines },
}));
