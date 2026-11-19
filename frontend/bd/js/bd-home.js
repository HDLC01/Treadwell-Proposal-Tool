/* The BD home, /bd/ (#806): greets the person by first name and says their BD role.
 *
 * It reads /api/bd/me through the tool's shell, TWAuth.bdMe(): the same single answer the sidebar's
 * BD CRM group reads for its sections, so the page costs no second request. It starts only once
 * TWAuth.ready settles, which never happens on a page the tool has refused (the refusal card stays).
 *
 * Without a BD login (no BD role, a turned-off login, a proposal-tool admin nobody added on BD's
 * People table) the page shows the server's own sentence and no data. So does every other failure:
 * the tool's sign-in gate's 401 and 403 (their sentence is in `error`, there is no `message`), BD's
 * 503s, and no network. The sentence is TWAuth.bdFailure's, the one reader the sidebar's BD group
 * also uses, so the two never say different things about the same answer. Every value is set as
 * text, never as markup.
 *
 * This Week (the weekly list) fills this page in the next ticket, and brings the role-home redirect
 * with it (an assistant's BD home is Contacts). Until then the note about it shows only to a role
 * that will have the list (can.week); anyone else is told their BD pages move in next.
 */
(function () {
  "use strict";

  function el(id) { return document.getElementById(id); }

  function setText(id, text) {
    var e = el(id);
    if (e) e.textContent = text;
  }

  function showRefused(res) {
    setText("bd-greeting", "BD CRM");
    setText("bd-role", window.TWAuth.bdFailure(res && res.status, res && res.body).message);
    var note = el("bd-home-note");
    if (note) note.hidden = true;
  }

  function showWelcome(body) {
    var BD = window.BD;
    var user = body.user || {};
    var first = BD.firstName(user.name || user.email || "");
    var hello = BD.greeting(BD.bizNowISO());
    setText("bd-greeting", first ? hello + ", " + first : hello);
    var role = BD.LABELS.role[user.role] || String(user.role || "");
    setText("bd-role", "Your BD role: " + role);
    var week = !!(body.can && body.can.week === true);
    setText("bd-home-note-text", week ? "This Week, your list of calls for the week, comes here next."
      : "Your BD pages move in here next.");
    var note = el("bd-home-note");
    if (note) note.hidden = false;
  }

  function start() {
    var auth = window.TWAuth;
    if (!auth || typeof auth.bdMe !== "function" || typeof auth.bdFailure !== "function") return;
    auth.bdMe().then(function (res) {
      var ok = res && res.status >= 200 && res.status < 300 && res.body && res.body.ok;
      if (ok) showWelcome(res.body);
      else showRefused(res);
    });
  }

  var ready = window.TWAuth && window.TWAuth.ready;
  if (ready && typeof ready.then === "function") ready.then(start);
})();
