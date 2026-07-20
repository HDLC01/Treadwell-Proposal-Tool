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
 *    and a Projects/History nav.
 */
(function () {
  const LOGIN_PAGE = "/login.html";
  const HOME_PAGE = "/projects.html";
  const path = location.pathname.toLowerCase();
  const onLogin = path === "/login.html" || path.endsWith("/login.html");

  let sb = null;
  let currentUser = null;          // { email, name, role, status }

  window.TWAuth = {
    ready: null,
    client: () => sb,
    user: () => currentUser,
    token: () => window.__TW_TOKEN || null,
    signInWithGoogle,
    signOut,
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
    } catch {
      currentUser = { email, role: "user", name: (session.user.user_metadata || {}).full_name };
    }
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
  function initials(name, email) {
    const s = (name || email || "?").trim();
    const parts = s.split(/\s+/);
    return ((parts[0] || "")[0] || "" + ((parts[1] || "")[0] || "")).toUpperCase()
      || s.slice(0, 2).toUpperCase();
  }

  // Left sidebar matching the main Treadwell app (light, 240px, red accent),
  // collapsing to an off-canvas drawer under 768px.
  function navItem(href, glyph, label) {
    const active = location.pathname.toLowerCase().endsWith(href.toLowerCase());
    return '<a class="tw-nav-item' + (active ? " active" : "") + '" href="' + href + '">' +
      '<span class="tw-nav-ico">' + glyph + '</span><span class="tw-nav-label">' + label + '</span></a>';
  }

  function renderSidebar() {
    if (document.getElementById("tw-sidebar")) return;
    injectSidebarStyles();
    const u = currentUser || {};
    const isAdmin = u.role === "admin" || u.role === "super_admin";
    const roleLabel = u.role === "super_admin" ? "SUPER ADMIN" : (u.role === "admin" ? "ADMIN" : "USER");
    const roleClass = u.role === "super_admin" ? "super" : (u.role === "admin" ? "admin" : "user");

    const aside = document.createElement("aside");
    aside.id = "tw-sidebar";
    aside.innerHTML =
      '<div class="tw-brand"><div class="tw-logo">T</div>' +
      '<div class="tw-brandtext"><div class="tw-brandname">Treadwell</div>' +
      '<div class="tw-brandsub">Proposal Tool</div></div>' +
      '<button class="tw-collapse" id="tw-collapse" title="Hide menu">‹</button></div>' +
      '<nav class="tw-nav">' +
      '<div class="tw-section">Workspace</div>' +
      navItem("/projects.html", "▣", "Projects") +
      navItem("/crm.html", "▦", "Pipeline") +
      navItem("/portal.html", "◆", "Customer Portal") +
      navItem("/notifications.html", "✉", "Notification Sending") +
      navItem("/history.html", "⟲", "History") +
      navItem("/trash.html", "🗑", "Trash") +
      (isAdmin ? '<div class="tw-section">System</div>' + navItem("/admin.html", "◇", "Admin") : "") +
      '</nav>' +
      '<div class="tw-user"><div class="tw-avatar">' + esc(initials(u.name, u.email)) + '</div>' +
      '<div class="tw-userinfo"><div class="tw-userline">' +
      '<span class="tw-username">' + esc(u.name || u.email || "Signed in") + '</span>' +
      '<span class="tw-badge ' + roleClass + '">' + roleLabel + '</span></div>' +
      '<div class="tw-useremail">' + esc(u.email || "") + '</div></div>' +
      '<button class="tw-signout" id="tw-signout" title="Sign out">⏻</button></div>';
    document.body.appendChild(aside);

    const backdrop = document.createElement("div"); backdrop.id = "tw-backdrop";
    document.body.appendChild(backdrop);
    const burger = document.createElement("button"); burger.id = "tw-burger";
    burger.title = "Menu"; burger.innerHTML = "☰"; document.body.appendChild(burger);

    const setOpen = (open) => {
      document.documentElement.classList.toggle("tw-nav-open", open);
      try { localStorage.setItem("tw_nav_open", open ? "1" : "0"); } catch {}
    };
    let persisted = null; try { persisted = localStorage.getItem("tw_nav_open"); } catch {}
    const wide = window.matchMedia("(min-width: 768px)").matches;
    setOpen(persisted !== null ? persisted === "1" : wide);

    burger.addEventListener("click", () => setOpen(true));
    backdrop.addEventListener("click", () => setOpen(false));
    document.getElementById("tw-collapse").addEventListener("click", () => setOpen(false));
    document.getElementById("tw-signout").addEventListener("click", signOut);

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

    let items = [], unread = 0, open = false;

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
      try {
        const r = await fetch(apiBase() + "/api/notifications",
          { headers: { Authorization: "Bearer " + (window.__TW_TOKEN || "") } });
        const j = await r.json();
        if (j && j.ok) {
          items = j.notifications || []; unread = j.unread || 0;
          if (!open) setBadge(unread);
          if (open) renderList();
        }
      } catch { /* offline — keep the last view */ }
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
  }

  function injectSidebarStyles() {
    if (document.getElementById("tw-sidebar-css")) return;
    const css = `
:root{--tw-red:#c8102e;--tw-red-dark:#9e001f;--tw-ink:#1b1c1c;--tw-ink-v:#5c403f;
--tw-surf-low:#f5f3f3;--tw-surf-high:#e9e8e7;--tw-w:240px;}
body{transition:margin-left .2s ease;}
#tw-sidebar{position:fixed;top:0;left:0;height:100vh;width:var(--tw-w);background:#fff;
border-right:1px solid rgba(27,28,28,.1);display:flex;flex-direction:column;
padding:18px 14px;z-index:9998;transform:translateX(-100%);transition:transform .2s ease;
font:400 14px/1.4 'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--tw-ink);box-sizing:border-box;}
html.tw-nav-open #tw-sidebar{transform:translateX(0);}
.tw-brand{display:flex;align-items:center;gap:10px;margin-bottom:22px;}
.tw-logo{width:34px;height:34px;border-radius:9px;background:var(--tw-red);color:#fff;
font-weight:800;font-size:17px;display:flex;align-items:center;justify-content:center;flex:none;}
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
.tw-nav-item.active .tw-nav-ico{color:var(--tw-red-dark);}
.tw-user{display:flex;align-items:center;gap:10px;padding:8px;border-radius:9px;background:var(--tw-surf-low);
margin-top:10px;border-top:1px solid rgba(27,28,28,.05);}
.tw-avatar{width:34px;height:34px;border-radius:50%;background:var(--tw-surf-high);color:var(--tw-ink);
font-weight:700;font-size:13px;display:flex;align-items:center;justify-content:center;flex:none;}
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
#tw-burger{position:fixed;top:12px;left:12px;z-index:9996;width:40px;height:40px;border-radius:9px;
border:1px solid rgba(27,28,28,.12);background:#fff;color:var(--tw-ink);font-size:18px;cursor:pointer;
display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,.08);}
html.tw-nav-open #tw-burger{display:none;}
/* one-line header: [burger + brand] ......... [progress + bell] */
#tw-burger.tw-burger-inline{position:static;top:auto;left:auto;box-shadow:none;width:34px;height:34px;flex:none;}
.tw-hdr-left{display:flex;align-items:center;gap:12px;min-width:0;}
.tw-hdr-right{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end;}
#tw-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:9997;}
@media (min-width:768px){
  html.tw-nav-open body{margin-left:var(--tw-w);}
  #tw-backdrop{display:none !important;}
}
@media (max-width:767px){
  html.tw-nav-open #tw-backdrop{display:block;}
}
/* fixed top bar (hosts the notification bell, right-aligned) */
#tw-topbar{position:fixed;top:0;left:0;right:0;height:52px;z-index:9995;background:#fff;
border-bottom:1px solid rgba(27,28,28,.1);display:flex;align-items:center;justify-content:flex-end;
padding:0 18px;box-sizing:border-box;}
@media (min-width:768px){ html.tw-nav-open #tw-topbar{left:var(--tw-w);} }
@media (max-width:767px){ #tw-topbar{padding-left:60px;} }   /* clear the burger */
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
.tw-notif-item.sev-high .tw-notif-title{color:var(--tw-red-dark);}`;
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
