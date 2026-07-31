/* xl-core — the workbook-agnostic half of the spreadsheet grid.
 *
 * Addressing, value formatting, borders, keyboard nav, column/row resizing,
 * clipboard, the context menu, the HyperFormula wrapper, and the structural
 * (insert/delete row/column) transforms. Nothing in here knows about epoxy,
 * bids, prefills or roles — page-specific behaviour lives in the page.
 *
 * ONE global, on purpose. `estimate-review.js` is a classic script with
 * top-level `const HF` and `function colLetter`, so a bare declaration in a
 * shared file would be a redeclaration SyntaxError that takes the estimate page
 * down with it. Everything hangs off `window.TWXL`, matching `TW`/`TWAuth`.
 *
 * Consumers: js/info-sheet.js. `estimate-review.js` still carries its own
 * copies of most of this; migrating it is a separate change, deliberately not
 * bundled with the page that proves the extraction.
 */
(function () {
  "use strict";

  /* ── addressing ─────────────────────────────────────────────────── */

  function colLetter(n) {                       // 1 → A, 27 → AA
    let s = "";
    while (n > 0) { n--; s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26); }
    return s;
  }

  function colToNum(letters) {                  // "AA" → 27
    let n = 0;
    for (const ch of String(letters)) n = n * 26 + (ch.charCodeAt(0) - 64);
    return n;
  }

  function parseAddr(addr) {                    // "F10" → {r:10, c:6}
    const m = /^([A-Z]+)(\d+)$/.exec(String(addr || "").toUpperCase());
    return m ? { r: parseInt(m[2], 10), c: colToNum(m[1]) } : null;
  }

  const addrOf = (r, c) => colLetter(c) + r;

  /** Where an index lands after one op. null = the op deleted it. */
  function shiftIdx(idx, at, count, insert) {
    if (insert) return idx >= at ? idx + count : idx;
    if (idx < at) return idx;
    if (idx < at + count) return null;
    return idx - count;
  }

  /** Replay a whole op list over one template address. null = deleted.
   *  Mirrors `_translate_addr` in backend/estimate_writer.py. */
  function txAddr(addr, ops) {
    const p = parseAddr(addr);
    if (!p) return null;
    let { r, c } = p;
    for (const op of ops || []) {
      const rows = op.kind.endsWith("_rows");
      const insert = op.kind.startsWith("insert");
      const moved = shiftIdx(rows ? r : c, op.at, op.count, insert);
      if (moved === null) return null;
      if (rows) r = moved; else c = moved;
    }
    return addrOf(r, c);
  }

  /* ── value formatting ───────────────────────────────────────────── */

  const isPctFmt = (fmt) => /%/.test(fmt || "");
  const isTextFmt = (fmt) => (fmt || "").trim() === "@";

  /** Render a number the way Excel's number format would.
   *
   *  `exactDecimals` counts the zeros in the format instead of using the
   *  legacy 1-or-2 heuristic. Off by default: the estimate template has 847
   *  cells whose percent formats ask for 2-4 decimals and have always shown 1,
   *  and changing that is not this module's business to decide.
   */
  function formatValue(v, fmt, opts) {
    if (v === null || v === undefined) return "";
    if (typeof v !== "number") return String(v);
    fmt = fmt || "";
    const exact = !!(opts && opts.exactDecimals);
    const decimalsFrom = (fallbackWhenDotted, fallback) => {
      if (!exact) return /0\.0/.test(fmt) ? fallbackWhenDotted : fallback;
      const m = /0\.(0+)/.exec(fmt);
      return m ? m[1].length : 0;
    };
    if (/%/.test(fmt)) {
      const d = decimalsFrom(1, 0);
      return (v * 100).toFixed(d) + "%";
    }
    if (/\$/.test(fmt)) {
      const d = exact ? decimalsFrom(2, 0) : (/0\.0{2}/.test(fmt) ? 2 : 0);
      return "$" + v.toLocaleString(undefined,
        { minimumFractionDigits: d, maximumFractionDigits: d });
    }
    if (/#,##0/.test(fmt)) {
      const d = decimalsFrom(2, 0);
      return v.toLocaleString(undefined,
        { minimumFractionDigits: d, maximumFractionDigits: d });
    }
    if (Math.floor(v) === v) return String(v);
    return String(Math.round(v * 10000) / 10000);
  }

  /** Normalize what the user typed for storage.
   *
   *  A number for numeric formats, a fraction for percents, the raw string for
   *  text cells and formulas. Storing the parsed value rather than the raw text
   *  is what stops "82,496" reaching the writer as a string and landing in a
   *  money cell as text.
   */
  function parseTyped(raw, fmt, isText) {
    const s = String(raw == null ? "" : raw).trim();
    if (s === "") return "";
    if (s[0] === "=") return s;                 // a typed formula, verbatim
    if (isText || isTextFmt(fmt)) return s;
    if (isPctFmt(fmt)) {
      const pct = Number(s.replace(/[%\s,]/g, ""));
      if (!Number.isFinite(pct)) return s;
      // "5" and "5%" both mean five percent; 0.05 is already the fraction.
      return (s.indexOf("%") >= 0 || Math.abs(pct) >= 1) ? pct / 100 : pct;
    }
    const bare = s.replace(/[$,\s]/g, "");
    const n = Number(bare);
    return (bare !== "" && Number.isFinite(n)) ? n : s;
  }

  const BORDER_STYLE = {
    hair: "1px solid", thin: "1px solid", medium: "2px solid", thick: "3px solid",
    double: "3px double", dotted: "1px dotted", dashed: "1px dashed",
    mediumDashed: "2px dashed", dashDot: "1px dashed", mediumDashDot: "2px dashed",
    dashDotDot: "1px dotted", mediumDashDotDot: "2px dotted", slantDashDot: "1px dashed",
  };

  function applyBorders(el, borders) {
    if (!borders) return;
    for (const side of ["top", "right", "bottom", "left"]) {
      const b = borders[side];
      if (!b || !b.style) continue;
      const css = BORDER_STYLE[b.style] || "1px solid";
      el.style["border" + side[0].toUpperCase() + side.slice(1)] =
        css + " " + (b.color || "#000");
    }
  }

  /* ── DOM ────────────────────────────────────────────────────────── */

  function makeCell(kind, text, pos) {
    const el = document.createElement("div");
    el.className = "gridcell " + kind;
    if (text !== undefined && text !== null && text !== "") el.textContent = text;
    if (pos) { el.style.gridRow = String(pos.row); el.style.gridColumn = String(pos.col); }
    return el;
  }

  /** Excel-style movement between cells. Returns a detach function.
   *
   *  Targets are found by `data-display-addr`, not by a sheet-qualified key, so
   *  this works on a sheet whose name contains quotes or brackets.
   */
  function attachKeyboardNav(grid, bounds) {
    const onKey = (e) => {
      const inp = e.target;
      if (!inp || !inp.dataset || !inp.dataset.displayAddr) return;
      const here = parseAddr(inp.dataset.displayAddr);
      if (!here) return;
      const isSelect = inp.tagName === "SELECT";
      let { r, c } = here;
      switch (e.key) {
        case "ArrowDown": r++; break;
        case "ArrowUp": r--; break;
        case "Enter": r++; break;
        case "Tab": c += e.shiftKey ? -1 : 1; break;
        case "ArrowRight":
          // Only leave the cell once the caret is already at the end, so
          // arrowing through text you are editing still works.
          if (!isSelect && inp.selectionStart !== inp.value.length) return;
          c++; break;
        case "ArrowLeft":
          if (!isSelect && inp.selectionStart !== 0) return;
          c--; break;
        default: return;
      }
      if (r < 1 || c < 1 || r > bounds.maxRow || c > bounds.maxCol) return;
      const next = grid.querySelector('[data-display-addr="' + addrOf(r, c) + '"]');
      if (!next) return;
      e.preventDefault();
      next.focus();
      if (next.select) try { next.select(); } catch (_) {}
    };
    grid.addEventListener("keydown", onKey);
    return () => grid.removeEventListener("keydown", onKey);
  }

  /** Draggable column/row edges. Returns a detach function.
   *
   *  The detach matters: the estimate page adds a document-level mousemove and
   *  mouseup per render and never removes them. A page that re-renders on every
   *  tab switch and every insert accumulates them fast.
   */
  function attachResizers(grid, colPx, rowPx, viewport, opts) {
    opts = opts || {};
    const gutter = opts.gutterW || 40;
    const header = opts.headerH || 22;
    let drag = null, ghost = null;

    const template = () => {
      grid.style.gridTemplateColumns = gutter + "px " + colPx.map((p) => p + "px").join(" ");
      grid.style.gridTemplateRows = header + "px " + rowPx.map((p) => p + "px").join(" ");
    };

    const onDown = (e) => {
      const h = e.target.closest && e.target.closest(".resize-h, .resize-v");
      if (!h) return;
      e.preventDefault(); e.stopPropagation();
      const horiz = h.classList.contains("resize-h");
      const idx = parseInt(horiz ? h.dataset.colIndex : h.dataset.rowIndex, 10) - 1;
      drag = { horiz, idx, start: horiz ? e.clientX : e.clientY,
               base: horiz ? colPx[idx] : rowPx[idx] };
      h.classList.add("dragging");
      ghost = document.createElement("div");
      ghost.style.cssText = "position:absolute;background:var(--treadwell-red);opacity:.5;z-index:9;"
        + (horiz ? "top:0;bottom:0;width:2px;" : "left:0;right:0;height:2px;");
      (viewport || grid.parentNode).appendChild(ghost);
      document.body.style.userSelect = "none";
    };

    const onMove = (e) => {
      if (!drag || !ghost) return;
      const delta = (drag.horiz ? e.clientX : e.clientY) - drag.start;
      const size = Math.max(drag.horiz ? 24 : 14, drag.base + delta);
      drag.size = size;
      const box = (viewport || grid.parentNode).getBoundingClientRect();
      if (drag.horiz) ghost.style.left = (e.clientX - box.left + (viewport ? viewport.scrollLeft : 0)) + "px";
      else ghost.style.top = (e.clientY - box.top + (viewport ? viewport.scrollTop : 0)) + "px";
    };

    const onUp = () => {
      if (!drag) return;
      if (drag.size != null) {
        if (drag.horiz) colPx[drag.idx] = drag.size; else rowPx[drag.idx] = drag.size;
        template();                              // one reflow, at the end
        if (opts.onCommit) opts.onCommit(colPx, rowPx);
      }
      if (ghost && ghost.parentNode) ghost.parentNode.removeChild(ghost);
      grid.querySelectorAll(".dragging").forEach((n) => n.classList.remove("dragging"));
      ghost = null; drag = null;
      document.body.style.userSelect = "";
    };

    grid.addEventListener("mousedown", onDown);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      grid.removeEventListener("mousedown", onDown);
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      if (ghost && ghost.parentNode) ghost.parentNode.removeChild(ghost);
    };
  }

  /* ── clipboard ──────────────────────────────────────────────────── */

  let _buffer = "";

  function clipboardWrite(text) {
    _buffer = text;
    try { if (navigator.clipboard) navigator.clipboard.writeText(text).catch(() => {}); } catch (_) {}
  }

  /** Read the system clipboard, falling back to our own buffer.
   *  `readText()` hangs indefinitely in some contexts rather than rejecting,
   *  so it races a short timer instead of being awaited outright. */
  function clipboardRead() {
    if (!navigator.clipboard || !navigator.clipboard.readText) return Promise.resolve(_buffer);
    return Promise.race([
      navigator.clipboard.readText().catch(() => _buffer),
      new Promise((res) => setTimeout(() => res(_buffer), 400)),
    ]).then((t) => (t == null || t === "" ? _buffer : t));
  }

  const sanitizeCellPaste = (t) =>
    String(t == null ? "" : t).replace(/\r\n?/g, "\n").replace(/ /g, "");

  function tsvParse(text) {
    return sanitizeCellPaste(text).replace(/\n$/, "").split("\n").map((r) => r.split("\t"));
  }

  const tsvJoin = (rows) => rows.map((r) => r.join("\t")).join("\n");

  /* ── context menu ───────────────────────────────────────────────── */

  let _menu = null;

  function closeCtxMenu() {
    if (_menu && _menu.parentNode) _menu.parentNode.removeChild(_menu);
    _menu = null;
  }

  /** items: [{label, fn, danger, disabled, hint} | null-for-separator] */
  function openCtxMenu(x, y, items) {
    closeCtxMenu();
    const m = document.createElement("div");
    m.className = "ctx-menu";
    for (const it of items) {
      if (!it) {
        const sep = document.createElement("div");
        sep.className = "ctx-sep";
        m.appendChild(sep);
        continue;
      }
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ctx-item" + (it.danger ? " danger" : "");
      b.textContent = it.label;
      if (it.hint) {
        const h = document.createElement("span");
        h.className = "ctx-hint";
        h.textContent = it.hint;
        b.appendChild(h);
      }
      if (it.disabled) b.disabled = true;
      else b.addEventListener("click", () => { closeCtxMenu(); it.fn(); });
      m.appendChild(b);
    }
    m.style.left = "0px"; m.style.top = "0px";
    document.body.appendChild(m);
    const box = m.getBoundingClientRect();
    m.style.left = Math.min(x, window.innerWidth - box.width - 8) + "px";
    m.style.top = Math.min(y, window.innerHeight - box.height - 8) + "px";
    _menu = m;
    return m;
  }

  document.addEventListener("mousedown", (e) => {
    if (_menu && !_menu.contains(e.target)) closeCtxMenu();
  }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeCtxMenu(); });

  /* ── HyperFormula ───────────────────────────────────────────────── */

  /** A formula engine over a set of named sheets.
   *
   *  A factory rather than a singleton so a page can hold more than one
   *  workbook, and so the estimate page's own instance is untouched.
   */
  function createEngine(sheetNames) {
    const api = {
      instance: null,
      sheetIdByName: {},
      domBySheetAddr: {},
      nameAliases: {},
      ready: false,

      addrToRC(addr) {
        const p = parseAddr(addr);
        return p ? { col: p.c - 1, row: p.r - 1 } : null;
      },

      rewriteNames(formula) {
        if (typeof formula !== "string" || formula.charAt(0) !== "=") return formula;
        let out = formula;
        for (const orig in api.nameAliases) {
          const esc = orig.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          out = out.replace(
            new RegExp("(?<![A-Za-z0-9_.])" + esc + "(?![A-Za-z0-9_.])", "g"),
            api.nameAliases[orig]);
        }
        return out;
      },

      loadSheet(sheetName, cells) {
        const id = api.sheetIdByName[sheetName];
        if (id === undefined || !api.instance) return;
        const maxRow = Math.max(0, ...cells.map((c) => c.row));
        const maxCol = Math.max(0, ...cells.map((c) => c.col));
        const data = [];
        for (let r = 0; r < maxRow; r++) data.push(new Array(maxCol).fill(null));
        for (const c of cells) {
          // Formula text wins so the engine computes rather than echoing a
          // cached value; empty must be null, because Excel ranks any text
          // above any number and "" > 149000 is true.
          const v = c.isFormula && c.formula != null
            ? api.rewriteNames(c.formula)
            : (c.value === "" || c.value === undefined ? null : c.value);
          data[c.row - 1][c.col - 1] = v;
        }
        try { api.instance.setSheetContent(id, data); }
        catch (e) { console.warn("HF setSheetContent failed for " + sheetName, e); }
      },

      getValue(sheetName, addr) {
        const id = api.sheetIdByName[sheetName];
        const rc = api.addrToRC(addr);
        if (id === undefined || !rc || !api.instance) return null;
        try { return api.instance.getCellValue({ sheet: id, col: rc.col, row: rc.row }); }
        catch (e) { return null; }
      },

      /** The formula text the engine currently holds, which is authoritative
       *  after a structural edit — the cached grid payload still carries the
       *  pre-shift text for every sheet except the one that was edited. */
      getFormula(sheetName, addr) {
        const id = api.sheetIdByName[sheetName];
        const rc = api.addrToRC(addr);
        if (id === undefined || !rc || !api.instance) return null;
        try { return api.instance.getCellFormula({ sheet: id, col: rc.col, row: rc.row }); }
        catch (e) { return null; }
      },

      setCellValue(sheetName, addr, value) {
        const id = api.sheetIdByName[sheetName];
        const rc = api.addrToRC(addr);
        if (id === undefined || !rc || !api.instance) return [];
        let v = value;
        if (typeof v === "string" && v.trim() !== "" && !isNaN(Number(v))) v = Number(v);
        if (v === "") v = null;
        let changes;
        try { changes = api.instance.setCellContents({ sheet: id, col: rc.col, row: rc.row }, v); }
        catch (e) { return []; }
        const out = [];
        for (const ch of changes || []) {
          if (!ch || !ch.address) continue;      // named-expression recalcs
          const sheet = Object.keys(api.sheetIdByName)
            .find((n) => api.sheetIdByName[n] === ch.address.sheet);
          out.push({ sheet, addr: addrOf(ch.address.row + 1, ch.address.col + 1),
                     value: ch.newValue });
        }
        return out;
      },

      /** Insert/delete rows or columns. Returns false if the engine refused,
       *  so the caller can abort before recording anything — page state must
       *  never describe a shape the engine does not have. */
      structOp(sheetName, kind, at, count) {
        const id = api.sheetIdByName[sheetName];
        if (id === undefined || !api.instance) return false;
        try {
          const span = [at - 1, count];
          if (kind === "insert_rows") api.instance.addRows(id, span);
          else if (kind === "delete_rows") api.instance.removeRows(id, span);
          else if (kind === "insert_cols") api.instance.addColumns(id, span);
          else if (kind === "delete_cols") api.instance.removeColumns(id, span);
          else return false;
        } catch (e) { console.warn("HF struct op failed", kind, e); return false; }
        return true;
      },

      registerDom(sheetName, addr, el) { api.domBySheetAddr[sheetName + "!" + addr] = el; },
      unregisterAll() { api.domBySheetAddr = {}; },
      syncSheetIds() {
        if (!api.instance) return;
        api.sheetIdByName = {};
        for (const n of api.instance.getSheetNames()) {
          api.sheetIdByName[n] = api.instance.getSheetId(n);
        }
      },
    };

    const hf = HyperFormula.buildEmpty({
      licenseKey: "gpl-v3", smartRounding: true, precisionRounding: 4,
    });
    for (const name of sheetNames) {
      hf.addSheet(name);
      api.sheetIdByName[name] = hf.getSheetId(name);
    }
    api.instance = hf;
    api.ready = true;
    return api;
  }

  /* ── structural transforms over a cached grid payload ───────────── */

  /** Shift a grid payload in place for one op: cells, merges, sizes, dropdowns.
   *  Keeps the client's cached copy in step with the engine without refetching.
   *  Cell `role` rides along because it lives on the cell object. */
  function transformGridForOp(grid, op) {
    if (!grid) return;
    const rows = op.kind.endsWith("_rows");
    const insert = op.kind.startsWith("insert");
    const mv = (i) => shiftIdx(i, op.at, op.count, insert);

    grid.cells = grid.cells.filter((c) => {
      const moved = mv(rows ? c.row : c.col);
      if (moved === null) return false;
      if (rows) c.row = moved; else c.col = moved;
      c.addr = addrOf(c.row, c.col);
      return true;
    });

    grid.merged = (grid.merged || []).filter((m) => {
      const lo = mv(rows ? m.minRow : m.minCol);
      const hi = mv(rows ? m.maxRow : m.maxCol);
      if (lo === null && hi === null) return false;
      const a = lo === null ? op.at : lo;
      const b = hi === null ? op.at - 1 : hi;
      if (a > b) return false;
      if (rows) { m.minRow = a; m.maxRow = b; } else { m.minCol = a; m.maxCol = b; }
      m.rowSpan = m.maxRow - m.minRow + 1;
      m.colSpan = m.maxCol - m.minCol + 1;
      m.anchor = addrOf(m.minRow, m.minCol);
      m.range = m.anchor + ":" + addrOf(m.maxRow, m.maxCol);
      return true;
    });

    if (rows) {
      const h = {};
      for (const k in grid.row_heights || {}) {
        const moved = mv(parseInt(k, 10));
        if (moved !== null) h[moved] = grid.row_heights[k];
      }
      grid.row_heights = h;
      grid.max_row = Math.max(1, insert ? grid.max_row + op.count : grid.max_row - op.count);
    } else {
      const w = {};
      for (const k in grid.col_widths || {}) {
        const moved = mv(colToNum(k));
        if (moved !== null) w[colLetter(moved)] = grid.col_widths[k];
      }
      grid.col_widths = w;
      grid.max_col = Math.max(1, insert ? grid.max_col + op.count : grid.max_col - op.count);
    }

    const d = {};
    for (const addr in grid.dropdowns || {}) {
      const moved = txAddr(addr, [op]);
      if (moved) d[moved] = grid.dropdowns[addr];
    }
    grid.dropdowns = d;
  }

  /** Re-key a `"Sheet!Addr"`-keyed map for one op on one sheet.
   *  Two phases so a shift can never clobber a key it is about to move. */
  function rekeyKeyedMapForOp(map, sheetName, op) {
    const prefix = sheetName + "!";
    const moves = [];
    for (const key in map) {
      if (key.indexOf(prefix) !== 0) continue;
      moves.push([key, txAddr(key.slice(prefix.length), [op])]);
    }
    const staged = [];
    for (const [key, moved] of moves) {
      const v = map[key];
      delete map[key];
      if (moved) staged.push([prefix + moved, v]);
    }
    for (const [key, v] of staged) map[key] = v;
  }

  window.TWXL = {
    colLetter, colToNum, parseAddr, addrOf, shiftIdx, txAddr,
    isPctFmt, isTextFmt, formatValue, parseTyped, applyBorders,
    makeCell, attachKeyboardNav, attachResizers,
    clipboardWrite, clipboardRead, tsvParse, tsvJoin, sanitizeCellPaste,
    openCtxMenu, closeCtxMenu,
    createEngine, transformGridForOp, rekeyKeyedMapForOp,
  };
})();
