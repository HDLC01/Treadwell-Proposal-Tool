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
  var VENDOR_USE = {};             // casefolded vendor name → how many materials name it
  var ADMIN = false;               // may change the VENDOR LIST; everyone may pick from it
  var openId = null;
  var view = "asm";

  // Offered by the dropdowns, not enforced by the server: a legacy row holds whatever somebody
  // typed, and refusing to save it would make those rows uneditable. An off-list value is rendered
  // as its own option so it stays visible and correctable.
  var DIVISIONS = ["Polished Concrete", "Epoxy", "Gypsum Underlayment"];
  var UNITS = ["Gallon", "Kit", "Bag"];

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
                                 api("/api/library/vendors")]);
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
    var list = (kind === "assemblies") ? ASMS : (kind === "vendors") ? VENDORS : ITEMS;
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

  function patchSoon(kind, id, body) {
    var key = kind + ":" + id;
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
        var fresh = saved.assembly || saved.item || saved.vendor;
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
        "<td>" + pick("category", it.category, DIVISIONS, "Division",
                      ' style="width:100%;min-width:150px;"') + "</td>" +
        '<td class="n"><input data-f="buy_qty" class="num" value="' + (it.buy_qty == null ? "" : it.buy_qty) + '" aria-label="How many units come in one purchase" style="width:64px;"></td>' +
        "<td>" + pick("unit", it.unit, UNITS, "Unit", ' style="width:100%;min-width:96px;"') + "</td>" +
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

  // ── vendors ────────────────────────────────────────────────────────────────
  function renderVendors() {
    var out = "";
    for (var i = 0; i < VENDORS.length; i++) {
      var v = VENDORS[i];
      var used = VENDOR_USE[String(v.name || "").toLowerCase()] || 0;
      out += '<tr data-vendor="' + esc(v.id) + '">' +
        "<td>" + (ADMIN
          ? '<input data-vf="name" value="' + esc(v.name) + '" aria-label="Vendor name" maxlength="200" style="width:100%;min-width:170px;">'
          : "<b>" + esc(v.name) + "</b>") + "</td>" +
        "<td>" + (ADMIN
          ? '<input data-vf="notes" value="' + esc(v.notes) + '" aria-label="Notes" maxlength="4000" style="width:100%;min-width:190px;">'
          : esc(v.notes)) + "</td>" +
        '<td class="n">' + used + "</td>" +
        "<td>" + (ADMIN
          ? '<button class="icon" type="button" data-del-vendor="' + esc(v.id) + '" title="Remove this vendor" aria-label="Remove ' + esc(v.name) + '">🗑</button>'
          : "") + "</td>" +
      "</tr>";
    }
    $("vendors-body").innerHTML = out;
    $("vendors-empty").hidden = VENDORS.length > 0;
    $("n-vendors").textContent = VENDORS.length;
    $("vendors-ro").hidden = ADMIN;
    $("vendor-addrow").hidden = !ADMIN;
    $("vendor-add-first").hidden = !ADMIN;
    if (!VENDORS.length && !ADMIN) {
      // An empty table with an Add button they cannot use would read as a broken page.
      $("vendors-empty-h").textContent = "No vendors yet";
      $("vendors-empty-why").textContent =
        "An admin adds the suppliers here, and they become a dropdown on every material.";
    }
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

  /** The material picker: a search box with autofill, not a dropdown.
   *
   *  Hanz asked for "a search bar and auto fill" because the list is going to get long, and a
   *  <select> can only be searched by typing its first letters. A `list=` input searches anywhere
   *  in the name, which is how somebody who remembers "glaze" finds "Ultra Glaze #4".
   *
   *  It stores the NAME in the field and resolves to an id on change (see itemByName), so what is
   *  on screen is what a person would say out loud. */
  function pickerFor(itemId) {
    var it = itemOf(itemId);
    return '<input data-lf="item_name" list="dl-materials" value="' + esc(it ? it.name : "") +
      '" placeholder="Search materials…" aria-label="Material" ' +
      'style="width:100%;min-width:170px;">';
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
      $("asm-empty-h").textContent = bare ? "Add some materials first" : "No assemblies yet";
      $("asm-empty-why").textContent = bare
        ? "An assembly is built out of your materials, so there is nothing to pick from yet. Add a few on the Items tab."
        : "Build a system out of your materials — a primer, a body coat, a top coat — and see what it costs per square foot.";
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
        qtyCell = '<span class="qty">' + esc(L.qtyLabel(r)) + '</span><div class="calc mono">' +
                  esc(L.explain(r, area)) + "</div>";
        costCell = '<span class="qty">' + L.money(r.cost) + '</span><div class="calc mono">' +
                   esc(L.costWorking(r)) + "</div>";
      } else if (r.ok) {
        qtyCell = '<span style="color:var(--ink-v)">—</span>';       // no area typed yet
        costCell = '<span style="color:var(--ink-v)">—</span>';
      } else if (r.reason === "missing_item") {
        qtyCell = '<span class="gone">Material removed</span>';
        costCell = "—";
      } else if (r.reason === "no_coverage") {
        qtyCell = '<span class="gone">Needs a coverage</span>';
        costCell = "—";
      } else {
        qtyCell = '<span class="gone">Needs a cost</span>';
        costCell = "—";
      }
      out += '<tr data-line="' + i + '"' + (r.ok ? "" : ' class="broken"') + ">" +
        "<td>" + pickerFor(ln.item_id) +
          (!r.ok && r.reason === "missing_item"
            ? '<div class="gone">Pick a replacement — this line is not priced</div>' : "") + "</td>" +
        '<td class="n cov"><input data-lf="coverage" class="num" value="' +
          (ln.coverage == null ? "" : ln.coverage) + '" aria-label="Coverage per unit"></td>' +
        '<td class="n"><input data-lf="waste_pct" class="num waste" value="' +
          (ln.waste_pct == null ? "" : ln.waste_pct) + '" aria-label="Waste factor, percent"> %</td>' +
        '<td class="ru"><input type="checkbox" data-lf="roundup"' +
          (ln.roundup === false ? "" : " checked") +
          ' aria-label="Round up to whole purchases"></td>' +
        '<td class="n">' + qtyCell + "</td>" +
        '<td class="n">' + costCell + "</td>" +
        '<td><button class="icon" type="button" data-del-line="' + i + '" title="Remove this line" aria-label="Remove line">🗑</button></td>' +
      "</tr>";
    }
    if (!asm.lines.length) {
      out = '<tr><td colspan="7" style="color:var(--ink-v);padding:22px;text-align:center;">' +
            "No lines yet. Add one and search for a material.</td></tr>";
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

  // ── vendors ────────────────────────────────────────────────────────────────
  // Writes are admin-only on the server too (`_require_admin`). The read-only render is what keeps
  // a non-admin from being offered a control that would 403 — not the only line of defence.
  function onVendorEdit(e) {
    var f = e.target.getAttribute && e.target.getAttribute("data-vf");
    if (!f) return;
    var row = e.target.closest("[data-vendor]");
    if (!row) return;
    var id = row.getAttribute("data-vendor");
    var v = null;
    for (var i = 0; i < VENDORS.length; i++) if (VENDORS[i].id === id) v = VENDORS[i];
    if (!v) return;
    v[f] = e.target.value;
    // A rename changes what the Items tab offers, but NOT what an item already says: items store
    // the name, on purpose. So the dropdowns are redrawn and existing values stay put — an off-list
    // value renders as its own option.
    if (f === "name") renderItems();
    patchSoon("vendors", id, (function () { var b = {}; b[f] = e.target.value; return b; })());
  }
  $("vendors-body").addEventListener("input", onVendorEdit);

  function lineOf(target) {
    var asm = current(), row = target.closest && target.closest("[data-line]");
    if (!asm || !row) return null;
    var ln = asm.lines[Number(row.getAttribute("data-line"))];
    return ln ? { asm: asm, ln: ln } : null;
  }

  $("lines-body").addEventListener("input", function (e) {
    var f = e.target.getAttribute("data-lf");
    // item_name resolves on `change` (a half-typed name is not a material), and the checkbox
    // reports through `change` as well.
    if (!f || f === "item_name" || f === "roundup") return;
    var ctx = lineOf(e.target);
    if (!ctx) return;
    ctx.ln[f] = (f === "coverage" || f === "waste_pct") ? L.num(e.target.value) : e.target.value;
    renderList();
    // Only the totals need redrawing, and re-rendering the table would move the caret out of
    // the field being typed in. So the numbers are refreshed without rebuilding the rows.
    refreshNumbers();
    patchSoon("assemblies", ctx.asm.id, { lines: ctx.asm.lines });
  });

  $("lines-body").addEventListener("change", function (e) {
    var f = e.target.getAttribute("data-lf");
    if (f !== "item_name" && f !== "roundup") return;
    var ctx = lineOf(e.target);
    if (!ctx) return;

    if (f === "roundup") {
      ctx.ln.roundup = !!e.target.checked;
      // Rebuilding is safe here: a checkbox has no caret to lose, and the quantity cell changes
      // shape entirely — "3 × 5 Gallon" becomes "13.09 Gallon".
      renderList(); refreshNumbers();
      patchSoon("assemblies", ctx.asm.id, { lines: ctx.asm.lines });
      return;
    }

    var typed = e.target.value;
    var it = itemByName(typed);
    if (!it) {
      // Left as typed rather than cleared, and said out loud. Silently blanking somebody's search
      // because it didn't match yet is how a line loses its material.
      say(typed ? "No material called “" + typed + "”. Add it on the Items tab first." : "");
      if (!typed) { ctx.ln.item_id = ""; paint();
                    patchSoon("assemblies", ctx.asm.id, { lines: ctx.asm.lines }); }
      return;
    }
    say("");
    ctx.ln.item_id = it.id;
    // Coverage follows the material just picked, unless one was already set by hand.
    if (!(Number(ctx.ln.coverage) > 0)) ctx.ln.coverage = it.coverage;
    paint();
    patchSoon("assemblies", ctx.asm.id, { lines: ctx.asm.lines });
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
    // BY POSITION, so these two indexes are load-bearing: Material · Coverage · Waste · Roundup?
    // · Quantity · Cost · delete. Adding a column ahead of them without moving these writes the
    // quantity into the waste box.
    var QTY_TD = 4, COST_TD = 5;
    for (var i = 0; i < rows.length; i++) {
      var r = p.rows[i];
      if (!r) continue;
      var tds = rows[i].querySelectorAll("td");
      if (tds.length <= COST_TD) continue;
      if (r.ok && r.priced) {
        tds[QTY_TD].innerHTML = '<span class="qty">' + esc(L.qtyLabel(r)) +
                           '</span><div class="calc mono">' + esc(L.explain(r, area)) + "</div>";
        tds[COST_TD].innerHTML = '<span class="qty">' + L.money(r.cost) +
                           '</span><div class="calc mono">' + esc(L.costWorking(r)) + "</div>";
        rows[i].classList.remove("broken");
      } else {
        tds[QTY_TD].innerHTML = r.ok
          ? '<span style="color:var(--ink-v)">—</span>'
          : '<span class="gone">' + (r.reason === "missing_item" ? "Material removed"
              : r.reason === "no_coverage" ? "Needs a coverage" : "Needs a cost") + "</span>";
        tds[COST_TD].innerHTML = "—";
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
            " it. Their lines will show “Material removed” until you pick a replacement."
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
