// Project Analytics: the two tabs, and the Plan vs Actual list (#780).
// Externalized (no inline scripts; CSP). Do not add inline handlers.
//
// THE TABS. [Plan vs Actual] [Schedule]. Plan vs Actual is the default; the address "#schedule"
// opens the Schedule, which is the calendar drawn by js/project-calendar.js, unchanged except that
// its old 60-day side list of Deadlines is gone.
//
// WHAT THE SERVER HAS ALREADY DONE (GET /api/project-analytics, backend/plan_vs_actual.py). It
// reads a year of the Treadwell Projects calendar, groups it into Projects (Punches with their
// jobs), keeps the ones in its window (`window_days` either side of today) and works out each one's calendar side: Deadline,
// Workdays left, Workdays booked so far, the planned Crew size and Planned hours, all "so far" up to
// yesterday in Central. This page only lays the rows out and filters them with the search box.
//
// THE RAKEN SIDE (#782) is the server's last "Refresh now" read of Raken's time cards, set beside
// each row: days clocked in, average on site a day, Actual hours, and the row's statuses (Behind,
// Not linked) as chips; the Raken projects with recent hours and no job in the list get their own
// section; the read's "as of" time is shown in Central, and when Raken cannot be read the server's
// one plain sentence goes in the notice. A GET never reads Raken; "Refresh now" does.
//
// THE BUDGET PAIR (#783): Projected total hours against Budgeted hours, both Raken's, with
// Over/under signed ("+12 h", "−130 h"). The Hours and Budget pairs each carry a small bar, the plan
// a tick and Raken the fill, its widths set through the CSSOM. Statuses are flags: On plan, or any of
// Behind and Over budget (both when both), or Not linked alone.
//
// READ ONLY, with ONE write: "Refresh now" POSTs /api/project-analytics/refresh, which reads Raken
// and keeps the result on the server. Nothing in Google Calendar or Raken is ever changed. Every
// text value is escaped, and every colour is set through element.style once the markup is in
// place, never as a style attribute.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const P = window.TWProjCal;

  // Every request, the GET and "Refresh now" alike: waits for sign-in, then sends the headers.
  const api = async (path, init) => {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    return fetch(TW.resolveApiBase() + path, Object.assign({ headers: TW.authHeaders() }, init));
  };

  const SK_Q = "tw_pva_q";
  const ss = (k, d) => { try { const v = sessionStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
  const ssSet = (k, v) => { try { v ? sessionStorage.setItem(k, v) : sessionStorage.removeItem(k); } catch {} };

  const POLL_MS = 5 * 60 * 1000;
  const REFRESH_POLL_MS = 5 * 1000;    // while the server says a refresh is reading Raken

  let DATA = null;                     // the last good response
  let LOAD_ERR = "";                   // why the last read failed, if it did
  let Q = ss(SK_Q, "");
  let LAST_SIG = "";                   // anti-blink: skip identical repaints
  let REFRESHING = false;              // a "Refresh now" is on its way
  let FOLLOW = 0;                      // the timer polling while the server is refreshing

  // ── tabs ──────────────────────────────────────────────────────────
  function showTab(id, focus) {
    P.TABS.forEach((t) => {
      const on = t.id === id;
      const btn = $("tab-" + t.id);
      btn.setAttribute("aria-selected", on ? "true" : "false");
      btn.tabIndex = on ? 0 : -1;
      $("panel-" + t.id).hidden = !on;
    });
    const want = id === "schedule" ? "#schedule" : "";
    if (location.hash !== want) {
      try { history.replaceState(null, "", location.pathname + location.search + want); } catch {}
    }
    if (focus) $("tab-" + id).focus();
  }

  // ── fetch ─────────────────────────────────────────────────────────
  /** Take a response from the GET or from "Refresh now". */
  async function take(r) {
    const body = await r.json().catch(() => null);
    if (!r.ok || !body || body.ok === false) {
      const why = (body && (body.detail || body.error)) || ("HTTP " + r.status);
      LOAD_ERR = typeof why === "string" ? why : "The server refused the request.";
      return;
    }
    body.projects = (Array.isArray(body.projects) ? body.projects : [])
      .filter((p) => p && typeof p === "object");
    body.raken_only = (Array.isArray(body.raken_only) ? body.raken_only : [])
      .filter((x) => x && typeof x === "object");
    DATA = body;
    LOAD_ERR = "";
  }

  /** While the server says a refresh is reading Raken (someone else's press, or this one's
   *  answered early), poll the GET until it is done. One timer at a time. */
  function follow() {
    clearTimeout(FOLLOW);
    FOLLOW = P.rakenRefreshing(DATA) ? setTimeout(load, REFRESH_POLL_MS) : 0;
  }

  /** The button reads "Refreshing…" while this page's press or the server's refresh runs. */
  function paintButton() {
    const busy = REFRESHING || P.rakenRefreshing(DATA);
    const btn = $("pva-refresh");
    btn.disabled = busy;
    btn.textContent = busy ? "Refreshing…" : "Refresh now";
  }

  async function load() {
    if (REFRESHING) return;            // the refresh's own answer is on its way
    try {
      await take(await api("/api/project-analytics"));
    } catch (err) {
      LOAD_ERR = "Couldn't reach the server.";
    }
    follow();
    paint();
  }

  // "Refresh now": the page's one write. The server reads Raken and answers with the whole list,
  // as the GET does; when a refresh is already running it answers at once with refreshing: true,
  // and follow() polls until that one is done.
  async function refreshNow() {
    if (REFRESHING || P.rakenRefreshing(DATA)) return;
    REFRESHING = true;
    paintButton();
    try {
      await take(await api("/api/project-analytics/refresh", { method: "POST" }));
    } catch (err) {
      LOAD_ERR = "Couldn't reach the server.";
    }
    REFRESHING = false;
    follow();
    paint();
  }

  // ── rendering ─────────────────────────────────────────────────────
  function showAlert(text) {
    $("pva-alert").textContent = text || "";
    $("pva-alert").hidden = !text;
  }

  function showState(html) {
    $("pva-state").innerHTML = html;
    $("pva-state").hidden = false;
    $("pva-main").hidden = true;
    $("pva-count").textContent = "";
  }

  /** A pair's small bar (P.pairBar): empty spans carrying the widths as data, set through the
   *  CSSOM by paintBars() once the markup is in place. "" when there is no bar. */
  function barHtml(bar, colourOver) {
    if (!bar) return "";
    return '<span class="pbar' + (colourOver && bar.over ? " over" : "") + '" aria-hidden="true">'
      + '<i class="pbar-fill" data-w="' + esc(bar.fill) + '"></i>'
      + '<i class="pbar-tick" data-l="' + esc(bar.tick) + '"></i></span>';
  }

  /** The Budget pair's cell: Projected total hours, "of" Budgeted hours, Over/under, its bar,
   *  and a note when there is no budget, it was not read, or the projection is below Actual
   *  hours. */
  function budgetHtml(p) {
    const bc = P.budgetCells(p);
    const figures = !bc.shown ? "" : "<small>of " + esc(bc.budgeted) + " budgeted</small>"
      + '<small class="ou' + (bc.over ? " over" : "") + '">' + esc(bc.over_under) + "</small>"
      + barHtml(bc.bar, true);
    const note = bc.note ? '<small class="why">' + esc(bc.note) + "</small>" : "";
    return "<b>" + esc(bc.projected) + "</b>" + figures + note;
  }

  function rowHtml(p) {
    const sub = [P.workTypeOf(p), p.foreman ? "Foreman " + p.foreman : "",
      !p.is_punch && Array.isArray(p.punches) && p.punches.length
        ? "+ " + p.punches.length + " Punch" + (p.punches.length === 1 ? "" : "es") : ""]
      .filter(Boolean).join(" · ");
    const chips = (p.label ? ' <span class="chip">' + esc(p.label) + "</span>" : "")
      + (p.crew_size_missing ? ' <span class="chip warn">Crew size missing</span>' : "");
    const rc = P.rakenCells(p);
    const flags = P.statusChips(p).map((c) =>
      '<span class="chip st-' + esc(c.id) + '">' + esc(c.label) + "</span>").join("");
    const why = P.rakenLabel(p);
    return "<tr>"
      + '<td><div class="job"><i class="sw" data-color="' + esc(P.colorOf(p) || "") + '"></i><div>'
      + (p.job_number ? '<span class="jn">' + esc(p.job_number) + "</span>" : "")
      + '<span class="jname">' + esc(p.name || "Untitled") + "</span>" + chips
      + '<span class="jsub">' + esc(sub) + "</span></div></div></td>"
      + '<td><span class="dd">' + esc(P.dayLong(p.deadline)) + "</span>"
      + "<small>" + esc(P.leftLabel(p)) + "</small></td>"
      + '<td class="num"><b>' + esc(P.numLabel(p.workdays_so_far)) + "</b></td>"
      + '<td class="num rk"><b>' + esc(rc.days) + "</b>"
      + (rc.days_note ? "<small>" + esc(rc.days_note) + "</small>" : "") + "</td>"
      + '<td class="num"><b>' + esc(P.numLabel(p.crew_size)) + "</b></td>"
      + '<td class="num rk"><b>' + esc(rc.on_site) + "</b></td>"
      + '<td class="num"><b>' + esc(P.numLabel(p.planned_hours)) + "</b></td>"
      + '<td class="num rk"><b>' + esc(rc.hours) + "</b>" + barHtml(P.hoursBar(p), false) + "</td>"
      + '<td class="num rk">' + budgetHtml(p) + "</td>"
      + '<td class="status">' + flags + (why ? "<small>" + esc(why) + "</small>" : "") + "</td>"
      + "</tr>";
  }

  function onlyRowHtml(x) {
    return "<tr>"
      + "<td>" + (x.number ? '<span class="jn">' + esc(x.number) + "</span>" : "")
      + '<span class="jname">' + esc(P.rakenOnlyName(x)) + "</span></td>"
      + '<td class="num"><b>' + esc(P.decLabel(x.actual_hours)) + "</b></td>"
      + '<td><span class="dd">' + esc(P.dayLong(x.last_day)) + "</span></td>"
      + "</tr>";
  }

  /** The Raken-only section, shown whenever the server listed any, even with no calendar rows. */
  function paintOnly() {
    const list = DATA && Array.isArray(DATA.raken_only) ? DATA.raken_only : [];
    $("pva-only").hidden = !list.length;
    $("pva-only-body").innerHTML = list.map(onlyRowHtml).join("");
    const from = DATA && DATA.raken ? P.dayLong(DATA.raken.read_from) : "";
    $("pva-only-from").textContent = from ? "since " + from : "";
  }

  function paintSwatches(root) {
    root.querySelectorAll(".sw[data-color]").forEach((el) => {
      const c = el.dataset.color;
      if (c && /^#[0-9a-f]{6}$/i.test(c)) el.style.background = c;
    });
  }

  /** The pair bars' fill widths and tick places, through the CSSOM (the CSP forbids style
   *  attributes). Only a percentage from 0 to 100 is ever set. */
  function paintBars(root) {
    const pct = (v) => {
      const n = Number(v);
      return isFinite(n) && n >= 0 && n <= 100 ? n + "%" : "";
    };
    root.querySelectorAll(".pbar-fill[data-w]").forEach((el) => { el.style.width = pct(el.dataset.w); });
    root.querySelectorAll(".pbar-tick[data-l]").forEach((el) => { el.style.left = pct(el.dataset.l); });
  }

  function paint() {
    paintButton();
    const sig = JSON.stringify([Q, LOAD_ERR, DATA]);
    if (sig === LAST_SIG) return;
    LAST_SIG = sig;

    $("pva-asof").textContent = DATA ? P.asOfText(DATA) : "";
    paintOnly();
    if (!DATA) {
      showAlert("");
      if (LOAD_ERR) {
        showState("<b>Couldn't load Plan vs Actual</b>" + esc(LOAD_ERR)
          + " It will try again in a few minutes.");
      } else {
        showState("Loading Plan vs Actual…");
      }
      return;
    }
    if (DATA.connected === false) {
      showAlert(P.rakenMessage(DATA));
      showState("<b>The Treadwell Projects calendar is not connected yet</b>"
        + "Once it is connected, each job's plan from Google Calendar shows here.");
      return;
    }

    const projects = DATA.projects;
    const notice = [];
    if (DATA.stale) {
      const at = P.centralStamp(DATA.fetched_at);
      notice.push(at ? "Showing the last copy from " + at + " (Central)."
                    : "Showing the last copy of the calendar.");
    } else if (LOAD_ERR) {
      notice.push("Couldn't refresh just now (" + LOAD_ERR + "). Showing what was loaded before.");
    }
    if (DATA.error && projects.length) notice.push(String(DATA.error));
    if (DATA.notice) notice.push(String(DATA.notice));
    if (P.rakenMessage(DATA)) notice.push(P.rakenMessage(DATA));
    showAlert(notice.join(" "));

    if (!projects.length && DATA.error) {
      showState("<b>Couldn't read the Treadwell Projects calendar</b>" + esc(DATA.error));
      return;
    }

    $("pva-state").hidden = true;
    $("pva-main").hidden = false;

    const shown = P.filterProjects(projects, Q);
    $("pva-count").textContent = Q
      ? shown.length + " of " + projects.length + " jobs"
      : projects.length + " job" + (projects.length === 1 ? "" : "s");
    const body = $("pva-body");
    body.innerHTML = shown.map(rowHtml).join("");
    paintSwatches(body);
    paintBars(body);

    const empty = !projects.length
      ? P.pvaEmptyText(DATA)
      : (!shown.length ? "No job matches the search." : "");
    $("pva-empty").textContent = empty;
    $("pva-empty").hidden = !empty;

    $("pva-foot").textContent = P.pvaFootText(DATA);
  }

  // ── wiring (delegated; CSP forbids inline handlers) ───────────────
  $("pva-refresh").addEventListener("click", refreshNow);
  $("pva-q").value = Q;
  $("pva-q").addEventListener("input", (e) => { Q = e.target.value || ""; ssSet(SK_Q, Q); paint(); });
  $("pva-q").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.target.value = ""; Q = ""; ssSet(SK_Q, ""); paint(); }
  });

  const tablist = document.querySelector('[role="tablist"]');
  tablist.addEventListener("click", (e) => {
    const b = e.target.closest('[role="tab"]');
    if (b) showTab(b.id.replace(/^tab-/, ""), false);
  });
  // The tab pattern's keys. Stopped here, so the Schedule's own arrow keys never page the calendar
  // because a tab had focus.
  tablist.addEventListener("keydown", (e) => {
    const ids = P.TABS.map((t) => t.id);
    const cur = ids.indexOf((e.target.id || "").replace(/^tab-/, ""));
    if (cur < 0) return;
    let next = -1;
    if (e.key === "ArrowRight") next = (cur + 1) % ids.length;
    else if (e.key === "ArrowLeft") next = (cur - 1 + ids.length) % ids.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = ids.length - 1;
    if (next < 0) return;
    e.preventDefault();
    e.stopPropagation();
    showTab(ids[next], true);
  });
  window.addEventListener("hashchange", () => showTab(P.tabFromHash(location.hash), false));

  showTab(P.tabFromHash(location.hash), false);
  paint();
  load();
  setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
})();
