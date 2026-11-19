/* The BD home, /bd/ (#806): greets the person by first name and says their BD role.
 *
 * It reads /api/bd/me through the tool's shell, TWAuth.bdMe(): the same single answer the sidebar's
 * BD CRM group reads for its sections, so the page costs no second request. It starts only once
 * TWAuth.ready settles, which never happens on a page the tool has refused (the refusal card stays).
 *
 * Without a BD login (no BD role, a turned-off login, a proposal-tool admin nobody added on BD's
 * People table) the page shows the server's own sentence and no data. So does every other failure:
 * the tool's sign-in gate's 401 and 403 (their sentence is in `error`, there is no `message`), BD's
 * 503s, and no network. Every value is set as text, never as markup.
 *
 * This Week (the weekly list) fills this page in the next ticket, and brings the role-home redirect
 * with it (an assistant's BD home is Contacts).
 */
(function () {
  "use strict";

  var CODE = /^[a-z][a-z_]*$/;

  function el(id) { return document.getElementById(id); }

  function setText(id, text) {
    var e = el(id);
    if (e) e.textContent = text;
  }

  /** The sentence to show for a failed /api/bd/me: BD's message, or the tool's gate's sentence. */
  function failureSentence(res) {
    var status = res && res.status;
    var body = res && res.body && typeof res.body === "object" ? res.body : {};
    if (typeof body.message === "string" && body.message) return body.message;
    if (typeof body.error === "string" && body.error && !CODE.test(body.error)) return body.error;
    if (!status) return "Can't reach the server. Check your connection and try again.";
    if (status === 401) return "Sign in again to continue.";
    if (status === 403) return "You don't have a BD role.";
    return "The BD CRM isn't answering right now. Try again in a minute.";
  }

  function showRefused(res) {
    setText("bd-greeting", "BD CRM");
    setText("bd-role", failureSentence(res));
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
    setText("bd-home-note-text", "This Week, your list of calls for the week, comes here next.");
    var note = el("bd-home-note");
    if (note) note.hidden = false;
  }

  function start() {
    var auth = window.TWAuth;
    if (!auth || typeof auth.bdMe !== "function") { showRefused({ status: 0 }); return; }
    auth.bdMe().then(function (res) {
      var ok = res && res.status >= 200 && res.status < 300 && res.body && res.body.ok;
      if (ok) showWelcome(res.body);
      else showRefused(res);
    });
  }

  var ready = window.TWAuth && window.TWAuth.ready;
  if (ready && typeof ready.then === "function") ready.then(start);
})();
