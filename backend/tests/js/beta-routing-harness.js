"use strict";
/* Run the REAL intake page script and the REAL projects-page router, and report where they went.
 *
 * WHY EXECUTED, NOT GREPPED. Everything interesting about a second button next to an existing one
 * is invisible to a source assertion:
 *
 *   * Both handlers navigate. A grep proves both strings are present in the file; it cannot tell
 *     you which handler holds which one. Crossing the wires — beta → /estimate-review.html,
 *     submit → /polish-intake.html — leaves every string in place and every grep green, and it is
 *     the single most likely refactor mistake here.
 *   * The beta handler carries its own copy of the state composition. Nothing in the source says
 *     the two copies agree; running both on ONE filled form and comparing the saved blobs does.
 *   * `betaBtn` could be a typo'd id, in which case it is `null` for the life of the page and the
 *     button silently does nothing. This harness only creates a node for an id that really exists
 *     in index.html, so a typo shows up as "no listener was ever wired".
 *   * The visibility rule lives inside syncScopeToWorkType, which also hides quantity fields. A
 *     test that re-implements "polish → show" would agree with itself. This one flips the real
 *     radios, fires the real change listener, and reads the real style off the node.
 *   * `open()` in projects.js branches on a flag; a swapped branch sends every SPREADSHEET bid to
 *     the beta intake. Source text cannot see which way round it is.
 *
 * The form serialiser, the ?d= builder and the form binder are LIFTED OUT OF shared.js rather
 * than faked, so `city_state`, the number coercion and the draft id are the page's own behaviour.
 * Only the network-ish edges are stubs: TW.getState/setState (localStorage + the server) and
 * window.location.
 *
 * Usage: node beta-routing-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
// Normalised on read: these harnesses match the pages' source text, and git hands the files out
// with CRLF on a Windows checkout. See the note in polish-estimate-harness.js.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const indexJs = read(path.join(ROOT, "js", "index.js"));
const indexHtml = read(path.join(ROOT, "index.html"));
const sharedJs = read(path.join(ROOT, "shared.js"));
const projectsJs = read(path.join(ROOT, "js", "projects.js"));

const DRAFT_ID = "d1e2f3a4";

// ── lifting real code out of the page files ──────────────────────────────────
/** Balance braces from `from` and return the source through the matching close. */
function balanced(src, from, what) {
  let depth = 0;
  for (let j = from; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(from, j + 1);
  }
  throw new Error("unbalanced braces reading " + what);
}

/** A named function out of shared.js's IIFE (two-space indent). */
function sharedFn(name) {
  const m = new RegExp("\\n  function " + name + "\\s*\\(").exec(sharedJs);
  if (!m) throw new Error(name + "() is gone from shared.js — rewrite this harness, don't stub it");
  const i = sharedJs.indexOf("{", m.index + m[0].length - 1);
  return sharedJs.slice(m.index, i) + balanced(sharedJs, i, name);
}

/** The `const open = (id) => { … };` router out of projects.js's wireList IIFE. */
function liftOpen() {
  const m = /\n\s*const open = \(id\) => \{/.exec(projectsJs);
  if (!m) {
    throw new Error("projects.js no longer declares `const open = (id) => { … }` — it is what "
      + "every card and row navigates through. Rewrite this harness, do not stub it.");
  }
  const i = m.index + m[0].length - 1;
  return "const open = (id) => " + balanced(projectsJs, i, "open") + ";";
}

// The real serialiser + the real ?d= builder. getDraftId is the one thing stubbed inside the
// lifted scope (it reads localStorage in the browser).
const twScope = new Function("DRAFT_ID", `
  "use strict";
  function getDraftId() { return DRAFT_ID; }
  ${sharedFn("readForm")}
  ${sharedFn("writeForm")}
  ${sharedFn("withDraft")}
  return { readForm: readForm, writeForm: writeForm, withDraft: withDraft };
`)(DRAFT_ID);

// ── a DOM stub, only as much as index.js touches ─────────────────────────────
function parseStyle(attrs) {
  const out = {};
  const m = /style="([^"]*)"/.exec(attrs || "");
  if (!m) return out;
  m[1].split(";").forEach(function (bit) {
    const kv = bit.split(":");
    if (kv.length === 2) out[kv[0].trim()] = kv[1].trim();
  });
  return out;
}

