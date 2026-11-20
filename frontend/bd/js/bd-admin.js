/* BD's Admin page, /bd/admin.html (#809: BD's js/admin.js, moved in as it works today, restyled like
 * the proposal tool by the approved BD mock-up).
 *
 * An admin sees everything: the People table (each person's BD role and whether their BD login is on),
 * the Friday list settings and "Make a list now", the yearly goals (editable) and the counting rule
 * (fixed), the lead-source and industry pick lists, the phone system status and the unmatched calls,
 * and the workbook import with its history. The assistant sees only the unmatched calls and the
 * imports; nothing admin-only is even asked for her.
 *
 * This page is BD's own. It is apart from the proposal tool's Admin page (/admin.html) and changes BD
 * logins only (GET/POST/PATCH /api/bd/admin/users): never a tool profile, role, sidebar policy or
 * Special permission. Who may open the BD CRM at all is the tool's Admin page's business.
 *
 * WHAT CHANGED IN THE MOVE:
 *   - BD's own shell (BDAuth) is gone: the page reads who this is from TWAuth.bdMe() (the one
 *     /api/bd/me answer the sidebar's BD group reads), and a failed answer is said in
 *     TWAuth.bdFailure's words. Each section is shown by `can`, never by a role name:
 *       admin          People, Friday list, Goals, Pick lists, the phone status
 *       admin_area     the page itself (BD's page gate) and the unmatched calls (the assistant's part)
 *       import         Imports: the workbook import and past imports, for whoever the page opens for
 *       manage_admins  the admin roles in the People table, and an admin's row (Q29: the super admin's
 *                      alone). A plain admin's locked row, and the add form, say why.
 *     A person with neither admin nor admin_area is told Admin is not part of their BD role. That is
 *     the salesperson too (#810): BD's sidebar never showed them Admin, and their import is back on
 *     Contacts, where BD had it.
 *   - THE IMPORT. #809 put it here, at the top of Past imports, while Contacts had not moved; #810 put
 *     it back on Contacts. Both pages open the one dialog, BD.importWorkbook (bd-shared.js): a
 *     practice run first, then "Import now".
 *   - The unknown calls' words and their dismiss dialog are bd-shared.js's (BD.callWords,
 *     BD.dismissCall): Contacts shows the newest three, with links here to attach them.
 *   - A new login's email is checked by the server (the tool's sign-in domain), not by the page.
 *   - Confirmations are BD.dialog's, the attach form opens with BD.sheet (bd-shared.js's focus trap),
 *     toasts are BD.toast's, and every route is under /api/bd/ (docs/bd/api-contract.md, "Admin").
 *   - "Open contact" after an attach goes to the contact page, a /bd/ page, through BD.pageHref.
 */
