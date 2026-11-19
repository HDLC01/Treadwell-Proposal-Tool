/* Treadwell BD CRM - the rules, as pure functions.
 *
 * PURE: no DOM, no network, no clock. Every function that needs "today" is handed it as an ISO
 * date ("2026-11-04", Central). The only thing this file writes is window.BDCore.
 *
 * WHY ONE FILE. The weekly 10, the pace bar, the cadence chip and the fallback next step are the
 * product's rules. The pages run them, and the backend (backend/bd/priority.py, backend/bd/pace.py
 * and the Friday batch) must give the same answers; the table tests in
 * backend/tests/test_bd_core_js.py are the shared spec.
 *
 * SHAPE. Every function is a declaration at exactly two spaces of indent inside the IIFE, so
 * backend/tests/js/bd/_lib.js can lift each one by name. Constants are `var` at the same indent
 * (lifted with grabConst). No nested declaration reuses a top-level name.
 *
 * The rules (BD's build plan, docs/bd/api-contract.md):
 *   touch      only a live call (answered / meeting_set), a meeting, or a hosted event
 *   pace       target = sum of frequencies; required = target x day_of_year / days_in_year
 *   frequency  frequency_per_year, or 4 (bd) / 3 (maintenance) when it is missing, 0 or bad.
 *              A BD contact's frequency is DERIVED, never typed: its active cadence override (until
 *              date on or after today) else the global bd_cadence setting, as weekly 52 / monthly 12 /
 *              quarterly 4 (CADENCE_FREQ). A maintenance contact's stays its stored number.
 *   follow-up  last_followup_at = the latest call, voicemail, meeting, hosted event, email or text
 *              (any outcome, never a note) dated on or before today. A maintenance contact is
 *              due once that + 120 days has come, or when it was never followed up.
 *   cadence    never -> complete (touches this year >= frequency; maintenance: >= 3) -> behind
 *              (due before today) -> on_track; due = last live + 365/frequency days
 *              (maintenance: + 120 days)
 *   score      the priority table; attempted in the last 3 days or already in a batch = skipped.
 *              A promised or next-step date on or before the last live talk is already met.
 *   weekly     5 new (never had a live talk) + 5 follow-ups, short side filled from the other.
 *              An unconfirmed contact keeps its kind; it only gets +8 and a "Not confirmed" chip.
 *   maintenance  a maintenance contact is on the list ONLY when due, and then it is pinned at the top
 *              as a "maintenance" task (most overdue first, never followed up first), outside the
 *              5 + 5 split, which is about the BD contacts only. A not-due one is excluded.
 */
