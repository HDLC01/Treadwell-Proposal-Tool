/**
 * Treadwell auth — Supabase Google sign-in, restricted to @wetreadwell.com.
 *
 * Load order on every page:  supabase-js (CDN)  →  auth.js  →  shared.js
 *
 *  - Inits the Supabase client from /api/public-config (publishable anon key).
 *  - Caches the access token on `window.__TW_TOKEN` so shared.js's API calls
 *    (and the autofill fetch) send `Authorization: Bearer …`.
 *  - Gates app pages: no session → redirect to /login.html; wrong domain →
 *    sign out + bounce with a message.
 *  - Renders a bottom-left "logged in as" indicator (+ an Admin link by role),
 *    and the left sidebar nav.
 */
(function () {
  const LOGIN_PAGE = "/login.html";
  // Where signing in lands you. Hanz, 2026-08-12: "tHE DEFAULT page when I go in to
  // propsals.wetreadwel should be the Active projects CRM not he databgase."
  //
  // It was /projects.html, which made sense while the Database was the only place to mint a
  // draft. That stopped being true when this board grew a + New button, and the page the weekly
  // sales meeting runs on should be the one that opens. Same reasoning as moving it to the top of
  // the sidebar, and the bare-domain redirect in main.py:_root moved with it — a landing page
  // decided in two places is a landing page that disagrees with itself.
  const HOME_PAGE = "/portal.html";
  const path = location.pathname.toLowerCase();
  const onLogin = path === "/login.html" || path.endsWith("/login.html");

  let sb = null;
  let currentUser = null;          // { email, name, role, status }

  // ── Which tabs a role may NOT reach ──
  // Hanz, 2026-08-19, on the Admin page's role matrix: "I cant toggle these on and off?" He chose
  // real blocking, so the server refuses a denied tab's own API routes as well; this is the same
  // policy on the menu side, and it arrives on /api/me (which init() already awaits before drawing
  // the sidebar, so it costs no round trip and cannot disagree with the gate).
  //
  // NAV_DENY holds the FULL per-role map when the page knows it — the Admin page fetches it so the
  // matrix can show every role's switches — and only the signed-in user's row otherwise. One object,
  // so renderSidebar and navMatrix read the same thing rather than two.
  //
  // Empty means nothing is denied, which is exactly today's behaviour: absent policy file, a role
  // the file never mentions, or a failed /api/me all land here.
  let NAV_DENY = {};
  // { page path: the denied tab href that owns it }, for the page this browser is ON. The server
  // expands it because ONE tab owns TWO pages (the Polish beta's step 2 is opened from two places
  // that are not its sidebar row), and a second copy of that mapping here is the copy that rots.
  let DENIED_PAGES = {};

  function denyFor(role) {
    const list = NAV_DENY && NAV_DENY[role];
    return Array.isArray(list) ? list : [];
  }

  window.TWAuth = {
    ready: null,
    client: () => sb,
    user: () => currentUser,
    token: () => window.__TW_TOKEN || null,
    signInWithGoogle,
    signOut,
    // ── The sidebar, read back ──
    // The Admin page shows which tabs each role gets. These three read the REAL menu rather
    // than a second list of it: sidebarMarkup(role) is the markup renderSidebar would put on
    // the page for that role, navSpec parses it into rows, navMatrix diffs the roles.
    // Accessors, not values, because the const they read is declared further down the file.
    //
    // Each takes an optional deny argument so the Admin page can render the matrix for a policy it
    // has fetched — or for one the user is part-way through editing — without saving anything.
    roles: () => ROLES.slice(),
    sidebarMarkup: (role, deny) => renderSidebar(role || ROLES[0], deny),
    navSpec: (role, deny) => parseNav(renderSidebar(role || ROLES[0], deny)),
    navMatrix,
    // The signed-in user's own denied tabs, and the whole map when this page has it.
    deniedPaths: () => denyFor((currentUser || {}).role || "user").slice(),
    navDeny: () => NAV_DENY,
    setNavDeny: (map) => { NAV_DENY = map && typeof map === "object" ? map : {}; },
  };

  function apiBase() { return window.TW_API_BASE || ""; }

  async function init() {
    let cfg = {};
    try { cfg = await (await fetch(apiBase() + "/api/public-config")).json(); } catch {}
    if (!cfg.supabase_url || !cfg.supabase_anon_key || !window.supabase) {
      if (!onLogin) showFatal("Sign-in isn't configured yet. (Supabase keys missing on the server.)");
      else showLoginError("Sign-in isn't configured yet — check back shortly.");
      return;
    }
    const domain = cfg.allowed_domain || "wetreadwell.com";
    sb = window.supabase.createClient(cfg.supabase_url, cfg.supabase_anon_key, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
    sb.auth.onAuthStateChange((_evt, session) => {
      window.__TW_TOKEN = session && session.access_token ? session.access_token : null;
    });
    const { data: { session } } = await sb.auth.getSession();
    window.__TW_TOKEN = session && session.access_token ? session.access_token : null;

    if (onLogin) return wireLoginPage(session, domain);

    // ── Gate every app page ──
    if (!session) { location.replace(LOGIN_PAGE); return; }
    const email = (session.user && session.user.email || "").toLowerCase();
    if (!email.endsWith("@" + domain)) {
      try { await sb.auth.signOut(); } catch {}
      location.replace(LOGIN_PAGE + "?denied=1");
      return;
    }
    // Identify the user (role/name) + ensure the profile row exists.
    try {
      const me = await (await fetch(apiBase() + "/api/me",
        { headers: { Authorization: "Bearer " + window.__TW_TOKEN } })).json();
      currentUser = (me && me.ok) ? me
        : { email, role: "user", name: (session.user.user_metadata || {}).full_name };
      // Fail OPEN if the response says nothing about permissions: a /api/me from a container that
      // predates this feature, or one whose policy read failed, must leave every tab where it was.
      NAV_DENY = {};
      NAV_DENY[currentUser.role || "user"] = (me && me.nav_denied) || [];
      DENIED_PAGES = (me && me.nav_denied_pages) || {};
    } catch {
      currentUser = { email, role: "user", name: (session.user.user_metadata || {}).full_name };
    }
    // Refuse the page BEFORE the sidebar goes up, so a denied member never sees the tab they are
    // standing on highlighted in a menu that is about to lose it.
    const owner = DENIED_PAGES[path] || DENIED_PAGES[location.pathname];
    if (owner) return showRefusal(owner);
    renderSidebar();
  }

  // ── Login page ──
  function wireLoginPage(session, domain) {
    const email = (session && session.user && session.user.email || "").toLowerCase();
    if (session && email.endsWith("@" + domain)) { location.replace(HOME_PAGE); return; }
    const btn = document.getElementById("google-signin");
    if (btn) btn.addEventListener("click", function () {
      btn.disabled = true; signInWithGoogle();
    });
    if (new URLSearchParams(location.search).get("denied")) {
      showLoginError("That isn't a @" + domain + " account. Please use your Treadwell Google account.");
    }
  }

  async function signInWithGoogle() {
    if (!sb) return;
    await sb.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: location.origin + HOME_PAGE,
        queryParams: { hd: "wetreadwell.com", prompt: "select_account" },
      },
    });
  }

  async function signOut() {
    try { await (sb && sb.auth.signOut()); } catch {}
    window.__TW_TOKEN = null;
    location.replace(LOGIN_PAGE);
  }

  // ── UI: bottom-left "logged in as" + nav ──
  // Names, initials and avatar colours all come from crm-core (window.TWCrm), the one
  // place that decides them, so the signed-in user looks the same here as they do on a
  // CRM card, a Projects row or an Analytics chip.
  //
  // The local fallbacks exist because the sidebar renders on login.html too, which loads
  // no page modules. They are never the path on a real app page. The OLD local initials()
  // had a paren bug — `(a[0] || "" + b[0])` short-circuits — so it returned ONE letter
  // for every two-word name; crm-core's version is correct.
  function initials(name, email) {
    const who = name || email || "";
    if (window.TWCrm) return window.TWCrm.initialsOf(who);
    const parts = String(who).trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
  }
  function avatarColor(name, email) {
    const who = name || email || "";
    return window.TWCrm ? window.TWCrm.colorOf(who) : "#4B5563";
  }

  // Left sidebar matching the main Treadwell app (light, 240px, red accent),
  // collapsing to an off-canvas drawer under 768px.
  // The hrefs the render CURRENTLY IN PROGRESS must leave out. A module-level variable rather than a
  // fourth navItem() parameter because three test files and the nav-visibility harness read the
  // sidebar's navItem(...) calls as SOURCE TEXT — the harness's probe run splices new ones in by
  // string match — so the shape of those calls has to stay exactly as it is.
  //
  // Set by renderSidebar and cleared the moment the markup is built. The whole innerHTML assignment
  // is synchronous and navMatrix walks the roles one at a time, so there is no window in which two
  // renders overlap.
  let RENDER_DENY = [];

  function navItem(href, glyph, label, tag) {
    // A denied tab leaves the menu entirely. Returning "" rather than hiding it with CSS is the
    // point of Hanz choosing real blocking: the server refuses this tab's own routes too, so a
    // present-but-hidden link would be a link to a page that says no.
    if (RENDER_DENY.indexOf(href) !== -1) return "";
    const active = location.pathname.toLowerCase().endsWith(href.toLowerCase());
    // `tag` marks a page as not-yet-finished. Optional so the other twelve callers are
    // untouched, and rendered as a chip rather than folded into the label so it reads as a
    // status on the page rather than part of its name.
    return '<a class="tw-nav-item' + (active ? " active" : "") + '" href="' + href + '">' +
      '<span class="tw-nav-ico">' + glyph + '</span><span class="tw-nav-label">' + label + '</span>' +
      (tag ? '<span class="tw-nav-tag">' + tag + '</span>' : "") + '</a>';
  }

  // Every role this app has, least privileged first. profiles.py stores exactly one of these
  // three on a profile row and nothing else; main.py's _require_admin accepts the last two.
  // super_admin is bootstrapped from SUPER_ADMIN_EMAIL and cannot be granted from the UI.
  const ROLES = ["user", "admin", "super_admin"];

  // Tabs this policy governs that have NO SIDEBAR ROW — the mirror of nav_access.py's
  // NO_SIDEBAR_TABS, which is asserted equal to this list in backend/tests/test_nav_access.py.
  //
  // WHY THIS LIST EXISTS AT ALL. Everything else about the menu is reflected out of the real
  // navItem() calls, deliberately, so a second copy cannot go stale. These tabs have no navItem()
  // call to reflect: Info Sheet moved into the project drawer on 2026-08-20 and is still a tab the
  // server can refuse per role. Without a row here the Admin page could not draw its switch, so a
  // role could be denied it with nothing on screen to see or undo — the one lockout with no way
  // back in the UI. The section/glyph/label are only what the switch is LABELLED with; what the
  // policy governs is the href, and nav_access.py is the authority on that.
  const NO_SIDEBAR_TABS = [
    { section: "Active", href: "/info-sheet.html", glyph: "📋", label: "Info Sheet", tag: "" },
  ];

  // Pull the nav entries back out of rendered sidebar markup: one row per item, in order, tagged
  // with the section heading above it. The Admin page's role matrix reads THIS, so the matrix and
  // the menu cannot disagree — there is one list, and this walks what it produced.
  //
  // Matches navItem()'s and the section headings' output above. If either changes shape this
  // returns fewer rows, which test_role_visibility_matrix.py fails on (it diffs the parse against
  // the markup with its own regex, and against what the Admin page renders).
  const NAV_ENTRY_RE = new RegExp(
    '<div class="tw-section">([^<]*)<\\/div>' +
    '|<a class="tw-nav-item[^"]*" href="([^"]*)">' +
    '<span class="tw-nav-ico">([^<]*)<\\/span>' +
    '<span class="tw-nav-label">([^<]*)<\\/span>' +
    '(?:<span class="tw-nav-tag">([^<]*)<\\/span>)?', "g");

  function unesc(s) {
    return String(s == null ? "" : s).replace(/&lt;/g, "<").replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
  }

  function parseNav(markup) {
    const all = String(markup || "");
    const from = all.indexOf('<nav class="tw-nav">');
    const body = from === -1 ? all : all.slice(from, all.indexOf("</nav>", from));
    const out = [];
    let section = "", m;
    NAV_ENTRY_RE.lastIndex = 0;
    while ((m = NAV_ENTRY_RE.exec(body)) !== null) {
      if (m[1] !== undefined) { section = unesc(m[1]); continue; }
      out.push({ section: section, href: m[2], glyph: unesc(m[3]),
                 label: unesc(m[4]), tag: m[5] ? unesc(m[5]) : "" });
    }
    return out;
  }

  // One row per sidebar tab, in sidebar order, with which roles see it — built by rendering the
  // nav once per role and diffing. Nothing here declares who may see what: a new item, or a new
  // role gate on an existing item, shows up with no bookkeeping. That is the point.
  //
  // Rows are created walking the MOST privileged role first, because a gate can only ever add
  // items, so that render is the one that holds every row in true sidebar order.
  // `deny` is an optional { role: [href] } map — the Admin page passes the stored policy, or the one
  // the user is part-way through editing, so the switches and the ticks are the same render. Omitted,
  // it uses whatever this page knows (NAV_DENY), which on an ordinary page is the signed-in user's
  // row and nothing else.
  //
  // The most-privileged-first walk is also what guarantees every row EXISTS: the super admin can
  // never be denied a tab (nav_access.py strips his role on write and on read), so his render always
  // holds the full list. A tab denied to both members and admins still gets a row, with its ticks off
  // — which is what the Admin page needs in order to draw a switch for it.
  function navMatrix(deny) {
    const rows = [], byHref = {};
    ROLES.slice().reverse().forEach(function (role) {
      parseNav(renderSidebar(role, deny ? (deny[role] || []) : denyFor(role))).forEach(function (e) {
        let row = byHref[e.href];
        if (!row) {
          // noSidebar false because this row came OUT of a render of the menu. The rows appended
          // below carry it true, which is how the Admin page can name a governed tab that has no
          // menu entry instead of counting it as one.
          row = byHref[e.href] = { section: e.section, href: e.href, glyph: e.glyph,
                                   label: e.label, tag: e.tag, noSidebar: false, roles: {} };
          ROLES.forEach(function (r) { row.roles[r] = false; });
          rows.push(row);
        }
        row.roles[role] = true;
      });
    });
    if (deny) addNoSidebarRows(rows, deny);
    return { roles: ROLES.slice(), rows: rows };
  }

  // The gated-but-undrawn tabs, added to a matrix that is REPORTING ON A POLICY.
  //
  // The deny argument is the seam, and it is not incidental: handed a deny map, the caller is asking
  // "what can this policy reach" — the Admin page's switches, and labelOf() naming a tab somebody
  // was just refused — and the answer has to include a tab whose switch is real even though its row
  // is gone. Asked with NO argument, the caller is asking about the MENU (navSpec, and the harness
  // in backend/tests/js/nav-visibility-harness.js that proves the matrix IS the sidebar), and the
  // answer stays exactly the sidebar, tab for tab.
  //
  // Roles are read straight off the deny map rather than from a render, because there is no render
  // to read: no navItem() call means nothing to leave out. A tab absent from a role's deny list is
  // one that role still gets, which is the same default-allow rule the rest of this policy has.
  //
  // That default-allow is only as good as the map it reads, so each of these rows is stamped
  // noSidebar:true. Handed an EMPTY map (a caller that has no policy to show) the ticks below all
  // come out on, and the flag is what lets the Admin page say "not known" for those cells instead
  // of showing an on state it cannot back.
  function addNoSidebarRows(rows, deny) {
    NO_SIDEBAR_TABS.forEach(function (t) {
      // If it ever gets a sidebar row back, that row wins and this one is not drawn twice.
      if (rows.some(function (r) { return r.href === t.href; })) return;
      const row = { section: t.section, href: t.href, glyph: t.glyph, label: t.label,
                    tag: t.tag || "", noSidebar: true, roles: {} };
      ROLES.forEach(function (r) {
        const list = deny[r];
        row.roles[r] = !(Array.isArray(list) && list.indexOf(t.href) !== -1);
      });
      // Placed after the LAST row of its own section, so the Admin page's print-the-heading-once
      // pass does not print that heading a second time further down the table. Appended if no row
      // carries that section at all.
      let at = -1;
      for (let i = 0; i < rows.length; i++) if (rows[i].section === t.section) at = i;
      rows.splice(at === -1 ? rows.length : at + 1, 0, row);
    });
  }

  // renderSidebar() draws the sidebar for the signed-in user. renderSidebar("admin") builds the
  // SAME markup for that role and RETURNS it, touching neither the DOM nor the styles — which is
  // how navSpec/navMatrix above report the menu.
  //
  // WHY REFLECTION AND NOT A DECLARED SPEC. The list is a chain of navItem() calls inside one
  // aside.innerHTML expression, and three test files read it there as source text: the labels, the
  // order, which section each item sits under, that no two share a glyph. Lifting the list out
  // into a data structure moves it out from under those tests; copying it into one leaves two
  // lists, and the copy is what goes stale the first time somebody adds a page. So the matrix is
  // generated by running the real builder, and the role gate it reports is the real
  // isAdmin-ternary below rather than a second opinion about it. (No backticks in this file's
  // comments — the injected stylesheet is one long template literal and one stray backtick took
  // auth.js off the air on staging once. See test_frontend_js_parses.py.)
  function renderSidebar(roleForSpec, denyForSpec) {
    const spec = !!roleForSpec;
    if (!spec) {
      if (document.getElementById("tw-sidebar")) return;
      injectSidebarStyles();
    }
    const u = spec ? { role: roleForSpec } : (currentUser || {});
    // Which tabs this render leaves out. Spec mode may be told explicitly (the Admin page rendering
    // an unsaved policy); otherwise both modes read the same NAV_DENY, so the menu on the page and
    // the matrix on the Admin page cannot report different things about the same role.
    RENDER_DENY = (spec && denyForSpec) ? denyForSpec : denyFor(u.role || "user");
    const isAdmin = u.role === "admin" || u.role === "super_admin";
    const roleLabel = u.role === "super_admin" ? "SUPER ADMIN" : (u.role === "admin" ? "ADMIN" : "USER");
    const roleClass = u.role === "super_admin" ? "super" : (u.role === "admin" ? "admin" : "user");

    // In spec mode the "element" is a throwaway object: the same assignment builds the same
    // string, and reading it back gives that string verbatim rather than a browser's
    // re-serialisation of a DOM tree. On a real page this is the element it always was.
    const aside = spec ? {} : document.createElement("aside");
    aside.id = "tw-sidebar";
    aside.innerHTML =
      '<div class="tw-brand">' +
      '<img class="tw-bison" src="/img/treadwell-bison.svg" width="54" height="34" alt="Treadwell">' +
      '<div class="tw-brandtext"><div class="tw-brandname">Treadwell</div>' +
      '<div class="tw-brandsub">Proposal Tool</div></div>' +
      '<button class="tw-collapse" id="tw-collapse" title="Hide menu">‹</button></div>' +
      '<nav class="tw-nav">' +
      // THREE HEADINGS, NOT EIGHT. Hanz, 2026-08-25, after a week of using the tool daily:
      //   "Instead of Separate Headers for the Side bar we have to change that to ACtive, Beta and
      //    Settings and remove the rest."
      //
      // PRESENTATION ONLY, and that is load-bearing. Every href, label, glyph and BETA tag below is the
      // one it already had; nothing was added, dropped or renamed. PERMISSIONS ARE KEYED ON HREF
      // (nav_access.py TABS, whose docstring says keying on the label would break on a rename), never on
      // the label or the heading - so regrouping cannot change who sees what, and no permission rule
      // moves with it.
      //
      // WHAT WAS WRONG WITH EIGHT. Each heading said something true on its own - Sales, Leads & bids,
      // Proposals, Analytics, Database, Library, Records, Settings - and together they said very little:
      // most carried one or two rows, so the labels were a good share of what you scrolled past. Three is
      // the only split an estimator acts on: a page I work in today, a beta I am trying out, a setting I
      // touch twice a year.
      //
      // The per-item notes below are kept where they still apply. Several record decisions that were
      // reversed at least once, and the quotes behind them are still live.
      '<div class="tw-section">Active</div>' +
      // ACTIVE PROJECTS IS FIRST. Hanz, 2026-08-12: "This active Projects tab will be the Main
      // tab for all. Majority of the Sales Meeting will be held in this tab." It used to sit second,
      // below the Proposals Database - right when the Database was where you started a bid, wrong once
      // this board could start one too. The page you run the meeting from should not be something you
      // scroll past.
      navItem("/portal.html", "◆", "Active Projects") +
      // BACK IN THE MENU ON 2026-08-24, and this is the THIRD decision about it; the first two
      // took it out. All three are written down because the last reader of a half-told version deleted
      // this page from the menu twice.
      //
      //   2026-08-10  Hanz: "Remove the followups on the sidebar." Both its items went.
      //   2026-08-11  Hanz, having seen both gone: "Keep the Cadence and EMAILs... Just the follow up
      //               tab." So the BOARD was the clutter, not the cadence - which is why Auto Followups
      //               is down in Settings rather than up here.
      //   2026-08-24  Hanz, the day automated follow-ups went live on production: "make sure all follow
      //               up emails are shown in the Chat box and in the Follow Ups section." HE REVERSED
      //               2026-08-10. Do not "tidy" it back out on the strength of that quote; it has been
      //               answered.
      //
      // Directly under Active Projects because it is the same population read a different way: the board
      // answers "where does each live job stand", this answers "who has not been chased". Its own rows
      // even open that page (/portal.html?open=...&sec=followup), so filing it anywhere else would put
      // the link under one heading and land the click under another.
      navItem("/followups.html", "⏱", "Follow-ups") +
      // The daily queue, in the order the work actually arrives: it comes in, you price it,
      // you watch what is due. Bid Calendar sits right after Bid Pipeline because the two answer halves
      // of one question - the board is "where does each bid stand", the calendar is "what is due, and
      // when". Both read the Basisboard bids; neither writes to them.
      navItem("/leads.html", "▤", "Lead Inbox") +
      navItem("/crm.html", "▦", "Bid Pipeline") +
      navItem("/calendar.html", "▧", "Bid Calendar") +
      // THE LOOK-BACK PAGES. These four had three headings between them until 2026-08-25 -
      // Analytics, Database, Records - and none of the three earned a line of its own. Their ORDER still
      // carries the decision that arranged them: Analytics above the Proposals Database at Hanz's ask on
      // 2026-08-15 ("move Analytics above the Proposal Database Please"), because Analytics is something
      // you open to answer a question while the Database is a filing cabinet you go to on purpose.
      //
      // INFO SHEET IS NOT HERE, and that is not an oversight. It moved into the project drawer's Proposal
      // tab on 2026-08-20 (Hanz), beside the job it is a hand-off for; the menu row could only ever land
      // on its own choose-a-project state. THE TAB STILL EXISTS AS A PERMISSION - nav_access.py keeps its
      // capability entry, so /api/info-sheet/* is still refused to a denied role - and the matching row in
      // NO_SIDEBAR_TABS (declared further UP, just above the nav parser) is what lets the Admin page draw
      // its switch. That row now reads section "Active", because "Proposals" is one of the headings this
      // change removed, and a rowless tab filed under a heading that no longer exists is a row the matrix
      // cannot group.
      navItem("/analytics.html", "◫", "Analytics") +
      navItem("/projects.html", "▣", "Proposals Database") +
      navItem("/history.html", "⟲", "History") +
      navItem("/trash.html", "🗑", "Trash") +
      // THE BETAS, TOGETHER. One sat under Proposals and the other under a Library heading of
      // its own, which put work that is still being proven in the middle of the daily list. Both keep
      // their BETA tag as well as the heading: the heading says which shelf, and the tag is what survives
      // being read alone in the Admin role matrix, which prints labels without headings.
      '<div class="tw-section">Beta</div>' +
      // Opens at the beta's INTAKE, step 1 of its own four. A door straight into step 2 starts
      // an estimator on a project with no name, no bid date and no job conditions - and the conditions are
      // exactly what moved onto the intake form in the 2026-08-17 rework, so pricing first would mean
      // pricing before the five switches that change the price have been seen. The mid-flow door is
      // different and stays different: the toolbar link on Estimate Review goes straight to
      // /polish-estimate.html, because there the project already exists.
      navItem("/polish-intake.html", "◐", "Polish Estimate", "BETA") +
      // Reference data, not a daily page - the materials Treadwell buys and the assemblies
      // built out of them. (The Polish Estimate beta does price its takeoff from these assemblies; no
      // live bid does.) The brick rather than another shaded square: the geometric set is low-distinction
      // enough without two rows sharing a glyph, and a brick says "materials" at a glance.
      navItem("/library.html", "🧱", "Items and Assemblies", "BETA") +
      // The admin-editable rate table behind the polish beta's markup line, third because it
      // is reference data the same way the library is, not a page an estimator opens daily.
      navItem("/markup.html", "%", "Markup", "BETA") +
      '<div class="tw-section">Settings</div>' +
      navItem("/notifications.html", "✉", "Notification Sending") +
      // Kept at Hanz's request on 2026-08-11 after the Follow-ups board came out; the full
      // sequence is on Follow-ups above. Beside Notification Sending because the two answer one question
      // from opposite ends: who hears from us, and what they hear. This page is the only editor for the
      // four recurring customer emails, and its save REPLACES the single settings row with no history, so
      // an unreachable version of it is one wording change away from being unrecoverable.
      navItem("/followup-settings.html", "⏲", "Auto Followups") +
      (isAdmin ? navItem("/admin.html", "◇", "Admin") : "") +
      '</nav>' +
      '<div class="tw-user"><div class="tw-avatar" style="background:' +
      avatarColor(u.name, u.email) + '">' + esc(initials(u.name, u.email)) + '</div>' +
      '<div class="tw-userinfo"><div class="tw-userline">' +
      '<span class="tw-username">' + esc(u.name || u.email || "Signed in") + '</span>' +
      '<span class="tw-badge ' + roleClass + '">' + roleLabel + '</span></div>' +
      '<div class="tw-useremail">' + esc(u.email || "") + '</div></div>' +
      '<button class="tw-signout" id="tw-signout" title="Sign out">⏻</button></div>';
    RENDER_DENY = [];        // the markup is built; nothing else may read this
    // Spec mode stops here: the caller wanted the markup, not a sidebar on the page.
    if (spec) return aside.innerHTML;
    document.body.appendChild(aside);

    // NO NAV ITEM NEEDS THE DRAFT ID any more. This is where the ?d= rewrite lived: the sidebar is
    // injected after sign-in resolves, long after shared.js's DOMContentLoaded pass that appends ?d=
    // to project-scoped links, so a project-scoped nav item had to carry it itself. Info Sheet was
    // the only one, and it left the menu on 2026-08-20 for the project drawer, where the project is
    // already in hand. Every item above is a whole-app page. If a project-scoped item ever comes
    // back, that rewrite comes back with it — it is not optional, or the link opens the wrong job.

    const backdrop = document.createElement("div"); backdrop.id = "tw-backdrop";
    backdrop.setAttribute("aria-hidden", "true");
    document.body.appendChild(backdrop);
    const burger = document.createElement("button"); burger.id = "tw-burger";
    burger.title = "Menu";
    // aria-label as well as the glyph: the ☰ reads as "trigram for heaven" to a screen reader.
    burger.setAttribute("aria-label", "Menu");
    burger.setAttribute("aria-controls", "tw-sidebar");
    burger.innerHTML = "☰"; document.body.appendChild(burger);
    const collapse = document.getElementById("tw-collapse");

    // ── THE VIEWPORT OWNS THE OPEN STATE, NOT THE ACCOUNT ────────────────────────────────
    // `tw_nav_open` is read and written ONLY at desktop width. Below it, every page starts with the
    // drawer shut and every toggle lasts as long as the visit.
    //
    // WHAT WAS WRONG. The flag used to be restored at any width, and the DESKTOP default is open, so
    // one visit on a laptop wrote "1" and every later phone visit inherited it. Measured on staging
    // at 375px: the 240px rail covered 64% of the screen and clicking the Items tab timed out with
    // the drawer's own <a class="tw-nav-item"> named as the element intercepting pointer events. The
    // drawer, the burger and the scrim all existed and all worked - what was broken was who decided
    // the starting state. That is why this is nine lines and not a new component.
    //
    // A live query object, not a one-shot boolean: the same page is a phone in portrait and a small
    // tablet in landscape, and the old `const wide = ...matches` answered for whichever it was at
    // sign-in.
    const mql = window.matchMedia("(min-width: 768px)");
    const wide = () => mql.matches;
    const isOpen = () => document.documentElement.classList.contains("tw-nav-open");
    const setOpen = (open) => {
      document.documentElement.classList.toggle("tw-nav-open", open);
      // The assistive tree agrees with the cascade. Without this a screen reader still walks a menu
      // the CSS has made inert, which is the same bug in the other modality.
      aside.setAttribute("aria-hidden", open ? "false" : "true");
      burger.setAttribute("aria-expanded", open ? "true" : "false");
      if (wide()) { try { localStorage.setItem("tw_nav_open", open ? "1" : "0"); } catch {} }
    };
    let persisted = null; try { persisted = localStorage.getItem("tw_nav_open"); } catch {}
    // Desktop keeps exactly the behaviour it had: remembered if remembered, open if never set.
    setOpen(wide() ? persisted !== "0" : false);

    const openNav = () => { setOpen(true); if (!wide()) collapse.focus(); };
    // Focus goes back where the finger was. A drawer that closes and leaves the caret inside its
    // now-invisible subtree is why visibility:hidden is doing half this job in CSS.
    const closeNav = () => { const wasNarrow = !wide(); setOpen(false); if (wasNarrow) burger.focus(); };

    burger.addEventListener("click", openNav);
    backdrop.addEventListener("click", closeNav);
    collapse.addEventListener("click", closeNav);
    document.getElementById("tw-signout").addEventListener("click", signOut);
    // Escape only where the drawer is MODAL. At desktop it is a rail beside the page and closing it
    // on Escape would fight every dialog and every Escape-to-cancel on the page behind it.
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !wide() && isOpen()) closeNav();
    });
    // Tapping a destination shuts the sheet. The next page starts shut anyway, but the drawer would
    // otherwise sit over the old page for the whole load, which reads as a tap that did nothing.
    aside.addEventListener("click", (e) => {
      if (!wide() && e.target.closest && e.target.closest(".tw-nav-item")) setOpen(false);
    });
    // Crossing DOWN over 768px shuts it, so a rotate or a resize cannot leave a desktop rail lying
    // across a phone. It writes nothing: setOpen only persists while wide() is true, and by the time
    // this fires it is false - so a rotate can never poison the remembered desktop state.
    const onWidthChange = () => { if (!wide()) setOpen(false); };
    if (typeof mql.addEventListener === "function") mql.addEventListener("change", onWidthChange);
    else if (typeof mql.addListener === "function") mql.addListener(onWidthChange);

    // Notification bell. When the page has a brand/step header (the wizard pages),
    // fold the burger + bell INTO that one row — no separate bar — so the content
    // viewport (e.g. the estimate worksheet) gets a full bar of height back.
    // Otherwise fall back to a fixed 52px top bar (pages without a header).
    const bellHTML =
      '<button class="tw-bell" id="tw-bell" title="Notifications" aria-label="Notifications">🔔' +
      '<span class="tw-bell-badge" id="tw-bell-badge" hidden></span></button>';
    const pageHeader = document.querySelector("header.topbar");
    if (pageHeader) {
      const brand = pageHeader.querySelector(".brand");
      const progress = pageHeader.querySelector(".progress");
      const left = document.createElement("div"); left.className = "tw-hdr-left";
      const right = document.createElement("div"); right.className = "tw-hdr-right";
      burger.classList.add("tw-burger-inline");   // static, in-row (not the fixed corner burger)
      left.appendChild(burger);
      if (brand) left.appendChild(brand);
      if (progress) right.appendChild(progress);
      right.insertAdjacentHTML("beforeend", bellHTML);
      pageHeader.replaceChildren(left, right);
    } else {
      const topbar = document.createElement("header");
      topbar.id = "tw-topbar";
      topbar.innerHTML = bellHTML;
      document.body.appendChild(topbar);
      // Reserve the bar's height so it never covers page content.
      if (!document.body.dataset.twTopbarPad) {
        const pt = parseFloat(getComputedStyle(document.body).paddingTop) || 0;
        document.body.style.paddingTop = (pt + 52) + "px";
        document.body.dataset.twTopbarPad = "1";
      }
    }

    mountNotifications();
  }

  // ── A page this account may not open ──
  // The tab's own label, read back out of the menu, so the card names the page the way the sidebar
  // does and a rename cannot leave it saying something else. Rendered with NO denials, because the
  // row being looked up is by definition one this role does not get.
  //
  // The EMPTY MAP rather than no argument is load-bearing: passing a deny map is what makes
  // navMatrix include the tabs with no sidebar row, and one of those (Info Sheet) is refusable. With
  // no argument this would fall through to "This page" on exactly the pages nobody can name.
  function labelOf(href) {
    const rows = navMatrix({}).rows;
    for (let i = 0; i < rows.length; i++) if (rows[i].href === href) return rows[i].label;
    return "This page";
  }

  /* Paint a refusal and stop. Called from init() the moment /api/me says this path is denied.
   *
   * NOT a bare redirect and NOT "Access denied". Somebody bounced silently to another page thinks
   * their click did not register; somebody who lands on "Access denied" with no explanation files a
   * bug. This says which tab, who can turn it on, and that nothing was lost.
   *
   * The sidebar still goes up, so this is not a dead end — every tab they DO have is one click away.
   *
   * TWAuth.ready NEVER SETTLES from here, and that is the mechanism rather than an oversight. Every
   * page module boots with `await window.TWAuth.ready` and shared.js's API helper awaits it too, so
   * nothing runs against the document this just emptied. The alternative — resolving — means each
   * page's own boot continues, finds its elements gone, and either throws or paints an empty shell
   * back over this card.
   */
  async function showRefusal(href) {
    const label = labelOf(href);
    injectSidebarStyles();
    document.title = label + " isn't available — Treadwell";
    // Replace the page's content wholesale. By now the page's own <script> tags have run their
    // synchronous boot — auth.js resolves /api/me several ticks later — so what this covers is an
    // empty shell, not data: every data call on those pages goes through shared.js, which waits.
    try { document.body.replaceChildren(); } catch { document.body.innerHTML = ""; }
    document.body.style.paddingTop = "";
    try { delete document.body.dataset.twTopbarPad; } catch { /* stubbed dataset */ }
    const card = document.createElement("div");
    card.className = "tw-refuse";
    card.innerHTML =
      '<div class="tw-refuse-card">' +
      '<div class="tw-refuse-ico" aria-hidden="true">🔒</div>' +
      '<h1 class="tw-refuse-h">' + esc(label) + " isn't available on your account.</h1>" +
      '<p class="tw-refuse-p">An admin can turn it on for members from the Admin page. ' +
      'Nothing you were doing was lost.</p>' +
      '<a class="tw-refuse-go" href="' + HOME_PAGE + '">Go to Active Projects</a>' +
      '</div>';
    document.body.appendChild(card);
    renderSidebar();
    await new Promise(function () {});
  }

  // ── Notification bell ──
  // Polls /api/notifications (proposal deadlines + Basisboard pipeline changes),
  // shows an unread count on the bell, and a dropdown panel. Unread is global
  // (shared across the team); opening the panel marks everything seen. All wiring
  // is here (CSP: no inline handlers); dynamic values go through esc().
  function mountNotifications() {
    const bell = document.getElementById("tw-bell");
    if (!bell || document.getElementById("tw-notif-panel")) return;

    const panel = document.createElement("div");
    panel.id = "tw-notif-panel"; panel.hidden = true;
    panel.innerHTML =
      '<div class="tw-notif-head"><span>Notifications</span>' +
      '<button class="tw-notif-close" id="tw-notif-close" title="Close">×</button></div>' +
      '<div class="tw-notif-list" id="tw-notif-list">' +
      '<div class="tw-notif-empty">Loading…</div></div>';
    document.body.appendChild(panel);
    const back = document.createElement("div");
    back.id = "tw-notif-backdrop"; back.hidden = true;
    document.body.appendChild(back);

    // Bottom-right toast stack for brand-new customer messages (slides in on poll).
    const toasts = document.createElement("div");
    toasts.id = "tw-toasts";
    document.body.appendChild(toasts);

    let items = [], unread = 0, open = false;
    let toasted = loadToasted();   // ids already previewed (per browser) so we never repeat

    // Which message ids we've already shown a toast for — survives navigation via
    // localStorage, capped so it can't grow without bound.
    function loadToasted() {
      try { return new Set(JSON.parse(localStorage.getItem("tw_toasted") || "[]")); }
      catch { return new Set(); }
    }
    function saveToasted(set) {
      try { localStorage.setItem("tw_toasted", JSON.stringify(Array.from(set).slice(-100))); }
      catch { /* quota / private mode — best-effort */ }
    }
    function showToast(n) {
      const el = document.createElement("div");
      el.className = "tw-toast";
      el.innerHTML =
        '<span class="tw-toast-ico">' + esc(n.icon || "💬") + '</span>' +
        '<span class="tw-toast-main">' +
        '<span class="tw-toast-title">' + esc(n.title || "") + '</span>' +
        '<span class="tw-toast-body">' + esc(n.body || "") + '</span>' +
        '<span class="tw-toast-time">' + esc(relTime(n.ts)) + '</span></span>' +
        '<button class="tw-toast-x" title="Dismiss" aria-label="Dismiss">×</button>';
      toasts.appendChild(el);
      requestAnimationFrame(() => el.classList.add("tw-toast-in"));   // trigger slide-in
      let gone = false;
      const dismiss = () => {
        if (gone) return; gone = true;
        el.classList.remove("tw-toast-in");
        setTimeout(() => el.remove(), 400);   // after the slide-out transition
      };
      el.querySelector(".tw-toast-x").addEventListener("click", (e) => { e.stopPropagation(); dismiss(); });
      el.addEventListener("click", () => { if (n.link) location.href = n.link; });
      setTimeout(dismiss, 10000);   // auto-dismiss
    }

    function setBadge(n) {
      const b = document.getElementById("tw-bell-badge");
      if (!b) return;
      if (n > 0) { b.textContent = n > 99 ? "99+" : String(n); b.hidden = false; }
      else b.hidden = true;
    }
    function relTime(iso) {
      const t = Date.parse(iso); if (isNaN(t)) return "";
      let s = Math.floor((Date.now() - t) / 1000); if (s < 0) s = 0;
      if (s < 60) return "just now";
      const m = Math.floor(s / 60); if (m < 60) return m + "m ago";
      const h = Math.floor(m / 60); if (h < 24) return h + "h ago";
      const d = Math.floor(h / 24); if (d < 30) return d + "d ago";
      return Math.floor(d / 30) + "mo ago";
    }
    function renderList() {
      const list = document.getElementById("tw-notif-list");
      if (!list) return;
      if (!items.length) {
        list.innerHTML = '<div class="tw-notif-empty">You’re all caught up 🎉</div>';
        return;
      }
      list.innerHTML = items.map(n =>
        '<a class="tw-notif-item sev-' + esc(n.severity || "info") + '" href="' + esc(n.link || "#") + '">' +
        '<span class="tw-notif-ico">' + esc(n.icon || "•") + '</span>' +
        '<span class="tw-notif-main"><span class="tw-notif-title">' + esc(n.title || "") + '</span>' +
        '<span class="tw-notif-body">' + esc(n.body || "") + '</span></span>' +
        '<span class="tw-notif-time">' + esc(relTime(n.ts)) + '</span></a>'
      ).join("");
    }
    async function poll() {
      // A background tab has nothing to show and every call takes a server-side
      // lock plus a state-file read/write, so hidden tabs used to hammer the box
      // pointlessly all day. Staff keep this open on several tabs at once.
      if (document.hidden) return;
      try {
        const r = await fetch(apiBase() + "/api/notifications",
          { headers: { Authorization: "Bearer " + (window.__TW_TOKEN || "") } });
        const j = await r.json();
        if (j && j.ok) {
          items = j.notifications || []; unread = j.unread || 0;
          if (!open) setBadge(unread);
          if (open) renderList();
          maybeToast(j.last_seen_at || "");
        }
      } catch { /* offline — keep the last view */ }
    }
    // Preview brand-new customer messages: newer than the global last-seen AND not
    // shown before. Toast the 3 newest (items arrive newest-first) and mark the
    // rest previewed so a backlog lands in the bell without a toast storm. Never
    // toasts while the bell panel is open.
    function maybeToast(lastSeen) {
      if (open) return;
      const fresh = items.filter(x =>
        x.kind === "portal_message" && (x.ts || "") > lastSeen && !toasted.has(x.id));
      if (!fresh.length) return;
      fresh.slice(0, 3).forEach(showToast);
      fresh.forEach(x => toasted.add(x.id));
      saveToasted(toasted);
    }
    async function markSeen() {
      try {
        await fetch(apiBase() + "/api/notifications/seen",
          { method: "POST", headers: { Authorization: "Bearer " + (window.__TW_TOKEN || "") } });
      } catch { /* best-effort */ }
    }
    function openP() {
      open = true; panel.hidden = false; back.hidden = false;
      renderList();
      if (unread > 0) { markSeen(); unread = 0; setBadge(0); }   // opening = mark all seen
    }
    function closeP() { open = false; panel.hidden = true; back.hidden = true; }

    bell.addEventListener("click", (e) => { e.stopPropagation(); open ? closeP() : openP(); });
    document.getElementById("tw-notif-close").addEventListener("click", closeP);
    back.addEventListener("click", closeP);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && open) closeP(); });

    poll();
    setInterval(poll, 60000);   // refresh the badge every minute
    // Coming back to the tab should show current state immediately rather than up
    // to a minute later — and it catches up whatever was skipped while hidden.
    document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  }

  function injectSidebarStyles() {
    if (document.getElementById("tw-sidebar-css")) return;
    const css = `
:root{--tw-red:#c8102e;--tw-red-dark:#9e001f;--tw-ink:#1b1c1c;--tw-ink-v:#5c403f;
--tw-surf-low:#f5f3f3;--tw-surf-high:#e9e8e7;--tw-w:240px;}
body{transition:margin-left .2s ease;}
/* THE CLOSED DRAWER IS INERT, not merely off-screen. visibility:hidden takes the whole subtree
   out of hit-testing AND out of the tab order, so a shut menu can neither steal a tap meant for
   the page nor hand the keyboard thirteen links nobody can see; pointer-events:none states the
   first half again in the property a test can resolve without a browser. transform alone was
   never the guarantee it looked like - it is animatable, and mid-transition the rail is still
   over the page - and this repo has shipped the wearing-a-disguise version of this bug twice
   already (a class display rule beating the hidden attribute, and opacity:0 still taking clicks).
   visibility is switched with a 0s transition DELAYED by the slide's duration on the way out and
   0s on the way in, so the drawer is visible for the whole animation in both directions and
   inert the instant it has finished leaving. */
#tw-sidebar{position:fixed;top:0;left:0;height:100vh;width:var(--tw-w);background:#fff;
border-right:1px solid rgba(27,28,28,.1);display:flex;flex-direction:column;
padding:18px 14px;z-index:9998;transform:translateX(-100%);visibility:hidden;pointer-events:none;
transition:transform .2s ease,visibility 0s linear .2s;
font:400 14px/1.4 'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--tw-ink);box-sizing:border-box;}
html.tw-nav-open #tw-sidebar{transform:translateX(0);visibility:visible;pointer-events:auto;
transition:transform .2s ease,visibility 0s linear 0s;}
.tw-brand{display:flex;align-items:center;gap:10px;margin-bottom:22px;}
/* block kills the inline baseline gap; flex:none stops the 240px rail squeezing the mark */
.tw-bison{width:54px;height:34px;display:block;flex:none;}
.tw-brandname{font-size:18px;font-weight:600;line-height:1.1;}
.tw-brandsub{font-size:10.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--tw-ink-v);}
.tw-collapse{margin-left:auto;border:none;background:none;color:var(--tw-ink-v);font-size:20px;cursor:pointer;line-height:1;padding:2px 6px;border-radius:6px;}
.tw-collapse:hover{background:var(--tw-surf-low);}
.tw-nav{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:3px;}
.tw-section{font-size:10.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
color:var(--tw-ink-v);opacity:.7;padding:0 10px;margin:14px 0 4px;}
.tw-section:first-child{margin-top:0;}
.tw-nav-item{display:flex;align-items:center;gap:10px;min-height:42px;padding:0 10px;border-radius:7px;
text-decoration:none;color:var(--tw-ink);}
.tw-nav-item:hover{background:var(--tw-surf-low);}
.tw-nav-item.active{background:rgba(200,16,46,.1);color:var(--tw-red-dark);font-weight:600;}
.tw-nav-ico{width:20px;text-align:center;color:var(--tw-ink-v);font-size:15px;}
.tw-nav-tag{margin-left:auto;font:700 8.5px/1 system-ui;letter-spacing:.06em;
  padding:3px 5px;border-radius:4px;background:rgba(200,16,46,.12);
  color:var(--tw-red-dark);white-space:nowrap;}
.tw-nav-item.active .tw-nav-ico{color:var(--tw-red-dark);}
.tw-user{display:flex;align-items:center;gap:10px;padding:8px;border-radius:9px;background:var(--tw-surf-low);
margin-top:10px;border-top:1px solid rgba(27,28,28,.05);}
.tw-avatar{width:34px;height:34px;border-radius:50%;color:#fff;
font-weight:800;font-size:12.5px;letter-spacing:.02em;display:flex;align-items:center;justify-content:center;flex:none;}
/* THE estimator/person chip, defined once here because this stylesheet is injected on
   every page. Colour rides inline (per person, from crm-core's colorOf) since the CSP
   forbids an inline <style> block. Any page that names a person uses this class, so one
   person looks identical on the CRM board, Projects, Analytics and the Bid Pipeline.

   NOTE: this whole stylesheet is a JS template literal, so it must never contain a
   backtick — one in a comment silently ends the string and the entire file stops parsing.
   That took auth.js out on staging once, and because auth.js is what mints the bearer
   token, every page then answered 401 with no clue as to why.

   vertical-align:middle, not a pixel offset: the chip is a fixed 20px riding in text that
   ranges from 11px (Bid Pipeline card foot) to 14px (drawer body), and an offset like
   -4px is an ABSOLUTE shift of the chip's own baseline — which, since align-items:center
   already parks the initials near the middle of the disc, sits low to begin with. Tuned
   once at one font-size it can only be right there; on the 12px "Estimator:" line it
   dropped the disc ~5px below the name's optical centre. middle is measured against the
   PARENT's x-height, so it re-centres itself at every size. */
.tw-av{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;
border-radius:50%;margin-right:5px;flex:0 0 auto;font:800 9.5px/1 system-ui;letter-spacing:.02em;
color:#fff;vertical-align:middle;text-transform:uppercase;}
/* An inherited owner nobody actually chose. The "?" beside the name says so too — the
   dimming is reinforcement, never the only signal. */
.tw-av-dim{opacity:.5;}
.tw-userinfo{flex:1;min-width:0;}
.tw-userline{display:flex;align-items:center;gap:6px;}
.tw-username{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tw-badge{font-size:9px;font-weight:700;letter-spacing:.04em;padding:2px 5px;border-radius:5px;white-space:nowrap;}
.tw-badge.super{background:var(--tw-red-dark);color:#fff;}
.tw-badge.admin{background:#264b8b;color:#fff;}
.tw-badge.user{background:var(--tw-surf-high);color:var(--tw-ink-v);}
.tw-useremail{font-size:11px;color:var(--tw-ink-v);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tw-signout{border:none;background:none;color:var(--tw-ink-v);font-size:16px;cursor:pointer;flex:none;padding:4px;border-radius:6px;}
.tw-signout:hover{background:var(--tw-surf-high);color:var(--tw-red-dark);}
#tw-burger{position:fixed;top:12px;left:12px;z-index:9996;width:44px;height:44px;border-radius:9px;
border:1px solid rgba(27,28,28,.12);background:#fff;color:var(--tw-ink);font-size:18px;cursor:pointer;
display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,.08);}
html.tw-nav-open #tw-burger{display:none;}
/* one-line header: [burger + brand] ......... [progress + bell] */
#tw-burger.tw-burger-inline{position:static;top:auto;left:auto;box-shadow:none;width:34px;height:34px;flex:none;}
.tw-hdr-left{display:flex;align-items:center;gap:12px;min-width:0;}
.tw-hdr-right{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end;}
/* pointer-events as well as display: the scrim is the other half of the shut-drawer guarantee,
   and a stray display:block from anywhere would otherwise hand it every tap on the page. */
#tw-backdrop{display:none;pointer-events:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:9997;}
@media (min-width:768px){
  html.tw-nav-open body{margin-left:var(--tw-w);}
  #tw-backdrop{display:none !important;}
}
@media (max-width:767px){
  html.tw-nav-open #tw-backdrop{display:block;pointer-events:auto;}
  /* WIDER ON A PHONE, NOT NARROWER. 240px was chosen against a 1440px desktop where it is a rail
     beside the page; on a phone it is a modal sheet, and at 240 of 375 the long labels
     ("Notification Sending", "Items and Assemblies") truncate on the one screen where the label is
     all you have. min() keeps a strip of the page showing at every width this supports, so the
     sheet still reads as something laid OVER the page rather than as a new one. */
  #tw-sidebar{width:min(296px,86vw);}
  /* 44px is Apple's floor and 48 is Material's; a menu row is a whole-width target either way, so
     it takes the larger. Everything else in the chrome is a lone glyph and takes 44. The DESKTOP
     sizes are untouched - a mouse does not need this and the rail has no room for it. */
  .tw-nav-item{min-height:48px;}
  #tw-burger,#tw-burger.tw-burger-inline{width:44px;height:44px;}
  .tw-collapse,.tw-signout,.tw-bell{min-width:44px;min-height:44px;display:inline-flex;
    align-items:center;justify-content:center;}
  /* WIDE CONTENT SCROLLS IN ITS OWN BOX AND STOPS THERE. Every one of these already had
     overflow-x:auto; what they lacked is the second half - a swipe that runs off the end of a
     table used to hand the gesture to the browser's back navigation, which on the Bid Pipeline
     means losing the board rather than reaching the last column. Named one by one, and deliberately
     WITHOUT the proposal editor's .word-canvas: that box scrolls in both axes and a rule aimed at
     the horizontal one is not the place to start changing how the editor handles gestures. */
  .tablewrap,.tw,.t12-wrap,.mx-scroll,.board,.boardwrap{
    overscroll-behavior-x:contain;-webkit-overflow-scrolling:touch;}
}
/* a page this account may not open. Centred in the content column, not the viewport, so the
   sidebar beside it still reads as the way out. */
.tw-refuse{display:flex;align-items:center;justify-content:center;min-height:82vh;padding:28px 20px;
box-sizing:border-box;font:400 14px/1.55 'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
color:var(--tw-ink);}
.tw-refuse-card{max-width:46ch;text-align:center;background:#fff;border:1px solid rgba(27,28,28,.12);
border-radius:14px;padding:30px 28px 26px;box-shadow:0 10px 30px rgba(0,0,0,.07);}
.tw-refuse-ico{font-size:30px;line-height:1;margin-bottom:12px;}
.tw-refuse-h{font-size:17px;font-weight:600;line-height:1.35;margin:0 0 8px;}
.tw-refuse-p{margin:0 0 18px;color:var(--tw-ink-v);}
.tw-refuse-go{display:inline-block;text-decoration:none;background:var(--tw-red);color:#fff;
font-weight:600;padding:9px 16px;border-radius:9px;}
.tw-refuse-go:hover{background:var(--tw-red-dark);}
/* fixed top bar (hosts the notification bell, right-aligned) */
#tw-topbar{position:fixed;top:0;left:0;right:0;height:52px;z-index:9995;background:#fff;
border-bottom:1px solid rgba(27,28,28,.1);display:flex;align-items:center;justify-content:flex-end;
padding:0 18px;box-sizing:border-box;}
@media (min-width:768px){ html.tw-nav-open #tw-topbar{left:var(--tw-w);} }
/* clear the burger: it is fixed at left:12px and 44px wide since the phone pass, so 64 is 12+44+8 */
@media (max-width:767px){ #tw-topbar{padding-left:64px;} }
/* notification bell + dropdown */
.tw-bell{position:relative;border:none;background:none;color:var(--tw-ink-v);
font-size:18px;cursor:pointer;padding:5px 6px;border-radius:8px;line-height:1;}
.tw-bell:hover{background:var(--tw-surf-low);color:var(--tw-red-dark);}
.tw-bell-badge{position:absolute;top:-1px;right:-1px;min-width:16px;height:16px;padding:0 3px;
border-radius:8px;background:var(--tw-red);color:#fff;font:700 9px/16px system-ui;text-align:center;box-sizing:border-box;}
#tw-notif-backdrop{position:fixed;inset:0;z-index:10000;background:transparent;}
#tw-notif-panel{position:fixed;top:58px;right:16px;left:auto;width:min(340px,calc(100vw - 28px));max-height:72vh;
overflow-y:auto;background:#fff;border:1px solid rgba(27,28,28,.12);border-radius:12px;
box-shadow:0 16px 44px rgba(0,0,0,.22);z-index:10001;color:var(--tw-ink);
font:400 13px/1.45 'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}
.tw-notif-head{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;
font-weight:700;font-size:14px;border-bottom:1px solid rgba(27,28,28,.08);position:sticky;top:0;background:#fff;}
.tw-notif-close{border:none;background:none;font-size:18px;line-height:1;cursor:pointer;color:var(--tw-ink-v);padding:0 4px;border-radius:6px;}
.tw-notif-close:hover{background:var(--tw-surf-low);}
.tw-notif-list{padding:6px;}
.tw-notif-empty{padding:26px 14px;text-align:center;color:var(--tw-ink-v);}
.tw-notif-item{display:flex;gap:10px;align-items:flex-start;padding:10px;border-radius:9px;text-decoration:none;color:var(--tw-ink);}
.tw-notif-item:hover{background:var(--tw-surf-low);}
.tw-notif-ico{font-size:15px;line-height:1.3;flex:none;width:18px;text-align:center;}
.tw-notif-main{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px;}
.tw-notif-title{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tw-notif-body{color:var(--tw-ink-v);font-size:12px;}
.tw-notif-time{color:var(--tw-ink-v);font-size:11px;flex:none;white-space:nowrap;padding-top:1px;}
.tw-notif-item.sev-high .tw-notif-title{color:var(--tw-red-dark);}
/* bottom-right toast previews for new customer messages */
#tw-toasts{position:fixed;right:16px;bottom:16px;z-index:9990;display:flex;flex-direction:column;gap:10px;
width:min(360px,calc(100vw - 28px));pointer-events:none;}
.tw-toast{pointer-events:auto;display:flex;gap:10px;align-items:flex-start;background:#fff;
border:1px solid rgba(27,28,28,.12);border-left:3px solid var(--tw-red);border-radius:11px;
padding:12px 12px 12px 13px;box-shadow:0 12px 34px rgba(0,0,0,.20);cursor:pointer;
transform:translateX(120%);opacity:0;transition:transform .32s cubic-bezier(.22,1,.36,1),opacity .32s ease;
font:400 13px/1.4 'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--tw-ink);}
.tw-toast.tw-toast-in{transform:translateX(0);opacity:1;}
.tw-toast-ico{font-size:16px;line-height:1.25;flex:none;}
.tw-toast-main{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.tw-toast-title{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tw-toast-body{color:var(--tw-ink-v);font-size:12px;display:-webkit-box;-webkit-line-clamp:3;
-webkit-box-orient:vertical;overflow:hidden;}
.tw-toast-time{color:var(--tw-ink-v);font-size:11px;margin-top:2px;}
.tw-toast-x{border:none;background:none;color:var(--tw-ink-v);font-size:17px;line-height:1;cursor:pointer;
padding:0 3px;border-radius:6px;flex:none;}
.tw-toast-x:hover{background:var(--tw-surf-low);color:var(--tw-red-dark);}
@media (max-width:767px){#tw-toasts{left:12px;right:12px;bottom:12px;width:auto;}}`;
    const style = document.createElement("style");
    style.id = "tw-sidebar-css"; style.textContent = css;
    document.head.appendChild(style);
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function showFatal(msg) {
    const d = document.createElement("div");
    d.style.cssText = "position:fixed;inset:0;z-index:99999;background:#111;color:#eee;display:flex;" +
      "align-items:center;justify-content:center;text-align:center;padding:24px;font:500 15px system-ui;";
    d.innerHTML = esc(msg);
    document.body.appendChild(d);
  }

  function showLoginError(msg) {
    const e = document.getElementById("login-error");
    if (e) { e.textContent = msg; e.style.display = "block"; }
  }

  window.TWAuth.ready = init();
})();
