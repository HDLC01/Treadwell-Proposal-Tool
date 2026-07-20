// Externalized from estimate-review.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
// ─── HyperFormula engine ─────────────────────────────────────────────
// One global engine instance holds all 16 sheets. As the user edits
// a cell, HF recomputes downstream formulas and we update the DOM for
// every affected cell on the currently-visible sheet.
const HF = {
  instance: null,
  sheetIdByName: {},       // "Epoxy" -> 0, "Polish" -> 1, ...
  domBySheetAddr: {},      // "Epoxy!B4" -> input element
  nameAliases: {},         // HF-invalid name -> valid alias, e.g. "Glaze4" -> "Glaze_4"
  ready: false,

  init(sheetNames) {
    const hf = HyperFormula.buildEmpty({
      licenseKey: "gpl-v3",  // free for GPL-compatible use
      smartRounding: true,
      precisionRounding: 4,
    });
    for (const name of sheetNames) {
      hf.addSheet(name);
      this.sheetIdByName[name] = hf.getSheetId(name);
    }
    this.instance = hf;
    this.ready = true;
  },

  /** Load all cells from one sheet's API payload into the engine. */
  loadSheet(sheetName, cells) {
    if (!this.instance) return;
    const sheetId = this.sheetIdByName[sheetName];
    if (sheetId === undefined) return;
    // Build a sparse array of values keyed by row/col then setSheetContent
    const maxRow = Math.max(...cells.map(c => c.row), 0);
    const maxCol = Math.max(...cells.map(c => c.col), 0);
    const data = [];
    for (let r = 0; r < maxRow; r++) {
      data.push(new Array(maxCol).fill(null));
    }
    for (const c of cells) {
      // Use the FORMULA TEXT when present (so HF computes it).
      // Otherwise the raw value. Rewrite any HF-invalid named-range tokens
      // (e.g. "Glaze4" -> "Glaze_4") so the formula resolves instead of #NAME?.
      const cellInput = c.formula != null ? this.rewriteNames(c.formula) : c.value;
      data[c.row - 1][c.col - 1] = cellInput;
    }
    try {
      // HF 2.7+ wants a raw sheetId number, NOT an object wrapper.
      this.instance.setSheetContent(sheetId, data);
    } catch (e) {
      console.warn(`HF setSheetContent failed for ${sheetName}:`, e);
    }
  },

  /** Replace HF-invalid named-range tokens in a formula with their valid
   *  aliases (whole-token only — never inside a longer identifier). */
  rewriteNames(formula) {
    if (typeof formula !== "string" || formula.charAt(0) !== "=") return formula;
    let out = formula;
    for (const orig in this.nameAliases) {
      const esc = orig.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      out = out.replace(new RegExp("(?<![A-Za-z0-9_.])" + esc + "(?![A-Za-z0-9_.])", "g"),
                        this.nameAliases[orig]);
    }
    return out;
  },

  /** Get the current computed value for a cell. */
  getValue(sheetName, addr) {
    if (!this.instance) return null;
    try {
      const sheetId = this.sheetIdByName[sheetName];
      if (sheetId === undefined) return null;
      const [colLetter, rowStr] = (addr.match(/^([A-Z]+)(\d+)$/) || []).slice(1);
      if (!colLetter || !rowStr) return null;
      const col = colLetter.split("").reduce((a, ch) => a * 26 + (ch.charCodeAt(0) - 64), 0) - 1;
      const row = parseInt(rowStr, 10) - 1;
      // SimpleCellAddress: { sheet, col, row } — note: 'sheet' is the property name
      const v = this.instance.getCellValue({ sheet: sheetId, col, row });
      return v;
    } catch (e) {
      return null;
    }
  },

  /** User typed something — push it into HF and return the affected cells. */
  setCellValue(sheetName, addr, value) {
    if (!this.instance) return [];
    const sheetId = this.sheetIdByName[sheetName];
    if (sheetId === undefined) return [];
    const [colLetter, rowStr] = (addr.match(/^([A-Z]+)(\d+)$/) || []).slice(1);
    if (!colLetter || !rowStr) return [];
    const col = colLetter.split("").reduce((a, ch) => a * 26 + (ch.charCodeAt(0) - 64), 0) - 1;
    const row = parseInt(rowStr, 10) - 1;
    // Coerce numeric strings to numbers so HF treats them as numbers
    let coerced = value;
    if (typeof value === "string" && value.trim() !== "" && !isNaN(Number(value))) {
      coerced = Number(value);
    }
    const changes = this.instance.setCellContents({ sheet: sheetId, col, row }, coerced);
    // Map HF "changes" back to {sheet, addr} pairs
    const affected = [];
    for (const ch of changes) {
      // Named-expression recalcs come back as changes with no `.address`
      // (they carry `.name` instead) — skip them so we don't deref undefined.
      if (!ch || !ch.address) continue;
      const sheet = Object.keys(this.sheetIdByName).find(
        n => this.sheetIdByName[n] === ch.address.sheet
      );
      const colLet = (() => {
        let n = ch.address.col + 1, s = "";
        while (n > 0) { n--; s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26); }
        return s;
      })();
      affected.push({
        sheet,
        addr: `${colLet}${ch.address.row + 1}`,
        value: ch.newValue,
      });
    }
    return affected;
  },

  /** Register an input element so we can find it later when its value changes. */
  registerDom(sheetName, addr, inputEl) {
    this.domBySheetAddr[`${sheetName}!${addr}`] = inputEl;
  },

  unregisterAll() {
    this.domBySheetAddr = {};
  },

  /** Rebuild sheetIdByName from the engine (after add/rename/remove). */
  syncSheetIds() {
    if (!this.instance) return;
    this.sheetIdByName = {};
    for (const n of this.instance.getSheetNames()) {
      this.sheetIdByName[n] = this.instance.getSheetId(n);
    }
  },

  /** Add a new (empty) sheet. Returns false if the name is taken. */
  createSheet(name) {
    if (!this.instance || this.sheetIdByName[name] !== undefined) return false;
    try { this.instance.addSheet(name); } catch (e) { return false; }
    this.syncSheetIds();
    return true;
  },

  /** Rename a sheet; cross-sheet refs (=Epoxy!…) resolve via the registry so
   *  no formula text needs rewriting. Returns false on failure/collision. */
  renameSheet(oldName, newName) {
    if (!this.instance || this.sheetIdByName[oldName] === undefined) return false;
    try { this.instance.renameSheet(this.sheetIdByName[oldName], newName); }
    catch (e) { return false; }
    this.syncSheetIds();
    return true;
  },

  /** Remove a sheet (room tab delete). */
  removeSheet(name) {
    if (!this.instance || this.sheetIdByName[name] === undefined) return;
    try { this.instance.removeSheet(this.sheetIdByName[name]); } catch (e) {}
    this.syncSheetIds();
  },
};

const state = TW.getState();
if (!state.project_name) {
  document.querySelector("main").innerHTML = `
    <div style="padding:60px;text-align:center;">
      <h1 style="color: var(--ink-variant);">No project started</h1>
      <p>Start an intake first to enable the Estimate step.</p>
      <a href="/?edit=1" class="btn-primary" style="text-decoration:none;padding:12px 20px;">← Go to Intake</a>
    </div>
  `;
  throw new Error("estimate-review: no project in state");
}

// ─── Project Info canonicalization ──────────────────────────────────
// In the source xlsx, the Polish/Gyp/Seal/etc sheets reference Epoxy's
// project-info block via formulas (=Epoxy!B1, =Epoxy!B2, ...).
// In our editable UI we mirror that: rows 1-10, columns A-D are the
// "Project Info" zone and ALWAYS write to Epoxy!{addr} no matter which
// tab the user is currently on. Other tabs render the same value live.
const CANONICAL_SHEET = "Epoxy";
// The 5 gyp underlayment variants (identical layout). Their project-info block
// lives on the GYP base sheet (offset +1 row vs Epoxy, NOT =Epoxy! mirrors), so
// project-info edits on any gyp tab must canonicalize to the gyp base — NOT Epoxy.
const GYP_BASE = 'Gyp (USG 1-8")';
const GYP_SHEETS = [GYP_BASE, 'Gyp (USG N12ULTRA)', 'Gyp (USG N25 1-4")', 'Gyp (GWorx SC190)', 'Gyp (FR)'];
function isProjectInfoCell(addr) {
  const m = (addr || "").match(/^([A-D])(\d+)$/);
  if (!m) return false;
  const row = parseInt(m[2], 10);
  return row >= 1 && row <= 10;
}
// Which sheet a tab's shared project-info canonicalizes to. Gyp-layout tabs →
// the gyp base; everything else → Epoxy (unchanged for epoxy/polish/seal/etc.).
function canonicalSheetFor(sheet) {
  try { return /^Gyp/i.test(layoutIdFor(sheet)) ? GYP_BASE : CANONICAL_SHEET; }
  catch { return CANONICAL_SHEET; }
}
function canonicalKey(sheet, addr) {
  return isProjectInfoCell(addr)
    ? `${canonicalSheetFor(sheet)}!${addr}`
    : `${sheet}!${addr}`;
}

// Same canonicalization but returns the {sheet, addr} pair separately —
// HF needs both, not a single combined key.
function canonicalTarget(sheet, addr) {
  return isProjectInfoCell(addr)
    ? { sheet: canonicalSheetFor(sheet), addr }
    : { sheet, addr };
}

// In-memory store of cell edits keyed by "{Sheet}!{Address}"
const cellValues = Object.assign({}, state.cell_values || {});

// Auto-fill Screen 1 intake values into the matching estimate cells.
// Mapping derived from the EPOXY_CELL_MAP in the backend (project name
// added explicitly; the sheet keeps it in B1 next to the "Project" label).
const FORM_TO_CELL = {
  // Intake → Epoxy tab
  project_name:      "Epoxy!B1",
  bid_date:          "Epoxy!B2",
  address:           "Epoxy!B3",
  city_state:        "Epoxy!C3",   // sits next to the address
  approx_start_date: "Epoxy!B7",
  architect:         "Epoxy!B8",
  // Quantities from Screen 1 → matching estimate cells. Without these
  // the user sees zero material/cost-per-SF on first load until they
  // re-type the same numbers they already gave us.
  system_1_sf:       "Epoxy!E20",
  cove_1_lf:         "Epoxy!E34",
  polish_sf:         "Polish!E18",   // E18 = polish SF (F18="SF"); E19 is LF — the bid reads E18

  // System 2 (the sheet is fully wired for two systems — see analysis).
  system_2_sf:       "Epoxy!E24",
  cove_2_lf:         "Epoxy!E37",
  // Systems 3+ have no estimate cells yet (template must be extended by
  // Kyle first — see docs); their intake values are captured but not
  // written to the sheet until those cells exist.
  // Bidding Contacts block (header lives in Epoxy!G1; estimator
  // historically filled the rows beneath by hand). Flow the intake
  // contact info into the rows so Troy sees it on the estimate.
  contact_name:      "Epoxy!G2",
  contact_email:     "Epoxy!H2",
  contact_phone:     "Epoxy!I2",
};

// Gyp intake → estimate cells. Project info lives on the gyp BASE sheet at a
// +1-row offset vs Epoxy and is NOT an =Epoxy! mirror, so it maps to its own
// cells (parity: mirrors backend GYP_CELL_MAP / GYP_SF_MAP).
const GYP_FORM_TO_CELL = {
  project_name:      `${GYP_BASE}!B2`,
  bid_date:          `${GYP_BASE}!B3`,
  address:           `${GYP_BASE}!B4`,
  city_state:        `${GYP_BASE}!C4`,
  approx_start_date: `${GYP_BASE}!B9`,
  architect:         `${GYP_BASE}!B10`,
  contact_name:      `${GYP_BASE}!G2`,
  contact_email:     `${GYP_BASE}!H2`,
  contact_phone:     `${GYP_BASE}!I2`,
};
// The three SF buckets seed G9/I9/K9 on EVERY gyp variant so the estimator can
// compare variants / mark them as options without re-typing the takeoff.
const GYP_SF_CELLS = { gyp_soft_sf: "G9", gyp_hard_sf: "I9", gyp_corridor_sf: "K9" };

// SF / cove-LF INPUT cells per template LAYOUT (template coords — always read
// through txAddr so a copy tab with row edits still resolves). Snapshotted from
// the resolved BASE tab into state.sheet_area so the proposal's "Area" line
// follows the sheet (incl. a copy base) instead of only the intake fields.
// JS↔PY parity: backend/tests/test_area_sourcing.py greps this map. Gyp layouts
// reuse GYP_SF_CELLS (G9/I9/K9).
const AREA_SF_CELLS = {
  Epoxy:  { epoxy_sf: "E20", epoxy_sf_2: "E24", cove_lf: "E34", cove_lf_2: "E37" },
  Polish: { polish_sf: "E18" },
};

// Lookup-table automations layered on top of the raw intake → cell map.
// These never override the user's saved edits (we skip if cellValues
// already has the address). Each one cites the rule it's encoding.
function applyHeuristics(intake, putIfBlank) {
  // Gyp is mobilization-based and doesn't use the Epoxy crew/labor sheet — skip
  // the Epoxy!A47/B47/C47 heuristics entirely so a gyp job never seeds stale
  // crew/rate values onto the (reference-only) Epoxy tab.
  if ((intake.work_type || "epoxy").toLowerCase() === "gyp") return;
  const sf = Number(intake.system_1_sf || 0);
  // Crew + days heuristic — scale a baseline crew to floor SF.
  //   ≤ 5k SF  → 2 guys × 3 days
  //   ≤15k SF  → 3 guys × 5 days
  //   ≤30k SF  → 4 guys × 8 days
  //    >30k SF → 5 guys × 12 days
  if (sf > 0) {
    let crew = 2, days = 3;
    if (sf > 30000)      { crew = 5; days = 12; }
    else if (sf > 15000) { crew = 4; days = 8;  }
    else if (sf > 5000)  { crew = 3; days = 5;  }
    putIfBlank("Epoxy!A47", crew);
    putIfBlank("Epoxy!B47", days);
  }
  // Labor rate from Prevailing Wage flag (D5). Default $32.20 standard,
  // $48.00 PW. The flag itself gets set by the AI Autofill button.
  const pwRaw = (intake.cell_values || {})["Epoxy!D5"] || "";
  const pw = String(pwRaw).toLowerCase() === "yes";
  putIfBlank("Epoxy!C47", pw ? 48.00 : 32.20);
}

(function autofillFromIntake() {
  const seed = (addr, v) => {
    if (v !== undefined && v !== null && v !== "" && cellValues[addr] === undefined) cellValues[addr] = v;
  };
  for (const [field, addr] of Object.entries(FORM_TO_CELL)) seed(addr, state[field]);
  // Gyp jobs additionally seed the gyp base sheet's project info + the three SF
  // buckets across all five gyp variants (Epoxy/Polish seeds above are inert
  // reference data — the gyp base is the actual bid driver here).
  if ((state.work_type || "epoxy").toLowerCase() === "gyp") {
    for (const [field, addr] of Object.entries(GYP_FORM_TO_CELL)) seed(addr, state[field]);
    for (const sheet of GYP_SHEETS)
      for (const [field, cell] of Object.entries(GYP_SF_CELLS)) seed(`${sheet}!${cell}`, state[field]);
  }
  applyHeuristics(state, (addr, val) => {
    if (cellValues[addr] === undefined) cellValues[addr] = val;
  });
})();

// ─── System Name + Texture inline inputs (flow into proposal too) ──
const sysNameInput = document.getElementById("sys-name");
let texInput       = document.getElementById("tex-name");
if (state.system_name) sysNameInput.value = state.system_name;

// Texture: Epoxy/Combo pick from a fixed dropdown; Polish keeps free text (the
// field there describes sheen, e.g. "Standard sheen, salt & pepper").
const TEXTURE_OPTIONS = ["Smooth", "Orange Peel", "Light", "Medium", "Heavy"];
(function buildTextureControl() {
  const wt = (state.work_type || "epoxy").toLowerCase();
  // Gyp underlayment has no texture/sheen selection — hide the whole control
  // (its label wrapper) so the ribbon doesn't show an irrelevant field.
  if (wt === "gyp") {
    const wrap = texInput.closest("label") || texInput;
    if (wrap) wrap.style.display = "none";
    return;
  }
  if (wt === "polish") { if (state.texture) texInput.value = state.texture; return; }
  const cur = state.texture || "";
  const sel = document.createElement("select");
  sel.id = "tex-name"; sel.className = "tex";
  const opts = TEXTURE_OPTIONS.slice();
  if (cur && !opts.includes(cur)) opts.unshift(cur);   // don't lose an off-list value
  sel.innerHTML = '<option value="">—</option>' +
    opts.map(o => `<option value="${o.replace(/"/g, "&quot;")}">${o}</option>`).join("");
  sel.value = cur;
  texInput.replaceWith(sel);
  texInput = sel;
})();

// System Name auto-derives from the live System 1/2 picks (see refreshSystemName
// below). A non-empty manual edit sets `system_name_manual` (persisted in state,
// so the override survives reloads); clearing the field re-enables auto-derive.
let systemNameDirty = !!state.system_name_manual;
function pushSysTextureToState() {
  state.system_name = sysNameInput.value;
  state.texture     = texInput.value;
  TW.setState({ ...state, system_name: state.system_name, texture: state.texture,
                system_name_manual: state.system_name_manual });
}
sysNameInput.addEventListener("input", () => {
  const manual = sysNameInput.value.trim() !== "";
  systemNameDirty = manual; state.system_name_manual = manual;
  pushSysTextureToState();
  if (!manual) refreshSystemName();   // cleared → fall back to System 1/2 auto-name
});
texInput.addEventListener("input",  pushSysTextureToState);
texInput.addEventListener("change", pushSysTextureToState);

const tabBar    = document.getElementById("tab-bar");
const sheetGrid = document.getElementById("sheet-grid");
const badge     = document.getElementById("type-badge");

let sheets = [];
let activeSheet = null;
let sheetCache = {};  // name → fetched cell data

// ─── Worksheet tabs: rename + true copy ──────────────────────────────
// The user can RENAME any worksheet tab and DUPLICATE one ("copy with all of
// its contents"). To keep the many places that hardcode "Epoxy!"/"Polish!"
// (cell maps, intake autofill, totals, pricing engine, =Epoxy! formulas) safe,
// each tab has a STABLE internal id (the HF sheet name) and an editable DISPLAY
// label. Renaming changes only the label (nothing else moves); the downloaded
// .xlsx is retitled + its cross-sheet formulas rewritten at generate time.
//
//   • base tabs   → id = template name (Epoxy/Polish/Sealer/…), kind 'base'
//   • copied tabs → id = "Copy<N>" (stable), kind 'copy', cloned from a source
//
// Persisted in state.tab_labels {id→label}, state.tab_copies [{id,source,role}],
// state.tab_notes {id→[manual notes]}. Per-tab cell edits live in cellValues
// keyed "<id>!<addr>". A copied epoxy tab is one priced option in the proposal.
const MAX_COPIES = 12;
const BASE_ROLE = { Epoxy: "epoxy", Polish: "polish" };
GYP_SHEETS.forEach((s) => { BASE_ROLE[s] = "gyp"; });   // all 5 gyp variants are priced 'gyp'

// One-time migration of the old separate-"rooms" model → the tab model.
if (Array.isArray(state.rooms) && state.rooms.length && !Array.isArray(state.tab_copies)) {
  state.tab_copies = state.rooms.map(r => ({ id: String(r.name), source: r.source || "Epoxy", role: "epoxy" }));
  state.tab_labels = state.tab_labels || {};
  state.tab_notes  = state.tab_notes  || {};
  for (const r of state.rooms)
    if (Array.isArray(r.notes_manual) && r.notes_manual.length) state.tab_notes[String(r.name)] = r.notes_manual;
}
state.tab_copies = Array.isArray(state.tab_copies) ? state.tab_copies : [];
state.tab_labels = (state.tab_labels && typeof state.tab_labels === "object") ? state.tab_labels : {};
state.tab_notes  = (state.tab_notes  && typeof state.tab_notes  === "object") ? state.tab_notes  : {};
state.tab_order  = Array.isArray(state.tab_order) ? state.tab_order : [];   // drag-to-reorder
state.tab_opts   = (state.tab_opts && typeof state.tab_opts === "object") ? state.tab_opts : {};
state.base_tab_id = (typeof state.base_tab_id === "string") ? state.base_tab_id : null;
// Structural edits (insert/delete rows & columns), in the order made:
// [{sheet, kind: insert_rows|delete_rows|insert_cols|delete_cols, at, count}].
// The backend replays these onto the .xlsx; here they drive HF, the cached
// sheet data, and the coordinate translation below.
state.tab_structs = Array.isArray(state.tab_structs) ? state.tab_structs : [];
// Per-sheet cell-lock overrides from the "Lock cell" toolbar button:
// { sheetId: { lock: [addr...], unlock: [addr...] } }, addresses in CURRENT
// grid coordinates. Merged over the preset locks by lockedCellsFor / the
// backend. Rekeyed on structural edits like cellValues.
state.lock_overrides = (state.lock_overrides && typeof state.lock_overrides === "object" &&
                        !Array.isArray(state.lock_overrides)) ? state.lock_overrides : {};

