/* SEND ALL BUILDS WHAT WAS NEVER BUILT (Hanz, 2026-10-28).
 *
 * "When I add a new base bid, and add a new proposal in this set of proposals, I'm not able to send
 * it." A proposal made by Create Multiple Proposals starts with no document, and the project's one
 * press (main.py api_scope_group_send_all) refused it: "Room 2: build its files on its Files page
 * first". Hanz chose: build it automatically, exactly as if the estimator had opened its tab and
 * pressed Continue with no edits, then send the one email.
 *
 * WHY THE PAGES FLIP BY, AND NOT A SECOND BUILDER. A proposal's document is composed in exactly one
 * place, the Proposal step's continueToDone (computeTokenValues, the template's version, the notes,
 * the cover letter, the composeKey stamp), and the Files page's door already presses it unattended
 * (proposal-review.js composeForFiles, `?compose=files`). So when the press answers `needs_build`,
 * this file walks the tab through that door once per proposal named, and then back to the page that
 * pressed, which presses again. The document is the manual path's because it IS the manual path's
 * code. A copy in Python, or in a hidden frame, was the alternative; the first would drift, and the
 * second would take the one localStorage blob every page shares away from the page that pressed.
 *
 * WHAT KEEPS AN UNATTENDED SEND SAFE. The walk is held in sessionStorage (this tab only) under a
 * random token the URLs carry, for ten minutes at most. Any door that stops (no template, a base with
 * no price, a copy saved elsewhere, a save refused) abandons it, so nothing is ever sent after a
 * build that did not happen. The resume is taken once, only by the page of the same project, and a
 * page that has resumed never starts another walk (a second `needs_build` is said in words).
 * A document a door builds on a walk is marked `proposal_auto_built` (proposal-review.js
 * continueToDone), and the press holds one that still prints Kyle's template placeholders
 * ("xx gallons", "-or-" choices; main._send_all_placeholders) until a person composes it.
 *
 * window.TWSendAll: start, nextHop, abandon, progress, take. Node (tests): module.exports.create(root),
 * where root carries sessionStorage, location, history and (optionally) crypto and Date.
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = { create: factory };
  if (typeof window !== "undefined" && root === window) root.TWSendAll = factory(root);
})(typeof window !== "undefined" ? window : this, function (root) {
  "use strict";
  var KEY = "treadwell.sendall.chain";
  var TTL_MS = 10 * 60 * 1000;
  var ID_RE = /^[A-Za-z0-9_-]{1,80}$/;
  var resumed = {};               // groups this page has already resumed a walk for

  function store() {
    try { return root.sessionStorage || null; } catch (e) { return null; }
  }
  function now() { return (root.Date || Date).now(); }
  function read() {
    var s = store();
    if (!s) return null;
    try {
      var r = JSON.parse(s.getItem(KEY) || "null");
      return r && typeof r === "object" && typeof r.token === "string" ? r : null;
    } catch (e) { return null; }
  }
  function write(r) {
    var s = store();
    if (!s) return false;
    try { s.setItem(KEY, JSON.stringify(r)); } catch (e) { return false; }
    var back = read();
    return !!back && back.token === r.token;
  }
  function clear() {
    var s = store();
    try { if (s) s.removeItem(KEY); } catch (e) { /* nothing to undo */ }
  }
  function token() {
    var out = "";
    try {
      var a = new Uint8Array(16);
      root.crypto.getRandomValues(a);
      for (var i = 0; i < a.length; i++) out += ("0" + a[i].toString(16)).slice(-2);
    } catch (e) { out = ""; }
    if (out.length < 32) {
      out = "";
      for (var j = 0; j < 4; j++) out += Math.floor(Math.random() * 0x100000000).toString(16);
    }
    return out;
  }
  function doorUrl(id, tok) {
    return "/proposal-review.html?d=" + encodeURIComponent(id) + "&compose=files&sendall="
      + encodeURIComponent(tok);
  }
  /** `url` without this file's own two parameters (a walk never rides a walk's URL). */
  function stripOwn(url) {
    var s = String(url || "");
    var hash = "";
    var h = s.indexOf("#");
    if (h >= 0) { hash = s.slice(h); s = s.slice(0, h); }
    var q = s.indexOf("?");
    if (q < 0) return s + hash;
    var kept = s.slice(q + 1).split("&").filter(function (kv) {
      var k = kv.split("=")[0];
      return kv && k !== "sendall" && k !== "sendall_resume";
    });
    return s.slice(0, q) + (kept.length ? "?" + kept.join("&") : "") + hash;
  }
  function withParam(url, k, v) {
    var s = String(url || "");
    var h = s.indexOf("#");
    var hash = h >= 0 ? s.slice(h) : "";
    if (h >= 0) s = s.slice(0, h);
    return s + (s.indexOf("?") >= 0 ? "&" : "?") + k + "=" + encodeURIComponent(v) + hash;
  }
  function get(params, k) {
    try { return params && params.get ? params.get(k) : null; } catch (e) { return null; }
  }
  /** The walk this door page belongs to, when its token is the live one. */
  function live(params) {
    var tok = get(params, "sendall");
    var r = tok ? read() : null;
    if (!r || r.token !== tok || r.done) return null;
    if (!(r.expires > now())) { clear(); return null; }
    return r;
  }

  /** Begin the walk: `o.build` [{id, label}] are the proposals the press named, `o.returnUrl` the
   *  page that pressed, `o.stash` what that page needs to press again. Leaves for the first door and
   *  answers true; false (nothing written, nowhere gone) when it cannot, so the caller says the
   *  press's own sentence instead. */
  function start(o) {
    o = o || {};
    var group = String(o.group || "");
    var build = Array.isArray(o.build) ? o.build : [];
    var ids = build.map(function (b) { return String((b && b.id) || ""); });
    if (!group || !ids.length || ids.some(function (id) { return !ID_RE.test(id); })) return false;
    if (resumed[group]) return false;     // built once already from this page: never round again
    var labels = {};
    build.forEach(function (b) { labels[String(b.id)] = String(b.label || "A proposal"); });
    var r = { token: token(), group: group, queue: ids, built: [], labels: labels,
              returnUrl: stripOwn(o.returnUrl || "/portal.html"), stash: o.stash || null,
              expires: now() + TTL_MS, done: false };
    if (!write(r)) return false;
    try { root.location.assign(doorUrl(ids[0], r.token)); } catch (e) { clear(); return false; }
    return true;
  }

  /** Where a door that has just saved its document goes next: the next proposal's door, or back to
   *  the page that pressed with `sendall_resume`. null when this page is not on a live walk, which
   *  leaves continueToDone to go to its own Files page as it always has. */
  function nextHop(params) {
    var r = live(params);
    if (!r) return null;
    var id = get(params, "d");
    if (r.queue[0] !== id) { clear(); return null; }    // not the door the walk is at: stop it
    r.queue.shift();
    r.built.push(id);
    if (r.queue.length) return write(r) ? doorUrl(r.queue[0], r.token) : null;
    r.done = true;
    return write(r) ? withParam(r.returnUrl, "sendall_resume", r.token) : null;
  }

  /** A door that stopped: the walk ends here and nothing is sent. Answers what it was doing
   *  ({label, i, n}) so the page can say so, or null when it was not on one. */
  function abandon(params) {
    var tok = get(params, "sendall");
    var r = tok ? read() : null;
    if (!r || r.token !== tok) return null;
    var p = progressOf(r, get(params, "d"));
    clear();
    return p;
  }

  function progressOf(r, id) {
    var n = r.built.length + r.queue.length;
    return { label: r.labels[id] || "A proposal", i: Math.min(r.built.length + 1, n), n: n };
  }

  /** {label, i, n} for this door's banner, or null. */
  function progress(params) {
    var r = live(params);
    return r ? progressOf(r, get(params, "d")) : null;
  }

  /** The finished walk, ONCE, for the page that pressed (`group` is its project): {stash, built,
   *  labels}. Null for anything else, and the record is gone either way: an expired walk, another
   *  project's, one that never finished, or one already taken never presses anything. */
  function take(params, group) {
    var tok = get(params, "sendall_resume");
    if (!tok) return null;
    try {
      var loc = root.location;
      var bare = stripOwn(loc.pathname + loc.search + (loc.hash || ""));
      if (bare !== loc.pathname + loc.search + (loc.hash || "")) root.history.replaceState(null, "", bare);
    } catch (e) { /* the address bar keeps it; the record below is single-use regardless */ }
    var r = read();
    if (!r || r.token !== tok) return null;
    clear();
    if (!r.done || !group || r.group !== String(group) || !(r.expires > now())) return null;
    resumed[r.group] = true;
    return { stash: r.stash, built: r.built.slice(), labels: r.labels };
  }

  return { start: start, nextHop: nextHop, abandon: abandon, progress: progress, take: take,
           KEY: KEY, TTL_MS: TTL_MS };
});
