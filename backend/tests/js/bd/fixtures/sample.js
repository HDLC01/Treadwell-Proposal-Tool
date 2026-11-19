"use strict";
/* A small, fictional page-shaped file for the _lib.js self-test. It is NOT a page of this app.
 *
 * It holds the shapes that make a source lifter go wrong: a brace inside a string, a template
 * literal with a substitution, a regular expression with a slash inside a class, a default
 * parameter holding an object, comments that quote code, and constants of several shapes. The
 * self-test lifts every function declared here, compiles each one, and scans every string.
 * Nothing in this file is ever executed by the app.
 */
(function () {
  const TAGS = new Set(["new", "followup"]);
  const FREQUENCY = { bd: 4, maintenance: 3 };
  const WEEKDAYS = [
    "Mon", "Tue", "Wed",
    "Thu", "Fri",
  ];
  var SEPARATOR = "}{";

  function label(kind) { return FREQUENCY[kind] === 3 ? "Maintenance" : "Business development"; }

  function braces() { return "}" + `{${SEPARATOR}}` + /}/.source; }

  function pick(list, opts = { first: true }) {
    // a comment that quotes code: function nope() { return "}"; }
    return opts.first ? list[0] : list[list.length - 1];
  }

  async function loadOne(id, fetcher) {
    const r = await fetcher(`/api/contacts/${id}`);
    return r && r.ok ? r.json() : null;
  }

  function splitName(full) {
    const m = /^([^/\]]+)[/ ]+(.*)$/.exec(String(full || ""));
    return m ? { first: m[1], rest: m[2] } : { first: "", rest: "" };
  }

  function half(total, parts) { return (total + parts) / 2 / 2; }

  function describe(c) {
    const bits = [];
    if (c.name) bits.push(`<b>${c.name}</b>`);
    if (c.company) bits.push('<i>' + `${c.company}` + '</i>');
    return bits.join(" - ") || "unknown";
  }

  function weekday(n) { return WEEKDAYS[((n % 5) + 5) % 5]; }

  window.__sample = { label, braces, pick, loadOne, splitName, half, describe, weekday, TAGS };
})();
