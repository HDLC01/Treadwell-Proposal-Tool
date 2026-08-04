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
// TWO SOURCES, ONE GRID. This is the calendar Treadwell staff are meant to use as they
// move off Basisboard, so it has to accept work that never came from Basisboard at all:
//
//   * Basisboard bids — read from /api/analytics (the only dataset carrying
//     bid_deadline_at, the GC companies and the estimator ids). MIRRORED and READ-ONLY:
//     our integration never writes upstream, so an edit could not be saved there and
//     would silently revert on the next sync. Their cards are LINKS OUT — there is no
//     edit affordance on something we can't save, so nobody discovers the limit by
//     losing work to it.
//   * Treadwell's own entries — /api/calendar/events, full add/edit/delete, in our own
//     Postgres. Their cards open the editor on click and can be DRAGGED to another day,
//     which just means "give it that deadline" (keeping the time of day — moving a 2pm bid
//     to Thursday should leave it due at 2pm). Once Basisboard is gone, only these remain
//     and nothing here has to change.
//
// A Basisboard outage therefore degrades to "ours only" rather than an empty page.
//
// All the date arithmetic lives in calendar-core.js, which is pure and tested under node.
// Deadlines are entered and shown as Central wall-clock and stored as UTC instants; the
// conversion measures the zone's offset AT THAT DATE, so a deadline typed either side of a
// DST change is stored correctly.
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

  let ROWS = [];               // both sources, merged — what the grid draws
  let BB = [];                 // Basisboard's bids: mirrored, read-only
  let MINE = [];               // Treadwell's own entries: editable
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

  /** One card, from either source.
   *
   *  Ours is a draggable div[role=button] that opens the editor; a mirrored Basisboard bid is
   *  a plain link out to Basisboard. That difference is the whole read-only story made
   *  visible: no edit affordance and no drag handle on something we cannot save, so nobody
   *  discovers the limitation by losing work to it. */
  function card(r, urg) {
    const val = money(r.quote);
    const mine = r.source === "treadwell";
    const inner = '<p class="cname">' + esc(r.name || "Untitled") + "</p>"
      + '<div class="cmeta">' + estimatorChip(r)
      + '<span class="when">' + esc(timeLabel(r)) + "</span>"
      + (val ? '<span class="amt">' + val + "</span>" : "")
      + "</div>" + gcLine(r);
    const cls = "card u-" + urg + (mine ? " mine" : "");
    if (mine) {
      // A DIV with role=button, NOT a <button>: `button` may only contain PHRASING content and
      // this card holds <p> and <div>, so the parser closes the button early and the card's
      // content spills loose into the day cell — losing its border, stripe and click target.
      // The same mistake broke the Follow-ups board grid (#246); it was latent here only
      // because a board with no Treadwell-owned entries never renders one of these.
      // Draggable, because for OUR entries a drag means "give it this deadline instead".
      return '<div class="' + cls + '" role="button" tabindex="0" draggable="true"'
        + ' data-edit="' + esc(r.id) + '"'
        + ' title="' + esc(r.name || "") + (val ? " — " + moneyFull(r.quote) : "")
        + ' · click to edit, or drag to another day">' + inner + "</div>";
    }
    const href = "https://app.basisboard.com/projects/" + encodeURIComponent(r.id || "");
    return '<a class="' + cls + '" href="' + esc(href) + '"'
      + ' target="_blank" rel="noopener noreferrer"'
      + ' title="' + esc(r.name || "") + (val ? " — " + moneyFull(r.quote) : "")
      + ' · lives in BasisBoard, opens there">' + inner + "</a>";
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
    return '<div class="' + cls.join(" ") + '" data-day="' + day + '">' + head
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
    BB = Array.isArray(j.projects) ? j.projects.map(markMirror) : [];
    STAGES = Array.isArray(j.stages) ? j.stages : [];
    NAMES = {};
    (j.estimators || []).forEach((e) => { NAMES[e.id] = e.name || e.id; });
    COMPANIES = {};
    (j.companies || []).forEach((c) => { COMPANIES[c.id] = c.name || ""; });
    TODAY = A.today();
    recombine();
    fillFilters();
    paint();
  }

  /** Basisboard's rows don't carry a source, so stamp one rather than inferring it later
   *  from the absence of a field — "no `source` key" and "source is basisboard" must not be
   *  the same test, or a shape change upstream silently makes their bids editable. */
  function markMirror(r) {
    return Object.assign({}, r, { source: "basisboard", editable: false });
  }

  /** Both sources, one list. Ours last so a same-day tie sorts predictably by deadline
   *  rather than by which fetch happened to finish first. */
  function recombine() {
    ROWS = BB.concat(MINE);
  }

  async function loadMine(first) {
    try {
      const r = await api("/api/calendar/events");
      const j = await r.json();
      if (!j || j.ok === false) return;
      MINE = Array.isArray(j.events) ? j.events : [];
      recombine();
      if (!first || MINE.length) { fillFilters(); paint(); }
    } catch {
      // Ours failing must not blank the Basisboard half — it is the larger dataset and the
      // page is still useful without the editable rows.
    }
  }

  async function load(first) {
    try {
      // Wait for auth.js to mint the bearer token before the first read. Without this the
      // page fires its fetch as it parses, beats the token into existence, and renders
      // "Missing bearer token." on a screen that has nothing wrong with it — the same race
      // that hit /api/default-notes. The poll is per-call and resolves immediately once
      // the token exists, so the 2-minute refresh pays nothing for it.
      try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
      const r = await api("/api/analytics");
      const j = await r.json();
      if (!j || j.ok === false) {
        // Basisboard being unavailable (or simply unconfigured) must not blank OUR rows —
        // they're the half that always works, and this page has to stay usable as the
        // calendar Treadwell owns. Only say nothing loaded when nothing did.
        if (first && !ROWS.length) {
          $("grid").className = "empty";
          $("grid").textContent = (j && j.error) || "Couldn't load the bid calendar.";
        } else if (MINE.length) {
          showAlert("Showing Treadwell's own entries only — BasisBoard's bids couldn't be "
            + "loaded just now.", true);
          paint();
        }
        return;
      }
      // `building` with no rows is a genuinely empty state, not an error: the dataset is
      // being fetched for the first time on a brand-new container. Anything else — a
      // restored snapshot, a live build — has rows to draw immediately.
      if (j.building && !(j.projects || []).length) {
        if (first && !ROWS.length) {
          $("grid").className = "loading";
          $("grid").textContent = "Reading the bid history from BasisBoard…";
        } else if (MINE.length) {
          paint();                       // ours are ready; don't hide them behind a spinner
        }
        return;
      }
      applyData(j);
      showAlert(j.stale
        ? "Showing the last saved copy of the bid data while a fresh read finishes."
        : "", true);
    } catch (err) {
      if (first && !ROWS.length) {
        $("grid").className = "empty";
        $("grid").textContent = "Couldn't reach the server. " + (err.message || "");
      }
    }
  }

  // ── add / edit / delete ───────────────────────────────────────────
  // Only ever operates on OUR rows. A Basisboard bid has no edit affordance at all (its
  // card is a link out), so the read-only boundary is visible in the UI rather than
  // enforced by a message after somebody has already typed.
  let EDITING = null;          // id being edited, or null when adding

  /** A Central wall-clock value for <input type="datetime-local">.
   *
   *  The input has no timezone, so it must be fed Central digits or the picker shows a
   *  deadline in the viewer's zone — an estimator in another state would open a 2pm bid and
   *  see 3pm, then "save" it an hour off. Built from the formatted Central parts rather than
   *  the raw Date, which is the only way to get this right without a tz library. */
  function toLocalInput(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const p = {};
    new Intl.DateTimeFormat("en-US", {
      timeZone: A.BIZ_TZ, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).formatToParts(d).forEach((x) => { p[x.type] = x.value; });
    // Central midnight formats as hour "24" in some ICU versions, which the input rejects.
    const hh = p.hour === "24" ? "00" : p.hour;
    return p.year + "-" + p.month + "-" + p.day + "T" + hh + ":" + p.minute;
  }

  /** The inverse: Central wall-clock digits -> a real UTC instant.
   *
   *  Computed by measuring Central's offset AT THAT DATE rather than assuming one, so a
   *  deadline entered either side of a DST change is stored correctly. */
  function fromLocalInput(v) {
    if (!v) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(v.trim());
    if (!m) return null;
    const asUTC = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    // What those same digits mean in Central: shift by the zone's offset on that date.
    const probe = new Date(asUTC);
    const parts = {};
    new Intl.DateTimeFormat("en-US", {
      timeZone: A.BIZ_TZ, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).formatToParts(probe).forEach((x) => { parts[x.type] = x.value; });
    const seenUTC = Date.UTC(+parts.year, +parts.month - 1, +parts.day,
                             parts.hour === "24" ? 0 : +parts.hour, +parts.minute);
    return new Date(asUTC + (asUTC - seenUTC)).toISOString();
  }

  function fillEstimatorPicker() {
    const sel = $("f-est");
    const chosen = sel.value;
    const seen = {};
    MINE.forEach((r) => { if (r.estimator_email) seen[r.estimator_email] = r.estimator_email; });
    Object.keys(NAMES).forEach((id) => { if (id.includes("@")) seen[id] = NAMES[id]; });
    sel.innerHTML = ['<option value="">Unassigned</option>'].concat(
      Object.keys(seen).sort().map((e) =>
        '<option value="' + esc(e) + '">' + esc(C.nameOf(seen[e]) || e) + "</option>")).join("");
    sel.value = chosen;
  }

  function openDialog(row) {
    EDITING = row ? row.id : null;
    $("dlg-title").textContent = row ? "Edit calendar entry" : "Add to the calendar";
    $("dlg-err").hidden = true;
    fillEstimatorPicker();
    $("f-title").value = row ? (row.name || "") : "";
    $("f-deadline").value = row ? toLocalInput(row.bid_deadline_at) : "";
    $("f-kind").value = (row && row.kind) || "bid";
    $("f-customer").value = row ? (row.customer || "") : "";
    $("f-value").value = row && typeof row.quote === "number" ? String(row.quote) : "";
    $("f-location").value = row ? (row.location || "") : "";
    $("f-est").value = row ? (row.estimator_email || "") : "";
    $("f-notes").value = row ? (row.notes || "") : "";
    $("f-del").hidden = !row;
    $("dlg").showModal();
    $("f-title").focus();
  }

  function dialogError(msg) {
    const el = $("dlg-err");
    el.textContent = msg;
    el.hidden = !msg;
  }

  async function save(ev) {
    ev.preventDefault();
    const title = $("f-title").value.trim();
    if (!title) { dialogError("Give it a name so it can be found later."); return; }
    const body = {
      title: title,
      deadline_at: fromLocalInput($("f-deadline").value),
      kind: $("f-kind").value,
      customer: $("f-customer").value.trim(),
      value: $("f-value").value.trim(),
      location: $("f-location").value.trim(),
      estimator_email: $("f-est").value,
      notes: $("f-notes").value.trim(),
    };
    const btn = $("f-save");
    btn.disabled = true;
    try {
      const r = await api(EDITING ? "/api/calendar/events/" + encodeURIComponent(EDITING)
                                  : "/api/calendar/events",
        { method: EDITING ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        // The server's message is written for a person, so show it rather than a generic
        // failure — "That value isn't a number" is actionable, "Save failed" isn't.
        dialogError(j.detail || j.error || ("Couldn't save (HTTP " + r.status + ")."));
        return;
      }
      $("dlg").close();
      await loadMine(false);
    } catch (err) {
      dialogError("Couldn't reach the server. " + (err.message || ""));
    } finally {
      btn.disabled = false;
    }
  }

  async function remove() {
    if (!EDITING) return;
    const row = MINE.find((r) => r.id === EDITING);
    if (!window.confirm("Delete “" + ((row && row.name) || "this entry")
        + "” from the calendar?")) return;
    try {
      const r = await api("/api/calendar/events/" + encodeURIComponent(EDITING),
                          { method: "DELETE" });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        dialogError(j.detail || "Couldn't delete that entry.");
        return;
      }
      $("dlg").close();
      await loadMine(false);
    } catch (err) {
      dialogError("Couldn't reach the server. " + (err.message || ""));
    }
  }

  // A div[role=button] does not fire on Enter/Space by itself, and the card must stay a div
  // (see card() — `button` cannot legally contain the <p>/<div> it holds).
  $("grid").addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const card = e.target.closest('.card[role="button"]');
    if (!card) return;
    e.preventDefault();
    card.click();
  });

  // ── drag a Treadwell entry to another day ───────────────────────────
  // Only OUR entries are draggable — a Basisboard bid's deadline lives in Basisboard and we
  // never write there, so dragging one would show a change that reverts on the next sync.
  // Their cards are <a> elements with no draggable attribute, so they cannot start a drag.
  //
  // A drag means "give this entry that deadline", keeping the TIME OF DAY. Moving a 2pm bid to
  // Thursday should leave it due at 2pm, not midnight — the hour is a real fact about the bid,
  // not an artefact of which day it was on.
  let DRAG_ID = null;
  let DRAGGING = false;

  $("grid").addEventListener("dragstart", (e) => {
    const card = e.target.closest(".card.mine[data-edit]");
    if (!card) return;
    DRAG_ID = card.dataset.edit;
    DRAGGING = true;
    card.classList.add("dragging");
    try { e.dataTransfer.setData("text/plain", DRAG_ID); e.dataTransfer.effectAllowed = "move"; } catch {}
  });

  $("grid").addEventListener("dragend", () => {
    DRAGGING = false; DRAG_ID = null;
    document.querySelectorAll(".card.dragging").forEach((c) => c.classList.remove("dragging"));
    document.querySelectorAll(".cell.over").forEach((c) => c.classList.remove("over"));
  });

  $("grid").addEventListener("dragover", (e) => {
    const cell = e.target.closest(".cell[data-day]");
    if (!cell || !DRAG_ID) return;
    const row = MINE.find((r) => r.id === DRAG_ID);
    if (!row) return;
    // Dropping on the day it is already due is a no-op, so don't invite it.
    if (row.bid_deadline_at && A.bizDay(row.bid_deadline_at) === cell.dataset.day) return;
    e.preventDefault();
    try { e.dataTransfer.dropEffect = "move"; } catch {}
    document.querySelectorAll(".cell.over").forEach((c) => c.classList.remove("over"));
    cell.classList.add("over");
  });

  $("grid").addEventListener("drop", (e) => {
    const cell = e.target.closest(".cell[data-day]");
    if (!cell || !DRAG_ID) return;
    e.preventDefault();
    const id = DRAG_ID, day = cell.dataset.day;
    DRAGGING = false; DRAG_ID = null;
    cell.classList.remove("over");
    reschedule(id, day);
  });

  /** Move one of OUR entries to `day`, keeping its time of day. */
  async function reschedule(id, day) {
    const row = MINE.find((r) => r.id === id);
    if (!row) return;
    // Keep the existing clock time; default to 2pm Central for an entry that had no deadline,
    // because that is when bids are actually due and midnight would read as "no time set".
    const hhmm = row.bid_deadline_at
      ? (toLocalInput(row.bid_deadline_at).split("T")[1] || "14:00")
      : "14:00";
    const iso = fromLocalInput(day + "T" + hhmm);
    if (!iso) return;
    try {
      const r = await api("/api/calendar/events/" + encodeURIComponent(id),
        { method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ deadline_at: iso }) });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        showAlert(j.detail || j.error || "Couldn't move that entry.", false);
        return;
      }
      await loadMine(false);
    } catch (err) {
      showAlert("Couldn't reach the server. " + (err.message || ""), false);
    }
  }

  $("add").addEventListener("click", () => openDialog(null));
  $("dlg-form").addEventListener("submit", save);
  $("f-cancel").addEventListener("click", () => $("dlg").close());
  $("f-del").addEventListener("click", remove);
  // Delegated because the grid is re-rendered wholesale on every paint.
  $("grid").addEventListener("click", (e) => {
    const b = e.target.closest("[data-edit]");
    if (!b) return;
    const row = MINE.find((r) => r.id === b.dataset.edit);
    if (row) openDialog(row);
  });
  $("tray").addEventListener("click", (e) => {
    const b = e.target.closest("[data-edit]");
    if (!b) return;
    const row = MINE.find((r) => r.id === b.dataset.edit);
    if (row) openDialog(row);
  });

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
  // Ours first: it's a small, fast read and it means a brand-new install with no
  // Basisboard key still shows a working, editable calendar rather than an error.
  loadMine(true).then(() => load(true));
  // A repaint mid-drag pulls the card out from under the pointer.
  setInterval(() => { if (!DRAGGING) { loadMine(false); load(false); } }, 120000);
  // Coming back to a tab left open overnight must not leave "Today" on yesterday.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { TODAY = A.today(); loadMine(false); load(false); }
  });
})();
