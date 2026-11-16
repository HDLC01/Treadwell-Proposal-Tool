/* Connect Raken (#781): the admin-only control on the Project Analytics page.
 *
 * Its own script, so the page's own script (js/project-calendar.js) stays free of writes: this is
 * the only place on the page that sends one (the POST that finishes a sign-in). It finds the page's
 * header (".top") or makes its own row, and puts a status line and a "Connect Raken" button in it.
 * A member who is not an admin gets nothing at all; the routes refuse them anyway (403).
 *
 * The sign-in, as the browser sees it:
 *   1. "Connect Raken" asks GET /api/raken/connect for Raken's Allow-page address (a GET with the
 *      bearer token: this app has no cookies, so a bare navigation to the route would carry no
 *      identity) and goes there. Only an https address on app.rakenapp.com is followed.
 *   2. Raken sends the browser to /api/raken/callback, which bounces back to this page with
 *      raken_code and raken_state (or raken_error) in the address.
 *   3. This script takes them out of the address at once and hands them to POST
 *      /api/raken/callback, then shows the status: "Connected: N Raken projects, M with a Project
 *      Number" plus a few example numbers, which is how an admin checks that Raken's Project
 *      Numbers are our Job numbers.
 *
 * Styling goes through classes the page already has (.btn) and the CSSOM, never an inline style
 * attribute (the nginx CSP). Every value from the server is shown with textContent.
 */
