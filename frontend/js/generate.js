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
 */
(function () {
  "use strict";
  var TW = window.TW;
  var LIMIT = 3;                                   // builds at once
  var FRAME_MS = 30000;                            // a compose frame that has not reported by then stops
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
  async function readDraft(id) {
    var r = await call("GET", "/api/draft/" + encodeURIComponent(id));
    var data = r.ok && r.body && r.body.data;
    return data && typeof data === "object" && !Array.isArray(data) ? data : null;
  }

  /** Build one proposal's files: the route the Files step uses, then its PDF, so a PDF that cannot be
   *  made is said here rather than at the Files step. A backup composed from the default wording
   *  (`row.auto`) is built as it stands and says to review it; any other document asks the server to
   *  hold one that was put together unattended and still prints placeholders. */
  async function build(row) {
    row.status = "building";
    row.message = "";
    paint();
    var r = await call("POST", "/api/draft/" + encodeURIComponent(row.id) + "/documents",
                       { hold_placeholders: !row.auto });
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
    row.message = row.auto ? "Built from the default wording; review it on its Proposal tab before sending." : "";
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
        if (d.phase === "started") { started = true; return; }
        if (d.phase === "saved") finish({ ok: true });
        else if (d.phase === "stopped") {
          finish({ ok: false, reason: typeof d.reason === "string" && d.reason ? d.reason
                                      : "Its Proposal step could not rebuild it." });
        }
      }
      window.addEventListener("message", onMessage);
      timer = setTimeout(function () {
        finish({ ok: false, reason: "Its Proposal step took too long to rebuild it." });
      }, FRAME_MS);
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
                skipped: "Not built", rebuilding: "Rebuilding…" };
  var FILES = [["xlsx_download_url", "Estimate (.xlsx)", "_estimate.xlsx"],
               ["docx_download_url", "Proposal (.docx)", "_proposal.docx"],
               ["pdf_download_url", "Proposal (.pdf)", "_proposal.pdf"]];

  function paint() {
    var list = $("gen-list");
    if (!list) return;
    list.innerHTML = rows.map(function (r, i) {
      var name = esc(r.name) + (r.sheet && r.sheet !== r.name ? ' <span class="gen-sheet">(' + esc(r.sheet) + ")</span>" : "")
        + (r.current && rows.length > 1 ? ' <span class="gen-here">this proposal</span>' : "");
      var links = r.status === "built" && r.files ? FILES.filter(function (f) { return r.files[f[0]]; })
        .map(function (f) {
          return '<button type="button" class="download-link gen-dl" data-row="' + i + '" data-file="' + f[0] + '">'
            + icon("arrow-down", 14) + " " + esc(f[1]) + "</button>";
        }).join("") : "";
      return '<li class="gen-row gen-' + esc(r.status) + '" data-id="' + esc(r.id) + '">'
        + '<div class="gen-head"><span class="gen-name">' + name + "</span>"
        + '<span class="gen-status">' + esc(LABEL[r.status] || r.status)
        + (r.status === "built" && r.total ? " · " + esc(r.total) : "") + "</span></div>"
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
    var failed = rows.filter(function (r) { return r.status !== "built"; }).length;
    if (!rows.length) return "";
    if (built === rows.length) return rows.length === 1 ? "The files are built." : "All " + rows.length + " proposals are built.";
    return built + " of " + rows.length + " built."
      + (failed ? " The ones not built say why. You can still continue; the Files step can build them again." : "");
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

  async function visit() {
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

    var datas = await Promise.all(members.map(function (m) {
      return m.id === id && seen.server ? Promise.resolve(seen.server) : readDraft(m.id);
    }));
    rows = members.map(function (m, i) {
      var data = datas[i];
      var name = m.display_label || m.label || (data && data.project_name) || st.project_name || "Proposal";
      var plan = sort(m, data, m.id === id, seen, refresh);
      var neverOpened = plan === "frame" && !(data && data.proposal_payload && data.proposal_payload.values);
      return { id: m.id, name: name, sheet: m.sheet_label || "", current: m.id === id,
               status: typeof plan === "object" ? plan.status : "waiting",
               message: typeof plan === "object" ? plan.message : "", files: null, total: "",
               plan: plan, data: data, neverOpened: neverOpened,
               auto: neverOpened || !!(data && data.proposal_auto_built === true) };
    });
    var work = rows.filter(function (r) { return r.plan === "build" || r.plan === "frame"; });
    var started = 0;
    function begin(r) {
      started++;
      say("Generating files: " + r.name + " (" + started + " of " + work.length + ")…");
    }
    paint();

    var framedCurrent = false;
    async function composeThenBuild(list) {
      for (var i = 0; i < list.length; i++) {
        var r = list[i];
        begin(r);
        r.status = "rebuilding";
        r.message = r.neverOpened ? "Writing its proposal from the default wording…"
          : "Rebuilding its proposal from the latest estimate…";
        paint();
        var out = await composeInFrame(r, r.data);
        if (!out.ok) { fail(r, out.reason); continue; }
        if (r.current) framedCurrent = true;
        await build(r);
      }
    }
    await Promise.all([
      pool(rows.filter(function (r) { return r.plan === "build"; }), LIMIT,
           function (r) { begin(r); return build(r); }),
      composeThenBuild(rows.filter(function (r) { return r.plan === "frame"; })),
    ]);
    // The open proposal's document was composed in a frame and saved: this browser's copy takes it,
    // as it was the saved copy until then ("adopted"), so no page here holds the one from before.
    if (framedCurrent) { try { await TW.reconcileWithServer(); } catch (e) { /* the next page asks again */ } }
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
  var done = visit().catch(function (e) {
    say("Something went wrong building the files: " + ((e && e.message) || e) + ". You can still continue.");
  });
  window.TWGenerate = {
    done: done,
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
