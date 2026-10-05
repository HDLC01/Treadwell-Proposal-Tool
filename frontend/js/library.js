// Items and Assemblies page — materials as they are bought, and the systems estimated out of them.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// THREE TABS. Items is one row per thing on an invoice (the pack, and what the pack costs);
// Assemblies is how a system is estimated from them; Vendors is the list the item dropdown offers.
// Only an admin may change the vendor LIST — anybody may pick from it (Hanz, 2026-08-15).
//
// The pricing maths is NOT here. It lives in library-core.js as pure functions so node can
// test it against Kyle's sheet; this file only renders what that returns.
//
// SAVING. Every edit is a field-level PATCH, debounced. There is no Save button because this
// is a reference list somebody maintains a row at a time — a form with a Save step would make
// correcting one price a four-click job. The cost of that choice is that a failed write must be
// visible, so a failure says so in the status line and leaves the typed value on screen rather
// than reverting it under the cursor.
(function () {
  "use strict";

  var L = window.TWLib;                     // pricing (library-core.js)
  // nameOf() ONLY — the app's one email→display-name convention (crm-core.js). Held as an alias
  // for the reason L is, and with the same caveat: this line does not itself throw if the include
  // is missing, it just leaves CRM undefined, and the TypeError arrives later — the first time
  // somebody sorts the rail by who created an assembly. So the script tag in library.html is what
  // actually guarantees this, and there is a test on the tag's presence and its order, because no
  // amount of executing these functions can see a missing <script>.
  var CRM = window.TWCrm;
  var $ = function (id) { return document.getElementById(id); };

  var ITEMS = [];
  var ASMS = [];
  var VENDORS = [];
  var DIVISION_REFS = [];
  var UNIT_REFS = [];
  var VENDOR_USE = {};             // casefolded vendor name → how many materials name it
  var DIVISION_USE = {};
  var UNIT_USE = {};
  var ADMIN = false;               // may change administration lists; everyone may pick from them
  var openId = null;
  var view = "asm";
  /** Which line's item picker is showing its results, by index within the current assembly.
   *
   *  Deliberately NOT stored on the line object. The line is what `patchSoon("assemblies", …,
   *  { lines })` sends to the server, so transient UI state living there gets persisted — the
   *  previous version's `_division_filter` / `_vendor_filter` rode along in every save. `null`
   *  means every picker is closed, which is the state a row should be in while somebody is reading
   *  the table rather than editing it. */
  var pickerOpen = null;

  // Offered by the dropdowns, not enforced by the server: a legacy row holds whatever somebody
  // typed, and refusing to save it would make those rows uneditable. An off-list value is rendered
  // as its own option so it stays visible and correctable.
  var DIVISIONS = ["Polished Concrete", "Epoxy", "Gypsum Underlayment"];
  var UNITS = ["Gallon", "Kit", "Bag"];
  var DEFAULT_DIVISIONS = DIVISIONS.slice();
  var DEFAULT_UNITS = UNITS.slice();

  // Every request waits for the bearer token in ONE place. Doing it per-call is how the Bid
  // Calendar shipped with a 401 that hid the estimator's own entries: `load()` waited and its
  // sibling `loadMine()` did not.
  var api = async function (path, opts) {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) {}
    return fetch(TW.resolveApiBase() + path,
      Object.assign({}, opts || {}, { headers: TW.authHeaders((opts || {}).headers) }));
  };

  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  };

  /** One inline SVG glyph, Lucide-shaped: 24x24 box, no fill, currentColor stroke, width 2,
   *  round caps and joins.
   *
   *  NEVER AN EMOJI. This page shipped with a trash can and a stacked-squares character standing
   *  in for its delete and duplicate controls, and the house rule against that is not taste: an
   *  emoji is drawn by whatever the machine has installed, so the control Kyle presses on Windows
   *  is a different picture from the one on a phone, it cannot take the row's own colour on hover,
   *  and it ignores every stroke and size token on the page.
   *
   *  ONE FUNCTION RATHER THAN A PATHS TABLE, because library-ui-harness.js lifts named functions
   *  out of this file by regex and executes them. A separate lookup object would have to be lifted
   *  too, and every renderer that reaches for a glyph would die on the missing identifier.
   *
   *  The glyph is not a click target: see the pointer-events rule on `.icon svg` in library.html,
   *  and the closest() lookups in the click handler, which are the two halves of the same answer. */
  function icon(name) {
    var d = name === "trash"
        ? '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6"></path>'
      : name === "copy"
        ? '<rect x="9" y="9" width="12" height="12" rx="2"></rect>' +
          '<path d="M5 15V5a2 2 0 0 1 2-2h10"></path>'
      : name === "plus" ? '<path d="M12 5v14M5 12h14"></path>'
      : "";
    return '<svg class="ic" viewBox="0 0 24 24" width="16" height="16" ' +
      'fill="none" ' +
      'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true" focusable="false">' + d + "</svg>";
  }

  var alertEl = $("alert");
  function say(msg) { alertEl.textContent = msg || ""; }
  function saving(msg) { $("asm-saving").textContent = msg || ""; }

  // ── loading ────────────────────────────────────────────────────────────────
  async function load() {
    // Resolved before the first paint, because the Vendors tab renders differently for an admin
    // and a wrong first render would offer buttons that 403 on click.
    try {
      if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready;
      var me = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
      ADMIN = me.role === "admin" || me.role === "super_admin";
    } catch (e) { ADMIN = false; }
    try {
      var rs = await Promise.all([api("/api/library/items"), api("/api/library/assemblies"),
                                 api("/api/library/vendors"), api("/api/library/divisions"),
                                 api("/api/library/units")]);
      if (!rs[0].ok || !rs[1].ok) throw new Error("HTTP " + rs[0].status + "/" + rs[1].status);
      var items = await rs[0].json(), asms = await rs[1].json();
      ITEMS = items.items || [];
      ASMS = asms.assemblies || [];
      // The vendor list failing must not take the materials down with it — an item's vendor is a
      // string it already holds, so the worst case is a dropdown with only the current value in it.
      if (rs[2].ok) {
        var vs = await rs[2].json();
        VENDORS = vs.vendors || [];
        VENDOR_USE = vs.usage || {};
      }
      if (rs[3].ok) {
        var ds = await rs[3].json();
        DIVISION_REFS = ds.divisions || [];
        DIVISION_USE = ds.usage || {};
        DIVISIONS = (DIVISION_REFS.length ? DIVISION_REFS.map(function (d) { return d.name; }) : DEFAULT_DIVISIONS.slice());
      }
      if (rs[4].ok) {
        var us = await rs[4].json();
        UNIT_REFS = us.units || [];
        UNIT_USE = us.usage || {};
        UNITS = (UNIT_REFS.length ? UNIT_REFS.map(function (u) { return u.name; }) : DEFAULT_UNITS.slice());
      }
      // The Markup page's Global lines, for the Defaults tab to SHOW. Its own request rather than
      // a sixth entry in the Promise.all above, and deliberately outside the `throw` that guards
      // items and assemblies: this page's whole job works without it, and a markup service having
      // a bad afternoon must not take Items and Assemblies down with it. A failure leaves the list
      // empty, which is the honest answer -- a bond rate this page invented because a request
      // timed out would be worse than a row that is not there.
      try {
        var mk = await api("/api/markup/rules");
        if (mk.ok) {
          var mj = await mk.json();
          GLOBAL_MARKUP = (mj.rules || []).filter(function (r) {
            return r.layout === "global" && r.applies;
          }).map(function (r) {
            // id AND line_key KEPT. The Defaults tab can now edit these, and an edit here
            // PUTs the same markup_rules row the Markup page edits -- one home, two doors.
            // Dropping the id was what made this list read-only in the first place.
            return { id: r.id, line_key: r.line_key, layout: r.layout,
                     label: (r.line_key || "").replace(/_/g, " "), formula: r.formula };
          });
        }
      } catch (e) { GLOBAL_MARKUP = []; }
      // The Defaults tab's own labor lines, on the same terms and for a sharper reason: the
      // table behind this endpoint exists on staging and NOT on production, so the request that
      // answers here answers with nothing there. Its own try, outside the `throw` above, because
      // the day this page 500s over a list that is empty by design is the day an estimator cannot
      // open a material. A failure leaves the custom rows absent and Travel still listed.
      try {
        var lb = await api("/api/library/labor");
        if (lb.ok) {
          var lj = await lb.json();
          LABOR = lj.labor || [];
        }
      } catch (e) { LABOR = []; }
      // The Takeoff conditions' stored answers, on exactly the same terms and for a
      // sharper version of the same reason: `condition_defaults` is applied to NEITHER
      // database yet, so today this answers with nothing everywhere. Empty is not a
      // failure -- it means nobody has overridden anything, the shipped literals stand,
      // and the switches below show them. Its own try, outside the `throw` above,
      // because a table Hanz has not promoted must not cost an estimator the Items tab.
      try {
        var cd = await api("/api/condition-defaults");
        if (cd.ok) {
          var cj = await cd.json();
          COND_DEFAULTS = cj.conditions || [];
        }
      } catch (e) { COND_DEFAULTS = []; }
      if (!openId || !current()) openId = ASMS.length ? ASMS[0].id : null;
      say("");
      paint();
    } catch (err) {
      say("Couldn't load the library. " + (err.message || ""));
    }
  }

  function current() {
    for (var i = 0; i < ASMS.length; i++) if (ASMS[i].id === openId) return ASMS[i];
    return null;
  }
  function itemOf(id) { return L.findItem(ITEMS, id); }

  /** The three RESERVED library_items ids, each mapped to the Takeoff condition it IS: the Joint
   *  Filler kit, Remove existing joint filler, and Dye. The ids match backend/library.py's
   *  RESERVED_ITEM_IDS and the `item_id` on polish-estimate.js's CONDITION_CARDS; the values match
   *  the keys takeoffConditionDefaults answers and backend/condition_defaults.KEYS.
   *
   *  Hanz: "joint filler and die should be library items so that we are able to edit them as
   *  well", and on 2026-10-01, of all three on the Defaults tab: "make these 3 as materials". All
   *  three are seeded by the schema files at these literal ids, the Travel-row pattern. Joint
   *  filler and dye price the Polish estimate's two condition cards; remove-existing prices
   *  NOTHING -- it is a fourth hand on the joint-filler line, priced on the Labor step -- and has a
   *  row so it can be listed, found and edited like the other two. Each is an ordinary Items-tab
   *  row for EDITING, with three differences:
   *
   *    * NO DELETE. Nothing reachable from this page can make a row at one of these ids again
   *      (create_item mints its own uuid), so a delete would lose the row for good. renderItems
   *      leaves the button off; delete_item refuses the id server-side as well.
   *    * NEVER PICKED INTO ANYTHING. Not an assembly line, not the bulk-add list, not a takeoff
   *      row: the Polish estimate already charges each one through its own condition card, and a
   *      second copy buried in an assembly would charge the same material twice.
   *    * A DEFAULT THROUGH ITS CONDITION, not its `favorite`. On the Defaults tab each one is
   *      listed, removed and added exactly like a material, and every one of those writes the
   *      condition default a new Polish estimate opens with (condition_defaults) -- see
   *      takeoffDefaultGroups, removeDefault and defaultCandidates.
   *
   *  A literal map rather than a lookup: isReservedItem runs inside filters over the whole
   *  library on every repaint, and a key check is all it needs to be. */
  var RESERVED_ITEM_CONDITION = {
    "joint-filler-kit": "joint_filler", "remove-existing-jf": "remove_existing_jf", "dye": "dye"
  };

  function isReservedItem(id) {
    return !!id && Object.prototype.hasOwnProperty.call(RESERVED_ITEM_CONDITION, id);
  }

  /** What an assembly is measured and priced per: "SF" or "LF".
   *
   *  Takes the assembly so it stays a pure function of its argument — the harness lifts the three
   *  renderers that call this out of the source text, and a helper that closed over module state
   *  would need its own grab() in there.
   *
   *  Anything unrecognised reads as SF, matching `_coverage_unit`-style read-shaping on the server:
   *  the column is free text to 24 chars and a legacy row may hold "sqft" or "Each". Defaulting
   *  rather than displaying the raw value keeps the label honest about which arithmetic actually
   *  ran — priceAssembly divides by the one area input either way. */
  function asmUnit(asm) {
    return String((asm || {}).unit || "").trim().toUpperCase() === "LF" ? "LF" : "SF";
  }

  // ── writes ─────────────────────────────────────────────────────────────────
  var timers = {};
  var pendingPatch = {};
  // WHICH RECORDS HAVE A PATCH ON THE WIRE RIGHT NOW. See the guard in flush(): without it a
  // second debounced save goes out stamped with the version the FIRST one is about to
  // replace, and the server rightly rejects it as stale — a 409 against our own write.
  var inFlight = {};
  // RECORDS CREATED ON THIS PAGE THAT HAVE NOT HAD A SAVE LAND YET, by kind then id. Creating a row
  // POSTs it, so it exists server-side from the first click -- what is unsaved is whatever is
  // typed over the placeholder name, which only goes out when the row is left or 600ms pass. That
  // is why somebody who typed a new material and looked for a Save button found nothing to press.
  // The Save button shows while an id is in here; a successful save of the record clears it.
  //
  // WIDENED 2026-10-05 (Hanz, B3b): the map now holds EVERY record with changes not yet confirmed by
  // the server, not just new ones. The value is "new" for a row created on this page and true for a
  // saved row somebody has edited since. patchSoon sets it; only a server-confirmed save (or a
  // refused/reverted change, or a conflict repaint, or a delete) clears it. The name is kept
  // because the harnesses seed it.
  var FRESH = { items: {}, assemblies: {} };
  // A FLUSH THAT HAS TAKEN ITS PAYLOAD BUT NOT YET HEARD BACK, by record key: a promise that settles
  // when that flush is completely finished (confirm dialog answered, PATCH answered). flush deletes
  // pendingPatch[key] the moment it starts, so "nothing pending" used to read as "saved" while the
  // question was still on screen or the request still on the wire. saveNow waits on this instead.
  var takenP = {};
  /** PATCH one record, debounced per record so holding a key is one write.
   *
   *  Pending fields are MERGED, not replaced. The first version replaced the body on each call,
   *  and since every edit sends a single field, editing a material's name and then its cost
   *  inside the debounce window sent only the cost — the name was silently dropped. Caught on
   *  staging: after a reload the materials were all still called "New material" and only one of
   *  three costs had saved. Typing a name and tabbing straight to a price is the normal way to
   *  fill a row, so this was going to happen constantly. */
  function byId(kind, id) {
    var list = (kind === "assemblies") ? ASMS
      : (kind === "vendors") ? VENDORS
      : (kind === "divisions") ? DIVISION_REFS
      : (kind === "units") ? UNIT_REFS
      : (kind === "labor") ? LABOR
      : ITEMS;
    for (var i = 0; i < (list || []).length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  // Take the server's version stamp after our own successful write, so the next keystroke does
  // not conflict with the change we just made.
  function adoptSaved(kind, fresh) {
    var known = byId(kind, fresh.id);
    if (!known) return;
    var moved = fresh.updated_at !== known.updated_at;
    known.updated_at = fresh.updated_at;
    // …and the price date, which only the SERVER can decide: it moves when the cost actually
    // changed, not when a PATCH was sent. Without adopting it the row goes on saying "not since we
    // started tracking" until a reload — the stamp Hanz asked for, looking like it doesn't work.
    if (kind === "items" && fresh.cost_updated_at !== known.cost_updated_at) {
      known.cost_updated_at = fresh.cost_updated_at;
      moved = true;
    }
    // AND THE EDITOR, for exactly the same reason one line up. `updated_by` is server-set from the
    // bearer token, so the reply is the only place the client can learn it. The repaint is now
    // driven by `updated_at` too, not by the price date alone: an ordinary edit — a spelling, a
    // vendor — moves `updated_at` and `updated_by` while leaving `cost_updated_at` alone, so the
    // old condition would have left the new "Edited … by …" line quoting the PREVIOUS editor
    // until a reload. Same failure the price date had, one column over.
    // `undefined` is not an answer, and adopting it would BLANK a name we already have. The server
    // sends `updated_by` on every reply — "" when the row predates the column, never absent — so a
    // missing key means a caller that isn't the real API, and the safe reading of silence is "no
    // news", not "nobody edited it".
    if (kind === "items" && fresh.updated_by !== undefined &&
        fresh.updated_by !== known.updated_by) {
      known.updated_by = fresh.updated_by;
      moved = true;
    }
    if (kind === "items" && moved) paintDates(known);
  }


  // Somebody else got there first. Show THEIR version rather than leaving a screen that quietly
  // disagrees with the database - and say so, because a silent redraw mid-edit is worse than the
  // conflict.
  function adoptConflict(id, fresh) {
    if (!fresh || !fresh.id) return;
    for (var i = 0; i < ASMS.length; i++) {
      if (ASMS[i].id === id) { ASMS[i] = fresh; break; }
    }
    // Disarm the timer as well as emptying the buffer. Somebody typing during the ~300ms the
    // conflicting PATCH is in flight re-arms it, and dropping only the payload left a timer that
    // fired 600ms later on nothing — throwing before the try block, so the write never left the
    // browser and the screen said nothing. On a page with no Save button, that is a lost edit with
    // no trace, arriving right after we told them to re-apply their change.
    var key = "assemblies:" + id;
    // Unconditional: clearTimeout(undefined) is a harmless no-op, while `if (timers[key])` would
    // skip a falsy handle. Browsers never hand out 0, but a guard that depends on that is a trap
    // for whoever reuses this pattern next.
    clearTimeout(timers[key]);
    delete timers[key];
    delete pendingPatch[key];
    // The server's copy replaced ours, so nothing of ours is left unsaved.
    delete FRESH.assemblies[id];
    renderList();
    renderPanel();
  }

  /** Strip the picker's scratch keys out of a lines payload.
   *
   *  A line carries `_item_search` while somebody is typing in that row, and `patchSoon` sends the
   *  whole lines array. The server rebuilds each line from known keys, so this cannot corrupt
   *  anything — but a save should not carry one screen's half-typed search string, and doing it
   *  here rather than at the five call sites means a sixth cannot forget. Underscore prefix is the
   *  convention: `_`-keyed fields are this page's, not the row's. */
  function lineForSave(ln) {
    var out = {};
    Object.keys(ln).forEach(function (k) { if (k.charAt(0) !== "_") out[k] = ln[k]; });
    return out;
  }

  // ── confirming an Item change ─────────────────────────────────────────────
  // Hanz, 2026-08-25: every Item field change is confirmed first, because items "will be
  // connected to many assemblies and an accidental change could alter the pricing." That makes
  // this a PRICING-INTEGRITY control rather than a politeness — an item's unit_cost reprices
  // every assembly built on it, live, and nothing else on this page asks before doing that.
  //
  // ONE DIALOG PER ROW PER VISIT, NOT ONE PER KEYSTROKE AND NOT ONE PER PAUSE.
  //
  // The first version asked at flush time — 600ms after the last keystroke — which put the
  // question in front of somebody who was still working in the row: one field in, mid-edit, over
  // a change they had not finished making. Hanz, 2026-08-27: ask when focus LEAVES THE ROW. While
  // the row holds the focus, edits accumulate and the flush re-defers; the moment focus lands
  // outside it, everything that moved goes into one question.
  //
  // AND THAT IS ALSO THE FIX FOR A REAL DEFECT, not just an improvement in timing.
  // The dialog could be answered "no" while the rejected value still reached the database:
  // shared.js focused its Cancel button, that BLURRED the input being typed in, a blurred input
  // with an uncommitted value fires `change`, `change` is bound to #items-body — so the page
  // re-entered onItemEdit while its own dialog was open, snapshotted the ALREADY-EDITED model,
  // and queued a second patch. That one compared before against after, found them equal, asked
  // nothing, and sent the number the estimator had just refused. Waiting for the row to be left
  // kills it at the root: when the dialog opens there is no row input left to blur, so no
  // `change` can fire and no re-entry is possible. `itemConfirmOpen` below is the belt.
  //
  // AND IT CANNOT LIVE IN onItemEdit FOR A MECHANICAL REASON WORTH WRITING DOWN.
  // library-ui-harness.js lifts that function and runs it against a stub `document` that has only
  // querySelector; TW.confirmDanger calls document.createElement and reads document.activeElement.
  // A dialog inside onItemEdit would fail all 38 of that harness's tests in one go, which is a
  // loud failure — but it would also have to be un-picked afterwards, and this is the better
  // shape regardless.
  var ITEM_FIELD_LABELS = {
    name: "Name", unit: "Unit", unit_cost: "Cost", buy_qty: "Order amount",
    coverage: "Coverage per unit", waste_pct: "Waste factor", roundup: "Roundup",
    vendor: "Vendor", divisions: "Division",
  };

  // THE SERVER'S FIELDS, NOT OURS. `updated_at` moves on every write, `cost_updated_at` moves
  // only when the cost really changed, and `updated_by` is stamped from the bearer token — all
  // three are decided server-side and adopted off the reply (see adoptSaved). A snapshot taken
  // before that reply landed holds the old values, so restoring the WHOLE snapshot on a Cancel
  // would throw away what the server just told us: the History cell would go back to quoting a
  // price date the database has already moved past, and an editor who is no longer the last one,
  // with nothing on screen marking either. Cancel restores what the estimator typed, nothing else.
  var SERVER_OWNED_ITEM_FIELDS = ["updated_at", "cost_updated_at", "updated_by"];

  // The item as it stood before this round of edits, captured on the first keystroke after each
  // flush. Two jobs: the dialog quotes before → after, and Cancel has something to put back.
  var itemBefore = {};
  // Which item's confirmation is on screen right now, by id, or null. Read by onItemEdit (any
  // event arriving while this is set is the dialog's own doing — the modal overlay traps every
  // real one) and by the flush, so a second row waits its turn instead of stacking a second modal.
  var itemConfirmOpen = null;
  // The field the estimator last changed in this round, per item, so a Cancel can put the caret
  // back where they were working. Recorded here rather than read off document.activeElement at
  // dialog time because by then focus has deliberately left the row.
  var itemLastField = {};

  function snapshotItem(it) {
    var out = {};
    // Arrays are COPIED, not referenced: `divisions` is the one array field on an item, and a
    // shared reference would make the snapshot mutate along with the edit it is meant to remember,
    // so Cancel would restore the value it was supposed to undo.
    Object.keys(it).forEach(function (k) {
      out[k] = Array.isArray(it[k]) ? it[k].slice() : it[k];
    });
    return out;
  }

  function rememberItem(it) {
    if (!itemBefore[it.id]) itemBefore[it.id] = snapshotItem(it);
  }

  function shownValue(v) {
    if (Array.isArray(v)) return v.length ? v.join(", ") : "(none)";
    var t = String(v === undefined || v === null ? "" : v).trim();
    return t === "" ? "(blank)" : t;
  }

  /** Is the estimator still working inside this item's row?
   *
   *  The one question the row-leave rule turns on. `contains` covers the whole <tr> deliberately:
   *  tabbing from the cost box to the vendor dropdown, or reaching for that row's own Duplicate
   *  button, is not leaving the row and must not raise the question. */
  function rowHasFocus(id) {
    var row = document.querySelector('[data-item="' + id + '"]');
    var here = document.activeElement;
    return !!(row && here && row.contains && row.contains(here));
  }

  /** Put the caret back in the field a cancelled edit was typed into.
   *
   *  Re-queried rather than held as a node, because the Cancel path calls renderItems() first and
   *  the input the estimator was in no longer exists by the time this runs. No .select(): they
   *  just said "leave it as it was", so the value they get back should not be sitting there
   *  highlighted and one keystroke from being wiped again. */
  function refocusItemField(id, f) {
    if (!f) return;
    var el = document.querySelector('[data-item="' + id + '"] [data-f="' + f + '"]');
    if (el && el.focus) el.focus();
  }

  // The round is over: the next keystroke on this row starts a new snapshot. Every exit from
  // confirmItemPatch goes through here, so a path that returns early cannot leave a stale
  // "before" for the next round to compare against — which is the shape the bypass had.
  function endItemRound(id) {
    delete itemBefore[id];
    delete itemLastField[id];
  }

  /** Ask before an item's edits go to the server, and put them back if the answer is no.
   *
   *  Returns true to let the save proceed.
   *
   *  ON A NO, THE MODEL IS RESTORED AND THE PAGE REDRAWN. Without that the screen would keep
   *  showing a value the server was never told about — a lie that outlives the dialog and is worse
   *  than the accidental edit this exists to catch, because the next person to open the row reads
   *  the wrong number with nothing marking it.
   *
   *  Compares against the snapshot rather than trusting the payload to be a change: patchSoon
   *  MERGES fields across a quiet period, so a value typed and then typed back lands in the
   *  payload identical to where it started. Asking about that would train the estimator to dismiss
   *  the dialog, which is the failure mode that makes a confirmation worthless.
   *
   *  THE SNAPSHOT IS CONSUMED AFTER THE AWAIT, NOT BEFORE IT. Deleting it first is what let the
   *  bypass through: anything that re-entered onItemEdit while the dialog was open found no
   *  snapshot, took a fresh one off the already-edited model, and the next flush then compared
   *  the rejected value against itself and sent it without asking. */
  async function confirmItemPatch(id, payload) {
    var before = itemBefore[id];
    var it = itemOf(id);
    if (!before || !it) { endItemRound(id); return true; }
    var fields = Object.keys(payload).filter(function (f) {
      return f !== "expected_updated_at" && shownValue(payload[f]) !== shownValue(before[f]);
    });
    // A no-op payload is still SENT — harmless, and an existing test pins it — but the snapshot
    // has done its job and must not be left behind for the next round to compare against.
    if (!fields.length) { endItemRound(id); return true; }
    // THE QUESTION IS ABOUT THE ASSEMBLIES THAT PRICE FROM THIS MATERIAL. A material no assembly
    // uses has nothing downstream to change, so a brand-new row (or any unused one) saves without
    // asking; the dialog's own sentence ("priced into every assembly that uses it") would be false.
    var usedByAssembly = (ASMS || []).some(function (a) {
      return (a.lines || []).some(function (l) { return l.item_id === id; });
    });
    if (!usedByAssembly) { endItemRound(id); return true; }
    var lines = fields.map(function (f) {
      return (ITEM_FIELD_LABELS[f] || f) + ":  " + shownValue(before[f]) + "  →  "
        + shownValue(payload[f]);
    });
    var focusField = itemLastField[id] || fields[0];
    // SET SYNCHRONOUSLY, BEFORE THE AWAIT. Everything that reads it — onItemEdit's guard and the
    // flush's defer — runs on events that fire during the await, so setting it afterwards would
    // set it too late to be worth having.
    itemConfirmOpen = id;
    var ok = false;
    try {
      ok = await TW.confirmDanger({
        tone: "warn",
        // Inline SVG, through the slot that takes markup: the shared default for the warn tone is
        // a WASTEBASKET, which is the wrong thing to draw over "Save this change?". Sized for the
        // 54px badge rather than the 16px row buttons, which is why it is written here instead of
        // through icon().
        iconSvg: '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" ' +
          'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
          'aria-hidden="true" focusable="false"><path d="M12 20h9"></path>' +
          '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"></path></svg>',
        title: fields.length === 1 ? "Save this change?" : "Save these changes?",
        name: before.name || it.name || "this item",
        after: " is priced into every assembly that uses it, so this changes what those cost.",
        detail: lines.join("\n"),
        confirmText: "Save change",
        cancelText: "Leave it as it was",
        // A DIALOG THAT CANNOT BE ANSWERED BY ACCIDENT. See the block comment above
        // ITEM_FIELD_LABELS: focusing a button is what fired the re-entrant `change`, and a
        // backdrop click is how the next cell somebody reaches for would revert a deliberate edit.
        focus: "container",
        dismiss: "explicit",
      });
    } catch (err) {
      // A DIALOG THAT BLEW UP IS A CANCEL, NOT A DROPPED WRITE. Letting this escape would leave
      // itemConfirmOpen set for the rest of the session, and onItemEdit's guard would then
      // swallow every keystroke on the page in silence.
      ok = false;
      say("Couldn't ask about that change, so it wasn't saved.");
    } finally {
      itemConfirmOpen = null;
    }
    endItemRound(id);
    if (ok) return true;
    Object.keys(before).forEach(function (k) {
      if (SERVER_OWNED_ITEM_FIELDS.indexOf(k) === -1) it[k] = before[k];
    });
    // Purge this row's queue the way adoptConflict does, timer included. Nothing should be able to
    // queue behind an open dialog any more — that is what the guard in onItemEdit is for — but a
    // payload left here would go out on the next flush as an unasked-for save of the value that
    // was just refused, which is the exact bug this function exists to prevent.
    var key = "items:" + id;
    clearTimeout(timers[key]);
    delete timers[key];
    delete pendingPatch[key];
    renderItems(); renderList(); renderPanel();
    refocusItemField(id, focusField);
    saving("");
    return false;
  }

  function patchSoon(kind, id, body) {
    var key = kind + ":" + id;
    if (body && Array.isArray(body.lines)) {
      body = Object.assign({}, body, { lines: body.lines.map(lineForSave) });
    }
    pendingPatch[key] = Object.assign(pendingPatch[key] || {}, body);
    // Unsaved from this keystroke until the server confirms. showUnsaved is the DOM half (absent
    // in a bare harness scope, hence the typeof).
    if (FRESH[kind] && !FRESH[kind][id]) {
      FRESH[kind][id] = true;
      if (typeof showUnsaved === "function") showUnsaved(kind, id);
    }
    arm(kind, id, key);
  }

  // The debounce, on its own so the flush can re-arm itself when it decides to wait.
  //
  // The callback RETURNS the flush's promise. setTimeout throws it away, as it always has, but a
  // driver that can await it then does — which is how the harness sequences a PATCH in flight
  // against the next keystroke. The alternative was an async callback whose promise nothing could
  // reach, which is what made a 409 scenario there pass while the second write went out anyway.
  function arm(kind, id, key) {
    if (timers[key]) clearTimeout(timers[key]);
    timers[key] = setTimeout(function () { return flush(kind, id, key); }, 600);
  }

  /** Send one record's coalesced edits, or decide not to yet.
   *
   *  `now` is set by the focusout path, which knows focus has left the row and must not ask this
   *  function to check for itself: during a `focusout` the browser has already blurred the old
   *  element and has not yet focused the new one, so `document.activeElement` is the body and
   *  reading it would answer the wrong question either way. */
  async function flush(kind, id, key, now) {
    var payload = pendingPatch[key];
    // Nothing to send is not an error — a conflict repaint empties the buffer, and this used to
    // throw on the missing payload BEFORE the try block, which turned a dropped write into an
    // unhandled rejection and a silent screen. Belt to adoptConflict's braces.
    if (!payload) { delete timers[key]; return; }
    // ONE PATCH PER RECORD ON THE WIRE AT A TIME.
    //
    // Every successful PATCH bumps `updated_at`, and an assembly save declares the version it was
    // editing so two people cannot silently overwrite each other. Those two facts together made a
    // race against OURSELVES: this function used to take the payload and await the request without
    // recording that it was in flight, so a second save armed 600ms later read the SAME stale
    // `updated_at` (adoptSaved has not run yet), went out, and came back 409. `adoptConflict` then
    // replaced the model wholesale, dropped the pending buffer, and said "Somebody else changed
    // this while you had it open" — about nobody. Reachable by typing quickly on a slow connection,
    // and with the bulk picker it could discard a whole batch of lines.
    //
    // RE-ARM, never drop: the edit is still on screen and still unsaved, and the payload has not
    // been consumed yet at this point — so the next tick sends it with a version stamp that is by
    // then correct. This is the same "wait and try again" the three item gates below use.
    if (inFlight[key]) { arm(kind, id, key); return; }
    if (kind === "items") {
      // ONE DIALOG AT A TIME, ACROSS ALL ROWS — and across all QUESTIONS, not just this one.
      //
      // Two of these modals is one trapping the focus the other one needs, over a question that
      // names neither row clearly. The second check catches what the first cannot: clicking a
      // row's own Remove button leaves the focus INSIDE the row, so nothing flushes — and then
      // THAT dialog focuses its Cancel button, which blurs the button and fires the focusout this
      // page saves on. Without asking shared.js whether a modal is up, "Remove this material?"
      // would get "Save this change?" stacked on top of it.
      //
      // Re-arm rather than drop: the edit is still on screen and still unsaved.
      if (itemConfirmOpen) { arm(kind, id, key); return; }
      if (TW.modalOpen && TW.modalOpen()) { arm(kind, id, key); return; }
      // …and while the estimator is still working in the row, keep waiting. This is the timing
      // Hanz asked for and the reason no `change` can re-enter the handler while the dialog is up.
      if (!now && rowHasFocus(id)) { arm(kind, id, key); return; }
    }
    delete pendingPatch[key];
    // From here until the finally below, this record's save is UNCONFIRMED even though the buffer
    // is empty. saveNow and the leave-page warning both read takenP for exactly that.
    var release;
    takenP[key] = new Promise(function (r) { release = r; });
    try {
    // Declare the version being edited. A line change rewrites the WHOLE lines array, so
    // without this two people with the same assembly open overwrite each other in silence:
    // the second save replaces the first person's lines with a snapshot taken before they
    // existed, and neither screen shows anything wrong.
    if (kind === "assemblies") {
      var known = byId(kind, id);
      if (known && known.updated_at) payload.expected_updated_at = known.updated_at;
    }
    // Items only. An assembly's lines are a takeoff somebody is actively building and a dialog
    // per pause would be unusable; an item is reference data that other records are priced from,
    // which is the whole distinction Hanz drew.
    if (kind === "items" && !(await confirmItemPatch(id, payload))) {
      // Refused: the field went back to what the server holds, so a saved row is clean again. A
      // NEW row stays unsaved -- its typed name was just refused, and it still wants a Save.
      if (FRESH.items[id] !== "new") { delete FRESH.items[id]; if (typeof hideUnsaved === "function") hideUnsaved(kind, id); }
      return;
    }
    // AFTER the confirm above, which can return false and bail — marking earlier would leave the
    // record permanently locked by a question somebody answered "no" to.
    inFlight[key] = 1;
    saving("Saving…");
    try {
      var r = await api("/api/library/" + kind + "/" + encodeURIComponent(id),
        { method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload) });
      if (r.status === 409) {
        var conflict = await r.json().catch(function () { return {}; });
        adoptConflict(id, conflict.assembly);
        say(conflict.error || "Somebody else changed this while you had it open.");
        saving("Not saved");
        return;
      }
      if (!r.ok) {
        var j = await r.json().catch(function () { return {}; });
        // Deliberately does NOT revert the field. Overwriting what somebody just typed while
        // they are looking at it loses their work and hides the reason.
        say(j.detail || j.error || "That change didn't save.");
        saving("Not saved");
        requeueFailed(key, payload);
        return;
      }
      // Adopt the new version stamp, or the NEXT save conflicts with our own write.
      var saved = await r.json().catch(function () { return {}; });
      // `row`, not `labor` — POST/PATCH /api/library/labor answers { ok, row }, the same key
      // create_labor/update_labor always have, unlike the other library endpoints which are
      // named after their own kind. See patchLabor's own note for why labor's writer beside it
      // is a separate function rather than a third branch taught to this one.
      var fresh = saved.assembly || saved.item || saved.vendor || saved.division || saved.unit ||
        saved.row;
      if (fresh && fresh.id) adoptSaved(kind, fresh);
      // CONFIRMED -- this is the only place the unsaved mark is lifted by a save. Not while a newer
      // edit is already queued behind this one: that keystroke is still unsaved.
      if (FRESH[kind] && !pendingPatch[key]) {
        delete FRESH[kind][id];
        if (typeof hideUnsaved === "function") hideUnsaved(kind, id);
      }
      say(""); saving("Saved");
      setTimeout(function () { saving(""); }, 1200);
    } catch (err) {
      say("Couldn't reach the server. " + (err.message || ""));
      saving("Not saved");
      requeueFailed(key, payload);
    } finally {
      // `finally`, because the try block returns early on 409 and on any non-ok status. A lock left
      // set on one of those paths would silence every later save for that record — a worse bug than
      // the one this guard fixes.
      delete inFlight[key];
    }
    } finally {
      delete takenP[key];
      release();
    }
  }

  /** A failed save keeps its edit queued (no timer: no retry loop), so the next Save press or the
   *  leave-page flush sends it again instead of finding an empty buffer and retiring the button
   *  over a value the server never received. A newer keystroke queued meanwhile wins per field. */
  function requeueFailed(key, payload) {
    // Keeps the SAME object (newer keystrokes folded in): saveNow reads identity to tell "my flush
    // failed and handed the edit back" from "a newer edit arrived", and stops after one attempt.
    pendingPatch[key] = Object.assign(payload, pendingPatch[key] || {});
  }

  /** Drop everything this page is still holding for an item that no longer exists.
   *
   *  A deleted row can have an edit queued and a timer armed, which is far more likely now the
   *  save waits for the row to be left: typing a cost and then reaching for that row's Remove
   *  button never leaves the row at all. Left alone, the timer fires after the delete and PATCHes
   *  a dead id — a 404 and "That change didn't save." about a material the estimator has just
   *  watched disappear. */
  function forgetItem(id) {
    var key = "items:" + id;
    clearTimeout(timers[key]);
    delete timers[key];
    delete pendingPatch[key];
    delete FRESH.items[id];
    endItemRound(id);
  }

  /** Send one item row's pending edits NOW, because focus has left it.
   *
   *  Disarms the debounce first. Leaving it armed would let it fire behind the dialog this flush
   *  is about to open, which is a second flush of a payload that has already been taken — the
   *  no-op it lands on is harmless, but the timer handle it leaves in `timers` is not, because the
   *  Cancel path clears that handle to purge the row and would clear the wrong one. */
  function flushItemRow(id) {
    var key = "items:" + id;
    if (!pendingPatch[key]) return;
    clearTimeout(timers[key]);
    delete timers[key];
    return flush("items", id, key, true);
  }

  /** The Save button on a new material or a new assembly: send what is typed NOW.
   *
   *  The same path as leaving the row, so a material still gets its one "Save this change?"
   *  question and an assembly still declares the version it edited. Nothing queued means the
   *  record is already exactly what the server holds (the create POST wrote it), so the press
   *  just retires the button. Returns whether the record is still marked new, which is how the
   *  caller knows to keep the button after a Cancel, a 409 or a failed request. */
  async function saveNow(kind, id) {
    var key = kind + ":" + id;
    var worked = false;
    // Loop: a keystroke can land while a save is out, queueing another behind it. Bounded, so a
    // page that keeps producing edits cannot trap the press.
    for (var n = 0; n < 6; n++) {
      if (pendingPatch[key]) {
        clearTimeout(timers[key]);
        delete timers[key];
        worked = true;
        var sent = pendingPatch[key];
        await flush(kind, id, key, true);
        // The same payload back in the buffer means the save failed: one press, one attempt.
        if (pendingPatch[key] === sent) break;
      } else if (takenP[key]) {
        // A flush already took the payload and has not heard back (dialog open, request on the
        // wire). An empty buffer is NOT "saved"; wait for that flush to finish, then judge.
        worked = true;
        await takenP[key];
      } else {
        break;
      }
    }
    // Nothing was queued or in flight at the press: the record is what the server holds (the
    // create POST wrote it), so just retire the button.
    if (!worked && FRESH[kind]) delete FRESH[kind][id];
    // Whatever is left marked is unconfirmed: a Cancel, a 409, a failed request.
    return !!(FRESH[kind] && FRESH[kind][id]);
  }

  /** The Save button follows the unsaved mark live, without waiting for a repaint (a repaint of
   *  the Items table mid-typing would steal the caret). Items: add or drop the button in that
   *  row's action cell. Assemblies: show or hide #asm-save when that assembly is the open one. */
  function itemSaveButtonHtml(id, name) {
    return '<button class="btn sm" type="button" data-save-new="items" data-save-id="' + esc(id) +
      '" title="Save this material now" aria-label="Save ' + esc(name) + '">Save</button>';
  }
  function showUnsaved(kind, id) {
    if (typeof document === "undefined") return;
    if (kind === "assemblies") {
      var b = $("asm-save");
      if (b && openId === id) b.hidden = false;
      return;
    }
    var cell = document.querySelector('#items-body [data-item="' + id + '"] .rowact');
    if (cell && !cell.querySelector("[data-save-new]")) {
      var tmp = document.createElement("span");
      tmp.innerHTML = itemSaveButtonHtml(id, (itemOf(id) || {}).name || "");
      cell.insertBefore(tmp.firstChild, cell.firstChild);
    }
  }
  function hideUnsaved(kind, id) {
    if (typeof document === "undefined") return;
    if (kind === "assemblies") {
      var b = $("asm-save");
      if (b && openId === id) b.hidden = true;
      return;
    }
    var btn = document.querySelector('#items-body [data-item="' + id + '"] [data-save-new]');
    if (btn && btn.parentNode) btn.parentNode.removeChild(btn);
  }

  /** LEAVING THE PAGE MUST NOT LOSE A TYPED CHANGE. Send everything queued the moment the tab goes
   *  to the background or the page is hidden/closed (autosave stays as the backup for the rest).
   *  A material's "Save this change?" question cannot be answered on a closing page, so that one
   *  waits for the estimator's return; assemblies and the rest go out. */
  function flushAllPending() {
    Object.keys(pendingPatch).forEach(function (key) {
      var cut = key.indexOf(":");
      var kind = key.slice(0, cut), id = key.slice(cut + 1);
      clearTimeout(timers[key]);
      delete timers[key];
      flush(kind, id, key, true);
    });
  }
  /** True while any save is still unconfirmed: queued, or taken and waiting on the server. */
  function savePending() {
    return Object.keys(pendingPatch).length > 0 || Object.keys(takenP).length > 0;
  }

  /** Focus left an item row → that row's edits go in, and get their one question.
   *
   *  `relatedTarget` is where the focus is GOING. Inside the same row it is still the same visit —
   *  the cost box to the vendor dropdown, or that row's own Duplicate button — so nothing fires.
   *  A null relatedTarget is a click on something unfocusable, which IS leaving. */
  function onItemRowFocusOut(e) {
    var row = e.target.closest && e.target.closest("[data-item]");
    if (!row) return;
    var to = e.relatedTarget;
    if (to && row.contains && row.contains(to)) return;
    return flushItemRow(row.getAttribute("data-item"));
  }

  async function post(kind, body) {
    var r = await api("/api/library/" + kind, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(j.detail || j.error || ("HTTP " + r.status));
    return j;
  }

  async function del(kind, id) {
    var r = await api("/api/library/" + kind + "/" + encodeURIComponent(id), { method: "DELETE" });
    if (!r.ok) {
      var j = await r.json().catch(function () { return {}; });
      throw new Error(j.detail || j.error || ("HTTP " + r.status));
    }
  }

  /** A default switch, sent immediately -- never through patchSoon. That queue exists for a typed
   *  field whose save is worth debouncing and, for an item, worth confirming ("this is priced into
   *  every assembly that uses it"); switching a default changes no price and no assembly, so
   *  routing it through the same pipe would ask the estimator to confirm a change with no
   *  consequence to describe. One field, sent on the press, the same as Duplicate and Remove.
   *
   *  THE COLUMN IS STILL CALLED `favorite` IN THE DATABASE, and that is deliberate rather than
   *  sloppy. It was the star's column, the star is gone, and the flag it held was read by nothing
   *  -- no sort, no filter, no default -- so it was free to take over. Renaming it would be DDL on
   *  two separate databases, which is this project's documented way of shipping a 502. The name is
   *  wrong and the migration is worse; this comment is the trade. */
  async function patchDefault(kind, id, on) {
    var r = await api("/api/library/" + kind + "/" + encodeURIComponent(id), {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ favorite: on }) });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(j.detail || j.error || ("HTTP " + r.status));
    return j;
  }

  /** The Defaults tab's on/off slider: does this default START ON in a new bid. Sent on the press,
   *  beside patchDefault for the same reason patchLabor is -- that one sends `{ favorite }` and
   *  nothing else. A database without the default_on column answers 502 here, which setDefaultOn
   *  turns into the put-it-back and a message, never a slider that looks saved and is not. */
  async function patchDefaultOn(kind, id, on) {
    var r = await api("/api/library/" + kind + "/" + encodeURIComponent(id), {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ default_on: !!on }) });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(j.detail || j.error || ("HTTP " + r.status));
    return j;
  }

  /** Which work types a default is offered for, sent on every chip press.
   *
   *  BESIDE patchDefault RATHER THAN THROUGH IT, for the reason the labor patch below gives:
   *  that one sends `{ favorite }` and nothing else. library.py has accepted, coerced and
   *  returned `default_work_types` on items, assemblies AND labor since the column landed --
   *  this is the half that was missing, and its absence is why the work-type chips filtered
   *  nothing. Every row in the library carried `[]`, appliesToWorkType reads `[]` as "applies
   *  everywhere", so all five chips rendered one identical list. Hanz, 2026-09-21: "the filters
   *  in items in assemblies on the default items in assemblies. Is not working." */
  async function patchWorkTypes(kind, id, list) {
    var r = await api("/api/library/" + kind + "/" + encodeURIComponent(id), {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ default_work_types: list }) });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(j.detail || j.error || ("HTTP " + r.status));
    return j;
  }

  /** One labor default's typed fields, sent on Save.

   *  BESIDE patchDefault RATHER THAN THROUGH IT. That one sends `{ favorite }` and nothing else,
   *  which is the whole of what a takeoff default is. A labor line has a name, a rate and a unit,
   *  and widening the function every takeoff row presses so it could also carry them would put a
   *  body behind a control that can never produce one. Adding beside beats editing working. */
  async function patchLabor(id, body) {
    var r = await api("/api/library/labor/" + encodeURIComponent(id), {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(j.detail || j.error || ("HTTP " + r.status));
    return j;
  }

  /** One condition's default answer, sent on the change.

   *  A PUT, NOT A PATCH, because the row IS the answer: there is one editable field and the
   *  request states it in full. `set_default` upserts on the key, so the first press creates the
   *  row and every press after it moves the same one -- which is what keeps "one live row per
   *  condition" true without the client knowing whether a row exists.

   *  BESIDE patchDefault RATHER THAN THROUGH IT, the same call patchLabor makes: that one sends
   *  `{ favorite }` against /api/library/<kind>/<id>, and a condition has no library row and no
   *  id. Widening it would put a body behind a control that can never produce one. */
  // WRITES `listed` -- AND `on: false` -- since 2026-10-01. Whether a new estimate shows the
  // condition's card (grayed until switched on) is what the Defaults tab edits now, and Hanz's
  // rule is that all three START off: "dont start as on". So every press here also clears any
  // `on: true` an earlier version of this tab stored (its Add button wrote one), or a condition
  // removed from the list would still open switched on, and priced, on every new bid.
  async function putConditionDefault(key, body) {
    var r = await api("/api/condition-defaults/" + encodeURIComponent(key), {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(j.detail || j.error || ("HTTP " + r.status));
    return j;
  }

  // ── items ──────────────────────────────────────────────────────────────────
  /** A dropdown that never loses what the row already says.
   *
   *  `list` is what we offer; `value` is what the row holds. A value that isn't on the list — a
   *  legacy "Gal", a vendor since removed — is rendered as its own selected option. The
   *  alternative is a select that silently displays the first entry instead, which would rewrite
   *  the row the next time anybody touched it. */
  function pick(field, value, list, label, extra) {
    var v = String(value == null ? "" : value);
    // Case-insensitively, so a row holding "sherwin-williams" selects the curated
    // "Sherwin-Williams" instead of appearing beside it as a second supplier. A value that differs
    // by more than case ("Gal" against "Gallon") is genuinely off-list and gets its own option.
    var lower = v.toLowerCase();
    var match = "";
    for (var k = 0; k < list.length; k++) {
      if (String(list[k]).toLowerCase() === lower) { match = list[k]; break; }
    }
    var s = '<select data-f="' + field + '" aria-label="' + esc(label) + '"' + (extra || "") + ">";
    s += '<option value=""' + (v ? "" : " selected") + ">—</option>";
    if (v && !match) s += '<option value="' + esc(v) + '" selected>' + esc(v) + "</option>";
    for (var i = 0; i < list.length; i++) {
      s += '<option value="' + esc(list[i]) + '"' + (list[i] === match ? " selected" : "") + ">" +
           esc(list[i]) + "</option>";
    }
    return s + "</select>";
  }

  /** The Division cell: one toggle chip per division, side by side on ONE line.
   *
   *  Hanz, 2026-08-24: "For the [divisions] can we have it in just one row? Also instead of a
   *  checkbox please pick a better UI that allows a material to have multiple divisions but they
   *  show up in one row." Three stacked checkbox labels made every row of this table three lines
   *  tall, which is the whole complaint.
   *
   *  N DIVISIONS, NOT THREE. The list is loaded from /api/library/divisions and merged with
   *  whatever old items already say (divisionNames), and the Administration tab lets anybody with
   *  the rights add another. So the strip wraps rather than stretches: three fit on one line, six
   *  take two, and a long custom name keeps its first 22 characters with the rest in the tooltip.
   *  A fixed-width segmented control could not survive any of that.
   *
   *  THE SAME SHAPE AS THE NOTIFICATION CHIPS in the CRM drawer, where a filled pill means on and
   *  the page says so in words. Its own class rather than nt-chip, for the reason recipientsHtml
   *  gives in portal.js: green there means "receives this project's emails", and borrowing the
   *  class would say something untrue here. The rules sit in this page's own style block because
   *  nt-chip is not in styles.css either, portal.html, notifications.html and done.html each keep
   *  a copy, and this page may not edit theirs.
   *
   *  STILL A REAL CHECKBOX, only drawn as a pill. A div with aria-pressed would have to
   *  re-implement Tab, Space and the announced state; the input arrives with all three, with
   *  multi-select semantics no screen reader can mistake for a radio group, and it leaves the save
   *  contract exactly where it was: onItemEdit still reads data-f="divisions" and data-div off the
   *  input that changed.
   *
   *  COLOUR IS NOT THE ONLY SIGNAL. The face carries a mark that changes SHAPE with the state, a
   *  tick when the material is in that division and a plus when it is not, so the on chips stay
   *  countable in greyscale. That mark is CSS content keyed off :checked rather than markup,
   *  because a click must not re-render the row: rebuilding the cell would throw away the focus
   *  the estimator just tabbed into, so anything state-dependent has to be reachable by a
   *  selector instead. */
  function divisionPick(it) {
    var selected = {};
    itemDivisions(it).forEach(function (d) { selected[d.toLowerCase()] = true; });
    var names = divisionNames();
    return '<div class="division-chips" role="group" aria-label="Divisions">' +
      names.map(function (d) {
        var on = !!selected[String(d).toLowerCase()];
        return '<label class="dchip" title="' + esc(d) + '">' +
          '<input type="checkbox" data-f="divisions" data-div="' + esc(d) + '" aria-label="' +
          esc(d) + '"' + (on ? " checked" : "") + ">" +
          '<span class="dchip-f"><span class="dchip-mark" aria-hidden="true"></span>' +
          '<span class="dchip-t">' + esc(d) + "</span></span></label>";
      }).join("") + "</div>";
  }

  /** What the Vendor dropdown offers: the curated list, plus any supplier already named on a
   *  material that isn't on it yet.
   *
   *  The union matters because only an admin may add to the list. Without it, an estimator on a
   *  fresh install could not record a vendor at all — the box they used to type into would be a
   *  dropdown with nothing in it. Names already on materials ARE Treadwell's vendors; they just
   *  haven't been curated yet.
   *
   *  Matched case-insensitively with the curated spelling winning, so "sika" typed last month
   *  doesn't reappear beside "Sika" and re-create the duplication this list exists to end. */
  function vendorNames() {
    var names = VENDORS.map(function (v) { return v.name; });
    var seen = {};
    names.forEach(function (n) { seen[String(n).toLowerCase()] = true; });
    var extra = [];
    ITEMS.forEach(function (it) {
      var v = String(it.vendor || "").trim();
      if (!v || seen[v.toLowerCase()]) return;
      seen[v.toLowerCase()] = true;
      extra.push(v);
    });
    extra.sort(function (a, b) { return a.localeCompare(b); });
    return names.concat(extra);
  }

  function itemDivisions(it) {
    var raw = Array.isArray((it || {}).divisions) ? it.divisions.slice() : [];
    if (!raw.length && (it || {}).category) raw.push(it.category);
    var seen = {}, out = [];
    raw.forEach(function (d) {
      var v = String(d || "").trim();
      var key = v.toLowerCase();
      if (!v || seen[key]) return;
      seen[key] = true;
      out.push(v);
    });
    return out;
  }

  function namesWithItemExtras(refs, field, listGetter) {
    var names = refs.slice();
    var seen = {};
    names.forEach(function (n) { seen[String(n).toLowerCase()] = true; });
    ITEMS.forEach(function (it) {
      var vals = listGetter ? listGetter(it) : [it[field]];
      vals.forEach(function (raw) {
        var v = String(raw || "").trim();
        if (!v || seen[v.toLowerCase()]) return;
        seen[v.toLowerCase()] = true;
        names.push(v);
      });
    });
    return names;
  }

  function divisionNames() { return namesWithItemExtras(DIVISIONS, "divisions", itemDivisions); }
  function unitNames() { return namesWithItemExtras(UNITS, "unit"); }

  function qtyText(v) {
    var n = Number(v);
    if (!isFinite(n)) return "";
    return String(Math.round(n * 1000) / 1000).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
  }

  function orderAmount(it) {
    if (!it) return "—";
    return qtyText((it.buy_qty == null ? 1 : it.buy_qty)) + " " + String(it.unit || "Unit");
  }

  function optionsHtml(list, selected) {
    var out = '<option value="">—</option>';
    var sel = String(selected || "").toLowerCase();
    list.forEach(function (name) {
      out += '<option value="' + esc(name) + '"' +
        (String(name).toLowerCase() === sel ? " selected" : "") + ">" + esc(name) + "</option>";
    });
    return out;
  }

  /** Materials whose name looks like this one's, so two people don't enter the same product twice
   *  under two spellings. A hint, not a block: the same product legitimately appears twice at
   *  different coverages, and Hanz asked for "a hint … to avoid duplicates". */
  function similarNames(name, selfId) {
    var n = String(name || "").trim().toLowerCase();
    if (n.length < 3) return [];
    var hits = [];
    for (var i = 0; i < ITEMS.length && hits.length < 3; i++) {
      var other = ITEMS[i];
      if (other.id === selfId) continue;
      var o = String(other.name || "").toLowerCase();
      if (o && (o.indexOf(n) !== -1 || n.indexOf(o) !== -1)) hits.push(other.name);
    }
    return hits;
  }

  function dupeHtml(names) {
    if (!names.length) return "";
    return '<div class="dupe">Already in the list: ' + esc(names.join(", ")) + "</div>";
  }



  /** "by Hanz" for a row that names someone, and an honest "by unknown" for one that cannot.
   *
   *  `CRM.nameOf` is the app's single email→display-name convention (crm-core.js) — the same one
   *  the Assemblies rail sorts by, so one person reads identically on both tabs. The name is a
   *  `<b>` so it takes the emphasis `.dates b` already gives a date, rather than needing a class.
   *
   *  "unknown" is not a failure state and not "nobody": `updated_by` was added to the tables on
   *  2026-09-04, so every row filed before that carries no editor and never will. Rendering the
   *  line bare would read as a name that failed to load. */
  function byHtml(email) {
    var n = CRM.nameOf(String(email || ""));
    return n ? 'by <b>' + esc(n) + "</b>" : 'by <span class="never">unknown</span>';
  }  /** Who added it, when the price last moved, and who last changed it.
   *
   *  Three lines rather than the original two, because Hanz asked for the NAMES on this tab and
   *  "when" without "who" answers half the question people bring to a shared library.
   *
   *  THE MIDDLE LINE HAS NO NAME ON PURPOSE. `cost_updated_at` is decided server-side when the
   *  cost really moved, and no column records who moved it — pairing it with `updated_by` would
   *  attribute a price change to whoever last fixed a spelling. It stays the question it already
   *  answered: "how old is this number?"
   *
   *  `updated_at === created_at` is the server's own way of saying nothing has happened since the
   *  row was filed, because a create stamps both columns in one write. So that case reads as "not
   *  edited since" rather than as an edit by the creator — the same distinction the price line
   *  already drew with "not since we started tracking" -- a line this cell no longer prints.
   *
   *  TWO LINES, NOT THREE, since 2026-09-18. The price line came out ("too much clutter"): it
   *  answered "how old is this number?" for a number sitting in the very next column along,
   *  and it was the third stacked line on every row of a dense editing table. cost_updated_at
   *  is still stored, still returned, and still what the Price-updated sort orders by. */
  function datesHtml(it) {
    var made = it.created_at ? TW.fmtBizDateTime(it.created_at) : "—";
    var edited = (it.updated_at && it.updated_at !== it.created_at)
      ? "Edited <b>" + esc(TW.fmtBizDateTime(it.updated_at)) + "</b> " + byHtml(it.updated_by)
      : '<span class="never">not edited since</span>';
    return '<div class="dates"><div>Added <b>' + esc(made) + "</b> " +
             byHtml(it.owner_email) + "</div>" +
           // NO PRICE LINE. Hanz, 2026-09-18: "too much clutter" -- three stacked lines on
           // every row of a dense editing table was two more than anyone reads, and the price
           // one was the least of them: it answered "how old is this number?" for a number
           // shown in the very next column along.
           //
           // cost_updated_at IS STILL STORED, still returned by the API, and still what the
           // Price-updated sort orders by. Only the printing went.
           "<div>" + edited + "</div></div>";
  }

  /** Rewrite one row's Dates cell in place.
   *
   *  In place, not renderItems(): the debounce fires 600ms after the last keystroke, so the reply
   *  routinely lands while somebody is still in the field. Rebuilding the row would move their
   *  caret to the end of it. The Dates cell holds no inputs, so replacing it is safe. */
  function paintDates(it) {
    var cell = document.querySelector('[data-item="' + it.id + '"] .datescell');
    if (cell) cell.innerHTML = datesHtml(it);
  }  /** The library's own comparison form of a name: case, spacing and punctuation all ignored.
   *
   *  Mirrors `_item_key` in backend/library.py, which is what actually REFUSES a duplicate. It is
   *  a mirror rather than the authority, and the two differ on one point worth knowing: Python's
   *  str.isalnum() keeps accented letters, this drops them. That only ever makes the client more
   *  cautious about a name than the server is, so the worst case is a copy numbered (3) when (2)
   *  was free — never a name the client offers and the server then rejects. */
  function nameKey(s) {
    return String(s == null ? "" : s).toLowerCase().replace(/[\s\W_]+/g, "");
  }

  /** "Densifier" → "Densifier (2)", and a copy of that → "Densifier (3)".
   *
   *  HANZ'S FORMAT, 2026-08-25, and it diverges from the house one deliberately: `uniqueLabel` in
   *  estimate-review.js produces "Densifier copy 2". He asked for the parenthesised form on this
   *  page, the two lists never appear together, and following the wording he gave costs nothing.
   *
   *  Counts from 2, as uniqueLabel does — "(1)" reads as the first of a set and implies the
   *  original was renamed too. The trailing "(n)" is stripped off the stem first, so duplicating a
   *  copy gives "Densifier (3)" rather than "Densifier (2) (2)".
   *
   *  Collisions are checked through nameKey and not by exact string, because the server's block
   *  strips punctuation: "Densifier(2)" and "Densifier (2)" are one name to it. A counter that
   *  only avoided exact matches would hand back a name the save then refuses, which reads as the
   *  Duplicate button being broken. */
  function duplicateName(base) {
    var stem = String(base == null ? "" : base).trim().replace(/\s*\(\d+\)$/, "").trim();
    if (!stem) stem = "New material";
    var taken = {};
    ITEMS.forEach(function (x) { taken[nameKey(x.name)] = true; });
    for (var n = 2; n <= 999; n++) {
      var candidate = stem + " (" + n + ")";
      if (!taken[nameKey(candidate)]) return candidate;
    }
    return stem + " (copy)";
  }

  /** Does anything on `list` already answer to this name, in the server's comparison form? */
  function nameTaken(name, list) {
    var k = nameKey(name);
    return (list || []).some(function (x) { return nameKey(x && x.name) === k; });
  }

  /** The name "+ Add material" creates a row under.
   *
   *  It used to post the literal "New material" every time. `create_item` refuses a duplicate name
   *  with a 400, so the SECOND press of that button was simply dead — "Couldn't add that material.
   *  "New material" is already in the library." — with nothing on screen to suggest that the fix
   *  was to go and rename the row from last time.
   *
   *  BARE STEM FIRST, and that is the whole reason this is not just a call to duplicateName:
   *  that function counts from 2 and never offers the stem, which is right for a COPY (a copy of
   *  "Densifier" must not also be called "Densifier") and wrong here, where the plain name is the
   *  one the row wants. Once it is taken, the numbering is the same one the Duplicate button
   *  uses, so the two never disagree about what a free name looks like. */
  function newMaterialName(stem) {
    var base = String(stem == null ? "" : stem).trim() || "New material";
    return nameTaken(base, ITEMS) ? duplicateName(base) : base;
  }

  /** The same thing for the Administration tab, which carries the identical literal default
   *  ("New vendor", "New division", "New unit") against the identical duplicate block.
   *
   *  Checked against that tab's OWN list: uniqueness is per table, so a material called
   *  "New vendor" must not stop the Vendors tab from adding one. */
  function newRefName(kind) {
    var base = "New " + singular(kind);
    var list = adminList(kind);
    if (!nameTaken(base, list)) return base;
    for (var n = 2; n <= 999; n++) {
      if (!nameTaken(base + " (" + n + ")", list)) return base + " (" + n + ")";
    }
    return base + " (copy)";
  }

  function renderItems() {
    var out = "";
    var shown = visibleItems();
    for (var i = 0; i < shown.length; i++) {
      var it = shown[i];
      out += '<tr data-item="' + esc(it.id) + '">' +
        '<td><input data-f="name" class="cell-name" value="' + esc(it.name) + '" aria-label="Material name, as the manufacturer names it" maxlength="200" list="dl-materials">' +
          dupeHtml(similarNames(it.name, it.id)) + "</td>" +
        "<td>" + divisionPick(it) + "</td>" +
        '<td class="n"><input data-f="buy_qty" class="num cell-qty" value="' + (it.buy_qty == null ? "" : it.buy_qty) + '" aria-label="How many units come in one purchase"></td>' +
        "<td>" + pick("unit", it.unit, unitNames(), "Unit", ' class="cell-unit"') + "</td>" +
        // COVERAGE, WASTE AND ROUNDUP LIVE ON THE MATERIAL, from 2026-09-22. Hanz: "we must have
        // coverage per unit, waste factor, roundup, and materials tab. And then it gets pulled in
        // to assemblies instead of it being in assemblies." No per-line override: a material used
        // at two coverages is two materials (see the migration note in library.py). Same width
        // classes (.n.w-cov / .n.w-waste / .w-ru) the assembly-lines table already defines for
        // these three columns — reused here, not reinvented.
        '<td class="n w-cov"><input data-f="coverage" class="num" value="' + (it.coverage == null ? "" : it.coverage) + '" aria-label="Coverage per unit"></td>' +
        '<td class="n w-waste"><input data-f="waste_pct" class="num" value="' + (it.waste_pct == null ? "" : it.waste_pct) + '" aria-label="Waste factor, percent"></td>' +
        // Unchecked only when roundup is explicitly false. NULL and true both read as checked --
        // "absent means yes" (library-core.js's priceLine), so the box must not show unticked for
        // a material nobody has touched yet.
        '<td class="w-ru"><input type="checkbox" data-f="roundup"' +
          (it.roundup === false ? "" : " checked") + ' aria-label="Round up to whole purchase units"></td>' +
        // REMOVE EXISTING JOINT FILLER BUYS NOTHING, so its cost cell says so instead of offering
        // a box. It is a fourth hand on the joint-filler line, priced on the Labor step, and the
        // Polish estimate never reads a material price off this row -- a figure typed here would
        // sit in the library looking like a charge that no bid makes.
        '<td class="n">' + (it.id === "remove-existing-jf"
          ? '<span class="builtin">No material cost</span>'
          : '<span class="money"><span>$</span><input data-f="unit_cost" class="num cell-cost" value="' + (it.unit_cost == null ? "" : it.unit_cost) + '" aria-label="Cost of one purchase"></span>') + "</td>" +
        "<td>" + pick("vendor", it.vendor, vendorNames(), "Vendor", ' class="cell-vendor"') + "</td>" +
        '<td class="datescell">' + datesHtml(it) + "</td>" +
        '<td class="rowact">' +
          (FRESH.items[it.id]
            ? itemSaveButtonHtml(it.id, it.name)
            : "") +
          '<button class="icon" type="button" data-dupe-item="' + esc(it.id) + '" title="Make a copy of this material" aria-label="Duplicate ' + esc(it.name) + '">' + icon("copy") + "</button>" +
          // NO REMOVE ON THE THREE RESERVED ROWS (joint filler kit, remove-existing, dye) -- see
          // isReservedItem. Every other cell on the row stays editable; that is the point of it.
          (isReservedItem(it.id) ? "" :
          '<button class="icon danger" type="button" data-del-item="' + esc(it.id) + '" title="Remove this material" aria-label="Remove ' + esc(it.name) + '">' + icon("trash") + "</button>") +
          "</td>" +
      "</tr>";
    }
    $("items-body").innerHTML = out;
    // Three states, not two: nothing in the library, nothing matching the search, and rows. The
    // "No materials yet" panel offers an Add button, which is the wrong thing to offer somebody
    // who has 40 materials and a typo in the search box.
    // A FACET COUNTS AS FILTERING, not just the text box. The version of this line that read
    // only itemQuery left the no-match panel hidden whenever the search box was empty, so
    // narrowing to a division that nothing is filed under produced a blank table with the add
    // row gone and nothing on screen saying why.
    var filtering = anyFilterActive();
    $("items-empty").hidden = ITEMS.length > 0;
    if ($("items-nomatch")) {
      $("items-nomatch").hidden = !(filtering && ITEMS.length > 0 && shown.length === 0);
    }
    // The empty state names what it left out. "Nothing matches that" on its own makes the
    // estimator reconstruct the query from three controls and a text box to find the one that
    // went too far.
    if ($("items-nomatch-why")) {
      $("items-nomatch-why").textContent = filtering
        ? "No materials " + filterSummary() + "." : "";
    }
    // THE ADD ROW IS THE NEXT ROW OF THE TABLE, so it belongs to the table having rows. Under
    // "No materials yet" it would be the second Add button in one card, and under "Nothing
    // matches that" it would answer a typo with an invitation to create the duplicate the search
    // just failed to find — the same trap the two empty states were split apart to avoid.
    if ($("items-addrow")) $("items-addrow").hidden = shown.length === 0;
    if ($("item-hits")) {
      $("item-hits").hidden = !filtering;
      $("item-hits").textContent = filtering
        ? shown.length + " of " + ITEMS.length + " shown" : "";
    }
    // The tab badge stays the TOTAL. It is how many materials Treadwell has, not how many are on
    // screen right now, and a badge that moved as somebody typed would read as rows disappearing.
    $("n-items").textContent = ITEMS.length;
    // Feeds both the name field's own autosuggest and the assemblies' searchable picker.
    $("dl-materials").innerHTML = ITEMS.map(function (it) {
      return '<option value="' + esc(it.name) + '"></option>';
    }).join("");
  }

  // ── labor, 2026-09-24 ─────────────────────────────────────────────────────────
  // Hanz: "we dont have a tab for labor like the items and assemblies so we add a tab like that
  // for all default labor then if we want it to be a default we add it to 'Default items &
  // Assemblies'." EVERY LABOR LINE THE CATALOG HOLDS lives here -- creation, editing and
  // deletion -- as its own peer to Items and Assemblies. WHETHER ONE IS A DEFAULT is a separate,
  // sequential question, answered on the Default Items & Assemblies tab (renderDefaultLabor)
  // exactly the way it already is for a material or an assembly. The two tabs read the same
  // `LABOR` array and the same `favorite` column; this one shows every row, that one shows only
  // the favorited ones.

  var NUMERIC_LABOR_FIELDS = ["rate", "sort"];

  /** Which rows have their guys_auto/sort fields open. Module state, not a property on the row --
   *  the same reason `pickerOpen` is not stored on an assembly line: which row has "more" open is
   *  this SCREEN's business, and it must not ride along on a save the way a persisted field would. */
  var laborMoreOpen = {};

  /** One edit inside the Labor tab's table -- name, rate, unit or notes as headline fields, and
   *  guys_auto/sort behind the "more" disclosure. Debounced onto the wire the same way Items' own
   *  inline table already is, generalized to a third row-kind rather than reached for a second
   *  time: patchSoon/flush/arm/post/del do not know or care that "labor" is new to them.
   *
   *  NO CONFIRMATION DIALOG, unlike onItemEdit. That gate is a PRICING-INTEGRITY control, Hanz's
   *  own words, because an item's cost reprices every assembly built on it live the moment it
   *  saves. A labor rate has no such fan-out -- it only ever reaches a bid through `favorite`, on
   *  a SEPARATE press, on a SEPARATE tab, so there is nothing here for the dialog to protect. */
  function onLaborEdit(e) {
    var f = e.target.getAttribute && e.target.getAttribute("data-f");
    if (!f) return;
    var row = e.target.closest("[data-labor]");
    if (!row) return;
    var r = byId("labor", row.getAttribute("data-labor"));
    if (!r) return;
    var body = {};
    if (f === "guys_auto") {
      r.guys_auto = !!e.target.checked;
      body.guys_auto = r.guys_auto;
    } else {
      var raw = e.target.value;
      r[f] = NUMERIC_LABOR_FIELDS.indexOf(f) !== -1 ? L.num(raw) : raw;
      body[f] = raw;
      // The row is NOT redrawn under the caret, so the two buttons that name the line by their
      // aria-label would keep announcing the old name (Remove New labor line). Say the new one.
      if (f === "name" && row.querySelector) {
        var mb = row.querySelector("[data-labor-more-toggle]");
        var db = row.querySelector("[data-del-labor]");
        if (mb) mb.setAttribute("aria-label", (mb.getAttribute("aria-expanded") === "true"
          ? "Hide" : "Show") + " more fields for " + raw);
        if (db) db.setAttribute("aria-label", "Remove " + raw);
      }
    }
    // THE DEFAULTS TAB DRAWS THE SAME ROW, and a tab switch only flips `hidden` -- it does not
    // repaint. Without this a renamed or re-rated default reads the old figure there until the
    // next reload. That table is on another pane, so redrawing it cannot move this caret.
    renderDefaultLabor();
    patchSoon("labor", r.id, body);
  }

  /** Show or hide one row's guys_auto/sort fields. The redraw replaces the button that was
   *  pressed, so the focus goes back onto its successor rather than to the top of the page. */
  function toggleLaborMore(id) {
    laborMoreOpen[id] = !laborMoreOpen[id];
    renderLabor();
    var lb = $("labor-body");
    var b = lb && lb.querySelector && lb.querySelector('[data-labor-more-toggle="' + id + '"]');
    if (b && b.focus) b.focus();
  }

  /** Put the caret in an Items tab row's name box -- where the Defaults tab's Edit on a material
   *  lands, the job focusLaborRow below does for a labor line.
   *
   *  IT WAS CALLED AND NEVER DEFINED. The Edit router has called focusItemRow since #532, and no
   *  function by that name existed, so every material Edit switched to the Items tab and then
   *  threw a ReferenceError: the tab changed, the caret went nowhere, and the console said why.
   *  Hanz's 2026-10-01 ask -- Edit on joint filler, remove-existing or dye "opens that material's
   *  row" -- is the first time anything leant on the second half of that.
   *
   *  A ROW THE ITEMS TAB'S OWN SEARCH IS HIDING comes back first. The search and the facets
   *  outlive a tab switch, so an estimator who filtered for "densifier" an hour ago and then pressed
   *  Edit on Dye would otherwise land on a table without the row they asked for -- a dead button,
   *  by another route. clearFilters is the same Clear the bar and the empty state already offer. */
  function focusItemRow(id) {
    var find = function () {
      var body = $("items-body");
      return body && body.querySelector && body.querySelector(
        '[data-item="' + id + '"] input[data-f="name"]');
    };
    var el = find();
    if (!el && anyFilterActive()) { clearFilters(); el = find(); }
    if (el && el.focus) el.focus();
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "center" });
  }

  /** Put the caret in a Labor tab row's name box -- the job refocusItemField does for Items,
   *  reached from the Defaults tab's Edit button on a favorited line, and from Travel's own Edit,
   *  which now sends an admin here instead of opening the form that used to live on that tab. */
  function focusLaborRow(id) {
    var lb = $("labor-body");
    var el = lb && lb.querySelector && lb.querySelector(
      '[data-labor="' + id + '"] input[data-f="name"]');
    if (el && el.focus) el.focus();
  }

  /** The Labor tab: every labor line the catalog holds, Travel included -- name, rate, unit and
   *  notes as the headline columns, one row per line, always editable in place. Modeled directly
   *  on renderItems() -- a flat, always-editable inline table -- and NOT on Assemblies' card-rail-
   *  with-nested-editor shape, because a labor line is a flat record with no sub-list of its own.
   *
   *  UNFILTERED BY `favorite`, ON PURPOSE. This is the catalog -- "every labor type Treadwell can
   *  bill" -- not "what a new bid opens holding", which is the Defaults tab's own filtered read of
   *  these same rows (see renderDefaultLabor). Creating a line here and making it a default are
   *  two separate, sequential actions on two different tabs, and this table is the first of them,
   *  never the second.
   *
   *  TRAVEL IS A ROW HERE TOO, fully editable in place the same way its Defaults-tab row already
   *  lets it be -- the delete icon is the ONE control this function withholds for it
   *  (`id === "travel"`), matching the server's own fail-closed refusal in delete_labor(). Hiding
   *  the icon is a UI nicety on top of that refusal, never a substitute for it: a caller that goes
   *  around this render still meets the 400 `delete_labor` raises. Travel carries no work-type
   *  chips either: it is seeded into every estimate whatever its list says, so a chip on it would
   *  be a control that changes nothing.
   *
   *  TEXT, NOT INPUTS, FOR ANYBODY BUT AN ADMIN. Every write to library_labor is admin-only on the
   *  server (`_require_admin`), so this follows the Administration lists' own rule: a non-admin
   *  reads the rates and is handed nothing that would 403 on press -- no inputs, no chips, no
   *  More, no Add and no delete.
   *
   *  THE UNIT IS ITS OWN TWO-OPTION SELECT, not pick(). pick() offers a blank "—" first, and a
   *  blank unit saves as "hours" on the server while the screen goes on saying "—": the one field
   *  here that decides what the rate multiplies must not be able to show one thing and store
   *  another. */
  function renderLabor() {
    var body = $("labor-body");
    if (!body) return;
    var out = "";
    for (var i = 0; i < LABOR.length; i++) {
      var r = LABOR[i];
      var travel = r.id === "travel";
      var perUnit = (r.unit === "days" ? " / day" : " / hr");
      var everyBid = '<span class="wtall">Every estimate</span>';
      if (!ADMIN) {
        out += '<tr data-labor="' + esc(r.id) + '">' +
          "<td><b>" + esc(r.name) + "</b></td>" +
          '<td class="n">' + esc(L.money(r.rate)) + perUnit + "</td>" +
          "<td>" + esc(r.unit) + "</td>" +
          "<td>" + esc(r.notes) + "</td>" +
          "<td>" + (travel ? everyBid : workTypeLabel(r)) + "</td>" +
          '<td class="rowact"></td></tr>';
        continue;
      }
      var open = !!laborMoreOpen[r.id];
      var units = "";
      for (var u = 0; u < LABOR_UNITS.length; u++) {
        units += '<option value="' + esc(LABOR_UNITS[u]) + '"' +
          (r.unit === LABOR_UNITS[u] ? " selected" : "") + ">" + esc(LABOR_UNITS[u]) + "</option>";
      }
      out += '<tr data-labor="' + esc(r.id) + '">' +
        '<td><input data-f="name" class="cell-name" value="' + esc(r.name) +
          '" aria-label="Labor line name" maxlength="200"></td>' +
        '<td class="n"><span class="money"><span>$</span><input data-f="rate" class="num cell-rate" value="' +
          esc(r.rate == null ? "" : String(r.rate)) + '" aria-label="Rate"></span></td>' +
        '<td><select data-f="unit" class="cell-unit" aria-label="Priced per">' + units +
          "</select></td>" +
        '<td><input data-f="notes" class="cell-note" value="' + esc(r.notes) +
          '" aria-label="Notes" maxlength="4000"></td>' +
        "<td>" + (travel ? everyBid : workTypeCell("labor", r)) + "</td>" +
        '<td class="rowact">' +
          '<button class="btn ghost sm" type="button" data-labor-more-toggle="' + esc(r.id) +
            '" aria-expanded="' + (open ? "true" : "false") + '" aria-label="' +
            (open ? "Hide" : "Show") + " more fields for " + esc(r.name) + '">' +
            (open ? "Less" : "More") + "</button>" +
          (travel ? "" :
            '<button class="icon danger" type="button" data-del-labor="' + esc(r.id) +
              '" title="Remove this labor line" aria-label="Remove ' + esc(r.name) +
              '">' + icon("trash") + "</button>") +
        "</td></tr>";
      if (open) {
        out += '<tr data-labor="' + esc(r.id) + '" class="labor-more">' +
          '<td colspan="6">' +
            '<label class="morefield"><input type="checkbox" data-f="guys_auto"' +
              (r.guys_auto ? " checked" : "") +
              '> Man-days come off the crew rows above it</label>' +
            '<label class="morefield">Position ' +
              '<input type="number" data-f="sort" class="num" value="' +
              (r.sort == null ? 0 : r.sort) + '"></label>' +
          "</td></tr>";
      }
    }
    body.innerHTML = out;
    // Same three-state shape renderItems already draws: nothing in the catalog at all, versus
    // rows. There is no search on this tab (the catalog is small by nature -- a rate per line
    // somebody actually bills), so there is no "nothing matches" state to hold apart from it.
    $("labor-empty").hidden = LABOR.length > 0;
    // Both Add controls are writes, so both follow ADMIN the way renderRefSection's do.
    $("labor-addrow").hidden = !ADMIN || LABOR.length === 0;
    var first = $("labor-empty").querySelector
      ? $("labor-empty").querySelector("[data-add-labor]") : null;
    if (first) first.hidden = !ADMIN;
    if ($("labor-ro")) $("labor-ro").hidden = ADMIN;
    // The badge is the TOTAL, matching #n-items and #n-asm: how many labor lines the catalog
    // holds, not how many are favorited -- that count belongs to the Defaults tab, not this one.
    $("n-labor").textContent = LABOR.length;
  }

  /** "Add labor line": a new row, NOT a default. The body names no `favorite`, so validate_labor
   *  stores false and the column's own default agrees -- the line only reaches a new bid once
   *  somebody adds it on the Default Items & Assemblies tab, which is the whole point of the tab.
   *
   *  NAMED, NOT INLINE IN THE CLICK LISTENER, for the reason openDefaultAdd gives: the harness can
   *  run a function and cannot run a listener. Unshifted, matching Items' own Add, so the new row
   *  lands where the button is. */
  async function addLaborLine() {
    try {
      var lj = await post("labor", { name: "New labor line", rate: 0, unit: "hours" });
      if (!lj.row) return;
      LABOR.unshift(lj.row);
      paint();
      var lb = $("labor-body");
      var lf = lb && lb.querySelector && lb.querySelector(
        '[data-labor="' + lj.row.id + '"] input[data-f="name"]');
      if (lf) { lf.focus(); if (lf.select) lf.select(); }
    } catch (err) { say("Couldn't add that labor line. " + err.message); }
  }

  /** The Labor tab's delete icon: a SOFT delete of the row itself, which is why it asks first and
   *  the Defaults tab's Remove (stop being a default) does not. Travel is refused here as well as
   *  on the server, so a stale page that somehow drew the icon still sends nothing.
   *
   *  NOT OPTIMISTIC. The row stays until the server says it is gone, and a refusal leaves it where
   *  it was with the server's reason on screen. */
  async function removeLaborLine(id) {
    if (!id || id === "travel") return;
    var row = byId("labor", id);
    var ok = await TW.confirmDanger({
      title: "Remove this labor line?",
      name: row ? row.name : "This labor line",
      after: " will be taken out of the library. Any bid already holding it keeps its own " +
        "copy of the rate.",
    });
    if (!ok) return;
    try {
      await del("labor", id);
      // An edit typed into the row just before the press is still queued, and would PATCH a
      // dead id 600ms later -- a 404 about a line the estimator watched go. forgetItem's reason.
      var key = "labor:" + id;
      clearTimeout(timers[key]);
      delete timers[key];
      delete pendingPatch[key];
      LABOR = LABOR.filter(function (r) { return r.id !== id; });
      paint();
    } catch (err) { say("Couldn't remove that labor line. " + err.message); }
  }

  // ── administration ─────────────────────────────────────────────────────────
  function adminList(kind) {
    return kind === "divisions" ? DIVISION_REFS : kind === "units" ? UNIT_REFS : VENDORS;
  }

  function usageFor(kind, name) {
    var key = String(name || "").toLowerCase();
    return (kind === "divisions" ? DIVISION_USE : kind === "units" ? UNIT_USE : VENDOR_USE)[key] || 0;
  }

  function singular(kind) {
    return kind === "divisions" ? "division" : kind === "units" ? "unit" : "vendor";
  }

  function renderRefSection(kind) {
    var list = adminList(kind);
    var out = "";
    for (var i = 0; i < list.length; i++) {
      var v = list[i], one = singular(kind);
      var used = usageFor(kind, v.name);
      out += '<tr data-ref-kind="' + kind + '" data-ref-id="' + esc(v.id) + '">' +
        "<td>" + (ADMIN
          ? '<input data-rf="name" class="cell-ref" value="' + esc(v.name) + '" aria-label="' + one + ' name" maxlength="200">'
          : "<b>" + esc(v.name) + "</b>") + "</td>" +
        "<td>" + (ADMIN
          ? '<input data-rf="notes" class="cell-note" value="' + esc(v.notes) + '" aria-label="Notes" maxlength="4000">'
          : esc(v.notes)) + "</td>" +
        '<td class="n">' + used + "</td>" +
        '<td class="rowact">' + (ADMIN
          ? '<button class="icon danger" type="button" data-del-ref="' + kind + '" data-ref-id="' + esc(v.id) + '" title="Remove this ' + one + '" aria-label="Remove ' + esc(v.name) + '">' + icon("trash") + "</button>"
          : "") + "</td>" +
      "</tr>";
    }
    $(kind + "-body").innerHTML = out;
    $(kind + "-empty").hidden = list.length > 0;
    var addrow = document.querySelector('[data-addrow-ref="' + kind + '"]');
    if (addrow) addrow.hidden = !ADMIN;
    var first = $(kind + "-empty").querySelector
      ? $(kind + "-empty").querySelector("[data-add-ref]") : null;
    if (first) first.hidden = !ADMIN;
  }

  function renderVendors() {
    renderRefSection("divisions");
    renderRefSection("units");
    renderRefSection("vendors");
    $("vendors-ro").hidden = ADMIN;
  }

  // ── assemblies ─────────────────────────────────────────────────────────────
  function renderList() {
    var area = $("area").value, out = "";
    var shown = visibleAssemblies(area);
    for (var i = 0; i < shown.length; i++) {
      var a = shown[i], p = L.priceAssembly(a, ITEMS, area);
      var per = p.per_unit == null ? "not priced" : L.perUnit(p.per_unit) + "/" + esc(a.unit);
      // The value the rail is ORDERED on. A sort whose result cannot be read off the rows is a
      // list that just reshuffled itself; see asmSortLabel for which keys say something and which
      // are already legible.
      //
      // ITS OWN LINE, in the grid .arow already is, and NOT appended to the meta line — which is
      // where the first version put it. The rail is 272px: "3 lines · $1.099/SF ·
      // Sherwin-Williams +1 more" wraps, so the rows with a long vendor became two-line while
      // their neighbours stayed one, and the rail read as ragged. Found in a browser; no DOM
      // assertion can see a wrap. Ellipsis was the other option and it is worse, because the
      // thing that gets truncated first on that line is the price.
      //
      // Reusing .am rather than coining a class: it is the same muted meta treatment at the same
      // size, and a fifth way to draw small grey text under a name is exactly the vocabulary
      // drift this page is trying not to add to.
      var by = asmSortLabel(a, ASM_SORT, ITEMS, p);
      out += '<button class="arow" type="button" data-open="' + esc(a.id) + '"' +
        (a.id === openId ? ' aria-current="true"' : "") + ">" +
        '<span class="an">' + esc(a.name) +
          "</span>" +
        '<span class="am">' + a.lines.length + " line" + (a.lines.length === 1 ? "" : "s") +
        " · " + per + (p.broken_lines ? " · " + p.broken_lines + " to fix" : "") +
        "</span>" +
        (by ? '<span class="am">' + esc(by) + "</span>" : "") +
        "</button>";
    }
    $("asm-list").innerHTML = out;
    // THE CARD, not the list inside it. "+ New assembly" is the rail's FIRST row (Hanz,
    // 2026-09-04) and it has been a child of this card since it left the page header, so hiding
    // just the inner list would leave a create button alone in an empty box while the "No
    // assemblies yet" panel offered a second one beside it.
    $("asm-rail").hidden = ASMS.length === 0;
    // The badge stays the TOTAL, for the reason #n-items does: it says how many systems Treadwell
    // has, and a number that fell as somebody typed would read as assemblies being deleted.
    $("n-asm").textContent = ASMS.length;

    var filtering = anyAsmFilterActive();
    var noMatch = filtering && ASMS.length > 0 && shown.length === 0;
    if ($("asm-nomatch")) $("asm-nomatch").hidden = !noMatch;
    if ($("asm-nomatch-why")) {
      $("asm-nomatch-why").textContent = noMatch
        ? "No assemblies " + asmFilterSummary() + "." : "";
    }
    // "+ New assembly" goes with the rows, and STILL DOES now that it sits above them rather than
    // below: left up, a typo would be answered with an invitation to build the assembly the search
    // just failed to find. Which end of the rail the button lives at changes nothing about that —
    // what it must not do is stand over an empty list offering to create the thing that is missing
    // only because the query was wrong.
    if ($("asm-addrow")) $("asm-addrow").hidden = noMatch;
    if ($("asm-hits")) {
      $("asm-hits").hidden = !filtering;
      $("asm-hits").textContent = filtering
        ? shown.length + " of " + ASMS.length + " shown" : "";
    }
    renderAsmFilterBar();
  }

  /** Does this item answer to `query`, whatever the searcher happened to remember about it?
   *
   *  Hanz, 2026-08-19: "The search option for the Items must be multi dimensional. Could be from
   *  name, divison or vendor or comibation of those." So ONE box matched against all three rather
   *  than a box plus two filter dropdowns — "glaze" finds the product, "polished" finds everything
   *  in that division, "sherwin" finds everything from that supplier, and each result prints its
   *  division and vendor underneath so the match is never a mystery.
   *
   *  Every word has to land somewhere, so "polished glaze" narrows instead of finding nothing:
   *  the fields are searched as one haystack, which is what "combination of those" asks for. */
  /** What the Items tab is currently showing.
   *
   *  A PLAIN VARIABLE, never a field on an item, an assembly or anything else that gets
   *  serialised. The dropdown filters deleted on 2026-08-19 kept their state on the line object,
   *  so every debounced save shipped the estimator's filter to the server and `lineForSave` had to
   *  strip `_`-prefixed keys to undo it. A filter is a view of the data, not part of it. */
  var itemQuery = "";

  /** The facets, and the same rule: A PLAIN VARIABLE, never a field on a record.
   *
   *  Kept on one line so library-ui-harness.js can lift the declaration verbatim rather than
   *  restating a default shape that could drift from this one.
   *
   *  divisions is an array because a facet with one value is a dropdown; the question an
   *  estimator actually asks is "epoxy OR gypsum", so it ORs within itself and ANDs against the
   *  other two, which is what every faceted list does and what nobody has to be told. */
  var FILTERS = { divisions: [], vendor: "", condition: "" };
  var asmQuery = "";
  var ASM_FILTERS = { unit: "", condition: "" };

  /** HOW THE RAIL IS ORDERED. Hanz, 2026-09-04: "in the assemblies we must be able to sort by
   *  vendor, scope or worktype, unit, who created it."
   *
   *  A PLAIN VARIABLE, and the third one on this page held to that rule for the same reason
   *  itemQuery and ASM_FILTERS are: an ordering is a view of the data, not part of it, and the
   *  dropdown filters deleted on 2026-08-19 kept their state on the line object — so every
   *  debounced save shipped one estimator's view of the list to the server and `lineForSave` had
   *  to strip it back off. Nothing serialises this.
   *
   *  NOT a filter, and deliberately outside anyAsmFilterActive(): a sort narrows nothing, so it
   *  must not light up the hits count, must not raise the no-match panel, and must not be reset
   *  by Clear filters. One line, so library-ui-harness.js can lift the default verbatim. */
  var ASM_SORT = "name";

  /** Is the tab showing a subset? Text, facets, or both.
   *
   *  One predicate rather than four checks at four call sites: the hits count, the no-match
   *  panel, the Clear button and visibleItems must agree about whether a filter is on, and the
   *  version of this that only looked at the search box left the no-match panel hidden behind an
   *  active facet, which is a blank table with nothing on screen saying why. */
  function anyFilterActive() {
    return !!String(itemQuery).trim() || FILTERS.divisions.length > 0 ||
      !!FILTERS.vendor || !!FILTERS.condition;
  }

  /** Break a query into terms.
   *
   *  THE GRAMMAR, and it is deliberately small enough to guess at:
   *
   *      sherwin              a bare word: name, division or vendor
   *      "opf primer"         a phrase, matched as one string
   *      vendor:sherwin       scoped to one field
   *      cost:>200            a number, with > < >= <= or plain equals
   *      -epoxy               everything that does NOT match
   *
   *  Every term narrows. That is the rule the old matcher already followed and the one Hanz asked
   *  for in the first place ("could be from name, divison or vendor or comibation of those"), so a
   *  bare word behaves exactly as it did before this and the assembly picker inherits the rest.
   *
   *  A SCOPED TERM WITH NOTHING AFTER THE COLON IS NOT YET A TERM. Somebody typing vendor:s goes
   *  through vendor: on the way, and blanking the table for one keystroke reads as the search
   *  breaking. An unknown field name is NOT dropped, though: sku:x is searched as the literal
   *  text "sku:x", which finds nothing and says so, rather than being quietly ignored and handing
   *  back every row. */
  function parseQuery(q) {
    var out = [];
    var toks = String(q == null ? "" : q).match(/-?(?:[a-z]+:)?"[^"]*"|\S+/gi) || [];
    for (var i = 0; i < toks.length; i++) {
      var tok = toks[i];
      var neg = tok.charAt(0) === "-";
      if (neg) tok = tok.slice(1);
      var field = "", value = tok;
      var colon = tok.indexOf(":");
      if (colon > 0) {
        var key = tok.slice(0, colon).toLowerCase();
        var mapped =
            (key === "name" || key === "material") ? "name"
          : (key === "division" || key === "div") ? "divisions"
          : (key === "vendor" || key === "supplier") ? "vendor"
          : (key === "unit") ? "unit"
          : (key === "cost" || key === "price") ? "unit_cost"
          : (key === "pack" || key === "qty" || key === "buy") ? "buy_qty"
          : "";
        if (mapped) { field = mapped; value = tok.slice(colon + 1); }
      }
      value = value.replace(/^"/, "").replace(/"$/, "").trim();
      if (!value) continue;
      out.push({ neg: neg, field: field, value: value });
    }
    return out;
  }

  /** Does one term hit this material?
   *
   *  An unscoped term searches name, division and vendor as one string, which is the haystack the
   *  previous matcher used and the reason "polished primer" narrows instead of finding nothing. */
  function termHits(it, term) {
    if (term.field === "unit_cost" || term.field === "buy_qty") {
      return numberHits(it[term.field], term.value);
    }
    var hay = term.field === "name" ? String(it.name || "")
      : term.field === "divisions" ? itemDivisions(it).join(" ")
      : term.field === "vendor" ? String(it.vendor || "")
      : term.field === "unit" ? String(it.unit || "")
      : [String(it.name || ""), itemDivisions(it).join(" "), String(it.vendor || "")].join(" ");
    return hay.toLowerCase().indexOf(term.value.toLowerCase()) !== -1;
  }

  /** cost:>200, pack:5, cost:<=99.99. A comma and a dollar sign are tolerated, because that is
   *  how the number is written on the invoice being read from.
   *
   *  NONSENSE MATCHES NOTHING, NOT EVERYTHING. cost:abc cannot be true of any material, so it
   *  returns false rather than being discarded: a discarded term hands back the whole list and
   *  reads as the filter being ignored, which is the one behaviour a search must never have.
   *  A material with no cost recorded fails every cost comparison for the same reason. Absent is
   *  not zero, and treating it as zero would file it under cost:<1 as though somebody had priced
   *  it at nothing. */
  function numberHits(actual, expr) {
    var m = /^(>=|<=|>|<|=)?\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)$/.exec(String(expr).trim());
    if (!m) return false;
    var want = Number(String(m[2]).replace(/,/g, ""));
    var have = Number(actual);
    if (!isFinite(want) || actual === null || actual === undefined || actual === "" ||
        !isFinite(have)) return false;
    var op = m[1] || "=";
    return op === ">" ? have > want
      : op === "<" ? have < want
      : op === ">=" ? have >= want
      : op === "<=" ? have <= want
      : have === want;
  }

  /** The condition facet. Four states a material can be in that a price list cares about, every
   *  one of them read off a column that already exists.
   *
   *  THIS IS THE FACET THAT EARNS THE BAR. Division and vendor only narrow what somebody could
   *  already find by typing; these answer the question no search can, which is what in here is
   *  not safe to price a bid from. A material with no cost prices every assembly built on it at
   *  nothing, silently, and until now there was no way to go looking for one. */
  function conditionHits(it, c) {
    // Remove existing joint filler has no material cost BY DESIGN (a labor modifier), so it is
    // not a material that is missing one.
    if (c === "no_cost") return !(Number(it.unit_cost) > 0) && it.id !== "remove-existing-jf";
    if (c === "no_division") return itemDivisions(it).length === 0;
    if (c === "no_vendor") return !String(it.vendor || "").trim();
    if (c === "no_price_date") return !it.cost_updated_at;
    return true;
  }

  function conditionPhrase(c) {
    return c === "no_cost" ? "with no cost recorded"
      : c === "no_division" ? "not filed under a division"
      : c === "no_vendor" ? "with no vendor"
      : c === "no_price_date" ? "whose price has never been recorded"
      : "";
  }

  /** The facets, ANDed with each other and ORed within the division list.
   *
   *  `F` defaults to this tab's FILTERS so every existing caller is unchanged. It is a parameter
   *  because the bulk-add picker draws its OWN facet bar and must not move the Items tab's — the
   *  same reasoning the note on visibleItems gives for why the line picker ignores these. Sharing
   *  one FILTERS between two visible bars is how a screen ends up narrowed by a control on another
   *  tab that the estimator cannot see.
   *
   *  ES5 default rather than a default parameter: this file is var-and-function throughout, and the
   *  harness lifts it into a `new Function` scope where the surrounding dialect is what it is. */
  function matchesFilters(it, F) {
    F = F || FILTERS;
    if (F.divisions.length) {
      var mine = {};
      itemDivisions(it).forEach(function (d) { mine[String(d).toLowerCase()] = true; });
      var any = false;
      for (var i = 0; i < F.divisions.length; i++) {
        if (mine[String(F.divisions[i]).toLowerCase()]) { any = true; break; }
      }
      if (!any) return false;
    }
    if (F.vendor &&
        String(it.vendor || "").toLowerCase() !== String(F.vendor).toLowerCase()) {
      return false;
    }
    if (F.condition && !conditionHits(it, F.condition)) return false;
    return true;
  }

  /** What is being filtered out, in a sentence, so the empty state can say it instead of leaving
   *  the estimator to reconstruct it from three controls and a text box. */
  function filterSummary() {
    var bits = [];
    var q = String(itemQuery).trim();
    if (q) bits.push("matching " + JSON.stringify(q));
    if (FILTERS.divisions.length) bits.push("in " + FILTERS.divisions.join(" or "));
    if (FILTERS.vendor) bits.push("from " + FILTERS.vendor);
    if (FILTERS.condition) bits.push(conditionPhrase(FILTERS.condition));
    return bits.join(", ");
  }

  /** The materials the query and the facets leave, in the order they already had.
   *
   *  Reuses itemMatches, the same matcher the assembly picker searches with, so the two boxes on
   *  this page cannot disagree about what "Sika primer" finds. The FACETS are this tab's alone: a
   *  line picker silently narrowed by a bar on another tab would be a trap. */
  function visibleItems() {
    if (!anyFilterActive()) return ITEMS;
    return ITEMS.filter(function (it) {
      return matchesFilters(it) && itemMatches(it, itemQuery);
    });
  }

  // ── bulk add: the decisions, as pure functions ─────────────────────────────
  // Will wants to put a dozen materials into an assembly at once instead of pressing "Add item
  // line" twelve times and searching twelve times (Hanz, 2026-08-28).
  //
  // WHY THESE ARE SEPARATE FROM THE MODAL. The test harness builds a DOM stub that knows only
  // innerHTML/textContent/hidden/value — it cannot open a dialog, move focus or tick a checkbox, and
  // it takes the same position with `confirmDanger`. So every DECISION lives in a function that
  // takes its state as arguments and returns a value, and the modal is left holding only wiring.
  // Everything worth being wrong about is therefore testable.
  //
  // The 60 here is `_MAX_LINES` in backend/library.py. Two literals for one rule is not ideal, but
  // there is no config endpoint to read it from, and the alternative — finding out on save — is the
  // bug this guard exists to prevent.
  var BULK_MAX_LINES = 60;

  /** The materials a bulk picker should show, given its own query and its OWN facets.
   *
   *  Reuses itemMatches, so this box, the Items tab's box and the per-line picker cannot disagree
   *  about what "vendor:sherwin" or "-epoxy" finds. `F` is the MODAL's filter state, never the Items
   *  tab's FILTERS — see the note on matchesFilters. */
  function anyAsmFilterActive() {
    return !!String(asmQuery).trim() || !!ASM_FILTERS.unit || !!ASM_FILTERS.condition;
  }

  /** The three conditions this tab can answer, read off the price it already computes.
   *
   *  `p` is passed in rather than computed here because renderList prices every visible row
   *  anyway and priceAssembly walks every line of every assembly: computing it twice per row
   *  would double the cost of typing a letter. A caller with no condition filter passes null and
   *  never reaches this. */
  function asmConditionHits(a, c, p) {
    if (c === "no_lines") return ((a || {}).lines || []).length === 0;
    if (c === "unpriced") return !p || p.per_unit == null;
    if (c === "broken") return !!(p && p.broken_lines > 0);
    return true;
  }

  /** Takes the filter state as an ARGUMENT, for the reason matchesFilters does: nothing else on
   *  this page may narrow the rail, and a shared module variable is how a control on one tab ends
   *  up filtering another that the estimator cannot see.
   *
   *  Keyed on asmUnit(a), not a.unit. The raw field is what the rail PRINTS; asmUnit is what the
   *  pricing and the polish beta believe, and a blank or "sf" would otherwise match neither
   *  option in a two-option select. */
  function asmMatchesFilters(a, F, p) {
    F = F || ASM_FILTERS;
    if (F.unit && asmUnit(a) !== F.unit) return false;
    if (F.condition && !asmConditionHits(a, F.condition, p)) return false;
    return true;
  }

  /** One term against an assembly: its own name and unit, OR any material inside it.
   *
   *  PER TERM rather than per haystack, which is what makes the grammar behave. Running
   *  itemMatches over each haystack and OR-ing the answers would make `-epoxy` mean "some line
   *  has no epoxy in it" - true of nearly every assembly. Asking each term separately makes it
   *  mean "nothing in here mentions epoxy", which is what somebody typing it wants.
   *
   *  Reaching inside is the point. "Which assemblies use that primer?" is a question this tab
   *  cannot otherwise answer without opening all of them, and it comes free: termHits is the same
   *  function the three item boxes use, so `vendor:sherwin` and `cost:>200` work here too. */
  function asmTermHits(a, term, items) {
    if (termHits({ name: (a || {}).name, unit: asmUnit(a) }, term)) return true;
    var lines = (a || {}).lines || [];
    for (var i = 0; i < lines.length; i++) {
      var it = L.findItem(items || [], lines[i].item_id);
      if (it && termHits(it, term)) return true;
    }
    return false;
  }

  function asmMatches(a, query, items) {
    var terms = parseQuery(query);
    for (var i = 0; i < terms.length; i++) {
      var hit = asmTermHits(a, terms[i], items || ITEMS);
      if (terms[i].neg ? hit : !hit) return false;
    }
    return true;
  }

  /** Say what was asked for, so "nothing matches" does not make somebody reconstruct the query
   *  out of two selects and a text box. */
  function asmFilterSummary() {
    var bits = [];
    var q = String(asmQuery).trim();
    if (q) bits.push("matching " + JSON.stringify(q));
    if (ASM_FILTERS.unit) bits.push("priced per " +
      (ASM_FILTERS.unit === "LF" ? "linear foot" : "square foot"));
    if (ASM_FILTERS.condition) bits.push(
      ASM_FILTERS.condition === "unpriced" ? "still without a price"
      : ASM_FILTERS.condition === "broken" ? "with lines to fix"
      : "with no lines yet");
    return bits.join(", ");
  }

  /** WHICH SUPPLIER AN ASSEMBLY IS "FROM", WHICH IS NOT A FIELD ON ONE.
   *
   *  There is no vendor column on library_assemblies and there should not be: a vendor is a fact
   *  about a MATERIAL, and an assembly is a recipe over several of them. So it is derived, and
   *  Hanz's rule (2026-09-04, settled — do not re-open it) is the most frequent vendor among the
   *  lines, ties broken alphabetically.
   *
   *  WHY MOST FREQUENT rather than the first line's. "MACRO Flake" is three coats of Sherwin
   *  product and one Ardex patch; ordering it under Ardex because the patch happens to be line
   *  one is the answer nobody wants, and line order on an assembly is the order somebody typed
   *  it in, which carries no meaning at all.
   *
   *  WHO DOESN'T VOTE: a line with no item picked yet, a line pointing at a deleted material, and
   *  a material nobody has named a supplier for. All three are silence, not a vendor called "".
   *
   *  Counted case-insensitively and reported in the spelling the item actually carries, because
   *  `vendor` is free text on an item — "Sherwin-Williams" and "sherwin-williams" are one supplier
   *  with two spellings and must not split the vote between them. */
  function asmVendorTally(a, items) {
    var lines = (a || {}).lines || [], counts = {}, spelling = {};
    for (var i = 0; i < lines.length; i++) {
      var it = L.findItem(items || ITEMS, lines[i].item_id);
      var v = it ? String(it.vendor || "").trim() : "";
      if (!v) continue;
      var k = v.toLowerCase();
      counts[k] = (counts[k] || 0) + 1;
      if (!spelling[k]) spelling[k] = v;
    }
    var keys = Object.keys(counts);
    if (!keys.length) return { primary: "", others: 0 };
    keys.sort(function (x, y) {
      return counts[y] - counts[x] || spelling[x].localeCompare(spelling[y]);
    });
    return { primary: spelling[keys[0]], others: keys.length - 1 };
  }

  /** The vendor as the rail prints it. "+N more" is the honest part: an assembly built out of two
   *  suppliers has been filed under one of them, and saying so beats a row that looks
   *  single-sourced. */
  function asmVendorLabel(a, items) {
    var t = asmVendorTally(a, items);
    if (!t.primary) return "No vendor";
    return t.primary + (t.others ? " +" + t.others + " more" : "");
  }

  /** "kyle.loseke@wetreadwell.com" → "Kyle Loseke". Hanz asked to sort by "who created it", and
   *  the answer is a person's name — sorting by the raw address orders by the local part's
   *  punctuation, and prints an address where a name belongs.
   *
   *  TWCrm.nameOf, not a second spelling of it: the CRM board, the trash list and the admin table
   *  all render people through that one function, and it already falls back to the whole string
   *  for anything it cannot split. */
  function asmOwnerName(a) {
    return CRM.nameOf((a || {}).owner_email || "");
  }

  /** The one value the rail is currently ordered on, as a plain string.
   *
   *  "" means this assembly cannot answer the question, and sortAssemblies puts every "" LAST
   *  whichever direction the key runs — a blank surfacing at the top of a sort is how an ordering
   *  loses the reader's trust. `unit` never blanks (asmUnit defaults to SF), and `name` is here
   *  only as the tie-break every other key falls through to. */
  function asmSortValue(a, key, items) {
    if (key === "new") return String((a || {}).created_at || "");
    if (key === "scope") return String((a || {}).category || "").trim();
    if (key === "unit") return asmUnit(a);
    if (key === "vendor") return asmVendorTally(a, items).primary;
    if (key === "owner") return asmOwnerName(a);
    return String((a || {}).name || "");
  }

  /** Order the rail. A NEW ARRAY — never a sort in place, because visibleAssemblies hands back
   *  ASMS itself when nothing is filtered and reordering that would silently reorder the model
   *  every other function reads (`current()`, the delete's fallback openId, load()'s first pick).
   *
   *  "name" IS A PASS-THROUGH, AND THAT IS THE DECISION HERE, not an oversight. list_assemblies()
   *  on the server already does `.order("name")`, so the order it hands us IS name A–Z and the
   *  default view is byte-for-byte what this tab showed before this control existed. Re-sorting it
   *  client-side would cost nothing visible on a loaded page and would break the one thing Hanz
   *  asked for in the same breath: a just-created assembly is unshifted to the FRONT of the rail,
   *  and an active name sort would drop it straight back under N for "New assembly". So the
   *  default respects the server's order including this session's prepend, and "Newest first" is
   *  the option that makes new-work-on-top survive a reload. */
  function sortAssemblies(list, key, items) {
    if (!key || key === "name") return list;
    var desc = key === "new";
    return list.slice().sort(function (x, y) {
      var vx = asmSortValue(x, key, items), vy = asmSortValue(y, key, items);
      // Blanks last in BOTH directions: the `desc` flip never reaches this branch.
      if (!vx !== !vy) return vx ? -1 : 1;
      var c = desc ? String(vy).localeCompare(String(vx))
                   : String(vx).localeCompare(String(vy));
      // ONE TOTAL ORDER. Every key has ties — four assemblies are per SF, two are Kyle's — and
      // falling through to the name makes the rail stable and predictable instead of leaving the
      // tied rows in whatever order the array happened to hold.
      return c || String((x || {}).name || "").localeCompare(String((y || {}).name || ""));
    });
  }

  /** WHERE A BRAND-NEW ASSEMBLY LANDS IN THE RAIL. Hanz, 2026-09-04: "when a new assembly is added
   *  it should append up top not below."
   *
   *  A NAMED FUNCTION FOR ONE STATEMENT, and the reason is testability, the same reason the bulk
   *  modal's four decisions were pulled out of it. The create path lives inside the page's
   *  anonymous `document.addEventListener("click", …)`, which library-ui-harness.js cannot lift —
   *  so `push` against `unshift` would be a behaviour change with no test that could fail without
   *  it, on the half of the instruction most likely to be quietly reverted by somebody tidying up.
   *  Out here it is executed against the real ASMS the renderer reads. (The two ITEMS.unshift
   *  calls in that same listener are still unreachable, and still browser-verified only.)
   *
   *  IN PLACE, returning the same array: ASMS is the model `current()`, `load()`'s first pick and
   *  the delete's fallback openId all read, and replacing it with a copy would leave those three
   *  looking at the old one. */
  function placeNewAssembly(list, asm) {
    list.unshift(asm);
    return list;
  }

  /** What the row SAYS about the key it is being ordered on, so an order is never a mystery.
   *
   *  Only under the sort it belongs to. Printing the vendor and the author on every row would put
   *  two more lines of small grey text on a 272px rail that nobody asked to widen, and neither is
   *  what an estimator scanning for "MACRO Flake" is reading.
   *
   *  `unit` is the exception and prints only when the row has no price: the unit is already the
   *  denominator of the "$1.497/SF" the row shows, so saying it twice would be noise — but an
   *  unpriced row says "not priced" and would then show nothing at all about the thing it was
   *  just sorted by. */
  function asmSortLabel(a, key, items, p) {
    if (key === "new") {
      return (a || {}).created_at ? "added " + TW.fmtBizDate(a.created_at) : "no added date";
    }
    if (key === "scope") return String((a || {}).category || "").trim() || "No scope";
    if (key === "vendor") return asmVendorLabel(a, items);
    if (key === "owner") return asmOwnerName(a) || "No creator recorded";
    if (key === "unit") return (p && p.per_unit != null) ? "" : "per " + asmUnit(a);
    return "";
  }

  /** WHAT THE RAIL SHOWS, in the order it shows it. FILTER FIRST, THEN SORT — the hits count says
   *  "N of M shown" and the no-match panel fires off `shown.length === 0`, so an ordering applied
   *  before the narrowing would still be right here and both of those would still be right, but
   *  the pair only stays obviously right if the two steps are in the order the sentence reads. */
  function visibleAssemblies(area) {
    if (!anyAsmFilterActive()) return sortAssemblies(ASMS, ASM_SORT, ITEMS);
    return sortAssemblies(ASMS.filter(function (a) {
      var p = ASM_FILTERS.condition ? L.priceAssembly(a, ITEMS, area) : null;
      return asmMatchesFilters(a, ASM_FILTERS, p) && asmMatches(a, asmQuery, ITEMS);
    }), ASM_SORT, ITEMS);
  }

  /** Unlike renderFilterBar this never writes markup - all three selects are static, because an
   *  assembly's unit is a closed SF/LF domain, the three conditions are fixed and the six sort
   *  keys are. So there is nothing to rebuild, nothing to rebuild AT, and no focus to lose: an
   *  estimator who tabs into Sort, picks a key and keeps tabbing is still where they left off,
   *  which is exactly what the item bar needs its filterBarSig to fake.
   *
   *  THE SORT IS SYNCED HERE AND CLEARED NOWHERE. It is written back on every render for the same
   *  reason the facets are — a control whose value does not survive a re-render lies about the
   *  list under it — but it is absent from clearAsmFilters, because Clear filters clears filters
   *  and an ordering is not one. */
  function renderAsmFilterBar() {
    if ($("fa-unit")) $("fa-unit").value = ASM_FILTERS.unit;
    if ($("fa-condition")) $("fa-condition").value = ASM_FILTERS.condition;
    if ($("fa-sort")) $("fa-sort").value = ASM_SORT;
    if ($("fa-clear")) $("fa-clear").hidden = !anyAsmFilterActive();
    // Nothing to filter is not a filter bar. With no assemblies the rail is hidden and the "No
    // assemblies yet" panel is doing the talking; a search box over it would offer to narrow
    // nothing.
    if ($("asm-filterbar")) $("asm-filterbar").hidden = ASMS.length === 0;
  }

  function bulkCandidates(items, query, F) {
    return (items || []).filter(function (it) {
      return matchesFilters(it, F) && itemMatches(it, query);
    });
  }

  /** "none" | "some" | "all" for the select-all control, over WHAT IS CURRENTLY SHOWN.
   *
   *  Shown, not the whole library: after typing a query, "all" has to mean "all of these", or the
   *  control claims everything is ticked while the list in front of you is half unticked. Ticks
   *  outside the current search are still held — narrowing the search must not silently untick
   *  what you already chose — so `picked` is read, not overwritten. */
  function bulkSelectAllState(shownIds, picked) {
    var ids = shownIds || [], on = 0;
    for (var i = 0; i < ids.length; i++) if (picked && picked[ids[i]]) on += 1;
    if (!ids.length || !on) return "none";
    return on === ids.length ? "all" : "some";
  }

  /** Assembly lines for the picked materials, in the order they were shown.
   *
   *  Since 2026-09-30 coverage, waste and roundup live on the MATERIAL: `priceLine` reads them off
   *  the item and never off the line, and `_clean_lines` strips all three from a saved line. The
   *  coverage/waste_pct/roundup keys below are kept only so a line added this way has the same
   *  shape as one added by hand until it is saved; they do not price anything.
   *
   *  A material whose own coverage is unset still lands, and still reads "Needs a coverage" — an
   *  honest report about the material, fixed on the Materials tab, not a fault in the add. */
  function bulkLinesFor(itemIds, items) {
    var out = [];
    (itemIds || []).forEach(function (id) {
      var it = L.findItem(items || [], id);
      if (!it) return;                       // deleted between opening the picker and pressing Add
      out.push({ role: "", item_id: it.id,
                 coverage: (Number(it.coverage) > 0) ? it.coverage : null,
                 // The same defaults the single "Add item line" path sets, so a bulk-added row and
                 // a hand-added one save with identical numbers.
                 waste_pct: 5, roundup: true, note: "" });
    });
    return out;
  }

  /** How much room is left, so the picker can say so BEFORE the click.
   *
   *  The server caps an assembly at 60 lines. It used to take `raw[:60]` silently, which is
   *  defensible against a hostile 500-line payload and indefensible against a deliberate add of 40:
   *  ten materials would vanish under a 200 OK. Answering here means the button can explain itself
   *  while there is still something to change. */
  function bulkAddRoom(asm, n) {
    var used = ((asm && asm.lines) || []).length;
    var room = Math.max(0, BULK_MAX_LINES - used);
    return { used: used, room: room, over: Math.max(0, (n || 0) - room),
             fits: (n || 0) <= room, max: BULK_MAX_LINES };
  }

  function itemMatches(it, query) {
    var terms = parseQuery(query);
    for (var i = 0; i < terms.length; i++) {
      var hit = termHits(it, terms[i]);
      if (terms[i].neg ? hit : !hit) return false;
    }
    return true;
  }

  /** Fill the facet controls, and DO NOT REBUILD THEM UNLESS THE OFFERED VALUES CHANGED.
   *
   *  This is the whole answer to "the filter must survive a re-render". The controls live outside
   *  #items-body, so renderItems, which replaces only that tbody, cannot reach them; and the
   *  state itself lives in FILTERS and itemQuery rather than in the DOM, so nothing is read back
   *  off a control that might have been rebuilt. What is left is this function, which paint()
   *  calls on every edit and every save: rebuilding the chip strip there would throw away the
   *  focus of anybody tabbing through it, so it compares the offered lists first and writes
   *  markup only when an admin has actually added or renamed something.
   *
   *  When it does rebuild, it rebuilds FROM FILTERS, so a division that is switched on comes
   *  back switched on. */
  var filterBarSig = "";
  function renderFilterBar() {
    var names = divisionNames();
    var vendors = vendorNames();
    var sig = JSON.stringify([names, vendors]);
    if (sig !== filterBarSig) {
      filterBarSig = sig;
      var on = {};
      FILTERS.divisions.forEach(function (d) { on[String(d).toLowerCase()] = true; });
      $("f-divisions").innerHTML = names.map(function (d) {
        return '<label class="fchip" title="' + esc(d) + '">' +
          '<input type="checkbox" data-fdiv="' + esc(d) + '" aria-label="' + esc(d) + '"' +
          (on[String(d).toLowerCase()] ? " checked" : "") + ">" +
          '<span class="fchip-f">' + esc(d) + "</span></label>";
      }).join("");
      $("f-vendor").innerHTML = '<option value="">Any vendor</option>' +
        vendors.map(function (v) {
          return '<option value="' + esc(v) + '"' +
            (String(v).toLowerCase() === String(FILTERS.vendor).toLowerCase() ? " selected" : "") +
            ">" + esc(v) + "</option>";
        }).join("");
    }
    // Cheap every time, and safe on a control somebody has focused: setting a value it already
    // holds is a no-op, where re-writing its markup would not be.
    $("f-vendor").value = FILTERS.vendor;
    $("f-condition").value = FILTERS.condition;
    $("f-clear").hidden = !anyFilterActive();
  }

  function itemResultsHtml(line) {
    var query = line._item_search == null ? "" : line._item_search;
    var matches = ITEMS.filter(function (candidate) {
      // The three reserved rows (joint filler kit, remove-existing, dye) are never an assembly
      // line -- see isReservedItem. The Polish estimate already owns each through its own
      // condition card.
      return !isReservedItem(candidate && candidate.id) && itemMatches(candidate, query);
    }).slice(0, 12);
    if (!matches.length) return '<div class="gone">No items match that search.</div>';
    return matches.map(function (candidate) {
      var divs = itemDivisions(candidate).join(", ") || "No division";
      var vendor = candidate.vendor || "No vendor";
      return '<button class="item-result" type="button" data-pick-item="' + esc(candidate.id) + '"' +
        (candidate.id === line.item_id ? ' aria-pressed="true"' : ' aria-pressed="false"') + ">" +
        "<b>" + esc(candidate.name) + "</b>" +
        "<span>" + esc(divs) + " &middot; " + esc(vendor) + " &middot; " + esc(orderAmount(candidate)) + "</span>" +
        "</button>";
    }).join("");
  }

  /** ONE ROW per line item.
   *
   *  Hanz, 2026-08-19: "divisions should be a label up top like before not on the row. Make one
   *  line item, one row." The previous version rendered a permanently-open panel in this cell — a
   *  search box, a "Divisions" label with a division select, a vendor select, and an expanded list
   *  of twelve results — so one line filled a tall block, and a column label sat in the data area
   *  where the header already labels things.
   *
   *  Now: one input, showing the chosen item. The results list is emitted only for the line whose
   *  picker is open and is positioned absolutely (see .item-results in library.html), so opening it
   *  cannot change the row's height. */
  function pickerFor(line, index) {
    var it = itemOf(line.item_id);
    var open = pickerOpen === index;
    var typed = line._item_search;
    // Closed, the box reads as the answer ("OPF — 5 gal pail"). Open, it reads as the question, so
    // the whole name does not have to be deleted before searching for a different product.
    var value = open ? (typed == null ? "" : typed) : (it ? it.name : "");
    return '<div class="item-picker">' +
      '<input data-lf="item_search" value="' + esc(value) + '" autocomplete="off"' +
        ' placeholder="Search items" aria-label="Search items by name, division or vendor">' +
      (open ? '<div class="item-results">' + itemResultsHtml(line) + "</div>" : "") +
      "</div>";
  }

  /** Resolve typed text to a material. Exact name first, then a unique case-insensitive match —
   *  never a "closest" guess, because silently picking the wrong primer is worse than saying no. */
  function itemByName(text) {
    var t = String(text || "").trim();
    if (!t) return null;
    var lower = t.toLowerCase(), hits = [];
    for (var i = 0; i < ITEMS.length; i++) {
      if (ITEMS[i].name === t) return ITEMS[i];
      if (String(ITEMS[i].name || "").toLowerCase() === lower) hits.push(ITEMS[i]);
    }
    return hits.length === 1 ? hits[0] : null;
  }

  function renderPanel() {
    var asm = current();
    var noneAtAll = ASMS.length === 0;
    $("asm-panel").hidden = !asm;
    $("asm-empty").hidden = !noneAtAll;
    if (noneAtAll) {
      // An assembly with nothing to choose from cannot be built, so say that rather than
      // offering a button that opens an empty dropdown.
      var bare = ITEMS.length === 0;
      $("asm-empty-h").textContent = bare ? "Add some items first" : "No assemblies yet";
      $("asm-empty-why").textContent = bare
        ? "An assembly is built out of your items, so there is nothing to pick from yet. Add a few on the Items tab."
        : "Build a system out of your items - a primer, a body coat, a top coat - and see what it costs per square foot.";
      $("asm-new").hidden = bare;
      return;
    }
    if (!asm) return;

    if ($("asm-name").value !== asm.name) $("asm-name").value = asm.name;
    $("asm-save").hidden = !FRESH.assemblies[asm.id];
    var area = $("area").value;
    var p = L.priceAssembly(asm, ITEMS, area);
    var out = "";
    for (var i = 0; i < asm.lines.length; i++) {
      var ln = asm.lines[i], r = p.rows[i];
      var qtyCell, costCell;
      if (r.ok && r.priced) {
        qtyCell = '<div class="line-primary"><span class="qty">' + esc(L.qtyLabel(r)) + '</span></div><div class="calc mono">' +
                  esc(L.explain(r, area)) + "</div>";
        costCell = '<div class="line-primary"><span class="qty">' + L.money(r.cost) + '</span></div><div class="calc mono">' +
                   esc(L.costWorking(r)) + "</div>";
      } else if (r.ok) {
        qtyCell = '<span class="dash">—</span>';                     // no area typed yet
        costCell = '<span class="dash">—</span>';
      } else if (r.reason === "no_item") {
        // The instruction, not a fault. Grey, and the row is NOT tinted below.
        qtyCell = '<span class="unpicked">Pick a material</span>';
        costCell = "—";
      } else if (r.reason === "missing_item") {
        qtyCell = '<span class="gone">Item removed</span>';
        costCell = "—";
      } else if (r.reason === "no_coverage") {
        qtyCell = '<span class="gone">Needs a coverage</span>';
        costCell = "—";
      } else {
        qtyCell = '<span class="gone">Needs a cost</span>';
        costCell = "—";
      }
      if (qtyCell.indexOf("line-primary") === -1) {
        qtyCell = '<div class="line-primary">' + qtyCell + "</div>";
      }
      if (costCell.indexOf("line-primary") === -1) {
        costCell = '<div class="line-primary">' + costCell + "</div>";
      }
      var lineItem = itemOf(ln.item_id);
      // An unfilled line is not tinted. This is the amber row refreshNumbers could clear only
      // after an unrelated keystroke -- and `paint()` (which is what + line calls) never runs
      // refreshNumbers at all, so it was the first thing the estimator saw.
      out += '<tr data-line="' + i + '"' +
        (r.ok || r.reason === "no_item" ? "" : ' class="broken"') + ">" +
        "<td>" + pickerFor(ln, i) +
          (!r.ok && r.reason === "missing_item"
            ? '<div class="gone">Pick a replacement item — this line is not priced</div>' : "") + "</td>" +
        '<td class="n"><div class="line-primary">' + esc(orderAmount(lineItem)) + "</div></td>" +
        // PULLED IN FROM THE MATERIAL, NOT TYPED HERE. Hanz, 2026-09-22: "we must have coverage
        // per unit, waste factor, roundup, and materials tab. And then it gets pulled in to
        // assemblies instead of it being in assemblies."
        //
        // STILL SHOWN, though. "It gets pulled in" is a statement about where the numbers are
        // SET, not about hiding them: an estimator reading an assembly has to see the coverage a
        // line is priced at without opening another tab, and a blank column would make the
        // arithmetic in the two derived cells beside it unfollowable.
        //
        // READ OFF `r`, THE PRICED ROW, rather than off `ln`. r.coverage is what the engine
        // actually used, so this cell cannot disagree with the cost cell next to it -- and a
        // legacy line still carrying its own numbers displays the material's, which is the whole
        // point. A line whose material is missing has no r.coverage, hence the em dash.
        // qtyText, which this file already uses for every quantity -- NOT a formatter invented
        // here. The first draft of this line called num0(), which does not exist in this file or
        // any it loads: an unbound identifier that a regex over the markup could never catch and
        // that would have thrown on the first assembly anybody opened.
        '<td class="n cov derived"><div class="line-primary">' +
          (r.coverage == null ? "—" : esc(qtyText(r.coverage))) + "</div></td>" +
        '<td class="n derived"><div class="line-primary">' +
          (r.waste_pct == null ? "—" : r.waste_pct + " %") + "</div></td>" +
        '<td class="ru derived"><div class="line-primary">' +
          (!r.ok ? "—" : (r.roundup ? "Yes" : "No")) + "</div></td>" +
        // `derived` tints the two columns nobody types into, so the cells this page WORKS OUT
        // read as a band apart from the ones that feed them. Tone only — the class carries a
        // background and nothing else, because these are the numbers a bid is priced from.
        '<td class="n derived">' + qtyCell + "</td>" +
        '<td class="n derived">' + costCell + "</td>" +
        '<td class="rowact"><button class="icon danger" type="button" data-del-line="' + i + '" title="Remove this line" aria-label="Remove line">' + icon("trash") + "</button></td>" +
      "</tr>";
    }
    if (!asm.lines.length) {
      out = '<tr><td colspan="8" class="lines-empty">' +
            "No lines yet. Add one and search for an item.</td></tr>";
    }
    $("lines-body").innerHTML = out;

    var priced = p.priced_lines > 0;
    $("t-total").textContent = priced ? L.money(p.total) : "—";
    $("t-unit").textContent = p.per_unit == null ? "—" : L.perUnit(p.per_unit);

    // THE UNIT, SAID OUT LOUD IN THREE PLACES. All three read the assembly rather than a constant,
    // so a cove assembly stops being described as square feet. The arithmetic is identical either
    // way — priceAssembly divides by whatever is in the one area input — which is exactly why the
    // labels mattered: the number was already right and the words around it were wrong.
    var u = asmUnit(asm);
    $("t-unit-k").textContent = "Price per " + u;
    $("area-k").textContent = u === "LF" ? "Test length" : "Test area";
    $("area-u").textContent = u;
    // Set, not rebuilt, and only when it differs — the same rule renderFilterBar follows for its
    // selects. Rewriting a control somebody has open would close it mid-choice.
    if ($("asm-unit").value !== u) $("asm-unit").value = u;
  }

  // renderFilterBar is in here rather than inside renderItems on purpose: it must run when the
  // OFFERED values change (an admin adds a division, a new vendor appears on a material) and it
  // must not run on every keystroke of a search. It is cheap and self-guarding either way.
  function paint() {
    renderItems(); renderFilterBar(); renderVendors(); renderList(); renderPanel();
    renderLabor();
    renderDefaultTakeoff(); renderDefaultLabor();
  }

  /** The markup lines that are one rule everywhere, as this page last read them.
   *
   *  FETCHED, NEVER STORED HERE. Bond's rate belongs to the Markup page's Global tab, and
   *  markup.py enforces ONE HOME PER LINE for exactly the reason that rule exists: two rows for
   *  one line is a precedence question, and that question decides a price. So this tab READS it
   *  and says where it lives. Editing it here would be the second home the whole split was written
   *  to prevent.
   *
   *  Empty until the fetch lands, and empty forever if it fails. A bond rate this page invented
   *  because a request timed out would be worse than a row that is not there. */
  var GLOBAL_MARKUP = [];

  /** The labor lines somebody typed on the Defaults tab, as this page last read them.

   *  FETCHED, AND EMPTY WHEN THE FETCH CANNOT ANSWER. `library_labor` was applied to staging on
   *  2026-09-17 and production does not have it yet, by decision -- staging first, prod when Hanz
   *  promotes it. So on prod today this request answers with nothing, and it has to leave a page
   *  that works: a tab that 500s over a list which is legitimately empty there would take Items
   *  and Assemblies down with it. No custom lines is the honest answer; a broken tab is not.

   *  TRAVEL IS NOT IN HERE. It is seeded into every estimate by travelSeed and it is not a row of
   *  this table -- see the renderer below, and the note on it. */
  var LABOR = [];

  /** The answers an admin has already set for the Takeoff conditions, as this page last read them.

   *  ONLY THE OVERRIDES, never the whole answer. What a new estimate opens answering for joint
   *  filler, remove-existing and dye lives in freshModel() in polish-bid-core.js; a row in here
   *  says somebody changed one of those three on this tab. takeoffConditionDefaults() merges the
   *  two through the estimate's OWN seedConditionDefaults, so this page cannot arrive at a
   *  different answer from the bid it is describing.

   *  EMPTY WHEN THE READ CANNOT ANSWER, and today that is everywhere: `condition_defaults` is
   *  written into both schema files and applied to neither, pending Hanz. Empty is the honest
   *  answer -- the shipped literals stand and the rows show them -- and a tab that 500s over a
   *  table nobody has promoted would take Items and Assemblies down with it. */
  var COND_DEFAULTS = [];

  /** The three conditions the Takeoff step carries, and what a new estimate answers for each.
   *
   *  THEY WERE "BUILT IN" AND THEY ARE NOT ANY MORE. Hanz, twice: "All line items and the default
   *  items in assemblies should be editable please don't put in a hard coded or built in line
   *  items", and then, seeing the chip still there: "I told you to remove the built-in and keep and
   *  make everything editable in the takeoff." Changing one changes what the NEXT blank bid opens
   *  answering.
   *
   *  THEY ARE MATERIALS, 2026-10-01. Hanz, looking at the Materials list with the three of them
   *  sitting below it as always-listed rows with an Add or a Remove and a "writes Polish!E29 · not
   *  in a new bid" tag: "make these 3 as materials" -- then, offered the choice, "All 3 exactly
   *  like materials". So each is drawn by the material row's own code (materialDefaultRow):
   *  the same Edit and Remove. LATER THE SAME DAY Hanz settled what a listed one MEANS: it is on
   *  a new estimate, grayed until switched on, and all three start off -- see conditionDefaultRow.
   *  What they do NOT share with a material is where the
   *  answer is stored -- condition_defaults, not a `favorite` -- and that is removeDefault's and
   *  the add router's business, not the row's.
   *
   *  THE CELL IS NO LONGER PRINTED. Polish!E29 is a fact about the workbook Kyle maintains and it
   *  was never editable here; the tag saying so was the one thing on these rows no material row
   *  carries. The answer still reaches the same cell through CONDITION_CELLS in polish-bid-core.js.
   *
   *  THE RATE LIVES ON THE ITEMS TAB, 2026-09-30. $500 a kit is Kyle's C29 and $0.14 a square
   *  foot is his C25, and both are reserved library_items rows (`joint-filler-kit`, `dye` -- see
   *  isReservedItem) that an admin edits on the Items tab like any other material. This row READS
   *  them, the same row polish-estimate.js's condLine prices from, so the figure shown here cannot
   *  disagree with the figure charged. RATES (and the kit's 3,500 sq ft) are what stand when the
   *  row is not there to read -- the same fallback the estimate takes. `name` is the row's own
   *  name for the same reason, and the condition's label only when there is no row to read.
   *
   *  THE SHIPPED ANSWER IS STILL READ FROM freshModel, and the stored overrides are written over
   *  it through the ESTIMATE'S OWN seedConditionDefaults rather than a merge written again here.
   *  Two merges is two chances for this page to describe a bid it does not agree with -- and the
   *  page claiming joint filler ships off while every new bid opens with it on is worse than no
   *  page at all. `B.seedConditionDefaults` is guarded because window.TWPolishBid is a script tag
   *  that can fail to load, and a Defaults tab that throws would take Items and Assemblies with it.
   *
   *  THIS LIST IS THE VOCABULARY, and backend/condition_defaults.KEYS is the same three.
   *  test_condition_defaults.py reads both files and pins them together, so a key renamed on one
   *  side cannot quietly become a row that saves and is read by nothing. `item_id` is the
   *  reserved row each key IS, and RESERVED_ITEM_CONDITION maps it back; the harness pins the two
   *  directions together. */
  function takeoffConditionDefaults() {
    var B = window.TWPolishBid;
    if (!B || !B.freshModel) return [];
    var shipped = (B.freshModel() || {}).conditions || {};
    var c = B.seedConditionDefaults ? B.seedConditionDefaults(shipped, COND_DEFAULTS) : shipped;
    // THE RESERVED ROW WHEN IT CAN PRICE, RATES WHEN IT CANNOT -- condLine's own rule in
    // polish-estimate.js, asked the same way: priceLine answers ok only for a row that is there
    // with a usable cost and coverage. The guard on `B` above stays: a page that threw because the
    // shared module did not load would take Items and Assemblies down with it, and an em dash is
    // a better answer than a blank screen.
    var R = (B.RATES || {});
    var kitLine = L.priceLine({ item_id: "joint-filler-kit" }, ITEMS, 0);
    var dyeLine = L.priceLine({ item_id: "dye" }, ITEMS, 0);
    var kitRate = kitLine.ok ? kitLine.unit_price : R.JOINT_FILLER_KIT_COST;
    var kitCov = kitLine.ok ? kitLine.coverage : 3500;
    // PER SQUARE FOOT, which is what the dye line costs whatever its row buys by: one unit's
    // price over what one unit covers, plus its waste. The seeded row (coverage 1, waste 0)
    // makes this exactly its unit_cost.
    var dyeRate = dyeLine.ok
      ? (dyeLine.unit_price / dyeLine.coverage) * (1 + dyeLine.waste_pct / 100)
      : R.DYE_PER_SF;
    var kit = L.num(kitRate) != null ? L.money(kitRate) : null;
    var dye = L.num(dyeRate) != null ? L.money(dyeRate) : null;
    // THE MATERIAL ROW'S OWN WORDING, "$X per <unit>", with the unit off the row when there is
    // one -- then what one of them covers, which is the half of the kit's price a bare "$500 per
    // Kit" would leave out.
    var kitUnit = (itemOf("joint-filler-kit") || {}).unit || "kit";
    var named = function (id, label) { return (itemOf(id) || {}).name || label; };
    // ON THE DEFAULTS TAB unless an admin took it off (`listed: false`). The same reading as
    // seedConditionsShown in polish-bid-core.js, which is what a new estimate snapshots.
    var listedOf = function (key) {
      for (var i = 0; i < COND_DEFAULTS.length; i++) {
        var r = COND_DEFAULTS[i];
        if (r && r.key === key) return r.listed !== false;
      }
      return true;
    };
    return [
      { key: "joint_filler", item_id: "joint-filler-kit", label: "Joint filler",
        name: named("joint-filler-kit", "Joint filler"), on: !!c.joint_filler, listed: listedOf("joint_filler"),
        priced: kit ? kit + " per " + kitUnit + " · 1 per " + L.qtyText(kitCov) + " SF"
                    : "No rate loaded for the kit" },
      { key: "remove_existing_jf", item_id: "remove-existing-jf",
        label: "Remove existing joint filler",
        name: named("remove-existing-jf", "Remove existing joint filler"),
        on: !!c.remove_existing_jf, listed: listedOf("remove_existing_jf"),
        // NO PRICE, and saying so is the point. It is a fourth hand on the joint-filler line -- a
        // labor modifier the estimator prices on the Labor step -- so a dollar figure here would
        // be an invention. "No material cost" is a real answer; a made-up $0.00 would read as
        // free.
        priced: "No material cost" },
      { key: "dye", item_id: "dye", label: "Dye", name: named("dye", "Dye"), on: !!c.dye, listed: listedOf("dye"),
        // THE ROW IS ONE COAT and a bid buys B.DYE_COATS of them -- Kyle's rows 25 and 26.
        priced: dye ? dye + " per SF a coat · " + (B.DYE_COATS || 2) + " coats"
                    : "No rate loaded for dye" }
    ];
  }

  /** One condition's answer, sent on the change, with the optimistic flip and the put-it-back in
   *  one place -- the split setDefault's own note argues for and for the same reason: two
   *  functions is two places to forget the rollback.
   *
   *  IT REPAINTS THE TAKEOFF LIST AND NOTHING ELSE. `paint()` would rebuild the Items tab, the
   *  Labor tab, the assembly rail and the open panel, none of which a condition answer touches.
   *
   *  A FAILED SAVE PUTS THE ROW BACK and says why. The row's BUTTON is the answer -- Remove while
   *  a new bid buys it, Add while it does not (conditionDefaultRow) -- so a refused write that left the
   *  list alone would be showing an admin a set of defaults no new bid actually opens with, and
   *  they would find that out from a bid. The rollback is the same reassign-and-repaint either
   *  way round, which is why add and remove share this one function. */
  async function setConditionDefault(key, listed) {
    var was = COND_DEFAULTS;
    var next = [];
    var found = false;
    for (var i = 0; i < was.length; i++) {
      // `on` is CLEARED with the press -- see putConditionDefault: all three start off.
      if (was[i] && was[i].key === key) {
        next.push(Object.assign({}, was[i], { key: key, on: false, listed: !!listed }));
        found = true;
      } else next.push(was[i]);
    }
    if (!found) next.push({ key: key, on: false, listed: !!listed });
    COND_DEFAULTS = next;
    renderDefaultTakeoff();
    try {
      await putConditionDefault(key, { listed: !!listed, on: false });
    } catch (err) {
      COND_DEFAULTS = was;
      renderDefaultTakeoff();
      say("Couldn't save that. " + err.message);
    }
  }


  /** The Takeoff defaults: what a new estimate opens holding, and what it opens having answered.
   *
   *  THE SWITCHED-ON LIBRARY ROWS COME FIRST because they are the ones somebody chose here.
   *  The conditions come last because they are the odd kind out: an assembly or a material is a
   *  line a new estimate OPENS WITH, and a condition is a question it opens ANSWERED.
   *
   *  NOT because they are built in. They were, until 2026-09-18, and this comment used to say
   *  so -- "nobody set them on this page and nobody can unset them here either". Hanz twice
   *  asked for that to stop being true, and it has: a condition is listed when a new bid buys it
   *  and removed when it does not, and both directions write condition_defaults. Travel under
   *  Labor is the one row on this tab that is still built in, and its own note says why. */
  /** The Defaults tab's own way in, which is what lets the switches come off the other two tabs.
   *
   *  THE SEARCH IS THE CONTROL, not a filter over what is already listed. Hanz asked for it "for
   *  when entering the defaults", and with the row switches gone it is the only way a library row
   *  becomes a default at all -- so it has to ADD, and the results have to be things not already
   *  on the list.
   *
   *  Assemblies before materials, and both capped: a library of 200 items behind a two-character
   *  query is a wall, not a picker. The cap is stated on screen rather than silently applied,
   *  because a result somebody expected and cannot see reads as the search being broken. */
  /** Edit and Remove, on the rows that can have them.
   *
   *  THIS IS AN ADMIN SCREEN, not a viewport -- Hanz, and he is right: a list you can only look at
   *  makes you go somewhere else to change anything it shows.
   *
   *  EDIT GOES TO THE ROW ITSELF rather than editing here. What you would want to change about a
   *  default assembly -- its lines, its unit, a material's cost -- is the assembly, not the fact
   *  that it is a default. Two places to edit one thing is how they come to disagree, and this
   *  page already has the good version of that argument written into markup.py.
   *
   *  REMOVE MEANS "STOP BEING A DEFAULT". It does not delete the assembly, which would be a very
   *  different and much worse button to put on this screen, so it says Remove and not the bin
   *  glyph the Items tab uses for actual deletion. */
  /** On or off, for any of the three kinds, with the optimistic flip and the put-it-back both in
   *  one place.
   *
   *  ONE FUNCTION FOR ADD AND REMOVE because they are the same write: `favorite` true or false.
   *  Two functions would be two places to forget the rollback, and a default that looks removed
   *  and comes back on the next reload is worse than one that refuses.
   *
   *  LABOR JOINED 2026-09-24, the same day the Labor tab did -- the small, mechanical extension
   *  the design called for. A labor type is created on that tab and favorited here, on this one,
   *  through this same function: the Labor tab's own `renderLabor` is what changes when THIS
   *  write lands, which is why that repaint is folded into `paint()` rather than kept beside
   *  `renderDefaultTakeoff`/`renderDefaultLabor` alone -- a favorite flipped from the Defaults
   *  tab has to be visible back on the Labor tab without a reload. */
  async function setDefault(kind, id, on) {
    var list = kind === "assemblies" ? ASMS : kind === "labor" ? LABOR : ITEMS;
    var row = null;
    for (var i = 0; i < list.length; i++) if (list[i].id === id) { row = list[i]; break; }
    if (!row) return;
    var was = !!row.favorite;
    row.favorite = !!on;
    paint();
    try {
      await patchDefault(kind, id, !!on);
    } catch (err) {
      row.favorite = was;
      paint();
      say("Couldn't save that. " + err.message);
    }
  }

  /** A default's Remove, sent to the store that holds that default.
   *
   *  ONE BUTTON, TWO STORES. Joint filler, remove-existing and dye carry the same Remove as every
   *  material (materialDefaultRow), keyed by their reserved library ids -- but whether a new bid
   *  opens with one of them is the CONDITION default (condition_defaults), never the row's
   *  `favorite`. So a reserved id goes to setConditionDefault, with its optimistic flip and its
   *  put-it-back, and everything else goes to setDefault as it always has. Flipping `favorite` on
   *  a reserved row instead would save cleanly, change nothing any bid reads, and leave the row
   *  listed on the next load.
   *
   *  NAMED, NOT INLINE IN THE CLICK LISTENER, because the harness can run a function and cannot
   *  run a listener -- and this is a decision. */
  async function removeDefault(kind, id) {
    if (kind === "items" && isReservedItem(id)) {
      await setConditionDefault(RESERVED_ITEM_CONDITION[id], false);
      return;
    }
    await setDefault(kind, id, false);
  }

  /** Toggle one work type on one library row. OPTIMISTIC, WITH THE ROLLBACK IN HERE, exactly
   *  like setDefault above and setConditionDefault below -- the same argument applies: two
   *  functions is two places to forget to put the row back.
   *
   *  EMPTY MEANS EVERY WORK TYPE and that is not a special case invented here -- it is what
   *  appliesToWorkType has always read `[]` as, and what every row in the library currently
   *  relies on. So pressing the last one off returns the row to all five rather than to none,
   *  and the cell says which of the two it is on every render.
   *
   *  renderDefaultTakeoff(), NOT paint(), for the reason setConditionDefault gives below: this
   *  field is read by this one table and nothing else, and paint() would rebuild the Items tab,
   *  the assembly rail and the open panel -- one of which may be holding a half-typed labor line.
   *  The row dropping out of the list when it stops applying to the work type on screen happens
   *  in that one render.
   *
   *  LABOR REPAINTS renderLabor(), NOT renderDefaultTakeoff() -- the chips live on the Labor tab's
   *  own row now (workTypeCell's first real caller), not on the Defaults tab, which dropped its
   *  per-row chips 2026-09-22 and has carried none since. Repainting the wrong one would leave the
   *  press invisible on the only table it is drawn in. */
  async function setRowWorkType(kind, id, wt, on) {
    var list = kind === "assemblies" ? ASMS : kind === "labor" ? LABOR : ITEMS;
    var row = null;
    for (var i = 0; i < list.length; i++) if (list[i].id === id) { row = list[i]; break; }
    if (!row) return;
    var was = (row.default_work_types || []).slice();
    var next = [];
    for (var j = 0; j < was.length; j++) if (was[j] !== wt) next.push(was[j]);
    if (on) next.push(wt);
    row.default_work_types = next;
    // A LABOR CHIP REPAINTS BOTH LABOR TABLES: the Labor tab it sits on, and the Defaults tab's
    // Labor list, which is filtered by exactly this field and is not repainted by a tab switch.
    // The chip pressed is replaced by the redraw, so the focus goes back onto its successor --
    // a keyboard user pressing Space must not be dropped to the top of the page.
    function repaint() {
      if (kind !== "labor") { renderDefaultTakeoff(); return; }
      renderLabor();
      renderDefaultLabor();
      var lb = $("labor-body");
      var chip = lb && lb.querySelector && lb.querySelector('[data-wt-toggle="labor"][data-wt-id="' +
        id + '"][data-wt="' + wt + '"]');
      if (chip && chip.focus) chip.focus();
    }
    repaint();
    try {
      await patchWorkTypes(kind, id, next);
    } catch (err) {
      row.default_work_types = was;
      repaint();
      say("Couldn't save that. " + err.message);
    }
  }

  /** The five work types as pressable chips, so the filter above the table has something to
   *  filter ON. Rendered in the row rather than behind an Edit, because Edit leaves this tab
   *  for the Items table -- which is eight columns wide already -- and because this field is
   *  read by nothing except the chips a few lines up the same screen.
   *
   *  THE CELL STATES THE CONSEQUENCE, not just the state. Going from "all work types" to one
   *  pressed chip NARROWS the row from five lists to one, which is a bigger move than a chip
   *  press looks like, so the line under the chips says which it is. */
  function workTypeCell(kind, row) {
    var list = (row && row.default_work_types) || [];
    var chips = WORK_TYPES.map(function (wt) {
      var on = list.indexOf(wt) !== -1;
      return '<button class="wtchip" type="button" aria-pressed="' + (on ? "true" : "false") +
        '" data-wt-toggle="' + esc(kind) + '" data-wt-id="' + esc(row.id) +
        '" data-wt="' + esc(wt) + '" aria-label="' + esc(row.name || "This line") +
        (on ? " applies to " : " does not apply to ") + esc(wt) + '">' + esc(wt) + "</button>";
    }).join("");
    return '<span class="wtchips">' + chips + "</span>" +
      '<span class="wtall">' + (list.length ? "" : "All work types") + "</span>";
  }

  /** The slider cell of one default: ON means a new bid starts with this row counted, OFF means it
   *  starts grayed and adding nothing (the estimate's own slider, flipped there per bid).
   *
   *  THE SAME COMPONENT THE ESTIMATE DRAWS -- B.sliderHtml, from the shared module both pages
   *  load -- so the two cannot look or behave differently. `canEdit` false draws the state as plain
   *  words, not a switch that would 403 on press (the rule the labor Remove already follows). With
   *  no shared module there is no slider, rather than a hand-typed second copy of it. */
  function defaultSlider(kind, id, name, on, canEdit) {
    var B = window.TWPolishBid;
    if (!canEdit) return '<span class="wtall">' + (on ? "On" : "Off") + "</span>";
    if (!B || !B.sliderHtml) return "";
    return B.sliderHtml(on, 'data-def-on="' + esc(kind) + '" data-def-on-id="' + esc(id) + '"',
      on ? "On" : "Off", (on ? "Starts on" : "Starts off") + " when an estimate opens: " + name);
  }

  /** Flip one default's starting state. OPTIMISTIC, WITH THE PUT-BACK IN HERE, like setDefault and
   *  setConditionDefault: two places to forget the rollback is how a slider ends up showing a
   *  state nothing stored.
   *
   *  THREE STORES, ONE FUNCTION. A library row (item, assembly, labor line) holds `default_on`; the
   *  three condition materials are RESERVED items whose answer is condition_defaults.on_by_default,
   *  so a reserved id goes there (the same split removeDefault makes). Neither writes `favorite`:
   *  whether a row IS a default and whether it STARTS ON are different questions. */
  async function setDefaultOn(kind, id, on) {
    if (kind === "items" && isReservedItem(id)) {
      var key = RESERVED_ITEM_CONDITION[id];
      var was = COND_DEFAULTS;
      var next = [], found = false;
      for (var i = 0; i < was.length; i++) {
        if (was[i] && was[i].key === key) {
          next.push(Object.assign({}, was[i], { on: !!on })); found = true;
        } else next.push(was[i]);
      }
      if (!found) next.push({ key: key, on: !!on, listed: true });
      COND_DEFAULTS = next;
      renderDefaultTakeoff();
      try {
        await putConditionDefault(key, { on: !!on });
      } catch (err) {
        COND_DEFAULTS = was;
        renderDefaultTakeoff();
        say("Couldn't save that. " + err.message);
      }
      return;
    }
    var list = kind === "assemblies" ? ASMS : kind === "labor" ? LABOR : ITEMS;
    var row = null;
    for (var j = 0; j < list.length; j++) if (list[j].id === id) { row = list[j]; break; }
    if (!row) return;
    var prior = row.default_on;
    row.default_on = !!on;
    var repaint = function () { if (kind === "labor") renderDefaultLabor(); else renderDefaultTakeoff(); };
    repaint();
    try {
      await patchDefaultOn(kind, id, !!on);
    } catch (err2) {
      row.default_on = prior;
      repaint();
      say("Couldn't save that. " + err2.message);
    }
  }

  function defaultRowActions(kind, id, name) {
    return '<button class="btn ghost sm" type="button" data-def-edit="' + esc(kind) +
      '" data-def-id="' + esc(id) + '">Edit</button>' +
      '<button class="btn ghost sm danger" type="button" data-def-off="' + esc(kind) +
      '" data-def-id="' + esc(id) + '" aria-label="Stop ' + esc(name) +
      ' being a default">Remove</button>';
  }

  /** One row of the Takeoff defaults' Materials group, for a favorited material AND for each of
   *  the three condition materials -- one function, so the two cannot be drawn differently.
   *
   *  Hanz, 2026-10-01, of joint filler, remove-existing and dye: "make these 3 as materials", then
   *  "All 3 exactly like materials". Until then they had their own row code (conditionRowActions
   *  and a priced cell with a "writes Polish!E29 · not in a new bid" tag) and were listed whether
   *  or not a new bid bought them, so they looked like a different kind of thing sitting under the
   *  Materials heading. Now there is one row builder and one pair of buttons, defaultRowActions'
   *  own: Edit opens the row on the Items tab, where all three are reserved library rows, and
   *  Remove stops it being a default. Which STORE Remove writes is decided when it is pressed
   *  (removeDefault), not by drawing a different button. */
  function materialDefaultRow(id, name, how) {
    return { name: name, how: how, actions: defaultRowActions("items", id, name) };
  }

  /** One of the three condition materials on the Takeoff list, drawn as the material row it is.
   *
   *  LISTED MEANS "ON A NEW ESTIMATE, GRAYED UNTIL SWITCHED ON". Hanz, 2026-10-01, after a day
   *  of answers: "it should be edit and remove", "dont start as on staart as off in the
   *  estimating sheet but it appears as grayed out like travel in labor", and "Everything that is
   *  in the defaults and labor tab in the Items and Assemblies appear as grayed out options that
   *  can be enabled or not". So a listed condition is a default like any material -- Edit, Remove
   *  -- and what it gives a new bid is its card on the Takeoff step, dimmed and switched off.
   *  Remove takes it off this list (condition_defaults.listed = false) and off the next new bid;
   *  "+ Add a takeoff default" puts it back. Nothing here can make one START on.
   *
   *  REMOVE IS AN ADMIN'S ONLY. PUT /api/condition-defaults refuses anybody else
   *  (_require_admin), so offering it to an estimator would be a button that always 403s -- the
   *  reason the labor rows on this tab are gated on ADMIN too. Everyone keeps Edit. */
  function conditionDefaultRow(c) {
    var row = materialDefaultRow(c.item_id, c.name, c.priced);
    // THE SLIDER IS THE CONDITION'S STARTING ANSWER (condition_defaults.on_by_default). An admin's:
    // the PUT behind it refuses anybody else, so everyone else reads the state as words.
    row.slider = defaultSlider("items", c.item_id, c.name, !!c.on, ADMIN);
    if (!ADMIN) {
      row.actions = '<button class="btn ghost sm" type="button" data-def-edit="items" data-def-id="' +
        esc(c.item_id) + '">Edit</button>';
    }
    return row;
  }

  var DEFAULT_Q = "";
  var DEFAULT_MAX = 8;
  // BROWSE MODE. The search answers "I know what it is called"; this answers "show me what
  // there is". Sitting down to set the defaults up is the second one, and an empty query
  // returning nothing made the Add button below the list have nothing to open.
  var DEFAULT_BROWSE = false;

  // WHICH WORK TYPE THE DEFAULTS TAB IS SHOWING. The five are markup.TABS -- the tabs of
  // Kyle's workbook and the list the markup rules are already filed under. `combo` is not
  // among them: a combo job runs on the epoxy AND polish tabs, so it reads both lists.
  var WORK_TYPES = ["polish", "seal", "epoxy", "leveling", "gyp"];
  var DEFAULT_WT = WORK_TYPES[0];

  /** Does this default belong on the tab currently showing?
   *
   *  AN EMPTY LIST MEANS EVERY WORK TYPE, and that is the whole backwards-compatibility
   *  story: every row set before these tabs existed has no list, so it keeps appearing
   *  everywhere exactly as it did. Nobody opens this tab to find their defaults gone. */
  function appliesToWorkType(row, wt) {
    var list = row && row.default_work_types;
    if (!list || !list.length) return true;
    return list.indexOf(wt) !== -1;
  }

  /** What a row says about where it applies, so the list can be read without clicking
   *  through all five tabs to find out. */
  function workTypeLabel(row) {
    var list = (row && row.default_work_types) || [];
    if (!list.length) return '<span class="wtall">All work types</span>';
    return esc(list.join(", "));
  }

  function defaultCandidates() {
    var q = DEFAULT_Q.trim().toLowerCase();
    if (!q && !DEFAULT_BROWSE) return { rows: [], more: 0 };
    var hits = [];
    ASMS.forEach(function (a) {
      if (!a.favorite && (!q || String(a.name || "").toLowerCase().indexOf(q) !== -1)) {
        hits.push({ kind: "assemblies", id: a.id, name: a.name, what: "Assembly" });
      }
    });
    ITEMS.forEach(function (it) {
      // THE THREE RESERVED ROWS ARE NOT OFFERED HERE, by their `favorite` -- that flag is not what
      // puts them in a bid. They are offered just below, by their condition.
      if (isReservedItem(it.id)) return;
      if (!it.favorite && (!q || String(it.name || "").toLowerCase().indexOf(q) !== -1)) {
        hits.push({ kind: "items", id: it.id, name: it.name, what: "Material" });
      }
    });
    // JOINT FILLER, REMOVE-EXISTING AND DYE, once taken off the list, are found here like any
    // material that is not a default, and adding one puts it back (the add router's "conditions"
    // arm). Polish tab only, and an admin's only -- the write is _require_admin.
    //
    // FIRST IN THE LIST: Browse shows DEFAULT_MAX rows, and after eight un-favorited materials a
    // removed condition would fall off the end and be findable only by typing its name.
    //
    // MATCHED ON THE ROW'S NAME AND THE CONDITION'S LABEL, so "joint" finds the kit whatever an
    // admin has renamed it to.
    if (ADMIN && DEFAULT_WT === "polish") {
      var condHits = [];
      takeoffConditionDefaults().forEach(function (c) {
        if (c.listed) return;
        if (!q || String(c.name || "").toLowerCase().indexOf(q) !== -1 ||
            String(c.label || "").toLowerCase().indexOf(q) !== -1) {
          condHits.push({ kind: "conditions", id: c.key, name: c.name, what: "Material" });
        }
      });
      hits = condHits.concat(hits);
    }
    // LABOR, 2026-09-24 -- the Labor tab's own rows, offered the same way an un-favorited
    // material or assembly already is: findable here, one press to make a default. `travel`
    // is deliberately never a candidate -- it is not opted into a bid the way a favorited row
    // is, it is built into every estimate whether or not this table can address it at all, so
    // offering it here would be a second, misleading way to "add" a line that is already on
    // every bid regardless.
    //
    // AN ADMIN'S ONLY. Making a labor line a default is a PATCH to /api/library/labor, which the
    // server refuses anybody else; an Add offered here to a non-admin would 403 on press.
    LABOR.forEach(function (l) {
      if (ADMIN && l.id !== "travel" && !l.favorite &&
          (!q || String(l.name || "").toLowerCase().indexOf(q) !== -1)) {
        hits.push({ kind: "labor", id: l.id, name: l.name, what: "Labor" });
      }
    });
    return { rows: hits.slice(0, DEFAULT_MAX), more: Math.max(0, hits.length - DEFAULT_MAX) };
  }

  // NAMED, NOT INLINE IN THE LISTENERS, because this harness can only read a listener body
  // and not run it -- its own doc says anything with a decision in it belongs in a function.
  // Both of these have one: whether the results box opens at all.
  function setDefaultQuery(value) {
    DEFAULT_Q = value == null ? "" : String(value);
    renderDefaultSearch();
  }

  /** WHERE THE SEARCH BOX SITS. Hanz, 2026-10-05: "Adding a default [labor] should have the search
   *  bar right above the [Labor] container itself, not on the work type up above." There is ONE
   *  box (#default-search, input and results together) and this moves it to sit directly above
   *  the table of the section whose button was pressed -- one box means only one can be open at
   *  a time, and nothing else (ids, handlers, the browse data) had to be duplicated. A box that
   *  moves to ANOTHER section starts empty: a query typed for Takeoff is not a question about
   *  Labor. */
  function placeDefaultSearch(which) {
    var wrap = $("default-search"), sec = $("default-" + which);
    if (!wrap || !sec || !sec.querySelector) return;
    var tw = sec.querySelector(".tw");
    if (!tw || !tw.parentNode) return;
    if (wrap.parentNode !== tw.parentNode) {
      DEFAULT_Q = "";
      var qb = $("default-q");
      if (qb) qb.value = "";
      tw.parentNode.insertBefore(wrap, tw);
    }
    wrap.hidden = false;
  }

  /** Cancel / Escape: shut the box and forget the query, leaving the rows alone. Focus goes back
   *  to the button that opened it, so the keyboard is not stranded on a hidden input. */
  function closeDefaultSearch() {
    DEFAULT_Q = "";
    DEFAULT_BROWSE = false;
    var qb = $("default-q");
    if (qb) qb.value = "";
    var wrap = $("default-search");
    if (wrap) wrap.hidden = true;
    renderDefaultSearch();
    var par = wrap && wrap.parentNode, btn = par && par.querySelector &&
      par.querySelector("[data-add-default]");
    if (btn && btn.focus) btn.focus();
  }

  /** The search box's keyboard: Escape closes it. Named for the reason openDefaultAdd gives. */
  function onDefaultSearchKey(e) {
    if (e && e.key === "Escape") {
      if (e.stopPropagation) e.stopPropagation();
      closeDefaultSearch();
      return true;
    }
    return false;
  }

  function openDefaultBrowse(which) {
    if (which) placeDefaultSearch(which);
    DEFAULT_BROWSE = true;
    renderDefaultSearch();
    var abox = $("default-q");
    if (abox) abox.focus();
  }

  /** Which "add a default" was pressed, and what that opens. NAMED FOR THE SAME REASON THE TWO
   *  ABOVE ARE: the harness can read a listener body and cannot run one, and its own doc says
   *  anything with a decision in it belongs in a function a test can call.

   *  BOTH ARMS OPEN THE SAME BROWSE, 2026-09-24. Until the Labor tab existed a labor line did not
   *  exist until somebody TYPED it here, so this used to open a form instead of the shared browse
   *  -- and for one day it opened NOTHING: the button was markup with no handler, and every test
   *  over it passed, because they matched the pane for data-add-default="labor" and a dead button
   *  carries that attribute perfectly. Hanz found it instead, twice. Creating a labor TYPE is the
   *  new Labor tab's job now; this button is only ever reached to make one an existing type a
   *  DEFAULT, which is exactly what a takeoff default already is -- a library row that already
   *  exists and has to be FOUND. `defaultCandidates()` already answers with all three kinds, so
   *  the two arms collapse into the one search-and-browse mechanism Items and Assemblies already
   *  used here; only the label on the button still says which list somebody meant to sit down and
   *  fill in. */
  function openDefaultAdd(which) {
    if (which === "takeoff" || which === "labor") openDefaultBrowse(which);
  }

  function renderDefaultSearch() {
    var box = $("default-hits");
    if (!box) return;
    var res = defaultCandidates();
    if (!DEFAULT_Q.trim() && !DEFAULT_BROWSE) {
      box.hidden = true; box.innerHTML = ""; return;
    }
    box.hidden = false;
    if (!res.rows.length) {
      box.innerHTML = '<p class="nores">' + (DEFAULT_Q.trim()
        ? "Nothing left to add by that name. Anything already a default is not offered twice."
        : "Every material and assembly in the library is already a default.") + "</p>";
      return;
    }
    box.innerHTML = res.rows.map(function (r) {
      return '<button class="defhit" type="button" data-def-add="' + esc(r.kind) +
        '" data-def-id="' + esc(r.id) + '">' + esc(r.name) +
        '<span class="k">' + esc(r.what) + "</span></button>";
    }).join("") + (res.more
      ? '<p class="nores">' + res.more + " more match" + (res.more === 1 ? "" : "es") +
        " — keep typing.</p>"
      : "");
  }

  // GROUPED, NOT A KIND COLUMN, and the comment in library.html that argued the other way is
  // replaced rather than ignored. Hanz, 2026-09-17: "for the take off please sub categorize the
  // containers wheter they are materials or assemblies". The old reasoning was that a column
  // says "one list read three ways" while sections would say the three are unrelated. That
  // reasoning survives here: these are SUB-HEADINGS INSIDE ONE TABLE, not four tables. One
  // list, one scroll, signposted -- which is what he asked for and what that comment wanted.
  //
  // The Kind column goes, because with a heading over every group it repeated itself on every
  // row, and an empty group renders NOTHING rather than a heading over blank space.
  //
  // SEPARATE FROM THE RENDERER so a test can execute the grouping and read it back as data.
  // This page has already shipped a dead button behind a green markup regex once.
  function takeoffDefaultGroups() {
    var groups = [
      { title: "Assemblies",
        rows: ASMS.filter(function (a) {
          return a.favorite && appliesToWorkType(a, DEFAULT_WT);
        }).map(function (a) {
          var n = (a.lines || []).length;
          return { name: a.name,
                   how: n + " item line" + (n === 1 ? "" : "s") + " \u00b7 per " + (a.unit || "SF"),
                   slider: defaultSlider("assemblies", a.id, a.name, a.default_on !== false, true),
                   actions: defaultRowActions("assemblies", a.id, a.name) };
        }) },
      { title: "Materials",
        // JOINT FILLER, REMOVE-EXISTING AND DYE ARE MATERIALS HERE, drawn by the material row's
        // own code. Hanz, 2026-09-18: "die and joint filler are supposed to be materials not
        // something that is default"; 2026-10-01: "make these 3 as materials", then "All 3
        // exactly like materials". So each is drawn by the material row's code with the same Edit
        // and Remove while a new bid buys it.
        //
        // LISTED MEANS ON A NEW ESTIMATE, GRAYED UNTIL SWITCHED ON (later on 2026-10-01): listed
        // while condition_defaults.listed is not false, with the material's Edit and Remove; all
        // three still start off (conditionDefaultRow).
        rows: ITEMS.filter(function (it) {
          // Never a reserved row by its `favorite`: the three are listed below, by their condition.
          return it.favorite && !isReservedItem(it.id) && appliesToWorkType(it, DEFAULT_WT);
        }).map(function (it) {
          var mrow = materialDefaultRow(it.id, it.name,
                   L.num(it.unit_cost) != null
                     ? L.money(it.unit_cost) + " per " + (it.unit || "unit")
                     : "No cost in the library yet");
          mrow.slider = defaultSlider("items", it.id, it.name, it.default_on !== false, true);
          return mrow;
        }).concat(takeoffConditionDefaults().filter(function (c) {
          // ON THE POLISH TAB ONLY. All three write Polish-sheet cells (CONDITION_CELLS in
          // polish-bid-core.js) and nothing on the other four work types reads them; a combo job
          // reads the Polish list. And only while LISTED -- see conditionDefaultRow.
          return DEFAULT_WT === "polish" && c.listed;
        }).map(function (c) {
          // KEYED BY THE RESERVED ROW'S ID, so Edit lands on that row on the Items tab like any
          // material's does, and Remove reaches removeDefault, which sends a reserved id to the
          // condition default rather than to `favorite`.
          return conditionDefaultRow(c);
        })) },
      { title: "Markup",
        rows: GLOBAL_MARKUP.map(function (g) {
          // EDITABLE HERE, STORED THERE. Hanz asked for no read-only rows on this tab. The
          // danger with a rate is TWO HOMES: markup.py enforces one home per line because
          // two places to set one price disagree the first time somebody changes one, and a
          // disagreement between them is a wrong bid, not a cosmetic bug.
          //
          // So this is a second DOOR, not a second home. The box writes the same
          // markup_rules row the Markup page writes, by id. There is still exactly one
          // place the number lives, and it is impossible for the two screens to hold
          // different answers because they are holding the same row.
          return { name: g.label,
                   how: '<input class="mkin" type="text" data-markup-formula="' +
                     esc(g.id) + '" value="' + esc(g.formula || "") +
                     '" aria-label="Formula for ' + esc(g.label) +
                     '" placeholder="not set" /> <span class="wtall">also on the Markup ' +
                     'page\u2019s Global tab</span>',
                   rawHow: true,
                   actions: '<span class="builtin">Saved to Markup</span>' };
        }) },
    ];
    return groups.filter(function (g) { return g.rows.length > 0; });
  }

  function renderDefaultTakeoff() {
    var body = $("default-takeoff-body");
    if (!body) return;
    var out = "";
    takeoffDefaultGroups().forEach(function (g) {
      out += '<tr class="grouphead"><th scope="colgroup" colspan="4">' +
        esc(g.title) + "</th></tr>";
      g.rows.forEach(function (r) {
        // rawHow ONLY for the rows that build their own control. Everything else stays
        // escaped -- a material name is somebody typed text and must never render as HTML.
        //
        // NO WORK-TYPES COLUMN. It lived here for one day. Hanz, 2026-09-22: "remove the
        // worktype section because this is not looking good" -- five chips on every row, wrapping
        // to two lines, over a table whose other two columns are a name and a sentence.
        //
        // THE SCOPING DID NOT GO WITH IT. The chips were the only writer for
        // default_work_types, and deleting them outright would put the work-type filter above
        // this table straight back to filtering nothing, which is the defect he reported the same
        // morning. The control moved to the material's own row on the Items tab, where the rest
        // of a material's properties (coverage, waste, roundup) now live -- and Edit on this row
        // already goes there.
        out += "<tr><td>" + esc(r.name) + "</td><td>" +
          (r.rawHow ? r.how : esc(r.how)) + "</td>" +
          '<td class="rowon">' + (r.slider || "") + "</td>" +
          '<td class="rowact">' + r.actions + "</td></tr>";
      });
    });
    body.innerHTML = out;
    if ($("default-takeoff-empty")) $("default-takeoff-empty").hidden = out !== "";
  }

  // -- the Labor defaults, 2026-09-24: favorited on this tab, TYPED on the new Labor tab -------
  /** What a labor line may be measured in.

   *  A LIST RATHER THAN A FREE BOX, because `unit` is not a label: it decides whether the rate
   *  multiplies hours or man-days, and a third value typed here would price at whichever branch
   *  the estimate's `else` happens to be. The API refuses anything off this list with a 400; the
   *  control declines to offer it in the first place, so the refusal is not something an estimator
   *  has to read out of a response body.
   *
   *  SHARED WITH THE LABOR TAB'S OWN UNIT PICKER, not restated there -- see renderLabor. */
  var LABOR_UNITS = ["hours", "days"];

  /** Put Travel back on the rate the tool ships with.

   *  A PATCH, NOT A DELETE, and that is a deliberate difference from Remove above. A soft delete
   *  would also work on screen -- list_labor() would stop answering with the row and travelSeed()
   *  would fall back to the shipped rate -- but it would take the row's ID with it, and the id is
   *  the only thing anything can address Travel by. `LibraryLaborIn` has no id field and
   *  create_labor mints a uuid, both on purpose, so nothing reachable from this page could ever
   *  make a row called `travel` again: one press of Reset would cost the editability the rest of
   *  this change is about, permanently, and the button that did it would then vanish too. PATCHing
   *  the row back to the shipped figures says exactly the same thing to a reader of the list and
   *  leaves Travel editable tomorrow.

   *  THE SHIPPED FIGURES COME FROM travelSeed(), not from three literals here. This page has no
   *  business holding a second copy of Travel's rate -- see the note above travelSeed for what
   *  happened the last time two copies existed.

   *  OPTIMISTIC, WITH THE ROW PUT BACK ON A FAILURE, like both writes above it: a rate that looks
   *  reset and returns on the next reload is worse than one that refuses out loud. */
  async function resetTravelDefault() {
    var B = window.TWPolishBid;
    var shipped = B && B.travelSeed ? B.travelSeed() : null;
    if (!shipped) return;
    var at = -1;
    for (var i = 0; i < LABOR.length; i++) {
      if (LABOR[i] && LABOR[i].id === shipped.id) { at = i; break; }
    }
    // Nothing stored means nothing overridden: the line is already on the shipped rate and there
    // is no row to patch. The button is not drawn in that state, so this is the second tab case.
    if (at === -1) return;
    var was = LABOR[at];
    var body = { name: shipped.label, rate: shipped.rate, unit: shipped.unit };
    LABOR[at] = Object.assign({}, was, body);
    renderDefaultLabor();
    try {
      var pj = await patchLabor(shipped.id, body);
      for (var k = 0; k < LABOR.length; k++) {
        if (LABOR[k] && LABOR[k].id === shipped.id) {
          LABOR[k] = pj.row || Object.assign({}, was, body);
          break;
        }
      }
      say("");
      renderDefaultLabor();
    } catch (err) {
      for (var j = 0; j < LABOR.length; j++) {
        if (LABOR[j] && LABOR[j].id === shipped.id) { LABOR[j] = was; break; }
      }
      renderDefaultLabor();
      say("Couldn't reset " + shipped.label + ". " + (err.message || ""));
    }
  }

  /** Travel's own row controls on the Defaults tab, for an admin and nobody else. TRAVEL ONLY,
   *  since 2026-09-24 -- every OTHER labor default on this tab now carries the same Edit/Remove
   *  pair every item and assembly default already does (see `defaultRowActions`), because a
   *  labor type is a library row like theirs now and Edit means the same thing for all three:
   *  go to where the thing is defined. Travel is the one row that is not a library row a browse
   *  can find or a Remove can take off the list -- it is seeded by the schema and by nothing
   *  else, so it keeps the bespoke pair this function has always drawn for it.
   *
   *  THE WRITES ARE ADMIN-ONLY ON THE SERVER, so this does not offer a control that 403s on press.
   *  That is the rule load() already follows when it resolves the role BEFORE the first paint, and
   *  the one the Administration lists follow when they render text instead of inputs.
   *
   *  `travel` IS THE STORED library_labor ROW WITH THE RESERVED ID, or null when there is none.
   *  Two things follow from it and each is the honest answer rather than a convenience:
   *
   *    * NO STORED ROW, NO CONTROLS. Every estimate is seeded with Travel from travelSeed()
   *      whether or not this table answers, so on a database where `library_labor` has not been
   *      created the line is real and its rate is genuinely not editable -- there is nothing to
   *      PATCH. An Edit button there would open the Labor tab onto a row that is not on it, which
   *      is worse than the chip it replaced, not better.
   *    * RESET, ONLY WHEN THERE IS SOMETHING TO RESET. `travelSeed(row)` with no row IS the
   *      shipped row, so an unedited default compares equal to it and offers no Reset at all -- a
   *      control that would change nothing is a control that reads as broken when it appears to
   *      do nothing. Name, rate and unit are compared because those are the three the Labor tab's
   *      own row can edit; a renamed Travel with the shipped rate still has a way back. */
  function laborRowActions(travel) {
    if (!ADMIN) return "";
    var B = window.TWPolishBid;
    var shipped = B && B.travelSeed ? B.travelSeed() : null;
    if (!shipped || !travel) return "";
    // EDIT GOES TO THE ROW, on the Labor tab -- the same rule defaultRowActions already follows
    // for a material or an assembly, and the one Travel itself did not have until that tab
    // existed to send it to.
    var edit = '<button class="btn ghost sm" type="button" data-def-edit="labor"' +
      ' data-def-id="' + esc(shipped.id) + '">Edit</button>';
    var now = B.travelSeed(travel);
    var changed = now.label !== shipped.label || now.rate !== shipped.rate ||
                  now.unit !== shipped.unit;
    if (!changed) return edit;
    return edit + '<button class="btn ghost sm danger" type="button" data-labor-reset="' +
      esc(shipped.id) + '" aria-label="Reset ' + esc(shipped.label) +
      ' to the rate the tool ships with">Reset</button>';
  }

  /** The Labor defaults. Travel is in here before anybody adds anything.
   *
   *  IT IS NOT A NEW DEFAULT, it is the one that was always there and never shown. Every new
   *  estimate is seeded with a Travel row and every older draft has one appended on migration, so
   *  the bid has behaved this way for months -- what was missing is anywhere to SEE that, which is
   *  what made it read as hardcoded rather than as a default somebody chose.
   *
   *  READ FROM THE SHARED MODULE, never re-typed. travelSeed's own comment records the two copies
   *  that existed before drifting within a day; a third on this page would drift unseen, because
   *  nothing here prices anything and a stale rate would look exactly like a fresh one. That is
   *  also why the id it looks the stored row up by is `travelSeed().id` rather than a string typed
   *  here: one statement of what Travel is called in a model, still.
   *
   *  ONE TRAVEL ROW, MERGED, NOT TWO. The stored row carrying the reserved id is drawn THROUGH
   *  travelSeed and then excluded from the list below. Left in, it would appear a second time,
   *  under the same name, with its own Edit and Remove -- and an admin would have two rows to
   *  choose between with no way to tell which one prices a bid.
   *
   *  EVERY OTHER ROW IS FILTERED ON `favorite`, 2026-09-24. Before that column existed every row
   *  here WAS shown, because existence in this table was the only thing "default" could mean; a
   *  labor type can now exist on the Labor tab without being one, and this list is "what a new
   *  bid opens holding", not "every labor type Treadwell has ever typed" -- that second list is
   *  the Labor tab's job. `defaultRowActions("labor", …)` is the same Edit/Remove pair an item or
   *  an assembly default already carries here; Edit goes to the Labor tab now, the same way an
   *  item default's Edit goes to the Items tab. */
  function renderDefaultLabor() {
    var body = $("default-labor-body");
    if (!body) return;
    var B = window.TWPolishBid;
    var shipped = B && B.travelSeed ? B.travelSeed() : null;
    // The stored override, or null on a database where this table does not exist yet -- in which
    // case travelSeed(null) hands back the shipped row and the line renders exactly as it did
    // before any of this, which is what production sees until the DDL runs.
    var storedTravel = null;
    if (shipped) {
      for (var s = 0; s < LABOR.length; s++) {
        if (LABOR[s] && LABOR[s].id === shipped.id) { storedTravel = LABOR[s]; break; }
      }
    }
    var rows = shipped ? [B.travelSeed(storedTravel)] : [];
    var out = "";
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      out += "<tr>" +
        "<td>" + esc(r.label) + "</td>" +
        '<td class="n">' + esc(L.money(r.rate)) + (r.unit === "hours" ? " / hr" : " / day") +
        "</td>" +
        "<td>" + (r.guys_auto
          ? "Man-days come off the crew rows above it"
          : "Typed on the estimate") + "</td>" +
        // Travel's slider needs the stored row to PATCH; with none there is nothing to switch.
        '<td class="rowon">' + (storedTravel
          ? defaultSlider("labor", storedTravel.id, r.label, storedTravel.default_on !== false, ADMIN)
          : "") + "</td>" +
        '<td class="rowact">' + laborRowActions(storedTravel) + "</td>" +
        "</tr>";
    }
    // THE LINES SOMEBODY HAS FAVORITED, beside the one that was always there. Each carries the
    // same Edit/Remove pair the Takeoff list beside it already does, and Remove there and here
    // mean the same thing: stop being a default, not delete the underlying row -- that is the new
    // Labor tab's delete icon, a different and more consequential action on a different screen.
    // FILTERED BY THE WORK-TYPE TAB, like the Takeoff list above it. Travel is neither filtered
    // nor listed here: it is seeded into every bid whatever tab it sits on, and it has already
    // been drawn above -- listing it again is the double-Travel row this merge exists to prevent.
    var shown = LABOR.filter(function (r) {
      return (!shipped || r.id !== shipped.id) && r.favorite && appliesToWorkType(r, DEFAULT_WT);
    });
    for (var k = 0; k < shown.length; k++) {
      var c = shown[k];
      out += "<tr>" +
        "<td>" + esc(c.name) + "</td>" +
        '<td class="n">' + esc(L.money(c.rate)) +
          (c.unit === "days" ? " / day" : " / hr") + "</td>" +
        "<td>" + (c.guys_auto
          ? "Man-days come off the crew rows above it"
          : "Typed on the estimate") + "</td>" +
        '<td class="rowon">' + defaultSlider("labor", c.id, c.name, c.default_on !== false, ADMIN) +
          "</td>" +
        // ADMIN ONLY, unlike an item's or an assembly's pair: `favorite` on a labor line is a
        // PATCH to /api/library/labor, which is `_require_admin`, so a non-admin is not handed a
        // Remove that 403s -- the rule laborRowActions already follows for Travel.
        '<td class="rowact">' + (ADMIN ? defaultRowActions("labor", c.id, c.name) : "") +
        "</td></tr>";
    }
    body.innerHTML = out;
    // Counts BOTH, so a page that could not reach the shared module still hides the empty state
    // once there is a favorited line to show. Travel is normally in `rows`, which is why this
    // read correctly while it was the only thing that could be.
    if ($("default-labor-empty")) {
      $("default-labor-empty").hidden = (rows.length + shown.length) > 0;
    }
    // THE ADD BUTTON IS AN ADMIN'S, for the same reason as the row pair: what it opens is the
    // shared browse, but the only labor it can offer there is a PATCH the server refuses anybody
    // else, and defaultCandidates leaves labor out for a non-admin. A "labor default" button that
    // opened onto materials alone would be the dead control this tab has already shipped once.
    var addrow = $("default-labor-addrow");
    if (addrow) addrow.hidden = !ADMIN;
  }

  // ── the Labor Calculator tab (Hanz, 2026-10-05) ────────────────────────────
  /** WHAT THIS TAB IS: where the calculations behind a new estimate's default labor lines live.
   *  Today it holds the TRAVEL section -- Travel Labor, Lodging and Per Diem -- and the rest of the
   *  calculator (per-line crew/production-rate modes) is a queued follow-up.
   *
   *  LODGING AND PER DIEM ARE NOT STORED HERE. They are the Markup page's Global lines
   *  `travel_lodging` ($70 a night) and `travel_per_diem` ($45 a day), and the boxes below are a
   *  second DOOR onto those same markup_rules rows -- one home, so the two screens cannot disagree.
   *  A new estimate copies each onto its own Lodging / Per Diem line when it opens
   *  (polish-estimate.js), which start OFF. Travel Labor's rate is the Labor tab's Travel row.
   *
   *  ITS OWN READ of /api/markup/rules?layout=global rather than GLOBAL_MARKUP: that list keeps
   *  only filed, applying rows and drops `notes`, and a PUT states the whole row -- a save that
   *  forgot the note would clear one filed elsewhere. */
  var TRAVEL_KEYS = [
    { line: "travel_lodging", label: "Lodging", per: "night", shipped: 70,
      how: "One charge per night away. Nights are the man-days of the labor tasks on the estimate " +
           "(the way the pricing engine counts them) unless the estimator types a number." },
    { line: "travel_per_diem", label: "Per Diem", per: "day", shipped: 45,
      how: "One charge per day away, for meals. Days are counted the same way as nights." }
  ];
  var TRAVEL_RULES = {};            // line_key -> the filed markup_rules row, when there is one
  var TRAVEL_RULES_LOADED = false;
  var TRAVEL_RULES_ERR = false;

  async function loadTravelRules() {
    try {
      var res = await api("/api/markup/rules?layout=global");
      if (!res.ok) throw new Error("HTTP " + res.status);
      var j = await res.json();
      TRAVEL_RULES = {};
      (j.rules || []).forEach(function (r) {
        if (r && r.layout === "global") TRAVEL_RULES[r.line_key] = r;
      });
      TRAVEL_RULES_ERR = false;
    } catch (e) {
      // Empty, not invented: a rate this page made up because a request failed would be worse
      // than a box that says it could not read the figure.
      TRAVEL_RULES = {};
      TRAVEL_RULES_ERR = true;
    }
    TRAVEL_RULES_LOADED = true;
  }

  /** The dollar figure a filed rule holds, or "" when none is filed or it is not a plain number. */
  function travelFigure(rule) {
    if (!rule || rule.applies === false) return "";
    var m = /^\s*\$?\s*(\d+(?:\.\d+)?)\s*$/.exec(String(rule.formula == null ? "" : rule.formula));
    return m ? m[1] : "";
  }

  /** The Labor Calculator's Travel section, drawn from what is loaded. Never throws. */
  function renderLabCalc() {
    var body = $("labcalc-body");
    if (!body) return;
    if (!TRAVEL_RULES_LOADED) {
      body.innerHTML = '<p class="paneintro">Loading...</p>';
      Promise.all([loadTravelRules(), loadCalcRows()]).then(renderLabCalc);
      return;
    }
    var B = window.TWPolishBid;
    var ro = $("labcalc-ro");
    if (ro) ro.hidden = !!ADMIN;
    // Travel Labor is the Labor tab's Travel row; its rate and unit come from there.
    var stored = null;
    for (var s = 0; s < LABOR.length; s++) if (LABOR[s] && LABOR[s].id === "travel") stored = LABOR[s];
    // READ FROM THE SHARED MODULE, never re-typed here (see the note above travelSeed).
    var tl = B.travelSeed(stored);
    var html = '<h3 class="labcalc-h">Travel</h3>' +
      '<p class="paneintro">Travel is expected when the job is <b>70 miles or more</b> from the ' +
      'Olathe office. Under 70 miles all three lines stay gray on the estimate until the ' +
      'estimator switches one on. Lodging and Per Diem start off on every new estimate, and are ' +
      'priced inside the markups, before GP, superintendent and soft costs.</p>' +
      '<div class="tw"><table class="items-table"><thead><tr><th>Line</th><th class="n">Rate</th>' +
      '<th>How it is worked out</th><th class="w-act"></th></tr></thead><tbody>';
    html += '<tr data-labcalc-row="travel"><td>' + esc(tl.label) + '</td><td class="n">' +
      esc(L.money(tl.rate)) + " an " + (tl.unit === "days" ? "day" : "hour") + '</td><td>' +
      'Guys are the man-days of the labor tasks; the estimator types the drive hours for the job. ' +
      'The rate is the Travel line on the Labor tab.</td><td class="rowact">' +
      (ADMIN ? '<button class="ghostlink" type="button" data-labcalc-goto-labor>Edit rate</button>' : "") +
      '</td></tr>';
    TRAVEL_KEYS.forEach(function (t) {
      var fig = travelFigure(TRAVEL_RULES[t.line]);
      html += '<tr data-labcalc-row="' + esc(t.line) + '"><td>' + esc(t.label) + '</td><td class="n">' +
        (ADMIN
          ? '$<input class="mkin" type="text" inputmode="decimal" data-travel-rate="' + esc(t.line) +
            '" value="' + esc(fig) + '" placeholder="' + esc(String(t.shipped)) +
            '" aria-label="' + esc(t.label) + ' rate, dollars per ' + esc(t.per) + '" /> per ' +
            esc(t.per)
          : esc(L.money(fig === "" ? t.shipped : Number(fig))) + " per " + esc(t.per)) +
        '</td><td>' + esc(t.how) + '</td><td class="rowact"><span class="builtin">Saved to Markup' +
        '</span></td></tr>';
    });
    html += '</tbody></table></div>';
    if (TRAVEL_RULES_ERR) {
      html += '<p class="ronote">Could not read the saved figures, so the boxes are empty. ' +
        'Reload to try again.</p>';
    }
    html += calcSectionHtml();
    body.innerHTML = html;
    renderTryIt();
  }

  /** Save one travel rate. A PUT of the whole markup row, notes carried so nothing filed elsewhere
   *  is cleared. A blank box files nothing (the shipped figure stands); anything that is not a
   *  positive number is refused here in words rather than as a 400. */
  async function saveTravelRate(input) {
    var key = input.getAttribute("data-travel-rate");
    var def = null;
    TRAVEL_KEYS.forEach(function (t) { if (t.line === key) def = t; });
    var out = $("labcalc-alert");
    var say2 = function (m) { if (out) out.textContent = m || ""; };
    if (!def) return;
    var raw = String(input.value || "").trim().replace(/^\$/, "");
    var prev = travelFigure(TRAVEL_RULES[key]);
    if (raw === prev) return;
    if (raw === "") {
      say2("Type a dollar figure. The shipped $" + def.shipped + " stands until you do.");
      return;
    }
    if (!/^\d+(\.\d+)?$/.test(raw) || Number(raw) <= 0) {
      say2(def.label + " has to be a dollar figure above zero, like " + def.shipped + ".");
      input.value = prev;
      return;
    }
    say2("");
    try {
      var rule = TRAVEL_RULES[key] || {};
      var res = await api("/api/markup/rules", { method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ layout: "global", line_key: key, applies: true,
                               notes: rule.notes || "", formula: raw }) });
      if (res.status === 403) {
        say2("Changing these figures is admin-only. Nothing was saved.");
        input.value = prev;
        return;
      }
      var j = await res.json().catch(function () { return {}; });
      if (!res.ok) { say2(j.detail || "That didn't save."); input.value = prev; return; }
      TRAVEL_RULES[key] = j.rule || Object.assign({}, rule, { layout: "global", line_key: key,
                                                               applies: true, formula: raw });
      // The Defaults tab's Markup list reads the same row; keep its copy honest.
      GLOBAL_MARKUP.forEach(function (g) { if (g.line_key === key) g.formula = raw; });
      say2(def.label + " saved: $" + raw + " per " + def.per + ". New estimates start from it.");
    } catch (err) {
      say2("Couldn't reach the server. Nothing was saved.");
      input.value = prev;
    }
  }

  // ── the Labor Calculator's per-line modes (Kyle's notes B7b) ───────────────
  /** Each default labor line gets a MODE the estimate's Labor step fills a NEW bid from:
   *    From SF  crew size + production rate (SF a day): days = ceil(job SF / rate)
   *    Fixed    guys + days
   *  both at 8 or 10 hours a day, at the line's own rate or (blank) the company labor rate.
   *  "Not set" is today's behaviour. Stored by /api/library/labor-calc (backend/ops/labor_calc.sql);
   *  an absent table reads as every line "Not set". The arithmetic is B.laborCalcValues, the one
   *  function the estimate also calls, so the Try-it box shows what a new bid will get. */
  var CALC = {};          // line_id -> the mode as it is being edited (may be unsaved/incomplete)
  var CALC_SAVED = {};    // line_id -> what the server holds
  var CALC_TRY_SF = "";
  var CALC_MODES = [["", "Not set (blank, as before)"], ["sf", "From SF"], ["fixed", "Fixed"]];

  async function loadCalcRows() {
    CALC = {}; CALC_SAVED = {};
    try {
      var res = await api("/api/library/labor-calc");
      var j = await res.json();
      ((j && j.calc instanceof Array) ? j.calc : []).forEach(function (r) {
        if (r && r.line_id && r.mode) {
          CALC[r.line_id] = JSON.parse(JSON.stringify(r));
          CALC_SAVED[r.line_id] = JSON.parse(JSON.stringify(r));
        }
      });
    } catch (e) { /* no table / no answer: every line reads Not set */ }
  }

  /** The lines the calculator configures: the built-in crew rows, then the favorited custom ones
   *  that bill by the day. Travel is its own section above. */
  function calcLines() {
    var out = (window.TWPolishBid.LABOR_CALC_BUILTINS || []).map(function (l) {
      return { id: l.id, name: l.name };
    });
    LABOR.forEach(function (r) {
      if (r && r.favorite && r.id !== "travel" && r.unit !== "hours") out.push({ id: r.id, name: r.name });
    });
    return out;
  }

  function calcCompanyRate() {
    var B = window.TWPolishBid;
    return B.laborRateOrShipped(B.laborRateFromRules(
      Object.keys(TRAVEL_RULES).map(function (k) { return TRAVEL_RULES[k]; })));
  }

  /** In words, what stops this mode being saved; "" when it is complete. */
  function calcProblem(c) {
    if (!c || !c.mode) return "";
    var pos = function (v) { return Number(String(v == null ? "" : v).replace(/[$,\s]/g, "")) > 0; };
    if (c.mode === "sf") {
      if (!pos(c.crew)) return "Type how many guys are on the crew.";
      if (!pos(c.sf_per_day)) return "Type how many square feet the crew does in a day.";
    } else {
      if (!pos(c.guys)) return "Type how many guys the line has.";
      if (!pos(c.days)) return "Type how many days the line takes.";
    }
    return "";
  }

  function calcSectionHtml() {
    var co = calcCompanyRate();
    var html = '<h3 class="labcalc-h">Default labor lines</h3>' +
      '<p class="paneintro">Pick how each line fills in on a <b>new</b> estimate. <b>From SF</b> ' +
      "works the days out from the job's square feet (days = SF / production rate, rounded up). " +
      '<b>Fixed</b> uses the guys and days you type. A blank rate uses the company labor rate (' +
      esc(L.money(co)) + ' an hour). The estimator can still change any of it on the bid, and a ' +
      'saved bid is never recomputed.</p>' +
      '<div class="tw"><table class="items-table"><thead><tr><th>Line</th><th>Mode</th>' +
      '<th>Crew and production</th><th>Hours a day</th><th class="n">Rate</th>' +
      '<th class="w-act"></th></tr></thead><tbody>';
    calcLines().forEach(function (l) {
      var c = CALC[l.id] || { mode: "" };
      var inp = function (f, label, w) {
        return ADMIN
          ? '<input class="mkin" type="text" inputmode="decimal" data-lcalc="' + esc(l.id) +
            '" data-f="' + f + '" value="' + esc(c[f] == null ? "" : c[f]) + '" aria-label="' +
            esc(l.name + " " + label) + '" style="width:' + (w || 64) + 'px" />'
          : esc(c[f] == null || c[f] === "" ? "-" : c[f]);
      };
      var fields = c.mode === "sf"
        ? inp("crew", "crew size") + ' guys, ' + inp("sf_per_day", "production rate", 80) + ' SF a day'
        : c.mode === "fixed"
          ? inp("guys", "guys") + ' guys for ' + inp("days", "days") + ' days'
          : '<span class="builtin">Left blank on a new estimate</span>';
      var modeCell = ADMIN
        ? '<select data-lcalc-mode="' + esc(l.id) + '" aria-label="' + esc(l.name) + ' mode">' +
          CALC_MODES.map(function (m) {
            return '<option value="' + m[0] + '"' + ((c.mode || "") === m[0] ? " selected" : "") + '>' +
              esc(m[1]) + '</option>';
          }).join("") + '</select>'
        : esc((CALC_MODES.filter(function (m) { return m[0] === (c.mode || ""); })[0] || [])[1] || "");
      var hpd = Number(c.hours_per_day) === 10 ? 10 : 8;
      var hoursCell = !c.mode ? "" : ADMIN
        ? '<select data-lcalc="' + esc(l.id) + '" data-f="hours_per_day" aria-label="' + esc(l.name) +
          ' hours a day"><option value="8"' + (hpd === 8 ? " selected" : "") + '>8</option>' +
          '<option value="10"' + (hpd === 10 ? " selected" : "") + '>10</option></select>'
        : String(hpd);
      var rateCell = !c.mode ? "" : ADMIN
        ? '$<input class="mkin" type="text" inputmode="decimal" data-lcalc="' + esc(l.id) +
          '" data-f="rate" value="' + esc(c.rate == null ? "" : c.rate) + '" placeholder="' +
          esc(String(co)) + '" aria-label="' + esc(l.name) + ' rate" />'
        : esc(L.money(c.rate > 0 ? Number(c.rate) : co));
      html += '<tr data-lcalc-row="' + esc(l.id) + '"><td>' + esc(l.name) + '</td><td>' + modeCell +
        '</td><td>' + fields + '</td><td>' + hoursCell + '</td><td class="n">' + rateCell +
        '</td><td class="rowact"></td></tr>';
    });
    html += '</tbody></table></div>' +
      '<h3 class="labcalc-h">Try it</h3>' +
      '<p class="paneintro">Type a job size to see what a new estimate would fill in. This changes ' +
      'nothing.</p>' +
      '<p><label>Job SF <input class="mkin" type="text" inputmode="decimal" data-tryit-sf ' +
      'value="' + esc(CALC_TRY_SF) + '" aria-label="Job square feet" style="width:100px" /></label></p>' +
      '<div id="labcalc-tryout"></div>';
    return html;
  }

  /** The Try-it table, from what is SAVED (what a new bid would really get). Never throws. */
  function renderTryIt() {
    var out = $("labcalc-tryout");
    if (!out) return;
    var B = window.TWPolishBid;
    var sf = Number(String(CALC_TRY_SF).replace(/[$,\s]/g, "")) || 0;
    var co = calcCompanyRate();
    var rows = "", total = 0, n = 0;
    calcLines().forEach(function (l) {
      var v = B.laborCalcValues(CALC_SAVED[l.id], sf, co);
      if (!v) return;
      n += 1;
      var cost = B.laborCost({ guys: v.guys, days: v.days, rate: v.rate, hours_per_day: v.hours_per_day });
      total += cost;
      rows += '<tr><td>' + esc(l.name) + '</td><td class="n">' + esc(String(v.guys)) + '</td>' +
        '<td class="n">' + esc(String(v.days)) + '</td><td class="n">' + v.hours_per_day + '</td>' +
        '<td class="n">' + esc(L.money(v.rate)) + '</td><td class="n">' + esc(L.money(cost)) + '</td></tr>';
    });
    if (!n) {
      out.innerHTML = '<p class="paneintro">No line has a mode saved yet, so a new estimate leaves ' +
        'them all blank.</p>';
      return;
    }
    out.innerHTML = '<div class="tw"><table class="items-table"><thead><tr><th>Line</th>' +
      '<th class="n">Guys</th><th class="n">Days</th><th class="n">Hours a day</th>' +
      '<th class="n">Rate</th><th class="n">Cost</th></tr></thead><tbody>' + rows +
      '<tr><td><b>Total</b></td><td></td><td></td><td></td><td></td><td class="n"><b data-tryit-total>' +
      esc(L.money(total)) + '</b></td></tr></tbody></table></div>' +
      '<p class="paneintro">Before burden, travel and markups.' +
      (sf > 0 ? "" : " Type a job size to see the SF-based days.") + '</p>';
  }

  /** Save one line's mode (or clear it). Complete modes only; an incomplete one is said in words
   *  and kept on screen. A refused or failed save puts the line back to what the server holds. */
  async function saveCalc(id) {
    var out = $("labcalc-alert");
    var say2 = function (m) { if (out) out.textContent = m || ""; };
    var c = CALC[id];
    var saved = CALC_SAVED[id];
    var body;
    if (!c || !c.mode) {
      if (!saved) { say2(""); return; }
      body = { mode: "none" };
    } else {
      var why = calcProblem(c);
      if (why) { say2(why + " Nothing is saved until it is complete."); return; }
      body = { mode: c.mode, crew: c.crew, sf_per_day: c.sf_per_day, guys: c.guys, days: c.days,
               hours_per_day: c.hours_per_day || 8, rate: c.rate };
    }
    say2("");
    try {
      var res = await api("/api/library/labor-calc/" + encodeURIComponent(id), { method: "PUT",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      var j = await res.json().catch(function () { return {}; });
      if (!res.ok) {
        say2(res.status === 403 ? "Changing these is admin-only. Nothing was saved."
                                : (j.detail || "That didn't save."));
        if (saved) CALC[id] = JSON.parse(JSON.stringify(saved)); else delete CALC[id];
        renderLabCalc();
        return;
      }
      if (j.row) { CALC[id] = JSON.parse(JSON.stringify(j.row)); CALC_SAVED[id] = JSON.parse(JSON.stringify(j.row)); }
      else { delete CALC[id]; delete CALC_SAVED[id]; }
      say2("Saved. New estimates start from it.");
      renderTryIt();
    } catch (err) {
      say2("Couldn't reach the server. Nothing was saved.");
      if (saved) CALC[id] = JSON.parse(JSON.stringify(saved)); else delete CALC[id];
      renderLabCalc();
    }
  }

  /** A mode picker or a calculator box changed. */
  function calcEdit(el) {
    var id = el.getAttribute("data-lcalc-mode");
    if (id !== null) {
      if (!el.value) delete CALC[id];
      else CALC[id] = Object.assign({ hours_per_day: 8 }, CALC[id] || {}, { mode: el.value });
      renderLabCalc();
      return saveCalc(id);
    }
    id = el.getAttribute("data-lcalc");
    var f = el.getAttribute("data-f");
    if (id === null || !f || !CALC[id]) return null;
    CALC[id][f] = f === "hours_per_day" ? Number(el.value) : String(el.value).trim().replace(/^\$/, "");
    return saveCalc(id);
  }

  // ── view switch ────────────────────────────────────────────────────────────
  // LABOR SITS RIGHT AFTER ASSEMBLIES, BEFORE ADMINISTRATION -- a peer to Items and Assemblies,
  // not a fourth Administration list and not folded into Defaults, which stays what it always
  // was: what a new bid opens holding, not what the catalog holds.
  var PANES = ["items", "asm", "labor", "labcalc", "vendors", "defaults"];
  var TAB_OF = { items: "tab-items", asm: "tab-asm", labor: "tab-labor", labcalc: "tab-labcalc",
                 vendors: "tab-vendors", defaults: "tab-defaults" };
  function showView(which) {
    view = which;
    PANES.forEach(function (p) {
      $(TAB_OF[p]).setAttribute("aria-selected", String(p === which));
      $("pane-" + p).hidden = p !== which;
    });
    // AND THE ADDRESS BAR SAYS SO. Hanz, on staging: "when I reload the page, why does it
    // automatically land on assemblies? and not on the tab that I have under items and
    // assemblies". `view` above is a module variable that dies with the page; the fragment is
    // the only part of this that a reload still has.
    //
    // WRITTEN HERE, not in the click listener, because the tab strip is not the only thing that
    // switches tabs — there are several other call sites. The Defaults tab's Edit buttons jump to
    // the material, the assembly or the labor line behind a default (`showView("labor"); paint();
    // focusLaborRow(id)`, and the item/assembly pair beside it), and creating a material, an
    // assembly, a labor line or a vendor lands you on its own tab. A reload after any of those has
    // to come back to where it put you, and a listener-only write would send you to Assemblies
    // instead.
    //
    // `typeof window` rather than a bare read: the test harnesses run these functions in scopes
    // that bind only what the page itself declares, and an unbound identifier is a ReferenceError
    // that reds every scenario at once. The script tag is what guarantees the module is there,
    // and a test asserts the tag, because no amount of executing this can see a missing <script>.
    if (typeof window !== "undefined" && window.TWTabMemo) {
      window.TWTabMemo.write(window, { tab: which });
    }
  }
  /** Show one work type's defaults: the strip's own state, and nothing else.
   *
   *  Split out of the click listener so restoreView below can reach it. It deliberately does NOT
   *  repaint the two lists — at restore time nothing has been fetched yet and there is nothing to
   *  draw, and load()'s paint() is what draws them a moment later. The listener repaints because
   *  by the time somebody can click, there is something to repaint. */
  function setWorkType(wt) {
    DEFAULT_WT = wt;
    WORK_TYPES.forEach(function (k) {
      var b = $("wt-" + k);
      if (b) b.setAttribute("aria-selected", String(k === wt));
    });
  }
  /** Open on the tab — and the work type — the URL names.
   *
   *  A REMEMBERED TAB THAT NO LONGER EXISTS FALLS BACK, which is the whole of what `pick` is for:
   *  a link carrying `#tab=rooms` from some later shape of this page has to show Assemblies, not
   *  an empty pane. The fallbacks are the page's own declared defaults, read out of `view` and
   *  `DEFAULT_WT` rather than retyped here, so this cannot disagree with them.
   *
   *  Runs before load(), and costs nothing: showView only flips `hidden` and `aria-selected`, and
   *  setWorkType only moves the strip. No pane fetches anything it was not going to fetch, which
   *  is the rule that keeps this from turning one tab's page into four tabs' worth of requests. */
  function restoreView() {
    if (typeof window === "undefined" || !window.TWTabMemo) return;
    var M = window.TWTabMemo;
    showView(M.pick(M.read(window, "tab"), PANES, view));
    setWorkType(M.pick(M.read(window, "wt"), WORK_TYPES, DEFAULT_WT));
  }
  PANES.forEach(function (p) {
    $(TAB_OF[p]).addEventListener("click", function () {
      showView(p);
      if (p === "labcalc") renderLabCalc();
    });
  });
  restoreView();

  // ── add from library: the modal ────────────────────────────────────────────
  // The DECISIONS are the four pure functions above; this is wiring, and it is kept apart from them
  // on purpose. The test harness's DOM stub cannot open a dialog, move focus or tick a checkbox, so
  // anything that lives only here is verified in a browser instead — the same split this file
  // already accepts for confirmDanger.
  var BULK = { open: false, q: "", picked: {}, shown: [], against: null,
               F: { divisions: [], vendor: "", condition: "" } };

  function bulkShow(on) {
    BULK.open = !!on;
    $("bulk-ov").hidden = !on;
    // The class the shared stylesheet fades in with. Set after `hidden` clears so the transition
    // has a frame to run in.
    if (on) $("bulk-ov").classList.add("tw-in");
    else $("bulk-ov").classList.remove("tw-in");
  }

  function bulkClose() {
    bulkShow(false);
    BULK.picked = {}; BULK.q = ""; BULK.against = null;
    BULK.F = { divisions: [], vendor: "", condition: "" };
    // Back to the control that opened it, which is where the keyboard expects to be.
    var back = $("bulk-open");
    if (back) back.focus();
  }

  function bulkOpen() {
    // A confirm dialog can stack on top of this one — `flush`'s modal gate only covers item saves,
    // and shared.js's counter cannot see an overlay it did not create. Refusing to open on top of a
    // question is cheaper than fighting over the focus trap.
    if (TW.modalOpen && TW.modalOpen()) { say("Answer the question on screen first."); return; }
    var asm = current();
    if (!asm) return;
    // HELD AS AN IDENTITY TOKEN AND NOTHING ELSE. `adoptConflict` replaces ASMS[i] wholesale on a
    // 409, so comparing identity at Add time is what catches "the assembly moved underneath you".
    // Mutating through this reference would push pre-conflict lines back and undo the very thing
    // the conflict machinery protected.
    BULK.against = asm;
    BULK.picked = {}; BULK.q = "";
    BULK.F = { divisions: [], vendor: "", condition: "" };
    $("bulk-q").value = "";
    $("bulk-sub").textContent = 'Tick what this assembly uses. Added to "' + asm.name + '".';
    bulkFilters();
    bulkPaint();
    bulkShow(true);
    $("bulk-q").focus();
  }

  /** The modal's own facet controls, built from the same offered lists the Items tab uses. */
  function bulkFilters() {
    $("bulk-divisions").innerHTML = divisionNames().map(function (d) {
      return '<label class="fchip" title="' + esc(d) + '">' +
        '<input type="checkbox" data-bdiv="' + esc(d) + '" aria-label="' + esc(d) + '">' +
        '<span class="fchip-f">' + esc(d) + "</span></label>";
    }).join("");
    $("bulk-vendor").innerHTML = '<option value="">Any vendor</option>' +
      vendorNames().map(function (v) {
        return '<option value="' + esc(v) + '">' + esc(v) + "</option>";
      }).join("");
  }

  function bulkPaint() {
    var asm = current();
    // Materials already on this assembly are shown but not tickable: hiding them would make the
    // list a puzzle about which materials went missing, and a second line for the same material is
    // a second charge for it.
    var already = {};
    ((asm && asm.lines) || []).forEach(function (ln) { if (ln.item_id) already[ln.item_id] = true; });

    // The three reserved rows are left out here too -- the same reason as itemResultsHtml, the
    // one-line picker this modal is the bulk version of.
    var list = bulkCandidates(
      ITEMS.filter(function (it) { return !isReservedItem(it && it.id); }), BULK.q, BULK.F);
    BULK.shown = list.map(function (it) { return it.id; });

    $("bulk-list").innerHTML = list.map(function (it) {
      var on = !!already[it.id];
      var divs = itemDivisions(it).join(", ") || "No division";
      var vendor = it.vendor || "No vendor";
      return '<label class="bulk-row' + (on ? " on" : "") + '">' +
        '<input type="checkbox" data-bpick="' + esc(it.id) + '"' +
          (on ? " disabled" : (BULK.picked[it.id] ? " checked" : "")) + ">" +
        '<span class="bulk-box"></span>' +
        '<span class="bulk-nm"><b>' + esc(it.name) + "</b><span>" +
          esc(divs) + " &middot; " + esc(vendor) + "</span></span>" +
        (on ? '<span class="bulk-in">On this assembly</span>'
            : '<span class="bulk-cost">' + esc(orderAmount(it)) + "</span>") +
        "</label>";
    }).join("");

    var none = !list.length;
    $("bulk-none").hidden = !none;
    if (none) {
      $("bulk-none").textContent = ITEMS.length
        ? "Nothing in the library matches that. Try fewer words, or clear a facet."
        : "The library has no materials yet. Add some on the Items tab first.";
    }

    // Tickable ids only, so "select all" cannot claim to have ticked a disabled row.
    var pickable = BULK.shown.filter(function (id) { return !already[id]; });
    var state = bulkSelectAllState(pickable, BULK.picked);
    var master = $("bulk-master");
    master.checked = state === "all";
    master.indeterminate = state === "some";
    master.disabled = !pickable.length;
    $("bulk-master-l").textContent = state === "all" && pickable.length ? "Clear all" : "Select all";

    var n = bulkPickedIds().length;
    var room = bulkAddRoom(asm, n);
    var count = $("bulk-count");
    count.classList.toggle("over", !room.fits);
    if (!room.fits) {
      // Names the number, because "too many" leaves the estimator counting rows.
      count.textContent = "Untick " + room.over + " — this assembly holds " + room.max +
                          " lines and " + room.used + " are used.";
    } else {
      count.textContent = n ? n + " selected · " + room.used + " of " + room.max + " lines used"
                            : room.used + " of " + room.max + " lines used";
    }
    var add = $("bulk-add");
    add.disabled = !n || !room.fits;
    add.textContent = n ? "Add " + n + " material" + (n === 1 ? "" : "s") : "Add";
  }

  /** The ticked ids, in the order the library holds them — so the lines land in a predictable
   *  order rather than in whatever order the boxes happened to be clicked. */
  function bulkPickedIds() {
    return ITEMS.filter(function (it) { return BULK.picked[it.id]; })
                .map(function (it) { return it.id; });
  }

  function bulkCommit() {
    var picked = bulkPickedIds();
    if (!picked.length) return;
    var asm = current();
    // THE CONFLICT CHECK. Identity, not id: a 409 handled while the picker was open replaced the
    // object, and appending to the detached one would resurrect the lines the server rejected.
    if (!asm || asm !== BULK.against) {
      bulkClose();
      say("This assembly changed while the picker was open — reopen it and pick again.");
      return;
    }
    var room = bulkAddRoom(asm, picked.length);
    if (!room.fits) { bulkPaint(); return; }         // the footer already says what to do

    asm.lines = asm.lines.concat(bulkLinesFor(picked, ITEMS));
    bulkClose();
    paint();
    // ONE PATCH for the whole batch. patchSoon debounces per record and merges by field, so this
    // replaces any pending lines snapshot with the newer one rather than racing it.
    patchSoon("assemblies", asm.id, { lines: asm.lines });
    say("");
  }

  // ── events ─────────────────────────────────────────────────────────────────
  $("area").addEventListener("input", function () { renderList(); renderPanel(); });

  // ── add-from-library listeners ─────────────────────────────────────────────
  // The stylesheet for .tw-ov lives in shared.js and is injected on demand. Called once here
  // rather than on open, so the first press does not paint an unstyled overlay for a frame.
  if (TW.injectModalCss) TW.injectModalCss();

  $("bulk-open").addEventListener("click", bulkOpen);
  $("bulk-x").addEventListener("click", bulkClose);
  $("bulk-cancel").addEventListener("click", bulkClose);
  $("bulk-add").addEventListener("click", bulkCommit);

  $("bulk-q").addEventListener("input", function () { BULK.q = this.value; bulkPaint(); });

  // THE DEFAULTS TAB SEARCH. It shipped on 2026-09-17 with nothing bound to it: DEFAULT_Q
  // was declared, read and reset, but never assigned, so the query could not become
  // non-empty, defaultCandidates() took its early return every time and the results box
  // stayed hidden forever. The tab that had just become the only way to set a default had
  // no working way to set one. Typing also leaves browse mode on, so clearing the box
  // returns you to the full list rather than to nothing.
  if ($("default-q")) {
    $("default-q").addEventListener("input", function () {
      setDefaultQuery(this.value);
    });
    $("default-q").addEventListener("keydown", onDefaultSearchKey);
  }

  // NO `change` LISTENER ON THE TAKEOFF TBODY ANY MORE. One lived here for the conditions'
  // Yes/No selects; the selects came off on 2026-09-19 (Hanz: "remove these yes and no what are
  // these for?") and a listener whose only arm read `data-cond-key` would now be reading an
  // attribute this page never renders. Both writes to condition_defaults go through the click
  // delegation instead -- Remove on a listed row, Add on a removed one -- and both land in
  // setConditionDefault, which is still the one place that writes them.

  // THE LABOR FORM'S TYPING used to bind here. It shut down with the form itself, 2026-09-24 --
  // renderDefaultLabor no longer draws a `data-labor-f` input anywhere, creating a labor line
  // moved to its own tab, and a listener kept alive over a form that no longer exists is exactly
  // the kind of dead wiring this file's own tests exist to catch.
  // Escape in the search box clears it before it closes the dialog — the same two-stage behaviour
  // the Items tab's box has, so a typo does not cost you the whole selection.
  $("bulk-q").addEventListener("keydown", function (e) {
    if (e.key === "Escape" && this.value) { e.stopPropagation(); this.value = ""; BULK.q = ""; bulkPaint(); }
  });

  $("bulk-vendor").addEventListener("change", function () {
    BULK.F.vendor = this.value; bulkPaint();
  });
  // Bound to the CONTAINER, not the chips: bulkFilters replaces that markup, and a listener on a
  // replaced element dies with it. Same rule renderFilterBar's note gives for the Items tab.
  $("bulk-divisions").addEventListener("change", function () {
    BULK.F.divisions = Array.prototype.map.call(
      this.querySelectorAll("input[data-bdiv]:checked"),
      function (el) { return el.getAttribute("data-bdiv"); });
    bulkPaint();
  });

  // ONE delegated listener for the rows, because bulkPaint replaces all of them on every keystroke.
  $("bulk-list").addEventListener("change", function (e) {
    var box = e.target && e.target.closest && e.target.closest("[data-bpick]");
    if (!box) return;
    var id = box.getAttribute("data-bpick");
    if (box.checked) BULK.picked[id] = true; else delete BULK.picked[id];
    bulkPaint();
  });

  $("bulk-master").addEventListener("change", function () {
    var asm = current();
    var already = {};
    ((asm && asm.lines) || []).forEach(function (ln) { if (ln.item_id) already[ln.item_id] = true; });
    var pickable = BULK.shown.filter(function (id) { return !already[id]; });
    // Over the SHOWN rows only. Ticking "all" while a search is narrowing the list must not reach
    // materials the estimator cannot see, and clearing must not drop ticks made before the search.
    if (this.checked) pickable.forEach(function (id) { BULK.picked[id] = true; });
    else pickable.forEach(function (id) { delete BULK.picked[id]; });
    bulkPaint();
  });

  // Escape closes, and a press on the scrim itself closes — but a press that started inside the box
  // does not, or dragging to select text in the search field would dismiss the dialog.
  $("bulk-ov").addEventListener("mousedown", function (e) {
    if (e.target === this) bulkClose();
  });
  document.addEventListener("keydown", function (e) {
    if (!BULK.open) return;
    if (e.key === "Escape") { e.preventDefault(); bulkClose(); return; }
    if (e.key !== "Tab") return;
    // FOCUS STAYS IN THE DIALOG. Without this, Tab walks into the page behind — which is both a
    // keyboard trap in reverse and a way to edit the assembly under an open picker.
    var ov = $("bulk-ov");
    var f = ov.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])');
    var real = Array.prototype.filter.call(f, function (el) {
      return el.offsetParent !== null || el.type === "checkbox";   // the visually-hidden boxes count
    });
    if (!real.length) return;
    var first = real[0], last = real[real.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  $("asm-name").addEventListener("input", function () {
    var a = current(); if (!a) return;
    a.name = this.value;
    renderList();
    patchSoon("assemblies", a.id, { name: a.name });
  });

  // SF or LF for the whole assembly. `change` and not `input`: a select fires both, and there is no
  // half-typed state to catch up with the way there is in the name field.
  //
  // renderPanel repaints so the three labels follow immediately, and renderList so the rail's
  // "$1.497/SF" becomes "/LF" in the same tick. Nothing recalculates — priceAssembly divides by the
  // one area input whatever the unit says — so this is a relabel that happens to be persisted.
  $("asm-unit").addEventListener("change", function () {
    var a = current(); if (!a) return;
    a.unit = this.value === "LF" ? "LF" : "SF";
    renderPanel();
    renderList();
    patchSoon("assemblies", a.id, { unit: a.unit });
  });

  // Item edits reprice every assembly live. That IS the reason items and assemblies are
  // separate records, so it should not need a reload to show.
  //
  // NUMERIC FIELDS MUST BE LISTED. `buy_qty` reaching the model as the string "5" would make
  // `5 / "5"` work by luck and `"5" * 2` produce "55" the first time somebody multiplied instead
  // of divided — the pricing layer's `num()` is defensive, but the model it reads should not be
  // the thing needing defending.
  var NUMERIC_ITEM_FIELDS = ["unit_cost", "coverage", "buy_qty", "waste_pct"];
  function onItemEdit(e) {
    // NOTHING GETS IN WHILE A CONFIRMATION IS ON SCREEN. The modal overlay traps every real
    // keystroke and click, so the only event that can arrive here in that window is one the dialog
    // provoked itself: focusing anything blurs whatever the estimator was typing in, and a blurred
    // input with an uncommitted value fires `change` — which is bound to this handler. That
    // re-entry is how a cancelled edit used to reach the database. See the block comment above
    // ITEM_FIELD_LABELS for the full sequence.
    //
    // AND IT CANNOT LOSE AN EDIT, because `input` fires first and has already put the value in the
    // model and the queue: the `change` this discards is the same value a second time. The one
    // theoretical exception is a <select> in a DIFFERENT row being committed in the instant a
    // deferred dialog goes up, in a browser that reports `change` without `input` — narrow enough
    // to name here rather than to complicate this guard for.
    if (itemConfirmOpen) return;
    var f = e.target.getAttribute && e.target.getAttribute("data-f");
    if (!f) return;
    var row = e.target.closest("[data-item]");
    if (!row) return;
    var it = itemOf(row.getAttribute("data-item"));
    if (!it) return;
    // BEFORE the model is touched, and before the divisions branch below returns early — this is
    // what Cancel puts back and what the dialog quotes. No-op after the first keystroke of a
    // round, so a row typed into for ten seconds still remembers where it started.
    rememberItem(it);
    // Where the caret was, so a Cancel can put it back. Overwritten on every edit: the field they
    // were last in is the one they will want to correct.
    itemLastField[it.id] = f;
    if (f === "divisions") {
      var vals = Array.from(row.querySelectorAll('input[data-f="divisions"]:checked'))
        .map(function (x) { return x.getAttribute("data-div"); })
        .filter(Boolean);
      it.divisions = vals;
      it.category = vals[0] || "";
      renderList(); renderPanel();
      patchSoon("items", it.id, { divisions: vals });
      return;
    }
    // A checkbox, not a text field: `.value` on an unchecked box is still "on", so the generic
    // raw-string path below would send a truthy string every time. `.checked` is the only real
    // answer, and it is already the boolean the server wants -- nothing to parse on either end.
    if (f === "roundup") {
      it.roundup = !!e.target.checked;
      renderList(); renderPanel();
      patchSoon("items", it.id, { roundup: it.roundup });
      return;
    }
    var raw = e.target.value;
    it[f] = NUMERIC_ITEM_FIELDS.indexOf(f) !== -1 ? L.num(raw) : raw;
    if (f === "name") {
      // Redrawn in place: rebuilding the row would move the caret out of the name being typed.
      var cell = e.target.parentNode;
      var hint = cell.querySelector(".dupe");
      var names = similarNames(raw, it.id);
      if (hint) hint.remove();
      if (names.length) cell.insertAdjacentHTML("beforeend", dupeHtml(names));
    }
    renderList(); renderPanel();
    var body = {}; body[f] = raw;
    patchSoon("items", it.id, body);
  }
  // Both events: a text input reports `input`, and a <select> is only guaranteed to report
  // `change`. The handler is idempotent and the PATCH is debounced, so a browser firing both
  // costs one write either way.
  // The search box lives OUTSIDE #items-body, so it needs its own listener — and it must not go
  // through onItemEdit, which would look for a data-f attribute, find none, and return anyway.
  // Re-rendering on every keystroke is safe here in a way it is not inside the table: the query
  // input is not one of the rows being replaced, so it keeps its focus and its caret.
  if ($("item-q")) {
    $("item-q").addEventListener("input", function (e) {
      itemQuery = e.target.value;
      renderItems();
      // Only the Clear button's visibility depends on the text, and it lives outside the tbody,
      // so this is a two-property sync rather than a rebuild. renderFilterBar guards its own
      // markup write, so calling it per keystroke cannot cost the caret.
      renderFilterBar();
    });
    // CLEARABLE WITHOUT A MOUSE. type="search" gets a native clear affordance in Chromium but it
    // is a mouse target, and Escape is not wired to it consistently across browsers. This is one
    // line and it is the same key that closes the item picker two tables over, so the page
    // answers Escape the same way twice.
    $("item-q").addEventListener("keydown", function (e) {
      if (e.key !== "Escape" || !String(itemQuery).trim()) return;
      e.preventDefault();
      itemQuery = "";
      e.target.value = "";
      renderItems();
      renderFilterBar();
    });
  }

  // ── the facets ────────────────────────────────────────────────────────────
  // Bound to the CONTAINERS, which are never re-rendered by renderItems, rather than to the
  // controls, which renderFilterBar can replace when an admin adds a division. A listener on a
  // replaced element goes with it, silently, and the facet stops working with nothing on screen
  // to show for it.
  if ($("f-divisions")) {
    $("f-divisions").addEventListener("change", function (e) {
      if (!e.target.getAttribute || !e.target.getAttribute("data-fdiv")) return;
      // Read back off the DOM rather than pushing and splicing, so the model cannot drift from
      // the boxes: whatever is ticked IS the filter.
      FILTERS.divisions = Array.prototype.slice
        .call(this.querySelectorAll("input[data-fdiv]:checked"))
        .map(function (x) { return x.getAttribute("data-fdiv"); })
        .filter(Boolean);
      renderItems();
      renderFilterBar();
    });
  }
  if ($("f-vendor")) {
    $("f-vendor").addEventListener("change", function (e) {
      FILTERS.vendor = e.target.value;
      renderItems();
      renderFilterBar();
    });
  }
  if ($("f-condition")) {
    $("f-condition").addEventListener("change", function (e) {
      FILTERS.condition = e.target.value;
      renderItems();
      renderFilterBar();
    });
  }

  /** Put the tab back to showing everything.
   *
   *  Reachable from two places on purpose: the bar, where somebody who can see the controls looks
   *  for it, and the empty state, where somebody staring at no rows looks for it. Both carry
   *  data-clear-filters so one handler serves them and neither can drift.
   *
   *  The chips are unticked in the DOM as well as in FILTERS. renderFilterBar only rewrites that
   *  markup when the offered list changes, which this is not, so clearing the model alone would
   *  leave three ticked chips over an unfiltered table. */
  function clearFilters() {
    itemQuery = "";
    FILTERS.divisions = [];
    FILTERS.vendor = "";
    FILTERS.condition = "";
    if ($("item-q")) $("item-q").value = "";
    var boxes = $("f-divisions") ? $("f-divisions").querySelectorAll("input[data-fdiv]") : [];
    for (var i = 0; i < boxes.length; i++) boxes[i].checked = false;
    renderItems();
    renderFilterBar();
    // Focus goes to the search box, which is where the next thing they type belongs, and it means
    // clearing from the empty state does not leave focus on a button that just vanished.
    if ($("item-q")) $("item-q").focus();
  }

  // ── the same three controls for the Assemblies tab ────────────────────────
  // Only renderList() here, not renderPanel(): narrowing the rail must not close the assembly
  // somebody is editing. openId is read off the unfiltered ASMS and renderList never writes it,
  // so an open assembly that the filter excludes keeps its panel and simply loses its highlight.
  //
  // renderList calls renderAsmFilterBar itself, which is why none of these do.
  if ($("asm-q")) {
    $("asm-q").addEventListener("input", function (e) {
      asmQuery = e.target.value;
      renderList();
    });
    // Same key the item box answers, two tables over.
    $("asm-q").addEventListener("keydown", function (e) {
      if (e.key !== "Escape" || !String(asmQuery).trim()) return;
      e.preventDefault();
      asmQuery = "";
      e.target.value = "";
      renderList();
    });
  }
  // Bound to the selects themselves and not a container, unlike the item facets: all three are
  // static markup that renderAsmFilterBar only ever assigns `.value` on, so there is no element
  // here that can be replaced out from under a listener.
  if ($("fa-unit")) {
    $("fa-unit").addEventListener("change", function (e) {
      ASM_FILTERS.unit = e.target.value;
      renderList();
    });
  }
  if ($("fa-condition")) {
    $("fa-condition").addEventListener("change", function (e) {
      ASM_FILTERS.condition = e.target.value;
      renderList();
    });
  }
  // The sort, wired the same way and for the same reason: static markup, so nothing can be
  // replaced out from under this listener.
  //
  // renderList() ONLY, and nothing else. Not clearAsmFilters (which resets the box and the two
  // facets, and then puts the caret in the search box) and no focus call of its own: an estimator
  // who has tabbed Unit → Condition → Sort and picked a key is still in the Sort control, and
  // both of those would yank them out of it mid-keyboard-pass. renderList repaints the rail
  // underneath and touches no focus at all.
  if ($("fa-sort")) {
    $("fa-sort").addEventListener("change", function (e) {
      ASM_SORT = e.target.value;
      renderList();
    });
  }

  /** The Assemblies tab's own clear, on its own attribute.
   *
   *  data-clear-asm-filters rather than reusing data-clear-filters, which is deliberately one
   *  route for the Items tab's two buttons: sharing it would have the assemblies button silently
   *  reset the item table instead, on a tab where the estimator cannot see it happen. */
  function clearAsmFilters() {
    asmQuery = "";
    ASM_FILTERS.unit = "";
    ASM_FILTERS.condition = "";
    // ASM_SORT IS DELIBERATELY NOT RESET HERE, and this is the line to read before "fixing" it.
    // Clear filters undoes the NARROWING — it exists so somebody looking at an empty rail can get
    // all of it back in one press. A sort hides nothing, so there is nothing to get back, and
    // reshuffling the list as a side effect of a button labelled Clear filters would be the least
    // predictable thing on this tab. The Sort select is a control the estimator can put back
    // themselves, in the one place they set it.
    if ($("asm-q")) $("asm-q").value = "";
    // The two facet selects are put back by renderAsmFilterBar, which renderList calls; unlike the
    // item chips there is no markup here that survives a model change.
    renderList();
    if ($("asm-q")) $("asm-q").focus();
  }

  $("items-body").addEventListener("input", onItemEdit);
  $("items-body").addEventListener("change", onItemEdit);
  // …and the event that actually triggers the save. `focusout` and not `blur`, because blur does
  // not bubble and this is one listener on a tbody whose rows are replaced on every render.
  $("items-body").addEventListener("focusout", onItemRowFocusOut);
  // LEAVING WITH UNSAVED CHANGES (Hanz, B3b): flush when the tab goes hidden or the page is
  // hidden/closed, and warn on close only if a save is still unconfirmed after that.
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") flushAllPending();
  });
  window.addEventListener("pagehide", flushAllPending);
  window.addEventListener("beforeunload", function (e) {
    if (!savePending()) return;
    e.preventDefault();
    e.returnValue = "";
    return "";
  });

  // Both events, for the reason the comment above already gives: a text input reports `input`,
  // a <select> and a checkbox are only guaranteed to report `change`. No focusout listener --
  // there is no confirmation dialog on this table for one to schedule around.
  $("labor-body").addEventListener("input", onLaborEdit);
  $("labor-body").addEventListener("change", onLaborEdit);

  // ── administration ────────────────────────────────────────────────────────
  // Writes are admin-only on the server too (`_require_admin`). The read-only render is what keeps
  // a non-admin from being offered a control that would 403 — not the only line of defence.
  function onRefEdit(e) {
    var f = e.target.getAttribute && e.target.getAttribute("data-rf");
    if (!f) return;
    var row = e.target.closest("[data-ref-kind]");
    if (!row) return;
    var kind = row.getAttribute("data-ref-kind");
    var id = row.getAttribute("data-ref-id");
    var list = adminList(kind);
    var v = null;
    for (var i = 0; i < list.length; i++) if (list[i].id === id) v = list[i];
    if (!v) return;
    v[f] = e.target.value;
    // A rename changes what the Items tab offers, but NOT what an item already says. Existing
    // values stay put and render as off-list choices until someone changes that item.
    if (f === "name") {
      if (kind === "divisions") DIVISIONS = DIVISION_REFS.map(function (d) { return d.name; });
      if (kind === "units") UNITS = UNIT_REFS.map(function (u) { return u.name; });
      renderItems();
    }
    patchSoon(kind, id, (function () { var b = {}; b[f] = e.target.value; return b; })());
  }
  ["divisions-body", "units-body", "vendors-body"].forEach(function (id) {
    $(id).addEventListener("input", onRefEdit);
  });

  function lineOf(target) {
    var asm = current(), row = target.closest && target.closest("[data-line]");
    if (!asm || !row) return null;
    var ln = asm.lines[Number(row.getAttribute("data-line"))];
    return ln ? { asm: asm, ln: ln } : null;
  }

  $("lines-body").addEventListener("input", function (e) {
    var f = e.target.getAttribute("data-lf");
    // Picker filters are temporary UI state; item selection itself happens by stable item id.
    if (!f || f === "roundup") return;
    var ctx = lineOf(e.target);
    if (!ctx) return;
    if (f === "item_search") {
      ctx.ln._item_search = e.target.value;
      // Repaint the RESULTS ONLY. renderPanel() rebuilds `lines-body`, which destroys the very
      // input being typed into and takes the caret with it — the same reason refreshNumbers()
      // exists below, and a bug class this project has shipped twice.
      repaintItemResults(e.target);
      return;
    }
    ctx.ln[f] = (f === "coverage" || f === "waste_pct") ? L.num(e.target.value) : e.target.value;
    renderList();
    // Only the totals need redrawing, and re-rendering the table would move the caret out of
    // the field being typed in. So the numbers are refreshed without rebuilding the rows.
    refreshNumbers();
    patchSoon("assemblies", ctx.asm.id, { lines: ctx.asm.lines });
  });

  $("lines-body").addEventListener("change", function (e) {
    var f = e.target.getAttribute("data-lf");
    if (f !== "roundup") return;
    var ctx = lineOf(e.target);
    if (!ctx) return;
    ctx.ln.roundup = !!e.target.checked;
    // Rebuilding is safe here: a checkbox has no caret to lose, and the quantity cell changes
    // shape entirely — "3 × 5 Gallon" becomes "13.09 Gallon".
    renderList(); refreshNumbers();
    patchSoon("assemblies", ctx.asm.id, { lines: ctx.asm.lines });
  });

  /** Redraw one picker's floating results beside the input the estimator is typing in.
   *
   *  Finds the list relative to the input rather than rebuilding the table, so the element with
   *  focus is never replaced. */
  function repaintItemResults(input) {
    var ctx = lineOf(input);
    if (!ctx) return;
    var picker = input.parentNode;
    if (!picker) return;
    var list = picker.querySelector(".item-results");
    if (!list) {
      list = document.createElement("div");
      list.className = "item-results";
      picker.appendChild(list);
    }
    list.innerHTML = itemResultsHtml(ctx.ln);
  }

  /** Open a line's picker for searching, without disturbing what is already chosen.
   *
   *  The typed query starts EMPTY rather than pre-filled with the item's name: somebody opening
   *  this wants a different product, and pre-filling means deleting thirty characters before they
   *  can type three. */
  $("lines-body").addEventListener("focusin", function (e) {
    if (e.target.getAttribute("data-lf") !== "item_search") return;
    var ctx = lineOf(e.target);
    if (!ctx) return;
    var idx = ctx.asm.lines.indexOf(ctx.ln);
    if (pickerOpen === idx) return;
    pickerOpen = idx;
    ctx.ln._item_search = "";
    e.target.value = "";
    repaintItemResults(e.target);
  });

  // Escape closes the list and puts the chosen item's name back, so the box never lies about what
  // the line is priced from.
  $("lines-body").addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || e.target.getAttribute("data-lf") !== "item_search") return;
    closeItemPicker();
  });

  function closeItemPicker() {
    if (pickerOpen === null) return;
    var asm = current();
    var ln = asm && asm.lines ? asm.lines[pickerOpen] : null;
    if (ln) delete ln._item_search;
    pickerOpen = null;
    renderPanel();
  }

  // Clicking anywhere else closes it. Without this the list stays open over the rows below and the
  // table reads as though that line were still being edited.
  document.addEventListener("mousedown", function (e) {
    if (pickerOpen === null) return;
    if (e.target.closest && e.target.closest(".item-picker")) return;
    closeItemPicker();
  });

  /** Redraw the computed cells and totals WITHOUT rebuilding the inputs.
   *
   *  Rebuilding the rows while somebody is typing in one of them moves the caret to the end of
   *  the field, which makes editing a coverage backwards feel broken. */
  function refreshNumbers() {
    var asm = current();
    if (!asm) return;
    var area = $("area").value;
    var p = L.priceAssembly(asm, ITEMS, area);
    var rows = $("lines-body").querySelectorAll("[data-line]");
    // BY POSITION, so these two indexes are load-bearing: Items · Order Amount · Coverage ·
    // Waste · Roundup? · Quantity · Cost · delete. Adding a column ahead of them without moving these writes the
    // quantity into the waste box.
    var QTY_TD = 5, COST_TD = 6;
    for (var i = 0; i < rows.length; i++) {
      var r = p.rows[i];
      if (!r) continue;
      var tds = rows[i].querySelectorAll("td");
      if (tds.length <= COST_TD) continue;
      // The pricing core tells them apart now (reason "no_item" vs "missing_item"), so this no
      // longer re-derives it from the line. One source of truth: renderPanel, renderList and the
      // Polish page all read the same distinction.
      var neverPicked = r.reason === "no_item";
      if (r.ok && r.priced) {
        tds[QTY_TD].innerHTML = '<div class="line-primary"><span class="qty">' + esc(L.qtyLabel(r)) +
                           '</span></div><div class="calc mono">' + esc(L.explain(r, area)) + "</div>";
        tds[COST_TD].innerHTML = '<div class="line-primary"><span class="qty">' + L.money(r.cost) +
                           '</span></div><div class="calc mono">' + esc(L.costWorking(r)) + "</div>";
        rows[i].classList.remove("broken");
      } else {
        tds[QTY_TD].innerHTML = r.ok
          ? '<span class="dash">—</span>'
          : '<span class="' + (neverPicked ? "unpicked" : "gone") + '">'
            + (neverPicked ? "Pick a material"
              : r.reason === "missing_item" ? "Item removed"
              : r.reason === "no_coverage" ? "Needs a coverage" : "Needs a cost") + "</span>";
        tds[COST_TD].innerHTML = "—";
        if (tds[QTY_TD].innerHTML.indexOf("line-primary") === -1) {
          tds[QTY_TD].innerHTML = '<div class="line-primary">' + tds[QTY_TD].innerHTML + "</div>";
        }
        if (tds[COST_TD].innerHTML.indexOf("line-primary") === -1) {
          tds[COST_TD].innerHTML = '<div class="line-primary">' + tds[COST_TD].innerHTML + "</div>";
        }
        rows[i].classList.toggle("broken", !r.ok && !neverPicked);
      }
    }
    $("t-total").textContent = p.priced_lines > 0 ? L.money(p.total) : "—";
    $("t-unit").textContent = p.per_unit == null ? "—" : L.perUnit(p.per_unit);
  }

  document.addEventListener("click", async function (e) {
    var t = e.target;

    // Both the bar's button and the empty state's, one handler.
    if (t.closest && t.closest("[data-clear-filters]")) { clearFilters(); return; }
    if (t.closest && t.closest("[data-clear-asm-filters]")) { clearAsmFilters(); return; }

    var open = t.closest && t.closest("[data-open]");
    if (open) { openId = open.getAttribute("data-open"); paint(); return; }

    var pickItem = t.closest && t.closest("[data-pick-item]");
    if (pickItem) {
      var ctxPick = lineOf(pickItem);
      var picked = itemOf(pickItem.getAttribute("data-pick-item"));
      if (!ctxPick || !picked) return;
      ctxPick.ln.item_id = picked.id;
      // Picking answers the question, so the list closes and the box goes back to showing the
      // chosen item. Leaving it open over the rows below reads as "still editing this line".
      delete ctxPick.ln._item_search;
      pickerOpen = null;
      if (!(Number(ctxPick.ln.coverage) > 0)) ctxPick.ln.coverage = picked.coverage;
      say("");
      paint();
      patchSoon("assemblies", ctxPick.asm.id, { lines: ctxPick.asm.lines });
      return;
    }

    if (t.closest && t.closest("[data-add-item]")) {
      try {
        var j = await post("items",
          { name: newMaterialName("New material"), unit: "Gallon", buy_qty: 1 });
        // Unshift, not push+sort: the add control moved to the TOP of the list (Hanz,
        // 2026-08-28) precisely so pressing it and seeing the result stay the same spot on
        // screen — sorting it back into alphabetical order would undo that.
        ITEMS.unshift(j.item);
        FRESH.items[j.item.id] = "new";
        showView("items"); paint();
        var f = $("items-body").querySelector('[data-item="' + j.item.id + '"] input[data-f="name"]');
        if (f) { f.focus(); f.select(); }
      } catch (err) { say("Couldn't add that material. " + err.message); }
      return;
    }

    // THROUGH closest(), NOT off the clicked element. These controls hold an inline SVG now, so
    // a press can land on the <svg> or one of its <path>s — none of which carry the attribute.
    // Reading it off e.target would make the button dead over most of its own area. The
    // pointer-events rule on `.icon svg` also prevents it; this is the half that survives
    // somebody tidying the stylesheet.
    // ── the Defaults tab owns defaults now ────────────────────────────────────────────────────
    // The switch came off the item rows and the assembly editor on 2026-09-17, at Hanz's ask:
    // "all the default items in assemblies should be handled in default items in assemblies tab".
    // These three are what replaced it, and they had to land in the same change -- a tab that
    // lists defaults but cannot set them would have left no way to set one at all.
    // THE ADD BUTTON UNDER EACH LIST. It shipped as markup with no handler on 2026-09-17,
    // and the search box shipped with no input listener, so between them there was NO WAY
    // LEFT to make a default -- the same change had just taken the switch off the item rows.
    // BOTH OPEN THE SAME BROWSE NOW, 2026-09-24. Creating a labor TYPE moved to its own Labor
    // tab; this pair only ever makes an EXISTING type (or material, or assembly) a default, which
    // is what the shared search-and-browse below already does for the other two kinds.
    // THE WORK-TYPE STRIP. It narrows both lists at once, because a work type is the one
    // question "what does a polish bid open holding?" and Takeoff and Labor are two halves
    // of that answer. Repainting both is the point, not an accident.
    var wtBtn = t.closest && t.closest("[data-work-type]");
    if (wtBtn) {
      var wt = wtBtn.getAttribute("data-work-type");
      if (WORK_TYPES.indexOf(wt) !== -1) {
        setWorkType(wt);
        // REMEMBERED BESIDE THE TAB, not instead of it. Landing on Defaults and showing the wrong
        // one of the five work types is the same reload bug one level down, so the fragment
        // carries both: `#tab=defaults&wt=epoxy`.
        if (typeof window !== "undefined" && window.TWTabMemo) {
          window.TWTabMemo.write(window, { wt: wt });
        }
        renderDefaultTakeoff();
        renderDefaultLabor();
        renderDefaultSearch();
      }
      return;
    }
    if (t.closest && t.closest("[data-def-search-close]")) { closeDefaultSearch(); return; }
    var addDef = t.closest && t.closest("[data-add-default]");
    if (addDef) {
      openDefaultAdd(addDef.getAttribute("data-add-default"));
      return;
    }
    // ITS OWN ARM, not a Remove or a Delete. The three say different things and send different
    // requests -- a DELETE here would soft-delete the only row anything can address Travel by,
    // and setDefault's Remove would try to un-favorite a row that is not gated by favorite at all.
    if (t.closest && t.closest("[data-labor-reset]")) { await resetTravelDefault(); return; }

    // ── the Labor tab: every labor line, created and edited here ─────────────────────────────
    if (t.closest && t.closest("[data-add-labor]")) { await addLaborLine(); return; }
    var moreBtn = t.closest && t.closest("[data-labor-more-toggle]");
    if (moreBtn) { toggleLaborMore(moreBtn.getAttribute("data-labor-more-toggle")); return; }
    var delLab = t.closest && t.closest("[data-del-labor]");
    if (delLab) { await removeLaborLine(delLab.getAttribute("data-del-labor")); return; }
    var addBtn = t.closest && t.closest("[data-def-add]");
    if (addBtn) {
      // TWO SAVERS, ONE BUTTON, because a condition's answer is not a library row's `favorite`:
      // an OFF joint filler, remove-existing or dye row carries a "conditions" Add
      // (conditionDefaultRow), and pressing it writes condition_defaults. Routing here rather than
      // teaching setDefault a third store keeps each saver owning one table -- removeDefault is
      // the same split for the Remove button.
      var addKind = addBtn.getAttribute("data-def-add");
      if (addKind === "conditions") {
        await setConditionDefault(addBtn.getAttribute("data-def-id"), true);
      } else {
        await setDefault(addKind, addBtn.getAttribute("data-def-id"), true);
      }
      // ONLY A SEARCH HIT IS SPENT. The Add on an off condition row sits in the table, not in the
      // results box, and pressing it must leave whatever the admin had typed there alone.
      if (addBtn.classList && addBtn.classList.contains("defhit")) {
        DEFAULT_Q = "";                    // the row has moved to the list; the hit is spent
        var qbox = $("default-q");
        if (qbox) qbox.value = "";
        renderDefaultSearch();
      }
      return;
    }
    // THE WORK-TYPE CHIPS, FIRST of the row controls: they sit in the same row as the Edit and
    // Remove pair and `closest` walks up, so a selector that could also match must not run
    // before this one. Reads aria-pressed rather than a data flag -- the attribute the button
    // already has to carry for a screen reader is the same fact, and two copies of one state is
    // how a control ends up disagreeing with itself.
    var wtBtn = t.closest && t.closest("[data-wt-toggle]");
    if (wtBtn) {
      await setRowWorkType(wtBtn.getAttribute("data-wt-toggle"), wtBtn.getAttribute("data-wt-id"),
                        wtBtn.getAttribute("data-wt"),
                        wtBtn.getAttribute("aria-pressed") !== "true");
      return;
    }
    // ONE REMOVE FOR EVERY ROW, conditions included since 2026-10-01 -- joint filler,
    // remove-existing and dye carry the material's own button now. removeDefault decides which
    // store the press writes (see its note); there is no second attribute to route.
    // THE STARTING-STATE SLIDER, before Edit/Remove: it sits in the same row and `closest` walks up.
    var onSw = t.closest && t.closest("[data-def-on]");
    if (onSw) {
      var swOn = !(onSw.getAttribute("aria-checked") === "true");
      await setDefaultOn(onSw.getAttribute("data-def-on"), onSw.getAttribute("data-def-on-id"), swOn);
      return;
    }
    var offBtn = t.closest && t.closest("[data-def-off]");
    if (offBtn) {
      await removeDefault(offBtn.getAttribute("data-def-off"), offBtn.getAttribute("data-def-id"));
      return;
    }
    // EDIT GOES TO THE ROW, not to an editor here. What you want to change about a default is the
    // assembly, the material or the labor line, and this page already has screens for all three.
    var edBtn = t.closest && t.closest("[data-def-edit]");
    if (edBtn) {
      var ek = edBtn.getAttribute("data-def-edit");
      var eid = edBtn.getAttribute("data-def-id");
      if (ek === "assemblies") { openId = eid; showView("asm"); paint(); }
      else if (ek === "labor") { showView("labor"); paint(); focusLaborRow(eid); }
      else { showView("items"); paint(); focusItemRow(eid); }
      return;
    }

    var saveBtn = t.closest && t.closest("[data-save-new]");
    if (saveBtn) {
      var sk = saveBtn.getAttribute("data-save-new"), sid = saveBtn.getAttribute("data-save-id");
      var still = await saveNow(sk, sid);
      if (!still && saveBtn.parentNode) saveBtn.parentNode.removeChild(saveBtn);
      return;
    }

    var dupBtn = t.closest && t.closest("[data-dupe-item]");
    var dup = dupBtn && dupBtn.getAttribute("data-dupe-item");
    if (dup) {
      var src = itemOf(dup);
      if (!src) return;
      try {
        // Every priced field comes across. A copy that dropped the cost or the pack size would be
        // a row that looks finished and prices at nothing, which is the failure this button is
        // meant to save people from by hand-typing.
        var copy = await post("items", {
          name: duplicateName(src.name),
          unit: src.unit || "",
          buy_qty: src.buy_qty,
          unit_cost: src.unit_cost,
          vendor: src.vendor || "",
          divisions: itemDivisions(src),
        });
        // Same reasoning as the Add button above: land at the top, don't re-sort it away.
        ITEMS.unshift(copy.item);
        showView("items"); paint();
        // Focused and selected, like the Add button does: the name is the one field a copy always
        // needs changing, and "(2)" is a placeholder rather than an answer.
        var nf = $("items-body").querySelector('[data-item="' + copy.item.id + '"] input[data-f="name"]');
        if (nf) { nf.focus(); nf.select(); }
      } catch (err) { say("Couldn't copy that material. " + err.message); }
      return;
    }

    var delBtn = t.closest && t.closest("[data-del-item]");
    var di = delBtn && delBtn.getAttribute("data-del-item");
    if (di) {
      var it = itemOf(di);
      var used = ASMS.filter(function (a) {
        return (a.lines || []).some(function (l) { return l.item_id === di; });
      }).length;
      // `name` + before/after, not `message`: shared.js emphasises the name and there is no
      // `body` option — passing one would have rendered an empty line.
      var ok = await TW.confirmDanger({
        title: "Remove this material?",
        name: it ? it.name : "This material",
        after: " will be taken out of the library.",
        // Naming the consequence rather than blocking the delete: the assemblies keep working,
        // they just show a line that needs repointing.
        detail: used
          ? used + " assembl" + (used === 1 ? "y uses" : "ies use") +
            " it. Their lines will show \"Item removed\" until you pick a replacement."
          : "No assemblies are using it.",
        confirmText: "Remove material",
      });
      if (!ok) return;
      try {
        await del("items", di);
        // Before the model loses the row, so a queued edit cannot fire a PATCH at a dead id.
        forgetItem(di);
        ITEMS = ITEMS.filter(function (x) { return x.id !== di; });
        paint();
      } catch (err) { say("Couldn't remove that material. " + err.message); }
      return;
    }

    // asm-new-top is gone: the create control that used to sit in the page header now lives at
    // the TOP OF THE ASSEMBLY RAIL, which is the list it appends to. Same card either way — see
    // the .addrow note in library.html for why the August objection is not being reversed here.
    var newAsm = t.closest && t.closest("#asm-new, #asm-new-2");
    if (newAsm) {
      try {
        var a = await post("assemblies", { name: "New assembly", unit: "SF" });
        // THE FRONT, not the end. Hanz, 2026-09-04: "when a new assembly is added it should
        // append up top not below." The button is the rail's first row now, so the row it produces
        // appears directly under the control that produced it. Through placeNewAssembly rather
        // than an inline unshift because nothing in this listener is reachable from the harness.
        //
        // SAY PLAINLY HOW LONG THIS LASTS, because it is not permanent and that is not a bug.
        // list_assemblies() on the server does `.order("name")`, so on the next page load "New
        // assembly" comes back under N and the rail is name A–Z again. That is why the default
        // sort is a pass-through of the server's order rather than a client-side name sort (which
        // would undo this on the very next render — see sortAssemblies): the front placement is
        // for THIS SESSION, for the minute between creating a system and naming it. The estimator
        // who wants new work at the top permanently picks "Newest first" in the Sort control,
        // which orders on created_at and survives a reload.
        //
        // It is on screen either way: openId is set to it and its name field is focused and
        // selected two lines down, ready to be typed over.
        placeNewAssembly(ASMS, a.assembly);
        FRESH.assemblies[a.assembly.id] = "new";
        openId = a.assembly.id;
        showView("asm"); paint();
        $("asm-name").focus(); $("asm-name").select();
      } catch (err) { say("Couldn't create that assembly. " + err.message); }
      return;
    }

    if (t.closest && t.closest("#add-line")) {
      var asm = current();
      if (!asm) return;
      // BLANK, not pre-filled with ITEMS[0]. That was whichever material sorts first
      // alphabetically, carried in with its coverage — a real material, on a line nobody chose,
      // pricing real money if it was left there. Hanz, 2026-08-25: the line should start empty.
      asm.lines.push({ role: "", item_id: "", coverage: null,
                       // 5% and rounding up are the defaults he asked for, set HERE as well as
                       // read-shaped server-side so the row shows the numbers it will save with.
                       waste_pct: 5, roundup: true, note: "" });
      // NOT SAVED YET, and that is the second half of the answer. `_clean_lines` on the server
      // DROPS a line with no item_id, so a PATCH here would report success and the line would be
      // gone on the next load, with nothing to explain it. The line becomes data on the first
      // pick, which is also the moment it becomes worth saving.
      pickerOpen = asm.lines.length - 1;
      paint();
      return;
    }

    var addRefBtn = t.closest && t.closest("[data-add-ref]");
    var addRef = addRefBtn && addRefBtn.getAttribute("data-add-ref");
    if (addRef) {
      try {
        var one = singular(addRef);
        var made = await post(addRef, { name: newRefName(addRef) });
        var row = made[one];
        adminList(addRef).push(row);
        adminList(addRef).sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); });
        if (addRef === "divisions") DIVISIONS = DIVISION_REFS.map(function (d) { return d.name; });
        if (addRef === "units") UNITS = UNIT_REFS.map(function (u) { return u.name; });
        showView("vendors"); paint();
        var rf = $(addRef + "-body")
          .querySelector('[data-ref-id="' + row.id + '"] input[data-rf="name"]');
        if (rf) { rf.focus(); rf.select(); }
      } catch (err) {
        say("Couldn't add that value. " + err.message);
      }
      return;
    }

    var delRefBtn = t.closest && t.closest("[data-del-ref]");
    var delRef = delRefBtn && delRefBtn.getAttribute("data-del-ref");
    if (delRef) {
      var rid = delRefBtn.getAttribute("data-ref-id");
      var listRef = adminList(delRef);
      var refRow = null;
      for (var ri = 0; ri < listRef.length; ri++) if (listRef[ri].id === rid) refRow = listRef[ri];
      var usedRef = usageFor(delRef, (refRow || {}).name);
      var oneRef = singular(delRef);
      var okRef = await TW.confirmDanger({
        title: "Remove this " + oneRef + "?",
        name: refRow ? refRow.name : "This value",
        after: " will stop being offered on items.",
        detail: usedRef
          ? usedRef + " item" + (usedRef === 1 ? "" : "s") + " still use" +
            (usedRef === 1 ? "s" : "") + " it and will keep doing so until manually changed."
          : "No items use it.",
        confirmText: "Remove " + oneRef,
      });
      if (!okRef) return;
      try {
        await del(delRef, rid);
        if (delRef === "divisions") {
          DIVISION_REFS = DIVISION_REFS.filter(function (x) { return x.id !== rid; });
          DIVISIONS = DIVISION_REFS.map(function (d) { return d.name; });
        } else if (delRef === "units") {
          UNIT_REFS = UNIT_REFS.filter(function (x) { return x.id !== rid; });
          UNITS = UNIT_REFS.map(function (u) { return u.name; });
        } else {
          VENDORS = VENDORS.filter(function (x) { return x.id !== rid; });
        }
        paint();
      } catch (err) { say("Couldn't remove that value. " + err.message); }
      return;
    }

    if (t.id === "vendor-add" || t.id === "vendor-add-first") {
      try {
        var nv = await post("vendors", { name: newRefName("vendors") });
        VENDORS.push(nv.vendor);
        VENDORS.sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); });
        showView("vendors"); paint();
        var vf = $("vendors-body")
          .querySelector('[data-vendor="' + nv.vendor.id + '"] input[data-vf="name"]');
        if (vf) { vf.focus(); vf.select(); }
      } catch (err) {
        // The likely failure is the duplicate-name refusal, which is the table doing its job —
        // so the message is the server's, not a generic one.
        say("Couldn't add that vendor. " + err.message);
      }
      return;
    }

    var delVenBtn = t.closest && t.closest("[data-del-vendor]");
    var dv = delVenBtn && delVenBtn.getAttribute("data-del-vendor");
    if (dv) {
      var ven = null;
      for (var vi = 0; vi < VENDORS.length; vi++) if (VENDORS[vi].id === dv) ven = VENDORS[vi];
      var usedBy = VENDOR_USE[String((ven || {}).name || "").toLowerCase()] || 0;
      var okv = await TW.confirmDanger({
        title: "Remove this vendor?",
        name: ven ? ven.name : "This vendor",
        after: " will stop being offered on materials.",
        detail: usedBy
          ? usedBy + " material" + (usedBy === 1 ? "" : "s") + " still name" +
            (usedBy === 1 ? "s" : "") + " it, and will keep doing so — an item records where it " +
            "was actually bought."
          : "No materials name it.",
        confirmText: "Remove vendor",
      });
      if (!okv) return;
      try {
        await del("vendors", dv);
        VENDORS = VENDORS.filter(function (x) { return x.id !== dv; });
        paint();
      } catch (err) { say("Couldn't remove that vendor. " + err.message); }
      return;
    }

    if (t.closest && t.closest("#asm-save")) {
      var sa = current();
      if (!sa) return;
      var stillA = await saveNow("assemblies", sa.id);
      $("asm-save").hidden = !stillA;
      return;
    }

    if (t.closest && t.closest("#asm-del")) {
      var cur = current();
      if (!cur) return;
      var yes = await TW.confirmDanger({
        title: "Delete this assembly?",
        name: cur.name,
        after: " will be removed from the library.",
        detail: "The materials it uses are not affected.",
        confirmText: "Delete assembly",
      });
      if (!yes) return;
      try {
        await del("assemblies", cur.id);
        ASMS = ASMS.filter(function (x) { return x.id !== cur.id; });
        openId = ASMS.length ? ASMS[0].id : null;
        paint();
      } catch (err) { say("Couldn't delete that assembly. " + err.message); }
      return;
    }

    var delLineBtn = t.closest && t.closest("[data-del-line]");
    if (delLineBtn) {
      var owner = current();
      if (!owner) return;
      owner.lines.splice(Number(delLineBtn.getAttribute("data-del-line")), 1);
      paint();
      patchSoon("assemblies", owner.id, { lines: owner.lines });
    }
  });

  // The Labor Calculator's rate boxes, and its jumps. Delegated on the pane because the body is
  // redrawn from state.
  $("pane-labcalc").addEventListener("change", function (e) {
    var el = e.target;
    if (el && el.getAttribute && el.getAttribute("data-travel-rate") !== null) saveTravelRate(el);
    else if (el && el.getAttribute && (el.getAttribute("data-lcalc-mode") !== null ||
                                       el.getAttribute("data-lcalc") !== null)) calcEdit(el);
  });
  $("pane-labcalc").addEventListener("input", function (e) {
    var el = e.target;
    if (el && el.getAttribute && el.getAttribute("data-tryit-sf") !== null) {
      CALC_TRY_SF = el.value;
      renderTryIt();
    }
  });
  $("pane-labcalc").addEventListener("click", function (e) {
    var t = e.target;
    if (t && t.closest && t.closest("[data-labcalc-goto-labor]")) {
      showView("labor"); paint(); focusLaborRow("travel");
    }
  });
  // The Defaults tab's pointer ("Travel is set in Labor Calculator").
  var goLabCalc = document.querySelector("[data-goto-labcalc]");
  if (goLabCalc) goLabCalc.addEventListener("click", function (e) {
    e.preventDefault();
    showView("labcalc");
    renderLabCalc();
  });

  load().then(function () { if (view === "labcalc") renderLabCalc(); });
})();
