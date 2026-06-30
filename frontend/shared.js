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

  // ─── Confirm modal ────────────────────────────────────────────────
  // A styled in-app replacement for the browser's native confirm() — used for
  // destructive actions (delete forever, move to trash). Returns a Promise that
  // resolves true (confirmed) / false (cancelled). CSP allows inline <style>
  // (every page ships one) but NOT inline scripts, so the CSS is injected here
  // once and all behaviour is wired with addEventListener.
  let _modalCssDone = false;
  function injectModalCss() {
    if (_modalCssDone) return; _modalCssDone = true;
    const s = document.createElement("style");
    s.textContent = [
      ".tw-ov{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;padding:20px;",
      "background:rgba(20,18,18,.55);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);opacity:0;transition:opacity .16s ease;}",
      ".tw-ov.tw-in{opacity:1;}",
      ".tw-dlg{background:#fff;color:#1b1c1c;width:100%;max-width:420px;border-radius:16px;padding:26px 24px 20px;",
      "box-shadow:0 24px 60px rgba(0,0,0,.30);text-align:center;transform:translateY(10px) scale(.97);transition:transform .16s ease;",
      "font:400 14px/1.55 'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}",
      ".tw-ov.tw-in .tw-dlg{transform:none;}",
      ".tw-dlg-ic{width:54px;height:54px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:25px;margin:0 auto 14px;}",
      ".tw-dlg--danger .tw-dlg-ic{background:rgba(200,16,46,.10);}",
      ".tw-dlg--warn .tw-dlg-ic{background:rgba(245,158,11,.14);}",
      ".tw-dlg-h{font-size:18px;font-weight:800;margin:0 0 7px;letter-spacing:-.01em;}",
      ".tw-dlg-m{color:#5c403f;margin:0;}",
      ".tw-dlg-m b{color:#1b1c1c;}",
      ".tw-dlg-d{color:#9e001f;font-weight:600;font-size:12.5px;margin:9px 0 0;}",
      ".tw-dlg-act{display:flex;gap:10px;margin-top:22px;}",
      ".tw-dlg-act button{flex:1;border-radius:10px;padding:11px 16px;font:700 14px system-ui;cursor:pointer;border:1px solid transparent;transition:background .12s,filter .12s;}",
      ".tw-dlg-no{background:#f1f0ef;color:#1b1c1c;border-color:rgba(27,28,28,.12);}",
      ".tw-dlg-no:hover{background:#e7e6e4;}",
      ".tw-dlg--danger .tw-dlg-go{background:#c8102e;color:#fff;}",
      ".tw-dlg--warn .tw-dlg-go{background:#b45309;color:#fff;}",
      ".tw-dlg-go:hover{filter:brightness(.93);}",
      ".tw-dlg-go:focus-visible,.tw-dlg-no:focus-visible{outline:2px solid #1b1c1c;outline-offset:2px;}",
      "@media (max-width:430px){.tw-dlg-act{flex-direction:column-reverse;}}",
    ].join("");
    document.head.appendChild(s);
  }

  function confirmDanger(opts) {
    opts = opts || {};
    const tone = opts.tone === "warn" ? "warn" : "danger";
    return new Promise((resolve) => {
      injectModalCss();
      const prevFocus = document.activeElement;
      const ov = document.createElement("div");
      ov.className = "tw-ov";
      ov.setAttribute("role", "dialog");
      ov.setAttribute("aria-modal", "true");
      ov.setAttribute("aria-labelledby", "tw-dlg-h");
      const dlg = document.createElement("div");
      dlg.className = "tw-dlg tw-dlg--" + tone;
      dlg.innerHTML =
        '<div class="tw-dlg-ic"></div>' +
        '<h2 class="tw-dlg-h" id="tw-dlg-h"></h2>' +
        '<p class="tw-dlg-m"></p>' +
        '<p class="tw-dlg-d" hidden></p>' +
        '<div class="tw-dlg-act"><button type="button" class="tw-dlg-no"></button>' +
        '<button type="button" class="tw-dlg-go"></button></div>';
      // textContent everywhere → no HTML injection from project names.
      dlg.querySelector(".tw-dlg-ic").textContent = opts.icon || (tone === "warn" ? "🗑" : "⚠️");
      dlg.querySelector(".tw-dlg-h").textContent = opts.title || "Are you sure?";
      const mEl = dlg.querySelector(".tw-dlg-m");
      // message may carry an emphasised name → support {name} highlight
      if (opts.name) {
        mEl.append(document.createTextNode((opts.before || "") + "“"));
        const b = document.createElement("b"); b.textContent = opts.name; mEl.append(b);
        mEl.append(document.createTextNode("”" + (opts.after || "")));
      } else {
        mEl.textContent = opts.message || "";
      }
      if (opts.detail) { const d = dlg.querySelector(".tw-dlg-d"); d.textContent = opts.detail; d.hidden = false; }
      const noBtn = dlg.querySelector(".tw-dlg-no");
      const goBtn = dlg.querySelector(".tw-dlg-go");
      noBtn.textContent = opts.cancelText || "Cancel";
      goBtn.textContent = opts.confirmText || "Delete";
      ov.appendChild(dlg);

      let settled = false;
      function close(val) {
        if (settled) return; settled = true;
        document.removeEventListener("keydown", onKey, true);
        ov.classList.remove("tw-in");
        setTimeout(() => { ov.remove(); try { prevFocus && prevFocus.focus && prevFocus.focus(); } catch {} }, 170);
        resolve(val);
      }
      function onKey(e) {
        if (e.key === "Escape") { e.preventDefault(); close(false); }
        else if (e.key === "Tab") {                       // trap focus between the 2 buttons
          const f = [noBtn, goBtn]; let i = f.indexOf(document.activeElement); if (i < 0) i = 0;
          e.preventDefault();
          f[(i + (e.shiftKey ? f.length - 1 : 1)) % f.length].focus();
        }
      }
      noBtn.addEventListener("click", () => close(false));
      goBtn.addEventListener("click", () => close(true));
      ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(false); });  // click backdrop = cancel
      document.addEventListener("keydown", onKey, true);
      document.body.appendChild(ov);
      requestAnimationFrame(() => { ov.classList.add("tw-in"); noBtn.focus(); });  // focus Cancel (safe default)
    });
  }

  // ─── Dates (business timezone) ────────────────────────────────────
  // Treadwell operates in the Kansas City metro, which is Central Time. Format
  // every project/server timestamp in this fixed business timezone — NOT the
  // viewer's local timezone — so Kyle & Troy in Kansas, and anyone testing from
  // elsewhere, all see the SAME date for a project (e.g. a job saved late on the
  // 30th UTC reads "6/30" for everyone, not "7/1" for a viewer in +UTC).
  const BIZ_TZ = "America/Chicago";
  function fmtBizDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d) ? "—" : d.toLocaleDateString("en-US", { timeZone: BIZ_TZ });
  }
  function fmtBizDateTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleString("en-US", { timeZone: BIZ_TZ, timeZoneName: "short" });
  }
  // "YYYY-MM" in the business timezone — matches the month fmtBizDate() shows, so
  // the Projects month filter buckets each job under the month on its card.
  function bizYM(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone: BIZ_TZ, year: "numeric", month: "2-digit" }).formatToParts(d);
    const y = (parts.find(p => p.type === "year") || {}).value;
    const m = (parts.find(p => p.type === "month") || {}).value;
    return (y && m) ? y + "-" + m : "";
  }
  // "2026-07" → "July 2026" (rendered in the business timezone; noon-UTC anchor
  // avoids any date rollover when shifting to Central).
  function bizMonthLabel(ym) {
    try { return new Date(ym + "-01T12:00:00Z").toLocaleString("en-US", { timeZone: BIZ_TZ, month: "long", year: "numeric" }); }
    catch { return ym; }
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
    confirmDanger,
    fmtBizDate,
    fmtBizDateTime,
    bizYM,
    bizMonthLabel,
    fmtUsd,
    absoluteUrl,
    resolveApiBase,
    getDraftId,
    initDraftSync,
  };
})();
