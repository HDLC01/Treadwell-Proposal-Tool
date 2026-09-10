// Externalized from polish-estimates.html (CSP: script-src has no 'unsafe-inline').
// Do not add inline scripts or onclick= handlers — both fail silently in production.
//
// THE POLISH ESTIMATE DATABASE. Hanz, 2026-09-10: "the polish estimate database ... the beta
// polish estimates that does not add up to the analytics, just something to test and save the
// polish projects."
//
// THIS IS THE SECOND DOOR ONTO ONE FILTER, ON PURPOSE. The Proposals Database already carries a
// "Beta Polish" tab (js/projects.js:131, ten tests in test_projects_beta_tab.py) and it STAYS.
// What that tab could not fix is where somebody goes looking: it lives inside a page filed under
// Active, behind a chip that opens on "active" out of sessionStorage. This page is a sidebar row
// under BETA, beside the calculator itself.
//
// So the two must never be able to disagree. Both read `polish_beta` and `total` off the SAME
// /api/drafts summary, and neither computes money: the resolution lives in exactly one place,
// backend/drafts.py:_bid_total, and any arithmetic here would be a second answer to a question
// that already has one.
//
// NOTHING ON THIS PAGE WRITES. No Test toggle, no archive pill, no trash, no assign — every one
// of those belongs to the Proposals Database, and a second writer for `is_test` or `archived` is
// how two pages start disagreeing about the same project. This is a reader.
(function () {
  // Dates render in Treadwell's business timezone (Central), not the viewer's, so the row date
  // and the month bucket agree for every user. The dev box clock is ~13 hours ahead of Central.
  const fmtDate = (iso) => TW.fmtBizDate(iso);
  const localYM = (iso) => TW.bizYM(iso);
  // TW.fmtUsd, not a local money(). It is the shared formatter and it produces byte-identical
  // output to the Proposals Database's own one-liner for a number ("$128,430"), so the same bid
  // cannot render two ways on the two pages that show it.
  const money = (n) => TW.fmtUsd(n);

  // Names, initials and avatar colours come from crm-core — the same module the CRM board and the
  // Proposals Database use. A local copy of nameOf() would make one person two people.
  const nameOf = window.TWCrm.nameOf;
  const avatar = window.TWCrm.avatarHtml;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  // Resolve as soon as auth.js sets the token (right after getSession) so the fetch runs in
  // PARALLEL with the sidebar's /api/me + render, instead of waiting for the whole handshake.
  // Lifted from js/projects.js, which documents the round-trip it saves.
  function tokenSoon() {
    return new Promise((res) => {
      const t0 = Date.now();
      (function poll() {
        if (window.__TW_TOKEN) return res(true);
        if (Date.now() - t0 > 8000) return res(false);   // unauth → auth.js redirects
        setTimeout(poll, 40);
      })();
    });
  }

  // /api/drafts is capped at the 300 most-recently-updated drafts (backend/drafts.py:530,
  // list_drafts(limit=300)) and this page cannot raise it — main.py calls it with no argument.
  // The constant is here so the footnote states the real ceiling rather than a remembered one.
  const READ_CEILING = 300;

  // Its own sessionStorage keys, NOT the tw_projects_* ones. Sharing them would mean sorting
  // here silently re-sorted the Proposals Database, whose list is a different population.
  const QUERY_KEY = "tw_polishdb_q";
  const MONTH_KEY = "tw_polishdb_month";
  const SORTFIELD_KEY = "tw_polishdb_sortfield";
  const SORTDIR_KEY = "tw_polishdb_sortdir";
  const _ss = (k, d) => { try { const v = sessionStorage.getItem(k); return v == null ? d : v; } catch { return d; } };

  let SEARCH = _ss(QUERY_KEY, "");
  let MONTH = _ss(MONTH_KEY, "");
  const SORT_FIELDS = ["updated", "name", "deadline", "total"];
  // Each field opens in its natural order: dates newest-first, names A→Z, deadlines soonest,
  // totals high→low. The toggle reverses whichever field is picked. Same table as projects.js.
  const NATURAL_DIR = { updated: "desc", name: "asc", deadline: "asc", total: "desc" };
  let SORTFIELD = _ss(SORTFIELD_KEY, "updated");
  let SORTDIR = _ss(SORTDIR_KEY, "");
  if (!SORT_FIELDS.includes(SORTFIELD)) SORTFIELD = "updated";
  if (SORTDIR !== "asc" && SORTDIR !== "desc") SORTDIR = NATURAL_DIR[SORTFIELD];

  let ALL = [];          // every beta estimate the summary returned
  let LOADED = false;    // a real answer has come back at least once

  // THE FILTER, AND THE ONE FIELD IT KEYS ON. `polish_beta` is true when
  // data.polish_estimate.version === 2 (backend/drafts.py:857 _polish_beta, which coerces both
  // the TEXT that PostgREST's ->> projection returns and the int the fallback shaper sees to the
  // same boolean). It arrives as one scalar out of the object rather than the object itself:
  // polish_estimate carries every area, material and crew line, and this list is read 300 rows
  // at a time on every page load.
  const isBeta = (p) => !!p.polish_beta;

  // A beta project is almost always ALSO a test project — polish-sandbox.js files each copy it
  // makes with is_test:true and renames it "<name> (beta test)". That is expected, not an error
  // state, and it is why this page never filters on is_test in either direction: filtering tests
  // out would empty it, and filtering them in would hide the ones somebody has since marked real.
  const isTest = (p) => p.is_test === true;

  const estimatorOf = (p) => String(p.assigned_estimator || p.owner_email || "");
  const isAssigned = (p) => !!p.assigned_estimator;

  /** Avatar + name + the "?" that marks an owner nobody actually chose. Same shape as the
   *  Proposals Database's estLabel, so a person reads identically on both pages. Read-only
   *  here — no assign pencil, because assignment belongs to the page that can write it. */
  function estLabel(p) {
    const email = estimatorOf(p);
    if (!email) return "&mdash;";
    return avatar(email, !isAssigned(p)) + esc(nameOf(email)) + (isAssigned(p) ? "" : "?");
  }

  function matchesSearch(p) {
    if (!SEARCH.trim()) return true;
    const q = SEARCH.trim().toLowerCase();
    return String(p.project_name || "").toLowerCase().includes(q)
        || String(estimatorOf(p)).toLowerCase().includes(q);
  }

  function shownRows() {
    const out = ALL.filter((p) => matchesSearch(p) && (!MONTH || localYM(p.updated_at) === MONTH));
    const dir = SORTDIR === "asc" ? 1 : -1;
    const cmp = {
      // A blank deadline and an un-priced estimate are real rows — the beta saves the project
      // before it has a price — so they sort to one end by construction rather than landing
      // wherever a null happens to compare. "￿" is above every printable character.
      updated: (a, b) => (new Date(a.updated_at || 0)) - (new Date(b.updated_at || 0)),
      name: (a, b) => String(a.project_name || "").localeCompare(String(b.project_name || "")),
      deadline: (a, b) => String(a.deadline || "￿").localeCompare(String(b.deadline || "￿")),
      total: (a, b) => (typeof a.total === "number" ? a.total : -Infinity)
                     - (typeof b.total === "number" ? b.total : -Infinity),
    }[SORTFIELD];
    return out.sort((a, b) => cmp(a, b) * dir);
  }

  // ── the table ─────────────────────────────────────────────────────────────
  // COLUMNS ARE EXACTLY WHAT /api/drafts ALREADY PROJECTS. Nothing here costs a second request,
  // and two columns an estimator would reasonably want are deliberately ABSENT: polished area
  // and $/SF. Both live inside data.polish_estimate, which _build_summaries selects ONE scalar
  // out of (the version, for this page's own filter) precisely so that reading the list does not
  // drag every area, material and crew line across the wire for 300 rows. If they are wanted,
  // the summary has to grow a scalar for them on the backend — never a blob read here.
  const TCOLS = [
    { label: "Project", sort: "name" },
    { label: "Flag", sort: null },
    { label: "Type", sort: null },
    // "BETA TOTAL", AND IT MUST NOT BE TIDIED BACK TO "TOTAL".
    //
    // backend/drafts.py:_bid_total INVERTS its resolution order for a beta project:
    //
    //     order = (engine, lump_sum) if beta else (lump_sum, engine)
    //
    // Every other money surface in the app resolves `proposal_lump_sum` FIRST — that is the
    // estimate sheet's own TOTAL LUMP SUM (D88/D82), the figure the estimator is looking at and
    // the one the proposal prints. For a beta bid the order flips, because the beta calculator
    // prices itself and writes `computed_bid` on every save (polish-estimate.js:202) while never
    // touching `proposal_lump_sum`. On a job priced on the spreadsheet and THEN re-priced in the
    // beta, the lump sum is the stale number and the engine object is the live one, so preferring
    // the lump sum here would quote a price nobody uses any more.
    //
    // The consequence for this page: the figure in this column is the BETA CALCULATOR'S, and on a
    // re-priced job it disagrees with the sheet. _bid_total's own docstring records real spreads —
    // $30,960 against $45,629, and $11,573 against $7,861. A column headed plain "Total" on a
    // page called a database is a number somebody reads as the bid. This header is what says
    // whose figure it is; the sentence under the page heading says it again in words, and the
    // cell carries it a third time as a title. Renaming this to "Total" reintroduces the
    // misreading all three exist to prevent.
    { label: "Beta total", sort: "total", num: true },
    { label: "Files", sort: null },
    { label: "Estimator", sort: null },
    { label: "Due", sort: "deadline" },
    { label: "Updated", sort: "updated" },
  ];

  function tableHtml(rows) {
    const head = TCOLS.map((c) => {
      const cls = c.num ? "num" : "";
      if (!c.sort) return `<th class="${cls}">${esc(c.label)}</th>`;
      const on = SORTFIELD === c.sort;
      return `<th class="${cls} th-sort${on ? " is-sorted" : ""}" aria-sort="${
        on ? (SORTDIR === "asc" ? "ascending" : "descending") : "none"}">` +
        `<button type="button" data-sortby="${c.sort}">${esc(c.label)}${
          on ? (SORTDIR === "asc" ? " ↑" : " ↓") : ""}</button></th>`;
    }).join("");

    const body = rows.map((p) => {
      const email = estimatorOf(p);
      return `<tr class="trow" data-id="${encodeURIComponent(p.id)}" tabindex="0">
        <td class="t-name">${esc(p.project_name || "(untitled)")}</td>
        <td>${isTest(p)
          ? `<span class="badge badge-test" title="Filed as a test project — the beta files every copy it makes this way">Test</span>`
          : ""}</td>
        <td>${p.work_type ? esc(p.work_type) : ""}</td>
        <td class="num${p.total != null ? " total" : " soft"}"${p.total != null
          ? ` title="Priced in the Polish Estimate beta — not the estimate sheet's lump sum"` : ""
        }>${p.total != null ? money(p.total) : "&mdash;"}</td>
        <td>${p.has_files
          ? `<span class="badge" title="Generate has run for this project at least once">Generated</span>`
          : `<span class="soft">&mdash;</span>`}</td>
        <td class="est-cell${isAssigned(p) ? "" : " soft"}" title="${esc(email || "nobody yet")}${
          isAssigned(p) ? "" : " — nobody is assigned yet, this is whoever built the estimate"
        }">${estLabel(p)}</td>
        <td${p.deadline ? "" : ' class="soft"'}>${p.deadline ? esc(p.deadline) : "&mdash;"}</td>
        <td>${fmtDate(p.updated_at)}</td>
      </tr>`;
    }).join("");

    return `<div class="tablewrap"><table class="ptable">`
      + `<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  // ── the states a list has to have designed, not defaulted ─────────────────
  // EMPTY TELLS THE TRUTH ABOUT WHERE ROWS COME FROM. A bare "nothing here" is the exact shape of
  // the report this whole area exists to answer: Will said beta work "doesn't save", and half of
  // that was work which HAD saved and was invisible everywhere anybody looked
  // (test_projects_beta_tab.py records it). An estimator who saved beta work, opened the page
  // named after it and read "no projects" would file that report again.
  function emptyHtml() {
    if (SEARCH.trim() || MONTH) {
      return `<div class="card empty">
        <p class="empty-h">Nothing matches that.</p>
        <p class="empty-p">${ALL.length} beta ${ALL.length === 1 ? "estimate is" : "estimates are"}`
        + ` saved &mdash; none of them match the search or month you have set.</p>
      </div>`;
    }
    return `<div class="card empty">
      <svg class="empty-mark" width="28" height="28" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
           aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M12 3a9 9 0 0 1 0 18z"></path></svg>
      <p class="empty-h">No beta polish estimates yet.</p>
      <p class="empty-p">An estimate lands here the moment it is priced in the <b>Polish Estimate</b>
        beta &mdash; either from the beta's own intake, or by pressing <b>Try the polish beta</b> on a
        polish job's Estimate Review. Bids priced on the spreadsheet stay in the Proposals Database.
        This list reads the ${READ_CEILING} most recently updated projects, so a beta estimate older
        than that will not appear here.</p>
      <div class="empty-act">
        <a class="btn" href="/polish-intake.html">Start a beta estimate</a>
        <a class="btn-quiet" href="/projects.html">Proposals Database</a>
      </div>
    </div>`;
  }

  // A FAILED FETCH IS ITS OWN STATE, never an empty list. "No beta polish estimates yet" on a 500
  // is a lie that reads as data loss — the one thing this page must not say by accident.
  function failedHtml(msg) {
    return `<div class="card failed">
      <p class="empty-h">Could not load the beta estimates.</p>
      <p class="empty-p">Nothing is lost &mdash; this page only reads.
        ${esc(msg || "The request did not come back.")}</p>
      <div class="empty-act"><button type="button" id="retry" class="btn">Try again</button></div>
    </div>`;
  }

  function syncToolbar() {
    const tb = document.getElementById("toolbar");
    // `tb.hidden` alone would not be enough: .toolbar carries `display:flex`, which beats the UA
    // `[hidden]` rule outright. The stylesheet has the `.toolbar[hidden]` guard — see the note
    // there, and the four live instances of this bug that test_hidden_is_actually_hidden.py
    // exists because of.
    tb.hidden = !LOADED || ALL.length === 0;
    const q = document.getElementById("q");
    if (q.value !== SEARCH) q.value = SEARCH;
    document.getElementById("sort").value = SORTFIELD;
    const dir = document.getElementById("dir");
    dir.textContent = SORTDIR === "asc" ? "↑ Asc" : "↓ Desc";
    dir.setAttribute("aria-pressed", SORTDIR === "asc" ? "true" : "false");
    document.getElementById("clear").hidden = !(SEARCH.trim() || MONTH);
  }

  function syncMonths() {
    const sel = document.getElementById("month");
    const counts = {};
    ALL.forEach((p) => { const ym = localYM(p.updated_at); if (ym) counts[ym] = (counts[ym] || 0) + 1; });
    if (MONTH && !counts[MONTH]) { MONTH = ""; try { sessionStorage.removeItem(MONTH_KEY); } catch {} }
    const months = Object.keys(counts).sort().reverse();
    sel.innerHTML = `<option value="">Any month</option>`
      + months.map((ym) => `<option value="${esc(ym)}">${esc(TW.bizMonthLabel(ym))} (${counts[ym]})</option>`).join("");
    sel.value = MONTH;
  }

  function paint() {
    const el = document.getElementById("list");
    const rows = shownRows();
    el.className = "";                       // drop the boot-time .loading
    el.innerHTML = rows.length ? tableHtml(rows) : emptyHtml();

    const n = rows.length;
    document.getElementById("count").textContent = (SEARCH.trim() || MONTH)
      ? `${n} of ${ALL.length}`
      : `${n} ${n === 1 ? "estimate" : "estimates"}`;

    // The read ceiling, stated on screen once there is enough data for it to bite. Below the cap
    // it would be noise; at the cap the list is silently truncated and somebody has to know.
    const ceiling = document.getElementById("ceiling");
    const at = !SEARCH.trim() && !MONTH && ALL.length >= READ_CEILING;
    ceiling.hidden = !at;
    if (at) {
      ceiling.textContent = `Showing the ${READ_CEILING} most recently updated projects. `
        + `A beta estimate older than that is still saved, but will not appear here.`;
    }
    syncToolbar();
  }

  async function load() {
    const el = document.getElementById("list");
    if (!await tokenSoon()) return;          // auth.js is redirecting to sign-in
    try {
      const r = await fetch("/api/drafts", { headers: TW.authHeaders() });
      const j = await r.json();
      // The route answers 200 with ok:false and an error string when the read itself failed
      // (main.py:api_list_drafts). An empty `projects` there is a FAILURE, not an empty database,
      // and telling the two apart is the whole reason failedHtml exists.
      if (!j || j.ok === false) throw new Error((j && j.error) || "the server could not read the list");
      ALL = (j.projects || []).filter(isBeta);
      LOADED = true;
      syncMonths();
      paint();
    } catch (err) {
      if (LOADED) return;                    // a blip on the 60s poll: keep what is on screen
      el.className = "";
      el.innerHTML = failedHtml(err && err.message);
      document.getElementById("toolbar").hidden = true;
      document.getElementById("ceiling").hidden = true;
    }
  }

  // ── wiring ────────────────────────────────────────────────────────────────
  // ONE delegated listener for the whole list: paint() replaces #list's innerHTML on every 60s
  // poll as well as on every sort, so per-row listeners would be re-bound dozens of times an hour.
  (function wire() {
    const el = document.getElementById("list");

    // A BETA PROJECT OPENS ON THE BETA'S OWN INTAKE. Identical rule to js/projects.js:538, and
    // for the identical reason it records: a bid priced in the beta has no spreadsheet behind it,
    // so resuming it on the live intake walks the estimator into an Excel grid whose numbers are
    // not there. Every row on this page is `polish_beta` by construction, so there is no branch to
    // get wrong here — but the destination has to stay in step with that router if it ever moves.
    const open = (id) => window.location.assign("/polish-intake.html?d=" + id);

    el.addEventListener("click", (e) => {
      if (e.target.closest("#retry")) { load(); return; }
      const th = e.target.closest("[data-sortby]");
      if (th) {
        const f = th.dataset.sortby;
        // Clicking the sorted column flips it; a new column opens its natural way.
        SORTDIR = SORTFIELD === f ? (SORTDIR === "asc" ? "desc" : "asc") : (NATURAL_DIR[f] || "desc");
        SORTFIELD = f;
        try { sessionStorage.setItem(SORTFIELD_KEY, SORTFIELD); sessionStorage.setItem(SORTDIR_KEY, SORTDIR); } catch {}
        paint();
        return;
      }
      const row = e.target.closest(".trow");
      if (!row) return;
      open(row.dataset.id);                  // already encodeURIComponent'd
    });

    // The rows are focusable (tabindex=0), so they have to answer the keyboard too — a table you
    // can tab into and not open is worse than one you cannot tab into at all.
    el.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const row = e.target.closest && e.target.closest(".trow");
      if (!row) return;
      e.preventDefault();
      open(row.dataset.id);
    });

    // Search filters as you type. This is a FILTER, not a validated field — there is nothing to
    // scold anybody about mid-word, and nothing is submitted.
    let t = null;
    document.getElementById("q").addEventListener("input", (e) => {
      SEARCH = e.target.value;
      try { sessionStorage.setItem(QUERY_KEY, SEARCH); } catch {}
      clearTimeout(t);
      t = setTimeout(paint, 120);
    });
    document.getElementById("month").addEventListener("change", (e) => {
      MONTH = e.target.value;
      try { sessionStorage.setItem(MONTH_KEY, MONTH); } catch {}
      paint();
    });
    document.getElementById("sort").addEventListener("change", (e) => {
      SORTFIELD = SORT_FIELDS.includes(e.target.value) ? e.target.value : "updated";
      SORTDIR = NATURAL_DIR[SORTFIELD];
      try { sessionStorage.setItem(SORTFIELD_KEY, SORTFIELD); sessionStorage.setItem(SORTDIR_KEY, SORTDIR); } catch {}
      paint();
    });
    document.getElementById("dir").addEventListener("click", () => {
      SORTDIR = SORTDIR === "asc" ? "desc" : "asc";
      try { sessionStorage.setItem(SORTDIR_KEY, SORTDIR); } catch {}
      paint();
    });
    document.getElementById("clear").addEventListener("click", () => {
      SEARCH = ""; MONTH = "";
      try { sessionStorage.removeItem(QUERY_KEY); sessionStorage.removeItem(MONTH_KEY); } catch {}
      document.getElementById("q").value = "";
      document.getElementById("month").value = "";
      paint();
    });

    syncToolbar();
  })();

  load();
  // Another estimator's saved beta estimate should appear without an F5. The list sits behind a
  // 60s server cache, so match it rather than beat on it.
  setInterval(() => { if (!document.hidden) load(); }, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
})();