function mkEl(props) {
  const el = {
    style: {},
    listeners: {},
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    contains() { return false; },
    classList: { add() {}, remove() {} },
    getAttribute() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    innerHTML: "",
    value: "",
  };
  return Object.assign(el, props || {});
}

/** One form field, built from the tag as it appears in the real markup. */
function mkField(attrs, tag) {
  const name = (/name="([^"]*)"/.exec(attrs) || [])[1];
  const type = (/type="([^"]*)"/.exec(attrs) || [])[1]
    || (tag === "textarea" ? "textarea" : tag === "select" ? "select-one" : "text");
  return mkEl({
    name: name,
    type: type,
    id: (/id="([^"]*)"/.exec(attrs) || [])[1] || null,
    value: (/value="([^"]*)"/.exec(attrs) || [])[1] || "",
    checked: /(^|\s)checked(\s|$|=)/.test(attrs),
    required: /(^|\s)required(\s|$|=)/.test(attrs),
    _rendered: false,
  });
}

/** Every named field in index.html, in document order — the browser's form.elements. */
function fieldsFromMarkup(html) {
  const out = [];
  const re = /<(input|select|textarea)\b([^>]*?)\/?>/gi;
  let m;
  while ((m = re.exec(html))) {
    const f = mkField(m[2], m[1].toLowerCase());
    if (f.name) out.push(f);
  }
  return out;
}

/** The tag that carries id="X" in index.html, or null when the page has no such element. */
function attrsOfId(html, id) {
  const at = html.indexOf('id="' + id + '"');
  if (at === -1) return null;
  return html.slice(html.lastIndexOf("<", at), html.indexOf(">", at) + 1);
}

/** Turn renderSystems' output into the object graph syncScopeToWorkType walks. */
function parseSystems(html) {
  const inputs = [], labels = [], rows = [];
  html.split('<div class="row">').slice(1).forEach(function (chunk) {
    const inner = chunk.split("</div>")[0];
    const rowLabels = [];
    const lre = /<label data-scope="([^"]*)">([\s\S]*?)<\/label>/g;
    let lm;
    while ((lm = lre.exec(inner))) {
      const scope = lm[1];
      const lab = mkEl({ getAttribute: (k) => (k === "data-scope" ? scope : null) });
      rowLabels.push(lab);
      labels.push(lab);
      const im = /<input([^>]*)>/.exec(lm[2]);
      if (im) {
        const f = mkField(im[1], "input");
        f._rendered = true;
        inputs.push(f);
      }
    }
    rows.push(mkEl({ querySelectorAll: (sel) => (sel === "[data-scope]" ? rowLabels : []) }));
  });
  return { inputs: inputs, labels: labels, rows: rows };
}

