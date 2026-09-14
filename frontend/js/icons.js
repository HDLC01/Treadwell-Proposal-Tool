// The app's icon set — one inline SVG per name, and the ONLY place a UI glyph is drawn.
// Externalized (CSP: no inline scripts, and prod's `script-src 'self' https://cdn.jsdelivr.net`
// has no unsafe-eval). Do not add inline scripts, and do not add an icon library: this is
// hand-rolled on purpose.
//
// THE HOUSE RULE, written first in js/markup.js and js/library.js and now shared by the whole app:
//
//   NEVER an emoji — an emoji is drawn by whatever font the machine has, cannot take the row's
//   colour, and ignores every size token on the page.
//
// So every glyph here is Lucide-shaped: a 24x24 viewBox, `fill="none"`, `stroke="currentColor"`,
// stroke-width 2, round caps and joins, `aria-hidden="true" focusable="false"`. currentColor is
// the whole point — a danger button's icon goes red because the BUTTON is red, and a disabled
// row's icon dims with the row. A 🗑 could do neither.
//
// WHY THIS FILE EXISTS RATHER THAN A COPY PER PAGE. The tool already carried six radius tokens
// with conflicting values because a model that could not find a name invented a neighbour; a
// second way to draw a wastebasket is the same defect one layer up. auth.js alone drew glyphs for
// eighteen sidebar rows, and the wastebasket appeared in five more files. One table, loaded before
// auth.js on every page, is what keeps them the same shape.
//
// ADDING ONE: pick the Lucide name if a Lucide icon fits, keep the 24x24 stroke geometry, and add
// it to the list in alphabetical order. Do NOT coin a near-miss of a name that already exists
// (`bin` beside `trash`, `tick` beside `check`) — reuse the name that is here, or say in review
// that nothing here fits.
//
// The two page-local sets that predate this file stay where they are: js/library.js's icon() adds
// a `class="ic"` the Items page's stylesheet takes out of hit-testing and a `filled` argument its
// favourite star needs, and js/markup.js's is inside that page's IIFE. Both already draw the same
// geometry; neither has a glyph this file does not.
(function () {
  "use strict";

  /** The path data, by name. Values are raw SVG children — the wrapper below supplies every
   *  presentation attribute, so nothing in here carries a fill, a colour or a size. */
  var PATHS = {
    // ── status and marks ──────────────────────────────────────────────────────
    check: '<path d="M20 6L9 17l-5-5"></path>',
    "check-circle": '<circle cx="12" cy="12" r="9"></circle><path d="M8 12.2l2.8 2.8L16 9.8"></path>',
    x: '<path d="M6 6l12 12M18 6L6 18"></path>',
    plus: '<path d="M12 5v14M5 12h14"></path>',
    minus: '<path d="M5 12h14"></path>',
    warning: '<path d="M12 3.4L2.3 20.1h19.4L12 3.4z"></path><path d="M12 9.5v4M12 17.2v.01"></path>',
    info: '<circle cx="12" cy="12" r="9.5"></circle><path d="M12 8v.01M11 11h1.5v5.5H11"></path>',
    slash: '<circle cx="12" cy="12" r="9.5"></circle><path d="M5.5 5.5l13 13"></path>',
    star: '<path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8L3.5 9.2l5.9-.9L12 3z"></path>',

    // ── objects ───────────────────────────────────────────────────────────────
    trash: '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6"></path>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"></rect>' +
      '<path d="M5 15V5a2 2 0 0 1 2-2h10"></path>',
    pencil: '<path d="M4 20h4L18.5 9.5a2.83 2.83 0 0 0-4-4L4 16v4z"></path><path d="M13.5 6.5l4 4"></path>',
    lock: '<rect x="4" y="11" width="16" height="10" rx="2"></rect>' +
      '<path d="M8 11V7a4 4 0 0 1 8 0v4"></path>',
    unlock: '<rect x="4" y="11" width="16" height="10" rx="2"></rect>' +
      '<path d="M8 11V7a4 4 0 0 1 7.5-2"></path>',
    bell: '<path d="M18 9a6 6 0 1 0-12 0c0 5-2 6-2 6h16s-2-1-2-6"></path>' +
      '<path d="M10.2 19.5a2.2 2.2 0 0 0 3.6 0"></path>',
    mail: '<rect x="2.5" y="5" width="19" height="14" rx="2"></rect><path d="M3 6.5l9 6 9-6"></path>',
    message: '<path d="M21 11.5a7.5 7.5 0 0 1-7.5 7.5H8l-5 3 1.2-4.2A7.5 7.5 0 0 1 10.5 4h3a7.5 7.5 0 0 1 7.5 7.5z"></path>',
    clipboard: '<rect x="5" y="4.5" width="14" height="16.5" rx="2"></rect>' +
      '<rect x="8.5" y="2.5" width="7" height="4" rx="1"></rect><path d="M9 11.5h6M9 15.5h4"></path>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2.2 2.6H19a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"></path>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z"></path>' +
      '<path d="M14 3v5h5"></path>',
    cash: '<rect x="2.5" y="6" width="19" height="12" rx="2"></rect>' +
      '<circle cx="12" cy="12" r="2.6"></circle><path d="M6 12h.01M18 12h.01"></path>',
    layers: '<path d="M12 2.8l9 4.6-9 4.6-9-4.6 9-4.6z"></path><path d="M3 12.4l9 4.6 9-4.6"></path>' +
      '<path d="M3 16.9l9 4.6 9-4.6"></path>',
    shield: '<path d="M12 3l8 3v5.5c0 4.9-3.3 8.3-8 9.5-4.7-1.2-8-4.6-8-9.5V6l8-3z"></path>',
    power: '<path d="M12 3.5v8.5"></path><path d="M18.4 6.6a9 9 0 1 1-12.8 0"></path>',

    // ── pages and views ───────────────────────────────────────────────────────
    board: '<rect x="3" y="4" width="18" height="16" rx="2"></rect><path d="M9 4v16M15 4v16"></path>',
    table: '<rect x="3" y="4" width="18" height="16" rx="2"></rect>' +
      '<path d="M3 9.5h18M3 15h18M9.5 9.5V20"></path>',
    cards: '<rect x="3" y="3.5" width="7.5" height="7.5" rx="1.5"></rect>' +
      '<rect x="13.5" y="3.5" width="7.5" height="7.5" rx="1.5"></rect>' +
      '<rect x="3" y="13" width="7.5" height="7.5" rx="1.5"></rect>' +
      '<rect x="13.5" y="13" width="7.5" height="7.5" rx="1.5"></rect>',
    funnel: '<path d="M3 4.5h18l-7 8.5V20l-4-2.2v-5L3 4.5z"></path>',
    inbox: '<path d="M3 13h5l1.5 3h5L16 13h5"></path>' +
      '<path d="M5.5 5h13l2.5 8v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5l2.5-8z"></path>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"></rect>' +
      '<path d="M3 10h18M8 3v4M16 3v4"></path>',
    chart: '<path d="M3 3v18h18"></path><path d="M7 15.5l3.5-4.5 3 3L20 7"></path>',
    database: '<ellipse cx="12" cy="6" rx="8" ry="3"></ellipse>' +
      '<path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"></path>' +
      '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"></path>',
    archive: '<rect x="3" y="4" width="18" height="4.5" rx="1"></rect>' +
      '<path d="M5 8.5V19a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 19V8.5"></path>' +
      '<path d="M10 12.5h4"></path>',
    calculator: '<rect x="5" y="3" width="14" height="18" rx="2"></rect>' +
      '<path d="M8.5 7h7M8.5 12h.01M12 12h.01M15.5 12h.01M8.5 16.5h.01M12 16.5h.01M15.5 16.5h.01"></path>',
    percent: '<path d="M19 5L5 19"></path><circle cx="7.5" cy="7.5" r="2.5"></circle>' +
      '<circle cx="16.5" cy="16.5" r="2.5"></circle>',
    clock: '<circle cx="12" cy="12" r="9"></circle><path d="M12 6.8V12l3.6 2.1"></path>',
    timer: '<path d="M9.5 2.5h5"></path><circle cx="12" cy="13.5" r="7.5"></circle>' +
      '<path d="M12 9.5v4"></path>',
    history: '<path d="M3.6 12a8.4 8.4 0 1 0 2.6-6.1L3 8.4"></path><path d="M3 4.2v4.2h4.2"></path>' +
      '<path d="M12 7.6V12l3 1.8"></path>',

    // ── controls ──────────────────────────────────────────────────────────────
    menu: '<path d="M3 6h18M3 12h18M3 18h18"></path>',
    list: '<path d="M8.5 6h12M8.5 12h12M8.5 18h12"></path><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01"></path>',
    play: '<path d="M7 4.6l12 7.4-12 7.4V4.6z"></path>',
    pause: '<path d="M9 5v14M15 5v14"></path>',
    refresh: '<path d="M3.5 12a8.5 8.5 0 0 1 14.6-5.9L21 8.6"></path><path d="M21 4v4.6h-4.6"></path>' +
      '<path d="M20.5 12a8.5 8.5 0 0 1-14.6 5.9L3 15.4"></path><path d="M3 20v-4.6h4.6"></path>',
    undo: '<path d="M9 14.5L4 9.5l5-5"></path><path d="M4 9.5h10a6 6 0 0 1 0 12h-3"></path>',
    external: '<path d="M14 4h6v6"></path><path d="M20 4l-8.5 8.5"></path>' +
      '<path d="M18 14.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3.5"></path>',
    "indent-less": '<path d="M20 6H9.5M20 12H9.5M20 18H9.5"></path><path d="M7 9l-3 3 3 3"></path>',
    "indent-more": '<path d="M4 6h10.5M4 12h10.5M4 18h10.5"></path><path d="M17 9l3 3-3 3"></path>',

    // ── direction ─────────────────────────────────────────────────────────────
    "arrow-up": '<path d="M12 19V5"></path><path d="M6 11l6-6 6 6"></path>',
    "arrow-down": '<path d="M12 5v14"></path><path d="M6 13l6 6 6-6"></path>',
    "arrow-left": '<path d="M19 12H6"></path><path d="M11 7l-5 5 5 5"></path>',
    "arrow-right": '<path d="M5 12h13"></path><path d="M13 7l5 5-5 5"></path>',
    "chev-up": '<path d="M6 15l6-6 6 6"></path>',
    "chev-down": '<path d="M6 9l6 6 6-6"></path>',
    "chev-left": '<path d="M15 5l-7 7 7 7"></path>',
    "chev-right": '<path d="M9 5l7 7-7 7"></path>'
  };

  /** One glyph, as an SVG string ready to concatenate into markup.
   *
   *  `name` must be a key above. An unknown name draws an EMPTY box of the right size rather than
   *  throwing: a renderer half-way through building a row should not take the page down over a
   *  typo, and an empty square is visible in review in a way a silent `undefined` is not.
   *
   *  `size` is one number for both dimensions, in px, because every icon here is square. It
   *  defaults to 16 — the size that sits on a line of 13-15px text without pushing it around.
   *  `cls` adds a class beside `tw-ico` for a page that needs its own hook.
   *
   *  EVERY glyph carries `tw-ico`, and that class is the app-wide hook auth.js's stylesheet hangs
   *  two rules on — no pointer events, and sitting on the text's optical centre. A class rather
   *  than the `svg[aria-hidden][focusable]` attribute selector it started as: the CSS resolver in
   *  backend/tests/test_phone_shell.py cannot parse attribute selectors and FAILS on one rather
   *  than going quietly blind, which is the right behaviour from a test that decides whether the
   *  phone drawer can be clicked through. */
  function TWIcon(name, size, cls) {
    var d = Object.prototype.hasOwnProperty.call(PATHS, name) ? PATHS[name] : "";
    var px = Number(size) > 0 ? Number(size) : 16;
    return '<svg class="tw-ico' + (cls ? " " + cls : "") + '" viewBox="0 0 24 24" width="' + px +
      '" height="' + px + '" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
      d + "</svg>";
  }

  /** The names, for anything that wants to check one exists before asking for it. */
  TWIcon.names = function () { return Object.keys(PATHS); };
  TWIcon.has = function (name) {
    return Object.prototype.hasOwnProperty.call(PATHS, name);
  };

  window.TWIcon = TWIcon;
})();
