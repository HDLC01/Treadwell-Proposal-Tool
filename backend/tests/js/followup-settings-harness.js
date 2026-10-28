"use strict";
/* EXECUTE the Auto Followups page: the whole of frontend/js/followup-settings.js, run against the ids
 * frontend/followup-settings.html really has, with only the network and the TW helpers stubbed.
 *
 * WHY EXECUTED. The page's promises since 2026-10-28 (Hanz: two emails per step, each with its own
 * switch and days, 0 is never "off", a day out of range is REFUSED and never silently replaced, the
 * page shows what was saved) are all about behaviour: what a box shows after a load, what Save puts
 * on the wire, where the portal's refusal sentence lands, what a box shows after the portal stored
 * something. A source grep sees none of it.
 *
 * THE DOM is a bag of elements keyed by the ids in the HTML file (read from it, so an id the script
 * reaches for that the page does not have is a lookup that comes back null and throws, exactly as it
 * would in a browser). Each element keeps value, checked, hidden, disabled, textContent, innerHTML,
 * attributes, classes and listeners.
 *
 * Usage: node followup-settings-harness.js <frontend-dir>  ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(process.argv[2]);
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const HTML = read(path.join(ROOT, "followup-settings.html"));
const SRC = read(path.join(ROOT, "js", "followup-settings.js"));
const IDS = Array.from(HTML.matchAll(/\sid="([^"]+)"/g), (m) => m[1]);

function makeEl(id) {
  const classes = new Set();
  const attrs = {};
  const el = {
    id, value: "", checked: false, hidden: false, disabled: false, textContent: "",
    innerHTML: "", listeners: {}, focused: 0, selectionStart: 0, selectionEnd: 0,
    get className() { return Array.from(classes).join(" "); },
    set className(v) { classes.clear(); String(v || "").split(/\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c),
      toggle: (c, on) => { const v = on === undefined ? !classes.has(c) : !!on;
                           if (v) classes.add(c); else classes.delete(c); return v; },
    },
    setAttribute: (k, v) => { attrs[k] = String(v); },
    removeAttribute: (k) => { delete attrs[k]; },
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    attrs,
    addEventListener(t, f) { (el.listeners[t] = el.listeners[t] || []).push(f); },
    fire(t, ev) {
      return Promise.all((el.listeners[t] || []).map((f) => f.call(el, Object.assign({ target: el }, ev || {}))));
    },
    focus() { el.focused += 1; },
    setSelectionRange() {},
    closest() { return null; },
  };
  return el;
}

function makePage(answers) {
  const els = new Map(IDS.map((id) => [id, makeEl(id)]));
  const requests = [];
  const document = {
    getElementById: (id) => els.get(id) || null,
  };
  const timers = [];
  const queue = answers.slice();
  const fetch = (url, init) => {
    const body = init && init.body ? JSON.parse(init.body) : null;
    requests.push({ url, method: (init && init.method) || "GET", body });
    const isPreview = /\/preview$/.test(url);
    const ans = isPreview ? { status: 200, body: { ok: true, previews: {} } } : queue.shift();
    if (!ans) return Promise.reject(new Error("no answer queued for " + url));
    return Promise.resolve({ ok: ans.status < 400, status: ans.status,
                             json: () => Promise.resolve(JSON.parse(JSON.stringify(ans.body))) });
  };
  const danger = [];
  const TW = {
    resolveApiBase: () => "",
    authHeaders: (h) => h || {},
    fmtBizDate: (s) => "BIZ(" + s + ")",
    confirmDanger: (o) => { danger.push(o); return Promise.resolve(true); },
  };
  const window = { TWAuth: null, TW };
  const sandbox = { window, document, fetch, TW, console,
                    setTimeout: (f) => { timers.push(f); return timers.length; },
                    clearTimeout: () => {} };
  window.window = window;
  vm.runInNewContext(SRC, sandbox, { filename: "followup-settings.js" });
  return { els, el: (id) => els.get(id), requests, danger, queue };
}

const tick = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 12; i++) await tick(); };

const rule = (on, days) => ({ on, days });
const NEW_SETTINGS = {
  steps: { not_opened: { first: rule(true, 3), second: rule(true, 7) },
           opened: { first: rule(true, 3), second: rule(false, 7) } },
  estimator: rule(true, 1),
  thread_subject: "Your Treadwell proposal — {project}",
  send_start_hour: 9, send_end_hour: 17,
  templates: { not_viewed: { title: "Still there?", body: "Hi {first_name}\n\n{link}", cta: "Open" },
               checkin: { title: "Old", body: "x {link}", cta: "Open" } },
};
const GET_NEW = { status: 200, body: { ok: true, settings: NEW_SETTINGS, saved: true,
  updated_at: "2026-10-28T15:00:00Z", updated_by: "will@wetreadwell.com",
  labels: { sent: "Proposal sent", not_viewed: "Not opened yet", next_steps: "After they open it",
            second_nudge: "Second email after opening", checkin: "Recurring check-in",
            deposit_nudge: "Deposit reminder" },
  previews: { not_viewed: { body: "Hi Dave\n\n[ Open ]" } } } };

const ROW_IDS = ["no1", "no2", "op1", "op2", "est"];
function boxes(page) {
  const out = {};
  for (const id of ROW_IDS) {
    out[id] = { on: page.el(id + "-on").checked, days: page.el(id + "-days").value,
                off: page.el(id + "-row").classList.contains("is-off"),
                err: page.el(id + "-err").hidden ? null : page.el(id + "-err").textContent,
                invalid: page.el(id + "-days").getAttribute("aria-invalid") };
  }
  return out;
}
const tabs = (page) => Array.from(page.el("tabs").innerHTML.matchAll(/data-key="([^"]+)"/g), (m) => m[1]);
const puts = (page) => page.requests.filter((r) => r.method === "PUT").map((r) => r.body);

const out = { errors: {} };
async function run() {
  // 1. A NEW PORTAL'S SETTINGS: every switch and number shown as stored, retired tabs dropped.
  try {
    const page = makePage([GET_NEW]);
    await settle();
    out.loaded = { boxes: boxes(page), tabs: tabs(page), alert: page.el("alert").textContent,
                   saveDisabled: page.el("save").disabled, meta: page.el("meta").textContent,
                   main: !page.el("main").hidden };

    // 2. ZERO IS NOT OFF: typed 0, pressed Save, the portal refuses with its sentence and field.
    page.el("no2-days").value = "0";
    await page.el("no2-days").fire("input");
    const REFUSAL = { status: 400, body: { ok: false, error: "2nd email must be 1 to 90 days after the 1st",
                                           field: "steps.not_opened.second.days",
                                           detail: "2nd email must be 1 to 90 days after the 1st" } };
    out.refused = await press(page, [REFUSAL]);

    // 3. TYPING IN THE BOX clears its refusal.
    page.el("no2-days").value = "10";
    await page.el("no2-days").fire("input");
    out.afterRetype = boxes(page).no2;

    // 4. A GOOD SAVE: switch one email off, change a number, and the boxes refill from the answer.
    page.el("op1-on").checked = false;
    await page.el("op1-on").fire("change");
    out.switchedOff = boxes(page).op1;
    const stored = JSON.parse(JSON.stringify(NEW_SETTINGS));
    stored.steps.not_opened.second = rule(true, 10);
    stored.steps.opened.first = rule(false, 3);
    out.saved = await press(page, [{ status: 200, body: { ok: true, settings: stored, saved: true,
      updated_at: "2026-10-29T15:00:00Z", updated_by: "hanz@wetreadwell.com",
      previews: { not_viewed: { body: "Hi Dave\n\n[ Open ]" } } } }]);

    // 5. THE PORTAL STORED SOMETHING ELSE: the page says so and shows what it stored.
    const other = JSON.parse(JSON.stringify(stored));
    other.estimator = rule(true, 2);
    out.differs = await press(page, [{ status: 200, body: { ok: true, settings: other, saved: true,
      updated_at: "2026-10-29T15:01:00Z", updated_by: "hanz@wetreadwell.com", previews: {} } }]);

    // 6. AN ESTIMATOR REFUSAL lands under the estimator row.
    page.el("est-days").value = "200";
    await page.el("est-days").fire("input");
    out.estRefused = await press(page, [{ status: 400, body: { ok: false,
      error: "Tell the estimator must be 1 to 90 days after the last email", field: "estimator.days" } }]);

    // 7. A REFUSAL THAT NAMES NO ROW (a template): said in the alert, no row marked.
    out.templateRefused = await press(page, [{ status: 400, body: { ok: false,
      error: "The Not opened yet email needs {link}", field: "templates.not_viewed.body" } }]);
  } catch (e) {
    out.errors.newPortal = e.constructor.name + ": " + e.message + "\n" + e.stack;
  }

  // 8. AN OLD PORTAL (flat hours, no `steps`): shown as the migration maps it, saving locked.
  try {
    const page = makePage([{ status: 200, body: { ok: true, saved: true,
      settings: { first_nudge_hours: 72, second_nudge_hours: 168, recurring_hours: 2160,
                  max_recurring: 1, staff_personal_hours: 24, thread_subject: "S {project}",
                  templates: {} } } }]);
    await settle();
    out.oldPortal = { boxes: boxes(page), saveDisabled: page.el("save").disabled,
                      resetDisabled: page.el("reset").disabled, alert: page.el("alert").textContent };
  } catch (e) {
    out.errors.oldPortal = e.constructor.name + ": " + e.message + "\n" + e.stack;
  }

  // 9. RESET is an explicit flag beside an empty payload, asked first. The portal ACKNOWLEDGES it
  //    (`reset: true`) and answers with its shipped defaults; the boxes show those.
  try {
    const defaults = JSON.parse(JSON.stringify(NEW_SETTINGS));
    defaults.steps.not_opened.second = rule(true, 5);
    defaults.estimator = rule(true, 2);
    const page = makePage([GET_NEW, { status: 200, body: { ok: true, reset: true, settings: defaults,
                                                            saved: true, previews: {} } }]);
    await settle();
    await page.el("reset").fire("click");
    await settle();
    out.reset = { puts: puts(page), asked: page.danger.length, alert: page.el("alert").textContent,
                  alertOk: page.el("alert").className.indexOf("ok") >= 0, boxes: boxes(page) };
  } catch (e) {
    out.errors.reset = e.constructor.name + ": " + e.message + "\n" + e.stack;
  }

  // 9b. A PORTAL THAT IGNORES THE FLAG: it fills the empty payload from what is saved, stores the
  //     same cadence again and answers without `reset`. The page must not say it reset.
  try {
    const kept = JSON.parse(JSON.stringify(NEW_SETTINGS));
    kept.steps.not_opened.first = rule(true, 20);
    kept.estimator = rule(false, 1);
    const page = makePage([{ status: 200, body: Object.assign({}, GET_NEW.body, { settings: kept }) },
                           { status: 200, body: { ok: true, settings: kept, saved: true,
                                                  previews: {} } }]);
    await settle();
    await page.el("reset").fire("click");
    await settle();
    out.resetIgnored = { puts: puts(page), alert: page.el("alert").textContent,
                         alertOk: page.el("alert").className.indexOf("ok") >= 0, boxes: boxes(page) };
  } catch (e) {
    out.errors.resetIgnored = e.constructor.name + ": " + e.message + "\n" + e.stack;
  }

  // 10. THE FLAT SPELLING (not_opened_first_on, ..._days, estimator_on/_days), which the portal
  //     half was built with: read, written back in the same spelling, and a refusal that carries
  //     only its sentence (no `field`) still lands under the right box.
  try {
    const FLAT = { not_opened_first_on: true, not_opened_first_days: 3,
                   not_opened_second_on: false, not_opened_second_days: 7,
                   opened_first_on: true, opened_first_days: 4,
                   opened_second_on: true, opened_second_days: 8,
                   estimator_on: true, estimator_days: 2, send_start_hour: 8, send_end_hour: 18,
                   thread_subject: "S {project}", templates: {} };
    const page = makePage([{ status: 200, body: { ok: true, saved: true, settings: FLAT } }]);
    await settle();
    out.flat = { loaded: boxes(page), saveDisabled: page.el("save").disabled };
    page.el("op2-days").value = "0";
    out.flat.refused = await press(page, [{ status: 400, body: { ok: false,
      error: "Opened, no decision: the 2nd email must be 1 to 90 days after the 1st." } }]);
    page.el("op2-days").value = "9";
    const stored = Object.assign({}, FLAT, { opened_second_days: 9 });
    out.flat.saved = await press(page, [{ status: 200, body: { ok: true, saved: true,
                                                               settings: stored, previews: {} } }]);
  } catch (e) {
    out.errors.flat = e.constructor.name + ": " + e.message + "\n" + e.stack;
  }
}

// Press Save with these answers queued for the PUT, and read back everything a person would see.
async function press(page, answers) {
  page.requests.length = 0;
  page.queue.push(...answers);          // what the portal answers this press's PUT with
  await page.el("save").fire("click");
  await settle();
  return { puts: puts(page), boxes: boxes(page), alert: page.el("alert").textContent,
           alertOk: page.el("alert").className.indexOf("ok") >= 0,
           saveDisabled: page.el("save").disabled, meta: page.el("meta").textContent };
}

run().then(() => process.stdout.write(JSON.stringify(out) + "\n"),
           (e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
