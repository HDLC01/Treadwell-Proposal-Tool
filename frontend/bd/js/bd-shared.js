/* Treadwell BD CRM - small helpers every BD page uses, as window.BD (#806: moved in from BD's
 * js/shared.js, beside the tool's own /shared.js and never in its place).
 *
 * The business-date block is the proposal tool's (frontend/shared.js, BIZ_TZ). PEOPLE are named by
 * the tool's js/crm-core.js (window.TWCrm, loaded before this file), the one place that decides a
 * person's name, initials and avatar colour, so a person looks the same here as on the tool's board.
 * BD adds only what its data needs: a UserRef or contact object ({name, email}) and a display name
 * kept as written.
 *
 * DATES. Treadwell works in Central time and the dev PC's clock runs ~13 hours ahead of it, so
 * nothing here reads a date off the viewer's clock zone. A bare "YYYY-MM-DD" is anchored at noon
 * UTC before formatting, which can never cross a day boundary when shifted into Central (the
 * mistake the tool's fmtBizDay documents). Pages take "today" from /api/bd/me (`today`);
 * bizToday() is the live clock's Central date.
 *
 * GLYPHS come from the tool's one icon set, window.TWIcon (js/icons.js). An open sheet or dialog
 * marks the page's <body> (the BD root, .bd-app) with bd-locked, so the page behind it does not scroll.
 */
