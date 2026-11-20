/* Analytics, /bd/analytics.html (#809: BD's js/analytics.js, moved in as it is today, restyled like the
 * proposal tool by the approved BD mock-up). The manager and the admins (can.analytics).
 *
 * "Is BD working?" for a period and, optionally, one owner: GET /api/bd/analytics?from=&to=&owner=, and
 * its CSV, GET /api/bd/analytics/export.csv with the same query.
 *
 * AS IT IS TODAY. Both routes are not built: they answer 503 "This part is not built yet (Phase 7)."
 * after their role check (bd/routers/pending.py), exactly as in BD. So the page works as BD's does
 * today: the period tabs (Week, Month, Quarter, Year, Dates), the custom dates and their checks, and
 * the Owner list (the people who own contacts, from GET /api/bd/contacts) each ask again, the body
 * says the server's sentence with Try again, and Download CSV says it in a toast. BD's number cards,
 * pace bar and charts are not carried: nothing can reach them until the route is built, which is its
 * own ticket (the #809 PR lists them). Dates are Central, from /api/bd/me's `today`.
 */
(function () {
  "use strict";

  var BD = window.BD, Api = window.BDApi;
  var esc = BD.esc;

  var today = "";
  var period = "year";
  var seq = 0;                  // a slow answer must never overwrite a newer one
  var contactsLoad = null;

  function $(id) { return document.getElementById(id); }

  // ── the period ───────────────────────────────────────────────────────────────────────────
  function quarterStart(iso) {
    var m = Number(iso.slice(5, 7));
    var q = Math.floor((m - 1) / 3) * 3 + 1;
    return iso.slice(0, 4) + "-" + (q < 10 ? "0" : "") + q + "-01";
  }

  function rangeFor(p) {
    if (p === "week") return { from: BD.bizWeekStart(today), to: today };
    if (p === "month") return { from: today.slice(0, 8) + "01", to: today };
    if (p === "quarter") return { from: quarterStart(today), to: today };
    if (p === "custom") return { from: $("an-from").value, to: $("an-to").value };
    return { from: today.slice(0, 4) + "-01-01", to: today };
  }

  /** "Jan 1 - Wed, Nov 4, 2026" (the start shows its year only when it differs). */
  function rangeText(from, to) {
    if (!from || !to) return "";
    var start = BD.fmtBizDate(from).replace(/, \d{4}$/, "");
    if (from.slice(0, 4) !== to.slice(0, 4)) start = BD.fmtBizDate(from);
    return start + " - " + BD.fmtBizDate(to, "short") + ", " + to.slice(0, 4);
  }

  function setPeriod(p) {
    period = p;
    Array.prototype.forEach.call(document.querySelectorAll("#an-period button"), function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-period") === p ? "true" : "false");
    });
    $("an-custom").hidden = p !== "custom";
    if (p === "custom" && !$("an-from").value) {
      var r = rangeFor("year");
      $("an-from").value = r.from; $("an-to").value = r.to;
    }
    load();
  }

  function query() {
    var r = rangeFor(period);
    var q = "from=" + encodeURIComponent(r.from) + "&to=" + encodeURIComponent(r.to);
    if ($("an-owner").value) q += "&owner=" + encodeURIComponent($("an-owner").value);
    return q;
  }

  /** What is wrong with the chosen dates, or "" when they are fine. */
  function rangeProblem() {
    if (period !== "custom") return "";
    var from = $("an-from").value, to = $("an-to").value;
    if (!from || !to) return "Pick a start date and an end date.";
    if (from > to) return "The first date is after the last date.";
    return "";
  }

  /** Set an attribute only when it changes. Chrome drops a date that is half typed with the
   *  keyboard whenever min or max is written to that input, even with the same value. */
  function setAttrIfChanged(el, name, value) {
    if (el.getAttribute(name) !== value) el.setAttribute(name, value);
  }

  function syncDateLimits() {
    var fromEl = $("an-from"), toEl = $("an-to");
    // To can't be before From; neither can be after today (max is set once at start-up).
    if (fromEl.value) setAttrIfChanged(toEl, "min", fromEl.value);
    else if (toEl.hasAttribute("min")) toEl.removeAttribute("min");
    var custom = period === "custom";
    var fromBad = custom && (!fromEl.value || (!!toEl.value && fromEl.value > toEl.value));
    var toBad = custom && !toEl.value;
    setAttrIfChanged(fromEl, "aria-invalid", fromBad ? "true" : "false");
    setAttrIfChanged(toEl, "aria-invalid", toBad ? "true" : "false");
  }

  /** The dates are not usable: say so, and take the last range's answer off the screen. An answer
   *  still on its way is dropped (seq). */
  function showRangeProblem(msg) {
    ++seq;
    var err = $("an-range-error"), body = $("an-body");
    err.textContent = msg;
    err.hidden = false;
    $("an-export").disabled = true;
    $("an-sub").textContent = "Pick the dates";
    body.setAttribute("aria-busy", "false");
    body.innerHTML = '<div class="card empty"><div class="empty-ico">' + BD.icon("calendar", 22) + "</div>" +
      '<p class="empty-title">No dates to show yet</p>' +
      '<p class="empty-text">The numbers come back once the start and end dates are set, with the start first.</p></div>';
  }

  function showError(e) {
    var body = $("an-body");
    body.setAttribute("aria-busy", "false");
    body.innerHTML = '<div class="error-box" role="alert"><p>' + esc(BD.errText(e)) + "</p>" +
      '<button type="button" class="btn" data-retry>Try again</button></div>';
  }

  /** The owners: the people who own contacts (a manager cannot list the BD logins). Optional: a
   *  failure leaves the filter on Everyone. */
  function loadOwners() {
    if (!contactsLoad) {
      contactsLoad = Api.get("/api/bd/contacts?limit=500").then(function (res) {
        var seen = {}, people = [];
        (res.items || []).forEach(function (c) {
          if (c.owner && c.owner.id != null && !seen[c.owner.id]) { seen[c.owner.id] = true; people.push(c.owner); }
        });
        people.sort(function (x, y) { return String(x.name).localeCompare(String(y.name)); });
        $("an-owner").insertAdjacentHTML("beforeend", people.map(function (p) {
          return '<option value="' + esc(p.id) + '">' + esc(p.name) + "</option>";
        }).join(""));
      }, function () { /* the filter stays on Everyone */ });
    }
    return contactsLoad;
  }

  function load() {
    syncDateLimits();
    var problem = rangeProblem();
    if (problem) { showRangeProblem(problem); return Promise.resolve(); }
    $("an-range-error").hidden = true;
    $("an-export").disabled = false;
    var mine = ++seq;
    var r = rangeFor(period);
    $("an-sub").textContent = rangeText(r.from, r.to);
    var body = $("an-body");
    body.setAttribute("aria-busy", "true");
    return Api.get("/api/bd/analytics?" + query()).then(function () {
      if (mine !== seq) return;
      body.setAttribute("aria-busy", "false");
      body.innerHTML = '<div class="panel-info an-note" role="status">' + BD.icon("info", 18) +
        "<span>The numbers came back, but this page does not draw them yet.</span></div>";
    }, function (e) { if (mine === seq) showError(e); });
  }

  function download() {
    var btn = $("an-export");
    BD.setBusy(btn, true);
    Api.get("/api/bd/analytics/export.csv?" + query()).then(function (text) {
      var blob = new Blob([typeof text === "string" ? text : ""], { type: "text/csv;charset=utf-8" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url; a.download = "bd-contacts-" + today + ".csv";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
    }).catch(function (e) {
      BD.toast(BD.errText(e), { kind: "error" });
    }).then(function () { BD.setBusy(btn, false); btn.disabled = !!rangeProblem(); });
  }

  function renderNote(words) {
    var body = $("an-body");
    body.setAttribute("aria-busy", "false");
    body.innerHTML = '<div class="panel-info an-note" role="status">' + BD.icon("info", 18) + "<span>" + esc(words) + "</span></div>";
  }

  var auth = window.TWAuth;
  if (!auth || !auth.ready || typeof auth.bdMe !== "function" || typeof auth.bdFailure !== "function") return;
  auth.ready.then(function () { return auth.bdMe(); }).then(function (res) {
    var ok = res && res.status >= 200 && res.status < 300 && res.body && res.body.ok;
    if (!ok) { renderNote(auth.bdFailure(res && res.status, res && res.body).message); return null; }
    if ((res.body.can || {}).analytics !== true) { renderNote("Analytics isn't part of your BD role."); return null; }
    today = res.body.today || BD.bizToday();
    $("an-from").max = today;
    $("an-to").max = today;
    $("an-tools").hidden = false;
    var btn = $("an-export");
    btn.insertAdjacentHTML("afterbegin", BD.icon("download", 18));
    btn.addEventListener("click", download);
    $("an-period").addEventListener("click", function (e) {
      var b = e.target.closest && e.target.closest("button[data-period]");
      if (b) setPeriod(b.getAttribute("data-period"));
    });
    $("an-body").addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest("[data-retry]")) load();
    });
    $("an-from").addEventListener("change", load);
    $("an-to").addEventListener("change", load);
    $("an-owner").addEventListener("change", load);
    $("an-sub").textContent = rangeText(rangeFor(period).from, today);
    return loadOwners().then(load);
  });
})();
