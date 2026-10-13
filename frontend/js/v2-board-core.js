// The v2 Estimates board: pure logic and markup, no DOM access, no fetch, no storage.
// Externalized so it runs under node (CSP: no inline scripts). js/v2-board.js owns the page.
//
// BETA, AND SEPARATE ON PURPOSE. Hanz, 2026-10-13: "the V2 pipeline is still in beta ... so do not
// merge it to the existing". This file READS the shared, DOM-free js/crm-core.js (stage, group,
// onBoard, cardTotal, sort and the person chip) so the columns match the Direct Projects board
// exactly, and it changes none of it. It does not call into js/portal.js, which draws the real
// boards, and the real boards do not know this file exists.
//
// READ ONLY. Nothing built here is a control that reaches a customer: no send, no follow-up, no
// deposit, no chat, no won/lost/hand-off buttons. A card opens a small panel with facts and ONE
// link, to the Estimating Tool v2 intake, where the bid is actually worked on.
//
// ITS OWN STORAGE KEYS (KEYS below, all `tw_v2_*`). The real boards keep theirs under `tw_crm_*`, and
// `tw_crm_view_<tab>` is not even per-pipeline, so nothing here may read or write any of them.
(function (root, factory) {
  var C = root.TWCrm;
  if (!C && typeof require !== "undefined") C = require("./crm-core.js");   // node, for tests
  var api = factory(C);
  root.TWV2Board = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this, function (C) {
  "use strict";

  var KEYS = { tab: "tw_v2_tab", est: "tw_v2_est", search: "tw_v2_search" };
  // Direct and GC are the two boards (by audience). Lost and Handed off only appear when they
  // hold a v2 bid (tabsToShow), so a beta board does not open with two tabs that say 0.
  var TABS = ["direct", "gc", "lost", "handed_off"];
  var TAB_LABEL = { direct: "Direct", gc: "GC", lost: "Lost", handed_off: "Handed off" };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Whole dollars, losslessly: a trailing ".00" goes, a real fraction stays. Same rule as the real
  // board's money() so one bid reads the same on both. null is "" here; callers decide the dash.
  function money(n) {
    if (n == null) return "";
    var s = "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return s.slice(-3) === ".00" ? s.slice(0, -3) : s;
  }

  function openHref(id) { return "/polish-intake.html?d=" + encodeURIComponent(String(id)); }

  // ── which cards, on which tab ──────────────────────────────────────────────
  // The four pools PARTITION the rows: a dead deal is Lost whichever board it was on, a handed-off
  // one is Handed off, and everything else is live on the board its audience names. Test copies
  // are live work here (every v2 copy is filed as a test), so they sit on Direct or GC with a chip.
  function isLive(p) { return !C.isLost(p) && !C.isHandedOff(p); }

  function pool(rows, tab) {
    var list = rows || [];
    if (tab === "lost") return list.filter(C.isLost);
    if (tab === "handed_off") return list.filter(function (p) { return !C.isLost(p) && C.isHandedOff(p); });
    return C.onBoard(list, tab === "gc" ? "gc" : "direct").filter(isLive);
  }

  function counts(rows) {
    var out = {};
    TABS.forEach(function (t) { out[t] = pool(rows, t).length; });
    return out;
  }

  /** The tabs worth drawing: Direct and GC always, Lost / Handed off only when they hold a bid (or
   *  are the tab you are on, so a remembered tab never vanishes under you). */
  function tabsToShow(rows, current) {
    var n = counts(rows);
    return TABS.filter(function (t) { return t === "direct" || t === "gc" || n[t] > 0 || t === current; });
  }

  /** A stored tab that no longer exists falls back to Direct rather than painting nothing. */
  function normTab(t) { return TABS.indexOf(t) >= 0 ? t : "direct"; }

  function columnsFor(tab) {
    if (tab === "lost") return [C.STAGE_LOST];
    if (tab === "handed_off") return C.HANDOFF_COLS;
    return C.STAGES;
  }

  function groupFor(items, tab) {
    if (tab === "lost") { var by = {}; by[C.STAGE_LOST] = items.slice(); return by; }
    if (tab === "handed_off") return C.groupHandedOff(items);
    return C.group(items, C.STAGES);
  }

  // ── filters: search and estimator only. Month and sort are deliberately gone. ──
  function filterSearch(items, q) {
    var t = String(q || "").toLowerCase().trim();
    if (!t) return items;
    var tokens = t.split(/\s+/);
    return items.filter(function (p) {
      var hay = [p.project_name, p.customer_email, p.customer_name, C.estimatorOf(p),
                 C.nameOf(C.estimatorOf(p))].filter(Boolean).join(" ").toLowerCase();
      return tokens.every(function (w) { return hay.indexOf(w) >= 0; });
    });
  }

  function filterEstimator(items, est) {
    return est ? items.filter(function (p) { return C.estimatorOf(p).toLowerCase() === est; }) : items;
  }

  /** {email: count} over a pool, for the estimator menu: it never offers a person with no cards. */
  function estimatorCounts(items) {
    var by = {};
    items.forEach(function (p) {
      var e = C.estimatorOf(p).toLowerCase();
      if (e) by[e] = (by[e] || 0) + 1;
    });
    return by;
  }

  // ── markup. Classes are the Direct Projects board's own (.col, .deal, .chip, ...). ──
  function dateOf(ts, env) { return env && env.fmtDate ? env.fmtDate(ts) : String(ts || "").slice(0, 10); }

  function chipsHtml(p) {
    var out = [];
    if (C.isLost(p)) {
      var why = C.lostReason(p);
      out.push('<span class="chip chip-lost">Closed lost' + (why ? " · " + esc(why) : "") + "</span>");
    } else {
      if (p.portal_unknown) out.push('<span class="chip chip-unknown" title="Sent, but the customer portal is not answering, so the status is unknown">Portal status unknown</span>');
      if (C.isWon(p)) out.push('<span class="chip chip-won">Won</span>');
      if (C.isHandedOff(p)) out.push('<span class="chip chip-handoff">Handed off</span>');
    }
    // A test copy says so on every tab. Estimating Tool v2 files each copy it makes as a test, so
    // this is expected on most cards and deliberately quiet.
    if (C.isTest(p)) out.push('<span class="chip chip-test" title="A test copy made in Estimating Tool v2">Test</span>');
    return out.join("");
  }

  function whoHtml(p) {
    var email = C.estimatorOf(p);
    if (!email) return '<span class="unassigned" title="Nobody is assigned">&mdash;</span>';
    var on = C.isAssigned(p);
    return C.avatarHtml(email, !on)
      + "<span" + (on ? "" : ' class="unassigned" title="Nobody is assigned. This is whoever built the estimate"') + ">"
      + esc(C.nameOf(email)) + (on ? "" : "?") + "</span>";
  }

  function cardHtml(p, env) {
    var act = C.lastActivity(p);
    var total = C.cardTotal(p);
    var chips = chipsHtml(p);
    return '<div class="deal" data-id="' + esc(p.proposal_id) + '" tabindex="0">'
      + '<div class="name">' + esc(p.project_name || "Untitled") + "</div>"
      + (p.customer_email ? '<div class="meta">' + esc(p.customer_email) + "</div>" : "")
      + '<div class="meta who"><span class="k">Estimator:</span> ' + whoHtml(p) + "</div>"
      + (act ? '<div class="meta act"><span class="k">' + esc(act.label) + ":</span> " + esc(dateOf(act.ts, env)) + "</div>" : "")
      + (chips ? '<div class="chips">' + chips + "</div>" : "")
      // A bid with no price yet shows a dash, never $0: a v2 bid is saved before it has a price.
      + (total != null ? '<div class="val" title="Priced in Estimating Tool v2">' + esc(money(total)) + "</div>"
                       : '<div class="val val-none" title="Not priced yet">&mdash;</div>')
      + "</div>";
  }

  function boardHtml(items, tab, env) {
    if (tab !== "direct" && tab !== "gc" && !items.length) {
      return '<div class="empty">Nothing here.</div>';
    }
    var cols = columnsFor(tab);
    var by = groupFor(C.sort(items, "activity", "desc"), tab);
    return cols.map(function (c) {
      var cards = by[c].map(function (p) { return cardHtml(p, env); }).join("") || '<div class="empty">&mdash;</div>';
      return '<div class="col"><h2>' + esc(c) + "<span>" + by[c].length + "</span></h2>" + cards + "</div>";
    }).join("");
  }

  /** The two kinds of empty, told apart: no v2 estimate exists at all (explain where they come
   *  from), or there are some and the search / estimator filter hides every one. */
  function emptyHtml(totalRows, filtered) {
    if (totalRows > 0 || filtered) {
      return '<div class="card-empty"><p class="empty-h">Nothing matches that.</p>'
        + '<p class="empty-p">Clear the search or the estimator, or look at the other tab.</p></div>';
    }
    return '<div class="card-empty"><p class="empty-h">No v2 estimates yet.</p>'
      + '<p class="empty-p">A bid lands here the moment it is created in <b>Estimating Tool v2</b>. '
      + "Bids priced on the spreadsheet stay on the Direct Projects and GC Projects boards.</p></div>";
  }

  // ── the read-only panel ─────────────────────────────────────────────────────
  // Facts and ONE link. The only button is Close. test_v2_board.py reads this markup and fails if a
  // send, follow-up, deposit, chat or status control ever appears in it.
  function panelHtml(p, env) {
    var act = C.lastActivity(p);
    var total = C.cardTotal(p);
    var email = C.estimatorOf(p);
    function row(k, v) { return "<dt>" + esc(k) + "</dt><dd>" + v + "</dd>"; }
    var chips = chipsHtml(p);
    return '<div class="v2p-head"><h2>' + esc(p.project_name || "Untitled") + '</h2>'
      + '<button type="button" class="v2p-close" data-v2-close aria-label="Close">Close</button></div>'
      + '<p class="v2p-beta"><span class="tag">Beta</span> Read only. Nothing on this panel reaches a customer.</p>'
      + (chips ? '<div class="chips">' + chips + "</div>" : "")
      + "<dl>"
      + row("Project", esc(p.project_name || "Untitled"))
      + row("Estimator", email ? esc(C.nameOf(email)) + (C.isAssigned(p) ? "" : " (whoever built it)") : "Nobody yet")
      + row("Stage", esc(C.stage(p)))
      + row("v2 total", total != null ? esc(money(total)) : "Not priced yet")
      + row("Last updated", act ? esc(dateOf(act.ts, env)) : "&mdash;")
      + "</dl>"
      + '<a class="v2p-open" href="' + esc(openHref(p.proposal_id)) + '">Open in Estimating Tool v2</a>';
  }

  return {
    KEYS: KEYS, TABS: TABS, TAB_LABEL: TAB_LABEL,
    esc: esc, money: money, openHref: openHref,
    pool: pool, counts: counts, tabsToShow: tabsToShow, normTab: normTab,
    columnsFor: columnsFor, groupFor: groupFor,
    filterSearch: filterSearch, filterEstimator: filterEstimator, estimatorCounts: estimatorCounts,
    chipsHtml: chipsHtml, cardHtml: cardHtml, boardHtml: boardHtml, emptyHtml: emptyHtml,
    panelHtml: panelHtml,
  };
});
