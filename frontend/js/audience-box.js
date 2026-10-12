// SHOWS THE DRAWINGS & SPECS BOX ONLY FOR A GENERAL CONTRACTOR. Externalized (CSP: no inline scripts).
// Do not add inline scripts.
//
// Loaded by BOTH intakes (index.html and polish-intake.html), after the page's own script, so the box
// follows the Audience radios the same way on each. The rule itself, and why the box is hidden and never
// removed, is js/intake-scope.js's (applyAudience): this file only reads the radios and calls it.
//
// A page that fills the radios after this file ran (the v2 intake hydrates once its sandbox has settled)
// calls window.TWAudienceBox.sync() when it is done, so a draft saved as GC opens with the box showing.
(function () {
  "use strict";
  var S = window.TWIntakeScope;
  var form = document.getElementById("intake-form");
  var box = document.getElementById("drawings-specs-box");
  if (!S || !form || !box) return;

  /** The audience the radios say. Direct when nothing is ticked, as the draft treats a missing one. */
  function chosen() {
    var el = form.querySelector("[name='audience']:checked");
    return el ? el.value : "Direct";
  }

  function sync() { S.applyAudience(chosen(), box); }

  form.addEventListener("change", function (e) {
    if (e && e.target && e.target.name === "audience") sync();
  });
  // Back and forward restore the radios from the browser's own memory, without a change event.
  window.addEventListener("pageshow", sync);

  window.TWAudienceBox = { sync: sync };
  sync();
})();