// ─── Structural-edit coordinate translation ──────────────────────────
// Hardcoded TEMPLATE coordinates (lock cells, totals cells, derive reads)
// must follow the user's inserts/deletes. Mirrors _translate_addr in
// backend/estimate_writer.py exactly.
function structOpsFor(sheetId) { return state.tab_structs.filter(o => o.sheet === sheetId); }
function _shiftIdx(idx, at, count, insert) {
  if (insert) return idx >= at ? idx + count : idx;
  if (idx >= at && idx < at + count) return null;          // deleted
  return idx >= at + count ? idx - count : idx;
}
// Template-coordinate addr -> CURRENT addr for `sheetId` (null if deleted).
function txAddr(sheetId, addr) {
  const ops = structOpsFor(sheetId);
  if (!ops.length) return addr;
  const m = /^([A-Z]{1,3})([0-9]{1,7})$/i.exec(addr);
  if (!m) return addr;
  let col = m[1].toUpperCase().split("").reduce((a, ch) => a * 26 + (ch.charCodeAt(0) - 64), 0);
  let row = parseInt(m[2], 10);
  for (const op of ops) {
    const rows = op.kind.endsWith("_rows"), insert = op.kind.startsWith("insert");
    if (rows) row = _shiftIdx(row, op.at, op.count, insert);
    else col = _shiftIdx(col, op.at, op.count, insert);
    if (row === null || col === null) return null;
  }
  let s = "";
  while (col > 0) { col--; s = String.fromCharCode(65 + (col % 26)) + s; col = Math.floor(col / 26); }
  return s + row;
}
// HF read at a template coordinate, translated (0 / "" when the cell is gone).
const hfNumTx = (id, addr) => { const t = txAddr(id, addr); return t ? hfNum(id, t) : 0; };

const labelFor = (id) => state.tab_labels[id] || id;
function roleFor(id) {
  if (BASE_ROLE[id]) return BASE_ROLE[id];
  const c = state.tab_copies.find(x => x.id === id);
  return c ? (c.role || "epoxy") : "other";
}
// A tab's underlying TEMPLATE layout sheet: walk copy-source chains (a copy of a
// copy resolves to the original template tab). Mirrors lockedCellsFor's walk —
// used to guard coordinate reads that only make sense on Epoxy/Polish layouts.
function layoutIdFor(id) {
  let cur = id, guard = 0;
  while (guard++ < 20) {
    const c = state.tab_copies.find(x => x.id === cur);
    if (!c) break;
    cur = c.source || "Epoxy";
  }
  return cur;
}

// ─── Base bid + priced options ───────────────────────────────────────
// One tab is the Base bid (state.base_tab_id); the estimator marks OTHER
// priced tabs as proposal options, each shown/hidden and priced as a
// "total" (its own price) or a "deduct" (savings vs. the base). These
// controls live in #bid-bar here AND mirror onto the Proposal Review
// sidebar — both edit state.base_tab_id + state.tab_opts[id].
const PRICED_ROLES = new Set(["epoxy", "polish", "gyp"]);
const isPricedRole = (r) => PRICED_ROLES.has(r);
// role-aware total cells (fixes reading a polish tab at D88 instead of D82).
// TEMPLATE coordinates translated through the sheet's structural edits, so a
// tab with inserted/deleted rows still reads ITS actual totals. A deleted
// totals cell keeps the template addr (deletion of totals rows is blocked in
// the UI; direct API abuse just reads a stale cell, never a wrong-money one).
function totalCellsFor(id) {
  const role = roleFor(id);
  const base = role === "polish" ? TOTAL_CELLS.Polish
             : role === "gyp"    ? TOTAL_CELLS.Gyp
             : TOTAL_CELLS.Epoxy;
  if (!structOpsFor(id).length) return base;
  const out = {};
  for (const k in base) out[k] = txAddr(id, base[k]) || base[k];
  return out;
}
function pricedTabs() { return tabs.filter(t => isPricedRole(t.role)); }
const hfNum = (id, addr) => { const v = HF.getValue(id, addr); return typeof v === "number" ? v : 0; };

// ─── Sheet-sourced Area (SF / cove LF) for the proposal ─────────────
// Read a tab's SF / cove-LF input cells (by role/layout, through txAddr so a
// copy tab with row edits still resolves) into a plain {field: number}. Feeds
// state.sheet_area so the proposal's "Area" line follows the resolved BASE
// tab's sheet cells (incl. a copy base) instead of only the intake fields.
function sfFieldsFor(id) {
  const role = roleFor(id);
  const map = role === "gyp"    ? GYP_SF_CELLS
            : role === "polish" ? AREA_SF_CELLS.Polish
            :                     AREA_SF_CELLS.Epoxy;
  const out = {};
  for (const f in map) out[f] = hfNumTx(id, map[f]);
  return out;
}
// The two epoxy system-name picks (A22/A26) for a tab, as raw strings — the
// caller filters "Options" placeholders (matching renderSystemPreview).
function sysNamesFor(id) {
  return ["A22", "A26"].map(a0 => {
    const a = txAddr(id, a0);
    const v = a ? HF.getValue(id, a) : "";
    return typeof v === "string" ? v : "";
  });
}
// Aggregate the Area buckets from the BASE tab(s) ONLY — options never
// contribute (per Hanz: "SF options should not be present in the proposal").
// combo default base = the epoxy + polish base-kind tabs. Stale snapshots
// (no .sf) contribute nothing. MIRRORS proposal-review.js:baseAreaFrom.
function baseAreaFrom(tabsSnap, baseIds) {
  const acc = {};
  const ids = new Set((baseIds || []).filter(Boolean));
  for (const t of tabsSnap || []) {
    if (!ids.has(t.id) || !t.sf) continue;
    for (const k in t.sf) acc[k] = (acc[k] || 0) + (Number(t.sf[k]) || 0);
  }
  return acc;
}
// The template sheet to open / fall back to for the current work type:
// gyp → the gyp base, polish → Polish, else Epoxy.
function defaultBaseSheet() {
  const wt = (state.work_type || "epoxy").toLowerCase();
  return wt === "gyp" ? GYP_BASE : wt === "polish" ? "Polish" : "Epoxy";
}
function resolveBaseTab() {
  const byId = tabs.find(t => t.id === state.base_tab_id && isPricedRole(t.role));
  if (byId) return byId;
  const wt = (state.work_type || "epoxy").toLowerCase();
  if (wt === "gyp") {
    const g = tabs.filter(t => t.role === "gyp");             // gyp base = the USG 1-8" tab
    return g.find(t => t.id === GYP_BASE) || g.find(t => t.kind === "base") || g[0] || pricedTabs()[0] || null;
  }
  if (wt === "polish") {                                      // polish-only base = the Polish tab
    const po = tabs.filter(t => t.role === "polish");
    return po.find(t => t.kind === "base") || po[0] || pricedTabs()[0] || null;
  }
  const ep = tabs.filter(t => t.role === "epoxy");           // epoxy / combo fallback derivation
  return ep.find(t => t.kind === "base") || ep[0] || pricedTabs()[0] || null;
}
function ensureOpt(id) {
  if (!state.tab_opts[id]) state.tab_opts[id] =
    { show_system: true, show_diff: false, is_option: false, show: true, price_mode: "total" };
  return state.tab_opts[id];
}
function persistBidOptions() {
  TW.setState({ ...state, base_tab_id: state.base_tab_id, tab_opts: state.tab_opts });
}
const _escBB = (s) => String(s).replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const _moneyBB = (n) => "$" + Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });

// Render the per-sheet Base-bid toggles + option chips into #bid-bar. Every priced
// tab is a chip with a "Base bid" radio; non-base chips carry the option (show +
// total/deduct) controls. Plus an Auto/combined chip.
function renderBidOptions() {
  const list = document.getElementById("bid-options-list");
  if (!list) return;
  const wt = (state.work_type || "epoxy").toLowerCase();
  const priced = pricedTabs();
  // Guard a stale explicit base from an old draft; never overwrite base_tab_id with
  // the auto-derived default (null base = auto; for combo that's Epoxy + Polish).
  if (state.base_tab_id && !priced.some(t => t.id === state.base_tab_id)) state.base_tab_id = null;
  const baseId = state.base_tab_id;
  const autoBase = resolveBaseTab();
  // gyp is a priced role too, so all 5 gyp variants live in `priced` on EVERY
  // job. By default show only the job's own work-type chips (gyp → gyp variants;
  // else → epoxy/polish) plus anything engaged. Cross-type systems stay hidden
  // UNTIL the estimator clicks "+ Add another system" (state.reveal_systems) —
  // this supports the real, if uncommon, multi-system bid (e.g. a big gyp job
  // with a small epoxy scope). Engaged tabs always show, so a revealed option
  // survives a collapse. NOTE: don't treat "non-zero total" as engaged — every
  // sheet carries fixed overhead at 0 SF, so that would never hide anything. The
  // stale-base guard above still runs on the unfiltered `priced` list.
  const chipEngaged = (t) =>
    t.id === baseId ||
    (state.tab_opts[t.id] && state.tab_opts[t.id].is_option);
  const defaultChipVisible = (t) => (wt === "gyp") ? (t.role === "gyp" || chipEngaged(t))
                                                   : (t.role !== "gyp" || chipEngaged(t));
  const revealSystems = !!state.reveal_systems;
  const visible = revealSystems ? priced.slice() : priced.filter(defaultChipVisible);
  const hasHiddenSystems = priced.some(t => !defaultChipVisible(t));
  // NO "Auto"/"combined" pseudo-chip on ANY job (Hanz: remove it from epoxy,
  // polish, gyp — and combo too). The base bid is always a real, listed sheet:
  // the estimator's explicit pick (baseId), or — until they pick one — the
  // auto-resolved base tab (autoBase), shown with the "base bid" tag. Every
  // other sheet, including the second base-kind tab on a combo, appears as an
  // ordinary "add as option" chip.
  const soloBase = baseId ? null
                 : (autoBase ? autoBase.id
                             : (visible.length ? visible[0].id : null));
  // No hidden-under-auto-base tabs anymore: with a single resolved base, every
  // other chip gets its normal option controls.
  const isPartOfAutoBase = () => false;
  const baseRadio = (val, checked, label) =>
    `<label class="bb-baselbl" title="Set as the Base bid"><input type="radio" name="bb-base" class="bb-base" value="${_escBB(val)}"${checked ? " checked" : ""}> <span class="bb-name">${_escBB(label)}</span></label>`;
  let html = "";
  html += visible.map(t => {
    const o = state.tab_opts[t.id] || {};
    const isBase = baseId === t.id || soloBase === t.id;
    const isOpt = !!o.is_option, show = o.show !== false, mode = o.price_mode === "deduct" ? "deduct" : "total";
    const tot = HF.ready ? hfNum(t.id, totalCellsFor(t.id).total) : 0;
    let inner = baseRadio(t.id, isBase, labelFor(t.id)) +
                `<span class="bb-price">${tot ? _moneyBB(tot) : ""}</span>`;
    if (isBase) {
      inner += `<span class="bb-tag">base bid</span>`;
    } else if (!isPartOfAutoBase(t)) {
      inner += `<span class="bb-sub">` +
        `<label title="Add this sheet to the proposal as an option"><input type="checkbox" class="bb-isopt"${isOpt ? " checked" : ""}> add as option</label>` +
        `<span class="bb-optsub"${isOpt ? "" : ' style="display:none"'}>` +
        `<label><input type="checkbox" class="bb-show"${show ? " checked" : ""}> show in proposal</label>` +
        `<span class="bb-modewrap">price as <select class="bb-mode"><option value="total"${mode === "total" ? " selected" : ""}>total</option><option value="deduct"${mode === "deduct" ? " selected" : ""}>add/deduct</option></select></span>` +
        `</span></span>`;
    }
    return `<span class="bb-opt" data-id="${_escBB(t.id)}">${inner}</span>`;
  }).join("");
  // "+ Add another system" — reveals the cross-work-type chips (e.g. Epoxy/Polish
  // on a gyp job) so the estimator can mark them as options for a multi-system
  // bid. Only shown when there ARE hidden systems to reveal.
  if (hasHiddenSystems) {
    const lbl = revealSystems ? "− Fewer systems" : "+ Add another system";
    html += `<span class="bb-opt bb-addsys"><button type="button" class="bb-addsys-btn">${_escBB(lbl)}</button></span>`;
  }
  list.innerHTML = html;
  // The legend (#bid-options-hint) stays visible — it explains base vs. option.
}

// Delegated listeners on #bid-bar (static container — attach once).
function wireBidBar() {
  const list = document.getElementById("bid-options-list");
  if (!list) return;
  // "+ Add another system" / "− Fewer systems" toggle (a button → click, not change).
  list.addEventListener("click", (e) => {
    if (!e.target.classList.contains("bb-addsys-btn")) return;
    state.reveal_systems = !state.reveal_systems;
    renderBidOptions();
    TW.setState({ ...state, reveal_systems: state.reveal_systems });
  });
  list.addEventListener("change", (e) => {
    const el = e.target;
    if (el.classList.contains("bb-base")) {          // Base-bid radio toggled
      if (!el.checked) return;
      state.base_tab_id = el.value || null;
      if (el.value && state.tab_opts[el.value]) state.tab_opts[el.value].is_option = false;  // base ≠ option
      renderBidOptions();
      persistBidOptions();
      return;
    }
    const wrap = el.closest(".bb-opt"); if (!wrap || !wrap.dataset.id) return;
    const o = ensureOpt(wrap.dataset.id);
    if (el.classList.contains("bb-isopt")) {
      o.is_option = el.checked;
      if (o.is_option) { if (o.show === undefined) o.show = true; if (!o.price_mode) o.price_mode = "total"; }
      const sub = wrap.querySelector(".bb-optsub"); if (sub) sub.style.display = el.checked ? "" : "none";
    } else if (el.classList.contains("bb-show")) {
      o.show = el.checked;
    } else if (el.classList.contains("bb-mode")) {
      o.price_mode = el.value === "deduct" ? "deduct" : "total";
    }
    persistBidOptions();
  });
}

// Display order of tab ids: saved order first (filtered to ones that still
// exist), then any new/unsaved ids appended (so a fresh copy shows up at the end).
function orderedIds() {
  const all = [...sheets, ...state.tab_copies.map(c => c.id)];
  const seen = new Set();
  const ordered = [];
  for (const id of state.tab_order) if (all.includes(id) && !seen.has(id)) { ordered.push(id); seen.add(id); }
  for (const id of all) if (!seen.has(id)) ordered.push(id);
  return ordered;
}

let tabs = [];
function buildTabs() {
  const byId = {};
  for (const id of sheets) byId[id] = { id, label: labelFor(id), role: roleFor(id), kind: "base" };
  for (const c of state.tab_copies)
    byId[c.id] = { id: c.id, label: labelFor(c.id), role: c.role || "epoxy", kind: "copy", source: c.source };
  tabs = orderedIds().map(id => byId[id]).filter(Boolean);
}

// Drag-to-reorder (Excel-style): move draggedId to targetId's slot.
// Smooth pointer-based, horizontal-only drag-to-reorder. The grabbed tab follows
// the cursor (no transition → no lag); the other tabs slide to open a gap (CSS
// transition). On release the new order is committed and the bar re-renders.
let _drag = null;
let suppressNextClick = false;

function beginTabDrag(e, btn) {
  if (e.button != null && e.button !== 0) return;     // left button / primary only
  if (e.target.closest(".room-del")) return;          // let the × delete work
  const buttons = Array.from(tabBar.querySelectorAll("button"));
  const fromIndex = buttons.indexOf(btn);
  if (fromIndex < 0) return;
  const rects = buttons.map(b => {
    const r = b.getBoundingClientRect();
    return { el: b, center: r.left + r.width / 2 };
  });
  _drag = { btn, fromIndex, buttons, rects, startX: e.clientX,
            width: btn.getBoundingClientRect().width, toIndex: fromIndex,
            active: false, pointerId: e.pointerId };
  window.addEventListener("pointermove", onTabDragMove);
  window.addEventListener("pointerup", onTabDragEnd, { once: true });
}

function onTabDragMove(e) {
  if (!_drag) return;
  const dx = e.clientX - _drag.startX;
  if (!_drag.active) {
    if (Math.abs(dx) < 5) return;                     // threshold → preserve click/dblclick
    _drag.active = true;
    document.body.style.userSelect = "none";
    _drag.btn.classList.add("dragging");
    try { _drag.btn.setPointerCapture(_drag.pointerId); } catch (_) {}
  }
  _drag.btn.style.transform = `translateX(${dx}px)`;  // follow cursor, horizontal only
  const { rects, fromIndex, width } = _drag;
  const projected = rects[fromIndex].center + dx;
  let to = fromIndex;
  while (to < rects.length - 1 && projected > rects[to + 1].center) to++;
  while (to > 0 && projected < rects[to - 1].center) to--;
  _drag.toIndex = to;
  rects.forEach((r, i) => {                            // slide siblings to open the gap
    if (i === fromIndex) return;
    let shift = 0;
    if (fromIndex < to && i > fromIndex && i <= to) shift = -width;
    else if (fromIndex > to && i >= to && i < fromIndex) shift = width;
    r.el.style.transition = "transform .15s ease";
    r.el.style.transform = shift ? `translateX(${shift}px)` : "";
  });
}

function onTabDragEnd() {
  window.removeEventListener("pointermove", onTabDragMove);
  const d = _drag; _drag = null;
  if (!d) return;
  document.body.style.userSelect = "";
  d.rects.forEach(r => { r.el.style.transition = ""; r.el.style.transform = ""; });
  d.btn.classList.remove("dragging");
  if (!d.active) return;                               // never moved → it was a click
  suppressNextClick = true;                            // don't let the drop fire a tab switch
  setTimeout(() => { suppressNextClick = false; }, 60);
  if (d.toIndex === d.fromIndex) return;               // dropped in place
  const order = d.buttons.map(b => b.dataset.sheet);   // current displayed order
  const [moved] = order.splice(d.fromIndex, 1);
  order.splice(d.toIndex, 0, moved);
  state.tab_order = order;
  buildTabs();
  TW.setState({ ...state, tab_order: state.tab_order });
  renderTabs();
}