(function () {
  "use strict";

  var BD = window.BD, Api = window.BDApi;
  var esc = BD.esc, errText = BD.errText, setBusy = BD.setBusy, pill = BD.pill;

  var DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
  // The run builds next week's list and closes this week's open tasks: the end of the week only
  // (the server's weekly.ALLOWED_RUN_DAYS).
  var RUN_DAYS = ["friday", "saturday", "sunday"];
  var BASE_ROLES = ["salesperson", "assistant", "manager"];
  var ADMIN_ROLES = ["admin", "super_admin"];
  var LIST_SIZE = 10;            // the Friday list is always 10: new people + follow-ups

  var S = {
    me: null, can: {}, today: "",
    users: [], settings: null, telephony: null, unmatched: [], imports: [],
    draft: { lead_sources: [], industries: [] },
  };

  function $(id) { return document.getElementById(id); }
  function ico(name, size) { return BD.icon(name, size || 16); }
  function cap(s) { return String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1); }
  function hourLabel(h) { return ((Number(h) % 12) || 12) + ":00 " + (Number(h) < 12 ? "AM" : "PM"); }
  function sameList(a, b) { return JSON.stringify(a || []) === JSON.stringify(b || []); }
  function roleWord(r) { return BD.LABELS.role[r] || r; }
  function isAdminRole(r) { return ADMIN_ROLES.indexOf(r) !== -1; }
  function full() { return S.can.admin === true; }
  function mayManageAdmins() { return S.can.manage_admins === true; }
  /** An email that may break after its "@" on a narrow screen, never cut off. */
  function emailHtml(s) { return esc(s).replace("@", "<wbr>@"); }
  function focusId(id) {
    var n = id && $(id);
    if (n && !n.disabled && n.focus) { n.focus(); return true; }
    return false;
  }

  /** A section that did not load: the reason and Try again (one click handler on the box, so a
   *  redraw never leaves a dead button). */
  function sectionError(box, e, retry) {
    if (!box) return;
    BD.errorBox(box, e);
    box._adRetry = retry;
  }
  function wireRetry(box) {
    if (!box) return;
    box.addEventListener("click", function (e) {
      var b = e.target.closest && e.target.closest("[data-retry]");
      if (b && typeof box._adRetry === "function") box._adRetry();
    });
  }

  function showFieldErrors(form, fields) {
    if (!form || !form.querySelectorAll) return;
    Array.prototype.forEach.call(form.querySelectorAll(".field"), function (f) {
      f.classList.remove("has-error");
      var old = f.querySelector(".field-error");
      if (old) old.parentNode.removeChild(old);
    });
    Object.keys(fields || {}).forEach(function (k) {
      var input = form.querySelector('[name="' + k + '"]');
      var field = input && input.closest(".field");
      if (!field) return;
      field.classList.add("has-error");
      var msg = document.createElement("div");
      msg.className = "field-error";
      msg.setAttribute("role", "alert");
      msg.textContent = fields[k];
      field.appendChild(msg);
    });
  }

  // ── people (BD logins) ───────────────────────────────────────────────────────────────────
  /** The roles this person may give: an admin role only with can.manage_admins (a plain admin can't
   *  make or change an admin). A locked admin row still shows its own role. */
  function roleOptions(current) {
    var list = BASE_ROLES.slice();
    if (mayManageAdmins()) list = list.concat(ADMIN_ROLES);
    else if (isAdminRole(current)) list.push(current);
    return list.map(function (r) {
      return '<option value="' + esc(r) + '"' + (r === current ? " selected" : "") + ">" + esc(roleWord(r)) + "</option>";
    }).join("");
  }

  function userById(id) { return S.users.filter(function (x) { return x.id === id; })[0] || null; }

  function userRow(u) {
    var self = S.me && u.id === S.me.id;
    var locked = self || (isAdminRole(u.role) && !mayManageAdmins());
    var why = self ? "You can't change your own role or sign-in." : (locked ? "Only a super admin can change an admin." : "");
    var seen = u.last_seen_at ? BD.fmtBizDate(u.last_seen_at, "short") + ", " + BD.fmtBizTime(u.last_seen_at) : "Not signed in yet";
    var id = esc(u.id);
    return '<tr class="ad-user" data-id="' + id + '">' +
      '<td class="ad-c-who"><div class="ad-who">' + BD.avatarHTML(u) +
      '<div class="who"><span class="who-name">' + esc(u.name) + (self ? " " + pill("outline", "You") : "") +
      (u.active ? "" : " " + pill("warn", "Cannot sign in")) + "</span>" +
      '<span class="who-sub">' + emailHtml(u.email) + "</span></div></div></td>" +
      '<td class="ad-c-role"><label for="ad-role-' + id + '" class="sr-only">BD role for ' + esc(u.name) + "</label>" +
      '<select class="select ad-role" id="ad-role-' + id + '" data-role' + (locked ? " disabled" : "") +
      (why ? ' aria-describedby="ad-why-' + id + '"' : "") + ">" + roleOptions(u.role) + "</select>" +
      (why ? '<span class="ad-why" id="ad-why-' + id + '">' + esc(why) + "</span>" : "") + "</td>" +
      '<td class="ad-c-active"><label class="ad-switch"><button type="button" class="switch" role="switch" id="ad-active-' + id +
      '" data-active aria-checked="' + (u.active ? "true" : "false") + '" aria-label="' + (u.active ? "Active" : "Off") +
      ", sign-in for " + esc(u.name) + '"' +
      (locked ? " disabled" : "") + "></button>" + "<span>" + (u.active ? "Active" : "Off") + "</span></label></td>" +
      '<td class="ad-c-seen">' + (u.last_seen_at ? '<span class="ad-seen-label">Last seen </span>' : "") + esc(seen) + "</td></tr>";
  }

  /** Redraws the table and the add form. `keep` is the id of the control to focus again. */
  function renderUsers(keep) {
    var box = $("ad-users");
    box.innerHTML =
      (S.users.length
        ? '<div class="table-wrap ad-table-wrap"><table class="table ad-users"><caption class="sr-only">People who can sign in to the BD CRM</caption><thead><tr>' +
          '<th scope="col">Person</th><th scope="col">BD role</th><th scope="col">Sign-in</th><th scope="col">Last seen</th></tr></thead><tbody>' +
          S.users.map(userRow).join("") + "</tbody></table></div>"
        : '<div class="empty"><p class="empty-text">No BD logins yet.</p></div>') +
      '<form class="ad-form ad-add-user" id="ad-add-user" novalidate>' +
      '<h3 class="ad-sub-title">Add a person</h3>' +
      '<div class="ad-grid ad-grid-3">' +
      '<div class="field"><label for="ad-new-email">Work email</label><input class="input" id="ad-new-email" name="email" type="email" autocomplete="off" /></div>' +
      '<div class="field"><label for="ad-new-name">Name</label><input class="input" id="ad-new-name" name="name" type="text" autocomplete="off" maxlength="120" placeholder="First name" /></div>' +
      '<div class="field"><label for="ad-new-role">BD role</label><select class="select" id="ad-new-role" name="role"' +
      (mayManageAdmins() ? "" : ' aria-describedby="ad-new-role-hint"') + ">" + roleOptions("salesperson") + "</select>" +
      (mayManageAdmins() ? "" : '<span class="field-hint" id="ad-new-role-hint">Only a super admin can add an admin.</span>') +
      "</div></div>" +
      '<div class="wrap-row"><button type="submit" class="btn btn-primary">' + ico("user-plus", 18) + "Add person</button>" +
      '<span class="field-hint">They sign in with their Treadwell Google account.</span></div></form>';
    if (keep) focusId(keep);
  }

  function replaceUser(u, keep) {
    S.users = S.users.map(function (x) { return x.id === u.id ? u : x; });
    renderUsers(keep);
    renderRunOwner();
  }

  /** PATCH one login. opts: {ok(user) -> message, keep (control id), undo (body to put it back)}. */
  function patchUser(id, body, opts) {
    return Api.patch(Api.path("admin", "users", id), body).then(function (res) {
      replaceUser(res.user, opts.keep);
      var t = { kind: "ok" };
      if (opts.undo) {
        t.ms = 8000;
        t.action = { label: "Undo", onClick: function () {
          patchUser(id, opts.undo, { keep: opts.keep, ok: function (nu) { return "Put back: " + nu.name + " is " + roleWord(nu.role).toLowerCase() + " again."; } });
        } };
      }
      BD.toast(opts.ok(res.user), t);
    }, function (e) {
      renderUsers(opts.keep);                         // put the control back where it was
      BD.toast(errText(e), { kind: "error" });
    });
  }

  function changeRole(sel) {
    var id = Number(sel.closest(".ad-user").getAttribute("data-id"));
    var u = userById(id);
    if (!u) return;
    var from = u.role, to = sel.value, keep = sel.id;
    if (to === from) return;
    var go = function () {
      patchUser(id, { role: to }, { keep: keep, undo: { role: from },
        ok: function (nu) { return nu.name + " is now " + roleWord(nu.role).toLowerCase() + "."; } });
    };
    if (from !== "salesperson") { go(); return; }
    // Moving off salesperson takes away a weekly list: ask first.
    var others = S.users.filter(function (x) { return x.role === "salesperson" && x.active && x.id !== id; }).length;
    BD.dialog({
      title: "Make " + u.name + " " + roleWord(to).toLowerCase() + "?",
      text: u.name + " stops getting a weekly list of 10." +
        (others ? "" : " Nobody else is a salesperson, so no weekly list is made until someone is."),
      yes: "Yes, make " + roleWord(to).toLowerCase(),
    }).then(function (yes) {
      if (yes) { go(); return; }
      sel.value = from;
      sel.focus();
    });
  }

  function toggleActive(sw) {
    var id = Number(sw.closest(".ad-user").getAttribute("data-id"));
    var u = userById(id);
    if (!u) return;
    var keep = sw.id;
    var go = function () {
      patchUser(id, { active: !u.active }, { keep: keep,
        ok: function (nu) { return nu.name + (nu.active ? " can sign in again." : " can no longer sign in."); } });
    };
    if (!u.active) { go(); return; }
    BD.dialog({
      title: "Turn off sign-in for " + u.name + "?",
      text: u.name + " can't open the BD CRM until you turn it back on. Nothing they added is lost.",
      yes: "Turn off sign-in",
      danger: true,
    }).then(function (yes) { if (yes) go(); });
  }

  function wireUsers() {
    var box = $("ad-users");
    box.addEventListener("change", function (e) {
      var sel = e.target.closest && e.target.closest("select[data-role]");
      if (sel) changeRole(sel);
    });
    box.addEventListener("click", function (e) {
      var sw = e.target.closest && e.target.closest("button[data-active]");
      if (sw) toggleActive(sw);
    });
    box.addEventListener("submit", function (e) {
      var form = e.target.closest && e.target.closest("#ad-add-user");
      if (!form) return;
      e.preventDefault();
      var btn = form.querySelector('button[type="submit"]');
      var body = { email: form.elements.email.value.trim(), name: form.elements.name.value.trim(), role: form.elements.role.value };
      var fields = {};
      if (!/^[^@\s]+@[^@\s]+$/.test(body.email)) fields.email = "Type their work email.";
      showFieldErrors(form, fields);
      if (Object.keys(fields).length) { form.elements.email.focus(); return; }
      setBusy(btn, true);
      Api.post("/api/bd/admin/users", body).then(function (res) {
        S.users.push(res.user);
        renderUsers("ad-new-email");
        renderRunOwner();
        BD.toast(res.user.name + " was added as " + roleWord(res.user.role).toLowerCase() + ".", { kind: "ok" });
      }, function (err) {
        setBusy(btn, false);
        showFieldErrors(form, err && err.fields);
        BD.toast(err && err.message ? err.message : "That person was not added.", { kind: "error" });
      });
    });
    $("ad-add-jump").insertAdjacentHTML("afterbegin", ico("user-plus", 18));
    $("ad-add-jump").addEventListener("click", function () {
      var f = $("ad-new-email");
      if (!f) return;
      f.scrollIntoView({ block: "center" });
      f.focus();
    });
  }

  function loadUsers() {
    return Api.get("/api/bd/admin/users").then(function (res) { S.users = res.items || []; renderUsers(); })
      .catch(function (e) { sectionError($("ad-users"), e, loadUsers); });
  }

  // ── Friday list ──────────────────────────────────────────────────────────────────────────
  function fridayHint(w) {
    return w.enabled ? "Runs " + cap(String(w.run_day || "")).slice(0, 3) + " " + hourLabel(w.run_hour) + " Central, for the next week." : "Off. Nothing is made on its own.";
  }

  function followups(n) { return Number.isInteger(n) && n >= 0 && n <= LIST_SIZE ? LIST_SIZE - n : null; }

  /** The Monday of this week and of next week (Central). */
  function weekChoices() {
    var ws = BD.bizWeekStart(S.today);
    return { "this": ws, next: window.BDCore.addDays(ws, 7) };
  }

  /** "Next week" once the automatic run time has passed this week (a Friday 4 PM run that failed,
   *  fixed on Friday evening or the weekend), else "this week". The hour is Central's. */
  function defaultRunWeek() {
    var w = (S.settings && S.settings.weekly) || {};
    var dayIdx = BD.daysBetween(BD.bizWeekStart(S.today), S.today);          // Mon 0 .. Sun 6
    var runIdx = DAYS.indexOf(w.run_day);
    var hour = Number(String(BD.bizNowISO(S.today)).slice(11, 13));
    if (runIdx === -1) return "this";
    return dayIdx > runIdx || (dayIdx === runIdx && hour >= Number(w.run_hour)) ? "next" : "this";
  }

  function renderFriday() {
    var w = S.settings.weekly || {};
    var dayOpts = RUN_DAYS.map(function (d) { return '<option value="' + d + '"' + (d === w.run_day ? " selected" : "") + ">" + cap(d) + "</option>"; }).join("");
    var hourOpts = "";
    for (var h = 0; h < 24; h++) hourOpts += '<option value="' + h + '"' + (h === Number(w.run_hour) ? " selected" : "") + ">" + hourLabel(h) + "</option>";
    var prev = $("ad-run-week");      // a save redraws this card: keep the pick
    var wk = weekChoices(), pick = prev && (prev.value === "this" || prev.value === "next") ? prev.value : defaultRunWeek();
    var weekOpts = [["this", "This week"], ["next", "Next week"]].map(function (x) {
      return '<option value="' + x[0] + '"' + (x[0] === pick ? " selected" : "") + ">" + x[1] + " (" + esc(BD.fmtBizDate(wk[x[0]], "short")) + ")</option>";
    }).join("");
    $("ad-friday").innerHTML =
      '<form class="ad-form" id="ad-weekly-form" novalidate>' +
      '<label class="ad-switch ad-switch-lead"><button type="button" class="switch" role="switch" id="ad-weekly-on" aria-checked="' + (w.enabled ? "true" : "false") + '" aria-labelledby="ad-weekly-on-l"></button>' +
      '<span id="ad-weekly-on-l">Make the weekly list on its own</span></label>' +
      '<div class="ad-grid">' +
      '<div class="field"><label for="ad-run-day">Day</label><select class="select" id="ad-run-day" name="run_day">' + dayOpts + "</select></div>" +
      '<div class="field"><label for="ad-run-hour">Time (Central)</label><select class="select" id="ad-run-hour" name="run_hour">' + hourOpts + "</select></div>" +
      '<div class="field"><label for="ad-new-count">New people (of 10)</label><input class="input" id="ad-new-count" name="new_count" type="number" min="0" max="10" step="1" inputmode="numeric" value="' + esc(w.new_count) + '" aria-describedby="ad-fu-count" /></div>' +
      '<div class="field"><span class="label">Follow-ups</span><output class="ad-output" id="ad-fu-count" for="ad-new-count" aria-live="polite"></output></div>' +
      "</div>" +
      '<p class="field-hint" id="ad-weekly-hint">' + esc(fridayHint(w)) + "</p>" +
      '<div class="wrap-row"><button type="submit" class="btn btn-primary">Save</button></div></form>' +
      '<hr class="divider ad-divider" />' +
      '<div class="ad-form" id="ad-run-card">' +
      '<div><h3 class="ad-sub-title">Make a weekly list now</h3>' +
      '<p class="ad-sub-text" id="ad-run-text"></p></div>' +
      '<div class="ad-grid">' +
      '<div class="field ad-run-owner"><label for="ad-run-owner">Make it for</label><select class="select" id="ad-run-owner"></select></div>' +
      '<div class="field"><label for="ad-run-week">Week</label><select class="select" id="ad-run-week">' + weekOpts + "</select></div></div>" +
      '<div class="wrap-row"><button type="button" class="btn ad-run-btn" id="ad-run-btn">' + ico("play", 18) + "Make the list now</button></div></div>";
    updateFollowups();
    renderRunOwner();
  }

  function runWeekStart() {
    var sel = $("ad-run-week");
    return weekChoices()[sel && sel.value === "next" ? "next" : "this"];
  }

  function weekOwnerName(id) {
    var u = userById(id);
    return u ? u.name : "that person";
  }

  function updateRunText() {
    var t = $("ad-run-text");
    if (!t) return;
    var sel = $("ad-run-owner");
    var owner = sel && Number(sel.value) ? weekOwnerName(Number(sel.value)) : "the salesperson";
    t.textContent = owner + ", week of " + BD.fmtBizDate(runWeekStart(), "short") + ".";
  }

  function renderRunOwner() {
    var sel = $("ad-run-owner");
    if (!sel) return;
    var keep = sel.value;
    var sales = S.users.filter(function (u) { return u.role === "salesperson" && u.active; });
    sel.innerHTML = sales.length
      ? sales.map(function (u) { return '<option value="' + esc(u.id) + '"' + (String(u.id) === keep ? " selected" : "") + ">" + esc(u.name) + "</option>"; }).join("")
      : '<option value="">No salesperson yet</option>';
    var btn = $("ad-run-btn");
    if (btn) btn.disabled = !sales.length;
    updateRunText();
  }

  function runWeekly(force) {
    var sel = $("ad-run-owner"), btn = $("ad-run-btn");
    var owner = Number(sel.value);
    if (!owner) return;
    var weekStart = runWeekStart(), when = BD.fmtBizDate(weekStart, "short"), name = weekOwnerName(owner);
    setBusy(btn, true);
    /** setBusy disabled the focused button, so focus fell to the page; put it back. */
    function done() {
      setBusy(btn, false);
      var a = document.activeElement;
      if (!a || a === document.body || a === btn) focusId("ad-run-btn");
    }
    return Api.post("/api/bd/admin/weekly/run", { owner: owner, week_start: weekStart, force: !!force }).then(function (res) {
      done();
      BD.toast("Made " + BD.plural(res.tasks_created, "task") + " for " + name + ", week of " + when + ".", { kind: "ok" });
    }, function (e) {
      done();
      if (e && e.status === 409 && !force) {
        BD.dialog({
          title: "Make the list again?",
          text: name + " already has a list for the week of " + when + ". Make it again? Anything not done on the old list is set aside, and those people are scored again.",
          yes: "Yes, make it again",
        }).then(function (yes) { if (yes) runWeekly(true); });
        return;
      }
      BD.toast(errText(e), { kind: "error" });
    });
  }

  function readFriday(form) {
    var raw = form.elements.new_count.value;
    return {
      enabled: $("ad-weekly-on").getAttribute("aria-checked") === "true",
      run_day: form.elements.run_day.value,
      run_hour: Number(form.elements.run_hour.value),
      new_count: raw === "" ? NaN : Number(raw),
    };
  }

  function updateFollowups() {
    var form = $("ad-weekly-form"), out = $("ad-fu-count");
    if (!form || !out) return;
    var fu = followups(readFriday(form).new_count);
    out.textContent = fu === null ? "New people must be 0 to 10." : fu + " (always 10 in all)";
  }

  function updateFridayHint() {
    var form = $("ad-weekly-form"), hint = $("ad-weekly-hint");
    if (form && hint) hint.textContent = fridayHint(readFriday(form));
  }

  function wireFriday() {
    var box = $("ad-friday");
    box.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest("#ad-run-btn")) { runWeekly(false); return; }
      var sw = e.target.closest && e.target.closest("#ad-weekly-on");
      if (sw) { sw.setAttribute("aria-checked", sw.getAttribute("aria-checked") === "true" ? "false" : "true"); updateFridayHint(); }
    });
    box.addEventListener("change", function (e) {
      if (e.target.id === "ad-run-owner" || e.target.id === "ad-run-week") { updateRunText(); return; }
      updateFridayHint();
    });
    box.addEventListener("input", function (e) { if (e.target.id === "ad-new-count") updateFollowups(); });
    box.addEventListener("submit", function (e) {
      var form = e.target.closest && e.target.closest("#ad-weekly-form");
      if (!form) return;
      e.preventDefault();
      var w = readFriday(form);
      var fields = {};
      if (followups(w.new_count) === null) fields.new_count = "Use a whole number from 0 to 10.";
      showFieldErrors(form, fields);
      if (Object.keys(fields).length) { form.elements.new_count.focus(); return; }
      w.followup_count = followups(w.new_count);
      var btn = form.querySelector('button[type="submit"]');
      setBusy(btn, true);
      Api.put("/api/bd/admin/settings", { weekly: w }).then(function (res) {
        S.settings = res.settings;
        renderFriday();
        BD.toast("Friday list settings saved.", { kind: "ok" });
        var again = document.querySelector('#ad-weekly-form button[type="submit"]');
        if (again) again.focus();
      }, function (err) {
        setBusy(btn, false);
        var f = (err && err.fields) || {};
        showFieldErrors(form, f.weekly ? { new_count: f.weekly } : f);
        BD.toast(err && err.message ? err.message : "That did not save.", { kind: "error" });
      });
    });
  }

  // ── the yearly goals (editable) and the counting rule (fixed) ────────────────────────────
  function touchWords(s) {
    var kinds = s.touch_kinds && s.touch_kinds.length ? s.touch_kinds : ["call (answered or meeting set)", "meeting", "hosted"];
    return kinds.map(function (k) {
      if (k.indexOf("call") === 0) return "A live phone call";
      if (k === "meeting") return "A meeting";
      if (k === "hosted") return "A hosted event";
      return cap(k);
    });
  }

  function chips(words, kind) {
    return '<span class="wrap-row ad-pills">' + words.map(function (x) { return pill(kind, x); }).join("") + "</span>";
  }

  function renderRules() {
    var s = S.settings, f = s.default_frequency || {};
    var num = function (id, name, label, val, lo, hi, hint) {
      return '<div class="field"><label for="' + id + '">' + label + '</label><input class="input" id="' + id + '" name="' + name +
        '" type="number" min="' + lo + '" max="' + hi + '" step="1" inputmode="numeric" value="' + esc(val) + '"' +
        (hint ? ' aria-describedby="' + id + '-hint"' : "") + " />" +
        (hint ? '<p class="field-hint" id="' + id + '-hint">' + hint + "</p>" : "") + "</div>";
    };
    $("ad-rules").innerHTML =
      '<form class="ad-form" id="ad-goals-form" novalidate>' +
      '<h3 class="ad-sub-title">Goals</h3>' +
      '<div class="ad-grid">' +
      '<div class="field"><span class="label" id="ad-freq-bd-l">BD follow-up cadence</span>' +
      '<div class="ad-seg" id="ad-freq-bd" role="radiogroup" aria-label="BD follow-up cadence" aria-describedby="ad-freq-bd-hint">' +
      [["weekly", "Weekly"], ["monthly", "Monthly"], ["quarterly", "Quarterly"]].map(function (o) {
        return '<label class="ad-seg-opt"><input type="radio" name="bd_cadence" value="' + o[0] + '"' +
          (s.bd_cadence === o[0] ? " checked" : "") + " /><span>" + o[1] + "</span></label>";
      }).join("") + "</div>" +
      '<p class="field-hint" id="ad-freq-bd-hint">Every BD contact follows this unless you give one an override.</p></div>' +
      num("ad-freq-mt", "maintenance", "Live talks a year, maintenance", f.maintenance, 1, 52,
        "A maintenance follow-up comes due " + esc(s.maintenance_touch_days || 120) + " days after the last call, meeting, email or text, and stays on the list until one is logged.") +
      num("ad-meet-goal", "weekly_meeting_goal", "Meetings a week", s.weekly_meeting_goal, 0, 50) +
      num("ad-meet-min", "non_dsbc_website_min", "Of those, not from DSBC or website", s.non_dsbc_website_min, 0, 50) +
      "</div>" +
      '<div class="wrap-row"><button type="submit" class="btn btn-primary">Save goals</button></div></form>' +
      '<hr class="divider ad-divider" />' +
      '<div class="ad-form">' +
      '<div><h3 class="ad-sub-title">What counts as a live talk</h3>' +
      '<p class="ad-sub-text ad-lock">' + ico("lock", 16) + "<span>Fixed for everyone</span></p></div>" +
      '<dl class="ad-kv">' +
      "<div><dt>Counts as a live talk</dt><dd>" + chips(touchWords(s), "ok") + "</dd></div>" +
      "<div><dt>Does not count as a live talk</dt><dd>" + chips(["Emails", "Texts", "Notes", "Voicemails", "Calls nobody answered"], "neutral") + "</dd></div>" +
      "<div><dt>Maintenance follow-ups</dt><dd>Come due " + esc(s.maintenance_touch_days) + " days after the last logged follow-up: a call, voicemail, meeting, event, email or text. A note does not count.</dd></div></dl></div>";
  }

  function wireRules() {
    $("ad-rules").addEventListener("submit", function (e) {
      var form = e.target.closest && e.target.closest("#ad-goals-form");
      if (!form) return;
      e.preventDefault();
      var v = function (k) { var x = form.elements[k].value; return x === "" ? NaN : Number(x); };
      var ok = function (n, lo, hi) { return Number.isInteger(n) && n >= lo && n <= hi; };
      var body = { bd_cadence: form.elements.bd_cadence.value, default_frequency: { maintenance: v("maintenance") },
        weekly_meeting_goal: v("weekly_meeting_goal"), non_dsbc_website_min: v("non_dsbc_website_min") };
      var fields = {};
      if (!ok(body.default_frequency.maintenance, 1, 52)) fields.maintenance = "Use a whole number from 1 to 52.";
      if (!ok(body.weekly_meeting_goal, 0, 50)) fields.weekly_meeting_goal = "Use a whole number from 0 to 50.";
      else if (!ok(body.non_dsbc_website_min, 0, body.weekly_meeting_goal)) fields.non_dsbc_website_min = "Use a whole number from 0 up to the meeting goal.";
      showFieldErrors(form, fields);
      var bad = form.querySelector(".has-error input");
      if (bad) { bad.focus(); return; }
      var btn = form.querySelector('button[type="submit"]');
      setBusy(btn, true);
      Api.put("/api/bd/admin/settings", body).then(function (res) {
        S.settings = res.settings;
        renderRules();
        BD.toast("Goals saved.", { kind: "ok" });
        var on = document.querySelector("#ad-freq-bd input:checked");
        if (on) on.focus();
      }, function (err) {
        setBusy(btn, false);
        var f = (err && err.fields) || {};
        if (f.default_frequency) f.maintenance = f.default_frequency;
        showFieldErrors(form, f);
        BD.toast(err && err.message ? err.message : "That did not save.", { kind: "error" });
      });
    });
  }

  // ── pick lists ───────────────────────────────────────────────────────────────────────────
  // `filter` is the GET /api/bd/contacts query key that counts who uses a value.
  var LISTS = [
    { key: "lead_sources", title: "Lead sources", add: "Add a lead source", filter: "lead_source" },
    { key: "industries", title: "Industries", add: "Add an industry", filter: "industry" },
  ];

  function locked(key, word) {
    return key === "lead_sources" && (S.settings.system_lead_sources || []).indexOf(word) !== -1;
  }

  function listCard(L) {
    var words = S.draft[L.key], dirty = !sameList(words, S.settings[L.key]);
    return '<form class="ad-form ad-list" data-key="' + L.key + '" novalidate>' +
      '<div class="ad-list-head"><h3 class="ad-sub-title" id="ad-t-' + L.key + '">' + esc(L.title) + "</h3>" +
      '<span class="count" aria-label="' + words.length + ' items">' + words.length + "</span></div>" +
      '<ul class="ad-chips" aria-labelledby="ad-t-' + L.key + '">' + words.map(function (x, i) {
        if (locked(L.key, x)) {
          return '<li class="ad-chip is-locked">' + esc(x) + ' <span class="ad-chip-lock" aria-hidden="true">' + ico("lock", 14) + '</span><span class="sr-only">(always kept)</span></li>';
        }
        return '<li class="ad-chip">' + esc(x) +
          '<button type="button" class="ad-chip-x" id="ad-x-' + L.key + "-" + i + '" data-remove="' + i + '" aria-label="Remove ' + esc(x) + '">' + ico("x", 14) + "</button></li>";
      }).join("") + "</ul>" +
      '<div class="field"><label for="ad-add-' + L.key + '">' + esc(L.add) + "</label>" +
      '<div class="ad-add-row"><input class="input ad-add-input" id="ad-add-' + L.key + '" name="word" type="text" autocomplete="off" maxlength="120" />' +
      '<button type="submit" class="btn" data-add>' + ico("plus", 18) + "Add</button></div></div>" +
      '<div class="wrap-row ad-list-foot"><button type="button" class="btn btn-primary" data-save' + (dirty ? "" : " disabled") + ">Save " + esc(L.title.toLowerCase()) + "</button>" +
      '<button type="button" class="btn btn-tertiary" data-revert' + (dirty ? "" : " disabled") + ">Undo changes</button></div></form>";
  }

  /** Redraws both lists. `keep`: an element id to focus, else the add box of `focusKey`. */
  function renderLists(focusKey, keep) {
    $("ad-lists").innerHTML = '<div class="ad-lists">' + LISTS.map(listCard).join("") + "</div>";
    if (keep && focusId(keep)) return;
    if (focusKey) focusId("ad-add-" + focusKey);
  }

  /** Removes one value from the draft; the next chip's x (or the add box) gets focus. */
  function dropWord(key, i) {
    S.draft[key].splice(i, 1);
    var next = null;
    for (var j = i; j < S.draft[key].length; j++) { if (!locked(key, S.draft[key][j])) { next = "ad-x-" + key + "-" + j; break; } }
    renderLists(key, next);
  }

  /** How many contacts use a value; null when the count could not be had. */
  function usedBy(L, word) {
    return Api.get("/api/bd/contacts?" + L.filter + "=" + encodeURIComponent(word) + "&limit=1")
      .then(function (res) { return Number(res.total) || 0; }, function () { return null; });
  }

  function wireLists() {
    var box = $("ad-lists");
    box.addEventListener("submit", function (e) {
      var form = e.target.closest && e.target.closest(".ad-list");
      if (!form) return;
      e.preventDefault();
      var key = form.getAttribute("data-key");
      var word = String(form.elements.word.value || "").replace(/\s+/g, " ").trim();
      if (!word) return;
      var dupe = S.draft[key].some(function (x) { return x.toLowerCase() === word.toLowerCase(); });
      if (dupe) { showFieldErrors(form, { word: "That one is already in the list." }); return; }
      S.draft[key].push(word);
      renderLists(key);
    });
    box.addEventListener("click", function (e) {
      var form = e.target.closest && e.target.closest(".ad-list");
      if (!form) return;
      var key = form.getAttribute("data-key");
      var L = LISTS.filter(function (x) { return x.key === key; })[0];
      var rm = e.target.closest("[data-remove]");
      if (rm) {
        var i = Number(rm.getAttribute("data-remove")), word = S.draft[key][i];
        if (locked(key, word)) return;
        setBusy(rm, true);
        usedBy(L, word).then(function (n) {
          setBusy(rm, false);
          if (!n) { dropWord(key, i); return; }
          BD.dialog({
            title: "Remove " + word + "?",
            text: BD.plural(n, "contact uses", "contacts use") + " " + word + ". They keep it, but it is no longer offered as a choice. Nothing changes until you save.",
            yes: "Remove",
          }).then(function (yes) { if (yes) dropWord(key, i); });
        });
        return;
      }
      if (e.target.closest("[data-revert]")) { S.draft[key] = S.settings[key].slice(); renderLists(key); return; }
      var save = e.target.closest("[data-save]");
      if (!save) return;
      if (!S.draft[key].length) { showFieldErrors(form, { word: "Keep at least one." }); return; }
      setBusy(save, true);
      var body = {};
      body[key] = S.draft[key].slice();
      Api.put("/api/bd/admin/settings", body).then(function (res) {
        S.settings = res.settings;
        S.draft[key] = (S.settings[key] || []).slice();
        renderLists(key);
        BD.toast(L.title + " saved.", { kind: "ok" });
      }, function (err) {
        setBusy(save, false);
        var f = (err && err.fields) || {};
        if (f[key]) showFieldErrors(form, { word: f[key] });
        BD.toast(err && err.message ? err.message : "That did not save.", { kind: "error" });
      });
    });
  }

  // ── the phone system and the unmatched calls ─────────────────────────────────────────────
  function unmatchedRow(u) {
    var w = BD.callWords(u);
    var num = esc(w.phone);
    return '<li class="list-row ad-call" data-id="' + esc(u.id) + '">' +
      '<span class="ad-call-ico" aria-hidden="true">' + ico(u.direction === "in" ? "phone-incoming" : "phone", 18) + "</span>" +
      '<div class="ad-call-main"><div class="who"><span class="who-name">' + num + "</span>" +
      '<span class="who-sub">' + esc(w.way) + " · " + esc(w.length) + " · " +
      esc(w.when) + "</span>" +
      (u.summary ? '<span class="who-sub ad-call-sum">' + esc(u.summary) + "</span>" : "") + "</div>" +
      '<div class="wrap-row ad-call-acts">' +
      '<button type="button" class="btn" id="ad-attach-' + esc(u.id) + '" data-attach>' + ico("link", 18) + 'Attach to a contact<span class="sr-only"> (' + num + ")</span></button>" +
      '<button type="button" class="btn btn-tertiary" data-dismiss aria-label="Dismiss the call from ' + num + '">Dismiss</button></div></div></li>';
  }

  function statusHtml() {
    var t = S.telephony || {};
    var named = t.provider && t.provider !== "null" ? cap(t.provider) : "";
    var status = t.connected ? pill("ok", "Connected", "check-circle") : pill("neutral", "Not connected");
    var line;
    if (t.connected) {
      line = "Connected to " + (named || "the phone system") + "." +
        (t.last_event_at ? " Last call came in " + BD.fmtBizDateTime(t.last_event_at) + "." : " Nothing has come in yet.");
    } else {
      line = (t.message || "No phone system connected yet.") + (named ? " Provider: " + named + "." : "");
    }
    $("ad-phone-status").innerHTML = status;
    return '<p class="ad-sub-text" id="ad-phone-line">' + esc(line) + "</p>";
  }

  /** Redraws the section; `keep` is an element id to focus afterwards. */
  function renderPhone(keep) {
    var n = S.unmatched.length;
    var count = '<span class="count' + (n ? " count-warn" : "") + '" aria-label="' + n + ' open calls">' + n + "</span>";
    if (!full()) $("ad-phone-status").innerHTML = count;
    $("ad-phone").innerHTML = (full() ? statusHtml() + '<hr class="divider ad-divider" />' +
      '<div class="ad-list-head"><h3 class="ad-sub-title">Unknown calls</h3>' + count + "</div>" : "") +
      '<p class="ad-sub-text">A call or text from a number we do not know lands here. Attach it to the right contact so it counts, or dismiss it.</p>' +
      (n
        ? '<ul class="list ad-calls" id="ad-unmatched">' + S.unmatched.map(unmatchedRow).join("") + "</ul>"
        : '<div class="empty"><div class="empty-ico">' + ico("check", 22) + '</div><p class="empty-title">No unknown calls.</p></div>');
    if (keep) focusId(keep);
  }

  /** After a call leaves the list: focus the next call's Attach button, or the section heading. */
  function dropCall(id) {
    var idx = -1;
    S.unmatched.forEach(function (u, i) { if (u.id === id) idx = i; });
    S.unmatched = S.unmatched.filter(function (u) { return u.id !== id; });
    var next = S.unmatched[Math.min(Math.max(idx, 0), S.unmatched.length - 1)];
    renderPhone(next ? "ad-attach-" + next.id : "ad-h-phone");
  }

  function callOf(btn) {
    var id = Number(btn.closest(".list-row").getAttribute("data-id"));
    return S.unmatched.filter(function (x) { return x.id === id; })[0] || null;
  }

  function dismissCall(b) {
    var u = callOf(b);
    if (!u) return;
    BD.dismissCall(u, b).then(function (done) {
      if (!done) return;
      dropCall(u.id);
      BD.toast("Call dismissed.", { kind: "ok" });
    }, function (err) {
      BD.toast(errText(err), { kind: "error" });
    });
  }

  // ── attach a call to a contact ───────────────────────────────────────────────────────────
  var att = { call: null, picked: null, results: [], seq: 0 };

  function attEl(name) {
    return $({ q: "ad-attach-q", results: "ad-attach-results", status: "ad-attach-status", outcome: "ad-attach-outcome",
      save: "ad-attach-save", saveLabel: "ad-attach-save-label", saveHint: "ad-attach-save-hint", yes: "ad-attach-yes" }[name]);
  }

  function openAttach(b) {
    var u = callOf(b);
    if (!u) return;
    att.call = u; att.picked = null; att.results = []; att.seq += 1;
    var box = $("ad-attach");
    showFieldErrors(box, {});
    var w = BD.callWords(u);
    $("ad-attach-call").textContent = w.phone + " · " + w.way + " on " + w.when + " · " + w.length +
      (u.summary ? ". " + u.summary : "");
    attEl("q").value = "";
    // The same rule the server uses when nobody says: a minute or more is a talk.
    attEl("outcome").value = (Number(u.duration_s) || 0) >= 60 ? "answered" : "no_answer";
    attEl("save").checked = false;
    attEl("saveLabel").textContent = "Save " + w.phone + " on the contact";
    attEl("saveHint").textContent = "";
    setBusy(attEl("yes"), false);
    renderResults("Type a name, company or phone number to find the contact.");
    BD.sheet.open(box, { initialFocus: "#ad-attach-q" });
  }

  function resultRow(c) {
    var bits = [c.company && c.company.name, c.title, BD.fmtPhone(c.phone)].filter(Boolean).join(" · ");
    return '<label class="check ad-result"><input type="radio" name="contact_id" value="' + esc(c.id) + '"' +
      (att.picked && att.picked.id === c.id ? " checked" : "") + ' /> <span class="who"><span class="who-name">' + esc(c.name) + "</span>" +
      (bits ? '<span class="who-sub">' + esc(bits) + "</span>" : "") + "</span></label>";
  }

  function renderResults(note) {
    attEl("results").innerHTML = note
      ? '<p class="field-hint">' + esc(note) + "</p>"
      : att.results.map(resultRow).join("");
    attEl("status").textContent = note || (BD.plural(att.results.length, "contact") + " found.");
  }

  /** The pick only holds while the results still show it; otherwise nobody is picked. */
  function keepPick() {
    var c = att.picked;
    if (c && !att.results.some(function (r) { return r.id === c.id; })) pickContact(null);
  }

  var searchContacts = BD.debounce(function () {
    var q = attEl("q").value.trim();
    var seq = ++att.seq;
    if (q.length < 2) { att.results = []; keepPick(); renderResults("Type a name, company or phone number to find the contact."); return; }
    Api.get("/api/bd/contacts?q=" + encodeURIComponent(q) + "&limit=8").then(function (res) {
      if (seq !== att.seq) return;                   // a newer search is on its way
      att.results = res.items || [];
      keepPick();
      renderResults(att.results.length ? "" : "No contact matches “" + q + "”.");
    }, function (e) {
      if (seq !== att.seq) return;
      att.results = [];
      keepPick();
      renderResults(errText(e));
    });
  }, 250);

  /** Picks a contact (or nobody). The number is saved by default only for a contact without one;
   *  replacing an existing number is always the person's own tick. */
  function pickContact(c) {
    att.picked = c || null;
    attEl("save").checked = !!(c && !c.phone);
    updateSaveHint();
  }

  function updateSaveHint() {
    var c = att.picked;
    attEl("saveHint").textContent = !c || !c.phone ? ""
      : attEl("save").checked ? "This replaces " + c.name + "'s number, " + BD.fmtPhone(c.phone) + "."
      : c.name + " already has " + BD.fmtPhone(c.phone) + ". Tick this to replace it.";
  }

  function wireAttach() {
    var box = $("ad-attach");
    Array.prototype.forEach.call(box.querySelectorAll(".btn-icon[data-close]"), function (b) { b.innerHTML = ico("x", 20); });
    box.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest("[data-close]")) BD.sheet.close(box, "close");
    });
    attEl("q").addEventListener("input", function () { showFieldErrors(box, {}); searchContacts(); });
    attEl("q").addEventListener("keydown", function (e) { if (e.key === "Enter") e.preventDefault(); });
    attEl("save").addEventListener("change", updateSaveHint);
    attEl("results").addEventListener("change", function (e) {
      var r = e.target.closest && e.target.closest('input[name="contact_id"]');
      if (!r) return;
      pickContact(att.results.filter(function (c) { return String(c.id) === r.value; })[0] || null);
      showFieldErrors(box, {});
    });
    box.addEventListener("submit", function (e) {
      e.preventDefault();
      var u = att.call;
      if (!u) return;
      if (!att.picked) {
        showFieldErrors(box, { q: "Pick the contact this call was with." });
        var first = attEl("results").querySelector('input[name="contact_id"]');
        (first || attEl("q")).focus();
        return;
      }
      var c = att.picked, yes = attEl("yes");
      setBusy(yes, true);
      Api.post(Api.path("admin", "unmatched-calls", u.id, "attach"),
        { contact_id: c.id, save_number: attEl("save").checked, outcome: attEl("outcome").value }).then(function (res) {
        setBusy(yes, false);
        BD.sheet.close(box, "done");
        dropCall(u.id);
        var i = res.interaction || {};
        var href = BD.pageHref("/bd/contact.html?id=", c.id);
        BD.toast("Call attached to " + c.name + (i.counts_as_touch ? ". It counts as a live talk." : ". It does not count as a live talk."), {
          kind: "ok", ms: 8000,
          action: href ? { label: "Open contact", onClick: function () { window.location.href = href; } } : null,
        });
      }, function (err) {
        setBusy(yes, false);
        BD.toast(errText(err), { kind: "error" });
      });
    });
  }

  function wirePhone() {
    $("ad-phone").addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("[data-attach]");
      if (a) { openAttach(a); return; }
      var d = e.target.closest && e.target.closest("[data-dismiss]");
      if (d) dismissCall(d);
    });
    wireAttach();
  }

  function loadPhone() {
    var calls = Api.get("/api/bd/admin/unmatched-calls");
    var status = full() ? Api.get("/api/bd/admin/telephony") : Promise.resolve({ telephony: null });
    return Promise.all([status, calls]).then(function (r) {
      S.telephony = r[0].telephony;
      S.unmatched = r[1].items || [];
      renderPhone();
    }).catch(function (e) { sectionError($("ad-phone"), e, loadPhone); });
  }

  // ── imports: the workbook import and past imports ────────────────────────────────────────
  function problemsList(errs) {
    return errs.map(function (x) {
      return "<li>" + esc(x.sheet) + ", row " + esc(x.row) + ": " + esc(x.message) + "</li>";
    }).join("");
  }
  function importProblems(i, none) {
    var errs = i.errors || [];
    return errs.length
      ? '<details class="ad-problems"><summary>' + esc(BD.plural(errs.length, "problem")) + "</summary>" +
        '<ul class="ad-errors">' + problemsList(errs) + "</ul></details>"
      : '<span class="muted">' + esc(none || "None") + "</span>";
  }
  function importChip(i) { return i.dry_run ? " " + pill("info", "Practice run") : ""; }
  function importWhen(i) { return BD.fmtBizDateTime(i.started_at) + (i.by ? " · " + BD.nameOf(i.by) : ""); }

  function importRow(i) {
    return '<tr><td><div class="who"><span class="who-name">' + esc(i.file_name) + importChip(i) + "</span>" +
      '<span class="who-sub">' + esc(importWhen(i)) + "</span></div></td>" +
      '<td class="num">' + esc(i.rows_read) + '</td><td class="num">' + esc(i.created) + '</td><td class="num">' + esc(i.updated) +
      '</td><td class="num">' + esc(i.skipped) + '</td><td class="num">' + esc(i.possible_duplicates) + "</td><td>" + importProblems(i) + "</td></tr>";
  }

  /** The phone layout: one stacked row per run, every number in words (no hidden columns). */
  function importCard(i) {
    var counts = [BD.plural(i.rows_read, "row") + " read", i.created + " added", i.updated + " updated", i.skipped + " skipped",
      BD.plural(i.possible_duplicates, "maybe duplicate", "maybe duplicates")].join(" · ");
    return '<li class="list-row ad-import"><span class="ad-call-ico" aria-hidden="true">' + ico("upload", 18) + "</span>" +
      '<div class="who"><span class="who-name">' + esc(i.file_name) + importChip(i) + "</span>" +
      '<span class="who-sub">' + esc(importWhen(i)) + "</span>" +
      '<span class="who-sub">' + esc(counts) + "</span>" +
      '<span class="who-sub">' + importProblems(i, "No problems") + "</span></div></li>";
  }

  function renderImports() {
    var box = $("ad-imports");
    if (!S.imports.length) {
      box.innerHTML = '<div class="empty"><div class="empty-ico">' + ico("upload", 22) +
        '</div><div class="empty-title">No imports yet</div><p class="empty-text">When the workbook or a CSV is imported, each run shows up here.</p></div>';
      return;
    }
    box.innerHTML = '<div class="table-wrap ad-table-wrap ad-imports-table"><table class="table"><caption class="sr-only">Import history, newest first</caption><thead><tr>' +
      '<th scope="col">File</th><th scope="col" class="num">Rows read</th><th scope="col" class="num">Created</th><th scope="col" class="num">Updated</th>' +
      '<th scope="col" class="num">Skipped</th><th scope="col" class="num">Maybe duplicates</th><th scope="col">Problems</th></tr></thead><tbody>' +
      S.imports.map(importRow).join("") + "</tbody></table></div>" +
      '<ul class="list ad-imports ad-imports-cards" aria-label="Import history, newest first">' + S.imports.map(importCard).join("") + "</ul>";
  }

  function loadImports() {
    return Api.get("/api/bd/admin/imports").then(function (res) { S.imports = res.items || []; renderImports(); })
      .catch(function (e) { sectionError($("ad-imports"), e, loadImports); });
  }

  function wireImports() {
    var btn = $("ad-import"), input = $("ad-import-file");
    btn.insertAdjacentHTML("afterbegin", ico("upload", 18));
    btn.addEventListener("click", function () { input.click(); });
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      input.value = "";
      // The practice run is a past import too, so the list is read again after each run.
      if (file) BD.importWorkbook(file, { returnFocus: function () { return $("ad-import"); }, onRun: loadImports });
    });
  }

  // ── settings (Friday, goals, pick lists) ─────────────────────────────────────────────────
  function loadSettings() {
    return Api.get("/api/bd/settings").then(function (res) {
      S.settings = res.settings;
      S.draft.lead_sources = (S.settings.lead_sources || []).slice();
      S.draft.industries = (S.settings.industries || []).slice();
      renderFriday();
      renderRules();
      renderLists();
    }).catch(function (e) {
      sectionError($("ad-friday"), e, loadSettings);
      sectionError($("ad-rules"), e, loadSettings);
      sectionError($("ad-lists"), e, loadSettings);
    });
  }

  // ── the section nav ──────────────────────────────────────────────────────────────────────
  /** The nav lists the sections this person sees; the one in view is marked (aria-current). */
  function wireNav() {
    var nav = $("ad-nav");
    var links = Array.prototype.slice.call(nav.querySelectorAll("a[data-sec]"));
    links.forEach(function (a) {
      var sec = $(a.getAttribute("data-sec"));
      if (!sec || sec.hidden) a.parentNode.removeChild(a);
    });
    links = Array.prototype.slice.call(nav.querySelectorAll("a[data-sec]"));
    // One section needs no nav.
    $("ad-navbar").hidden = links.length < 2;
    function mark(id) {
      links.forEach(function (a) {
        if (a.getAttribute("data-sec") === id) a.setAttribute("aria-current", "true");
        else a.removeAttribute("aria-current");
      });
    }
    mark(links.length ? links[0].getAttribute("data-sec") : "");
    nav.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a[data-sec]");
      if (!a) return;
      var sec = $(a.getAttribute("data-sec"));
      if (!sec) return;
      e.preventDefault();
      mark(a.getAttribute("data-sec"));
      var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      sec.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      try { history.replaceState(null, "", "#" + sec.id); } catch (err) { /* the address just stays */ }
    });
    if (!window.IntersectionObserver) return;
    var seen = {};
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { seen[en.target.id] = en.isIntersecting; });
      var first = links.filter(function (a) { return seen[a.getAttribute("data-sec")]; })[0];
      if (first) mark(first.getAttribute("data-sec"));
    }, { rootMargin: "-80px 0px -55% 0px" });
    links.forEach(function (a) { io.observe($(a.getAttribute("data-sec"))); });
  }

  // ── start ────────────────────────────────────────────────────────────────────────────────
  /** The page in place of the sections: a sentence and no data (a failed /api/bd/me, or a BD role
   *  with no part of Admin). */
  function renderNote(words) {
    var note = $("ad-note");
    if (!note) return;
    note.hidden = false;
    BD.note(note, words, "ad-note");
  }

  function show(id, on) {
    var sec = $(id);
    if (sec) sec.hidden = !on;
  }

  var auth = window.TWAuth;
  if (!auth || !auth.ready || typeof auth.bdMe !== "function" || typeof auth.bdFailure !== "function") return;
  auth.ready.then(function () { return auth.bdMe(); }).then(function (res) {
    var ok = res && res.status >= 200 && res.status < 300 && res.body && res.body.ok;
    if (!ok) { renderNote(auth.bdFailure(res && res.status, res && res.body).message); return null; }
    var me = res.body;
    S.can = me.can || {};
    S.me = me.user || null;
    S.today = me.today || BD.bizToday();
    // BD's page gate is admin_area (#810: import no longer opens it; the salesperson imports on Contacts).
    var calls = S.can.admin_area === true, imports = S.can["import"] === true;
    if (!full() && !calls) { renderNote("Admin isn't part of your BD role."); return null; }
    ["ad-s-users", "ad-s-friday", "ad-s-rules", "ad-s-lists"].forEach(function (id) { show(id, full()); });
    show("ad-s-phone", calls);
    show("ad-s-imports", imports);
    // A link from Contacts (#ad-s-phone: "Attach to a contact"; #ad-s-imports: "Past imports") lands on
    // its section, now that it shows: the browser looked for it while every section was still hidden.
    var at = window.location && window.location.hash ? $(window.location.hash.slice(1)) : null;
    if (at && !at.hidden && at.scrollIntoView) at.scrollIntoView({ block: "start" });
    if (!full()) $("ad-h-phone").textContent = "Unknown calls";
    ["ad-users", "ad-friday", "ad-rules", "ad-lists", "ad-phone", "ad-imports"].forEach(function (id) { wireRetry($(id)); });
    wireNav();
    var jobs = [];
    if (calls) { wirePhone(); jobs.push(loadPhone()); }
    if (imports) { wireImports(); jobs.push(loadImports()); }
    if (!full()) return Promise.all(jobs);
    wireUsers();
    wireFriday();
    wireRules();
    wireLists();
    // Users first: the Friday card's "Make it for" list needs them.
    return loadUsers().then(function () { return Promise.all(jobs.concat([loadSettings()])); });
  }).catch(function (e) {
    renderNote(errText(e));
  });
})();
