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
      <a href="/" class="btn-primary" style="text-decoration:none;padding:12px 20px;">← Go to Intake</a>
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
function isProjectInfoCell(addr) {
  const m = (addr || "").match(/^([A-D])(\d+)$/);
  if (!m) return false;
  const row = parseInt(m[2], 10);
  return row >= 1 && row <= 10;
}
function canonicalKey(sheet, addr) {
  return isProjectInfoCell(addr)
    ? `${CANONICAL_SHEET}!${addr}`
    : `${sheet}!${addr}`;
}

// Same canonicalization but returns the {sheet, addr} pair separately —
// HF needs both, not a single combined key.
function canonicalTarget(sheet, addr) {
  return isProjectInfoCell(addr)
    ? { sheet: CANONICAL_SHEET, addr }
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

// Lookup-table automations layered on top of the raw intake → cell map.
// These never override the user's saved edits (we skip if cellValues
// already has the address). Each one cites the rule it's encoding.
function applyHeuristics(intake, putIfBlank) {
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
  for (const [field, addr] of Object.entries(FORM_TO_CELL)) {
    const v = state[field];
    if (v !== undefined && v !== null && v !== "" && cellValues[addr] === undefined) {
      cellValues[addr] = v;
    }
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

const labelFor = (id) => state.tab_labels[id] || id;
function roleFor(id) {
  if (BASE_ROLE[id]) return BASE_ROLE[id];
  const c = state.tab_copies.find(x => x.id === id);
  return c ? (c.role || "epoxy") : "other";
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
  state.tab_labels = { ...state.tab_labels, [newId]: label };
  buildTabs();
  TW.setState({ ...state, tab_copies: state.tab_copies, tab_labels: state.tab_labels, cell_values: cellValues });
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
function deleteTab(id) {
  // Invariant: never delete a base template tab — it would break the hardcoded
  // Epoxy!/Polish! reads + the canonical project-info block.
  if (BASE_ROLE[id] || sheets.includes(id) || !state.tab_copies.some(c => c.id === id)) return;
  if (!confirm(`Delete the "${labelFor(id)}" tab? Its estimate is removed.`)) return;
  HF.removeSheet(id);
  for (const key of Object.keys(cellValues)) if (key.startsWith(id + "!")) delete cellValues[key];
  delete sheetCache[id];
  state.tab_copies = state.tab_copies.filter(c => c.id !== id);
  delete state.tab_labels[id];
  delete state.tab_notes[id];
  buildTabs();
  TW.setState({ ...state, tab_copies: state.tab_copies, tab_labels: state.tab_labels,
                tab_notes: state.tab_notes, cell_values: cellValues });
  renderTabs();
  if (activeSheet === id) showSheet((state.work_type || "epoxy").toLowerCase() === "polish" ? "Polish" : "Epoxy");
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
  const n = (a) => { const v = HF.getValue(id, a); return typeof v === "number" ? v : 0; };
  const out = [];
  if (n("E34") + n("E37") > 0) out.push('Includes 6" Cove Base');
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

  // 4. Open the right starting tab
  const wt = (state.work_type || "epoxy").toLowerCase();
  const initialSheet = wt === "polish" ? "Polish" : "Epoxy";
  badge.textContent = labelFor(initialSheet).toUpperCase();
  showSheet(initialSheet);
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
    const label = document.createElement("span");
    label.textContent = t.label;
    btn.appendChild(label);
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
    let clickTimer = null;
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
}

// The "⧉ Copy sheet" button lives in the header (beside Texture) so it's always
// visible — the tab bar overflows horizontally and would hide a button at its end.
(function wireCopySheetButton() {
  const btn = document.getElementById("copy-sheet-btn");
  if (btn) btn.addEventListener("click", () => { if (activeSheet) copyTab(activeSheet); });
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
    const handle = document.createElement("div");
    handle.className = "resize-h";
    handle.dataset.colIndex = String(c);
    header.appendChild(handle);
    grid.appendChild(header);
  }
  // Row number headers — with draggable bottom-edge resize handle
  for (let r = 1; r <= maxRow; r++) {
    const header = makeCell("row-header", String(r), { row: r + 1, col: 1 });
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
    if (!cell.isFormula) continue;
    // Look up the cell's DOM input via HF's registration map — avoids
    // having to CSS-escape sheet names that contain special chars like
    // 'Gyp (USG 1-8")'.
    const tgt = canonicalTarget(sheet, cell.addr);
    const inp = HF.domBySheetAddr[`${tgt.sheet}!${cell.addr}`];
    if (!inp) continue;
    if (document.activeElement === inp) continue; // don't clobber a focused cell

    // Project-info cells (rows 1-10) on Polish/Gyp/… are =Epoxy!Bn formulas.
    // An empty Epoxy source makes that formula compute to 0 → "0" (text cells)
    // or a date artifact. Mirror the CANONICAL Epoxy value so the block is
    // identical on every tab (blank when Epoxy is blank).
    if (isProjectInfoCell(cell.addr) && sheet !== CANONICAL_SHEET) {
      const cKey = `${CANONICAL_SHEET}!${cell.addr}`;
      if (cellValues[cKey] != null) {
        inp.value = cellValues[cKey];
      } else {
        const epoxy = sheetCache[CANONICAL_SHEET];
        const src = epoxy && epoxy.cells ? epoxy.cells.find(c => c.addr === cell.addr) : null;
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
  Epoxy:  { total: "D88", psf: "D16", material: "D43", labor: "D53", tooling: "D62", sales_tax: "D80", remodel: "D81" },
  Polish: { total: "D82", psf: "D15", material: "D33", labor: "D45", tooling: "D55", sales_tax: "D74", remodel: "D75" },
};

function updateTotalBar(data, byAddr) {
  const map = TOTAL_CELLS[data.sheet] || {};
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

  // Canonical-key remap: Project Info cells (A1:D10) always live on
  // Epoxy. Editing them on any tab writes to Epoxy!{addr} so all tabs
  // stay in sync (mirroring how the source xlsx wires Polish/Gyp/etc
  // to Epoxy via cross-sheet formula references).
  const addrKey = canonicalKey(sheet, cell.addr);
  const isYellow = cell.fill && /^#FFF[F4][0A][03A]/i.test(cell.fill);
  if (isYellow) d.classList.add("editable");
  // Visual cue when a cell is canonicalised but we're not on the source tab
  if (isProjectInfoCell(cell.addr) && sheet !== CANONICAL_SHEET) {
    d.classList.add("canonical-mirror");
    d.title = `Project Info — canonical source: ${CANONICAL_SHEET}!${cell.addr}`;
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
    // For canonical-mirror cells: prefer the user's edit, else the
    // Epoxy source cell's cached value, else fall back to the local
    // cell's value. This way Polish's "Project Info" rows actually
    // show what Epoxy holds, not the local formula's stale 0.
    let displaySource = cell;
    if (isProjectInfoCell(cell.addr) && sheet !== CANONICAL_SHEET && sheetCache[CANONICAL_SHEET]) {
      const epoxyCells = sheetCache[CANONICAL_SHEET].cells || [];
      const sourceCell = epoxyCells.find(c => c.addr === cell.addr);
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
    if (HF && HF.ready) {
      const tgt = canonicalTarget(sheet, cell.addr);
      const affected = HF.setCellValue(tgt.sheet, tgt.addr, newVal);
      propagateChangesToDom(affected);
      updateTotalBarFromHF();
    }
  });
  // Percent entry on a %-formatted cell: the number you type IS the percent.
  // Kyle types whole numbers like in his sheet — hard-bid "-10" → -10%, soft
  // "10" → 10%, super "3" → 3%, "-17" → -17%. A trailing "%" is fine too
  // ("-17%" → -17%). Applied on commit (blur). Non-numeric text is left alone.
  const isPctCell = /%/.test(cell.fmt || "");
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
        propagateChangesToDom(affected);
        updateTotalBarFromHF();
      }
    });
  }
  d.appendChild(inp);
  return d;
}

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
  // Sums numeric HF values, skipping errors / nulls
  const sumCells = (sources) => sources.reduce((acc, src) => {
    const v = HF.getValue(src.sheet, src.addr);
    if (v && typeof v === "object" && "value" in v) return acc;  // HF error
    if (typeof v !== "number") return acc;
    return acc + v;
  }, 0);
  const cellsFor = (key) => {
    const out = [];
    if (workType !== "polish") out.push({ sheet: "Epoxy",  addr: TOTAL_CELLS.Epoxy[key]  });
    if (workType !== "epoxy")  out.push({ sheet: "Polish", addr: TOTAL_CELLS.Polish[key] });
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
    const v = HF.getValue(srcSheet, TOTAL_CELLS[srcSheet].psf);
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
    countyResults.innerHTML = `<div class="county-row" style="cursor:default;color:var(--ink-variant);">No counties match "${q}"</div>`;
    countyResults.classList.add("open");
    return;
  }
  countyHighlight = -1;
  countyResults.innerHTML = matches.map((c, i) => `
    <div class="county-row" data-idx="${i}">
      <div>
        <span class="county-name">${c.name} County</span>
        <span class="county-meta">${c.state}${c.remodel_rate != null
          ? ` · Remodel ${(c.remodel_rate * 100).toFixed(3)}%`
          : ` · ${(c.rate * 100).toFixed(3)}%`}</span>
      </div>
      ${c.notes ? `<div class="county-notes">${c.notes}</div>` : ""}
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
    <span class="county-pill">${c.name} County, ${c.state}${remodelNote}
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
      showAutofillBanner(`<b>Autofill unavailable.</b><br>${j.error || "Check that the backend's claude CLI is reachable."}`, "error");
    }
  } catch (err) {
    btn.textContent = "Failed";
    showAutofillBanner(`<b>Autofill failed.</b><br>${err.message || err}`, "error");
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
  const epoxyLump  = num("Epoxy",  TOTAL_CELLS.Epoxy.total);   // D88
  const polishLump = num("Polish", TOTAL_CELLS.Polish.total);  // D82
  state.hf_lump_sums = {
    epoxy:    epoxyLump,
    polish:   polishLump,
    combined: epoxyLump + polishLump,
  };
  // The single number the proposal should show, given work_type.
  state.proposal_lump_sum =
    wt === "epoxy"  ? epoxyLump :
    wt === "polish" ? polishLump :
                      epoxyLump + polishLump;
  // Sheet's OWN sales tax (D80/D74) + remodel tax (D81/D75) so the proposal's
  // itemized breakdown matches the Total Lump Sum exactly — not the recipe
  // engine's figures (which omit Kyle's manual sheet tweaks). Combo sums both.
  const pick = (e, p) => wt === "epoxy" ? e : wt === "polish" ? p : e + p;
  state.proposal_sales_tax = pick(num("Epoxy", TOTAL_CELLS.Epoxy.sales_tax),
                                  num("Polish", TOTAL_CELLS.Polish.sales_tax));
  state.proposal_remodel_tax = pick(num("Epoxy", TOTAL_CELLS.Epoxy.remodel),
                                    num("Polish", TOTAL_CELLS.Polish.remodel));
  // Per-sheet priced options: when 2+ epoxy-family sheets carry a bid, the proposal
  // lists each as an option (base bid first, then copies). Each can show its own
  // system/scope and a signed difference vs. the base bid (estimator toggles on
  // Proposal Review). 1 epoxy sheet → state.rooms = [] (unchanged single-bid).
  const tc = TOTAL_CELLS.Epoxy;
  const epoxyTabs = tabs.filter(t => t.role === "epoxy");
  const baseTab = epoxyTabs.find(t => t.kind === "base") || epoxyTabs[0];
  const baseTotal = baseTab ? num(baseTab.id, tc.total) : 0;
  state.tab_opts = (state.tab_opts && typeof state.tab_opts === "object") ? state.tab_opts : {};
  const opts = epoxyTabs.map(t => {
    const isBase = baseTab && t.id === baseTab.id;
    const saved = state.tab_opts[t.id] || {};
    return {
      id: t.id, name: labelFor(t.id), is_base: !!isBase,
      bid: { total: num(t.id, tc.total), sales_tax: num(t.id, tc.sales_tax), remodel: num(t.id, tc.remodel) },
      base_total: baseTotal,
      system_desc: deriveSystemNameFor(t.id),
      show_system: saved.show_system !== undefined ? saved.show_system : true,
      show_diff: saved.show_diff !== undefined ? saved.show_diff
                 : (!isBase && epoxyTabs.length === 2),
      notes_auto: deriveNotes(t.id),
      notes_manual: (state.tab_notes[t.id] || []),
    };
  }).filter(o => o.bid.total > 0);
  state.rooms = opts.length >= 2 ? opts : [];
}

function persistTabState() {
  snapshotLumpSumsToState();
  TW.setState({ ...state, cell_values: cellValues, rooms: state.rooms,
                tab_copies: state.tab_copies, tab_labels: state.tab_labels,
                tab_notes: state.tab_notes, tab_order: state.tab_order,
                tab_opts: state.tab_opts });
}
document.getElementById("back-btn").addEventListener("click", () => {
  persistTabState();
  window.location.assign("/");
});
document.getElementById("continue-btn").addEventListener("click", () => {
  persistTabState();
  window.location.assign("/proposal-review.html");
});

// ── Computed Bid panel (tool's 5.7-recipe pricing: multi-system, bulk, full bid) ──
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
  const names = [];
  for (const a of ["A22", "A26"]) {
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

async function computeBid() {
  const systems = [], coves = [];
  [["Epoxy!A22", "Epoxy!E20"], ["Epoxy!A26", "Epoxy!E24"]].forEach(([na, sa]) => {
    const name = _cbCell(na), sf = _cbNum(_cbCell(sa));
    if (_cbRealSystem(name) && sf > 0) systems.push({ name, sf });
  });
  [["Epoxy!A35", "Epoxy!E34"], ["Epoxy!A37", "Epoxy!E37"]].forEach(([oa, la]) => {
    const option = _cbCell(oa), lf = _cbNum(_cbCell(la));
    if (_cbRealCove(option) && lf > 0) coves.push({ option, lf });
  });
  const payload = {
    systems, coves,
    extras: getExtras(),
    bulk_discount: document.getElementById("cb-bulk").checked,
    taxable: String(_cbCell("Epoxy!B6") || "yes").toLowerCase() !== "no",
    remodel: String(_cbCell("Epoxy!D6") || "").toLowerCase() === "yes",
    remodel_rate: state.county_remodel_rate || 0,
    sales_tax_rate: 0.09475,
    full_bid: true,
  };
  const psf = _cbNum(_cbCell("Polish!E18")) || _cbNum(state.polish_sf);
  if (psf > 0) payload.polish_sf = psf;
  // Alternate (recommended) system — priced with the SAME tax/labor as the base.
  if (typeof altActive === "function" && altActive()) {
    payload.alternate_systems = [{ name: ALT.system, sf: _cbNum(ALT.sf) }];
    payload.alternate_label = (ALT.label || "").trim();
  }
  const grid = document.getElementById("cb-grid"), st = document.getElementById("cb-status");
  if (!systems.length && !payload.polish_sf) {
    grid.innerHTML = '<div style="color:var(--ink-variant,#888)">Select a system and enter SF to compute the bid.</div>';
    return;
  }
  st.textContent = "computing…";
  try {
    const r = await TW.postJSON("/api/price", payload);
    renderBid(r); st.textContent = "";
    // The full response carries `alternate_full_bid` + `alternate` when an
    // alternate was priced — stash it so the proposal step can render it.
    state.computed_bid = r;
    state.alternate_computed_bid = r.alternate_full_bid ? r : null;
    TW.setState({ ...state, computed_bid: r, alternate_computed_bid: state.alternate_computed_bid });
  } catch (e) { st.textContent = "error"; }
}

function renderBid(r) {
  const fb = r.full_bid, rows = [];
  r.systems.forEach((s, i) => rows.push([`System ${i + 1}: ${s.system}`, s.material]));
  if (r.coves && r.coves.length) rows.push(["Cove", r.coves.reduce((a, c) => a + c.material, 0)]);
  if (r.polish) rows.push(["Polish", r.polish.material]);
  if (r.patch) rows.push(["Patch", r.patch]);
  if (r.extras_total) rows.push([`Extra materials (${(r.extras || []).length})`, r.extras_total]);
  rows.push([`Shipping + escalation (${Math.round((r.shipping_pct || 0) * 100)}%)`, r.shipping_escalation]);
  rows.push(["Material Total", r.material_total, true]);
  if (fb) {
    rows.push(["Install labor + burden", fb.install_labor + fb.labor_burden]);
    rows.push(["Tooling", fb.tooling]);
    rows.push([`GP markup (${Math.round(fb.gp_pct * 100)}%)`, fb.gp_markup]);
    rows.push(["Super/PTO + Soft costs", fb.superintendent_pto + fb.soft_costs]);
    rows.push(["Sales tax", fb.sales_tax]);
    rows.push(["KS remodel tax", fb.remodel_tax]);
    rows.push(["ENGINE REFERENCE TOTAL (proposal uses the sheet's Total Lump Sum)", fb.total_base_bid, true]);
  }
  // Alternate (recommended) system — a second priced option beside the base.
  const altRes = document.getElementById("alt-result");
  if (r.alternate_full_bid && r.alternate_full_bid.total_base_bid) {
    const albl = (r.alternate && r.alternate.label) || "Alternate system";
    rows.push([`ALTERNATE — ${albl}`, r.alternate_full_bid.total_base_bid, true]);
    if (altRes) altRes.textContent = `Alternate Total Base Bid: ${_cbFmt(r.alternate_full_bid.total_base_bid)}`;
  } else if (altRes) {
    altRes.textContent = "";
  }
  document.getElementById("cb-grid").innerHTML = rows.map(([l, v, bold]) =>
    `<div style="display:flex;justify-content:space-between;padding:3px 0;${bold ? 'font-weight:700;border-top:2px solid var(--treadwell-red,#c0392b);margin-top:3px;padding-top:5px' : ''}"><span>${l}</span><span>${_cbFmt(v)}</span></div>`
  ).join("");
}

// ── Extra materials (appendable manual qty × unit-price lines) ──────────
// Mirrors the sheet's spare "=B*C" rows (rows 23,27,28,32,33,39 → 6 native
// slots). Unlimited in the tool/proposal; on generate the first 6 fill the
// native rows and any overflow lumps into one line + a note.
const SHEET_SPARE_ROWS = 6;
let EXTRAS = Array.isArray(state.extras) ? state.extras.slice() : [];

function getExtras() {
  // Only lines with a label and a non-zero amount count.
  return EXTRAS
    .map(e => ({ label: (e.label || "").trim(), qty: _cbNum(e.qty), unit_price: _cbNum(e.unit_price) }))
    .filter(e => e.label && e.qty * e.unit_price !== 0);
}

function persistExtras() { state.extras = EXTRAS; TW.setState({ ...state, extras: EXTRAS }); }

function renderExtras() {
  const wrap = document.getElementById("cb-extras");
  document.getElementById("cb-extras-head").style.display = EXTRAS.length ? "grid" : "none";
  wrap.innerHTML = "";
  EXTRAS.forEach((e, i) => {
    const amt = _cbNum(e.qty) * _cbNum(e.unit_price);
    const row = document.createElement("div");
    row.style.cssText = "display:grid;grid-template-columns:1fr 70px 90px 90px 28px;gap:6px;align-items:center;margin-bottom:4px;";
    row.innerHTML =
      `<input type="text" data-k="label" placeholder="Material name" value="${(e.label || "").replace(/"/g, "&quot;")}" style="font-size:12.5px;padding:3px 6px;">
       <input type="number" data-k="qty" placeholder="0" value="${e.qty ?? ""}" style="font-size:12.5px;padding:3px 6px;text-align:right;">
       <input type="number" step="0.01" data-k="unit_price" placeholder="0.00" value="${e.unit_price ?? ""}" style="font-size:12.5px;padding:3px 6px;text-align:right;">
       <span style="text-align:right;font-size:12.5px;font-variant-numeric:tabular-nums;">${_cbFmt(amt)}</span>
       <button type="button" data-act="rm" title="Remove" style="cursor:pointer;border:none;background:none;color:var(--treadwell-red,#c0392b);font-size:15px;">×</button>`;
    row.querySelectorAll("input").forEach(inp => {
      inp.addEventListener("input", () => {
        EXTRAS[i][inp.dataset.k] = inp.value;
        // live-update just this row's amount, persist, recompute (debounced)
        row.children[3].textContent = _cbFmt(_cbNum(EXTRAS[i].qty) * _cbNum(EXTRAS[i].unit_price));
        persistExtras();
        clearTimeout(_cbTimer); _cbTimer = setTimeout(computeBid, 400);
      });
    });
    row.querySelector('[data-act="rm"]').addEventListener("click", () => {
      EXTRAS.splice(i, 1); persistExtras(); renderExtras(); computeBid();
    });
    wrap.appendChild(row);
  });
  const note = document.getElementById("cb-extras-note");
  if (EXTRAS.length > SHEET_SPARE_ROWS) {
    note.style.display = "block";
    note.textContent = `⚠ ${EXTRAS.length} lines — the estimate sheet has ${SHEET_SPARE_ROWS} spare material rows; extras beyond that are lumped into one "Misc materials" line in the .xlsx (all lines still itemized in the proposal).`;
  } else {
    note.style.display = "none";
  }
}

// Seed from the sheet's spare rows if the estimator already typed materials
// there (e.g. an imported draft) — read label/qty/price straight off the grid.
function seedExtrasFromSheet() {
  if (EXTRAS.length) return;   // user/draft data wins
  const SPARE = [23, 27, 28, 32, 33, 39];
  for (const r of SPARE) {
    const label = _cbCell(`Epoxy!A${r}`);
    if (!label || /^=/.test(label) || /^MATERIAL|Options|Sub Total|Discount/i.test(label)) continue;
    const qty = _cbNum(_cbCell(`Epoxy!B${r}`)), up = _cbNum(_cbCell(`Epoxy!C${r}`));
    if (label.trim() && (qty || up)) EXTRAS.push({ label: label.trim(), qty, unit_price: up });
  }
}

document.getElementById("cb-add-extra").addEventListener("click", () => {
  EXTRAS.push({ label: "", qty: "", unit_price: "" });
  persistExtras(); renderExtras();
  // focus the new row's name field
  const inputs = document.querySelectorAll("#cb-extras input[data-k='label']");
  if (inputs.length) inputs[inputs.length - 1].focus();
});

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
      PRICE_LINES.splice(i, 1); persistPriceLines(); renderPriceLines();
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

// ── Alternate (recommended) system selector ─────────────────────────────
let ALT = Object.assign({ system: "", sf: "", label: "" }, state.alternate || {});
function altActive() { return _cbRealSystem(ALT.system) && _cbNum(ALT.sf) > 0; }
function persistAlt() { state.alternate = ALT; TW.setState({ ...state, alternate: ALT }); }
function populateAltSystems(list) {
  const sys = document.getElementById("alt-system");
  if (!sys) return;
  const cur = ALT.system || "";
  sys.innerHTML = '<option value="">— none —</option>' +
    (list || []).map(n => `<option value="${String(n).replace(/"/g, "&quot;")}"${n === cur ? " selected" : ""}>${n}</option>`).join("");
}
function wireAlt() {
  const sys = document.getElementById("alt-system"),
        sf = document.getElementById("alt-sf"),
        lab = document.getElementById("alt-label");
  if (!sys) return;
  if (ALT.sf) sf.value = ALT.sf;
  if (ALT.label) lab.value = ALT.label;
  const recompute = () => {
    ALT.system = sys.value; ALT.sf = sf.value; ALT.label = lab.value; persistAlt();
    clearTimeout(_cbTimer); _cbTimer = setTimeout(computeBid, 400);
  };
  sys.addEventListener("change", recompute);
  sf.addEventListener("input", recompute);
  lab.addEventListener("input", () => { ALT.label = lab.value; persistAlt(); });
}

