/* The BD CRM's one door to its API, as window.BDApi (#806, spec #802 Q6).
 *
 *   BDApi.get(path) . post(path, body, opts) . patch(path, body) . put(path, body) . del(path)
 *   BDApi.path("tasks", 7, "done")  ->  "/api/bd/tasks/7/done"   (each part encoded)
 *
 * Every call returns a Promise of the JSON in docs/bd/api-contract.md, or rejects with an Error whose
 * .message is the plain sentence to show, plus .status (HTTP; 0 when the server could not be
 * reached), .code ("not_found", "forbidden", ...) and .fields (per-field messages on a 400).
 *
 * ONLY /api/bd/. A path is written in full, the way the contract writes it ("/api/bd/me"), and a path
 * that is not under /api/bd/ is refused here without a request: BD's pages never call one of the
 * tool's own routes through this door.
 *
 * SIGN-IN IS THE TOOL'S. The bearer token is the one /auth.js holds (TWAuth.token()), and a call
 * waits for TWAuth.tokenReady, so nothing is sent before there is a token to send.
 *
 * TWO ERROR SHAPES. A BD route answers {ok: false, error: "<code>", message: "<sentence>"}. The tool's
 * own sign-in gate, which every /api/bd/ request passes first, answers 401 and 403 as
 * {ok: false, error: "<sentence>"} with no message: that sentence is what is shown, and the code is
 * the status's. Both are read by TWAuth.bdFailure (/auth.js), the one reader the sidebar's BD group
 * and the BD home page use too, so a failure reads the same wherever it is shown.
 *
 * ONLY /api/bd/, CHECKED AFTER RESOLVING. A path is resolved the way fetch will resolve it before it
 * is checked, so an encoded dot segment ("%2e%2e") cannot climb out of /api/bd/.
 *
 * BD's old mock mode (mock data, the ?mock and ?as switches, the preview gate) is gone: every call
 * goes to the server. Load order: the tool's shell (Supabase SDK, /js/icons.js, /auth.js,
 * /shared.js, /js/crm-core.js), then THIS FILE, bd-shared.js, bd-core.js, the page's own scripts.
 */
(function () {
  "use strict";

  var BASE = "/api/bd/";

  function apiError(status, code, message, fields) {
    var e = new Error(message || "Something went wrong.");
    e.status = status; e.code = code; if (fields) e.fields = fields;
    return e;
  }

  /** A path this door may send: written from the site root, under /api/bd/, and left exactly as it
   *  was when resolved the way fetch resolves it. A dot segment, plain or percent-encoded ("%2e%2e"),
   *  is collapsed by that resolving, so a path carrying one is refused rather than sent somewhere
   *  else. No backslash (a browser reads it as a slash), no encoded slash or backslash, no control
   *  character. */
  function isBdPath(path) {
    var p = String(path == null ? "" : path);
    if (p.indexOf(BASE) !== 0 || /[\\\u0000-\u001f\u007f]|%2f|%5c/i.test(p)) return false;
    var origin = (window.location && window.location.origin) || "https://bd.invalid";
    var u;
    try { u = new URL(p, origin); } catch (e) { return false; }
    return u.origin === new URL(origin).origin && u.pathname === p.split(/[?#]/)[0] &&
      u.pathname.indexOf(BASE) === 0;
  }

  /** {message, code, fields} from a failed answer: TWAuth.bdFailure's words, and BD's fields. */
  function readFailure(status, data) {
    var f = window.TWAuth.bdFailure(status, data);
    return { message: f.message, code: f.code, fields: data && typeof data === "object" ? data.fields : undefined };
  }

  function request(method, path, body, opts) {
    if (!isBdPath(path)) {
      return Promise.reject(apiError(0, "bad_request", "That is not a BD CRM address: " + String(path) + "."));
    }
    var auth = window.TWAuth;
    var wait = auth && auth.tokenReady ? auth.tokenReady : Promise.resolve();
    return wait.then(function () {
      var headers = { Accept: "application/json" };
      var token = auth && typeof auth.token === "function" ? auth.token() : null;
      if (token) headers.Authorization = "Bearer " + token;
      var init = { method: method, headers: headers };
      // keepalive lets a call sent while the page is closing still land.
      if (opts && opts.keepalive) init.keepalive = true;
      if (body !== undefined && body !== null) {
        if (typeof FormData !== "undefined" && body instanceof FormData) init.body = body;
        else { headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
      }
      return fetch((window.TW_API_BASE || "") + path, init);
    }).then(function (res) {
      var type = (res.headers && res.headers.get && res.headers.get("content-type")) || "";
      if (type.indexOf("application/json") === -1) {
        return res.text().then(function (text) {
          if (!res.ok) {
            var p = readFailure(res.status, null);
            throw apiError(res.status, p.code, p.message);
          }
          return text;
        });
      }
      return res.json().then(function (data) {
        if (!res.ok || (data && data.ok === false)) {
          var f = readFailure(res.status, data);
          throw apiError(res.status, f.code, f.message, f.fields);
        }
        return data;
      });
    }, function (e) {
      if (e && e.status) throw e;
      var n = readFailure(0, null);
      throw apiError(0, n.code, n.message);
    });
  }

  /** A BD route's address from its parts, each one encoded: path("contacts", 21, "interactions") is
   *  "/api/bd/contacts/21/interactions". For a path with an id in it; a fixed one is written out. */
  function path() {
    return BASE + Array.prototype.map.call(arguments, function (p) { return encodeURIComponent(String(p)); }).join("/");
  }

  window.BDApi = {
    base: BASE,
    path: path,
    get: function (path) { return request("GET", path); },
    /** opts.keepalive: the request survives the page closing. */
    post: function (path, body, opts) { return request("POST", path, body === undefined ? {} : body, opts); },
    patch: function (path, body) { return request("PATCH", path, body || {}); },
    put: function (path, body) { return request("PUT", path, body || {}); },
    del: function (path) { return request("DELETE", path); },
  };
})();