// `seed` is the draft the page loads INTO -- how a project coming back through Back, or one
// the AI autofill has already written flags for, actually arrives.
function build(seed) {
  const NAV = [];
  const SAVES = [];
  const STATE = JSON.parse(JSON.stringify(seed || {}));
  const nodes = {};
  const flags = { valid: true, reportValidityCalls: 0 };

  const fields = fieldsFromMarkup(indexHtml);
  const radios = fields.filter((f) => f.name === "work_type");
  const byName = (n) => form.elements.filter((f) => f.name === n)[0];

  const form = mkEl({ id: "intake-form" });
  form.elements = fields;
  form.reportValidity = function () {
    flags.reportValidityCalls++;
    return flags.valid;
  };
  form.querySelector = function (sel) {
    if (sel === "[name='work_type']:checked") return radios.filter((r) => r.checked)[0] || null;
    if (sel === "[name='bid_date']") return byName("bid_date");
    throw new Error("form.querySelector: unexpected selector " + sel + " — teach the harness");
  };
  form.querySelectorAll = function (sel) {
    if (sel === "[name='work_type']") return radios;
    throw new Error("form.querySelectorAll: unexpected selector " + sel + " — teach the harness");
  };
  nodes["intake-form"] = form;

  // #systems-container: renderSystems writes it, syncScopeToWorkType reads it back. The inputs it
  // renders join form.elements, exactly as they would in a real form.
  const systems = mkEl({ id: "systems-container" });
  let parsed = { inputs: [], labels: [], rows: [] };
  let systemsHtml = "";
  Object.defineProperty(systems, "innerHTML", {
    get() { return systemsHtml; },
    set(v) {
      systemsHtml = v;
      parsed = parseSystems(v);
      form.elements = form.elements.filter((f) => !f._rendered).concat(parsed.inputs);
    },
  });
  systems.querySelectorAll = function (sel) {
    if (sel === "input[name]") return parsed.inputs;
    if (sel === "[data-scope]") return parsed.labels;
    if (sel === ".row") return parsed.rows;
    throw new Error("systems-container: unexpected selector " + sel + " — teach the harness");
  };
  nodes["systems-container"] = systems;

  // #conditions: the job-condition toggles. Registered up front for the same reason
  // #systems-container is -- index.js takes the node once, at load, and every later
  // render goes through this setter.
  const condBox = mkEl({ id: "conditions" });
  let condSwitches = [];
  let condHtml = "";
  Object.defineProperty(condBox, "innerHTML", {
    get() { return condHtml; },
    set(v) {
      condHtml = v;
      condSwitches = parseSwitches(v);
      // Reachable by id, because toggleCondition() puts focus back on the switch it just
      // re-rendered -- a real DOM would hand back the NEW node, and so does this.
      condSwitches.forEach((sw) => { nodes[sw.id] = sw; });
    },
  });
  nodes["conditions"] = condBox;


  /** The switches js/index.js renders into #conditions, as stub nodes.
 *
 *  Parsed out of the emitted HTML rather than mirrored from CONDITIONS, so "renders but
 *  binds nothing", "renders the wrong count for this work type" and "says on when it is
 *  off" are all visible. Each node answers closest("[data-cond]") with itself, which is
 *  how the page's delegated click and keydown find it.
 */
function parseSwitches(html) {
  const out = [];
  const parts = String(html).split('<div class="sw');
  for (let i = 1; i < parts.length; i++) {
    const chunk = parts[i];
    const key = (/data-cond="([^"]*)"/.exec(chunk) || [])[1];
    if (!key) continue;
    const head = chunk.slice(0, chunk.indexOf(">"));
    const sw = mkEl({
      id: "cond-" + key,
      key: key,
      on: / on\b/.test(head) || /^ on/.test(head),
      inert: /\binert\b/.test(head),
      ariaChecked: (/aria-checked="([^"]*)"/.exec(chunk) || [])[1],
      role: (/role="([^"]*)"/.exec(chunk) || [])[1],
      tabindex: (/tabindex="([^"]*)"/.exec(chunk) || [])[1],
      hasTrack: /<span class="track">/.test(chunk),
      label: (/<span class="t">([^<]*)</.exec(chunk) || [])[1] || "",
      why: (/<span class="c">([^<]*)</.exec(chunk) || [])[1] || "",
      focused: false,
    });
    sw.closest = (sel) => (sel === "[data-cond]" ? sw : null);
    sw.getAttribute = (a) => (a === "data-cond" ? key : null);
    sw.focus = () => { sw.focused = true; };
    out.push(sw);
  }
  return out;
}