(function () {
  "use strict";

  var MS_DAY = 86400000;
  var MAINTENANCE_TOUCH_DAYS = 120;
  var MAINTENANCE_TOUCHES = 3;
  var DEFAULT_FREQUENCY_BD = 4;
  var DEFAULT_BD_CADENCE = "quarterly";
  var CADENCE_FREQ = { weekly: 52, monthly: 12, quarterly: 4 };
  var FOLLOWUP_KINDS = ["call", "voicemail", "meeting", "hosted", "email", "sms"];
  var ATTEMPT_COOLDOWN_DAYS = 3;
  var LIVE_FOLLOWUP_DAYS = 105;
  var RETRY_DAYS = 7;
  var MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december"];
  var MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var WEEKDAYS_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var WEEKDAYS_LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var NUMBER_WORDS = { a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7,
    eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, couple: 2 };

  // ── dates (ISO strings in, ISO strings out; day maths in UTC, which has no DST) ──────────────

  /** "YYYY-MM-DD" -> days since 1970-01-01. */
  function dayNum(iso) {
    var s = String(iso).slice(0, 10);
    return Math.round(Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) / MS_DAY);
  }

  /** days since 1970-01-01 -> "YYYY-MM-DD". */
  function isoOfDay(n) {
    return new Date(n * MS_DAY).toISOString().slice(0, 10);
  }

  function addDays(iso, n) {
    return isoOfDay(dayNum(iso) + n);
  }

  /** Whole days from a to b (b - a). Both are dates or Central-offset timestamps. */
  function daysBetween(a, b) {
    return dayNum(bizDateOf(b)) - dayNum(bizDateOf(a));
  }

  /** The Central calendar date of a date or timestamp, as "YYYY-MM-DD"; "" for nothing.
   *  A bare date is returned as is. A timestamp that carries a Central offset (-05:00 / -06:00,
   *  which is how the API sends them) is read off the string. Anything else (UTC "Z", another
   *  offset) goes through Intl in America/Chicago. */
  function bizDateOf(v) {
    if (!v) return "";
    var s = String(v);
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
    if (/^\d{4}-\d{2}-\d{2}T[\d:.]+-0[56]:00$/.test(s)) return s.slice(0, 10);
    var d = new Date(s);
    if (isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Chicago", year: "numeric",
      month: "2-digit", day: "2-digit" }).format(d);
  }

  function isLeap(y) {
    return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  }

  function daysInYear(y) {
    return isLeap(y) ? 366 : 365;
  }

  /** 1 for Jan 1. */
  function dayOfYear(iso) {
    return dayNum(iso) - dayNum(String(iso).slice(0, 4) + "-01-01") + 1;
  }

  /** "2026-11-06" -> "Fri, Nov 6". */
  function shortDate(iso) {
    var n = dayNum(iso);
    var wd = WEEKDAYS_SHORT[((n % 7) + 11) % 7];   // 1970-01-01 was a Thursday
    var s = isoOfDay(n);
    return wd + ", " + MONTHS_SHORT[+s.slice(5, 7) - 1] + " " + (+s.slice(8, 10));
  }

  /** The same day next month, clamped to the month's last day (Jan 31 -> Feb 28). */
  function addMonths(iso, k) {
    var y = +iso.slice(0, 4), m = +iso.slice(5, 7) - 1 + k, d = +iso.slice(8, 10);
    y += Math.floor(m / 12); m = ((m % 12) + 12) % 12;
    var last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    return isoOfDay(Math.round(Date.UTC(y, m, Math.min(d, last)) / MS_DAY));
  }

  function plural(n, one, many) {
    return n + " " + (n === 1 ? one : (many || one + "s"));
  }

  // ── the counting rule ───────────────────────────────────────────────────────────────────────

  /** A meaningful touch: a live call, a meeting, or a hosted event. Emails, texts, notes,
   *  voicemails and unanswered calls never count, whatever a `counts_as_touch` flag says. */
  function isTouch(i) {
    if (!i) return false;
    if (i.kind === "meeting" || i.kind === "hosted") return true;
    return i.kind === "call" && (i.outcome === "answered" || i.outcome === "meeting_set");
  }

  /** A phone attempt, any outcome. */
  function isAttempt(i) {
    return !!i && (i.kind === "call" || i.kind === "voicemail");
  }

  // ── frequency ───────────────────────────────────────────────────────────────────────────

  /** Live talks a year this contact needs. A missing, 0, negative or non-number frequency (a bad
   *  import row) falls back to the category default, so pace, cadence and score agree. */
  function freqOf(c) {
    var f = Number(c && c.frequency_per_year);
    if (f > 0) return f;
    return c && c.category === "maintenance" ? MAINTENANCE_TOUCHES : DEFAULT_FREQUENCY_BD;
  }

  /** Touches this year that make the cadence "complete": 3 for maintenance (the workbook's rule,
   *  whatever its frequency says), the frequency for bd. */
  function touchesNeeded(c) {
    return c && c.category === "maintenance" ? MAINTENANCE_TOUCHES : freqOf(c);
  }

  /** weekly, monthly or quarterly (and not an inherited key such as "toString"). */
  function isCadenceWord(w) {
    return typeof w === "string" && Object.prototype.hasOwnProperty.call(CADENCE_FREQ, w);
  }

  /** True while the contact's cadence override applies: both fields set, a known cadence word, and
   *  the last day (cadence_override_until) is today or later, so the last day itself is still
   *  inside it. */
  function overrideActive(c, todayISO) {
    var until = c && c.cadence_override_until ? String(c.cadence_override_until).slice(0, 10) : "";
    return !!(c && isCadenceWord(c.cadence_override) && until && until >= todayISO);
  }

  /** The cadence a contact follows: { cadence, source }. BD: the active override ("override")
   *  else the global cadence ("global"; an unknown word is the default, quarterly).
   *  Maintenance has none: both are null. */
  function cadenceOf(c, bdCadence, todayISO) {
    if (c && c.category === "maintenance") return { cadence: null, source: null };
    if (overrideActive(c, todayISO)) return { cadence: c.cadence_override, source: "override" };
    return { cadence: isCadenceWord(bdCadence) ? bdCadence : DEFAULT_BD_CADENCE, source: "global" };
  }

  /** The follow-ups a year a contact is held to. BD: from its cadence (weekly 52, monthly 12,
   *  quarterly 4), whatever is stored. Maintenance: the stored number when it is 1 or more, else 3. */
  function effectiveFrequency(c, bdCadence, todayISO) {
    if (c && c.category === "maintenance") {
      var f = Number(c.frequency_per_year);
      return f >= 1 ? f : MAINTENANCE_TOUCHES;
    }
    return CADENCE_FREQ[cadenceOf(c, bdCadence, todayISO).cadence];
  }

  // ── follow-ups and the maintenance due date ──────────────────────────────────────────────────

  /** The timestamp of the latest follow-up action (call, voicemail, meeting, hosted event, email
   *  or text, any outcome; never a note) dated on or before today, or null. `interactions` are
   *  this contact's; a later one is picked by the instant, whatever offset it is written in. */
  function lastFollowupAt(interactions, todayISO) {
    var best = null, bestMs = -Infinity;
    (interactions || []).forEach(function (i) {
      if (!i || FOLLOWUP_KINDS.indexOf(i.kind) === -1 || bizDateOf(i.occurred_at) > todayISO) return;
      var t = new Date(i.occurred_at).getTime();
      if (t > bestMs) { bestMs = t; best = i.occurred_at; }
    });
    return best;
  }

  /** A maintenance contact's follow-up date: the day of the last follow-up + 120 days; null for BD
   *  and for a maintenance contact never followed up. */
  function maintenanceDueDate(c, lastFollowup) {
    if (!c || c.category !== "maintenance" || !lastFollowup) return null;
    return addDays(bizDateOf(lastFollowup), MAINTENANCE_TOUCH_DAYS);
  }

  /** Maintenance, and never followed up or the follow-up date has come (today counts). */
  function isMaintenanceDue(c, lastFollowup, todayISO) {
    if (!c || c.category !== "maintenance") return false;
    return !lastFollowup || maintenanceDueDate(c, lastFollowup) <= todayISO;
  }

  // ── pace and weekly progress ────────────────────────────────────────────────────────────────

  /** The annual pace over `contacts` (every contact the owner owns, bd and maintenance).
   *  Only touches in the current Central year, up to and including today, are counted. */
  function pace(contacts, interactions, todayISO) {
    var year = +String(todayISO).slice(0, 4);
    var ids = {};
    var target = 0;
    (contacts || []).forEach(function (c) {
      ids[c.id] = true;
      target += freqOf(c);
    });
    var completed = 0;
    (interactions || []).forEach(function (i) {
      if (!isTouch(i) || !ids[i.contact_id]) return;
      var d = bizDateOf(i.occurred_at);
      if (d && +d.slice(0, 4) === year && d <= todayISO) completed += 1;
    });
    var required = Math.round(10 * target * dayOfYear(todayISO) / daysInYear(year)) / 10;
    var pct = target > 0 ? Math.round(100 * completed / target) : 0;
    var delta = Math.round(completed - required);
    if (delta === 0) delta = 0;                      // no "-0"
    return {
      year: year,
      as_of: todayISO,
      required_to_date: required,
      completed: completed,
      target_total: target,
      pct: pct,
      delta: delta,
      label: paceLabel(year, pct, delta),
    };
  }

  function paceLabel(year, pct, delta) {
    var head = year + " BD Pace: " + pct + "% — ";
    if (delta === 0) return head + "right on pace";
    return head + plural(Math.abs(delta), "interaction") + (delta > 0 ? " ahead of pace" : " behind pace");
  }

  /** "Did I do my 10?" Snoozed tasks still count in the total: a slot is never refilled. */
  function weeklyProgress(tasks) {
    var list = tasks || [];
    var done = list.filter(function (t) { return t.status === "done"; }).length;
    return { done: done, total: list.length, label: done + " of " + list.length + " done" };
  }

  // ── cadence ─────────────────────────────────────────────────────────────────────────────────

  /** Days between live touches this contact needs. */
  function cadenceIntervalDays(contact) {
    if (contact.category === "maintenance") return MAINTENANCE_TOUCH_DAYS;
    return Math.floor(365 / freqOf(contact));
  }

  /** last live + the interval, or null when never reached. */
  function nextDueDate(contact) {
    var last = bizDateOf(contact.last_live_at);
    return last ? addDays(last, cadenceIntervalDays(contact)) : null;
  }

  /** "never" | "complete" | "behind" | "on_track", checked in that order (api-contract.md).
   *  Maintenance: complete at 3 touches this year (MAINTENANCE_TOUCHES), behind once last touch +
   *  120 days has passed. BD: behind once the days since the last live talk pass 365/frequency. */
  function cadenceStatus(contact, todayISO) {
    if (!contact.last_live_at) return "never";
    if ((Number(contact.touches_this_year) || 0) >= touchesNeeded(contact)) return "complete";
    return nextDueDate(contact) < todayISO ? "behind" : "on_track";
  }

  /** The derived fields of one contact, recomputed from its interactions (the server's
   *  contacts_summary view does the same). `bdCadence` is the global setting (weekly | monthly |
   *  quarterly; anything else is quarterly). Besides the touch fields it sets the cadence fields
   *  (cadence, cadence_source), the DERIVED frequency_per_year of a BD contact, and the follow-up
   *  clock (last_followup_at, maintenance_due_date, maintenance_due). Returns a NEW object; the
   *  input is not touched. */
  function deriveContact(contact, interactions, todayISO, bdCadence) {
    var year = String(todayISO).slice(0, 4);
    var mine = (interactions || []).filter(function (i) {
      return i.contact_id === contact.id && bizDateOf(i.occurred_at) <= todayISO;
    }).sort(function (a, b) { return a.occurred_at < b.occurred_at ? -1 : (a.occurred_at > b.occurred_at ? 1 : 0); });
    var lastLive = null, lastAttempt = null, since = 0, touches = 0;
    mine.forEach(function (i) {
      if (isAttempt(i)) lastAttempt = i.occurred_at;
      if (isTouch(i)) {
        lastLive = i.occurred_at; since = 0;
        if (bizDateOf(i.occurred_at).slice(0, 4) === year) touches += 1;
      } else if (isAttempt(i)) {
        since += 1;
      }
    });
    var out = {};
    Object.keys(contact).forEach(function (k) { out[k] = contact[k]; });
    var cad = cadenceOf(contact, bdCadence, todayISO);
    var followup = lastFollowupAt(mine, todayISO);
    out.cadence_override = contact.cadence_override || null;
    out.cadence_override_until = contact.cadence_override_until || null;
    out.cadence = cad.cadence;
    out.cadence_source = cad.source;
    out.frequency_per_year = effectiveFrequency(contact, bdCadence, todayISO);
    out.last_followup_at = followup;
    out.maintenance_due_date = maintenanceDueDate(contact, followup);
    out.maintenance_due = isMaintenanceDue(contact, followup, todayISO);
    out.last_live_at = lastLive;
    out.last_attempt_at = lastAttempt;
    out.attempts_since_live = since;
    out.touches_this_year = touches;
    out.next_due_date = nextDueDate(out);
    out.cadence_status = cadenceStatus(out, todayISO);
    return out;
  }

  // ── the fallback next step (used whenever the AI is off or fails) ───────────────────────────

  /** A date the customer asked for, read from free text, or null.
   *  Understands "next month", "next week", "in N days|weeks|months" (digits or words, "a couple
   *  of"), and "after <Month>" (the 1st of the following month, this year or next). */
  function parseAskedDate(text, todayISO) {
    var said = String(text || "").replace(/\s+/g, " ");      // the words as typed, for the reason
    var t = said.toLowerCase();
    if (!t) return null;
    var m = /\bin (?:about |around )?(\d{1,2}|a couple of|a couple|an|a|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve) (day|week|month)s?\b/.exec(t);
    if (m) {
      var word = m[1].replace(/ of$/, "").replace(/^a couple$/, "couple");
      var n = /^\d+$/.test(word) ? +word : NUMBER_WORDS[word];
      if (n > 0) {
        var unit = m[2];
        var due = unit === "day" ? addDays(todayISO, n) : (unit === "week" ? addDays(todayISO, 7 * n) : addMonths(todayISO, n));
        return { due_date: due, phrase: said.substr(m.index, m[0].length) };
      }
    }
    m = /\bafter (january|february|march|april|may|june|july|august|september|october|november|december)\b/.exec(t);
    if (m) {
      var mi = MONTHS.indexOf(m[1]);
      var y = +todayISO.slice(0, 4);
      var cur = +todayISO.slice(5, 7) - 1;
      if (mi < cur) y += 1;                      // "after March" said in November = next March
      var next = mi + 1;
      if (next > 11) { next = 0; y += 1; }
      return { due_date: y + "-" + (next < 9 ? "0" : "") + (next + 1) + "-01", phrase: said.substr(m.index, m[0].length) };
    }
    if (/\bnext month\b/.test(t)) return { due_date: addMonths(todayISO, 1), phrase: "next month" };
    if (/\bnext week\b/.test(t)) return { due_date: addDays(todayISO, 7), phrase: "next week" };
    return null;
  }

  /** The rule-based next action after an interaction. `outcome` is the call outcome
   *  (answered | meeting_set | voicemail | no_answer) or the kind for a meeting/hosted event.
   *  A date the customer asked for in `text` wins over the outcome rule. */
  function fallbackNextAction(outcome, text, todayISO) {
    var asked = parseAskedDate(text, todayISO);
    if (asked) {
      return { action: "Call back on the date they asked for", due_date: asked.due_date,
        reason: "They said “" + asked.phrase + "”. Call on " + shortDate(asked.due_date) + ".",
        source: "fallback" };
    }
    var live = outcome === "answered" || outcome === "meeting_set" || outcome === "meeting" || outcome === "hosted";
    if (live) {
      return { action: "Check in again in about 3–4 months", due_date: addDays(todayISO, LIVE_FOLLOWUP_DAYS),
        reason: (outcome === "meeting_set" ? "Meeting set." : (outcome === "answered" ? "Good live call." : "Met in person.")) +
          " Check in again in about 3–4 months.",
        source: "fallback" };
    }
    return { action: "Try again next week", due_date: addDays(todayISO, RETRY_DAYS),
      reason: (outcome === "voicemail" ? "Voicemail." : "No answer.") + " Try again in a week.",
      source: "fallback" };
  }

  // ── priority ────────────────────────────────────────────────────────────────────────────────

  /** "3 months ago" / "2 weeks ago" / "5 days ago" for a gap in days. The ONE way the app says
   *  how long ago something was: the reason chip and the card's "Last talked" line both use it. */
  function agoText(days) {
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days >= 45) return plural(Math.floor(days / 30), "month") + " ago";
    if (days >= 14) return plural(Math.floor(days / 7), "week") + " ago";
    return plural(days, "day") + " ago";
  }

  /** When an attempt happened, in words for a follow-up message: "today", "yesterday",
   *  "on Monday" (within the past week), else "on Jun 25". */
  function whenPhrase(iso, todayISO) {
    var day = bizDateOf(iso);
    if (!day) return "recently";
    var gap = dayNum(todayISO) - dayNum(day);
    if (gap <= 0) return "today";
    if (gap === 1) return "yesterday";
    if (gap < 7) return "on " + WEEKDAYS_LONG[((dayNum(day) % 7) + 11) % 7];
    return "on " + shortDate(day).slice(5);
  }

  /** The priority points of one contact and the plain-English reasons, strongest first.
   *  `facts` overrides or adds to the contact: { has_open_task, last_quote_date, ... }.
   *  Returns { score, reasons, excluded, exclude_reason }. An excluded contact still gets a
   *  score (managers may want to see it); pickWeekly leaves it out. The exclusions are checked in
   *  this order: archived, already in a batch, tried in the last 3 days, maintenance but not due. */
  function scoreContact(contact, facts, todayISO) {
    var c = {};
    Object.keys(contact || {}).forEach(function (k) { c[k] = contact[k]; });
    Object.keys(facts || {}).forEach(function (k) { c[k] = facts[k]; });
    var parts = [];        // {points, text, order}
    function add(points, text) { parts.push({ points: points, text: text, order: parts.length }); }

    var triesAll = Number(c.attempts_since_live) || 0;
    if (!c.last_live_at) {
      // One phrase for a never-reached contact: "2 tries since the last live talk" would describe
      // a live talk that never happened.
      add(40, triesAll > 0 ? "Never reached after " + plural(triesAll, "try", "tries") : "Never contacted");
    } else {
      var since = daysBetween(c.last_live_at, todayISO);
      var interval = c.category === "maintenance" ? MAINTENANCE_TOUCH_DAYS : 365 / freqOf(c);
      var cadence = Math.min(40, Math.round(30 * since / interval));
      var need = "needs " + touchesNeeded(c) + " a year";
      if (cadence > 0) add(cadence, "Last live talk " + agoText(since) + "; " + need);
    }

    // A date on or before the last live talk was met by that talk: it never adds points again.
    var lastLive = bizDateOf(c.last_live_at);
    var dates = [c.promised_date, c.next_step_date].filter(function (x) {
      return x && !(lastLive && lastLive >= bizDateOf(x));
    }).sort();
    if (dates.length) {
      var d = dates[0];
      var promised = d === c.promised_date;
      var gap = daysBetween(todayISO, d);
      var what = promised ? "Promised a call by " : "Next step due ";
      if (gap <= 0) add(50, what + shortDate(d));
      else if (gap <= 7) add(25, what + shortDate(d));
    }

    if (c.last_quote_date) {
      var q = daysBetween(c.last_quote_date, todayISO);
      // Worded as a sign of an active account, never as a quote to chase: quote follow-up stays in
      // the proposal tool and the portal.
      if (q >= 0 && q <= 30) add(15, "Recent quote activity (" + shortDate(c.last_quote_date) + ")");
    }

    var imp = Number(c.importance) || 1;
    // Importance 2 adds points but no words: "Important account" on half the cards says nothing.
    if (imp >= 3) add(20, "Key account");
    else if (imp === 2) add(10, null);

    var tries = Math.min(3, triesAll);
    if (tries > 0) add(5 * tries, c.last_live_at ? plural(triesAll, "try", "tries") + " since the last live talk" : null);

    if (c.confirmed === false) add(8, "Needs confirming: still the right person?");

    var score = parts.reduce(function (s, p) { return s + p.points; }, 0);
    var reasons = parts.filter(function (p) { return p.text; })
      .sort(function (a, b) { return b.points - a.points || a.order - b.order; })
      .map(function (p) { return p.text; });

    var excluded = false, why = null;
    if (c.archived_at) { excluded = true; why = "archived"; }
    else if (c.has_open_task) { excluded = true; why = "already in this week's list"; }
    else if (c.last_attempt_at && daysBetween(c.last_attempt_at, todayISO) < ATTEMPT_COOLDOWN_DAYS) {
      excluded = true; why = "tried in the last 3 days";
    }
    else if (c.category === "maintenance" && !c.maintenance_due) {
      excluded = true; why = "maintenance, not due yet";
    }
    return { score: score, reasons: reasons, excluded: excluded, exclude_reason: why };
  }

  /** The chip text: the top two reasons as sentences. */
  function reasonText(reasons) {
    return (reasons || []).slice(0, 2).map(function (r) { return /[.?!]$/.test(r) ? r : r + "."; }).join(" ");
  }

  /** "maintenance" (a due maintenance contact), "new" (never had a live talk) or "followup"
   *  (everyone else). Whether the contact is confirmed does not change the kind: an unconfirmed
   *  contact with a promised call is still a follow-up (it gets +8 points and a "Not confirmed"
   *  chip instead). */
  function taskKind(contact) {
    if (contact.category === "maintenance" && contact.maintenance_due) return "maintenance";
    return !contact.last_live_at ? "new" : "followup";
  }

  /** Why a due maintenance contact is on the list, first among its reasons: "No follow-up logged
   *  yet" (never followed up), "Follow-up due today", or "Follow-up was due Fri, Nov 6". */
  function maintenanceDueReason(contact, todayISO) {
    var due = contact.maintenance_due_date ? bizDateOf(contact.maintenance_due_date) : "";
    if (!contact.last_followup_at || !due) return "No follow-up logged yet";
    if (due === todayISO) return "Follow-up due today";
    return "Follow-up was due " + shortDate(due);
  }

  /** Due maintenance contacts first (most overdue first: the earliest follow-up date, never
   *  followed up before any date, then the lower id), then everyone else by score, best first
   *  (ties: lower id first). The two tiers never mix. */
  function rankOrder(a, b) {
    var am = a.kind === "maintenance", bm = b.kind === "maintenance";
    if (am !== bm) return am ? -1 : 1;
    if (am) {
      var ad = a.contact.maintenance_due_date || "", bd = b.contact.maintenance_due_date || "";
      if (ad !== bd) return ad < bd ? -1 : 1;                // "" (never followed up) sorts first
      return a.contact.id - b.contact.id;
    }
    return b.score - a.score || a.contact.id - b.contact.id;
  }

  /** Every contact that may be suggested, scored, in list order: due maintenance first, then BD
   *  by score. A maintenance contact that is not due is not suggested at all. A due one's reasons
   *  start with why it is due; its score is the normal priority score. */
  function rankContacts(contacts, interactions, excludeIds, todayISO, bdCadence) {
    var skip = {};
    (excludeIds || []).forEach(function (id) { skip[id] = true; });
    var out = [];
    (contacts || []).forEach(function (raw) {
      var c = interactions ? deriveContact(raw, interactions, todayISO, bdCadence) : raw;
      var s = scoreContact(c, { has_open_task: !!skip[c.id] }, todayISO);
      if (s.excluded) return;
      var kind = taskKind(c);
      var reasons = kind === "maintenance" ? [maintenanceDueReason(c, todayISO)].concat(s.reasons) : s.reasons;
      out.push({ contact: c, kind: kind, score: s.score, reasons: reasons, reason: reasonText(reasons) });
    });
    out.sort(rankOrder);
    return out;
  }

  /** The Friday batch: every due maintenance contact first (most overdue first), then nNew "new"
   *  + nFollow "followup" BD tasks, best first. When one BD side is short the other fills the gap,
   *  so the BD part reaches nNew + nFollow whenever enough people are left; the maintenance ones
   *  are on top of that, so more than 10 due makes the batch longer. `openTaskContactIds` (ids
   *  already in a batch this week) and anyone tried in the last 3 days are left out.
   *  `interactions` may be null to trust the contacts' derived fields.
   *  Returns [{contact_id, contact, kind, score, reason, reasons}]. */
  function pickWeekly(contacts, interactions, openTaskContactIds, todayISO, nNew, nFollow, bdCadence) {
    var wantNew = nNew == null ? 5 : nNew;
    var wantFollow = nFollow == null ? 5 : nFollow;
    var ranked = rankContacts(contacts, interactions, openTaskContactIds, todayISO, bdCadence);
    var pinned = ranked.filter(function (r) { return r.kind === "maintenance"; });
    var news = ranked.filter(function (r) { return r.kind === "new"; });
    var follows = ranked.filter(function (r) { return r.kind === "followup"; });
    var takeNew = Math.min(wantNew, news.length);
    var takeFollow = Math.min(wantFollow, follows.length);
    var room = wantNew + wantFollow - takeNew - takeFollow;
    if (room > 0 && takeNew < news.length) { var a = Math.min(room, news.length - takeNew); takeNew += a; room -= a; }
    if (room > 0 && takeFollow < follows.length) { takeFollow += Math.min(room, follows.length - takeFollow); }
    var picked = news.slice(0, takeNew).concat(follows.slice(0, takeFollow));
    picked.sort(function (x, y) { return y.score - x.score || x.contact.id - y.contact.id; });
    return pinned.concat(picked).map(toTask);
  }

  /** "Give Me 10 More": the next n of the same ranking, whatever their kind. A maintenance contact
   *  that came due mid-week heads the list as a maintenance task. */
  function pickNext(contacts, interactions, excludeIds, todayISO, n, bdCadence) {
    return rankContacts(contacts, interactions, excludeIds, todayISO, bdCadence).slice(0, n == null ? 10 : n).map(toTask);
  }

  function toTask(r) {
    return { contact_id: r.contact.id, contact: r.contact, kind: r.kind, score: r.score,
      reason: r.reason, reasons: r.reasons };
  }

  window.BDCore = {
    CADENCE_FREQ: CADENCE_FREQ,
    MAINTENANCE_TOUCH_DAYS: MAINTENANCE_TOUCH_DAYS,
    MAINTENANCE_TOUCHES: MAINTENANCE_TOUCHES,
    ATTEMPT_COOLDOWN_DAYS: ATTEMPT_COOLDOWN_DAYS,
    dayNum: dayNum,
    addDays: addDays,
    addMonths: addMonths,
    daysBetween: daysBetween,
    bizDateOf: bizDateOf,
    dayOfYear: dayOfYear,
    daysInYear: daysInYear,
    shortDate: shortDate,
    agoText: agoText,
    whenPhrase: whenPhrase,
    isTouch: isTouch,
    isAttempt: isAttempt,
    pace: pace,
    paceLabel: paceLabel,
    weeklyProgress: weeklyProgress,
    freqOf: freqOf,
    cadenceOf: cadenceOf,
    effectiveFrequency: effectiveFrequency,
    lastFollowupAt: lastFollowupAt,
    maintenanceDueDate: maintenanceDueDate,
    isMaintenanceDue: isMaintenanceDue,
    touchesNeeded: touchesNeeded,
    cadenceIntervalDays: cadenceIntervalDays,
    nextDueDate: nextDueDate,
    cadenceStatus: cadenceStatus,
    deriveContact: deriveContact,
    parseAskedDate: parseAskedDate,
    fallbackNextAction: fallbackNextAction,
    scoreContact: scoreContact,
    reasonText: reasonText,
    taskKind: taskKind,
    maintenanceDueReason: maintenanceDueReason,
    rankContacts: rankContacts,
    pickWeekly: pickWeekly,
    pickNext: pickNext,
  };
})();
