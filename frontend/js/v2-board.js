// Externalized from v2-board.html (CSP: script-src has no 'unsafe-inline').
// Do not add inline scripts or onclick= handlers; both fail silently in production.
//
// THE ESTIMATING TOOL v2 BOARD (BETA). Every Estimating Tool v2 bid, from the moment it is created,
// in the same columns as the Direct Projects board, with Direct and GC as two tabs. Hanz, 2026-10-13:
// "make the V2 have a pipeline like the ones we have for active projects", "make sure they are
// separate tho", and "the V2 pipeline is still in beta ... so do not merge it to the existing".
// 2026-10-15: it is the Estimating Tool v2 row's front door ("It should be here not V2 estimates"),
// with "+ New" into the intake, and its cards carry the Direct Projects outcome buttons ("Yes, same
// buttons").
//
// SO THIS PAGE OWNS ITS OWN CODE. It reads the shared DOM-free helpers (js/crm-core.js, through
// js/v2-board-core.js) and never loads or calls js/portal.js. Its data is its own route,
// /api/v2/pipeline. Its storage keys are all `tw_v2_*` (TWV2Board.KEYS); it never touches the real
// boards' `tw_crm_*` keys. The one exception is "+ New", which clears the three
// `treadwell.proposal_tool.*` keys every "start a project" door clears (projects.js, portal.js), so
// the intake opens on a new bid rather than the last one.
//
// WHAT WRITES: the three card buttons, and only to the routes the Direct Projects card posts to
// (/api/draft/{id}/status, and /api/portal/proposal/{id}/status to close out a bid the customer
// has). The close-out dialog and the hand-off prompt are copies of portal.js's closeOutDialog and
// confirmHandoff, kept word for word so one act reads one way on both boards. Nothing here sends,
// follows up, takes a deposit or chats; the panel a card opens is facts and one link.
(function () {
  var V = window.TWV2Board;
  var KEYS = V.KEYS;
  var $ = function (id) { return document.getElementById(id); };

  var ss = function (k, d) { try { var v = sessionStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } };
  var ssSet = function (k, v) { try { if (v) sessionStorage.setItem(k, v); else sessionStorage.removeItem(k); } catch (e) { /* private mode */ } };

  var TAB = V.normTab(ss(KEYS.tab, "direct"));
  var EST = ss(KEYS.est, "");
  var SEARCH = ss(KEYS.search, "");
  var ALL = [];          // every v2 row the endpoint returned
  var LOADED = false;    // a real answer has come back at least once
  var SIG = "";          // what is on screen; an unchanged poll must not repaint (it would blink)
  var CUR = null;        // the project whose panel is open
  var OPENED_FROM_URL = false;

  var DEG_SIG = "";      // what the portal notice shows; an unchanged poll must not repaint it

  var ENV = {
    fmtDate: function (ts) { return (window.TW && TW.fmtBizDate) ? TW.fmtBizDate(ts) : String(ts || "").slice(0, 10); },
    fmtDateTime: function (iso) { return (window.TW && TW.fmtBizDateTime) ? TW.fmtBizDateTime(iso) : String(iso || "").slice(0, 16); }
  };

  // The customer portal's own health, said the way the real board says it: nothing when it is live,
  // a notice when the rows are old (stale) or were rebuilt from this tool's list alone (offline). It
  // lives outside #list, so the board's repaint never touches it.
  function paintDegraded(j) {
    var html = V.degradedHtml(j && j.portal_status, j && j.portal_fetched_at, ENV);
    if (html === DEG_SIG) return;
    DEG_SIG = html;
    var el = $("v2-degraded");
    el.innerHTML = html;
    el.hidden = !html;
  }

  function tokenSoon() {
    return new Promise(function (res) {
      var t0 = Date.now();
      (function poll() {
        if (window.__TW_TOKEN) return res(true);
        if (Date.now() - t0 > 8000) return res(false);     // unauthenticated: auth.js is redirecting
        setTimeout(poll, 40);
      })();
    });
  }

  function failedHtml(msg) {
    return '<div class="card-empty"><p class="empty-h">Could not load the v2 estimates.</p>'
      + '<p class="empty-p">Nothing is lost. This page only reads. ' + V.esc(msg || "The request did not come back.") + "</p>"
      + '<p><button type="button" id="retry" class="btn">Try again</button></p></div>';
  }

  function render() {
    var sig = JSON.stringify([ALL, TAB, EST, SEARCH]);
    if (LOADED && sig === SIG) return;
    SIG = sig;

    var pool = V.pool(ALL, TAB);
    var by = V.estimatorCounts(pool);
    // A stale estimator (their cards all moved off this tab) is dropped, not left to blank the board.
    if (EST && !by[EST]) { EST = ""; ssSet(KEYS.est, ""); }
    var emails = Object.keys(by).sort(function (a, b) { return TWCrm.nameOf(a).localeCompare(TWCrm.nameOf(b)); });
    $("est").innerHTML = '<option value="">Any estimator</option>' + emails.map(function (e) {
      return '<option value="' + V.esc(e) + '">' + V.esc(TWCrm.nameOf(e)) + " (" + by[e] + ")</option>";
    }).join("");
    $("est").value = EST;

    var n = V.counts(ALL);
    $("v2-tabs").innerHTML = V.tabsToShow(ALL, TAB).map(function (t) {
      return '<button type="button" class="tw-tab' + (t === TAB ? " on" : "") + '" data-tab="' + t
        + '" aria-pressed="' + (t === TAB ? "true" : "false") + '">' + V.esc(V.TAB_LABEL[t])
        + ' <span class="n">' + n[t] + "</span></button>";
    }).join("");

    var items = V.filterEstimator(V.filterSearch(pool, SEARCH), EST);
    var filtered = !!(SEARCH.trim() || EST);
    $("count").textContent = items.length === pool.length
      ? pool.length + " estimate" + (pool.length === 1 ? "" : "s")
      : items.length + " of " + pool.length;
    $("clear").hidden = !filtered;
    $("toolbar").hidden = !LOADED || ALL.length === 0;
    var list = $("list");
    list.className = "board";
    list.innerHTML = ALL.length === 0 ? V.emptyHtml(0, false)
      : (!items.length && filtered) ? V.emptyHtml(ALL.length, true)
      : V.boardHtml(items, TAB, ENV);
    var q = $("q");
    if (q.value !== SEARCH) q.value = SEARCH;
    // The drawer-style panel is rebuilt from the fresh row so a poll never shows a stale stage.
    if (CUR) paintPanel();
  }

  // ── the read-only panel ─────────────────────────────────────────────────────
  function rowFor(id) {
    for (var i = 0; i < ALL.length; i++) if (String(ALL[i].proposal_id) === String(id)) return ALL[i];
    return null;
  }
  function markOpenInUrl(id) {
    try {
      var q = new URLSearchParams(location.search);
      if (id) q.set("open", id); else q.delete("open");
      var s = q.toString();
      var next = location.pathname + (s ? "?" + s : "") + location.hash;
      if (next !== location.pathname + location.search + location.hash) history.replaceState(null, "", next);
    } catch (e) { /* the panel still opens */ }
  }
  function paintPanel() {
    var p = rowFor(CUR);
    if (!p) { closePanel(); return; }       // the bid was archived or trashed in another tab
    $("v2-panel").innerHTML = V.panelHtml(p, ENV);
  }
  function openPanel(id) {
    if (!rowFor(id)) return;
    CUR = id;
    paintPanel();
    $("v2-panel").classList.add("open");
    $("v2-scrim").style.display = "block";
    markOpenInUrl(id);
    var c = document.querySelector("[data-v2-close]");
    if (c && c.focus) c.focus();
  }
  function closePanel() {
    CUR = null;
    $("v2-panel").classList.remove("open");
    $("v2-panel").innerHTML = "";
    $("v2-scrim").style.display = "none";
    markOpenInUrl(null);
  }

  async function load() {
    if (!await tokenSoon()) return;
    try {
      var base = (window.TW && TW.resolveApiBase) ? TW.resolveApiBase() : "";
      var r = await fetch(base + "/api/v2/pipeline", { headers: TW.authHeaders() });
      var j = await r.json();
      // ok:false means the READ failed. An empty list there is a failure, not an empty board.
      if (!r.ok || !j || j.ok === false) throw new Error((j && (j.error || j.detail)) || "the server could not read the list");
      ALL = j.proposals || [];
      LOADED = true;
      paintDegraded(j);
      $("ceiling").hidden = false;
      $("ceiling").textContent = "Reads the " + (j.read_ceiling || 300) + " most recently updated projects, so a v2 bid older than that will not appear here.";
      render();
      // ?open=<id> deep link, once. A reload keeps the panel you were on.
      var want = new URLSearchParams(location.search).get("open");
      if (want && !OPENED_FROM_URL) { OPENED_FROM_URL = true; openPanel(want); }
    } catch (err) {
      if (LOADED) return;                    // a blip on the poll: keep what is on screen
      var list = $("list");
      list.className = "";
      list.innerHTML = failedHtml(err && err.message);
      $("toolbar").hidden = true;
      $("ceiling").hidden = true;
    }
  }

  // ── the card buttons (the Direct Projects card's own, portal.js) ─────────────
  // How long a hold pauses the chasing for, on a bid the customer HAS. portal.js HOLD_MONTHS, and the
  // backend's HOLD_PAUSE_MONTHS for the unsent half; test_v2_board.py keeps the three equal.
  var HOLD_MONTHS = 4;

  function api(path, opts) {
    var base = (window.TW && TW.resolveApiBase) ? TW.resolveApiBase() : "";
    opts = opts || {};
    opts.headers = Object.assign({}, TW.authHeaders(), opts.headers || {});
    return fetch(base + path, opts);
  }

  /** The row this button belongs to, out of ALL rather than the filtered pool: the minute poll can
   *  move a row between the paint and the click. null when the bid was trashed in another tab. */
  function cardRowOf(btn) {
    return rowFor(decodeURIComponent(btn.dataset.won || btn.dataset.lost || btn.dataset.handoff || ""));
  }

  /** One POST, with the button saying what it is doing, because the card moves out from under the
   *  cursor either way and a silent wait there looks like a dead control. `patch` moves the card on
   *  this paint instead of the next poll; load() then re-reads the truth. */
  async function post(btn, path, body, patch) {
    btn.disabled = true;
    var orig = btn.textContent;
    btn.textContent = "Saving…";
    var said = "";
    try {
      var r = await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      var j = await r.json().catch(function () { return {}; });
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      if (patch) { patch(); SIG = ""; render(); }
      load();
      said = j.followups_note || "";
    } catch (err) {
      btn.textContent = "Failed: " + (err.message || "retry");
      btn.disabled = false;
      setTimeout(function () { btn.textContent = orig; }, 2600);
      return;
    }
    // SAVED, BUT THE CUSTOMER IS STILL BEING EMAILED. Won and Hand it off switch the automatic
    // follow-up emails off (main.py _followups_off_for_outcome); when the portal could not be told,
    // the mark is saved anyway and the answer carries `followups_note`. portal.js markCardWon says it
    // in the same dialog. This board has no Follow-up tab, so "Open the project" goes to the Direct
    // Projects drawer's (the ?open=&sec=followup deep link the Follow-ups board uses). After the
    // try, so a dialog that failed could never be reported as a failed save.
    if (!said) return;
    var id = decodeURIComponent(btn.dataset.won || btn.dataset.handoff || btn.dataset.lost || "");
    if (await TW.confirmDanger({
      title: "Follow-up emails are still on", message: said,
      confirmText: "Open the project", cancelText: "OK", tone: "warn", icon: "warning",
    }) && id) window.location.assign("/portal.html?open=" + encodeURIComponent(id) + "&sec=followup");
  }

  /** Mark as won/approved. No prompt, as on Direct Projects: nothing is sent and the card stays on
   *  the board, in Won/Approved. */
  function markWon(btn) {
    var row = cardRowOf(btn);
    if (!row) return;
    post(btn, "/api/draft/" + encodeURIComponent(row.proposal_id) + "/status", { status: "won" },
         function () { row.won_at = new Date().toISOString(); });
  }

  /** Hand it off. Asks only when the contacts are not in (confirmHandoff below). */
  async function markHandoff(btn) {
    var row = cardRowOf(btn);
    if (!row) return;
    if (!(await confirmHandoff(row))) return;
    post(btn, "/api/draft/" + encodeURIComponent(row.proposal_id) + "/status", { status: "handed_off" },
         function () { row.handed_off_at = new Date().toISOString(); });
  }

  /** Mark as lost. The route follows whether the customer has the bid, the split portal.js makes: a
   *  sent bid has a portal row whose close-out also stops the cadence; an unsent one has only the
   *  draft. A hold is not patched onto the row: the card stays put and the pause date is the
   *  server's. */
  async function markLost(btn) {
    var row = cardRowOf(btn);
    if (!row) return;
    var why = await closeOutDialog(row, { unsent: !!row.not_sent });
    if (!why) return;
    var id = encodeURIComponent(row.proposal_id);
    var hold = why.outcome === "hold";
    var path = row.not_sent ? "/api/draft/" + id + "/status" : "/api/portal/proposal/" + id + "/status";
    var body = row.not_sent
      ? (hold ? { status: "on_hold", reason: why.reason, note: why.note }
              : { status: "closed_lost", reason: why.reason, note: why.note })
      : (hold ? { status: "delayed", months: HOLD_MONTHS, reason: why.reason, note: why.note }
              : { status: "closed_lost", reason: why.reason, note: why.note });
    post(btn, path, body, hold ? null : function () {
      row.proposal_status = "closed_lost";
      row.followup_state = Object.assign({}, row.followup_state, { closed_lost_reason: why.reason });
    });
  }

  /** + New: a fresh bid in the intake. The same three keys every "start a project" door clears
   *  (projects.js, portal.js startNewProposal), so shared.js mints a new draft id instead of resuming
   *  the last one, and polish-sandbox.js files the new bid the way it files every v2 bid. From the GC
   *  tab the bid starts as a GC one, as it does from the GC Projects board.
   *
   *  AND IT SAYS WHAT THE PROJECT IS STARTED AS, like every other door that starts one (X1, round 4, F2): a v2 estimate is a test project,
   *  so setNewProjectTestIntent("v2") mints the new project's id with its start under it, and the page that opens resumes that id. The start
   *  is the v2 page's: shared.js hands it to a v2 page that creates the project and to no other page (X1, round 5, L1), because the
   *  browser has ONE current draft and the live intake resumes it too (the sidebar's link, "/?new=1"): a real bid typed there was born a
   *  test when this said plain test. It comes AFTER the keys are cleared, which is what makes the id it mints the one the browser resumes. */
  function startNew() {
    try {
      localStorage.removeItem("treadwell.proposal_tool.state");
      localStorage.removeItem("treadwell.proposal_tool.draft_id");
      sessionStorage.removeItem("treadwell.proposal_tool.hydrated_once");
      if (TAB === "gc") localStorage.setItem("treadwell.proposal_tool.state", JSON.stringify({ audience: "GC" }));
    } catch (e) { /* private mode: the intake still opens, it just will not resume */ }
    TW.setNewProjectTestIntent("v2");
    window.location.assign("/polish-intake.html");
  }

  /** portal.js closeOutDialog, copied. Resolves { reason, note, outcome }, or null when dismissed.
   *  The comment is required, as there: a reason alone tells the sales meeting nothing. */
  function closeOutDialog(p, opts) {
    var C = window.TWCrm;
    var esc = V.esc;
    var unsent = !!(opts && opts.unsent);
    var name = p.project_name || "This project";
    return new Promise(function (resolve) {
      var ov = document.createElement("div");
      ov.className = "inv-ov";
      ov.innerHTML = '<div class="inv-dlg" role="dialog" aria-modal="true" aria-label="Close this bid out">'
        + '<div class="inv-h">Close this bid out?</div>'
        + '<p class="inv-sub" data-sub></p>'
        + '<label class="inv-f co-f"><span>Why?</span><select data-why>'
        + C.CLOSE_CHOICES.map(function (c) {
          return '<option value="' + esc(c.key) + '">' + esc(c.label) + "</option>";
        }).join("")
        + "</select></label>"
        + '<label class="inv-f co-f"><span>What happened? Required</span>'
        + '<textarea data-note rows="3" maxlength="2000" placeholder="We were 12% over Wilson on the pour,'
        + ' GC said they would call us for phase 2."></textarea></label>'
        + '<p class="note co-err" data-err></p>'
        + '<div class="inv-act"><button type="button" class="btn btn-s" data-x>Cancel</button>'
        + '<button type="button" class="btn btn-p" data-go disabled>Close it out</button></div></div>';
      document.body.appendChild(ov);
      var sel = ov.querySelector("[data-why]");
      var note = ov.querySelector("[data-note]");
      var err = ov.querySelector("[data-err]");
      var go = ov.querySelector("[data-go]");
      var sub = ov.querySelector("[data-sub]");
      function paint() {
        var hold = C.closeOutcome(sel.value) === "hold";
        go.textContent = hold ? "Put it on hold" : "Close it out";
        sub.textContent = hold
          ? name + " stays on the board and the reminder emails pause for about "
            + HOLD_MONTHS + " months. Nothing is sent to the customer. You can bring it back sooner."
          : name + (unsent
            ? " moves to the Lost tab under the reason you pick. It was never sent, so nothing"
              + " changes for the customer."
            : " moves out of the pipeline and all follow-ups stop. The customer is not emailed.")
            + " You can bring it back later.";
        var filled = !!note.value.trim();
        go.disabled = !filled;
        err.textContent = filled ? ""
          : "Say what happened. One sentence is plenty, and it is the part the sales meeting reads.";
      }
      paint();
      function onKey(e) { if (e.key === "Escape") close(null); }
      function close(v) { ov.remove(); document.removeEventListener("keydown", onKey); resolve(v); }
      document.addEventListener("keydown", onKey);
      sel.addEventListener("change", paint);
      note.addEventListener("input", paint);
      note.addEventListener("change", paint);
      ov.querySelector("[data-x]").addEventListener("click", function () { close(null); });
      ov.addEventListener("click", function (e) { if (e.target === ov) close(null); });
      go.addEventListener("click", function () {
        var text = note.value.trim();
        if (!text) { paint(); note.focus(); return; }
        var reason = sel.value || "other";
        close({ reason: reason, note: text, outcome: C.closeOutcome(reason) });
      });
      sel.focus();
    });
  }

  /** portal.js confirmHandoff, copied: a prompt only when the contacts are not in. */
  function confirmHandoff(p) {
    if (p && p.contacts_status === "received") return Promise.resolve(true);
    return TW.confirmDanger({
      title: "Hand it off anyway?",
      before: "We have not recorded the contact info for ",
      name: (p && p.project_name) || "this project",
      after: " yet.",
      detail: "Handing off takes it off the board and onto the Handed off tab. Operations"
        + " will need those details from somewhere. You can bring it back.",
      confirmText: "Hand it off", cancelText: "Not yet", tone: "warn", icon: "arrow-right",
    });
  }

  // ── wiring ────────────────────────────────────────────────────────────────
  $("v2-tabs").addEventListener("click", function (e) {
    var b = e.target.closest("[data-tab]");
    if (!b || b.dataset.tab === TAB) return;
    TAB = V.normTab(b.dataset.tab);
    ssSet(KEYS.tab, TAB);
    render();
  });
  $("list").addEventListener("click", function (e) {
    if (e.target.closest("#retry")) { load(); return; }
    // The buttons sit inside a .deal, so each returns before the card's own click opens the panel.
    var b;
    if ((b = e.target.closest("[data-won]"))) { markWon(b); return; }
    if ((b = e.target.closest("[data-handoff]"))) { markHandoff(b); return; }
    if ((b = e.target.closest("[data-lost]"))) { markLost(b); return; }
    if (e.target.closest("[data-new-v2]")) { startNew(); return; }
    var d = e.target.closest(".deal");
    if (d && d.dataset.id) openPanel(d.dataset.id);
  });
  $("new-v2").addEventListener("click", startNew);
  $("list").addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    // Enter on a focused card button is that button's own click, not "open the card".
    if (e.target.closest && e.target.closest("button")) return;
    var d = e.target.closest && e.target.closest(".deal");
    if (!d) return;
    e.preventDefault();
    openPanel(d.dataset.id);
  });
  $("v2-panel").addEventListener("click", function (e) {
    if (e.target.closest("[data-v2-close]")) closePanel();
  });
  $("v2-scrim").addEventListener("click", closePanel);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && CUR) closePanel(); });

  var t = null;
  $("q").addEventListener("input", function (e) {
    SEARCH = e.target.value;
    ssSet(KEYS.search, SEARCH);
    clearTimeout(t);
    t = setTimeout(render, 120);
  });
  $("est").addEventListener("change", function (e) {
    EST = e.target.value;
    ssSet(KEYS.est, EST);
    render();
  });
  $("clear").addEventListener("click", function () {
    SEARCH = ""; EST = "";
    ssSet(KEYS.search, ""); ssSet(KEYS.est, "");
    $("q").value = "";
    render();
  });

  load();
  // Another estimator's new v2 bid should appear without an F5.
  setInterval(function () { if (!document.hidden) load(); }, 60000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
})();
