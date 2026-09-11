// The OPTIONAL cover letter, on the Proposal step. Externalized like every other script on this
// page (CSP: no script-src 'unsafe-inline'). Loaded AFTER proposal-review.js.
//
// ─── WHY THIS IS ITS OWN FILE AND NOT PART OF proposal-review.js ─────────────────────────────
// The Node harnesses in backend/tests/js/ LIFT functions out of proposal-review.js by regex and
// execute them in isolation — `renderBlock`, `collectOverrides`, `schedulePersistOverrides`,
// `effectiveWorkType`, `setBlockContent`, `serializeBlock` and about two hundred others are all
// on that list (grep `fn("` across backend/tests/js/). A lifted function that calls a function
// the harness did NOT lift dies with a ReferenceError and takes every scenario in that file with
// it. So the cover letter reuses the PATTERN those functions established — one editing host, a
// per-template override store keyed on work type + audience, a version gate, an 800ms persist —
// and reuses their CSS vocabulary verbatim, but adds no call into any of them.
//
// The whole file is an IIFE for the other half of that boundary: proposal-review.js is a classic
// script with no wrapper of its own, so its top-level `const`/`let` live in the shared script
// scope. A bare `const state` here would be a duplicate declaration and would kill BOTH files.
// Inside the IIFE the names are ours; the outer scope is still readable, which is how the few
// genuinely shared helpers below are borrowed (each one feature-detected, never assumed).
//
// ─── WHAT THE ESTIMATOR GETS ─────────────────────────────────────────────────────────────────
// A checkbox in the Word ribbon, OFF by default: most bids do not want a letter, and a document
// that appears without being asked for is a document nobody proofread. Turning it on reveals the
// letter's own page, mounted directly ABOVE the proposal's in the SAME scrolling canvas — no tab
// to switch to (Hanz, 2026-09-11: the letter is already page 1 of one document at generate time,
// so the editor should read that way too, not as a second document you have to go find). Every
// paragraph is editable; edits persist into the draft the same way the proposal's do and ride the
// generate payload as `cover_letter_paragraph_overrides`.
//
// Both surfaces are always genuinely rendered when the letter is on — never `display:none` — for
// the same reason the old off-stage design needed that: the proposal's Terms pages paginate by
// measuring real element heights, and a display:none subtree measures zero.
(function () {
  "use strict";

  // ── the borrowed few, each optional ───────────────────────────────────────────────────────
  // Read once, at call time, never at load time: proposal-review.js throws on a page with no
  // project in state, and a `typeof` that ran during load order would then be wrong forever.
  const g = (name) => (typeof window[name] === "function" ? window[name] : null);

  const CL_TOKEN_RE = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g;
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /** The token values this letter should show.
   *
   *  `cover_letter_writer._ensure_cover_letter_values` says it plainly: "every other token in
   *  these templates is one the proposal already fills". So the proposal editor's own resolver is
   *  the correct answer and a second one would be a second source of truth for the same numbers.
   *  Borrowed, not copied — and guarded, because a letter that renders raw {{tokens}} is still a
   *  usable editor while a page that threw is not.
   *
   *  `computeTokenValues` REQUIRES its `mergedValues` argument — it dereferences it immediately
   *  (`mergedValues.polish_sf`, ...) — so it must be called the same way every one of its callers
   *  in proposal-review.js calls it: the stored draft overlaid with whatever is currently typed
   *  into the on-screen form, `Object.assign({}, state, TW.readForm(form))`. Calling it with no
   *  argument throws, and that throw was landing in the catch below and coming back as `{}` —
   *  which is indistinguishable, to `render()`, from "no tokens are known", so every `{{token}}`
   *  printed literally. Read fresh each time (`clState()`, not a load-time snapshot) for the same
   *  reason the rest of this file does. */
  function clTokens() {
    const f = g("computeTokenValues");
    if (!f) return {};
    try {
      const st = clState();
      const formEl = document.getElementById("proposal-form");
      const canReadForm = formEl && window.TW && typeof TW.readForm === "function";
      const merged = canReadForm ? Object.assign({}, st, TW.readForm(formEl)) : st;
      return f(merged) || {};
    } catch { return {}; }
  }

  // ── work type + audience, DUPLICATED on purpose ───────────────────────────────────────────
  /** The work type that actually drives the document — the BASE bid's role, not the intake's
   *  answer (Phase B). Deliberately a duplicate of `effectiveWorkType` in proposal-review.js
   *  rather than a call to it: that function is lifted by five harnesses, and the moment a lifted
   *  function is asked to serve a second caller it becomes a shared dependency that any of them
   *  can break. Twelve lines duplicated is cheaper than that coupling, and the tests below assert
   *  the two agree.
   *
   *  If you change the rule here, change it there too. */
  function clWorkType() {
    const st = clState();
    const wt = String(st.work_type || "epoxy").toLowerCase();
    if (wt === "combo") return "combo";
    const all = Array.isArray(st.priced_tabs) ? st.priced_tabs : [];
    const base = st.base_tab_id ? all.find((t) => t && t.id === st.base_tab_id) : null;
    const role = base && base.role ? String(base.role).toLowerCase() : "";
    return (role === "epoxy" || role === "polish" || role === "gyp") ? role : wt;
  }

  /** The audience the letter is written to — Direct, GC or Gyp.
   *
   *  The companion the coordinator asked for, and it exists for the same reason the proposal has
   *  one: the two things that pick a template file are work type and audience, so a store keyed
   *  on work type alone would hand a GC's letter to an owner after a single audience switch.
   *  Same duplication rule as above. */
  function clAudience() {
    return String(clState().audience || "Direct");
  }

  /** One key out of the CURRENT stored blob.
   *
   *  Not out of a load-time snapshot: `TW.setState` re-reads localStorage into a new object and
   *  writes it back, so a top-level key it REPLACES never reaches a `const state` captured at
   *  load. proposal-review.js learned that the expensive way — a stale snapshot is how a sibling
   *  template's saved layout got dropped from a draft — and the same trap is set here, because
   *  every store this file keeps is a top-level key. */
  function clState() {
    try { return (window.TW && TW.getState()) || {}; } catch { return {}; }
  }
  function live(name) {
    const v = clState()[name];
    return v;
  }

  const clKey = (wt, audience) => String(wt || "") + ":" + String(audience || "Direct");

  /** The per-template store with ONE template's entry replaced, as a new object.
   *
   *  Merge, never replace — the proposal's `mergeOverrideEntry`, in the cover letter's own
   *  namespace and with the cover letter's own value shape (an id-keyed OBJECT, which is what
   *  `_sanitize_cover_letter_overrides` expects, not the proposal's array). Pure so the test can
   *  exercise the real thing: an epoxy → polish → epoxy round trip that lost the epoxy letter's
   *  edits is the exact bug this shape exists to prevent. */
  function clMergeEntry(all, wt, audience, templateVersion, items) {
    const next = Object.assign({}, (all && typeof all === "object") ? all : null);
    next[clKey(wt, audience)] = { template_version: templateVersion, items: items };
    return next;
  }

  /** The saved entry for one template, or null. Legacy fallback to the flat pair, same as the
   *  proposal's `savedOverridesFor`: a draft saved before the keyed store existed has its edits
   *  only in the old shape, and dropping them would be losing text somebody typed. */
  function clSavedFor(wt, audience) {
    const all = live("cover_letter_paragraph_overrides_all");
    const hit = (all && typeof all === "object") ? all[clKey(wt, audience)] : null;
    if (hit && hit.items && typeof hit.items === "object") return hit;
    const meta = live("cover_letter_paragraph_overrides_meta") || {};
    if (meta.work_type === wt && meta.audience === audience) {
      const flat = live("cover_letter_paragraph_overrides");
      return { template_version: String(meta.template_version || ""),
               items: (flat && typeof flat === "object" && !Array.isArray(flat)) ? flat : {} };
    }
    return null;
  }

  // ── module state ──────────────────────────────────────────────────────────────────────────
  let surface = null;          // #cl-surface — our own, never #doc-surface
  let toggleEl = null;         // the ribbon checkbox
  let blocks = null;           // the template's block records
  let templateVersion = "";
  let pristine = new Map();    // block id -> the template's own rendering, the edit baseline
  let loadedFor = "";          // "wt:audience:v" of what is currently on screen
  let loading = false;
  const artCache = new Map();

  // ── rendering ─────────────────────────────────────────────────────────────────────────────
  function fillPlain(text, tokens) {
    CL_TOKEN_RE.lastIndex = 0;
    return String(text).replace(CL_TOKEN_RE, (m0, name) =>
      Object.prototype.hasOwnProperty.call(tokens, name) ? String(tokens[name]) : m0);
  }

  /** Substituted HTML for one stretch of template text. Each filled token is wrapped in
   *  `.tw-fill` so a value that came from the estimate is visibly a value and not typing — the
   *  same cue, the same class and therefore the same yellow as the proposal beside it. Screen
   *  only; the .docx is filled server-side from the tokens, never from this HTML. */
  function fillHtml(text, tokens) {
    CL_TOKEN_RE.lastIndex = 0;
    let html = "", last = 0, m;
    const t = String(text == null ? "" : text);
    while ((m = CL_TOKEN_RE.exec(t))) {
      html += esc(t.slice(last, m.index));
      const known = Object.prototype.hasOwnProperty.call(tokens, m[1]);
      html += `<span class="tw-fill" data-token="${esc(m[1])}">` +
              esc(known ? String(tokens[m[1]]) : m[0]) + "</span>";
      last = m.index + m[0].length;
    }
    return html + esc(t.slice(last));
  }

  /** The template's own formatted run segments for one paragraph, or null when they cannot be
   *  trusted. `proposal_writer._block_runs` builds them and the cover-letter endpoint returns them
   *  verbatim: `[{text, bold, italic, underline, size_pt, font, color}]`, each switch either a
   *  boolean or null for "unresolved, use the page default".
   *
   *  ONE PREDICATE, TWO CALLERS, and that is the whole point of it. `blockHtml` renders from these
   *  and `renderBlock` drops the paragraph-level `tw-bold` class when they exist — so if the two
   *  ever disagreed about whether a paragraph HAS usable runs, that paragraph would come out with
   *  neither the class nor the per-run weights and lose its bold altogether.
   *
   *  Three ways runs are refused, each of them a real .docx:
   *    · none at all — a response cached before the endpoint carried them, which is what the flat
   *      path below is still for;
   *    · they do not rejoin to `b.text` — hyperlink runs are not direct `w:r` children, so the
   *      walk that built them saw less text than the paragraph has (`_block_runs` invariant 1,
   *      which it asks the frontend to verify by name);
   *    · a token straddles a run boundary. The backend promises this cannot happen (invariant 2:
   *      every token is its own segment, carrying the formatting of the run the match starts in)
   *      and a promise worth leaning on is a promise worth checking. Rendering runs one at a time
   *      means a token split down the middle matches in neither half and prints itself raw at the
   *      estimator — which is the complaint that nothing on the letter was substituted. Flat
   *      rendering loses the per-run weights and keeps the value; that is the better half to lose. */
  function clRunsFor(b) {
    const runs = (b && Array.isArray(b.runs) && b.runs.length) ? b.runs : null;
    if (!runs) return null;
    const text = String((b && b.text) || "");
    const chunk = (r) => String((r && r.text) || "");
    if (runs.map(chunk).join("") !== text) return null;
    const edges = [];
    let pos = 0;
    for (const r of runs) { pos += chunk(r).length; edges.push(pos); }
    CL_TOKEN_RE.lastIndex = 0;
    let m;
    while ((m = CL_TOKEN_RE.exec(text))) {
      const a = m.index, z = a + m[0].length;
      if (edges.some((e) => e > a && e < z)) { CL_TOKEN_RE.lastIndex = 0; return null; }
    }
    return runs;
  }

  /** One paragraph's HTML: the template's own runs when there are usable ones, each carrying its
   *  own weight, and the flat token walk when there are not.
   *
   *  WHY THE PER-RUN PASS IS THE FIX. Hanz, with a screenshot of a bulleted letter: "Only those
   *  words before and including the colon should be default bold. The other details should not be.
   *  So, material/system, area, schedule, options should be the only ones bold." They already are
   *  in the .docx — Kyle's template bolds the label run and leaves the detail run plain — and this
   *  renderer was throwing that away. It walked `b.text` alone, so the only weight it could show
   *  was the paragraph-level class, and `b.style.bold` is `any(r.bold for r in p.runs)` on the
   *  server. Every label bullet has a bold label, so every label bullet reported as a wholly bold
   *  PARAGRAPH and drew itself as one.
   *
   *  ONLY WHAT A RUN TURNS ON IS EMITTED. `clRunCss` can also write the negatives —
   *  `font-weight:400`, `font-style:normal` — and those are load-bearing when the ESTIMATOR
   *  presses a switch off, because the .docx then has to say so out loud. Coming from the template
   *  they are noise with a cost: `clFmtAt` reads inline styles back, so the first press on any
   *  paragraph would start pinning "not italic, not underlined" onto every run of it. An absent
   *  switch reads back as null — "inherit whatever the template's own run says" — which is exactly
   *  true here, because nothing on this path changes it.
   *
   *  SIZE IS DELIBERATELY NOT EMITTED AT ALL, though the run records carry one and the proposal's
   *  renderer uses it. This page is a to-scale preview of a printed sheet: a point size is
   *  geometry, and re-sizing every run would reflow the letter — an unasked-for change arriving
   *  inside the one that was asked for. Weight, slant and underline carry no layout of their own,
   *  which is why they can come across on their own. Absent still means "inherit the template's",
   *  and it is already what a formatting press stores today.
   *
   *  Nesting order matches `clRenderRuns` — the styled span outside, the `.tw-fill` inside — so a
   *  paragraph re-rendered after a press has the same shape as one drawn straight from the
   *  template, and `clSegments` reads the two identically. */
  function blockHtml(b, tokens) {
    const runs = clRunsFor(b);
    if (!runs) return fillHtml((b && b.text) || "", tokens);
    const on = (v) => (v === true ? true : null);
    let html = "";
    for (const r of runs) {
      const inner = fillHtml((r && r.text) || "", tokens);
      const css = clRunCss({ bold: on(r.bold), italic: on(r.italic), underline: on(r.underline) });
      html += css ? `<span style="${css}">${inner}</span>` : inner;
    }
    return html;
  }

  /** A contenteditable block back to plain text. `.tw-fill` spans give up their VALUE (never the
   *  token), <br> and nested divs become newlines, NBSPs normalise. The inverse of blockHtml, and
   *  the same walk `serializeBlock` does for the proposal — an edit is detected by comparing this
   *  against the pristine rendering, so the two have to agree on what "the text" is. */
  function serialize(el) {
    const walk = (node) => {
      let out = "";
      node.childNodes.forEach((n) => {
        if (n.nodeType === Node.TEXT_NODE) { out += n.nodeValue; return; }
        if (n.nodeType !== Node.ELEMENT_NODE) return;
        if (n.tagName === "BR") { out += "\n"; return; }
        if (/^(DIV|P)$/.test(n.tagName) && out && !out.endsWith("\n")) out += "\n";
        out += walk(n);
      });
      return out;
    };
    return walk(el).replace(/\u00a0/g, " ");
  }

  const TWIPS_PER_PT = 20;
  /** The paragraph's own geometry from the template record. Same reason the proposal does it on
   *  the first paint: without it a class's hand-picked indent stands in for the file's real
   *  numbers, and the on-screen letter disagrees with the printed one. */
  function applyGeom(el, para) {
    if (!para) return;
    const pt = (tw) => (Number(tw) / TWIPS_PER_PT) + "pt";
    const leftTw = Math.max(0, Number(para.indent || 0));
    const hangTw = Math.max(0, Number(para.hanging || 0));
    el.style.marginLeft = pt(Math.max(0, leftTw - hangTw));
    el.style.paddingLeft = hangTw ? pt(hangTw) : "0";
    el.style.textIndent = para.first_line ? pt(para.first_line) : "";
    const sp = para.spacing || {};
    el.style.marginTop = sp.before ? pt(sp.before) : "0";
    el.style.marginBottom = sp.after ? pt(sp.after) : "0";
    if (sp.line && sp.line_rule === "auto") el.style.lineHeight = String(Number(sp.line) / 240);
    else if (sp.line) el.style.lineHeight = pt(sp.line);
    else el.style.lineHeight = "";
  }

  /** One paragraph.
   *
   *  NO contentEditable HERE — the PR #393 rule, and the single most important line in this file.
   *  A paragraph that carries its own contenteditable is its own editing host, and a browser
   *  selection cannot cross a host boundary: Ctrl+A stops at one line, a drag stops at one line,
   *  and every line draws its own little focus box. The page (or, for the date, its box) carries
   *  it; this inherits. */
  function renderBlock(b, tokens) {
    const el = document.createElement("div");
    el.className = "tw-block";
    el.dataset.id = String(b.id);
    el.spellcheck = false;
    // A NUMBERED LINE SHOWS ITS NUMBER, not a red square — and on this document that is every
    // list line there is. `b.list` only says the paragraph carries Word numbering, which is true
    // of a bulleted row and a numbered one alike, so trusting it painted a red Wingdings square in
    // front of lines the customer's PDF prints "1." to "4." on. `para.marker` is what the level
    // actually prints (`proposal_writer._para_marker`) and it is empty for a real bullet row.
    //
    // MEASURED, not assumed, across all seven files in backend/templates/CoverLetter: every list
    // paragraph in every one of them is `bullet: false` with a real decimal marker — Direct/Epoxy
    // and Direct/Polish 1. to 4., Combo 1. to 4. and then 1. to 3. again for the second system, GC
    // and Gyp 1. to 3. — and NOT ONE bulleted paragraph exists in any of them. So the square was
    // never right here; it was wrong on all seven letters, on every labelled line.
    //
    // Same fault, same fix and the same two classes as the proposal's 27 numbered Terms clauses.
    // The note above `.tw-block.tw-empty.tw-li::before` in styles.css records that round: "a
    // numbered Terms clause was ALSO drawn as .tw-li, so emptying one hid its red square here
    // while Word printed a bare clause number". Still falls back to the square when there is no
    // marker to show, which is what that branch was always for: a list level whose definition
    // cannot be read is the one case where the old behaviour is the best guess left.
    if (b.list && b.para && b.para.marker) {
      el.classList.add("tw-num");
      el.dataset.marker = String(b.para.marker);
    }
    else if (b.list) el.classList.add("tw-li");                  // a real Word bullet
    else if (b.style && b.style.name === "List Paragraph") el.classList.add("tw-list");
    if (b.align) el.style.textAlign = b.align;
    // A RUN-LESS FALLBACK ONLY, which is how the proposal's own renderBlock has it. `.tw-bold`
    // weights every character of the paragraph that no inline style overrides, and `b.style.bold`
    // is `any(r.bold for r in p.runs if r.bold is not None)` on the server — true the moment ONE
    // run is bold. So on a bullet with a bold "Area:" label and plain details it said "this whole
    // paragraph is bold", and the class obligingly bolded the details too. With the runs on screen
    // each one states its own weight and a run that states none means the page default, so there
    // is nothing left for the class to say and saying it anyway is the bug.
    if (b.style && b.style.bold && !clRunsFor(b)) el.classList.add("tw-bold");
    applyGeom(el, b.para);
    el.innerHTML = blockHtml(b, tokens);
    const plain = fillPlain(b.text, tokens);
    pristine.set(Number(b.id), plain);
    el.classList.toggle("tw-empty", !plain.trim());
    return el;
  }

  /** One media part of the cover-letter template, as a data: URI.
   *
   *  data:, not blob:. The tool's CSP is an nginx $host map on the VPS and its `img-src` does not
   *  carry `blob:` on every host — a blob URL renders locally and shows nothing in production,
   *  which is exactly how no attachment photo rendered on prod for weeks. A failure is not
   *  cached, so a flaky fetch can be retried by re-rendering. */
  function artUrl(wt, audience, name) {
    const key = wt + ":" + audience + ":" + name;
    if (!artCache.has(key)) {
      const url = `/api/coverletter-template/media?work_type=${encodeURIComponent(wt)}` +
                  `&audience=${encodeURIComponent(audience)}&name=${encodeURIComponent(name)}`;
      const p = fetch(url, { headers: TW.authHeaders() })
        .then((r) => (r.ok ? r.blob() : null))
        .then((b) => (b ? new Promise((res) => {
          const fr = new FileReader();
          fr.onload = () => res(String(fr.result || ""));
          fr.onerror = () => res(null);
          fr.readAsDataURL(b);
        }) : null))
        .catch(() => null)
        .then((u) => { if (!u) artCache.delete(key); return u; });
      artCache.set(key, p);
    }
    return artCache.get(key);
  }

  /** Draw the letter.
   *
   *  ONE page. A cover letter is one sheet — there is no Terms flow underneath it and no
   *  pagination, which is most of why this renderer is a fraction of the proposal's.
   *
   *  TWO KINDS OF CONTENT, and the split is the template's, not ours. Kyle's real letter
   *  (`docs/Cover Letter/Treadwell Cover Letter - Example1.docx`) anchors the DATE in a floating
   *  text box over the letterhead artwork; the body flows beneath. So anything the template
   *  reports as living in a box is POSITIONED at the box's own coordinates, and everything else
   *  flows. A template with no boxes — which is what the endpoint served before the date box was
   *  baked in — renders entirely as flow, which is why that branch is not a fallback for a
   *  failure but a first-class layout.
   *
   *  NO DRAG, NO RESIZE, NO GRIPS. The proposal's boxes are Kyle's design surface and he moves
   *  them; the date sits where the letterhead was drawn for it to sit, and a handle offering to
   *  move it would only offer a way to get it wrong. Position is read; only text is written. */
  function render(geo, tokens) {
    const page = (geo && geo.page) || {};
    const wPt = Number(page.w_pt) || 612;
    const hPt = Number(page.h_pt) || 792;
    const margin = page.margin || { top: 72, left: 90, right: 90, bottom: 72 };
    const wt = clWorkType(), audience = clAudience();

    surface.textContent = "";
    surface.classList.remove("cl-error");

    const boxed = new Map();
    (blocks || []).forEach((b) => {
      if (b.txbx == null) return;
      if (!boxed.has(b.txbx)) boxed.set(b.txbx, []);
      boxed.get(b.txbx).push(b);
    });
    const boxes = ((geo && geo.boxes) || []).filter((bx) => bx && bx.x_pt != null && boxed.has(bx.id));
    const positioned = boxes.length > 0;

    const pg = document.createElement("div");
    pg.className = "tw-page cl-page";
    pg.style.width = wPt + "pt";
    if (positioned) {
      pg.style.height = hPt + "pt";
      pg.style.overflow = "hidden";
    } else {
      // Flow layout has no artwork behind it to register against, so it needs the template's own
      // margins as padding — otherwise the letter starts hard against the sheet edge.
      pg.classList.add("tw-flow");
      pg.style.padding = `${Number(margin.top) || 72}pt ${Number(margin.right) || 90}pt ` +
                         `${Number(margin.bottom) || 72}pt ${Number(margin.left) || 90}pt`;
    }
    surface.appendChild(pg);

    // The letterhead artwork, behind everything. Appended asynchronously and PREPENDED so it
    // lands under the text no matter which resolves first.
    const art = ((geo && geo.images) || []).slice()
      .sort((a, b) => (a.para_index || 0) - (b.para_index || 0))[0];
    if (art && art.name) {
      artUrl(wt, audience, art.name).then((u) => {
        if (!u || !pg.isConnected) return;
        const img = document.createElement("img");
        img.className = "tw-page-art";
        img.style.left = Math.max(0, art.x_pt || 0) + "pt";
        img.style.top = Math.max(0, art.y_pt || 0) + "pt";
        img.style.width = (art.w_pt || wPt) + "pt";
        img.style.height = (art.h_pt || hPt) + "pt";
        img.alt = "";
        img.src = u;
        pg.prepend(img);
      });
    }

    if (positioned) {
      // Body goes in FIRST. It and every box share z-index:1 (styles.css), so with equal
      // z-index the later DOM sibling paints on top — boxes must be appended after the body
      // or the body's full-page click/edit surface covers them and eats every click.
      const body = document.createElement("div");
      body.className = "cl-body";
      // The body's own inset. The boxes are absolutely positioned so they do not push it down;
      // the artwork is behind it; this is what keeps the letter inside the printable area.
      body.style.padding = `${Number(margin.top) || 72}pt ${Number(margin.right) || 90}pt ` +
                           `${Number(margin.bottom) || 72}pt ${Number(margin.left) || 90}pt`;
      body.contentEditable = "true";
      body.spellcheck = false;
      (blocks || []).filter((b) => b.txbx == null).forEach((b) => body.appendChild(renderBlock(b, tokens)));
      pg.appendChild(body);

      for (const bx of boxes) {
        const host = document.createElement("div");
        host.className = "tw-txbx cl-txbx";
        host.dataset.boxId = String(bx.id);
        // THE EDITING HOST for what is inside it. One box, one editable region.
        host.contentEditable = "true";
        host.spellcheck = false;
        host.style.left = (Number(bx.x_pt) || 0) + "pt";
        host.style.top = (Number(bx.y_pt) || 0) + "pt";
        host.style.width = (Number(bx.w_pt) || 200) + "pt";
        if (bx.h_pt) host.style.minHeight = Number(bx.h_pt) + "pt";
        boxed.get(bx.id).forEach((b) => host.appendChild(renderBlock(b, tokens)));
        pg.appendChild(host);
      }
    } else {
      // THE PAGE IS THE EDITING HOST. Same role a box plays above, for the same reason: without
      // one, the paragraphs render as text nobody can type in, because none of them carries a
      // contenteditable of its own.
      pg.contentEditable = "true";
      pg.spellcheck = false;
      (blocks || []).forEach((b) => pg.appendChild(renderBlock(b, tokens)));
    }

    restoreSaved(wt, audience);
    pg.addEventListener("input", onInput);
  }

  /** Replay the estimator's saved edits — only when they were captured against THIS template
   *  file. A block id is a position in a walk over one .docx, so a version mismatch means the
   *  saved entry describes different paragraphs; replaying it would put the estimator's sentence
   *  on somebody else's line. The backend applies the identical gate on the way out. */
  function restoreSaved(wt, audience) {
    const saved = clSavedFor(wt, audience);
    if (!saved || String(saved.template_version || "") !== templateVersion) return;
    for (const rawId of Object.keys(saved.items || {})) {
      const entry = saved.items[rawId];
      if (!entry || typeof entry.text !== "string") continue;
      const el = surface.querySelector(`.tw-block[data-id="${Number(rawId)}"]`);
      if (!el) continue;
      // RUNS FIRST, and only when there are any. A paragraph the estimator merely retyped
      // saves as text alone, and putting text back is both cheaper and exactly what it saved.
      if (Array.isArray(entry.runs) && entry.runs.length && clF()) {
        clRenderRuns(el, entry.runs);
        el.classList.add("tw-fmt");       // so collect() picks it up again next time round
      } else {
        el.textContent = entry.text;      // pre-wrap renders the line breaks
      }
      el.classList.add("tw-dirty");
      el.classList.toggle("tw-empty", !entry.text.trim());
    }
  }

  /** Every hand-edited paragraph, as `{"<id>": {text}}`.
   *
   *  The id-keyed OBJECT shape is the backend's (`_sanitize_cover_letter_overrides`), which folds
   *  the key back into an `id` field and then runs the entry through the very same validator the
   *  proposal's overrides pass through.
   *
   *  Falls back to what is already saved when the editor never rendered — a template fetch that
   *  404s must not silently throw away edits the estimator made before the deploy that broke it. */
  function collect() {
    if (!blocks || !surface) {
      const flat = live("cover_letter_paragraph_overrides");
      return (flat && typeof flat === "object" && !Array.isArray(flat)) ? flat : {};
    }
    const out = {};
    surface.querySelectorAll(".tw-block").forEach((el) => {
      const id = Number(el.dataset.id);
      const cur = serialize(el);
      const textChanged = cur !== pristine.get(id);
      // BOLDING A WORD CHANGES NO CHARACTER. Reading text alone is what made every B/I/U
      // press vanish on the way out, so a block carrying `tw-fmt` is examined even when its
      // text is untouched -- and then dropped anyway if the runs turn out plain, which is
      // what a bold-then-unbold leaves behind. An untouched letter still ships no overrides.
      const runs = el.classList.contains("tw-fmt") ? clStoredRuns(el) : [];
      const formatted = runs.length > 0 && !clRunsArePlain(runs);
      if (!textChanged && !formatted) return;
      out[String(id)] = formatted ? { text: cur, runs: runs } : { text: cur };
    });
    return out;
  }

  // ── persistence ───────────────────────────────────────────────────────────────────────────
  let persistTimer = null;
  /** 800ms after the last keystroke, exactly like the proposal's `schedulePersistOverrides` —
   *  which then hands off to `TW.setState`'s own 2500ms server save. Two layers, not one: typing
   *  must not be a request per character, and the draft must not be 800ms of typing behind.
   *
   *  Reads the store FRESH inside the timer rather than closing over an earlier copy, because the
   *  debounce window can straddle a base-bid switch that rewrote it. */
  function schedulePersist() {
    if (persistTimer) clearTimeout(persistTimer);
    persistTimer = setTimeout(persistNow, 800);
  }

  function persistNow() {
    if (persistTimer) { clearTimeout(persistTimer); persistTimer = null; }
    try {
      const wt = clWorkType(), audience = clAudience();
      const items = collect();
      TW.setState({
        cover_letter_paragraph_overrides_all:
          clMergeEntry(live("cover_letter_paragraph_overrides_all"), wt, audience, templateVersion, items),
        // Kept in lockstep for the CURRENT template: this flat pair is what the generate payload
        // carries and what `collect()` falls back to when the editor never loaded.
        cover_letter_paragraph_overrides: items,
        cover_letter_paragraph_overrides_meta: {
          template_version: templateVersion, work_type: wt, audience: audience,
        },
        cover_letter_template_version: templateVersion,
      });
    } catch { /* a refused state write (foreign draft) is TW's call, not ours */ }
  }

  function onInput(e) {
    const el = e.target && e.target.closest ? e.target.closest(".tw-block") : null;
    if (el) {
      const id = Number(el.dataset.id);
      const cur = serialize(el);
      // `|| tw-fmt` for the same reason collect() looks at it: the text of a bolded paragraph
      // is identical to the template's, and without this it would repaint as untouched.
      el.classList.toggle("tw-dirty", cur !== pristine.get(id) || el.classList.contains("tw-fmt"));
      el.classList.toggle("tw-empty", !cur.trim());
    }
    schedulePersist();
  }

  // ── load ──────────────────────────────────────────────────────────────────────────────────
  function showLoading() {
    surface.textContent = "";
    surface.classList.remove("cl-error");
    const pg = document.createElement("div");
    pg.className = "tw-page cl-page";
    pg.style.padding = "72pt 90pt";
    pg.setAttribute("role", "status");
    pg.setAttribute("aria-live", "polite");
    pg.textContent = "Loading the cover letter template…";
    surface.appendChild(pg);
  }

  /** The letter did not load. AMBER, NOT RED, and the distinction is the whole design of this
   *  panel: the proposal is unaffected, the bid is unaffected, and the estimator can continue and
   *  send today. A red banner would claim otherwise. It is the same palette `.pr-inert-warn`
   *  already uses for an option configured into thin air, for the same reason — a mistake to
   *  correct, not a failure to fear.
   *
   *  Two ways out, both of them real: try the fetch again, or turn the letter off and get on with
   *  the bid. A dead end with an error code in it is not an error state, it is an apology. */
  function showError(msg) {
    surface.textContent = "";
    surface.classList.add("cl-error");
    const box = document.createElement("div");
    box.className = "cl-warn";
    box.setAttribute("role", "alert");
    const p = document.createElement("p");
    p.className = "cl-warn-text";
    // The old copy said "you can carry on and send it without a letter", which was not true while
    // the box was still ticked: /api/generate builds the letter from the same template, and a
    // fault there 500s the whole generate — the estimator would have lost the xlsx and the docx
    // too. The way out is real, but it is the button below, so say so.
    p.innerHTML = "<strong>The cover letter template didn’t load.</strong> " +
      "Your bid and your proposal aren’t affected. Try again, or turn the letter off and send " +
      "the proposal on its own — leaving it on will stop the files generating. " +
      esc(msg ? "(" + msg + ")" : "");
    const row = document.createElement("div");
    row.className = "cl-warn-actions";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "cl-warn-btn";
    retry.textContent = "Try again";
    retry.addEventListener("click", () => { loadedFor = ""; load(true); });
    const off = document.createElement("button");
    off.type = "button";
    off.className = "cl-warn-btn cl-warn-btn-quiet";
    off.textContent = "Turn the cover letter off";
    off.addEventListener("click", () => {
      if (toggleEl) { toggleEl.checked = false; toggleEl.dispatchEvent(new Event("change", { bubbles: true })); }
    });
    row.appendChild(retry);
    row.appendChild(off);
    box.appendChild(p);
    box.appendChild(row);
    surface.appendChild(box);
  }

  async function load(force) {
    if (!surface || loading) return;
    const wt = clWorkType(), audience = clAudience();
    const want = wt + ":" + audience;
    if (!force && loadedFor === want) return;
    loading = true;
    showLoading();
    try {
      // The endpoint is auth-gated. Wait for the Supabase token the way every other pull-on-load
      // fetch on this page does, or a slow sign-in 401s the template and the estimator sees the
      // amber panel for a problem that was only ever a race.
      try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
      const res = await fetch(
        `/api/coverletter-template?work_type=${encodeURIComponent(wt)}` +
        `&audience=${encodeURIComponent(audience)}`,
        { headers: TW.authHeaders() });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const j = await res.json();
      blocks = Array.isArray(j.blocks) ? j.blocks : [];
      templateVersion = String(j.template_version || "");
      pristine = new Map();
      render(j.geometry || {}, clTokens());
      loadedFor = want;
      // Stamp the version the moment the template is on screen, not only on the first keystroke:
      // an estimator who turns the letter on and presses Continue without typing must still ship
      // a payload the backend can version-gate.
      persistNow();
    } catch (err) {
      console.error("Cover letter preview failed to render:", err);
      loadedFor = "";
      showError(err && err.message ? err.message : "");
    } finally {
      loading = false;
    }
  }

  // ── RUN FORMATTING ON THE LETTER: Bold / Italic / Underline / Size ─────────────────────────
  //
  // Hanz, 2026-09-03, with a screenshot of the Cover letter tab: "These options to edit the text
  // to make it bold does not apply".
  //
  // He is right, and every part of it was behaving as written. Two separate things had to be true
  // for a press to do nothing, and both still would be if this borrowed nothing:
  //
  //   1. The proposal's `fmtTargetBlock()` returns a block only when `#doc-surface` contains it,
  //      so a `.tw-block` living in `#cl-surface` is unreachable to that ribbon by construction —
  //      true whether or not a tab strip exists, since the two surfaces are always separate DOM
  //      subtrees. With no target, `renderFmtBar()` sets `disabled` on every button, select and
  //      input in the bar, and a disabled button dispatches no click for anyone to intercept.
  //   2. Even a press that landed would have been thrown away on the way out. `collect()` compares
  //      the serialized TEXT of each block against its pristine copy, and bolding a word does not
  //      change one character of it, so the override was computed as "unchanged" and dropped.
  //
  // The letter therefore BORROWS the ribbon rather than growing a second one — same buttons, same
  // keystrokes, one place to look. WHICHEVER SURFACE HOLDS THE SELECTION WINS THE RIBBON, the same
  // way moving the caret between two proposal paragraphs already re-aims it with no explicit
  // hand-off: this file's own `selectionchange` listener aims at a letter paragraph only when the
  // selection is actually inside `#cl-surface` (`clBlockAtSelection`), the proposal's untouched
  // listener does the same for `#doc-surface`, and because the two subtrees are disjoint exactly
  // one of them ever acts on a given selection change. It intercepts a ribbon press in the CAPTURE
  // phase, before the proposal's own bubble-phase handlers on `.tw-fmtbar` ever see it — but ONLY
  // while the ribbon is actually aimed at a letter paragraph (`clTargetBlock()`), so a press made
  // while the proposal owns the bar reaches the proposal exactly as it always has.
  //
  // WHAT IT DOES NOT DO is call into proposal-review.js. Everything below is a local copy of that
  // file's pattern, for the reason recorded at the top of this file: those functions are lifted by
  // name into the Node harnesses, and a second caller makes each one a shared dependency that any
  // harness can then break. The three that ARE borrowed through `g()` — ensureFmtBar,
  // renderFmtBar, idleFmtBar — are the ones that build and hand back the shared chrome, which is
  // precisely the thing that must not be duplicated. (They are reachable because
  // proposal-review.js has no wrapper of its own: its top-level function declarations are on
  // window.)
  //
  // The run ALGEBRA is not copied. `window.TWFmt` (proposal-format-core.js) is already a
  // standalone module written to have two consumers, so patch/summarize/toggle come from there.
  // Absent it, every function below degrades to a no-op and the editor behaves as it does today.
  //
  // NEVER `document.execCommand`. It writes <b>/<i>/<u> TAGS, and the reader below — like the
  // proposal's — measures inline STYLES. The words would look bold on screen and reach the .docx
  // as nothing at all, which is worse than a button that visibly does nothing.

  const CL_RUN_KEYS = ["bold", "italic", "underline", "size_pt"];
  const CL_MARK_A = "\u0001", CL_MARK_B = "\u0002";   // never occur in a cover-letter template
  let clFmtBlock = null;    // the paragraph the ribbon is aimed at, ours alone
  let clFmtRange = null;    // the last real selection in it, for a press made after focus moved
  let clFmtBusy = false;    // re-entrancy guard: clSelectionRange moves the caret on purpose
  let clRibbonWired = false;
  let clSurfaceWired = false;

  const clF = () => (window.TWFmt && typeof window.TWFmt.patchRuns === "function") ? window.TWFmt : null;

  /** The computed run format at a node, walking up to (not past) the block.
   *  Inline styles only — a `tw-bold` CLASS on the block is the template's own weight, not an
   *  estimator's edit, and reading it would make the first press look like a no-op. */
  function clFmtAt(node, stop) {
    const out = { bold: null, italic: null, underline: null, size_pt: null };
    let el = node && node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
    while (el && el !== stop && el !== document.body) {
      const s = el.style;
      if (out.bold === null && s.fontWeight) out.bold = Number(s.fontWeight) >= 600;
      if (out.italic === null && s.fontStyle) out.italic = s.fontStyle === "italic";
      if (out.underline === null && s.textDecorationLine) {
        out.underline = s.textDecorationLine.includes("underline");
      }
      // The shorthand too, exactly as the proposal's reader does it. `text-decoration:underline`
      // is what clRunCss writes, and a browser fills the longhand in from it -- but a value that
      // only ever arrives as the shorthand (a paste, a hand-written style) would read as "not
      // underlined" if this branch were missing, and the button would show the wrong state.
      if (out.underline === null && s.textDecoration) {
        out.underline = String(s.textDecoration).includes("underline");
      }
      if (out.size_pt === null && s.fontSize && s.fontSize.endsWith("pt")) {
        out.size_pt = parseFloat(s.fontSize);
      }
      el = el.parentElement;
    }
    return out;
  }

  const clSameFmt = (a, b) => CL_RUN_KEYS.every((k) => a[k] === b[k]);

  /** One walk over the block, producing the text runs and where each one sits. Everything else
   *  here — the stored runs, the toolbar's character offsets, the caret restore — is derived from
   *  this single walker, so the offsets a press acts on and the offsets that get saved cannot
   *  disagree. `serialize()` above stays the plain-text answer for the same content. */
  function clSegments(el) {
    const segs = [];
    const push = (text, node, n2) => {
      if (!text) return;
      const fill = n2 && n2.parentElement ? n2.parentElement.closest(".tw-fill[data-token]") : null;
      segs.push({ text: text, fmt: clFmtAt(n2, el), node: node,
                  tok: fill && el.contains(fill) ? fill.dataset.token : null });
    };
    const walk = (node) => {
      node.childNodes.forEach((n) => {
        if (n.nodeType === Node.TEXT_NODE) {
          push(String(n.nodeValue).replace(/\u00a0/g, " "), n, n);
          return;
        }
        if (n.nodeType !== Node.ELEMENT_NODE) return;
        if (n.tagName === "BR") { push("\n", null, n); return; }
        if (/^(DIV|P)$/.test(n.tagName)) {
          const last = segs[segs.length - 1];
          if (last && !last.text.endsWith("\n")) push("\n", null, n);
        }
        walk(n);
      });
    };
    walk(el);
    return segs;
  }

  /** The editing view: runs split at both format and token boundaries, so a re-render after a
   *  press can put the `.tw-fill` spans back exactly where they were. */
  function clEditRuns(el) {
    const merged = [];
    for (const s of clSegments(el)) {
      const prev = merged[merged.length - 1];
      if (prev && clSameFmt(prev._f, s.fmt) && prev.tok === s.tok) { prev.text += s.text; continue; }
      merged.push({ text: s.text, tok: s.tok, _f: s.fmt });
    }
    return merged.map((r) => {
      const out = { text: r.text, tok: r.tok };
      for (const k of CL_RUN_KEYS) if (r._f[k] !== null) out[k] = r._f[k];
      return out;
    });
  }

  /** What gets SAVED. No `tok`: `restoreSaved` replays a saved paragraph as text, so the fill
   *  spans are already not round-tripped, and carrying the token here would only invite the
   *  proposal's whole token-safety analysis into a file that has no use for it. It is stripped
   *  BEFORE coalescing, because coalesce compares tok as well as the four run keys — leave it on
   *  and plain text stays split into one run per token, which reads as formatting that isn't. */
  function clStoredRuns(el) {
    const F = clF();
    if (!F) return [];
    return F.coalesce(clEditRuns(el).map((r) => {
      const out = { text: r.text };
      for (const k of CL_RUN_KEYS) if (r[k] !== undefined) out[k] = r[k];
      return out;
    }));
  }

  function clRunsArePlain(runs) {
    return runs.length <= 1 && (!runs[0] || CL_RUN_KEYS.every((k) => runs[0][k] === undefined));
  }

  function clRunsEqual(a, b) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (String(a[i].text) !== String(b[i].text)) return false;
      if ((a[i].tok || null) !== (b[i].tok || null)) return false;
      for (const k of CL_RUN_KEYS) if (a[i][k] !== b[i][k]) return false;
    }
    return true;
  }

  /** `false` is not the same as absent: absent means "inherit the template's own run", `false`
   *  means the estimator turned it off and the .docx must say so explicitly. */
  function clRunCss(s) {
    let css = "";
    if (s.bold === true) css += "font-weight:700;";
    else if (s.bold === false) css += "font-weight:400;";
    if (s.italic === true) css += "font-style:italic;";
    else if (s.italic === false) css += "font-style:normal;";
    if (s.underline === true) css += "text-decoration:underline;";
    else if (s.underline === false) css += "text-decoration-line:none;";
    if (s.size_pt) css += `font-size:${Number(s.size_pt)}pt;`;
    return css;
  }

  function clRenderRuns(el, runs) {
    let html = "";
    for (const r of runs) {
      let inner = esc(String(r.text));
      if (r.tok) inner = `<span class="tw-fill" data-token="${esc(r.tok)}">${inner}</span>`;
      const css = clRunCss(r);
      html += css ? `<span style="${css}">${inner}</span>` : inner;
    }
    el.innerHTML = html || "<br>";
  }

  /** A character offset back to a caret position, skipping the synthetic newlines (they have no
   *  text node of their own to sit in). */
  function clPointAt(el, offset) {
    let pos = 0, last = null;
    for (const s of clSegments(el)) {
      if (s.node) {
        if (offset <= pos + s.text.length) return { node: s.node, offset: offset - pos };
        last = { node: s.node, offset: s.text.length };
      }
      pos += s.text.length;
    }
    return last;
  }

  function clPlaceSelection(el, start, end) {
    const a = clPointAt(el, start), b = clPointAt(el, end);
    if (!a || !b) return;
    const r = document.createRange();
    try {
      r.setStart(a.node, Math.max(0, Math.min(a.offset, a.node.length)));
      r.setEnd(b.node, Math.max(0, Math.min(b.offset, b.node.length)));
    } catch { return; }
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
  }

  /** The live selection as character offsets into the block. Measured by dropping two marker
   *  characters at the range's ends and reading them back out of the same walker every other
   *  offset here comes from — so a DOM the walker flattens differently than the browser does
   *  cannot put the press on the wrong words. The markers are removed and the caret is put back
   *  before returning. */
  function clSelectionRange(el) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return null;
    const r = sel.getRangeAt(0);
    if (!el.contains(r.startContainer) || !el.contains(r.endContainer)) return null;
    const prev = clFmtBusy;
    clFmtBusy = true;
    try {
      const a = document.createTextNode(CL_MARK_A), b = document.createTextNode(CL_MARK_B);
      const rb = r.cloneRange(); rb.collapse(false); rb.insertNode(b);
      const ra = r.cloneRange(); ra.collapse(true); ra.insertNode(a);
      const text = clSegments(el).map((s) => s.text).join("");
      a.remove(); b.remove();
      el.normalize();
      let i = text.indexOf(CL_MARK_A), j = text.indexOf(CL_MARK_B);
      if (i < 0 || j < 0) return null;
      if (j > i) j -= 1;                      // MARK_A shifted everything after it along by one
      const out = [Math.min(i, j), Math.max(i, j)];
      clPlaceSelection(el, out[0], out[1]);   // put back what the markers disturbed
      return out;
    } catch {
      return null;
    } finally {
      clFmtBusy = prev;
    }
  }

  /** What the buttons should show, and what a press would act on. A collapsed caret means "this
   *  whole paragraph" — pressing B with the cursor resting in a line is a request to bold the
   *  line, not to bold nothing. */
  function clSelectionFormat(el, fallback) {
    const F = clF();
    const runs = clEditRuns(el);
    const total = F ? F.runsLength(runs) : 0;
    const live = clSelectionRange(el);
    const sel = live || fallback || null;
    let start = sel ? sel[0] : 0, end = sel ? sel[1] : total;
    start = Math.max(0, Math.min(start, total));
    end = Math.max(start, Math.min(end, total));
    if (start === end) { start = 0; end = total; }
    const f = (F && total) ? F.summarize(runs, start, end) : {};
    return { bold: f.bold, italic: f.italic, underline: f.underline, size_pt: f.size_pt,
             range: [start, end], empty: total === 0, live: !!live };
  }

  /** The paragraph the ribbon is aimed at, or null. Re-checked against the live DOM every time:
   *  `render()` rebuilds the whole surface on a work-type switch, and a remembered block from the
   *  previous template is a paragraph that no longer exists. */
  function clTargetBlock() {
    if (clFmtBlock && (!surface || !surface.contains(clFmtBlock))) {
      clFmtBlock = null;
      clFmtRange = null;
    }
    return clFmtBlock;
  }

  function clAimAt(el) {
    if (el !== clFmtBlock) clFmtRange = null;
    if (clFmtBlock && clFmtBlock !== el) clFmtBlock.classList.remove("tw-fmt-target");
    if (el) el.classList.add("tw-fmt-target");
    clFmtBlock = el || null;
    clRenderFmtBar();
  }

  function clAimClear() {
    if (clFmtBlock) clFmtBlock.classList.remove("tw-fmt-target");
    clFmtBlock = null;
    clFmtRange = null;
  }

  function clBlockAtSelection() {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !surface) return null;
    const n = sel.getRangeAt(0).startContainer;
    const el = n && n.nodeType === Node.TEXT_NODE ? n.parentElement : n;
    if (!el || !el.closest || !surface.contains(el)) return null;
    return el.closest(".tw-block");
  }

  const clBar = () => {
    const make = g("ensureFmtBar");
    if (make) { try { return make(); } catch { /* fall through to the DOM */ } }
    return document.querySelector(".tw-fmtbar");
  };

  /** Paint the shared ribbon for the LETTER. Only ever called once a caller has already confirmed
   *  the ribbon's target is a letter paragraph (`clAimAt`, or a press already gated on
   *  `clTargetBlock()`) — nothing here decides whether the letter owns the bar, only how it looks
   *  once it does. */
  function clRenderFmtBar() {
    const bar = clBar();
    if (!bar) return;
    const el = clTargetBlock();
    bar.classList.toggle("tw-fmtbar-idle", !el);
    // RE-ENABLE. This is the half a capture-phase interceptor cannot do for itself: the proposal
    // disabled these when it let go of its paragraph, and a disabled button fires no click for
    // anyone to intercept.
    bar.querySelectorAll("button[data-fmt],input[data-fmt]").forEach((n) => { n.disabled = !el; });
    // The paragraph group stays out of the way. Bullets and indents are properties of a proposal
    // block record; a cover-letter block has neither, so the honest thing is to show no control
    // rather than one that reads as available and does nothing.
    bar.querySelectorAll("[data-para]").forEach((n) => {
      n.style.visibility = "hidden";
      if (n.tagName === "BUTTON") n.disabled = true;
    });
    const f = el ? clSelectionFormat(el, clFmtRange) : null;
    if (f && f.live) clFmtRange = f.range;
    bar.querySelectorAll("button[data-fmt]").forEach((b) => {
      const k = b.dataset.fmt;
      const on = !!(f && k !== "reset" && f[k] === true);
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    const size = bar.querySelector("input[data-fmt='size']");
    if (size && document.activeElement !== size) {
      size.value = (f && f.size_pt) ? String(f.size_pt) : "";
    }
  }

  /** Hand the ribbon back. `renderFmtBar()`'s own idle branch clears the buttons, empties the
   *  size box and restores the paragraph group's visibility, so there is nothing to undo here. */
  function clReleaseFmtBar() {
    clAimClear();
    const f = g("renderFmtBar");
    if (f) { try { f(); } catch { /* the proposal's ribbon is the proposal's problem */ } }
  }

  /** Apply one patch to the current selection. Returns true if the document actually changed. */
  function clApplyFormat(el, patch, range) {
    const F = clF();
    if (!F) return false;
    const runs = clEditRuns(el);
    const start = range[0], end = range[1];
    if (end <= start) return false;
    const next = F.patchRuns(runs, start, end, patch);
    // A PRESS THAT CHANGES NOTHING IS NOT AN EDIT. Without this, Reset on an untouched paragraph
    // would mark it edited and ship an override that says exactly what the template already says
    // — and "an untouched letter carries no overrides", which the version gate leans on, would
    // quietly stop being true.
    if (clRunsEqual(runs, next)) return false;
    const sel = window.getSelection();
    const inSurface = !!(sel && sel.rangeCount && surface &&
                         surface.contains(sel.getRangeAt(0).startContainer));
    clRenderRuns(el, next);
    if (inSurface) clPlaceSelection(el, start, end);
    clFmtRange = [start, end];
    // `tw-fmt` is what makes a format-only edit survive collect(). The synthetic input event then
    // takes the ordinary path — dirty/empty classes, the 800ms persist — rather than a second one.
    // Neither innerHTML nor a Range fires input on its own, which is why it is dispatched here.
    el.classList.add("tw-fmt");
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  }

  function clPress(key) {
    const F = clF();
    const el = clTargetBlock();
    if (!F || !el) return;
    const f = clSelectionFormat(el, clFmtRange);
    if (f.empty) return;
    if (key === "reset") {
      clApplyFormat(el, { bold: null, italic: null, underline: null, size_pt: null }, f.range);
    } else {
      const patch = {};
      patch[key] = F.nextToggle(f[key]);
      clApplyFormat(el, patch, f.range);
    }
    clRenderFmtBar();
  }

  /** Half-points, the writer's real granularity; empty means "back to the template's own size". */
  function clTypedSize(raw) {
    const t = String(raw == null ? "" : raw).trim().replace(/\s*pt$/i, "");
    if (t === "") return null;
    const n = Number(t);
    if (!Number.isFinite(n)) return undefined;
    const half = Math.round(n * 2) / 2;
    if (half < 1 || half > 200) return undefined;
    return half;
  }

  function clCommitSize(box) {
    const el = clTargetBlock();
    if (!el) return;
    const v = clTypedSize(box.value);
    const f = clSelectionFormat(el, clFmtRange);
    if (v === undefined) {                       // unreadable — put back what is actually there
      box.value = f.size_pt ? String(f.size_pt) : "";
      return;
    }
    clApplyFormat(el, { size_pt: v }, f.range);
    clRenderFmtBar();
  }

  /** Take the press before the proposal does — but only while the ribbon is actually aimed at a
   *  letter paragraph (`clTargetBlock()`), so a press made while the proposal owns the bar reaches
   *  the proposal exactly as it always has.
   *
   *  On `#fmt-ribbon` and in the CAPTURE phase: the ribbon is the PARENT of `.tw-fmtbar`, so
   *  capture here runs before the bar's own bubble-phase click, change and keydown handlers and
   *  before the button itself.
   *
   *  Only `button[data-fmt]` is taken. A click on the size box must reach it and focus it; the
   *  proposal's own click handler returns early on anything that is not a button[data-fmt], so
   *  letting it through costs nothing. The bar's mousedown preventDefault — which is what keeps
   *  the estimator's selection alive across a press — is left exactly as it is. */
  function clWireRibbon() {
    const host = document.getElementById("fmt-ribbon");
    if (!host || clRibbonWired) return;
    clRibbonWired = true;

    host.addEventListener("click", (e) => {
      if (!clTargetBlock()) return;
      const t = e.target && e.target.closest ? e.target : null;
      if (!t || !t.closest(".tw-fmtbar")) return;
      const btn = t.closest("button[data-fmt]");
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      clPress(btn.dataset.fmt);
    }, true);

    host.addEventListener("change", (e) => {
      if (!clTargetBlock()) return;
      const t = e.target && e.target.closest ? e.target : null;
      const box = t ? t.closest("input[data-fmt='size']") : null;
      if (!box || !box.closest(".tw-fmtbar")) return;
      e.stopPropagation();
      clCommitSize(box);
    }, true);

    host.addEventListener("keydown", (e) => {
      if (!clTargetBlock()) return;
      const t = e.target && e.target.closest ? e.target : null;
      const box = t ? t.closest("input[data-fmt='size']") : null;
      if (!box || !box.closest(".tw-fmtbar")) return;
      if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); clCommitSize(box); }
      else if (e.key === "Escape") {
        e.preventDefault(); e.stopPropagation();
        const el = clTargetBlock();
        const f = el ? clSelectionFormat(el, clFmtRange) : null;
        box.value = (f && f.size_pt) ? String(f.size_pt) : "";
        box.blur();
      }
    }, true);
  }

  /** Keep the ribbon aimed as the caret moves, and give the letter its own Ctrl+B/I/U.
   *
   *  Both are needed because the proposal's equivalents are scoped to `#doc-surface`: its
   *  selectionchange only re-aims for a line that surface contains, and its Ctrl+B keydown is
   *  bound to that surface, so neither ever fires for the letter. The selectionchange below is
   *  the only thing that can aim at a cover-letter paragraph at all — the editing host is the
   *  page or the box, not the paragraph, so moving between paragraphs raises no focus event.
   *
   *  RELEASES ITS OWN TARGET when the selection leaves `#cl-surface` entirely, so the letter's
   *  last paragraph does not sit highlighted as the ribbon's target after the estimator has
   *  moved on to a proposal paragraph (or anywhere else). The reverse direction — a stale
   *  highlight left on a PROPOSAL paragraph after the ribbon moves to the letter — is the
   *  proposal's own state to clear and is not reached from here, matching the existing rule that
   *  this file never calls into proposal-review.js. */
  function clWireSurface() {
    if (!surface || clSurfaceWired) return;
    clSurfaceWired = true;

    document.addEventListener("selectionchange", () => {
      if (clFmtBusy) return;
      const el = clBlockAtSelection();
      if (el) { clAimAt(el); return; }
      if (clFmtBlock) clAimClear();
    });

    surface.addEventListener("keydown", (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      const k = String(e.key).toLowerCase();
      if (k !== "b" && k !== "i" && k !== "u") return;
      const el = clBlockAtSelection();
      if (!el) return;
      e.preventDefault();
      if (el !== clTargetBlock()) clAimAt(el);
      clPress(k === "b" ? "bold" : k === "i" ? "italic" : "underline");
    });
  }

  // ── the switch ────────────────────────────────────────────────────────────────────────────
  /** Reflect the toggle. Turning it OFF never deletes the edits — the store keeps them, so
   *  switching the letter back on later brings the estimator's wording back rather than making
   *  them retype it. `cover_letter_enabled: false` is enough for the backend to skip the file.
   *
   *  `surface.hidden`, not a class, and not `display: none` written directly — the ordinary
   *  `hidden` attribute is what the rest of this page toggles visibility with, and a CSS class
   *  that sets its own `display` on `#cl-surface` would silently defeat it (the exact bug
   *  `hidden-attribute-cascade-trap.md` documents, already hit four times on this codebase). No
   *  off-stage trick is needed any more either: there is no second "hidden but must still lay
   *  out" state to protect once the letter is simply present or absent, never mid tab-switch. */
  function setEnabled(on) {
    const enabled = !!on;
    document.body.classList.toggle("cl-on", enabled);
    try { TW.setState({ cover_letter_enabled: enabled }); } catch {}
    if (surface) surface.hidden = !enabled;
    if (enabled) { clWireSurface(); load(false); }
    else clAimClear();   // let go of the ribbon if it was aimed at a letter paragraph
  }

  // ── wiring ────────────────────────────────────────────────────────────────────────────────
  function init() {
    toggleEl = document.getElementById("cl-toggle");
    surface = document.getElementById("cl-surface");
    if (!toggleEl || !surface) return;   // not this page
    clWireRibbon();

    toggleEl.checked = !!live("cover_letter_enabled");
    toggleEl.addEventListener("change", () => setEnabled(toggleEl.checked));
    setEnabled(toggleEl.checked);

    // A base-bid switch changes the effective work type with no page load, which picks a
    // different letter. Nothing broadcasts that — there is no event bus on this page — so the
    // re-check has to be driven off whatever the estimator does next. `load(false)` is a no-op
    // whenever the key is unchanged (`loadedFor === want`), so these are cheap to fire often.
    //
    // Two triggers, covering the two ways a stale letter can be reached while it's on screen:
    //   visibilitychange   — flipped the base bid, left the tab, returned
    //   pointerdown        — flipped it and never left the page
    //
    // The second is the one that matters and the one that was missing when this only ran on tab
    // reveal. The letter stays on screen showing the old work type's template, and the overrides
    // `persistNow()` has already stamped are keyed to that old template — so pressing Continue
    // ships edits the backend version-gate then silently drops (template_version is the file's
    // mtime; a mismatch discards every paragraph override). Safe, but the estimator's wording
    // vanishes with no warning.
    //
    // Capture phase and document-wide, because the click that reveals the staleness is usually
    // the click INTO the letter. Re-rendering under a live pointer normally steals the
    // interaction the estimator just started, which is a real cost — but it is only paid when the
    // letter on screen is genuinely the wrong document, and losing one click beats typing a
    // paragraph into a template that is about to be thrown away.
    //
    // EXCEPT while the amber error panel is up (`surface.classList.contains("cl-error")`,
    // set by showError / cleared by showLoading). `load()` starts synchronously — it calls
    // showLoading(), which does `surface.textContent = ""`, before its first `await` — so a
    // capture-phase pointerdown on the panel's OWN "Try again" / "Turn the cover letter off"
    // buttons ran this same recheck first and detached them before their own click handlers
    // could fire (per the UI Events spec, `click` does not dispatch when the target is removed
    // between pointerdown and pointerup). Both buttons appear to do nothing; "Turn the cover
    // letter off" is the one that silently breaks, since nothing else would flip the checkbox.
    // The panel's buttons already call load() themselves on success — skipping the recheck here
    // costs nothing but a redundant reload we were about to trigger anyway.
    const recheck = () => {
      if (!surface.hidden && !surface.classList.contains("cl-error")) load(false);
    };
    document.addEventListener("visibilitychange", () => { if (!document.hidden) recheck(); });
    document.addEventListener("pointerdown", recheck, true);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  // Tested surface. Everything here is a pure function of its arguments or of TW state, which is
  // what lets the harness exercise the store rules without a DOM.
  window.TWCoverLetter = {
    workType: clWorkType,
    audience: clAudience,
    key: clKey,
    mergeEntry: clMergeEntry,
    savedFor: clSavedFor,
    collect: collect,
    serialize: serialize,
    fillPlain: fillPlain,
    setEnabled: setEnabled,
    load: load,
    /** The two override fields the generate payload carries. One reader, so the Proposal step's
     *  Continue and the Files page's rebuild cannot drift into disagreeing about what was sent.
     *  `cover_letter_enabled` itself is NOT here — proposal-review.js reads that straight off
     *  `liveKey("cover_letter_enabled")` and has since the fix for the bug recorded at that read:
     *  a second path re-deriving the same flag from a different snapshot is exactly the shape
     *  that bug was.
     *
     *  FLUSHES THE PENDING DEBOUNCE FIRST. This reads the persisted store, and `persistNow` runs
     *  800ms after the last keystroke — so an estimator who types a sentence and clicks Continue
     *  inside that window had the sentence silently dropped from the generate payload and from the
     *  revision frozen for the customer. Only when a timer is actually pending: an unconditional
     *  write would stamp the keyed store with the module's empty `templateVersion` on a page (or a
     *  harness) where the editor never loaded. */
    payloadFields: function () {
      if (persistTimer) persistNow();
      const enabled = !!live("cover_letter_enabled");
      const flat = live("cover_letter_paragraph_overrides");
      return {
        cover_letter_paragraph_overrides:
          (enabled && flat && typeof flat === "object" && !Array.isArray(flat)) ? flat : {},
        cover_letter_template_version: enabled ? String(live("cover_letter_template_version") || "") : "",
      };
    },
  };
})();
