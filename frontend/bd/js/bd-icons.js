// The BD CRM's glyphs (#806, spec #802 Q6), as window.BDIcon. Loaded on the BD pages only, after the
// tool's /js/icons.js and before every other BD script.
//
// BD GLYPHS SIT UNDER THEIR OWN GLOBAL. BD's old icons.js was a copy of the tool's with BD's glyphs
// added, and it set window.TWIcon. Loaded beside the tool's table it would have replaced the tool's
// icon global on every BD page, sidebar included. This file never assigns to TWIcon or to anything
// hanging off it; it only reads it. backend/tests/test_bd_assets.py runs both files and checks.
//
//   BDIcon(name, size, cls)   one glyph as an SVG string, the same wrapper as the tool's TWIcon
//   BDIcon.names()            every name BDIcon can draw (the tool's and BD's)
//   BDIcon.has(name)
//
// A name the tool's table has is drawn BY the tool's table, so a BD page and the sidebar beside it
// can never draw the same name two ways. BD_PATHS holds only the glyphs the tool does not have
// (BD's old "BD CRM additions", less users, which the tool now draws for the BD CRM row), and
// ALIASES the two longer names BD's pages ask for. The house rules are the tool's (js/icons.js):
// Lucide-shaped, 24x24, stroke-only, currentColor, never an emoji.
(function () {
  "use strict";

  /** BD's own glyphs: the same 24x24, stroke-only geometry as the tool's, by name. */
  var BD_PATHS = {
    "bar-chart": '<path d="M3 3v18h18"></path><path d="M8 17v-3M13 17V6M18 17V10"></path>',
    building: '<rect x="4" y="2.5" width="16" height="19" rx="1.5"></rect>' +
      '<path d="M9 21.5v-4h6v4M8.5 7h.01M12 7h.01M15.5 7h.01M8.5 11h.01M12 11h.01M15.5 11h.01"></path>',
    "calendar-check": '<rect x="3" y="4" width="18" height="18" rx="2"></rect>' +
      '<path d="M16 2v4M8 2v4M3 10h18M9 16l2 2 4-4"></path>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><path d="M7 10l5 5 5-5M12 15V3"></path>',
    flag: '<path d="M4 22V4"></path><path d="M4 4.5c5-3 8 3 16 0V14c-8 3-11-3-16 0"></path>',
    "help-circle": '<circle cx="12" cy="12" r="9.5"></circle><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"></path>' +
      '<path d="M12 17h.01"></path>',
    lightbulb: '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5 .7 .7 1.3 1.5 1.5 2.5"></path>' +
      '<path d="M9 18h6M10 22h4"></path>',
    link: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7.1-7.1l-1.7 1.7"></path>' +
      '<path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7.1 7.1l1.7-1.7"></path>',
    "log-out": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><path d="M16 17l5-5-5-5M21 12H9"></path>',
    "map-pin": '<path d="M20 10c0 5.5-8 12-8 12s-8-6.5-8-12a8 8 0 0 1 16 0z"></path>' +
      '<circle cx="12" cy="10" r="3"></circle>',
    more: '<circle cx="5" cy="12" r="1"></circle><circle cx="12" cy="12" r="1"></circle><circle cx="19" cy="12" r="1"></circle>',
    phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 ' +
      '2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 ' +
      '2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"></path>',
    "phone-incoming": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 ' +
      '2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 ' +
      '2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"></path><path d="M16 2v6h6M22 2l-6 6"></path>',
    "phone-missed": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 ' +
      '2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 ' +
      '2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"></path><path d="M16 2l6 6M22 2l-6 6"></path>',
    search: '<circle cx="11" cy="11" r="7"></circle><path d="M20 20l-3.6-3.6"></path>',
    settings: '<circle cx="12" cy="12" r="3"></circle>' +
      '<path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21' +
      'a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8' +
      ' 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1' +
      'a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1' +
      'a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"></path>',
    sparkles: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"></path>' +
      '<path d="M19 15l.7 1.8 1.8.7-1.8.7L19 20l-.7-1.8-1.8-.7 1.8-.7L19 15z"></path>',
    "trending-up": '<path d="M22 7l-8.5 8.5-5-5L2 17"></path><path d="M16 7h6v6"></path>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><path d="M17 8l-5-5-5 5M12 3v12"></path>',
    user: '<circle cx="12" cy="8" r="4"></circle><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"></path>',
    "user-plus": '<circle cx="9" cy="7" r="4"></circle><path d="M2 21v-1a6 6 0 0 1 6-6h2a6 6 0 0 1 6 6v1"></path>' +
      '<path d="M19 8v6M16 11h6"></path>',
    "user-x": '<circle cx="9" cy="7" r="4"></circle><path d="M2 21v-1a6 6 0 0 1 6-6h2a6 6 0 0 1 6 6v1"></path>' +
      '<path d="M17 8.5l5 5M22 8.5l-5 5"></path>',
    voicemail: '<circle cx="6.5" cy="12" r="4"></circle><circle cx="17.5" cy="12" r="4"></circle><path d="M6.5 16h11"></path>'
  };

  /** Longer names BD's pages ask for, drawn with the tool's glyph of the same shape. */
  var ALIASES = { "chevron-right": "chev-right", filter: "funnel" };

  function tool() {
    return typeof window.TWIcon === "function" ? window.TWIcon : null;
  }

  function own(name) {
    return Object.prototype.hasOwnProperty.call(BD_PATHS, name);
  }

  /** One glyph. A BD glyph is drawn here in the tool's wrapper (class tw-ico, so the tool's rules for
   *  every glyph apply); any other name goes to the tool's TWIcon, after the aliases. An unknown name,
   *  or no tool table on the page, draws an empty box rather than throwing. */
  function BDIcon(name, size, cls) {
    var key = Object.prototype.hasOwnProperty.call(ALIASES, name) ? ALIASES[name] : name;
    var px = Number(size) > 0 ? Number(size) : 16;
    var tw = tool();
    if (!own(key) && tw) return tw(key, px, cls);
    return '<svg class="tw-ico' + (cls ? " " + cls : "") + '" viewBox="0 0 24 24" width="' + px +
      '" height="' + px + '" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
      (own(key) ? BD_PATHS[key] : "") + "</svg>";
  }

  BDIcon.names = function () {
    var tw = tool();
    var all = (tw && typeof tw.names === "function" ? tw.names() : []).concat(Object.keys(BD_PATHS), Object.keys(ALIASES));
    return all.filter(function (n, i) { return all.indexOf(n) === i; });
  };
  BDIcon.has = function (name) {
    if (own(name) || Object.prototype.hasOwnProperty.call(ALIASES, name)) return true;
    var tw = tool();
    return !!(tw && typeof tw.has === "function" && tw.has(name));
  };

  window.BDIcon = BDIcon;
})();
