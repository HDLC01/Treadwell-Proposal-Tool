// Externalized from polish-estimates.html (CSP: script-src has no 'unsafe-inline').
// Do not add inline scripts or onclick= handlers; both fail silently in production.
//
// THE v2 ESTIMATES BOARD (BETA). Every Estimating Tool v2 bid, from the moment it is created, in
// the same columns as the Direct Projects board, with Direct and GC as two tabs. Hanz, 2026-10-13:
// "make the V2 have a pipeline like the ones we have for active projects", "make sure they are
// separate tho", and "the V2 pipeline is still in beta ... so do not merge it to the existing".
//
// SO THIS PAGE OWNS ITS OWN CODE. It reads the shared DOM-free helpers (js/crm-core.js, through
// js/v2-board-core.js) and never loads or calls js/portal.js. Its data is its own route,
// /api/v2/pipeline. Its storage keys are all `tw_v2_*` (TWV2Board.KEYS); it never touches the real
// boards' `tw_crm_*` keys or the `treadwell.proposal_tool.*` keys.
//
// NOTHING ON THIS PAGE WRITES. A card opens a read-only panel with an "Open in Estimating Tool v2"
// link. There is no send, follow-up, deposit, chat or status control here, and the panel markup
// that would carry one is pinned empty by test_v2_board.py.
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
    var d = e.target.closest(".deal");
    if (d && d.dataset.id) openPanel(d.dataset.id);
  });
  $("list").addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
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