document.getElementById("cb-bulk").addEventListener("change", e => {
  // mirror Kyle's D41 toggle into the grid so it flows to the generated sheet
  cellValues["Epoxy!D41"] = e.target.checked ? "BULK Discount ON" : "Bulk Discount OFF";
  state.cb_bulk = e.target.checked;
  computeBid();
});
// recompute when any grid selection / SF changes (debounced)
document.getElementById("sheet-grid").addEventListener("change", () => {
  refreshSystemName();
  clearTimeout(_cbTimer); _cbTimer = setTimeout(computeBid, 400);
});

init();
if (state.cb_bulk) document.getElementById("cb-bulk").checked = true;

// Collapsible Computed Bid → the worksheet gets the rest of the window.
// Default collapsed (headline totals stay in the total-bar); choice is remembered.
(function initCbCollapse(){
  const panel  = document.getElementById("computed-bid");
  const header = document.getElementById("cb-header");
  const caret  = document.getElementById("cb-caret");
  if (!panel || !header) return;
  let collapsed = true;
  try { const v = localStorage.getItem("tw_cb_collapsed"); if (v !== null) collapsed = v === "1"; } catch {}
  const apply = () => {
    panel.classList.toggle("cb-collapsed", collapsed);
    if (caret) caret.textContent = collapsed ? "▸ Show breakdown" : "▾ Hide";
    if (window.__twCbApplySaved) window.__twCbApplySaved();   // re-apply dragged height / hide resizer
  };
  apply();
  header.addEventListener("click", (e) => {
    // Clicks inside the bulk-discount label toggle the checkbox, not the panel
    // (replaces the element's former inline onclick="event.stopPropagation()").
    if (e.target.closest && e.target.closest("#cb-bulk-label")) return;
    collapsed = !collapsed;
    try { localStorage.setItem("tw_cb_collapsed", collapsed ? "1" : "0"); } catch {}
    apply();
  });
})();

