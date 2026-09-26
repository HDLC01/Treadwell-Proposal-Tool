// Externalized from done.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.

  /** One drawn glyph out of js/icons.js, which every page loads before this file.
   *
   *  NEVER an emoji — an emoji is drawn by whatever font the machine has, cannot take the
   *  row's colour, and ignores every size token on the page. `typeof TWIcon` rather than
   *  `window.TWIcon` because the test harnesses lift these renderers into a bare Function
   *  scope with no `window`; an icons.js that failed to load then costs a page its pictures
   *  rather than its render.
   */
  function icon(name, size) {
    return typeof TWIcon === "function" ? TWIcon(name, size) : "";
  }
  const state = TW.getState();
  const result = state.generate_result;

  const preEl   = document.getElementById("pre-generate");
  const postEl  = document.getElementById("post-generate");
  const emptyEl = document.getElementById("empty-state");

  // "View files" entry from the Projects list: /done.html?d=<id>&files=1 —
  // skip the intake→estimate→proposal walk and just produce + show the
  // downloads for this saved project (initDraftSync already hydrated its state).
  const filesMode = (() => {
    try { return new URLSearchParams(location.search).get("files") === "1"; }
    catch { return false; }
  })();

  /** Did the estimator arrive here straight from the Proposal step's Continue, a moment ago?
   *
   *  continueToDone marks its navigation `composed=1`. The mark is taken off the address at once,
   *  so a reload, a bookmark or a link copied out of the bar comes back through the door like any
   *  other arrival. What it buys is a loop guard, nothing more: a page that has just been built
   *  from the draft is never sent straight back to be built again. */
  const composedHere = (() => {
    try {
      const u = new URL(location.href);
      if (u.searchParams.get("composed") !== "1") return false;
      u.searchParams.delete("composed");
      history.replaceState(history.state, "", u.pathname + u.search + u.hash);
      return true;
    } catch { return false; }
  })();

  /** The Total the document was actually filled with, off the payload being sent to /api/generate.
   *
   *  `values.total_formatted` and not `proposal_lump_sum`: this has to be the figure the DOCUMENT
   *  received, because the whole job of the stamp is to answer "is the price on screen the price
   *  in these files". Reading the draft's own number instead would stamp what the sidebar believed
   *  at that moment, which is the thing being checked rather than the thing to check it against. */
  function builtAt(payload) {
    const v = (payload && payload.values) || {};
    return typeof v.total_formatted === "string" ? v.total_formatted : null;
  }

  /** A money string as a number. "$36,700.00" → 36700. null when there is nothing to read.
   *
   *  THE DIGIT TEST IS THE WHOLE POINT. Stripping non-numerics out of "—" leaves "", and
   *  `Number("")` is 0 — a perfectly finite, perfectly wrong zero. Without this the card renders
   *  an em dash as a price of nothing, and the staleness check reads an unpriced draft as having
   *  moved to $0.00. Both were live until the harness ran. */
  function money(s) {
    if (s == null) return null;
    const cleaned = String(s).replace(/[^0-9.-]/g, "");
    if (!/\d/.test(cleaned)) return null;
    const n = Number(cleaned);
    return Number.isFinite(n) ? n : null;
  }

  /** The price moved after these files were built.
   *
   *  `generate_result` is persisted and never cleared, so a project generated once lands straight
   *  on the PREVIOUS downloads and never rebuilds — proposal-review.js's Continue drops the result
   *  only when the cover letter changed, and says in its own comment that "the same staleness still
   *  applies to a price edited after a generate". That was survivable while this card named no
   *  figure. It stopped being survivable when it started naming one: the card would print the
   *  draft's current price beside documents containing the old one, which is the same sentence
   *  that has burned this page twice — the claim's input was not the input the document was built
   *  from.
   *
   *  So the price the payload was ACTUALLY filled with is stamped beside the result at generate
   *  time, and a disagreement sends the estimator back to a live Generate button instead of to
   *  downloads that are quietly out of date. Compared as NUMBERS with the same cent tolerance
   *  publishDrift uses: `lump_sum_display` is #tb-total's own text and `total_formatted` is
   *  fmtUSDdoc() of the number parsed out of it, so the two are the same quantity formatted by
   *  two different functions and a string compare would report drift on every project.
   *
   *  A draft generated BEFORE this shipped carries no stamp. Unknown is not the same as changed,
   *  so those keep their downloads rather than every already-generated project demanding a
   *  regenerate on the day this lands. */
  function priceMovedSinceGenerate(st) {
    const built = money(st.generated_lump_sum);
    const now = money(st.lump_sum_display);
    if (built == null || now == null) return false;
    return Math.abs(built - now) >= 0.01;
  }

  /** Put the price on the generated card, or take the row away entirely.
   *
   *  Read LIVE rather than off the module-top `state` snapshot: doGenerate leaves that snapshot
   *  behind the setState it just made, and the stamp is written in the same call — so a snapshot
   *  read here would show the PREVIOUS build's figure on the very visit that produced a new one.
   *  That is the one-shot-snapshot trap this codebase keeps meeting, and money is the worst place
   *  to meet it again.
   *
   *  The stamp first, because it is the figure the document was actually filled with.
   *  `lump_sum_display` is the fallback for a project generated before the stamp existed — and by
   *  the time this runs the mode decider has already established the two agree, or sent the
   *  estimator to a Generate button instead.
   *
   *  No figure means no row. A "—" where money belongs reads as zero, and a zero on the card an
   *  estimator checks a price on is worse than saying nothing. */
  function paintLumpSum() {
    const live = TW.getState() || {};
    // THE SAVED DOCUMENT'S OWN TOTAL FIRST. Every Download and Send now builds from the saved
    // proposal_payload, so its Total is the price in the files by construction. The stamp and
    // the display are figures from an EARLIER moment: /documents records the build only the first
    // time, and the pricing sidebar re-prices the payload without Continue ever rewriting
    // lump_sum_display. Hanz, 2026-09-25, on staging: the base bid moved to $14,224 (the editor and
    // the downloaded file both said so) and this card still read $7,447.
    const pp = live.proposal_payload;
    const docTotal = pp && pp.values && typeof pp.values.total_formatted === "string"
      && money(pp.values.total_formatted) != null ? pp.values.total_formatted : "";
    const lump = docTotal || live.generated_lump_sum || live.lump_sum_display || "";
    const row = document.getElementById("lump-row");
    const val = document.getElementById("lump-sum");
    if (!row || !val) return;
    // `el.hidden`, never a style write: .fp-money carries its own [hidden] rule precisely because
    // a class `display` beats the attribute, and a style write here would go on to fight both.
    if (money(lump) == null) { row.hidden = true; return; }
    val.textContent = lump;
    row.hidden = false;
  }

  // ─── Decide which mode to show ────────────────────────────────────
  // Wait for initDraftSync to settle draft ownership first: for a foreign /
  // mis-keyed blob it reloads the page (and this promise never resolves), so
  // files-mode can't POST /api/generate from the previous draft's data.
  (async () => {
    try { await (TW.draftReady || Promise.resolve()); } catch {}
    // initDraftSync has adopted this project's own copy and is reloading the page onto it, so
    // everything below would run on the blob it just replaced. The reload decides instead.
    if (TW.reloadPending && TW.reloadPending()) return;
    let st = TW.getState();
    // ── THE DOOR ────────────────────────────────────────────────────────────────────────────
    // Hanz, 2026-09-25: "Clicking to Done should regenerate and make the proposal correctly."
    // Everything on this page — Download, Send, the customer's PDF — is built from the SERVER's
    // saved `proposal_payload`, and only the Proposal step's Continue composes one. Every other
    // way in (the Files pill from Intake or Estimate, the Polish beta's Files link, View files off
    // the board, a reload, a typed URL) used to show the document from the LAST Continue,
    // whatever had changed since: a texture picked on the Estimate step, a re-price, a note, the
    // tax mode, a base flip. So the page asks first whether the document is the one the draft
    // describes now (TW.documentHolds: the key TW.composeKey stamps at Continue), and when it is
    // not, sends the estimator through the Proposal step to have it built (proposal-review.js
    // composeForFiles), which comes straight back here. REPLACE, so Back from here is not a page
    // that bounces forward again.
    //
    // ASKED OF THE SERVER'S COPY, because that is what Download and Send render — and never
    // answered by building from this browser's copy when that is older. initDraftSync does not
    // re-read a blob already stamped for this draft, so a colleague's revision, Troy marking the
    // job Won or an Estimate-step edit on another machine never reaches it; composing from it and
    // saving would put the old copy back over all of that. TW.reconcileWithServer reads the
    // server first: a local copy with nothing the server lacks is REPLACED by the server's, and
    // the question is then asked of that. A local copy that is the server's plus changes whose save
    // never landed ("ahead": nobody has saved the server's since) goes through the door, which
    // builds it and saves it — that loses nothing of anyone's. A current document is left alone
    // and nothing is written. `composedHere` is the loop guard — a page built from this draft a
    // moment ago is never sent round again, and a send is still checked against the key (see the
    // Send button).
    //
    // AND NEVER THROUGH THE DOOR ON A COPY THAT IS NOT KNOWN TO BE SAFE TO SAVE. The Proposal step
    // saves the page's whole copy as it loads (its pricing rebuild), so sending a copy there is
    // saving it. Review of fix 4, 2026-09-25: Kyle's note went to the server as his tab closed,
    // with nobody left to record that it had; RJ then re-priced to $15,000 and Troy marked the job
    // Won; Kyle's View files found his copy "kept", sent it through the door, and the Proposal
    // step's load put his $10,000 copy back over both. A copy where both sides have moved
    // ("kept"), one with no record to tell ("unknown"), or one the server could not be asked about,
    // stops here and says so. The way on from "kept" is the estimator's own choice to load the saved
    // copy; from "unknown" it is theirs too, the saved copy or this browser's.
    if (st.project_name && !composedHere) {
      const toDoor = () => location.replace(TW.withDraft("/proposal-review.html?compose=files"
                                                         + (filesMode ? "&files=1" : "")));
      const seen = await TW.reconcileWithServer();
      if (seen.status === "adopted") {
        // The server's copy now stands in this browser. Its document is current, or it goes
        // through the door; either way this page's module-top snapshot is the old copy, so it is
        // never shown — a current one is shown by a reload.
        if (TW.documentHolds(seen.server)) location.reload(); else toDoor();
        return;
      }
      // "unknown" is the same stop, in words that claim no more than is known: this browser has no
      // record of the saved copy (every browser's on deploy day), so it cannot tell an older copy
      // from one holding a save that never landed. Taking the server's copy unasked dropped such an
      // edit with nothing on screen (review of fix 4, round 3). So the choice is the estimator's,
      // and both ways are on the card: the saved copy, or this browser's. With only the first, an
      // edit whose save went as its page closed was dropped by the card's one button, where the same
      // edit with a record was built and saved (review of fix 4, round 4).
      if (seen.status === "kept" || seen.status === "unknown") {
        const known = seen.status === "kept";
        const couldNotRead = () => {
          const p = emptyEl.querySelector(".lede");     // a button that does nothing is no way on
          if (p) p.textContent = "The saved copy could not be read, so nothing changed. Check "
                               + "your connection, then press the button again.";
        };
        showDoorStop(known ? "This project was changed somewhere else"
                           : "This browser's copy doesn't match the saved project",
          known
            ? "This browser has changes to it that never reached the server, and the saved project has "
              + "changed since, maybe on someone else's computer. Nothing was rebuilt or saved. Load the "
              + "saved copy to carry on from it. Changes that were only in this browser are dropped."
            : "This browser holds a copy of this project that is not the one saved on the server, and "
              + "it can't tell which of the two is newer. Nothing was rebuilt or saved. Load the saved "
              + "copy to carry on from it, and anything that was only in this browser is dropped. Or "
              + "keep this browser's copy: it is rebuilt and saved in place of the saved project, and "
              + "anything saved on another computer since this browser last had it is lost.",
          "Load the saved copy",
          async () => {
            if (await TW.useServerCopy()) { location.reload(); return; }
            couldNotRead();
          },
          known ? null : { label: "Keep this browser's copy",
                           onPress: async () => {
                             if (await TW.keepLocalCopy()) { location.reload(); return; }
                             couldNotRead();
                           } });
        return;
      }
      // "unreachable" stops whatever this browser's own copy says. Carrying on from it was going on
      // from a copy nobody had checked: the files shown are the server's, and this page's copy
      // could be a day old (review of fix 4, round 2).
      if (seen.status === "unreachable") {
        showDoorStop("Couldn't check the saved project",
          "The server could not be reached, so this page could not check its files against your "
          + "latest changes. Check your connection, then reload this page.",
          "Reload this page", () => location.reload());
        return;
      }
      if (seen.status === "ahead" || !TW.documentHolds(seen.server)) { toDoor(); return; }
      st = TW.getState();
    }
    const res = st.generate_result;
    // Decided HERE rather than in proposal-review's Continue, where the cover-letter version of
    // this lives. Every route into this page has to be covered — the Files step pill, "View
    // files" off the Projects list, a reload, a second tab — and only this one is on all of them.
    const stale = !!res && priceMovedSinceGenerate(st);
    if (filesMode && (st.proposal_payload || st.project_name || st.job_name)) {
      viewFiles();                       // generate fresh + show downloads
    } else if (res && !stale) {
      showPostGenerate(res);             // already generated — show the buttons, which build fresh
    } else if (st.proposal_payload && st.project_name) {
      showPreGenerate();                 // ready to generate — show review card
    } else if (res) {
      showPostGenerate(res);             // priced-out but nothing better to offer than the files
    } else {
      emptyEl.style.display = "";        // no project in flight
    }
  })();

  /** The door stopping: the empty-state card says why, and its button is the way on — or its two
   *  buttons, when `alt` ({label, onPress}) offers a second. Nothing is built, shown or written —
   *  until the estimator presses one. */
  function showDoorStop(title, lede, label, onPress, alt) {
    emptyEl.style.display = "";
    const h = emptyEl.querySelector("h1");
    if (h) h.textContent = title;
    const p = emptyEl.querySelector(".lede");
    if (p) p.textContent = lede;
    const a = emptyEl.querySelector(".actions a");
    if (a) {
      a.textContent = label;
      a.addEventListener("click", (e) => { e.preventDefault(); onPress(); });
    }
    const b = alt ? emptyEl.querySelector(".actions a.door-alt") : null;
    if (b) {
      b.textContent = alt.label;
      b.style.display = "";
      b.addEventListener("click", (e) => { e.preventDefault(); alt.onPress(); });
    }
  }

  // Generate the files for a saved project and jump straight to downloads.
  async function viewFiles() {
    emptyEl.style.display = "";
    emptyEl.querySelector("h1").textContent = "Preparing files…";
    const lede = emptyEl.querySelector(".lede");
    if (lede) lede.textContent = "Generating the estimate, proposal, and PDF for this project — a few seconds.";
    // viewFiles auto-runs on load; auth.js sets the bearer token asynchronously,
    // so wait for it before the (auth-gated) render or we'd 401.
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    try {
      const out = await freshDocuments();
      emptyEl.style.display = "none";
      showPostGenerate(out);
    } catch (err) {
      emptyEl.querySelector("h1").textContent = "Couldn't load files";
      if (lede) lede.textContent = "Generating failed: " + (err.message || err) +
        ". Try “Open / Edit” from Projects instead.";
    }
  }

  /** The document the estimator CHECKED: the `render_id` of the last file downloaded on this page.
   *
   *  Send hands it back as `document_render_id`, and the server refuses the send unless the
   *  document it is about to freeze has the same key — so a colleague's save, an older copy of
   *  this page written back, or a deploy landing between the Download and the Send can no longer
   *  freeze a document nobody looked at. Held in memory, for this page view only: a download is a
   *  check of what was on screen then, and a key remembered across visits would refuse next
   *  week's revised send for having changed, which is the point of revising. Empty until a
   *  download succeeds, and then Send carries nothing and is checked as it always was. */
  const checkedDocument = { renderId: "" };

  /** THE FILES, BUILT WHEN THEY ARE ASKED FOR, FROM THE SAVED DRAFT.
   *
   *  Hanz, 2026-09-25: "Sending out the proposal should be the same PDF from the download button
   *  in the last page." It was not. Download fetched the token kept in `generate_result` — files
   *  built from whatever payload the last generate had been handed, alive in server memory for up
   *  to an hour — while Send pinned the SAVED `proposal_payload`. Change the texture, the tax mode
   *  or a note after a generate, press Continue, and the estimator downloaded and checked one
   *  document while the customer was sent another.
   *
   *  So every button on this page asks for its files fresh: flush this page's pending save, then
   *  POST /api/draft/{id}/documents, which renders the STORE'S copy of `proposal_payload` through
   *  the same server function Send uses. What ties a Download to the Send after it is the
   *  `render_id` the answer carries (which payload, templates and code built the file): downloadAs
   *  keeps it in `checkedDocument`, Send hands it back, and the server refuses a send whose
   *  document no longer has that key. Nothing on this page downloads from `generate_result`.
   *
   *  AND NOTHING ON THIS PATH WRITES THE DRAFT. This page's copy of the draft can be OLDER than
   *  the server's — initDraftSync does not re-read a blob already stamped for this draft, so a
   *  colleague's Continue on another computer never reaches it — and TW.setState PUTs the whole
   *  blob. Recording the build with setState therefore wrote the colleague's revision away on
   *  every Download press. The server records `has_files` itself (/documents), and this page only
   *  remembers the build locally. The card's figure is the one the SERVER rendered
   *  (`document_total`), not this page's copy of it.
   *
   *  NO SAVED PAYLOAD, NO FILES. There used to be a second builder here for a draft never taken
   *  through the Proposal step's Continue: it posted the draft's own fields to /api/generate, and
   *  its own comment said it "still drops paragraph_overrides / remodel / rooms". That was a way
   *  to put a document in front of the estimator — and, through the files it recorded, in front of
   *  a customer — that no Proposal step had ever composed. The page's door (the mode decider)
   *  sends a draft with no document through the Proposal step first, so a press that still finds
   *  none refuses instead. A draft with no id (never saved) has nothing for the server to read,
   *  so its composed payload itself goes to /api/generate. */
  async function freshDocuments(draftVersion) {
    if (!await TW.flushState()) {
      throw new Error("Couldn't save your latest changes, so the files were not built — "
                      + "check your connection and try again.");
    }
    const st = TW.getState() || {};
    const draftId = TW.getDraftId();
    const pp = st.proposal_payload;
    if (!pp || typeof pp !== "object" || !pp.values || typeof pp.values !== "object") {
      throw new Error("This proposal hasn't been put together yet. Open the Proposal step and "
                      + "press Continue to Done, then come back here.");
    }
    if (draftId) {
      // `draftVersion`, when a Download asked the question of the server's copy first
      // (TWPrice.confirmSavedCopy): when the server stored that copy. The server builds nothing
      // from a draft stored again since, so the file is the copy he was asked about.
      const out = await TW.postJSON("/api/draft/" + encodeURIComponent(draftId) + "/documents",
                                    draftVersion ? { draft_version: draftVersion } : {});
      TW.setLocalState({ generate_result: out, generated_lump_sum: (out && out.document_total) || null });
      return out;
    }
    const out = await TW.postJSON("/api/generate", pp);
    TW.setState({ generate_result: out, generated_lump_sum: builtAt(pp) });
    return out;
  }

  function fmtUSD(n) {
    return "$" + Number(n || 0).toLocaleString(undefined,
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  // ─── "Send to customer portal" recipients modal ───────────────────────
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  const MAX_PORTAL_EMAILS = 10;

  // TW.postJSON flattens a non-2xx into Error("POST … → 400: {\"detail\":\"…\"}").
  // Pull the human message back out for the modal's inline error line.
  function portalErrMsg(err) {
    const s = String((err && err.message) || err || "");
    const m = /"(?:detail|error)"\s*:\s*"([^"]+)"/.exec(s);
    if (m) return m[1];
    return s || "Send failed — try again.";
  }

  // The code the server answers a refused publish with. One value, and it is the switch: the
  // sentence in `error` is for humans and may be reworded any day, so nothing branches on it.
  const STALE_DOCUMENT_CODE = "stale_document";

  /** The server's own refusal of a stale-document send, or null for any other failure.
   *
   *  THE THIRD LAYER, and it exists because the first two cannot see everything. The gate in
   *  the Send handler judges this browser's blob; the server judges the blob it is about to
   *  snapshot, which is the one that counts when an edit lands from another tab, another
   *  device, or a colleague between the flush and the write. On 409 the server has written
   *  nothing and sent no email, so this is still a refusal and not a report.
   *
   *  It reads the body back out of the thrown message, the same way portalErrMsg above does:
   *  TW.postJSON flattens a non-2xx into Error("POST … → 409: <body>"). Parsing here rather
   *  than teaching postJSON to carry structured errors keeps the blast radius to this page --
   *  that function is called from every screen in the tool.
   *
   *  Branches on `code` alone. Not the status line, which is a format, and not the sentence,
   *  which is copy. */
  function staleDocRefusal(err) {
    const text = String((err && err.message) || err || "");
    const i = text.indexOf("{");
    if (i < 0) return null;
    let body;
    try { body = JSON.parse(text.slice(i)); } catch { return null; }
    if (!body || typeof body !== "object" || body.code !== STALE_DOCUMENT_CODE) return null;
    // `snapshot` is documented as byte-identical in shape to a successful send's
    // `sent_snapshot`, which is what makes this a mapping and not a second comparison: it
    // drops straight into the same TW.docDrift the gate and the panel already use.
    return body;
  }

  // Inline recipients editor on the Files page — shown BEFORE sending (no popup).
  // The intake email is a fixed row; the estimator adds/removes extra recipients;
  // the "Send to customer portal" button sends to the whole list. Every recipient
  // gets a secure link + full portal access (view / ask / approve). Exposes a few
  // methods on `portalRecip` for the button handler below.
  // `noFollowups` is the set of addresses the sender un-ticked. Hanz, 2026-08-12: "just like the
  // 25% deposit creat a checkbox for each contact if they will be able to receive the automated
  // follow ups or no". Stored as an opt-OUT set rather than an opt-in list so the default — chase
  // everybody, which is how it has always worked — needs no entry at all.
  const portalRecip = { intake: "", hasIntake: false, extras: [], noFollowups: [], ready: false };

  // ── Require deposit ─────────────────────────────────────────────────────────
  // Ticked → the customer must pay the 25% deposit after approving (today's
  // behaviour). Unticked → the portal requests no deposit at all: no invoice, no
  // Deposit step. Direct work defaults to requiring one, GC work does not, but
  // either can be overridden per send for edge cases.
  //
  // Read state fresh rather than trusting a module-level snapshot: the Files page
  // is reachable both straight after generating and via ?files=1 on a reload.
  function mountRequireDeposit() {
    const el = document.getElementById("portal-require-deposit");
    if (!el) return;
    let st = {};
    try { st = TW.getState() || {}; } catch {}
    const isGC = String(st.audience || "Direct").trim().toUpperCase() === "GC";
    // A previously-sent choice wins over the audience default.
    el.checked = (typeof st.require_deposit === "boolean") ? st.require_deposit : !isGC;
    const hint = document.getElementById("portal-require-deposit-hint");
    if (hint) hint.textContent = isGC ? "(off by default for GC work)" : "(25% on approval)";
  }

  // ── Sent versions (revisions) ───────────────────────────────────────────────
  // Each send snapshots the estimate, so a revised price reuses this project rather
  // than forcing a duplicate — and every version stays downloadable. A revision sent
  // since 2026-09-25 hands back the proposal files it was SENT with (stored at send
  // time); an older one, and every revision's workbook, is rebuilt from the snapshot.
  async function mountRevisions() {
    const box = document.getElementById("revisions-box");
    const list = document.getElementById("revisions-list");
    if (!box || !list) return;
    const draftId = TW.getDraftId();
    if (!draftId) return;
    let revs = [];
    try {
      const r = await fetch(TW.absoluteUrl("/api/draft/" + encodeURIComponent(draftId) + "/revisions"),
                            { headers: TW.authHeaders() });
      if (!r.ok) return;                       // never block the page on history
      revs = (await r.json()).revisions || [];
    } catch { return; }
    if (!revs.length) { box.style.display = "none"; return; }
    const fmtDate = (s) => (window.TW && TW.fmtBizDate) ? TW.fmtBizDate(s)
      : new Date(s).toLocaleDateString("en-US");
    // Whole dollars, LOSSLESSLY: a trailing ".00" is dropped, a real fraction is kept. Same rule
    // as portal.js's money() and proposal-review.js's fmtUSDdoc, so a revision row reads the same
    // figure as the proposal that revision actually sent. NOT maximumFractionDigits: 0 -- that
    // would round a fractional total and this list is the basis-and-transparency record. The em
    // dash guard stays as it was: a revision with no total is UNKNOWN, not zero.
    const money = (n) => {
      if (n == null) return "—";
      const s = "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      return s.endsWith(".00") ? s.slice(0, -3) : s;
    };
    // Classes, not inline styles: this row lives in the send screen's right-hand rail now, where
    // it is ~380px wide, and the three download buttons have to WRAP onto their own line rather
    // than crush the price. `.rev-acts` carries the flex-basis that does it — a rule an inline
    // style could never hold, because an inline style has no media query and no container.
    list.innerHTML = revs.map((rv, i) => `
      <div class="rev-row">
        <span class="rev-no">Rev ${rv.revision_no}</span>
        ${i === 0 ? '<span class="rev-cur">current</span>' : ""}
        <span class="hint">${fmtDate(rv.created_at)}</span>
        <span class="hint">${rv.created_by
          ? window.TWCrm.avatarHtml(rv.created_by) + esc(window.TWCrm.nameOf(rv.created_by))
          : "—"}</span>
        <strong class="rev-money">${money(rv.total)}</strong>
        ${rv.has_documents ? `
          <span class="rev-acts">
            <button class="btn-secondary rev-dl" type="button" data-rev="${rv.revision_no}" data-kind="xlsx">.xlsx</button>
            <button class="btn-secondary rev-dl" type="button" data-rev="${rv.revision_no}" data-kind="docx">.docx</button>
            <button class="btn-secondary rev-dl" type="button" data-rev="${rv.revision_no}" data-kind="pdf">PDF</button>
          </span>`
        : '<span class="hint">no documents</span>'}
      </div>`).join("");
    box.style.display = "";
    // Delegated: the list is re-rendered after every send.
    if (!list.dataset.wired) {
      list.dataset.wired = "1";
      list.addEventListener("click", (e) => {
        const b = e.target.closest(".rev-dl");
        if (b) downloadRevision(b.dataset.rev, b.dataset.kind, b);
      });
    }
  }

  /** Fetch one revision's documents and download the requested one. Separate
   *  from the main downloadAs(): that one renders the LIVE draft's saved payload,
   *  which is exactly what an old revision must NOT be rendered from. */
  async function downloadRevision(revNo, kind, button) {
    const draftId = TW.getDraftId();
    if (!draftId) return;
    const orig = button.textContent;
    button.disabled = true; button.textContent = "…";
    try {
      const out = await TW.postJSON(
        "/api/draft/" + encodeURIComponent(draftId) + "/revisions/" + encodeURIComponent(revNo) + "/files", {});
      const key = kind === "xlsx" ? "xlsx_download_url"
        : kind === "docx" ? "docx_download_url" : "pdf_download_url";
      const url = out && out[key];
      if (!url) throw new Error("That document isn't available for this revision.");
      const resp = await fetch(TW.absoluteUrl(url), { headers: TW.authHeaders() });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const safe = String((out.project_name || TW.getState().project_name || "proposal"))
        .replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 60);
      const ext = kind === "pdf" ? "pdf" : kind;
      const name = `${safe}_rev${revNo}_${kind === "xlsx" ? "estimate" : "proposal"}.${ext}`;
      // octet-stream so the browser saves under our name instead of letting the
      // inline PDF viewer hijack the click (same reason as the main downloads).
      const blobUrl = URL.createObjectURL(new Blob([await resp.arrayBuffer()],
                                                  { type: "application/octet-stream" }));
      const a = document.createElement("a");
      a.href = blobUrl; a.download = name;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);
      button.innerHTML = icon("check", 14);
    } catch (err) {
      console.error("Revision download failed", err);
      button.textContent = "failed";
    }
    setTimeout(() => { button.textContent = orig; button.disabled = false; }, 1800);
  }

  // ── Assigned estimator ──────────────────────────────────────────────────────
  // Required at send: the assignee owns the follow-up cadence, gets the "not viewed"
  // and "make it personal" notes, and appears in their morning digest. Unassigned
  // means nobody chases it, which is the failure this whole system exists to fix.
  let _estimatorsPromise = null;

  // Names come from `profiles`, i.e. from whatever people typed into SSO — escape
  // before building option markup.
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function mountEstimatorPicker() {
    const sel = document.getElementById("portal-estimator");
    if (!sel) return;
    // Somebody may have assigned this project from the CRM drawer while this machine still held
    // an older copy of the blob — the full hydrate only runs for a DIFFERENT draft id, so that
    // change would otherwise be invisible here and the picker would read blank. Hanz, 2026-08-13:
    // "that estimator picker should also reflect in the Section 4 of the estimate."
    try { await TW.refreshServerOwned(); } catch {}
    let st = {};
    try { st = TW.getState() || {}; } catch {}
    // Memoised: showPostGenerate can run more than once per page.
    if (!_estimatorsPromise) {
      _estimatorsPromise = fetch(TW.absoluteUrl("/api/estimators"), { headers: TW.authHeaders() })
        .then(r => r.ok ? r.json() : { estimators: [] })
        .catch(() => ({ estimators: [] }));
    }
    const list = ((await _estimatorsPromise) || {}).estimators || [];
    const prev = String(st.assigned_estimator || "").toLowerCase();
    // A native <option> can't hold a coloured chip, so the initials ride in the label
    // instead — "KL · Kyle Loseke". Same names and the same initials as the chips
    // everywhere else; the colour is the one thing a select can't carry.
    sel.innerHTML = '<option value="">Choose the estimator…</option>'
      + list.map(e => `<option value="${esc(e.email)}">${esc(window.TWCrm.initialsOf(e.name || e.email))} · ${esc(e.name)}</option>`).join("");
    // A re-send remembers the last explicit choice, and so does a first send whose project was
    // assigned in the CRM — both are somebody's decision, which is the bar. What still starts
    // blank is a project nobody has assigned at all: the "Kyle?" guess on a card is the draft's
    // AUTHOR, not an assignment, and pre-selecting it would let one click promote a guess.
    if (prev && list.some(e => String(e.email).toLowerCase() === prev)) sel.value = prev;
    if (!list.length) {
      // Couldn't reach the list. Fail visibly rather than letting the send 400 with
      // a bare error the estimator can't act on.
      sel.innerHTML = '<option value="">Estimator list unavailable — reload the page</option>';
    }
  }

  const readAssignedEstimator = () =>
    (document.getElementById("portal-estimator") || {}).value || "";

  /** Who on the team hears about THIS send, chosen before pressing Send.
   *
   *  Hanz, 2026-08-19: "we need that notifcation sending selection in the Files. so we can select
   *  who receives it first." The Notification Sending page sets the standing default; this picks
   *  the exceptions for one job, next to the recipients it is being sent to.
   *
   *  HELD IN MEMORY, SENT WITH THE PUBLISH. Nothing is written when a chip is clicked, for a
   *  reason that is not stylistic: the per-project override table has a foreign key onto the
   *  proposal row, and on a FIRST send that row does not exist until the publish creates it — a
   *  write beforehand is refused by the portal. So the picks travel in the publish body and the
   *  portal applies them after it creates the row and before it decides who to notify. It also
   *  keeps the send a single request, which is what the flush-then-publish ordering depends on.
   *
   *  Deliberately NOT part of the draft blob: `refreshServerOwned` would overwrite in-progress
   *  picks, and this is a decision about one send rather than a property of the project. */
  // `isAdmin` / `me` decide which chips are toggleable — see paintNotifyChips. Both are filled in
  // from TWAuth when the roster loads; until then nothing is painted, so the defaults here only ever
  // apply to an unmounted control. Defaulting isAdmin to FALSE is the safe direction: the worst case
  // is a chip that looks read-only for a moment, not one that offers a change the server will refuse.
  const notifyPick = { roster: [], changed: {}, ready: false, isAdmin: false, me: "" };

  notifyPick.effective = (email) => {
    const person = notifyPick.roster.find(p => p.email.toLowerCase() === email.toLowerCase());
    if (!person) return false;
    const override = notifyPick.changed[email.toLowerCase()];
    return override === undefined ? person.base : override;
  };

  // Only what the estimator actually changed. Anybody left alone follows the roster, so an
  // untouched send forwards nothing and the request stays byte-for-byte the legacy one.
  notifyPick.adds = () => Object.keys(notifyPick.changed)
    .filter(e => notifyPick.changed[e] === true && !baseOf(e));
  notifyPick.mutes = () => Object.keys(notifyPick.changed)
    .filter(e => notifyPick.changed[e] === false && baseOf(e));

  function baseOf(email) {
    const person = notifyPick.roster.find(p => p.email.toLowerCase() === email.toLowerCase());
    return !!(person && person.base);
  }

  async function mountNotifyRoster() {
    const box = document.getElementById("notify-pick");
    const chips = document.getElementById("notify-pick-chips");
    if (!box || !chips) return;
    let list = [];
    try {
      const r = await fetch(TW.absoluteUrl("/api/portal/notify-recipients"),
                            { headers: TW.authHeaders() });
      const j = r.ok ? await r.json() : {};
      // 'general' only: a deposit-kind row is for deposit alerts, not for "we sent a proposal".
      list = (j.recipients || []).filter(x => x.kind === "general");
    } catch { list = []; }
    // Nobody configured, or the roster is unreachable: say nothing rather than showing an empty
    // control that implies the send tells no one. The standing roster still applies server-side.
    if (!list.length) { box.hidden = true; return; }
    notifyPick.roster = list.map(x => ({ email: x.email, base: x.enabled !== false }));
    // Whatever was chosen in the CRM drawer before this project was sent. That control writes the
    // draft (an unsent project has no portal row to override against), and this is the screen that
    // carries the decision into the send — so it has to open showing what was already decided
    // rather than silently discarding it.
    notifyPick.changed = {};
    try {
      const saved = (TW.getState() || {}).notify_picks || {};
      (saved.add || []).forEach(e => { notifyPick.changed[String(e).toLowerCase()] = true; });
      (saved.mute || []).forEach(e => { notifyPick.changed[String(e).toLowerCase()] = false; });
    } catch {}
    // Who is looking, so paintNotifyChips knows which chips they may touch. Read the same way the
    // Notification Sending page reads it, off TWAuth rather than from a role guessed here.
    try {
      const who = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
      notifyPick.me = String(who.email || "").toLowerCase();
      notifyPick.isAdmin = who.role === "admin" || who.role === "super_admin";
    } catch { notifyPick.isAdmin = false; notifyPick.me = ""; }
    notifyPick.ready = true;
    box.hidden = false;
    paintNotifyChips();
  }

  function paintNotifyChips() {
    const chips = document.getElementById("notify-pick-chips");
    const why = document.getElementById("notify-pick-why");
    if (!chips) return;
    const estimator = String(readAssignedEstimator() || "").toLowerCase();
    chips.innerHTML = notifyPick.roster.map(person => {
      const on = notifyPick.effective(person.email);
      // The assigned estimator hears about the job whether or not they sit on the roster (the
      // portal folds them in), so the chip says so instead of offering to add somebody who is
      // already coming. A mute still wins, so it stays clickable.
      const owns = person.email.toLowerCase() === estimator;
      // Only an admin may toggle somebody else, exactly as the Notification Sending page has always
      // had it — and now enforced server-side too, so an ungated chip would just 403. Rendered as a
      // plain span rather than a disabled button: a disabled control invites clicking and explains
      // nothing, and the sentence below says who may change what.
      const mayToggle = notifyPick.isAdmin || person.email.toLowerCase() === notifyPick.me;
      const cls = 'nt-chip' + ((on || owns) ? ' on' : '') + (mayToggle ? '' : ' nt-chip-ro');
      const label = '<span class="nt-av">' + esc(window.TWCrm.initialsOf(person.email)) + "</span>"
        + esc(window.TWCrm.nameOf(person.email));
      const title = esc(person.email + (owns ? " — owns this job, so always told" : "")
        + (mayToggle ? "" : " — only an admin can change this"));
      if (!mayToggle) return '<span class="' + cls + '" title="' + title + '">' + label + "</span>";
      return '<button type="button" class="' + cls + '"'
        + ' data-notify="' + esc(person.email) + '"'
        + ' title="' + title + '">' + label + "</button>";
    }).join("");
    if (why) {
      const n = notifyPick.roster.filter(p => notifyPick.effective(p.email)).length;
      const how = notifyPick.isAdmin ? "Click to change." : "You can change only your own.";
      why.textContent = n
        ? n + " of " + notifyPick.roster.length + " will be told this went out. " + how
        : "Nobody will be told this went out. " + how;
    }
  }

  // Delegated, because the chips are rebuilt whenever the estimator changes.
  document.addEventListener("click", (e) => {
    const chip = e.target.closest && e.target.closest("[data-notify]");
    if (!chip) return;
    const email = chip.getAttribute("data-notify").toLowerCase();
    const now = notifyPick.effective(email);
    // Back to the roster's own answer → forget the deviation entirely, so an untouched-in-effect
    // send sends nothing rather than an override that happens to agree.
    if (!now === baseOf(email)) delete notifyPick.changed[email];
    else notifyPick.changed[email] = !now;
    paintNotifyChips();
  });

  function readRequireDeposit() {
    const el = document.getElementById("portal-require-deposit");
    // Missing element (older cached page) → fall back to the audience default so a
    // Direct customer never silently loses their deposit requirement.
    if (el) return !!el.checked;
    try { return String((TW.getState() || {}).audience || "Direct").trim().toUpperCase() !== "GC"; }
    catch { return true; }
  }

  function mountPortalRecipients() {
    const box = document.getElementById("portal-recipients");
    if (!box) return;
    const st = TW.getState();
    const intake = String(st.contact_email || "").trim();
    portalRecip.intake = intake;
    portalRecip.hasIntake = !!intake && EMAIL_RE.test(intake);
    const saved = Array.isArray(st.portal_emails) ? st.portal_emails : [];
    portalRecip.extras = saved
      .map(e => String(e || "").trim())
      .filter(e => e && EMAIL_RE.test(e) && (!portalRecip.hasIntake || e.toLowerCase() !== intake.toLowerCase()));

    box.innerHTML =
      '<div class="tw-em-label">Recipients</div>' +
      '<div class="tw-em-list"></div>' +
      '<div class="tw-em-add"><input type="email" placeholder="Add another email — name@company.com" autocomplete="off">' +
      '<button type="button" class="tw-em-addbtn">Add</button></div>' +
      '<p class="tw-em-err"></p>';

    const listEl = box.querySelector(".tw-em-list");
    const addInput = box.querySelector(".tw-em-add input");
    const addBtn = box.querySelector(".tw-em-addbtn");
    const errEl = box.querySelector(".tw-em-err");

    const setErr = (m) => { errEl.textContent = m || ""; };
    const allEmails = () => (portalRecip.hasIntake ? [portalRecip.intake] : []).concat(portalRecip.extras);
    // Only the un-ticked ones that are actually being SENT to. An address removed after being
    // un-ticked, or an intake edited to something else, must not travel as an opt-out for a
    // recipient that no longer exists.
    portalRecip.noFollowupsToSend = () => {
      const on = allEmails();
      return portalRecip.noFollowups.filter((e) => on.indexOf(e) >= 0);
    };

    // The intake email starts locked (it came from the customer's lead). "Edit"
    // unlocks it inline so the estimator can retarget the send — e.g. to their own
    // address for a test. The edit is a TRANSIENT send-target override only: it
    // changes who this send goes to, and deliberately does NOT persist back to the
    // draft's contact_email, so a test send can never overwrite the customer's real
    // email of record (which also feeds the estimate sheet + portal identity).
    let editingIntake = false;
    let editInput = null;   // the live <input> while the intake row is being edited
    let intakeDraft = null; // typed-but-unsaved value, preserved across re-renders
    let editJustOpened = false; // focus the editor only on first open, not every rebuild
    let intakeEdited = false;   // once retargeted, the row is no longer the raw intake

    // Commit an edited intake address into the in-memory send target. Validates and
    // folds a duplicate extra into the intake slot. Does NOT touch contact_email —
    // the send uses the emails list, and persisting would corrupt customer data.
    // Returns true on success, false (+ inline error) on an invalid address so the
    // caller can block — the send guard relies on this.
    function saveIntake(val) {
      const v = String(val || "").trim();
      if (!EMAIL_RE.test(v)) { setErr("That doesn’t look like an email address."); return false; }
      const lc = v.toLowerCase();
      portalRecip.extras = portalRecip.extras.filter(e => e.toLowerCase() !== lc);
      portalRecip.intake = v;
      portalRecip.hasIntake = true;
      intakeEdited = true;
      editingIntake = false; editInput = null; intakeDraft = null; setErr(""); renderList();
      return true;
    }

    function renderList() {
      // Preserve an in-progress intake edit across incidental rebuilds (e.g. the
      // user adds/removes another recipient mid-edit) so Send can't silently revert
      // to the original address. A detached <input> keeps its .value.
      if (editingIntake && editInput) intakeDraft = editInput.value;
      listEl.textContent = "";
      const rows = (portalRecip.hasIntake ? [{ email: portalRecip.intake, fixed: true }] : [])
        .concat(portalRecip.extras.map(e => ({ email: e, fixed: false })));
      if (!rows.length) {
        const empty = document.createElement("div");
        empty.className = "tw-em-empty";
        empty.textContent = "No customer email on file — add one below.";
        listEl.appendChild(empty);
      }
      rows.forEach((r) => {
        // Hanz, 2026-08-13: "ccan you put the follow up checkbox to the right of edit outside
        // the container?" Each entry is a WRAPPER holding two things side by side: the bordered
        // row (email · tag · Edit/×) and, outside that border, the Follow-ups checkbox. The
        // checkbox is visibly not part of the recipient, which is the point — it is a decision
        // ABOUT the recipient, not one of its fields.
        const wrap = document.createElement("div");
        wrap.className = "tw-em-rowwrap";
        const row = document.createElement("div");
        row.className = "tw-em-row";

        // Intake row in edit mode: swap the locked label for an input + Save/Cancel.
        if (r.fixed && editingIntake) {
          const input = document.createElement("input");
          input.type = "email"; input.className = "em";
          input.value = (intakeDraft != null) ? intakeDraft : portalRecip.intake;
          input.setAttribute("aria-label", "Edit the recipient email");
          editInput = input;
          const save = document.createElement("button");
          save.type = "button"; save.className = "tw-em-editbtn"; save.textContent = "Save";
          const cancel = document.createElement("button");
          cancel.type = "button"; cancel.className = "tw-em-editbtn"; cancel.textContent = "Cancel";
          cancel.setAttribute("aria-label", "Cancel editing");
          const cancelEdit = () => { editingIntake = false; editInput = null; intakeDraft = null; setErr(""); renderList(); };
          save.addEventListener("click", () => saveIntake(input.value));
          cancel.addEventListener("click", cancelEdit);
          input.addEventListener("input", () => { intakeDraft = input.value; });
          input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") { e.preventDefault(); saveIntake(input.value); }
            else if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
          });
          row.appendChild(input); row.appendChild(save); row.appendChild(cancel);
          // No Follow-ups control while the address is being edited: the checkbox belongs to a
          // recipient, and mid-edit there is not a settled one to attach it to.
          wrap.appendChild(row);
          listEl.appendChild(wrap);
          // Focus only when the editor first opens — not on every incidental rebuild,
          // which would otherwise steal focus + reselect while the user is elsewhere.
          if (editJustOpened) { editJustOpened = false; setTimeout(() => { input.focus(); input.select(); }, 0); }
          return;
        }

        const em = document.createElement("span");
        em.className = "em"; em.textContent = r.email;
        row.appendChild(em);

        // Follow-ups for THIS contact. On the intake row too: the person the lead came from is
        // exactly who somebody might not want chased four times.
        const fu = document.createElement("label");
        fu.className = "tw-em-fu";
        fu.title = "Automated follow-up emails. Un-tick and this contact still gets the proposal, "
                 + "the invoice and every reply — just not the chasing.";
        const fuBox = document.createElement("input");
        fuBox.type = "checkbox";
        fuBox.checked = portalRecip.noFollowups.indexOf(r.email) < 0;
        fuBox.addEventListener("change", () => {
          const k = portalRecip.noFollowups.indexOf(r.email);
          if (fuBox.checked) { if (k >= 0) portalRecip.noFollowups.splice(k, 1); }
          else if (k < 0) portalRecip.noFollowups.push(r.email);
        });
        fu.appendChild(fuBox);
        fu.appendChild(document.createTextNode(" Follow-ups"));
        // NOT row.appendChild — it goes on the wrapper, after the row closes, so it renders
        // outside the bordered container and to the right of Edit.

        if (r.fixed) {
          const tag = document.createElement("span");
          tag.className = "tw-em-tag"; tag.textContent = intakeEdited ? "custom" : "intake";
          row.appendChild(tag);
          const edit = document.createElement("button");
          edit.type = "button"; edit.className = "tw-em-editbtn"; edit.textContent = "Edit";
          edit.setAttribute("aria-label", "Edit this recipient email to send to a different address");
          edit.addEventListener("click", () => {
            editingIntake = true; intakeDraft = portalRecip.intake; editJustOpened = true; setErr(""); renderList();
          });
          row.appendChild(edit);
        } else {
          const x = document.createElement("button");
          x.type = "button"; x.className = "tw-em-x"; x.textContent = "\u00d7";
          x.setAttribute("aria-label", "Remove " + r.email);
          x.addEventListener("click", () => {
            const k = portalRecip.extras.indexOf(r.email);
            if (k >= 0) portalRecip.extras.splice(k, 1);
            // Drop any opt-out with it. Otherwise removing an address and adding it back gives a
            // ticked box that is a lie: the stale entry would still suppress its follow-ups.
            const f = portalRecip.noFollowups.indexOf(r.email);
            if (f >= 0) portalRecip.noFollowups.splice(f, 1);
            setErr(""); renderList();
          });
          row.appendChild(x);
        }
        wrap.appendChild(row);
        wrap.appendChild(fu);      // outside the border, right of Edit / ×
        listEl.appendChild(wrap);
      });
    }

    // Add whatever is typed. Returns false (+ shows an error) on invalid residual
    // text so the send can block instead of silently dropping it.
    function tryAdd() {
      const v = addInput.value.trim();
      if (!v) return true;
      if (!EMAIL_RE.test(v)) { setErr("That doesn\u2019t look like an email address."); return false; }
      const lc = v.toLowerCase();
      if (allEmails().some(e => e.toLowerCase() === lc)) { setErr("That email is already in the list."); return false; }
      if (allEmails().length >= MAX_PORTAL_EMAILS) { setErr("Maximum " + MAX_PORTAL_EMAILS + " recipients."); return false; }
      portalRecip.extras.push(v); addInput.value = ""; setErr(""); renderList(); addInput.focus();
      return true;
    }

    addBtn.addEventListener("click", () => tryAdd());
    addInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); tryAdd(); } });

    portalRecip.allEmails = allEmails;
    portalRecip.tryAdd = tryAdd;
    // Flush a pending intake edit before a send, so clicking "Send" without first
    // clicking "Save" still uses the edited address (returns false to block on an
    // invalid in-progress edit).
    portalRecip.commitEdit = () => (!editingIntake) ? true : saveIntake(editInput ? editInput.value : portalRecip.intake);
    portalRecip.setErr = setErr;
    portalRecip.setBusy = (b) => { addInput.disabled = addBtn.disabled = !!b; };
    portalRecip.ready = true;
    renderList();
  }

  /** WHAT PAGE 1 WILL BE, ASKED ONCE, FOR BOTH SURFACES THAT SHOW IT.
   *
   *  Two places on this page talk about the cover letter — the pre-generate review row and the
   *  post-generate warning banner — and they must never disagree, because between them they are
   *  the only signal that the customer's document has a first page at all. They were separate
   *  reads for one day and immediately drifted: the banner was moved onto `proposal_payload` and
   *  the row was left on the top-level flag, so on the untick-without-Continue path the row
   *  promised a letterhead page for a document that would not have one.
   *
   *  `proposal_payload` IS THE SOURCE, not top-level state. That blob is what /api/generate builds
   *  from, what `create_revision` pins, and what `hasCoverLetter` reports to the portal — so
   *  reading it makes every claim on this page agree with the document by construction. The
   *  fallback mirrors `viewFiles`'s own, for a draft with no payload yet.
   *
   *  THE LIST IS NOT CACHED ANYWHERE. It is a pure function of (work_type, audience) read off the
   *  TEMPLATE, and the one thing this feature has proved repeatedly is that a remembered copy goes
   *  stale in a direction that reaches a customer. Asking twice on one page load is cheaper than
   *  one more stale-value defect.
   *
   *  BOUNDED. An 8s AbortController, because the caller is fire-and-forget: `showPostGenerate`
   *  yields at its first await and goes on to wire Send, so a request that hung forever would
   *  leave Send live with the banner never appearing and nothing on screen to explain it. A
   *  timeout turns "silent forever" into "could not be checked", which is a state both callers
   *  already render.
   *
   *  Returns `{enabled, hasLetter, placeholders}`. `enabled:false` means no letter is being built.
   *  `placeholders: null` means the check could not be made — never read that as "clean". */
  async function coverLetterCheck() {
    const st = TW.getState() || {};
    const pp = st.proposal_payload;
    const src = (pp && pp.values) ? pp : st;
    if (!src.cover_letter_enabled) return { enabled: false, placeholders: null };
    const out = { enabled: true, hasLetter: null, placeholders: null };
    try {
      // Awaited BEFORE the fetch, never alongside it: /api/default-notes shipped without this and
      // fired before the auth header existed, so brand-new projects silently missed their
      // boilerplate — a 401 that read as a missing feature (PR #124).
      if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready;
      const ctl = new AbortController();
      const bell = setTimeout(() => ctl.abort(), 8000);
      const q = "?work_type=" + encodeURIComponent(src.work_type || "epoxy")
              + "&audience=" + encodeURIComponent(src.audience || "Direct");
      let r;
      try {
        r = await fetch(TW.resolveApiBase() + "/api/cover-letter/placeholders" + q,
                        { headers: TW.authHeaders(), signal: ctl.signal });
      } finally {
        clearTimeout(bell);
      }
      // `r.ok` is load-bearing on its own. A gateway or an auth proxy answers a 502/401 with its
      // OWN json envelope, which can carry a perfectly well-formed `placeholders: []` — read
      // without the status check that is "page 1 is clean" from a request that never arrived.
      if (r.ok) {
        const j = await r.json();
        if (Array.isArray(j.placeholders)) {
          out.placeholders = j.placeholders.filter(s => String(s || "").trim());
          out.hasLetter = j.has_letter !== false;
        }
      }
    } catch (err) {
      console.error("cover-letter placeholder check failed", err);
    }
    return out;
  }

  function showPreGenerate() {
    preEl.style.display = "";
    // Show the project deadline as a compact YY.MM.DD due date.
    const dueDate = (iso) => {
      const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
      return m ? `${m[1].slice(2)}.${m[2]}.${m[3]}` : "—";
    };
    document.getElementById("rv-folder").textContent   = state.deadline ? dueDate(state.deadline) : "—";
    document.getElementById("rv-project").textContent  = state.project_name || "—";
    document.getElementById("rv-location").textContent = [state.address, state.city_state, state.zip].filter(Boolean).join(" · ") || "—";
    document.getElementById("rv-worktype").textContent = (state.work_type || "epoxy").toUpperCase();
    document.getElementById("rv-audience").textContent = state.audience || "Direct";
    // The total of the document Generate will build (the saved payload's), for the same reason
    // paintLumpSum reads it: lump_sum_display is not rewritten when the sidebar re-prices.
    const _rvPp = (TW.getState() || {}).proposal_payload;
    const _rvTotal = _rvPp && _rvPp.values && typeof _rvPp.values.total_formatted === "string"
      && money(_rvPp.values.total_formatted) != null ? _rvPp.values.total_formatted : "";
    document.getElementById("rv-lump").textContent     = _rvTotal || state.lump_sum_display || "—";
    // PAGE 1, SAID OUT LOUD, BEFORE ANYTHING IS BUILT. Through `coverLetterCheck` so this row and
    // the post-generate banner cannot come to disagree — see that function for why the source is
    // `proposal_payload` and not the top-level flag. The row is hidden rather than showing "No",
    // because a bid without a letter should look exactly as it did before this feature existed.
    //
    // IT ALSO REPORTS A WORK TYPE THAT HAS NO LETTER. /api/generate REFUSES those (sealer, budget)
    // rather than sending the epoxy fallback, so without this the estimator ticks the box, reads
    // "Yes — letterhead prints as page 1", presses Generate and meets a 400. `has_letter` exists
    // on the endpoint for exactly this and was read nowhere until now.
    (async function coverLetterRow() {
      const row = document.getElementById("rv-cover-row");
      const val = document.getElementById("rv-cover");
      if (!row || !val) return;
      const chk = await coverLetterCheck();
      if (!chk.enabled) { row.style.display = "none"; return; }
      if (chk.hasLetter === false) {
        val.textContent = "No letter is written for this work type — Generate will refuse until "
                        + "you untick it on the Proposal step";
      } else if (chk.placeholders === null) {
        val.textContent = "Yes — Treadwell letterhead prints as page 1 (its wording could not be "
                        + "checked from here)";
      } else if (chk.placeholders.length) {
        val.textContent = "Yes — Treadwell letterhead prints as page 1, and "
                        + chk.placeholders.length + " line"
                        + (chk.placeholders.length === 1 ? "" : "s")
                        + " on it still need your wording";
      } else {
        val.textContent = "Yes — Treadwell letterhead prints as page 1 of the proposal";
      }
      row.style.display = "";
    })();

    document.getElementById("back-btn-done").addEventListener("click", () => {
      window.location.assign(TW.withDraft("/proposal-review.html"));
    });
    document.getElementById("gen-btn").addEventListener("click", doGenerate);
  }

  /** The files going out WITH this proposal.
   *
   *  Held in the browser until Send, unlike the chat's attachments which upload the moment they
   *  are picked. That difference is forced: the chat always has a proposal row to hang an upload
   *  off, and a first send does not have one until the publish creates it.
   *
   *  So the cost is paid at Send instead — which is why the total is capped at 10 MB and said out
   *  loud on the page. Resend would take four times that; the customer's own mail server is the
   *  one that would bounce it, and they would find out from the customer.
   */
  const sendAtts = (() => {
    const MAX_TOTAL = 10 * 1024 * 1024;
    const MAX_ONE = 15 * 1024 * 1024;
    let items = [];
    const size = (n) => (n < 1024 ? n + " B"
      : n < 1024 * 1024 ? Math.round(n / 1024) + " KB"
      : (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0) + " MB");
    const total = () => items.reduce((a, b) => a + (b.size || 0), 0);

    function draw() {
      const strip = document.getElementById("send-atts");
      const note = document.getElementById("send-att-note");
      if (!strip) return;
      strip.innerHTML = items.map((a, i) => `
        <span class="att-chip">
          ${a.preview ? `<img src="${a.preview}" alt="">` : ""}
          <span class="att-name"></span>
          <span class="att-size">${size(a.size)}</span>
          <button type="button" class="att-x" data-att-remove="${i}" aria-label="Remove">&times;</button>
        </span>`).join("");
      // Names go in as TEXT, never as markup: a filename is the one string on this page that
      // came from outside it.
      strip.querySelectorAll(".att-name").forEach((el, i) => { el.textContent = items[i].name; });
      strip.hidden = !items.length;
      if (note) {
        note.textContent = items.length
          ? `${items.length} file${items.length > 1 ? "s" : ""} · ${size(total())} of 10 MB`
          : "";
      }
    }

    function add(files) {
      for (const f of Array.from(files || [])) {
        if (items.length >= 10) break;
        if (f.size > MAX_ONE) { alert(`${f.name} is larger than 15 MB.`); continue; }
        if (total() + f.size > MAX_TOTAL) {
          alert(`${f.name} would take this over 10 MB. Send the large files in the chat instead — `
                + `the customer gets them the same way, without risking the email bouncing.`);
          continue;
        }
        const image = /^image\//.test(f.type || "");
        items.push({ file: f, name: f.name || "attachment", size: f.size,
                     mime: f.type || "application/octet-stream",
                     preview: image ? URL.createObjectURL(f) : "" });
      }
      draw();
    }

    document.addEventListener("click", (e) => {
      if (e.target.closest("#send-attach")) {
        e.preventDefault();
        const inp = document.getElementById("send-file");
        if (inp) inp.click();
        return;
      }
      const rm = e.target.closest("#send-atts [data-att-remove]");
      if (!rm) return;
      const i = Number(rm.dataset.attRemove);
      if (items[i] && items[i].preview) URL.revokeObjectURL(items[i].preview);
      items.splice(i, 1);
      draw();
    });
    const inp = document.getElementById("send-file");
    if (inp) inp.addEventListener("change", (e) => { add(e.target.files); e.target.value = ""; });

    return {
      /** Read every file as base64, in parallel, at Send time.
       *
       *  Not at pick time: an estimator who attaches four photos and then removes three should
       *  not have paid to encode all four, and holding the encoded copies as well as the File
       *  objects doubles the memory for no gain.
       */
      payload: () => Promise.all(items.map((a) => new Promise((res) => {
        const r = new FileReader();
        r.onload = () => res({ name: a.name, mime: a.mime,
                               // readAsDataURL gives "data:<mime>;base64,<data>" — the server
                               // wants the data only.
                               b64: String(r.result || "").split(",")[1] || "" });
        r.onerror = () => res(null);
        r.readAsDataURL(a.file);
      }))).then((all) => all.filter(Boolean)),
      clear: () => {
        items.forEach((a) => { if (a.preview) URL.revokeObjectURL(a.preview); });
        items = [];
        draw();
      },
      count: () => items.length,
    };
  })();

  /** Put the stop sign on screen, or take it away.
   *
   *  `mode` only changes the opening line, and the opening line is the whole point: the same
   *  three numbers mean "do not send this" before a send and "the customer already has this"
   *  after one, and an estimator reading it at 11pm should not have to work out which. */
  /** The stale-document panel's fixed furniture: its heading, its how-to line, and whether the
   *  Update the PDF button applies at all. Two callers set it, so it is set in one place. */
  function paintStaleDocChrome(title, how, showFix) {
    const t = document.getElementById("stale-doc-title");
    const h = document.getElementById("stale-doc-how");
    const f = document.getElementById("stale-doc-fix");
    if (t) t.textContent = title;
    if (h) h.textContent = how;
    if (f) f.hidden = !showFix;
  }

  /** Stop the send because this browser cannot save, and say which one it is.
   *
   *  RJ, 2026-09-03: "I keep getting the below error message. I go back to the PDF and hit
   *  continue as the message says and everything appears to be correct but I keep getting the
   *  error message." He was right, and the screen was wrong. The drift it showed him was real,
   *  but the cure it named could not work: TW.setState refuses a write when the local blob
   *  belongs to a different draft than the page is on -- another tab of this tool -- and it
   *  refuses it silently, handing the caller back the unchanged blob. So Continue rebuilt a
   *  payload that went nowhere, this page found the same drift, and it pointed at Continue again.
   *
   *  flushState cannot tell us this: it resolves TRUE after dropping a save it was not allowed
   *  to make (see shared.js saveBlocked's own docstring). So ask saveBlocked directly, and ask it
   *  BEFORE blaming the document, because a document that cannot be rebuilt is a symptom here,
   *  not the fault. The words come from TW.saveBlockedSay, the same ones the Proposal step
   *  paints, so the two pages cannot come to describe one refusal two ways.
   *
   *  Returns true when it painted, i.e. when the caller must NOT send. */
  function showSaveBlocked() {
    let b = null;
    try { b = TW.saveBlockedSay ? TW.saveBlockedSay() : null; } catch { b = null; }
    if (!b) return false;
    const box = document.getElementById("stale-doc");
    if (!box) return false;
    // No Update the PDF button: pressing it is the loop.
    paintStaleDocChrome(b.say, b.fix, false);
    const lede = document.getElementById("stale-doc-lede");
    if (lede) lede.textContent = "Nothing was sent. Until this is sorted out, changes made on this tab are not being saved, so the document cannot be rebuilt from them.";
    const tab = document.getElementById("stale-doc-rows");
    if (tab) tab.textContent = "";   // the drift figures are not the story
    box.hidden = false;
    try { box.scrollIntoView({ block: "center", behavior: "smooth" }); } catch {}
    return true;
  }
  function showStaleDoc(rows, mode) {
    const box = document.getElementById("stale-doc");
    if (!box) return;
    if (!rows || !rows.length) { box.hidden = true; return; }
    // Put the panel's OWN words back first. showSaveBlocked below borrows this same box and
    // rewrites its title, its how-to and its button, so a drift shown after one of those would
    // otherwise inherit the wrong cure -- the panel would name the drift and then tell the
    // estimator to close a tab he has already closed.
    paintStaleDocChrome(
      "The PDF has the old numbers",
      "Update the PDF opens the Proposal step. Press Continue there and the document is rebuilt with these numbers, then you land back here to send.",
      true);
    const lede = document.getElementById("stale-doc-lede");
    if (lede) {
      lede.textContent =
        mode === "blocked" ? "Nothing was sent. Your changes are saved, but the document the "
                           + "customer would open was built before them."
      : mode === "sent"    ? "This one has already gone to the customer, and the document they "
                           + "can open was built before this pricing."
      :                      "Your changes are saved, but the document the customer would open "
                           + "was built before them. Sending now gives them the old figures.";
    }
    const tab = document.getElementById("stale-doc-rows");
    if (tab) {
      tab.textContent = "";
      // textContent throughout, never markup: a base bid's name is a worksheet label the
      // estimator typed, which makes it the one string in this panel from outside the page.
      const cell = (cls, text) => {
        const el = document.createElement("span");
        el.className = cls;
        el.textContent = text;
        tab.appendChild(el);
      };
      cell("sd-h", "");
      cell("sd-h", "The PDF says");
      cell("sd-h", "It should say");
      rows.forEach((r) => { cell("sd-k", r.k); cell("sd-was", r.pdf); cell("sd-now", r.now); });
    }
    box.hidden = false;
    if (mode === "blocked" || mode === "sent") {
      try { box.scrollIntoView({ block: "center", behavior: "smooth" }); } catch {}
    }
  }

  /** Compare the pricing the server just SENT against the pricing this page is showing.
   *  Returns a human sentence naming the difference, or "" when they agree.
   *
   *  The publish flush closes the same-tab race. This closes the rest: a second tab, another
   *  device, a colleague editing while you send. Only ever warns — the send has already
   *  happened and the portal is pinned, so the useful thing is to say WHAT differs.
   *
   *  Compares base label + lump sum + how many options a customer can pick, because those
   *  are the three things a wrong version gets wrong in a way that costs money. */
  function publishDrift(sent) {
    if (!sent || typeof sent !== "object") return "";     // older backend — nothing to compare
    const s = TW.getState() || {};
    const rooms = Array.isArray(s.rooms) ? s.rooms : [];
    const localBase = (rooms.find(r => r && r.is_base) || {}).name || null;
    const localOpts = rooms.filter(r => r && !r.is_base && r.show !== false).length;
    const localLump = s.proposal_lump_sum;
    const bits = [];
    if (sent.base_label && localBase && sent.base_label !== localBase) {
      bits.push("the base bid sent was " + sent.base_label + ", not " + localBase);
    }
    // TW.fmtUsd, not the local `money` in mountRevisions — that one is scoped to its own
    // function, and reaching for it here would be a ReferenceError at the moment somebody
    // most needs the warning.
    const usd = (n) => (window.TW && TW.fmtUsd) ? TW.fmtUsd(n) : String(n);
    const near = (a, b) => (a == null || b == null) ? a === b : Math.abs(Number(a) - Number(b)) < 0.01;
    if (!near(sent.lump_sum, localLump)) {
      bits.push("the price sent was " + usd(sent.lump_sum) + ", not " + usd(localLump));
    }
    if (typeof sent.option_count === "number" && sent.option_count !== localOpts) {
      bits.push("it sent " + sent.option_count + " option" + (sent.option_count === 1 ? "" : "s")
                + ", not " + localOpts);
    }
    // ── The DOCUMENT half of the same snapshot ────────────────────────────────────────────
    // BELT AND BRACES, AND BOTH ARE NEEDED. The pre-send gate in the Send handler refuses a
    // drifted publish before a request leaves this browser, and the server refuses one that
    // gets past it. This is the third layer: it reads the snapshot the server ACTUALLY took,
    // so it still speaks up when the drift arrived between the flush and the write, or from a
    // second tab, another device, or a colleague editing while you sent. The gate cannot see
    // any of those, and a send that lands drifted must never land silently.
    //
    // The rows come from the same TW.docDrift the gate and the panel use, so what a warning
    // calls a problem and what a gate refuses to send can never come apart.
    const rows = TW.docDrift(sent);
    if (rows.length) {
      bits.push("the PDF they can open was built before this pricing, and shows "
                + rows.map(r => r.say).join(", and ")
                + ". Press Update the PDF above, then send it again");
    }
    return bits.join("; ");
  }

  async function doGenerate() {
    const btn = document.getElementById("gen-btn");
    btn.disabled = true;
    btn.textContent = "Generating…";
    try {
      // The SAVED payload, through the render Send uses — not the module-top snapshot of it, which
      // is whatever this page loaded with (see freshDocuments).
      const out = await freshDocuments();
      // Swap views — pre → post
      preEl.style.display = "none";
      showPostGenerate(out);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "Generate Files →";
      alert("Generate failed: " + err.message);
    }
  }

  function showPostGenerate(result) {
    postEl.style.display = "";

    const wt = (state.work_type || "epoxy").toUpperCase();
    const audience = state.audience || "Direct";
    document.getElementById("project-line").textContent =
      `${state.project_name} · ${wt} · ${audience}`;

    paintLumpSum();

    // Carry the draft across so the info sheet opens on THIS project rather than
    // whichever one the browser last held.
    const infoLink = document.getElementById("info-sheet-link");
    if (infoLink) infoLink.href = TW.withDraft("/info-sheet.html");

    const safeName = (state.project_name || "proposal")
      .replace(/[^A-Za-z0-9._-]+/g, "_")
      .slice(0, 60);

    async function downloadAs(urlKey, filename, button) {
      const orig = button.textContent;
      button.disabled = true;
      try {
        // A PRICE LINE WITH A FIGURE OF HIS OWN: the question Send asks, asked BEFORE anything is
        // built or fetched (Hanz, 2026-09-26: warn on all three -- Send, Download, To Dropbox). One
        // check, TWPrice.confirmOwnFigures, asked of the copy the server is about to build, which
        // is not always this page's (TWPrice.confirmSavedCopy has the case). The estimate sheet
        // carries no price line, so its button is not asked. Cancel builds and fetches nothing.
        let checkedVersion = "";
        if (urlKey !== "xlsx_download_url") {
          const asked = await TWPrice.confirmSavedCopy(TW, "download", (q) => window.confirm(q));
          if (asked.failed) {
            throw new Error("Couldn't save your latest changes or read the saved proposal, so "
                            + "nothing was downloaded — check your connection and try again.");
          }
          if (!asked.go) { button.disabled = false; return; }
          checkedVersion = asked.version;
        }
        button.textContent = "Downloading…";
        // BUILT NOW, from the saved draft, through the render Send uses — never a token kept from
        // an earlier build. There used to be a 404 self-heal here that regenerated from the
        // module-top snapshot of the payload after a restart expired the kept token, so a download
        // could come from either of two payloads depending on server uptime. A token minted a
        // moment ago has nothing to heal. `checkedVersion`: the server builds nothing from a draft
        // saved again since the copy the question was asked of.
        const out = await freshDocuments(checkedVersion);
        paintLumpSum();
        const url = out && out[urlKey];
        if (!url) throw new Error("That file isn't available for this project.");
        // Downloads now require the Supabase bearer (no longer a public
        // capability URL) — TW.authHeaders() carries Authorization: Bearer.
        const resp = await fetch(TW.absoluteUrl(url), { headers: TW.authHeaders() });
        if (!resp.ok) throw new Error(resp.statusText || ("HTTP " + resp.status));
        // This is the document the estimator is about to read, so it is the one Send must freeze.
        // Recorded only once the file itself came back: a failed fetch checked nothing.
        checkedDocument.renderId = (out && out.render_id) || "";
        // Force a generic type so the browser DOWNLOADS the file under our
        // `a.download` name. If we kept the real type (application/pdf), Chrome's
        // inline PDF viewer hijacks the click, ignores the filename, and saves
        // it as the blob URL's UUID. octet-stream sidesteps that for every type.
        const blob = new Blob([await resp.arrayBuffer()], { type: "application/octet-stream" });
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);
        button.innerHTML = icon("check", 14) + " Downloaded";
        setTimeout(() => { button.textContent = orig; button.disabled = false; }, 1800);
      } catch (err) {
        console.error("Download failed", err);
        button.textContent = "Failed — try again";
        setTimeout(() => { button.textContent = orig; button.disabled = false; }, 2200);
      }
    }

    // WHAT IS STILL UNFINISHED ON PAGE 1.
    //
    // ASKED, NOT REMEMBERED, and that is the whole design of this block. It read the list off
    // `result` (= `state.generate_result`) for one day and broke five different ways, every one of
    // them the same sentence: THE WARNING'S INPUT WAS NOT THE INPUT THE DOCUMENT IS BUILT FROM.
    // `generate_result` is persisted on the draft, never cleared, and `continueToDone` does not
    // regenerate — it stashes a fresh `proposal_payload` and navigates straight here. So the copy
    // sitting in state could
    //   * predate the estimator ticking the box (generate letter-off, go back, tick, Continue) —
    //     the banner hid itself and the customer got the bracketed instructions unwarned;
    //   * describe a DIFFERENT variant than the one about to be pinned (generate epoxy/Direct,
    //     change the audience to GC, Continue) — 1 instruction shown, 4 actually sent;
    //   * arrive as a shape indistinguishable from "scanned and clean".
    // All three failed by UNDER-reporting, which is the direction that reaches a customer.
    //
    // The list is a pure function of `(work_type, audience)` — it is read off the TEMPLATE, so no
    // estimator input is in it — so the page asks the server for it with the variant it is
    // ACTUALLY about to send, and keeps no copy that can go stale.
    //
    // THE VARIANT AND THE FLAG COME FROM `proposal_payload`, NOT FROM TOP-LEVEL STATE. That blob is
    // what /api/generate builds from, what `create_revision` pins, and what `hasCoverLetter` tells
    // the portal — so reading it here makes the banner and the document agree by construction.
    // Gating on the top-level flag instead was defect five: tick, Continue, Back, untick, then
    // reach this page via Projects → View files, and `viewFiles` builds from `pp` (letter IS built)
    // while the top-level flag said false (banner hidden). The fallback to top-level state mirrors
    // `viewFiles`'s own fallback branch, for a draft that has no payload yet.
    //
    // IT FAILS LOUD, NOT QUIET. If the fetch fails there is no way to know what is on page 1, and
    // "cannot tell" is not "clean" — the banner still appears, without a list, saying so.
    (async function showCoverLetterPlaceholders() {
      const box = document.getElementById("cl-placeholders");
      const ul = document.getElementById("cl-ph-list");
      const head = document.getElementById("cl-ph-head");
      const note = document.getElementById("cl-ph-text");
      if (!box || !ul) return;

      const chk = await coverLetterCheck();
      if (!chk.enabled) { box.style.display = "none"; return; }
      const list = chk.placeholders;                 // null = the check could not be made
      if (list && !list.length) { box.style.display = "none"; return; }   // scanned, clean

      ul.textContent = "";
      (list || []).forEach((text) => {
        const li = document.createElement("li");
        li.textContent = text;                    // textContent: template copy, never markup
        ul.appendChild(li);
      });
      if (head) {
        head.textContent = !list
          ? "Page 1 could not be checked."
          : (list.length === 1
            ? "Page 1 still has 1 line of unfinished wording."
            : `Page 1 still has ${list.length} lines of unfinished wording.`);
      }
      if (note) {
        note.textContent = !list
          ? ("The cover letter is the first page of the proposal, and its wording is still a "
             + "draft — parts of it are instructions to you rather than finished copy. This page "
             + "could not reach the server to check which ones are still on it. Reload before "
             + "sending, or untick Cover letter on the Proposal step to send the proposal on its "
             + "own.")
          : ("The cover letter is the first page of the proposal, and these lines are "
             + "instructions to you, not finished copy. They will print to the customer exactly "
             + "as shown. Untick Cover letter on the Proposal step to send the proposal on its "
             + "own.");
      }
      box.style.display = "";
    })();

    const xlsxBtn = document.getElementById("dl-xlsx");
    const docxBtn = document.getElementById("dl-docx");
    const pdfBtn  = document.getElementById("dl-pdf");
    xlsxBtn.addEventListener("click", () => downloadAs(
      "xlsx_download_url", `${safeName}_estimate.xlsx`, xlsxBtn));
    docxBtn.addEventListener("click", () => downloadAs(
      "docx_download_url", `${safeName}_proposal.docx`, docxBtn));
    // PDF is rendered on demand from the .docx (LibreOffice). Only wire the
    // button when the backend returned a pdf url (older cached results won't).
    if (result.pdf_download_url) {
      pdfBtn.addEventListener("click", () => downloadAs(
        "pdf_download_url", `${safeName}_proposal.pdf`, pdfBtn));
    } else {
      pdfBtn.style.display = "none";
    }
    // NO SEPARATE COVER-LETTER DOWNLOAD. There used to be a fourth button here, and a careful
    // two-part gate on it (a letter cached for THIS `result`, AND the estimator's current choice)
    // because `result` can be stale. Both are gone: the letter is page 1 of the .docx and the PDF
    // that "↓ Proposal" already hands over, so there is no second file to offer and no way for the
    // two downloads to disagree about whether the job has a letter.

    // Send to the inline recipient list shown above (no popup). Every recipient
    // gets a secure link + full portal access (view / ask / approve).
    mountPortalRecipients();
    // Restore a previously-typed customer message (so a re-send keeps it).
    const _msgEl = document.getElementById("portal-message");
    if (_msgEl) { try { _msgEl.value = TW.getState().portal_message || ""; } catch {} }
    mountRequireDeposit();
    // Awaited so the chips can mark whoever ends up assigned as already-included; the estimator
    // picker is what decides that, and it resolves the roster from the server.
    mountEstimatorPicker().then(paintNotifyChips).catch(() => {});
    mountNotifyRoster();
    // Changing the estimator changes who is implicitly told, so the chips follow the select.
    const _estSel = document.getElementById("portal-estimator");
    if (_estSel) _estSel.addEventListener("change", paintNotifyChips);
    mountRevisions();
    // Look at the document BEFORE the estimator has typed a message or picked recipients. The
    // gate on the Send button is the thing that actually refuses; this is only so the news does
    // not arrive as a surprise at the last click, and so the one button that fixes it is on
    // screen from the moment the page settles.
    try { showStaleDoc(TW.docDrift(TW.publishDigest(TW.getState())), "mount"); } catch {}
    const fixBtn = document.getElementById("stale-doc-fix");
    if (fixBtn) {
      fixBtn.addEventListener("click", () => {
        // THE PROPOSAL STEP IS WHERE THE FIX LIVES, and it cannot be done from here. The
        // document payload is written by exactly one line of code, in that step's Continue
        // handler, from machinery that only exists on that page: computeTokenValues, the
        // paragraph and box overrides, the system picks. Re-deriving any of it here would be a
        // second copy of the token mapping, which is how the two halves drifted in the first
        // place. So this takes them there, one press, carrying the draft id.
        //
        // `resync=1` tells that page WHY the estimator arrived: it repaints the same drift in
        // the same words above the document (proposal-review.js explainWhyYouAreHere). It does
        // NOT press Continue for them, deliberately -- auto-submitting would send a document
        // nobody had looked at, which is the failure this whole gate exists to stop.
        window.location.assign(TW.withDraft("/proposal-review.html?resync=1"));
      });
    }
    const portalBtn = document.getElementById("portal-btn");
    if (portalBtn) {
      portalBtn.addEventListener("click", async () => {
        const requireDeposit = readRequireDeposit();
        const assignedEstimator = readAssignedEstimator();
        const draftId = TW.getDraftId();
        if (!draftId) { alert("Save the project first (open it from Projects), then send."); return; }
        if (portalRecip.commitEdit && !portalRecip.commitEdit()) return;   // flush a pending intake edit
        if (portalRecip.tryAdd && !portalRecip.tryAdd()) return;   // invalid residual text blocks the send
        const emails = portalRecip.allEmails ? portalRecip.allEmails() : [];
        if (!emails.length) { if (portalRecip.setErr) portalRecip.setErr("Add at least one recipient email."); return; }
        if (!assignedEstimator) {
          if (portalRecip.setErr) portalRecip.setErr("Choose the assigned estimator before sending.");
          const sel = document.getElementById("portal-estimator");
          if (sel) sel.focus();
          return;
        }
        const orig = portalBtn.textContent;
        portalBtn.disabled = true; portalBtn.textContent = "Sending\u2026";
        if (portalRecip.setBusy) portalRecip.setBusy(true);
        if (portalRecip.setErr) portalRecip.setErr("");
        const msgEl = document.getElementById("portal-message");
        const message = (msgEl && msgEl.value || "").trim();
        try {
          // WAIT for this page's edits to reach the server before publishing. The publish
          // route snapshots the SERVER's copy of the draft (main.py create_revision) and the
          // portal pins the customer's view to that snapshot for good — so a debounced save
          // still in flight means the customer is shown the version BEFORE the change that
          // prompted the send.
          //
          // Hanz, 2026-08-13, on a resend of "Hanz Company 123": "I have made changes and
          // resent the proposal but the new proposal does not appear correctly." Revision 2
          // was stamped 16:00:28 with base_tab_id=Epoxy; his draft said Room 1 at 16:02:14.
          // The portal showed the old base, the PDF (built from the live draft) showed the
          // new one, and neither was wrong — the send had simply raced the autosave.
          portalBtn.textContent = "Saving your changes…";
          if (!await TW.flushState()) {
            throw new Error("Couldn't save your latest changes, so nothing was sent — "
                            + "check your connection and try again.");
          }
          // ── …OR IF THE DRAFT HAS MOVED SINCE THIS PAGE BUILT ITS DOCUMENT ───────────────
          // The door (the mode decider) checked the document against the draft when the page
          // opened, and nothing this page writes is an input to it (TW.composeKey). So a key
          // that no longer matches means the draft was changed somewhere else: a texture picked
          // on the Estimate step in another tab, then Send here, froze the old texture, because
          // the drift gate below compares only the price, the base and the number of options.
          //
          // Asked of BOTH copies. This browser's, for another tab whose save has not landed yet;
          // and the SERVER's, because that is the one the publish freezes — a colleague's
          // Estimate-step edit on another machine moves the server's draft and never this page's,
          // so a check of this browser's copy alone passed it and sent the old document. Nothing
          // is posted. A reload goes back through the door, which builds the document from the
          // draft as it now stands.
          //
          // AND THE TWO MUST BE ONE COPY (TW.matchesServer). Review of fix 4: Kyle's page held
          // his $10,000 copy, keyed by his own Continue; RJ revised to $15,000 and pressed Continue
          // on his machine, so the server's copy was keyed too. Both held, the send went, and the
          // customer was sent RJ's document from a page showing Kyle's — and the save this handler
          // makes after a send then PUT Kyle's whole copy back over RJ's. Two copies that differ
          // mean this page is not showing what would be frozen, so nothing is sent.
          //
          // AND THE PUBLISH IS HELD TO THE COPY CHECKED HERE. Between this read and the publish the
          // page waits (encoding the attachments, the network), and the server reloads the draft
          // when the publish arrives: a colleague's Continue landing in that gap was what the
          // customer got, while this page said Sent (review of fix 4, round 2). So the read's
          // `version` — when the server last stored the draft — travels with the publish as
          // `draft_version`, and the server refuses a draft stored again since.
          const _now = TW.getState() || {};
          const _row = _now.project_name ? await TW.readServerRow() : null;
          const _saved = _row ? _row.data : null;
          const _moved = _now.project_name
            && (!TW.documentHolds(_now)
                || (_saved && (!TW.documentHolds(_saved) || !TW.matchesServer(_saved))));
          if (_moved || (_now.project_name && !_saved)) {
            portalBtn.disabled = false; portalBtn.textContent = orig;
            if (portalRecip.setBusy) portalRecip.setBusy(false);
            if (portalRecip.setErr) {
              portalRecip.setErr(_moved
                ? "This proposal changed after this page opened (in another tab, or by someone "
                  + "else), so nothing was sent. Reload this page — the files are rebuilt from the "
                  + "latest changes — check them, then send."
                : "Couldn't check the saved proposal, so nothing was sent — check your connection "
                  + "and try again.");
            }
            return;                            // NOTHING is posted. No portal row, no email.
          }
          // ── THE SEND STOPS HERE IF THE PDF WOULD BE THE OLD ONE ──────────────────────
          // Checked AFTER the flush and BEFORE the publish, and that order is the whole
          // trick. The flush has just made this browser's blob and the server's copy the
          // same blob, so a verdict taken now is a verdict about what the publish would
          // snapshot — no extra round trip, and nothing to read that the page does not
          // already hold. Both halves are in that blob: `rooms` is what the customer's
          // portal page renders, `proposal_payload` is what their PDF is rebuilt from.
          //
          // Until now this was only ever caught AFTERWARDS, from the publish response, by
          // which point the email had gone and the revision was pinned. A teammate hit it
          // at 11:47pm and could not tell what the yellow message meant, which is fair: it
          // was an apology with a four-step manual dance attached. Refusing costs a send
          // that was going to be wrong anyway.
          const stale = TW.docDrift(TW.publishDigest(TW.getState()));
          // Asked BEFORE the drift is blamed on the document. A refused save is a different
          // problem with a different cure, and it is the one that produces a drift that cannot
          // be cleared: RJ pressed Update the PDF, pressed Continue, came back, and got this
          // panel again, because his Continue never landed. Send is refused either way.
          if (stale.length && showSaveBlocked()) {
            portalBtn.disabled = false; portalBtn.textContent = orig;
            if (portalRecip.setBusy) portalRecip.setBusy(false);
            return;                          // NOTHING is posted. No portal row, no email.
          }
          if (stale.length) {
            showStaleDoc(stale, "blocked");
            portalBtn.disabled = false; portalBtn.textContent = orig;
            if (portalRecip.setBusy) portalRecip.setBusy(false);
            const fix = document.getElementById("stale-doc-fix");
            if (fix) fix.focus();
            return;                            // NOTHING is posted. No portal row, no email.
          }
          // ── A PRICE LINE WITH A FIGURE OF HIS OWN: ASK, THEN LET HIM SEND ──────────────
          // Hanz, 2026-09-25: "warn, then let him send." An edited price line follows the
          // estimate unless the estimator typed a DIFFERENT dollar figure into it; the Proposal
          // step marks those lines, and the document it built lists them (price_warnings, read
          // off the same flushed blob the publish is about to freeze). Cancel sends nothing.
          // THE ONE CHECK (TWPrice.confirmOwnFigures) that Download and To Dropbox ask too.
          if (!TWPrice.confirmOwnFigures(TW.getState(), "send", (q) => window.confirm(q))) {
            portalBtn.disabled = false; portalBtn.textContent = orig;
            if (portalRecip.setBusy) portalRecip.setBusy(false);
            return;                            // NOTHING is posted. No portal row, no email.
          }
          portalBtn.textContent = "Sending…";
          // AWAITED, and read here rather than at pick time: an estimator who attaches four
          // photos and removes three should not have paid to encode all four, and holding the
          // encoded copies alongside the File objects doubles the memory for nothing.
          const attachments = await sendAtts.payload();
          // What the portal is told must agree with what `create_revision` (main.py) is about to
          // pin — `row.get("data")`, i.e. the persisted `proposal_payload` — because that is the
          // exact blob `/api/admin/proposal-pdf` reads back later (`pp["cover_letter_enabled"]`,
          // which decides whether the customer's document gets its letterhead page 1).
          // `generate_result` is the WRONG source for this: it is whatever the last successful
          // `/api/generate` call happened to return, and Continuing from the Proposal step after
          // toggling the letter does not call generate again (it stashes a fresh `proposal_payload`
          // and navigates straight to Done — see continueToDone). So a toggle-then-Continue leaves
          // `generate_result` describing the PREVIOUS state of the letter, disagreeing with the
          // payload that is about to be frozen — in either direction: advertising a letter the
          // pinned snapshot has no letter for (a 404 when the customer clicks it), or hiding one
          // the pinned snapshot does have.
          //
          // Read FRESH, not from the module-top `state` — that is a one-shot snapshot taken on
          // load. Safe to do here specifically because this line runs AFTER `TW.flushState()`
          // above: the flush has just made this browser's blob and the server's copy identical, so
          // `TW.getState().proposal_payload` is exactly what `create_revision` is about to pin —
          // the same guarantee `docDrift`'s check three lines up already relies on.
          const _liveState = TW.getState() || {};
          const _pp = (_liveState.proposal_payload && typeof _liveState.proposal_payload === "object")
            ? _liveState.proposal_payload : {};
          const hasCoverLetter = !!_pp.cover_letter_enabled;
          const j = await TW.postJSON("/api/portal/publish?draft_id=" + encodeURIComponent(draftId),
                                      { emails, message, require_deposit: requireDeposit,
                                        has_cover_letter: hasCoverLetter,
                                        // They travel in this body rather than being uploaded
                                        // first because on a FIRST send the portal proposal row
                                        // does not exist until this request creates it — there is
                                        // nothing yet for an upload to hang off.
                                        attachments,
                                        assigned_estimator: assignedEstimator,
                                        // Which of those contacts should not be chased. Filtered
                                        // to the addresses actually being sent to, so a removed
                                        // or retargeted one cannot travel as a stale opt-out.
                                        no_followups: portalRecip.noFollowupsToSend(),
                                        // Which STAFF hear about this send — only the deviations
                                        // from the standing roster, so an untouched send carries
                                        // nothing and behaves exactly as it always has.
                                        notify_add: notifyPick.adds(),
                                        notify_mute: notifyPick.mutes(),
                                        // The document the estimator downloaded and checked on
                                        // this page, if any. The server refuses the send when
                                        // the one it would freeze is not that document (see
                                        // checkedDocument). Absent, it is not asked.
                                        document_render_id: checkedDocument.renderId || undefined,
                                        // When the server last stored the copy checked above.
                                        // The server refuses a draft stored again since.
                                        draft_version: (_row && _row.version) || undefined });
          if (j && j.ok === false) throw new Error(j.error || j.detail || "Send failed.");
          // Only now. Clearing before the request would lose the files on a failed send and leave
          // the estimator re-picking them with no idea they had gone.
          sendAtts.clear();
          // Remember both for a re-send — ONLY while the server still holds the copy this send
          // was checked against. TW.setState PUTs this page's whole copy, and the publish takes
          // seconds: a colleague's save landing inside them would be put back to this page's
          // copy. When the server has moved, nothing is remembered (a convenience lost), and the
          // next arrival here goes through the door onto the server's copy.
          const _after = await TW.readServerDraft();
          if (_after && TW.matchesServer(_after)) {
            // require_deposit persists so a deliberate GC-with-deposit (or Direct-without) choice
            // survives a reload instead of snapping back to the audience default.
            // (assigned_estimator is this browser's copy only: the server keeps its own value on
            // every save, and the publish has just recorded it on the draft.)
            TW.setState({ portal_message: message, require_deposit: requireDeposit,
                          assigned_estimator: assignedEstimator });
            // Persist only the EXTRAS (never the intake row) so they pre-fill next time.
            // The intake is restored from contact_email on the next mount; persisting it
            // here would re-add an edited/retargeted intake as a stray extra on reload.
            const persistExtras = emails.filter(e => !portalRecip.hasIntake || e.toLowerCase() !== String(portalRecip.intake || "").toLowerCase());
            TW.setState({ portal_emails: persistExtras });
            TW.flushState();          // sent now, not 2.5 s later, while the check above still holds
          }
          if (portalRecip.setBusy) portalRecip.setBusy(false);
          portalBtn.textContent = "\u2713 Sent to customer portal";
          mountRevisions();   // the send just created a new version \u2014 show it
          const r = document.getElementById("portal-result");
          if (r) {
            r.style.display = "";
            r.textContent = "";
            // NO LINK AND NO RECIPIENT LIST. Removed on Hanz's ask (2026-08-26). The URL is a
            // secret token that opens the customer's proposal, and there is no reason for it to
            // sit on screen after a send — the CRM drawer copies it on demand when somebody
            // actually wants it. "Sent to customer portal" on the button is the confirmation.
            //
            // The element stays, because the DRIFT WARNING below still needs somewhere to land,
            // and that one must never be dropped: it is the only thing that says the customer
            // received different numbers from the ones on this screen.
            const drift = publishDrift(j.sent_snapshot);
            if (drift) {
              const w = document.createElement("p");
              w.className = "portal-drift";
              w.textContent = "This one has gone to the customer, and it is not what this "
                + "page is showing: " + drift + ".";
              r.appendChild(w);
              // And raise the panel on the server's OWN numbers, so a send that landed
              // drifted offers the same one press as one that was stopped. The paragraph is
              // the notice; the panel is the way out of it.
              showStaleDoc(TW.docDrift(j.sent_snapshot), "sent");
            }
          }
          setTimeout(() => { portalBtn.textContent = "\u2197 Re-send to customer portal"; portalBtn.disabled = false; }, 2500);
        } catch (err) {
          portalBtn.disabled = false; portalBtn.textContent = orig;
          if (portalRecip.setBusy) portalRecip.setBusy(false);
          // THE SERVER REFUSED IT. Same panel, same three columns, same one press: an estimator
          // must not have to tell "the page stopped me" apart from "the server stopped me",
          // because the thing they have to do about it is identical. Nothing was sent either way.
          const refused = staleDocRefusal(err);
          if (refused) {
            const rows = TW.docDrift(refused.snapshot);
            showStaleDoc(rows, "blocked");
            // The server's own sentence only when the panel could not be built from the
            // snapshot: a refusal the estimator cannot see is a Send button that does nothing.
            if (portalRecip.setErr) {
              portalRecip.setErr(rows.length ? "" : (refused.error || portalErrMsg(err)));
            }
            return;
          }
          const msg = portalErrMsg(err);
          if (portalRecip.setErr) portalRecip.setErr(msg === "no_contact_email"
            ? "This proposal has no customer email — add a recipient above." : msg);
        }
      });
    }

    document.getElementById("restart-btn").addEventListener("click", () => {
      TW.clearState();
      window.location.assign("/?new=1");   // start a fresh project (home is Projects)
    });
  }
