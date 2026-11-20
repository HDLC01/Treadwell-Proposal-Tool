"use strict";
/* The BD CRM row's collapsible group in the sidebar (#806). Runs the REAL frontend/auth.js init().
 *
 * auth.js runs in a bare VM context with a small fake document: every element the code looks up by id
 * is one persistent object that remembers its attributes, its `hidden` and its innerHTML, so what the
 * sidebar does to the chevron and the section list can be read back after each click. The tool's
 * /api/me and BD's /api/bd/me answer what the scenario says (the test takes BD's `can` map from the
 * real bd/auth.py can()).
 *
 * Usage: node bd-sidebar-group-harness.js <frontend-dir> <scenario.json>  ->  one line of JSON
 *
 * scenario: { pathname, wide, storage: {key: value}, me: {...tool /api/me...},
 *             bdMe: {status, body} | null or false (the fetch rejects: no network) |
 *                   "pending" (no answer yet, ever),
 *             clicks: ["chev" | "burger" | "section" ...] }
 * out:      { rows, lit, groupInMarkup, insideSidebar, markup: {expanded, controls, hidden},
 *             states: [{expanded, controls, hidden, sections: [{href, label, active, current}],
 *                       note, storage, navOpen}], fetches }
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(process.argv[2]);
const SC = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const AUTH_SRC = read(path.join(ROOT, "auth.js"));
const ICONS_SRC = read(path.join(ROOT, "js", "icons.js"));

function storage(initial) {
  const s = Object.assign({}, initial || {});
  return {
    data: s,
    getItem(k) { return Object.prototype.hasOwnProperty.call(s, k) ? s[k] : null; },
    setItem(k, v) { s[k] = String(v); },
    removeItem(k) { delete s[k]; },
  };
}

function element(id) {
  const e = {
    id: id || "", innerHTML: "", textContent: "", title: "", hidden: false, className: "",
    style: { cssText: "", paddingTop: "" }, dataset: {}, attrs: {}, listeners: {}, kids: [],
    classList: { add() {}, remove() {}, toggle() {} },
    appendChild(c) { e.kids.push(c); }, insertAdjacentHTML() {}, replaceChildren() {}, remove() {},
    addEventListener(type, fn) { (e.listeners[type] = e.listeners[type] || []).push(fn); },
    setAttribute(k, v) { e.attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(e.attrs, k) ? e.attrs[k] : null; },
    removeAttribute(k) { delete e.attrs[k]; },
    focus() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; },
  };
  return e;
}

const fetches = [];
const appended = [];
const byId = {};
const htmlClasses = new Set();
const local = storage(SC.storage);
const session = storage({});

const win = {
  location: { pathname: SC.pathname, search: "", hash: "", origin: "https://example.test",
              replace() {}, assign() {} },
  localStorage: local,
  sessionStorage: session,
  matchMedia() { return { matches: !!SC.wide, addEventListener() {} }; },
  getComputedStyle() { return { paddingTop: "0px" }; },
  setTimeout() {}, setInterval() {}, clearInterval() {}, requestAnimationFrame() {},
  console, JSON, URL, URLSearchParams, Set, Map, Array, Object, Promise, Error, String,
};
const html = element("html");
html.classList = {
  add(c) { htmlClasses.add(c); }, remove(c) { htmlClasses.delete(c); },
  toggle(c, on) { if (on === undefined ? !htmlClasses.has(c) : on) htmlClasses.add(c); else htmlClasses.delete(c); },
  contains(c) { return htmlClasses.has(c); },
};
const body = element("body");
body.appendChild = (e) => { appended.push(e); if (e.id) byId[e.id] = e; };
win.document = {
  head: element("head"), body: body, documentElement: html, hidden: false, title: "",
  getElementById(id) {
    if (id === "tw-sidebar" || id === "tw-sidebar-css") return byId[id] || null;
    if (!byId[id]) byId[id] = element(id);
    return byId[id];
  },
  createElement() { return element(""); },
  querySelector() { return null; }, querySelectorAll() { return []; }, addEventListener() {},
};
win.fetch = (url) => {
  const u = String(url);
  fetches.push(u);
  if (u.indexOf("/api/public-config") !== -1) {
    return Promise.resolve({ ok: true, status: 200, json: async () => (
      { supabase_url: "https://sb.test", supabase_anon_key: "anon", allowed_domain: "wetreadwell.com" }) });
  }
  if (u.indexOf("/api/bd/me") !== -1) {
    if (SC.bdMe === "pending") return new Promise(() => {});
    if (!SC.bdMe) return Promise.reject(new Error("harness: no answer"));
    return Promise.resolve({ ok: SC.bdMe.status < 400, status: SC.bdMe.status,
                             json: async () => SC.bdMe.body });
  }
  return Promise.resolve({ ok: true, status: 200, json: async () => SC.me });
};
win.supabase = { createClient: () => ({ auth: {
  onAuthStateChange() {},
  getSession: async () => ({ data: { session: { access_token: "token",
    user: { email: SC.me.email, user_metadata: { full_name: "Marisol Quint" } } } } }),
  signOut: async () => {},
  signInWithOAuth: async () => {},
} }) };
win.window = win; win.self = win; win.globalThis = win;

function navOf(markup) {
  const i = markup.indexOf('<nav class="tw-nav">');
  const j = markup.indexOf("</nav>");
  return i === -1 || j === -1 ? "" : markup.slice(i, j + 6);
}

function sectionsOf(markup) {
  return Array.from(String(markup || "").matchAll(
    /<a class="tw-bd-sec( active)?" href="([^"]*)"( aria-current="page")?>([^<]*)<\/a>/g))
    .map((m) => ({ href: m[2], label: m[4], active: !!m[1], current: !!m[3] }));
}

function noteOf(markup) {
  const m = /<div class="tw-bd-note">([^<]*)<\/div>/.exec(String(markup || ""));
  return m ? m[1] : "";
}

function state() {
  const chev = byId["tw-bd-chev"];
  const list = byId["tw-bd-sections"];
  return {
    expanded: chev ? chev.getAttribute("aria-expanded") : null,
    controls: chev ? chev.getAttribute("aria-controls") : null,
    hidden: list ? !!list.hidden : null,
    sections: list ? sectionsOf(list.innerHTML) : [],
    note: list ? noteOf(list.innerHTML) : "",
    storage: Object.assign({}, local.data),
    navOpen: htmlClasses.has("tw-nav-open"),
  };
}

const settle = () => new Promise((res) => setImmediate(res));

async function main() {
  vm.createContext(win);
  vm.runInContext(ICONS_SRC, win, { filename: "icons.js" });
  vm.runInContext(AUTH_SRC, win, { filename: "auth.js" });
  await Promise.race([win.TWAuth.ready, new Promise((res) => setTimeout(res, 200))]);
  for (let i = 0; i < 5; i++) await settle();
  const aside = appended.filter((e) => e.id === "tw-sidebar")[0];
  const markup = aside ? aside.innerHTML : "";
  const nav = navOf(markup);
  const rows = Array.from(nav.matchAll(/<a class="tw-nav-item( active)?" href="([^"]*)"/g));
  const chevTag = (/<button[^>]*id="tw-bd-chev"[^>]*>/.exec(markup) || [""])[0];
  const listTag = (/<div[^>]*id="tw-bd-sections"[^>]*>/.exec(markup) || [""])[0];
  const out = {
    rows: rows.map((m) => m[2]),
    lit: rows.filter((m) => m[1]).map((m) => m[2]),
    groupInMarkup: markup.indexOf('id="tw-bd-group"') !== -1,
    insideSidebar: nav.indexOf('id="tw-bd-chev"') !== -1 && nav.indexOf('id="tw-bd-sections"') !== -1,
    markup: {
      expanded: (/aria-expanded="([^"]*)"/.exec(chevTag) || [])[1] || null,
      controls: (/aria-controls="([^"]*)"/.exec(chevTag) || [])[1] || null,
      type: (/type="([^"]*)"/.exec(chevTag) || [])[1] || null,
      hidden: listTag ? / hidden/.test(listTag) : null,
      live: (/aria-live="([^"]*)"/.exec(listTag) || [])[1] || null,
      shut: / tw-shut[" ]/.test(listTag),
    },
    states: [state()],
    fetches: fetches,
  };
  for (const click of SC.clicks || []) {
    if (click === "chev") {
      const chev = byId["tw-bd-chev"];
      (chev && chev.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {} }));
    } else if (click === "burger") {
      const burger = byId["tw-burger"];
      (burger && burger.listeners.click || []).forEach((fn) => fn({ preventDefault() {} }));
    } else if (click === "section") {
      const target = { closest: (sel) => (String(sel).indexOf("tw-bd-sec") !== -1 ? {} : null) };
      (aside && aside.listeners.click || []).forEach((fn) => fn({ target: target }));
    }
    for (let i = 0; i < 5; i++) await settle();
    out.states.push(state());
  }
  out.fetches = fetches.slice();
  process.stdout.write(JSON.stringify(out) + "\n");
}
main().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
