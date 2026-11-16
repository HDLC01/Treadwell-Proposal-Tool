// Project Analytics, the Schedule tab: the crews' job schedule, read from the "Treadwell Projects"
// Google calendar. The Plan vs Actual tab, and the switching between the two, is
// js/plan-vs-actual.js. Externalized (no inline scripts; CSP). Do not add inline handlers.
//
// READ ONLY, ON PURPOSE. This page never writes to Google and stores nothing of its own: no
// create, edit, drag or delete control exists anywhere on it. The schedule is kept in Google
// Calendar by the people who run the crews, and a second place to change it would be a second
// version of the truth. A bar opens its job's detail in Plan vs Actual (#789) when the list holds
// the bar's event, found by the EVENT ID (P.pvaLookup); otherwise it opens a details panel, whose
// way out is "Open in Google Calendar", saying so when the job is outside the list's window.
//
// WHAT THE SERVER HAS ALREADY DONE (GET /api/project-calendar). It reads that one calendar as the
// connected Google account, parses each free-text title into Job number, Crew size, Mobilization, Foreman
// and flags, and turns Google's dates into inclusive Central days. When the calendar is not
// connected it says so (connected:false) and this page shows a plain message, not an error. When
// Google fails it serves the last good copy with stale:true, and this page says when that copy is
// from.
//
// WHAT THIS FILE DOES. Fetch, then paint. All layout and arithmetic (bars across weeks, lanes,
// workdays, Deadlines, filtering) lives in js/project-calendar-core.js, which is pure and tested
// under node; the range and paging maths is the Bid Calendar's js/calendar-core.js, read here and
// never edited from here.
//
// Every text value from the API is escaped: titles are typed by hand in Google. Every colour and
// grid position is set through element.style AFTER the markup is in place, never as an inline
// style attribute, so the nginx CSP needs no widening.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const K = window.TWCal;
  const P = window.TWProjCal;
  const icon = (name, size) => (typeof window.TWIcon === "function" ? window.TWIcon(name, size) : "");

  // Every request waits for auth.js to mint the bearer token first. The wait lives in this one
  // helper, as on the Bid Calendar, because a caller that forgets it 401s on first paint.
  const api = async (path) => {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    return fetch(TW.resolveApiBase() + path, { headers: TW.authHeaders() });
  };

  // ── state ─────────────────────────────────────────────────────────
  const SK = { mode: "tw_pcal_mode", q: "tw_pcal_q" };
  const ss = (k, d) => { try { const v = sessionStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
  const ssSet = (k, v) => { try { v ? sessionStorage.setItem(k, v) : sessionStorage.removeItem(k); } catch {} };

  const POLL_MS = 5 * 60 * 1000;       // the server caches for about this long anyway

  let MODE = P.MODES.some((m) => m.id === ss(SK.mode, "")) ? ss(SK.mode, "two") : "two";
  let Q = ss(SK.q, "");
  let WORK_TYPES = [];                 // the server's colour -> Work type list, for the legend
  let TODAY = P.centralToday();        // the Central calendar's today, not the laptop's
  let ANCHOR = TODAY;

  // Responses by range ("from..to"), so paging back to a range already seen paints at once
  // instead of flashing a loading state. Kept small; a fresh read replaces an entry.
  const CACHE = {};
  const CACHE_ORDER = [];
  const CACHE_MAX = 12;
  const ERR = {};                      // range key -> why the last read of it failed
  let CONNECTED = null;                // the last answer the server gave about the connection
  let SEQ = 0;                         // newest range request wins
  let LAST_SIG = "";                   // anti-blink: skip identical repaints
  let BY_KEY = {};                     // event key -> event, for the details panel

  const rangeKey = (r) => r.from + ".." + r.to;

  function remember(key, body) {
    if (!CACHE[key]) CACHE_ORDER.push(key);
    CACHE[key] = body;
    while (CACHE_ORDER.length > CACHE_MAX) delete CACHE[CACHE_ORDER.shift()];
  }

  /** A stable key per event, so a re-read of unchanged data repaints nothing. Google's id where
   *  there is one; otherwise its position. `src` names the read the event came from. */
  function keyEvents(events, src) {
    events.forEach((e, i) => {
      e._k = src + ":" + (e.id != null && e.id !== "" ? String(e.id) : "#" + i);
    });
  }

  // ── fetch ─────────────────────────────────────────────────────────
  /** One read of the calendar. Never throws: answers {ok:true, body} or {ok:false, error}. */
  async function read(from, to, src) {
    try {
      const r = await api("/api/project-calendar?start=" + encodeURIComponent(from)
                          + "&end=" + encodeURIComponent(to));
      const body = await r.json().catch(() => null);
      if (!r.ok || !body || body.ok === false) {
        const why = (body && (body.detail || body.error)) || ("HTTP " + r.status);
        return { ok: false, error: typeof why === "string" ? why : "The server refused the request." };
      }
      body.events = (Array.isArray(body.events) ? body.events : []).filter((e) => e && typeof e === "object");
      keyEvents(body.events, src);
      return { ok: true, body: body };
    } catch (err) {
      return { ok: false, error: "Couldn't reach the server." };
    }
  }

  async function loadRange() {
    const range = K.rangeFor(ANCHOR, MODE);
    const key = rangeKey(range);
    const mine = ++SEQ;
    const res = await read(range.from, range.to, "r");
    if (res.ok) {
      remember(key, res.body);         // worth keeping even if the view has moved on
      if (Array.isArray(res.body.work_types)) WORK_TYPES = res.body.work_types;
      CONNECTED = res.body.connected !== false;
      delete ERR[key];
    } else {
      ERR[key] = res.error;
    }
    if (mine !== SEQ) return;          // the view moved on while this was in flight
    paint();
  }

  function refreshAll() {
    TODAY = P.centralToday();
    loadRange();
  }

  // ── rendering helpers ─────────────────────────────────────────────
  function visible(events) {
    return P.filterEvents(events, { q: Q });
  }

  function showAlert(text) {
    $("alert").textContent = text || "";
    $("alert").hidden = !text;
  }

  function showState(html) {
    $("state").innerHTML = html;
    $("state").hidden = false;
    $("main").hidden = true;
  }

  function safeLink(u) {
    return typeof u === "string" && /^https:\/\//i.test(u.trim()) ? u.trim() : "";
  }

  function barHtml(sg) {
    const ev = sg.ev;
    const parts = P.barParts(ev);
    const cls = ["bar"];
    if (!sg.starts) cls.push("cont-l");
    if (!sg.ends) cls.push("cont-r");
    if (sg.ends) cls.push("dl-end");   // every bar is a Duration: its last day is the Deadline
    const tip = (ev.title || parts.name) + " · " + P.spanLabel(ev);
    const aria = parts.name + (parts.meta ? ", " + parts.meta : "") + ", " + P.spanLabel(ev)
      + ", " + P.workTypeOf(ev) + (sg.ends ? ", Deadline " + P.dayLong(sg.ev.deadline || P.spanOf(ev).last) : "")
      + (!sg.starts ? ", continued from the week before" : "");
    return '<button type="button" class="' + cls.join(" ") + '"'
      + ' data-k="' + esc(ev._k) + '" data-c="' + sg.col + '" data-s="' + sg.span + '"'
      + ' data-l="' + sg.lane + '" data-color="' + esc(P.colorOf(ev) || "") + '"'
      + ' title="' + esc(tip) + '" aria-label="' + esc(aria) + '">'
      + '<span class="bn">' + esc(parts.name) + "</span>"
      + (parts.meta ? '<span class="bm">' + esc(parts.meta) + "</span>" : "")
      + (sg.ends ? '<span class="dlm">Deadline</span>' : "")
      + "</button>";
  }

  function weekHtml(week, wi) {
    const days = week.days.map((d, i) => {
      const cls = ["day"];
      if (K.isWeekend(d)) cls.push("we");
      if (d === TODAY) cls.push("today");
      if (MODE === "month" && d.slice(0, 7) !== ANCHOR.slice(0, 7)) cls.push("other-month");
      return '<div class="' + cls.join(" ") + '" data-col="' + i + '">'
        + '<div class="dn">' + Number(d.slice(8, 10))
        + (d === TODAY ? ' <span class="tag">Today</span>' : "") + "</div></div>";
    }).join("");
    return '<div class="week" data-w="' + wi + '" data-lanes="' + week.lanes + '">'
      + days + week.segments.map(barHtml).join("") + "</div>";
  }

  /** Grid rows, bar positions and colours, applied through the CSSOM once the markup exists. */
  function placeBars(grid) {
    const minH = MODE === "month" ? 96 : 128;
    grid.querySelectorAll(".week").forEach((w) => {
      const lanes = Number(w.dataset.lanes) || 0;
      const fill = Math.max(8, minH - 26 - lanes * 27);
      w.style.gridTemplateRows = "24px" + (lanes ? " repeat(" + lanes + ", 24px)" : "") + " " + fill + "px";
      w.querySelectorAll(".day").forEach((d) => {
        d.style.gridColumn = String(Number(d.dataset.col) + 1);
        d.style.gridRow = "1 / " + (lanes + 3);
      });
      w.querySelectorAll(".bar").forEach((b) => {
        b.style.gridColumn = (Number(b.dataset.c) + 1) + " / span " + Number(b.dataset.s);
        b.style.gridRow = String(Number(b.dataset.l) + 2);
        const c = b.dataset.color;
        if (c && /^#[0-9a-f]{6}$/i.test(c)) {
          b.style.background = c;
          b.style.color = P.textOn(c) || "#ffffff";
        }
      });
    });
  }

  // Drawn from the server's list (the one copy of colour -> Work type); swatches are painted
  // through the CSSOM in paintSwatches, like the bars.
  function legendHtml() {
    return WORK_TYPES.map((w) => '<span><i class="sw" data-color="' + esc(w.color || "") + '"></i>'
      + esc(w.name) + "</span>").join("")
      + "<span>Any other colour, or none: " + esc(P.WORK_TYPE_UNKNOWN_LABEL) + "</span>"
      + '<span><span class="mk">Deadline</span>the last day of every bar</span>';
  }

  function paintSwatches(root) {
    root.querySelectorAll(".sw[data-color]").forEach((el) => {
      const c = el.dataset.color;
      if (c && /^#[0-9a-f]{6}$/i.test(c)) el.style.background = c;
    });
  }

  // ── paint ─────────────────────────────────────────────────────────
  function paint() {
    const range = K.rangeFor(ANCHOR, MODE);
    const key = rangeKey(range);
    const cached = CACHE[key] || null;
    const loadErr = ERR[key] || "";
    const sig = JSON.stringify([key, MODE, Q, TODAY, loadErr, CONNECTED,
      cached && [cached.connected, cached.stale, cached.fetched_at, cached.error, cached.notice,
        cached.events]]);
    if (sig === LAST_SIG) return;
    LAST_SIG = sig;

    // The details panel looks events up by key.
    BY_KEY = {};
    (cached && cached.events || []).forEach((e) => { BY_KEY[e._k] = e; });

    $("range").textContent = K.rangeLabel(range, MODE);
    $("today").disabled = K.isCurrent(range, TODAY);
    $("modes").innerHTML = P.MODES.map((m) =>
      '<button type="button" data-mode="' + m.id + '" aria-pressed="'
      + (m.id === MODE ? "true" : "false") + '">' + esc(m.label) + "</button>").join("");

    let current = cached;
    let pending = false;
    if (!current) {
      if (loadErr) {
        // Nothing to show for this range and the read failed: say so plainly.
        $("toolbar").hidden = CONNECTED === false;
        showAlert("");
        showState("<b>Couldn't load the Schedule</b>" + esc(loadErr)
          + " It will try again in a few minutes.");
        return;
      }
      if (CONNECTED !== true) {
        showState("Loading the Schedule…");
        return;
      }
      // Paging to a range not read yet, on a calendar known to be connected: draw the new range's
      // empty weeks at once (no flash of a loading box), and let the read fill them.
      current = { connected: true, stale: false, error: null, events: [] };
      pending = true;
    }

    // Not connected: a plain fact, not a failure.
    if (current.connected === false) {
      $("toolbar").hidden = true;
      showAlert("");
      showState("<b>The Treadwell Projects calendar is not connected yet</b>"
        + "Once it is connected, the crews' schedule from Google Calendar shows here.");
      return;
    }

    $("toolbar").hidden = false;
    const events = current.events || [];

    // The stale notice wins over the refresh-failed one: either way the bars are a saved copy,
    // and "from when" is the useful part. The server's `error` (the read FAILED, e.g. a sign-in
    // to reconnect) follows whenever there are bars to show; with no bars the state box below
    // says it instead. The server's `notice` (the read WORKED but hides something, e.g. free/busy
    // access) always goes here, never in the failure box: an empty month read that way is still
    // an empty month. textContent: never markup.
    const notice = [];
    if (current.stale) {
      const at = P.centralStamp(current.fetched_at);
      notice.push(at ? "Showing the last copy from " + at + " (Central)."
                    : "Showing the last copy of the calendar.");
    } else if (loadErr) {
      notice.push("Couldn't refresh just now (" + loadErr + "). Showing what was loaded before.");
    }
    if (current.error && events.length) notice.push(String(current.error));
    if (current.notice) notice.push(String(current.notice));
    showAlert(notice.join(" "));

    if (!events.length && current.error) {
      showState("<b>Couldn't read the Treadwell Projects calendar</b>" + esc(current.error));
      return;
    }

    $("state").hidden = true;
    $("main").hidden = false;

    const shown = visible(events);
    const lay = P.layout(shown, range);
    const note = [];
    if (pending) note.push("Loading this range…");
    else if (!events.length) note.push("Nothing is booked in this range.");
    else if (!shown.length) note.push("Nothing in this range matches the search.");
    if (lay.unplaced) {
      note.push(lay.unplaced + " event" + (lay.unplaced === 1 ? " has" : "s have")
        + " no readable date and " + (lay.unplaced === 1 ? "is" : "are") + " not drawn.");
    }
    $("note").textContent = note.join(" ");
    $("note").hidden = !note.length;

    $("dows").innerHTML = K.DOW.map((d) => '<div class="dow">' + d.slice(0, 3) + "</div>").join("");
    const grid = $("grid");
    grid.innerHTML = lay.weeks.map(weekHtml).join("");
    placeBars(grid);

    $("legend").innerHTML = legendHtml();
    paintSwatches($("legend"));
  }

  // ── details panel ─────────────────────────────────────────────────
  function fact(label, valueHtml) {
    return valueHtml ? "<dt>" + esc(label) + "</dt><dd>" + valueHtml + "</dd>" : "";
  }

  /** `line` is said under the title: why the bar did not open the job's Plan vs Actual detail. */
  function openDetails(ev, line) {
    if (!ev) return;
    const parts = P.barParts(ev);
    const color = P.colorOf(ev);
    const total = P.workdaysOf(ev);
    const left = P.workdaysLeft(ev, TODAY);
    const span = P.spanOf(ev);

    $("dlg-title").textContent = parts.name;
    $("dlg-raw").textContent = ev.title ? "In Google: " + ev.title : "";
    $("dlg-raw").hidden = !ev.title;
    $("dlg-note").textContent = line || "";
    $("dlg-note").hidden = !line;
    const sw = $("dlg-sw");
    sw.style.background = color || "";

    const dl = P.validDay(ev.deadline) ? ev.deadline : (span && span.last);
    const st = P.deadlineStatus(dl, TODAY);
    const n = P.daysUntil(dl, TODAY);
    const dlLabel = st === "today" ? "Today" : st === "overdue" ? "Passed"
      : (n === 1 ? "Tomorrow" : "In " + n + " days");
    const deadline = esc(P.dayLong(dl))
      + (st ? ' <span class="chip st-' + st + '">' + esc(dlLabel) + "</span>" : "");

    const flags = P.flagsOf(ev).map((f) => '<span class="chip">' + esc(f) + "</span>").join("");
    const facts =
      fact("Dates", esc(P.spanLabel(ev)) || '<span class="chip">No readable date</span>')
      + fact("Workdays", span ? esc(String(total)) + " <span class=\"chip\">Mon to Fri</span>" : "")
      + fact("Workdays left", span ? esc(String(left)) + (total ? " of " + esc(String(total)) : "") : "")
      + fact("Deadline", deadline)
      + fact("Job number", esc(ev.job_number || ""))
      + fact("Crew size", typeof ev.crew_size === "number" ? esc(String(ev.crew_size)) : "")
      + fact("Work type", esc(P.workTypeOf(ev)))
      + fact("Foreman", esc(ev.foreman || ""))
      + fact("Marked", flags);
    $("dlg-facts").innerHTML = facts;

    const foot = [];
    const href = P.projectHref(ev.project);
    if (href) {
      foot.push('<a class="btn" href="' + esc(href) + '">'
        + icon("folder", 14) + " Open project: " + esc(ev.project.name || "this project") + "</a>");
    } else if (ev.job_number) {
      foot.push('<span class="muted">No project in this tool has Job number '
        + esc(ev.job_number) + " yet.</span>");
    }
    const link = safeLink(ev.html_link);
    if (link) {
      foot.push('<a class="btn" href="' + esc(link) + '" target="_blank" rel="noopener noreferrer">'
        + "Open in Google Calendar " + icon("external", 13) + "</a>");
    }
    $("dlg-foot").innerHTML = foot.join("");
    $("dlg-foot").hidden = !foot.length;

    const dlg = $("dlg");
    if (typeof dlg.showModal === "function") { if (!dlg.open) dlg.showModal(); }
    else dlg.setAttribute("open", "");
    $("dlg-close").focus();
  }

  function closeDetails() {
    const dlg = $("dlg");
    if (typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open");
  }

  // ── wiring (delegated; CSP forbids inline handlers) ───────────────
  $("prev").innerHTML = icon("chev-left", 15);
  $("next").innerHTML = icon("chev-right", 15);
  $("dlg-close").innerHTML = icon("x", 16);
  $("q").value = Q;

  const go = (dir) => { ANCHOR = K.shift(ANCHOR, MODE, dir); paint(); loadRange(); };
  $("prev").addEventListener("click", () => go(-1));
  $("next").addEventListener("click", () => go(1));
  $("today").addEventListener("click", () => {
    TODAY = P.centralToday(); ANCHOR = TODAY; paint(); loadRange();
  });
  $("modes").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mode]");
    if (!b || b.dataset.mode === MODE) return;
    // Re-anchor on the day being looked at, so switching length keeps those days on screen.
    const focus = P.focusDay(K.rangeFor(ANCHOR, MODE), TODAY);
    MODE = b.dataset.mode;
    ssSet(SK.mode, MODE);
    ANCHOR = MODE === "month" ? focus.slice(0, 8) + "01" : K.startOfWeek(focus);
    paint();
    loadRange();
  });
  $("q").addEventListener("input", (e) => { Q = e.target.value || ""; ssSet(SK.q, Q); paint(); });
  $("q").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.target.value = ""; Q = ""; ssSet(SK.q, ""); paint(); }
  });

  // A bar opens its job's Plan vs Actual detail (js/plan-vs-actual.js, window.TWPva) when the list
  // holds the bar's event; otherwise the details panel, saying why once the list has loaded.
  const openFrom = (e) => {
    const b = e.target.closest("[data-k]");
    const ev = b && BY_KEY[b.dataset.k];
    if (!ev) return;
    const pva = window.TWPva;
    const found = pva ? pva.lookup(ev.id) : { state: "unknown", row: null };
    if (found.state === "found" && pva.openFromSchedule(found.row, b.dataset.k)) return;
    openDetails(ev, found.state === "absent" ? P.notInPvaLine(pva.data()) : "");
  };
  $("grid").addEventListener("click", openFrom);
  $("dlg-close").addEventListener("click", closeDetails);
  // A click on the backdrop lands on the <dialog> itself, outside its body.
  $("dlg").addEventListener("click", (e) => { if (e.target === $("dlg")) closeDetails(); });

  // Arrow keys page the calendar, "t" goes to today. Only while the Schedule tab is shown, not while
  // typing, and not with the panel open.
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if ($("panel-schedule").hidden || $("dlg").open) return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
    if (e.key === "ArrowLeft") go(-1);
    else if (e.key === "ArrowRight") go(1);
    else if (e.key === "t" || e.key === "T") { TODAY = P.centralToday(); ANCHOR = TODAY; paint(); loadRange(); }
  });

  paint();
  refreshAll();
  setInterval(() => { if (!document.hidden) refreshAll(); }, POLL_MS);
  // A tab left open overnight must not keep "Today" on yesterday.
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshAll(); });
})();