function allLabels(exceptId) {
  return new Set(tabs.filter(t => t.id !== exceptId).map(t => labelFor(t.id).toLowerCase()));
}
function validateLabel(label, exceptId) {
  const n = String(label || "").trim();
  if (!n) return "Enter a tab name.";
  if (n.length > 31) return "Name must be 31 characters or fewer.";
  if (/[!:\\/?*\[\]"]/.test(n)) return 'Name can\'t contain  ! : \\ / ? * [ ] "';
  if (allLabels(exceptId).has(n.toLowerCase())) return `"${n}" is already a tab name.`;
  return null;
}
function uniqueLabel(base) {
  const used = allLabels(null);
  const root = base.slice(0, 31);
  if (!used.has(root.toLowerCase())) return root;
  for (let i = 2; ; i++) {                                  // reserve room for the suffix
    const suffix = " " + i;
    const label = base.slice(0, 31 - suffix.length) + suffix;
    if (!used.has(label.toLowerCase())) return label;
  }
}
function nextCopyId() {
  // ids and display labels are SEPARATE namespaces — "Copy<N>" is only ever an id.
  const used = new Set([...sheets, ...state.tab_copies.map(c => c.id)]);
  let i = 1; while (used.has("Copy" + i)) i++; return "Copy" + i;
}

// True worksheet copy: clone the source's CURRENT contents (template cells +
// the user's own edits) into a fresh HF sheet, and mirror its "<src>!.." edits
// onto the copy's keys so the backend duplicate starts identical too.
function copyTab(sourceId) {
  const srcTab = tabs.find(t => t.id === sourceId);
  if (!srcTab) return;
  if (state.tab_copies.length >= MAX_COPIES) { alert(`Limit is ${MAX_COPIES} copied tabs.`); return; }
  const src = sheetCache[sourceId];
  if (!src || !src.cells) { alert("Open that sheet once before copying it."); return; }
  const newId = nextCopyId();
  if (!HF.createSheet(newId)) { alert("Couldn't create a copy."); return; }
  HF.loadSheet(newId, src.cells);
  sheetCache[newId] = { ...src, sheet: newId };
  for (const key of Object.keys(cellValues)) {           // replay source edits onto the copy
    if (key.startsWith(sourceId + "!")) {
      const addr = key.slice(sourceId.length + 1);
      // Project info (A1:D10) is shared via =Epoxy! mirrors — don't fork it onto the copy.
      if (isProjectInfoCell(addr)) continue;
      cellValues[newId + "!" + addr] = cellValues[key];
      HF.setCellValue(newId, addr, cellValues[key]);
    }
  }
  const label = uniqueLabel(labelFor(sourceId) + " copy");
  state.tab_copies = [...state.tab_copies, { id: newId, source: sourceId, role: srcTab.role }];
  // The copy starts from the source's CURRENT layout (transformed cache), so
  // it inherits the source's structural edits under its own id — that keeps
  // txAddr/lockedCellsFor right on the copy AND tells the backend to replay
  // the same inserts/deletes on the cloned worksheet.
  const srcOps = structOpsFor(sourceId);
  if (srcOps.length) state.tab_structs = [...state.tab_structs, ...srcOps.map(o => ({ ...o, sheet: newId }))];
  // The copy inherits the source's per-cell lock overrides under its own id —
  // coordinate spaces match (same op prefix on both), so a deep copy is valid.
  const srcOv = state.lock_overrides[sourceId];
  if (srcOv) state.lock_overrides[newId] = { lock: [...(srcOv.lock || [])], unlock: [...(srcOv.unlock || [])] };
  state.tab_labels = { ...state.tab_labels, [newId]: label };
  // Place the copy immediately to the RIGHT of the sheet it was copied from
  // (Excel behavior), not at the far end of the tab bar.
  const order = orderedIds();              // includes newId (appended at the end)
  const ni = order.indexOf(newId);
  if (ni >= 0) order.splice(ni, 1);
  const si = order.indexOf(sourceId);
  order.splice(si >= 0 ? si + 1 : order.length, 0, newId);
  state.tab_order = order;
  buildTabs();
  TW.setState({ ...state, tab_copies: state.tab_copies, tab_labels: state.tab_labels,
                tab_order: state.tab_order, cell_values: cellValues });
  renderTabs();
  showSheet(newId);
}

// Rename = change the DISPLAY label only (id, cellValues, formulas untouched).
function renameTab(id, rawNew) {
  const newLabel = String(rawNew || "").trim();
  if (!newLabel || newLabel === labelFor(id)) { renderTabs(); return; }
  const err = validateLabel(newLabel, id);
  if (err) { alert(err); renderTabs(); return; }
  state.tab_labels = { ...state.tab_labels, [id]: newLabel };
  buildTabs();
  TW.setState({ ...state, tab_labels: state.tab_labels });
  renderTabs();
  if (activeSheet === id) badge.textContent = newLabel.toUpperCase();
}

// Delete is offered for copied tabs only (base template tabs stay).
async function deleteTab(id) {
  // Invariant: never delete a base template tab — it would break the hardcoded
  // Epoxy!/Polish! reads + the canonical project-info block.
  if (BASE_ROLE[id] || sheets.includes(id) || !state.tab_copies.some(c => c.id === id)) return;
  const ok = await TW.confirmDanger({ title: "Delete tab?", before: "Delete the ", name: labelFor(id),
    after: " tab?", detail: "Its estimate is removed.", confirmText: "Delete", tone: "danger" });
  if (!ok) return;
  HF.removeSheet(id);
  for (const key of Object.keys(cellValues)) if (key.startsWith(id + "!")) delete cellValues[key];
  delete sheetCache[id];
  state.tab_copies = state.tab_copies.filter(c => c.id !== id);
  delete state.tab_labels[id];
  delete state.tab_notes[id];
  delete state.tab_opts[id];
  delete state.lock_overrides[id];   // freed copy ids get reused — don't leak locks
  // Same reuse hazard for the per-option PRICE display override: nextCopyId()
  // hands the freed "Copy<N>" id to the NEXT copy, so a leftover
  // price_overrides.options[id] would print this deleted tab's overridden
  // amount/label on the new (unrelated) option's customer proposal. Drop it.
  if (state.price_overrides && state.price_overrides.options) delete state.price_overrides.options[id];
  if (state.base_tab_id === id) state.base_tab_id = null;   // fall back to auto-derive
  buildTabs();
  TW.setState({ ...state, tab_copies: state.tab_copies, tab_labels: state.tab_labels,
                tab_notes: state.tab_notes, tab_opts: state.tab_opts,
                base_tab_id: state.base_tab_id, cell_values: cellValues });
  renderTabs();
  if (activeSheet === id) showSheet(defaultBaseSheet());
}

// Inline rename: double-click a tab → editable input (Enter commits, Esc cancels).
function startRename(btn, id) {
  const input = document.createElement("input");
  input.type = "text"; input.value = labelFor(id); input.className = "room-rename";
  input.maxLength = 31;
  btn.replaceWith(input);
  input.focus(); input.select();
  let done = false;
  const finish = (commit) => {
    if (done) return; done = true;
    if (commit) renameTab(id, input.value);
    else renderTabs();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
}

// Auto-derive per-tab notes (cove base) from the tab's cove LF cells.
function deriveNotes(id) {
  // E34/E37 are the EPOXY-layout cove cells. On Polish/Gyp/other layouts those
  // same coords hold unrelated takeoff numbers, so the cove heuristic would
  // false-positive — gate it to Epoxy-layout tabs (mirrors phaseAt's guard).
  if (layoutIdFor(id) !== "Epoxy") return [];
  // Template coords translated through the tab's structural edits.
  const out = [];
  if (hfNumTx(id, "E34") + hfNumTx(id, "E37") > 0) out.push('Includes 6" Cove Base');
  return out;
}

async function init() {
  // Wait for the Supabase session/token to be ready before any /api/* call —
  // every endpoint is auth-gated, so firing before the token is set 401s and
  // the grid shows "Failed to load …".
  try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
  // 1. Tab bar + sheet list
  try {
    const res = await fetch("/api/sheets", { headers: TW.authHeaders() });
    const j = await res.json();
    sheets = j.sheets || [];
  } catch (err) {
    sheetGrid.textContent = "Could not load sheets: " + err;
    return;
  }
  buildTabs();
  renderTabs();

  // 2. Initialize HyperFormula with ALL sheet names. We need the engine
  //    to know about every sheet up front so cross-sheet formulas
  //    (=Epoxy!B1 on Polish) resolve correctly.
  HF.init(sheets);

  // 2b. Register the workbook's named expressions (e.g. AT_Clear_Satin_w_Grit)
  //    so formulas referencing them resolve instead of throwing #NAME?
  try {
    const nameRes = await fetch("/api/named-expressions", { headers: TW.authHeaders() });
    const nameData = await nameRes.json();
    // HyperFormula rejects names shaped like a cell reference — letters then
    // only digits, e.g. "Glaze4" (used by the MACRO Flake / quartz systems).
    // Alias those to a valid form ("Glaze4" -> "Glaze_4") and remember the map
    // so loadSheet() rewrites the same token in every formula. Without this the
    // whole product block returns #NAME? in the live preview.
    const aliasFor = (name) => {
      let a = name.replace(/(\d+)$/, "_$1");      // Glaze4 -> Glaze_4
      if (a === name) a = name + "_n";            // no trailing digits → suffix
      return a;
    };
    let registered = 0;
    for (const n of nameData.names || []) {
      const scopeId = (n.scope && HF.sheetIdByName[n.scope] !== undefined)
        ? HF.sheetIdByName[n.scope] : undefined;
      let regName = n.name;
      try {
        // If HF won't accept the raw name, register it under a valid alias and
        // record the rename so formula tokens get rewritten to match.
        if (!HF.instance.isItPossibleToAddNamedExpression(regName, n.expression, scopeId)) {
          regName = aliasFor(n.name);
          HF.nameAliases[n.name] = regName;
        }
        if (scopeId !== undefined) HF.instance.addNamedExpression(regName, n.expression, scopeId);
        else HF.instance.addNamedExpression(regName, n.expression);
        registered++;
      } catch (e) {
        // Couldn't register even the alias — drop the rename so we don't rewrite
        // formula tokens to a name that doesn't exist (would still be #NAME?,
        // but at least matches the unregistered original).
        delete HF.nameAliases[n.name];
      }
    }
    console.log(`Registered ${registered}/${(nameData.names || []).length} named expressions`,
                Object.keys(HF.nameAliases).length ? `(aliased: ${JSON.stringify(HF.nameAliases)})` : "");
  } catch (err) {
    console.warn("Failed to load named expressions:", err);
  }

  // 3. Fetch + load all sheets into HF up front. This is a one-time
  //    cost (~1-2 seconds) but lets formulas recompute live with no
  //    further server round-trips. Apply any saved cell_values overrides.
  sheetGrid.textContent = "Loading workbook into formula engine…";
  await Promise.all(sheets.map(async (name) => {
    try {
      const r = await fetch("/api/sheet/" + encodeURIComponent(name), { headers: TW.authHeaders() });
      const data = await r.json();
      sheetCache[name] = data;
      HF.loadSheet(name, data.cells);
    } catch (err) {
      console.warn(`Failed to load ${name}:`, err);
    }
  }));
  // 3b. Rehydrate copied tabs BEFORE replaying cell edits, so each
  //     "<copyId>!<addr>" setCellValue below lands on an existing sheet.
  //     Load the source's template content first; the cellValues replay then
  //     re-applies the copy's own edits (persisted at copy time). Process so a
  //     copy-of-a-copy comes after its source (loop until no progress).
  let pending = state.tab_copies.filter(c => c && c.id);
  for (let guard = 0; pending.length && guard < pending.length + 2; guard++) {
    const next = [];
    for (const c of pending) {
      const src = sheetCache[c.source];                 // exact source only — no Epoxy fallback
      if (!src || !src.cells) { next.push(c); continue; } // source not materialized yet — retry
      if (HF.createSheet(c.id)) { HF.loadSheet(c.id, src.cells); sheetCache[c.id] = { ...src, sheet: c.id }; }
    }
    if (next.length === pending.length) break;           // no progress (orphan source) — stop
    pending = next;
  }
  // Apply saved overrides
  for (const [key, val] of Object.entries(cellValues)) {
    const [sheet, addr] = key.split("!");
    if (sheet && addr) HF.setCellValue(sheet, addr, val);
  }

  // 4. Open the right starting tab (gyp → the gyp base, polish → Polish, else Epoxy)
  const initialSheet = defaultBaseSheet();
  badge.textContent = labelFor(initialSheet).toUpperCase();
  showSheet(initialSheet);
  // 5. Re-render the bid bar + total bar now that EVERY sheet (incl. copied
  //    tabs) exists in HF with the saved overrides applied. Without this the
  //    chips keep their pre-HF render (blank prices) until the 1.2s delayed
  //    pricing IIFE fires — and that one can RACE this async load, leaving a
  //    copy's chip permanently blank after a back-navigation while its grid
  //    shows the real total (the "chip vs sheet not uniform" report).
  renderBidOptions();
  if (HF && HF.ready) updateTotalBarFromHF();
}

function renderTabs() {
  tabBar.innerHTML = "";
  // Each tab: click = open, double-click = rename, drag = reorder (Excel-style),
  // × = delete (copies only). Display label is decoupled from the stable id.
  for (const t of tabs) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.sheet = t.id;
    btn.className = (t.kind === "copy" ? "room-tab" : "") + (t.id === activeSheet ? " active" : "");
    btn.title = "Click to open · double-click to rename · drag to reorder";
    // Declared early so the rename pencil's handler (below) can cancel a pending
    // single-click before opening the inline editor.
    let clickTimer = null;
    const cancelClick = () => { if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; } };

    const label = document.createElement("span");
    label.textContent = t.label;
    btn.appendChild(label);

    // Visible ✎ rename affordance on EVERY tab. Double-click still renames, but
    // Kyle couldn't discover that ("Not sure how to rename the tabs"), so expose
    // a button beside the name. stopPropagation so it neither opens nor drags the
    // tab; cancelClick so the pending single-click doesn't steal focus.
    const ren = document.createElement("span");
    ren.className = "tab-rename-btn";
    ren.textContent = "✎";
    ren.title = "Rename tab";
    ren.addEventListener("pointerdown", (e) => e.stopPropagation());
    ren.addEventListener("click", (e) => { e.stopPropagation(); cancelClick(); startRename(btn, t.id); });
    btn.appendChild(ren);

    if (t.kind === "copy") {
      const del = document.createElement("span");
      del.className = "room-del";
      del.textContent = "×";
      del.title = "Delete tab";
      del.addEventListener("click", (e) => { e.stopPropagation(); deleteTab(t.id); });
      btn.appendChild(del);
    }
    // Single click opens the tab; double click renames it. Disambiguate with a
    // short timer so the double-click's preceding single-clicks don't fire
    // showSheet (whose async grid reload would steal focus from the rename box).
    // suppressNextClick guards against a drag-release firing a tab switch.
    btn.addEventListener("click", () => {
      if (suppressNextClick) { suppressNextClick = false; return; }
      if (clickTimer) return;
      clickTimer = setTimeout(() => { clickTimer = null; showSheet(t.id); }, 220);
    });
    btn.addEventListener("dblclick", (e) => {
      e.preventDefault();
      if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
      startRename(btn, t.id);
    });
    // Drag-to-reorder (smooth, pointer-based, horizontal only).
    btn.addEventListener("pointerdown", (e) => beginTabDrag(e, btn));
    tabBar.appendChild(btn);
  }
  renderBidOptions();   // keep the base-bid picker + option chips in sync with the tabs
}

// The "⧉ Copy sheet" button lives in the header (beside Texture) so it's always
// visible — the tab bar overflows horizontally and would hide a button at its end.
(function wireCopySheetButton() {
  const btn = document.getElementById("copy-sheet-btn");
  if (btn) btn.addEventListener("click", () => { if (activeSheet) copyTab(activeSheet); });
})();

// ─── "Lock cell" toolbar button (Excel ribbon model) ────────────────────
// Toggles the PERMANENT lock of the active cell — extends the preset
// rate/markup/tax locks to ANY cell. The per-cell 🔒 (temporary unlock-for-
// one-edit) is unchanged. Label + enabled-state track the active cell via
// syncFormulaBar(); the toggle writes state.lock_overrides then re-renders.
const lockCellBtn = document.getElementById("lock-cell-btn");
// The addr the active cell reports as its OWN (data-display-addr) — the same
// key lockedCellsFor()/the backend merge use. null when no cell is selected.
function _activeCellAddr() {
  const inp = _activeCellInput;
  return (inp && inp.isConnected && inp.dataset && inp.dataset.displayAddr) ? inp.dataset.displayAddr : null;
}
function refreshLockButton() {
  if (!lockCellBtn) return;
  const addr = _activeCellAddr();
  if (!addr || !activeSheet) {
    lockCellBtn.disabled = true;
    lockCellBtn.textContent = "🔒 Lock cell";
    lockCellBtn.title = "Select a cell, then lock or unlock it (locked cells can't be edited in Excel)";
    return;
  }
  lockCellBtn.disabled = false;
  // Label reflects the PERMANENT (merged) lock state, NOT inp.readOnly — a
  // per-cell temporary unlock leaves readOnly=false while still permanently locked.
  const locked = lockedCellsFor(activeSheet).has(addr);
  lockCellBtn.textContent = locked ? `🔓 Unlock ${addr}` : `🔒 Lock ${addr}`;
  lockCellBtn.title = locked
    ? `Unlock ${addr} so it can be edited in Excel`
    : `Lock ${addr} so it can't be fat-fingered in Excel`;
}
if (lockCellBtn) {
  lockCellBtn.addEventListener("click", async () => {
    const addr = _activeCellAddr();
    if (!addr || !activeSheet) return;
    const wasLocked = lockedCellsFor(activeSheet).has(addr);
    const ov = state.lock_overrides[activeSheet] || { lock: [], unlock: [] };
    ov.lock = (ov.lock || []).filter(a => a !== addr);
    ov.unlock = (ov.unlock || []).filter(a => a !== addr);
    if (wasLocked) ov.unlock.push(addr);   // toggle -> unlocked (unlock wins over any preset)
    else ov.lock.push(addr);               // toggle -> locked
    if (ov.lock.length || ov.unlock.length) state.lock_overrides[activeSheet] = ov;
    else delete state.lock_overrides[activeSheet];
    const sheet = activeSheet;
    persistTabState();
    await showSheet(sheet);                 // re-render so the 🔒 icon / readonly follow
    // showSheet nulls _activeCellInput — re-focus the same cell so the button
    // keeps its target (and the label flips) instead of dead-ending.
    const again = sheetGrid.querySelector(`[data-display-addr="${addr}"]`);
    if (again) again.focus();
    refreshLockButton();
  });
}
wireBidBar();   // base-bid toggles + per-tab option controls (delegated, once)
// Collapse the bid bar to hand its height back to the worksheet (remembered).
(function wireBidCollapse() {
  const bar = document.getElementById("bid-bar");
  const btn = document.getElementById("bid-collapse");
  if (!bar || !btn) return;
  const apply = (c) => { bar.classList.toggle("collapsed", c); btn.textContent = c ? "▸ Show" : "▾ Hide"; };
  let c = false; try { c = localStorage.getItem("tw_bidbar_collapsed") === "1"; } catch {}
  apply(c);
  btn.addEventListener("click", () => {
    c = !c;
    try { localStorage.setItem("tw_bidbar_collapsed", c ? "1" : "0"); } catch {}
    apply(c);
  });
})();

async function showSheet(name) {
  activeSheet = name;
  for (const btn of tabBar.querySelectorAll("button")) {
    btn.classList.toggle("active", btn.dataset.sheet === name);
  }
  badge.textContent = labelFor(name).toUpperCase();
  // Clear stale DOM registrations from the previous sheet — those input
  // elements got detached when we tore down the prior grid.
  if (HF && HF.unregisterAll) HF.unregisterAll();
  // Same for the formula bar — its active cell is about to be detached
  // with the old grid, so drop the reference and blank the bar.
  _activeCellInput = null;
  // Any multi-cell selection belonged to the outgoing sheet's DOM — clear it so
  // the range never points at detached cells (also covers structural-op /
  // lock-toggle re-renders, which all route through showSheet).
  if (typeof _clearRangeSel === "function") { _rangeSel = null; _rangeEls = []; }
  syncFormulaBar();
  sheetGrid.className = "sheet-loading";
  sheetGrid.textContent = "Loading " + name + "…";

  if (!sheetCache[name]) {
    try {
      const r = await fetch("/api/sheet/" + encodeURIComponent(name), { headers: TW.authHeaders() });
      if (!r.ok) {
        sheetGrid.textContent = "Failed to load " + name;
        return;
      }
      sheetCache[name] = await r.json();
    } catch (err) {
      sheetGrid.textContent = "Failed to load " + name + ": " + err;
      return;
    }
  }
  renderSheet(sheetCache[name]);
}

// Map Excel border styles → CSS border declarations
const _BORDER_STYLE_MAP = {
  thin:           "1px solid",
  medium:         "2px solid",
  thick:          "3px solid",
  double:         "3px double",
  hair:           "1px dotted",
  dotted:         "1px dotted",
  dashed:         "1px dashed",
  mediumDashed:   "2px dashed",
  dashDot:        "1px dashed",
  mediumDashDot:  "2px dashed",
  dashDotDot:     "1px dotted",
  mediumDashDotDot: "2px dotted",
  slantDashDot:   "1px dashed",
};

function applyBorders(el, borders) {
  for (const side of ["top", "right", "bottom", "left"]) {
    const b = borders[side];
    if (!b || !b.style) continue;
    const css = _BORDER_STYLE_MAP[b.style] || "1px solid";
    el.style["border-" + side] = `${css} ${b.color || "#000"}`;
  }
}

function formatNumericValue(v, fmt) {
  if (v === null || v === undefined) return "";
  if (typeof v !== "number") return String(v);
  fmt = fmt || "";
  // Currency
  if (/\$/.test(fmt)) {
    const decimals = /0\.0{2}/.test(fmt) ? 2 : 0;
    return "$" + v.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }
  // Percent
  if (/%/.test(fmt)) {
    const decimals = /0\.0/.test(fmt) ? 1 : 0;
    return (v * 100).toFixed(decimals) + "%";
  }
  // Generic number with commas
  if (/#,##0/.test(fmt)) {
    const decimals = /0\.0/.test(fmt) ? 2 : 0;
    return v.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }
  // Plain number — trim long decimals
  if (Math.floor(v) === v) return String(v);
  return String(Math.round(v * 10000) / 10000);
}

function colLetter(n) {
  // 1 -> A, 2 -> B, 27 -> AA, ...
  let s = "";
  while (n > 0) { n--; s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26); }
  return s;
}

