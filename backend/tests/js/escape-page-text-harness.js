"use strict";
/* Data reaches the page as TEXT, never as markup -- RUN, not read.
 *
 * The 2026-09-28 security review found that several places on the estimate and proposal pages build
 * markup out of values that are not ours: the AI autofill's answers, a texture saved on a draft, a
 * typed price-line amount, a notification's link, an address from the lookup service, a clipboard.
 * Any of them carrying `<img src=x onerror=...>` or `" onfocus="...` would have run script in a
 * staff member's signed-in session, where the login token sits in localStorage.
 *
 * Every function below is lifted out of the shipped file BY NAME and executed against a small DOM
 * whose innerHTML is a real (if small) HTML tokenizer: quoted, single-quoted and bare attributes,
 * entities, void elements. So "the value came out as text" is read off the tree the markup builds,
 * not off the source -- a missed escape shows up here as an element or an attribute that the data
 * created. Deliberately not jsdom, for the reason box-drag-harness.js gives: a full DOM lets a
 * missing binding hide behind a stub.
 *
 * Usage: node escape-page-text-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
// Normalised to LF: the frontend is checked out CRLF on Windows and the lifters anchor on "\n".
const read = (p) => fs.readFileSync(path.join(FRONTEND, p), "utf8").replace(/\r\n/g, "\n");
const EST = read("js/estimate-review.js");
const PROP = read("js/proposal-review.js");
const AUTH = read("auth.js");
const INDEX = read("js/index.js");
const NL = "\n";

// ── lifting the real source ──────────────────────────────────────────────────
/** `function name(...) {...}` at the given indent, braces balanced. */
function liftFn(src, file, name, indent) {
  const m = new RegExp("\\n" + indent + "(?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from " + file + " -- rewrite this harness, don't stub it");
  return balanced(src, m.index + 1, src.indexOf("{", m.index + m[0].length - 1), name);
}

/** From `from` to the brace that closes the one at `open`. */
function balanced(src, from, open, what) {
  let depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(from, j + 1);
  }
  throw new Error("unbalanced braces reading " + what);
}

/** A statement that starts with `head` and whose first `{` opens the body; `tail` follows the
 *  closing brace (the `);` of a listener, the `)();` of an IIFE). */
function liftStatement(src, file, head, tail) {
  const i = src.indexOf(head);
  if (i < 0) throw new Error(JSON.stringify(head) + " is gone from " + file + " -- rewrite this harness");
  const body = balanced(src, i, src.indexOf("{", i + head.length - 1), head);
  if (src.slice(i + body.length, i + body.length + tail.length) !== tail) {
    throw new Error(JSON.stringify(head) + " no longer ends with " + JSON.stringify(tail));
  }
  return body + tail;
}

function grab(src, re, what) {
  const m = re.exec(src);
  if (!m) throw new Error("could not lift " + what + " -- rewrite this harness, don't stub it");
  return m[0];
}

/** Bind lifted source to `deps` BY NAME and return the named values it defines. A callee missing
 *  from deps is an unbound identifier inside the lifted copy -- the failure that took prod down. */
function bind(code, deps, names) {
  const keys = Object.keys(deps);
  return new Function(...keys, code + NL + "return { " + names.join(", ") + " };")(
    ...keys.map((k) => deps[k]));
}

