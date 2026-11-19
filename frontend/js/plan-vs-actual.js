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
// yesterday in Central. This page only lays the rows out, filters them (the search box and the
// filters below) and splits them into pages.
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
// THE JOB DETAIL (#789). A row's name is a button: it opens that job's detail in place of the list
// (a view inside the page, not a new page): the four pairs larger, the status chips, the day-by-day
// chart (one column per Workday the server sent in `day_by_day`: the planned crew as a tick, the
// people clocked in that day as a bar, a missed day marked out, a day missing a Crew size marked,
// Actual hours over Planned hours under it, days from today on the plan only), the Mobilizations
// and Punches with their links to Google Calendar, the Foreman, the flags and "Open project". A
// Schedule bar opens the same detail through window.TWPva.openEvent, found by the bar's EVENT ID
// (P.pvaLookup). "Back", or Esc, returns to where it was opened from: the list, or the Schedule.
// Leaving by the tab bar closes the detail.
//
// THE SUMMARY STRIP (#788), above the list, from the server's `summary`: four counts (On plan,
// Behind, Over budget, Not linked; a job Behind and Over budget is counted under both), last week's
// Planned hours against Actual hours, and the Budget totals. Each count is a button (aria-pressed):
// pressing it shows only the jobs carrying that status, together with the search box; pressing it
// again, or "Show all jobs", clears it, and the focus stays on the count. Until Raken is read the
// counts are not known: each is a dash, cannot be pressed, and a line under them says why. The two
// figure tiles are the job detail's own pair (pairHtml).
//
// THE FILTERS AND THE PAGER (#819). Beside the search box, three labelled selects: Work type (the
// server's colour-to-Work-type list and "Work type unknown"), Foreman (the list's own Foremen and
// "No foreman") and Status. Status is the summary strip's count filter, not a second one: choosing
// it presses the count, pressing a count sets it, "Show all jobs" and Clear filters clear both, and
// it is disabled while the counts are not known. Everything combines (AND). Under the list, the
// pager shows 25, 50 or 100 jobs a page; the server still sends the whole list. Any change to the
// search, a filter or the page size goes back to page 1, and a page past the end shows the last.
// THE VIEW (search, filters, page, page size) lives in the address's query string, written with
// replaceState as it changes, so a reload or a shared link opens the same list; what the list does
// not offer falls back to "All" (P.readView, P.settleView). The "#schedule" hash still picks the tab,
// and every other key in the address is left alone: Connect Raken (js/raken-connect.js, loaded
// after this script) comes back here with raken_code and raken_state and reads them later.
//
// THE DOWNLOAD (#785): "Download" fetches the list as it is filtered on screen (the search box, the
// pressed count and the Work type and Foreman filters go as `q`, `status`, `work_type` and
// `foreman`; never the page) as an Excel file, a GET built on the server.
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
  const icon = (name, size) => (typeof window.TWIcon === "function" ? window.TWIcon(name, size) : "");

  // Every request, the GET and "Refresh now" alike: waits for sign-in, then sends the headers.
  const api = async (path, init) => {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    return fetch(TW.resolveApiBase() + path, Object.assign({ headers: TW.authHeaders() }, init));
  };

  const POLL_MS = 5 * 60 * 1000;
  const REFRESH_POLL_MS = 5 * 1000;    // while the server says a refresh is reading Raken

  let DATA = null;                     // the last good response
  let LOAD_ERR = "";                   // why the last read failed, if it did
  // The list's view (#819): the search, the pressed count (`status`), the Work type and Foreman
  // filters, the page and the page size. Read from the address; written back by writeView().
  let VIEW = P.readView(location.search);
  let LAST_SIG = "";                   // anti-blink: skip identical repaints
  let REFRESHING = false;              // a "Refresh now" is on its way
  let FOLLOW = 0;                      // the timer polling while the server is refreshing
  let DETAIL = null;                   // {key, origin, barKey} while a job's detail is open
  let SCROLLED_FOR = "";               // the detail whose chart was last scrolled to today

  // ── tabs ──────────────────────────────────────────────────────────
  function showTab(id, focus) {
    // Leaving Plan vs Actual by a tab closes an open detail: coming back shows the list, and Esc on
    // the Schedule never acts on a view nobody can see. (closeDetail clears DETAIL before it
    // switches, so its own way back to the Schedule is unaffected.)
    if (id !== "pva" && DETAIL) { DETAIL = null; paint(); }
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
    // A shared link's Work type or Foreman the list does not offer falls back to "All".
    VIEW = P.settleView(VIEW, DATA);
    writeView();
  }

  // ── the view in the address (#819) ────────────────────────────────
  /** The address carries the view: replaceState, so Back is not flooded. Only the view's own keys
   *  are rewritten (P.addressSearch); any other key and the hash (the tab) are kept as they are. */
  function writeView() {
    const want = location.pathname + P.addressSearch(location.search, VIEW) + location.hash;
    if (location.pathname + location.search + location.hash !== want) {
      try { history.replaceState(null, "", want); } catch {}
    }
  }

  /** A change to the view: a new search, filter or page size goes back to page 1 (P.nextView). */
  function setView(patch) {
    VIEW = P.nextView(VIEW, patch);
    writeView();
    paint();
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

  // ── the Excel download (#785) ─────────────────────────────────────
  /** The download's address right now: the filters in force (P.viewFilters: no count while the
   *  counts are not known, as the list itself ignores a pressed count then), never the page. */
  function downloadPath() {
    const f = P.viewFilters(DATA, VIEW);
    return P.downloadHref(f.q, f.status, f);
  }

  // "Download": a GET of the list as it is filtered on screen. Every /api route needs the sign-in
  // header, which a plain link cannot send (so the control is a button with no address), so a
  // click fetches the file and saves it under the server's name (it carries the Central day it
  // was made). A read, never a write.
  let DOWNLOADING = false;
  async function downloadNow() {
    if (DOWNLOADING) return;
    DOWNLOADING = true;
    const btn = $("pva-download");
    btn.disabled = true;
    btn.textContent = "Downloading…";
    try {
      const r = await api(downloadPath());
      if (!r.ok) throw new Error("HTTP " + r.status);
      const buf = await r.arrayBuffer();
      const url = URL.createObjectURL(new Blob([buf], { type: "application/octet-stream" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = P.downloadName(r.headers.get("content-disposition"), P.centralToday());
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    } catch (err) {
      showAlert("Couldn't download the list just now. Try again in a minute.");
    }
    DOWNLOADING = false;
    btn.disabled = false;
    btn.textContent = "Download";
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

  /** The line under a job's name: Work type, Foreman, and how many Punches it carries. */
  function subOf(p) {
    return [P.workTypeOf(p), p.foreman ? "Foreman " + p.foreman : "",
      !p.is_punch && Array.isArray(p.punches) && p.punches.length
        ? "+ " + p.punches.length + " Punch" + (p.punches.length === 1 ? "" : "es") : ""]
      .filter(Boolean).join(" · ");
  }

  /** The Punch label and "Crew size missing", as chips. */
  function labelChips(p) {
    return (p.label ? ' <span class="chip">' + esc(p.label) + "</span>" : "")
      + (p.crew_size_missing ? ' <span class="chip warn">Crew size missing</span>' : "");
  }

  /** The row's statuses (On plan, Behind, Over budget, Not linked) as chips: the list and the
   *  detail both say them. */
  function statusChipsHtml(p) {
    return P.statusChips(p).map((c) =>
      '<span class="chip st-' + esc(c.id) + '">' + esc(c.label) + "</span>").join("");
  }

  function rowHtml(p) {
    const sub = subOf(p);
    const chips = labelChips(p);
    const rc = P.rakenCells(p);
    const flags = statusChipsHtml(p);
    const why = P.rakenLabel(p);
    // The row opens the job's detail: its name is the button (keyboard), the whole row the target.
    return '<tr data-key="' + esc(p.key) + '">'
      + '<td><div class="job"><i class="sw" data-color="' + esc(P.colorOf(p) || "") + '"></i><div>'
      + (p.job_number ? '<span class="jn">' + esc(p.job_number) + "</span>" : "")
      + '<button type="button" class="jlink" data-key="' + esc(p.key) + '">'
      + esc(p.name || "Untitled") + "</button>" + chips
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

  /** A percentage from 0 to 100 as a CSS length, else "": the only value ever set below. */
  const pct = (v) => {
    const n = Number(v);
    return isFinite(n) && n >= 0 && n <= 100 ? n + "%" : "";
  };

  /** The pair bars' fill widths and tick places, through the CSSOM (the CSP forbids style
   *  attributes). */
  function paintBars(root) {
    root.querySelectorAll(".pbar-fill[data-w]").forEach((el) => { el.style.width = pct(el.dataset.w); });
    root.querySelectorAll(".pbar-tick[data-l]").forEach((el) => { el.style.left = pct(el.dataset.l); });
  }

  // ── the summary strip (#788) ──────────────────────────────────────
  /** Put the focus on the count tile `id`. A paint rebuilds the strip's buttons, so the one just
   *  pressed is gone and the focus would drop to <body>. */
  function focusTile(id) {
    const tile = Array.from($("pva-sum").querySelectorAll("[data-st]"))
      .find((b) => b.dataset.st === id);
    if (tile) tile.focus();
  }

  /** A count pressed: show only its jobs, or every job when it was already the one pressed. The
   *  focus stays on the count pressed. */
  function setStatus(id) {
    setView({ status: P.toggleStatus(VIEW.status, id) });
    focusTile(id);
  }

  /** "Show all jobs": clear the count filter (the search box stays), and put the focus back on the
   *  count that was pressed, since the button itself goes away. */
  function clearStatus() {
    if (!VIEW.status) return;
    const was = VIEW.status;
    setView({ status: "" });
    focusTile(was);
  }

  // ── the filters and the pager (#819) ──────────────────────────────
  /** Clear filters: no search and no filter, page 1 (the page size stays). The button goes away,
   *  so the focus goes to the search box. */
  function clearFilters() {
    VIEW = P.clearedView(VIEW);
    $("pva-q").value = "";
    writeView();
    paint();
    $("pva-q").focus();
  }

  /** "All", then one option per value the list offers. */
  function optionsHtml(list) {
    return '<option value="">All</option>' + list.map((o) =>
      '<option value="' + esc(o.value) + '">' + esc(o.label) + "</option>").join("");
  }

  let OPTS_SIG = "";                   // the options last written, so an open select is not rebuilt
  /** The three selects show the filters in force (`f`, P.viewFilters); Status cannot be used
   *  while the counts are not known, like the count buttons. */
  function paintFilters(f) {
    const o = P.filterOptions(DATA);
    const sig = JSON.stringify([o.work_types, o.foremen, o.statuses]);
    if (sig !== OPTS_SIG) {
      OPTS_SIG = sig;
      $("pva-wt").innerHTML = optionsHtml(o.work_types);
      $("pva-fm").innerHTML = optionsHtml(o.foremen);
      $("pva-st").innerHTML = optionsHtml(o.statuses);
    }
    $("pva-wt").value = f.work_type;
    $("pva-fm").value = f.foreman;
    $("pva-st").value = f.status;
    $("pva-st").disabled = !o.status_known;
    // Disabled, it points at the line under the counts that says why (paintSummary).
    if (o.status_known) $("pva-st").removeAttribute("aria-describedby");
    else $("pva-st").setAttribute("aria-describedby", "pva-sum-note");
    $("pva-per").value = String(VIEW.per);
    $("pva-clear").hidden = !P.filtersActive(f);   // what filters the list, not what the view holds
  }

  /** Previous, the page numbers (the one shown is aria-current="page"; a gap is an ellipsis) and
   *  Next, disabled at the ends. */
  function pagerHtml(pg) {
    const btn = (page, label, extra) => '<button type="button" class="btn pg" data-page="'
      + esc(page) + '"' + extra + ">" + esc(label) + "</button>";
    return btn("prev", "Previous", pg.prev ? "" : " disabled")
      + pg.items.map((n) => (typeof n !== "number"
        ? '<span class="pg-gap" aria-hidden="true">' + esc(n) + "</span>"
        : btn(n, n, ' aria-label="Page ' + esc(n) + '"'
          + (n === pg.page ? ' aria-current="page"' : "")))).join("")
      + btn("next", "Next", pg.next ? "" : " disabled");
  }

  // One live region speaks at a time: "M of N jobs" (#pva-count) says a search or filter change,
  // and "Showing A–B of N" (#pva-range) is live only while the page itself moved (goPage).
  let PAGE_MOVED = false;
  function paintPager(pg) {
    $("pva-pager").hidden = !pg.total;
    $("pva-range").setAttribute("aria-live", PAGE_MOVED ? "polite" : "off");
    $("pva-range").textContent = pg.text;
    $("pva-pages").innerHTML = pg.total ? pagerHtml(pg) : "";
  }

  /** A pager button: "prev", "next" or a page number. A paint rebuilds the buttons, so the focus
   *  goes back to the one pressed, or to the page shown when that one is now disabled. A pointer
   *  click (`pointer`) also brings the top of the list back into view when it has scrolled away;
   *  a keyboard press does not, so the focused button stays on screen. */
  function goPage(which, pointer) {
    const n = which === "prev" ? VIEW.page - 1 : (which === "next" ? VIEW.page + 1 : Number(which));
    if (!(n >= 1) || n === VIEW.page) return;
    PAGE_MOVED = true;
    try { setView({ page: n }); } finally { PAGE_MOVED = false; }
    const btns = Array.from($("pva-pages").querySelectorAll("[data-page]"));
    const same = btns.find((b) => b.dataset.page === String(which) && !b.disabled);
    const cur = btns.find((b) => b.getAttribute("aria-current") === "page");
    if (same || cur) (same || cur).focus({ preventScroll: !!pointer });
    const main = $("pva-main");
    if (pointer && main.getBoundingClientRect().top < 0) main.scrollIntoView({ block: "start" });
  }

  /** A count tile. An unknown count (Raken not read) is a dash and the tile is disabled. */
  function countTileHtml(t) {
    return '<button type="button" class="sum-tile st-' + esc(t.id) + '" data-st="' + esc(t.id)
      + '" aria-pressed="' + (t.pressed ? "true" : "false") + '"' + (t.disabled ? " disabled" : "")
      + ">"
      + "<b>" + esc(t.count === null ? "—" : t.count) + "</b><span>" + esc(t.label) + "</span></button>";
  }

  /** The strip: the four counts, a line saying why they fall short (or are not known), and two
   *  figure tiles drawn as the job detail's own plan-beside-Raken pair (pairHtml). */
  function paintSummary() {
    const tiles = P.countTiles(DATA, VIEW.status);
    const lw = P.lastWeekTile(DATA);
    const bt = P.budgetTile(DATA);
    const note = P.countsNote(DATA);
    const box = $("pva-sum");
    box.hidden = !tiles.length;
    let html = tiles.map(countTileHtml).join("");
    if (tiles.length && note) html += '<p id="pva-sum-note" class="sum-note">' + esc(note) + "</p>";
    if (tiles.length && lw) {
      html += pairHtml({ label: "Last week", sub: lw.range, plan: lw.planned,
        planSub: "Planned hours", actual: lw.actual, actualSub: "Actual hours", note: lw.note });
    }
    if (tiles.length && bt) {
      html += pairHtml({ label: "Budget", plan: bt.budgeted, planSub: "Budgeted hours",
        actual: bt.projected, actualSub: "Projected total hours",
        extra: bt.over_under, over: bt.over, note: bt.note });
    }
    box.innerHTML = html;
  }

  function paint() {
    paintButton();
    const sig = JSON.stringify([VIEW, LOAD_ERR, DATA, DETAIL]);
    if (sig === LAST_SIG) return;
    LAST_SIG = sig;
    paintList();
    paintDetail();
  }

  function paintList() {
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
    paintSummary();

    // The filters in force: the count only while the counts are known, a Work type or Foreman only
    // when the list offers it. Then the page of the matching jobs.
    const f = P.viewFilters(DATA, VIEW);
    paintFilters(f);
    const shown = P.visibleProjects(projects, f.q, f.status, f);
    const pg = P.pageModel(shown.length, VIEW.page, VIEW.per);
    // A page past the end shows the last page, and the address says so. The one place a paint
    // changes the view, on purpose: only here is the number of matching jobs known. The next paint
    // sees a new signature, which is harmless.
    if (pg.page !== VIEW.page) {
      VIEW = P.nextView(VIEW, { page: pg.page });
      writeView();
    }
    $("pva-count").textContent = P.listCountText(shown.length, projects.length, f.q, f.status, f);
    $("pva-showall").hidden = !f.status;
    const body = $("pva-body");
    body.innerHTML = P.pageSlice(shown, pg).map(rowHtml).join("");
    paintSwatches(body);
    paintBars(body);
    paintPager(pg);

    const empty = !projects.length
      ? P.pvaEmptyText(DATA)
      : (!shown.length ? P.noMatchText(f.q, f.status, f) : "");
    $("pva-empty").textContent = empty;
    $("pva-empty").hidden = !empty;

    $("pva-foot").textContent = P.pvaFootText(DATA);
  }

  // ── one job's detail (#789) ───────────────────────────────────────
  // Drawn from the current DATA on every paint, so a refresh updates an open detail in place.
  function rowByKey(key) {
    const list = DATA && Array.isArray(DATA.projects) ? DATA.projects : [];
    return list.find((p) => p.key === key) || null;
  }

  /** Open a job's detail. `origin` is "pva" (its row) or "schedule" (its bar, `barKey` the bar's
   *  data-k, so Back can put the focus on it again). */
  function openDetail(key, origin, barKey) {
    if (key == null) return;
    DETAIL = { key: String(key), origin: origin === "schedule" ? "schedule" : "pva",
      barKey: barKey ? String(barKey) : "" };
    if (DETAIL.origin === "schedule") showTab("pva", false);
    paint();
    $("pd-title").focus();
  }

  /** Back (or Esc): to the list, or to the Schedule when the detail was opened from there, with
   *  the focus on the row or bar it was opened from. */
  function closeDetail() {
    if (!DETAIL) return;
    const was = DETAIL;
    DETAIL = null;
    paint();
    if (P.detailBack(was.origin).tab === "schedule") {
      showTab("schedule", false);
      const bar = Array.from(document.querySelectorAll("#grid [data-k]"))
        .find((b) => b.dataset.k === was.barKey);
      (bar || $("tab-schedule")).focus();
    } else {
      const btn = Array.from($("pva-body").querySelectorAll(".jlink"))
        .find((b) => b.dataset.key === was.key);
      if (btn) btn.focus();
    }
  }

  function fact(label, valueHtml) {
    return valueHtml ? "<dt>" + esc(label) + "</dt><dd>" + valueHtml + "</dd>" : "";
  }

  /** One of the four pairs, larger: the plan (the calendar) beside Raken's figure. The summary
   *  strip's two figure tiles are drawn with it too, with a `sub` beside the heading. */
  function pairHtml(x) {
    return '<div class="pd-pair"><h3>' + esc(x.label)
      + (x.sub ? "<small>" + esc(x.sub) + "</small>" : "") + "</h3>"
      + '<div class="pd-two"><div><b>' + esc(x.plan) + "</b><small>" + esc(x.planSub) + "</small></div>"
      + '<div class="rk"><b>' + esc(x.actual) + "</b><small>" + esc(x.actualSub) + "</small></div></div>"
      + (x.extra ? '<small class="ou' + (x.over ? " over" : "") + '">Over/under ' + esc(x.extra) + "</small>" : "")
      + (x.note ? "<small>" + esc(x.note) + "</small>" : "")
      + barHtml(x.bar, x.id === "budget") + "</div>";
  }

  /** One column of the day-by-day chart (P.dayChart). Its bar height and tick place are carried
   *  as data and set through the CSSOM by paintChart(). The column's words are its aria-label. */
  function colHtml(c) {
    return '<div class="pd-col ' + esc(c.kind) + (c.week ? " wk" : "") + (c.over ? " over" : "")
      + (c.warn ? " warn" : "")
      + '" role="listitem" aria-label="' + esc(c.label) + '">'
      + '<span class="pd-wk" aria-hidden="true">' + esc(c.week) + "</span>"
      + '<span class="pd-plot" aria-hidden="true">'
      + (c.bar != null ? '<i class="pd-bar" data-h="' + esc(c.bar) + '"></i>' : "")
      + (c.tick != null ? '<i class="pd-tick" data-b="' + esc(c.tick) + '"></i>' : "")
      + (c.kind === "missed" ? '<span class="pd-x">\u2715</span>' : "")
      + "</span>"
      + '<span class="pd-dow" aria-hidden="true">' + esc(c.dow) + "</span>"
      + '<span class="pd-dom" aria-hidden="true">' + esc(c.dom) + "</span>"
      + '<span class="pd-hrs" aria-hidden="true"><span class="pd-a">' + esc(c.actual) + "</span>"
      + '<span class="pd-p">' + esc(c.planned) + "</span></span></div>";
  }

  /** The chart's bar heights and tick places, through the CSSOM (the CSP forbids style
   *  attributes). */
  function paintChart(root) {
    root.querySelectorAll(".pd-bar[data-h]").forEach((el) => { el.style.height = pct(el.dataset.h); });
    root.querySelectorAll(".pd-tick[data-b]").forEach((el) => { el.style.bottom = pct(el.dataset.b); });
  }

  /** The Mobilizations and Punches, each with its dates, Crew size and Google Calendar link. */
  function eventHtml(e) {
    return '<li><span class="pd-kind">' + esc(e.kind) + "</span>"
      + '<span class="pd-when">' + esc(e.dates) + "</span>"
      + '<span class="pd-crew">' + esc(e.crew) + (e.foreman ? " · Foreman " + esc(e.foreman) : "") + "</span>"
      + (e.link ? '<a href="' + esc(e.link) + '" target="_blank" rel="noopener noreferrer">'
        + "Open in Google Calendar " + icon("external", 13) + "</a>" : "")
      + "</li>";
  }

  function paintDetail() {
    $("pva-list").hidden = !!DETAIL;
    $("pva-detail").hidden = !DETAIL;
    if (!DETAIL) { SCROLLED_FOR = ""; return; }
    $("pd-back").textContent = P.detailBack(DETAIL.origin).label;
    $("pd-asof").textContent = DATA ? P.asOfText(DATA) : "";
    const p = rowByKey(DETAIL.key);
    $("pd-body").hidden = !p;
    if (!p) {
      // A refresh can drop a job out of the window while its detail is open.
      $("pd-title").textContent = "This job is no longer in Plan vs Actual";
      $("pd-sub").textContent = "";
      $("pd-chips").innerHTML = "";
      $("pd-sw").style.background = "";
      return;
    }

    $("pd-title").textContent = (p.job_number ? p.job_number + " " : "") + (p.name || "Untitled");
    $("pd-sub").textContent = subOf(p);
    $("pd-sw").style.background = P.colorOf(p) || "";
    const why = P.rakenLabel(p);
    $("pd-chips").innerHTML = statusChipsHtml(p) + labelChips(p)
      + (why ? "<small>" + esc(why) + "</small>" : "");

    const pairs = $("pd-pairs");
    pairs.innerHTML = P.detailPairs(p).map(pairHtml).join("");
    paintBars(pairs);

    const chart = P.dayChart(p.day_by_day);
    const box = $("pd-chart");
    box.innerHTML = chart.columns.map(colHtml).join("");
    paintChart(box);
    $("pd-scale").textContent = chart.columns.length
      ? "Top of the chart: " + chart.scale + (chart.scale === 1 ? " person" : " people")
      : "No Workdays are booked for this job.";
    if (SCROLLED_FOR !== DETAIL.key) {
      // A long job opens on its latest days: scroll the chart box (never the page) so the last day
      // before today is in view.
      SCROLLED_FOR = DETAIL.key;
      const scroller = box.parentElement;
      const future = box.querySelector(".pd-col.future");
      scroller.scrollLeft = future
        ? Math.max(0, future.offsetLeft - box.offsetLeft - scroller.clientWidth * 0.6)
        : scroller.scrollWidth;
    }

    const events = P.detailEvents(p);
    $("pd-events").innerHTML = events.length ? events.map(eventHtml).join("")
      : '<li class="muted">No Mobilizations read.</li>';

    const flags = P.detailFlags(p).map((f) => '<span class="chip">' + esc(f) + "</span>").join("");
    $("pd-facts").innerHTML =
      fact("Job number", esc(p.job_number || ""))
      + fact("Work type", esc(P.workTypeOf(p)))
      + fact("Foreman", esc(p.foreman || ""))
      + fact("Start", esc(P.dayLong(p.start)))
      + fact("Deadline", esc(P.dayLong(p.deadline)) + " <span class=\"chip\">" + esc(P.leftLabel(p)) + "</span>")
      + fact("Marked", flags);

    // "Open project": the same door, in the same words, as the Schedule's details panel.
    const pf = P.projectFoot(p.project, p.job_number);
    let foot = "";
    if (pf && pf.href) {
      foot = '<a class="btn" href="' + esc(pf.href) + '">' + icon("folder", 14) + " "
        + esc(pf.label) + "</a>";
    } else if (pf) {
      foot = '<span class="muted">' + esc(pf.note) + "</span>";
    }
    $("pd-foot").innerHTML = foot;
    $("pd-foot").hidden = !foot;
  }

  /** Esc closes the detail, only while it is in view: never from the Schedule, and never under
   *  the Schedule's details panel, which handles its own Esc. */
  function onEscape(e) {
    if (e.key !== "Escape" || !DETAIL || $("dlg").open || $("panel-pva").hidden) return;
    e.preventDefault();
    closeDetail();
  }

  /** The Schedule's one question (js/project-calendar.js), by a bar's event id: open that job's
   *  detail ({opened: true}), or say what the details panel should ({opened: false, line}), the
   *  line "" while the list has not loaded, since the page cannot know the job is outside it. */
  function openEvent(id, barKey) {
    const found = P.pvaLookup(DATA, id);
    if (found.state === "found" && found.row.key != null) {
      openDetail(found.row.key, "schedule", barKey);
      return { opened: true, line: "" };
    }
    return { opened: false, line: found.state === "absent" ? P.notInPvaLine(DATA) : "" };
  }

  window.TWPva = { openEvent: openEvent };

  // ── wiring (delegated; CSP forbids inline handlers) ───────────────
  $("pva-refresh").addEventListener("click", refreshNow);
  $("pva-download").addEventListener("click", downloadNow);
  $("pva-sum").addEventListener("click", (e) => {
    const b = e.target.closest("[data-st]");
    if (b) setStatus(b.dataset.st);
  });
  $("pva-showall").addEventListener("click", clearStatus);
  $("pva-clear").addEventListener("click", clearFilters);
  $("pva-wt").addEventListener("change", (e) => setView({ work_type: e.target.value || "" }));
  $("pva-fm").addEventListener("change", (e) => setView({ foreman: e.target.value || "" }));
  $("pva-st").addEventListener("change", (e) => setView({ status: e.target.value || "" }));
  $("pva-per").addEventListener("change", (e) => setView({ per: Number(e.target.value) }));
  $("pva-pages").addEventListener("click", (e) => {
    const b = e.target.closest("[data-page]");
    if (b && !b.disabled) goPage(b.dataset.page, e.detail > 0);   // detail 0: the keyboard
  });
  $("pva-body").addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    const tr = e.target.closest("tr[data-key]");
    if (tr) openDetail(tr.dataset.key, "pva", "");
  });
  $("pd-back").addEventListener("click", closeDetail);
  document.addEventListener("keydown", onEscape);
  $("pva-q").value = VIEW.q;
  $("pva-q").addEventListener("input", (e) => setView({ q: e.target.value || "" }));
  $("pva-q").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.target.value = ""; setView({ q: "" }); }
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

  writeView();                         // the view's junk values leave the address at once
  showTab(P.tabFromHash(location.hash), false);
  paint();
  load();
  setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
})();
