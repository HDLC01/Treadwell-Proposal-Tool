// Externalized for the CSP (no inline scripts). The page script of generate.html.
/* 3 · GENERATE FILES (Hanz, 2026-10-28; reworked 2026-10-29).
 *
 * "Before we go to proposal, we should add another step that says generate files, so that every
 * time we would have a backup or a safety net that it would generate the files every time we change
 * something in the estimate." The wizard is 1 Intake, 2 Estimate, 3 Generate Files, 4 Proposal,
 * 5 Files. Every arrival here builds, for this draft and for every live proposal of its project
 * (Create Multiple Proposals: the parent and its children, drafts.proposals_view), the estimate
 * .xlsx, the proposal .docx and the PDF, then offers Continue to Proposal. Nothing here ever blocks
 * Continue: a proposal that could not be built says why, and the Files step can build it again.
 *
 * "It should always generate the 3 proposals already" / "if we are on the generate files it should
 * stay on that page until I click continue" (Hanz, 2026-10-29, three base bids, one built, the tab
 * flipping between Proposal and Generate Files). So:
 *
 * THE PAGE NEVER LEAVES. The address bar stays on step 3 for the whole run, one progress line says
 * what is being built, and each row ends Built (its price and its three files) or with the reason it
 * was not. Only Continue to Proposal, Back and the step pills leave.
 *
 * EVERY LIVE PROPOSAL IS BUILT, off the SERVER's copy of each:
 *   * a child whose copy of the estimate is older than the estimate (`stale`), or that prices no base
 *     bid of its own (`out_of_step`): the project's Refresh runs first, once, the very call the
 *     Proposal step's "Estimate changed" banner makes (POST /api/draft/{id}/proposals/refresh:
 *     each proposal keeps its own wording and re-copies the estimate). A child it cannot move (one
 *     the customer has) says the server's sentence and is not built. Never run while this browser
 *     holds a copy of the open proposal the server does not ("kept", "unknown", or "ahead" whose
 *     save failed): the Files step's "choose which copy to keep" card decides that first;
 *   * its saved document still matches its draft (TW.documentHolds): built through
 *     POST /api/draft/{id}/documents, the route the Files step's Generate and Download use;
 *   * its document is older than its draft (the estimate moved, or Refresh just re-copied it), or it
 *     has no document yet (nobody opened it): its document is composed by the Proposal step's own
 *     door, run in a HIDDEN same-origin iframe (proposal-review.html?d=<id>&compose=frame&frame=<t>,
 *     composeInFrame below; shared.js FRAME keeps that page off the one localStorage blob every
 *     tab shares), so the document is byte for byte the one Continue would compose. Then it is built
 *     as above. One frame at a time, each torn down when it reports; one that stops (no template, a
 *     base with no price, a copy saved since, 30 s) says why on its row and the page stays;
 *   * one nobody had opened is composed from the template's default wording, as a BACKUP only: the
 *     door marks it `proposal_auto_built`, so Send all still holds it while it prints Kyle's
 *     placeholders (main._send_all_placeholders), and its row says to review it before sending;
 *   * a sibling closed lost or on hold on the board is not built.
 *
 * ONLY WHAT CHANGED IS REBUILT, AND IN PARALLEL (Hanz, 2026-10-29: "there are multiple proposals why
 * not generate them in parallel also ... if we only edited one proposal then it should only
 * regenerate that proposal"). A proposal is UP TO DATE, and costs no build, only when all of this is
 * proven, and anything short of it is rebuilt:
 *   * its saved document holds for its saved draft (TW.documentHolds: `proposal_payload_key` equals
 *     the key over every input the draft carries now, the estimate's cells included, and over the
 *     document itself), it is not stale or out of step with the estimate, and Refresh did not touch it;
 *   * the server still has that very saved copy (`draft_version`, its `updated_at`), and its render
 *     cache holds the render of exactly that document (main._render_key: the payload's hash, which is
 *     everything the .xlsx and the .docx are filled from, the template and the code) with all three
 *     files made, the PDF included (POST /api/draft/{id}/documents/held). The files come back under
 *     fresh tokens; nothing is rendered and LibreOffice does not run.
 * An estimate-only edit changes the draft's inputs, so its document no longer holds: it is composed
 * again and rebuilt. A link whose token has expired since (a restart, an hour) builds the files of
 * the copy its row was judged on again (`draft_version`) and downloads them, as the Files step does;
 * a copy saved since is refused and the link says to reload. "Rebuild all" builds every one again,
 * cache or not: the safety net. Compose frames run FRAME_LIMIT at once (each its own window, token,
 * seed and draft); builds run LIMIT at once in all, the frames' included (`buildSlot`); the server
 * caps the template fills (main._GENERATE_SEM) and LibreOffice (main._PDF_RENDER_SEM) itself.
 */
