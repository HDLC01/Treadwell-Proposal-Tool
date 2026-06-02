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
    renderIndicator();
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

  function renderIndicator() {
    if (document.getElementById("tw-userbar")) return;
    const u = currentUser || {};
    const isAdmin = u.role === "admin" || u.role === "super_admin";
    const bar = document.createElement("div");
    bar.id = "tw-userbar";
    bar.style.cssText =
      "position:fixed;left:12px;bottom:12px;z-index:9999;display:flex;align-items:center;gap:10px;" +
      "background:#1c1c1e;color:#eee;border:1px solid rgba(255,255,255,.12);border-radius:10px;" +
      "padding:8px 12px;font:500 12px/1.2 system-ui,sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.35);";
    bar.innerHTML =
      '<div style="width:30px;height:30px;border-radius:50%;background:#3a3a3c;display:flex;' +
      'align-items:center;justify-content:center;font-weight:700;font-size:11px;">' +
      esc(initials(u.name, u.email)) + '</div>' +
      '<div style="display:flex;flex-direction:column;min-width:0;">' +
      '<span style="font-weight:700;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' +
      esc(u.name || u.email || "Signed in") +
      (isAdmin ? ' <span style="color:#c9a227;font-size:10px;">' + (u.role === "super_admin" ? "SUPER ADMIN" : "ADMIN") + "</span>" : "") +
      '</span>' +
      '<span style="opacity:.7;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(u.email || "") + '</span>' +
      '</div>' +
      '<a href="' + HOME_PAGE + '" title="Projects" style="color:#9ab;text-decoration:none;font-size:11px;">Projects</a>' +
      '<a href="/history.html" title="History" style="color:#9ab;text-decoration:none;font-size:11px;">History</a>' +
      (isAdmin ? '<a href="/admin.html" title="Admin" style="color:#c9a227;text-decoration:none;font-size:11px;">Admin</a>' : "") +
      '<button id="tw-signout" title="Sign out" style="background:none;border:none;color:#e88;cursor:pointer;font-size:15px;line-height:1;">⏻</button>';
    document.body.appendChild(bar);
    document.getElementById("tw-signout").addEventListener("click", signOut);
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