(function () {
  "use strict";

  var BIZ_TZ = "America/Chicago";
  var DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /** $42,800 (no cents unless asked). "$—" for nothing. */
  function money(n, cents) {
    if (n == null || n === "" || isNaN(Number(n))) return "$—";
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD",
      minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0 }).format(Number(n));
  }

  function toDate(v) {
    if (!v) return null;
    var s = String(v);
    var d = new Date(DATE_ONLY.test(s) ? s + "T12:00:00Z" : s);
    return isNaN(d.getTime()) ? null : d;
  }

  /** A date or timestamp as a Central date.
   *  style "long" (default) "Nov 4, 2026" · "short" "Wed, Nov 4" · "numeric" "11/4/2026". */
  function fmtBizDate(v, style) {
    var d = toDate(v);
    if (!d) return "—";
    var o = { timeZone: BIZ_TZ };
    if (style === "short") { o.weekday = "short"; o.month = "short"; o.day = "numeric"; }
    else if (style === "numeric") { o.year = "numeric"; o.month = "numeric"; o.day = "numeric"; }
    else { o.year = "numeric"; o.month = "short"; o.day = "numeric"; }
    return d.toLocaleDateString("en-US", o);
  }

  /** "Nov 4, 2026, 10:05 AM CST". */
  function fmtBizDateTime(v) {
    var d = toDate(v);
    if (!d) return "";
    return d.toLocaleString("en-US", { timeZone: BIZ_TZ, year: "numeric", month: "short",
      day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  }

  /** "10:05 AM". */
  function fmtBizTime(v) {
    var d = toDate(v);
    return d ? d.toLocaleTimeString("en-US", { timeZone: BIZ_TZ, hour: "numeric", minute: "2-digit" }) : "";
  }

  /** The Central calendar date of a date or timestamp, "YYYY-MM-DD"; "" for nothing. */
  function bizDateOf(v) {
    if (!v) return "";
    if (DATE_ONLY.test(String(v))) return String(v);
    var d = toDate(v);
    return d ? new Intl.DateTimeFormat("en-CA", { timeZone: BIZ_TZ, year: "numeric",
      month: "2-digit", day: "2-digit" }).format(d) : "";
  }

  /** Today's date in Central, "YYYY-MM-DD", from the live clock. */
  function bizToday() {
    return bizDateOf(new Date().toISOString());
  }

  /** The Monday of the week `v` falls in (default today), "YYYY-MM-DD" in Central.
   *  Monday because the BD week runs Monday to Sunday (the workbook's top box). */
  function bizWeekStart(v) {
    var day = bizDateOf(v || new Date().toISOString());
    if (!day) return "";
    var anchor = new Date(day + "T12:00:00Z");
    var back = (anchor.getUTCDay() + 6) % 7;          // Mon 0 .. Sun 6
    anchor.setUTCDate(anchor.getUTCDate() - back);
    return anchor.toISOString().slice(0, 10);
  }

  /** Whole Central days from a to b (b - a); null when either is missing. */
  function daysBetween(a, b) {
    var x = bizDateOf(a), y = bizDateOf(b);
    if (!x || !y) return null;
    return Math.round((Date.parse(y + "T12:00:00Z") - Date.parse(x + "T12:00:00Z")) / 86400000);
  }

  /** Now, as an ISO timestamp with the Central offset it has ("2026-11-04T10:05:00-06:00").
   *  `onDate` swaps the date part (a fixed "today" with the real time of day). */
  function bizNowISO(onDate) {
    var now = new Date();
    var parts = {};
    new Intl.DateTimeFormat("en-US", { timeZone: BIZ_TZ, hourCycle: "h23", year: "numeric",
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })
      .formatToParts(now).forEach(function (p) { parts[p.type] = p.value; });
    var date = onDate || (parts.year + "-" + parts.month + "-" + parts.day);
    var time = parts.hour + ":" + parts.minute + ":" + parts.second;
    return date + "T" + time + centralOffset(date + "T" + time);
  }

  /** "-05:00" (CDT) or "-06:00" (CST) for a Central wall-clock "YYYY-MM-DDTHH:MM:SS". */
  function centralOffset(wall) {
    var guess = new Date(wall + "Z");
    var name = "";
    try {
      new Intl.DateTimeFormat("en-US", { timeZone: BIZ_TZ, timeZoneName: "shortOffset" })
        .formatToParts(new Date(guess.getTime() + 6 * 3600000)).forEach(function (p) {
          if (p.type === "timeZoneName") name = p.value;
        });
    } catch (e) { name = ""; }
    return name === "GMT-5" ? "-05:00" : "-06:00";
  }

  // ── people (named by the tool's crm-core.js) ─────────────────────────────────────────────

  function crm() { return window.TWCrm; }

  /** The display name of a UserRef or contact object, a name, or an address. A name is shown as
   *  written ("Dr. Ian Pruitt"); an address is named by crm-core ("avery.quill@example.com" ->
   *  "Avery Quill"). Exported as BD.nameOf. */
  function displayName(who) {
    if (who && typeof who === "object") return who.name ? String(who.name) : displayName(who.email);
    var s = String(who == null ? "" : who);
    return s.indexOf("@") === -1 ? s.trim() : crm().nameOf(s);
  }

  // ── matching ─────────────────────────────────────────────────────────────────────────────

  var COMPANY_SUFFIXES = ["inc", "incorporated", "llc", "co", "corp", "corporation", "company", "ltd", "lc", "pllc"];

  /** The duplicate-check key for a company name: lower case, non-breaking spaces made spaces,
   *  punctuation dropped, spaces collapsed, and trailing Inc/LLC/Co (and similar) removed.
   *  " Kestrelwood Gear Co. " -> "kestrelwood gear". The name itself is never stored this way. */
  function normalizeCompany(name) {
    var s = String(name == null ? "" : name).replace(/[   ]/g, " ").toLowerCase();
    s = s.replace(/&/g, " ").replace(/[^a-z0-9\s]/g, "").replace(/\s+/g, " ").trim();
    var words = s ? s.split(" ") : [];
    while (words.length > 1 && COMPANY_SUFFIXES.indexOf(words[words.length - 1]) !== -1) words.pop();
    return words.join(" ");
  }

  /** A US phone number as "+1XXXXXXXXXX", or null. Accepts dots, dashes, spaces, parentheses
   *  and a leading 1 or +1 ("816.555.0110", "(913) 555-0117", "+1 816 555 0110"). */
  function e164(phone) {
    var digits = String(phone == null ? "" : phone).replace(/\D/g, "");
    if (digits.length === 11 && digits.charAt(0) === "1") digits = digits.slice(1);
    return digits.length === 10 ? "+1" + digits : null;
  }

  /** A US phone number for DISPLAY as "816-555-0110", whatever way it was typed (the workbook
   *  mixes "816.555.0110" and "816-555-0110"). Anything that is not a US number is shown as given.
   *  The stored value and edit fields keep what was entered. */
  function fmtPhone(phone) {
    var e = e164(phone);
    if (!e) return phone == null ? "" : String(phone);
    return e.slice(2, 5) + "-" + e.slice(5, 8) + "-" + e.slice(8);
  }

  // ── small utilities ──────────────────────────────────────────────────────────────────────

  function debounce(fn, ms) {
    var t = null;
    return function () {
      var self = this, args = arguments;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms == null ? 250 : ms);
    };
  }

  /** One query-string parameter, or null. */
  function qs(name) {
    try { return new URLSearchParams(location.search).get(name); } catch (e) { return null; }
  }

  // ── words the pages share (one place, so a status is called the same thing everywhere) ──

  var LABELS = {
    cadence: { never: "Never reached", behind: "Behind", on_track: "On track", complete: "Done for the year" },
    category: { bd: "BD", maintenance: "Maintenance" },
    task_kind: { "new": "New", followup: "Follow-up" },
    outcome: { answered: "Answered", meeting_set: "Meeting set", voicemail: "Voicemail", no_answer: "No answer" },
    kind: { call: "Call", voicemail: "Voicemail", meeting: "Meeting", email: "Email", sms: "Text",
      note: "Note", hosted: "Hosted event" },
    role: { salesperson: "Salesperson", assistant: "Assistant", manager: "Manager", admin: "Admin",
      super_admin: "Super admin" },
  };

  /** Timeline event words (api-contract.md, "event.action"). */
  var VERB = {
    created: "added this contact", confirmed: "confirmed this contact",
    unconfirmed: "marked this contact as not confirmed", duplicate_cleared: "marked this as not a duplicate",
    owner_changed: "changed the owner", frequency_changed: "changed how often to follow up",
    merged: "merged a duplicate into this contact", archived: "archived this contact",
    restored: "restored this contact", added_from_quote: "added this contact from a quote",
  };

  // ── the redesign's helpers (docs: the apply plan, section 1.6) ───────────────────────────
  // Every pure helper takes `today` ("YYYY-MM-DD", on a page the `today` of /api/bd/me) as an
  // argument and never reads a clock. This file is also loaded in a bare node vm (no document,
  // no storage), so DOM and storage are touched only inside function bodies.

  /** The one avatar: the person's initials on their colour, both crm-core's (the same colour as on
   *  the tool's board), hidden from screen readers (the name is beside it).
   *  size "" (40px) | "sm" (32) | "lg" (56) | "xl" (72); badge "done" (green check) | "off"
   *  (dashed ring, "Not this week") | null. The colour is one of crm-core's constants. */
  function avatarHTML(who, size, badge) {
    var cls = "avatar" + (size ? " avatar-" + size : "");
    var name = displayName(who);
    var mark = "";
    if (badge === "done") {
      var check = typeof window.TWIcon === "function" ? window.TWIcon("check", 11) : "";
      mark = '<span class="avatar-badge">' + check + "</span>";
    } else if (badge === "off") {
      mark = '<span class="avatar-badge-off"></span>';
    }
    return '<span class="' + cls + '" style="background:' + esc(crm().colorOf(name)) + '" aria-hidden="true">' +
      esc(crm().initialsOf(name)) + mark + "</span>";
  }

  /** "Good morning" / "Good afternoon" / "Good evening" from the wall-clock hour of a Central ISO
   *  timestamp (pages pass BD.bizNowISO(); tests pass a fixed string). */
  function greeting(nowISO) {
    var m = /T(\d{2}):/.exec(String(nowISO || ""));
    var h = m ? parseInt(m[1], 10) : 9;
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  }

  /** "1,234" (en-US grouping). */
  function fmtCount(n) {
    var x = Number(n);
    return isFinite(x) ? new Intl.NumberFormat("en-US").format(x) : "0";
  }

  /** "1 call" / "6 calls": the count and the right word. `many` defaults to `one` + "s". */
  function plural(n, one, many) {
    return fmtCount(n) + " " + (Number(n) === 1 ? one : (many || one + "s"));
  }

  /** "Marcus" from "Marcus Ebner" (or from an address or a UserRef). */
  function firstName(who) {
    return displayName(who).split(/\s+/).filter(Boolean)[0] || "";
  }

  function ymd(iso) {
    var s = bizDateOf(iso);
    if (!s) return null;
    return { y: +s.slice(0, 4), m: +s.slice(5, 7), d: +s.slice(8, 10) };
  }
  function isoOf(y, m, d) {
    return String(y) + "-" + (m < 10 ? "0" : "") + m + "-" + (d < 10 ? "0" : "") + d;
  }
  function daysInMonth(y, m) { return new Date(Date.UTC(y, m, 0)).getUTCDate(); }
  function addDays(iso, n) {
    var d = new Date(bizDateOf(iso) + "T12:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  /** The same day `n` months on; a day that month does not have clamps to its last day. */
  function addMonths(iso, n) {
    var p = ymd(iso);
    if (!p) return "";
    var total = p.y * 12 + (p.m - 1) + n;
    var y = Math.floor(total / 12), m = (total % 12) + 1;
    return isoOf(y, m, Math.min(p.d, daysInMonth(y, m)));
  }

  /** "Mon, Nov 9"; "Mon, Jan 11, 2027" when the date is not in `today`'s year. "" for nothing. */
  function fmtDay(iso, today) {
    var d = toDate(iso);
    if (!d) return "";
    var o = { timeZone: BIZ_TZ, weekday: "short", month: "short", day: "numeric" };
    var t = ymd(today), p = ymd(iso);
    if (t && p && t.y !== p.y) o.year = "numeric";
    return d.toLocaleDateString("en-US", o);
  }

  /** How far off a date is, in plain words, from `today` (calendar days in Central):
   *  "today", "tomorrow", "in 3 days", "in a week", "in 2 weeks", "in 3 weeks", "in about a
   *  month", "about 3 months", "about a year", "about 2 years". A past date gives "". */
  function fmtRel(iso, today) {
    var days = daysBetween(today, iso);
    if (days == null || days < 0) return "";
    if (days === 0) return "today";
    if (days === 1) return "tomorrow";
    if (days <= 6) return "in " + days + " days";
    if (days <= 13) return "in a week";
    if (days <= 20) return "in 2 weeks";
    if (days <= 29) return "in 3 weeks";
    if (days <= 44) return "in about a month";
    if (days <= 364) {
      var n = Math.floor(days / 30.4);
      return n <= 1 ? "about a month" : "about " + n + " months";
    }
    var y = Math.floor(days / 365);
    return y <= 1 ? "about a year" : "about " + y + " years";
  }

  /** The date a quick-pick chip means, from `today`: "week" = 7 days on, "month" = the same day
   *  next month, "3months" = the same day three months on (a missing day clamps: Jan 31 + a month
   *  = Feb 28). */
  function chipDate(chip, today) {
    if (!bizDateOf(today)) return "";
    if (chip === "week") return addDays(today, 7);
    if (chip === "month") return addMonths(today, 1);
    if (chip === "3months") return addMonths(today, 3);
    return "";
  }

  /** "6 min", "1 min 35 s", "45 s". */
  function fmtDuration(s) {
    var n = Math.max(0, Math.round(Number(s) || 0));
    var m = Math.floor(n / 60), r = n % 60;
    if (!m) return r + " s";
    return r ? m + " min " + r + " s" : m + " min";
  }

  /** Whole weeks left in `today`'s year, today counted, at least 1 (2026-11-04: 58 days, 8 weeks). */
  function weeksLeft(today) {
    var t = ymd(today);
    if (!t) return 1;
    var daysLeft = daysBetween(today, isoOf(t.y, 12, 31)) + 1;
    return Math.max(1, Math.floor(daysLeft / 7));
  }

  /** The pace in words, one source for This Week (week.pace) and Analytics
   *  (interactions_vs_target): {completed, required_to_date, target_total} in, the contract's
   *  half-up rounding (-14.5 -> -14). Returns {pct, target, done, dueToday, delta, state
   *  ("behind" | "ahead" | "on"), short ("15 behind"), sentence ("15 behind. About 2 extra calls a
   *  week catches up."), caption ("61 of 90 this year · 8 weeks left")}. */
  function paceWords(pace, today) {
    var p = pace || {};
    var done = Number(p.completed) || 0;
    var target = Number(p.target_total) || 0;
    var req = Number(p.required_to_date) || 0;
    var pct = target > 0 ? Math.round((100 * done) / target) : 0;
    var delta = target > 0 ? Math.round(done - req) : 0;
    var state = delta < 0 ? "behind" : (delta > 0 ? "ahead" : "on");
    var weeks = weeksLeft(today);
    var short, sentence;
    if (state === "behind") {
      var extra = Math.ceil(Math.abs(delta) / weeks);
      short = Math.abs(delta) + " behind";
      sentence = short + ". About " + plural(extra, "extra call") + " a week catches up.";
    } else if (state === "ahead") {
      short = delta + " ahead";
      sentence = short + ". Nice work.";
    } else {
      short = "On pace";
      sentence = "Right on pace.";
    }
    return {
      pct: pct, target: target, done: done, dueToday: Math.round(req), delta: delta, state: state,
      short: short, sentence: sentence,
      caption: done + " of " + target + " this year · " + plural(weeks, "week") + " left",
    };
  }

  /** A pill: kind ok | warn | info | neutral | ai | outline, plain text, an optional 14 px glyph. */
  function pill(kind, text, glyph) {
    var ico = glyph && typeof window.TWIcon === "function" ? window.TWIcon(glyph, 14) : "";
    return '<span class="pill pill-' + kind + '">' + ico + esc(text) + "</span>";
  }

  /** The ONE status pill a person shows, most important first: Possible duplicate > Needs
   *  confirming > Key account > Maintenance > none (""). `reasons` is a task's reasons list;
   *  `pinned` (a due maintenance task) drops only the neutral Maintenance pill. */
  function statusPill(contact, reasons, pinned) {
    var c = contact || {};
    var rs = reasons || [];
    if (c.duplicate_of) return pill("warn", "Possible duplicate");
    if (c.confirmed === false) return pill("warn", "Needs confirming");
    var key = c.importance === 3 || rs.some(function (r) { return /^key account/i.test(String(r)); });
    if (key) return pill("info", "Key account");
    // A pinned maintenance task already wears "Maintenance · due": the neutral pill would repeat it.
    if (c.category === "maintenance" && !pinned) return pill("neutral", "Maintenance");
    return "";
  }

  /** The kind of a weekly task as a pill: "Follow-up" or "New" (outline), or "Maintenance \u00b7 due"
   *  (warn: a pinned maintenance follow-up, which says why it is on the list, so the neutral
   *  "Maintenance" status pill is not shown next to it). */
  function kindPill(task) {
    var k = task && task.kind;
    if (k === "maintenance") return pill("warn", "Maintenance \u00b7 due");
    if (k !== "new" && k !== "followup") return "";
    return pill("outline", k === "new" ? "New" : "Follow-up");
  }

  /** The first "why this one" reason that the status pill does not already say, without its
   *  trailing period; "" when none. */
  function firstReason(task) {
    var rs = (task && task.reasons) || (task && task.reason ? [task.reason] : []);
    for (var i = 0; i < rs.length; i++) {
      var r = String(rs[i] || "").trim();
      if (!r || /^key account/i.test(r) || /^needs confirming/i.test(r)) continue;
      return r.replace(/\.+$/, "");
    }
    return "";
  }

  /** The full tel: link for a contact or a phone string ("tel:+18165550110"); "" without one. */
  function telHref(who) {
    var phone = who && typeof who === "object" ? (who.phone_e164 || who.phone) : who;
    if (!phone) return "";
    var n = e164(phone) || String(phone).replace(/[^\d+]/g, "");
    return n ? "tel:" + n : "";
  }

  /** localStorage / sessionStorage as JSON, never throwing: a blocked store reads null. */
  var store = {
    get: function (key, opts) {
      try {
        var s = opts && opts.session ? window.sessionStorage : window.localStorage;
        var v = s.getItem(key);
        return v == null ? null : JSON.parse(v);
      } catch (e) { return null; }
    },
    set: function (key, value, opts) {
      try {
        var s = opts && opts.session ? window.sessionStorage : window.localStorage;
        s.setItem(key, JSON.stringify(value));
        return true;
      } catch (e) { return false; }
    },
    del: function (key, opts) {
      try {
        var s = opts && opts.session ? window.sessionStorage : window.localStorage;
        s.removeItem(key);
      } catch (e) { /* nothing stored, nothing to remove */ }
    },
  };

  // ── overlays: sheet (phone bottom sheet / desktop right drawer), dialog, menu ──────────────
  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), ' +
    'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  var openSheets = [];

  function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }
  function focusables(el) {
    return Array.prototype.filter.call(el.querySelectorAll(FOCUSABLE), function (n) {
      return n.offsetParent !== null || n === document.activeElement;
    });
  }

  /** Open `el` (a .sheet or a .dialog, appended to <body> if it is not in the page) as a modal:
   *  a scrim, the rest of the page inert, focus kept inside, Escape and a scrim click close it
   *  (reason "escape" / "scrim"), the page does not scroll behind it, focus goes back to the
   *  opener on close, and on a phone the pinned .sheet-bar stays above the keyboard.
   *  opts: {onClose(reason), initialFocus (an element or a selector), label, returnFocus (a
   *  function giving the element to focus on close when the opener has left the page, as when a
   *  save redrew the list behind the sheet)}.
   *  On a phone, opening one clears the toasts, which would cover its buttons. */
  function sheetOpen(el, opts) {
    var o = opts || {};
    if (!el || el._bdSheet) return;
    var doc = document;
    if (!el.parentNode) doc.body.appendChild(el);
    var scrim = doc.createElement("div");
    scrim.className = "scrim" + (el.classList.contains("dialog") ? " scrim-dialog" : "");
    scrim.setAttribute("aria-hidden", "true");
    doc.body.insertBefore(scrim, el);
    el.setAttribute("role", el.getAttribute("role") || "dialog");
    el.setAttribute("aria-modal", "true");
    if (o.label) el.setAttribute("aria-label", o.label);
    el.hidden = false;

    var inerted = [];
    Array.prototype.forEach.call(doc.body.children, function (c) {
      if (c === el || c === scrim || c.id === "bd-toasts" || c.id === "bd-live" || c.id === "bd-alert" ||
          c.tagName === "SCRIPT" || c.hasAttribute("inert")) return;
      c.setAttribute("inert", "");
      inerted.push(c);
    });
    doc.body.classList.add("bd-locked");
    var toastBox = doc.getElementById("bd-toasts");
    if (toastBox && window.matchMedia && window.matchMedia("(max-width: 767px)").matches) {
      Array.prototype.forEach.call(toastBox.children, function (t) { if (t._bdDismiss) t._bdDismiss("dismissed"); });
    }

    var state = { scrim: scrim, inerted: inerted, opener: doc.activeElement, opts: o };
    state.onKey = function (e) {
      if (openSheets[openSheets.length - 1] !== el) return;
      if (e.key === "Escape") { e.preventDefault(); sheetClose(el, "escape"); return; }
      if (e.key !== "Tab") return;
      var f = focusables(el);
      if (!f.length) { e.preventDefault(); return; }
      var first = f[0], last = f[f.length - 1], at = doc.activeElement;
      if (e.shiftKey && (at === first || !el.contains(at))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (at === last || !el.contains(at))) { e.preventDefault(); first.focus(); }
    };
    state.onScrim = function () { sheetClose(el, "scrim"); };
    state.onViewport = function () {
      var vv = window.visualViewport;
      if (!vv || !el.classList.contains("sheet")) return;
      var kb = Math.max(0, window.innerHeight - (vv.height + vv.offsetTop));
      el.style.bottom = kb ? kb + "px" : "";
    };
    doc.addEventListener("keydown", state.onKey);
    scrim.addEventListener("click", state.onScrim);
    if (window.visualViewport) window.visualViewport.addEventListener("resize", state.onViewport);
    el._bdSheet = state;
    openSheets.push(el);

    var target = typeof o.initialFocus === "string" ? el.querySelector(o.initialFocus) : o.initialFocus;
    if (!target) target = focusables(el)[0] || el;
    if (target === el && !el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
    var focusIn = function () {
      try { target.focus({ preventScroll: true }); } catch (e) { target.focus(); }
    };
    // The sheet is visibility: hidden until .is-open lands (two frames later, for the slide-in),
    // and a hidden field cannot take focus: try now, then again once it shows, unless focus is
    // already inside it.
    var show = function () {
      scrim.classList.add("is-open");
      el.classList.add("is-open");
      if (el._bdSheet === state && !el.contains(doc.activeElement)) focusIn();
    };
    focusIn();
    if (reducedMotion()) {
      show();
      // Belt and braces: if the switch to visible has not landed yet, try once more next frame.
      requestAnimationFrame(function () { if (el._bdSheet === state && !el.contains(doc.activeElement)) focusIn(); });
    }
    else requestAnimationFrame(function () { requestAnimationFrame(show); });
  }

  /** Close a sheet or dialog opened with sheetOpen; `reason` reaches its onClose. */
  function sheetClose(el, reason) {
    var s = el && el._bdSheet;
    if (!s) return;
    el._bdSheet = null;
    openSheets = openSheets.filter(function (x) { return x !== el; });
    document.removeEventListener("keydown", s.onKey);
    if (window.visualViewport) window.visualViewport.removeEventListener("resize", s.onViewport);
    s.inerted.forEach(function (c) { c.removeAttribute("inert"); });
    if (!openSheets.length) document.body.classList.remove("bd-locked");
    el.classList.remove("is-open");
    s.scrim.classList.remove("is-open");
    var gone = function () {
      if (s.scrim.parentNode) s.scrim.parentNode.removeChild(s.scrim);
      if (!el._bdSheet) { el.hidden = true; el.style.bottom = ""; }
    };
    if (reducedMotion()) gone(); else setTimeout(gone, 200);
    var back = s.opener && s.opener.focus && document.contains(s.opener) ? s.opener : null;
    if (!back && typeof s.opts.returnFocus === "function") {
      var r = s.opts.returnFocus();
      back = r && r.focus && document.contains(r) ? r : null;
    }
    if (back) {
      try { back.focus({ preventScroll: true }); } catch (e) { back.focus(); }
    }
    if (typeof s.opts.onClose === "function") s.opts.onClose(reason || "close");
  }

  /** A centred confirm box (a bottom sheet on a phone). Resolves true for `yes`, false for `no`,
   *  Escape or a scrim click. {title, text, yes ("Yes"), no ("Cancel"), danger (red yes),
   *  field: {label, placeholder, maxlength} (one optional line of text: `yes` then resolves with
   *  what was typed, or true when it was left empty)}. */
  function dialog(opts) {
    var o = opts || {};
    return new Promise(function (resolve) {
      var el = document.createElement("div");
      el.className = "dialog";
      el.setAttribute("role", "alertdialog");
      var tid = "bd-dialog-" + Date.now();
      el.setAttribute("aria-labelledby", tid);
      var fid = tid + "-f";
      el.innerHTML = '<h2 class="dialog-title" id="' + tid + '">' + esc(o.title || "Are you sure?") + "</h2>" +
        (o.text ? '<p class="dialog-text">' + esc(o.text) + "</p>" : "") +
        (o.field ? '<div class="field dialog-field"><label for="' + fid + '">' + esc(o.field.label || "") + "</label>" +
          '<input class="input" type="text" id="' + fid + '" autocomplete="off"' +
          (o.field.maxlength ? ' maxlength="' + esc(o.field.maxlength) + '"' : "") +
          (o.field.placeholder ? ' placeholder="' + esc(o.field.placeholder) + '"' : "") + " /></div>" : "") +
        '<div class="dialog-actions">' +
        '<button type="button" class="btn" data-act="no">' + esc(o.no || "Cancel") + "</button>" +
        '<button type="button" class="btn ' + (o.danger ? "btn-danger-fill" : "btn-primary") + '" data-act="yes">' +
        esc(o.yes || "Yes") + "</button></div>";
      var answer = false;
      var input = o.field ? el.querySelector("#" + fid) : null;
      if (input) {
        input.addEventListener("keydown", function (e) {
          if (e.key !== "Enter") return;
          e.preventDefault();
          answer = true;
          sheetClose(el, "yes");
        });
      }
      el.addEventListener("click", function (e) {
        var b = e.target.closest && e.target.closest("[data-act]");
        if (!b) return;
        answer = b.getAttribute("data-act") === "yes";
        sheetClose(el, answer ? "yes" : "no");
      });
      sheetOpen(el, {
        initialFocus: input || '[data-act="no"]',
        onClose: function () {
          setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 220);
          resolve(answer && input ? (input.value.trim() || true) : answer);
        },
      });
    });
  }

  var openMenu = null;

  /** An href a menu item may carry: a same-site path ("/bd/...": one leading slash, not two, and no
   *  backslash, which a browser reads as a slash), or a mailto: or tel: link. Anything else (a
   *  javascript: or data: URL, another site) is "" and the item is drawn as a button. */
  function safeHref(href) {
    var h = String(href == null ? "" : href).trim();
    if (/[\u0000-\u001f\u007f\\]/.test(h)) return "";
    if (/^\/(?!\/)/.test(h)) return h;
    if (/^(mailto|tel):\S/i.test(h)) return h;
    return "";
  }

  function closeMenu(focusAnchor) {
    var m = openMenu;
    if (!m) return;
    openMenu = null;
    document.removeEventListener("keydown", m.onKey, true);
    document.removeEventListener("pointerdown", m.onOutside, true);
    window.removeEventListener("resize", m.onResize);
    m.anchor.setAttribute("aria-expanded", "false");
    if (m.el.parentNode) m.el.parentNode.removeChild(m.el);
    if (m.scrim.parentNode) m.scrim.parentNode.removeChild(m.scrim);
    if (focusAnchor && document.contains(m.anchor)) m.anchor.focus();
  }

  /** A small menu for `anchorBtn`, on <body> (outside <main>): items [{act, label, icon, href,
   *  danger, sub}] (`sub`: an optional second, smaller line under the label; `href`: see safeHref). Choosing one dispatches a bubbling "bd-menu" CustomEvent {detail: {act, anchor}}
   *  on the anchor and closes the menu. Arrow keys move, Escape closes, an outside click closes.
   *  On a phone it opens as a bottom action sheet. Opening the same anchor again closes it. */
  function menu(anchorBtn, items) {
    var again = openMenu && openMenu.anchor === anchorBtn;
    closeMenu(false);
    if (again || !anchorBtn) return;
    var doc = document;
    var el = doc.createElement("div");
    el.className = "menu";
    el.setAttribute("role", "menu");
    var label = anchorBtn.getAttribute("aria-label") || anchorBtn.textContent || "";
    if (label.trim()) el.setAttribute("aria-label", label.trim());
    el.innerHTML = (items || []).map(function (it) {
      var ico = it.icon && typeof window.TWIcon === "function" ? window.TWIcon(it.icon, 18) : "";
      var cls = "menu-item" + (it.danger ? " is-danger" : "");
      var inner = ico + (it.sub
        ? '<span class="menu-label"><span>' + esc(it.label) + '</span><span class="menu-sub">' + esc(it.sub) + "</span></span>"
        : "<span>" + esc(it.label) + "</span>");
      var href = safeHref(it.href);
      if (href) {
        return '<a class="' + cls + '" role="menuitem" tabindex="-1" data-act="' + esc(it.act) + '" href="' +
          esc(href) + '">' + inner + "</a>";
      }
      return '<button type="button" class="' + cls + '" role="menuitem" tabindex="-1" data-act="' +
        esc(it.act) + '">' + inner + "</button>";
    }).join("");
    var scrim = doc.createElement("div");
    scrim.className = "menu-scrim";
    scrim.setAttribute("aria-hidden", "true");
    doc.body.appendChild(scrim);
    doc.body.appendChild(el);
    anchorBtn.setAttribute("aria-haspopup", "menu");
    anchorBtn.setAttribute("aria-expanded", "true");

    var place = function () {
      var phone = window.matchMedia && !window.matchMedia("(min-width: 768px)").matches;
      el.classList.toggle("is-sheet", !!phone);
      if (phone) { el.style.top = ""; el.style.left = ""; return; }
      var r = anchorBtn.getBoundingClientRect();
      var w = el.offsetWidth, h = el.offsetHeight;
      var left = Math.min(Math.max(8, r.right - w), window.innerWidth - w - 8);
      var top = r.bottom + 6;
      if (top + h > window.innerHeight - 8 && r.top - h - 6 > 8) top = r.top - h - 6;
      el.style.left = Math.round(left + window.scrollX) + "px";
      el.style.top = Math.round(top + window.scrollY) + "px";
    };
    place();

    var list = function () { return Array.prototype.slice.call(el.querySelectorAll(".menu-item")); };
    var m = {
      el: el, scrim: scrim, anchor: anchorBtn,
      onKey: function (e) {
        var all = list(), i = all.indexOf(doc.activeElement);
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeMenu(true); }
        else if (e.key === "ArrowDown") { e.preventDefault(); all[(i + 1) % all.length].focus(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); all[(i - 1 + all.length) % all.length].focus(); }
        else if (e.key === "Home") { e.preventDefault(); all[0].focus(); }
        else if (e.key === "End") { e.preventDefault(); all[all.length - 1].focus(); }
        else if (e.key === "Tab") closeMenu(false);
      },
      onOutside: function (e) {
        if (el.contains(e.target) || anchorBtn.contains(e.target)) return;
        closeMenu(false);
      },
      onResize: function () { closeMenu(false); },
    };
    el.addEventListener("click", function (e) {
      var it = e.target.closest && e.target.closest(".menu-item");
      if (!it) return;
      var act = it.getAttribute("data-act");
      closeMenu(!it.hasAttribute("href"));
      anchorBtn.dispatchEvent(new CustomEvent("bd-menu", { bubbles: true, detail: { act: act, anchor: anchorBtn } }));
    });
    scrim.addEventListener("click", function () { closeMenu(true); });
    doc.addEventListener("keydown", m.onKey, true);
    doc.addEventListener("pointerdown", m.onOutside, true);
    window.addEventListener("resize", m.onResize);
    openMenu = m;
    var first = list()[0];
    if (first) first.focus();
  }

  window.BD = {
    BIZ_TZ: BIZ_TZ,
    esc: esc,
    money: money,
    fmtBizDate: fmtBizDate,
    fmtBizDateTime: fmtBizDateTime,
    fmtBizTime: fmtBizTime,
    bizDateOf: bizDateOf,
    bizToday: bizToday,
    bizWeekStart: bizWeekStart,
    bizNowISO: bizNowISO,
    daysBetween: daysBetween,
    nameOf: displayName,
    initialsOf: function (who) { return crm().initialsOf(displayName(who)); },
    byTs: function (get) { return crm().byTs(get); },
    normalizeCompany: normalizeCompany,
    e164: e164,
    fmtPhone: fmtPhone,
    debounce: debounce,
    qs: qs,
    LABELS: LABELS,
    VERB: VERB,
    avatarHTML: avatarHTML,
    greeting: greeting,
    plural: plural,
    fmtCount: fmtCount,
    firstName: firstName,
    fmtDay: fmtDay,
    fmtRel: fmtRel,
    chipDate: chipDate,
    fmtDuration: fmtDuration,
    weeksLeft: weeksLeft,
    paceWords: paceWords,
    pill: pill,
    statusPill: statusPill,
    kindPill: kindPill,
    firstReason: firstReason,
    telHref: telHref,
    store: store,
    sheet: { open: sheetOpen, close: sheetClose },
    dialog: dialog,
    menu: menu,
    safeHref: safeHref,
    closeMenu: closeMenu,
  };
})();
