/* Fill the County remodel tax box from the job address, once, for both intake pages.
 *
 * Hanz, 2026-10-13, looking at the empty county box on intake: "shouldn't this autofill based on
 * the address?" Yes. The address is already typed (or picked from the suggestions) a few inches
 * above it, and the server can turn an address into a county with the same free US Census
 * geocoder it already uses for the distance (POST /api/county, backend/distance.py).
 *
 *   TWCountyAutofill.mount({ county, address, city, state, zip })
 *
 *   county   the object js/county-picker.js's mount() returned. All it needs from it is the
 *            picker's own public API: autoFill(), whenLoaded(), hasPick(), isAuto().
 *   address, city, state, zip   the four input elements.
 *
 * Returns { onPick(p), check() }. js/address-lookup.js calls onPick(p) when the estimator picks a
 * row from the suggestions (its `onPick` option), with { county, state, place } off the Photon
 * result: that is an INSTANT first guess, shown before the Census answer lands and replaced by it
 * when the two disagree. A typed address is checked when a field is committed (the `change`
 * event, i.e. on leaving the box), not on every keystroke, so a half-typed street never costs a
 * lookup.
 *
 * THE RULES, all of which live in the picker so both pages get them from one place:
 *   - A county the estimator picked, typed, or that a saved draft already holds is NEVER
 *     overwritten. Nothing here reads the draft: opening a saved bid fires no field event, so no
 *     lookup runs and the saved county stays exactly as it was.
 *   - A fill is remembered as a fill (picker.isAuto), so changing the address later re-fills it,
 *     and picking or clearing by hand makes it theirs.
 *   - A county or city the list has no row for leaves the box empty. Nothing is approximated. A city
 *     the list has no row for, inside a county it does have, gets the county rate and a sentence
 *     saying the city may charge more (picker.autoFill).
 *   - A fill belongs to the address it was made for. When that address is gone (the street emptied) or
 *     nothing answers for the new one, the fill is removed; a county picked or cleared by hand never is.
 *   - Any failure (no answer, slow, address not found) is silent: this is a convenience, and the box
 *     still works by hand. It writes nothing, and a later change asks again.
 *   - The estimator typing in the county search box is never interrupted: the answer waits and the same
 *     address is asked again later.
 */
