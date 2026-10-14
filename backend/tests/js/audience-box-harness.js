"use strict";
/* The Drawings & specs box follows the Audience radios, on BOTH intakes (Will, 2026-10-12: "the
 * drawings and specs should only be for the general contractor").
 *
 * WHY THIS IS EXECUTED. "The box hides for Direct" is a claim about what a RADIO CHANGE does to a
 * real element, and about the order two scripts run in: js/index.js fills the radios as it loads, so
 * a draft saved as GC opens with the box showing only if audience-box.js looked AFTER that. A source
 * assertion cannot tell a listener on the right element from one that never fires.
 *
 * What is real: js/intake-scope.js (applyAudience), js/audience-box.js, and the two pages' own
 * markup -- the radios, the box and the spec input are read out of index.html and polish-intake.html,
 * so a renamed id or a box moved out of the form fails here. What is a stub: the DOM nodes, which only
 * model what the script touches (value, checked, style, listeners).
 *
 * Usage: node audience-box-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const S = require(path.join(ROOT, "js", "intake-scope.js"));
const SCRIPT = read(path.join(ROOT, "js", "audience-box.js"));

function attr(tag, k) {
  const i = tag.indexOf(" " + k + '="');
  if (i < 0) return null;
  const start = i + k.length + 3;
  return tag.slice(start, tag.indexOf('"', start));
}

/** The intake form's named inputs and the box, as the page's own markup draws them. */
function parsePage(file) {
  const html = read(path.join(ROOT, file));
  const from = html.indexOf('<form id="intake-form">');
  const to = html.indexOf("</form>", from);
  const form = html.slice(from, to);
  const boxAt = form.indexOf('<fieldset id="drawings-specs-box">');
  const boxEnd = form.indexOf("</fieldset>", boxAt);
  const tags = (s) => s.match(/<input\b[^>]*>/g) || [];
  const radios = tags(form).filter((t) => attr(t, "name") === "audience")
    .map((t) => ({ name: "audience", value: attr(t, "value"), checked: t.indexOf(" checked") >= 0 }));
  const boxInputs = boxAt < 0 ? [] : tags(form.slice(boxAt, boxEnd)).map((t) => attr(t, "name"));
  const scripts = (html.match(/<script src="[^"]*"/g) || []).map((s) => s.slice(13, -1));
  // The addenda box's own limits, as the page draws them: what the browser checks on Continue.
  const addendaTag = tags(form).filter((t) => attr(t, "name") === "addenda_count")[0] || "";
  const addendaLimits = {};
  ["min", "max", "step"].forEach((k) => { const v = attr(addendaTag, k); if (v !== null) addendaLimits[k] = v; });
  return { html, radios, boxInputs, boxInForm: boxAt >= 0, scripts, addendaLimits };
}

/** Run the REAL audience-box.js against stubs shaped like `page`. */
function mount(page, opts) {
  opts = opts || {};
  const formListeners = [];
  const winListeners = [];
  const radios = page.radios.map((r) => Object.assign({}, r));
  const spec = { name: "spec_section", value: "033543-A" };
  // The number input in the box, modelled only as far as its attributes: hidden, a limit the value
  // breaks (2.5 under step=1) cancels the form's submit with no message, so the limits must be off.
  const attrs = Object.assign({}, page.addendaLimits);
  const addenda = {
    name: "addenda_count", type: "number",
    hasAttribute: (k) => Object.prototype.hasOwnProperty.call(attrs, k),
    getAttribute: (k) => (Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null),
    setAttribute: (k, v) => { attrs[k] = String(v); },
    removeAttribute: (k) => { delete attrs[k]; },
  };
  const box = {
    id: "drawings-specs-box", style: {}, removed: false,
    querySelectorAll: (sel) => {
      if (sel !== "input[type='number']") throw new Error("audience-box.js asked the box for " + sel + " -- teach the harness");
      return [addenda];
    },
  };
  const form = {
    id: "intake-form",
    addEventListener: (type, fn) => formListeners.push({ type: type, fn: fn }),
    querySelector: (sel) => {
      if (sel === "[name='audience']:checked") return radios.filter((r) => r.checked)[0] || null;
      throw new Error("audience-box.js asked the form for " + sel + " -- teach the harness");
    },
  };
  const win = {
    TWIntakeScope: S,
    addEventListener: (type, fn) => winListeners.push({ type: type, fn: fn }),
  };
  const doc = {
    getElementById: (id) => {
      if (id === "intake-form") return opts.noForm ? null : form;
      if (id === "drawings-specs-box") return opts.noBox ? null : box;
      throw new Error("audience-box.js asked for #" + id + " -- teach the harness");
    },
  };
  new Function("window", "document", SCRIPT)(win, doc);
  const pick = (value) => radios.forEach((r) => { r.checked = r.value === value; });
  return {
    box, spec, win, radios,
    display: () => box.style.display,
    limits: () => ["min", "max", "step"].filter((k) => addenda.hasAttribute(k)).map((k) => k + "=" + attrs[k]),
    pick,
    // What the browser does when a person clicks a radio: the value changes, then `change` fires.
    click: (value) => { pick(value); formListeners.filter((l) => l.type === "change")
      .forEach((l) => l.fn({ target: { name: "audience", value: value } })); },
    typeInSpecBox: () => formListeners.filter((l) => l.type === "change")
      .forEach((l) => l.fn({ target: spec })),
    pageshow: () => winListeners.filter((l) => l.type === "pageshow").forEach((l) => l.fn({})),
    listeners: { form: formListeners.map((l) => l.type), win: winListeners.map((l) => l.type) },
  };
}

const out = { pages: {}, unit: {} };

// The module's own rule, on its own.
out.unit = {
  gc: ["GC", "gc", " GC ", "Gc"].map((a) => S.isGcAudience(a)),
  notGc: ["Direct", "", null, undefined, "General contractor", "Gyp", 0].map((a) => S.isGcAudience(a)),
  noBox: (function () { try { S.applyAudience("GC", null); return "ok"; } catch (e) { return String(e); } })(),
};

["index.html", "polish-intake.html"].forEach((file) => {
  const page = parsePage(file);
  const r = {};
  r.radioValues = page.radios.map((x) => x.value);
  r.defaultChecked = page.radios.filter((x) => x.checked).map((x) => x.value);
  r.boxInForm = page.boxInForm;
  r.boxInputs = page.boxInputs;
  r.scripts = page.scripts.filter((s) => /audience-box|index\.js|polish-intake\.js|intake-scope/.test(s));

  // 1. a new bid is Direct: the box is not shown.
  let m = mount(page);
  r.opensAs = m.display();
  r.listeners = m.listeners;
  // 2. a click on GC shows it, a click back on Direct hides it, a click on GC again shows it.
  m.click("GC");        r.afterGC = m.display();
  m.click("Direct");    r.afterDirect = m.display();
  m.click("GC");        r.afterGCAgain = m.display();
  // 3. what was typed in the box is untouched by hiding: the box and its value are still there.
  m.click("Direct");
  r.valueKept = m.spec.value;
  r.boxStillThere = m.box.removed === false && m.box.style.display === "none";
  // 3b. the number box's limits are set aside while hidden (a value they reject would cancel Continue
  //     on a field nobody can see) and are back, unchanged, once it shows again.
  r.limitsDrawn = Object.keys(page.addendaLimits).map((k) => k + "=" + page.addendaLimits[k]);
  r.limitsOpenHidden = mount(page).limits();
  m.click("GC");        r.limitsShown = m.limits();
  m.click("Direct");    r.limitsHidden = m.limits();
  m.click("GC");        r.limitsBack = m.limits();
  m.click("Direct");
  // 4. a change on some other field does not toggle it.
  m.typeInSpecBox();    r.afterOtherChange = m.display();
  // 5. a draft that was saved as GC and restored by the page BEFORE this script ran (index.js fills
  //    the radios as it loads): the script reads the radios as they are, so the box opens showing.
  const restored = Object.assign({}, page, { radios: page.radios.map((x) => Object.assign({}, x, { checked: x.value === "GC" })) });
  r.opensRestoredGC = mount(restored).display();
  // 6. a radio ticked WITHOUT a change event (Back, or the page's own hydrate) is picked up by sync()
  //    and by pageshow.
  m = mount(page);
  m.pick("GC");         r.beforeSync = m.display();
  m.win.TWAudienceBox.sync();   r.afterSync = m.display();
  m = mount(page);
  m.pick("GC");         m.pageshow();   r.afterPageshow = m.display();
  // 7. nothing ticked reads as Direct.
  m = mount(Object.assign({}, page, { radios: page.radios.map((x) => Object.assign({}, x, { checked: false })) }));
  r.nothingTicked = m.display();
  // 8. a page without the form or the box is left alone, and says nothing.
  r.noBoxThrew = (function () { try { mount(page, { noBox: true }); return false; } catch (e) { return String(e); } })();
  r.noFormThrew = (function () { try { mount(page, { noForm: true }); return false; } catch (e) { return String(e); } })();
  out.pages[file] = r;
});

console.log(JSON.stringify(out));
