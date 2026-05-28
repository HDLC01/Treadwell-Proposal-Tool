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
  function getState() {
    try {
      const raw = sessionStorage.getItem(STATE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  function setState(partial) {
    const merged = Object.assign(getState(), partial || {});
    sessionStorage.setItem(STATE_KEY, JSON.stringify(merged));
    return merged;
  }

  function clearState() {
    sessionStorage.removeItem(STATE_KEY);
  }

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
  async function postJSON(path, body) {
    const res = await fetch(resolveApiBase() + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
    fmtUsd,
    absoluteUrl,
    resolveApiBase,
  };
})();
