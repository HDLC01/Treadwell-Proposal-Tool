/**
 * Shared helpers for the 3-screen proposal-generator flow.
 *
 * State between screens is held in `sessionStorage` under a single key.
 * Refreshing mid-flow is intentional: starts the user from Screen 1
 * so we don't show stale half-filled data.
 *
 * Each screen reads state on load, writes state on next/back click,
 * navigates via window.location.assign(). No SPA, no router — just
 * static HTML pages talking through the storage bucket.
 */
(function () {
  const STATE_KEY = "treadwell.proposal_tool.state";
  const DRAFT_ID_KEY = "treadwell.proposal_tool.draft_id";
  const RELOAD_GUARD = "treadwell.proposal_tool.hydrated_once";

  /**
   * API base URL resolution (in priority order):
   *   1. `window.TW_API_BASE` set by a page's inline <script> (used by Vercel
   *      deploys to point at the Railway backend URL)
   *   2. `localStorage.tw_api_base` (debug override, e.g. point at staging)
   *   3. Empty string = same-origin (used when FastAPI serves the static
   *      frontend itself during local dev)
   */
  function resolveApiBase() {
    if (typeof window.TW_API_BASE === "string") return window.TW_API_BASE;
    try {
      const fromStorage = localStorage.getItem("tw_api_base");
      if (fromStorage) return fromStorage;
    } catch {/* private mode */}
    return "";
  }

  // ─── State accessors ──────────────────────────────────────────────
  // Storage is localStorage (not sessionStorage) so a draft survives the
  // tab being closed + reopened on the SAME machine. Cross-device is
  // handled by the SQLite sync layer below (draft id travels in the URL).
  function getState() {
    try {
      const raw = localStorage.getItem(STATE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  function setState(partial) {
    const merged = Object.assign(getState(), partial || {});
    try { localStorage.setItem(STATE_KEY, JSON.stringify(merged)); }
    catch {/* quota / private mode */}
    scheduleServerSave(merged);   // debounced push to SQLite
    return merged;
  }

  function clearState() {
    // Start a fresh project: clear LOCAL state only. We intentionally do NOT
    // delete the server draft — projects are unified + persistent (shared with
    // the whole @wetreadwell domain), so "start new" must never remove a saved
    // project from everyone's Projects list. Removal is an explicit Admin action.
    try { localStorage.removeItem(STATE_KEY); } catch {}
    try { localStorage.removeItem(DRAFT_ID_KEY); } catch {}
    try { sessionStorage.removeItem(RELOAD_GUARD); } catch {}
    // Drop the ?d= from the URL so a fresh start gets a fresh id.
    try {
      const url = new URL(window.location.href);
      url.searchParams.delete("d");
      window.history.replaceState({}, "", url);
    } catch {}
  }

  // ─── Draft id + multi-device sync ─────────────────────────────────
  // The draft id lives in the URL (?d=<uuid>) so the URL is shareable
  // across devices, and in localStorage so it persists across same-tab
  // navigations (which drop the query string).
  function getDraftId() {
    try {
      const fromUrl = new URL(window.location.href).searchParams.get("d");
      if (fromUrl) return fromUrl;
    } catch {}
    try { return localStorage.getItem(DRAFT_ID_KEY) || null; } catch { return null; }
  }

  function newDraftId() {
    try {
      if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    } catch {}
    // Fallback: timestamp + random
    return "d" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  function setDraftId(id) {
    try { localStorage.setItem(DRAFT_ID_KEY, id); } catch {}
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.get("d") !== id) {
        url.searchParams.set("d", id);
        window.history.replaceState({}, "", url);
      }
    } catch {}
  }

  let _saveTimer = null;
  function scheduleServerSave(state) {
    const id = getDraftId();
    if (!id) return;            // no id yet → nothing to sync
    if (_saveTimer) clearTimeout(_saveTimer);
    _saveTimer = setTimeout(() => {
      fetch(resolveApiBase() + "/api/draft/" + encodeURIComponent(id), {
        method: "PUT",
        headers: authHeaders(),
        body: JSON.stringify({ data: state }),
        keepalive: true,         // let it finish even if the tab is closing
      }).catch(() => {/* offline / backend down — local copy still safe */});
    }, 2500);                    // debounce: save 2.5s after the last edit
  }

  // Runs once on every page load (before the page's own init reads state).
  // Handles three cases:
  //   1. URL has ?d= matching local  → same session, trust local, sync URL
  //   2. URL has ?d= NOT in local    → cross-device open → pull from server,
  //                                     write to localStorage, reload once
  //   3. no ?d= but local has a draft → assert the id back into the URL
  //   4. nothing                      → mint a fresh id (lazily, on first save)
  async function initDraftSync() {
    // The cross-device pull below hits the auth-gated /api/draft/{id}. Wait for
    // the Supabase token (set by auth.js) so the GET isn't 401'd — otherwise a
    // reopened project link would silently start empty instead of hydrating.
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    let urlId = null;
    try { urlId = new URL(window.location.href).searchParams.get("d"); } catch {}
    const localId = (() => { try { return localStorage.getItem(DRAFT_ID_KEY); } catch { return null; } })();
    const guard = (() => { try { return sessionStorage.getItem(RELOAD_GUARD); } catch { return null; } })();

    if (urlId && urlId !== localId && guard !== urlId) {
      // Cross-device (or returning) open — pull the server copy.
      try {
        const res = await fetch(resolveApiBase() + "/api/draft/" + encodeURIComponent(urlId),
                                { headers: authHeaders() });
        if (res.ok) {
          const body = await res.json();
          if (body && body.data) {
            try { localStorage.setItem(STATE_KEY, JSON.stringify(body.data)); } catch {}
            try { localStorage.setItem(DRAFT_ID_KEY, urlId); } catch {}
            try { sessionStorage.setItem(RELOAD_GUARD, urlId); } catch {}
            window.location.reload();   // re-run page init with hydrated state
            return;
          }
        }
        // 404 → treat the url id as a brand-new draft on this device.
        setDraftId(urlId);
      } catch {
        setDraftId(urlId);              // backend unreachable — adopt id locally
      }
    } else if (urlId) {
      setDraftId(urlId);                // same-session, keep URL + local in sync
    } else if (localId) {
      setDraftId(localId);             // re-assert id into URL after navigation
    } else {
      // No draft yet. Mint one only once the user actually has state, so
      // a bare visit to "/" doesn't create empty drafts. We set it here
      // anyway so the very first setState() syncs.
      setDraftId(newDraftId());
    }
  }

  // Kick off sync as soon as the script loads.
  try { initDraftSync(); } catch {/* never block page render */}

  // ─── Form helpers ─────────────────────────────────────────────────
  /** Serialise a <form> into a plain object. Numbers become Numbers. */
  function readForm(formEl) {
    const out = {};
    for (const el of formEl.elements) {
      if (!el.name) continue;
      if (el.type === "checkbox") {
        out[el.name] = el.checked;
      } else if (el.type === "radio") {
        if (el.checked) out[el.name] = el.value;
      } else if (el.type === "number") {
        out[el.name] = el.value === "" ? null : Number(el.value);
      } else {
        out[el.name] = el.value;
      }
    }
    return out;
  }

  /** Bind state into a <form> so refreshes / Back buttons pre-fill it. */
  function writeForm(formEl, values) {
    if (!values) return;
    for (const el of formEl.elements) {
      if (!el.name || values[el.name] == null) continue;
      if (el.type === "checkbox") {
        el.checked = !!values[el.name];
      } else if (el.type === "radio") {
        el.checked = String(el.value) === String(values[el.name]);
      } else {
        el.value = values[el.name];
      }
    }
  }

  // ─── API helpers ──────────────────────────────────────────────────
  // Every API call carries the Supabase auth token (set by auth.js on
  // window.__TW_TOKEN) + the current project id. The backend gates /api/*
  // on the token and uses X-Project-Id for the per-project rate bucket +
  // history attribution.
  function authHeaders(extra) {
    const h = Object.assign({ "Content-Type": "application/json" }, extra || {});
    const tok = (typeof window !== "undefined") ? window.__TW_TOKEN : null;
    if (tok) h["Authorization"] = "Bearer " + tok;
    const id = getDraftId();
    if (id) h["X-Project-Id"] = id;
    return h;
  }

  async function postJSON(path, body) {
    const res = await fetch(resolveApiBase() + path, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`POST ${path} → ${res.status}: ${text}`);
    }
    return res.json();
  }

  // ─── Number formatting ────────────────────────────────────────────
  function fmtUsd(n) {
    if (n == null || isNaN(Number(n))) return "$—";
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(Number(n));
  }

  /** Build an absolute URL to a backend path (e.g. download links). */
  function absoluteUrl(path) {
    return resolveApiBase() + path;
  }

  // ─── Expose ───────────────────────────────────────────────────────
  window.TW = {
    getState,
    setState,
    clearState,
    readForm,
    writeForm,
    postJSON,
    authHeaders,
    fmtUsd,
    absoluteUrl,
    resolveApiBase,
    getDraftId,
    initDraftSync,
  };
})();
