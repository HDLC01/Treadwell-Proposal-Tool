// Item Library page — materials, and the assemblies built out of them.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
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
  var openId = null;
  var view = "asm";

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
    try {
      var rs = await Promise.all([api("/api/library/items"), api("/api/library/assemblies")]);
      if (!rs[0].ok || !rs[1].ok) throw new Error("HTTP " + rs[0].status + "/" + rs[1].status);
      var items = await rs[0].json(), asms = await rs[1].json();
      ITEMS = items.items || [];
      ASMS = asms.assemblies || [];
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
  function patchSoon(kind, id, body) {
    var key = kind + ":" + id;
    pendingPatch[key] = Object.assign(pendingPatch[key] || {}, body);
    if (timers[key]) clearTimeout(timers[key]);
    timers[key] = setTimeout(async function () {
      var payload = pendingPatch[key];
      delete pendingPatch[key];
      saving("Saving…");
      try {
        var r = await api("/api/library/" + kind + "/" + encodeURIComponent(id),
          { method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload) });
        if (!r.ok) {
          var j = await r.json().catch(function () { return {}; });
          // Deliberately does NOT revert the field. Overwriting what somebody just typed while
          // they are looking at it loses their work and hides the reason.
          say(j.detail || j.error || "That change didn't save.");
          saving("Not saved");
          return;
        }
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
  function renderItems() {
    var out = "";
    for (var i = 0; i < ITEMS.length; i++) {
      var it = ITEMS[i];
      out += '<tr data-item="' + esc(it.id) + '">' +
        '<td><input data-f="name" value="' + esc(it.name) + '" aria-label="Material name" maxlength="200" style="width:100%;min-width:130px;"></td>' +
        '<td><input data-f="category" value="' + esc(it.category) + '" aria-label="Category" maxlength="200" style="width:100%;min-width:110px;"></td>' +
        '<td><input data-f="unit" value="' + esc(it.unit) + '" aria-label="Purchase unit" maxlength="24" style="width:70px;"></td>' +
        '<td class="n"><input data-f="unit_cost" class="num" value="' + (it.unit_cost == null ? "" : it.unit_cost) + '" aria-label="Cost per unit" style="width:96px;"></td>' +
        '<td class="n"><input data-f="coverage" class="num" value="' + (it.coverage == null ? "" : it.coverage) + '" aria-label="Coverage in square feet per unit" style="width:82px;"></td>' +
        '<td><input data-f="vendor" value="' + esc(it.vendor) + '" aria-label="Vendor" maxlength="200" style="width:100%;min-width:120px;"></td>' +
        '<td><button class="icon" type="button" data-del-item="' + esc(it.id) + '" title="Remove this material" aria-label="Remove ' + esc(it.name) + '">🗑</button></td>' +
      "</tr>";
    }
    $("items-body").innerHTML = out;
    $("items-empty").hidden = ITEMS.length > 0;
    $("n-items").textContent = ITEMS.length;
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

  function optionsFor(selected) {
    var s = '<option value=""' + (selected ? "" : " selected") + ">Pick a material…</option>";
    for (var i = 0; i < ITEMS.length; i++) {
      s += '<option value="' + esc(ITEMS[i].id) + '"' +
           (ITEMS[i].id === selected ? " selected" : "") + ">" +
           esc(ITEMS[i].name) + " (" + esc(ITEMS[i].unit) + ")</option>";
    }
    return s;
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
        qtyCell = '<span class="qty">' + r.qty.toLocaleString("en-US") + " " +
                  esc(r.item.unit) + '</span><div class="calc mono">' +
                  esc(L.explain(r, area)) + "</div>";
        costCell = '<span class="qty">' + L.money(r.cost) + '</span><div class="calc mono">' +
                   r.qty.toLocaleString("en-US") + " × " + L.money(r.unit_cost) + "</div>";
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
      var known = !!itemOf(ln.item_id);
      out += '<tr data-line="' + i + '"' + (r.ok ? "" : ' class="broken"') + ">" +
        '<td class="role"><input data-lf="role" value="' + esc(ln.role) + '" aria-label="Role" maxlength="80"></td>' +
        '<td><select data-lf="item_id" aria-label="Material">' + optionsFor(known ? ln.item_id : "") + "</select>" +
          (!r.ok && r.reason === "missing_item"
            ? '<div class="gone">Pick a replacement — this line is not priced</div>' : "") + "</td>" +
        '<td class="n cov"><input data-lf="coverage" class="num" value="' +
          (ln.coverage == null ? "" : ln.coverage) + '" aria-label="Coverage"></td>' +
        '<td class="n">' + qtyCell + "</td>" +
        '<td class="n">' + costCell + "</td>" +
        '<td><button class="icon" type="button" data-del-line="' + i + '" title="Remove this line" aria-label="Remove line">🗑</button></td>' +
      "</tr>";
    }
    if (!asm.lines.length) {
      out = '<tr><td colspan="6" style="color:var(--ink-v);padding:22px;text-align:center;">' +
            "No lines yet. Add one and pick a material.</td></tr>";
    }
    $("lines-body").innerHTML = out;

    var priced = p.priced_lines > 0;
    $("t-total").textContent = priced ? L.money(p.total) : "—";
    $("t-unit").textContent = p.per_unit == null ? "—" : L.perUnit(p.per_unit);
  }

  function paint() { renderItems(); renderList(); renderPanel(); }

  // ── view switch ────────────────────────────────────────────────────────────
  function showView(which) {
    view = which;
    $("tab-items").setAttribute("aria-selected", String(which === "items"));
    $("tab-asm").setAttribute("aria-selected", String(which === "asm"));
    $("pane-items").hidden = which !== "items";
    $("pane-asm").hidden = which !== "asm";
  }
  $("tab-items").addEventListener("click", function () { showView("items"); });
  $("tab-asm").addEventListener("click", function () { showView("asm"); });

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
  $("items-body").addEventListener("input", function (e) {
    var f = e.target.getAttribute("data-f");
    if (!f) return;
    var row = e.target.closest("[data-item]");
    var it = itemOf(row.getAttribute("data-item"));
    if (!it) return;
    var raw = e.target.value;
    it[f] = (f === "unit_cost" || f === "coverage") ? L.num(raw) : raw;
    renderList(); renderPanel();
    var body = {}; body[f] = raw;
    patchSoon("items", it.id, body);
  });

  $("lines-body").addEventListener("input", function (e) {
    var f = e.target.getAttribute("data-lf");
    if (!f || f === "item_id") return;
    var asm = current(), row = e.target.closest("[data-line]");
    if (!asm || !row) return;
    var ln = asm.lines[Number(row.getAttribute("data-line"))];
    if (!ln) return;
    ln[f] = (f === "coverage") ? L.num(e.target.value) : e.target.value;
    renderList();
    // Only the totals need redrawing, and re-rendering the table would move the caret out of
    // the field being typed in. So the numbers are refreshed without rebuilding the rows.
    refreshNumbers();
    patchSoon("assemblies", asm.id, { lines: asm.lines });
  });

  $("lines-body").addEventListener("change", function (e) {
    if (e.target.getAttribute("data-lf") !== "item_id") return;
    var asm = current(), row = e.target.closest("[data-line]");
    if (!asm || !row) return;
    var ln = asm.lines[Number(row.getAttribute("data-line"))];
    if (!ln) return;
    ln.item_id = e.target.value;
    // Coverage follows the material just picked, unless one was already set by hand.
    var it = itemOf(ln.item_id);
    if (it && !(Number(ln.coverage) > 0)) ln.coverage = it.coverage;
    paint();
    patchSoon("assemblies", asm.id, { lines: asm.lines });
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
    for (var i = 0; i < rows.length; i++) {
      var r = p.rows[i];
      if (!r) continue;
      var tds = rows[i].querySelectorAll("td");
      if (tds.length < 5) continue;
      if (r.ok && r.priced) {
        tds[3].innerHTML = '<span class="qty">' + r.qty.toLocaleString("en-US") + " " +
                           esc(r.item.unit) + '</span><div class="calc mono">' +
                           esc(L.explain(r, area)) + "</div>";
        tds[4].innerHTML = '<span class="qty">' + L.money(r.cost) + '</span><div class="calc mono">' +
                           r.qty.toLocaleString("en-US") + " × " + L.money(r.unit_cost) + "</div>";
        rows[i].classList.remove("broken");
      } else {
        tds[3].innerHTML = r.ok
          ? '<span style="color:var(--ink-v)">—</span>'
          : '<span class="gone">' + (r.reason === "missing_item" ? "Material removed"
              : r.reason === "no_coverage" ? "Needs a coverage" : "Needs a cost") + "</span>";
        tds[4].innerHTML = "—";
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
        var j = await post("items", { name: "New material", unit: "Gal" });
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
      asm.lines.push({ role: "", item_id: first ? first.id : "",
                       coverage: first ? first.coverage : null, note: "" });
      paint();
      patchSoon("assemblies", asm.id, { lines: asm.lines });
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
