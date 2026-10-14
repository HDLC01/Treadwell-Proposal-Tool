/* The county / city tax picker, once, for every page that needs it.
 *
 * WHY THIS FIELD EXISTS. Kyle's workbook hardcodes the remodel tax at 10% (Polish!B75). That is
 * not a real rate anywhere. Kansas charges sales tax on commercial remodel LABOR at the state
 * rate plus the COUNTY portion only — 6.5% + 1.475% = 7.975% in Johnson County, less in most
 * others. Hanz, 2026-08-18: "For the Remodel tax please use the real state tax or city tax, DONT
 * USE 10%".
 *
 * WHY IT IS SHARED. This control existed twice before this file: once on the beta polish intake
 * (js/polish-intake.js) and once on the live estimate screen (js/estimate-review.js). The two had
 * already drifted — only one had keyboard navigation, only one showed each row's rate, and only
 * one said out loud what the pick was doing to the bid. Folding the beta's step 1 into the live
 * intake form needed the control on a THIRD page, and a third copy of a control that had already
 * drifted twice is how an estimator picks a county on one screen and is shown a different one on
 * the next. So the beta's version — the richer one — moved here, and both intake pages call this.
 * The estimate screen's copy is deliberately NOT folded in yet: it is welded to the workbook-cell
 * machinery (REMODEL_RATE_BY_LAYOUT, remodelRateTargets, effectiveRemodelRate) and does a second
 * job, writing the rate into cells; reconciling it belongs in its own change rather than riding
 * along with a reported defect.
 *
 * THE FOUR KEYS ARE THE CONTRACT, and they are the live estimate screen's own: `county`,
 * `county_tax_rate`, `county_remodel_rate`, `county_notes`. Written under the same names and in
 * the same label shape (city "<Name>, ST" or county "<Name> County, ST" — see rowLabel) so a
 * project that picked its county/city on ANY screen is understood by all of them —
 * js/polish-estimate.js reads `county_remodel_rate` off the draft without caring which screen set
 * it, and every screen replays `county` verbatim to restore its own field instead of parsing it
 * back apart (a city label has no "County" substring to find).
 *
 * WHY THE PICK IS NOT A FORM FIELD. TW.setState is a shallow merge (shared.js:70,
 * `Object.assign(cur, partial)`), so writing these four keys straight to the draft leaves every
 * other key alone — which is what lets the live intake form carry this control without either of
 * its two Continue handlers being edited. Those two handlers are compared blob-for-blob by
 * test_beta_intake_routing.py precisely so they cannot drift, and the cheapest way to keep that
 * true is to add nothing to either one. The search box is deliberately left `name`-less for the
 * same reason: TW.readForm sweeps named inputs, and a half-typed search is not an answer.
 *
 * THE LIST IS NEVER HARDCODED HERE. It comes from /api/reference/counties, which serves
 * backend/reference_tax.py — rates pulled one by one from the KS DOR Address Tax Rate Locator.
 * A copy in this file would be a second table to keep in step with the DOR, silently wrong. The
 * same reasoning covers the Kansas state fallback rate: reference_tax.py and
 * js/bid-model.js already hold that number twice, so this file reads it off the endpoint
 * rather than writing it down a third time.
 */