// Drag the #cb-resizer to resize the WORKSHEET; the Computed Bid panel flexes to
// fill whatever's left (and its body scrolls), so nothing runs off-screen. We
// size the worksheet (not the panel) because the panel's content is unbounded.
(function initCbResize(){
  const panel = document.getElementById("computed-bid");
  const vp = document.querySelector(".xl-viewport");
  const rez = document.getElementById("cb-resizer");
  if (!panel || !vp || !rez) return;
  const KEY = "tw_ws_height";   // persisted WORKSHEET height (expanded mode)
  const tbEl = document.getElementById("total-bar");
  // Cap the worksheet at the actual space available between it and the bottom of
  // the window, reserving room for the total-bar, the handle, and a >=90px panel —
  // so dragging the worksheet bigger can never push the bid panel off-screen.
  function maxWs(){
    const vpTop = vp.getBoundingClientRect().top;
    const tbH = tbEl ? tbEl.getBoundingClientRect().height : 0;
    const rezH = rez.getBoundingClientRect().height || 10;
    return Math.max(160, Math.floor(window.innerHeight - vpTop - tbH - rezH - 90));
  }
  const clamp = h => Math.max(120, Math.min(h, maxWs()));
  function applySaved(){
    if (panel.classList.contains("cb-collapsed")) {
      // Collapsed: worksheet fills the window (back to flex:1), no resizer.
      vp.style.height = ""; vp.style.flex = ""; rez.style.display = "none"; return;
    }
    rez.style.display = "";
    // Expanded: fix the worksheet height (default ≈ half the window); the panel
    // flexes into the remainder and scrolls.
    const saved = parseInt(localStorage.getItem(KEY) || "", 10);
    vp.style.flex = "0 0 auto";
    vp.style.height = clamp(saved || Math.round(window.innerHeight * 0.50)) + "px";
  }
  window.__twCbApplySaved = applySaved;
  let startY = 0, startH = 0, dragging = false;
  function onMove(e){
    if (!dragging) return;
    // Drag DOWN (clientY increases) => bigger worksheet / smaller bid panel.
    vp.style.height = clamp(startH + (e.clientY - startY)) + "px";
    e.preventDefault();
  }
  function onUp(){
    if (!dragging) return;
    dragging = false; document.body.style.userSelect = "";
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onUp);
    try { localStorage.setItem(KEY, String(Math.round(vp.getBoundingClientRect().height))); } catch {}
  }
  rez.addEventListener("pointerdown", e => {
    if (panel.classList.contains("cb-collapsed")) return;
    dragging = true; startY = e.clientY; startH = vp.getBoundingClientRect().height;
    document.body.style.userSelect = "none"; e.preventDefault();
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  });
  applySaved();
})();
// Load the recipe-known system names so the panel only counts real picks,
// then compute once the grid + cellValues have hydrated. Wait for the auth
// token first (gated endpoint) + send it, else it 401s and VALID_SYSTEMS is empty.
(window.TWAuth && window.TWAuth.ready ? window.TWAuth.ready : Promise.resolve())
  .then(() => fetch(TW.absoluteUrl("/api/pricing/systems"), { headers: TW.authHeaders() }))
  .then(r => r.json())
  .then(d => { const list = (d.systems || d.epoxy || []); list.forEach(n => VALID_SYSTEMS.add(n)); populateAltSystems(list); })
  .catch(() => {})
  .finally(() => setTimeout(() => {
    seedExtrasFromSheet(); renderExtras();
    renderPriceLines(); wireAlt();
    refreshSystemName();
    computeBid();
  }, 1200));