function renderSheet(data) {
  // Clip to a viewable size. Most sheets only really use rows 1-100 / cols A-H
  // for the actual estimate; the rest is reference tables we still want
  // available but at least show the workable area.
  const maxRow = Math.min(data.max_row, 100);
  const maxCol = Math.min(data.max_col, 30);

  // Build a sparse map address → cell
  const byAddr = new Map();
  for (const c of data.cells) byAddr.set(c.addr, c);

  // Build merged-cell lookups:
  //   anchorMap: addr → {rowSpan, colSpan} for cells that ARE the anchor
  //   insideMerged: Set of addresses that are inside a merge (but NOT the anchor) — skip rendering
  const anchorMap = new Map();
  const insideMerged = new Set();
  for (const m of (data.merged || [])) {
    if (!m.anchor) continue;
    anchorMap.set(m.anchor, { rowSpan: m.rowSpan, colSpan: m.colSpan });
    // Mark every cell inside the range (except the anchor) as hidden
    for (let rr = m.minRow; rr <= m.maxRow; rr++) {
      for (let cc = m.minCol; cc <= m.maxCol; cc++) {
        const addr = colLetter(cc) + rr;
        if (addr !== m.anchor) insideMerged.add(addr);
      }
    }
  }

  // Column widths — Excel "characters" ≈ ~7.5px wide
  const colPx = [];
  for (let c = 1; c <= maxCol; c++) {
    const letter = colLetter(c);
    const w = data.col_widths[letter];
    colPx.push(Math.max(48, Math.round((w || 9) * 7.5)));
  }
  const rowPx = [];
  for (let r = 1; r <= maxRow; r++) {
    const h = data.row_heights[r];
    rowPx.push(Math.max(20, Math.round((h || 15) * 1.33)));
  }

  // Build grid container
  const grid = document.createElement("div");
  grid.className = "xl-grid";
  grid.style.gridTemplateColumns = `40px ${colPx.map(p => p + "px").join(" ")}`;
  grid.style.gridTemplateRows    = `22px ${rowPx.map(p => p + "px").join(" ")}`;

  // Top-left corner
  grid.appendChild(makeCell("corner", "", { row: 1, col: 1 }));
  // Column letter headers — with draggable right-edge resize handle
  for (let c = 1; c <= maxCol; c++) {
    const header = makeCell("col-header", colLetter(c), { row: 1, col: c + 1 });
    header.dataset.colIndex = String(c);      // right-click insert/delete target
    const handle = document.createElement("div");
    handle.className = "resize-h";
    handle.dataset.colIndex = String(c);
    header.appendChild(handle);
    grid.appendChild(header);
  }
  // Row number headers — with draggable bottom-edge resize handle
  for (let r = 1; r <= maxRow; r++) {
    const header = makeCell("row-header", String(r), { row: r + 1, col: 1 });
    header.dataset.rowIndex = String(r);      // right-click insert/delete target
    const handle = document.createElement("div");
    handle.className = "resize-v";
    handle.dataset.rowIndex = String(r);
    header.appendChild(handle);
    grid.appendChild(header);
  }

  // Data cells — every cell in the visible grid gets an editable input,
  // matching Excel's behaviour where you can click any cell and type.
  // For merged ranges: render only the anchor with row/col spans applied,
  // skip the interior cells entirely.
  for (let r = 1; r <= maxRow; r++) {
    for (let c = 1; c <= maxCol; c++) {
      const addr = colLetter(c) + r;
      if (insideMerged.has(addr)) continue;   // hidden inside a merge
      const cell = byAddr.get(addr) || {
        addr, row: r, col: c,
        value: null, isFormula: false,
        fill: null, fontColor: null,
        bold: false, italic: false, fmt: "", align: "",
      };
      const cellEl = makeDataCell(cell, data.sheet, r, c, data.dropdowns);
      const span = anchorMap.get(addr);
      if (span) {
        // Stretch the anchor across its merged range
        cellEl.style.gridRow = `${r + 1} / span ${span.rowSpan}`;
        cellEl.style.gridColumn = `${c + 1} / span ${span.colSpan}`;
        cellEl.classList.add("merged-anchor");
      }
      grid.appendChild(cellEl);
    }
  }

  sheetGrid.className = "";
  sheetGrid.innerHTML = "";
  sheetGrid.appendChild(grid);

  // Wire up draggable column/row resizers
  attachResizers(grid, colPx, rowPx);
  // Wire up Excel-style keyboard nav between cells
  attachKeyboardNav(grid, maxRow, maxCol, data.sheet);
  // Bounds for range selection (clamp drag / Shift-arrow / paste to the grid).
  _rangeBounds.maxRow = maxRow; _rangeBounds.maxCol = maxCol;
  // Update the project/sheet labels in the bar (the rest is filled below)
  document.getElementById("tb-project").textContent = state.project_name || "—";
  document.getElementById("tb-sheet").textContent   = data.sheet;
  // Sync every formula cell's DOM with HF's live computed value so
  // we don't display stale xlsx-cached values when HF disagrees.
  refreshDomFromHF(data, grid);
  // Then pull bid totals from Epoxy/Polish via HF — these don't change
  // when the user switches tabs, only when they edit a driver cell.
  if (HF && HF.ready) updateTotalBarFromHF();
}

