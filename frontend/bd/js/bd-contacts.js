/* Contacts, /bd/contacts.html (#810: BD's contacts page, rebuilt as the approved mock-up's list of BD
 * accounts, restyled like the tool). Optional ?company=<id> (open that account), ?q= (a search) and
 * ?tab=maintenance.
 *
 * Two tabs, BD and Maintenance, each a list of companies ("BD accounts", Q19; the Maintenance tab is
 * grouped by company too since 2026-11-20, Q6). A company row says how many of that tab's people work
 * there, who owns them (the salesperson who owns the most, plus "+N" other salespeople; a tie goes to
 * whoever had the latest live talk there, Q33 and Q41), and the last live talk with anyone there (Q34). The server
 * works all of that out (GET /api/bd/contacts/accounts); the page only draws it. A row opens to its
 * people: name, title, phone, email, the status pill, and a link to each one's contact page.
 *
 * SEARCH (Q22, Q35). The box asks GET /api/bd/contacts/search?q= (the term rides ?q=, never a path, so
 * the audit log never holds it). The page then shows the matched accounts on the tab the first hit is
 * on, open, with the people who matched highlighted, says what it found (BD.announce), and offers the
 * other tab's hits. The term stays in the address (?q=), so Back from a contact comes back to it.
 *
 * MAKE MAINTENANCE ACCOUNT / MOVE BACK TO BD (2026-11-20, Q1-Q11). Each company row has a "..." button,
 * and a right-click on the row opens the same menu. One item: "Make maintenance account" on the BD tab,
 * "Move back to BD" on the Maintenance tab. A one-line confirm names the company and how many people
 * move; the server does the rest at once. The server keeps the move undoable for two minutes, and only
 * for whoever made it: the toast offers Undo for a few seconds, and a line under the tabs (#ct-moved)
 * keeps one, focused after the move and announced, until the two minutes are up (WCAG 2.2.1).
 *
 * LIKELY DUPLICATE BD ACCOUNTS (#811, Q21, Q36). On the Possible duplicates filter (?filter=dupes), for
 * merge_companies, the mock-up's "Same account?" notes sit above the list (#ct-dupes): both names,
 * their people, the shared phone or email domain the server found (a hint only), Merge and Keep
 * separate. The list under them holds the flagged people's accounts (#810, unchanged), both accounts
 * of each pair, and the survivor of each recent merge. Merge asks which name stays, in a dialog (a
 * bottom sheet on a phone); the account whose name stays is the one that stays, so the line reads
 * "Move 1 person from X into Y?". Every merge can be undone with no time limit: the toast offers Undo,
 * and "Recently merged" (the server's latest 10 that Undo may still take) keeps one per merge; a
 * refused Undo leaves focus on that one. Keep separate is for good, so it asks first and its toast has
 * no Undo. To tidy's Duplicates card counts the pairs with the flagged people. ?filter=dupes is the
 * link to this view; no other chip is read from or written to the address.
 *
 * WHAT A PERSON MAY DO COMES FROM can (bd/auth.py can()), never from a role name:
 *   import          Import (a workbook, BD's practice run first: BD.importWorkbook)
 *   admin_area      To tidy this Friday (possible duplicates, people to confirm, unknown calls, each
 *                   call with "Attach to a contact", a link to Admin, which opens for exactly these
 *                   people), and "Past imports" in the Import menu
 *   add_contact     Add contact, and "Add someone here" in an opened account
 *   clear_duplicate the Possible duplicates chip
 *   move_company    the "..." menu (Q5: never the assistant)
 *   merge_companies the "Same account?" notes, Merge, Undo, Keep separate and Recently merged, and the
 *                   pairs in To tidy's Duplicates count (Q21, Q36: never a salesperson or the manager)
 *   week without pick_owner (a salesperson, working their own list): BD's chips and sorts for them,
 *                   All and Mine and no "Last live talk" sort (BD's "no overdue pile" rule)
 *
 * Routes (docs/bd/api-contract.md): GET /api/bd/contacts/accounts (both tabs, paged at 500),
 * GET /api/bd/contacts/search, POST /api/bd/contacts/accounts/{id}/move,
 * POST /api/bd/contacts/accounts/moves/{id}/undo, GET /api/bd/admin/unmatched-calls,
 * POST /api/bd/admin/unmatched-calls/{id}/dismiss, GET /api/bd/admin/imports, POST /api/bd/admin/import,
 * GET /api/bd/contacts/accounts/duplicates (paged at 500), POST /api/bd/contacts/accounts/{id}/merge,
 * POST /api/bd/contacts/accounts/merges/{id}/undo, POST /api/bd/contacts/accounts/duplicates/keep.
 * Dates are Central, from /api/bd/me's today (never the PC clock).
 */
