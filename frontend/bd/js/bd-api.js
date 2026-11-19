/* The BD CRM's one door to its API, as window.BDApi (#806, spec #802 Q6).
 *
 *   BDApi.get(path) . post(path, body, opts) . patch(path, body) . put(path, body) . del(path)
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
 * the status's.
 *
 * BD's old mock mode (mock data, the ?mock and ?as switches, the preview gate) is gone: every call
 * goes to the server. Load order: the tool's shell (Supabase SDK, /js/icons.js, /auth.js,
 * /shared.js), then bd-icons.js, THIS FILE, bd-shared.js, bd-core.js, the page's own scripts.
 */
(function () {
  "use strict";

  var BASE = "/api/bd/";

  var STATUS_CODE = { 400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
    409: "conflict", 413: "too_large", 429: "rate_limited", 500: "error", 503: "unavailable" };
  var CODE = /^[a-z][a-z_]*$/;

  function apiError(status, code, message, fields) {
    var e = new Error(message || "Something went wrong.");
    e.status = status; e.code = code; if (fields) e.fields = fields;
    return e;
  }

  /** The sentence for a failed response whose body is not ours (an nginx 502 page, say). */
  function plainFailure(status, statusText) {
    if (status >= 500) return "The server had a problem. Try again in a minute.";
    return statusText || "Something went wrong.";
  }

  /** A path this door may send: under /api/bd/, one leading slash, no way back up the tree. */
  function isBdPath(path) {
    var p = String(path == null ? "" : path);
    return p.indexOf(BASE) === 0 && !/(^|\/)\.\.?(\/|$|\?)/.test(p) && p.indexOf("\\") === -1;
  }

  /** {message, code, fields} from a failed JSON body: BD's envelope, or the tool's gate's. */
  function readFailure(status, statusText, data) {
    var d = data && typeof data === "object" ? data : {};
    var err = typeof d.error === "string" ? d.error : "";
    var message = typeof d.message === "string" && d.message ? d.message
      : (err && !CODE.test(err) ? err : plainFailure(status, statusText));
    var code = err && CODE.test(err) ? err : (STATUS_CODE[status] || "error");
    return { message: message, code: code, fields: d.fields };
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
          if (!res.ok) throw apiError(res.status, STATUS_CODE[res.status] || "error", plainFailure(res.status, res.statusText));
          return text;
        });
      }
      return res.json().then(function (data) {
        if (!res.ok || (data && data.ok === false)) {
          var f = readFailure(res.status, res.statusText, data);
          throw apiError(res.status, f.code, f.message, f.fields);
        }
        return data;
      });
    }, function (e) {
      if (e && e.status) throw e;
      throw apiError(0, "network", "Can't reach the server. Check your connection and try again.");
    });
  }

  window.BDApi = {
    base: BASE,
    get: function (path) { return request("GET", path); },
    /** opts.keepalive: the request survives the page closing. */
    post: function (path, body, opts) { return request("POST", path, body === undefined ? {} : body, opts); },
    patch: function (path, body) { return request("PATCH", path, body || {}); },
    put: function (path, body) { return request("PUT", path, body || {}); },
    del: function (path) { return request("DELETE", path); },
  };
})();