// ── the smallest DOM this code touches, with a real tokenizer for innerHTML ─────
const ENT = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
const decode = (s) => String(s).replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (all, k) => {
  if (k[0] === "#") return String.fromCodePoint(k[1] === "x" || k[1] === "X"
    ? parseInt(k.slice(2), 16) : parseInt(k.slice(1), 10));
  return Object.prototype.hasOwnProperty.call(ENT, k) ? ENT[k] : all;
});
const VOID = new Set(["BR", "IMG", "HR", "INPUT", "META", "LINK", "SOURCE", "WBR"]);
const TOKEN = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^\s"'>\/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*)\s*\/?>|([^<]+)|(<)/g;
const ATTR = /([^\s"'>\/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;

class Text {
  constructor(v) { this.nodeType = 3; this.nodeValue = String(v); this.parentNode = null; }
  get textContent() { return this.nodeValue; }
}

class El {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this.attrs = {};
    this.style = {};
    this.dataset = {};
    this._l = {};
    this._html = null;
    const self = this;
    this.classList = {
      add: (c) => { const s = new Set(self.className.split(/\s+/).filter(Boolean)); s.add(c); self.className = [...s].join(" "); },
      remove: (c) => { self.className = self.className.split(/\s+/).filter((x) => x && x !== c).join(" "); },
      contains: (c) => self.className.split(/\s+/).includes(c),
    };
  }
  get id() { return this.attrs.id || ""; }
  set id(v) { this.attrs.id = String(v); }
  get className() { return this.attrs.class || ""; }
  set className(v) { this.attrs.class = String(v); }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get options() { return this.children.filter((n) => n.tagName === "OPTION"); }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(""); }
  set textContent(v) {
    this.childNodes.slice().forEach((n) => this.removeChild(n));
    if (String(v) !== "") this.appendChild(new Text(v));
  }
  /** An <option>'s value is its value attribute, else its text; a <select>'s is its selected
   *  option's -- so `sel.value = cur` finding (or not finding) the saved texture is observable. */
  get value() {
    if (this.tagName === "SELECT") {
      const on = this.options.find((o) => o._selected);
      return on ? on.value : "";
    }
    if (this._value !== undefined) return this._value;
    if (this.attrs.value !== undefined) return this.attrs.value;
    return this.tagName === "OPTION" ? this.textContent : "";
  }
  set value(v) {
    if (this.tagName === "SELECT") {
      this.options.forEach((o) => { o._selected = false; });
      const hit = this.options.find((o) => o.value === String(v));
      if (hit) hit._selected = true;
      return;
    }
    this._value = String(v);
  }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    this.childNodes.push(c);
    return c;
  }
  removeChild(c) {
    const i = this.childNodes.indexOf(c);
    if (i >= 0) this.childNodes.splice(i, 1);
    c.parentNode = null;
    return c;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  replaceWith(other) {
    this._replacedBy = other;
    const p = this.parentNode;
    if (!p) return;
    const i = p.childNodes.indexOf(this);
    if (other.parentNode) other.parentNode.removeChild(other);
    p.childNodes[i] = other;
    other.parentNode = p;
    this.parentNode = null;
  }
  set innerHTML(html) {
    this._html = String(html);
    this.childNodes.slice().forEach((n) => this.removeChild(n));
    const stack = [this];
    let m;
    TOKEN.lastIndex = 0;
    while ((m = TOKEN.exec(this._html))) {
      const top = stack[stack.length - 1];
      if (m[1]) {
        const want = m[1].toUpperCase();
        for (let k = stack.length - 1; k > 0; k--) {
          if (stack[k].tagName === want) { stack.length = k; break; }
        }
      } else if (m[2]) {
        const el = new El(m[2]);
        ATTR.lastIndex = 0;
        let a;
        while ((a = ATTR.exec(m[3]))) {
          const v = a[2] !== undefined ? a[2] : a[3] !== undefined ? a[3] : a[4] !== undefined ? a[4] : "";
          el.attrs[a[1].toLowerCase()] = decode(v);
          if (a[1].startsWith("data-")) el.dataset[a[1].slice(5)] = decode(v);
        }
        top.appendChild(el);
        if (!VOID.has(el.tagName)) stack.push(el);
      } else if (m[4] !== undefined) {
        top.appendChild(new Text(decode(m[4])));
      } else if (m[5]) {
        top.appendChild(new Text("<"));
      }
    }
  }
  get innerHTML() { return this._html; }
  descendants() {
    const out = [];
    for (const c of this.children) { out.push(c); out.push(...c.descendants()); }
    return out;
  }
  querySelectorAll(sel) { return this.descendants().filter((e) => matches(e, sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  addEventListener(type, f) { (this._l[type] = this._l[type] || []).push(f); }
  fire(type, ev) { (this._l[type] || []).forEach((f) => f(Object.assign({ target: this, stopPropagation() {} }, ev || {}))); }
}

function matches(el, sel) {
  return String(sel).split(",").some((one) => {
    const part = one.trim();
    if (!part) return false;
    const tag = /^[a-zA-Z][\w-]*/.exec(part);
    if (tag && el.tagName !== tag[0].toUpperCase()) return false;
    const id = /#([\w-]+)/.exec(part);
    if (id && el.id !== id[1]) return false;
    for (const m of part.matchAll(/\.([\w-]+)/g)) if (!el.classList.contains(m[1])) return false;
    for (const m of part.matchAll(/\[([\w-]+)(?:=["']?([^\]"']*)["']?)?\]/g)) {
      const have = el.attrs[m[1]];
      if (have === undefined) return false;
      if (m[2] !== undefined && String(have) !== m[2]) return false;
    }
    return true;
  });
}

/** What a tree holds: its element tags, every attribute name, and its text. */
function census(root) {
  const els = root.descendants();
  return {
    tags: els.map((e) => e.tagName),
    attrNames: [...new Set(els.flatMap((e) => Object.keys(e.attrs)))].sort(),
    text: root.textContent,
  };
}

function makeDocument() {
  const body = new El("body");
  return {
    body,
    hidden: false,
    createElement: (t) => new El(t),
    getElementById: (id) => body.descendants().find((e) => e.id === id) || null,
    querySelector: (sel) => body.querySelector(sel),
    querySelectorAll: (sel) => body.querySelectorAll(sel),
    addEventListener() {},
  };
}

// The payloads. Everything markup-significant at once: a tag, an entity-looking ampersand, both
// quotes, and a tag that would run script if it were ever parsed as one.
const PAY = `<b>bold</b> & "dq" 'sq' <img src=x onerror=alert(1)>`;
const ATTR_PAY = `1" autofocus onfocus="alert(1)`;
const out = { PAY, ATTR_PAY };

// ═══ 1. THE AI-AUTOFILL BANNER ═══════════════════════════════════════════════
// The click listener is anonymous, so it is grabbed verbatim -- head to `});` -- and run as itself,
// with the real showAutofillBanner and the real escHtml behind it.
(async () => {
  {
    const document = makeDocument();
    const btn = new El("button");
    btn.id = "autofill-btn";
    document.body.appendChild(btn);
    const reply = { ok: true, cell_values: {
      "Epoxy!B4": PAY, "Epoxy!B6": "Yes", texture: PAY, system_name: "Quartz" } };
    const lifted = bind([
      liftFn(EST, "estimate-review.js", "escHtml", ""),
      liftFn(EST, "estimate-review.js", "showAutofillBanner", ""),
      liftStatement(EST, "estimate-review.js",
        'document.getElementById("autofill-btn").addEventListener("click", async (e) => {', ");"),
    ].join(NL), {
      document,
      state: { project_name: "P", address: "A", city_state: "C", notes: "n" },
      callAutofillEndpoint: async () => reply,
      cellValues: {},
      HF: { setCellValue() {} },
      applyJobFlags() {},
      // The autofill's two tax answers go through this now (the base sheet's, on a split draft);
      // bound so the lifted handler reaches its banner. jobFlagKindFor is only asked on a split draft.
      applyAutofillJobFlags() { return 0; },
      jobFlagKindFor() { return null; },
      // The handler skips a Hard Bid? answer through this (2026-10-03). This reply carries none,
      // and the rule itself is executed in no-hard-bid-harness.js / taxable-flag-harness.js.
      isHardBidFlagCell() { return false; },
      TW: { setState() {}, authHeaders: () => ({}), getDraftId: () => "d" },
      sysNameInput: { value: "" },
      texInput: { value: "" },
      icon: () => '<i class="ic"></i>',
      activeSheet: null,
      sheetCache: {},
      showSheet: async () => {},
      setTimeout: () => 0,
      console,
    }, ["escHtml"]);
    void lifted;
    await btn._l.click[0]({ target: btn });
    const banner = document.getElementById("autofill-banner");
    out.autofill = banner ? census(banner) : null;
  }

  // ═══ 2. THE TEXTURE <select>, BOTH PAGES ═════════════════════════════════════
  // A texture that is not one of the five is kept as the first option, and it is whatever the AI or
  // a saved draft put there.
  const estimateTexture = (texture) => {
    const document = makeDocument();
    const wrap = new El("label");
    const input = new El("input");
    input.id = "tex-name";
    wrap.appendChild(input);
    document.body.appendChild(wrap);
    const got = bind([
      grab(EST, /^const TEXTURE_OPTIONS = .*$/m, "TEXTURE_OPTIONS"),
      "let texInput = input;",
      liftStatement(EST, "estimate-review.js", "(function buildTextureControl() {", ")();"),
    ].join(NL), { document, input, state: { work_type: "epoxy", texture } }, ["texInput"]);
    const sel = got.texInput;
    return { tag: sel.tagName, value: sel.value,
             options: sel.options.map((o) => ({ value: o.value, text: o.textContent })),
             inPage: wrap.children[0] === sel, ...census(sel) };
  };
  out.texture = { estimate: { hostile: estimateTexture(PAY), onList: estimateTexture("Orange Peel") } };

  const proposalTexture = (texture) => {
    const document = makeDocument();
    const row = new El("div");
    row.id = "texture-row";
    const input = new El("input");
    input.className = "ro";
    input.attrs.name = "texture";
    row.appendChild(input);
    document.body.appendChild(row);
    document.querySelector = (sel) => (sel === '#texture-row input[name="texture"]'
      ? (row.children[0] === input ? input : null) : null);
    const got = bind(liftFn(PROP, "proposal-review.js", "buildTextureControl", "  "),
      { document, state: { texture }, effectiveWorkType: () => "epoxy" }, ["buildTextureControl"]);
    got.buildTextureControl();
    const sel = row.children[0];
    return { tag: sel.tagName, value: sel.value, className: sel.className,
             options: sel.options.map((o) => ({ value: o.value, text: o.textContent })), ...census(sel) };
  };
  out.texture.proposal = { hostile: proposalTexture(PAY), onList: proposalTexture("Medium") };

  // ═══ 3. THE MANUAL PRICE-LINE INPUTS ═════════════════════════════════════════
  // Both values sit inside value="...": an unescaped `"` ends the attribute and starts new ones.
  {
    const document = makeDocument();
    const list = new El("div"); list.id = "cb-pricelines";
    const head = new El("div"); head.id = "cb-pricelines-head";
    document.body.appendChild(head); document.body.appendChild(list);
    const state = { price_lines: [{ label: PAY, amount: ATTR_PAY }, { label: "Mockup", amount: 250 }],
                    price_overrides: {} };
    const api = bind([
      "let PRICE_LINES = state.price_lines.slice();",
      liftFn(EST, "estimate-review.js", "escHtml", ""),
      liftFn(EST, "estimate-review.js", "reKeyPriceLineOverrides", ""),
      liftFn(EST, "estimate-review.js", "persistPriceLines", ""),
      liftFn(EST, "estimate-review.js", "renderPriceLines", ""),
    ].join(NL), { state, document, TW: { setState() {} } }, ["renderPriceLines"]);
    api.renderPriceLines();
    out.priceLines = list.children.map((row) => {
      const inputs = row.querySelectorAll("input");
      return {
        ...census(row),
        label: inputs[0] ? inputs[0].attrs.value : null,
        amount: inputs[1] ? inputs[1].attrs.value : null,
        amountAttrs: inputs[1] ? Object.keys(inputs[1].attrs).sort() : null,
      };
    });
  }

  // ═══ 4. NOTIFICATION LINKS ═══════════════════════════════════════════════════
  // The real mountNotifications, polled once against a stub /api/notifications that answers ONE
  // item: the bell list's <a href> is read off its parsed markup, and the toast is clicked for real
  // to see where the page is sent.
  const ORIGIN = "https://proposals.wetreadwell.com";
  const bell = async (link) => {
    const document = makeDocument();
    const bellBtn = new El("button"); bellBtn.id = "tw-bell";
    document.body.appendChild(bellBtn);
    const sent = [];
    const location = {
      origin: ORIGIN,
      get href() { return ORIGIN + "/crm.html"; },
      set href(v) { sent.push(String(v)); },
    };
    const item = { id: "m1", kind: "portal_message", ts: "2026-09-29T12:00:00Z", icon: "info",
                   severity: "info", title: "Customer", body: "Hello", link };
    const api = bind([
      liftFn(AUTH, "auth.js", "esc", "  "),
      liftFn(AUTH, "auth.js", "safeNotifLink", "  "),
      liftFn(AUTH, "auth.js", "mountNotifications", "  "),
    ].join(NL), {
      document, location, window: {},
      icon: () => "",
      apiBase: () => "",
      localStorage: { getItem: () => null, setItem() {} },
      requestAnimationFrame: (f) => f(),
      setTimeout: () => 0,
      setInterval: () => 0,
      fetch: async () => ({ json: async () => ({ ok: true, notifications: [item], unread: 1,
                                                  last_seen_at: "" }) }),
    }, ["mountNotifications", "safeNotifLink"]);
    api.mountNotifications();
    for (let k = 0; k < 5; k++) await new Promise((r) => setImmediate(r));
    const toast = document.body.querySelector(".tw-toast");
    if (toast) toast.fire("click");
    bellBtn.fire("click");
    const a = document.body.querySelector("a.tw-notif-item");
    return { href: a ? a.attrs.href : null, navigated: sent, toasted: !!toast,
             safe: api.safeNotifLink(link) };
  };
  const LINKS = {
    // the ones notifications.py actually sends
    crm: "/crm.html",
    draft: "/?d=abc123&edit=1",
    portal: "/portal.html?open=p1",
    dropbox: "https://www.dropbox.com/scl/fo/abc/def?dl=0",
    ownOrigin: ORIGIN + "/leads.html",
    // the ones it must never follow
    js: "javascript:alert(document.cookie)",
    jsMixedCase: "JaVaScRiPt:alert(1)",
    jsLeadingSpace: " javascript:alert(1)",
    data: "data:text/html,<script>alert(1)</script>",
    protocolRelative: "//evil.example/x",
    backslash: "/\\evil.example/x",
    tabToSlashes: "/\t/evil.example/x",
    offSite: "https://evil.example/login",
    plainHttpOwnHost: "http://proposals.wetreadwell.com/crm.html",
    lookalikeDropbox: "https://www.dropbox.com.evil.example/x",
    // the Dropbox host under another scheme: the URL parser still reports hostname
    // "www.dropbox.com", so only the https-scheme check stands between these and a click
    jsOnDropboxHost: "javascript://www.dropbox.com/%0Aalert(document.domain)",
    httpDropbox: "http://www.dropbox.com/scl/fo/x",
    ftpDropbox: "ftp://dropbox.com/x",
  };
  out.links = {};
  for (const [k, v] of Object.entries(LINKS)) out.links[k] = { link: v, ...(await bell(v)) };

  // ═══ 5. THE ESCAPE HELPERS THAT MISSED THE SINGLE QUOTE ══════════════════════
  // js/address-lookup.js's two renderers (moved out of index.js 2026-10-05), run for real: the
  // actual module is mounted on stub inputs, a Photon-shaped answer comes back through a stub
  // fetch, and the markup it wrote into the dropdown is what gets counted.
  const intake = (which) => {
    const doc = makeDocument();
    const mk = (id) => { const e = new El("div"); e.id = id; doc.body.appendChild(e); return e; };
    const els = { address: mk("address-input"), business: mk("business-input"),
                  city: mk("city-input"), state: mk("state-input"), zip: mk("zip-input") };
    const results = { renderAddr: mk("address-results"), renderBusinesses: mk("business-results") };
    els.address.value = "12 Main St"; els.business.value = "Acme";
    const feature = { properties: { name: PAY, housenumber: "12", street: PAY, city: "O'Fallon",
                                    state: "Missouri", postcode: "63366" } };
    const fakeFetch = async () => ({ json: async () => ({ features: [feature] }) });
    const win = {};
    new Function("document", "window", "fetch", "setTimeout", "clearTimeout",
                 read("js/address-lookup.js"))(doc, win, fakeFetch, (f) => { f(); return 1; }, () => {});
    win.TWAddress.mount(els);
    const target = which === "renderAddr" ? els.address : els.business;
    target._l.input.forEach((f) => f());
    return new Promise((res) => setTimeout(res, 20)).then(() => {
      const r = results[which];
      return { markup: r.innerHTML, ...census(r) };
    });
  };
  out.intake = { renderAddr: await intake("renderAddr"), renderBusinesses: await intake("renderBusinesses") };

  // estimate-review.js's bid-bar escape, called as itself.
  out.escBB = bind(grab(EST, /^const _escBB = [^\n]*\n[^\n]*;$/m, "_escBB"), {}, ["_escBB"])._escBB(PAY);

  process.stdout.write(JSON.stringify(out) + "\n");
})().catch((e) => { process.stderr.write(String(e && e.stack || e) + "\n"); process.exit(1); });
