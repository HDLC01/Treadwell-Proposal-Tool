// Externalized for the CSP (no inline scripts). The page script of generate.html.
/* 3 · GENERATE FILES (Hanz, 2026-10-28).
 *
 * "Before we go to proposal, we should add another step that says generate files, so that every
 * time we would have a backup or a safety net that it would generate the files every time we change
 * something in the estimate." The wizard is now 1 Intake, 2 Estimate, 3 Generate Files, 4 Proposal,
 * 5 Files. Every arrival here builds, for this draft and for every live proposal of its project
 * (Create Multiple Proposals: the parent and its children, drafts.proposals_view), the estimate
 * .xlsx, the proposal .docx and the PDF, then offers Continue to Proposal. Nothing here ever blocks
 * Continue: a proposal that could not be built says why, and the Files step can build it again.
 *
 * ONE BUILD PATH, THE FILES STEP'S. A document is composed in exactly one place, the Proposal step's
 * continueToDone. So each proposal is sorted, off the SERVER's copy of it:
 *   * its saved document still matches the draft (TW.documentHolds): built now through
 *     POST /api/draft/{id}/documents, the route the Files step's Generate and Download use, which
 *     renders the saved document and records `generate_result` exactly as it does for them;
 *   * it has a document, but the draft changed since it was composed (the estimate moved): the tab
 *     is walked through that proposal's own Proposal-step door (send-all-chain.js, kind "generate",
 *     the door the Files page uses), which composes it from the draft as it stands and comes back
 *     here; then it is built as above. Building the saved document instead would hand out files at
 *     the price from before the change, which is the opposite of a safety net;
 *   * it has NO document yet (a proposal nobody has opened): NOT built here. It says "Built on the
 *     Proposal step". Composing it unattended would put Kyle's template placeholders ("xx gallons",
 *     "-or-" choices) into a customer-facing file with nobody reading it, and the estimator is one
 *     step from writing it properly. Its files are built when its Proposal step's Continue is pressed;
 *   * a proposal of Create Multiple Proposals whose copy of the estimate is older than its parent's,
 *     or that prices no base bid of its own: NOT built, with the Proposal step's own words (press
 *     Refresh there). A sibling closed lost or on hold on the board is not built either.
 * A document Send all's walk composed unattended that still prints placeholders is refused by the
 * server (`hold_placeholders`) with its sentence.
 *
 * THE WALK RUNS ONCE PER VISIT. A page that came back from one (`sendall_resume`) never starts
 * another: a proposal still not matching after it says so instead of looping.
 */
