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
  // Set by initDraftSync the moment it adopts the URL's draft and calls reload(). From then on this
  // page instance is a leftover: its module-top snapshots were read from the blob that was just
  // replaced (another project's, or none), and the reload will run the page again on the right one.
  // So every write from it is refused (setState / setLocalState below). Without that, anything this
  // page did after TW.draftReady resolved — the Files page's door pressing Continue was the first
  // to do it unattended — merged the OTHER project's snapshot into this one under this one's stamp,
  // which nothing else refuses, and the reload then found the result "owned" and saved it.
  let _reloadPending = false;
  // Set by dropHeldChanges when the Files page's door gives its copy back and leaves: this page's
  // writes were built on a copy the server no longer holds, and it has put this browser's copy back
  // to the last one the server did hold. A write landing after that (the cover letter's template
  // arriving while the page unloads) would undo it, so every write from here is refused too.
  let _givenUp = false;

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

  // What this page last wrote to the blob, exactly. localStorage is shared by every tab of this
  // browser, so when it no longer reads back as this, another tab has written since (dropHeldChanges).
  let _lastWrittenRaw = null;
  function writeBlob(obj) {
    try {
      const raw = JSON.stringify(obj);
      localStorage.setItem(STATE_KEY, raw);
      _lastWrittenRaw = raw;
      return true;
    }
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
    if (_reloadPending) {
      console.warn("[TW] refused state write: this page is reloading onto draft", id);
      return cur;
    }
    if (_givenUp) {
      console.warn("[TW] refused state write: this page gave its copy of draft", id, "back");
      return cur;
    }
    const merged = Object.assign(cur, partial || {});
    if (id) merged[STAMP] = id;   // force-stamp AFTER the merge (partials can carry a stale stamp)
    writeBlob(merged);
    scheduleServerSave(merged);   // debounced push to the server draft
    return merged;
  }

  /** setState for THIS BROWSER ONLY: the same merge and the same refusal, and NO server save.
   *
   *  For a fact the server has already recorded itself, which this page only needs to remember.
   *  A setState would PUT the page's whole blob to say it — and the blob can be older than the
   *  server's copy, because initDraftSync does not re-read a blob already stamped for this draft.
   *  That is how pressing Download on the Files page wrote a colleague's newer revision away: the
   *  press recorded `generate_result` with setState, and the PUT carried the page's stale proposal
   *  along with it. The next real edit on this page still PUTs everything, this included.
   *
   *  `opts.alreadyOnServer`: the server has stored this very change on its own copy (To Dropbox's
   *  record of the filing, main.py api_to_dropbox). A copy that was the one this browser last saw
   *  the server hold (SYNCED_KEY) is then still that copy, plus a change the server has too, so the
   *  record moves with it. Left behind, the record said the copy held something the server never
   *  got: opening another project PUT it back over a colleague's newer revision (flushEvictedBlob),
   *  and the Files page showed the "changed somewhere else" card for a change nobody made (review of
   *  fix 4, round 3). A copy that was already ahead of its record stays ahead. */
  function setLocalState(partial, opts) {
    const id = getDraftId();
    const cur = getState();
    if (cur[STAMP] && id && cur[STAMP] !== id) {
      console.warn("[TW] refused local state write: blob owned by draft", cur[STAMP], "but page is on", id);
      return cur;
    }
    if (_reloadPending || _givenUp) return cur; // a leftover page; see _reloadPending and _givenUp
    // Asked before the merge, which changes `cur` in place.
    const inSync = !!(opts && opts.alreadyOnServer) && !!id && syncedDigest(id) === draftDigest(cur);
    const merged = Object.assign(cur, partial || {});
    if (id) merged[STAMP] = id;
    if (writeBlob(merged) && inSync) markSynced(id, draftDigest(merged));
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
      // Compare before writing: an unconditional write would rewrite the blob on every page load.
      //
      // AND IN THIS BROWSER ONLY (setLocalState). These values came FROM the server, so there is
      // nothing to send it, and a setState would PUT this page's WHOLE copy to say it — a copy
      // that can be older than the server's (see readServerDraft). Review of fix 4, round 2: a
      // Files page left open while RJ revised the project and Troy reassigned it to him put
      // Kyle's $10,000 copy back over RJ's revision the moment the estimator picker re-read the
      // assignment, because the assignment had "moved".
      const cur = getState();
      const moved = Object.keys(patch).filter((k) => cur[k] !== patch[k]);
      if (moved.length) setLocalState(patch);
      return patch;
    } catch {
      return {};
    }
  }

  // ─── Is this browser's copy the one the server holds? ─────────────
  // initDraftSync keeps a blob already stamped for the URL's draft WITHOUT re-reading the server,
  // so this browser's copy can be older than the server's (a colleague revised the project on
  // another machine, Troy marked it Won) — or newer (a save of this browser's edits is still in
  // flight, or failed). Anything that builds from the local copy and then PUTs the whole blob has
  // to know which, and the Files page's door does both. So every time the two are known to be
  // equal — a hydrate read the server, a PUT was stored — this browser remembers a digest of that
  // copy (SYNCED_KEY). A local copy whose digest is still that one has nothing the server lacks;
  // one whose digest has moved on holds changes the server has not confirmed.

  /** A canonical string of a JSON value: keys sorted, so the order a merge happened to leave them
   *  in cannot move a hash. */
  function canonJSON(v) {
    if (Array.isArray(v)) return "[" + v.map(canonJSON).join(",") + "]";
    if (v && typeof v === "object") {
      return "{" + Object.keys(v).sort()
        .map((k) => JSON.stringify(k) + ":" + canonJSON(v[k])).join(",") + "}";
    }
    return JSON.stringify(v);
  }

  /** cyrb53: 53 bits, so two different drafts sharing a hash is not a practical concern here. */
  function hash53(s) {
    let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < s.length; i++) {
      const c = s.charCodeAt(i);
      h1 = Math.imul(h1 ^ c, 2654435761);
      h2 = Math.imul(h2 ^ c, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
  }

  /** Keys the two copies may disagree on without either being out of date: the ownership stamp,
   *  the server-owned keys (a browser's save cannot change them — /api/draft/{id} keeps the
   *  server's own values on every save, drafts.save_draft `keep_server_owned` — and the page
   *  re-reads them), and the Files page's own record of its last build, which it keeps with
   *  setLocalState while /api/draft/{id}/documents records its own on the server. */
  const DIGEST_IGNORED = [STAMP, "generate_result", "generated_lump_sum"].concat(SERVER_OWNED_KEYS);

  /** A digest of a draft blob: everything but DIGEST_IGNORED, off a JSON round trip, so an object
   *  in memory and the same object read back from localStorage or the server give one answer. */
  function draftDigest(blob) {
    let plain;
    try { plain = JSON.parse(JSON.stringify(blob || {})); } catch { return ""; }
    if (!plain || typeof plain !== "object" || Array.isArray(plain)) return "";
    const keep = {};
    Object.keys(plain).forEach((k) => { if (DIGEST_IGNORED.indexOf(k) < 0) keep[k] = plain[k]; });
    return hash53(canonJSON(keep));
  }

  const SYNCED_KEY = "treadwell.proposal_tool.synced";
  function markSynced(id, digest) {
    if (!id || !digest) return;
    try { localStorage.setItem(SYNCED_KEY, id + ":" + digest); } catch {}
  }
  /** The digest of this draft as last seen equal to the server's, or null when this browser has
   *  never seen it so (a copy written before the marker existed, or another draft's marker). */
  function syncedDigest(id) {
    try {
      const raw = localStorage.getItem(SYNCED_KEY) || "";
      const i = raw.lastIndexOf(":");
      return (i > 0 && raw.slice(0, i) === id) ? raw.slice(i + 1) : null;
    } catch { return null; }
  }

  /** The SERVER's copy of this page's draft, as `{data, version}`, or null when it cannot be read
   *  (no id, a draft this session adopted blind, not found, offline). `version` is the time the
   *  server last stored a save of it ("" when the row has none): Send hands it back, so the
   *  publish can refuse a draft saved again after this read. Reads only: nothing is written. */
  async function readServerRow() {
    const id = getDraftId();
    if (!id || isUnverified(id)) return null;
    try {
      const res = await fetch(resolveApiBase() + "/api/draft/" + encodeURIComponent(id),
                              { headers: authHeaders() });
      if (!res.ok) return null;
      const body = await res.json();
      const data = body && body.data;
      if (!(data && typeof data === "object" && !Array.isArray(data))) return null;
      return { data, version: (body && typeof body.updated_at === "string") ? body.updated_at : "" };
    } catch {
      return null;
    }
  }

  /** The SERVER's copy of this page's draft (readServerRow's `data`), or null. */
  async function readServerDraft() {
    const row = await readServerRow();
    return row ? row.data : null;
  }

  /** Bring this browser's copy of the draft in line with the server's, when that loses nothing.
   *
   *  Resolves `{status, server}`, `server` being the server's copy (null when it was not read):
   *    "same"        the two agree (DIGEST_IGNORED aside). Nothing is written.
   *    "adopted"     they did not, and this browser's copy held nothing the server lacks: it is
   *                  the copy last seen on the server. So the SERVER's copy is the newer one, and
   *                  it now replaces this browser's — which is what stops an older copy being
   *                  built from and put back over it. A page holding a module-top snapshot must
   *                  reload to see it.
   *    "unknown"     they did not, and this browser has no record of seeing this draft on the
   *                  server (a copy written before the record existed — every browser's on deploy
   *                  day). Nothing can tell an older copy from one holding a save that never
   *                  landed, so neither side is dropped or written: left exactly as it is, like
   *                  "kept". It used to be "adopted", which put the server's copy over an unsaved
   *                  edit with nothing on screen (review of fix 4, round 3). The estimator picks:
   *                  the saved copy (useServerCopy) or this browser's (keepLocalCopy).
   *    "ahead"       they did not, and it is the SERVER's copy that is the one last seen there:
   *                  nobody has saved it since. So this browser's copy is that copy plus changes
   *                  whose save never landed (it failed, or went as the page closed and was too
   *                  large or too late). Building from it and saving it loses nothing of anyone's.
   *                  Left as it is.
   *    "kept"        they did not, and BOTH have moved since this browser last saw the server:
   *                  this copy has changes the server never confirmed, and someone has saved the
   *                  server's since. Or this copy could not be replaced. Left exactly as it is,
   *                  and nothing may build from it or save it unattended: a save would put it
   *                  over a colleague's work, and dropping it could drop this estimator's.
   *    "unreachable" the server could not be read. Nothing is known and nothing is changed.
   *  This page's own pending save is flushed first, so a "kept" is never merely that. */
  async function reconcileWithServer() {
    const id = getDraftId();
    if (!id || _reloadPending) return { status: "unreachable", server: null };
    await flushState();
    const server = await readServerDraft();
    if (!server) return { status: "unreachable", server: null };
    const local = getState();
    const mine = draftDigest(local);
    const theirs = draftDigest(server);
    if (mine === theirs) { markSynced(id, mine); return { status: "same", server }; }
    const last = syncedDigest(id);
    if (local[STAMP] && local[STAMP] !== id) return { status: "kept", server };
    if (last === null) return { status: "unknown", server };
    if (last !== mine) return { status: last === theirs ? "ahead" : "kept", server };
    if (!writeBlob(Object.assign({}, server, { [STAMP]: id }))) return { status: "kept", server };
    markSynced(id, theirs);
    return { status: "adopted", server };
  }

  /** Is this browser's copy of the draft the same as `server`, the server's copy just read
   *  (DIGEST_IGNORED aside)? When it is, that is recorded (SYNCED_KEY) as a stored save records it.
   *  A save sent as the page closed (pagehide's keepalive) is stored with nobody left to record it,
   *  so the record lags a step behind until the two are next read equal — which is here, or in
   *  reconcileWithServer. Writes nothing else. */
  function matchesServer(server) {
    const id = getDraftId();
    if (!id || !server) return false;
    const mine = draftDigest(getState());
    if (mine !== draftDigest(server)) return false;
    markSynced(id, mine);
    return true;
  }

  /** The server's copy in place of this browser's, on the estimator's say-so: the way out of a
   *  "kept" copy, where nothing here can tell whose changes should win.
   *  Nothing is flushed first — this page's queued save is the very copy being given up, so it is
   *  dropped unsent. Resolves true when the server's copy now stands in this browser (the page
   *  must reload to show it), false when it could not be read or written. */
  async function useServerCopy() {
    const id = getDraftId();
    if (!id || _reloadPending) return false;
    cancelPendingSave();
    const server = await readServerDraft();
    if (!server) return false;
    const cur = getState();
    if (cur[STAMP] && cur[STAMP] !== id) await flushEvictedBlob(cur);   // another tab's project: its own id
    if (!writeBlob(Object.assign({}, server, { [STAMP]: id }))) return false;
    markSynced(id, draftDigest(server));
    return true;
  }

  /** The other way out of an "unknown" copy, on the estimator's say-so: THIS browser's copy goes on,
   *  over the server's. It records the server's copy, read now, as the one this browser last saw
   *  there, so the Files page reads this browser's copy as "ahead" of it, and the door builds it and
   *  saves it. The door still asks the server again as it saves: a save landing in between sends it
   *  back to the Files page, which then stops on the "changed somewhere else" card.
   *
   *  Review of fix 4, round 4: on deploy day no browser has a record yet, so an edit whose save went
   *  out as a page closed (a keepalive, refused above 64 KB) reached the "doesn't match" card, and
   *  that card's one button put the server's copy over it. With a record the same edit is built and
   *  saved. Writes nothing to the draft; resolves true when the record is written, false when the
   *  server's copy could not be read or this browser's copy is another project's. */
  async function keepLocalCopy() {
    const id = getDraftId();
    if (!id || _reloadPending || _givenUp) return false;
    const cur = getState();
    if (!cur[STAMP] || cur[STAMP] !== id) return false;
    const server = await readServerDraft();
    if (!server) return false;
    const theirs = draftDigest(server);
    if (!theirs) return false;
    markSynced(id, theirs);
    return true;
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
  function putDraft(id, blob, keepalive = false) {
    try {
      // Taken as the body is, before anything can change the blob, so a stored write records
      // exactly the copy the server now holds (see SYNCED_KEY).
      const sent = draftDigest(blob);
      const p = fetch(resolveApiBase() + "/api/draft/" + encodeURIComponent(id), {
        method: "PUT",
        headers: authHeaders(),
        body: JSON.stringify({ data: blob }),
        // Chromium caps a keepalive request body at ~64KiB combined per origin — a
        // large draft (Gerson Company measured ~89KB) blows that cap and fails
        // SYNCHRONOUSLY with "TypeError: Failed to fetch", swallowed below with no
        // visible error. keepalive is only for a save racing page teardown
        // (pagehide); the routine in-tab autosave must NOT set it.
        keepalive: keepalive,
      }).then(async (res) => {
        // /api/draft/{id} answers a caught server-side exception with HTTP 200 and
        // {"ok": false, "error": ...} — main.py:api_save_draft's own except branch. res.ok only
        // sees the HTTP status, so that shape read as a success here while polish-sandbox.js's
        // saveThenFileAsTest (the one other PUT to this route) already checked the body. Same
        // check now applies to every autosave, not just the sandbox's one-off file-as-test call.
        const body = res && res.ok
          ? await res.json().catch(() => null)
          : null;
        const ok = !!(res && res.ok) && !(body && body.ok === false);
        // Only after the row exists: set_test_flag returns false on a missing draft, so filing
        // before the first save would be a silent no-op and the project would stay in Active.
        if (ok) applyPendingTestIntent(id);
        // Only for the draft this page is on: an evicted blob flushed to its own id must not
        // overwrite the marker of the draft being adopted in its place.
        //
        // AND ONLY WHILE THIS BROWSER'S COPY IS STILL THAT DRAFT'S. The record describes the one
        // copy localStorage holds, and every tab shares it. Review of fix 4, round 3: tab B's
        // queued save for project Y landed after tab A had opened X, and marked Y — tab B's URL
        // still said Y — so X's record was gone, and the Files page then put the server's copy of
        // X over an edit of Kyle's that had not saved.
        if (ok && id === getDraftId() && getState()[STAMP] === id) markSynced(id, sent);
        return ok;
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

  /** The same three refusals, in the estimator's own words, with the way out of each.
   *
   *  THIS IS THE OTHER HALF OF RJ'S LOOP. The Files page found a document holding the old
   *  numbers, refused the send, and sent him back here to press Continue -- which is the right
   *  instruction, and it was the only instruction. Continue rebuilds the payload and calls
   *  setState, setState REFUSES a write it cannot own and hands back the unchanged blob, and the
   *  caller navigated on regardless. So the document never got rebuilt, the Files page found the
   *  same drift, and around he went. Deterministic, and with no exit: he reported doing exactly
   *  what the screen told him, repeatedly, and getting the same message back.
   *
   *  Both ends now ask BEFORE they act -- Continue before it writes, the send gate before it
   *  blames the document -- and both say this, because a message that differs between the two
   *  pages is how they would start describing the same refusal two ways. Returns null when a
   *  save would go through, so a truthy answer always means STOP and say so.
   *
   *  `say` states the situation. `fix` is the one thing to do about it, and it is never "press
   *  Continue again": that is the loop. */
  function saveBlockedSay() {
    const reason = saveBlocked();
    if (!reason) return null;
    if (reason === "foreign-blob") {
      return { reason,
        say: "This project is open in another tab, and that tab has the keys.",
        fix: "Close the other tab (or reload this page), then come back to this step." };
    }
    if (reason === "no-draft") {
      return { reason,
        say: "This page has lost track of which project it is on, so nothing can be saved.",
        fix: "Open the project again from the Projects page." };
    }
    // "unverified" -- set by markUnverified when a hydrate could not be trusted, so every
    // server write for this draft is refused for the rest of the session.
    return { reason,
      say: "Your changes are not reaching the server, so the document cannot be rebuilt.",
      fix: "Reload this page. If it says this again, tell Hanz before you send anything." };
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
    if (_hold) return flushHeld(_hold);
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

  /** Drop this page's queued server save, unsent. This browser's copy keeps the write; the server
   *  is not sent it, now or as the page closes (pagehide sends only a queued save). For a page
   *  giving its copy up for the server's (useServerCopy). The next edit queues a save again — a
   *  page that must not save until the server says so holds its saves instead (holdServerSaves). */
  function cancelPendingSave() {
    if (_saveTimer) { clearTimeout(_saveTimer); _saveTimer = null; }
  }

  // ─── A page whose saves wait for the server's say-so ─────────────
  // The Files page's door opens the Proposal step to build the document with nobody watching, and
  // that page saves its whole copy as it loads (its pricing rebuild), whenever something on it
  // writes (the cover letter's editor, as its template arrives), and at Continue. Asking the
  // server once, as the page opened, left all of those free to land later over a colleague's
  // revision saved in between (review of fix 4, round 2: RJ's $15,480 Continue landing while the
  // template loaded was put back to Kyle's $10,000 copy, which the next Send then froze).
  //
  // So on that page every save is held: asked for, it is only remembered — no timer, so nothing
  // goes on its own or as the page closes (pagehide sends only a queued save). flushState, which
  // Continue and Ctrl+S call, asks the hold's `gate` at that very moment, and only a yes sends the
  // page's copy; a no keeps it held and resolves false.
  //
  // FOR AS LONG AS THE PAGE IS UNATTENDED, a stored save does not lift the hold (review of fix 4,
  // round 3). It used to: Kyle ticked the cover letter while the page said "Updating the
  // proposal…", that save went through the gate and lifted it, RJ's Continue landed, and the
  // door's own Continue then saved Kyle's $10,000 copy over RJ's with nothing asked. Instead the
  // door's question also accepts the page's own last stored save (heldSaveDigest), so that save is
  // never taken for a colleague's. Once the door has stopped and says so, the page is the estimator's:
  // releaseHeldSaves asks once more, sends what is held on a yes, and lifts the hold.
  let _hold = null;
  let _watchingTouches = false;

  /** Hold this page's server saves behind `gate`, an async () => boolean asked just before each
   *  one is sent. A save already queued is held with the rest, unsent. */
  function holdServerSaves(gate) {
    _hold = { gate, dirty: !!_saveTimer || !!(_hold && _hold.dirty), handedOver: false,
              saved: null, touches: 0 };
    if (_saveTimer) { clearTimeout(_saveTimer); _saveTimer = null; }
    watchTouches();
  }

  /** Count what the estimator does on a held page that could have changed something. Only real
   *  input counts (isTrusted): the page's own writes as it loads are not the estimator's, and
   *  dropHeldChanges may give those back, never these. Generous where it cannot tell — a key that
   *  can type, delete, indent, undo or format; a click on a control (the ribbon, a box's buttons, a
   *  tick); a drag (a box moved or resized); anything the page reports as input or a change — so
   *  an edit is never dropped unseen. NOT a key or a click that cannot edit anything: Escape, an
   *  arrow, a modifier on its own, a click that only puts the caret somewhere or lands on the page
   *  itself. Those used to count, so a click while the page said "Updating the proposal…" kept the
   *  door's own writes, the Files page said this browser had changes that never reached the server,
   *  and opening another project PUT them over the colleague's revision (review of fix 4, round 4).
   *  The keystroke rule is the Proposal step's own (proposal-review.js undoUnitForKey): what it
   *  keeps an undo step for, plus Ctrl+Z and Ctrl+Y. */
  let _pointerDown = null;
  function mayEdit(e) {
    if (e.type === "pointerdown") {
      _pointerDown = { x: e.clientX, y: e.clientY };
      return false;
    }
    if (e.type === "keydown") {
      const k = String(e.key || "");
      if (e.ctrlKey || e.metaKey) return /^[biuvxyz]$/i.test(k);
      if (e.altKey) return false;
      return k === "Enter" || k === "Tab" || k === "Backspace" || k === "Delete" || k.length === 1;
    }
    if (e.type === "pointerup") {
      const down = _pointerDown;
      _pointerDown = null;
      const t = e.target;
      // A disabled one does nothing: the door's own "Updating the proposal…" button is the one an
      // impatient estimator clicks.
      const c = (t && typeof t.closest === "function") ? t.closest(
        "button, a, input, select, textarea, label, summary, [role='button'], [role='checkbox'], "
        + "[role='switch'], [role='menuitem'], [role='option'], [role='tab']") : null;
      const onControl = !!c && !c.disabled;
      const dragged = !!down && typeof e.clientX === "number" && typeof down.x === "number"
        && (Math.abs(e.clientX - down.x) > 3 || Math.abs(e.clientY - down.y) > 3);
      return onControl || dragged;
    }
    return true;                                   // input, change, paste, cut, drop
  }
  function watchTouches() {
    if (_watchingTouches) return;
    _watchingTouches = true;
    const note = (e) => { if (_hold && e && e.isTrusted && mayEdit(e)) _hold.touches++; };
    try {
      ["keydown", "input", "change", "paste", "cut", "drop", "pointerdown", "pointerup"]
        .forEach((t) => document.addEventListener(t, note, true));
    } catch {}
  }

  function liftHold(hold) {
    if (_hold !== hold) return;
    _hold = null;
    if (hold.dirty) scheduleServerSave(getState());       // an edit made while it was being asked
  }

  async function flushHeld(hold) {
    if (!hold.dirty) {
      if (!_inFlight) return true;
      try { return await _inFlight; } catch { return false; }
    }
    let yes = false;
    try { yes = !!(await hold.gate()); } catch { yes = false; }
    if (!yes || _hold !== hold) return false;
    const id = getDraftId();
    const blob = getState();
    // Same refusal rule as scheduleServerSave — never write a blob owned by another draft.
    if (!id || (blob[STAMP] && blob[STAMP] !== id) || isUnverified(id)) return false;
    const touches = hold.touches;          // what the estimator had done when the copy was read
    hold.dirty = false;                    // an edit made while this is in flight sets it again
    if (!await putDraft(id, blob)) { hold.dirty = true; return false; }
    hold.saved = { raw: JSON.stringify(blob), digest: draftDigest(blob), touches };
    if (hold.handedOver) liftHold(hold);  // the door has stopped: the server has now said yes
    return true;
  }

  /** The digest of the copy this page last stored through its hold, or null. The server holding
   *  it means nobody has saved since this page did. */
  function heldSaveDigest() {
    return (_hold && _hold.saved) ? _hold.saved.digest : null;
  }

  /** The door has stopped and says why, so the page is the estimator's from here. Asks the gate
   *  once more; on a yes, sends what is held and lifts the hold, and the page saves as every page
   *  does — its autosave, its pagehide save, and a Continue that is not asked again. It used to
   *  hold for the page's whole life with nothing on screen to say so, and the first Continue after
   *  any server-side change, even Troy marking the job Won, went back to a Files card whose one
   *  button dropped everything typed (review of fix 4, round 3). Resolves true when the hold is
   *  lifted; false leaves it held (the server could not be read, or the save failed — the gate has
   *  already sent the page back if the server holds another copy), and then the first save the
   *  gate does let through lifts it. */
  async function releaseHeldSaves() {
    const hold = _hold;
    if (!hold) return true;
    hold.handedOver = true;
    if (hold.dirty) return (await flushHeld(hold)) && _hold !== hold;
    let yes = false;
    try { yes = !!(await hold.gate()); } catch { yes = false; }
    if (!yes || _hold !== hold) return false;
    liftHold(hold);
    return true;
  }

  /** The door gives up: this browser's copy goes back to the last one the server held on this
   *  page's watch — its own last stored save, else the copy it loaded — and what the page wrote
   *  since and never sent is dropped.
   *
   *  Those writes were the page's own, built on a copy the server no longer holds: its pricing
   *  rebuild as it loaded, the cover letter's template version, the document the automatic
   *  Continue composed. Left in place they read as changes the server never got. The Files page
   *  then showed the "changed somewhere else" card for changes nobody made, and opening another
   *  project PUT them over the colleague's revision that had sent the door back (review of fix 4,
   *  round 3).
   *
   *  NOT when anything here was the estimator's, or might have been: after any real input since
   *  that copy (watchTouches), or when another tab of this browser has been at the copy since —
   *  saved it (the record of what the server holds has moved off this page's), or written it after
   *  this page last did. localStorage is every tab's, and what another tab typed is in it. Then the
   *  copy is left as it is, and the Files page asks. Nor once the hold is lifted, when the page
   *  saves as any page does. Keeps the hold, and refuses every later write from this page
   *  (_givenUp). Returns true when this browser's copy was put back. */
  function dropHeldChanges() {
    const hold = _hold;
    if (!hold || _reloadPending) return false;
    const base = hold.saved || { raw: _bootRaw, touches: 0 };
    if (hold.touches > base.touches) return false;
    const id = getDraftId();
    if (!id || syncedDigest(id) !== (hold.saved ? hold.saved.digest : _bootSynced)) return false;
    let back = null;
    try { back = JSON.parse(base.raw || "null"); } catch { back = null; }
    if (!back || typeof back !== "object" || Array.isArray(back)) return false;
    let now = null;
    try { now = localStorage.getItem(STATE_KEY); } catch { return false; }
    if (now !== (_lastWrittenRaw !== null ? _lastWrittenRaw : _bootRaw)) return false;
    const cur = getState();
    if ((cur[STAMP] && cur[STAMP] !== id) || (back[STAMP] && back[STAMP] !== id)) return false;
    if (!writeBlob(Object.assign(back, { [STAMP]: id }))) return false;
    hold.dirty = false;
    _givenUp = true;
    return true;
  }

  // Before we evict a FOREIGN blob from localStorage (adopting a different
  // draft), flush it to ITS OWN stamped id so another draft's unsynced edits
  // aren't destroyed. Correctly keyed by construction (only ever its own stamp).
  //
  // ONLY WHEN IT HOLDS SOMETHING THE SERVER WAS NEVER CONFIRMED TO HAVE. A blob whose digest is
  // still the one this browser last saw the server store for that draft (SYNCED_KEY) has nothing
  // to save — and PUTting it anyway puts yesterday's copy back over whatever has been saved there
  // since. Review of fix 4, round 2: Kyle's browser still held project X from yesterday, in sync
  // then; RJ re-priced X to $15,000 and Troy marked it Won; Kyle opened another project, and the
  // eviction put his $10,000 copy back over both.
  //
  // AND ONLY OVER A SERVER COPY NOBODY HAS SAVED SINCE THIS BROWSER LAST SAW IT, asked of the server
  // first (reconcileWithServer's "ahead"). A blob with changes the server never confirmed may be the
  // tail of a save that never landed — a large draft's pagehide keepalive fails outright — and this
  // is its last chance, so it is saved when that loses nothing of anyone's: the server still holds
  // the copy last seen there, or has no row for it at all. It used to be saved whatever the server
  // held (review of fix 4, round 4): Kyle's deploy-day copy of X, with no record, went back over
  // RJ's $15,000 revision and Troy's Won, and RJ's browser, whose copy was in step with its record,
  // then took the server's copy in place of his own (reconcileWithServer's "adopted") — so the
  // revision was gone from the server and from every browser. A blob whose server copy has moved
  // on since ("kept"), or that has no record to tell ("unknown"), or whose server copy cannot be
  // read, is not sent: in a real conflict the saved copy stands, as the Files page's own card has it.
  async function flushEvictedBlob(blob) {
    const owner = blob && blob[STAMP];
    if (!owner) return;
    if (Object.keys(blob).filter((k) => k !== STAMP).length === 0) return;  // empty → nothing to save
    if (_saveTimer) { clearTimeout(_saveTimer); _saveTimer = null; }         // its pending save is superseded
    const mine = draftDigest(blob);
    const last = syncedDigest(owner);
    if (last === mine) return;                                               // the server has all of it
    let theirs = null;
    try {
      const res = await fetch(resolveApiBase() + "/api/draft/" + encodeURIComponent(owner),
                              { headers: authHeaders() });
      if (res.status === 404) { await putDraft(owner, blob); return; }       // no row: nothing to lose
      if (!res.ok) return;
      const body = await res.json();
      const data = body && body.data;
      if (!(data && typeof data === "object" && !Array.isArray(data))) return;
      theirs = draftDigest(data);
    } catch { return; }
    if (theirs === mine) return;                                             // the server has all of it
    if (last !== null && last === theirs) { await putDraft(owner, blob); return; }   // "ahead"
    console.warn("[TW] left an evicted copy of draft", owner, "unsaved: the saved copy has changed "
                 + "since this browser last saw it, or this browser has no record of seeing it");
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
    if (_hold) { _hold.dirty = true; return; }   // waits for the gate (holdServerSaves)
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
      // Already hydrated+reloaded this id seconds ago and the stamp STILL mismatches: storage
      // writes are failing (private mode), or another tab took the one slot in between — two tabs
      // opening two projects at once (a restored session, two pasted links). Don't loop.
      //
      // AND LEAVE THE SLOT AS FOUND: this page reads another draft's blob, so every write from it is
      // refused (setState's stamp check), as for any tab whose project another tab has since taken,
      // and Continue says so. It used to drop a stamped-empty blob here, "so we never render another
      // draft as this one" — but the page's snapshot was read before this ran, so it rendered the
      // other draft anyway, and the empty blob's stamp AGREED with this page: its load save merged
      // the other draft's pricing into it and PUT eight keys over this project, name, scope and
      // document gone (review of fix 4, round 4). A later load then found that blob "owned" and
      // opened a blank form over the project. With storage failing, the write never landed anyway.
      // The draft-id key is left too, so it still names the draft the slot holds; this page's id is
      // its URL's (getDraftId).
      console.error("[TW] hydration loop stopped for draft", urlId, "— local storage may be unavailable");
      return;
    }

    await flushEvictedBlob(blob);                  // save the OTHER draft's tail under its own id
    const adoptAndReload = (data, seen) => {
      data[STAMP] = urlId;                         // force-stamp (server copy may carry a stale stamp)
      writeBlob(data);
      if (seen) markSynced(urlId, draftDigest(data));    // this IS the server's copy
      setDraftId(urlId);
      setGuard(urlId);
      _reloadPending = true;                       // this page's snapshots are the old blob's
      window.location.reload();                    // re-run page init with the right state
    };
    const attempt = async () => {
      const res = await fetch(resolveApiBase() + "/api/draft/" + encodeURIComponent(urlId),
                              { headers: authHeaders() });
      if (res.ok) {
        const body = await res.json();
        clearUnverified();                                 // we have seen what the server holds
        return adoptAndReload((body && body.data) || {}, true);
      }
      if (res.status === 404) {
        clearUnverified();                                 // a real answer: there is nothing to lose
        return adoptAndReload({}, true);                   // brand-new / never-saved draft
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

  // The digest of the blob as this page FOUND it, taken before initDraftSync can touch it. Every
  // page reads its module-top snapshot (`const state = TW.getState()`) in the same synchronous run
  // right after this script, so this is the digest of what that snapshot was built from — before
  // the page's own init mutates the snapshot in place. The Files page's door asks it: a page may
  // only compose unattended when what it was built from is the server's copy.
  const _bootDigest = (() => { try { return draftDigest(getState()); } catch { return ""; } })();
  // And the blob itself, as found: the copy the door puts back when it gives up (dropHeldChanges).
  const _bootRaw = (() => { try { return localStorage.getItem(STATE_KEY); } catch { return null; } })();
  // And, taken at the same moment, the digest this browser last saw the server hold for the draft
  // (SYNCED_KEY) — before this page's own first save can land and move it. A server still holding
  // exactly that has had nothing saved to it since, so a page built from this browser's copy is
  // building on the server's (reconcileWithServer's "ahead").
  const _bootSynced = (() => { try { return syncedDigest(getDraftId()); } catch { return null; } })();

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
    putDraft(id, blob, true);   // only call site that legitimately needs keepalive
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
      ".tw-dlg-ic{width:54px;height:54px;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 14px;}",
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

  /** One drawn glyph out of js/icons.js, which every page loads before this file.
   *
   *  NEVER an emoji — an emoji is drawn by whatever font the machine has, cannot take the row's
   *  colour, and ignores every size token on the page. Exported on TW so a page that needs one
   *  icon does not grow a private copy of the table. `typeof TWIcon` rather than `window.TWIcon`
   *  because the harnesses lift this function into a bare Function scope with no `window`; and
   *  guarded either way, so a missing icons.js costs a dialog its picture rather than the page its
   *  render. */
  function icon(name, size) {
    return typeof TWIcon === "function" ? TWIcon(name, size) : "";
  }

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
   *  `opts.icon` IS A js/icons.js NAME — "trash", "check", "pause" — not a character. It was a
   *  typed glyph until 2026-09-15 and went through textContent, which was the safe way to render
   *  something a caller might have built out of a project name. A name is safer still: it never
   *  reaches the markup, it only indexes icons.js's table, and an unknown one draws an empty box.
   *  The dialog's other text keeps textContent, because THAT is where the customer-typed project
   *  and vendor names go and none of them should ever be parsed as markup.
   *
   *  `iconSvg` stays separate and still takes literal markup, for a caller that needs a glyph this
   *  dialog's tone colours differently or that icons.js does not carry. */
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
      else icEl.innerHTML = icon(opts.icon || (tone === "warn" ? "trash" : "warning"), 26);
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

  // ─── Was the document built from what the draft says now? ─────────
  /** Keys that never reach the proposal, so a change to one of them leaves the document current.
   *
   *  Everything the Files page writes for itself (the files it last built, the message and the
   *  recipients of a send, the deposit switch, the Dropbox copy), the three keys the SERVER owns
   *  (SERVER_OWNED_KEYS), the Project Info Sheet's own workbook, the ownership stamp, and the
   *  document and its key themselves. A key missing from this list costs a rebuild the proposal
   *  did not need; a key WRONGLY on it would let a changed proposal through unrebuilt, so nothing
   *  that any template prints may ever be added here.
   *
   *  And the board's own marks, which the server writes into the draft from the CRM (drafts.py
   *  set_notify_picks, set_close_lost, set_on_hold, set_won, set_handed_off): who hears about a
   *  send, Lost, On hold, Won, Handed off. No template prints any of them. Counted as inputs, each
   *  one made the next Files visit rebuild the proposal on whichever machine opened it — as
   *  whoever was signed in there, often not the estimator who wrote it (review of fix 4). */
  const COMPOSE_IGNORED = [STAMP, "proposal_payload", "proposal_payload_key",
    "generate_result", "generated_lump_sum", "portal_message", "portal_emails",
    "require_deposit", "dropbox_result",
    "info_cell_values", "info_tab_structs", "info_template_version", "job_number",
    "notify_picks", "closed_lost", "on_hold", "won", "handed_off",
  ].concat(SERVER_OWNED_KEYS);

  /** The key of a draft's document: which inputs it was built from, and which document it is.
   *
   *  Hanz, 2026-09-25: "Clicking to Done should regenerate and make the proposal correctly." The
   *  Files page sends whatever `proposal_payload` is saved, and until now only the Proposal step's
   *  Continue wrote one. A texture picked on the Estimate step, a re-price, a note, a tax mode or a
   *  base flip left by any other door (a step pill, View files, a reload) reached the Files page
   *  with the document from the last Continue, and the customer was sent that.
   *
   *  So Continue stamps the draft with this key as it writes the document (proposal-review.js
   *  continueToDone), and the Files page recomputes it on arrival and before a send. Two halves,
   *  and both must hold:
   *    * the INPUTS: every key of the draft except COMPOSE_IGNORED. An edit anywhere changes it.
   *    * the DOCUMENT: `proposal_payload` itself. A write that put an older document back (a
   *      debounced save landing after Continue) changes this half while leaving the first alone.
   *  "" when there is no document at all, which never equals a stored key.
   *
   *  Pure, and computed off a JSON round trip, so an object in memory and the same object read
   *  back out of localStorage (undefined dropped, NaN as null) give one answer. Keys are sorted, so
   *  the order a merge happened to leave them in cannot move it. The identity of whoever is signed
   *  in and today's date are deliberately NOT inputs: opening a colleague's project on another day
   *  is not a change to it. */
  function composeKey(blob) {
    let plain;
    try { plain = JSON.parse(JSON.stringify(blob || {})); } catch { return ""; }
    if (!plain || typeof plain !== "object" || Array.isArray(plain)) return "";
    const doc = plain.proposal_payload;
    if (!doc || typeof doc !== "object") return "";
    const inputs = {};
    Object.keys(plain).forEach((k) => { if (COMPOSE_IGNORED.indexOf(k) < 0) inputs[k] = plain[k]; });
    return hash53(canonJSON(inputs)) + "." + hash53(canonJSON(doc));
  }

  /** Does this blob's document hold, i.e. was it built from the inputs the blob now carries? */
  function documentHolds(blob) {
    const key = composeKey(blob);
    return !!key && !!blob && blob.proposal_payload_key === key;
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
    setLocalState,
    flushState,
    saveBlocked,
    saveBlockedSay,
    refreshServerOwned,
    clearState,
    readForm,
    writeForm,
    postJSON,
    authHeaders,
    confirmDanger,
    modalOpen,
    icon,
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
    composeKey,
    documentHolds,
    draftDigest,
    bootDigest: () => _bootDigest,
    bootSynced: () => _bootSynced,
    reloadPending: () => _reloadPending,
    readServerDraft,
    readServerRow,
    reconcileWithServer,
    matchesServer,
    useServerCopy,
    keepLocalCopy,
    holdServerSaves,
    heldSaveDigest,
    releaseHeldSaves,
    dropHeldChanges,
  };
})();
