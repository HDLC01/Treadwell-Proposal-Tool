"use strict";
/* Render the Done page's RECIPIENTS list for real and report the resulting tree.
 *
 * The claim is structural — "the checkbox is outside the bordered container" — so a grep for
 * `wrap.appendChild(fu)` proves nothing about where it lands. This builds the list with a tiny
 * DOM shim and walks the actual parent/child relationships.
 *
 * Usage: node recipients-row-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[2];

// ── a DOM small enough to read, real enough to hold a tree ───────────────────
function makeEl(tag) {
  const el = {
    tagName: String(tag).toUpperCase(), children: [], parent: null,
    className: "", type: "", value: "", checked: false, title: "", _text: "",
    style: {}, attrs: {}, listeners: {},
    appendChild(c) { c.parent = el; el.children.push(c); return c; },
    setAttribute(k, v) { el.attrs[k] = v; },
    addEventListener(k, fn) { (el.listeners[k] = el.listeners[k] || []).push(fn); },
    querySelector(sel) { return find(el, sel)[0] || null; },
    querySelectorAll(sel) { return find(el, sel); },
    focus() {}, select() {},
    get textContent() {
      return el._text + el.children.map((c) => c.textContent).join("");
    },
    set textContent(v) { el._text = String(v); el.children.length = 0; },
  };
  return el;
}
function matches(el, sel) {
  if (sel.startsWith(".")) return (" " + el.className + " ").indexOf(" " + sel.slice(1) + " ") >= 0;
  if (sel.startsWith("#")) return el.attrs.id === sel.slice(1);
  return el.tagName === sel.toUpperCase();
}
/** Supports the two forms done.js actually uses: a single selector, and one descendant pair
 *  (".tw-em-add input"). Anything fancier would be the harness inventing capability the page
 *  does not rely on. */
function find(root, sel) {
  const parts = String(sel).trim().split(/\s+/);
  let scope = [root];
  parts.forEach((part) => {
    const next = [];
    scope.forEach((s) => {
      (function walk(n) {
        n.children.forEach((c) => { if (matches(c, part)) next.push(c); walk(c); });
      })(s);
    });
    scope = next;
  });
  return scope;
}

// The bits of done.js we need: mountPortalRecipients builds the whole block.
const src = fs.readFileSync(path.join(ROOT, "js", "done.js"), "utf8");
const m = /\n  function mountPortalRecipients\(\) \{[\s\S]*?\n  \}/.exec(src);
if (!m) throw new Error("mountPortalRecipients() is gone from done.js — rewrite this harness");

function render(state, opts) {
  const o = opts || {};
  const box = makeEl("div");
  box.attrs.id = "portal-recipients";
  // innerHTML is a string in the real DOM; the function sets it once then queries. Emulate by
  // materialising exactly the four nodes it looks for afterwards.
  Object.defineProperty(box, "innerHTML", {
    set() {
      box.children.length = 0;
      const label = makeEl("div"); label.className = "tw-em-label";
      const list = makeEl("div"); list.className = "tw-em-list";
      const add = makeEl("div"); add.className = "tw-em-add";
      const input = makeEl("input"); input.type = "email";
      const btn = makeEl("button"); btn.className = "tw-em-addbtn";
      add.appendChild(input); add.appendChild(btn);
      const err = makeEl("p"); err.className = "tw-em-err";
      [label, list, add, err].forEach((n) => box.appendChild(n));
    },
    get() { return ""; },
  });

  const doc = {
    getElementById: (id) => (id === "portal-recipients" ? box : null),
    createElement: makeEl,
    // A text node is a child that contributes text and nothing else — enough for the
    // " Follow-ups" label to appear in textContent where the tests look for it.
    createTextNode: (t) => {
      const n = makeEl("#text");
      n._text = String(t);
      return n;
    },
    addEventListener() {},
  };
  const TW = { getState: () => state, setState() {}, authHeaders: () => ({}),
               absoluteUrl: (p) => p, fmtBizDate: (s) => String(s), fmtUsd: (n) => "$" + n };
  const portalRecip = { noFollowups: (o.noFollowups || []).slice() };

  // EMAIL_RE lives at module scope in done.js; lift it so the function behaves as shipped.
  const reM = /const EMAIL_RE = [^\n]+/.exec(src);
  const fn = new Function("document", "TW", "portalRecip", "console",
    (reM ? reM[0] + "\n" : "const EMAIL_RE = /.+@.+/;\n") + m[0] +
    "\n; mountPortalRecipients(); return { box: arguments[0].getElementById('portal-recipients'), portalRecip };");
  const res = fn(doc, TW, portalRecip, { warn() {}, error() {} });

  const list = box.querySelector(".tw-em-list");
  const describe = (w) => ({
    className: w.className,
    childClasses: w.children.map((c) => c.className || c.tagName),
    // Where did the follow-ups control land?
    fuIsDirectChildOfWrap: w.children.some((c) => c.className === "tw-em-fu"),
    fuIsInsideRow: w.children.filter((c) => c.className === "tw-em-row")
                    .some((r) => find(r, ".tw-em-fu").length > 0),
    // Order matters: the checkbox must come AFTER the bordered row.
    fuAfterRow: (() => {
      const iRow = w.children.findIndex((c) => c.className === "tw-em-row");
      const iFu = w.children.findIndex((c) => c.className === "tw-em-fu");
      return iRow >= 0 && iFu > iRow;
    })(),
    rowChildren: (w.children.find((c) => c.className === "tw-em-row") || { children: [] })
                   .children.map((c) => c.className || c.tagName + ":" + c.textContent.trim()),
    fuChecked: (() => {
      const fu = w.children.find((c) => c.className === "tw-em-fu");
      const cb = fu ? find(fu, "input")[0] : null;
      return cb ? cb.checked : null;
    })(),
  });
  // Re-read after an interaction: renderList() replaces the list's contents, so the wraps have
  // to be walked again rather than held.
  const snapshot = () => (box.querySelector(".tw-em-list").children).map(describe);
  return {
    wraps: snapshot(),
    reread: snapshot,
    editButtons: find(box, ".tw-em-editbtn"),
    portalRecip: res.portalRecip,
  };
}

const out = {};

// One intake contact, nothing opted out — the screenshot's case.
out.intakeOnly = render({ contact_email: "hdlcruz03@gmail.com", portal_emails: [] }).wraps;

// Intake + an extra, with the extra opted OUT of chasing.
out.twoWithOptOut = render(
  { contact_email: "hdlcruz03@gmail.com", portal_emails: ["ap@acme.com"] },
  { noFollowups: ["ap@acme.com"] }).wraps;

// No customer email on file at all — the empty state must not grow a stray checkbox.
out.noIntake = render({ contact_email: "", portal_emails: [] }).wraps;

// EDIT MODE, reached by clicking the intake row's Edit button — the real path, not a flag poked
// from outside. Mid-edit the entry is input + Save + Cancel and must carry no follow-ups
// control: the decision belongs to a settled recipient, and there isn't one yet.
out.editing = (() => {
  const r = render({ contact_email: "hdlcruz03@gmail.com", portal_emails: [] });
  const edit = r.wraps.length ? r.editButtons[0] : null;
  if (!edit) return [];
  (edit.listeners.click || []).forEach((fn) => fn({}));
  return r.reread();
})();

console.log(JSON.stringify(out));
