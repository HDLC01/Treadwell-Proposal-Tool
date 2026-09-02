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
  // Ownership stamp stored INSIDE the state blob so we can tell which draft it
  // belongs to. Without it, one global blob + a URL-keyed server save let a
  // stale (e.g. bfcache-restored) page write draft A's data under draft B's id.
  const STAMP = "__draft_id";
  const GUARD_WINDOW_MS = 15000;   // reload-loop guard: only blocks a re-hydrate of the SAME id within this window

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

  function writeBlob(obj) {
    try { localStorage.setItem(STATE_KEY, JSON.stringify(obj)); return true; }
    catch { return false; /* quota / private mode */ }
  }

  function setState(partial) {
    const id = getDraftId();
    const cur = getState();
    // Refuse a write when the blob belongs to a DIFFERENT draft than the page
    // is on (both truthy + differ). Stops a stale/bfcache-restored page from
    // clobbering another draft's state locally AND on the server.
    if (cur[STAMP] && id && cur[STAMP] !== id) {
      console.warn("[TW] refused state write: blob owned by draft", cur[STAMP], "but page is on", id);
      return cur;
    }
    const merged = Object.assign(cur, partial || {});
    if (id) merged[STAMP] = id;   // force-stamp AFTER the merge (partials can carry a stale stamp)
    writeBlob(merged);
    scheduleServerSave(merged);   // debounced push to the server draft
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

  // ── "the new project lands in the tab you started it from" ────────────────
  //
  // Projects records the intent when + New project is pressed; it is applied here, once, after
  // the project first reaches the server.
  //
  // WHY IT IS NOT JUST A FIELD IN THE SAVED BLOB. `is_test` is server-owned (see
  // _SERVER_OWNED_KEYS in backend/drafts.py). The browser PUTs the whole blob on every autosave,
  // so a tab that held its own copy of `is_test` would overwrite whatever somebody had since
  // chosen on the Projects card — file a project as real, leave yesterday's tab open, and its
  // next autosave silently files it back as a test. Keeping the flag off the blob and applying
  // it through /test-flag is what stops that.
  //
  // WHY IT IS BOUND TO AN ID. Unbound, the intent would attach to whatever project happened to
  // be saved next — press New project, change your mind, open a real customer bid, and that bid
  // gets filed as a test. So it is rewritten as "<id>:<0|1>" the moment an id exists, and only
  // ever applied to that id.
  const NEW_IS_TEST_KEY = "treadwell.proposal_tool.new_is_test";

  /** Called by Projects. `true`/`false` state a position; `null` says nothing (All, Inactive). */
  function setNewProjectTestIntent(want) {
    try {
      if (want === null || want === undefined) localStorage.removeItem(NEW_IS_TEST_KEY);
      else localStorage.setItem(NEW_IS_TEST_KEY, want ? "1" : "0");
    } catch {}
  }

  function bindNewProjectTestIntent(id) {
    try {
      const raw = localStorage.getItem(NEW_IS_TEST_KEY);
      if (raw === "1" || raw === "0") localStorage.setItem(NEW_IS_TEST_KEY, id + ":" + raw);
    } catch {}
  }

  /** An intent still waiting for its id — the user pressed New project and then went somewhere
   *  else. Dropped rather than left to land on an unrelated project. */
  function dropUnboundTestIntent() {
    try {
      const raw = localStorage.getItem(NEW_IS_TEST_KEY);
      if (raw === "1" || raw === "0") localStorage.removeItem(NEW_IS_TEST_KEY);
    } catch {}
  }

  function pendingTestIntentFor(id) {
    try {
      const raw = localStorage.getItem(NEW_IS_TEST_KEY) || "";
      const i = raw.lastIndexOf(":");
      if (i < 0 || raw.slice(0, i) !== id) return null;
      const v = raw.slice(i + 1);
      return v === "1" ? true : (v === "0" ? false : null);
    } catch { return null; }
  }

  function applyPendingTestIntent(id) {
    const want = pendingTestIntentFor(id);
    if (want === null) return;
    // Cleared before the call, win or lose. A retry that outlived the page would fight whatever
    // the estimator has since chosen on the card, and filing is one click to redo.
    try { localStorage.removeItem(NEW_IS_TEST_KEY); } catch {}
    try {
      // Same endpoint the Test? button on the Projects card uses. It is "/test" — an earlier
      // version of this guessed "/test-flag" from the handler's name and got a 405 on every
      // call, which the source tests could not see because they only checked the string was
      // there. Caught by creating a project on staging and reading the flag back.
      //
      // keepalive because the first save often coincides with leaving the page: intake submits
      // and navigates straight to Estimate Review, and a plain fetch is cancelled on unload —
      // the PUT above carries it for exactly the same reason.
      fetch(resolveApiBase() + "/api/draft/" + encodeURIComponent(id) + "/test", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ is_test: want }),
        keepalive: true,
      }).catch(() => {});
    } catch {}
  }

  // Keys the SERVER owns inside the blob (the mirror of _SERVER_OWNED_KEYS in backend/drafts.py).
  // Somebody else can change any of them from the CRM while this page holds an older copy.
  const SERVER_OWNED_KEYS = ["assigned_estimator", "is_test", "archived"];

  /** Re-read the server-owned keys for this draft and merge them into local state.
   *
   *  Hanz, 2026-08-13, on assigning an estimator from the CRM drawer: "that estimator picker
   *  should also reflect in the Section 4 of the estimate."
   *
   *  It did not, and the reason is subtle. The full hydrate only runs when the local blob belongs
   *  to a DIFFERENT draft — so assigning from the drawer and then opening the same project's Files
   *  screen on the same machine skipped it entirely and the picker read a copy of the state from
   *  before the assignment. The server value is authoritative for these keys by definition (that
   *  is what server-owned means), so re-reading them costs one small GET and can never lose work.
   *
   *  Narrow on purpose: it merges ONLY these keys, so it cannot stomp anything the estimator has
   *  typed on this page. Failure is silent — a blip must leave the page exactly as it was.
   *
   *  Resolves to the merged subset ({} when there was nothing to read). */
  async function refreshServerOwned() {
    const id = getDraftId();
    if (!id || isUnverified(id)) return {};
    try {
      const res = await fetch(resolveApiBase() + "/api/draft/" + encodeURIComponent(id),
                              { headers: authHeaders() });
      if (!res.ok) return {};
      const body = await res.json();
      const data = (body && body.data) || {};
      const patch = {};
      SERVER_OWNED_KEYS.forEach((k) => {
        if (Object.prototype.hasOwnProperty.call(data, k)) patch[k] = data[k];
      });
      // Compare before writing: an unconditional setState would mark the blob dirty on every
      // page load and schedule a PUT that changes nothing.
      const cur = getState();
      const moved = Object.keys(patch).filter((k) => cur[k] !== patch[k]);
      if (moved.length) setState(patch);
      return patch;
    } catch {
      return {};
    }
  }

  // The most recent server write, so flushState() can await it. A rejected promise is
  // never stored — callers get a boolean, never an unhandled rejection.
  let _inFlight = null;

  // One place that actually PUTs a blob to a draft id. Callers guarantee the
  // blob belongs to `id`; this never picks the id itself.
  //
  // RETURNS a promise resolving true on a stored write, false on anything else. It used to
  // return nothing, which is what made the publish race possible: /api/portal/publish
  // snapshots the SERVER's copy of the draft, and with no handle on the in-flight save
  // there was no way for the Done page to wait for its own edits to land. On 2026-08-12 a
  // resend of "Hanz Company 123" pinned revision 2 to a draft two minutes older than the
  // base-bid change the estimator had just made, so the portal showed Epoxy as the base
  // and the PDF (regenerated from the live draft) showed Room 1. Both were "right".
  function putDraft(id, blob) {
    try {
      const p = fetch(resolveApiBase() + "/api/draft/" + encodeURIComponent(id), {
        method: "PUT",
        headers: authHeaders(),
        body: JSON.stringify({ data: blob }),
        keepalive: true,         // let it finish even if the tab is closing
      }).then((res) => {
        // Only after the row exists: set_test_flag returns false on a missing draft, so filing
        // before the first save would be a silent no-op and the project would stay in Active.
        if (res && res.ok) applyPendingTestIntent(id);
        return !!(res && res.ok);
      }).catch(() => false /* offline / backend down — local copy still safe */);
      _inFlight = p;
      return p;
    } catch {
      return Promise.resolve(false);
    }
  }

  /** Why a server save would be REFUSED for this draft right now, or null when one would go
   *  through. Read-only: it writes nothing, schedules nothing, and changes nothing about what
   *  flushState does for the callers that gate on it.
   *
   *  IT EXISTS BECAUSE flushState CANNOT ANSWER THIS. flushState resolves TRUE when there was
   *  nothing to do, which is the honest answer for a page already in sync -- but it resolves true
   *  after DROPPING a pending save too: it clears the debounce timer, one of the three gates below
   *  refuses the PUT, and it then awaits `_inFlight`, which is a promise belonging to an older and
   *  possibly successful write. Anything that reports a save to the estimator has to be able to
   *  tell "already in sync" from "refused before it left the browser", and this is the only way to
   *  ask. Ctrl+S on the proposal editor asks it first, and says the honest thing when the answer is
   *  not null: the work is here, it is not there.
   *
   *  The three gates are scheduleServerSave's own, in its own order. Kept as a mirror rather than
   *  folded into it because the two have opposite jobs -- that one decides, this one only reports,
   *  and a reporter that could refuse a save would be a second place for the rule to drift.
   *
   *  Returns "no-draft", "unverified", "foreign-blob", or null. */
  function saveBlocked() {
    const id = getDraftId();
    if (!id) return "no-draft";
    if (isUnverified(id)) return "unverified";
    const stamp = getState()[STAMP];
    if (stamp && stamp !== id) return "foreign-blob";
    return null;
  }

  /** Wait until this draft's edits are on the server. Resolves true when the server holds
   *  what this page shows, false if the write failed or was refused.
   *
   *  Anything that makes the SERVER read the draft — publishing to the portal, generating
   *  files — must await this first. The debounce is 2.5s; a person who edits and clicks
   *  Send inside that window is the normal case, not an edge case.
   *
   *  Deliberately fires the pending save immediately rather than waiting out the timer:
   *  the point is to be finished, not to be patient. Returns true when there was nothing
   *  to do (no id, nothing dirty) — "the server is in sync" is the honest answer then. */
  async function flushState() {
    if (_saveTimer) {
      clearTimeout(_saveTimer); _saveTimer = null;
      const id = getDraftId();
      const blob = getState();
      // Same refusal rule as scheduleServerSave — never write a blob owned by another draft.
      if (id && !(blob[STAMP] && blob[STAMP] !== id) && !isUnverified(id)) {
        putDraft(id, blob);
      }
    }
    if (!_inFlight) return true;
    try { return await _inFlight; } catch { return false; }
  }

  // Before we evict a FOREIGN blob from localStorage (adopting a different
  // draft), flush it to ITS OWN stamped id so another draft's unsynced edits
  // aren't destroyed. Correctly keyed by construction (only ever its own stamp).
  function flushEvictedBlob(blob) {
    const owner = blob && blob[STAMP];
    if (!owner) return;
    if (Object.keys(blob).filter((k) => k !== STAMP).length === 0) return;  // empty → nothing to save
    if (_saveTimer) { clearTimeout(_saveTimer); _saveTimer = null; }         // its pending save is superseded
    putDraft(owner, blob);
  }

  let _saveTimer = null;
  function scheduleServerSave(state) {
    const id = getDraftId();
    if (!id) return;            // no id yet → nothing to sync
    if (isUnverified(id)) {     // never read this draft — do not write over it
      console.warn("[TW] refused server save: draft", id, "was adopted without being read");
      return;
    }
    // Gate at schedule time: never queue a save of a blob owned by another draft.
    if (state && state[STAMP] && state[STAMP] !== id) {
      console.warn("[TW] refused server save: state stamped", state[STAMP], "≠ draft", id);
      return;
    }
    if (_saveTimer) clearTimeout(_saveTimer);
    _saveTimer = setTimeout(() => {
      _saveTimer = null;
      // Re-check at FIRE time — a bfcache-resumed timer may fire after the URL/draft changed.
      const nowId = getDraftId();
      if (!nowId || nowId !== id || (state[STAMP] && state[STAMP] !== nowId)) {
        console.warn("[TW] skipped queued save — draft changed since it was scheduled");
        return;
      }
      putDraft(id, state);
    }, 2500);                    // debounce: save 2.5s after the last edit
  }

  // sessionStorage reload-guard, time-windowed so it only breaks reload LOOPS
  // (a re-hydrate of the SAME id within GUARD_WINDOW_MS) — it must NOT block a
  // legitimate re-hydration on later navigation (that was the multi-tab / return
  // bug). Value format: "<id>:<epoch-ms>". A legacy bare "<id>" blocks once.
  function guardBlocks(id) {
    try {
      const raw = sessionStorage.getItem(RELOAD_GUARD) || "";
      const i = raw.lastIndexOf(":");
      if (i < 0) return raw === id;
      return raw.slice(0, i) === id && (Date.now() - Number(raw.slice(i + 1))) < GUARD_WINDOW_MS;
    } catch { return false; }
  }
  function setGuard(id) { try { sessionStorage.setItem(RELOAD_GUARD, id + ":" + Date.now()); } catch {} }

  // ── "we have not actually read this project" ──────────────────────────────
  // Dropping the `!stamp && empty` ownership clause above fixed the common way a blank form
  // overwrote a live bid, but not the last one: if the hydrate GET fails twice we adopt a
  // stamped-empty blob, and from then on the stamp AGREES with the draft id, so every save
  // guard is satisfied and the first keystroke PUTs emptiness over the server copy.
  //
  // So an adopt that never saw the server is recorded, and server saves are refused while it
  // stands. The customer-facing trade is deliberate: edits made in that state are not pushed
  // (they survive locally), which is a smaller loss than replacing a bid nobody can recover.
  //
  // sessionStorage, because it has to survive the reload that adoptAndReload triggers. Cleared
  // the moment a read succeeds — including a 404, which is a real answer: the server genuinely
  // holds nothing for a draft nobody has saved yet, so empty is the truth rather than a guess.
  const UNVERIFIED = "treadwell.proposal_tool.unverified";
  function markUnverified(id) { try { sessionStorage.setItem(UNVERIFIED, id); } catch {} }
  function clearUnverified() { try { sessionStorage.removeItem(UNVERIFIED); } catch {} }
  function isUnverified(id) {
    try { return !!id && sessionStorage.getItem(UNVERIFIED) === id; } catch { return false; }
  }

  // Runs once on every page load, before the page's own init reads state.
  // Ownership is decided by the blob's STAMP (not by DRAFT_ID_KEY): if the URL's
  // ?d= draft doesn't own the local blob, hydrate it (fetch → clean-replace →
  // reload). This self-heals after corruption and covers cross-device opens.
  async function initDraftSync() {
    // The pull below hits the auth-gated /api/draft/{id}. Wait for the Supabase
    // token (set by auth.js) so the GET isn't 401'd — otherwise a reopened link
    // would start empty instead of hydrating.
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    let urlId = null;
    try { urlId = new URL(window.location.href).searchParams.get("d"); } catch {}
    const localId = (() => { try { return localStorage.getItem(DRAFT_ID_KEY); } catch { return null; } })();
    const blob = getState();
    const stamp = blob[STAMP] || null;
    const empty = Object.keys(blob).filter((k) => k !== STAMP).length === 0;

    if (!urlId) {
      const minting = !localId;                  // a genuinely new project, not a resumed one
      setDraftId(localId || newDraftId());
      // Bind now, while we know this id is the one + New project was pressed for.
      if (minting) bindNewProjectTestIntent(getDraftId());
      if (!stamp && !empty) { blob[STAMP] = getDraftId(); writeBlob(blob); }   // lazy-stamp legacy blob
      return;
    }

    // Arriving at an EXISTING project instead. Whatever the last + New project meant, it was
    // not this — drop it rather than let it file somebody's real bid as a test.
    dropUnboundTestIntent();

    // Does the local blob belong to this URL's draft?
    //
    // There used to be a third clause here: `|| (!stamp && empty)` — "fresh device /
    // just-cleared, nothing to protect". It read as harmless and it was the worst bug in this
    // file. It answers the wrong question. Nothing to protect LOCALLY is not the same as owning
    // the project, and claiming ownership is what SKIPS the hydrate below. So opening a real
    // project link on a machine with cleared storage rendered a blank form over a live bid, and
    // the first keystroke put that blank blob back over the server copy: setState stamps the
    // merged blob with the URL's id, so scheduleServerSave's mismatch guard sees a stamp that
    // agrees and lets the PUT through. Name, scope notes and square footage all replaced.
    // Reproduced on prod with a sentinel before this was changed.
    //
    // An empty blob is now exactly the case that MUST hydrate. The fetch below already handles
    // every outcome: 200 adopts the server copy, 404 (a draft nobody has saved yet) adopts
    // empty, and a failed read falls back to a stamped-empty floor. The only cost is one GET
    // and one reload on a genuinely clean slate, which is what the non-owned path has always
    // done for a cross-device open — and which is the point of the draft id being in the URL.
    // `&& !isUnverified` is what makes the block self-healing rather than permanent: a draft we
    // adopted blind is treated as not-ours, so the next load re-attempts the read. guardBlocks
    // keeps that from becoming a tight loop.
    const owned = (stamp === urlId
                || (!stamp && localId === urlId))  // migration: unstamped blob owned by DRAFT_ID_KEY
               && !isUnverified(urlId);
    if (owned) {
      setDraftId(urlId);
      if (!stamp && !empty) { blob[STAMP] = urlId; writeBlob(blob); }          // lazy-stamp
      return;
    }

    // Blob belongs to a DIFFERENT draft → must hydrate.
    if (guardBlocks(urlId)) {
      // Already hydrated+reloaded this id seconds ago and the stamp STILL
      // mismatches (storage writes failing, e.g. private mode). Don't loop:
      // drop a stamped-empty blob so we never render another draft as this one.
      flushEvictedBlob(blob);
      writeBlob({ [STAMP]: urlId });
      setDraftId(urlId);
      console.error("[TW] hydration loop stopped for draft", urlId, "— local storage may be unavailable");
      return;
    }

    flushEvictedBlob(blob);                        // save the OTHER draft's tail under its own id
    const adoptAndReload = (data) => {
      data[STAMP] = urlId;                         // force-stamp (server copy may carry a stale stamp)
      writeBlob(data);
      setDraftId(urlId);
      setGuard(urlId);
      window.location.reload();                    // re-run page init with the right state
    };
    const attempt = async () => {
      const res = await fetch(resolveApiBase() + "/api/draft/" + encodeURIComponent(urlId),
                              { headers: authHeaders() });
      if (res.ok) {
        const body = await res.json();
        clearUnverified();                                 // we have seen what the server holds
        return adoptAndReload((body && body.data) || {});
      }
      if (res.status === 404) {
        clearUnverified();                                 // a real answer: there is nothing to lose
        return adoptAndReload({});                         // brand-new / never-saved draft
      }
      throw new Error("HTTP " + res.status);
    };
    try { await attempt(); }
    catch {
      try { await attempt(); }                     // one silent retry for a transient blip
      catch {
        // Adopting blind. Mark it so no save can push this emptiness over whatever the server
        // is holding, and so the next load tries the read again.
        markUnverified(urlId);
        console.error("[TW] could not read draft", urlId,
                      "— editing locally, but saves are held back until it can be read");
        adoptAndReload({});
      }
    }
  }

  // Kick off sync as soon as the script loads. Expose the promise so pages that
  // auto-act on load (done.js files-mode) can await a settled draft first.
  let draftReady;
  try { draftReady = initDraftSync().catch(() => {}); }
  catch { draftReady = Promise.resolve(); }         // never block page render

  // Browser Back can restore a frozen (bfcache) page whose in-memory state
  // belongs to another draft; reload so initDraftSync re-validates ownership.
  window.addEventListener("pageshow", (e) => { if (e.persisted) window.location.reload(); });
  // Flush the pending debounced save on navigation so the last ≤2.5s of edits
  // aren't dropped (same refusal rule as scheduleServerSave).
  window.addEventListener("pagehide", () => {
    if (!_saveTimer) return;
    clearTimeout(_saveTimer); _saveTimer = null;
    const id = getDraftId();
    const blob = getState();
    if (!id || (blob[STAMP] && blob[STAMP] !== id)) return;
    putDraft(id, blob);
  });

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
      // Above EVERY other layer: the Customer Portal scrim/drawer (10000/10001 in
      // portal.html) and the notification panel (10001 in auth.js). At 10000 the
      // confirm rendered *behind* the drawer that opened it.
      ".tw-ov{position:fixed;inset:0;z-index:10100;display:flex;align-items:center;justify-content:center;padding:20px;",
      "background:rgba(20,18,18,.55);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);opacity:0;transition:opacity .16s ease;}",
      ".tw-ov.tw-in{opacity:1;}",
      ".tw-dlg{background:#fff;color:#1b1c1c;width:100%;max-width:420px;border-radius:16px;padding:26px 24px 20px;",
      "box-shadow:0 24px 60px rgba(0,0,0,.30);text-align:center;transform:translateY(10px) scale(.97);transition:transform .16s ease;",
      "font:400 14px/1.55 'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}",
      ".tw-ov.tw-in .tw-dlg{transform:none;}",
      ".tw-dlg-ic{width:54px;height:54px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:25px;margin:0 auto 14px;}",
      // Only reaches a dialog whose caller asked to hold the focus (opts.focus === "container").
      // The ring belongs on a control; on the modal wrapper it outlines the whole card.
      ".tw-dlg[tabindex]:focus{outline:none;}",
      ".tw-dlg--warn .tw-dlg-ic svg{color:#b45309;}",
      ".tw-dlg--danger .tw-dlg-ic svg{color:#c8102e;}",
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

  /** How many confirmDanger dialogs are on screen. Counted, not a boolean, because `close()`
   *  decrements and two overlapping dialogs would otherwise leave the flag down after the first
   *  one closed.
   *
   *  Exposed as TW.modalOpen() for callers that must not put a SECOND question on screen on top of
   *  one already being asked. The Items page needs it: a row's own Remove button opens a delete
   *  confirmation, and that dialog focusing its Cancel button fires a `focusout` on the row — which
   *  is that page's save trigger, so without this check it would stack a "save this change?" modal
   *  on top of the "remove this material?" one. */
  let openModals = 0;
  function modalOpen() { return openModals > 0; }

  /** The shared two-button modal. Resolves true for the confirm button, false for anything else.
   *
   *  THREE OPT-INS ADDED 2026-08-27, ALL DEFAULT-OFF. There are twenty-odd call sites for this
   *  helper and every one of them was written against the behaviour below, so the new options are
   *  read only where they are passed and the untouched path is byte-identical.
   *
   *    opts.focus === "container"  focus the DIALOG (tabindex="-1") instead of the Cancel button,
   *                                and do not hand the focus back on close.
   *    opts.dismiss === "explicit" no backdrop-mousedown-cancels listener.
   *    opts.iconSvg                inline SVG for the icon slot, as markup.
   *
   *  The first two exist because of a real defect on the Items page. `noBtn.focus()` BLURS
   *  whatever the estimator was typing in, a blurred input with an uncommitted value fires
   *  `change`, and on a page that saves on `change` that re-entered the very handler the dialog
   *  was asking about — so a Cancel could restore the screen while the rejected value went to the
   *  database. Focusing the dialog itself also means a stray SPACE cannot press a button nobody
   *  aimed at, and an inert backdrop means clicking the next cell cannot silently revert an edit
   *  somebody meant to make. Escape closes either way: an unclosable dialog is worse than both.
   *
   *  `iconSvg` is separate from `icon` on purpose. `icon` goes through textContent because the
   *  same dialog renders customer-typed project and vendor names, and there is no route by which
   *  one of those should ever be parsed as markup. `iconSvg` is only ever a literal written in
   *  our own source. */
  function confirmDanger(opts) {
    opts = opts || {};
    const tone = opts.tone === "warn" ? "warn" : "danger";
    // The caller manages the focus itself when it asks to hold it: see the Items page, where the
    // question is asked AFTER focus has left the row, so `prevFocus` is whatever the browser
    // parked on mid-transition and restoring it would yank the caret back out again.
    const holdFocus = opts.focus === "container";
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
      // Focusable only when the caller asked for it, or Tab would find a dialog wrapper that no
      // other caller expects in its tab order.
      if (holdFocus) dlg.setAttribute("tabindex", "-1");
      // textContent everywhere → no HTML injection from project names. The ONE exception is
      // iconSvg, which is markup out of our own source and never a value anybody typed.
      const icEl = dlg.querySelector(".tw-dlg-ic");
      if (opts.iconSvg) icEl.innerHTML = opts.iconSvg;
      else icEl.textContent = opts.icon || (tone === "warn" ? "🗑" : "⚠️");
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
      openModals += 1;
      function close(val) {
        if (settled) return; settled = true;
        openModals -= 1;
        document.removeEventListener("keydown", onKey, true);
        ov.classList.remove("tw-in");
        setTimeout(() => {
          ov.remove();
          if (holdFocus) return;
          try { prevFocus && prevFocus.focus && prevFocus.focus(); } catch {}
        }, 170);
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
      // Click backdrop = cancel, unless the caller wants the question answered on purpose. A
      // wrong click is a cheap "no" in front of a deletion and an expensive one in front of a
      // save the estimator meant to make.
      if (opts.dismiss !== "explicit") {
        ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(false); });
      }
      document.addEventListener("keydown", onKey, true);
      document.body.appendChild(ov);
      requestAnimationFrame(() => {
        ov.classList.add("tw-in");
        // Cancel is the safe default — EXCEPT where focusing a button is itself the hazard: it
        // makes SPACE an answer, and .focus() on anything blurs whatever the caller's page had
        // focused. onKey moves the focus onto a button the moment Tab is pressed either way.
        if (holdFocus) dlg.focus(); else noBtn.focus();
      });
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
    // Falsy in, empty out. `new Date(null)` is the epoch, not an invalid date, so the isNaN guard
    // below lets a null timestamp through as "1969-12" — which the board's period dropdown would
    // then offer as a real option. Never surfaced because every row that reaches it has a sent_at;
    // found by feeding the filter a row with no activity at all.
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone: BIZ_TZ, year: "numeric", month: "2-digit" }).formatToParts(d);
    const y = (parts.find(p => p.type === "year") || {}).value;
    const m = (parts.find(p => p.type === "month") || {}).value;
    return (y && m) ? y + "-" + m : "";
  }
  // Today's date in Central as "YYYY-MM-DD" — the form the server sends plain dates
  // in (a follow-up pause, a bid date). Comparing those as strings against this is
  // exact and needs no Date parsing; comparing against the VIEWER's today is what
  // makes a pause look expired to someone an hour east of Kansas.
  function bizToday() {
    return new Intl.DateTimeFormat("en-CA", { timeZone: BIZ_TZ, year: "numeric",
      month: "2-digit", day: "2-digit" }).format(new Date());
  }
  // A bare "YYYY-MM-DD" → "9/1/2026". Not fmtBizDate: that parses the string as UTC
  // midnight and then shifts it BACK into Central, so every date-only value would
  // render a day early. Anchoring at noon UTC leaves no room for the shift to cross
  // a day boundary in either direction.
  function fmtBizDay(d) {
    const s = String(d || "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return fmtBizDate(d);
    return new Date(s + "T12:00:00Z").toLocaleDateString("en-US", { timeZone: BIZ_TZ });
  }
  // "2026-07" → "July 2026" (rendered in the business timezone; noon-UTC anchor
  // avoids any date rollover when shifting to Central).
  function bizMonthLabel(ym) {
    try { return new Date(ym + "-01T12:00:00Z").toLocaleString("en-US", { timeZone: BIZ_TZ, month: "long", year: "numeric" }); }
    catch { return ym; }
  }

  // The MONDAY of the week a timestamp falls in, as "YYYY-MM-DD" in Central — the bucket key for
  // the board's week filter.
  //
  // Monday rather than Sunday because this board is read in a Monday sales meeting: "this week"
  // has to mean the week that meeting is in, not one that ended the day before.
  //
  // The date parts are read in CENTRAL, which is the half that matters: bucketing on the viewer's
  // clock puts a Friday-evening bid in Kansas into Saturday for anybody an hour east.
  //
  // The noon-UTC anchor is only defensive. Day arithmetic here happens in UTC, where there is no
  // DST, and the result is read straight back off the ISO string — so midnight would work equally
  // well today. Noon is kept so that formatting the anchor through a timezone later (the mistake
  // `fmtBizDay` documents) cannot silently shift it across a day boundary. A mutation to midnight
  // is therefore harmless, and this comment says so rather than claiming a guard that isn't there.
  function bizWeekStart(iso) {
    if (!iso) return "";                        // see bizYM: new Date(null) is the epoch, not NaN
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone: BIZ_TZ, year: "numeric",
      month: "2-digit", day: "2-digit", weekday: "short" }).formatToParts(d);
    const get = (t) => (parts.find((p) => p.type === t) || {}).value;
    const y = get("year"), m = get("month"), day = get("day"), wd = get("weekday");
    const back = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 }[wd];
    if (!y || !m || !day || back == null) return "";
    const anchor = new Date(y + "-" + m + "-" + day + "T12:00:00Z");
    anchor.setUTCDate(anchor.getUTCDate() - back);
    return anchor.toISOString().slice(0, 10);
  }

  // "2026-08-10" (a Monday) → "Aug 10–16", or "Aug 31–Sep 6" across a month boundary, with the
  // year appended only when it is not the current one. The end day is derived rather than stored,
  // so a week can never be labelled as a range it does not cover.
  function bizWeekLabel(startYmd) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(startYmd || ""))) return String(startYmd || "");
    const s = new Date(startYmd + "T12:00:00Z");
    const e = new Date(startYmd + "T12:00:00Z");
    e.setUTCDate(e.getUTCDate() + 6);
    const full = { timeZone: BIZ_TZ, month: "short", day: "numeric" };
    const sTxt = s.toLocaleDateString("en-US", full);
    const eTxt = e.toLocaleDateString("en-US", full);
    // Same month → drop the repeated month name from the end of the range.
    const sameMonth = sTxt.split(" ")[0] === eTxt.split(" ")[0];
    const tail = sameMonth ? eTxt.split(" ")[1] : eTxt;
    const sYear = startYmd.slice(0, 4);
    const eYear = e.toISOString().slice(0, 4);
    // A week that crosses new year gets BOTH years, short form. A single trailing year read as
    // "Dec 29–Jan 4, 2025" says January was in 2025, and that week is offered every January.
    if (sYear !== eYear) return sTxt + " '" + sYear.slice(2) + "–" + eTxt + " '" + eYear.slice(2);
    return sTxt + "–" + tail + (sYear !== bizToday().slice(0, 4) ? ", " + sYear : "");
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

  // Append the current draft id to an in-app path so navigation carries ?d=
  // (the wizard's Back/Continue + step links otherwise drop it and rely on
  // localStorage — the exact trust this bug shows is misplaced).
  function withDraft(path) {
    const id = getDraftId();
    if (!id) return path;
    return path + (path.indexOf("?") >= 0 ? "&" : "?") + "d=" + encodeURIComponent(id);
  }

  // Rewrite static wizard step-nav anchors to carry ?d=. Skips the "/" home and
  // "?new" (a fresh start must NOT inherit a draft id); leaves cross-origin and
  // non-wizard links alone.
  const _WIZARD_PATH = /^\/(estimate-review|proposal-review|done|dropbox|info-sheet)\.html$|^\/$/;
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("a[href]").forEach((a) => {
      try {
        const href = a.getAttribute("href");
        const u = new URL(href, location.origin);
        if (u.origin !== location.origin || !_WIZARD_PATH.test(u.pathname)) return;
        if (u.pathname === "/" && !u.searchParams.has("edit")) return;   // "/" home / "?new" → no ?d=
        if (!u.searchParams.has("d")) a.setAttribute("href", withDraft(href));
      } catch {}
    });
  });

  // ─── What a customer was quoted, and whether the document agrees ──
  /** The two halves of THIS project's pricing, read out of the draft the browser is holding.
   *
   *  A DELIBERATE MIRROR of `_publish_digest` in backend/main.py. That function decides what a
   *  customer was quoted, from the blob the publish route snapshots; this one reaches the same
   *  verdict from the same fields, in the same shape, BEFORE any request goes out. Same keys,
   *  same `show !== false` option rule, same base-only fallback, so the pre-send check and the
   *  post-send check can share one comparison and cannot disagree about what counts as drift.
   *
   *  IT READS `proposal_payload.rooms`, NOT `proposal_payload.values.rooms`. The first is what
   *  the document renderer prints; the second is an inert echo of the page state that travels
   *  alongside it. Reading the echo would report the pricing the estimator was LOOKING at
   *  instead of the pricing the customer's PDF prints, which is this bug wearing a disguise.
   *  backend/tests/test_publish_race.py pins the server side of the pair.
   *
   *  IT LIVES HERE, not on a page, because TWO pages need the same answer: the Files page gates
   *  the send on it, and the Proposal step tells an estimator who arrived from a blocked send
   *  what they are there to fix. A second copy on the second page is the same mistake as the
   *  two halves of the revision that made this bug. */
  function publishDigest(s) {
    const st = (s && typeof s === "object") ? s : {};
    const list = (v) => (Array.isArray(v) ? v : []);
    const baseOf = (rs) => rs.find(r => r && typeof r === "object" && r.is_base) || {};
    // Only the options a customer can actually pick. An option the estimator deliberately hid
    // reaches neither the portal nor the document, so counting it here would cry drift on a
    // correct send, and a warning that fires on correct sends is one nobody reads.
    const opts = (rs) => rs.filter(r => r && typeof r === "object"
                                     && !r.is_base && r.show !== false).length;
    const num = (v) => (typeof v === "number" && isFinite(v)) ? v : null;

    const rooms = list(st.rooms);
    const pp = (st.proposal_payload && typeof st.proposal_payload === "object")
      ? st.proposal_payload : {};
    const pv = (pp.values && typeof pp.values === "object") ? pp.values : null;
    const prooms = list(pp.rooms);
    const pbase = baseOf(prooms);
    // The base room's own total, falling back to the payload's mirror of the lump sum: a
    // base-only proposal carries no rooms at all (rooms exist only once there is an option).
    let docLump = num(pbase.bid && typeof pbase.bid === "object" ? pbase.bid.total : null);
    if (docLump == null) docLump = num(pv ? pv.proposal_lump_sum : null);

    return {
      base_label: baseOf(rooms).name || null,
      lump_sum: num(st.proposal_lump_sum),
      option_count: opts(rooms),
      // False on a project that has never been through the Proposal step. There is no document
      // to be stale, so every check downstream stays silent instead of blocking a first send.
      has_document: !!pv,
      doc_base_label: pbase.name || null,
      doc_lump_sum: docLump,
      doc_option_count: prooms.length ? opts(prooms) : (pv ? 0 : null),
    };
  }

  /** What the DOCUMENT half of a digest gets wrong, one row per difference, or [] when it
   *  agrees. `{ k: "Price", pdf: "$13,265", now: "$18,670", say: "a price of $13,265, not …" }`
   *  — the first three for the panel's three columns, `say` for the one-line warning, so the
   *  prose and the table can never quote different figures at each other.
   *
   *  ONE COMPARISON, THREE CALLERS: the pre-send gate (fed a digest of local state), the
   *  post-send warning (fed the server's own snapshot), and the panel that renders either.
   *  A second copy of these three rules is how the two checks would start disagreeing about
   *  whether a send is safe.
   *
   *  Silent on anything it cannot read. An absent doc figure is not evidence of drift, and
   *  every revision minted before this existed carries none of these keys. */
  function docDrift(d) {
    if (!d || typeof d !== "object" || !d.has_document) return [];
    // fmtUsd is a sibling in this file, so the old `window.TW && TW.fmtUsd` dance is gone
    // along with the hazard it guarded: a page-scoped copy of this code could reach for the
    // wrong `money` and throw at the exact moment somebody needed the warning.
    const usd = fmtUsd;
    const near = (a, b) => (a == null || b == null) ? a === b
      : Math.abs(Number(a) - Number(b)) < 0.01;   // sub-cent is the same money, not drift
    const rows = [];
    // Price first: it is the number a customer signs. BOTH figures have to be there — a page
    // that has somehow lost its own lump sum is not evidence that the document is wrong, and
    // refusing the send over it would put "not $—" on the estimator's screen.
    if (d.doc_lump_sum != null && d.lump_sum != null && !near(d.doc_lump_sum, d.lump_sum)) {
      const pdf = usd(d.doc_lump_sum), now = usd(d.lump_sum);
      rows.push({ k: "Price", pdf: pdf, now: now, say: "a price of " + pdf + ", not " + now });
    }
    // A base-only document has no base ROOM, so doc_base_label is null on the most common
    // shape this tool produces. Comparing that against a real name would warn on every one.
    if (d.doc_base_label && d.base_label && d.doc_base_label !== d.base_label) {
      rows.push({ k: "Base bid", pdf: d.doc_base_label, now: d.base_label,
                  say: d.doc_base_label + " as the base bid, not " + d.base_label });
    }
    if (typeof d.doc_option_count === "number" && typeof d.option_count === "number"
        && d.doc_option_count !== d.option_count) {
      const n = d.doc_option_count;
      rows.push({ k: "Options", pdf: String(n), now: String(d.option_count),
                  say: n + " option" + (n === 1 ? "" : "s") + ", not " + d.option_count });
    }
    return rows;
  }


  /** Keep a floating panel's REMEMBERED position on screen.
   *
   *  Two panels move and remember where they were put: the Pricing options rail on step 3 and the
   *  polish-intake cheat sheet. Both clamped the position while dragging and then restored it
   *  without clamping, which is only safe as long as the window never gets smaller. Drag either to
   *  the far side of a 2560px monitor, reopen the page on a laptop, and it is restored past the
   *  edge with its drag handle off screen -- nothing left to grab it by, and no way to bring it
   *  back short of clearing site data. Found on the cheat sheet, fixed in both: the second one was
   *  going to be found by whoever it happened to.
   *
   *  Same bounds the drags themselves use, so a restore cannot land somewhere a drag could not.
   *  Bounded by `innerHeight - 40` rather than the panel's height on purpose -- a long panel may
   *  hang off the bottom, provided its header stays reachable. */
  function clampPanelPos(left, top, width) {
    return {
      left: Math.max(4, Math.min(left, window.innerWidth - (width || 250) - 4)),
      top: Math.max(4, Math.min(top, window.innerHeight - 40)),
    };
  }

  // ─── Expose ───────────────────────────────────────────────────────
  window.TW = {
    clampPanelPos,
    getState,
    setState,
    flushState,
    saveBlocked,
    refreshServerOwned,
    clearState,
    readForm,
    writeForm,
    postJSON,
    authHeaders,
    confirmDanger,
    modalOpen,
    injectModalCss,
    fmtBizDate,
    fmtBizDateTime,
    bizYM,
    bizToday,
    fmtBizDay,
    bizMonthLabel,
    bizWeekStart,
    bizWeekLabel,
    fmtUsd,
    absoluteUrl,
    resolveApiBase,
    getDraftId,
    initDraftSync,
    setNewProjectTestIntent,
    withDraft,
    draftReady,
    publishDigest,
    docDrift,
  };
})();