const documentStub = {
    listeners: {},
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    getElementById(id) {
      if (nodes[id]) return nodes[id];
      const attrs = attrsOfId(indexHtml, id);
      // NOT invented. An id the page does not carry has to come back null here, or a typo'd
      // getElementById would look wired in the harness and be dead in the browser.
      if (attrs === null) return null;
      nodes[id] = mkEl({ id: id, style: parseStyle(attrs), _attrs: attrs });
      return nodes[id];
    },
  };
  const windowStub = { location: { assign: (url) => NAV.push(url) } };
  const TW = {
    readForm: twScope.readForm,
    writeForm: twScope.writeForm,
    withDraft: twScope.withDraft,
    getState: () => STATE,
    setState: (partial) => { SAVES.push(JSON.parse(JSON.stringify(partial))); Object.assign(STATE, partial); },
  };

  // THE REAL PAGE SCRIPT, top to bottom. An unbound identifier anywhere in it throws here.
  new Function("document", "window", "TW", indexJs)(documentStub, windowStub, TW);

  function fire(el, type, ev) {
    const fns = (el.listeners || {})[type] || [];
    fns.forEach((fn) => fn(ev || { preventDefault() {}, target: el }));
    return fns.length;
  }
  function setWorkType(wt) {
    const target = radios.filter((r) => r.value === wt)[0];
    if (!target) throw new Error("no work_type radio with value " + wt);
    radios.forEach((r) => { r.checked = r === target; });
    fire(target, "change");            // only the clicked radio fires change in a browser
  }
  function fill(vals) {
    Object.keys(vals).forEach(function (k) {
      const f = byName(k);
      if (!f) throw new Error("index.html has no field named " + k);
      f.value = vals[k];
    });
  }

  /** The switches on screen right now, freshly re-read after every render. */
  function switches() { return condSwitches; }
  function switchFor(key) { return condSwitches.filter((s) => s.key === key)[0] || null; }
  /** A key press ON a focused switch, the way a keyboard user reaches one. */
  function press(key, k) {
    const sw = switchFor(key);
    if (!sw) throw new Error("no switch for " + key);
    let prevented = false;
    const fns = (condBox.listeners || {}).keydown || [];
    fns.forEach((fn) => fn({ key: k, target: sw, preventDefault() { prevented = true; } }));
    return { handlers: fns.length, prevented: prevented };
  }
  function clickSwitch(key) {
    const sw = switchFor(key);
    if (!sw) throw new Error("no switch for " + key);
    return fire(condBox, "click", { target: sw, preventDefault() {} });
  }
  return { NAV, SAVES, STATE, nodes, flags, form, radios, systems, documentStub,
           condBox, switches, switchFor, press, clickSwitch,
           fire, setWorkType, fill, byName };
}

const out = {};

// ── boot: is there a button at all, and is it wired? ─────────────────────────
{
  const b = build();
  const beta = b.nodes["beta-continue"];
  out.boot = {
    buttonIsInTheMarkup: !!beta,
    // Straight off the markup's style attribute: the button must not flash on an epoxy job
    // before any script runs.
    shipsHidden: !!beta && beta.style.display === "none",
    typeIsButton: /type="button"/.test((beta && beta._attrs) || ""),
    // Secondary, not a second primary — and the class has to be one styles.css defines.
    className: /class="([^"]*)"/.exec((beta && beta._attrs) || "") ?
      /class="([^"]*)"/.exec(beta._attrs)[1] : null,
    clickListeners: ((beta && beta.listeners.click) || []).length,
    submitListeners: ((b.form.listeners || {}).submit || []).length,
    label: (function () {
      if (!beta) return null;
      const at = indexHtml.indexOf('id="beta-continue"');
      const open = indexHtml.indexOf(">", at);
      const close = indexHtml.indexOf("</button>", open);
      return indexHtml.slice(open + 1, close);
    })(),
  };
}

// ── the visibility rule, driven through the real syncScopeToWorkType ─────────
{
  const b = build();
  const beta = b.nodes["beta-continue"];
  const gyp = b.nodes["gyp-sf-container"];
  out.visibility = {};
  out.liveIntakeUnchanged = {};
  ["epoxy", "polish", "combo", "gyp"].forEach(function (wt) {
    b.setWorkType(wt);
    out.visibility[wt] = beta.style.display;
    // Evidence that the same function still does its old job for the live path: gyp's buckets
    // and the per-work-type quantity scopes.
    out.liveIntakeUnchanged[wt] = {
      gypBuckets: gyp.style.display,
      systems: b.systems.style.display,
      shownScopes: b.systems.querySelectorAll("[data-scope]")
        .filter((l) => l.style.display !== "none")
        .map((l) => l.getAttribute("data-scope"))
        .filter((s, i, a) => a.indexOf(s) === i),
    };
  });
  // Hidden, never removed: the same fields (and the same button) come back on switching back.
  b.setWorkType("polish");
  out.visibility.polishAgainAfterEpoxy = beta.style.display;
  out.visibility.buttonStillWired = (beta.listeners.click || []).length;
}

