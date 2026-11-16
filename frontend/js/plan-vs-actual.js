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
// Raken's side reads "Connect Raken to compare" until Raken is connected.
//
// READ ONLY, like the Schedule: nothing here writes anywhere. Every text value is escaped, and every
// colour is set through element.style once the markup is in place, never as a style attribute.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const P = window.TWProjCal;

  const api = async (path) => {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    return fetch(TW.resolveApiBase() + path, { headers: TW.authHeaders() });
  };

  const SK_Q = "tw_pva_q";
  const ss = (k, d) => { try { const v = sessionStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
  const ssSet = (k, v) => { try { v ? sessionStorage.setItem(k, v) : sessionStorage.removeItem(k); } catch {} };

  const POLL_MS = 5 * 60 * 1000;

  let DATA = null;                     // the last good response
  let LOAD_ERR = "";                   // why the last read failed, if it did
  let Q = ss(SK_Q, "");
  let LAST_SIG = "";                   // anti-blink: skip identical repaints

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
  async function load() {
    try {
      const r = await api("/api/project-analytics");
      const body = await r.json().catch(() => null);
      if (!r.ok || !body || body.ok === false) {
        const why = (body && (body.detail || body.error)) || ("HTTP " + r.status);
        LOAD_ERR = typeof why === "string" ? why : "The server refused the request.";
      } else {
        body.projects = (Array.isArray(body.projects) ? body.projects : [])
          .filter((p) => p && typeof p === "object");
        DATA = body;
        LOAD_ERR = "";
      }
    } catch (err) {
      LOAD_ERR = "Couldn't reach the server.";
    }
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

  function rowHtml(p) {
    const sub = [P.workTypeOf(p), p.foreman ? "Foreman " + p.foreman : "",
      !p.is_punch && Array.isArray(p.punches) && p.punches.length
        ? "+ " + p.punches.length + " Punch" + (p.punches.length === 1 ? "" : "es") : ""]
      .filter(Boolean).join(" · ");
    const chips = (p.label ? ' <span class="chip">' + esc(p.label) + "</span>" : "")
      + (p.crew_size_missing ? ' <span class="chip warn">Crew size missing</span>' : "");
    return "<tr>"
      + '<td><div class="job"><i class="sw" data-color="' + esc(P.colorOf(p) || "") + '"></i><div>'
      + (p.job_number ? '<span class="jn">' + esc(p.job_number) + "</span>" : "")
      + '<span class="jname">' + esc(p.name || "Untitled") + "</span>" + chips
      + '<span class="jsub">' + esc(sub) + "</span></div></div></td>"
      + '<td><span class="dd">' + esc(P.dayLong(p.deadline)) + "</span>"
      + "<small>" + esc(P.leftLabel(p)) + "</small></td>"
      + '<td class="num"><b>' + esc(P.numLabel(p.workdays_so_far)) + "</b></td>"
      + '<td class="num"><b>' + esc(P.numLabel(p.crew_size)) + "</b></td>"
      + '<td class="num"><b>' + esc(P.numLabel(p.planned_hours)) + "</b></td>"
      + '<td class="raken">' + esc(P.rakenLabel(p)) + "</td>"
      + "</tr>";
  }

  function paintSwatches(root) {
    root.querySelectorAll(".sw[data-color]").forEach((el) => {
      const c = el.dataset.color;
      if (c && /^#[0-9a-f]{6}$/i.test(c)) el.style.background = c;
    });
  }

  function paint() {
    const sig = JSON.stringify([Q, LOAD_ERR, DATA]);
    if (sig === LAST_SIG) return;
    LAST_SIG = sig;

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
      showAlert("");
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

    const empty = !projects.length
      ? P.pvaEmptyText(DATA)
      : (!shown.length ? "No job matches the search." : "");
    $("pva-empty").textContent = empty;
    $("pva-empty").hidden = !empty;

    $("pva-foot").textContent = P.pvaFootText(DATA);
  }

  // ── wiring (delegated; CSP forbids inline handlers) ───────────────
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
