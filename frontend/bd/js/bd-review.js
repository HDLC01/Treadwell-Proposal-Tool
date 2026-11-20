/* Potential BD Contacts, /bd/review.html (#809: BD's js/review.js, moved in as it is today, restyled
 * like the proposal tool by the approved BD mock-up).
 *
 * Direct quotes from the last 90 days whose contact is not on the BD list yet, in three tabs: To review
 * (new), Added and Not added. One load, GET /api/bd/review/candidates?status=all, gives all three and
 * their counts.
 *
 * AS IT IS TODAY. That route is not built: it answers 503 "This part is not built yet (Phase 6)." after
 * its role check (bd/routers/pending.py), exactly as it does in BD, and the page shows that sentence
 * with Try again, as BD's page does. Building the review, with Add to BD, Not a BD contact and their
 * Undo, is its own ticket (#816), with a spec of its own first. So only what can happen today is
 * carried: the tabs and their counts, the failure, and the list read-only. BD's Add / Not a BD contact
 * buttons, their Undo window and its batching are not, because their routes are placeholders too and
 * nothing could ever reach them (the #809 PR lists them).
 *
 * Every BD role opens this page, as in BD. Routes are under /api/bd/ (docs/bd/api-contract.md).
 */
(function () {
  "use strict";

  var BD = window.BD, Api = window.BDApi;
  var esc = BD.esc;
  var VIEWS = {
    "new": { empty: "All done for this month.", label: "People to review" },
    added: { empty: "No one added yet.", label: "People added to BD" },
    ignored: { empty: "No one set aside.", label: "People not added" },
  };

  var view = "new";
  var items = [];
  var loadSeq = 0;

  function $(id) { return document.getElementById(id); }
  function trim(s) { return String(s == null ? "" : s).replace(/\s+/g, " ").trim(); }

  function updateCounts() {
    var n = { "new": 0, added: 0, ignored: 0 };
    items.forEach(function (c) { if (n[c.status] != null) n[c.status] += 1; });
    Object.keys(n).forEach(function (k) {
      var el = document.querySelector('#rv-views [data-count="' + k + '"]');
      if (el) el.textContent = BD.fmtCount(n[k]);
    });
  }

  /** One person, read-only: who, the company, and the quote. */
  function rowHtml(c) {
    var company = trim(c.company) || "No company";
    return '<article class="card rv-row" data-id="' + esc(c.id) + '" aria-label="' + esc(trim(c.contact_name) || company) + '">' +
      BD.avatarHTML({ name: c.contact_name || company }) +
      '<div class="rv-who"><h2 class="rv-name">' + esc(c.contact_name || "No contact name") + "</h2>" +
      '<div class="rv-company">' + esc(company) + "</div></div>" +
      '<div class="rv-quote"><div class="rv-project">' + BD.icon("file", 16) + "<span>" + esc(c.project_name || "Direct quote") + "</span></div>" +
      '<div class="rv-amount"><span class="rv-money">' + esc(BD.money(c.quote_total)) + "</span>" +
      '<span class="rv-date">' + esc(BD.fmtBizDate(c.quote_date, "short")) + "</span></div></div></article>";
  }

  function render() {
    var body = $("rv-body");
    body.setAttribute("aria-busy", "false");
    body.setAttribute("aria-label", VIEWS[view].label);
    var shown = items.filter(function (c) { return c.status === view; });
    body.innerHTML = shown.length ? shown.map(rowHtml).join("")
      : '<div class="card rv-empty"><span class="rv-empty-ico" aria-hidden="true">' + BD.icon("check", 20) + "</span>" +
        '<p class="rv-empty-title">' + esc(VIEWS[view].empty) + "</p></div>";
    updateCounts();
  }

  function load() {
    var seq = ++loadSeq;
    var body = $("rv-body");
    body.setAttribute("aria-busy", "true");
    body.innerHTML = '<div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div>';
    return Api.get("/api/bd/review/candidates?status=all").then(function (res) {
      if (seq !== loadSeq) return;
      items = (res.items || []).filter(function (c) { return VIEWS[c.status]; });
      render();
    }, function (e) { if (seq === loadSeq) BD.errorBox($("rv-body"), e); });
  }

  function setView(next) {
    view = VIEWS[next] ? next : "new";
    Array.prototype.forEach.call(document.querySelectorAll("#rv-views button[data-view]"), function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-view") === view ? "true" : "false");
    });
    try {
      var u = new URL(location.href);
      if (view === "new") u.searchParams.delete("show"); else u.searchParams.set("show", view);
      history.replaceState(null, "", u.pathname + u.search + u.hash);
    } catch (err) { /* the address just stays */ }
  }

  var auth = window.TWAuth;
  if (!auth || !auth.ready || typeof auth.bdMe !== "function" || typeof auth.bdFailure !== "function") return;
  auth.ready.then(function () { return auth.bdMe(); }).then(function (res) {
    var ok = res && res.status >= 200 && res.status < 300 && res.body && res.body.ok;
    if (!ok) { BD.note($("rv-body"), auth.bdFailure(res && res.status, res && res.body).message, "rv-note"); return null; }
    $("rv-views").addEventListener("click", function (e) {
      var b = e.target.closest && e.target.closest("button[data-view]");
      if (!b || b.getAttribute("data-view") === view) return;
      setView(b.getAttribute("data-view"));
      if (loadSeq && !$("rv-body").querySelector(".error-box")) render();
      else load();
    });
    $("rv-body").addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest("[data-retry]")) load();
    });
    view = VIEWS[BD.qs("show")] ? BD.qs("show") : "new";
    setView(view);
    return load();
  });
})();
