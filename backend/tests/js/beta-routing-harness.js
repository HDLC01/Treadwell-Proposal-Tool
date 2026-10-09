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
const countyJs = read(path.join(ROOT, "js", "county-picker.js"));
const addressJs = read(path.join(ROOT, "js", "address-lookup.js"));

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

/** The `const STAMP = "...";` line out of shared.js's IIFE: the key every blob is stamped under. */
function sharedStampLine() {
  const m = /\n  const STAMP = "[^"]*";/.exec(sharedJs);
  if (!m) throw new Error("STAMP is gone from shared.js. Rewrite this harness, don't stub it");
  return m[0].trim();
}

// The real serialiser + the real ?d= builder, and the real v2 predicate and ownership check the
// index.js guards ask (isV2Draft is self-contained; isThisDraft reads the stamp and the draft id).
// getDraftId is the one thing stubbed inside the lifted scope (it reads localStorage in the browser).
const twScope = new Function("DRAFT_ID", `
  "use strict";
  function getDraftId() { return DRAFT_ID; }
  ${sharedStampLine()}
  ${sharedFn("readForm")}
  ${sharedFn("writeForm")}
  ${sharedFn("withDraft")}
  ${sharedFn("isV2Draft")}
  ${sharedFn("isThisDraft")}
  return { readForm: readForm, writeForm: writeForm, withDraft: withDraft,
           isV2Draft: isV2Draft, isThisDraft: isThisDraft };
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
//
// `pageOpts.search` is the query string the page is loaded with ("?d=d1e2f3a4&edit=1"); it is empty
// unless a scenario says otherwise, which is how every scenario but the v2 routing ones loads.
function build(seed, countyOpts, condOpts, pageOpts) {
  const NAV = [];
  const REPLACED = [];
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
  // ── the county picker's nodes ──────────────────────────────────────────────
  //
  // Its ids are checked against the real markup first. The picker takes every one of them with
  // getElementById, so a rename in index.html turns the whole control into a set of no-ops that
  // throws nothing and logs nothing — the failure this harness must not be able to sleep through.
  ["county-field", "county-input", "county-results", "county-clear", "county-note"]
    .forEach(function (id) {
      if (attrsOfId(indexHtml, id) === null) {
        throw new Error(id + " is gone from index.html, but js/county-picker.js reaches for it "
          + "by id — fix the markup or rewrite this harness; do not stub the id.");
      }
    });

  // #county-results is registered up front with a parsing setter for the same reason #conditions
  // is: the module writes rows into it and then reads them back by id.
  const results = mkEl({ id: "county-results", hidden: true });
  let countyRows = [];
  let resultsHtml = "";
  Object.defineProperty(results, "innerHTML", {
    get() { return resultsHtml; },
    set(v) {
      resultsHtml = v;
      countyRows = parseCountyRows(v, results);
      countyRows.forEach((r) => { nodes[r.id] = r; });
    },
  });
  results.closest = (sel) => (sel === "[data-county-keep]" ? results : null);
  nodes["county-results"] = results;

  const countyInput = mkEl({ id: "county-input", value: "" });
  countyInput.closest = (sel) => (sel === "[data-county-keep]" ? countyInput : null);
  nodes["county-input"] = countyInput;

  // The reference fetch. Recorded rather than counted so a second, wasteful load would show.
  const countyFetches = [];
  const co = countyOpts || {};
  const fetchStub = async function (url) {
    countyFetches.push(String(url));
    // A reference table is not the draft: the module has to survive losing it, so the harness
    // has to be able to take it away.
    if (co.fail) throw new Error("network");
    return { json: async () => ({
      counties: co.rows === undefined ? COUNTY_TABLE : co.rows,
      ks_state_rate: co.ksRate === undefined ? 0.065 : co.ksRate,
    }) };
  };


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

// The reference table the county picker fetches. Six rows, shaped exactly like
// reference_tax.list_tax_areas(): a `kind`, a combined `rate`, a `remodel_rate` that is null on
// the Missouri row because Missouri remodel labor is generally exempt, and the `notes` field the
// module's own filter searches (which is where the city names live).
const COUNTY_TABLE = [
  // COPIED FROM THE LIVE TABLE, keys and all, on 2026-09-03. Three shapes, and the differences
  // are the point rather than noise -- a fixture that gave every row both rates would test the
  // picker against data the endpoint has never sent:
  //
  //   * A CITY carries `remodel_rate` and NO `rate`. So `county_tax_rate` saves null for all 15
  //     of them, absorbed by the picker's `c.rate == null` guard.
  //   * A KANSAS COUNTY carries both -- but `rate` is the county PORTION (Johnson: 1.475%), not a
  //     combined rate. `remodel_rate` is the combined 7.975%. They are different numbers meaning
  //     different things, and only the second one prices anything.
  //   * A MISSOURI COUNTY OMITS `remodel_rate` ALTOGETHER. Not null -- absent. Which is the
  //     harder case for `== null` to absorb, and the real one.
  { name: "Overland Park", state: "KS", county: "Johnson", kind: "city", remodel_rate: 0.0935,
    notes: "Verified 2026-09-02: 6.5% state + 1.475% county + 1.375% city." },
  { name: "Olathe", state: "KS", county: "Johnson", kind: "city", remodel_rate: 0.09475,
    notes: "Verified 2026-09-02 against KDOR (100 E Santa Fe St, 66061): 9.475%." },
  { name: "Johnson", state: "KS", kind: "county", fips: "20091", rate: 0.01475,
    county_portion: 0.01475, remodel_rate: 0.07975,
    notes: "County-only rate — correct for unincorporated land." },
  { name: "Wyandotte", state: "KS", kind: "county", fips: "20209", rate: 0.01,
    county_portion: 0.01, remodel_rate: 0.075, notes: "KCK, Bonner Springs." },
  { name: "Sedgwick", state: "KS", kind: "county", fips: "20173", rate: 0.01,
    county_portion: 0.01, remodel_rate: 0.075, notes: "Wichita levies no general city tax." },
  { name: "Jackson", state: "MO", kind: "county", fips: "29095", rate: 0.06225,
    notes: "KC metro core. Remodels for taxable-orgs: taxable. Gov/school: exempt." },
];

/** The rows js/county-picker.js renders into #county-results, as stub nodes.
 *
 *  Parsed out of the emitted markup rather than mirrored from COUNTY_TABLE, for the same reason
 *  parseSwitches is: "renders the wrong label", "renders a rate for a row that has none" and
 *  "renders nothing at all" are then all visible. The module reaches these back BY ID to paint
 *  the keyboard cursor, so each one registers itself under the id it was given.
 */
function parseCountyRows(html, keepAncestor) {
  const out = [];
  const re = /<div class="c-row" id="(county-row-\d+)" data-county="(\d+)">([\s\S]*?)<\/div>/g;
  let m;
  while ((m = re.exec(html))) {
    // Captured per iteration. `m` is the loop's own cursor and is null once the loop ends, so a
    // closure below that read m[2] directly would throw on the first click -- an hour lost to it.
    const idx = m[2];
    const row = mkEl({
      id: m[1],
      index: Number(idx),
      name: (/<span class="c-name">([^<]*)</.exec(m[3]) || [])[1] || "",
      rate: (/<span class="c-rate">([^<]*)</.exec(m[3]) || [])[1] || "",
      className: "c-row",
    });
    // Real ancestry, both ways: the row answers the module's row lookup, and it is also INSIDE
    // the results box, so clicking one must not read as a click outside the control.
    row.closest = (sel) => (sel === "[data-county]" ? row
      : sel === "[data-county-keep]" ? keepAncestor : null);
    row.getAttribute = (a) => (a === "data-county" ? idx : null);
    out.push(row);
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
      nodes[id] = mkEl({ id: id, style: parseStyle(attrs), _attrs: attrs,
                         hidden: /(^|\s)hidden(\s|>|=)/.test(attrs) });
      return nodes[id];
    },
  };
  const windowStub = { location: {
    assign: (url) => NAV.push(url),
    // `replace` and `search`: what the v2 routing guard at the top of index.js reads and calls.
    replace: (url) => REPLACED.push(url),
    search: (pageOpts && pageOpts.search) || "",
  } };
  const TW = {
    readForm: twScope.readForm,
    writeForm: twScope.writeForm,
    withDraft: twScope.withDraft,
    // The REAL v2 predicate and ownership check, lifted out of shared.js (see twScope).
    isV2Draft: twScope.isV2Draft,
    isThisDraft: twScope.isThisDraft,
    getState: () => STATE,
    setState: (partial) => { SAVES.push(JSON.parse(JSON.stringify(partial))); Object.assign(STATE, partial); },
    // js/county-picker.js builds its request out of these two, the way every other fetch in
    // the app does. Leave them off and its load() throws inside its own catch, the reference
    // table arrives empty, and the search box goes quiet in a way that is indistinguishable
    // from a network failure -- every county assertion below would pass by saying nothing.
    resolveApiBase: () => "",
    // condOpts.gated: the sign-in has not settled at script load. The header exists only once
    // releaseAuth() runs, exactly like the real TWAuth.ready / TW.authHeaders pair.
    authHeaders: () => (condOpts && condOpts.gated && !authReleased)
      ? {} : { Authorization: "Bearer t" },
  };
  let authReleased = !(condOpts && condOpts.gated);
  let releaseAuthFn = () => { authReleased = true; };
  if (condOpts && condOpts.gated) {
    windowStub.TWAuth = { ready: new Promise((r) => { releaseAuthFn = () => { authReleased = true; r(); }; }) };
  }

  // The admin-set answers for dye / joint_filler / remove_existing_jf, the same three the
  // Polish beta pages already fetch through this endpoint. Recorded rather than counted, the
  // same reason countyFetches is, so a second, wasteful load would show. `condOpts.rows` is
  // the `conditions` array GET /api/condition-defaults answers with; undefined means "nobody
  // has overridden anything" -- an empty list, which is production truth on both databases as
  // of this commit -- and `condOpts.fail` makes the request reject, the unreachable-endpoint
  // case the loadConditionDefaults() in index.js has to survive.
  const conditionFetches = [];
  const cndOpts = condOpts || {};
  const conditionFetchStub = async function (url, init) {
    conditionFetches.push(String(url));
    if (cndOpts.fail) throw new Error("network");
    // A request without the auth header is a 401 whose body carries no conditions.
    if (cndOpts.gated && !((init || {}).headers || {}).Authorization) {
      return { json: async () => ({ detail: "not signed in" }) };
    }
    return { json: async () => ({ ok: true,
                                  conditions: cndOpts.rows === undefined ? [] : cndOpts.rows }) };
  };

  // THE REAL SCRIPT TAGS, in the order index.html loads them. county-picker.js goes first
  // because the page script calls TWCounty.mount() as it boots; loading it second would leave
  // the mount guarded away and the whole control untested while every assertion below still ran.
  windowStub.TW = TW;        // county-picker.js reads window.TW, not the injected parameter
  // The one vocabulary (js/work-types.js), under its real global name, ahead of the page script exactly as
  // index.html orders the tags: index.js reads it for the split rule and throws by name without it. The REAL
  // module, so the live intake's split behaviour is the table's.
  windowStub.TWWorkTypes = require(path.join(ROOT, "js", "work-types.js"));
  new Function("document", "window", "fetch", countyJs)(documentStub, windowStub, fetchStub);
  // The address lookup, loaded before index.js exactly as index.html orders the tags: the page
  // script calls TWAddress.mount() as it boots, so a ReferenceError here is a missing script tag.
  new Function("document", "window", "fetch", addressJs)(documentStub, windowStub, fetchStub);
  // THE REAL PAGE SCRIPT, top to bottom. An unbound identifier anywhere in it throws here.
  //
  // `fetch` IS BOUND, unlike before this comment existed. index.js now calls it itself (the
  // admin condition-defaults read below), and `new Function` resolves an unbound identifier
  // against Node's own global scope rather than raising a ReferenceError -- and on this Node
  // version that global `fetch` is real, not nothing. Leaving this unbound would have every test
  // below firing a genuine network request at a relative URL the instant index.js loads.
  //
  // A v2 draft makes the script stop on purpose (a `replace` and then a throw), so that one error is
  // the page doing its job and is recorded as `stopped`. Anything else rethrows: an unbound
  // identifier must still fail loudly here.
  let stopped = null;
  try {
    new Function("document", "window", "TW", "fetch", indexJs)(
      documentStub, windowStub, TW, conditionFetchStub);
  } catch (e) {
    if (!/a v2 draft belongs on polish-intake/.test(String(e && e.message))) throw e;
    stopped = String(e.message);
  }

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
  /** A keystroke in the search box, which is how every search actually starts. */
  function typeCounty(text) {
    countyInput.value = text;
    return fire(countyInput, "input");
  }
  /** A key pressed while the search box has focus — Enter, Escape, the arrows. */
  function pressCounty(k) {
    let prevented = false;
    const fns = (countyInput.listeners || {}).keydown || [];
    fns.forEach((fn) => fn({ key: k, target: countyInput, preventDefault() { prevented = true; } }));
    return { handlers: fns.length, prevented: prevented };
  }
  function countyRowList() { return countyRows.slice(); }
  /** A click ANYWHERE on the page, through the document listener the module bound itself. */
  function pageClick(target) {
    const fns = documentStub.listeners.click || [];
    fns.forEach((fn) => fn({ target: target }));
    return fns.length;
  }
  return { NAV, REPLACED, stopped, SAVES, STATE, nodes, flags, form, radios, systems, documentStub,
           condBox, switches, switchFor, press, clickSwitch,
           countyFetches, conditionFetches, releaseAuth: () => releaseAuthFn(), typeCounty, pressCounty, countyRowList, pageClick,
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
  // The Drawings & specs box (2026-10-02, what Kyle's GC forms leave as "xx"). Plain named inputs,
  // so both doors must save them as typed -- the addenda count as a NUMBER, like the quantities.
  drawings_dated: "2026-08-15",
  spec_section: "033543",
  finish_tag: "PC",
  plan_sheet: "A900",
  addenda_count: "2",
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
(async function () {
  const tick = () => new Promise((r) => setImmediate(r));
  const cells = (b) => (b.STATE.cell_values || {});

  // Which questions each work type is asked. Read off the rendered nodes, in order.
  out.conditions = { byWorkType: {}, shape: null, defaults: null };
  for (const wt of ["epoxy", "polish", "combo", "gyp"]) {
    const b = build();
    await tick();          // let the admin-defaults gate settle before the first paint
    b.setWorkType(wt);
    out.conditions.byWorkType[wt] = b.switches().map((s) => s.key);
  }

  // The switch shape, and whether the labels say what the toggle does.
  {
    const b = build();
    await tick();
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
    // Defaults, on screen. joint_filler MUST now be OFF, and it was the opposite claim until
    // 2026-09-19: "Kyle's template ships Polish!E29 = Yes, so a default of off would quietly
    // remove filler from jobs that get it today". What changed is that the line started costing
    // money -- a $500 kit per 3,500 sq ft -- so "on by default" stopped being a harmless
    // transcription of the workbook and became $2,500 nobody had chosen. Hanz's call: all three
    // start off. index.js's `def` and bid-model's freshModel() both say so and must agree.
    out.conditions.defaults = {};
    b.switches().forEach((s) => { out.conditions.defaults[s.key] = s.on; });
  }

  // Nothing is written until something is touched -- a work type alone must not create a row.
  {
    const b = build();
    await tick();
    b.setWorkType("polish");
    out.conditions.savesOnWorkTypeAlone = b.SAVES.length;
    out.conditions.cellsOnWorkTypeAlone = Object.keys(cells(b)).length;
  }

  // A flip, and the literals it lands. Both tabs for local; Epoxy only for the three formulas.
  {
    const b = build();
    await tick();
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
    await tick();
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
    await tick();
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
    await tick();
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
  //
  // JOINT FILLER IS SWITCHED ON FIRST, because it ships OFF since 2026-09-19 -- so remove-existing
  // is inert from the moment the step opens and "before" would already be the state under test.
  // The press below is the one that matters; the press above only builds the precondition.
  {
    const b = build();
    await tick();
    b.setWorkType("polish");
    b.clickSwitch("joint_filler");               // ships off -> on, the precondition
    const before = b.switchFor("remove_existing_jf");
    b.clickSwitch("joint_filler");               // on -> off, the change under test
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
    await tick();
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
    await tick();
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
    await tick();
    b.setWorkType("polish");
    const read = {};
    b.switches().forEach((s) => { read[s.key] = s.on; });
    out.conditions.hydrated = read;
    out.conditions.hydrateSaves = b.SAVES.length;
  }

  // A SPLIT DRAFT (2026-09-30). Once the estimate screen has given every sheet its own Taxable? /
  // Remodel Tax? (state.tax_flags_per_sheet), these two switches are the BASE's own cells, found
  // through priced_tabs[].flag_cells -- and they are written by their own switch only. Options
  // (Leveling, 'Gyp (FR)', Epoxy on a polish job) keep their own answers through every save here.
  {
    const taxCells = ["Epoxy!B6", "Epoxy!D6", "Polish!B6", "Polish!D6", "Leveling!B6",
                      'Gyp (USG 1-8")!B8', "Gyp (FR)!B8"];
    const pick = (cv) => { const o = {}; taxCells.forEach((k) => { o[k] = cv[k]; }); return o; };
    const splitDraft = (base, wt) => ({
      tax_flags_per_sheet: true, base_tab_id: base, work_type: wt,
      priced_tabs: [
        { id: "Epoxy", flag_cells: { taxable: "Epoxy!B6", remodel: "Epoxy!D6" } },
        { id: "Polish", flag_cells: { taxable: "Polish!B6", remodel: "Polish!D6" } },
      ],
      cell_values: { "Epoxy!B6": "Yes", "Epoxy!D6": "No", "Polish!B6": "No", "Polish!D6": "No",
                     "Leveling!B6": "Yes", 'Gyp (USG 1-8")!B8': "No", "Gyp (FR)!B8": "No" },
    });
    const b = build(splitDraft("Polish", "polish"));
    await tick();
    // read at BOOT, before any radio fires: the change listener re-reads these two on its own
    const booted = { taxable: b.switchFor("taxable").on, remodel: b.switchFor("remodel_tax").on };
    b.setWorkType("polish");
    const hydrated = { taxable: b.switchFor("taxable").on, remodel: b.switchFor("remodel_tax").on };
    const before = pick(cells(b));
    b.clickSwitch("dye");                      // another switch: no tax cell may move
    const afterDye = pick(cells(b));
    b.clickSwitch("taxable");                  // the base's own switch: Polish's cell, and only it
    const afterTaxable = pick(cells(b));
    b.clickSwitch("remodel_tax");
    const afterRemodel = pick(cells(b));
    // a combo with no single base: both halves of the combined base, no option
    const c = build(splitDraft(null, "combo"));
    await tick();
    c.setWorkType("combo");
    c.clickSwitch("local");                    // Epoxy says Yes, Polish No: neither may be restated
    const comboAfterLocal = pick(cells(c));
    c.clickSwitch("taxable");                  // hydrated off Epoxy's Yes -> off -> "No" on both
    // and a draft the estimate screen has NOT split yet still writes the four literals
    const pre = build({ cell_values: {} });
    await tick();
    pre.setWorkType("epoxy");
    pre.clickSwitch("taxable");
    out.conditions.split = {
      booted, hydrated, before, afterDye, afterTaxable, afterRemodel,
      comboAfterLocal, combo: pick(cells(c)),
      unsplit: pick(cells(pre)),
    };
  }

  // A COMBO JOB IS PRICED ON TWO SHEETS, and the shared rule says which (js/work-types.js baseSheets): with
  // no explicit base both Epoxy's and Polish's own cells are the job's, so flipping Taxable writes BOTH and
  // nothing else tax. The earlier combo case above starts Polish at the answer it ends on, so it cannot tell a
  // lost second sheet from a written one; here Polish starts on Yes and has to come out No.
  {
    const c = build({
      tax_flags_per_sheet: true, base_tab_id: null, work_type: "combo",
      priced_tabs: [
        { id: "Epoxy", flag_cells: { taxable: "Epoxy!B6", remodel: "Epoxy!D6" } },
        { id: "Polish", flag_cells: { taxable: "Polish!B6", remodel: "Polish!D6" } },
      ],
      cell_values: { "Epoxy!B6": "Yes", "Polish!B6": "Yes", "Epoxy!D6": "No", "Polish!D6": "No",
                     "Leveling!B6": "Yes", 'Gyp (USG 1-8")!B8': "No" },
    });
    await tick();
    c.setWorkType("combo");
    c.clickSwitch("taxable");
    const cv = cells(c);
    out.conditions.comboBothHalves = {
      cells: { "Epoxy!B6": cv["Epoxy!B6"], "Polish!B6": cv["Polish!B6"], "Epoxy!D6": cv["Epoxy!D6"],
               "Polish!D6": cv["Polish!D6"], "Leveling!B6": cv["Leveling!B6"],
               "Gyp (USG 1-8\")!B8": cv['Gyp (USG 1-8")!B8'] },
    };
  }

  // THE ADDRESSES COME OFF THE DRAFT. priced_tabs[].flag_cells is the estimate screen's snapshot, and a string
  // that came out of a draft becomes a KEY in cell_values, so only a real "Sheet!A1" may be written. Phase 7b
  // moved that check out of this page and into the shared rule (js/work-types.js writeCellsFor), and this
  // scenario is what says it still happens: every address the Polish tab's snapshot offers here is wrong, so
  // flipping the two switches writes no tax cell and invents no key.
  {
    const b = build({
      tax_flags_per_sheet: true, base_tab_id: "Polish", work_type: "polish",
      priced_tabs: [{ id: "Polish", flag_cells: { taxable: "Polish!B6;x", remodel: "Polish!D6\n" } }],
      cell_values: { "Epoxy!B6": "Yes", "Polish!B6": "No", "Polish!D6": "No" },
    });
    await tick();
    b.setWorkType("polish");
    b.clickSwitch("taxable");
    b.clickSwitch("remodel_tax");
    const cv = cells(b);
    out.conditions.hostileFlagCells = {
      taxCells: { "Epoxy!B6": cv["Epoxy!B6"], "Polish!B6": cv["Polish!B6"], "Polish!D6": cv["Polish!D6"] },
      invented: Object.keys(cv).filter((k) => /[;\n]/.test(k)),
    };
  }

  // A WORK-TYPE CHANGE ON A SPLIT DRAFT moves the base with no explicit base_tab_id: a combo's is
  // Epoxy + Polish (the switch reads Epoxy's), a polish job's is Polish, a gyp job's the gyp base.
  // Every sheet here holds a DIFFERENT answer, and the seed's work type is not any of the ones
  // switched to, so the switch can only be right by re-reading the new base's own cell.
  {
    const flagCells = ["Epoxy!B6", "Epoxy!D6", "Polish!B6", "Polish!D6",
                       'Gyp (USG 1-8")!B8', 'Gyp (USG 1-8")!D8'];
    const pickFlags = (cv) => { const o = {}; flagCells.forEach((k) => { o[k] = cv[k]; }); return o; };
    const read = (x) => ({ taxable: x.switchFor("taxable").on, remodel: x.switchFor("remodel_tax").on });
    const t = build({
      tax_flags_per_sheet: true, base_tab_id: null, work_type: "combo",
      priced_tabs: [
        { id: "Epoxy", flag_cells: { taxable: "Epoxy!B6", remodel: "Epoxy!D6" } },
        { id: "Polish", flag_cells: { taxable: "Polish!B6", remodel: "Polish!D6" } },
        { id: 'Gyp (USG 1-8")',
          flag_cells: { taxable: 'Gyp (USG 1-8")!B8', remodel: 'Gyp (USG 1-8")!D8' } },
      ],
      cell_values: { "Epoxy!B6": "Yes", "Epoxy!D6": "Yes", "Polish!B6": "No", "Polish!D6": "No",
                     'Gyp (USG 1-8")!B8': "No", 'Gyp (USG 1-8")!D8': "Yes" },
    });
    await tick();
    const onCombo = read(t);                   // booted on combo: Epoxy's own Yes / Yes
    const seeded = pickFlags(cells(t));
    t.setWorkType("polish");
    const onPolish = read(t);                  // Polish's own No / No, not Epoxy's Yes / Yes
    const afterPolish = pickFlags(cells(t));
    t.setWorkType("gyp");
    const onGyp = read(t);                     // the gyp base's own No / Yes
    t.setWorkType("epoxy");
    const onEpoxy = read(t);                   // and back to Epoxy's Yes / Yes
    const afterTrips = pickFlags(cells(t));
    t.setWorkType("polish");
    t.clickSwitch("taxable");                  // off (Polish's No) -> on: Polish!B6 becomes Yes
    out.conditions.splitWorkType = {
      onCombo, onPolish, onGyp, onEpoxy, seeded, afterPolish, afterTrips,
      afterFlip: pickFlags(cells(t)), shownAfterFlip: read(t),
    };
  }

  // A draft that already carries one of these cells DOES get cleaned up on a work-type change,
  // because leaving a stale out-of-scope flag behind is the bug the cleanup exists for.
  {
    const b = build({ cell_values: { "Polish!E25": "Yes" } });
    await tick();
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
    await tick();
    b.setWorkType("polish");
    b.clickSwitch("dye");
    const cv = cells(b);
    out.conditions.merged = { "Epoxy!E20": cv["Epoxy!E20"], "Polish!E19": cv["Polish!E19"] };
  }

  // A data-cond nobody rendered invents nothing. Guards against a stale id in the markup
  // writing a cell for a condition this work type was never asked.
  {
    const b = build();
    await tick();
    b.setWorkType("epoxy");
    const fake = { closest: () => fake, getAttribute: () => "dye" };
    b.fire(b.condBox, "click", { target: fake, preventDefault() {} });
    out.conditions.strayCond = {
      saves: b.SAVES.length,
      dyeWritten: "Polish!E25" in (b.STATE.cell_values || {}),
    };
  }

  // == THE CONFIRMED GAP, closed. dye / joint_filler / remove_existing_jf now consult the
  // == SAME admin default the Polish beta already fetches (GET /api/condition-defaults), for
  // == these three keys only -- every other condition above keeps its own hardcoded c.def.
  //
  // THE CELL STILL WINS. All three workbook cells present, exactly as a real step-1 save
  // leaves them (Polish!E29=Yes, Polish!E25=No, Polish!F29=No), and the admin default set to
  // the OPPOSITE of every one of them. If the admin default ran ahead of the cell read (or
  // replaced it outright) every one of these three would come back flipped.
  {
    const b = build({ cell_values: {
      "Polish!E29": "Yes",                 // joint filler ON
      "Polish!E25": "No",                  // dye OFF
      "Polish!F29": "No",                  // remove existing jf OFF
    } }, null, { rows: [
      { key: "joint_filler", on: false },      // opposite of the cell
      { key: "dye", on: true },                // opposite of the cell
      { key: "remove_existing_jf", on: true },  // opposite of the cell
    ] });
    // (These stay as they are: every cell is PRESENT here, so each switch's answer can only have
    // come from its cell or from the admin row, and the two disagree on all three. What the tool
    // ships does not enter into it.)
    await tick();
    b.setWorkType("polish");
    out.conditions.cellBeatsAdminDefault = {
      fetched: b.conditionFetches.length > 0,
      jointFiller: b.switchFor("joint_filler").on,
      dye: b.switchFor("dye").on,
      removeExistingJf: b.switchFor("remove_existing_jf").on,
    };
  }

  // A GENUINELY FRESH LOAD -- no cell_values at all, no autofill, nothing typed yet. THIS is
  // the case the bug actually broke: hydrateConditions() fell back to the hardcoded c.def for
  // these three no matter what the Defaults tab said, so the FIRST touch of any of the ten
  // switches baked the wrong answer into the workbook. The admin default has to reach
  // condState here, and therefore the cells conditionCells() writes.
  {
    // EVERY ROW THE OPPOSITE OF WHAT SHIPS, or this case proves nothing: with no cells at all
    // the only two candidate answers are the hardcoded `def` and the admin row, so a row that
    // agreed with `def` would pass against a page that never read the endpoint. joint_filler
    // flipped here on 2026-09-19 when its `def` went to false.
    const b = build(null, null, { rows: [
      { key: "joint_filler", on: true },        // ships false; admin says true
      { key: "dye", on: true },                 // ships false; admin says true
      { key: "remove_existing_jf", on: true },  // ships false; admin says true
    ] });
    await tick();
    b.setWorkType("polish");
    // Touch an UNRELATED switch -- exactly the mechanism the report describes:
    // conditionCells() writes EVERY in-scope condition's cells the instant any ONE of the
    // ten is flipped, so this is what actually bakes the three into cell_values.
    b.clickSwitch("local");
    const written = cells(b);
    out.conditions.adminDefaultReachesFreshLoad = {
      fetched: b.conditionFetches.length > 0,
      jointFiller: b.switchFor("joint_filler").on,
      dye: b.switchFor("dye").on,
      removeExistingJf: b.switchFor("remove_existing_jf").on,
      cells: {
        "Polish!E29": written["Polish!E29"],
        "Polish!E25": written["Polish!E25"],
        "Polish!F29": written["Polish!F29"],
      },
    };
  }

  // == THE AUTH RACE. The page script fires the read at load, before sign-in settles. The stub
  // == answers 401-shaped (no conditions) unless the auth header is present, and the header
  // == exists only after releaseAuth(). A read fired at load therefore comes back {}; one that
  // == waits for TWAuth.ready comes back with the admin's answers.
  {
    const b = build(null, null, { gated: true, rows: [
      { key: "dye", on: true },
    ] });
    await tick();
    b.releaseAuth();
    await tick(); await tick();
    b.setWorkType("polish");
    out.conditions.authRace = { dye: b.switchFor("dye").on };
  }

  // ── the county picker, on the LIVE intake form ─────────────────────────────
  //
  // Continues inside this SAME async IIFE, sharing its `tick`, rather than opening a second one
  // of its own: two independent async IIFEs both feeding `out` would race the final
  // console.log(JSON.stringify(out)) below against whichever one happened to finish last.
  //
  // The county moved here from the polish beta's own step 1, which is being retired. It is a job
  // condition rather than a project field because it exists for the Remodel tax toggle directly
  // above it: Kansas taxes commercial remodel labor at the combined rate at the job site, and
  // Kyle's workbook hardcodes a flat 10% that is not a real rate anywhere.
  //
  // EXECUTED, because every way this can break is invisible to a source read:
  //
  //   * The mount is guarded (window.TWCounty ? … : null) so a script that failed to load
  //     degrades to a hidden field instead of a dead form. A grep sees the guard and cannot tell
  //     you which side of it the browser took. If the script tag were missing from index.html,
  //     or ordered after the page script, every assertion below would go quiet — so the harness
  //     loads the two files in the page's own order and asserts the control is actually alive.
  //   * The four draft keys are written by the module and merged by TW.setState. Whether the
  //     intake blob the Continue handlers save is UNCHANGED by all of this is a claim about what
  //     is in form.elements, and #county-input deliberately carries no `name`.
  //   * Enter inside a search list sits inside a form whose submit handler navigates. Whether it
  //     is swallowed is a fact about preventDefault at runtime.
  out.county = {};

  // Boot: is the control alive, and does it stay out of the way until it matters?
  {
    const b = build();
    await tick();
    const field = b.nodes["county-field"];
    out.county.boot = {
      // Proof the mount ran: the module bound these itself, inside wire().
      inputListeners: ((b.nodes["county-input"].listeners || {}).input || []).length,
      keydownListeners: ((b.nodes["county-input"].listeners || {}).keydown || []).length,
      // wire(true) — this page has no delegated click router of its own for the control.
      documentClickListeners: (b.documentStub.listeners.click || []).length,
      fetched: b.countyFetches.length,
      fetchedPath: b.countyFetches[0] || null,
      // Nothing picked and Remodel tax off: the field is not shown, and the Clear button that
      // only makes sense next to a pick is not shown either.
      fieldHidden: field.hidden,
      clearHidden: b.nodes["county-clear"].hidden,
      // The note is said even while hidden, so revealing the field never shows an empty line.
      note: b.nodes["county-note"].textContent || "",
      // THE INVARIANT THAT KEEPS THE TWO CONTINUE HANDLERS BYTE-FOR-BYTE IDENTICAL: the search
      // box is not a form field. TW.readForm sweeps named inputs only.
      inputIsAFormField: b.form.elements.some((f) => f.id === "county-input"),
      namedFieldCount: b.form.elements.filter((f) => f.name).length,
    };
  }

  // The toggle above it is what reveals it — through renderConditions, the one choke point.
  {
    const b = build();
    b.setWorkType("polish");
    await tick();
    const field = b.nodes["county-field"];
    const before = field.hidden;
    b.clickSwitch("remodel_tax");
    const on = field.hidden;
    const noteOn = b.nodes["county-note"].textContent;
    b.clickSwitch("remodel_tax");
    out.county.followsTheToggle = {
      hiddenWhileOff: before,
      hiddenWhileOn: on,
      hiddenAfterOffAgain: field.hidden,
      // The note quotes the toggle by name, so flipping it has to re-say the sentence.
      noteChanged: noteOn !== b.nodes["county-note"].textContent,
      noteOn: noteOn,
      noteOff: b.nodes["county-note"].textContent,
    };
  }

  // Searching, and what a pick writes.
  {
    const b = build();
    b.setWorkType("polish");
    b.clickSwitch("remodel_tax");
    await tick();
    const savesBefore = b.SAVES.length;
    b.typeCounty("johnson");
    const rows = b.countyRowList();
    b.pageClick(rows[0]);                       // the module's own document listener routes this
    out.county.pick = {
      rowCount: rows.length,
      firstLabel: rows[0] ? rows[0].name : null,
      firstRate: rows[0] ? rows[0].rate : null,
      resultsClosed: b.nodes["county-results"].hidden,
      // What the field shows afterwards is the label, not the half-typed search.
      inputShows: b.nodes["county-input"].value,
      clearOffered: b.nodes["county-clear"].hidden === false,
      saved: b.SAVES.slice(savesBefore).reduce((a, s) => Object.assign(a, s), {}),
      state: { county: b.STATE.county, rate: b.STATE.county_tax_rate,
               remodel: b.STATE.county_remodel_rate },
      note: b.nodes["county-note"].textContent,
      // A pick must not disturb the cells the toggles own.
      cellValuesIntact: b.STATE.cell_values && b.STATE.cell_values["Epoxy!D6"],
    };
  }

  // A city row and a Missouri row: the two labels and the exempt case.
  {
    const b = build();
    await tick();
    b.typeCounty("overland");
    const city = b.countyRowList()[0];
    const cityLabel = city ? city.name : null;
    const cityRate = city ? city.rate : null;
    b.pageClick(city);
    // A city serves no `rate`, so this is the one pick that saves a null tax rate on purpose.
    const citySaved = { rate: b.STATE.county_tax_rate, remodel: b.STATE.county_remodel_rate };
    b.typeCounty("jackson");
    const mo = b.countyRowList()[0];
    b.pageClick(mo);
    out.county.rowShapes = {
      cityLabel: cityLabel,
      cityRate: cityRate,
      citySavedTaxRate: citySaved.rate,
      citySavedRemodelRate: citySaved.remodel,
      moLabel: mo ? mo.name : null,
      moRate: mo ? mo.rate : null,
      // Missouri carries no remodel rate, and null is the correct answer rather than missing data.
      moRemodelSaved: b.STATE.county_remodel_rate,
      moTaxRateSaved: b.STATE.county_tax_rate,
    };
  }

  // The keyboard. Enter inside the list must never reach the form's submit handler.
  {
    const b = build();
    b.setWorkType("polish");
    await tick();
    b.typeCounty("ks");
    const down1 = b.pressCounty("ArrowDown");
    const down2 = b.pressCounty("ArrowDown");
    const enter = b.pressCounty("Enter");
    out.county.keyboard = {
      arrowHandled: down1.handlers > 0 && down1.prevented && down2.prevented,
      enterPrevented: enter.prevented,
      navigatedAway: b.NAV.slice(),              // must be empty: Enter chose a row, not Continue
      chose: b.STATE.county,
      resultsClosed: b.nodes["county-results"].hidden,
    };
  }
  {
    // Enter with nothing arrowed takes the top match — on a list narrowed to one row, Enter
    // means that row rather than "arrow down first".
    const b = build();
    await tick();
    b.typeCounty("wyandotte");
    const enter = b.pressCounty("Enter");
    out.county.enterTakesTopMatch = { prevented: enter.prevented, chose: b.STATE.county,
                                      nav: b.NAV.slice() };
  }
  {
    // Escape closes the list and puts the box back to what is SAVED, so an abandoned search
    // cannot leave the field naming a county the draft does not hold.
    const b = build();
    await tick();
    b.typeCounty("olathe");
    b.pressCounty("Enter");
    const picked = b.nodes["county-input"].value;
    b.typeCounty("wyando");
    b.pressCounty("Escape");
    out.county.escapeRestores = { picked: picked, after: b.nodes["county-input"].value,
                                  closed: b.nodes["county-results"].hidden };
  }

  // A click outside restores the same way; a click on the control itself must not.
  {
    const b = build();
    await tick();
    b.typeCounty("sedgwick");
    b.pressCounty("Enter");
    b.typeCounty("john");
    b.pageClick(b.nodes["county-input"]);        // inside the control: the list stays open
    const stillOpen = b.nodes["county-results"].hidden === false;
    const stillTyped = b.nodes["county-input"].value;
    b.pageClick(mkEl({ id: "somewhere-else", closest: () => null }));
    out.county.outsideClick = {
      stayedOpenOnItsOwnField: stillOpen,
      keptTypingOnItsOwnField: stillTyped,
      closedOnOutside: b.nodes["county-results"].hidden,
      restoredTo: b.nodes["county-input"].value,
    };
  }

  // Clear.
  {
    const b = build();
    b.setWorkType("polish");
    b.clickSwitch("remodel_tax");
    await tick();
    b.typeCounty("johnson");
    b.pressCounty("Enter");
    const n = b.SAVES.length;
    b.pageClick(mkEl({ closest: (sel) => (sel === "#county-clear" ? mkEl({}) : null) }));
    out.county.clear = {
      saved: b.SAVES.slice(n).reduce((a, s) => Object.assign(a, s), {}),
      state: { county: b.STATE.county, rate: b.STATE.county_tax_rate,
               remodel: b.STATE.county_remodel_rate, notes: b.STATE.county_notes },
      inputEmptied: b.nodes["county-input"].value,
      clearHiddenAgain: b.nodes["county-clear"].hidden,
      // Cleared, but the toggle is still on, so the field stays on screen to be answered again.
      // Reported as `hidden` and named for it -- an inverted name here reads as a failure when it
      // is a pass, and the pytest assertion inherits the confusion.
      fieldHidden: b.nodes["county-field"].hidden,
    };
  }

  // HYDRATION. A county chosen on the estimate screen has to show HERE, or the estimator picks
  // it twice and the second pick is the one that counts.
  {
    const b = build({ county: "Johnson County, KS", county_tax_rate: 0.07975,
                      county_remodel_rate: 0.07975, county_notes: "county floor" });
    await tick();
    out.county.hydrated = {
      inputShows: b.nodes["county-input"].value,
      clearOffered: b.nodes["county-clear"].hidden === false,
      note: b.nodes["county-note"].textContent,
      // THE ONE THAT MATTERS: Remodel tax is off, and the field is shown anyway. Hiding a picked
      // county would leave a rate in the draft with nothing on screen to account for it.
      fieldHidden: b.nodes["county-field"].hidden,
      // Hydration is a read. It must not write. Counted on the county keys rather than on
      // SAVES itself, so an unrelated boot save cannot make this pass or fail by accident.
      countySaves: b.SAVES.filter((s) => "county" in s).length,
    };
  }

  // The reference table is not the draft: losing it costs the search its rows and nothing else.
  {
    const b = build(null, { fail: true });
    b.setWorkType("polish");
    b.clickSwitch("remodel_tax");
    await tick();
    b.typeCounty("johnson");
    out.county.fetchFailed = {
      rows: b.countyRowList().length,
      // The estimator is told there is no match rather than left staring at a dead box.
      resultsHtml: b.nodes["county-results"].innerHTML,
      note: b.nodes["county-note"].textContent,
      // And the rest of the form still works: the toggles still save.
      togglesStillSave: b.SAVES.length > 0,
      formStillUsable: b.form.elements.filter((f) => f.name).length > 0,
    };
  }

  // The Kansas state fallback rate is quoted from the ENDPOINT, not written down a third time.
  {
    const b = build(null, { ksRate: 0.065 });
    b.setWorkType("polish");
    b.clickSwitch("remodel_tax");
    await tick();
    out.county.stateFallback = { note: b.nodes["county-note"].textContent };
  }
  {
    const b = build(null, { ksRate: null });
    b.setWorkType("polish");
    b.clickSwitch("remodel_tax");
    await tick();
    out.county.stateFallbackAbsent = { note: b.nodes["county-note"].textContent };
  }

  // ── a v2 draft does not open on the live intake ────────────────────────────────────────────
  //
  // The guard at the top of index.js, and the one in the submit handler. EXECUTED against the real
  // script and the REAL isV2Draft / isThisDraft lifted out of shared.js. What matters is which way
  // each load goes (replaced and stopped, or the form came up), so every scenario reports both, and
  // reports what was saved: a redirected page must write nothing.
  //
  // THE CASES THAT MUST NOT REDIRECT matter as much as the one that must. A v2 blob that is some
  // OTHER project's (storage holds yesterday's v2 project while a link opens a spreadsheet bid), and
  // a load that names no project (a bare page, or "?new=1" before shared.js has given the new
  // project its id) all have to get the form.
  {
    const FILLED = { project_name: "Nearman Creek (beta test)", work_type: "polish" };
    const v2 = (extra) => Object.assign({ polish_estimate: { version: 2 }, __draft_id: DRAFT_ID },
                                        FILLED, extra || {});
    const sheet = (extra) => Object.assign({ __draft_id: DRAFT_ID }, FILLED, extra || {});
    const go = (seed, search) => {
      const b = build(seed, null, null, { search: search });
      return { replaced: b.REPLACED.slice(), stopped: b.stopped, assigned: b.NAV.slice(),
               saves: b.SAVES.length, formBuilt: !!(b.nodes["systems-container"].innerHTML) };
    };
    const NAMED = "?d=" + DRAFT_ID + "&edit=1";
    out.v2routing = {
      namedAndEdit: go(v2(), NAMED),
      editOnly: go(v2(), "?edit=1"),
      dOnly: go(v2(), "?d=" + DRAFT_ID),
      textVersion: go(v2({ polish_estimate: { version: "2" } }), NAMED),
      // A reload of a new project's page: shared.js has put the project's id in the address bar by
      // then ("?new=1&d=..."), so the load names a project, and one that has become v2 goes on to v2.
      newProjectReloaded: go(v2(), "?new=1&d=" + DRAFT_ID),
      newProject: go(v2(), "?new=1"),
      noQuery: go(v2(), ""),
      anotherProjectsBlob: go(v2({ __draft_id: "some-other-draft" }), NAMED),
      unstamped: go(v2({ __draft_id: undefined }), NAMED),
      spreadsheetBid: go(sheet(), NAMED),
      noEstimateAtAll: go({ __draft_id: DRAFT_ID }, NAMED),
      oldPolishEstimate: go(sheet({ polish_estimate: { areas: [] } }), NAMED),
      versionOne: go(sheet({ polish_estimate: { version: 1 } }), NAMED),
    };

    // The submit handler, on a page that loaded BEFORE the draft became v2 (another tab priced it in
    // v2 since): the load guard cannot see it, so the handler must not carry it to the spreadsheet.
    const submit = (seed) => {
      const b = build(seed);
      // A page that already left at load has no form to fill. Reported rather than thrown, so a
      // scenario that breaks the load guard on purpose still reads the rest of this harness.
      if (b.stopped) return { stoppedAtLoad: true, replaced: b.REPLACED.slice() };
      b.setWorkType("epoxy");           // the stale form says epoxy; the draft says polish
      b.fill(PROJECT);
      b.fire(b.form, "submit");
      return { assigned: b.NAV.slice(), replaced: b.REPLACED.slice(), saves: b.SAVES.length,
               savedWorkType: b.STATE.work_type };
    };
    out.v2routing.submitOnAV2Draft = submit(v2());
    out.v2routing.submitOnAnotherProjectsV2Blob = submit(v2({ __draft_id: "some-other-draft" }));
    out.v2routing.submitOnASpreadsheetBid = submit(sheet());
  }

  // ── the intake's work-type scope, as the live page renders and shows it ──────────────────────────────
  // Phase 9a: every job type (and "blank", no radio checked) x both audiences, read off the nodes after the REAL
  // page script ran, once as the page LOADS with a saved draft and once after the radio is clicked. The markup of
  // the systems block, and the display state of everything the work type shows or hides. fixtures/
  // intake_scope_golden.json was written from the code BEFORE it moved onto js/intake-scope.js, so a test that
  // compares this to it proves the move changed nothing a person can see.
  out.scopeSnapshots = {};
  {
    const snapshot = (b) => ({
      systemsHtml: b.systems.innerHTML,
      systemsDisplay: b.systems.style.display === undefined ? null : b.systems.style.display,
      gypDisplay: b.nodes["gyp-sf-container"].style.display === undefined ? null : b.nodes["gyp-sf-container"].style.display,
      betaDisplay: b.nodes["beta-continue"].style.display === undefined ? null : b.nodes["beta-continue"].style.display,
      thicknessDisplay: b.nodes["thickness-row"].style.display === undefined ? null : b.nodes["thickness-row"].style.display,
      labels: b.systems.querySelectorAll("[data-scope]").map((l) => ({
        scope: l.getAttribute("data-scope"), display: l.style.display === undefined ? null : l.style.display })),
      rows: b.systems.querySelectorAll(".row").map((r) => (r.style.display === undefined ? null : r.style.display)),
    });
    ["Direct", "GC"].forEach(function (audience) {
      ["polish", "epoxy", "combo", "gyp", "blank"].forEach(function (job) {
        const key = audience + "/" + job;
        const seed = { audience: audience };
        if (job !== "blank") seed.work_type = job;
        const loaded = build(seed);
        if (job === "blank") loaded.radios.forEach((r) => { r.checked = false; });
        const atLoad = snapshot(loaded);
        const clicked = build({ audience: audience });
        if (job === "blank") {
          clicked.radios.forEach((r) => { r.checked = false; });
          clicked.fire(clicked.radios[0], "change");
        } else {
          clicked.setWorkType(job);
        }
        out.scopeSnapshots[key] = { atLoad: atLoad, afterClick: snapshot(clicked) };
      });
    });
  }

  console.log(JSON.stringify(out));
})();