(function (root) {
  "use strict";

  const ADMIN_ROLES = ["admin", "super_admin"];
  const RAKEN_AUTHORIZE = "https://app.rakenapp.com/oauth/authorize";

  function isAdmin(user) {
    return !!user && ADMIN_ROLES.indexOf(String(user.role || "")) !== -1;
  }

  /** {code, state, error} when the address carries a sign-in coming back from Raken, else null. */
  function callbackFrom(search) {
    let q;
    try { q = new URLSearchParams(String(search || "")); } catch (e) { return null; }
    const code = q.get("raken_code") || "";
    const state = q.get("raken_state") || "";
    const error = q.get("raken_error") || "";
    if (!code && !state && !error) return null;
    return { code: code, state: state, error: error };
  }

  /** The address without the raken_* parameters, so a reload never sends the code again. */
  function addressWithoutCallback(pathname, search, hash) {
    let q;
    try { q = new URLSearchParams(String(search || "")); } catch (e) { q = new URLSearchParams(); }
    ["raken_code", "raken_state", "raken_error"].forEach((k) => q.delete(k));
    const rest = q.toString();
    return String(pathname || "/") + (rest ? "?" + rest : "") + String(hash || "");
  }

  /** Follow only Raken's own Allow page, over https. */
  function isRakenAllowPage(url) {
    let u;
    try { u = new URL(String(url || "")); } catch (e) { return false; }
    return u.protocol === "https:" && u.origin + u.pathname === RAKEN_AUTHORIZE;
  }

  /** {text, tone} for a status response: tone is "ok", "warn" or "muted". */
  function statusLine(body) {
    if (!body || typeof body !== "object") return { text: "Raken status is unavailable.", tone: "warn" };
    const msg = typeof body.message === "string" ? body.message : "";
    if (body.state === "connected") {
      if (body.error) return { text: "Raken is connected. " + String(body.error), tone: "warn" };
      const ex = Array.isArray(body.examples) ? body.examples.filter((x) => typeof x === "string") : [];
      return { text: msg + (ex.length ? " (for example " + ex.join(", ") + ")" : ""), tone: "ok" };
    }
    if (body.state === "expired") return { text: msg, tone: "warn" };
    return { text: msg || "Raken is not connected.", tone: "muted" };
  }

  // ── the page ────────────────────────────────────────────────────────
  /** Run once the page's sign-in is known. `env` carries the browser pieces, so tests can run it. */
  async function boot(env) {
    const auth = env.auth;
    try { if (auth && auth.ready) await auth.ready; } catch (e) { return null; }
    if (!isAdmin(auth && auth.user ? auth.user() : null)) return null;

    const doc = env.document;
    const box = doc.createElement("span");
    box.className = "raken-connect";
    box.style.display = "inline-flex";
    box.style.alignItems = "center";
    box.style.gap = "8px";
    box.style.flexWrap = "wrap";
    const line = doc.createElement("span");
    line.className = "raken-status";
    line.style.fontSize = "12.5px";
    const btn = doc.createElement("button");
    btn.type = "button";
    btn.className = "btn";
    btn.textContent = "Connect Raken";
    box.appendChild(line);
    box.appendChild(btn);
    let host = doc.querySelector(".top");
    if (!host) {
      host = doc.createElement("div");
      host.className = "raken-connect-row";
      doc.body.insertBefore(host, doc.body.firstChild);
    }
    host.appendChild(box);

    const headers = (extra) => Object.assign({}, extra || {}, env.authHeaders());
    const say = (s) => {
      line.textContent = s.text;
      line.style.color = s.tone === "ok" ? "var(--calm, #4a6b8a)"
        : s.tone === "warn" ? "var(--warn, #7a5c00)" : "var(--ink-v, #555)";
    };

    async function refresh() {
      say({ text: "Checking Raken…", tone: "muted" });
      try {
        const r = await env.fetch(env.base() + "/api/raken/status", { headers: headers() });
        const body = await r.json().catch(() => null);
        say(r.ok ? statusLine(body)
          : { text: (body && typeof body.detail === "string" && body.detail) || "Raken status is unavailable.",
              tone: "warn" });
      } catch (e) {
        say({ text: "Couldn't reach the server.", tone: "warn" });
      }
    }

    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const r = await env.fetch(env.base() + "/api/raken/connect", { headers: headers() });
        const body = await r.json().catch(() => null);
        if (r.ok && body && isRakenAllowPage(body.url)) { env.go(body.url); return; }
        say({ text: (body && typeof body.detail === "string" && body.detail) || "Couldn't start the Raken sign-in.",
              tone: "warn" });
      } catch (e) {
        say({ text: "Couldn't reach the server.", tone: "warn" });
      }
      btn.disabled = false;
    });

    const back = callbackFrom(env.location.search);
    if (back) {
      // Out of the address first, so neither a reload nor the history replays the code.
      try {
        env.history.replaceState(null, "", addressWithoutCallback(env.location.pathname,
          env.location.search, env.location.hash));
      } catch (e) { /* an old browser keeps the address; the code is single-use anyway */ }
      if (back.error || !back.code) {
        say({ text: "The Raken sign-in was cancelled. Press Connect Raken to try again.", tone: "warn" });
        return box;
      }
      say({ text: "Finishing the Raken sign-in…", tone: "muted" });
      try {
        const r = await env.fetch(env.base() + "/api/raken/callback", {
          method: "POST",
          headers: headers({ "Content-Type": "application/json" }),
          body: JSON.stringify({ code: back.code, state: back.state }),
        });
        if (!r.ok) {
          const body = await r.json().catch(() => null);
          say({ text: (body && typeof body.detail === "string" && body.detail) || "The Raken sign-in failed.",
                tone: "warn" });
          return box;
        }
      } catch (e) {
        say({ text: "Couldn't reach the server.", tone: "warn" });
        return box;
      }
    }
    await refresh();
    return box;
  }

  const api = { isAdmin, callbackFrom, addressWithoutCallback, isRakenAllowPage, statusLine, boot };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }   // node, for tests
  root.TWRakenConnect = api;
  boot({
    auth: root.TWAuth,
    document: root.document,
    location: root.location,
    history: root.history,
    fetch: (url, opts) => root.fetch(url, opts),
    base: () => (root.TW && root.TW.resolveApiBase ? root.TW.resolveApiBase() : ""),
    authHeaders: () => (root.TW && root.TW.authHeaders ? root.TW.authHeaders() : {}),
    go: (url) => root.location.assign(url),
  });
})(typeof window !== "undefined" ? window : globalThis);
