/* Project Info Sheet — the ops hand-off workbook, as a real grid.
 *
 * Five tabs (Info Sheet, SOV, Foundation Import, Invoice, Deposit), every cell
 * editable, insert/delete of rows and columns, and the chartreuse/pink colour
 * key Hanz marks up by hand today. Shares its plumbing with the estimate grid
 * through TWXL (js/xl-core.js); everything specific to this workbook is here.
 *
 * VALUE CONVENTION — `info_cell_values[key]` holds the entry NORMALIZED on
 * commit, not the raw text: a number for numeric formats, a fraction for
 * percents, the raw string for text cells, the verbatim "=…" for a typed
 * formula. Storing raw text is how the estimate grid ends up persisting
 * "82,496", which the writer then fails to parse and lands in a money cell as
 * text. Old drafts already hold numbers under these keys, so they round-trip.
 *
 * FORMULA CELLS are editable like any other, so the resting view has to show
 * the computed value and the edit view the formula. If focus alone exposed the
 * computed value, tabbing through B18 would record "Epoxy - Commercial" as an
 * override and flatten the formula — and Foundation Import, the Invoice and the
 * Deposit tab all read this sheet.
 */
(function () {
  "use strict";

  const host      = document.getElementById("sheet-grid");
  const viewport  = document.getElementById("xl-viewport");
  const tabBar    = document.getElementById("tab-bar");
  const projLabel = document.getElementById("proj-name");
  const saveLabel = document.getElementById("save-state");
  const dlBtn     = document.getElementById("dl-btn");
  const fbarName  = document.getElementById("fbar-name");
  const fbarInput = document.getElementById("fbar-input");

  const X = window.TWXL;

  let order = [];                  // tab names, workbook order
  let grids = {};                  // name → grid payload (mutated by struct ops)
  let engine = null;
  let activeSheet = null;
  let textCells = new Set();       // "Info Sheet!B14"
  let cellValues = {};             // "SOV!C12" → normalized entry
  let structs = [];                // [{sheet, kind, at, count}]
  let draftId = null;
  const sizes = {};                // name → {colPx, rowPx}; session-only
  let teardown = [];               // detach fns for the current render
  let activeInput = null;
  let fbarDirty = false;

  const SHEET_INFO = "Info Sheet";   // the one tab the prefill and colour key apply to
  const keyOf = (sheet, addr) => sheet + "!" + addr;
  const isTextCell = (sheet, addr, fmt) =>
    textCells.has(keyOf(sheet, addr)) || X.isTextFmt(fmt);

  /* ── values ──────────────────────────────────────────────────────── */

  function stored(sheet, cell) {
    const k = keyOf(sheet, cell.addr);
    return Object.prototype.hasOwnProperty.call(cellValues, k) ? cellValues[k] : undefined;
  }

  /** Did the estimator actually change anything?
   *
   *  Matters more than it looks: every cell is an input now, so simply tabbing
   *  across the sheet fires a commit on each one. Without this, a pass through
   *  the grid would pin every formula as an override — and `refreshDerived`
   *  stops updating a cell the user owns, so the sheet would quietly freeze.
   */
  function unchanged(sheet, cell, typed) {
    const blank = (v) => v === "" || v === undefined || v === null;
    if (cell.isFormula) {
      const live = engine.getFormula(sheet, cell.addr);
      return typed === cell.formula || typed === live;
    }
    const base = cell.value === undefined ? "" : cell.value;
    return typed === base || (blank(typed) && blank(base));
  }

  function record(sheet, cell, typed) {
    const k = keyOf(sheet, cell.addr);
    if (unchanged(sheet, cell, typed)) delete cellValues[k];
    else cellValues[k] = typed;
    engine.setCellValue(sheet, cell.addr, typed);
    persist();
  }

  /* ── persistence ─────────────────────────────────────────────────── */

  let saveTimer = null;
  function persist() {
    clearTimeout(saveTimer);
    saveLabel.textContent = "Saving…";
    saveTimer = setTimeout(() => {
      TW.setState({ info_cell_values: cellValues, info_tab_structs: structs });
      saveLabel.textContent = "Saved";
      setTimeout(() => { if (saveLabel.textContent === "Saved") saveLabel.textContent = ""; }, 2200);
    }, 400);
  }

  /* ── formula bar ─────────────────────────────────────────────────── */

  function syncFormulaBar() {
    if (!activeInput || !activeInput.isConnected) {
      fbarName.value = ""; fbarInput.value = "";
      fbarInput.disabled = true; fbarDirty = false;
      return;
    }
    fbarInput.disabled = false;
    fbarName.value = activeInput.dataset.displayAddr || "";
    fbarInput.value = activeInput.value;
    fbarInput.readOnly = activeInput.tagName === "SELECT";
    fbarDirty = false;
  }

  // The bar never talks to the engine. It writes the cell's value and fires
  // the same events a keystroke would, so it inherits parsing, percent
  // handling and the resting view for free.
  fbarInput.addEventListener("input", () => {
    if (!activeInput) return;
    fbarDirty = true;
    activeInput.value = fbarInput.value;
    activeInput.dispatchEvent(new Event("input", { bubbles: true }));
  });
  fbarInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (activeInput) {
        activeInput.dispatchEvent(new Event("change", { bubbles: true }));
        activeInput.focus();
      }
      fbarDirty = false;
    } else if (e.key === "Escape") {
      e.preventDefault();
      syncFormulaBar();
      if (activeInput) activeInput.focus();
    }
  });
  fbarInput.addEventListener("blur", () => {
    if (fbarDirty && activeInput) activeInput.dispatchEvent(new Event("change", { bubbles: true }));
    fbarDirty = false;
  });

  /* ── rendering ───────────────────────────────────────────────────── */

  function styleCell(el, cell) {
    if (cell.fill)      el.style.background = cell.fill;
    if (cell.fontColor) el.style.color = cell.fontColor;
    if (cell.bold)      el.classList.add("bold");
    if (cell.italic)    el.classList.add("italic");
    if (cell.fontSize)  el.style.fontSize = Math.max(9, Math.round(cell.fontSize * 0.92)) + "px";
    if (cell.align === "center") el.style.justifyContent = "center";
    else if (cell.align === "right") el.style.justifyContent = "flex-end";
    else if (/#,##0|\$|%/.test(cell.fmt || "")) el.classList.add("numeric");
    X.applyBorders(el, cell.borders);
    // The colour key last, so provenance beats the template's own fill. Inline
    // rather than a class because the template fill is itself inline.
    if (cell.role === "prefill")  el.style.background = "#B3FF00";
    if (cell.role === "decision") el.style.background = "#FFB0FF";
  }

  function makeDataCell(sheet, cell, dropdowns) {
    const el = X.makeCell("", "", null);
    styleCell(el, cell);

    const fmt = cell.fmt || "";
    const asText = isTextCell(sheet, cell.addr, fmt);
    const saved = stored(sheet, cell);
    const options = dropdowns[cell.addr];

    const computed = () => {
      const v = engine.getValue(sheet, cell.addr);
      if (v && typeof v === "object") {          // an HF error wrapper
        return cell.value === undefined ? "" : String(cell.value);
      }
      return X.formatValue(v, fmt, { exactDecimals: true });
    };
    // What you'd type: your own entry, else the live formula (from the engine,
    // which is authoritative after a structural edit), else the plain value.
    const raw = () => {
      const s = stored(sheet, cell);
      if (s !== undefined) return s === null ? "" : String(s);
      if (cell.isFormula) return engine.getFormula(sheet, cell.addr) || cell.formula || "";
      const v = cell.value;
      return v === undefined || v === null ? "" : String(v);
    };

    if (options) {
      el.classList.add("haslist");
      const sel = document.createElement("select");
      const cur = String(saved !== undefined ? saved : (cell.value == null ? "" : cell.value));
      sel.appendChild(new Option("", ""));
      let matched = false;
      for (const opt of options) {
        const o = new Option(opt, opt);
        if (opt === cur) { o.selected = true; matched = true; }
        sel.appendChild(o);
      }
      // Keep a stored value the list no longer offers — blanking someone's
      // entry because an option was renamed is worse than an odd option.
      if (!matched && cur !== "") {
        const o = new Option(cur, cur); o.selected = true; sel.appendChild(o);
      }
      sel.dataset.displayAddr = cell.addr;
      sel.addEventListener("change", () => { record(sheet, cell, sel.value); refreshDerived(); });
      sel.addEventListener("focus", () => { activeInput = sel; syncFormulaBar(); });
      el.appendChild(sel);
      engine.registerDom(sheet, cell.addr, sel);
      return el;
    }

    const inp = document.createElement("input");
    inp.type = "text";
    inp.dataset.displayAddr = cell.addr;
    if (cell.isFormula) el.classList.add("formula-cell");

    // What the cell shows when it is not being edited. A formula — the
    // template's or one the estimator typed — rests as its RESULT; showing the
    // formula text at rest would mean the grid never displays an answer.
    const resting = (v) => {
      if (v === "" || v === undefined || v === null) return computed();
      if (typeof v === "string" && v.charAt(0) === "=") return computed();
      return X.formatValue(v, fmt, { exactDecimals: true }) || String(v);
    };
    inp.value = resting(saved);

    inp.addEventListener("focus", () => {
      inp.value = raw();
      activeInput = inp;
      syncFormulaBar();
      try { inp.select(); } catch (_) {}
    });
    inp.addEventListener("input", () => {
      if (!fbarDirty) fbarInput.value = inp.value;
    });
    inp.addEventListener("blur", () => {
      const typed = X.parseTyped(inp.value, fmt, asText);
      record(sheet, cell, typed);
      inp.value = resting(typed);
      refreshDerived();
    });
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") inp.blur(); });
    el.appendChild(inp);
    engine.registerDom(sheet, cell.addr, inp);
    return el;
  }

  /** Repaint every cell whose value the engine may have just changed. */
  function refreshDerived() {
    const grid = grids[activeSheet];
    if (!grid) return;
    for (const cell of grid.cells) {
      const el = engine.domBySheetAddr[keyOf(activeSheet, cell.addr)];
      if (!el || el === activeInput || el.tagName === "SELECT") continue;
      if (stored(activeSheet, cell) !== undefined) continue;   // the user owns it
      const v = engine.getValue(activeSheet, cell.addr);
      if (v && typeof v === "object") continue;                 // leave errors alone
      el.value = X.formatValue(v, cell.fmt || "", { exactDecimals: true });
    }
  }

  function renderSheet(name) {
    const grid = grids[name];
    const maxRow = Math.min(grid.max_row, 300);
    const maxCol = Math.min(grid.max_col, 80);
    const byAddr = new Map(grid.cells.map((c) => [c.addr, c]));

    const anchors = new Map();
    const hidden = new Set();
    for (const m of grid.merged || []) {
      anchors.set(m.anchor, m);
      for (let r = m.minRow; r <= m.maxRow; r++)
        for (let c = m.minCol; c <= m.maxCol; c++) {
          const a = X.addrOf(r, c);
          if (a !== m.anchor) hidden.add(a);
        }
    }

    const remembered = sizes[name] || {};
    const colPx = [], rowPx = [];
    for (let c = 1; c <= maxCol; c++)
      colPx.push((remembered.colPx && remembered.colPx[c - 1])
        || Math.max(56, Math.round((grid.col_widths[X.colLetter(c)] || 9) * 7.5)));
    for (let r = 1; r <= maxRow; r++)
      rowPx.push((remembered.rowPx && remembered.rowPx[r - 1])
        || Math.max(20, Math.round((grid.row_heights[r] || 15) * 1.33)));
    sizes[name] = { colPx, rowPx };

    const g = document.createElement("div");
    g.className = "xl-grid";
    g.style.gridTemplateColumns = "40px " + colPx.map((p) => p + "px").join(" ");
    g.style.gridTemplateRows = "22px " + rowPx.map((p) => p + "px").join(" ");

    g.appendChild(X.makeCell("corner", "", { row: 1, col: 1 }));
    for (let c = 1; c <= maxCol; c++) {
      const h = X.makeCell("col-header", X.colLetter(c), { row: 1, col: c + 1 });
      h.dataset.colIndex = String(c);
      const grip = document.createElement("div");
      grip.className = "resize-h"; grip.dataset.colIndex = String(c);
      h.appendChild(grip);
      g.appendChild(h);
    }
    for (let r = 1; r <= maxRow; r++) {
      const h = X.makeCell("row-header", String(r), { row: r + 1, col: 1 });
      h.dataset.rowIndex = String(r);
      const grip = document.createElement("div");
      grip.className = "resize-v"; grip.dataset.rowIndex = String(r);
      h.appendChild(grip);
      g.appendChild(h);
    }

    for (let r = 1; r <= maxRow; r++) {
      for (let c = 1; c <= maxCol; c++) {
        const addr = X.addrOf(r, c);
        if (hidden.has(addr)) continue;
        const cell = byAddr.get(addr) || { addr, row: r, col: c };
        const el = makeDataCell(name, cell, grid.dropdowns || {});
        el.style.gridRow = String(r + 1);
        el.style.gridColumn = String(c + 1);
        const span = anchors.get(addr);
        if (span) {
          el.style.gridRow = (r + 1) + " / span " + span.rowSpan;
          el.style.gridColumn = (c + 1) + " / span " + span.colSpan;
        }
        g.appendChild(el);
      }
    }

    host.className = "";
    host.innerHTML = "";
    host.appendChild(g);

    teardown.forEach((fn) => fn());
    teardown = [
      X.attachKeyboardNav(g, { maxRow, maxCol }),
      X.attachResizers(g, colPx, rowPx, viewport, { gutterW: 40, headerH: 22 }),
    ];
    wireContextMenu(g, name);
    refreshDerived();
  }

  function showSheet(name) {
    if (!grids[name]) return;
    activeSheet = name;
    activeInput = null;
    syncFormulaBar();
    engine.unregisterAll();
    try { sessionStorage.setItem("tw_info_tab", name); } catch (_) {}
    tabBar.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("active", b.dataset.sheet === name));
    renderSheet(name);
  }

  function renderTabs() {
    tabBar.innerHTML = "";
    for (const name of order) {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.sheet = name;
      b.textContent = name;
      b.addEventListener("click", () => showSheet(name));
      tabBar.appendChild(b);
    }
  }

  /* ── insert / delete rows and columns ────────────────────────────── */

  function applyStructOp(sheet, kind, at, count) {
    // The engine goes first and we abort if it refuses, so page state can
    // never describe a shape the engine does not have.
    if (!engine.structOp(sheet, kind, at, count)) {
      alert("Couldn't apply that change.");
      return;
    }
    const op = { sheet, kind, at, count };
    structs = structs.concat([op]);
    X.transformGridForOp(grids[sheet], op);
    X.rekeyKeyedMapForOp(cellValues, sheet, op);
    activeInput = null;
    syncFormulaBar();
    showSheet(sheet);
    persist();
  }

  function wireContextMenu(grid, sheet) {
    grid.addEventListener("contextmenu", (e) => {
      const cellEl = e.target.closest(".gridcell");
      if (!cellEl) return;
      e.preventDefault();

      const rowHdr = cellEl.classList.contains("row-header");
      const colHdr = cellEl.classList.contains("col-header");
      const inp = cellEl.querySelector("[data-display-addr]");
      const at = X.parseAddr(inp ? inp.dataset.displayAddr : "") ||
                 { r: parseInt(cellEl.dataset.rowIndex || "0", 10),
                   c: parseInt(cellEl.dataset.colIndex || "0", 10) };
      const r = rowHdr ? parseInt(cellEl.dataset.rowIndex, 10) : at.r;
      const c = colHdr ? parseInt(cellEl.dataset.colIndex, 10) : at.c;
      if (!r && !c) return;

      const L = X.colLetter(c);
      const items = [];
      if (!colHdr && r) {
        items.push({ label: "Insert row above " + r, fn: () => applyStructOp(sheet, "insert_rows", r, 1) });
        items.push({ label: "Insert row below " + r, fn: () => applyStructOp(sheet, "insert_rows", r + 1, 1) });
      }
      if (!rowHdr && c) {
        items.push({ label: "Insert column left of " + L, fn: () => applyStructOp(sheet, "insert_cols", c, 1) });
        items.push({ label: "Insert column right of " + L, fn: () => applyStructOp(sheet, "insert_cols", c + 1, 1) });
      }
      items.push(null);
      if (!colHdr && r) {
        items.push({ label: "Delete row " + r, danger: true,
                     fn: () => applyStructOp(sheet, "delete_rows", r, 1) });
      }
      if (!rowHdr && c) {
        items.push({ label: "Delete column " + L, danger: true,
                     fn: () => applyStructOp(sheet, "delete_cols", c, 1) });
      }
      X.openCtxMenu(e.clientX, e.clientY, items);
    });
  }

  /* ── download ────────────────────────────────────────────────────── */

  async function download() {
    const orig = dlBtn.textContent;
    dlBtn.disabled = true;
    dlBtn.textContent = "Building…";
    try {
      // Send the state WITH the request. shared.js debounces its PUT by 2.5 s
      // and every setState restarts that timer, so waiting for the autosave to
      // land would hand over a workbook missing the last few seconds of typing.
      clearTimeout(saveTimer);
      TW.setState({ info_cell_values: cellValues, info_tab_structs: structs });

      const res = await TW.postJSON("/api/info-sheet/generate", {
        draft_id: draftId, info_cell_values: cellValues, info_tab_structs: structs });
      if (res.job_number) TW.setState({ job_number: res.job_number });

      const file = await fetch(TW.absoluteUrl(res.xlsx_download_url), { headers: TW.authHeaders() });
      if (!file.ok) throw new Error("HTTP " + file.status);
      const blob = new Blob([await file.arrayBuffer()], { type: "application/octet-stream" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "$Project Info Sheet- " + (projLabel.textContent || "Project") + ".xlsx";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1500);
      dlBtn.textContent = "✓ Downloaded";
      setTimeout(() => { dlBtn.textContent = orig; dlBtn.disabled = false; }, 1800);
    } catch (err) {
      console.error("Info sheet download failed", err);
      dlBtn.textContent = "Failed — try again";
      setTimeout(() => { dlBtn.textContent = orig; dlBtn.disabled = false; }, 2400);
    }
  }

  /* ── boot ────────────────────────────────────────────────────────── */

  async function init() {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) {}
    try { await TW.draftReady; } catch (e) {}

    draftId = TW.getDraftId();
    if (!draftId) {
      host.innerHTML =
        '<div class="info-empty"><div class="info-empty-mark">📋</div>' +
        "<h2>Pick a project first</h2><p>The info sheet fills itself in from a " +
        "project's estimate, so it needs to know which job you mean.</p>" +
        '<a class="btn-primary" href="/projects.html">Choose a project →</a></div>';
      dlBtn.disabled = true;
      return;
    }

    const state = TW.getState() || {};
    cellValues = Object.assign({}, state.info_cell_values || {});
    structs = Array.isArray(state.info_tab_structs) ? state.info_tab_structs.slice() : [];
    projLabel.textContent = state.project_name || "";

    let payload;
    try {
      const res = await fetch(TW.resolveApiBase() + "/api/info-sheet/" + encodeURIComponent(draftId),
                              { headers: TW.authHeaders() });
      if (!res.ok) throw new Error("HTTP " + res.status);
      payload = await res.json();
    } catch (err) {
      console.error("Info sheet load failed", err);
      host.innerHTML = '<div class="info-msg">Couldn\'t load the info sheet. Reload the page, ' +
        'or open it again from <a href="/projects.html">Projects</a>.</div>';
      dlBtn.disabled = true;
      return;
    }

    order = payload.order || [];
    grids = payload.sheets || {};
    textCells = new Set(payload.text_cells || []);

    // The local blob can be a fresh hydration that has not been through the
    // wizard, so fall back to the sheet's own project name rather than showing
    // an unlabelled workbook.
    if (!projLabel.textContent) {
      const b15 = (grids[SHEET_INFO] || { cells: [] }).cells.find((c) => c.addr === "B15");
      projLabel.textContent = (b15 && b15.value) || "";
    }

    // Structural edits are recorded against a particular template. If the
    // committed workbook has been rebuilt since, the offsets no longer describe
    // the same layout — keep the typed values, drop the shape.
    if (state.info_template_version && payload.template_version &&
        state.info_template_version !== payload.template_version && structs.length) {
      console.warn("[info-sheet] template changed; discarding saved row/column edits");
      structs = [];
    }
    TW.setState({ info_template_version: payload.template_version });

    // Every sheet has to be in the engine before any op runs: inserting a row
    // on Info Sheet rewrites Invoice's references to it, which it can only do
    // if the Invoice is loaded.
    engine = X.createEngine(order);
    for (const name of order) engine.loadSheet(name, grids[name].cells);

    // Replay the saved shape. No re-keying here — cellValues were already
    // stored in post-op coordinates when the user made the edit.
    for (const op of structs) {
      if (!engine.structOp(op.sheet, op.kind, op.at, op.count)) {
        console.warn("[info-sheet] could not replay", op, "— dropping the rest");
        structs = structs.slice(0, structs.indexOf(op));
        break;
      }
      X.transformGridForOp(grids[op.sheet], op);
    }

    for (const key in cellValues) {
      const i = key.indexOf("!");
      if (i < 0) continue;
      engine.setCellValue(key.slice(0, i), key.slice(i + 1), cellValues[key]);
    }

    renderTabs();
    let first = null;
    try { first = sessionStorage.getItem("tw_info_tab"); } catch (_) {}
    showSheet(order.indexOf(first) >= 0 ? first : order[0]);
    dlBtn.addEventListener("click", download);
  }

  init();
})();