// ── where each handler goes, and what each one saves ────────────────────────
const PROJECT = {
  project_name: "Nearman Creek Polish",
  address: "1200 Kaw Dr",
  city: "Overland Park",
  state: "ks",                 // lower case on purpose: city_state must upper it
  zip: "66210",
  architect: "",
  contact_name: "Dave",
  contact_email: "dave@example.com",
  polish_sf: "2875",
};

function runHandler(which) {
  const b = build();
  b.setWorkType("polish");
  b.fill(PROJECT);
  if (which === "beta") b.fire(b.nodes["beta-continue"], "click");
  else b.fire(b.form, "submit");
  return b;
}

{
  const beta = runHandler("beta");
  const submit = runHandler("submit");
  out.nav = {
    beta: beta.NAV,
    submit: submit.NAV,
  };
  out.saves = {
    betaCount: beta.SAVES.length,
    submitCount: submit.SAVES.length,
    beta: beta.SAVES[0] || null,
    submit: submit.SAVES[0] || null,
  };
  // Two copies of one composition. Compared key for key so a change to either one that is not
  // made to the other fails here rather than in production.
  const norm = (o) => JSON.stringify(Object.keys(o || {}).sort().map((k) => [k, o[k]]));
  out.saves.identical = norm(beta.SAVES[0]) === norm(submit.SAVES[0]);
  out.saves.betaOnlyKeys = Object.keys(beta.SAVES[0] || {})
    .filter((k) => !(k in (submit.SAVES[0] || {})));
  out.saves.submitOnlyKeys = Object.keys(submit.SAVES[0] || {})
    .filter((k) => !(k in (beta.SAVES[0] || {})));
}

// ── the beta button is not a way around the required fields ─────────────────
{
  const b = build();
  b.setWorkType("polish");
  b.fill(PROJECT);
  b.flags.valid = false;                 // as if bid_date / project_name were empty
  b.fire(b.nodes["beta-continue"], "click");
  out.validation = {
    asked: b.flags.reportValidityCalls,
    navigated: b.NAV.length,
    saved: b.SAVES.length,
  };
}

// ── EXECUTED: the projects-page router ──────────────────────────────────────
{
  const navs = [];
  const list = [
    { id: "beta-1", polish_beta: true },
    { id: "sheet-1", polish_beta: false },
    { id: "legacy-1" },                                  // no flag at all (older rows)
    { id: "beta 2", polish_beta: true },                 // an id that needs encoding
  ];
  const open = new Function("ALL_PROJECTS", "window", liftOpen() + "\nreturn open;")(
    list, { location: { assign: (u) => navs.push(u) } });
  // Ids reach open() already encodeURIComponent'd — that is what the card/row markup carries.
  open(encodeURIComponent("beta-1"));
  open(encodeURIComponent("sheet-1"));
  open(encodeURIComponent("legacy-1"));
  open(encodeURIComponent("beta 2"));
  open(encodeURIComponent("never-heard-of-it"));
  out.projectsOpen = {
    beta: navs[0], sheet: navs[1], legacy: navs[2], encodedBeta: navs[3], unknown: navs[4],
    count: navs.length,
  };
}