(function () {
  "use strict";

  var COUNTY_LIMIT = 12;               // rows offered at once; the estimator types, not scrolls
  // Said under the box while the county on screen came from the job address (autoFill below).
  var AUTO_NOTE = "Filled from the address. Change it if it's wrong.";

  function $(id) { return document.getElementById(id); }

  /** "Johnson County", "johnson", " Sedgwick  County " -> "johnson", "sedgwick". Also drops a
   *  " County" / " Parish" / " Borough" tail (never " city": Kansas City is a name), so one
   *  comparison serves a name from the Census, one from Photon and one from the list. Case and
   *  spacing never decide a match. */
  function bareName(s) {
    return String(s == null ? "" : s).replace(/\s+/g, " ").trim().toLowerCase()
      .replace(/ (county|parish|borough)$/, "");
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  /** Percentages read the same here as on the beta's markup rows, which is half the point of
   *  sharing: 0.07975 -> "7.975%". Mirrors bid-model.js's pct so a page that has B and a
   *  page that does not cannot disagree about how a rate is spelled. */
  function pctOf(n) {
    var v = (Number(n) || 0) * 100;
    var s = parseFloat(v.toPrecision(12)).toFixed(4);
    s = s.replace(/0+$/, "").replace(/\.$/, "");
    return s + "%";
  }

  /** opts:
   *    remodelTaxOn()  -> bool. Whether the Remodel tax condition is on for THIS bid. The note
   *                       quotes it by name, so the note is stale the moment the toggle flips —
   *                       call renderNote() from whatever paints that toggle.
   *    onChange()      -> called after a pick or a clear, so the host page can save. The host owns
   *                       saving: the beta merges into its polish model, the live form writes the
   *                       four keys straight to the draft.
   *    pct(rate)       -> optional formatter override (the beta passes B.pct).
   *    ksState         -> optional Kansas state rate for the fallback sentence, for a host that
   *                       already has the figure loaded. The endpoint's value wins once it lands.
   */
  function mount(opts) {
    opts = opts || {};
    var remodelTaxOn = opts.remodelTaxOn || function () { return false; };
    var onChange = opts.onChange || function () {};
    var pct = opts.pct || pctOf;

    var counties = [];                 // from the API, at runtime
    var matches = [];                  // what the current search text matched, in rendered order
    var highlight = -1;                // keyboard cursor into matches, -1 for none
    // The pick, held as the four DRAFT keys rather than as an API row: hydration reads exactly
    // these four off the draft, so what a reopened project shows is what a fresh pick would write.
    var pick = null;
    // True only while the pick on screen was put there by autoFill() from the job address, and
    // nobody has touched it since. A hand pick, a Clear, or a county read back off a saved draft
    // all set it false, which is what makes "never overwrite the estimator's county" one flag
    // rather than a rule scattered across the host pages. In memory on purpose: a reopened draft
    // cannot tell a fill from a pick, so it treats its county as chosen and leaves it alone.
    var autoPick = false;
    // The city the address is in, while the fill on screen is a county FLOOR row for a city the list
    // has no row for ("" otherwise): the note must say the city may charge more. See autoFill.
    var autoGap = "";
    // True after the estimator pressed Clear. An empty box they emptied on purpose is theirs as much
    // as a county they picked: a later address edit must not fill it again. In memory, like autoPick.
    var handCleared = false;
    var loadPromise = null;
    var ksState = opts.ksState == null ? null : Number(opts.ksState);

    async function loadList() {
      try {
        if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready;
        var res = await fetch(window.TW.resolveApiBase() + "/api/reference/counties",
                              { headers: window.TW.authHeaders() });
        var body = await res.json();
        counties = (body && body.counties) || [];
        // One home for this number. Absent (an older backend) leaves whatever the host injected.
        if (body && body.ks_state_rate != null) ksState = Number(body.ks_state_rate);
      } catch (e) {
        // Reference data, not the draft. A failed load costs the search box its rows; it must not
        // stop an estimator filling in the rest of the form.
        counties = [];
      }
      // A list that arrived while somebody was already typing has to reach the rows they are
      // looking at, or the box keeps saying "no county matches" until the next keystroke.
      var input = $("county-input");
      if (!pick && input && input.value) renderResults(input.value);
      // The fallback sentence names a rate the endpoint may have just supplied, so the note is
      // re-said now that there is a number to say.
      renderNote();
      return counties;
    }

    /** Start the list fetch and remember it, so an auto-fill that fires before the list lands can
     *  wait for it (whenLoaded) instead of finding no rows and giving up. */
    function load() {
      loadPromise = loadList();
      return loadPromise;
    }

    /** Resolves once the list is here (or failed). Never rejects; resolves at once when load()
     *  was never called, which leaves whatever the host injected through _counties(). */
    function whenLoaded() {
      return loadPromise ? loadPromise.then(function () { return counties; },
                                            function () { return counties; })
                         : Promise.resolve(counties);
    }

    /** The two-letter state out of "Johnson County, KS".
     *
     *  Read off the name rather than inferred from the rate: BOTH states have a Johnson County,
     *  and "this row carries no remodel_rate" is not the same claim as "this job is in Missouri". */
    function stateOf(p) {
      var m = /,\s*([A-Za-z]{2})\s*$/.exec(String((p && p.county) || ""));
      return m ? m[1].toUpperCase() : "";
    }

    /** What one row charges, in the picker. Formatted with the host's own pct where it has one, so
     *  the rate promised here and the rate shown on the markup row read identically. */
    function rowRate(c) {
      return c && c.remodel_rate != null
        ? "remodel " + pct(c.remodel_rate)
        : "remodel labor exempt";
    }

    /** A row is either a CITY (kind: "city" — the full combined local rate, correct for a job site
     *  inside that city's limits) or a COUNTY (kind: "county" — a floor rate, correct only for
     *  unincorporated land; see backend/reference_tax.py). Only county rows get " County". */
    function rowLabel(c) {
      return c.kind === "city" ? c.name + ", " + c.state : c.name + " County, " + c.state;
    }

    function filter(query) {
      var q = String(query == null ? "" : query).trim().toLowerCase();
      if (!q) return [];
      var hits = [];
      for (var i = 0; i < counties.length && hits.length < COUNTY_LIMIT; i++) {
        var c = counties[i];
        // Name, state, "Johnson County, KS" and the notes, which is where the cities are: an
        // estimator types the town on the drawing set, not the county nobody puts on a plan.
        var hay = (c.name + " county, " + c.state + " " + (c.notes || "")).toLowerCase();
        if (hay.indexOf(q) >= 0) hits.push(c);
      }
      return hits;
    }

    /** Close the list AND put the box back to what is actually saved.
     *
     *  The restore is the load-bearing half. The chosen county is shown IN the input, so a search
     *  the estimator abandoned half-typed — Escape, or a click somewhere else on the page — would
     *  leave "wyando" sitting in a field whose draft says Johnson County. The field would be
     *  telling them the wrong county, which is the one thing this control exists to get right.
     *
     *  Deliberately NOT called from renderResults: emptying the box to type a different county
     *  must not have the old one typed back in on top of them. */
    function close() {
      var box = $("county-results");
      if (box) box.hidden = true;
      highlight = -1;
      var input = $("county-input");
      if (input) input.value = pick ? pick.county : "";
    }

    function renderResults(query) {
      var box = $("county-results");
      if (!box) return;
      var typed = String(query == null ? "" : query).trim();
      matches = filter(typed);
      highlight = -1;
      if (!matches.length) {
        box.innerHTML = typed
          ? '<div class="c-empty">No county matches &ldquo;' + esc(typed) + '&rdquo;</div>' : "";
        box.hidden = !typed;
        return;
      }
      box.innerHTML = matches.map(function (c, i) {
        return '<div class="c-row" id="county-row-' + i + '" data-county="' + i + '">' +
          '<span class="c-name">' + esc(rowLabel(c)) + '</span>' +
          '<span class="c-rate">' + esc(rowRate(c)) + '</span></div>';
      }).join("");
      box.hidden = false;
    }

    /** Move the keyboard cursor. Class-only: re-rendering the list would throw away the caret in
     *  the box the estimator is still typing in. */
    function paintHighlight() {
      for (var i = 0; i < matches.length; i++) {
        var el = $("county-row-" + i);
        if (el) el.className = "c-row" + (i === highlight ? " on" : "");
      }
    }

    /** The four keys a save writes. Nulls when nobody has picked, which is also what Clear means. */
    function keys() {
      if (!pick) {
        return { county: "", county_tax_rate: null, county_remodel_rate: null, county_notes: "" };
      }
      return { county: pick.county,
               county_tax_rate: pick.county_tax_rate,
               county_remodel_rate: pick.county_remodel_rate,
               county_notes: pick.county_notes };
    }

    /** A pick made by a person: from a row, by click or keyboard. */
    function choose(c) { handCleared = false; apply(c, false); }

    /** `gap` (a fill only): the city the address is in when the list has no row for it. */
    function apply(c, auto, gap) {
      if (!c || !c.name) return;
      autoPick = !!auto;
      autoGap = auto && gap ? String(gap) : "";
      pick = {
        // The live screen's shape (city "Overland Park, KS" or county "Johnson County, KS") — its
        // own restore path replays this label verbatim rather than parsing it back apart.
        county: rowLabel(c),
        county_tax_rate: c.rate == null ? null : c.rate,
        // MISSOURI ROWS HAVE NO remodel_rate, and that is correct rather than missing data:
        // Missouri remodel labor is generally exempt. Left null instead of filled in with
        // something.
        county_remodel_rate: c.remodel_rate == null ? null : c.remodel_rate,
        county_notes: c.notes || "",
      };
      // close() is what puts the chosen county in the box — one place owns what the field shows,
      // so a pick and an abandoned search cannot disagree about it.
      close();
      renderNote();
      onChange();                            // the host's own debounced save, which MERGES
    }

    /** Take whatever is picked away. NOT a statement by the estimator: autoFill uses it to remove a fill
     *  that belonged to an address they have left, and that must leave the box free to fill again. */
    function reset() {
      pick = null;
      autoPick = false;
      autoGap = "";
      matches = [];
      close();                               // which now empties the box, pick being null
      renderNote();
      onChange();
    }

    /** The estimator's Clear. The box is theirs from here: an address edit does not fill it again. */
    function clear() {
      handCleared = true;
      reset();
    }

    /** Remove a county the address filled, and ONLY that: a county picked or cleared by hand stays. For
     *  the host to call when the address that justified the fill has gone. Returns whether it cleared. */
    function clearFill() {
      if (!(pick && autoPick)) return false;
      reset();
      return true;
    }

    /** The fallback rate, named only when it is actually known. Writing "6.5%" into this file
     *  would be a third copy of a number that already lives in reference_tax.py and
     *  bid-model.js; saying the sentence without the figure until the endpoint supplies one
     *  is honest and needs no second table. */
    function ksPhrase() {
      return ksState == null ? "the Kansas state rate"
                             : "the Kansas state rate of " + pct(ksState);
    }

    /** What the county does to THIS bid, in plain words.
     *
     *  Said out loud because the number is not the one the workbook shows. An estimator who knows
     *  Kyle's sheet expects a flat 10% on this line; naming the real rate, the county it came
     *  from, and the fallback when there is no county is what stops the difference reading as a
     *  bug. */
    function baseNote() {
      var on = !!remodelTaxOn();
      var ksRate = ksPhrase();
      if (!pick) {
        if (!on) {
          return "Remodel tax is off, so the county is not affecting the price yet — it only " +
            "changes the bid on an occupied remodel.";
        }
        return "Remodel tax is on with no county picked, so this bid falls back to " + ksRate +
          " until you choose one.";
      }
      // MISSOURI. The row carries no remodel rate on purpose — MO taxes the contractor on
      // materials and leaves the labor exempt — so this says the rule and then says what to DO,
      // rather than promising a number. Which number a Missouri job would land on if Remodel tax
      // were left on is decided in markupChain and in how js/polish-estimate.js hands it the rate,
      // not here; the one instruction this control can honestly give is to turn the toggle off.
      if (stateOf(pick) === "MO") {
        return pick.county + " — Missouri remodel labor is generally exempt, so no remodel " +
          "tax applies." + (on
            ? " Remodel tax is on anyway: turn it off for a Missouri job unless you know this " +
              "labor is taxable."
            : " Remodel tax is off, so it is not affecting the price either way.");
      }
      var rate = pick.county_remodel_rate;
      if (rate == null || !(Number(rate) > 0)) {
        return pick.county + " has no remodel rate on file, so " + (on
          ? "this bid uses " + ksRate + "."
          : "Remodel tax would use " + ksRate +
            " — and the toggle is off, so nothing is added yet.");
      }
      return "Remodel tax " + pct(rate) + " · " + pick.county + (on
        ? ", on the labor and the markups. Never on materials."
        : " — but the Remodel tax toggle is off, so it is not affecting the price yet.");
    }

    /** The sentence above, plus one more while the pick is a fill from the address and nobody has
     *  touched it: the estimator has to be told this was not their own choice. */
    function noteText() {
      if (!(pick && autoPick)) return baseNote();
      // A county row is the floor rate for land outside any city. When the address IS inside a city the
      // list has no row for, that floor is what gets filled, and it can be too low: say so. Missouri
      // labor is exempt, so there is no rate for a city to add to.
      var gap = autoGap && stateOf(pick) !== "MO"
        ? " " + autoGap + " is not on the list, so this is the county rate only. A city can charge its own tax on top."
        : "";
      return baseNote() + gap + " " + AUTO_NOTE;
    }

    /** Which row of the list a job address sits in, or null.
     *
     *  Two inputs, in this order. A CITY row first: when the Census (or Photon) names the city the
     *  address is in AND the list has a verified row for that city in that state, the city row is
     *  the right one, because a county row is only the floor rate for unincorporated land (see
     *  rowLabel). A city row that names its own county must agree with the county found, so
     *  Shawnee, KS (Johnson) is never filled for an address in Shawnee County. Then the COUNTY
     *  row: name equal ignoring case, with or without " County", same state, kind "county".
     *  Anything else is null: a county the list does not have is left empty, never approximated. */
    function resolveArea(countyName, state, place) {
      var st = String(state || "").trim().toUpperCase();
      var cn = bareName(countyName);
      var pl = bareName(place);
      var i, c;
      if (!st) return null;
      if (pl) {
        for (i = 0; i < counties.length; i++) {
          c = counties[i];
          if (c.kind !== "city" || c.state !== st || bareName(c.name) !== pl) continue;
          if (cn && c.county && bareName(c.county) !== cn) continue;
          return c;
        }
      }
      if (!cn) return null;
      for (i = 0; i < counties.length; i++) {
        c = counties[i];
        if (c.kind !== "city" && c.state === st && bareName(c.name) === cn) return c;
      }
      return null;
    }

    /** Fill the box from a job address's county (and city), when and only when that is safe.
     *
     *  Returns what happened, so the caller can tell the estimator or stay quiet:
     *    "hand"    -- somebody picked (or a saved draft holds) a county, or pressed Clear. The box is
     *                 theirs: NEVER overwritten.
     *    "filled"  -- an empty box, or one this function filled earlier, now holds the match.
     *    "same"    -- the box already holds exactly that fill; nothing was written or saved.
     *    "none"    -- the list has no row for this place. An earlier FILL is cleared (it belonged
     *                 to the old address), an empty box stays empty.
     *    "pending" -- the list is not loaded, so there is nothing to match against yet.
     *    "busy"    -- the estimator is typing in the county search box right now; their text stays.
     *  "pending" and "busy" wrote nothing and may be tried again.
     *  Saves through the host's own onChange, like a pick does. */
    function autoFill(countyName, state, place) {
      if ((pick && !autoPick) || handCleared) return "hand";
      if (!counties.length) return "pending";
      // The box shows the pick (close() keeps it so) or is empty; anything else is a search in progress,
      // and filling now would overwrite half a word and close the list under their cursor.
      var input = $("county-input");
      if (input && String(input.value || "") !== (pick ? pick.county : "")) return "busy";
      var row = resolveArea(countyName, state, place);
      if (!row) {
        if (pick && autoPick) reset();
        return "none";
      }
      var placeName = String(place == null ? "" : place).replace(/\s+/g, " ").trim();
      // A county row for an address inside a city: the city may add its own tax, unless the row itself
      // says the county rate is the right one there (city_ok: Wichita levies none).
      var verified = (row.city_ok || []).some(function (n) { return bareName(n) === bareName(placeName); });
      var gap = row.kind !== "city" && !verified ? placeName : "";
      if (pick && autoPick && pick.county === rowLabel(row)) {
        // The same county again, but this answer may know the city and the last one did not.
        if (autoGap !== gap) { autoGap = gap; renderNote(); }
        return "same";
      }
      apply(row, true, gap);
      return "filled";
    }

    /** Text, not markup: every word of this is composed above, and the only variable in it is a
     *  county name from the server's own table. Nothing to escape and nothing to get wrong. */
    function renderNote() {
      var note = $("county-note");
      if (note) note.textContent = noteText();
      var btn = $("county-clear");
      if (btn) btn.hidden = !pick;
    }

    /** Read the pick straight off the draft, under the live screen's keys: a project that picked
     *  its county on the estimate screen has to show that county HERE, or the estimator picks it
     *  twice and the second pick is the one that counts. */
    function hydrate(state) {
      state = state || {};
      autoPick = false;                      // a saved county is treated as chosen, never refilled
      autoGap = "";
      handCleared = false;                   // a reopened draft cannot tell an empty box from a Clear
      pick = state.county
        ? { county: String(state.county),
            county_tax_rate: state.county_tax_rate == null ? null : state.county_tax_rate,
            county_remodel_rate:
              state.county_remodel_rate == null ? null : state.county_remodel_rate,
            county_notes: state.county_notes || "" }
        : null;
      matches = [];
      close();                               // which puts the hydrated county into the box
      renderNote();
    }

    function onInput() {
      var input = $("county-input");
      renderResults(input ? input.value : "");
    }

    function onKeydown(e) {
      var key = e && e.key;
      if (!key) return;
      var box = $("county-results");
      var open = !!box && box.hidden === false;
      if (key === "Escape") { if (open) close(); return; }
      if (!open) return;
      if (key === "Enter") {
        // Swallowed whenever the list is open, ALWAYS. This input lives inside the form, and the
        // form's submit handler navigates to the next step — so an un-prevented Enter would leave
        // the page while the estimator was choosing the row in front of them.
        if (e.preventDefault) e.preventDefault();
        // Nothing highlighted takes the top match: on a list narrowed to one row, Enter means
        // that row rather than "arrow down first".
        if (matches.length) choose(matches[highlight >= 0 ? highlight : 0]);
        return;
      }
      if (key === "ArrowDown") {
        if (e.preventDefault) e.preventDefault();
        highlight = Math.min(highlight + 1, matches.length - 1);
      } else if (key === "ArrowUp") {
        if (e.preventDefault) e.preventDefault();
        highlight = Math.max(highlight - 1, 0);
      } else {
        return;
      }
      paintHighlight();
    }

    /** A click anywhere on the page. Returns true if this control handled it, so a host page with
     *  its own delegated click handler can carry on when it did not. */
    function onDocumentClick(e) {
      var t = e && e.target;
      if (!t || !t.closest) return false;
      if (t.closest("#county-clear")) { clear(); return true; }
      var row = t.closest("[data-county]");
      if (row) {
        choose(matches[Number(row.getAttribute("data-county"))]);
        return true;
      }
      // Anything else outside the control puts the field back to what is saved. The two
      // [data-county-keep] nodes are the input and the results box: clicking the field you are
      // typing in must not close the list under your own cursor.
      if (!t.closest("[data-county-keep]")) close();
      return false;
    }

    /** Bind the control's own listeners. The document click is left to the host page where it
     *  already has one (the beta's delegated handler), and taken here where it does not. */
    function wire(bindDocumentClick) {
      var input = $("county-input");
      if (input) {
        input.addEventListener("input", onInput);
        input.addEventListener("keydown", onKeydown);
      }
      if (bindDocumentClick) document.addEventListener("click", onDocumentClick);
    }

    return {
      load: load, hydrate: hydrate, keys: keys, renderNote: renderNote, wire: wire,
      onDocumentClick: onDocumentClick, choose: choose, clear: clear, close: close,
      onInput: onInput, onKeydown: onKeydown, noteText: noteText,
      rowLabel: rowLabel, rowRate: rowRate, filter: filter, stateOf: stateOf,
      renderResults: renderResults, paintHighlight: paintHighlight,
      hasPick: function () { return !!pick; },
      autoFill: autoFill, resolveArea: resolveArea, whenLoaded: whenLoaded, clearFill: clearFill,
      isAuto: function () { return !!pick && autoPick; },
      // The box belongs to the estimator: a county they picked (or a saved draft holds), or one they
      // emptied with Clear. The address autofill leaves it alone and does not even ask.
      isTheirs: function () { return (!!pick && !autoPick) || handCleared; },
      // Read-only windows for a harness that needs to see what the control is holding, rather
      // than reaching into a closure it cannot.
      _matches: function () { return matches.slice(); },
      _highlight: function () { return highlight; },
      _counties: function (rows) { if (rows) counties = rows; return counties; },
    };
  }

  window.TWCounty = { mount: mount, pct: pctOf, LIMIT: COUNTY_LIMIT };
})();
