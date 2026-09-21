// Which tab you were on, in the URL — so a reload puts you back on it.
//
// WHY THIS FILE EXISTS. Hanz, on staging: "when I reload the page, why does it automatically land
// on assemblies? and not on the tab that I have under items and assemblies also find any
// functionality that does that when I refresh the page it should stay on the same page that I was
// on or editing". Every tabbed screen in this app answered that the same way: the open tab was a
// module variable with a literal default, so F5 threw the estimator back to whatever the code
// picked rather than to what they were reading.
//
// WHY THE URL AND NOT STORAGE. The address bar is the honest home for "which tab am I on". It
// survives a reload, it is what a bookmark keeps, it is what somebody gets when the link is pasted
// into a message, and Back from another page restores it for free. localStorage does none of that:
// it is per browser, invisible to whoever you send the link to, and reading it THROWS in a private
// window or with site data blocked. Nothing here touches storage, which is why nothing here needs a
// try/catch around one.
//
// It is NOT the draft blob either. Every save PUTs the whole blob, so two tabs clobber each other —
// and which pane somebody is looking at is not project data.
//
// THE FRAGMENT, NOT THE QUERY. `?d=<uuid>` already means "the draft this page is editing" and
// shared.js adopts whatever it finds there; a second query key sits inside that contract. The
// fragment is also never sent to the server, which is right for a view preference, and root-path.js
// deliberately KEEPS the fragment while dropping the query when it rewrites "/" to "/portal.html".
//
// The shape is `#key=value&key=value`, so one page can remember two things — Items and Assemblies
// remembers the tab AND, on the Defaults tab, which of the five work types is showing. Landing on
// the right tab and the wrong work type is the same bug one level down.
//
// Externalized (CSP: no inline scripts). Do not add inline scripts.
(function (root, factory) {
  var api = factory();
  root.TWTabMemo = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /** `#tab=defaults&wt=epoxy` → `{ tab: "defaults", wt: "epoxy" }`.
   *
   *  Anything it cannot read comes back as no keys rather than as a throw: a hand-typed fragment, a
   *  stale link in an older shape, a lone `#`. The caller then falls back to its own default, which
   *  is exactly the behaviour this module is replacing — never a broken page. */
  function parse(hash) {
    var out = {};
    var s = String(hash == null ? "" : hash);
    if (s.charAt(0) === "#") s = s.slice(1);
    if (!s) return out;
    var parts = s.split("&");
    for (var i = 0; i < parts.length; i++) {
      if (!parts[i]) continue;
      var eq = parts[i].indexOf("=");
      var k = eq < 0 ? parts[i] : parts[i].slice(0, eq);
      var v = eq < 0 ? "" : parts[i].slice(eq + 1);
      // A stray "%" is a URIError, and one bad pair must not cost the other pair its value.
      try { k = decodeURIComponent(k); } catch (e) { /* keep the raw key */ }
      try { v = decodeURIComponent(v); } catch (e) { v = ""; }
      if (k) out[k] = v;
    }
    return out;
  }

  /** The inverse. An empty object is the empty string and NOT "#": a bare hash is a scroll target
   *  in its own right, and it leaves a stub in the address bar that says nothing. */
  function stringify(obj) {
    var keys = Object.keys(obj || {});
    var parts = [];
    for (var i = 0; i < keys.length; i++) {
      var v = obj[keys[i]];
      if (v === null || v === undefined || v === "") continue;
      parts.push(encodeURIComponent(keys[i]) + "=" + encodeURIComponent(String(v)));
    }
    return parts.length ? "#" + parts.join("&") : "";
  }

  /** The tab to actually show: the remembered one while it is still on offer, the caller's own
   *  default otherwise.
   *
   *  THIS IS THE SAFETY RULE, and it is why every page routes through one function. A remembered
   *  tab can stop existing between two page loads — a copied worksheet deleted, a markup layout the
   *  API no longer serves, a cadence email the portal stopped offering, a pane this role may not
   *  see. Showing it anyway is an empty pane or a permission error, which is a worse page than the
   *  one being fixed here. `allowed` is what the page is prepared to render RIGHT NOW, asked at
   *  restore time, so the check cannot go stale. */
  function pick(wanted, allowed, fallback) {
    var list = allowed || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i] === wanted) return wanted;
    }
    return fallback === undefined ? "" : fallback;
  }

  /** One remembered value off `win.location.hash`, or "" — never a throw.
   *
   *  Takes the window rather than reading a global, so a test can hand it one. */
  function read(win, key) {
    var hash = "";
    try { hash = (win && win.location && win.location.hash) || ""; } catch (e) { hash = ""; }
    var all = parse(hash);
    return Object.prototype.hasOwnProperty.call(all, key) ? all[key] : "";
  }

  /** Merge `patch` into the fragment. True when the address bar now says so.
   *
   *  replaceState, NEVER pushState. A tab click is not a navigation: pushing one would make Back
   *  walk backwards through four tabs before it left the page, and on a screen with a strip of
   *  sixteen worksheet tabs that is unusable. Replacing still gives the reload, the bookmark, the
   *  shared link, and Back-from-another-page landing on the tab you left.
   *
   *  A key set to "" or null is REMOVED, so a page can drop a value that no longer applies instead
   *  of leaving a dead one in the URL.
   *
   *  Unchanged is a no-op. Every one of these pages calls its renderer again after an unrelated
   *  edit, and without this check one estimate screen rewrites its own URL on every repaint. */
  function write(win, patch) {
    try {
      var loc = win && win.location;
      var hist = win && win.history;
      if (!loc || !hist || typeof hist.replaceState !== "function") return false;
      var next = parse(loc.hash || "");
      var keys = Object.keys(patch || {});
      for (var i = 0; i < keys.length; i++) {
        var v = patch[keys[i]];
        if (v === null || v === undefined || v === "") delete next[keys[i]];
        else next[keys[i]] = String(v);
      }
      var hash = stringify(next);
      if (String(loc.hash || "") === hash) return true;
      // pathname + search kept verbatim. `?d=<uuid>` is the draft this page is editing, and a
      // replaceState given a bare fragment is fine in a browser but drops the query anywhere the
      // string is resolved by hand.
      hist.replaceState(null, "", String(loc.pathname || "") + String(loc.search || "") + hash);
      return true;
    } catch (e) {
      // A sandboxed frame throws SecurityError on replaceState. The tab still switches; it just is
      // not there after a reload, which is exactly where the page was before this file existed.
      return false;
    }
  }

  return { parse: parse, stringify: stringify, pick: pick, read: read, write: write };
});
