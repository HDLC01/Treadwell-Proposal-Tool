/* Add a BD contact, /bd/add.html (optional ?company=<id>) (#808: BD's js/add.js, moved in as it works
 * today, restyled like the proposal tool by the approved BD mock-up).
 *
 * The approved redesign (the apply plan, 2.2 and section 3): one centred column, company first.
 * Picking (or typing) a company that already has people shows a calm notice: "Angela Ruiz already
 * works at Switchgrass Construction. Is Mia someone new?" with two choices, "Yes, someone new"
 * (the default) and "Maybe Angela, check Friday". Adding is NEVER blocked: the save always goes
 * through (201), and the server flags a possible duplicate for the assistant's Friday tidy.
 *
 * The flag is cleared right after the save only when ALL of these hold (the plan's M7): the person
 * chose "Yes, someone new", they may clear a flag (can.clear_duplicate: the assistant, admins), and
 * every match the server found is "Same company name". A same phone or same email always keeps the
 * flag, whatever the choice (the choice only answers the company question). "Maybe ..." keeps it too.
 *
 * Everything else a new contact gets is shown as "Saved as" pills (BD contact, its owner, 4 live
 * talks a year, the company's industry, Needs confirming); "Change" opens those fields.
 *
 * WHAT CHANGED IN THE MOVE:
 *   - BD's own shell (BDAuth) is gone: the page reads who this is from TWAuth.bdMe() (the one
 *     /api/bd/me answer the sidebar's BD group reads), and a failed answer is said in
 *     TWAuth.bdFailure's words. Who may add is can.add_contact (salesperson, assistant, admins); anyone
 *     else is told so, with no form. BD did that with its nav gate's refusal page.
 *   - The owner list starts on the person adding when they are one of the salespeople it lists (the
 *     list of BD logins, GET /api/bd/users), else on the first salesperson. BD read the adder's role
 *     name for that; the page reads no role name of the person using it.
 *   - NO LINKS TO PAGES THAT HAVE NOT MOVED. BD's "Contacts" back link and Cancel went to the
 *     Contacts page, which has not moved: there is no back link, and Cancel goes to /bd/ (This Week,
 *     or an assistant's BD home). "Open" goes to the contact page, a /bd/ page, through BD.safeHref.
 *   - Toasts are BD.toast's; every route is under /api/bd/.
 *
 * Routes (docs/bd/api-contract.md): GET /api/bd/companies?q= (the type-ahead),
 * GET /api/bd/companies/{id}, GET /api/bd/contacts/duplicates (company=, phone=, email=),
 * POST /api/bd/contacts, PATCH /api/bd/contacts/{id}, GET /api/bd/settings, GET /api/bd/users.
 */