// == EXECUTED: the job-condition toggles ====================================
// Every claim here is about a DOM effect or a written literal, so none of it is reachable by
// reading js/index.js. Specifically:
//
//   * "Renders as toggles" is a shape, and the shape is built by string concatenation at
//     runtime. A grep for `class="sw"` cannot tell you the switch got a track, an
//     aria-checked, or a data-cond the listener can find.
//   * The literals are the whole point. Epoxy!D41 is compared against V136/V137 by six
//     formulas, and any other casing takes the OFF branch in silence -- so the assertion has
//     to read the value that lands in cell_values, not the constant in the source.
//   * `reno` off must write "New". A blank Epoxy!B10 makes IF(B10="New",0.05,0.15) take the
//     RENO branch, tripling the patch rate with nothing on screen. Only running the writer
//     shows whether "off" means "No" or means absent.
//   * Scope is a live filter over a live radio. Re-implementing "polish shows dye" would just
//     agree with itself; this flips the real radio and counts the real switches.
//   * Space and Enter are a listener that either exists or does not. The beta's switches
//     carried role="switch" tabindex="0" and bound click only, so they announced themselves
//     as switches and ignored both keys -- exactly the bug a source read misses.
{
  const cells = (b) => (b.STATE.cell_values || {});

  // Which questions each work type is asked. Read off the rendered nodes, in order.
  out.conditions = { byWorkType: {}, shape: null, defaults: null };
  ["epoxy", "polish", "combo", "gyp"].forEach((wt) => {
    const b = build();
    b.setWorkType(wt);
    out.conditions.byWorkType[wt] = b.switches().map((s) => s.key);
  });

  // The switch shape, and whether the labels say what the toggle does.
  {
    const b = build();
    b.setWorkType("polish");
    const dye = b.switchFor("dye");
    out.conditions.shape = {
      role: dye.role,
      tabindex: dye.tabindex,
      ariaChecked: dye.ariaChecked,
      hasTrack: dye.hasTrack,
      label: dye.label,
      whyNonEmpty: b.switches().every((s) => s.why.length > 10),
      allHaveTrack: b.switches().every((s) => s.hasTrack),
      allHaveRole: b.switches().every((s) => s.role === "switch"),
      allFocusable: b.switches().every((s) => s.tabindex === "0"),
    };
    // Defaults, on screen. joint_filler MUST be on: Kyle's template ships Polish!E29 = "Yes",
    // so a default of off would quietly remove filler from jobs that get it today.
    out.conditions.defaults = {};
    b.switches().forEach((s) => { out.conditions.defaults[s.key] = s.on; });
  }

  // Nothing is written until something is touched -- a work type alone must not create a row.
  {
    const b = build();
    b.setWorkType("polish");
    out.conditions.savesOnWorkTypeAlone = b.SAVES.length;
    out.conditions.cellsOnWorkTypeAlone = Object.keys(cells(b)).length;
  }

  // A flip, and the literals it lands. Both tabs for local; Epoxy only for the three formulas.
  {
    const b = build();
    b.setWorkType("polish");
    b.clickSwitch("dye");
    out.conditions.afterDyeOn = cells(b);
    out.conditions.dyeSaves = b.SAVES.length;
    out.conditions.dyeSwitchNowOn = b.switchFor("dye").on;
    out.conditions.dyeAriaNowTrue = b.switchFor("dye").ariaChecked;
  }

  // reno OFF is an explicit "New", not an absent key. The trap this whole section exists for.
  {
    const b = build();
    b.setWorkType("polish");
    b.clickSwitch("reno");                       // on  -> "Reno"
    const on = cells(b)["Epoxy!B10"];
    const onPolish = cells(b)["Polish!B10"];     // read WHILE on -- both tabs carry the word
    b.clickSwitch("reno");                       // off -> "New", NOT deleted
    const off = cells(b);
    out.conditions.reno = {
      on: on,
      onPolish: onPolish,
      off: off["Epoxy!B10"],
      offPolish: off["Polish!B10"],
      offIsPresent: "Epoxy!B10" in off,
      bothTabs: ("Epoxy!B10" in off) && ("Polish!B10" in off),
    };
  }

  // The bulk discount, byte for byte against the sheet's own V136/V137.
  {
    const b = build();
    b.setWorkType("epoxy");
    b.clickSwitch("bulk_discount");
    out.conditions.bulkOn = cells(b)["Epoxy!D41"];
    b.clickSwitch("bulk_discount");
    out.conditions.bulkOff = cells(b)["Epoxy!D41"];
  }

  // Switching work type drops the questions that no longer apply -- a polish job retyped as
  // epoxy must not carry Polish!E25 = "Yes" into a bid with no polish in it.
  {
    const b = build();
    b.setWorkType("polish");
    b.clickSwitch("dye");
    b.clickSwitch("joint_filler");               // -> "No"
    const before = Object.keys(cells(b)).slice().sort();
    b.setWorkType("epoxy");
    const after = cells(b);
    out.conditions.scopeCleanup = {
      before: before,
      after: Object.keys(after).sort(),
      polishGone: !("Polish!E25" in after) && !("Polish!E29" in after),
      epoxyKept: after["Epoxy!B4"],
    };
  }

  // remove_existing_jf is inert while joint_filler is off, and SAYS so rather than vanishing.
  {
    const b = build();
    b.setWorkType("polish");
    const before = b.switchFor("remove_existing_jf");
    b.clickSwitch("joint_filler");               // default on -> off
    const after = b.switchFor("remove_existing_jf");
    out.conditions.inert = {
      beforeInert: before.inert,
      afterInert: after.inert,
      afterStillRendered: !!after,
      afterWhy: after.why,
    };
  }

  // KEYBOARD. Space and Enter operate a focused switch; a plain letter does not.
  {
    const b = build();
    b.setWorkType("polish");
    const space = b.press("dye", " ");
    const onAfterSpace = b.switchFor("dye").on;
    const cellAfterSpace = cells(b)["Polish!E25"];   // read here: the sequence continues below
    const savesAfterSpace = b.SAVES.length;
    const enter = b.press("dye", "Enter");
    const onAfterEnter = b.switchFor("dye").on;
    const letter = b.press("dye", "a");
    out.conditions.keyboard = {
      handlers: space.handlers,
      spacePrevented: space.prevented,
      onAfterSpace: onAfterSpace,
      cellAfterSpace: cellAfterSpace,
      savesAfterSpace: savesAfterSpace,
      enterPrevented: enter.prevented,
      onAfterEnter: onAfterEnter,
      letterPrevented: letter.prevented,
      onAfterLetter: b.switchFor("dye").on,
    };
  }

  // Focus survives the re-render. toggleCondition() rebuilds the whole box, so without the
  // refocus a keyboard user is thrown back to the top of the page on every press.
  {
    const b = build();
    b.setWorkType("polish");
    b.press("dye", " ");
    out.conditions.focusKept = b.switchFor("dye").focused;
  }

  // HYDRATION. A draft arriving with these cells already set -- by Back, by the estimate grid,
  // or by the AI autofill, which has written these same keys since it shipped -- shows what the
  // sheet says, not what this page's defaults say.
  {
    const b = build({ cell_values: {
      "Epoxy!B6": "No",                  // taxable defaults TRUE; the draft says otherwise
      "Polish!E25": "Yes",               // dye defaults false
      "Polish!E29": "No",                // joint filler defaults true
      "Epoxy!B4": "no",                  // lower case, as a human might type into the grid
    } });
    b.setWorkType("polish");
    const read = {};
    b.switches().forEach((s) => { read[s.key] = s.on; });
    out.conditions.hydrated = read;
    out.conditions.hydrateSaves = b.SAVES.length;
  }

  // A draft that already carries one of these cells DOES get cleaned up on a work-type change,
  // because leaving a stale out-of-scope flag behind is the bug the cleanup exists for.
  {
    const b = build({ cell_values: { "Polish!E25": "Yes" } });
    b.setWorkType("epoxy");
    out.conditions.seededCleanup = {
      saves: b.SAVES.length,
      dyeGone: !("Polish!E25" in (b.STATE.cell_values || {})),
    };
  }

  // Unrelated cell_values entries survive a flip. cell_values is shared with the autofill and
  // with every cell the estimator edited by hand on the grid; a fresh object would drop them.
  {
    const b = build({ cell_values: { "Epoxy!E20": 4200, "Polish!E19": 3100 } });
    b.setWorkType("polish");
    b.clickSwitch("dye");
    const cv = cells(b);
    out.conditions.merged = { "Epoxy!E20": cv["Epoxy!E20"], "Polish!E19": cv["Polish!E19"] };
  }

  // A data-cond nobody rendered invents nothing. Guards against a stale id in the markup
  // writing a cell for a condition this work type was never asked.
  {
    const b = build();
    b.setWorkType("epoxy");
    const fake = { closest: () => fake, getAttribute: () => "dye" };
    b.fire(b.condBox, "click", { target: fake, preventDefault() {} });
    out.conditions.strayCond = {
      saves: b.SAVES.length,
      dyeWritten: "Polish!E25" in (b.STATE.cell_values || {}),
    };
  }
}

console.log(JSON.stringify(out));
