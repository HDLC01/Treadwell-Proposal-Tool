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

  function patchSoon(kind, id, body) {
    var key = kind + ":" + id;
    if (body && Array.isArray(body.lines)) {
      body = Object.assign({}, body, { lines: body.lines.map(lineForSave) });
    }
    pendingPatch[key] = Object.assign(pendingPatch[key] || {}, body);
    if (timers[key]) clearTimeout(timers[key]);
    timers[key] = setTimeout(async function () {
      var payload = pendingPatch[key];
      delete pendingPatch[key];
      // Nothing to send is not an error — a conflict repaint empties the buffer, and this used to
      // throw on the missing payload BEFORE the try block, which turned a dropped write into an
      // unhandled rejection and a silent screen. Belt to adoptConflict's braces.
      if (!payload) return;
      // Declare the version being edited. A line change rewrites the WHOLE lines array, so
      // without this two people with the same assembly open overwrite each other in silence:
      // the second save replaces the first person's lines with a snapshot taken before they
      // existed, and neither screen shows anything wrong.
      if (kind === "assemblies") {
        var known = byId(kind, id);
        if (known && known.updated_at) payload.expected_updated_at = known.updated_at;
      }
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
    }, 600);
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

  function renderItems() {
    var out = "";
    for (var i = 0; i < ITEMS.length; i++) {
      var it = ITEMS[i];
      out += '<tr data-item="' + esc(it.id) + '">' +
        '<td><input data-f="name" value="' + esc(it.name) + '" aria-label="Material name, as the manufacturer names it" maxlength="200" list="dl-materials" style="width:100%;min-width:150px;">' +
          dupeHtml(similarNames(it.name, it.id)) + "</td>" +
        "<td>" + divisionPick(it) + "</td>" +
        '<td class="n"><input data-f="buy_qty" class="num" value="' + (it.buy_qty == null ? "" : it.buy_qty) + '" aria-label="How many units come in one purchase" style="width:64px;"></td>' +
        "<td>" + pick("unit", it.unit, unitNames(), "Unit", ' style="width:100%;min-width:96px;"') + "</td>" +
        '<td class="n"><span class="money"><span>$</span><input data-f="unit_cost" class="num" value="' + (it.unit_cost == null ? "" : it.unit_cost) + '" aria-label="Cost of one purchase" style="width:92px;"></span></td>' +
        "<td>" + pick("vendor", it.vendor, vendorNames(), "Vendor",
                      ' style="width:100%;min-width:130px;"') + "</td>" +
        '<td class="datescell">' + datesHtml(it) + "</td>" +
        '<td><button class="icon" type="button" data-del-item="' + esc(it.id) + '" title="Remove this material" aria-label="Remove ' + esc(it.name) + '">🗑</button></td>' +
      "</tr>";
    }
    $("items-body").innerHTML = out;
    $("items-empty").hidden = ITEMS.length > 0;
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
          ? '<input data-rf="name" value="' + esc(v.name) + '" aria-label="' + one + ' name" maxlength="200" style="width:100%;min-width:170px;">'
          : "<b>" + esc(v.name) + "</b>") + "</td>" +
        "<td>" + (ADMIN
          ? '<input data-rf="notes" value="' + esc(v.notes) + '" aria-label="Notes" maxlength="4000" style="width:100%;min-width:190px;">'
          : esc(v.notes)) + "</td>" +
        '<td class="n">' + used + "</td>" +
        "<td>" + (ADMIN
          ? '<button class="icon" type="button" data-del-ref="' + kind + '" data-ref-id="' + esc(v.id) + '" title="Remove this ' + one + '" aria-label="Remove ' + esc(v.name) + '">🗑</button>'
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
    $("asm-list").hidden = ASMS.length === 0;
    $("asm-newrow").hidden = ASMS.length === 0;
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
  function itemMatches(it, query) {
    var words = String(query || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return true;
    var hay = [String(it.name || ""), itemDivisions(it).join(" "), String(it.vendor || "")]
      .join(" ").toLowerCase();
    for (var i = 0; i < words.length; i++) {
      if (hay.indexOf(words[i]) === -1) return false;
    }
    return true;
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
        qtyCell = '<span style="color:var(--ink-v)">—</span>';       // no area typed yet
        costCell = '<span style="color:var(--ink-v)">—</span>';
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
      out += '<tr data-line="' + i + '"' + (r.ok ? "" : ' class="broken"') + ">" +
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
        '<td class="n">' + qtyCell + "</td>" +
        '<td class="n">' + costCell + "</td>" +
        '<td><button class="icon" type="button" data-del-line="' + i + '" title="Remove this line" aria-label="Remove line">🗑</button></td>' +
      "</tr>";
    }
    if (!asm.lines.length) {
      out = '<tr><td colspan="8" style="color:var(--ink-v);padding:22px;text-align:center;">' +
            "No lines yet. Add one and search for an item.</td></tr>";
    }
    $("lines-body").innerHTML = out;

    var priced = p.priced_lines > 0;
    $("t-total").textContent = priced ? L.money(p.total) : "—";
    $("t-unit").textContent = p.per_unit == null ? "—" : L.perUnit(p.per_unit);
  }

  function paint() { renderItems(); renderVendors(); renderList(); renderPanel(); }

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

  // ── events ─────────────────────────────────────────────────────────────────
  $("area").addEventListener("input", function () { renderList(); renderPanel(); });

  $("asm-name").addEventListener("input", function () {
    var a = current(); if (!a) return;
    a.name = this.value;
    renderList();
    patchSoon("assemblies", a.id, { name: a.name });
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
    var f = e.target.getAttribute && e.target.getAttribute("data-f");
    if (!f) return;
    var row = e.target.closest("[data-item]");
    if (!row) return;
    var it = itemOf(row.getAttribute("data-item"));
    if (!it) return;
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
  $("items-body").addEventListener("input", onItemEdit);
  $("items-body").addEventListener("change", onItemEdit);

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
      if (r.ok && r.priced) {
        tds[QTY_TD].innerHTML = '<div class="line-primary"><span class="qty">' + esc(L.qtyLabel(r)) +
                           '</span></div><div class="calc mono">' + esc(L.explain(r, area)) + "</div>";
        tds[COST_TD].innerHTML = '<div class="line-primary"><span class="qty">' + L.money(r.cost) +
                           '</span></div><div class="calc mono">' + esc(L.costWorking(r)) + "</div>";
        rows[i].classList.remove("broken");
      } else {
        tds[QTY_TD].innerHTML = r.ok
          ? '<span style="color:var(--ink-v)">—</span>'
          : '<span class="gone">' + (r.reason === "missing_item" ? "Item removed"
              : r.reason === "no_coverage" ? "Needs a coverage" : "Needs a cost") + "</span>";
        tds[COST_TD].innerHTML = "—";
        if (tds[QTY_TD].innerHTML.indexOf("line-primary") === -1) {
          tds[QTY_TD].innerHTML = '<div class="line-primary">' + tds[QTY_TD].innerHTML + "</div>";
        }
        if (tds[COST_TD].innerHTML.indexOf("line-primary") === -1) {
          tds[COST_TD].innerHTML = '<div class="line-primary">' + tds[COST_TD].innerHTML + "</div>";
        }
        rows[i].classList.toggle("broken", !r.ok);
      }
    }
    $("t-total").textContent = p.priced_lines > 0 ? L.money(p.total) : "—";
    $("t-unit").textContent = p.per_unit == null ? "—" : L.perUnit(p.per_unit);
  }

  document.addEventListener("click", async function (e) {
    var t = e.target;

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
        var j = await post("items", { name: "New material", unit: "Gallon", buy_qty: 1 });
        ITEMS.push(j.item);
        ITEMS.sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); });
        showView("items"); paint();
        var f = $("items-body").querySelector('[data-item="' + j.item.id + '"] input[data-f="name"]');
        if (f) { f.focus(); f.select(); }
      } catch (err) { say("Couldn't add that material. " + err.message); }
      return;
    }

    var di = t.getAttribute && t.getAttribute("data-del-item");
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
        ITEMS = ITEMS.filter(function (x) { return x.id !== di; });
        paint();
      } catch (err) { say("Couldn't remove that material. " + err.message); }
      return;
    }

    if (t.id === "asm-new" || t.id === "asm-new-2") {
      try {
        var a = await post("assemblies", { name: "New assembly", unit: "SF" });
        ASMS.push(a.assembly);
        openId = a.assembly.id;
        showView("asm"); paint();
        $("asm-name").focus(); $("asm-name").select();
      } catch (err) { say("Couldn't create that assembly. " + err.message); }
      return;
    }

    if (t.id === "add-line") {
      var asm = current();
      if (!asm) return;
      var first = ITEMS[0];
      // 5% and rounding up are the defaults Hanz asked for, and they are set HERE as well as
      // read-shaped server-side, so the row shows the same numbers it will be saved with.
      asm.lines.push({ role: "", item_id: first ? first.id : "",
                       coverage: first ? first.coverage : null,
                       waste_pct: 5, roundup: true, note: "" });
      paint();
      patchSoon("assemblies", asm.id, { lines: asm.lines });
      return;
    }

    var addRef = t.getAttribute && t.getAttribute("data-add-ref");
    if (addRef) {
      try {
        var one = singular(addRef);
        var made = await post(addRef, { name: "New " + one });
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

    var delRef = t.getAttribute && t.getAttribute("data-del-ref");
    if (delRef) {
      var rid = t.getAttribute("data-ref-id");
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
        var nv = await post("vendors", { name: "New vendor" });
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

    var dv = t.getAttribute && t.getAttribute("data-del-vendor");
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

    if (t.id === "asm-del") {
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

    if (t.hasAttribute && t.hasAttribute("data-del-line")) {
      var owner = current();
      if (!owner) return;
      owner.lines.splice(Number(t.getAttribute("data-del-line")), 1);
      paint();
      patchSoon("assemblies", owner.id, { lines: owner.lines });
    }
  });

  load();
})();