(function () {
  "use strict";
  var TW = window.TW;
  var LIMIT = 3;                                   // builds at once
  // The Intake and Estimate steps of the spreadsheet flow (a v2 draft goes to the v2 pages).
  var INTAKE = "/?edit=1";
  var ESTIMATE = "/estimate-review.html";
  var rows = [];

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
    if (!res.ok) return { ok: false, status: res.status, error: sentence(res.status, json) };
    return { ok: true, status: res.status, body: json };
  }
  async function readDraft(id) {
    var r = await call("GET", "/api/draft/" + encodeURIComponent(id));
    var data = r.ok && r.body && r.body.data;
    return data && typeof data === "object" && !Array.isArray(data) ? data : null;
  }

  /** Build one proposal's files: the route the Files step uses, then its PDF, so a PDF that cannot be
   *  made is said here rather than at the Files step. */
  async function build(row) {
    row.status = "building";
    paint();
    var r = await call("POST", "/api/draft/" + encodeURIComponent(row.id) + "/documents",
                       { hold_placeholders: true });
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
    row.message = "";
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

  // ── the list ─────────────────────────────────────────────────────────────────────────────────
  var LABEL = { waiting: "Waiting", building: "Building…", built: "Built", failed: "Not built",
                skipped: "Not built", later: "Built on the Proposal step", rebuilding: "Rebuilding…" };
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
    var failed = rows.filter(function (r) { return r.status === "failed"; }).length;
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

  /** What to do with one proposal, off the server's copy of it: "build", "compose" (walk its door
   *  first), or a reason it is not built here ({status, message}). */
  function sort(m, data, isCurrent, seen, walked) {
    if (isCurrent && (seen.status === "kept" || seen.status === "unknown")) {
      return { status: "failed", message: "This browser's copy of the project doesn't match the saved one, "
        + "so it was not built. Open the Files step to choose which copy to keep." };
    }
    if (!data) {
      return { status: "failed", message: "This proposal could not be read from the server. "
        + "Check your connection, then reload this page." };
    }
    if (!isCurrent && data.closed_lost) return { status: "skipped", message: "It is closed as lost on the board." };
    if (!isCurrent && data.on_hold) return { status: "skipped", message: "It is on hold on the board." };
    if (!m.is_parent && m.out_of_step) {
      return { status: "skipped", message: "It prices no base bid of its own ("
        + (OUT_OF_STEP[m.out_of_step] || "out of step") + "). Press Refresh on its Proposal step, then come back." };
    }
    if (!m.is_parent && m.stale) {
      return { status: "skipped", message: "The estimate changed after this proposal was copied from it. "
        + "Press Refresh on its Proposal step, then come back." };
    }
    var pp = data.proposal_payload;
    if (!(pp && typeof pp === "object" && pp.values && typeof pp.values === "object")) {
      return { status: "later", message: "Its proposal hasn't been written yet, so there is nothing to build. "
        + "Its files are built when you open it on the Proposal step and press Continue." };
    }
    if (walked.indexOf(m.id) >= 0) return "build";       // composed by its door a moment ago
    if ((isCurrent && seen.status === "ahead") || !TW.documentHolds(data)) return "compose";
    return "build";
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
    var params = null;
    try { params = new URLSearchParams(window.location.search); } catch (e) { params = null; }
    var cameBack = !!(params && params.get("sendall_resume"));
    say("Building the files from the estimate as it stands…");

    var view = await TW.readProposals(id);
    var members = view && Array.isArray(view.members) && view.members.length ? view.members.slice()
      : [{ id: id, label: "", display_label: "", sheet_label: "", is_parent: true }];
    if (!members.some(function (m) { return m.id === id; })) {
      members.unshift({ id: id, label: "", display_label: "", sheet_label: "", is_parent: !st.proposal_of });
    }
    var group = (view && view.parent_id) || id;
    var taken = cameBack && window.TWSendAll ? window.TWSendAll.take(params, group, "generate") : null;
    var walked = taken ? taken.built : [];

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
    var datas = await Promise.all(members.map(function (m) {
      return m.id === id ? Promise.resolve(seen.server) : readDraft(m.id);
    }));

    rows = members.map(function (m, i) {
      var data = datas[i];
      var name = m.display_label || m.label || (data && data.project_name) || st.project_name || "Proposal";
      return { id: m.id, name: name, sheet: m.sheet_label || "", current: m.id === id,
               status: "waiting", message: "", files: null, total: "",
               plan: sort(m, data, m.id === id, seen, walked) };
    });
    rows.forEach(function (r) {
      if (typeof r.plan === "object") { r.status = r.plan.status; r.message = r.plan.message; }
    });
    var compose = rows.filter(function (r) { return r.plan === "compose"; });
    // A WALK LEAVES THIS PAGE'S COPY BEHIND. This browser's copy of the current proposal is not the
    // saved one ("kept": both moved; "unknown": no record to tell), and the one copy slot is handed
    // to each door's draft as the walk goes: shared.js only warns about a copy it cannot save, so
    // the edit the Files step's "choose which copy to keep" card offers would be gone before anyone
    // could choose it (review, 2026-10-28). So nothing walks; the rows that need no door still build.
    var unsure = seen.status === "kept" || seen.status === "unknown";
    if (compose.length && unsure) {
      compose.forEach(function (r) {
        r.status = "failed";
        r.message = "Not rebuilt: first choose which copy of the proposal open here to keep, on its "
          + "Files step. Then come back.";
      });
      compose = [];
    }
    if (compose.length) {
      var started = false;
      if (!cameBack && window.TWSendAll) {
        compose.forEach(function (r) { r.status = "rebuilding"; r.message = "Rebuilding its proposal from the latest estimate…"; });
        paint();
        say("Rebuilding " + (compose.length === 1 ? "the proposal" : compose.length + " proposals")
            + " from the latest estimate, then building the files…");
        started = window.TWSendAll.start({
          group: group, kind: "generate",
          build: compose.map(function (r) { return { id: r.id, label: r.name }; }),
          returnUrl: "/generate.html?d=" + encodeURIComponent(id),
        });
        if (started) return;                             // the tab is on its way to the first door
      }
      compose.forEach(function (r) {
        r.status = "failed";
        r.message = "It could not be rebuilt from the latest estimate here. Open its Proposal step and press Continue.";
      });
    }
    paint();
    await pool(rows.filter(function (r) { return r.plan === "build"; }), LIMIT, build);
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
    rows: function () { return JSON.parse(JSON.stringify(rows)); },
  };
})();
