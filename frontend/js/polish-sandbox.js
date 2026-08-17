// The polish BETA's sandbox: the beta never edits a live customer bid.
//
// WHY THIS IS ITS OWN FILE NOW.
//
// It lived inside js/polish-estimate.js while the beta was one page. The beta is two pages: the
// calculator (polish-estimate.html) writes the takeoff, and the beta intake form
// (polish-intake.html) writes the five job-condition toggles that used to be the calculator's
// step 2. Both need the same guarantee, and the intake page needs it if anything MORE than the
// calculator does — it opens straight onto whatever project you came from and saves a toggle
// within a second of the first click, so an unprotected intake page writing `conditions` onto a
// real live draft is precisely the edit this code exists to prevent.
//
// EVERY FUNCTION BODY BELOW WAS MOVED VERBATIM out of js/polish-estimate.js. This was an
// extraction, not a rewrite: the sandbox is the one thing standing between the beta and a
// customer's bid, and four defects were found in that page in a single day, so its behaviour is
// not up for tidying while it changes files. The comments came with the bodies, because each one
// records a defect somebody already paid for.
//
// WHAT THE BLOCK USED TO TAKE FROM THE PAGE IT LIVED IN, AND WHERE THAT WENT.
//
//   * `$(id)` — the one-line document.getElementById helper. COPIED into this file; there is
//     nothing worth sharing in two lines.
//   * `adopt(blob)` — the page's model-adopting callback. Now a PARAMETER of enterSandbox, since
//     the two pages adopt different models (the calculator rebuilds its worksheet cell map, the
//     intake page rebuilds its conditions) and this module cannot know either of them.
//   * `state` — the page's copy of the draft blob. Kept HERE too, read from TW.getState() at the
//     top of enterSandbox (which is exactly where the page's own `state` had just come from) and
//     re-pointed by adoptDraft. hasContent(state) and the copy's name both need it.
//
// TWO DELIBERATE ADDITIONS, both about there being a SECOND caller now:
//
//   * The three `$("loading").textContent = …` writes go through loadingNote(), which no-ops when
//     the page has no #loading element. Those writes are on the FAILURE path, and a throw there
//     would be caught by the caller and read as "carry on" — the one outcome with no undo. The
//     note banner (#sandbox-note) was already null-guarded and still is.
//   * repointWizardLinks() now also stamps ?d= onto the beta pages' own links. shared.js's
//     _WIZARD_PATH deliberately excludes /polish-intake.html and /polish-estimate.html, so those
//     hrefs arrive carrying no ?d= at all and the original rule — only touch a link shared.js
//     already stamped — walked straight past them.
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  // ── the beta is a sandbox: it never edits a live bid ────────────────────────
  //
  // Hanz, 2026-08-11: "The current polish excel sheet and the beta shuold be two different
  // workflows okay? The BETA is for testing and which means all data from that leads to the
  // 'test' Category of the proposals database." Asked what should happen when somebody opens a
  // REAL project in the beta, he chose: make a test copy, leave the real bid alone. It sits
  // under his standing rule from 2026-08-07: never test against a live Active project.
  //
  // So Kyle opening Nearman Creek here leaves Nearman Creek in Active exactly as it was, and
  // works on "Nearman Creek (beta test)" under Test. He can price one job both ways and compare
  // them, which is the whole reason the beta runs beside the old screen instead of replacing it.
  var BETA_SUFFIX = " (beta test)";

  // The draft blob this module is working ON, and the caller's own view of it. Reassigned
  // together by adopt(), because the page can switch drafts mid-boot: opening a real bid in the
  // beta works on a test copy instead (see enterSandbox), and leaving the caller rendering the
  // copy with the real bid's numbers still in hand would be the same silent mix-up in a
  // different direction.
  var state = {};
  var onAdopt = null;

  /** Point this module AND its caller at one draft's blob.
   *
   *  The caller's half is whatever it passed to enterSandbox: the calculator rebuilds its cell
   *  map and its worksheet model, the intake page rebuilds its conditions. Neither is this
   *  module's business — but both have to happen before anything is rendered from `blob`. */
  function adopt(blob) {
    state = blob || {};
    if (onAdopt) onAdopt(state);
  }

  /** The page's "stopped here, and why" line, when the page has somewhere to put it.
   *
   *  Null-guarded because this module has two callers now. Every use is on a failure path, where
   *  a throw would be swallowed by the caller's try and read as "carry on and open the project
   *  you were given" — which is the live-bid edit, arrived at by accident. */
  function loadingNote(msg) {
    var el = $("loading");
    if (el) el.textContent = msg;
  }

  /** The copy's id is DERIVED from the source's, not minted.
   *
   *  Idempotence is the reason, and there is no other cheap way to get it. Reopening the beta on
   *  the same real project has to find the copy it made last time or it mints a second, third and
   *  fourth; the projects list cannot be searched for it (_build_summaries in backend/drafts.py
   *  selects a fixed set of columns, and a "copy of" field is not one of them); and the obvious
   *  alternative, a pointer written onto the SOURCE, is exactly the write this whole feature
   *  exists to avoid. A derived id needs neither: one GET answers whether the copy exists. It
   *  also reads plainly in the database, which matters when Kyle is looking at two rows for one
   *  job. */
  function sandboxIdFor(id) { return id + "-beta"; }

  /** Recognisable at a glance in the Proposals Database, and it never stacks up: run the logic
   *  twice and the name still ends in ONE " (beta test)". */
  function betaName(name) {
    var n = String(name == null ? "" : name).trim();
    if (!n) return "Untitled" + BETA_SUFFIX;
    return n.slice(-BETA_SUFFIX.length) === BETA_SUFFIX ? n : n + BETA_SUFFIX;
  }

  function draftUrl(id, tail) {
    return TW.resolveApiBase() + "/api/draft/" + encodeURIComponent(id) + (tail || "");
  }

  /** Has anything actually been typed into this draft yet?
   *
   *  __draft_id is not content: it is shared.js's ownership stamp, and shared.js writes a
   *  stamped-EMPTY blob on purpose (initDraftSync's 404 floor, and again when its hydration guard
   *  trips). Counting it would read "nobody has touched this" as "there is work here". Same rule,
   *  and the same reason, as flushEvictedBlob in shared.js. */
  function hasContent(blob) {
    if (!blob) return false;
    return Object.keys(blob).filter(function (k) { return k !== "__draft_id"; }).length > 0;
  }

  /** Ask shared.js to file this project as a test on its FIRST real save, instead of creating the
   *  row here to have something to file.
   *
   *  The sidebar door is a bare /polish-estimate.html with no ?d=, so shared.js has already minted
   *  an id by the time enterSandbox runs, and saving unconditionally filed a nameless "Untitled"
   *  row under Test every time somebody opened the beta to look at it, `created` event and all.
   *  That is the same thing ae23c5d stopped the server doing ("the server stops creating projects
   *  nobody asked for").
   *
   *  Bound to this id ("<id>:1", the format pendingTestIntentFor reads) rather than the bare "1"
   *  that setNewProjectTestIntent writes: an unbound intent lands on whatever project is saved
   *  next, which is how a real customer bid would end up filed as a test. */
  function markNewProjectAsTest(id) {
    try { localStorage.setItem("treadwell.proposal_tool.new_is_test", id + ":1"); } catch (e) {}
  }

  /** A draft's blob, or null when that id has never been saved.
   *
   *  READ ONLY, deliberately: no method, no body. This is the one call that touches the real
   *  project, and it must not be able to change it.
   *
   *  Anything other than 200/404 throws rather than answering. An indeterminate reply read as
   *  "not filed as a test" would copy a project needlessly; read as "filed" it would edit a live
   *  bid, which is the one outcome there is no undoing. The caller stops the page instead. */
  async function loadRow(id) {
    var res = await fetch(draftUrl(id), { headers: TW.authHeaders() });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error("HTTP " + res.status);
    var body = await res.json();
    return (body && body.data) || {};
  }

  /** File a draft under the Projects page's Test tab.
   *
   *  The route is "/test". An earlier pass named it after the handler instead
   *  (api_test_flag_draft), got a silent 405 on every call, and the project sat in Active looking
   *  fine. projects.js has always posted to "/test" and this has to agree with it.
   *
   *  keepalive because the estimator can navigate while this is in flight; a plain fetch is
   *  cancelled on unload, same reason shared.js carries its own saves that way. */
  function fileAsTest(id) {
    return fetch(draftUrl(id, "/test"), {
      method: "POST",
      headers: TW.authHeaders(),
      body: JSON.stringify({ is_test: true }),
      keepalive: true,
    });
  }

  /** Write `blob` under `id`, and file it as a test only once that has actually landed.
   *
   *  Ordering is not stylistic. set_test_flag returns False on a missing draft, so filing before
   *  the first successful save is a silent no-op and the project stays in Active.
   *
   *  And "landed" is not res.ok: api_save_draft catches its own failures and answers 200 with
   *  {"ok": false, "error": ...}, so a save that never happened looks like a success to anyone
   *  checking the status alone.
   *
   *  The flag POST is best-effort on purpose. If it fails the copy still exists and is still safe
   *  to edit (it is not the real bid), and its "(beta test)" name puts it in the Test tab via
   *  the projects-page name heuristic anyway. Refusing to open over that would be worse. */
  async function saveThenFileAsTest(id, blob) {
    var res = await fetch(draftUrl(id), {
      method: "PUT",
      headers: TW.authHeaders(),
      body: JSON.stringify({ data: blob }),
      keepalive: true,
    });
    var body = res.ok ? await res.json().catch(function () { return null; }) : null;
    if (!res.ok || (body && body.ok === false)) {
      throw new Error("save refused: " + ((body && body.error) || res.status));
    }
    await fileAsTest(id).catch(function (e) { console.warn("[polish beta] test flag failed", e); });
  }

  /** The source's numbers under a new name, plus the marks that make the copy a copy. */
  function buildCopy(srcData, srcId) {
    var blob = Object.assign({}, srcData);
    // Server-owned (_SERVER_OWNED_KEYS in backend/drafts.py). is_test especially: the source may
    // carry `false`, meaning a human said "this IS a real bid", and this page PUTs the whole blob
    // on every autosave, so copying that key across would file the copy as a test through /test
    // and then quietly put it back in Active a couple of seconds later.
    delete blob.is_test;
    delete blob.archived;
    delete blob.assigned_estimator;
    delete blob.__draft_id;              // shared.js's ownership stamp; it belongs to the source
    blob.project_name = betaName(srcData.project_name);
    // Paired with the derived id, this is what makes reopening idempotent: a draft that says
    // whose sandbox it is never gets copied again, even if its test flag went missing.
    blob.beta_sandbox_of = srcId;
    blob.beta_sandbox_of_name = srcData.project_name || "";
    return blob;
  }

  /** Move the page, and the address bar, onto `id`, with `blob` as its state.
   *
   *  The URL matters as much as the id. A reload that still said ?d=<the real project> would land
   *  back on the live bid, and the next autosave would write to it.
   *
   *  clearState first so the source's blob is out of localStorage before anything is written: with
   *  it still there and stamped, shared.js refuses the setState below as a foreign write. */
  function adoptDraft(id, blob) {
    TW.clearState();
    try {
      var url = new URL(window.location.href);
      url.searchParams.set("d", id);
      window.history.replaceState({}, "", url);
    } catch (e) {}
    // shared.js keeps the id here for navigations that drop the query string and exports no
    // setter for it; projects.js reaches for the same key when it starts a fresh project.
    try { localStorage.setItem("treadwell.proposal_tool.draft_id", id); } catch (e) {}
    adopt(blob);
    TW.setState(state);
    repointWizardLinks();
  }

  // A beta page's OWN links. shared.js stamps ?d= onto the wizard's static step links at
  // DOMContentLoaded, but _WIZARD_PATH excludes both of these on purpose, so they arrive with no
  // ?d= at all — and the rule below only follows a link that already carries one.
  var BETA_PATH = /^\/polish-(intake|estimate)\.html$/;

  /** shared.js stamps ?d= onto the static wizard links at DOMContentLoaded, which is long before
   *  this page has settled which draft it is on. Left alone, "3 · Proposal" walks the estimator
   *  straight back onto the real bid — and "2 · Estimate" out of the beta intake form never
   *  carried an id in the first place. */
  function repointWizardLinks() {
    var id = TW.getDraftId();
    if (!id) return;
    document.querySelectorAll("a[href]").forEach(function (a) {
      try {
        var u = new URL(a.getAttribute("href"), location.origin);
        if (u.origin !== location.origin) return;
        if (!u.searchParams.has("d") && !BETA_PATH.test(u.pathname)) return;
        u.searchParams.set("d", id);
        a.setAttribute("href", u.pathname + u.search + u.hash);
      } catch (e) {}
    });
  }

  /** Say so, on screen. Working on a different project than the one clicked is worse than the bug
   *  being fixed if nobody is told. textContent throughout: a project name is not markup. */
  function showCopyNote(srcName, copyName) {
    var el = $("sandbox-note");
    if (!el) return;
    el.textContent = "";
    var ic = document.createElement("span");
    ic.className = "ic";
    ic.textContent = "⧉";
    el.appendChild(ic);
    var p = document.createElement("span");
    p.appendChild(document.createTextNode("You are editing a test copy. Everything here saves to "));
    var b1 = document.createElement("b");
    b1.textContent = copyName;
    p.appendChild(b1);
    p.appendChild(document.createTextNode(" under the Test tab. The real project, "));
    var b2 = document.createElement("b");
    b2.textContent = srcName || "the one you opened";
    p.appendChild(b2);
    p.appendChild(document.createTextNode(", is untouched in Active."));
    el.appendChild(p);
    el.hidden = false;
  }

  /** `pending` = the row does not exist yet, so nothing has been filed yet either. Saying "this
   *  project is filed as a test" over an empty page would be a claim about a row that is not
   *  there. */
  function showDirectNote(pending) {
    var el = $("sandbox-note");
    if (!el) return;
    el.textContent = "";
    var ic = document.createElement("span");
    ic.className = "ic";
    ic.textContent = "⧉";
    el.appendChild(ic);
    var p = document.createElement("span");
    p.textContent = pending
      ? "Nothing has been priced here yet. Whatever you enter is saved as a NEW test project, " +
        "under the Test tab. No real bid is involved."
      : "This project is filed as a test, so the beta is editing it directly. " +
        "No real bid is involved.";
    el.appendChild(p);
    el.hidden = false;
  }

  /** Settle which draft this page may write to, BEFORE it can be typed into.
   *
   *  Returns false when it could not settle that safely, in which case the caller leaves the page
   *  on its loading message. Stopping is the correct failure: the alternative is a beta that
   *  edits a customer's bid because a fetch blipped.
   *
   *  `adoptFn` is the caller's own model-adopting callback — the page half of adopt(). It is
   *  taken here rather than at load time because it is the caller's ONLY way of hearing that the
   *  draft moved, and nothing may be rendered until it has. */
  async function enterSandbox(adoptFn) {
    if (adoptFn) onAdopt = adoptFn;
    // The page's blob, which is where the old in-page `state` had just come from (its init()
    // called adopt(TW.getState()) on the line above this one).
    state = TW.getState() || {};

    var id = TW.getDraftId();
    if (!id) return true;                        // no project at all, nothing to protect

    var row;
    try { row = await loadRow(id); }
    catch (e) {
      loadingNote("Couldn't check whether this project is filed as a test, so the " +
        "beta stopped rather than risk editing a real bid. Reload to try again.");
      return false;
    }

    // Never saved: this id IS the sandbox, there is nothing to copy, and Hanz asked for
    // everything the beta touches to land under Test. Save it so the row exists, then file it.
    //
    // Only when there is something to save, though. Opening the beta must not CREATE a project:
    // see markNewProjectAsTest, which hands the filing to the first save the estimator earns.
    if (row === null) {
      if (hasContent(state)) {
        try { await saveThenFileAsTest(id, state); }
        catch (e) { console.warn("[polish beta] could not file the new project as a test", e); }
        showDirectNote(false);
      } else {
        markNewProjectAsTest(id);
        showDirectNote(true);
      }
      return true;
    }

    // Already filed as a test, or a copy this page made earlier. Work on it directly: no copy, no
    // rename. This is the normal path once somebody is working in the sandbox.
    //
    // `=== true` exactly, because is_test is a tri-state (see _tribool in backend/drafts.py):
    // `false` is a human saying "this IS a real bid" and absent is nobody having said. Both of
    // those are projects to copy, and a truthiness check would have read absent as filed.
    if (row.is_test === true || row.beta_sandbox_of) {
      showDirectNote(false);
      return true;
    }

    var copyId = sandboxIdFor(id);
    var copy;
    try { copy = await loadRow(copyId); }
    catch (e) {
      loadingNote("Couldn't check for this project's test copy, so the beta " +
        "stopped rather than risk editing the real bid. Reload to try again.");
      return false;
    }

    if (copy) {
      // Second visit. Reuse the copy AS IT IS: re-seeding it from the source would throw away
      // whatever was priced here last time, which is the comparison the beta exists for.
      if (copy.is_test !== true) {
        fileAsTest(copyId).catch(function (e) { console.warn("[polish beta] refiling failed", e); });
      }
      adoptDraft(copyId, copy);
    } else {
      var blob = buildCopy(row, id);
      try { await saveThenFileAsTest(copyId, blob); }
      catch (e) {
        loadingNote("Couldn't make the test copy, so the beta stopped rather than " +
          "edit the real project itself. Reload to try again.");
        return false;
      }
      adoptDraft(copyId, blob);
    }
    showCopyNote(row.project_name, state.project_name);
    return true;
  }

  window.TWPolishSandbox = {
    enterSandbox: enterSandbox,
    markNewProjectAsTest: markNewProjectAsTest,
    repointWizardLinks: repointWizardLinks,
    sandboxIdFor: sandboxIdFor,
    betaName: betaName,
    buildCopy: buildCopy,
    loadRow: loadRow,
    fileAsTest: fileAsTest,
    saveThenFileAsTest: saveThenFileAsTest,
    adoptDraft: adoptDraft,
    hasContent: hasContent,
    showCopyNote: showCopyNote,
    showDirectNote: showDirectNote,
  };
})();