(function () {
  "use strict";

  function val(el) { return el && el.value != null ? String(el.value) : ""; }

  /** The same "enough to look anything up" rule as the server's clean_address: a street AND a way
   *  to place it (city and state, or a zip). "" when there is not enough. Also the dedupe key, so
   *  the same address is never asked twice in a row. */
  function addressKey(address, city, state, zip) {
    function one(v) { return String(v == null ? "" : v).replace(/\s+/g, " ").trim().toLowerCase(); }
    var street = one(address), c = one(city), st = one(state).slice(0, 2), z = one(zip);
    if (!street) return "";
    if (!((c && st) || z)) return "";
    return [street, c, st, z].join("|");
  }

  function mount(opts) {
    opts = opts || {};
    var county = opts.county;
    var els = { address: opts.address, city: opts.city, state: opts.state, zip: opts.zip };
    if (!county || !els.address) return null;
    var delay = opts.delayMs == null ? 350 : opts.delayMs;

    var seq = 0;                 // each lookup gets a number; only the newest may write
    var lastKey = "";            // the address last looked up, so the same one is not asked twice
    var fillKey = null;          // the address the county on screen was filled for; null when none
    var timer = null;

    function keyNow() {
      return addressKey(val(els.address), val(els.city), val(els.state), val(els.zip));
    }

    /** A county the address filled belongs to THAT address. When the address has gone (the street was
     *  emptied) or has moved on and nothing answered for the new one, the fill is taken away, because
     *  the note under it still says "Filled from the address" and would be false. Only a fill: a
     *  county picked or cleared by hand is never touched. The dedupe key is dropped with it, so the
     *  same address typed again is looked up again. */
    function dropStaleFill(key) {
      if (!county.isAuto() || fillKey === key) return;
      if (county.clearFill) county.clearFill();
      fillKey = null;
      lastKey = "";                // the same address typed again is asked again
    }

    /** What the picker did with an answer, and what that means for the next one. */
    function settle(res, key) {
      if (res === "filled" || res === "same") fillKey = key;
      else if (res === "none") fillKey = null;              // the picker cleared the old fill itself
      else if (res === "pending" || res === "busy") lastKey = "";   // nothing written: ask again later
    }

    /** The city to look for in the list. The Census place, unless that cannot be trusted: it said so
     *  (it matched the street in another zip than the typed one), or there was no zip to confirm it
     *  and the city the estimator typed has a verified row in the county the Census found. Without a
     *  zip the geocoder can match 701 N 7th St, Kansas City KS into Edwardsville (real, 2026-10-13);
     *  with a matching zip the Census place stands, since a postal city is not always the legal one. A
     *  typed city with no row (Shawnee Mission) or a row in another county never beats the Census. */
    function placeFor(ans) {
      var typed = val(els.city);
      if (ans.place_sure === false) return typed;
      if (typed && val(els.zip).replace(/\D/g, "").length < 5) {
        var row = county.resolveArea(ans.county, ans.state, typed);
        if (row && row.kind === "city") return typed;
      }
      return ans.place;
    }

    /** One POST. Resolves to the parsed body, or null for ANY failure; never rejects. */
    async function ask() {
      try {
        var TW = window.TW;
        if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready;
        var res = await fetch(TW.resolveApiBase() + "/api/county", {
          method: "POST",
          headers: TW.authHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ address: val(els.address), city: val(els.city),
                                 state: val(els.state), zip: val(els.zip) }),
          signal: (typeof AbortSignal !== "undefined" && AbortSignal.timeout)
            ? AbortSignal.timeout(14000) : undefined
        });
        return await res.json();
      } catch (e) { return null; }
    }

    /** Look the address up and apply the answer, unless a person has the box or the address moved
     *  on while the answer was on its way. Never throws. */
    async function check() {
      try {
        var key = keyNow();
        if (!key) {
          // Not an address any more (the street was emptied): the fill made for it goes.
          dropStaleFill(key);   // the address is gone
          return;
        }
        if (key === lastKey) return;
        // Their county, picked or cleared. Skipped BEFORE the request, so a bid they have settled
        // spends no lookup at all.
        if (county.isTheirs()) return;
        lastKey = key;
        var mine = ++seq;
        // A newer address (or a second lookup) owns the box now: this answer is for one it has left.
        var stale = function () { return mine !== seq || key !== keyNow(); };
        var ans = await (opts.ask ? opts.ask() : ask());
        if (stale()) return;
        if (!ans || ans.ok !== true) {
          // No answer for THIS address: a later change retries, and a county filled for an older one
          // is not left standing as if it were this one's.
          lastKey = "";                // no answer: a later change asks again
          dropStaleFill(key);          // and an older address's fill is not left standing as this one's
          return;
        }
        await county.whenLoaded();
        if (stale()) return;           // the address moved on while the list loaded
        // The Census can match the street in another zip and name a city the job is not in
        // (place_sure false). Its county is still right; the city then comes from the box.
        settle(county.autoFill(ans.county, ans.state, placeFor(ans)), key);
      } catch (e) { lastKey = ""; }
    }

    function later() {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () { timer = null; check(); }, delay);
    }

    /** The estimator picked a suggestion. p = { county, state, place } from the Photon row (any
     *  may be empty). The first guess goes in at once; the Census answer then confirms or replaces
     *  it. The address boxes are already filled by the time this runs. */
    function onPick(p) {
      p = p || {};
      if (timer) { clearTimeout(timer); timer = null; }
      var pickKey = keyNow();
      var guess = Promise.resolve();
      if (p.county || p.place) {
        guess = county.whenLoaded().then(function () {
          // Only if the address has not moved on (a second pick, an edit) since this one.
          if (keyNow() !== pickKey) return;
          settle(county.autoFill(p.county || "", p.state || "", p.place || ""), pickKey);
        }).catch(function () {});
      }
      lastKey = "";               // a pick is a new address, whatever the fields said before
      return guess.then(check);
    }

    ["address", "city", "state", "zip"].forEach(function (k) {
      if (els[k] && els[k].addEventListener) els[k].addEventListener("change", later);
    });

    return { onPick: onPick, check: check, addressKey: keyNow };
  }

  window.TWCountyAutofill = { mount: mount, addressKey: addressKey };
})();