(function () {
  "use strict";

  var BD = window.BD, Api = window.BDApi;
  var esc = BD.esc, errText = BD.errText, setBusy = BD.setBusy;

  var DEFAULT_SOURCE = "Other/Misc";
  // a server field name -> this form's field key
  var FIELD_OF = { company: "company", name: "name", title: "title", phone: "phone", email: "email", city: "city",
    lead_source: "source", category: "category", owner_id: "owner", co_owner_id: "coowner",
    frequency_per_year: "freq", industry: "industry", stage: "stage", notes: "notes", account_type: "account" };
  var MORE_FIELDS = ["category", "owner", "coowner", "stage", "freq", "industry", "notes", "account"];

  var S = {
    me: null, today: "", canClear: false,   // canClear: /api/bd/me's can.clear_duplicate
    settings: null, users: [],
    company: null,          // the picked company {id, name, city, industry}, or null
    isNew: false,           // picked "Add X as a new company"
    people: [],             // who already works at that company [{id, name, title}]
    choice: "new",          // the duplicate question: "new" | "same"
    match: { phone: null, email: null },   // a contact the phone / email already belongs to
    results: [], active: -1, open: false,
    seq: { search: 0, people: 0, phone: 0, email: 0 },
    freqTouched: false, cityFromCompany: false, moreOpen: false,
  };

  function $(id) { return document.getElementById(id); }
  function ico(name, size) { return BD.icon(name, size || 18); }
  function val(id) { var el = $(id); return el ? String(el.value || "").trim() : ""; }
  function setting(key) { return BD.setting(S.settings, key); }
  /** The number a maintenance contact starts with. A BD contact has no number to type: it follows
   *  the BD cadence (the server derives its yearly count and refuses one sent with a BD create). */
  function defaultFreq() { return setting("default_frequency").maintenance; }
  /** The global BD cadence word (weekly | monthly | quarterly), quarterly when settings are trimmed. */
  function bdCadence() {
    var w = (S.settings || {}).bd_cadence;
    return w === "weekly" || w === "monthly" || w === "quarterly" ? w : "quarterly";
  }
  /** The live talks a year the BD cadence means (52, 12 or 4); for the "Saved as" pill only. */
  function bdFreq() {
    var f = window.BDCore && window.BDCore.CADENCE_FREQ;
    return (f && f[bdCadence()]) || 4;
  }
  function options(pairs, selected, placeholder) {
    return (placeholder != null ? '<option value="">' + esc(placeholder) + "</option>" : "") + pairs.map(function (p) {
      return '<option value="' + esc(p[0]) + '"' + (String(p[0]) === String(selected) ? " selected" : "") + ">" + esc(p[1]) + "</option>";
    }).join("");
  }
  function same(values) { return values.map(function (v) { return [v, v]; }); }
  function byName(a, b) { return String(a.name).localeCompare(String(b.name)); }

  // ── people pickers ─────────────────────────────────────────────────────────────────────────
  function salespeople() { return BD.withRole(S.users, ["salesperson"]).sort(byName); }
  function coOwners() { return BD.withRole(S.users, ["salesperson", "manager"]).sort(byName); }
  function defaultOwnerId() {
    var sp = salespeople();
    var myId = S.me && S.me.user ? S.me.user.id : null;
    // The person adding, when they are one of the salespeople listed (a salesperson adds their own).
    if (myId != null && sp.some(function (u) { return u.id === myId; })) return String(myId);
    return sp.length ? String(sp[0].id) : "";
  }

  // ── the form ───────────────────────────────────────────────────────────────────────────────
  function field(key, label, input, opt) {
    return '<div class="field" data-field="' + key + '"><label for="add-' + key + '">' + esc(label) +
      (opt ? ' <span class="opt">(optional)</span>' : "") + "</label>" + input +
      '<p class="field-hint" id="add-' + key + '-hint" hidden></p>' +
      '<p class="field-error" id="add-' + key + '-err" hidden></p></div>';
  }
  function text(key, type, extra) {
    return '<input class="input" id="add-' + key + '" name="' + key + '" type="' + type + '" autocomplete="off" ' + (extra || "") + " />";
  }

  function formHtml() {
    var freq = defaultFreq();
    return '<div class="add-wrap">' +
      '<p class="eyebrow">BD CRM</p>' +
      '<h1 class="page-title add-title">Add contact</h1>' +
      '<p class="page-sub add-sub">Pick the company first. Several people at one company share it.</p>' +
      '<form id="add-form" class="add-form" novalidate autocomplete="off">' +
      // the company, first
      '<div class="field add-company" data-field="company"><label for="add-company" id="add-company-label">Company</label>' +
      '<div class="input-wrap add-combo">' +
      '<span class="input-lead">' + ico("building", 18) + "</span>" +
      '<input class="input" id="add-company" name="company" type="text" autocomplete="off" role="combobox" aria-required="true" aria-autocomplete="list" ' +
      'aria-expanded="false" aria-controls="add-company-list" />' +
      '<span class="input-trail" id="add-company-check" hidden>' + ico("check", 20) + "</span>" +
      '<ul class="add-list" id="add-company-list" role="listbox" aria-labelledby="add-company-label" hidden></ul>' +
      "</div>" +
      '<p class="field-hint" id="add-company-hint" hidden></p>' +
      '<p class="field-error" id="add-company-err" hidden></p></div>' +
      '<section class="add-dupe" id="add-dupe" aria-label="Already at this company" hidden></section>' +
      // the person
      '<div class="add-grid">' +
      field("name", "Name", text("name", "text", "required")) +
      field("title", "Title", text("title", "text", 'placeholder="Project Manager"'), true) +
      field("phone", "Phone", text("phone", "tel", 'inputmode="tel"')) +
      field("email", "Email", text("email", "email", 'inputmode="email"')) +
      field("city", "City", text("city", "text")) +
      field("source", "Lead source", '<select class="select" id="add-source" name="source">' +
        options(same(setting("lead_sources")), DEFAULT_SOURCE) + "</select>") +
      "</div>" +
      // what else it is saved as
      '<section class="add-defaults" id="add-defaults" aria-labelledby="add-saved-h">' +
      '<div class="add-defaults-row"><h2 class="add-saved-h" id="add-saved-h">Saved as</h2>' +
      '<ul class="add-pills" id="add-pills"></ul>' +
      '<button type="button" class="btn btn-tertiary add-change" data-act="defaults" aria-expanded="false" aria-controls="add-more">' +
      "<span>Change</span>" + ico("chev-down", 18) + "</button></div>" +
      '<div class="add-more" id="add-more" hidden>' +
      field("category", "Category", '<select class="select" id="add-category" name="category">' +
        options([["bd", "BD contact"], ["maintenance", "Maintenance"]], "bd") + "</select>") +
      field("account", "Account type", '<select class="select" id="add-account" name="account">' +
        options(same(setting("account_types")), "", "Not set") + "</select>") +
      field("owner", "Owner", '<select class="select" id="add-owner" name="owner">' +
        (salespeople().length ? options(salespeople().map(function (u) { return [String(u.id), u.name]; }), defaultOwnerId())
          : '<option value="">Default owner</option>') + "</select>") +
      field("coowner", "Co-owner", '<select class="select" id="add-coowner" name="coowner">' +
        options(coOwners().map(function (u) { return [String(u.id), u.name]; }), "", "None") + "</select>") +
      field("stage", "Stage", '<select class="select" id="add-stage" name="stage">' +
        options(same(setting("stages")), "", "None yet") + "</select>") +
      field("freq", "Live talks a year", text("freq", "number", 'min="1" max="52" step="1" inputmode="numeric" value="' + esc(freq) + '"')) +
      '<div class="field add-cadence" data-field="cadence"><span class="label">Follow-up cadence</span>' +
      '<p class="field-hint add-freq-note" id="add-freq-note">Follows the BD cadence (' + esc(bdCadence()) + ").</p></div>" +
      field("industry", "Industry", '<select class="select" id="add-industry" name="industry">' +
        options(same(setting("industries")), "", "Not sure") + "</select>") +
      '<div class="add-switch-row"><button type="button" class="switch" role="switch" id="add-confirm" aria-checked="true" ' +
      'aria-labelledby="add-confirm-label" aria-describedby="add-confirm-hint"></button>' +
      '<span class="add-switch-text"><span class="add-switch-label" id="add-confirm-label">Needs confirming</span>' +
      '<span class="field-hint" id="add-confirm-hint">Leave it on until someone has checked they still work there.</span></span></div>' +
      '<div class="field add-notes" data-field="notes"><label for="add-notes">Notes <span class="opt">(optional)</span></label>' +
      '<textarea class="textarea" id="add-notes" name="notes" rows="3" placeholder="Anything worth knowing before the first call"></textarea>' +
      '<p class="field-error" id="add-notes-err" hidden></p></div>' +
      "</div></section>" +
      '<div class="wrap-row add-actions">' +
      '<button type="submit" class="btn btn-primary" id="add-submit">' + ico("plus", 18) + "<span>Add contact</span></button>" +
      '<a class="btn btn-tertiary" href="/bd/">Cancel</a></div>' +
      "</form></div>";
  }

  // ── the company combobox ───────────────────────────────────────────────────────────────────

  function exactHit(name) {
    var key = BD.normalizeCompany(name);
    return S.results.filter(function (c) { return BD.normalizeCompany(c.name) === key; })[0] || null;
  }

  function search(q) {
    var n = ++S.seq.search;
    if (!q) { S.results = []; closeList(); return; }
    Api.get("/api/bd/companies?q=" + encodeURIComponent(q) + "&limit=8").then(function (r) {
      if (n !== S.seq.search) return;
      S.results = (r.items || []).slice(0, 8);
      if (document.activeElement === $("add-company")) openList();
    }, function () { if (n === S.seq.search) { S.results = []; closeList(); } });
  }

  function listItems() {
    var q = val("add-company");
    var items = S.results.map(function (c) { return { kind: "co", co: c }; });
    if (q && !exactHit(q)) items.push({ kind: "new", name: q.replace(/\s+/g, " ") });
    return items;
  }

  function openList() {
    var items = listItems();
    var ul = $("add-company-list");
    if (!items.length) { closeList(); return; }
    if (S.active >= items.length) S.active = -1;
    ul.innerHTML = items.map(function (it, i) {
      var on = i === S.active;
      if (it.kind === "new") {
        return '<li class="add-option is-new" role="option" id="add-opt-' + i + '" data-i="' + i + '" aria-selected="' + on + '">' +
          ico("plus", 18) + "<span>Add “" + esc(it.name) + "” as a new company</span></li>";
      }
      var sub = [it.co.city, it.co.contact_count != null ? BD.plural(it.co.contact_count, "person", "people") : ""].filter(Boolean).join(" · ");
      return '<li class="add-option" role="option" id="add-opt-' + i + '" data-i="' + i + '" aria-selected="' + on + '">' +
        ico("building", 18) + '<span class="add-option-text"><span class="add-option-name">' + esc(it.co.name) + "</span>" +
        (sub ? '<span class="add-option-sub">' + esc(sub) + "</span>" : "") + "</span></li>";
    }).join("");
    ul.hidden = false;
    S.open = true;
    var input = $("add-company");
    input.setAttribute("aria-expanded", "true");
    if (S.active >= 0) input.setAttribute("aria-activedescendant", "add-opt-" + S.active);
    else input.removeAttribute("aria-activedescendant");
  }

  function closeList() {
    var ul = $("add-company-list");
    if (!ul) return;
    ul.hidden = true;
    ul.innerHTML = "";
    S.open = false;
    S.active = -1;
    $("add-company").setAttribute("aria-expanded", "false");
    $("add-company").removeAttribute("aria-activedescendant");
  }

  function choose(i) {
    var it = listItems()[i];
    closeList();
    if (!it) return;
    if (it.kind === "new") pickNew(it.name);
    else pickCompany(it.co);
  }

  /** A company from the list: the green check, its city and industry as defaults, its people. */
  function pickCompany(co) {
    S.company = { id: co.id, name: String(co.name).trim(), city: co.city || null, industry: co.industry || null };
    S.isNew = false;
    $("add-company").value = S.company.name;
    $("add-company-check").hidden = false;
    hint("company", "");
    clearError("company");
    companyDefaults();
    loadPeopleById(co.id);
  }

  /** The picked company's city (with "From the company") and industry, where nothing was typed. */
  function companyDefaults() {
    var co = S.company;
    if (!co) return;
    if (co.city && (!val("add-city") || S.cityFromCompany)) {
      $("add-city").value = co.city;
      S.cityFromCompany = true;
      hint("city", "From the company");
    }
    if (co.industry && !val("add-industry")) $("add-industry").value = co.industry;
    renderPills();
  }

  /** "Add X as a new company", or a name typed and left: no check; the server finds or makes it. */
  function pickNew(name) {
    S.company = null;
    S.isNew = true;
    $("add-company").value = name;
    $("add-company-check").hidden = true;
    clearError("company");
    loadPeopleByName(name);
    renderPills();
  }

  function loadPeopleById(id) {
    var n = ++S.seq.people;
    Api.get(Api.path("companies", id)).then(function (r) {
      if (n !== S.seq.people) return;
      if (r.company && S.company) {
        S.company.city = r.company.city || S.company.city;
        S.company.industry = r.company.industry || S.company.industry;
        companyDefaults();
      }
      setPeople((r.contacts || []).map(function (c) { return { id: c.id, name: c.name, title: c.title }; }));
    }, function () { if (n === S.seq.people) setPeople([]); });
  }

  function loadPeopleByName(name) {
    var n = ++S.seq.people;
    if (!name) { setPeople([]); return; }
    Api.get("/api/bd/contacts/duplicates?company=" + encodeURIComponent(name)).then(function (r) {
      if (n !== S.seq.people) return;
      setPeople((r.items || []).filter(function (d) { return d.reason === "Same company name"; })
        .map(function (d) { return { id: d.contact_id, name: d.name, title: null, company: d.company }; }));
    }, function () { if (n === S.seq.people) setPeople([]); });
  }

  function setPeople(list) {
    S.people = list;
    S.choice = "new";
    hint("company", !S.company && S.isNew && !list.length ? "New company" : "");
    renderDupe();
    renderPills();
  }

  function companyName() {
    if (S.company) return S.company.name;
    var p = S.people[0];
    return (p && p.company) || val("add-company");
  }

  // ── the duplicate notice ───────────────────────────────────────────────────────────────────
  function questionHtml() {
    var ps = S.people;
    var who = BD.firstName(val("add-name")) || "this person";
    var names;
    if (ps.length === 1) names = "<strong>" + esc(ps[0].name) + "</strong> already works at ";
    else {
      var shown = ps.slice(0, ps.length > 3 ? 2 : ps.length).map(function (p) { return "<strong>" + esc(p.name) + "</strong>"; });
      var last = ps.length > 3 ? BD.plural(ps.length - 2, "other") : shown.pop();
      names = shown.join(", ") + " and " + last + " already work at ";
    }
    return names + esc(companyName()) + ". Is " + esc(who) + " someone new?";
  }

  function renderDupe() {
    var box = $("add-dupe");
    var ps = S.people;
    if (!ps.length) { box.hidden = true; box.innerHTML = ""; return; }
    var appearing = box.hidden;
    var open = ps.length === 1
      ? '<a class="btn-link add-dupe-open" href="' + esc(BD.pageHref("/bd/contact.html?id=", ps[0].id)) + '" aria-label="Open ' + esc(ps[0].name) + '">Open</a>'
      : "";
    var links = ps.length > 1
      ? '<div class="wrap-row add-dupe-links">' + ps.slice(0, 6).map(function (p) {
        return '<a class="btn-link" href="' + esc(BD.pageHref("/bd/contact.html?id=", p.id)) + '">Open ' + esc(p.name) + "</a>";
      }).join("") + "</div>"
      : "";
    var maybe = ps.length === 1 ? "Maybe " + BD.firstName(ps[0].name) + ", check Friday" : "Maybe one of them, check Friday";
    box.innerHTML = '<div class="add-dupe-head">' + BD.avatarHTML(ps[0].name) +
      '<p class="add-dupe-q" id="add-dupe-q">' + questionHtml() + "</p>" + open + "</div>" + links +
      '<div class="add-radios" role="radiogroup" aria-labelledby="add-dupe-q">' +
      radio("new", "Yes, someone new") + radio("same", maybe) + "</div>";
    box.hidden = false;
    // A person who cannot see the box hears the question once, when it appears.
    if (appearing) BD.announce($("add-dupe-q").textContent);
  }

  function radio(key, label) {
    var on = S.choice === key;
    return '<button type="button" class="radio-tile" role="radio" data-dup="' + key + '" aria-checked="' + on + '" tabindex="' +
      (on ? "0" : "-1") + '">' + esc(label) + "</button>";
  }

  function setChoice(key, focus) {
    S.choice = key;
    Array.prototype.forEach.call(document.querySelectorAll("#add-dupe [data-dup]"), function (b) {
      var on = b.getAttribute("data-dup") === key;
      b.setAttribute("aria-checked", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    renderPills();
  }

  // ── Saved as ───────────────────────────────────────────────────────────────────────────────
  function selectedText(id) {
    var s = $(id);
    if (!s || !s.value) return "";
    var o = s.options[s.selectedIndex];
    return o ? o.textContent : "";
  }
  function flagged() {
    return !!(S.match.phone || S.match.email || (S.people.length && S.choice === "same"));
  }

  function renderPills() {
    var ul = $("add-pills");
    if (!ul) return;
    var out = [];
    function pill(kind, words) { out.push('<li class="pill pill-' + kind + '">' + esc(words) + "</li>"); }
    pill("neutral", val("add-category") === "maintenance" ? "Maintenance" : "BD contact");
    var owner = selectedText("add-owner");
    if (owner) pill("neutral", "Owner " + owner);
    var co = selectedText("add-coowner");
    if (co) pill("neutral", "With " + co);
    var n = val("add-category") === "maintenance" ? parseInt(val("add-freq"), 10) : bdFreq();
    if (n >= 1 && n <= 52) pill("neutral", BD.plural(n, "live talk") + " a year");
    if (val("add-category") === "maintenance" && val("add-account")) pill("neutral", val("add-account"));
    if (val("add-industry")) pill("neutral", val("add-industry"));
    if (val("add-stage")) pill("neutral", val("add-stage"));
    if ($("add-confirm").getAttribute("aria-checked") === "true") pill("warn", "Needs confirming");
    if (flagged()) pill("warn", "Possible duplicate");
    ul.innerHTML = out.join("");
  }

  function toggleMore(btn, open) {
    S.moreOpen = open == null ? !S.moreOpen : open;
    $("add-more").hidden = !S.moreOpen;
    btn.setAttribute("aria-expanded", S.moreOpen ? "true" : "false");
    btn.innerHTML = "<span>" + (S.moreOpen ? "Hide" : "Change") + "</span>" + ico(S.moreOpen ? "chev-up" : "chev-down", 18);
  }

  /** Maintenance shows the account type and the live-talks number; BD shows the one-line cadence note instead. */
  function syncAccount() {
    var maint = val("add-category") === "maintenance";
    var f = document.querySelector('[data-field="account"]');
    if (f) f.hidden = !maint;
    var n = document.querySelector('[data-field="freq"]');
    if (n) n.hidden = !maint;
    var note = document.querySelector('[data-field="cadence"]');
    if (note) note.hidden = maint;
  }

  // ── field checks ───────────────────────────────────────────────────────────────────────────
  /** The input's aria-describedby: its hint, its "This phone belongs to" box and its error, each
   *  only while it shows (none: no attribute). */
  function describe(key) {
    var input = $("add-" + key);
    if (!input) return;
    var ids = ["hint", "match", "err"].map(function (part) { return "add-" + key + "-" + part; }).filter(function (id) {
      var el = $(id);
      return el && !el.hidden && el.textContent;
    });
    if (ids.length) input.setAttribute("aria-describedby", ids.join(" ")); else input.removeAttribute("aria-describedby");
  }
  function hint(key, words) {
    var h = $("add-" + key + "-hint");
    if (!h) return;
    h.textContent = words || "";
    h.hidden = !words;
    describe(key);
  }
  function setError(key, words) {
    var wrap = document.querySelector('[data-field="' + key + '"]');
    var e = $("add-" + key + "-err");
    if (!wrap || !e) return null;
    wrap.classList.add("has-error");
    e.textContent = words;
    e.hidden = false;
    var input = $("add-" + key);
    if (input) input.setAttribute("aria-invalid", "true");
    describe(key);
    return input;
  }
  function clearError(key) {
    var wrap = document.querySelector('[data-field="' + key + '"]');
    var e = $("add-" + key + "-err");
    if (wrap) wrap.classList.remove("has-error");
    if (e) { e.hidden = true; e.textContent = ""; }
    var input = $("add-" + key);
    if (input) input.removeAttribute("aria-invalid");
    describe(key);
  }

  var EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function phoneError() {
    var p = val("add-phone");
    return p && !BD.e164(p) ? "Enter a 10-digit phone number" : "";
  }
  function emailError() {
    var m = val("add-email");
    return m && !EMAIL.test(m) ? "That doesn't look like an email address." : "";
  }

  /** On leaving Phone or Email: the format, then whose it already is ("This phone belongs to ..."). */
  function checkField(key) {
    var err = key === "phone" ? phoneError() : emailError();
    var v = val("add-" + key);
    S.match[key] = null;
    showMatch(key);
    renderPills();
    if (err) { setError(key, err); return; }
    clearError(key);
    if (!v) return;
    var n = ++S.seq[key];
    Api.get("/api/bd/contacts/duplicates?" + key + "=" + encodeURIComponent(v)).then(function (r) {
      if (n !== S.seq[key] || val("add-" + key) !== v) return;
      var want = key === "phone" ? "Same phone" : "Same email";
      var hit = (r.items || []).filter(function (d) { return d.reason === want; })[0] || null;
      S.match[key] = hit ? { id: hit.contact_id, name: hit.name } : null;
      showMatch(key);
      renderPills();
    }, function () { /* the check is a help, not a gate */ });
  }

  function showMatch(key) {
    var wrap = document.querySelector('[data-field="' + key + '"]');
    var box = wrap && wrap.querySelector(".add-match");
    var m = S.match[key];
    if (!m) { if (box) box.parentNode.removeChild(box); describe(key); return; }
    var words = "This " + (key === "phone" ? "phone" : "email") + " belongs to " + m.name + ".";
    var fresh = !box || box.getAttribute("data-said") !== words;
    if (!box) {
      box = document.createElement("p");
      box.className = "add-match";
      box.id = "add-" + key + "-match";
      wrap.appendChild(box);
    }
    box.innerHTML = ico("warning", 16) + "<span>" + esc(words) + "</span>" +
      '<a class="btn-link" href="' + esc(BD.pageHref("/bd/contact.html?id=", m.id)) + '" aria-label="Open ' + esc(m.name) + '">Open</a>';
    box.setAttribute("data-said", words);
    describe(key);
    // Said once when it appears (or names someone else), for a person who cannot see the box.
    if (fresh) BD.announce(words);
  }

  // ── saving ─────────────────────────────────────────────────────────────────────────────────
  function read() {
    var cat = val("add-category") || "bd";
    var name = val("add-company").replace(/ /g, " ").replace(/\s+/g, " ");
    var body = {
      company: S.company ? { id: S.company.id } : { name: name },
      name: val("add-name"),
      title: val("add-title") || null,
      phone: val("add-phone") || null,
      email: val("add-email") || null,
      city: val("add-city") || null,
      industry: val("add-industry") || null,
      lead_source: val("add-source") || DEFAULT_SOURCE,
      category: cat,
      confirmed: $("add-confirm").getAttribute("aria-checked") !== "true",
    };
    // The server refuses a number for a BD contact (it follows the BD cadence); only maintenance sends one.
    if (cat === "maintenance") body.frequency_per_year = parseInt(val("add-freq"), 10);
    if (val("add-owner")) body.owner_id = Number(val("add-owner"));
    if (cat === "maintenance" && val("add-account")) body.account_type = val("add-account");
    if (val("add-notes")) body.notes = val("add-notes");
    return { companyName: name, body: body, stage: val("add-stage"), coOwner: val("add-coowner") ? Number(val("add-coowner")) : null };
  }

  function validate(v) {
    var errs = {};
    var b = v.body;
    if (!v.companyName) errs.company = "Pick or type a company.";
    if (!b.name) errs.name = "Type the person's name.";
    if (phoneError()) errs.phone = phoneError();
    if (emailError()) errs.email = emailError();
    if (b.category === "maintenance" && !(b.frequency_per_year >= 1 && b.frequency_per_year <= 52)) errs.freq = "Use a number from 1 to 52.";
    if (v.coOwner != null && b.owner_id != null && v.coOwner === b.owner_id) errs.coowner = "Pick someone other than the owner.";
    return errs;
  }

  /** Show field errors (keys of this form) and focus the first one, opening "Change" if needed. */
  function showErrors(errs) {
    ["company", "name", "title", "phone", "email", "city", "source"].concat(MORE_FIELDS).forEach(clearError);
    var first = null;
    var order = ["company", "name", "title", "phone", "email", "city", "source"].concat(MORE_FIELDS);
    order.forEach(function (k) {
      if (!errs[k]) return;
      var input = setError(k, errs[k]);
      if (!first) first = { key: k, input: input };
    });
    if (!first) return;
    if (MORE_FIELDS.indexOf(first.key) !== -1 && !S.moreOpen) toggleMore(document.querySelector('[data-act="defaults"]'), true);
    if (first.input) first.input.focus();
  }

  function submit(e) {
    e.preventDefault();
    closeList();
    var v = read();
    var errs = validate(v);
    if (Object.keys(errs).length) { showErrors(errs); return; }
    showErrors({});
    var btn = $("add-submit");
    setBusy(btn, true);
    var choice = S.choice, hadPeople = S.people.length > 0, matched = !!(S.match.phone || S.match.email);
    Api.post("/api/bd/contacts", v.body).then(function (r) {
      var c = r.contact;
      var dups = r.possible_duplicates || [];
      var patch = {};
      if (v.stage) patch.stage = v.stage;
      if (v.coOwner != null) patch.co_owner_id = v.coOwner;
      // Clear the server's flag only for a same-company match the person said is someone new.
      var onlyCompany = dups.length > 0 && dups.every(function (d) { return d.reason === "Same company name"; });
      if (c.duplicate_of && S.canClear && choice === "new" && hadPeople && onlyCompany && !matched) patch.duplicate_of = null;
      if (!Object.keys(patch).length) return c;
      return Api.patch(Api.path("contacts", c.id), patch).then(function (r2) { return r2.contact; }, function (err) {
        BD.toast(c.name + " was added, but the rest didn't save: " + errText(err), { kind: "error" });
        return c;
      });
    }).then(function (c) {
      setBusy(btn, false);
      BD.toast(c.name + " added.", {
        kind: "ok", ms: 8000,
        action: { label: "Open", onClick: function () { var to = BD.pageHref("/bd/contact.html?id=", c.id); if (to) location.href = to; } },
      });
      resetForNext(c);
    }, function (err) {
      setBusy(btn, false);
      if (err && err.fields) {
        var mapped = {};
        Object.keys(err.fields).forEach(function (k) { mapped[FIELD_OF[k] || "name"] = err.fields[k]; });
        showErrors(mapped);
      } else {
        BD.toast(errText(err), { kind: "error" });
      }
    });
  }

  /** After a save: every field back to its default but the company (add another there). */
  function resetForNext(c) {
    ["add-name", "add-title", "add-phone", "add-email", "add-notes"].forEach(function (id) { $(id).value = ""; });
    $("add-source").value = DEFAULT_SOURCE;
    $("add-category").value = "bd";
    $("add-account").value = "";
    $("add-owner").value = defaultOwnerId();
    $("add-coowner").value = "";
    $("add-stage").value = "";
    $("add-freq").value = defaultFreq();
    S.freqTouched = false;
    $("add-industry").value = "";
    $("add-confirm").setAttribute("aria-checked", "true");
    $("add-city").value = "";
    hint("city", "");
    S.cityFromCompany = false;
    S.match = { phone: null, email: null };
    showMatch("phone");
    showMatch("email");
    syncAccount();
    // the company now has one more person: pick it again by its id, so the notice includes them
    if (c && c.company && c.company.id != null) pickCompany({ id: c.company.id, name: c.company.name });
    else renderPills();
    $("add-name").focus();
  }

  // ── events ─────────────────────────────────────────────────────────────────────────────────
  function wire() {
    var input = $("add-company");
    var typed = BD.debounce(function () { search(val("add-company")); }, 200);
    input.addEventListener("input", function () {
      S.company = null;
      S.isNew = false;
      $("add-company-check").hidden = true;
      hint("company", "");
      clearError("company");
      S.seq.people++;
      if (S.people.length) setPeople([]);
      S.active = -1;
      typed();
      if (!val("add-company")) closeList();
    });
    input.addEventListener("keydown", function (e) {
      var n = S.open ? listItems().length : 0;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (!S.open) { openList(); return; }
        S.active = n ? (S.active + 1) % n : -1;
        openList();
      } else if (e.key === "ArrowUp" && S.open) {
        e.preventDefault();
        S.active = n ? (S.active - 1 + n) % n : -1;
        openList();
      } else if (e.key === "Enter" && S.open && S.active >= 0) {
        e.preventDefault();
        choose(S.active);
      } else if (e.key === "Escape" && S.open) {
        e.preventDefault();
        closeList();
      }
    });
    input.addEventListener("blur", function () {
      setTimeout(function () {
        if (document.activeElement === input) return;
        closeList();
        var q = val("add-company");
        if (!q || S.company || S.isNew) return;
        var hit = exactHit(q);
        if (hit) pickCompany(hit); else pickNew(q);
      }, 150);
    });
    var list = $("add-company-list");
    list.addEventListener("mousedown", function (e) { e.preventDefault(); });   // keep focus in the box
    list.addEventListener("click", function (e) {
      var li = e.target.closest && e.target.closest("[data-i]");
      if (li) choose(Number(li.getAttribute("data-i")));
    });

    var form = $("add-form");
    form.addEventListener("submit", submit);
    form.addEventListener("click", function (e) {
      var t = e.target.closest && e.target.closest("[data-dup], [data-act], #add-confirm");
      if (!t) return;
      if (t.id === "add-confirm") {
        t.setAttribute("aria-checked", t.getAttribute("aria-checked") === "true" ? "false" : "true");
        renderPills();
      } else if (t.hasAttribute("data-dup")) {
        setChoice(t.getAttribute("data-dup"), false);
      } else if (t.getAttribute("data-act") === "defaults") {
        toggleMore(t);
      }
    });
    form.addEventListener("keydown", function (e) {
      var r = e.target.closest && e.target.closest("[data-dup]");
      if (!r) return;
      if (["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft"].indexOf(e.key) !== -1) {
        e.preventDefault();
        setChoice(S.choice === "new" ? "same" : "new", true);
      }
    });
    form.addEventListener("input", function (e) {
      var id = e.target.id;
      if (id === "add-name" && S.people.length) {
        var q = $("add-dupe-q");
        if (q) q.innerHTML = questionHtml();
      }
      if (id === "add-name") clearError("name");
      if (id === "add-city") { S.cityFromCompany = false; hint("city", ""); }
      if (id === "add-freq") { S.freqTouched = true; renderPills(); }
      if (id === "add-phone" || id === "add-email") {
        var key = id.slice(4);
        if (S.match[key]) { S.match[key] = null; showMatch(key); renderPills(); }
        if (document.querySelector('[data-field="' + key + '"].has-error')) clearError(key);
      }
    });
    form.addEventListener("change", function (e) {
      var id = e.target.id;
      if (id === "add-category") {
        if (!S.freqTouched) $("add-freq").value = defaultFreq() || val("add-freq");
        syncAccount();
        clearError("freq");
      }
      if (id === "add-coowner" || id === "add-owner") clearError("coowner");
      renderPills();
    });
    $("add-phone").addEventListener("blur", function () { checkField("phone"); });
    $("add-email").addEventListener("blur", function () { checkField("email"); });
  }

  function render() {
    var root = $("add-root");
    root.innerHTML = formHtml();
    syncAccount();
    wire();
    renderPills();
    var pre = BD.qs("company");
    if (pre && /^\d+$/.test(pre)) {
      Api.get(Api.path("companies", pre)).then(function (r) {
        if (r.company) pickCompany(r.company);
        $("add-name").focus();
      }, function () { $("add-company").focus(); });
    } else {
      $("add-company").focus();
    }
  }

  /** The page in place of the form: a sentence and no data (a failed /api/bd/me, or a BD role that
   *  does not add contacts). */
  function renderNote(words) {
    var root = $("add-root");
    if (!root) return;
    root.removeAttribute("aria-busy");
    root.innerHTML = '<div class="add-wrap"><h1 class="page-title add-title">Add contact</h1>' +
      '<div class="panel-info add-note" role="status">' + ico("info", 18) + "<span>" + esc(words) + "</span></div></div>";
  }

  var auth = window.TWAuth;
  if (!auth || !auth.ready || typeof auth.bdMe !== "function" || typeof auth.bdFailure !== "function") return;
  auth.ready.then(function () { return auth.bdMe(); }).then(function (res) {
    var ok = res && res.status >= 200 && res.status < 300 && res.body && res.body.ok;
    if (!ok) { renderNote(auth.bdFailure(res && res.status, res && res.body).message); return null; }
    var me = res.body;
    var can = me.can || {};
    if (can.add_contact !== true) { renderNote("Adding contacts isn't part of your BD role."); return null; }
    S.me = me;
    S.today = me.today || BD.bizToday();
    S.canClear = can.clear_duplicate === true;
    return Promise.all([
      Api.get("/api/bd/settings").then(function (r) { return r.settings; }, function () { return null; }),
      Api.get("/api/bd/users").then(function (r) { return r.items || []; }, function () { return []; }),
    ]).then(function (r) {
      S.settings = r[0];
      S.users = r[1];
      render();
    });
  }).catch(function (e) {
    var root = $("add-root");
    if (root) {
      root.innerHTML = '<div class="error-box" role="alert"><p>' + esc(errText(e)) + "</p>" +
        '<button type="button" class="btn" id="add-retry">Try again</button></div>';
      $("add-retry").addEventListener("click", function () { location.reload(); });
    }
  });
})();
