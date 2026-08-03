// Bid Calendar — every bid we're chasing, on the day it's due.
// Externalized (no inline scripts; CSP). Do not add inline handlers.
//
// WHY THIS PAGE EXISTS, and why it is not a copy of Basisboard's calendar.
//
// Basisboard has one, and it is where the deadlines live, so this page reads the same
// data. But four things about theirs make it hard to work from, and this page fixes each:
//
//   1. Their times are in the wrong zone. Theirs shows a cluster of bids at 3:00 AM and
//      5:00 AM; nobody sets a 3 AM bid deadline. Those are evening cut-offs rendered
//      somewhere other than Central. Every day and time here is America/Chicago, the
//      rule the rest of this app already follows.
//   2. Every card carries identical weight, so a bid due in three hours looks like one
//      due in nine days. Here the left stripe and tint triage before you read a word.
//   3. The value isn't on the card, and it's the number that decides what you pick up
//      first. Here it's on the card and totalled in the day header.
//   4. Bids with no deadline are hidden entirely. Those are exactly the ones that go
//      quiet and get forgotten, so they get a tray instead of oblivion.
//
// DATA. /api/analytics, the same dataset the dashboard uses — it is the only one carrying
// bid_deadline_at, the GC companies and the estimator ids. No new endpoint. All the date
// arithmetic lives in calendar-core.js, which is pure and tested under node.
//
// READ-ONLY. Our whole Basisboard integration is read-only, so there is no "Add bid"
// here: that button would write to their system. "Open in BasisBoard ↗" links out, and
// every card links to the bid in Basisboard rather than pretending to be editable.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const C = window.TWCrm;
  const A = window.TWAgg;
  const K = window.TWCal;

  const api = (path, opts) => fetch(TW.resolveApiBase() + path,
    Object.assign({}, opts || {}, { headers: TW.authHeaders((opts || {}).headers) }));

  // Compact money, because a day header has room for "$721k" and not for "$721,400".
  function money(n) {
    if (typeof n !== "number" || !isFinite(n) || n <= 0) return "";
    if (n >= 1e6) return "$" + (n / 1e6).toFixed(n >= 1e7 ? 0 : 2).replace(/\.0+$/, "") + "M";
    if (n >= 1e3) return "$" + Math.round(n / 1e3) + "k";
    return "$" + Math.round(n);
  }
  const moneyFull = (n) => (typeof n === "number" && isFinite(n)
    ? "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "");

  // ── state ─────────────────────────────────────────────────────────
  const SK = { mode: "tw_cal_mode", est: "tw_cal_est", stage: "tw_cal_stage", q: "tw_cal_q" };
  const ss = (k, d) => { try { const v = sessionStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
  const ssSet = (k, v) => { try { v ? sessionStorage.setItem(k, v) : sessionStorage.removeItem(k); } catch {} };

  let ROWS = [];
  let NAMES = {};              // estimator id -> display name
  let COMPANIES = {};          // company id  -> name
  let STAGES = [];
  let MODE = K.MODES.some((m) => m.id === ss(SK.mode, "")) ? ss(SK.mode, "two") : "two";
  let EST = ss(SK.est, "");
  let STAGE = ss(SK.stage, "");
  let Q = ss(SK.q, "");
  let TODAY = A.today();       // the Central calendar's today, not the laptop's
  let ANCHOR = TODAY;
  let LAST_SIG = "";           // same anti-blink guard as the Pipeline board

  // ── filtering ─────────────────────────────────────────────────────
  // Archived bids are dropped: the dataset is deliberately the whole HISTORY (so the
  // dashboard's past years total correctly), but a calendar is about work in front of
  // you, and a closed 2024 job with a deadline this week is noise.
  function inScope(r) {
    if (r.archived) return false;
    if (EST === "_none") { if (K.hasEstimator(r)) return false; }
    else if (EST && (r.estimator_ids || []).indexOf(EST) < 0) return false;
    if (STAGE && r.stage_id !== STAGE) return false;
    const q = Q.trim().toLowerCase();
    if (!q) return true;
    return [r.name, r.location, r.city, r.region]
      .concat((r.company_ids || []).map((id) => COMPANIES[id] || ""))
      .concat((r.estimator_ids || []).map((id) => NAMES[id] || ""))
      .some((v) => String(v || "").toLowerCase().includes(q));
  }

  // ── rendering ─────────────────────────────────────────────────────
  function estimatorChip(r) {
    const ids = (r.estimator_ids || []).filter(Boolean);
    if (!ids.length) {
      return '<span class="tw-av av-none" title="No estimator assigned">?</span>'
        + '<span class="soft">Unassigned</span>';
    }
    const name = NAMES[ids[0]] || "";
    // Same shared chip as the CRM board and Projects, so one person is one colour
    // everywhere. A second estimator is counted, not drawn — two chips on a card this
    // size is unreadable and the name is what you actually scan for.
    return C.avatarHtml(name) + esc(C.nameOf(name).split(/\s+/)[0] || name)
      + (ids.length > 1 ? ' <span class="plus">+' + (ids.length - 1) + "</span>" : "");
  }

  function gcLine(r) {
    const names = (r.company_ids || []).map((id) => COMPANIES[id]).filter(Boolean);
    if (!names.length) return "";
    return '<div class="cgc"><b>' + esc(names[0]) + "</b>"
      + (names.length > 1 ? '<span class="plus">+' + (names.length - 1) + "</span>" : "")
      + "</div>";
  }

  /** The deadline's clock time, in Central. Absent for a bid with no deadline. */
  function timeLabel(r) {
    if (!r.bid_deadline_at) return "No deadline";
    const d = new Date(r.bid_deadline_at);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString("en-US", {
      timeZone: A.BIZ_TZ, hour: "numeric", minute: "2-digit",
    });
  }

  function card(r, urg) {
    const href = "https://app.basisboard.com/projects/" + encodeURIComponent(r.id || "");
    const val = money(r.quote);
    return '<a class="card u-' + urg + '" href="' + esc(href) + '"'
      + ' target="_blank" rel="noopener noreferrer"'
      + ' title="' + esc(r.name || "") + (val ? " — " + moneyFull(r.quote) : "") + '">'
      + '<p class="cname">' + esc(r.name || "Untitled") + "</p>"
      + '<div class="cmeta">' + estimatorChip(r)
      + '<span class="when">' + esc(timeLabel(r)) + "</span>"
      + (val ? '<span class="amt">' + val + "</span>" : "")
      + "</div>" + gcLine(r) + "</a>";
  }

  function dayCell(day, rows) {
    const load = K.dayLoad(rows);
    const urg = K.urgency(day, TODAY);
    const cls = ["cell"];
    if (K.isWeekend(day)) cls.push("we");
    if (day === TODAY) cls.push("today");
    else if (urg === "late") cls.push("past");
    if (MODE === "month" && day.slice(0, 7) !== ANCHOR.slice(0, 7)) cls.push("other-month");
    // "Heavy" is relative to a working day, not to the rest of the range: three bids
    // due on one day is a lot regardless of what the fortnight looks like.
    if (load.count >= 3) cls.push("heavy");

    const num = Number(day.slice(8, 10));
    const head = '<div class="dnum"><b>' + num + "</b>"
      + (day === TODAY ? ' <span class="tag">Today</span>' : "")
      + (load.count
        ? ' <span class="load">' + load.count + (load.value ? " · " + money(load.value) : "") + "</span>"
        : "")
      + "</div>";
    return '<div class="' + cls.join(" ") + '">' + head
      + rows.map((r) => card(r, K.urgency(day, TODAY))).join("") + "</div>";
  }

  function paint() {
    const range = K.rangeFor(ANCHOR, MODE);
    const rows = A.decorate(ROWS.filter(inScope));
    const buckets = K.bucket(rows, range);
    const s = K.summarize(buckets, TODAY);

    // Anti-blink: this page polls, and paint() replaces the grid wholesale. Repainting
    // identical data destroyed and rebuilt every cell for no reason — the same bug the
    // Pipeline board and Lead Inbox had. The signature covers everything that changes
    // what is drawn, so navigating and filtering still repaint at once.
    const sig = JSON.stringify([range.from, range.to, MODE, EST, STAGE, Q, TODAY,
                                buckets.byDay, buckets.undated]);
    if (sig === LAST_SIG) return;
    LAST_SIG = sig;

    $("range").textContent = K.rangeLabel(range, MODE);
    $("today").disabled = K.isCurrent(range, TODAY);

    $("sum").hidden = false;
    $("sum").innerHTML = [
      ["Bids in view", s.bids, ""],
      ["Value in view", money(s.value) || "$0", ""],
      ["Due today", s.due_today, "s-late"],
      ["Due in " + K.SOON_DAYS + " days", s.due_soon, "s-soon"],
      ["No estimator", s.unassigned, s.unassigned ? "s-soon" : ""],
      ["No deadline", s.undated, ""],
    ].map(([label, v, cls]) =>
      '<div class="' + cls + '"><b>' + esc(String(v)) + "</b><span>" + esc(label) + "</span></div>"
    ).join("");

    $("dows").hidden = false;
    $("dows").innerHTML = K.DOW.map((d) => '<div class="dow">' + d + "</div>").join("");

    const grid = $("grid");
    grid.className = "grid";
    grid.innerHTML = range.days.map((d) => dayCell(d, buckets.byDay[d] || [])).join("");

    const tray = $("tray");
    tray.hidden = !buckets.undated.length;
    if (buckets.undated.length) {
      tray.innerHTML = "<h2>No deadline set · " + buckets.undated.length + " bid"
        + (buckets.undated.length === 1 ? "" : "s") + "</h2>"
        + "<p>Basisboard's calendar hides these entirely. They're the ones that go quiet and "
        + "get forgotten, so they sit here until somebody dates them.</p>"
        + '<div class="row">'
        + buckets.undated.map((r) => card(r, "none")).join("") + "</div>";
    }

    const legend = $("legend");
    legend.hidden = false;
    legend.innerHTML =
      '<span><i style="background:var(--late)"></i>Due today or overdue</span>'
      + '<span><i style="background:var(--soon)"></i>Due within ' + K.SOON_DAYS + ' days</span>'
      + '<span><i style="background:var(--calm)"></i>Later</span>'
      + '<span><span class="tw-av av-none">?</span>No estimator</span>'
      + "<span>Day header shows count · total value</span>"
      + (buckets.outside
        ? "<span>" + buckets.outside + " bid" + (buckets.outside === 1 ? "" : "s")
          + " due outside this range</span>"
        : "");
  }

  // ── filter vocabularies ───────────────────────────────────────────
  // Built from the data, with counts, so the dropdowns can't offer a stage nobody uses
  // or an estimator who has left. A selection that no longer exists is dropped rather
  // than silently filtering everything to nothing.
  function fillFilters() {
    const live = ROWS.filter((r) => !r.archived);

    const estCounts = {};
    let noneCount = 0;
    live.forEach((r) => {
      const ids = (r.estimator_ids || []).filter(Boolean);
      if (!ids.length) noneCount++;
      ids.forEach((id) => { estCounts[id] = (estCounts[id] || 0) + 1; });
    });
    const est = $("est");
    const estOpts = ['<option value="">Any estimator</option>']
      .concat(Object.keys(estCounts)
        .sort((a, b) => String(NAMES[a] || "").localeCompare(String(NAMES[b] || "")))
        .map((id) => '<option value="' + esc(id) + '">'
          + esc(NAMES[id] || "Unknown") + " (" + estCounts[id] + ")</option>"));
    if (noneCount) estOpts.push('<option value="_none">Unassigned (' + noneCount + ")</option>");
    est.innerHTML = estOpts.join("");
    if (EST && !estCounts[EST] && EST !== "_none") { EST = ""; ssSet(SK.est, ""); }
    est.value = EST;

    const stCounts = {};
    live.forEach((r) => { if (r.stage_id) stCounts[r.stage_id] = (stCounts[r.stage_id] || 0) + 1; });
    const stage = $("stage");
    stage.innerHTML = ['<option value="">Any stage</option>'].concat(
      STAGES.filter((s) => stCounts[s.id])
        .map((s) => '<option value="' + esc(s.id) + '">'
          + esc(s.name || "Unstaged") + " (" + stCounts[s.id] + ")</option>")).join("");
    if (STAGE && !stCounts[STAGE]) { STAGE = ""; ssSet(SK.stage, ""); }
    stage.value = STAGE;

    $("modes").innerHTML = K.MODES.map((m) =>
      '<button type="button" data-mode="' + m.id + '" aria-pressed="'
      + (m.id === MODE ? "true" : "false") + '">' + m.label + "</button>").join("");
    $("q").value = Q;
    $("toolbar").hidden = false;
  }

  function showAlert(text, stale) {
    const el = $("alert");
    el.textContent = text || "";
    el.hidden = !text;
    el.className = "alert" + (stale ? " stale" : "");
  }

  // ── load ──────────────────────────────────────────────────────────
  function applyData(j) {
    ROWS = Array.isArray(j.projects) ? j.projects : [];
    STAGES = Array.isArray(j.stages) ? j.stages : [];
    NAMES = {};
    (j.estimators || []).forEach((e) => { NAMES[e.id] = e.name || e.id; });
    COMPANIES = {};
    (j.companies || []).forEach((c) => { COMPANIES[c.id] = c.name || ""; });
    TODAY = A.today();
    fillFilters();
    paint();
  }

  async function load(first) {
    try {
      const r = await api("/api/analytics");
      const j = await r.json();
      if (!j || j.ok === false) {
        if (first) {
          $("grid").className = "empty";
          $("grid").textContent = (j && j.error) || "Couldn't load the bid calendar.";
        }
        return;
      }
      // `building` with no rows is a genuinely empty state, not an error: the dataset is
      // being fetched for the first time on a brand-new container. Anything else — a
      // restored snapshot, a live build — has rows to draw immediately.
      if (j.building && !(j.projects || []).length) {
        if (first) {
          $("grid").className = "loading";
          $("grid").textContent = "Reading the bid history from BasisBoard…";
        }
        return;
      }
      applyData(j);
      showAlert(j.stale
        ? "Showing the last saved copy of the bid data while a fresh read finishes."
        : "", true);
    } catch (err) {
      if (first) {
        $("grid").className = "empty";
        $("grid").textContent = "Couldn't reach the server. " + (err.message || "");
      }
    }
  }

  // ── events (delegated; CSP forbids inline handlers) ───────────────
  $("modes").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mode]");
    if (!b) return;
    MODE = b.dataset.mode;
    ssSet(SK.mode, MODE);
    // Re-anchor so switching length keeps you where you were looking instead of
    // jumping: a fortnight's anchor is its first day, a month's is the 1st.
    ANCHOR = MODE === "month" ? ANCHOR.slice(0, 8) + "01" : K.startOfWeek(ANCHOR);
    fillFilters();
    paint();
  });
  $("prev").addEventListener("click", () => { ANCHOR = K.shift(ANCHOR, MODE, -1); paint(); });
  $("next").addEventListener("click", () => { ANCHOR = K.shift(ANCHOR, MODE, 1); paint(); });
  $("today").addEventListener("click", () => { TODAY = A.today(); ANCHOR = TODAY; paint(); });

  $("est").addEventListener("change", (e) => { EST = e.target.value; ssSet(SK.est, EST); paint(); });
  $("stage").addEventListener("change", (e) => { STAGE = e.target.value; ssSet(SK.stage, STAGE); paint(); });
  $("q").addEventListener("input", (e) => { Q = e.target.value || ""; ssSet(SK.q, Q); paint(); });
  $("q").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.target.value = ""; Q = ""; ssSet(SK.q, ""); paint(); }
  });

  // Arrow keys page the calendar, which is what anybody who has used one expects —
  // but not while they're typing in the search box.
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
    if (e.key === "ArrowLeft") { ANCHOR = K.shift(ANCHOR, MODE, -1); paint(); }
    else if (e.key === "ArrowRight") { ANCHOR = K.shift(ANCHOR, MODE, 1); paint(); }
    else if (e.key === "t" || e.key === "T") { TODAY = A.today(); ANCHOR = TODAY; paint(); }
  });

  // The dataset is rebuilt server-side on a clock, so re-reading it on the same cadence
  // keeps the page current without anybody pressing F5. Cheap: it's a cached read.
  load(true);
  setInterval(() => load(false), 120000);
  // Coming back to a tab left open overnight must not leave "Today" on yesterday.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { TODAY = A.today(); load(false); }
  });
})();