(function () {
  "use strict";
  var TW = window.TW;
  var LIMIT = 3;                                   // builds at once
  var FRAME_LIMIT = 2;                             // hidden Proposal pages composing at once
  // A compose frame has FRAME_OPEN_MS to load its Proposal page and say "started", then FRAME_MS
  // from "started" to save; the load is not taken out of the compose's time, because two frames
  // load side by side with builds running (review of c6016a9d).
  var FRAME_OPEN_MS = 60000;
  var FRAME_MS = 30000;
  var FRAME_LOAD_GRACE_MS = 3000;                  // loaded, and still nothing said: it never started
  // The Intake and Estimate steps of the spreadsheet flow (a v2 draft goes to the v2 pages).
  var INTAKE = "/?edit=1";
  var ESTIMATE = "/estimate-review.html";
  var rows = [];
  var refreshCalls = 0;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function icon(name, size) { return typeof window.TWIcon === "function" ? window.TWIcon(name, size) : ""; }

  /** The draft whose Intake and Estimate these are: a proposal made from another draft's estimate
   *  has none of its own, so its parent's (TW.redirectProposalChild's rule). */
  function estimateOwner(st) {
    var parent = st && typeof st.proposal_of === "string" ? st.proposal_of : "";
    return parent && TW.isThisDraft(st) ? parent : TW.getDraftId();
  }
  /** Where 1 · Intake and 2 · Estimate (and Back) go from here. */
  function stepTargets(st) {
    var id = estimateOwner(st);
    var q = id ? "d=" + encodeURIComponent(id) : "";
    var v2 = !!(TW.isV2Draft && TW.isV2Draft(st));
    return {
      intake: v2 ? "/polish-intake.html" + (q ? "?" + q : "") : INTAKE + (q ? "&" + q : ""),
      estimate: (v2 ? "/polish-estimate.html" : ESTIMATE) + (q ? "?" + q : ""),
    };
  }
  function paintLinks(st) {
    var to = stepTargets(st);
    var pills = document.querySelectorAll(".progress a.step") || [];
    Array.prototype.forEach.call(pills, function (a) {
      var step = a.getAttribute("data-step");
      if (step === "intake") a.setAttribute("href", to.intake);
      else if (step === "estimate") a.setAttribute("href", to.estimate);
      else if (step === "proposal") a.setAttribute("href", TW.withDraft("/proposal-review.html"));
      else if (step === "files") a.setAttribute("href", TW.withDraft("/done.html"));
    });
    var back = $("gen-back");
    if (back) back.setAttribute("href", to.estimate);
    var next = $("gen-continue");
    if (next) next.setAttribute("href", TW.withDraft("/proposal-review.html"));
  }

  // ── what the server says ─────────────────────────────────────────────────────────────────────
  function sentence(status, body) {
    var d = body && (body.detail != null ? body.detail : body.error);
    if (typeof d === "string" && d.trim()) return d.trim();
    if (d && typeof d === "object" && typeof d.message === "string") return d.message;
    return "The server answered HTTP " + status + ".";
  }
  async function call(method, path, body) {
    var opts = { method: method, headers: TW.authHeaders() };
    if (body !== undefined) opts.body = JSON.stringify(body);
    var res;
    try { res = await fetch(TW.resolveApiBase() + path, opts); }
    catch (e) { return { ok: false, status: 0, error: "The server could not be reached. Check your connection." }; }
    var json = null;
    try { json = await res.json(); } catch (e) { json = null; }
    if (!res.ok || (json && json.ok === false)) return { ok: false, status: res.status, error: sentence(res.status, json) };
    return { ok: true, status: res.status, body: json };
  }
  /** The server's copy of draft `id` and the version it was stored as: {data, version}, or null. */
  async function readRow(id) {
    var r = await call("GET", "/api/draft/" + encodeURIComponent(id));
    var data = r.ok && r.body && r.body.data;
    if (!(data && typeof data === "object" && !Array.isArray(data))) return null;
    return { data: data, version: typeof r.body.updated_at === "string" ? r.body.updated_at : "" };
  }
  var AUTO_SAID = "Built from the default wording; review it on its Proposal tab before sending.";

  /** The version (`updated_at`) of the saved copy `row` was judged on, kept on the row; "" when it
   *  cannot be named. The open proposal was read through reconcileWithServer, which keeps no
   *  version: it is read again, and named only when that copy carries the same document and still
   *  holds. Never rejects. */
  async function versionOf(row) {
    if (row.version) return row.version;
    try {
      var again = await readRow(row.id);
      if (!again || !TW.documentHolds(again.data) || !row.data
          || again.data.proposal_payload_key !== row.data.proposal_payload_key) return "";
      row.version = again.version || "";
    } catch (e) { row.version = ""; }
    return row.version;
  }

  /** Are `row`'s files already built for exactly its saved document? Only asked of a row whose
   *  document holds for its draft (sort's "build"). True, and the row takes its files, only when the
   *  server says so of that very saved copy (see "ONLY WHAT CHANGED" at the top); false on any doubt. */
  async function upToDate(row) {
    try {
      var version = await versionOf(row);
      if (!version) return false;
      var r = await call("POST", "/api/draft/" + encodeURIComponent(row.id) + "/documents/held",
                         { draft_version: version, hold_placeholders: !row.auto });
      var f = r.ok && r.body && r.body.held === true ? r.body.files : null;
      if (!f || !f.xlsx_download_url || !f.docx_download_url || !f.pdf_download_url) return false;
      row.status = "uptodate";
      row.files = f;
      row.total = typeof f.document_total === "string" ? f.document_total : "";
      row.message = row.auto ? AUTO_SAID : "";
      return true;
    } catch (e) {
      return false;
    }
  }

  /** Build one proposal's files: the route the Files step uses, then its PDF, so a PDF that cannot be
   *  made is said here rather than at the Files step. A backup composed from the default wording
   *  (`row.auto`) is built as it stands and says to review it; any other document asks the server to
   *  hold one that was put together unattended and still prints placeholders.
   *  AT MOST LIMIT AT ONCE, WHOEVER ASKS (review of c6016a9d): the pool of proposals that hold and
   *  every compose frame that has saved share `buildSlot`, so the server's template fills (each
   *  workbook alone ~40 MB) never run more than LIMIT at once from this page. */
  function build(row, force) {
    return buildSlot(function () { return buildNow(row, force); });
  }
  /** At most `n` of the functions handed to it run at once; the rest wait their turn, in order. */
  function limiter(n) {
    var free = n;
    var queue = [];
    function release() {
      var next = queue.shift();
      if (next) next(); else free++;
    }
    return function (fn) {
      return new Promise(function (resolve) {
        if (free > 0) { free--; resolve(); } else queue.push(resolve);
      }).then(function () {
        return Promise.resolve().then(fn).then(function (v) { release(); return v; },
                                               function (e) { release(); throw e; });
      });
    };
  }
  var buildSlot = limiter(LIMIT);
  async function buildNow(row, force) {
    row.status = "building";
    row.message = "";
    paint();
    var ask = { hold_placeholders: !row.auto };
    if (force) ask.rebuild = true;                 // "Rebuild all": not the cached render
    var r = await call("POST", "/api/draft/" + encodeURIComponent(row.id) + "/documents", ask);
    if (!r.ok) { fail(row, r.error); return; }
    var out = r.body || {};
    if (out.pdf_download_url) {
      // The PDF itself is the body here; it does not parse as JSON, and `call` reads that as null.
      var pdf = await call("GET", out.pdf_download_url.replace(/^https?:\/\/[^/]+/, ""));
      if (!pdf.ok) {
        fail(row, "The estimate and proposal were built, but the PDF could not be made: " + pdf.error);
        return;
      }
    }
    row.status = "built";
    row.files = out;
    row.total = typeof out.document_total === "string" ? out.document_total : "";
    row.message = row.auto ? AUTO_SAID : "";
    paint();
  }
  function fail(row, why) {
    row.status = "failed";
    row.message = why || "Not built.";
    paint();
  }
  /** Run `fn` over `items`, at most `limit` at once. Never rejects. */
  async function pool(items, limit, fn) {
    var next = 0;
    async function worker() {
      while (next < items.length) {
        var item = items[next++];
        try { await fn(item); } catch (e) { fail(item, (e && e.message) || String(e)); }
      }
    }
    var n = Math.min(limit, items.length);
    var ws = [];
    for (var i = 0; i < n; i++) ws.push(worker());
    await Promise.all(ws);
  }

  // ── the hidden compose frame ─────────────────────────────────────────────────────────────────
  // Each frame's draft, handed over once by its token (shared.js frameMode reads it synchronously,
  // before the Proposal page takes its snapshot of the blob). The server's copy, read just before.
  var seeds = {};
  window.TWComposeFrames = {
    seed: function (token) {
      var s = Object.prototype.hasOwnProperty.call(seeds, token) ? seeds[token] : null;
      delete seeds[token];
      return s;
    },
  };
  function frameToken() {
    var out = "";
    try {
      var a = new Uint8Array(16);
      window.crypto.getRandomValues(a);
      for (var i = 0; i < a.length; i++) out += ("0" + a[i].toString(16)).slice(-2);
    } catch (e) { out = ""; }
    return out.length === 32 ? out : "";
  }
  function origin() {
    try { return window.location.origin; } catch (e) { return ""; }
  }

  /** Compose `row`'s document from `data` (the server's copy of its draft) through the Proposal
   *  step's own door, in a hidden iframe, without leaving this page. Resolves {ok: true} once the
   *  door has saved the document to the server, else {ok: false, reason}. Never rejects. Only a
   *  message from this page's own origin, from that frame, carrying its token, is listened to. */
  function composeInFrame(row, data) {
    return new Promise(function (resolve) {
      var tok = frameToken();
      if (!tok || !document.body) {
        resolve({ ok: false, reason: "This browser could not open its Proposal step here." });
        return;
      }
      seeds[tok] = { id: row.id, data: data };
      var frame = document.createElement("iframe");
      var settled = false;
      var started = false;
      var loads = 0;
      var timer = null;
      function finish(out) {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        window.removeEventListener("message", onMessage);
        delete seeds[tok];
        try { if (frame.parentNode) frame.parentNode.removeChild(frame); } catch (e) { /* gone already */ }
        resolve(out);
      }
      function onMessage(e) {
        if (!e || e.origin !== origin() || e.source !== frame.contentWindow) return;
        var d = e.data;
        if (!d || typeof d !== "object" || d.tw_compose_frame !== tok || d.id !== row.id) return;
        if (d.phase === "started") {
          if (started) return;
          started = true;
          if (timer) clearTimeout(timer);
          timer = setTimeout(tooLong, FRAME_MS);
          return;
        }
        if (d.phase === "saved") finish({ ok: true });
        else if (d.phase === "stopped") {
          finish({ ok: false, reason: typeof d.reason === "string" && d.reason ? d.reason
                                      : "Its Proposal step could not rebuild it." });
        }
      }
      function tooLong() { finish({ ok: false, reason: "Its Proposal step took too long to rebuild it." }); }
      window.addEventListener("message", onMessage);
      timer = setTimeout(tooLong, FRAME_OPEN_MS);
      frame.addEventListener("load", function () {
        loads++;
        // A second page in the frame: the Proposal step sent it somewhere else, so it is not composing.
        if (loads > 1) { finish({ ok: false, reason: "Its Proposal step could not rebuild it here." }); return; }
        setTimeout(function () {
          if (!started) finish({ ok: false, reason: "Its Proposal step could not be opened here." });
        }, FRAME_LOAD_GRACE_MS);
      });
      frame.className = "gen-frame";
      frame.setAttribute("title", "Rebuilding " + (row.name || "a proposal"));
      frame.setAttribute("aria-hidden", "true");
      frame.setAttribute("tabindex", "-1");
      frame.setAttribute("inert", "");
      frame.setAttribute("src", "/proposal-review.html?d=" + encodeURIComponent(row.id)
        + "&compose=frame&frame=" + encodeURIComponent(tok));
      document.body.appendChild(frame);
    });
  }

  // ── the project's Refresh ────────────────────────────────────────────────────────────────────
  /** POST /api/draft/{id}/proposals/refresh with the version of `id`'s saved copy, as the Proposal
   *  step's banner sends it. {ok, body} or {ok: false, error}. */
  async function runRefresh(id) {
    var row = TW.readServerRow ? await TW.readServerRow() : null;
    if (!row || !row.version) return { ok: false, error: "The saved copy could not be read, so nothing was refreshed." };
    refreshCalls++;
    return call("POST", "/api/draft/" + encodeURIComponent(id) + "/proposals/refresh",
                { draft_version: row.version });
  }

  // ── the list ─────────────────────────────────────────────────────────────────────────────────
  var LABEL = { waiting: "Waiting", building: "Building…", built: "Built", failed: "Not built",
                skipped: "Not built", rebuilding: "Rebuilding…", uptodate: "Up to date" };
  function hasFiles(r) { return (r.status === "built" || r.status === "uptodate") && !!r.files; }
  var FILES = [["xlsx_download_url", "Estimate (.xlsx)", "_estimate.xlsx"],
               ["docx_download_url", "Proposal (.docx)", "_proposal.docx"],
               ["pdf_download_url", "Proposal (.pdf)", "_proposal.pdf"]];

  function paint() {
    var list = $("gen-list");
    if (!list) return;
    list.innerHTML = rows.map(function (r, i) {
      // ONE NAME (Hanz, 2026-10-29): a proposal is called what its sheet is called, so no "(sheet)" after it.
      var name = esc(r.name)
        + (r.current && rows.length > 1 ? ' <span class="gen-here">this proposal</span>' : "");
      var links = hasFiles(r) ? FILES.filter(function (f) { return r.files[f[0]]; })
        .map(function (f) {
          return '<button type="button" class="download-link gen-dl" data-row="' + i + '" data-file="' + f[0] + '">'
            + icon("arrow-down", 14) + " " + esc(f[1]) + "</button>";
        }).join("") : "";
      return '<li class="gen-row gen-' + esc(r.status) + '" data-id="' + esc(r.id) + '">'
        + '<div class="gen-head"><span class="gen-name">' + name + "</span>"
        + '<span class="gen-status">' + esc(LABEL[r.status] || r.status)
        + (hasFiles(r) && r.total ? " · " + esc(r.total) : "") + "</span></div>"
        + (r.message ? '<p class="gen-msg">' + esc(r.message) + "</p>" : "")
        + (links ? '<div class="gen-files">' + links + "</div>" : "")
        + "</li>";
    }).join("");
  }
  function say(text) {
    var n = $("gen-note");
    if (!n) return;
    n.textContent = text || "";
    n.hidden = !text;
  }
  function summary() {
    var built = rows.filter(function (r) { return r.status === "built"; }).length;
    var fresh = rows.filter(function (r) { return r.status === "uptodate"; }).length;
    var failed = rows.length - built - fresh;
    var why = " The ones not built say why. You can still continue; the Files step can build them again.";
    if (!rows.length) return "";
    if (fresh) {
      if (!built && !failed) {
        return rows.length === 1 ? "The files are up to date." : "All " + rows.length + " proposals are up to date.";
      }
      return built + " rebuilt, " + fresh + " up to date" + (failed ? ", " + failed + " not built." + why : ".");
    }
    if (built === rows.length) return rows.length === 1 ? "The files are built." : "All " + rows.length + " proposals are built.";
    return built + " of " + rows.length + " built." + (failed ? why : "");
  }

  async function download(btn) {
    var row = rows[Number(btn.getAttribute("data-row"))];
    var key = btn.getAttribute("data-file");
    var f = FILES.filter(function (x) { return x[0] === key; })[0];
    if (!row || !row.files || !f) return;
    var orig = btn.innerHTML;
    btn.disabled = true;
    try {
      var resp = await fetch(TW.absoluteUrl(row.files[key]), { headers: TW.authHeaders() });
      if (resp.status === 404) {
        // ITS TOKEN EXPIRED (they live in the server's memory: a restart, or an hour). The files of
        // its saved document are built again, as the Files step does, and this file is fetched once more.
        // OF THE COPY THE ROW SHOWS, OR NOT AT ALL (review of c6016a9d): the build names the saved copy
        // the row was judged on (`draft_version`), so a copy saved since, from another tab, is refused
        // (409) and the link says to reload this page, which judges it again, as before the heal.
        if (!row.version) throw new Error("expired");
        var again = await buildSlot(function () {
          return call("POST", "/api/draft/" + encodeURIComponent(row.id) + "/documents",
                      { hold_placeholders: !row.auto, draft_version: row.version });
        });
        if (again.status === 409) throw new Error("expired");
        if (!again.ok || !again.body || !again.body[key]) throw new Error(again.error || "HTTP 404");
        row.files = again.body;
        if (typeof again.body.document_total === "string") row.total = again.body.document_total;
        paint();
        resp = await fetch(TW.absoluteUrl(row.files[key]), { headers: TW.authHeaders() });
      }
      if (!resp.ok) throw new Error(resp.status === 404 ? "expired" : "HTTP " + resp.status);
      var blob = new Blob([await resp.arrayBuffer()], { type: "application/octet-stream" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = String(row.name || "proposal").replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 60) + f[2];
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
      btn.disabled = false;
    } catch (e) {
      btn.textContent = /expired/.test(String(e && e.message)) ? "Expired, reload this page" : "Failed, try again";
      setTimeout(function () { btn.innerHTML = orig; btn.disabled = false; }, 2200);
    }
  }

  // ── the visit ────────────────────────────────────────────────────────────────────────────────
  var OUT_OF_STEP = { same_as_base: "same sheet as Base Bid 1", duplicate: "same sheet as another proposal",
                      not_base: "its sheet is not a base bid any more",
                      sheet_gone: "its sheet is not on the estimate any more" };
  var NOT_SAVED = {
    kept: "This browser's copy of the project doesn't match the saved one, so it was not built. "
      + "Open the Files step to choose which copy to keep.",
    ahead: "This browser holds changes to this proposal that could not be saved, so it was not built. "
      + "Check your connection, then reload this page.",
  };
  NOT_SAVED.unknown = NOT_SAVED.kept;

  /** Why Refresh did not catch a stale or out-of-step child up, said after its own sentence. */
  function notRefreshed(seen, refresh) {
    if (NOT_SAVED[seen.status]) {
      return " Refresh was not run here: first choose which copy of the proposal open here to keep, "
        + "on its Files step. Then come back.";
    }
    if (refresh && !refresh.ok) return " Refresh did not go through: " + refresh.error;
    return " Press Refresh on its Proposal step, then come back.";
  }

  /** What to do with one proposal, off the server's copy of it: "build", "frame" (compose its
   *  document in a hidden frame first), or a reason it is not built here ({status, message}). */
  function sort(m, data, isCurrent, seen, refresh) {
    if (isCurrent && NOT_SAVED[seen.status]) return { status: "failed", message: NOT_SAVED[seen.status] };
    if (!data) {
      return { status: "failed", message: "This proposal could not be read from the server. "
        + "Check your connection, then reload this page." };
    }
    if (!isCurrent && data.closed_lost) return { status: "skipped", message: "It is closed as lost on the board." };
    if (!isCurrent && data.on_hold) return { status: "skipped", message: "It is on hold on the board." };
    var held = refresh && refresh.ok ? refresh.skipped[m.id] : null;
    if (held) return { status: "skipped", message: held };
    if (!m.is_parent && m.out_of_step) {
      return { status: "skipped", message: "It prices no base bid of its own ("
        + (OUT_OF_STEP[m.out_of_step] || "out of step") + ")." + notRefreshed(seen, refresh) };
    }
    if (!m.is_parent && m.stale) {
      return { status: "skipped", message: "The estimate changed after this proposal was copied from it."
        + notRefreshed(seen, refresh) };
    }
    var pp = data.proposal_payload;
    if (!(pp && typeof pp === "object" && pp.values && typeof pp.values === "object")) return "frame";
    return TW.documentHolds(data) ? "build" : "frame";
  }

  /** The members of the project's strip, with this draft in it. */
  function membersOf(view, id, st) {
    var ms = view && Array.isArray(view.members) && view.members.length ? view.members.slice()
      : [{ id: id, label: "", display_label: "", sheet_label: "", is_parent: true }];
    if (!ms.some(function (m) { return m.id === id; })) {
      ms.unshift({ id: id, label: "", display_label: "", sheet_label: "", is_parent: !st.proposal_of });
    }
    return ms;
  }

  async function visit(force) {
    try { await TW.draftReady; } catch (e) { /* the checks below decide */ }
    // initDraftSync is reloading this page onto its own project: the reload decides instead.
    if (TW.reloadPending && TW.reloadPending()) return;
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) { /* 401s say so */ }
    var st = TW.getState() || {};
    var id = TW.getDraftId();
    paintLinks(st);
    if (!id || !st.project_name) {
      var empty = $("gen-empty");
      if (empty) empty.hidden = false;
      var main = $("gen-main");
      if (main) main.hidden = true;
      return;
    }
    say("Generating files…");

    var view = await TW.readProposals(id);
    var members = membersOf(view, id, st);
    var seen = await TW.reconcileWithServer();
    if (seen.status === "unreachable") {
      rows = members.map(function (m) {
        return { id: m.id, name: m.display_label || m.label || st.project_name, sheet: m.sheet_label || "",
                 current: m.id === id, status: "failed",
                 message: "The saved project could not be read, so nothing was built. Check your connection, then reload this page." };
      });
      paint();
      say(summary());
      return;
    }
    // THIS BROWSER'S COPY IS THE SAVED ONE PLUS CHANGES WHOSE SAVE NEVER LANDED, and nobody has saved
    // over it since ("ahead"): saving it loses nothing of anyone's, as the Proposal step's door did
    // when it composed it. Saved first, so everything below works off one copy.
    if (seen.status === "ahead") {
      TW.setState({});
      if (await TW.flushState()) seen = await TW.reconcileWithServer();
    }

    // REFRESH FIRST, ONCE, when a child is behind the estimate or out of step with the base bids.
    var refresh = null;
    var behind = members.filter(function (m) { return !m.is_parent && (m.stale || m.out_of_step); });
    if (behind.length && !NOT_SAVED[seen.status]) {
      say("Generating files: copying the estimate into "
          + (behind.length === 1 ? "1 proposal" : behind.length + " proposals") + "…");
      var j = await runRefresh(id);
      refresh = { ok: j.ok, error: j.error || "", skipped: {} };
      if (j.ok) {
        var body = j.body || {};
        var gone = [];
        (Array.isArray(body.skipped) ? body.skipped : []).forEach(function (s) {
          if (!s || !s.id) return;
          if (s.message) refresh.skipped[s.id] = String(s.message);
          else gone.push(s.id);
        });
        gone.forEach(function (sid) {
          refresh.skipped[sid] = "Its sheet is not on the estimate any more, so it was left as it was. "
            + "Delete it, or put the sheet back and Refresh.";
        });
        if (body.proposals && Array.isArray(body.proposals.members)) members = membersOf(body.proposals, id, st);
        // The refresh can rewrite this draft's own saved copy: this browser takes it ("adopted").
        seen = await TW.reconcileWithServer();
        if (seen.status === "unreachable") seen = { status: "same", server: null };
      }
    }

    var reads = await Promise.all(members.map(function (m) {
      return m.id === id && seen.server ? Promise.resolve({ data: seen.server, version: "" }) : readRow(m.id);
    }));
    rows = members.map(function (m, i) {
      var data = reads[i] ? reads[i].data : null;
      var name = m.display_label || m.label || (data && data.project_name) || st.project_name || "Proposal";
      var plan = sort(m, data, m.id === id, seen, refresh);
      var neverOpened = plan === "frame" && !(data && data.proposal_payload && data.proposal_payload.values);
      return { id: m.id, name: name, sheet: m.sheet_label || "", current: m.id === id,
               status: typeof plan === "object" ? plan.status : "waiting",
               message: typeof plan === "object" ? plan.message : "", files: null, total: "",
               plan: plan, data: data, version: reads[i] ? reads[i].version : "", neverOpened: neverOpened,
               auto: neverOpened || !!(data && data.proposal_auto_built === true) };
    });
    paint();

    // ONLY WHAT CHANGED: a proposal whose document holds is asked whether its files are already built
    // for exactly that document. Not on "Rebuild all", and never one Refresh moved (it is "frame").
    var holding = force ? [] : rows.filter(function (r) { return r.plan === "build"; });
    if (holding.length) {
      say("Generating files: checking which are up to date…");
      await pool(holding, LIMIT, async function (r) {
        if (await upToDate(r)) { r.plan = "uptodate"; paint(); }
      });
    }
    var work = rows.filter(function (r) { return r.plan === "build" || r.plan === "frame"; });
    var started = 0;
    function begin(r) {
      started++;
      say("Generating files: " + r.name + " (" + started + " of " + work.length + ")…");
    }
    paint();

    var framedCurrent = false;
    async function composeThenBuild(r) {
      begin(r);
      r.status = "rebuilding";
      r.message = r.neverOpened ? "Writing its proposal from the default wording…"
        : "Rebuilding its proposal from the latest estimate…";
      paint();
      var out = await composeInFrame(r, r.data);
      if (!out.ok) { fail(r, out.reason); return; }
      if (r.current) framedCurrent = true;
      // The copy its frame saved, so a link healed later builds that copy or says to reload.
      var saved = await readRow(r.id);
      r.version = saved && saved.data && saved.data.proposal_payload ? saved.version : "";
      await build(r, force);
    }
    await Promise.all([
      pool(rows.filter(function (r) { return r.plan === "build"; }), LIMIT,
           async function (r) { begin(r); await versionOf(r); return build(r, force); }),
      pool(rows.filter(function (r) { return r.plan === "frame"; }), FRAME_LIMIT, composeThenBuild),
    ]);
    // The open proposal's document was composed in a frame and saved: this browser's copy takes it,
    // as it was the saved copy until then ("adopted"), so no page here holds the one from before.
    if (framedCurrent) { try { await TW.reconcileWithServer(); } catch (e) { /* the next page asks again */ } }
    // `version` stays: it is the saved copy each row's files are of, which an expired link heals from.
    rows.forEach(function (r) { delete r.data; });
    say(summary());
  }

  var list = $("gen-list");
  if (list && list.addEventListener) {
    list.addEventListener("click", function (e) {
      var btn = e.target && e.target.closest ? e.target.closest("button.gen-dl") : null;
      if (btn) download(btn);
    });
  }
  // "REBUILD ALL": every proposal built again, cache or not (the safety net). Offered once a run has
  // finished, and not while one is going.
  var running = null;
  function paintRebuild() {
    var btn = $("gen-rebuild");
    if (!btn) return;
    btn.hidden = !rows.length;
    btn.disabled = !!running;
  }
  function start(force) {
    running = visit(!!force).catch(function (e) {
      say("Something went wrong building the files: " + ((e && e.message) || e) + ". You can still continue.");
    }).then(function () { running = null; paintRebuild(); });
    paintRebuild();
    return running;
  }
  var rebuild = $("gen-rebuild");
  if (rebuild && rebuild.addEventListener) {
    rebuild.addEventListener("click", function () { if (!running) start(true); });
  }
  var done = start(false);
  window.TWGenerate = {
    done: done,
    running: function () { return running; },
    rows: function () {
      return JSON.parse(JSON.stringify(rows.map(function (r) {
        var o = {};
        Object.keys(r).forEach(function (k) { if (k !== "data") o[k] = r[k]; });
        return o;
      })));
    },
    refreshCalls: function () { return refreshCalls; },
  };
})();