(function () {
  "use strict";

  var BD = window.BD, Api = window.BDApi;
  var esc = BD.esc, errText = BD.errText;

  var TABS = ["bd", "maintenance"];
  var TAB_NAME = { bd: "BD", maintenance: "Maintenance" };
  var SORTS = [["name", "Account A-Z"], ["people", "Most people"], ["last", "Last live talk"]];
  var CALLS_SHOWN = 3;            // the unknown calls To tidy shows; the rest are on Admin
  var UNDO_MS = 10000;            // the toast's Undo; the server allows two minutes
  var UNDO_WINDOW_MS = 120000;    // the server's two minutes: the page's own Undo (#ct-moved) lasts this long
  var PAGE = 500;

  var S = {
    can: {}, me: null, today: "", ownList: false,
    tab: "bd", lists: { bd: [], maintenance: [] }, loaded: false,
    open: {}, sort: "name", chip: "all",
    q: "", hits: null, seq: 0, undo: null,
    unknown: null, unknownOpen: false, lastImport: null,
    dupes: null, dupesErr: null, merging: {}, mergeToasts: {},
  };

  function $(id) { return document.getElementById(id); }
  function ico(name, size) { return BD.icon(name, size || 18); }
  function key(tab, id) { return tab + ":" + id; }
  function other(tab) { return tab === "bd" ? "maintenance" : "bd"; }
  function setHtml(id, v) { var el = $(id); if (el) el.innerHTML = v; }
  function show(id, on) { var el = $(id); if (el) el.hidden = !on; }
  function plural(n, one, many) { return BD.plural(n, one, many); }
  function peopleWord(n) { return plural(n, "person", "people"); }
  function people(list) { return list.reduce(function (n, a) { return n + (Number(a.people_count) || 0); }, 0); }
  function account(tab, id) {
    return S.lists[tab].filter(function (a) { return String(a.id) === String(id); })[0] || null;
  }
  function focusId(id) { var el = $(id); if (el && el.focus) el.focus(); }

  // ── loading ────────────────────────────────────────────────────────────────────────────────
  function fetchTab(tab) {
    var out = [];
    function next() {
      return Api.get("/api/bd/contacts/accounts?category=" + tab + "&limit=" + PAGE + "&offset=" + out.length).then(function (r) {
        var items = r.items || [];
        out = out.concat(items);
        return items.length && out.length < (Number(r.total) || 0) ? next() : out;
      });
    }
    return next();
  }

  function loadLists() {
    return Promise.all(TABS.map(fetchTab)).then(function (r) {
      S.lists = { bd: r[0], maintenance: r[1] };
      S.loaded = true;
    });
  }

  /** The likely duplicate account pairs and the recent merges (merge_companies only), every page of
   *  pairs; the first answer's merges. A failure is kept to say on the filter, never thrown. */
  function loadDupes() {
    if (S.can.merge_companies !== true) return Promise.resolve();
    var items = [], merges = null;
    function next() {
      return Api.get("/api/bd/contacts/accounts/duplicates?limit=" + PAGE + "&offset=" + items.length).then(function (r) {
        var got = r.items || [];
        items = items.concat(got);
        if (merges === null) merges = r.merges || [];
        return got.length && items.length < (Number(r.total) || 0) ? next() : null;
      });
    }
    return next().then(function () {
      S.dupes = { items: items, merges: merges || [] };
      S.dupesErr = null;
    }, function (e) {
      S.dupes = null;
      S.dupesErr = e;
    });
  }

  /** To tidy's calls and the Import menu's last run: optional, so a failure is nothing. */
  function loadExtras() {
    if (S.can.admin_area !== true) return Promise.resolve();
    var jobs = [Api.get("/api/bd/admin/unmatched-calls").then(function (r) {
      S.unknown = (r.items || []).filter(function (u) { return !u.status || u.status === "open"; })
        .sort(function (a, b) { return String(b.occurred_at).localeCompare(String(a.occurred_at)); });
    }, function () { S.unknown = null; })];
    if (S.can["import"] === true) {
      jobs.push(Api.get("/api/bd/admin/imports?limit=1").then(function (r) {
        S.lastImport = (r.items || [])[0] || null;
      }, function () { S.lastImport = null; }));
    }
    return Promise.all(jobs);
  }

  // ── the address ────────────────────────────────────────────────────────────────────────────
  function syncUrl() {
    var p = [];
    if (S.tab !== "bd") p.push("tab=" + S.tab);
    if (S.q) p.push("q=" + encodeURIComponent(S.q));
    else if (S.tab === "bd" && S.chip === "dupes") p.push("filter=dupes");
    try {
      window.history.replaceState(null, "", window.location.pathname + (p.length ? "?" + p.join("&") : ""));
    } catch (e) { /* the address just stays */ }
  }

  // ── what a tab shows ───────────────────────────────────────────────────────────────────────
  function chipDefs() {
    var mine = { key: "mine", label: "Mine", test: function (p) { return !!(p.owner && S.me && p.owner.id === S.me.id); } };
    var all = { key: "all", label: "All" };
    if (S.ownList) return [all, mine];
    var out = [all, mine,
      { key: "confirm", label: "Needs confirming", test: function (p) { return p.confirmed === false; } },
      { key: "never", label: "Never reached", test: function (p) { return p.cadence_status === "never"; } }];
    if (S.can.clear_duplicate === true) {
      out.push({ key: "dupes", label: "Possible duplicates", test: function (p) { return !!p.duplicate_of; } });
    }
    return out;
  }
  function chipOf(k) { return chipDefs().filter(function (d) { return d.key === k; })[0] || null; }

  function sortAllowed(v) { return !(v === "last" && S.ownList) && SORTS.some(function (s) { return s[0] === v; }); }

  /** The "Same account?" notes show: merge_companies, on the Possible duplicates filter of the BD tab. */
  function dupesView() {
    return S.can.merge_companies === true && S.tab === "bd" && !S.hits && S.chip === "dupes";
  }
  function pairsOf() { return S.dupes ? S.dupes.items : []; }

  /** {account id: true} for both accounts of each likely pair and the survivor of each recent merge:
   *  the Possible duplicates filter lists them beside the flagged people's accounts. Nothing unless
   *  the pairs loaded, which they do for merge_companies only (loadDupes). */
  function dupeAccounts() {
    var out = {};
    if (!S.dupes) return out;
    pairsOf().forEach(function (d) { out[d.a.id] = true; out[d.b.id] = true; });
    S.dupes.merges.forEach(function (m) { if (m.into) out[m.into.id] = true; });
    return out;
  }

  var COMPARE = {
    // the server's order is by name already; the index keeps it for ties
    name: function (a, b) { return a._i - b._i; },
    people: function (a, b) { return (b.a.people_count - a.a.people_count) || (a._i - b._i); },
    last: function (a, b) {
      var x = a.a.last_live_at ? Date.parse(a.a.last_live_at) : null, y = b.a.last_live_at ? Date.parse(b.a.last_live_at) : null;
      if (x === y) return a._i - b._i;
      if (x === null) return 1;
      if (y === null) return -1;
      return y - x;
    },
  };

  /** The accounts the open tab shows: a search's hits, or the chip's, sorted. */
  function shown() {
    var list = S.lists[S.tab];
    if (S.hits) {
      var hits = S.hits[S.tab];
      list = list.filter(function (a) { return !!hits[a.id]; });
    } else if (S.tab === "bd" && S.chip !== "all") {
      var c = chipOf(S.chip);
      var also = S.chip === "dupes" ? dupeAccounts() : {};
      if (c) list = list.filter(function (a) { return !!also[a.id] || (a.people || []).some(c.test); });
    }
    var cmp = COMPARE[S.sort] || COMPARE.name;
    return list.map(function (a, i) { return { a: a, _i: i }; }).sort(cmp).map(function (x) { return x.a; });
  }

  // ── the header and the tabs ────────────────────────────────────────────────────────────────
  function renderHead() {
    var bd = S.lists.bd, mt = S.lists.maintenance;
    var sub = $("ct-sub");
    if (sub) {
      sub.textContent = bd.length || mt.length
        ? peopleWord(people(bd)) + " at " + plural(bd.length, "BD account") + " · " + plural(people(mt), "maintenance contact")
        : "No one here yet.";
    }
    TABS.forEach(function (t) {
      var b = $("ct-tab-" + t);
      if (!b) return;
      b.innerHTML = esc(t === "bd" ? "BD accounts" : "Maintenance") + ' <span class="count">' + esc(BD.fmtCount(S.lists[t].length)) + "</span>";
      b.setAttribute("aria-selected", t === S.tab ? "true" : "false");
      b.setAttribute("tabindex", t === S.tab ? "0" : "-1");
    });
    var list = $("ct-list");
    if (list) list.setAttribute("aria-labelledby", "ct-tab-" + S.tab);
  }

  function renderTools() {
    var sel = $("ct-sort");
    if (sel) {
      sel.innerHTML = SORTS.filter(function (s) { return sortAllowed(s[0]); }).map(function (s) {
        return '<option value="' + esc(s[0]) + '"' + (s[0] === S.sort ? " selected" : "") + ">" + esc(s[1]) + "</option>";
      }).join("");
      sel.value = S.sort;
    }
    var chips = $("ct-chips");
    if (!chips) return;
    chips.hidden = S.tab !== "bd" || !!S.hits;
    chips.innerHTML = chipDefs().map(function (d) {
      return '<button type="button" class="chip-filter" data-chip="' + esc(d.key) + '" aria-pressed="' +
        (S.chip === d.key ? "true" : "false") + '">' + esc(d.label) + "</button>";
    }).join("");
  }

  // ── To tidy this Friday (admin_area) ───────────────────────────────────────────────────────
  function tidyCards() {
    var bd = [];
    S.lists.bd.forEach(function (a) { bd = bd.concat(a.people || []); });
    // the flagged people (#810) and the likely account pairs (#811; loaded for merge_companies only), as the mock-up counts
    var dup = bd.filter(function (p) { return !!p.duplicate_of; }).length + pairsOf().length;
    var conf = bd.filter(function (p) { return p.confirmed === false; }).length;
    var cards = [];
    if (S.can.clear_duplicate === true) {
      cards.push({ key: "dupes", n: dup, label: dup === 1 ? "Duplicate" : "Duplicates", tail: " to check", icon: "copy", tone: "warn" });
    }
    cards.push({ key: "confirm", n: conf, label: "To confirm", tail: "", icon: "help-circle", tone: "warn" });
    if (S.unknown) {
      cards.push({ key: "unknown", n: S.unknown.length, label: S.unknown.length === 1 ? "Unknown call" : "Unknown calls",
        tail: "", icon: "phone-incoming", tone: "info" });
    }
    return cards;
  }

  function tidyCardHtml(t) {
    var zero = t.n === 0;
    var inner = '<span class="ct-tidy-ico" data-tone="' + (zero ? "ok" : t.tone) + '">' + ico(zero ? "check" : t.icon, 20) + "</span>" +
      '<span class="ct-tidy-text"><span class="ct-tidy-n">' + esc(BD.fmtCount(t.n)) + "</span> " +
      '<span class="ct-tidy-label">' + esc(t.label) + (t.tail ? '<span class="sr-only">' + esc(t.tail) + "</span>" : "") + "</span></span>";
    if (t.key === "unknown") {
      return '<button type="button" class="ct-tidy-card" data-tidy="unknown" aria-controls="ct-unknown" aria-expanded="' +
        (S.unknownOpen ? "true" : "false") + '">' + inner + "</button>";
    }
    return '<button type="button" class="ct-tidy-card" data-tidy="' + t.key + '" aria-pressed="' +
      (S.tab === "bd" && !S.hits && S.chip === t.key ? "true" : "false") + '">' + inner + "</button>";
  }

  function renderTidy() {
    var box = $("ct-tidy");
    if (!box) return;
    box.hidden = S.can.admin_area !== true;
    if (box.hidden) return;
    var cards = tidyCards();
    var any = cards.some(function (t) { return t.n > 0; });
    setHtml("ct-tidy-cards", any
      ? '<div class="ct-tidy-grid">' + cards.map(tidyCardHtml).join("") + "</div>"
      : '<p class="ct-tidy-none">' + ico("check-circle", 20) + "<span>Nothing to tidy. Nice.</span></p>");
    if (!any) S.unknownOpen = false;
    renderUnknown();
  }

  function renderUnknown() {
    var box = $("ct-unknown");
    if (!box) return;
    if (!S.unknownOpen || !S.unknown) { box.hidden = true; box.innerHTML = ""; return; }
    box.hidden = false;
    if (!S.unknown.length) {
      box.innerHTML = '<div class="ct-unknown-card"><p class="ct-unknown-none">No unknown calls.</p></div>';
      return;
    }
    var calls = S.unknown.slice(0, CALLS_SHOWN);
    box.innerHTML = '<ul class="ct-unknown-card" aria-label="Unknown calls, newest first">' + calls.map(function (u) {
      var w = BD.callWords(u);
      var tel = BD.telHref(u.from_e164);
      var sum = (u.summary ? "“" + u.summary + "”" : "No summary") + " · " + w.length;
      return '<li class="ct-call" data-call="' + esc(u.id) + '">' +
        '<div class="ct-call-main"><p class="ct-call-line">' +
        (tel ? '<a class="ct-call-tel" href="' + esc(tel) + '">' + esc(w.phone) + "</a>" : esc(w.phone)) + " " +
        esc(w.way.toLowerCase()) + " " + esc(w.when) + "</p>" +
        '<p class="ct-call-sum">' + esc(sum) + "</p></div>" +
        '<div class="wrap-row ct-call-acts">' +
        '<a class="btn" href="/bd/admin.html#ad-s-phone">' + ico("link", 18) + "<span>Attach to a contact</span>" +
        '<span class="sr-only"> (' + esc(w.phone) + ")</span></a>" +
        '<button type="button" class="btn btn-tertiary" data-act="unknown-dismiss" data-id="' + esc(u.id) + '">Not a contact' +
        '<span class="sr-only"> (' + esc(w.phone) + ")</span></button>" +
        "</div></li>";
    }).join("") +
      (S.unknown.length > calls.length
        ? '<li class="ct-call-more"><a class="btn-link" href="/bd/admin.html#ad-s-phone">See all ' + esc(S.unknown.length) +
          " in Admin" + ico("arrow-right", 16) + "</a></li>" : "") +
      "</ul>";
  }

  function dismissUnknown(btn) {
    var id = btn.getAttribute("data-id");
    var call = (S.unknown || []).filter(function (u) { return String(u.id) === String(id); })[0];
    if (!call) return;
    BD.dismissCall(call, btn).then(function (done) {
      if (!done) return;
      S.unknown = S.unknown.filter(function (u) { return String(u.id) !== String(id); });
      renderTidy();
      var card = document.querySelector('[data-tidy="unknown"]');
      if (card) card.focus(); else focusId("ct-tidy-h");
      BD.toast("Call dismissed.", { kind: "ok" });
    }, function (e) {
      BD.toast(errText(e), { kind: "error" });
    });
  }

  // ── the list ───────────────────────────────────────────────────────────────────────────────
  /** The one cadence pill a person may carry (BD's): a due maintenance follow-up ("Due now"), or an
   *  active override ("Monthly until Dec 31"). */
  function cadPill(p) {
    if (p.category === "maintenance") return p.maintenance_due ? BD.pill("warn", "Due now") : "";
    if (p.cadence_source === "override" && p.cadence && p.cadence_override_until) {
      return BD.pill("info", p.cadence.charAt(0).toUpperCase() + p.cadence.slice(1) + " until " + BD.fmtMonthDay(p.cadence_override_until, S.today));
    }
    return "";
  }

  function lastWords(iso) { return iso ? BD.fmtDay(iso, S.today) : "Never"; }

  /** The row's flags: what needs a look at that account, at a glance. */
  function flags(a) {
    var ps = a.people || [];
    var dup = ps.filter(function (p) { return !!p.duplicate_of; }).length;
    var conf = ps.filter(function (p) { return p.confirmed === false; }).length;
    var out = [];
    if (dup) out.push(BD.pill("warn", plural(dup, "possible duplicate")));
    if (conf) out.push(BD.pill("warn", conf + " to confirm"));
    if (ps.some(function (p) { return p.importance === 3; })) out.push(BD.pill("info", "Key account"));
    if (ps.some(function (p) { return p.category === "maintenance" && p.maintenance_due; })) out.push(BD.pill("warn", "Due now"));
    return out.length ? '<span class="ct-flags">' + out.join("") + "</span>" : "";
  }

  function personHtml(p, tab, hit) {
    var href = BD.pageHref("/bd/contact.html?id=", p.id);
    var tel = BD.telHref(p);
    var phone = BD.fmtPhone(p.phone);
    var mail = p.email ? BD.safeHref("mailto:" + p.email) : "";
    var match = !!(hit && hit.people.indexOf(p.id) !== -1);
    return '<div class="ct-person' + (match ? " is-match" : "") + '" data-contact="' + esc(p.id) + '" role="listitem">' +
      '<div class="ct-p-who">' + BD.avatarHTML(p, "sm") +
      '<span class="who"><a class="who-name ct-p-name" href="' + esc(href) + '">' + esc(p.name) + "</a>" +
      (match ? '<span class="sr-only"> (matches your search)</span>' : "") +
      (p.title ? '<span class="who-sub">' + esc(p.title) + "</span>" : "") +
      '<span class="who-sub ct-p-sub-phone">' + (phone ? esc(phone) : "No phone") + "</span></span></div>" +
      '<div class="ct-p-phone">' + (tel ? '<a href="' + esc(tel) + '">' + esc(phone) + "</a>" : '<span class="ct-none">No phone</span>') + "</div>" +
      '<div class="ct-p-email">' + (mail ? '<a href="' + esc(mail) + '" title="' + esc(p.email) + '">' + esc(p.email) + "</a>" : '<span class="ct-none">No email</span>') + "</div>" +
      '<div class="ct-p-status">' + BD.statusPill(p) + cadPill(p) + "</div>" +
      '<div class="ct-p-last">' + (p.last_live_at ? esc(lastWords(p.last_live_at)) : '<span class="ct-none">Never</span>') + "</div>" +
      '<div class="ct-p-call">' + (tel ? '<a class="btn-call" href="' + esc(tel) + '" aria-label="Call ' + esc(p.name) + ", " +
        esc(phone) + '">' + ico("phone", 18) + "</a>" : "") + "</div></div>";
  }

  function accountHtml(a, tab) {
    var k = key(tab, a.id);
    var hit = S.hits ? S.hits[tab][a.id] : null;
    var open = !!S.open[k];
    var n = Number(a.people_count) || 0;
    var meta = [a.city, a.industry].filter(Boolean).join(" · ");
    var owner = a.owner
      ? BD.avatarHTML(a.owner, "sm") + '<span class="ct-owner">' + esc(BD.nameOf(a.owner)) +
        (a.other_owners ? ' <span class="ct-plus">+' + esc(a.other_owners) + "</span>" : "") + "</span>"
      : '<span class="ct-owner ct-none">No owner</span>';
    var pid = "ct-p-" + tab + "-" + a.id;
    var out = '<div class="ct-acct' + (open ? " is-open" : "") + '" data-acct="' + esc(a.id) + '" data-tab="' + tab + '">' +
      '<div class="ct-acct-head">' +
      '<button type="button" class="ct-acct-toggle" id="ct-a-' + tab + "-" + esc(a.id) + '" aria-expanded="' + (open ? "true" : "false") +
      '" aria-controls="' + pid + '">' +
      '<span class="ct-acct-ico">' + ico("building", 18) + "</span>" +
      '<span class="ct-acct-main"><span class="ct-acct-name">' + esc(a.name) + "</span>" +
      '<span class="ct-acct-meta">' + esc(meta) + '<span class="ct-phone-only">' + (meta ? " · " : "") + esc(peopleWord(n)) + "</span></span>" +
      flags(a) + "</span>" +
      '<span class="ct-c-people">' + esc(peopleWord(n)) + "</span>" +
      '<span class="ct-c-owner">' + owner + "</span>" +
      '<span class="ct-c-last">' + esc(lastWords(a.last_live_at)) + "</span>" +
      '<span class="ct-chev">' + ico("chev-right", 18) + "</span></button>" +
      (S.can.move_company === true
        ? '<button type="button" class="btn btn-icon btn-sm ct-more" id="ct-m-' + tab + "-" + esc(a.id) + '" data-more aria-label="More for ' +
          esc(a.name) + '" aria-haspopup="menu" aria-expanded="false">' + ico("more", 20) + "</button>"
        : '<span class="ct-more-gap" aria-hidden="true"></span>') +
      "</div>";
    if (open) {
      out += '<div class="ct-people" id="' + pid + '" role="list" aria-label="People at ' + esc(a.name) + '">' +
        (a.people || []).map(function (p) { return personHtml(p, tab, hit); }).join("") + "</div>" +
        '<div class="ct-people-foot"><span>' + esc(peopleWord(n)) + " at " + esc(a.name) + "</span>" +
        (S.can.add_contact === true
          ? '<a class="btn-link" href="' + esc(BD.pageHref("/bd/add.html?company=", a.id)) + '">' + ico("plus", 16) + "Add someone here</a>"
          : "") + "</div>";
    }
    return out + "</div>";
  }

  function emptyHtml(icon, title, act, label) {
    return '<div class="empty"><div class="empty-ico">' + ico(icon, 22) + '</div><p class="empty-title">' + esc(title) + "</p>" +
      (act ? '<button type="button" class="btn" data-act="' + act + '">' + esc(label) + "</button>" : "") + "</div>";
  }

  function renderList() {
    var box = $("ct-list");
    if (!box) return;
    box.setAttribute("aria-busy", "false");
    var list = shown();
    var html;
    if (!S.lists[S.tab].length && !S.hits) {
      html = emptyHtml("users", S.tab === "bd" ? "No BD accounts yet." : "No maintenance accounts yet.");
    } else if (!list.length) {
      html = S.hits
        ? emptyHtml("search", "No account or person matches “" + S.q + "”.", "clear-search", "Clear search")
        : emptyHtml("check-circle", "All tidy here. No account matches this filter.", "show-all", "Show every account");
    } else {
      html = '<div class="ct-colhead" aria-hidden="true"><span></span><span>Account</span><span>People</span><span>Owner</span>' +
        "<span>Last live talk</span><span></span></div>" +
        '<div class="ct-accts">' + list.map(function (a) { return accountHtml(a, S.tab); }).join("") + "</div>";
    }
    box.innerHTML = html;
    renderCount();
  }

  // ── search ─────────────────────────────────────────────────────────────────────────────────
  /** The count line under a search: what it found here, how many more on the other tab, Clear. */
  function searchWords() {
    var here = S.hits[S.tab], there = S.hits[other(S.tab)];
    var ids = Object.keys(here);
    var nOther = Object.keys(there).length;
    var found = {};
    ids.forEach(function (id) { here[id].people.forEach(function (pid) { found[pid] = id; }); });
    var pids = Object.keys(found);
    var first;
    if (!ids.length) first = "";
    else if (ids.length === 1 && pids.length === 1) {
      var acc = account(S.tab, ids[0]);
      var who = (acc ? acc.people || [] : []).filter(function (p) { return String(p.id) === pids[0]; })[0];
      first = (who ? who.name : "1 person") + " at " + (acc ? acc.name : "this account") + ".";
    } else if (!pids.length) first = plural(ids.length, "account") + (ids.length === 1 ? " matches." : " match.");
    else first = plural(ids.length, "account") + " and " + peopleWord(pids.length) + " match.";
    var more = nOther ? nOther + " more on the " + TAB_NAME[other(S.tab)] + " tab." : "";
    return { first: first, more: more };
  }

  function renderCount() {
    var p = $("ct-count");
    if (!p) return;
    if (!S.hits || !Object.keys(S.hits[S.tab]).length) {
      if (S.hits && Object.keys(S.hits[other(S.tab)]).length) {
        var w0 = searchWords();
        p.hidden = false;
        p.innerHTML = '<button type="button" class="btn-link" data-act="other-tab">' + esc(w0.more) + "</button>";
        return;
      }
      p.hidden = true;
      p.innerHTML = "";
      return;
    }
    var w = searchWords();
    p.hidden = false;
    p.innerHTML = "<span>" + esc(w.first) + "</span>" +
      (w.more ? ' <button type="button" class="btn-link" data-act="other-tab">' + esc(w.more) + "</button>" : "") +
      ' <button type="button" class="btn-link" data-act="clear-search">Clear search</button>';
  }

  function announceSearch() {
    if (!S.hits) return;
    var here = Object.keys(S.hits[S.tab]).length, there = Object.keys(S.hits[other(S.tab)]).length;
    if (!here && !there) { BD.announce("No account or person matches."); return; }
    var w = searchWords();
    BD.announce((w.first ? w.first + " " : "") + w.more);
  }

  /** quiet: asked again after a move or an import, whose toast says what happened (no second announcement). */
  function search(q, quiet) {
    S.q = q;
    S.seq += 1;
    var seq = S.seq;
    syncUrl();
    if (!q) {
      S.hits = null;
      render();
      return Promise.resolve();
    }
    return Api.get("/api/bd/contacts/search?q=" + encodeURIComponent(q)).then(function (r) {
      if (seq !== S.seq) return;
      var hits = { bd: {}, maintenance: {} };
      (r.items || []).forEach(function (it) {
        if (!hits[it.tab] || !it.account) return;
        hits[it.tab][it.account.id] = { people: (it.people || []).map(function (p) { return p.id; }), account: !!it.account_match };
      });
      S.hits = hits;
      S.chip = "all";
      // Stay on this tab when it has a hit; else go where the first one is.
      if (!Object.keys(hits[S.tab]).length && Object.keys(hits[other(S.tab)]).length) S.tab = other(S.tab);
      TABS.forEach(function (t) { Object.keys(hits[t]).forEach(function (id) { S.open[key(t, id)] = true; }); });
      syncUrl();
      render();
      if (!quiet) announceSearch();
    }, function (e) {
      if (seq !== S.seq) return;
      S.hits = null;
      render();
      var p = $("ct-count");
      if (p) { p.hidden = false; p.innerHTML = '<span class="ct-error">' + esc(errText(e)) + "</span>"; }
      BD.announce(errText(e), true);
    });
  }

  function clearSearch() {
    var box = $("ct-q");
    if (box) box.value = "";
    search("");
    focusId("ct-q");
  }

  // ── make maintenance account / move back to BD ─────────────────────────────────────────────
  function moveWords(a, tab) {
    var n = Number(a.people_count) || 0;
    var moves = peopleWord(n) + (n === 1 ? " moves" : " move");
    return tab === "bd"
      ? { to: "maintenance", title: "Make " + a.name + " a maintenance account?", text: moves + " to the Maintenance tab.",
          yes: "Make maintenance account" }
      : { to: "bd", title: "Move " + a.name + " back to BD?", text: moves + " to the BD tab.", yes: "Move back to BD" };
  }

  function openMore(btn) {
    var row = btn.closest(".ct-acct");
    if (!row) return;
    var tab = row.getAttribute("data-tab");
    BD.menu(btn, [tab === "bd"
      ? { act: "to-maintenance", label: "Make maintenance account", icon: "arrow-right" }
      : { act: "to-bd", label: "Move back to BD", icon: "arrow-left" }]);
  }

  /** The page's own Undo for move `m` of account `a`, under the tabs, until the server's window shuts
   *  (undo_until; the full two minutes when the PC clock disagrees with it). One at a time. */
  function showUndo(m, a, words) {
    hideUndo();
    var line = $("ct-moved");
    if (!line) return;
    var ms = Date.parse(m.undo_until) - Date.now();
    if (!(ms > 0 && ms <= UNDO_WINDOW_MS)) ms = UNDO_WINDOW_MS;
    var what = m.to === "maintenance" ? "making " + a.name + " a maintenance account" : "moving " + a.name + " back to BD";
    line.innerHTML = "<span>" + esc(words) + '</span><button type="button" class="btn-link" id="ct-moved-undo">Undo' +
      '<span class="sr-only"> ' + esc(what) + "</span></button>";
    line.hidden = false;
    S.undo = { m: m, a: a, timer: setTimeout(hideUndo, ms) };
  }

  /** Takes the page's Undo away; focus on it goes to the open tab, never to the page. */
  function hideUndo() {
    if (S.undo) clearTimeout(S.undo.timer);
    S.undo = null;
    var line = $("ct-moved");
    if (!line || line.hidden) return;
    var had = !!(line.contains && document.activeElement && line.contains(document.activeElement));
    line.hidden = true;
    line.innerHTML = "";
    if (had) focusId("ct-tab-" + S.tab);
  }

  /** Both tabs again (and the likely duplicate pairs, for merge_companies), after a move, a merge, an
   *  Undo or an import; a search on show is asked again too, so its hits follow a company to the tab it
   *  is on now. */
  function reload() {
    return Promise.all([loadLists(), loadDupes()]).then(function () { return S.q ? search(S.q, true) : render(); });
  }

  function move(btn) {
    var row = btn.closest(".ct-acct");
    var tab = row && row.getAttribute("data-tab");
    var a = row && account(tab, row.getAttribute("data-acct"));
    if (!a) return;
    var w = moveWords(a, tab);
    BD.dialog({ title: w.title, text: w.text, yes: w.yes, no: "Cancel" }).then(function (yes) {
      if (!yes) return;
      BD.setBusy(btn, true);
      Api.post(Api.path("contacts", "accounts", a.id, "move"), { to: w.to }).then(function (r) {
        var m = r.move || {};
        // What came off: open BD calls going to maintenance; the pinned maintenance follow-up coming back.
        var off = w.to === "maintenance" ? plural(m.calls_off, "call") : plural(m.calls_off, "maintenance follow-up");
        var words = (w.to === "maintenance" ? a.name + " is a maintenance account." : a.name + " is back on the BD tab.") +
          (m.calls_off ? " " + off + " came off this week's list." : "") +
          (m.pinned ? " " + plural(m.pinned, "follow-up") + " pinned to this week." : "");
        var offer = function () {
          // Its handle rides with the move, so an Undo from either place closes the toast's Undo too.
          m.closeToast = BD.toast(words, { kind: "ok", ms: UNDO_MS,
            action: { label: "Undo", onClick: function () { undo(m, a); } } });
          showUndo(m, a, words);
          focusId("ct-moved-undo");
          BD.announce(words + " Undo is available.");
        };
        // The move is made: its Undo is offered even when the list then fails to reload.
        return reload().then(offer, offer);
      }, function (e) {
        BD.setBusy(btn, false);
        BD.toast(errText(e), { kind: "error" });
      });
    });
  }

  function undo(m, a) {
    // The page's Undo stays focusable while it is asked (disabling it would drop focus to the page).
    var held = S.undo && S.undo.m === m ? S.undo : null;
    if (held) held.busy = true;
    // One Undo asked: the toast's goes at once (it cannot be pressed again while this is asked); the
    // page's stays until it is done, so a failed Undo can be asked again from there.
    if (typeof m.closeToast === "function") m.closeToast();
    Api.post(Api.path("contacts", "accounts", "moves", m.id, "undo"), {}).then(function () {
      if (held && S.undo === held) hideUndo();
      var said = function () {
        BD.toast("Put back: " + a.name + " is on the " + TAB_NAME[m.to === "maintenance" ? "bd" : "maintenance"] + " tab again.", { kind: "ok" });
      };
      return reload().then(function () {
        focusId("ct-tab-" + S.tab);
        said();
      }, said);
    }, function (e) {
      if (held) held.busy = false;
      BD.toast(errText(e), { kind: "error" });
    });
  }

  // ── likely duplicate BD accounts (#811) ────────────────────────────────────────────────────
  function quoted(s) { return "“" + s + "”"; }
  function joinAnd(xs) { return xs.length > 1 ? xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1] : xs.join(""); }

  /** What the two accounts share, as words: a hint only (a shared phone or a work email domain). */
  function hintWords(h) {
    var phones = ((h && h.phones) || []).map(function (p) { return BD.fmtPhone(p) || p; });
    var domains = (h && h.email_domains) || [];
    var ph = phones.length ? "have the " + (phones.length === 1 ? "phone " : "phones ") + joinAnd(phones) : "";
    var dm = domains.length ? "use the email " + (domains.length === 1 ? "domain " : "domains ") + joinAnd(domains) : "";
    if (!ph && !dm) return "No shared phone or email domain.";
    return "Both " + (ph && dm ? ph + " and " + dm : ph || dm) + ".";
  }

  /** The side Merge offers to keep: the one with more people (fewer move), the first on a tie. */
  function keepSide(d) { return (Number(d.b.people_count) || 0) > (Number(d.a.people_count) || 0) ? d.b : d.a; }

  /** A pair's key: its two account ids, lower first, as the server orders a pair's a and b. */
  function pairKeyOf(x, y) {
    var a = Number(x), b = Number(y);
    return Math.min(a, b) + "-" + Math.max(a, b);
  }
  function pairKey(d) { return pairKeyOf(d.a.id, d.b.id); }
  function pairByKey(k) { return pairsOf().filter(function (d) { return pairKey(d) === k; })[0] || null; }

  function pairHtml(d) {
    var keep = keepSide(d);
    var k = pairKey(d);
    return '<li class="panel-warn ct-pair" data-pair="' + esc(k) + '"><span class="ct-pair-ico">' + ico("copy", 18) + "</span>" +
      '<div class="ct-pair-main"><p class="ct-pair-text"><strong>Same account?</strong> ' +
      esc(quoted(d.a.name)) + " (" + esc(peopleWord(Number(d.a.people_count) || 0)) + ") and " +
      esc(quoted(d.b.name)) + " (" + esc(peopleWord(Number(d.b.people_count) || 0)) + "). " + esc(hintWords(d.hints)) + "</p>" +
      '<div class="wrap-row ct-pair-acts">' +
      '<button type="button" class="btn btn-sm btn-primary" id="ct-merge-' + esc(k) + '" data-act="merge">Merge into ' +
      esc(keep.name) + "</button>" +
      '<button type="button" class="btn btn-sm" id="ct-keep-' + esc(k) + '" data-act="keep">Keep separate' +
      '<span class="sr-only">: ' + esc(d.a.name) + " and " + esc(d.b.name) + "</span></button>" +
      "</div></div></li>";
  }

  /** One merge in Recently merged: what went where, who did it and when, and its Undo. */
  function mergedHtml(m) {
    var was = m.name_before && m.name_before !== m.into.name ? m.name_before : m.into.name;
    var what = m.account.name + " into " + was;
    return '<li class="ct-merged-row"><span class="ct-merged-main"><span class="ct-merged-what">' + esc(what) +
      (was !== m.into.name ? ", now named " + esc(m.into.name) : "") + "</span>" +
      '<span class="ct-merged-sub">' + esc(peopleWord(Number(m.people) || 0)) + " moved · " + esc(BD.fmtDay(m.at, S.today)) +
      (m.by && m.by.name ? " by " + esc(BD.nameOf(m.by)) : "") + "</span></span>" +
      '<button type="button" class="btn-link ct-unmerge" id="ct-unmerge-' + esc(m.id) + '" data-act="unmerge" data-id="' +
      esc(m.id) + '">Undo<span class="sr-only"> merging ' + esc(what) + "</span></button></li>";
  }

  function renderDupes() {
    var box = $("ct-dupes");
    if (!box) return;
    box.hidden = !dupesView();
    if (box.hidden) { box.innerHTML = ""; return; }
    if (!S.dupes) {
      box.innerHTML = '<p class="panel-warn ct-dupes-err">' + ico("warning", 18) + "<span>" +
        esc(S.dupesErr ? errText(S.dupesErr) : "Loading...") + "</span></p>";
      return;
    }
    var pairs = pairsOf(), merges = S.dupes.merges;
    box.innerHTML = (pairs.length
      ? '<ul class="ct-pairs">' + pairs.map(pairHtml).join("") + "</ul>"
      : '<p class="ct-pairs-none">' + ico("check-circle", 18) + "<span>No two accounts look like the same company.</span></p>") +
      (merges.length
        ? '<h2 class="eyebrow ct-merged-h" id="ct-merged-h">Recently merged</h2><ul class="ct-merged" aria-labelledby="ct-merged-h">' +
          merges.map(mergedHtml).join("") + "</ul>"
        : "");
  }

  /** Focus after the duplicates view redrew: the first of `ids` still there, else the filter's chip. */
  function focusAfterDupes(ids) {
    for (var i = 0; i < ids.length; i += 1) {
      var el = ids[i] && $(ids[i]);
      if (el) { el.focus(); return; }
    }
    var chip = document.querySelector('#ct-chips [data-chip="dupes"]');
    if (chip) chip.focus(); else focusId("ct-tab-" + S.tab);
  }

  /** The words above Merge, for keeping `into` and moving `from`'s people. */
  function mergeLine(from, into) {
    var n = Number(from.people_count) || 0;
    return n
      ? "Move " + peopleWord(n) + " from " + from.name + " into " + into.name + "?"
      : "Merge " + from.name + " into " + into.name + "? Nobody there needs to move.";
  }

  /** Asks which name stays (a dialog; a bottom sheet on a phone). Resolves {into, from} or null. */
  function askMerge(d) {
    return new Promise(function (resolve) {
      var sides = [d.a, d.b];
      var first = keepSide(d);
      var el = document.createElement("div");
      el.className = "dialog ct-merge-dlg";
      el.setAttribute("role", "alertdialog");       // as BD.dialog's every confirm
      el.setAttribute("aria-labelledby", "ct-merge-title");
      el.setAttribute("aria-describedby", "ct-merge-line");
      el.innerHTML = '<h2 class="dialog-title" id="ct-merge-title">Merge into one account?</h2>' +
        '<fieldset class="ct-merge-pick"><legend class="ct-merge-legend">Which name stays?</legend>' +
        sides.map(function (s) {
          var sub = peopleWord(Number(s.people_count) || 0) + (s.city ? " · " + s.city : "");
          return '<label class="ct-merge-opt"><input type="radio" name="ct-merge-name" value="' + esc(s.id) + '"' +
            (s === first ? " checked" : "") + ' /><span class="ct-merge-opt-text"><span class="ct-merge-opt-name">' +
            esc(s.name) + '</span><span class="ct-merge-opt-sub">' + esc(sub) + "</span></span></label>";
        }).join("") + "</fieldset>" +
        '<p class="dialog-text ct-merge-line" id="ct-merge-line" aria-live="polite"></p>' +
        '<p class="ct-merge-small">Each person keeps their owner, history and tasks. You can undo this.</p>' +
        '<div class="dialog-actions"><button type="button" class="btn" data-act="no">Cancel</button>' +
        '<button type="button" class="btn btn-primary" data-act="yes">Merge</button></div>';
      var answer = null;
      var picked = function () {
        var on = el.querySelector('input[name="ct-merge-name"]:checked');
        var into = on && String(on.value) === String(d.b.id) ? d.b : d.a;
        return { into: into, from: into === d.a ? d.b : d.a };
      };
      var line = function () {
        var p = picked();
        el.querySelector("#ct-merge-line").textContent = mergeLine(p.from, p.into);
      };
      line();
      el.addEventListener("change", line);
      el.addEventListener("click", function (e) {
        var b = e.target.closest && e.target.closest("[data-act]");
        if (!b) return;
        answer = b.getAttribute("data-act") === "yes" ? picked() : null;
        BD.sheet.close(el, answer ? "yes" : "no");
      });
      BD.sheet.open(el, {
        initialFocus: 'input[name="ct-merge-name"]:checked',
        onClose: function () {
          setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 220);
          resolve(answer);
        },
      });
    });
  }

  function merge(btn) {
    var li = btn.closest(".ct-pair");
    var d = li && pairByKey(li.getAttribute("data-pair"));
    if (!d) return;
    askMerge(d).then(function (p) {
      if (!p) return;
      BD.setBusy(btn, true);
      // The account whose name stays is the one that stays: both choices are sent, as the route asks.
      Api.post(Api.path("contacts", "accounts", p.from.id, "merge"), { into: p.into.id, name_from: p.into.id }).then(function (r) {
        var m = r.merge || {};
        var into = m.into || p.into;
        var words = "Merged. " + into.name + " now has " + peopleWord(Number(m.people_count) || 0) + ".";
        S.open[key("bd", into.id)] = true;
        var offer = function () {
          // Its handle is kept by the merge's id, so an Undo from Recently merged closes the toast's Undo too.
          S.mergeToasts[m.id] = BD.toast(words, { kind: "ok", ms: UNDO_MS,
            action: { label: "Undo", onClick: function () { undoMerge(m.id); } },
            onGone: function () { delete S.mergeToasts[m.id]; } });
          focusAfterDupes(["ct-unmerge-" + m.id]);
          BD.announce(words + " Undo is available.");
        };
        // The merge is made: its Undo is offered even when the page then fails to reload.
        return reload().then(offer, offer);
      }, function (e) {
        BD.setBusy(btn, false);
        BD.toast(errText(e), { kind: "error" });
      });
    });
  }

  /** Undo one merge, from its toast or from Recently merged. Its Recently merged button is busy while
   *  the request runs. Focus moves to the pair put back; when Undo is refused (409: something changed
   *  since) or the page cannot reload, to this merge's Undo in Recently merged, else the filter's chip,
   *  so it never drops to the page (the toast that held the focused button is gone). */
  function undoMerge(id) {
    if (S.merging[id]) return;
    S.merging[id] = true;
    var mine = "ct-unmerge-" + id;
    var btn = $(mine);
    if (btn) BD.setBusy(btn, true);
    var free = function () {
      delete S.merging[id];
      var b = $(mine);
      if (b) BD.setBusy(b, false);
    };
    if (typeof S.mergeToasts[id] === "function") S.mergeToasts[id]();
    Api.post(Api.path("contacts", "accounts", "merges", id, "undo"), {}).then(function (r) {
      var u = r.undone || {};
      var words = u.account && u.into ? "Put back: " + u.account.name + " and " + u.into.name + " are two accounts again." : "Merge undone.";
      return reload().then(function () {
        free();
        focusAfterDupes([u.account && u.into && "ct-merge-" + pairKeyOf(u.account.id, u.into.id)]);
        BD.toast(words, { kind: "ok" });
      }, function () {
        free();
        focusAfterDupes([mine]);
        BD.toast(words, { kind: "ok" });
      });
    }, function (e) {
      free();
      focusAfterDupes([mine]);
      BD.toast(errText(e), { kind: "error" });
    });
  }

  function keepSeparate(btn) {
    var li = btn.closest(".ct-pair");
    var d = li && pairByKey(li.getAttribute("data-pair"));
    if (!d) return;
    // Kept for good: nothing on the page takes it back, so it asks first.
    BD.dialog({ title: "Keep as two accounts?", yes: "Keep separate",
      text: d.a.name + " and " + d.b.name + " won't be suggested as one account again." }).then(function (yes) {
      if (!yes) return;
      BD.setBusy(btn, true);
      Api.post(Api.path("contacts", "accounts", "duplicates", "keep"), { accounts: [d.a.id, d.b.id] }).then(function () {
        var pairs = pairsOf();
        var at = pairs.indexOf(d);
        S.dupes.items = pairs.filter(function (x) { return x !== d; });
        render();
        var nextPair = S.dupes.items[at] || S.dupes.items[at - 1];
        focusAfterDupes([nextPair && "ct-merge-" + pairKey(nextPair)]);
        BD.toast("Kept as two accounts: " + d.a.name + " and " + d.b.name + ".", { kind: "ok" });
      }, function (e) {
        BD.setBusy(btn, false);
        BD.toast(errText(e), { kind: "error" });
      });
    });
  }

  // ── drawing it all ─────────────────────────────────────────────────────────────────────────
  function render() {
    renderHead();
    renderTools();
    renderTidy();
    renderDupes();
    renderList();
  }

  function pickTab(t, focus) {
    if (TABS.indexOf(t) === -1 || t === S.tab) return;
    S.tab = t;
    syncUrl();
    render();
    if (focus) focusId("ct-tab-" + t);
  }

  function pickChip(k) {
    S.chip = S.chip === k || k === "all" || !chipOf(k) ? "all" : k;
    if (S.tab !== "bd") S.tab = "bd";
    syncUrl();
    render();
  }

  function toggle(btn) {
    var row = btn.closest(".ct-acct");
    if (!row) return;
    var k = key(row.getAttribute("data-tab"), row.getAttribute("data-acct"));
    S.open[k] = !S.open[k];
    renderList();
    focusId(btn.id);
  }

  function wire() {
    var q = $("ct-q");
    if (q) {
      q.value = S.q;
      var typed = BD.debounce(function () { search(q.value.trim()); }, 250);
      q.addEventListener("input", typed);
      q.addEventListener("keydown", function (e) { if (e.key === "Escape" && q.value) { e.preventDefault(); clearSearch(); } });
    }
    setHtml("ct-q-ico", ico("search", 18));
    var sel = $("ct-sort");
    if (sel) sel.addEventListener("change", function () { S.sort = sortAllowed(sel.value) ? sel.value : "name"; renderList(); });

    var tabs = document.querySelector ? document.querySelector(".ct-tabs") : null;
    if (tabs) {
      tabs.addEventListener("click", function (e) {
        var b = e.target.closest && e.target.closest("[data-tab]");
        if (b) pickTab(b.getAttribute("data-tab"), false);
      });
      tabs.addEventListener("keydown", function (e) {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End") return;
        e.preventDefault();
        var to = e.key === "Home" ? "bd" : (e.key === "End" ? "maintenance" : other(S.tab));
        pickTab(to, true);
      });
    }
    var chips = $("ct-chips");
    if (chips) {
      chips.addEventListener("click", function (e) {
        var c = e.target.closest && e.target.closest("[data-chip]");
        if (c) pickChip(c.getAttribute("data-chip"));
      });
    }
    var tidy = $("ct-tidy");
    if (tidy) {
      tidy.addEventListener("click", function (e) {
        var card = e.target.closest && e.target.closest("[data-tidy]");
        if (card) {
          var k = card.getAttribute("data-tidy");
          if (k === "unknown") {
            S.unknownOpen = !S.unknownOpen;
            card.setAttribute("aria-expanded", S.unknownOpen ? "true" : "false");
            renderUnknown();
          } else {
            if (S.hits) { var box = $("ct-q"); if (box) box.value = ""; S.q = ""; S.hits = null; }
            pickChip(k);
            var again = document.querySelector('[data-tidy="' + k + '"]');
            if (again) again.focus();
          }
          return;
        }
        var dismiss = e.target.closest && e.target.closest('[data-act="unknown-dismiss"]');
        if (dismiss) dismissUnknown(dismiss);
      });
    }
    var moved = $("ct-moved");
    if (moved) {
      moved.addEventListener("click", function (e) {
        var b = e.target.closest && e.target.closest("#ct-moved-undo");
        if (b && S.undo && !S.undo.busy) undo(S.undo.m, S.undo.a);
      });
    }
    var dupes = $("ct-dupes");
    if (dupes) {
      dupes.addEventListener("click", function (e) {
        var b = e.target.closest && e.target.closest("[data-act]");
        if (!b || b.disabled) return;
        var act = b.getAttribute("data-act");
        if (act === "merge") merge(b);
        else if (act === "keep") keepSeparate(b);
        else if (act === "unmerge") undoMerge(b.getAttribute("data-id"));
      });
    }
    var count = $("ct-count");
    if (count) {
      count.addEventListener("click", function (e) {
        var b = e.target.closest && e.target.closest("[data-act]");
        if (!b) return;
        if (b.getAttribute("data-act") === "clear-search") clearSearch();
        else if (b.getAttribute("data-act") === "other-tab") pickTab(other(S.tab), true);
      });
    }
    var list = $("ct-list");
    if (list) {
      list.addEventListener("click", function (e) {
        var t = e.target;
        if (!t.closest) return;
        var more = t.closest("[data-more]");
        if (more) { openMore(more); return; }
        var tg = t.closest(".ct-acct-toggle");
        if (tg) { toggle(tg); return; }
        var act = t.closest("[data-act]");
        if (act && act.getAttribute("data-act") === "clear-search") clearSearch();
        else if (act && act.getAttribute("data-act") === "show-all") pickChip("all");
      });
      // A right-click on a company row opens its "..." menu (for whoever has one; else the browser's).
      list.addEventListener("contextmenu", function (e) {
        var head = e.target.closest && e.target.closest(".ct-acct-head");
        var more = head && head.querySelector("[data-more]");
        if (!more || (e.target.closest && e.target.closest("a"))) return;
        e.preventDefault();
        openMore(more);
      });
      list.addEventListener("bd-menu", function (e) {
        var d = e.detail || {};
        if (d.act === "to-maintenance" || d.act === "to-bd") move(d.anchor);
      });
    }

    var imp = $("ct-import"), file = $("ct-import-file");
    if (imp && file) {
      imp.innerHTML = ico("upload", 18) + "<span>Import</span>" + (S.can.admin_area === true ? ico("chev-down", 16) : "");
      // A menu (and so "collapsed" / "expanded") only for someone the Admin page opens for.
      if (S.can.admin_area === true) {
        imp.setAttribute("aria-haspopup", "menu");
        imp.setAttribute("aria-expanded", "false");
      }
      imp.addEventListener("click", function () {
        // Past imports are on Admin, which opens for admin_area: anyone else goes straight to the file.
        if (S.can.admin_area !== true) { file.click(); return; }
        var last = S.lastImport && S.lastImport.started_at ? "Last one " + BD.fmtDay(S.lastImport.started_at, S.today) : "";
        BD.menu(imp, [{ act: "import-file", label: "Upload a workbook", icon: "upload" },
          { act: "imports", label: "Past imports", icon: "history", href: "/bd/admin.html#ad-s-imports", sub: last }]);
      });
      imp.addEventListener("bd-menu", function (e) {
        if (e.detail && e.detail.act === "import-file") file.click();
      });
      file.addEventListener("change", function () {
        var f = file.files && file.files[0];
        file.value = "";
        if (!f) return;
        BD.importWorkbook(f, {
          returnFocus: function () { return $("ct-import"); },
          onImported: function () { reload(); },
        });
      });
    }
    var add = $("ct-add");
    if (add) add.innerHTML = ico("plus", 18) + "<span>Add contact</span>";
  }

  // ── start ──────────────────────────────────────────────────────────────────────────────────
  function renderNote(words) {
    show("ct-tools", false);
    show("ct-tidy", false);
    var sub = $("ct-sub");
    if (sub) sub.textContent = "";
    var note = $("ct-note");
    if (!note) return;
    note.hidden = false;
    BD.note(note, words, "ct-note-panel");
  }

  /** Opens the account ?company= names, on its tab, and brings it into view. A company on both tabs
   *  opens on the tab the link names (?tab=), else on the first that holds it. */
  function openCompany(id) {
    var t = account(S.tab, id) ? S.tab : TABS.filter(function (x) { return !!account(x, id); })[0];
    if (!t) return null;
    S.tab = t;
    S.open[key(t, id)] = true;
    return "ct-a-" + t + "-" + id;
  }

  var auth = window.TWAuth;
  if (!auth || !auth.ready || typeof auth.bdMe !== "function" || typeof auth.bdFailure !== "function") return;
  auth.ready.then(function () { return auth.bdMe(); }).then(function (res) {
    var ok = res && res.status >= 200 && res.status < 300 && res.body && res.body.ok;
    if (!ok) { renderNote(auth.bdFailure(res && res.status, res && res.body).message); return null; }
    var me = res.body;
    S.can = me.can || {};
    S.me = me.user || null;
    S.today = me.today || BD.bizToday();
    S.ownList = S.can.week === true && S.can.pick_owner !== true;
    show("ct-note", false);
    show("ct-tools", true);
    show("ct-import", S.can["import"] === true);
    show("ct-add", S.can.add_contact === true);
    S.q = (BD.qs("q") || "").trim();
    if (BD.qs("tab") === "maintenance") S.tab = "maintenance";
    // ?filter=dupes opens the Possible duplicates view, for whoever has that chip; nothing else is read.
    if (S.tab === "bd" && BD.qs("filter") === "dupes" && chipOf("dupes")) S.chip = "dupes";
    var company = BD.qs("company");
    wire();
    return Promise.all([loadLists(), loadExtras(), loadDupes()]).then(function () {
      var target = company ? openCompany(company) : null;
      if (S.q) return search(S.q);
      render();
      var el = target && $(target);
      if (el && el.scrollIntoView) el.scrollIntoView({ block: "center" });
      return null;
    });
  }).catch(function (e) {
    BD.errorBox($("ct-list"), e);
  });

  // Try again, after the page could not load: one handler on the box, so a redraw never leaves a dead button.
  var retryBox = $("ct-list");
  if (retryBox) {
    retryBox.addEventListener("click", function (e) {
      var b = e.target.closest && e.target.closest("[data-retry]");
      if (b) window.location.reload();
    });
  }
})();
