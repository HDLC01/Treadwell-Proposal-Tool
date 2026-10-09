// THE INTAKE'S QUANTITY FIELDS: draws them and shows the ones a job type asks for. Externalized (CSP: no
// inline scripts). Do not add inline scripts.
//
// WHY THIS FILE EXISTS. js/index.js used to hold its own copy of two facts that js/work-types.js already
// owns: which quantity fields exist and what they are called (systemFieldNames), and which of them each job
// type shows (SCOPE_BY_WORK_TYPE). Phase 9 of the v2 estimating program gives a fact one home, so the live
// intake draws and shows its fields from here, and the v2 intake can draw the same block without a second
// copy. This module owns the WORDS beside each field and the LAYOUT of a system block (which fields share a
// row); everything else comes from the vocabulary.
//
// WHAT IT DOES NOT DO. It does not read the page, the draft or the radios. The caller says which job type
// it means, every time: there is no default here, because a default is a guess, and the intake's own
// "epoxy when nothing is picked" is the page's rule, not the vocabulary's. A missing or unknown job type
// throws by name.
//
// HIDE, NEVER REMOVE. A field the job type does not ask for is hidden, not deleted: the field names are what
// saved drafts and the estimate-cell mappings key on, and a value typed under Combo is still there when
// somebody switches back. Keeping an orphaned value out of the sheet is estimate-review's job.
(function (root, factory) {
  var workTypes = (typeof module !== "undefined" && module.exports && typeof require === "function")
    ? require("./work-types.js") : root.TWWorkTypes;
  var api = factory(workTypes);
  root.TWIntakeScope = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function (workTypes) {
  "use strict";
  if (!workTypes) throw new Error("intake-scope.js needs work-types.js loaded before it");

  // The words beside each field. A label's text is ONE line, because the markup below is compared byte for
  // byte with what the intake rendered before this module existed.
  var LABELS = { epoxy: "Epoxy floor SF", polish: "Polish floor SF", cove: "Cove LF (epoxy)" };

  // Which fields share a row in a system block: epoxy and polish area side by side, cove under them.
  var ROWS = [["epoxy", "polish"], ["cove"]];

  function said(v) { return v === undefined ? "nothing" : JSON.stringify(v); }

  /** The job type, or a throw: the caller always says which one it means. */
  function need(jobType, who) {
    if (jobType === undefined || jobType === null || jobType === "") {
      throw new Error("intake-scope.js: " + who + "() needs the job type and was given " + said(jobType));
    }
    return jobType;
  }

  /** The names of system `k`'s fields, {epoxy, polish, cove}, read off the vocabulary. */
  function systemFieldNames(k) {
    var out = {};
    workTypes.FIELDS.forEach(function (f) { if (f.system === k) out[f.scope] = f.name; });
    if (!out.epoxy || !out.polish || !out.cove) {
      throw new Error("intake-scope.js: systemFieldNames() was asked about system " + said(k) +
        ", which work-types.js has no quantity fields for");
    }
    return out;
  }

  /** The number of systems the vocabulary has fields for. */
  function systemCount() {
    var most = 0;
    workTypes.FIELDS.forEach(function (f) { if (f.system > most) most = f.system; });
    return most;
  }

  /** The intake's data-scope tokens a job type shows in the system block ("epoxy", "polish", "cove"). Gypsum
   *  has its own box and shows none. */
  function scopesFor(jobType) {
    return workTypes.scopesFor(need(jobType, "scopesFor"));
  }

  /** The markup of `n` system blocks, as a string. The same for every job type: the job type only decides
   *  what is SHOWN (applyScope), never what exists. */
  function systemsMarkup(n) {
    n = Math.max(1, Math.min(systemCount(), parseInt(n, 10) || 1));
    var html = "";
    for (var k = 1; k <= n; k++) {
      var f = systemFieldNames(k);
      var label = k === 2 ? "System " + k + " (optional)" : "System " + k;
      var tag = n > 1 ? '<div class="system-tag">' + label + "</div>" : "";
      // data-scope drives which job types each field belongs to (see applyScope). Asking an epoxy job for
      // Polish floor SF, or a polish job for cove, is how an intake form teaches people to ignore it.
      html += '\n        <div class="system-block">\n          ' + tag;
      ROWS.forEach(function (row) {
        html += '\n          <div class="row">';
        row.forEach(function (scope) {
          html += '\n            <label data-scope="' + scope + '">' + LABELS[scope] +
            '\n              <input type="number" name="' + f[scope] + '" min="0" step="1" value="0">' +
            "\n            </label>";
        });
        html += "\n          </div>";
      });
      html += "\n        </div>";
    }
    return html;
  }

  /** Draws `n` system blocks into `container`, keeping anything already typed in a field of the same name. */
  function renderSystems(container, n) {
    if (!container) throw new Error("intake-scope.js: renderSystems() needs the container to draw into");
    // Preserve anything already typed before we rebuild the markup.
    var prev = {};
    container.querySelectorAll("input[name]").forEach(function (i) { prev[i.name] = i.value; });
    container.innerHTML = systemsMarkup(n);
    // Restore preserved values into the rebuilt fields.
    container.querySelectorAll("input[name]").forEach(function (i) {
      if (prev[i.name] != null && prev[i.name] !== "") i.value = prev[i.name];
    });
  }

  /** Shows the quantity fields `jobType` asks for and hides the rest. `parts` is {systems, gyp}: the system
   *  block's container and the gypsum box, either of which a page may not have. */
  function applyScope(jobType, parts) {
    need(jobType, "applyScope");
    var systems = parts && parts.systems, gyp = parts && parts.gyp;
    var isGyp = jobType === "gyp";
    var allowed = scopesFor(jobType);
    if (gyp) gyp.style.display = isGyp ? "" : "none";
    if (systems) systems.style.display = isGyp ? "none" : "";

    // Hide, never remove (see the header).
    (systems ? systems.querySelectorAll("[data-scope]") : []).forEach(function (el) {
      el.style.display = allowed.indexOf(el.getAttribute("data-scope")) !== -1 ? "" : "none";
    });
    // A row whose every field is hidden would otherwise leave an empty gap.
    (systems ? systems.querySelectorAll(".row") : []).forEach(function (row) {
      var fields = row.querySelectorAll("[data-scope]");
      var anyShown = Array.prototype.some.call(fields, function (el) { return el.style.display !== "none"; });
      if (fields.length) row.style.display = anyShown ? "" : "none";
    });
  }

  return {
    systemFieldNames: systemFieldNames, systemCount: systemCount, scopesFor: scopesFor,
    systemsMarkup: systemsMarkup, renderSystems: renderSystems, applyScope: applyScope
  };
});
