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
// that appears without being asked for is a document nobody proofread. Turning it on reveals two
// document tabs at the left of the formatting ribbon — Proposal | Cover letter — and renders the
// real template on its own page surface. Every paragraph is editable; edits persist into the
// draft the same way the proposal's do and ride the generate payload as
// `cover_letter_paragraph_overrides`.
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
  let tabsEl = null;           // the Proposal | Cover letter switch
  let toggleEl = null;         // the ribbon checkbox
  let blocks = null;           // the template's block records
  let templateVersion = "";
  let pristine = new Map();    // block id -> the template's own rendering, the edit baseline
  let activeTab = "proposal";
  let loadedFor = "";          // "wt:audience:v" of what is currently on screen
  let loading = false;
  const artCache = new Map();

  // ── rendering ─────────────────────────────────────────────────────────────────────────────
  function fillPlain(text, tokens) {
    CL_TOKEN_RE.lastIndex = 0;
    return String(text).replace(CL_TOKEN_RE, (m0, name) =>
      Object.prototype.hasOwnProperty.call(tokens, name) ? String(tokens[name]) : m0);
  }

  /** Substituted HTML for one paragraph. Each filled token is wrapped in `.tw-fill` so a value
   *  that came from the estimate is visibly a value and not typing — the same cue, the same
   *  class and therefore the same yellow as the proposal beside it. Screen only; the .docx is
   *  filled server-side from the tokens, never from this HTML. */
  function blockHtml(b, tokens) {
    CL_TOKEN_RE.lastIndex = 0;
    let html = "", last = 0, m;
    const text = String(b.text || "");
    while ((m = CL_TOKEN_RE.exec(text))) {
      html += esc(text.slice(last, m.index));
      const known = Object.prototype.hasOwnProperty.call(tokens, m[1]);
      html += `<span class="tw-fill" data-token="${esc(m[1])}">` +
              esc(known ? String(tokens[m[1]]) : m[0]) + "</span>";
      last = m.index + m[0].length;
    }
    return html + esc(text.slice(last));
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
    if (b.list) el.classList.add("tw-li");
    else if (b.style && b.style.name === "List Paragraph") el.classList.add("tw-list");
    if (b.align) el.style.textAlign = b.align;
    if (b.style && b.style.bold) el.classList.add("tw-bold");
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
      el.textContent = entry.text;          // pre-wrap renders the \n line breaks
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
      if (cur === pristine.get(id)) return;
      out[String(id)] = { text: cur };
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
      el.classList.toggle("tw-dirty", cur !== pristine.get(id));
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

  // ── the switch ────────────────────────────────────────────────────────────────────────────
  /** Show one document, hide the other.
   *
   *  The inactive surface is moved OFF-SCREEN rather than to `display: none`, and that is not
   *  fussiness. The proposal's terms pages are paginated by measuring real element heights, and
   *  everything inside a `display: none` subtree measures zero — so a repagination that happened
   *  to fire while the proposal was hidden would silently pack the Terms wrong and there would be
   *  nothing on screen to notice it by. Off-screen still lays out, so every measurement the other
   *  editor takes stays true whichever tab is in front. */
  function showTab(which) {
    activeTab = which === "cover" ? "cover" : "proposal";
    const docSurf = document.getElementById("doc-surface");
    if (docSurf) docSurf.classList.toggle("cl-offstage", activeTab === "cover");
    if (surface) surface.classList.toggle("cl-offstage", activeTab !== "cover");
    if (tabsEl) {
      tabsEl.querySelectorAll(".tab").forEach((t) => {
        const on = (t.dataset.doc || "proposal") === activeTab;
        t.classList.toggle("active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
    }
    // LET GO OF THE PROPOSAL PARAGRAPH. The formatting ribbon deliberately keeps its target after
    // focus leaves it (Kyle: the bar must not vanish when you reach for it), and it is scoped to
    // #doc-surface — so while the cover letter is in front, a press on Bold would format a
    // proposal paragraph that is not on screen. `idleFmtBar` is the existing way to say "aimed at
    // nothing"; it clears the target, the range and the buttons in one call.
    if (activeTab === "cover") { const f = g("idleFmtBar"); if (f) { try { f(); } catch {} } }
    if (activeTab === "cover") load(false);
  }

  /** Reflect the toggle. Turning it OFF never deletes the edits — the store keeps them, so
   *  switching the letter back on later brings the estimator's wording back rather than making
   *  them retype it. `cover_letter_enabled: false` is enough for the backend to skip the file. */
  function setEnabled(on, reveal) {
    const enabled = !!on;
    if (tabsEl) tabsEl.hidden = !enabled;
    document.body.classList.toggle("cl-on", enabled);
    try { TW.setState({ cover_letter_enabled: enabled }); } catch {}
    if (!enabled) showTab("proposal");
    else if (reveal) showTab("cover");           // they just asked for it — show it to them
    else load(false);                            // page load: stay on the proposal, warm the letter
  }

  // ── wiring ────────────────────────────────────────────────────────────────────────────────
  function init() {
    toggleEl = document.getElementById("cl-toggle");
    tabsEl = document.getElementById("doc-tabs");
    surface = document.getElementById("cl-surface");
    if (!toggleEl || !tabsEl || !surface) return;   // not this page

    toggleEl.checked = !!live("cover_letter_enabled");
    // REVEAL ON A TICK, NOT ON A RELOAD. Ticking the box is a request to see the thing, and a
    // checkbox whose only visible effect is a tab strip appearing somewhere else is a checkbox
    // people press twice. Re-opening a draft that already has a letter is the opposite: this step
    // is called "3 - Proposal", so it opens on the proposal and the letter warms up off-stage.
    toggleEl.addEventListener("change", () => setEnabled(toggleEl.checked, true));
    tabsEl.addEventListener("click", (e) => {
      const t = e.target && e.target.closest ? e.target.closest(".tab") : null;
      if (t) showTab(t.dataset.doc || "proposal");
    });
    setEnabled(toggleEl.checked);

    // A base-bid switch changes the effective work type with no page load, which picks a
    // different letter. Nothing broadcasts that — there is no event bus on this page — so the
    // re-check has to be driven off whatever the estimator does next. `load(false)` is a no-op
    // whenever the key is unchanged (`loadedFor === want`), so these are cheap to fire often.
    //
    // Three triggers, covering the three ways a stale letter can be reached:
    //   showTab("cover")   — flipped the base bid while the proposal was in front, then came back
    //   visibilitychange   — flipped it, left the tab, returned
    //   pointerdown        — flipped it while the LETTER was in front and never left the page
    //
    // The last one is the one that matters and the one that was missing. The letter stays on
    // screen showing the old work type's template, and the overrides `persistNow()` has already
    // stamped are keyed to that old template — so pressing Continue ships edits the backend
    // version-gate then silently drops (template_version is the file's mtime; a mismatch discards
    // every paragraph override). Safe, but the estimator's wording vanishes with no warning.
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
      if (activeTab === "cover" && !surface.classList.contains("cl-error")) load(false);
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
    showTab: showTab,
    setEnabled: setEnabled,
    load: load,
    /** The three fields the generate payload carries. One reader, so the Proposal step's Continue
     *  and the Files page's rebuild cannot drift into disagreeing about what was sent.
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
        cover_letter_enabled: enabled,
        cover_letter_paragraph_overrides:
          (enabled && flat && typeof flat === "object" && !Array.isArray(flat)) ? flat : {},
        cover_letter_template_version: enabled ? String(live("cover_letter_template_version") || "") : "",
      };
    },
  };
})();
