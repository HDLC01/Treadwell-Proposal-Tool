/* BD's old login page (#806): send the person to the proposal tool's sign-in, and have sign-in
 * return them to the BD CRM.
 *
 * The return rides in this browser tab under the key frontend/auth.js reads (tw_return_to), the same
 * way auth.js itself remembers the page a signed-out person asked for. auth.js checks the value again
 * before it follows it; this one is a fixed path. Somebody already signed in lands on /bd/ at once,
 * because the sign-in page sends a signed-in person straight on to their return.
 */
(function () {
  "use strict";
  try { window.sessionStorage.setItem("tw_return_to", "/bd/"); } catch (e) { /* lands on home */ }
  window.location.replace("/login.html");
})();
