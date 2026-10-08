// One search pop-up for adding library lines to an estimate: pure filtering and selection logic,
// plus a small DOM mount. Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHY IT EXISTS (Hanz, 2026-10-09, Estimating Tool v2 only). The Takeoff step added an empty row
// you then had to search; the Labor step added an empty "Task" card you then had to name. Both are
// the same job: pick lines from the library. So both steps open this one pop-up, tick what they
// want, and press Add. Nothing is created until something is picked.
//
// LOOKS LIKE library.html's "Add materials" dialog on purpose (search box, a list with ticks, an
// Add button) and reuses its CSS classes (.bulk-*), which polish-estimate.html carries a copy of.
// That dialog itself is not touched; moving it onto this module is a later job.
//
// SPLIT IN TWO so the decisions can be tested without a browser: shown / toggle / picked /
// cleanName are pure, and open() only wires them to elements. open() builds ONE overlay, listens on
// the overlay (never on its children, so repainting the list cannot lose a handler), and removes it
// again on close.
//
// ENTRIES are plain objects the caller builds: { key, name, sub, tag, first, on }.
//   key    a string that is unique within the list (the caller decides, e.g. "asm:" + id)
//   name   what the row is called; search matches it and `sub`
//   sub    the small line under the name
//   tag    the small label at the right ("Assembly", "Material", a rate)
//   first  true lists the row above the rest (a labor line meant for this bid's work type)
//   on     true shows the row ticked and locked ("already on this bid")
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.TWLibraryPicker = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function words(q) {
    var t = String(q == null ? "" : q).toLowerCase().split(/\s+/);
    var out = [];
    for (var i = 0; i < t.length; i++) if (t[i]) out.push(t[i]);
    return out;
  }

  /** Every word typed has to appear in the name or the small line. Several words narrow, never
   *  widen, and an empty box matches everything. */
  function matches(entry, query) {
    var w = words(query);
    if (!w.length) return true;
    var hay = (String((entry || {}).name == null ? "" : entry.name) + " " +
               String((entry || {}).sub == null ? "" : entry.sub)).toLowerCase();
    for (var i = 0; i < w.length; i++) if (hay.indexOf(w[i]) === -1) return false;
    return true;
  }

  /** The rows to draw: the ones the query keeps, with `first` rows above the rest. Stable inside
   *  each of the two groups, so the caller's own order (the library's order) is what shows. A NEW
   *  array; the one handed in is never touched. */
  function shown(entries, query) {
    var top = [];
    var rest = [];
    (entries instanceof Array ? entries : []).forEach(function (e) {
      if (!e || !matches(e, query)) return;
      if (e.first) top.push(e); else rest.push(e);
    });
    return top.concat(rest);
  }

  /** Tick or untick one key. A NEW array; keys keep the order they were ticked in. Keys are only
   *  ever compared, never used as property names. */
  function toggle(keys, key) {
    var list = (keys instanceof Array) ? keys : [];
    var at = list.indexOf(key);
    if (at === -1) return list.concat([key]);
    return list.slice(0, at).concat(list.slice(at + 1));
  }

  /** The ticked entries, in the order of the full list (not the order they were ticked), without
   *  any row that is locked as already on the bid. A key that no longer exists is dropped. */
  function picked(entries, keys) {
    var list = (keys instanceof Array) ? keys : [];
    return (entries instanceof Array ? entries : []).filter(function (e) {
      return e && !e.on && list.indexOf(e.key) !== -1;
    });
  }

  /** A typed one-off name: trimmed, inner runs of spaces folded, "" when nothing real was typed. */
  function cleanName(text) {
    return String(text == null ? "" : text).replace(/\s+/g, " ").replace(/^ | $/g, "");
  }

  function rowHtml(e, isOn) {
    var locked = !!e.on;
    return '<label class="bulk-row' + (locked ? " on" : "") + '">' +
      '<input type="checkbox" data-pk="' + esc(e.key) + '"' +
        (locked ? " disabled checked" : (isOn ? " checked" : "")) + ">" +
      '<span class="bulk-box"></span>' +
      '<span class="bulk-nm"><b>' + esc(e.name) + "</b><span>" + esc(e.sub) + "</span></span>" +
      (locked ? '<span class="bulk-in">' + esc(e.onText || "Already added") + "</span>"
              : '<span class="bulk-cost">' + esc(e.tag) + "</span>") +
      "</label>";
  }

  /** Open the pop-up. `doc` is the document; cfg is
   *    title, sub, placeholder       the heading, the line under it, the search box's hint
   *    entries                       the list (see the top of this file)
   *    emptyText                     what the list says when the library has nothing at all
   *    opener                        the button that opened it; it gets the focus back on close
   *    onClose()                     called once when it is gone, however it went
   *    onAdd(pickedEntries)          called once with the ticked rows when Add is pressed
   *    oneOff { label, placeholder, button, onAdd(name) }   optional "type your own" entry
   *  Returns { close, element }. Closing never calls onAdd. */
  function open(doc, cfg) {
    cfg = cfg || {};
    var entries = cfg.entries instanceof Array ? cfg.entries : [];
    var keys = [];
    var query = "";
    var closed = false;

    var ov = doc.createElement("div");
    ov.className = "tw-ov bulk-ov tw-in";
    ov.setAttribute("role", "dialog");
    ov.setAttribute("aria-modal", "true");
    ov.setAttribute("aria-labelledby", "pk-h");
    ov.innerHTML =
      '<div class="bulk-dlg">' +
        '<div class="bulk-head">' +
          '<h2 id="pk-h">' + esc(cfg.title || "Add lines") + "</h2>" +
          '<p class="bulk-sub">' + esc(cfg.sub || "") + "</p>" +
          '<button class="icon" type="button" data-pk-close="1" title="Close" aria-label="Close">' +
            '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ' +
            'focusable="false"><path d="M18 6L6 18M6 6l12 12"></path></svg></button>' +
        "</div>" +
        '<div class="bulk-filters"><span class="searchbox">' +
          '<input data-pk-el="q" type="search" placeholder="' + esc(cfg.placeholder || "Search") +
          '" aria-label="' + esc(cfg.placeholder || "Search") + '" autocomplete="off" /></span></div>' +
        '<div class="bulk-list" data-pk-el="list" role="group" aria-labelledby="pk-h"></div>' +
        '<p class="bulk-none" data-pk-el="none" hidden></p>' +
        (cfg.oneOff
          ? '<div class="bulk-oneoff"><b>' + esc(cfg.oneOff.label || "One-off line") + "</b>" +
            '<input data-pk-el="oneoff" type="text" placeholder="' +
              esc(cfg.oneOff.placeholder || "Name this line") + '" aria-label="' +
              esc(cfg.oneOff.label || "One-off line") + '" autocomplete="off" />' +
            '<button class="btn ghost" type="button" data-pk-oneoff="1" disabled>' +
              esc(cfg.oneOff.button || "Add line") + "</button></div>"
          : "") +
        '<div class="bulk-foot">' +
          '<span class="bulk-count" data-pk-el="count"></span>' +
          '<span class="bulk-spacer"></span>' +
          '<button class="btn ghost" type="button" data-pk-close="1">Cancel</button>' +
          '<button class="btn" type="button" data-pk-add="1" disabled>Add</button>' +
        "</div>" +
      "</div>";

    var list = ov.querySelector('[data-pk-el="list"]');
    var none = ov.querySelector('[data-pk-el="none"]');
    var count = ov.querySelector('[data-pk-el="count"]');
    var search = ov.querySelector('[data-pk-el="q"]');
    var addBtn = ov.querySelector("[data-pk-add]");
    var oneBox = ov.querySelector('[data-pk-el="oneoff"]');
    var oneBtn = ov.querySelector("[data-pk-oneoff]");
    if (oneBtn) oneBtn.disabled = true;      // until a name is typed

    function paintList() {
      var rows = shown(entries, query);
      list.innerHTML = rows.map(function (e) {
        return rowHtml(e, keys.indexOf(e.key) !== -1);
      }).join("");
      none.hidden = rows.length > 0;
      if (!rows.length) {
        none.textContent = entries.length
          ? "Nothing matches that. Try fewer words."
          : (cfg.emptyText || "The library has nothing to add yet.");
      }
    }
    function paintFoot() {
      var n = picked(entries, keys).length;
      count.textContent = n ? n + " picked" : "";
      addBtn.disabled = n === 0;
    }

    function close() {
      if (closed) return;
      closed = true;
      if (doc.body && doc.body.removeChild) doc.body.removeChild(ov);
      var back = cfg.opener;
      if (back && back.focus) back.focus();
      if (cfg.onClose) cfg.onClose();
    }

    function up(t, attr) {
      if (!t) return null;
      if (t.closest) return t.closest("[" + attr + "]");
      return (t.getAttribute && t.getAttribute(attr) !== null) ? t : null;
    }

    ov.addEventListener("click", function (e) {
      var t = e.target;
      if (up(t, "data-pk-close")) { close(); return; }
      if (up(t, "data-pk-add")) {
        var chosen = picked(entries, keys);
        if (!chosen.length) return;
        close();
        if (cfg.onAdd) cfg.onAdd(chosen);
        return;
      }
      if (up(t, "data-pk-oneoff")) { addOneOff(); return; }
      // The dim area around the box closes it, like the library's own dialog.
      if (t === ov) close();
    });
    ov.addEventListener("change", function (e) {
      var k = e.target && e.target.getAttribute ? e.target.getAttribute("data-pk") : null;
      if (k === null) return;
      keys = toggle(keys, k);
      paintFoot();
    });
    ov.addEventListener("input", function (e) {
      var t = e.target;
      if (t === search) { query = search.value; paintList(); return; }
      if (oneBox && t === oneBox) oneBtn.disabled = cleanName(oneBox.value) === "";
    });
    ov.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { if (e.preventDefault) e.preventDefault(); close(); return; }
      if (e.key !== "Enter") return;
      // Enter in the search box must not add anything blindly: it only keeps the form-less box
      // from doing whatever Enter does by default. Adding is the Add button.
      if (e.target === search) { if (e.preventDefault) e.preventDefault(); return; }
      if (oneBox && e.target === oneBox) { if (e.preventDefault) e.preventDefault(); addOneOff(); }
    });

    function addOneOff() {
      if (!oneBox) return;
      var name = cleanName(oneBox.value);
      if (!name) return;
      close();
      if (cfg.oneOff && cfg.oneOff.onAdd) cfg.oneOff.onAdd(name);
    }

    paintList();
    paintFoot();
    doc.body.appendChild(ov);
    if (search && search.focus) search.focus();
    return { close: close, element: ov };
  }

  return { shown: shown, toggle: toggle, picked: picked, cleanName: cleanName, matches: matches,
           open: open };
});
