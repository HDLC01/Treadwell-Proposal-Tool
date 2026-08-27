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
    return '<svg class="ic" viewBox="0 0 24 24" width="16" height="16" fill="none" ' +
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
      : ITEMS;
    for (var i = 0; i < (list || []).length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  // Take the server's version stamp after our own successful write, so the next keystroke does
  // not conflict with the change we just made.
  function adoptSaved(kind, fresh) {
    var known = byId(kind, fresh.id);
    if (!known) return;
    known.updated_at = fresh.updated_at;
    // …and the price date, which only the SERVER can decide: it moves when the cost actually
    // changed, not when a PATCH was sent. Without adopting it the row goes on saying "not since we
    // started tracking" until a reload — the stamp Hanz asked for, looking like it doesn't work.
    if (kind === "items" && fresh.cost_updated_at !== known.cost_updated_at) {
      known.cost_updated_at = fresh.cost_updated_at;
      paintDates(known);
    }
  }

  /** Rewrite one row's Dates cell in place.
   *
   *  In place, not renderItems(): the debounce fires 600ms after the last keystroke, so the reply
   *  routinely lands while somebody is still in the field. Rebuilding the row would move their
   *  caret to the end of it. The Dates cell holds no inputs, so replacing it is safe. */
  function paintDates(it) {
    var cell = document.querySelector('[data-item="' + it.id + '"] .datescell');
    if (cell) cell.innerHTML = datesHtml(it);
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
    coverage: "Coverage per unit", vendor: "Vendor", divisions: "Division",
  };

  // THE SERVER'S FIELDS, NOT OURS. `updated_at` moves on every write and `cost_updated_at` moves
  // only when the cost really changed — both are decided server-side and adopted off the reply
  // (see adoptSaved). A snapshot taken before that reply landed holds the old values, so
  // restoring the WHOLE snapshot on a Cancel would throw away what the server just told us: the
  // Dates cell would go back to quoting a price date the database has already moved past, with
  // nothing on screen marking it. Cancel restores what the estimator typed, and nothing else.
  var SERVER_OWNED_ITEM_FIELDS = ["updated_at", "cost_updated_at"];

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
    if (kind === "items" && !(await confirmItemPatch(id, payload))) return;
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
        return;
      }
      // Adopt the new version stamp, or the NEXT save conflicts with our own write.
      var saved = await r.json().catch(function () { return {}; });
      var fresh = saved.assembly || saved.item || saved.vendor || saved.division || saved.unit;
      if (fresh && fresh.id) adoptSaved(kind, fresh);
      say(""); saving("Saved");
      setTimeout(function () { saving(""); }, 1200);
    } catch (err) {
      say("Couldn't reach the server. " + (err.message || ""));
      saving("Not saved");
    }
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

  /** When it was added, and when the price last moved. Two dates rather than one, because the
   *  second is the question people actually ask — "how old is this number?" — and `updated_at`
   *  answers a different one, since fixing a spelling would make a stale price look fresh. */
  function datesHtml(it) {
    var made = it.created_at ? TW.fmtBizDateTime(it.created_at) : "—";
    var priced = it.cost_updated_at
      ? esc(TW.fmtBizDateTime(it.cost_updated_at))
      : '<span class="never">not since we started tracking</span>';
    return '<div class="dates"><div>Added <b>' + esc(made) + "</b></div>" +
           "<div>Price " + priced + "</div></div>";
  }

  /** The library's own comparison form of a name: case, spacing and punctuation all ignored.
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
        '<td class="n"><span class="money"><span>$</span><input data-f="unit_cost" class="num cell-cost" value="' + (it.unit_cost == null ? "" : it.unit_cost) + '" aria-label="Cost of one purchase"></span></td>' +
        "<td>" + pick("vendor", it.vendor, vendorNames(), "Vendor", ' class="cell-vendor"') + "</td>" +
        '<td class="datescell">' + datesHtml(it) + "</td>" +
        '<td class="rowact"><button class="icon" type="button" data-dupe-item="' + esc(it.id) + '" title="Make a copy of this material" aria-label="Duplicate ' + esc(it.name) + '">' + icon("copy") + "</button>" +
          '<button class="icon danger" type="button" data-del-item="' + esc(it.id) + '" title="Remove this material" aria-label="Remove ' + esc(it.name) + '">' + icon("trash") + "</button></td>" +
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
    for (var i = 0; i < ASMS.length; i++) {
      var a = ASMS[i], p = L.priceAssembly(a, ITEMS, area);
      var per = p.per_unit == null ? "not priced" : L.perUnit(p.per_unit) + "/" + esc(a.unit);
      out += '<button class="arow" type="button" data-open="' + esc(a.id) + '"' +
        (a.id === openId ? ' aria-current="true"' : "") + ">" +
        '<span class="an">' + esc(a.name) + "</span>" +
        '<span class="am">' + a.lines.length + " line" + (a.lines.length === 1 ? "" : "s") +
        " · " + per + (p.broken_lines ? " · " + p.broken_lines + " to fix" : "") +
        "</span></button>";
    }
    $("asm-list").innerHTML = out;
    // THE CARD, not the list inside it. "+ New assembly" is the rail's last row now — Hanz asked
    // for it out of the page header, and the list it appends to is the only honest home for it —
    // so hiding just the inner list would leave a create button alone in an empty box while the
    // "No assemblies yet" panel offered a second one beside it.
    $("asm-rail").hidden = ASMS.length === 0;
    $("n-asm").textContent = ASMS.length;
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
    if (c === "no_cost") return !(Number(it.unit_cost) > 0);
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
   *  SEEDS COVERAGE FROM THE ITEM, which is the whole reason this is a function with a test rather
   *  than three lines inside a click handler. `priceLine` reports a line with no coverage as
   *  `no_coverage`, and that reason IS counted in `broken_lines` — so a twelve-material add without
   *  this seed arrives with twelve amber rows reading "Needs a coverage", and the estimator would
   *  reasonably conclude the feature is broken. The single-pick path has always done it; this
   *  matches it deliberately rather than by coincidence.
   *
   *  An item whose own coverage is unset still lands, and still reads "Needs a coverage" — that is
   *  an honest report about the material, not a fault in the add. */
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
      return itemMatches(candidate, query);
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
        '<td class="n cov"><div class="line-primary"><input data-lf="coverage" class="num" value="' +
          (ln.coverage == null ? "" : ln.coverage) + '" aria-label="Coverage per unit"></div></td>' +
        '<td class="n"><div class="line-primary"><input data-lf="waste_pct" class="num waste" value="' +
          (ln.waste_pct == null ? "" : ln.waste_pct) + '" aria-label="Waste factor, percent"> %</div></td>' +
        '<td class="ru"><div class="line-primary"><input type="checkbox" data-lf="roundup"' +
          (ln.roundup === false ? "" : " checked") +
          ' aria-label="Round up to whole purchases"></div></td>' +
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
  }

  // ── view switch ────────────────────────────────────────────────────────────
  var PANES = ["items", "asm", "vendors"];
  var TAB_OF = { items: "tab-items", asm: "tab-asm", vendors: "tab-vendors" };
  function showView(which) {
    view = which;
    PANES.forEach(function (p) {
      $(TAB_OF[p]).setAttribute("aria-selected", String(p === which));
      $("pane-" + p).hidden = p !== which;
    });
  }
  PANES.forEach(function (p) {
    $(TAB_OF[p]).addEventListener("click", function () { showView(p); });
  });

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

    var list = bulkCandidates(ITEMS, BULK.q, BULK.F);
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
  var NUMERIC_ITEM_FIELDS = ["unit_cost", "coverage", "buy_qty"];
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

  $("items-body").addEventListener("input", onItemEdit);
  $("items-body").addEventListener("change", onItemEdit);
  // …and the event that actually triggers the save. `focusout` and not `blur`, because blur does
  // not bubble and this is one listener on a tbody whose rows are replaced on every render.
  $("items-body").addEventListener("focusout", onItemRowFocusOut);

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
    // the foot of the assembly rail, which is the list it appends to.
    var newAsm = t.closest && t.closest("#asm-new, #asm-new-2");
    if (newAsm) {
      try {
        var a = await post("assemblies", { name: "New assembly", unit: "SF" });
        ASMS.push(a.assembly);
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

  load();
})();
