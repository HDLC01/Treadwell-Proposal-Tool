/* Project Info Sheet — the ops hand-off workbook, filled and editable.
 *
 * One tab, one grid. The server sends the sheet as it sits in Kyle's template
 * plus a `prefill` of everything the estimate already answers; the estimator
 * corrects what's wrong, picks the market segment and payment terms, and
 * downloads. Their edits live on the draft as `info_cell_values` keyed
 * "Info Sheet!B14", so the same corrections come back on a re-download and the
 * server can rebuild the file without the browser.
 *
 * HyperFormula runs the sheet's own formulas — Division off Primary Floor, the
 * KC payroll-tax rule, the accounting prompts in column C — so the page reacts
 * the way the workbook does instead of showing stale cached results.
 */
(function () {
  "use strict";

  const host      = document.getElementById("sheet-host");
  const projLabel = document.getElementById("proj-name");
  const saveLabel = document.getElementById("save-state");
  const dlBtn     = document.getElementById("dl-btn");
  const backLink  = document.getElementById("back-link");

  const SHEET = "Info Sheet";
  const key   = (addr) => SHEET + "!" + addr;

  let grid = null;          // the template payload from the server
  let prefill = {};         // addr → value the estimate answered
  let overrides = {};       // "Info Sheet!B14" → what the estimator typed
  let textCells = new Set();// cells that must stay strings (see parseTyped)
  let hf = null;
  let hfSheet = 0;
  const derivedEls = new Map();   // addr → the element showing a formula's result

  function colLetter(n) {
    let s = "";
    while (n > 0) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = (n - r - 1) / 26; }
    return s;
  }

  function fail(html) {
    host.innerHTML = '<div class="info-msg">' + html + "</div>";
  }

  /* ── values ──────────────────────────────────────────────────────── */

  // What a cell holds before HyperFormula gets involved: the estimator's edit
  // wins, then the prefill, then whatever the template ships with.
  function effective(cell) {
    const k = key(cell.addr);
    if (Object.prototype.hasOwnProperty.call(overrides, k)) return overrides[k];
    if (Object.prototype.hasOwnProperty.call(prefill, cell.addr)) return prefill[cell.addr];
    return cell.value == null ? "" : cell.value;
  }

  // Mirrors the template's own baseline so we can drop an override that has
  // been typed back to what it already was, instead of pinning it forever.
  function baseline(cell) {
    if (Object.prototype.hasOwnProperty.call(prefill, cell.addr)) return prefill[cell.addr];
    return cell.value == null ? "" : cell.value;
  }

  function fmtDisplay(v, fmt) {
    if (v == null || v === "") return "";
    if (typeof v !== "number") return String(v);
    const f = fmt || "";
    if (f.indexOf("$") >= 0) {
      return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    if (f.indexOf("0.00") >= 0) return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (f.indexOf("#,##0") >= 0) return v.toLocaleString("en-US");
    return String(v);
  }

  // Typing "82,496" or "$82,496" should store a number, the way the estimate
  // grid does — otherwise the contract amount lands in Excel as text and the
  // Invoice tab's arithmetic quietly stops working. The exceptions are the cells
  // the server flags as text: a job number is "26.100", and as a number that is
  // 26.1 — which is then what the Invoice and Foundation Import tabs print.
  function parseTyped(addr, raw) {
    const s = String(raw == null ? "" : raw).trim();
    if (s === "") return "";
    if (s[0] === "=") return s;
    if (textCells.has(addr)) return s;
    const bare = s.replace(/[$,\s]/g, "");
    const n = Number(bare);
    return (bare !== "" && Number.isFinite(n)) ? n : s;
  }

  /* ── HyperFormula ────────────────────────────────────────────────── */

  function buildEngine() {
    const rows = [];
    for (let r = 1; r <= grid.max_row; r++) {
      const row = [];
      for (let c = 1; c <= grid.max_col; c++) row.push(null);
      rows.push(row);
    }
    for (const cell of grid.cells) {
      if (cell.row > grid.max_row || cell.col > grid.max_col) continue;
      if (cell.isFormula) { rows[cell.row - 1][cell.col - 1] = cell.formula; continue; }
      // Empty has to reach the engine as null, not "". Excel ranks any text
      // above any number, so an empty-string B57 made `=IF(B57>149000,…)` say a
      // Risk Management Plan was REQUIRED on every job with no contract amount.
      const v = effective(cell);
      rows[cell.row - 1][cell.col - 1] = v === "" ? null : v;
    }
    hf = HyperFormula.buildFromSheets({ [SHEET]: rows }, { licenseKey: "gpl-v3" });
    hfSheet = hf.getSheetId(SHEET);
  }

  function hfValue(addr) {
    const m = /^([A-Z]+)(\d+)$/.exec(addr);
    if (!m || !hf) return null;
    let col = 0;
    for (const ch of m[1]) col = col * 26 + (ch.charCodeAt(0) - 64);
    const v = hf.getCellValue({ sheet: hfSheet, row: Number(m[2]) - 1, col: col - 1 });
    if (v && typeof v === "object") return null;          // #REF!/#VALUE! etc.
    return v;
  }

  function refreshDerived() {
    derivedEls.forEach((el, addr) => {
      const v = hfValue(addr);
      el.textContent = fmtDisplay(v, el.dataset.fmt);
    });
  }

  function pushToEngine(addr, value) {
    const m = /^([A-Z]+)(\d+)$/.exec(addr);
    if (!m || !hf) return;
    let col = 0;
    for (const ch of m[1]) col = col * 26 + (ch.charCodeAt(0) - 64);
    hf.setCellContents({ sheet: hfSheet, row: Number(m[2]) - 1, col: col - 1 },
                       [[value === "" ? null : value]]);
    refreshDerived();
  }

  /* ── persistence ─────────────────────────────────────────────────── */

  let saveTimer = null;
  function persist() {
    clearTimeout(saveTimer);
    saveLabel.textContent = "Saving…";
    saveTimer = setTimeout(() => {
      TW.setState({ info_cell_values: overrides });
      saveLabel.textContent = "Saved";
      setTimeout(() => { if (saveLabel.textContent === "Saved") saveLabel.textContent = ""; }, 2200);
    }, 400);
  }

  function record(cell, typed) {
    const k = key(cell.addr);
    const base = baseline(cell);
    if (typed === base || (typed === "" && (base == null || base === ""))) delete overrides[k];
    else overrides[k] = typed;
    persist();
    pushToEngine(cell.addr, typed);
  }

  /* ── rendering ───────────────────────────────────────────────────── */

  function styleCell(el, cell) {
    if (cell.fill)      el.style.background = cell.fill;
    if (cell.fontColor) el.style.color = cell.fontColor;
    if (cell.bold)   el.classList.add("bold");
    if (cell.italic) el.classList.add("italic");
    if (cell.fontSize) el.style.fontSize = Math.max(9, Math.round(cell.fontSize * 0.92)) + "px";
    if (cell.align === "center" || cell.align === "right") el.style.justifyContent =
      cell.align === "center" ? "center" : "flex-end";
    else if ((cell.fmt || "").indexOf("#,##0") >= 0 || (cell.fmt || "").indexOf("$") >= 0)
      el.classList.add("numeric");
    const b = cell.borders || {};
    for (const side of ["top", "right", "bottom", "left"]) {
      if (!b[side] || !b[side].style) continue;
      const weight = /thick|double|medium/.test(b[side].style) ? "2px" : "1px";
      el.style["border" + side[0].toUpperCase() + side.slice(1)] =
        weight + " solid " + (b[side].color || "#000");
    }
  }

  function makeShell(cls, row, col) {
    const el = document.createElement("div");
    el.className = "gridcell " + cls;
    el.style.gridRow = String(row);
    el.style.gridColumn = String(col);
    return el;
  }

  function render() {
    const byAddr = new Map(grid.cells.map((c) => [c.addr, c]));
    const anchors = new Map();
    const hidden = new Set();
    for (const m of grid.merged || []) {
      anchors.set(m.anchor, m);
      for (let r = m.minRow; r <= m.maxRow; r++) {
        for (let c = m.minCol; c <= m.maxCol; c++) {
          const a = colLetter(c) + r;
          if (a !== m.anchor) hidden.add(a);
        }
      }
    }

    const colPx = [];
    for (let c = 1; c <= grid.max_col; c++) {
      const w = grid.col_widths[colLetter(c)];
      colPx.push(Math.max(56, Math.round((w || 9) * 7.5)));
    }
    const rowPx = [];
    for (let r = 1; r <= grid.max_row; r++) {
      rowPx.push(Math.max(20, Math.round((grid.row_heights[r] || 15) * 1.33)));
    }

    const g = document.createElement("div");
    g.className = "xl-grid";
    g.style.gridTemplateColumns = "36px " + colPx.map((p) => p + "px").join(" ");
    g.style.gridTemplateRows = "20px " + rowPx.map((p) => p + "px").join(" ");

    g.appendChild(makeShell("corner", 1, 1));
    for (let c = 1; c <= grid.max_col; c++) {
      const h = makeShell("col-header", 1, c + 1);
      h.textContent = colLetter(c);
      g.appendChild(h);
    }
    for (let r = 1; r <= grid.max_row; r++) {
      const h = makeShell("row-header", r + 1, 1);
      h.textContent = String(r);
      g.appendChild(h);
    }

    const editable = new Set(grid.editable || []);
    derivedEls.clear();

    for (let r = 1; r <= grid.max_row; r++) {
      for (let c = 1; c <= grid.max_col; c++) {
        const addr = colLetter(c) + r;
        if (hidden.has(addr)) continue;
        const cell = byAddr.get(addr) || { addr: addr, row: r, col: c, value: null };
        const el = makeShell("", r + 1, c + 1);
        styleCell(el, cell);

        const span = anchors.get(addr);
        if (span) {
          el.style.gridRow = (r + 1) + " / span " + span.rowSpan;
          el.style.gridColumn = (c + 1) + " / span " + span.colSpan;
        }

        if (cell.isFormula || cell.readOnly) {
          // Derived: show the live result, offer nothing to type into.
          el.classList.add("derived");
          el.dataset.fmt = cell.fmt || "";
          derivedEls.set(addr, el);
        } else if (editable.has(addr)) {
          const options = grid.dropdowns[addr];
          if (Object.prototype.hasOwnProperty.call(prefill, addr) &&
              prefill[addr] !== "" && !(key(addr) in overrides)) {
            el.classList.add("prefilled");
          }
          if (options) {
            el.classList.add("haslist");
            const sel = document.createElement("select");
            const cur = String(effective(cell) == null ? "" : effective(cell));
            const blank = document.createElement("option");
            blank.value = ""; blank.textContent = "";
            sel.appendChild(blank);
            let matched = false;
            for (const opt of options) {
              const o = document.createElement("option");
              o.value = opt; o.textContent = opt;
              if (opt === cur) { o.selected = true; matched = true; }
              sel.appendChild(o);
            }
            // A value the list no longer offers still has to be visible —
            // silently blanking someone's entry is worse than an odd option.
            if (!matched && cur !== "") {
              const o = document.createElement("option");
              o.value = cur; o.textContent = cur; o.selected = true;
              sel.appendChild(o);
            }
            sel.addEventListener("change", () => {
              el.classList.remove("prefilled");
              record(cell, sel.value);
            });
            el.appendChild(sel);
          } else {
            const inp = document.createElement("input");
            inp.type = "text";
            inp.value = fmtDisplay(effective(cell), cell.fmt);
            inp.addEventListener("focus", () => {
              const raw = effective(cell);
              inp.value = raw == null ? "" : String(raw);
            });
            inp.addEventListener("blur", () => {
              const typed = parseTyped(addr, inp.value);
              el.classList.remove("prefilled");
              record(cell, typed);
              inp.value = fmtDisplay(typed, cell.fmt);
            });
            inp.addEventListener("keydown", (e) => { if (e.key === "Enter") inp.blur(); });
            el.appendChild(inp);
          }
        } else {
          // A label or a spacer — rendered, not editable.
          const v = effective(cell);
          el.textContent = fmtDisplay(v, cell.fmt);
        }
        g.appendChild(el);
      }
    }

    host.innerHTML = "";
    host.appendChild(g);
    refreshDerived();
  }

  /* ── download ────────────────────────────────────────────────────── */

  async function download(draftId, projectName) {
    const orig = dlBtn.textContent;
    dlBtn.disabled = true;
    dlBtn.textContent = "Building…";
    try {
      // Flush the debounce first: the server rebuilds from the saved draft, so
      // an edit still sitting in the timer would be missing from the file.
      clearTimeout(saveTimer);
      TW.setState({ info_cell_values: overrides });
      await new Promise((r) => setTimeout(r, 250));

      const res = await TW.postJSON("/api/info-sheet/generate", { draft_id: draftId });
      const file = await fetch(TW.absoluteUrl(res.xlsx_download_url), { headers: TW.authHeaders() });
      if (!file.ok) throw new Error("HTTP " + file.status);
      const blob = new Blob([await file.arrayBuffer()], { type: "application/octet-stream" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "$Project Info Sheet- " + (projectName || "Project") + ".xlsx";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
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
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) { /* login redirects */ }
    try { await TW.draftReady; } catch (e) { /* hydration reloads the page */ }

    const draftId = TW.getDraftId();
    if (!draftId) {
      fail('No project selected. Open one from <a href="/projects.html">Projects</a>.');
      dlBtn.disabled = true;
      return;
    }
    backLink.href = "/projects.html";

    const state = TW.getState() || {};
    overrides = Object.assign({}, state.info_cell_values || {});
    projLabel.textContent = state.project_name || "";

    let payload;
    try {
      const res = await fetch(TW.resolveApiBase() + "/api/info-sheet/" + encodeURIComponent(draftId),
                              { headers: TW.authHeaders() });
      if (!res.ok) throw new Error("HTTP " + res.status);
      payload = await res.json();
    } catch (err) {
      console.error("Info sheet load failed", err);
      fail("Couldn't load the info sheet. Reload the page, or open it again from " +
           '<a href="/projects.html">Projects</a>.');
      dlBtn.disabled = true;
      return;
    }

    grid = payload.grid;
    prefill = payload.prefill || {};
    textCells = new Set(grid.text_cells || []);
    if (!projLabel.textContent) projLabel.textContent = prefill.B15 || "";

    buildEngine();
    render();
    dlBtn.addEventListener("click", () => download(draftId, projLabel.textContent));
  }

  init();
})();