function refreshDomFromHF(data, grid) {
  if (!HF || !HF.ready) return;
  const sheet = data.sheet;
  for (const cell of data.cells) {
    // Template formula cells AND cells where the user TYPED a formula ("=…"
    // in cellValues) both display their computed value at rest.
    const uVal = cellValues[canonicalKey(sheet, cell.addr)];
    const userFormula = typeof uVal === "string" && uVal.trim().startsWith("=");
    if (!cell.isFormula && !userFormula) continue;
    // Look up the cell's DOM input via HF's registration map — avoids
    // having to CSS-escape sheet names that contain special chars like
    // 'Gyp (USG 1-8")'.
    const tgt = canonicalTarget(sheet, cell.addr);
    const inp = HF.domBySheetAddr[`${tgt.sheet}!${cell.addr}`];
    if (!inp) continue;
    if (document.activeElement === inp) continue; // don't clobber a focused cell

    // Project-info cells (rows 1-10) on a non-canonical tab are =<canonical>!Bn
    // mirrors: Polish/Seal/… mirror Epoxy; gyp VARIANTS mirror the gyp base. An
    // empty source makes that formula compute to 0 → "0" (text cells) or a date
    // artifact. Mirror the CANONICAL value so the block is identical on every
    // tab of that layout (blank when the source is blank).
    const canon = canonicalSheetFor(sheet);
    if (isProjectInfoCell(cell.addr) && sheet !== canon) {
      const cKey = `${canon}!${cell.addr}`;
      if (cellValues[cKey] != null) {
        inp.value = cellValues[cKey];
      } else {
        const srcSheet = sheetCache[canon];
        const src = srcSheet && srcSheet.cells ? srcSheet.cells.find(c => c.addr === cell.addr) : null;
        inp.value = (src && src.value !== null && src.value !== undefined)
          ? formatNumericValue(src.value, src.fmt) : "";
      }
      continue;
    }

    const hfVal = HF.getValue(sheet, cell.addr);
    let display;
    if (hfVal && typeof hfVal === "object" && "value" in hfVal) {
      // HF error wrapper. Match what Excel shows for the same condition,
      // BUT fall back to the cached value if HF errors AND we have a cache
      // (covers cells using named expressions HF doesn't know — DOM still
      // shows Excel's last-good value rather than #NAME?).
      const cached = cell.value;
      if (cached !== null && cached !== undefined) {
        display = formatNumericValue(cached, cell.fmt);
      } else {
        display = String(hfVal.value);
      }
    } else if (typeof hfVal === "number") {
      display = formatNumericValue(hfVal, cell.fmt);
    } else if (hfVal === null || hfVal === undefined) {
      // HF returned nothing — keep the cached value if we have one
      if (cell.value !== null && cell.value !== undefined) {
        display = formatNumericValue(cell.value, cell.fmt);
      } else {
        display = "";
      }
    } else {
      display = String(hfVal);
    }
    // Empty subsections (e.g. a "$ / SF" row with no SF, System 2 when only
    // System 1 is used) divide by zero and read as #DIV/0! in this live preview.
    // Show blank instead — the cell fills once the section has quantities, and
    // the proposal's price comes from the sheet's Total Lump Sum (D88/D82).
    if (typeof display === "string" && /^\s*#DIV\/0!?/.test(display)) display = "";
    inp.value = display;
  }
}

// Cell addresses where each sheet keeps its key totals. Verified against
// the actual Excel labels in templates/estimate_sheet_5.7.xlsx:
//   Epoxy   A16='Total Base Bid:' → B16=D88 (lump), D16=$/SF
//           A43='Material Total' → D43
//           A53='Install Labor'  → D53  (NOT D55 — D55 is just Labor Burden)
//           A57='TOOLING & CONSUMABLES' section → D62 (Tooling Total)
//   Polish  A15='Total Base Bid:' → B15=D82 (lump), D15=$/SF
//           A33='Material Total' → D33
//           A45='Labor Total'    → D45  (NOT D47 — D47 is Labor Burden)
//           A49='TOOLING & CONSUMABLES' section → D55 (Tooling Total)
//
// Per user direction: lump sum is based on Epoxy + Polish only. Other
// sheets (Seal, Gyp, Leveling, etc.) are reference tabs — the Total
// Bar shows the same bid totals regardless of which tab is active.
const TOTAL_CELLS = {
  Epoxy:  { total: "D88", psf: "D16", material: "D43", labor: "D53", tooling: "D62", sales_tax: "D80", remodel: "D81", phase: "C91" },
  Polish: { total: "D82", psf: "D15", material: "D33", labor: "D45", tooling: "D55", sales_tax: "D74", remodel: "D75", phase: "C85" },
  // Gyp totals live in column E; mobilization-based → NO phase cell (phase_price
  // snapshots 0). All 5 gyp variants share this layout, so it's keyed by role,
  // not sheet name (see totalCellsFor / updateTotalBar's gyp-aware guards).
  Gyp:    { total: "E87", psf: "E18", material: "E41", labor: "E52", tooling: "E61", sales_tax: "E79", remodel: "E80" },
};

function updateTotalBar(data, byAddr) {
  // Gyp variant tabs aren't named "Gyp", so the sheet-name lookup misses them —
  // fall through to totalCellsFor (role-aware) when the sheet is a gyp layout.
  const map = (TOTAL_CELLS[data.sheet] || roleFor(data.sheet) === "gyp") ? totalCellsFor(data.sheet) : {};
  const cellVal = (addr) => {
    if (!addr) return null;
    const c = byAddr.get(addr);
    return c && c.value != null ? c.value : null;
  };
  document.getElementById("tb-sheet").textContent    = data.sheet;
  document.getElementById("tb-project").textContent  = state.project_name || "—";
  document.getElementById("tb-psf").textContent      = fmtMoney(cellVal(map.psf));
  document.getElementById("tb-material").textContent = fmtMoney(cellVal(map.material));
  document.getElementById("tb-labor").textContent    = fmtMoney(cellVal(map.labor));
  document.getElementById("tb-tooling").textContent  = fmtMoney(cellVal(map.tooling));
  document.getElementById("tb-total").textContent    = fmtMoney(cellVal(map.total));
}

function fmtMoney(v) {
  if (v == null || isNaN(v)) return "—";
  return "$" + Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

function attachKeyboardNav(grid, maxRow, maxCol, sheetName) {
  grid.addEventListener("keydown", (e) => {
    const inp = e.target;
    if (!(inp.tagName === "INPUT" || inp.tagName === "SELECT")) return;
    const addr = (inp.dataset.cellAddr || "").split("!")[1];
    if (!addr) return;
    const m = addr.match(/^([A-Z]+)(\d+)$/);
    if (!m) return;
    let col = m[1].split("").reduce((a, ch) => a * 26 + (ch.charCodeAt(0) - 64), 0);
    let row = parseInt(m[2], 10);

    let dRow = 0, dCol = 0;
    if (e.key === "ArrowDown")  dRow = 1;
    else if (e.key === "ArrowUp")    dRow = -1;
    else if (e.key === "ArrowRight" && (inp.selectionStart === inp.value.length || inp.tagName === "SELECT")) dCol = 1;
    else if (e.key === "ArrowLeft"  && (inp.selectionStart === 0 || inp.tagName === "SELECT")) dCol = -1;
    else if (e.key === "Tab")    { dCol = e.shiftKey ? -1 : 1; e.preventDefault(); }
    else if (e.key === "Enter")  { dRow = 1; e.preventDefault(); }
    else return;

    if (dRow === 0 && dCol === 0) return;

    const newRow = Math.max(1, Math.min(maxRow, row + dRow));
    const newCol = Math.max(1, Math.min(maxCol, col + dCol));
    if (newRow === row && newCol === col) return;
    e.preventDefault();
    const newAddr = `${sheetName}!${colLetter(newCol)}${newRow}`;
    const target = grid.querySelector(`[data-cell-addr="${newAddr}"]`);
    if (target) {
      target.focus();
      if (target.tagName === "INPUT" && target.type === "text") target.select();
    }
  });
}

function attachResizers(grid, colPx, rowPx) {
  // Resizing a 3000-cell CSS Grid on every mousemove pixel is what makes
  // the drag feel laggy — every change to gridTemplateColumns/Rows
  // reflows every cell. Excel's trick: show a thin "ghost line" at the
  // cursor during drag (cheap — one absolutely-positioned div), and
  // only commit the new size ONCE on mouseup (one reflow at the end).
  let dragging = null;  // { kind, index, startX, startY, startSize, ghost, viewport }

  function onMouseDown(e) {
    const target = e.target;
    const isCol = target.classList.contains("resize-h");
    const isRow = target.classList.contains("resize-v");
    if (!isCol && !isRow) return;

    const viewport = grid.closest(".xl-viewport");
    const vpRect = viewport.getBoundingClientRect();
    const ghost = document.createElement("div");
    ghost.style.cssText = `
      position: absolute;
      background: var(--treadwell-red);
      opacity: 0.55;
      z-index: 100;
      pointer-events: none;
    `;
    if (isCol) {
      ghost.style.top = "0";
      ghost.style.bottom = "0";
      ghost.style.width = "2px";
      ghost.style.left = (e.clientX - vpRect.left + viewport.scrollLeft) + "px";
    } else {
      ghost.style.left = "0";
      ghost.style.right = "0";
      ghost.style.height = "2px";
      ghost.style.top = (e.clientY - vpRect.top + viewport.scrollTop) + "px";
    }
    viewport.appendChild(ghost);

    const idx = parseInt(isCol ? target.dataset.colIndex : target.dataset.rowIndex, 10);
    dragging = {
      kind: isCol ? "col" : "row",
      index: idx,
      startX: e.clientX, startY: e.clientY,
      startSize: isCol ? colPx[idx - 1] : rowPx[idx - 1],
      ghost, viewport, vpRect,
    };
    target.classList.add("dragging");
    document.body.style.cursor = isCol ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
    e.preventDefault();
  }

  // Pure visual update: just move the ghost line. No grid reflow.
  function onMouseMove(e) {
    if (!dragging) return;
    const { kind, ghost, viewport, vpRect } = dragging;
    if (kind === "col") {
      ghost.style.left = (e.clientX - vpRect.left + viewport.scrollLeft) + "px";
    } else {
      ghost.style.top  = (e.clientY - vpRect.top  + viewport.scrollTop)  + "px";
    }
  }

  function onMouseUp(e) {
    if (!dragging) return;
    const { kind, index, startX, startY, startSize, ghost } = dragging;
    // ONE commit at the end — single reflow.
    if (kind === "col") {
      const delta = e.clientX - startX;
      colPx[index - 1] = Math.max(24, startSize + delta);
      grid.style.gridTemplateColumns = `40px ${colPx.map(p => p + "px").join(" ")}`;
    } else {
      const delta = e.clientY - startY;
      rowPx[index - 1] = Math.max(14, startSize + delta);
      grid.style.gridTemplateRows = `22px ${rowPx.map(p => p + "px").join(" ")}`;
    }
    ghost.remove();
    document.querySelectorAll(".resize-h.dragging, .resize-v.dragging")
      .forEach(el => el.classList.remove("dragging"));
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    dragging = null;
  }

  grid.addEventListener("mousedown", onMouseDown);
  document.addEventListener("mousemove", onMouseMove);
  document.addEventListener("mouseup", onMouseUp);

  // Double-click handle to auto-size — simple approximation: longest cell text
  grid.addEventListener("dblclick", (e) => {
    if (!e.target.classList.contains("resize-h")) return;
    const idx = parseInt(e.target.dataset.colIndex, 10);
    let maxLen = 6;
    for (const inp of grid.querySelectorAll(
      `.gridcell:not(.col-header):not(.row-header):not(.corner) input, ` +
      `.gridcell:not(.col-header):not(.row-header):not(.corner) select`
    )) {
      const cell = inp.parentElement;
      // grid-column is "<idx+1>" because col 1 = row-headers
      if (parseInt(cell.style.gridColumn, 10) === idx + 1) {
        maxLen = Math.max(maxLen, (inp.value || "").length);
      }
    }
    colPx[idx - 1] = Math.max(48, Math.min(360, maxLen * 7.5 + 12));
    grid.style.gridTemplateColumns = `40px ${colPx.map(p => p + "px").join(" ")}`;
  });
}

function makeCell(kind, text, pos) {
  const d = document.createElement("div");
  d.className = "gridcell " + kind;
  d.textContent = text;
  d.style.gridRow = pos.row;
  d.style.gridColumn = pos.col;
  return d;
}

// ─── Locked cells ────────────────────────────────────────────────────
// The rate/markup/tax cells are LOCKED by default (read-only) so they can't be
// fat-fingered. A 🔒 on the cell unlocks it for a single edit (re-locks on blur).
// Keyed by the sheet's template LAYOUT; copies inherit their source's set; the
// generated .xlsx protects the same cells (backend/estimate_writer.py). Full set
// incl. the formula % cells (GP / Sales Tax / Remodel) — overwriting those breaks
// the calc, so they're worth locking most.
const LOCKED_CELLS = {
  "Epoxy":        ["B73", "B74", "B75", "B76", "D77", "B80", "B81", "B84"],
  "Polish":       ["B67", "B68", "B69", "B70", "D71", "B74", "B75", "B78"],
  "Seal":         ["B67", "B68", "B69", "B70", "D71", "B74", "B75", "B78"],
  "Seal (+Jnts)": ["B67", "B68", "B69", "B70", "D71", "B74", "B75"],
  "Leveling":     ["B69", "B70", "B71", "B72", "D73", "B76", "B77", "B80"],
  "Epoxy blank":  ["B70", "B71", "B72", "B73", "D74", "B77", "B78", "B81"],
};
const GYP_LOCKED = ["B72", "B74", "B75", "E76", "B79", "B80", "B83"];
// Resolve a sheet id to its layout's EFFECTIVE locked-cell Set:
// (preset rate/markup/tax cells, translated through the sheet's structural
// edits) ∪ user `lock` − user `unlock`. Presets resolve by the copy's SOURCE
// layout; user overrides are keyed by the sheet's OWN id and are already in
// current coordinates (rekeyed live on structural edits), matching the backend
// merge in estimate_writer._resolve_ws_layouts.
function lockedCellsFor(sheetId) {
  let id = sheetId, guard = 0;
  while (guard++ < 20) {
    const c = state.tab_copies.find(x => x.id === id);
    if (!c) break;
    // A copy's source can be blank on an odd/old draft; the backend defaults
    // that to "Epoxy" too (estimate_writer.py) — mirror it instead of falling
    // through to an unlocked grid that doesn't match the generated .xlsx.
    id = c.source || "Epoxy";
  }
  const base = /^Gyp/i.test(id) ? GYP_LOCKED : (LOCKED_CELLS[id] || []);
  // Preset addresses are TEMPLATE coordinates — follow the sheet's own
  // structural edits (a deleted rate cell drops out of the set).
  const preset = structOpsFor(sheetId).length
    ? base.map(a => txAddr(sheetId, a)).filter(Boolean)
    : base;
  const ov = (state.lock_overrides && state.lock_overrides[sheetId]) || null;
  const set = new Set(preset);
  if (ov) {
    (ov.lock || []).forEach(a => set.add(a));
    (ov.unlock || []).forEach(a => set.delete(a));
  }
  return set;
}

// The grid cell the formula bar is currently pointed at (Excel-style).
let _activeCellInput = null;
// True once the bar has written a keystroke through to the active cell this
// edit session. Blur is the only reliable commit point for a click-away (no
// Enter) — see the bar's `blur` listener in the ─── Formula bar ─── section.
let _fbarDirty = false;

function makeDataCell(cell, sheet, r, c, dropdowns) {
  const d = document.createElement("div");
  d.className = "gridcell";
  d.style.gridRow = r + 1;
  d.style.gridColumn = c + 1;

  // Visual styling from the original sheet
  if (cell.fill) d.style.background = cell.fill;
  if (cell.fontColor) d.style.color = cell.fontColor;
  if (cell.bold) d.classList.add("bold");
  if (cell.italic) d.classList.add("italic");
  if (cell.underline) d.style.textDecoration = "underline";
  if (cell.fontSize) d.style.fontSize = (cell.fontSize * 0.92) + "pt";
  if (cell.wrap) d.style.whiteSpace = "normal";
  // Horizontal alignment
  if (cell.align === "right") d.style.justifyContent = "flex-end";
  else if (cell.align === "center") d.style.justifyContent = "center";
  else if (cell.align === "left") d.style.justifyContent = "flex-start";
  if (cell.align === "right" || /[\\$#,0]/.test(cell.fmt || "")) d.classList.add("numeric");
  // Vertical alignment
  if (cell.valign === "top") d.style.alignItems = "flex-start";
  else if (cell.valign === "bottom") d.style.alignItems = "flex-end";
  else if (cell.valign === "center") d.style.alignItems = "center";
  // Borders from the source xlsx (overrides the default grid lines)
  if (cell.borders) applyBorders(d, cell.borders);

  // Canonical-key remap: Project Info cells (A1:D10) canonicalize to the
  // layout's source tab — Epoxy for epoxy/polish/seal/…, the gyp BASE for gyp
  // variants. Editing them on any tab writes to <canon>!{addr} so all tabs of
  // that layout stay in sync (mirroring the source xlsx's cross-sheet formulas).
  const addrKey = canonicalKey(sheet, cell.addr);
  const canon = canonicalSheetFor(sheet);
  const isYellow = cell.fill && /^#FFF[F4][0A][03A]/i.test(cell.fill);
  if (isYellow) d.classList.add("editable");
  // Visual cue when a cell is canonicalised but we're not on the source tab
  if (isProjectInfoCell(cell.addr) && sheet !== canon) {
    d.classList.add("canonical-mirror");
    d.title = `Project Info — canonical source: ${canon}!${cell.addr}`;
  }

  // Every cell is editable. Dropdowns become <select>; everything else
  // becomes <input>. Formula cells show the formula string in the input —
  // editing replaces the formula with the typed value.
  const dropOpts = dropdowns[cell.addr];
  let inp;
  if (dropOpts && dropOpts.length) {
    inp = document.createElement("select");
    const blank = document.createElement("option");
    blank.value = ""; blank.textContent = "";
    inp.appendChild(blank);
    for (const o of dropOpts) {
      const opt = document.createElement("option");
      opt.value = o; opt.textContent = o;
      inp.appendChild(opt);
    }
    inp.value = cellValues[addrKey] != null
        ? cellValues[addrKey]
        : (cell.value != null ? String(cell.value) : "");
  } else {
    inp = document.createElement("input");
    inp.type = "text";
    let displayVal;
    // For canonical-mirror cells: prefer the user's edit, else the canonical
    // source cell's cached value (Epoxy for epoxy/polish, the gyp base for gyp
    // variants), else fall back to the local cell's value. This way a mirror
    // tab's "Project Info" rows show what the source holds, not a stale 0.
    let displaySource = cell;
    if (isProjectInfoCell(cell.addr) && sheet !== canon && sheetCache[canon]) {
      const srcCells = sheetCache[canon].cells || [];
      const sourceCell = srcCells.find(c => c.addr === cell.addr);
      if (sourceCell) displaySource = sourceCell;
    }
    if (cellValues[addrKey] != null) {
      displayVal = cellValues[addrKey];
    } else if (displaySource.value !== null && displaySource.value !== undefined) {
      displayVal = formatNumericValue(displaySource.value, displaySource.fmt);
    } else {
      displayVal = "";
    }
    inp.value = displayVal;
    // Formula cells are editable but visually marked — matches Excel,
    // where you CAN overwrite a formula by typing over it (you just
    // lose the formula). Untouched formula cells still pass through
    // verbatim in the downloaded xlsx because we only write
    // cell_values keys the user actually edited.
    if (cell.isFormula) {
      d.classList.add("formula-cell");
      inp.title = "Formula cell — typing here will replace the formula";
    }
  }
  inp.dataset.cellAddr = addrKey;
  // The formula bar's Name Box shows the cell's OWN address — cellAddr holds
  // the canonical key, which points at Epoxy for mirrored Project-Info cells.
  inp.dataset.displayAddr = cell.addr;
  // Register this input with HF using the CANONICAL key — that way
  // refreshDomFromHF and propagateChangesToDom can both find it whether
  // the cell is on its source sheet or mirrored from another.
  if (typeof HF !== "undefined" && HF.registerDom) {
    const tgt = canonicalTarget(sheet, cell.addr);
    HF.registerDom(tgt.sheet, tgt.addr, inp);
  }
  // Track only real edits (the original formula/value stays in the xlsx
  // unless the user actually types something different).
  const original = inp.value;
  // %-formatted cells (GP / discounts / tax rates) take whole-number entry
  // ("10" = 10%); see the "change" normalizer below. Declared here so the
  // "input" handler can skip the live HF push for them (no mid-type flash).
  const isPctCell = /%/.test(cell.fmt || "");
  inp.addEventListener("input", (e) => {
    const newVal = e.target.value;
    if (newVal === original) {
      delete cellValues[addrKey];
    } else {
      cellValues[addrKey] = newVal;
    }
    // Push the edit into HyperFormula and update every dependent cell's DOM
    // value. This is what makes the grid "feel" like Excel.
    // IMPORTANT: route project-info edits to the CANONICAL source on Epoxy.
    // Editing Polish!B1 should update Epoxy!B1; the formula =Epoxy!B1 on
    // Polish!B1 then recomputes naturally without us touching it.
    // %-cells defer the HF write to the "change" normalizer (n/100) so the raw
    // whole number ("10") never lands in HF mid-type — that would flash a 1000%
    // total. cellValues bookkeeping above still tracks the raw text; "change"
    // fixes cellValues + HF + totals on commit (blur / Enter / paste).
    if (HF && HF.ready && !isPctCell) {
      const tgt = canonicalTarget(sheet, cell.addr);
      const affected = HF.setCellValue(tgt.sheet, tgt.addr, newVal);
      // During a bulk paste/clear the per-cell DOM propagate + total-bar refresh
      // are deferred to one _afterBulkWrite pass (HF itself still updates here).
      if (!_bulkWrite) { propagateChangesToDom(affected); updateTotalBarFromHF(); }
    }
  });
  // Percent entry on a %-formatted cell: the number you type IS the percent.
  // Kyle types whole numbers like in his sheet — hard-bid "-10" → -10%, soft
  // "10" → 10%, super "3" → 3%, "-17" → -17%. A trailing "%" is fine too
  // ("-17%" → -17%). Applied on commit (blur). Non-numeric text is left alone.
  if (isPctCell) {
    inp.addEventListener("change", (e) => {
      const raw = String(e.target.value || "").trim();
      if (raw === "" || raw === original) return;
      const n = Number(raw.replace(/%$/, "").replace(/,/g, ""));
      if (!isFinite(n)) return;                      // text — leave alone
      const norm = n / 100;                          // typed number = that percent
      cellValues[addrKey] = norm;
      e.target.value = formatNumericValue(norm, cell.fmt);
      if (HF && HF.ready) {
        const tgt = canonicalTarget(sheet, cell.addr);
        const affected = HF.setCellValue(tgt.sheet, tgt.addr, norm);
        if (!_bulkWrite) { propagateChangesToDom(affected); updateTotalBarFromHF(); }
      }
    });
  }
  // Rate/markup/tax cells LOCK by default — read-only until the estimator clicks
  // the 🔒 to unlock a single edit (auto re-locks on blur). A readonly input
  // never fires "input", so the edit writers above stay dormant while locked.
  // The generated .xlsx protects these same cells (backend/estimate_writer.py).
  if (lockedCellsFor(sheet).has(cell.addr)) {
    inp.readOnly = true;
    d.classList.add("locked");
    const lk = document.createElement("span");
    lk.className = "cell-lock";
    lk.textContent = "🔒";
    lk.title = "Locked — click to unlock for editing";
    const setLocked = (lock) => {
      inp.readOnly = lock;
      d.classList.toggle("locked", lock);
      d.classList.toggle("unlocked", !lock);
      lk.textContent = lock ? "🔒" : "🔓";
      lk.title = lock ? "Locked — click to unlock for editing" : "Unlocked — click to re-lock";
      // The formula bar mirrors this cell's lock — keep its readOnly in step
      // so the bar can't sidestep a 🔒 (or stay stuck locked after a 🔓).
      if (_activeCellInput === inp) syncFormulaBar();
    };
    // Exposed so the formula bar's blur handler can re-lock after ITS edit
    // session ends — the bar edits this cell by remote control, so the
    // re-lock decision has to live wherever that session actually finishes.
    inp._setLocked = setLocked;
    // `readOnly` is INERT on a <select> — block interaction ourselves while
    // locked, but still allow programmatic focus (mousedown re-focuses) so the
    // toolbar Lock/Unlock button can target a locked dropdown to unlock it.
    if (inp.tagName === "SELECT") {
      inp.addEventListener("mousedown", (e) => { if (inp.readOnly) { e.preventDefault(); inp.focus(); } });
      inp.addEventListener("keydown", (e) => { if (inp.readOnly) e.preventDefault(); });
    }
    lk.addEventListener("click", (e) => {
      e.stopPropagation();
      const willUnlock = inp.readOnly;
      setLocked(!willUnlock);
      // .select() exists on <input>, not <select> — guard so locking a
      // dropdown cell (now possible via the toolbar) doesn't throw.
      if (willUnlock) { inp.focus(); if (typeof inp.select === "function") inp.select(); }
    });
    // Don't re-lock when focus is moving INTO the formula bar to keep editing
    // this same cell — that would re-lock it before the bar ever got to use
    // the unlock. The bar's own blur listener re-locks once ITS session ends.
    inp.addEventListener("blur", (e) => { if (!inp.readOnly && e.relatedTarget !== fbarInput) setLocked(true); });
    d.appendChild(lk);
  }

  // ── Google-Sheets-style formula views ──
  // Resting view = the COMPUTED value; edit view (focus) = the formula text.
  // Covers user-typed formulas (a "=…" string in cellValues) and the
  // template's own formula cells alike, so clicking any calculated cell shows
  // the formula for editing — and blurring shows the number again. The
  // formula bar mirrors whichever view the cell is in.
  const _userFormula = () => {
    const v = cellValues[addrKey];
    return (typeof v === "string" && v.trim().startsWith("=")) ? v : null;
  };
  inp._editView = () => {
    if (inp.tagName === "SELECT") return;
    const f = _userFormula();
    if (f) inp.value = f;
    // Template formula cells carry the formula TEXT in cell.formula; cell.value
    // is the cached computed number the sheet was saved with.
    else if (cellValues[addrKey] == null && cell.isFormula) {
      inp.value = String(cell.formula != null ? cell.formula : cell.value);
    }
  };
  inp._restingView = () => {
    if (inp.tagName === "SELECT") return;
    if (!(_userFormula() || (cellValues[addrKey] == null && cell.isFormula))) return;
    if (!HF || !HF.ready) return;                 // initial render — refreshDomFromHF covers it
    const tgt = canonicalTarget(sheet, cell.addr);
    const v = HF.getValue(tgt.sheet, tgt.addr);
    if (v === null || v === undefined) { inp.value = ""; return; }
    inp.value = (v && typeof v === "object" && "value" in v) ? String(v.value)
      : (typeof v === "number" ? formatNumericValue(v, cell.fmt) : String(v));
  };
  // Skip the swap-back when focus moves INTO the formula bar — the bar is
  // still editing this cell and needs its raw text left alone.
  inp.addEventListener("blur", (e) => {
    if (e.relatedTarget !== fbarInput) { inp._restingView(); updateRefHighlights(); }
  });
  // A user formula re-rendered after a tab switch shows its raw "=…" text —
  // swap in the computed value right away (no-op before HF is ready).
  if (_userFormula()) inp._restingView();

  // Formula bar: reflect this cell in the top bar when it gets focus (Excel-style).
  inp.addEventListener("focus", () => { inp._editView(); _activeCellInput = inp; syncFormulaBar(); });

  d.appendChild(inp);
  return d;
}

// ─── Formula bar ─────────────────────────────────────────────────────
// Excel-style strip above the worksheet: a Name Box showing the focused
// cell's address plus a value input bound two-way to that cell. The bar
// never talks to HyperFormula itself — it writes by dispatching REAL
// input/change events on the cell input, so the edit handlers wired in
// makeDataCell (cellValues, HF push, % normalization) run unchanged.
const fbarName  = document.getElementById("fbar-name");
const fbarInput = document.getElementById("fbar-input");
// Tracks which cell input the bar last mirrored, so syncFormulaBar() can tell
// a genuine cell change (snapshot a fresh Escape target) apart from a repeat
// sync of the SAME cell (every keystroke, every HF recompute) — the latter
// must not clobber the snapshot mid-edit.
let _fbarSyncedInput = null;
// The active cell's value when the CURRENT bar session started — what Escape
// restores. Keystrokes typed in the bar write through live (see the "input"
// listener below), so re-syncing on Escape would just redisplay the
// already-edited value; only this snapshot lets Escape actually undo it.
let _fbarOrig = "";

function syncFormulaBar() {
  const inp = _activeCellInput;
  if (!inp || !inp.isConnected) {
    // No active cell (or it was detached by a grid re-render) — blank out.
    fbarName.value = "";
    fbarInput.value = "";
    fbarInput.readOnly = false;
    fbarInput.disabled = true;
    _fbarSyncedInput = null;
    clearRefHighlights();
    refreshLockButton();
    return;
  }
  if (_fbarSyncedInput !== inp) {
    // New cell under the bar — start a fresh Escape snapshot.
    _fbarOrig = inp.value;
    _fbarSyncedInput = inp;
  }
  fbarName.value = inp.dataset.displayAddr || "";
  // A multi-cell selection shows its range ("A1:C5") in the name box instead of
  // the single anchor address (a re-sync from a lock toggle / recompute must not
  // clobber it). _rangeIsMulti is a hoisted function declaration.
  if (_rangeIsMulti()) fbarName.value = _rangeRef();
  fbarInput.disabled = false;
  // Dropdown cells only accept their listed options, and locked rate cells
  // must not be editable through the back door — mirror both as read-only.
  fbarInput.readOnly = inp.tagName === "SELECT" || inp.readOnly;
  fbarInput.value = inp.value;
  updateRefHighlights();   // outline the cells this formula references
  refreshLockButton();     // keep the toolbar Lock/Unlock label on the active cell
}

// ─── Formula reference highlights (Excel-style) ─────────────────────
// While a formula is being edited (in the cell or the bar), outline the
// cells it references — color-cycled per reference, like Excel. Only refs
// on the CURRENT sheet get outlines (bare refs, or a sheet-qualified ref
// naming the active sheet); cross-sheet refs have no DOM to point at.
const _REF_HL_MAX = 6;                 // color classes ref-hl-0 … ref-hl-5
const _REF_HL_CELL_CAP = 400;          // don't outline a giant range cell-by-cell
let _refHlEls = [];
const _REF_TOKEN_RE = /(?:('(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?(\$?[A-Z]{1,3}\$?[0-9]{1,7})(?::(\$?[A-Z]{1,3}\$?[0-9]{1,7}))?/gi;

function _colToNum(letters) {
  return letters.toUpperCase().split("").reduce((a, ch) => a * 26 + (ch.charCodeAt(0) - 64), 0);
}
function _numToCol(n) {
  let s = "";
  while (n > 0) { n--; s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26); }
  return s;
}

function clearRefHighlights() {
  for (const el of _refHlEls) {
    for (let i = 0; i < _REF_HL_MAX; i++) el.classList.remove("ref-hl-" + i);
  }
  _refHlEls = [];
}

function updateRefHighlights() {
  clearRefHighlights();
  const inp = _activeCellInput;
  if (!inp || !inp.isConnected) return;
  const v = inp.value;
  if (typeof v !== "string" || !v.trim().startsWith("=")) return;

  // displayAddr -> .gridcell div, current sheet only (the grid IS the sheet)
  const byAddr = {};
  document.querySelectorAll("#sheet-grid .gridcell > input, #sheet-grid .gridcell > select").forEach(el => {
    if (el.dataset.displayAddr) byAddr[el.dataset.displayAddr] = el.parentElement;
  });

  let m, colorIdx = 0;
  _REF_TOKEN_RE.lastIndex = 0;
  while ((m = _REF_TOKEN_RE.exec(v)) !== null) {
    const [, sheetTok, a1, a2] = m;
    if (sheetTok) {
      const name = (sheetTok.startsWith("'") ? sheetTok.slice(1, -1).replace(/''/g, "'") : sheetTok);
      if (activeSheet && name.toLowerCase() !== String(activeSheet).toLowerCase()) continue;
    }
    const cls = "ref-hl-" + (colorIdx % _REF_HL_MAX);
    colorIdx++;
    const parse = (t) => {
      const mm = t.replace(/\$/g, "").match(/^([A-Z]+)([0-9]+)$/i);
      return mm ? { c: _colToNum(mm[1]), r: parseInt(mm[2], 10) } : null;
    };
    const p1 = parse(a1), p2 = a2 ? parse(a2) : p1;
    if (!p1 || !p2) continue;
    const cLo = Math.min(p1.c, p2.c), cHi = Math.max(p1.c, p2.c);
    const rLo = Math.min(p1.r, p2.r), rHi = Math.max(p1.r, p2.r);
    if ((cHi - cLo + 1) * (rHi - rLo + 1) > _REF_HL_CELL_CAP) continue;
    for (let c = cLo; c <= cHi; c++) {
      for (let r = rLo; r <= rHi; r++) {
        const el = byAddr[_numToCol(c) + r];
        if (el) { el.classList.add(cls); _refHlEls.push(el); }
      }
    }
  }
}

// Cell → bar: while the user types in a grid cell, the bar follows along.
// Delegated on the grid container so makeDataCell's handlers stay untouched;
// skipped while the bar itself has focus so the write-back echo (the bar's
// own dispatched input event bubbling back up) can't fight the user's caret.
sheetGrid.addEventListener("input", (e) => {
  if (e.target === _activeCellInput && document.activeElement !== fbarInput) {
    fbarInput.value = e.target.value;
    updateRefHighlights();   // live re-outline as the formula is typed
  }
});
// Commit-time rewrites too — the %-cell normalizer reformats on change
// ("3" → "3%"), and the bar should show what the cell now shows.
sheetGrid.addEventListener("change", (e) => {
  if (e.target === _activeCellInput && document.activeElement !== fbarInput) {
    fbarInput.value = e.target.value;
  }
});

// Bar → cell: typing in the bar writes the active cell and fires a real
// "input" event, so cellValues + HyperFormula update exactly as if the
// user had typed in the cell itself. Locked cells never get written.
fbarInput.addEventListener("input", () => {
  const inp = _activeCellInput;
  if (!inp || !inp.isConnected || inp.readOnly || inp.tagName === "SELECT") return;
  inp.value = fbarInput.value;
  inp.dispatchEvent(new Event("input", { bubbles: true }));
  // Mark the session dirty — a plain click-away never fires a native
  // "change" on its own, so the blur listener below has to commit for us.
  _fbarDirty = true;
  updateRefHighlights();   // live re-outline as the formula is typed in the bar
});
fbarInput.addEventListener("keydown", (e) => {
  const inp = _activeCellInput;
  if (!inp || !inp.isConnected) return;
  if (e.key === "Enter") {
    // Commit like blurring the cell would: "change" runs the %-cell
    // normalization, then re-read the (possibly reformatted) value and
    // hand focus back to the cell.
    e.preventDefault();
    if (!inp.readOnly && inp.tagName !== "SELECT") {
      inp.dispatchEvent(new Event("change", { bubbles: true }));
    }
    // Already committed above — clear dirty so the blur this inp.focus()
    // triggers doesn't dispatch a second "change" (the normalizer is
    // idempotent, but don't rely on that).
    _fbarDirty = false;
    syncFormulaBar();
    inp.focus();
  } else if (e.key === "Escape") {
    // Abandon the bar edit for real: keystrokes already wrote through live
    // (see the "input" listener above), so restore the value snapshotted
    // when this bar session started instead of just re-syncing — re-syncing
    // would only redisplay the already-edited value, undoing nothing.
    e.preventDefault();
    inp.value = _fbarOrig;
    inp.dispatchEvent(new Event("input", { bubbles: true }));
    inp.dispatchEvent(new Event("change", { bubbles: true }));
    _fbarDirty = false;
    syncFormulaBar();
    inp.focus();
  }
});
// The single commit choke point: blur fires whether the user tabs away,
// clicks another cell, or clicks Continue — none of which fire a native
// "change" on #fbar-input the way Enter's explicit dispatch above does.
// Blur also fires BEFORE the next element's focus, so _activeCellInput
// still points at the cell the bar was editing even when the user clicks
// straight into another cell.
fbarInput.addEventListener("blur", (e) => {
  const inp = _activeCellInput;
  if (_fbarDirty && inp && inp.isConnected && !inp.readOnly) {
    inp.dispatchEvent(new Event("change", { bubbles: true }));
  }
  _fbarDirty = false;
  // The unlock this bar session used covered exactly one edit — re-lock
  // unless focus is heading straight back into the same cell (the user is
  // still mid-edit, just bouncing focus between the cell and the bar).
  if (inp && inp._setLocked && !inp.readOnly && e.relatedTarget !== inp) {
    inp._setLocked(true);
  }
  // The cell blurred BEFORE this bar session started, so nothing else will
  // swap a just-committed formula back to its computed value — do it here
  // (unless focus is returning to the cell, i.e. the edit continues).
  if (inp && inp.isConnected && e.relatedTarget !== inp && inp._restingView) {
    inp._restingView();
  }
  syncFormulaBar();   // mirror whatever the commit/re-lock above left behind
});

// ─── Insert/delete rows & columns (Excel-style structural edits) ─────
// Right-click a row number / column letter for insert/delete. Each edit is
// recorded in state.tab_structs, pushed into HyperFormula (which rewrites
// its own formulas), and the cached sheet data + cellValues keys shift to
// the new coordinates before a full re-render. The backend replays the same
// op list onto the real .xlsx at generate time (estimate_writer.py).
const STRUCT_HEADER_GUARD_ROW = 10;   // rows 1-10 = project-info block, canonical across tabs

function _transformCacheForOp(data, op) {
  const rows = op.kind.endsWith("_rows"), insert = op.kind.startsWith("insert");
  const sh = (idx) => _shiftIdx(idx, op.at, op.count, insert);

  const cells = [];
  for (const c of data.cells) {
    const nr = rows ? sh(c.row) : c.row;
    const nc = rows ? c.col : sh(c.col);
    if (nr === null || nc === null) continue;          // deleted with its row/col
    c.row = nr; c.col = nc; c.addr = colLetter(nc) + nr;
    cells.push(c);
  }
  data.cells = cells;

  const merged = [];
  for (const m of (data.merged || [])) {
    let lo = rows ? m.minRow : m.minCol, hi = rows ? m.maxRow : m.maxCol;
    if (insert) {
      if (lo >= op.at) lo += op.count;
      if (hi >= op.at) hi += op.count;
    } else {
      const nlo = sh(lo), nhi = sh(hi);
      lo = nlo === null ? op.at : nlo;
      hi = nhi === null ? op.at - 1 : nhi;
      if (lo > hi) continue;                           // merge fully deleted
    }
    if (rows) { m.minRow = lo; m.maxRow = hi; } else { m.minCol = lo; m.maxCol = hi; }
    m.rowSpan = m.maxRow - m.minRow + 1;
    m.colSpan = m.maxCol - m.minCol + 1;
    m.anchor = colLetter(m.minCol) + m.minRow;
    merged.push(m);
  }
  data.merged = merged;

  if (rows) {
    const rh = {};
    for (const [r, h] of Object.entries(data.row_heights || {})) {
      const n = sh(parseInt(r, 10));
      if (n !== null) rh[n] = h;
    }
    data.row_heights = rh;
    data.max_row = Math.max(1, (data.max_row || 1) + (insert ? op.count : -op.count));
  } else {
    const cw = {};
    for (const [letter, w] of Object.entries(data.col_widths || {})) {
      const idx = letter.split("").reduce((a, ch) => a * 26 + (ch.charCodeAt(0) - 64), 0);
      const n = sh(idx);
      if (n !== null) cw[colLetter(n)] = w;
    }
    data.col_widths = cw;
    data.max_col = Math.max(1, (data.max_col || 1) + (insert ? op.count : -op.count));
  }

  const dd = {};
  for (const [addr, opts] of Object.entries(data.dropdowns || {})) {
    const m = /^([A-Z]{1,3})([0-9]+)$/i.exec(addr);
    if (!m) continue;
    let col = m[1].toUpperCase().split("").reduce((a, ch) => a * 26 + (ch.charCodeAt(0) - 64), 0);
    let row = parseInt(m[2], 10);
    if (rows) row = sh(row); else col = sh(col);
    if (row !== null && col !== null) dd[colLetter(col) + row] = opts;
  }
  data.dropdowns = dd;
}

function _rekeyCellValuesForOp(sheet, op) {
  const rows = op.kind.endsWith("_rows"), insert = op.kind.startsWith("insert");
  const moves = [], drops = [];
  for (const key of Object.keys(cellValues)) {
    if (!key.startsWith(sheet + "!")) continue;
    const m = /^([A-Z]{1,3})([0-9]+)$/i.exec(key.slice(sheet.length + 1));
    if (!m) continue;
    let col = m[1].toUpperCase().split("").reduce((a, ch) => a * 26 + (ch.charCodeAt(0) - 64), 0);
    let row = parseInt(m[2], 10);
    if (rows) row = _shiftIdx(row, op.at, op.count, insert);
    else col = _shiftIdx(col, op.at, op.count, insert);
    if (row === null || col === null) { drops.push(key); continue; }
    const nkey = sheet + "!" + colLetter(col) + row;
    if (nkey !== key) moves.push([key, nkey]);
  }
  for (const k of drops) delete cellValues[k];
  const vals = moves.map(([k]) => cellValues[k]);
  for (const [k] of moves) delete cellValues[k];          // two-phase: avoid clobbering
  moves.forEach(([, nk], i) => { cellValues[nk] = vals[i]; });
}

// Shift a sheet's user lock/unlock addresses through one structural op, the
// same way cellValues keys move — a deleted cell drops out of both lists.
function _rekeyLockOverridesForOp(sheet, op) {
  const ov = state.lock_overrides && state.lock_overrides[sheet];
  if (!ov) return;
  const rows = op.kind.endsWith("_rows"), insert = op.kind.startsWith("insert");
  const shiftList = (arr) => {
    const out = [];
    for (const a of (arr || [])) {
      const m = /^([A-Z]{1,3})([0-9]+)$/i.exec(String(a));
      if (!m) continue;
      let col = m[1].toUpperCase().split("").reduce((x, ch) => x * 26 + (ch.charCodeAt(0) - 64), 0);
      let row = parseInt(m[2], 10);
      if (rows) row = _shiftIdx(row, op.at, op.count, insert);
      else col = _shiftIdx(col, op.at, op.count, insert);
      if (row === null || col === null) continue;           // deleted -> drop
      out.push(colLetter(col) + row);
    }
    return out;
  };
  ov.lock = shiftList(ov.lock);
  ov.unlock = shiftList(ov.unlock);
  if (!ov.lock.length && !ov.unlock.length) delete state.lock_overrides[sheet];
}

function applyStructOp(sheet, kind, at, count = 1) {
  const rows = kind.endsWith("_rows");
  // The project-info block (rows 1-10) is canonical across every tab and the
  // intake pre-fill's anchor — structural edits start below it.
  if (rows && at <= STRUCT_HEADER_GUARD_ROW) {
    alert(`Rows 1–${STRUCT_HEADER_GUARD_ROW} are the project header — insert or delete below row ${STRUCT_HEADER_GUARD_ROW}.`);
    return;
  }
  // Never let a delete take out the sheet's own totals cells — the bid and
  // the proposal snapshot read them. (Priced roles = epoxy/polish/gyp.)
  if (kind.startsWith("delete") && isPricedRole(roleFor(sheet))) {
    const totals = Object.values(totalCellsFor(sheet));
    for (const a of totals) {
      const m = /^([A-Z]{1,3})([0-9]+)$/i.exec(a || "");
      if (!m) continue;
      const idx = rows ? parseInt(m[2], 10)
                       : m[1].toUpperCase().split("").reduce((x, ch) => x * 26 + (ch.charCodeAt(0) - 64), 0);
      if (idx >= at && idx < at + count) {
        alert("That would delete the sheet's bid totals — blocked.");
        return;
      }
    }
  }
  const sid = HF.sheetIdByName[sheet];
  if (sid === undefined || !HF.instance) return;
  try {
    if (kind === "insert_rows")      HF.instance.addRows(sid, [at - 1, count]);
    else if (kind === "delete_rows") HF.instance.removeRows(sid, [at - 1, count]);
    else if (kind === "insert_cols") HF.instance.addColumns(sid, [at - 1, count]);
    else                             HF.instance.removeColumns(sid, [at - 1, count]);
  } catch (e) {
    console.warn("structural op failed in HF:", e);
    alert("Couldn't apply that change.");
    return;
  }
  state.tab_structs = [...state.tab_structs, { sheet, kind, at, count }];
  const op = { sheet, kind, at, count };
  if (sheetCache[sheet]) _transformCacheForOp(sheetCache[sheet], op);
  _rekeyCellValuesForOp(sheet, op);
  _rekeyLockOverridesForOp(sheet, op);
  _activeCellInput = null;
  syncFormulaBar();
  showSheet(sheet);                       // full re-render from the shifted cache
  persistTabState();
}

// Right-click menu on the row/column HEADERS and grid CELLS (Sheets-style).
let _ctxMenuEl = null;
function _closeCtxMenu() { if (_ctxMenuEl) { _ctxMenuEl.remove(); _ctxMenuEl = null; } }
document.addEventListener("click", _closeCtxMenu);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") _closeCtxMenu(); });

// Build + show a context menu at (x,y). `items` is a list of
// {label, fn, danger?, disabled?, hint?} objects; a null entry renders a
// separator. Shared by the header menu and the cell menu.
function _openCtxMenu(x, y, items) {
  _closeCtxMenu();
  const menu = document.createElement("div");
  menu.className = "ctx-menu";
  for (const item of items) {
    if (!item) { const hr = document.createElement("div"); hr.className = "ctx-sep"; menu.appendChild(hr); continue; }
    const it = document.createElement("button");
    it.type = "button";
    it.className = "ctx-item" + (item.danger ? " danger" : "");
    if (item.disabled) it.disabled = true;
    const lbl = document.createElement("span");
    lbl.textContent = item.label;
    it.appendChild(lbl);
    if (item.hint) { const h = document.createElement("span"); h.className = "ctx-hint"; h.textContent = item.hint; it.appendChild(h); }
    if (!item.disabled) it.addEventListener("click", () => { _closeCtxMenu(); item.fn(); });
    menu.appendChild(it);
  }
  menu.style.left = x + "px";
  menu.style.top = y + "px";
  document.body.appendChild(menu);
  _ctxMenuEl = menu;
}

// ── Single-cell clipboard (Sheets-style Cut / Copy / Paste) ───────────────
// Hybrid: an internal buffer always works; we ALSO mirror to the OS clipboard
// (best-effort) so a cell copied here can paste into Excel, and Paste can pull
// a value copied FROM Excel. navigator.clipboard.readText is gated behind a
// user gesture (the menu click qualifies) + permission; any failure falls back
// to the internal buffer. No keyboard interception — native Ctrl+C/X/V on the
// focused input already runs the cell's own commit path.
let _cellClipboard = "";
function _clipboardWrite(text) {
  _cellClipboard = text;
  try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).catch(() => {}); } catch {}
}
async function _clipboardRead() {
  try {
    if (navigator.clipboard && navigator.clipboard.readText) {
      // Race a short timeout: in some contexts (permission pending, headless,
      // Brave shields) readText() HANGS forever instead of rejecting, which
      // would wedge Paste. Fall back to the internal buffer after 400ms.
      const t = await Promise.race([
        navigator.clipboard.readText(),
        new Promise((_, rej) => setTimeout(() => rej(new Error("clipboard-read-timeout")), 400)),
      ]);
      if (t != null && t !== "") return t;
    }
  } catch {}
  return _cellClipboard;
}
// External pastes (Excel gives tab/newline-delimited grids) collapse to this
// one cell: first cell of the first row.
function _sanitizeCellPaste(t) {
  return String(t == null ? "" : t).replace(/\r/g, "").split("\n")[0].split("\t")[0];
}
// Copy/Cut text for a cell: a user-typed FORMULA verbatim (so it re-pastes as a
// formula), else the displayed value (computed result for template formulas,
// the literal for value cells, the selected option for dropdowns).
function _cellCopyText(inp) {
  const addrKey = inp.dataset.cellAddr;
  const edited = addrKey != null ? cellValues[addrKey] : undefined;
  if (typeof edited === "string" && edited.charAt(0) === "=") return edited;
  return inp.value != null ? String(inp.value) : "";
}
// Write `text` into a cell through the SAME path a manual edit takes: set the
// value + dispatch bubbling "input" (HF + cellValues + totals) and "change"
// (%-cell normalize + the #sheet-grid persistTabState listener), then restore
// the resting view (so a pasted formula shows its computed result). Respects
// readonly + dropdown option constraints; returns false on a no-op.
function _commitCellWrite(inp, text) {
  if (inp.readOnly) return false;
  if (inp.tagName === "SELECT" && !Array.from(inp.options).some(o => o.value === text)) return false;
  inp.value = text;
  inp.dispatchEvent(new Event("input", { bubbles: true }));
  inp.dispatchEvent(new Event("change", { bubbles: true }));
  if (typeof inp._restingView === "function") { try { inp._restingView(); } catch {} }
  return true;
}

// ─── Multi-cell range selection (Excel-style) ───────────────────────────
// Drag / Shift-click / Shift-Arrow select a rectangle (shown as "F10:H14" in the
// name box); Ctrl+C copies it as TSV (pasteable into Excel), Ctrl+V spills a TSV
// block from the anchor, Delete clears every covered cell. Single-cell behavior
// is UNCHANGED whenever no multi-cell range is active — _rangeIsMulti() gates
// every new path. The anchor is always the focused input, so its existing
// :has(input:focus) outline marks it (the painter skips the anchor); the other
// covered cells get .sel-range. All listeners bind once to the persistent
// #sheet-grid / document (renderSheet only sets _rangeBounds each render).
let _rangeSel   = null;   // { anchor:{r,c}, extent:{r,c} } — grid coords, ACTIVE sheet only
let _rangeEls   = [];     // painted .gridcell wrappers (fast unpaint)
let _dragAnchor = null;   // {r,c} mousedown'd cell, before a drag activates
let _dragActive = false;
let _bulkWrite  = false;  // suppress per-cell propagate/total during paste/clear loops
const _rangeBounds = { maxRow: 1, maxCol: 1 };

function _rangeNorm() {
  const a = _rangeSel.anchor, e = _rangeSel.extent;
  return { rLo: Math.min(a.r, e.r), rHi: Math.max(a.r, e.r),
           cLo: Math.min(a.c, e.c), cHi: Math.max(a.c, e.c) };
}
function _rangeRef() {
  const { rLo, rHi, cLo, cHi } = _rangeNorm();
  return `${_numToCol(cLo)}${rLo}:${_numToCol(cHi)}${rHi}`;
}
function _rangeIsMulti() {
  return !!_rangeSel && (_rangeSel.anchor.r !== _rangeSel.extent.r || _rangeSel.anchor.c !== _rangeSel.extent.c);
}
function _cellRC(inp) {   // displayAddr "F10" -> {r,c}; null if not a plain cell
  const m = ((inp && inp.dataset && inp.dataset.displayAddr) || "").match(/^([A-Z]+)(\d+)$/);
  return m ? { c: _colToNum(m[1]), r: parseInt(m[2], 10) } : null;
}
function _gridInputsByAddr() {   // displayAddr -> input, for the current grid
  const map = {};
  sheetGrid.querySelectorAll("input[data-display-addr], select[data-display-addr]")
    .forEach(el => { map[el.dataset.displayAddr] = el; });
  return map;
}
function _clearRangeSel() {
  for (const el of _rangeEls) el.classList.remove("sel-range");
  _rangeEls = [];
  _rangeSel = null;
  syncFormulaBar();   // restore the single-cell name box
}
function _paintRangeSel() {
  for (const el of _rangeEls) el.classList.remove("sel-range");
  _rangeEls = [];
  if (!_rangeIsMulti()) { syncFormulaBar(); return; }
  const { rLo, rHi, cLo, cHi } = _rangeNorm();
  const anchor = _rangeSel.anchor;
  const byAddr = _gridInputsByAddr();
  for (let r = rLo; r <= rHi; r++) {
    for (let c = cLo; c <= cHi; c++) {
      if (r === anchor.r && c === anchor.c) continue;   // anchor keeps its focus outline
      const inp = byAddr[_numToCol(c) + r];
      const gc = inp && inp.closest(".gridcell");
      if (gc) { gc.classList.add("sel-range"); _rangeEls.push(gc); }
    }
  }
  if (fbarName) fbarName.value = _rangeRef();
}
// Extend (or start) the selection from the active cell to (r,c), clamped.
function _extendRangeTo(r, c) {
  const a = _cellRC(_activeCellInput);
  if (!a) return;
  r = Math.max(1, Math.min(_rangeBounds.maxRow, r));
  c = Math.max(1, Math.min(_rangeBounds.maxCol, c));
  _rangeSel = { anchor: (_rangeSel && _rangeSel.anchor) || a, extent: { r, c } };
  _paintRangeSel();
}
// TSV of the covered cells (row-major). The anchor sits in edit-view (raw
// formula) — swap it to resting so its cell matches the computed values the
// other cells report, then restore. Merged interiors (no input) emit "".
function _tsvFromRange() {
  const { rLo, rHi, cLo, cHi } = _rangeNorm();
  const byAddr = _gridInputsByAddr();
  const anchor = _activeCellInput;
  try { anchor && anchor._restingView && anchor._restingView(); } catch {}
  const rows = [];
  for (let r = rLo; r <= rHi; r++) {
    const cols = [];
    for (let c = cLo; c <= cHi; c++) {
      const inp = byAddr[_numToCol(c) + r];
      cols.push(inp ? _cellCopyText(inp) : "");
    }
    rows.push(cols.join("\t"));
  }
  try { anchor && anchor._editView && anchor._editView(); } catch {}
  return rows.join("\n");
}
function _tsvParse(text) {
  let s = String(text == null ? "" : text).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  s = s.replace(/\n$/, "");   // drop the single trailing newline Excel appends
  return s.split("\n").map(line => line.split("\t"));
}
// End a bulk paste/clear: re-render the grid from HF + refresh the derived UI
// once (replicating what the per-cell events, suppressed via _bulkWrite, would
// have coalesced to via the 300ms persist debounce).
function _afterBulkWrite(sheet) {
  _bulkWrite = false;
  try { refreshDomFromHF(sheetCache[sheet], sheetGrid.querySelector(".xl-grid")); } catch {}
  try { updateTotalBarFromHF(); } catch {}
  try { refreshSystemName(); } catch {}
  clearTimeout(_cbTimer);
  _cbTimer = setTimeout(() => { renderBidOptions(); persistTabState(); }, 300);
}
// Spill TSV `text` from `origin`. Multi-cell → _commitCellWrite per target (full
// edit path: HF + cellValues + % normalize), returning the skipped (locked /
// invalid-dropdown) count. Single-cell text → today's _sanitizeCellPaste path.
function _pasteTextInto(origin, text) {
  const rows = _tsvParse(text);
  const multi = rows.length > 1 || (rows[0] && rows[0].length > 1);
  if (!multi) { _commitCellWrite(origin, _sanitizeCellPaste(text)); return 0; }
  const rc = _cellRC(origin);
  if (!rc) return 0;
  const byAddr = _gridInputsByAddr();
  let skipped = 0, widest = 1;
  _bulkWrite = true;
  try {
    for (let i = 0; i < rows.length; i++) {
      const rr = rc.r + i;
      if (rr > _rangeBounds.maxRow) break;
      widest = Math.max(widest, rows[i].length);
      for (let j = 0; j < rows[i].length; j++) {
        const cc = rc.c + j;
        if (cc > _rangeBounds.maxCol) break;
        const inp = byAddr[_numToCol(cc) + rr];
        if (!inp) continue;                         // merged interior — skip silently
        if (!_commitCellWrite(inp, rows[i][j])) skipped++;
      }
    }
  } finally { _afterBulkWrite(activeSheet); }
  // Select the pasted block (Excel behavior).
  _rangeSel = { anchor: { r: rc.r, c: rc.c },
                extent: { r: Math.min(_rangeBounds.maxRow, rc.r + rows.length - 1),
                          c: Math.min(_rangeBounds.maxCol, rc.c + widest - 1) } };
  _paintRangeSel();
  return skipped;
}
function _clearRangeContents() {
  if (!_rangeIsMulti()) return;
  const { rLo, rHi, cLo, cHi } = _rangeNorm();
  const byAddr = _gridInputsByAddr();
  _bulkWrite = true;
  try {
    for (let r = rLo; r <= rHi; r++)
      for (let c = cLo; c <= cHi; c++) {
        const inp = byAddr[_numToCol(c) + r];
        if (inp) _commitCellWrite(inp, "");   // locked cells skip silently
      }
  } finally { _afterBulkWrite(activeSheet); }
}

// Mouse: drag-select + Shift-click. Plain click never preventDefaults (native
// focus + caret intact); Shift-click preventDefaults (keeps focus on the anchor).
sheetGrid.addEventListener("mousedown", (e) => {
  if (e.target.closest(".resize-h, .resize-v, .cell-lock, .row-header, .col-header, .corner")) return;
  const gc = e.target.closest(".gridcell");
  const inp = gc && gc.querySelector("input[data-display-addr], select[data-display-addr]");
  const rc = inp && _cellRC(inp);
  if (e.button !== 0) {   // right-click: keep the range if inside it (for the ctx menu), else clear
    if (_rangeIsMulti() && rc) {
      const { rLo, rHi, cLo, cHi } = _rangeNorm();
      if (!(rc.r >= rLo && rc.r <= rHi && rc.c >= cLo && rc.c <= cHi)) _clearRangeSel();
    }
    return;
  }
  if (!rc) return;
  if (e.shiftKey && _activeCellInput && _activeCellInput.isConnected) {
    e.preventDefault();                    // don't move focus off the anchor
    _extendRangeTo(rc.r, rc.c);
    return;
  }
  _clearRangeSel();                        // plain click starts fresh
  _dragAnchor = rc; _dragActive = false;   // NO preventDefault — input focuses as today
});
document.addEventListener("mousemove", (e) => {
  if (!_dragAnchor) return;
  const vp = sheetGrid.closest(".xl-viewport") || sheetGrid;
  const box = vp.getBoundingClientRect();
  const el = document.elementFromPoint(
    Math.max(box.left + 2, Math.min(box.right - 4, e.clientX)),
    Math.max(box.top + 2,  Math.min(box.bottom - 4, e.clientY)));
  const gc = el && el.closest && el.closest("#sheet-grid .gridcell");
  const inp = gc && gc.querySelector("input[data-display-addr], select[data-display-addr]");
  const rc = inp && _cellRC(inp);
  if (!rc) return;
  if (!_dragActive) {
    if (rc.r === _dragAnchor.r && rc.c === _dragAnchor.c) return;   // still in the origin cell
    _dragActive = true;
    document.body.style.userSelect = "none";
  }
  const sel = window.getSelection && window.getSelection();
  if (sel && !sel.isCollapsed) sel.removeAllRanges();
  _rangeSel = { anchor: _dragAnchor, extent: rc };
  _paintRangeSel();
  if (e.clientX > box.right - 16) vp.scrollLeft += 24;
  else if (e.clientX < box.left + 16) vp.scrollLeft -= 24;
  if (e.clientY > box.bottom - 16) vp.scrollTop += 24;
  else if (e.clientY < box.top + 16) vp.scrollTop -= 24;
});
document.addEventListener("mouseup", () => {
  _dragAnchor = null;
  if (_dragActive) { _dragActive = false; document.body.style.userSelect = ""; }
});
// Keyboard: CAPTURE on #sheet-grid so it runs before attachKeyboardNav's bubble
// nav. Consumes (preventDefault + stopPropagation) ONLY the keys it handles.
sheetGrid.addEventListener("keydown", (e) => {
  const inp = e.target;
  if (!(inp && inp.dataset && inp.dataset.displayAddr)) return;
  const rc = _cellRC(inp);
  if (!rc) return;
  const meta = e.ctrlKey || e.metaKey;
  const isArrow = e.key === "ArrowUp" || e.key === "ArrowDown" || e.key === "ArrowLeft" || e.key === "ArrowRight";
  if (e.shiftKey && !meta && isArrow) {
    const horiz = e.key === "ArrowLeft" || e.key === "ArrowRight";
    // Left/Right defer to native in-input caret selection UNLESS a range is
    // already active, it's a SELECT, or the field text is fully selected/empty
    // (mirrors attachKeyboardNav's caret gate).
    if (horiz && !_rangeIsMulti() && inp.tagName !== "SELECT" &&
        !(inp.selectionStart === 0 && inp.selectionEnd === (inp.value || "").length)) return;
    const cur = (_rangeSel && _rangeSel.extent) || rc;
    const dr = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
    const dc = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    e.preventDefault(); e.stopPropagation();
    _extendRangeTo(cur.r + dr, cur.c + dc);
    return;
  }
  if ((e.key === "Delete" || e.key === "Backspace") && _rangeIsMulti()) {
    e.preventDefault(); e.stopPropagation();
    _clearRangeContents();
    return;
  }
  if (meta && (e.key === "c" || e.key === "C") && _rangeIsMulti()) {
    e.preventDefault(); e.stopPropagation();
    _clipboardWrite(_tsvFromRange());
    return;
  }
  if (e.key === "Escape" && _rangeIsMulti()) { _clearRangeSel(); return; }   // don't consume (ctx-menu Esc)
  // Any other key with a range active (unshifted nav or a typed char): collapse
  // the range, DON'T consume — the keystroke lands in the anchor / nav proceeds.
  if (_rangeIsMulti() && !meta &&
      (e.key.length === 1 || isArrow || e.key === "Tab" || e.key === "Enter")) {
    _clearRangeSel();
  }
}, true);
// Paste: only intercept a MULTI-cell TSV; a single value takes the native path.
sheetGrid.addEventListener("paste", (e) => {
  const inp = e.target;
  if (!(inp && inp.dataset && inp.dataset.cellAddr)) return;
  const text = (e.clipboardData && e.clipboardData.getData("text/plain")) || "";
  const stripped = text.replace(/\r?\n$/, "");
  if (stripped.indexOf("\t") < 0 && stripped.indexOf("\n") < 0) return;   // single cell → native
  e.preventDefault();
  let origin = inp;
  if (_rangeIsMulti()) {
    const { rLo, cLo } = _rangeNorm();
    origin = _gridInputsByAddr()[_numToCol(cLo) + rLo] || inp;
  }
  const skipped = _pasteTextInto(origin, text);
  if (skipped > 0) alert(`Skipped ${skipped} locked/invalid cell(s).`);
});
// Clicking OUTSIDE the grid (and not the ctx menu / formula bar) clears the range.
document.addEventListener("mousedown", (e) => {
  if (!_rangeSel) return;
  if (e.target === fbarName || e.target === fbarInput) return;
  if (e.target.closest && (e.target.closest("#sheet-grid") || e.target.closest(".ctx-menu"))) return;
  _clearRangeSel();
}, true);

sheetGrid.addEventListener("contextmenu", (e) => {
  if (!activeSheet) return;
  // HEADER menu (insert/delete rows & columns).
  const head = e.target.closest(".row-header, .col-header");
  if (head) {
    const isRow = head.classList.contains("row-header");
    const idx = parseInt(head.dataset[isRow ? "rowIndex" : "colIndex"] || "0", 10);
    if (!idx) return;
    e.preventDefault();
    const label = isRow ? `row ${idx}` : `column ${colLetter(idx)}`;
    _openCtxMenu(e.pageX, e.pageY, isRow ? [
      { label: `Insert row above ${idx}`, fn: () => applyStructOp(activeSheet, "insert_rows", idx) },
      { label: `Insert row below ${idx}`, fn: () => applyStructOp(activeSheet, "insert_rows", idx + 1) },
      { label: `Delete ${label}`, danger: true, fn: () => applyStructOp(activeSheet, "delete_rows", idx) },
    ] : [
      { label: `Insert column left of ${colLetter(idx)}`, fn: () => applyStructOp(activeSheet, "insert_cols", idx) },
      { label: `Insert column right of ${colLetter(idx)}`, fn: () => applyStructOp(activeSheet, "insert_cols", idx + 1) },
      { label: `Delete ${label}`, danger: true, fn: () => applyStructOp(activeSheet, "delete_cols", idx) },
    ]);
    return;
  }
  // CELL menu (Sheets-style). Data cells are .gridcell (headers/corner are not).
  const gc = e.target.closest(".gridcell");
  if (!gc) return;
  const inp = gc.querySelector("input[data-cell-addr], select[data-cell-addr]");
  if (!inp) return;
  const m = (inp.dataset.displayAddr || "").match(/^([A-Z]+)(\d+)$/);   // OWN addr, never canonical
  if (!m) return;
  const col = m[1].split("").reduce((a, ch) => a * 26 + (ch.charCodeAt(0) - 64), 0);
  const row = parseInt(m[2], 10);
  e.preventDefault();
  // Right-clicking INSIDE a multi-cell range acts on the range (the mousedown
  // that preceded this already cleared the range if the click was outside it) —
  // keep the anchor (don't refocus) and show range Copy/Paste/Clear.
  const inRange = _rangeIsMulti();
  if (!inRange) inp.focus();   // Sheets-style: select the right-clicked single cell
  const ro = !!inp.readOnly;
  _openCtxMenu(e.pageX, e.pageY, inRange ? [
    { label: "Copy",  hint: "Ctrl+C", fn: () => { _clipboardWrite(_tsvFromRange()); } },
    { label: "Paste", hint: "Ctrl+V", fn: async () => {
        const { rLo, cLo } = _rangeNorm();
        const origin = _gridInputsByAddr()[_numToCol(cLo) + rLo] || inp;
        const skipped = _pasteTextInto(origin, await _clipboardRead());
        if (skipped > 0) alert(`Skipped ${skipped} locked/invalid cell(s).`);
      } },
    { label: "Clear contents", fn: () => { _clearRangeContents(); } },
  ] : [
    { label: "Cut",   hint: "Ctrl+X", disabled: ro, fn: () => { _clipboardWrite(_cellCopyText(inp)); _commitCellWrite(inp, ""); } },
    { label: "Copy",  hint: "Ctrl+C", fn: () => { _clipboardWrite(_cellCopyText(inp)); } },
    { label: "Paste", hint: "Ctrl+V", disabled: ro, fn: async () => { _commitCellWrite(inp, _sanitizeCellPaste(await _clipboardRead())); } },
    null,
    { label: "Insert 1 row above",   fn: () => applyStructOp(activeSheet, "insert_rows", row) },
    { label: "Insert 1 row below",   fn: () => applyStructOp(activeSheet, "insert_rows", row + 1) },
    { label: "Insert 1 column left", fn: () => applyStructOp(activeSheet, "insert_cols", col) },
    { label: "Insert 1 column right",fn: () => applyStructOp(activeSheet, "insert_cols", col + 1) },
    null,
    { label: `Delete row ${row}`,               danger: true, fn: () => applyStructOp(activeSheet, "delete_rows", row) },
    { label: `Delete column ${colLetter(col)}`, danger: true, fn: () => applyStructOp(activeSheet, "delete_cols", col) },
  ]);
});

function propagateChangesToDom(changes) {
  // changes is an array of {sheet, addr, value} from HF.setCellValue.
  // Walk each, find its DOM input on the *current* sheet, and update the
  // displayed value (formatted using the cell's number format if we have it).
  if (!changes || !changes.length) return;
  for (const ch of changes) {
    if (!ch.sheet || !ch.addr) continue;
    const inputEl = HF.domBySheetAddr[`${ch.sheet}!${ch.addr}`];
    if (!inputEl) continue;
    // Skip the cell the user is actively typing in
    if (document.activeElement === inputEl) continue;
    // Same skip one hop removed: while the FORMULA BAR is editing this cell,
    // focus sits in the bar, not the cell — overwriting here would feed HF's
    // formatted echo ("10" → "1000%") back into the blur-commit normalizer,
    // committing 100x the typed percent.
    if (inputEl === _activeCellInput && document.activeElement === fbarInput) continue;
    // Find the original cell from cache to get fmt
    const sourceCells = (sheetCache[ch.sheet] || {}).cells || [];
    const sourceCell = sourceCells.find(c => c.addr === ch.addr);
    let display;
    if (ch.value && typeof ch.value === "object" && "value" in ch.value) {
      // HF error wrapper, e.g. { value: '#DIV/0!', type: 'DIV_BY_ZERO' }
      display = String(ch.value.value);
    } else if (typeof ch.value === "number") {
      display = formatNumericValue(ch.value, sourceCell ? sourceCell.fmt : "");
    } else if (ch.value === null || ch.value === undefined) {
      display = "";
    } else {
      display = String(ch.value);
    }
    inputEl.value = display;
  }
}

function updateTotalBarFromHF() {
  // Refresh the sticky Total bar from HF. We always pull from Epoxy
  // and/or Polish (the bid-driver sheets) — never the currently-active
  // tab — because reference tabs like Seal/Gyp don't have their own
  // bid totals; they're lookup data.
  if (!HF.ready) return;
  const workType = (state.work_type || "epoxy").toLowerCase();
  // Gyp is priced off ONE base tab (mobilization-based, column-E totals) — the
  // Total bar mirrors that single gyp sheet, not the Epoxy/Polish bid drivers.
  if (workType === "gyp") {
    const baseTab = resolveBaseTab();
    const gid  = baseTab ? baseTab.id : GYP_BASE;
    const gmap = totalCellsFor(gid);
    const val = (key) => {
      const v = HF.getValue(gid, gmap[key]);
      if (v && typeof v === "object" && "value" in v) return null;   // HF error
      return typeof v === "number" ? v : null;
    };
    const setTB = (id, v) => { document.getElementById(id).textContent = v == null ? "—" : fmtMoney(v); };
    setTB("tb-material", val("material"));
    setTB("tb-labor",    val("labor"));
    setTB("tb-tooling",  val("tooling"));
    setTB("tb-total",    val("total"));
    setTB("tb-psf",      val("psf"));
    return;
  }
  // Sums numeric HF values, skipping errors / nulls
  const sumCells = (sources) => sources.reduce((acc, src) => {
    const v = HF.getValue(src.sheet, src.addr);
    if (v && typeof v === "object" && "value" in v) return acc;  // HF error
    if (typeof v !== "number") return acc;
    return acc + v;
  }, 0);
  const cellsFor = (key) => {
    const out = [];
    if (workType !== "polish") out.push({ sheet: "Epoxy",  addr: totalCellsFor("Epoxy")[key]  });
    if (workType !== "epoxy")  out.push({ sheet: "Polish", addr: totalCellsFor("Polish")[key] });
    return out;
  };

  document.getElementById("tb-material").textContent = fmtMoney(sumCells(cellsFor("material")));
  document.getElementById("tb-labor").textContent    = fmtMoney(sumCells(cellsFor("labor")));
  document.getElementById("tb-tooling").textContent  = fmtMoney(sumCells(cellsFor("tooling")));
  document.getElementById("tb-total").textContent    = fmtMoney(sumCells(cellsFor("total")));

  // $/SF — for single work type, read that sheet's $/SF directly.
  // For combo, compute as total / total-SF.
  if (workType === "combo") {
    const totalLump = sumCells(cellsFor("total"));
    const epoxySF   = Number(HF.getValue("Epoxy", "E20") || 0);
    const polishSF  = Number(HF.getValue("Polish", "E19") || 0);
    const sumSF = epoxySF + polishSF;
    document.getElementById("tb-psf").textContent = sumSF > 0
      ? fmtMoney(totalLump / sumSF)
      : "—";
  } else {
    const srcSheet = workType === "polish" ? "Polish" : "Epoxy";
    const v = HF.getValue(srcSheet, totalCellsFor(srcSheet).psf);
    const isErr = v && typeof v === "object" && "value" in v;
    document.getElementById("tb-psf").textContent =
      isErr ? String(v.value) : (typeof v === "number" ? fmtMoney(v) : "—");
  }
}

// ─── County (Remodel Tax) searchable dropdown ──────────────────────
const countyInput    = document.getElementById("county-input");
const countyResults  = document.getElementById("county-results");
const countySelected = document.getElementById("county-selected");
let allCounties = [];
let countyHighlight = -1;

async function loadCounties() {
  try {
    if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready;
    const r = await fetch("/api/reference/counties", { headers: TW.authHeaders() });
    const j = await r.json();
    allCounties = j.counties || [];
  } catch (err) {
    console.warn("Failed to load counties:", err);
  }
}

// HTML-escape a value before embedding it in innerHTML (XSS guard for the
// county picker + autofill banner, which build markup from search input,
// reference data, and server error text).
function escHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderCountyResults(query) {
  const q = query.trim().toLowerCase();
  if (!q) { countyResults.classList.remove("open"); return; }
  // Match name, state, or notes
  const matches = allCounties.filter(c => {
    return c.name.toLowerCase().includes(q)
        || (c.state || "").toLowerCase().includes(q)
        || (c.notes || "").toLowerCase().includes(q)
        || `${c.name} ${c.state}`.toLowerCase().includes(q)
        || `${c.name} county, ${c.state}`.toLowerCase().includes(q);
  }).slice(0, 30);
  if (!matches.length) {
    countyResults.innerHTML = `<div class="county-row" style="cursor:default;color:var(--ink-variant);">No counties match "${escHtml(q)}"</div>`;
    countyResults.classList.add("open");
    return;
  }
  countyHighlight = -1;
  countyResults.innerHTML = matches.map((c, i) => `
    <div class="county-row" data-idx="${i}">
      <div>
        <span class="county-name">${escHtml(c.name)} County</span>
        <span class="county-meta">${escHtml(c.state)}${c.remodel_rate != null
          ? ` · Remodel ${(c.remodel_rate * 100).toFixed(3)}%`
          : ` · ${(c.rate * 100).toFixed(3)}%`}</span>
      </div>
      ${c.notes ? `<div class="county-notes">${escHtml(c.notes)}</div>` : ""}
    </div>
  `).join("");
  countyResults._matches = matches;
  countyResults.classList.add("open");
  for (const row of countyResults.querySelectorAll(".county-row")) {
    row.addEventListener("click", () => pickCounty(matches[parseInt(row.dataset.idx, 10)]));
  }
}

function pickCounty(c) {
  // Kansas remodel tax = state 6.5% + county portion (exact, not rounded).
  // Shown here so the estimator can type it into the sheet's manual
  // "ks remodel (enter rounded)" cell (Epoxy!K81 / per-tab equivalent).
  const remodelNote = c.remodel_rate != null
    ? ` — KS remodel tax <b>${(c.remodel_rate * 100).toFixed(3)}%</b> (enter in K81)`
    : "";
  countySelected.innerHTML = `
    <span class="county-pill">${escHtml(c.name)} County, ${escHtml(c.state)}${remodelNote}
      <span class="x" id="county-clear">×</span>
    </span>
  `;
  countyInput.value = "";
  countyResults.classList.remove("open");
  // Persist to state so the proposal step can use it (token: {{county}})
  state.county = `${c.name} County, ${c.state}`;
  state.county_tax_rate = c.rate;
  state.county_remodel_rate = c.remodel_rate != null ? c.remodel_rate : null;
  state.county_notes = c.notes;
  TW.setState({ ...state, county: state.county, county_tax_rate: state.county_tax_rate, county_remodel_rate: state.county_remodel_rate, county_notes: state.county_notes });
  document.getElementById("county-clear").addEventListener("click", () => {
    delete state.county; delete state.county_tax_rate; delete state.county_remodel_rate; delete state.county_notes;
    TW.setState(state);
    countySelected.innerHTML = "";
  });
}

countyInput.addEventListener("input", e => renderCountyResults(e.target.value));
countyInput.addEventListener("focus", e => { if (e.target.value) renderCountyResults(e.target.value); });
countyInput.addEventListener("keydown", e => {
  const matches = countyResults._matches || [];
  if (!matches.length) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    countyHighlight = Math.min(countyHighlight + 1, matches.length - 1);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    countyHighlight = Math.max(countyHighlight - 1, 0);
  } else if (e.key === "Enter" && countyHighlight >= 0) {
    e.preventDefault();
    pickCounty(matches[countyHighlight]);
    return;
  } else if (e.key === "Escape") {
    countyResults.classList.remove("open");
    return;
  } else {
    return;
  }
  for (const row of countyResults.querySelectorAll(".county-row")) {
    row.classList.toggle("active", parseInt(row.dataset.idx, 10) === countyHighlight);
  }
});

document.addEventListener("click", e => {
  if (!countyInput.contains(e.target) && !countyResults.contains(e.target)) {
    countyResults.classList.remove("open");
  }
});

// Restore prior selection if user revisits
if (state.county) {
  pickCounty({
    name: state.county.replace(/ County,.*$/, ""),
    state: (state.county.match(/,\s*([A-Z]{2})/) || [])[1] || "",
    rate: state.county_tax_rate || 0,
    remodel_rate: state.county_remodel_rate != null ? state.county_remodel_rate : null,
    notes: state.county_notes || "",
  });
}

loadCounties();

// Autofill button — calls Claude via the backend, applies inferred cell
// values to the estimate grid + stashes narrative for the proposal.
// Shows a sticky banner with the full breakdown so the estimator can
// verify what the AI did instead of guessing from a 2-second flash.
function showAutofillBanner(html, kind /* "success" | "error" */) {
  let b = document.getElementById("autofill-banner");
  if (!b) {
    b = document.createElement("div");
    b.id = "autofill-banner";
    b.style.cssText = "position:fixed;top:62px;right:16px;max-width:340px;" +
      "background:white;border:1px solid var(--xl-border);" +
      "border-left:4px solid #16a34a;padding:10px 14px;font-size:12px;" +
      "z-index:90;box-shadow:0 4px 14px rgba(0,0,0,0.12);border-radius:6px;";
    document.body.appendChild(b);
  }
  b.style.borderLeftColor = kind === "error" ? "#dc2626" : "#16a34a";
  b.innerHTML = html;
  const _closeBtn = document.createElement("button");
  _closeBtn.type = "button";
  _closeBtn.textContent = "×";
  _closeBtn.style.cssText = "float:right;border:none;background:none;cursor:pointer;font-size:14px;color:#666;margin:-2px -4px 0 6px;";
  _closeBtn.addEventListener("click", () => b.remove());
  b.appendChild(_closeBtn);
}

async function callAutofillEndpoint(payload, attempt = 1) {
  // claude -p occasionally returns slowly / non-JSON; quietly retry once
  // before surfacing failure. `X-Project-Id` (the draft id) is the per-project
  // bucket the server's rate limit counts against (max 3 / 5 min per project).
  const r = await fetch("/api/autofill", {
    method: "POST",
    // authHeaders() carries Content-Type + Authorization (Bearer) + X-Project-Id
    // (the draft id, the per-project rate-limit bucket). Without the Bearer the
    // gate 401s the paid endpoint.
    headers: TW.authHeaders({ "X-Project-Id": TW.getDraftId() || "no-draft" }),
    body: JSON.stringify(payload),
  });
  const text = await r.text();
  try {
    return JSON.parse(text);   // includes 429 bodies — they're valid JSON, no retry
  } catch (err) {
    if (attempt < 2) {
      console.warn("Autofill response wasn't JSON, retrying once…", text.slice(0,120));
      return callAutofillEndpoint(payload, attempt + 1);
    }
    throw new Error("Autofill timed out twice. Try once more or fill manually.");
  }
}

document.getElementById("autofill-btn").addEventListener("click", async (e) => {
  const btn = e.target;
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Thinking…";
  try {
    const j = await callAutofillEndpoint({
      project_name: state.project_name,
      address:      state.address,
      city_state:   state.city_state,
      notes:        state.notes || "",
    });
    if (j.ok && j.cell_values) {
      const FLAG_LABELS = {
        "Epoxy!B4":"Local",   "Epoxy!B5":"Hard Bid", "Epoxy!D5":"Prevailing Wage",
        "Epoxy!B6":"Taxable", "Epoxy!D6":"Remodel",  "Epoxy!B9":"Drawings dated",
        "Epoxy!B10":"New/Reno",
      };
      const narrativeKeys = ["system_name","texture","scope_notes","schedule_notes","exclusions"];
      const carriedNarrative = {};
      const filledFlags = [];
      let n = 0;
      for (const k of Object.keys(j.cell_values)) {
        const v = j.cell_values[k];
        if (v == null) continue;
        if (k.includes("!")) {
          cellValues[k] = v;
          // Also push the value into the live HF engine so downstream
          // formulas pick it up immediately. Without this the change
          // only shows up after a sheet reload + cellValues replay.
          const [sheet, addr] = k.split("!");
          if (sheet && addr) {
            try { HF.setCellValue(sheet, addr, v); }
            catch (e) { console.warn("HF.setCellValue failed for", k, v, e); }
          }
          if (FLAG_LABELS[k]) filledFlags.push(`${FLAG_LABELS[k]}: <b>${v}</b>`);
          n++;
        } else if (narrativeKeys.includes(k)) {
          carriedNarrative[k] = v;
          n++;
        }
      }
      if (Object.keys(carriedNarrative).length) {
        Object.assign(state, carriedNarrative);
        TW.setState({ ...state, ...carriedNarrative });
        if (carriedNarrative.system_name && !sysNameInput.value) {
          sysNameInput.value = carriedNarrative.system_name;
        }
        if (carriedNarrative.texture && !texInput.value) {
          texInput.value = carriedNarrative.texture;
        }
      }
      // Persistent banner showing exactly what got filled.
      const missingFlags = Object.keys(FLAG_LABELS)
        .filter(k => !(k in j.cell_values) || j.cell_values[k] == null)
        .map(k => FLAG_LABELS[k]);
      const narrFilled = Object.keys(carriedNarrative);
      const html =
        `<div style="font-weight:700;color:#0f5132;margin-bottom:4px;">✓ Autofilled ${n} value${n===1?"":"s"}</div>` +
        `<div style="margin:4px 0;"><b>Flags:</b><br>${filledFlags.join("<br>")}</div>` +
        (narrFilled.length ? `<div style="margin:4px 0;"><b>Proposal text:</b><br>${narrFilled.join(", ")}</div>` : "") +
        (missingFlags.length ? `<div style="margin-top:6px;color:#a16207;"><b>AI skipped:</b> ${missingFlags.join(", ")}<br><span style="font-size:11px;">(re-click Autofill to retry, or edit manually)</span></div>` : "");
      showAutofillBanner(html, "success");
      btn.textContent = `✓ Filled ${n}`;
      if (activeSheet) {
        delete sheetCache[activeSheet];
        await showSheet(activeSheet);
      }
    } else {
      btn.textContent = "Unavailable";
      showAutofillBanner(`<b>Autofill unavailable.</b><br>${escHtml(j.error) || "Check that the backend's claude CLI is reachable."}`, "error");
    }
  } catch (err) {
    btn.textContent = "Failed";
    showAutofillBanner(`<b>Autofill failed.</b><br>${escHtml(err.message || err)}`, "error");
  } finally {
    setTimeout(() => { btn.disabled = false; btn.textContent = orig; }, 3000);
  }
});

// Snapshot the audit-grade HF-computed lump sums into state so the
// Proposal Review can use the workbook's exact values instead of the
// rough Python approximation. Work-type-aware — Polish-only job
// snapshots only the Polish lump; Combo snapshots both.
function snapshotLumpSumsToState() {
  if (!HF.ready) return;
  const wt = (state.work_type || "epoxy").toLowerCase();
  const num = (s, a) => {
    const v = HF.getValue(s, a);
    return typeof v === "number" ? v : 0;
  };
  const epoxyLump  = num("Epoxy",  totalCellsFor("Epoxy").total);   // D88
  const polishLump = num("Polish", totalCellsFor("Polish").total);  // D82
  // Base bid = the estimator's designated tab (state.base_tab_id) or, when unset,
  // today's derivation (base-kind epoxy tab, or the gyp base on gyp jobs). A
  // designated base drives the proposal's Total Lump Sum + itemized taxes from
  // THAT tab's cells; with no designation we keep the work_type behavior
  // (combo = Epoxy + Polish sum; gyp = the single gyp base tab's col-E totals).
  const baseTab   = resolveBaseTab();
  const baseCells = baseTab ? totalCellsFor(baseTab.id) : TOTAL_CELLS.Epoxy;
  const baseTotal = baseTab ? num(baseTab.id, baseCells.total) : 0;
  const gypLump   = (wt === "gyp" && baseTab) ? num(baseTab.id, baseCells.total) : 0;
  state.hf_lump_sums = {
    epoxy:    epoxyLump,
    polish:   polishLump,
    combined: epoxyLump + polishLump,
    gyp:      gypLump,
  };

  if (wt === "gyp") {
    // Gyp: one base tab, column-E totals, no combo. Always drive off the resolved
    // gyp base (resolveBaseTab picks Gyp (USG 1-8") when nothing is designated).
    const gid    = baseTab ? baseTab.id : GYP_BASE;
    const gCells = baseTab ? baseCells : TOTAL_CELLS.Gyp;
    state.proposal_lump_sum    = num(gid, gCells.total);
    state.proposal_sales_tax   = num(gid, gCells.sales_tax);
    state.proposal_remodel_tax = num(gid, gCells.remodel);
  } else if (state.base_tab_id && baseTab) {
    state.proposal_lump_sum    = baseTotal;
    state.proposal_sales_tax   = num(baseTab.id, baseCells.sales_tax);
    state.proposal_remodel_tax = num(baseTab.id, baseCells.remodel);
  } else {
    // Fallback (no explicit base): the single number the proposal shows, given
    // work_type; sheet's OWN sales tax (D80/D74) + remodel tax (D81/D75) so the
    // itemized breakdown matches the Total Lump Sum. Combo sums both.
    state.proposal_lump_sum =
      wt === "epoxy"  ? epoxyLump :
      wt === "polish" ? polishLump :
                        epoxyLump + polishLump;
    const pick = (e, p) => wt === "epoxy" ? e : wt === "polish" ? p : e + p;
    state.proposal_sales_tax = pick(num("Epoxy", totalCellsFor("Epoxy").sales_tax),
                                    num("Polish", totalCellsFor("Polish").sales_tax));
    state.proposal_remodel_tax = pick(num("Epoxy", totalCellsFor("Epoxy").remodel),
                                      num("Polish", totalCellsFor("Polish").remodel));
  }

  // Per-phase surcharge ("Add for additional phase" cell) — INFORMATIONAL: it
  // drives the proposal NOTES bullet only, never the bid total. Read the base
  // tab's phase cell (Epoxy!C91 / Polish!C85), guarded to tabs whose underlying
  // layout is actually Epoxy/Polish — Seal/Gyp/Leveling reuse those coords by
  // role fallback but have different layouts, so they must NOT read the phase
  // cell. 0 (unset / guarded out / row deleted) → proposal defaults to $4,500.
  const phaseAt = (id) => {
    const role = roleFor(id);
    if (role === "polish" ? layoutIdFor(id) !== "Polish" : layoutIdFor(id) !== "Epoxy") return 0;
    const t = txAddr(id, (role === "polish" ? TOTAL_CELLS.Polish : TOTAL_CELLS.Epoxy).phase);
    if (!t) return 0;
    const v = HF.getValue(id, t);
    const n = typeof v === "number" ? v : parseFloat(String(v == null ? "" : v).replace(/[$,]/g, ""));
    return isFinite(n) ? n : 0;
  };
  // Gyp is mobilization-based — it has NO phase cell, so phase_price stays 0
  // (the gyp notes use a "$8,600 / $10,800 per mobilization" bullet instead).
  let _phase = (state.base_tab_id && baseTab && wt !== "gyp") ? phaseAt(baseTab.id) : 0;
  if (!_phase && wt !== "gyp") _phase = phaseAt(wt === "polish" ? "Polish" : "Epoxy");
  state.phase_price = _phase || 0;

  // Priced options: the estimator EXPLICITLY marks OTHER priced tabs as options
  // (state.tab_opts[id].is_option) and toggles show + price_mode ("total" | "deduct").
  // state.rooms = base first, then each SHOWN option; the proposal renders the base
  // via {{#single_bid}} and each option as a "$total – … as described above" line or
  // a "($savings) – Deduct VE for … in lieu of <base>" line. No shown option ⇒ [].
  const baseDesc = baseTab ? deriveSystemNameFor(baseTab.id) : "";
  const shownBase = state.proposal_lump_sum;   // the base bid the proposal actually displays
  const mkRoom = (t, isBase) => {
    const c = totalCellsFor(t.id);
    const total = isBase ? shownBase : num(t.id, c.total);
    const o = state.tab_opts[t.id] || {};
    const desc = deriveSystemNameFor(t.id) || labelFor(t.id);
    return {
      id: t.id, name: labelFor(t.id), is_base: !!isBase,
      bid: { total, sales_tax: num(t.id, c.sales_tax), remodel: num(t.id, c.remodel) },
      base_total: shownBase,
      deduct_amount: shownBase - total,       // savings vs the shown base; <=0 ⇒ backend falls back to total
      price_mode: isBase ? "total" : (o.price_mode === "deduct" ? "deduct" : "total"),
      show: isBase ? true : (o.show !== false),
      system_desc: desc,
      option_desc: desc,
      base_desc: baseDesc,
      show_system: o.show_system !== undefined ? o.show_system : true,
      show_diff:   o.show_diff   !== undefined ? o.show_diff   : false,
      notes_auto: deriveNotes(t.id),
      notes_manual: (state.tab_notes[t.id] || []),
    };
  };
  const optionTabs = pricedTabs().filter(t =>
    (!baseTab || t.id !== baseTab.id) &&
    state.tab_opts[t.id] && state.tab_opts[t.id].is_option &&
    state.tab_opts[t.id].show !== false);
  const shownOptions = optionTabs.map(t => mkRoom(t, false)).filter(o => o.bid.total > 0);
  state.rooms = (shownOptions.length && baseTab) ? [mkRoom(baseTab, true), ...shownOptions] : [];

  // Full per-tab pricing snapshot so the Proposal Review sidebar can switch the
  // base / toggle options WITHOUT the sheet engine (proposal-review's rebuildPricing
  // mirrors this). Every priced tab, not just the shown options. `sf`/`sys_names`
  // carry the tab's own Area inputs so the proposal's Area line can follow the
  // resolved BASE tab (see state.sheet_area below).
  state.priced_tabs = pricedTabs().map(t => {
    const c = totalCellsFor(t.id);
    return {
      id: t.id, name: labelFor(t.id), role: t.role, kind: t.kind,
      total: num(t.id, c.total), sales_tax: num(t.id, c.sales_tax), remodel: num(t.id, c.remodel),
      system_desc: deriveSystemNameFor(t.id), notes_auto: deriveNotes(t.id),
      sf: sfFieldsFor(t.id),
      sys_names: roleFor(t.id) === "polish" || roleFor(t.id) === "gyp" ? [] : sysNamesFor(t.id),
    };
  });
  // Area (SF / cove LF) for the proposal, sourced from the BASE tab(s) ONLY —
  // options never contribute. Mirrors the lump-sum base resolution above
  // (explicit base → that tab; else work_type default; combo = epoxy+polish
  // base-kind tabs). proposal-review.js:rebuildPricing recomputes this the same
  // way so a base switch there re-aggregates without the sheet engine.
  const _baseKindId = (role) => {
    const t = tabs.find(x => x.role === role && x.kind === "base") || tabs.find(x => x.role === role);
    return t ? t.id : null;
  };
  let _areaBaseIds;
  if (state.base_tab_id && baseTab) _areaBaseIds = [baseTab.id];
  else if (wt === "gyp")           _areaBaseIds = [baseTab ? baseTab.id : GYP_BASE];
  else if (wt === "polish")        _areaBaseIds = [_baseKindId("polish")];
  else if (wt === "combo")         _areaBaseIds = [_baseKindId("epoxy"), _baseKindId("polish")];
  else                             _areaBaseIds = [_baseKindId("epoxy")];
  state.sheet_area = baseAreaFrom(state.priced_tabs, _areaBaseIds);

  // The Reference Bid engine + Alternate system were removed; the proposal now
  // uses the sheet totals above. Null the engine/alternate results so a resumed
  // older draft can't leak a stale figure into the options doc (config kept).
  state.computed_bid = null;
  state.alternate_computed_bid = null;
}

function persistTabState() {
  snapshotLumpSumsToState();
  TW.setState({ ...state, cell_values: cellValues, rooms: state.rooms,
                tab_copies: state.tab_copies, tab_labels: state.tab_labels,
                tab_notes: state.tab_notes, tab_order: state.tab_order,
                tab_opts: state.tab_opts, lock_overrides: state.lock_overrides });
}
document.getElementById("back-btn").addEventListener("click", () => {
  persistTabState();
  window.location.assign(TW.withDraft("/?edit=1"));   // back to intake for the current draft (home is Projects)
});
document.getElementById("continue-btn").addEventListener("click", () => {
  persistTabState();
  window.location.assign(TW.withDraft("/proposal-review.html"));
});

// ── System-name helpers (live reads off the grid / HF for the auto System Name) ──
const _cbNum = x => { const n = parseFloat(String(x).replace(/[$,]/g, "")); return isNaN(n) ? 0 : n; };
const _cbFmt = n => "$" + Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
let _cbTimer = null;
let VALID_SYSTEMS = new Set();
// Read a cell's LIVE value from the grid DOM (reflects autofill + the user's
// dropdown pick), falling back to the saved-edit map. cellValues only holds
// cells the user actually changed, so the DOM is the source of truth here.
const _cbCell = a => {
  const el = document.querySelector(`[data-cell-addr="${a}"]`);
  return (el && el.value != null && el.value !== "") ? el.value : (cellValues[a] ?? "");
};
// Dropdown header placeholders ("System 1 Options", "Cove 1 Options", "Walls…")
// are not real selections — only count a system the recipe set actually knows.
const _cbRealSystem = n => VALID_SYSTEMS.has(n);
const _cbRealCove = o => /^(Epoxy|WR)\s+\d/.test(o || "");

// Build "System Name" from the live System 1/2 picks (Epoxy!A22 / A26) plus the
// Polished Concrete option on combos, e.g. "Treadwell MACRO Flake Single
// Broadcast & Polished Concrete". Empty until a real system is picked.
function deriveSystemName() {
  // Gyp jobs name the system from the gyp base tab's B16 (e.g. 'N12 1/8"'),
  // not the Epoxy system dropdowns.
  if ((state.work_type || "epoxy").toLowerCase() === "gyp") {
    const b = resolveBaseTab();
    return b ? deriveSystemNameFor(b.id) : "";
  }
  const names = [];
  ["Epoxy!A22", "Epoxy!A26"].forEach(a => {
    const v = _cbCell(a);
    if (_cbRealSystem(v) && !names.includes(v)) names.push(v);
  });
  const psf = _cbNum(_cbCell("Polish!E18")) || _cbNum(state.polish_sf);
  if (psf > 0 && !names.includes("Polished Concrete")) names.push("Polished Concrete");
  return names.length ? "Treadwell " + names.join(" & ") : "";
}
// Per-tab system name — each room/copy can pick its own system. Reads the tab's
// OWN A22/A26 dropdown picks from HF (resolves for non-active tabs too).
function deriveSystemNameFor(id) {
  // Gyp layouts hold the system name in B16 (e.g. 'N12 1/8"'); fall back to the
  // tab label when the cell is blank.
  if (roleFor(id) === "gyp") {
    const a = txAddr(id, "B16");
    const v = a ? HF.getValue(id, a) : "";
    const s = (typeof v === "string") ? v.trim() : (typeof v === "number" ? String(v) : "");
    return s || labelFor(id);
  }
  const names = [];
  for (const a0 of ["A22", "A26"]) {
    const a = txAddr(id, a0);            // template coords follow row/col edits
    if (!a) continue;
    const v = HF.getValue(id, a);
    const s = (typeof v === "string") ? v.trim() : "";
    if (s && _cbRealSystem(s) && !names.includes(s)) names.push(s);
  }
  return names.length ? "Treadwell " + names.join(" & ") : "";
}
// Push the derived name into the field unless the user has typed their own.
function refreshSystemName() {
  if (systemNameDirty) return;
  const derived = deriveSystemName();
  if (!derived || sysNameInput.value === derived) return;
  sysNameInput.value = derived;
  pushSysTextureToState();
}

// ── Proposal price lines (options / unit prices; display-only) ──────────
let PRICE_LINES = Array.isArray(state.price_lines) ? state.price_lines.slice() : [];
function getPriceLines() {
  return PRICE_LINES
    .map(p => ({ label: (p.label || "").trim(), amount: _cbNum(p.amount) }))
    .filter(p => p.label && p.amount);
}
function persistPriceLines() { state.price_lines = PRICE_LINES; TW.setState({ ...state, price_lines: PRICE_LINES }); }
function renderPriceLines() {
  const wrap = document.getElementById("cb-pricelines");
  if (!wrap) return;
  document.getElementById("cb-pricelines-head").style.display = PRICE_LINES.length ? "grid" : "none";
  wrap.innerHTML = "";
  PRICE_LINES.forEach((p, i) => {
    const row = document.createElement("div");
    row.style.cssText = "display:grid;grid-template-columns:1fr 120px 28px;gap:6px;align-items:center;margin-bottom:4px;";
    row.innerHTML =
      `<input type="text" data-k="label" placeholder="e.g. Onsite mockup" value="${(p.label || "").replace(/"/g, "&quot;")}" style="font-size:12.5px;padding:3px 6px;">
       <input type="number" data-k="amount" placeholder="0" value="${p.amount ?? ""}" style="font-size:12.5px;padding:3px 6px;text-align:right;">
       <button type="button" data-act="rm" title="Remove" style="cursor:pointer;border:none;background:none;color:var(--treadwell-red,#c0392b);font-size:15px;">×</button>`;
    row.querySelectorAll("input").forEach(inp => inp.addEventListener("input", () => {
      PRICE_LINES[i][inp.dataset.k] = inp.value; persistPriceLines();
    }));
    row.querySelector('[data-act="rm"]').addEventListener("click", () => {
      PRICE_LINES.splice(i, 1);
      // Manual PRICE display overrides are positional (state.price_overrides.manual
      // indexed by price-line position). Splice in tandem so the deletion doesn't
      // shift a later line's override onto the wrong line in the customer proposal.
      const _mo = state.price_overrides && state.price_overrides.manual;
      if (Array.isArray(_mo) && i < _mo.length) _mo.splice(i, 1);
      persistPriceLines(); renderPriceLines();
    });
    wrap.appendChild(row);
  });
}
document.getElementById("cb-add-priceline").addEventListener("click", () => {
  PRICE_LINES.push({ label: "", amount: "" });
  persistPriceLines(); renderPriceLines();
  const inputs = document.querySelectorAll("#cb-pricelines input[data-k='label']");
  if (inputs.length) inputs[inputs.length - 1].focus();
});

// Recompute the System Name + refresh the base-bid picker / option totals when
// any grid selection or SF changes (debounced). No engine round-trip anymore —
// the proposal uses the sheet's own Total Lump Sum.
//
// persistTabState() re-snapshots the sheet's live totals into state.priced_tabs /
// proposal_lump_sum — the ONLY source the Proposal screen reads for the Base Bid.
// Without this, a cell edit updated the grid + picker but NOT that snapshot, so
// the base bid only refreshed when the estimator clicked Back/Continue (or a
// lock/structural edit fired persistTabState). Navigating to the proposal any
// other way (step nav, browser back/forward) showed a stale base bid until a
// manual page refresh. Re-snapshotting on every settled edit keeps the proposal's
// base bid in lockstep with the sheet across every navigation path.
document.getElementById("sheet-grid").addEventListener("change", () => {
  if (_bulkWrite) return;   // bulk paste/clear coalesces into one _afterBulkWrite pass
  refreshSystemName();
  clearTimeout(_cbTimer);
  _cbTimer = setTimeout(() => { renderBidOptions(); persistTabState(); }, 300);
});

init();

// Load the recipe-known system names so the base-bid picker + System Name only
// count real picks. Wait for the auth token first (gated endpoint) + send it,
// else it 401s and VALID_SYSTEMS stays empty.
(window.TWAuth && window.TWAuth.ready ? window.TWAuth.ready : Promise.resolve())
  .then(() => fetch(TW.absoluteUrl("/api/pricing/systems"), { headers: TW.authHeaders() }))
  .then(r => r.json())
  .then(d => { const list = (d.systems || d.epoxy || []); list.forEach(n => VALID_SYSTEMS.add(n)); })
  .catch(() => {})
  .finally(() => setTimeout(() => {
    renderPriceLines();
    refreshSystemName();
    renderBidOptions();
  }, 1200));

