// Externalized from history.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
    // Every verb drafts.log_event can write, spelled the way a person would say it.
    // The row reads "<who> <verb> <project>", so each value is past tense and, where
    // the project is the object of the sentence, ends with the preposition that makes
    // it scan ("changed status on Oak Grove").
    //
    // A MISSING ENTRY IS NOT HARMLESS. The fallback below is `VERB[e.action] || e.action`,
    // which prints the raw column value — so before this map was filled in, History told
    // Troy that somebody "closed_lost" and "to_dropbox" a project. Ten verbs shipped over
    // the last three weeks without labels (won, not_won, closed_lost, reactivated,
    // notify_picked, nav_access_changed, to_dropbox, info_sheet_generated and the two
    // calendar ones), so this list needs a new line whenever log_event learns a word.
    const VERB = {
      created:"created", generated:"generated", published:"sent the proposal for",
      // Born in the Lead Inbox rather than typed by hand. The two are kept apart on
      // purpose: `created_from_lead` had a person press Create estimate, and
      // `auto_created_from_lead` did not — auto-creation has been off on prod since
      // 2026-08-07, so seeing that verb in the feed at all is worth a second look.
      created_from_lead:"created from a lead", auto_created_from_lead:"auto-created from a lead",
      lead_status_changed:"changed the lead status on",
      // The notification roster, per project.
      estimator_added:"added an estimator to", estimator_removed:"removed an estimator from",
      // Won / lost. `not_won` is the undo of a by-hand won mark, and it is NOT the same
      // as closed_lost — one says "nobody has decided yet", the other says "we lost it".
      won:"marked won", not_won:"cleared the won mark on",
      closed_lost:"closed as lost", reactivated:"reopened",
      // Filing and paperwork.
      to_dropbox:"filed to Dropbox", info_sheet_generated:"generated the info sheet for",
      email:"emailed",
      // Ownership and triage.
      assigned:"assigned an estimator on", status_changed:"changed status on",
      marked_test:"filed as a test project", marked_real:"filed as a real bid",
      notify_picked:"changed who gets notified on",
      // Lifecycle. Trash is reversible, purge is not — they must not read alike.
      archived:"archived", unarchived:"un-archived",
      trashed:"moved to trash", restored:"restored from trash",
      purged_project:"permanently deleted", deleted_project:"deleted project",
      // Calendar.
      calendar_event_created:"added a calendar event", calendar_event_updated:"updated a calendar event",
      calendar_event_deleted:"deleted a calendar event",
      // Admin, about a PERSON rather than a project.
      role_changed:"changed the role on", nav_access_changed:"changed tab permissions",
      banned:"banned", unbanned:"unbanned", deleted_user:"deleted",
    };
    function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
    function money(n){ return (typeof n==="number") ? " — $"+n.toLocaleString(undefined,{maximumFractionDigits:0}) : ""; }
    const when = (iso) => TW.fmtBizDateTime(iso);   // business timezone (Central), see shared.js

    async function load(){
      await window.TWAuth.ready;
      const el = document.getElementById("feed");
      try {
        const j = await (await fetch("/api/history", { headers: TW.authHeaders() })).json();
        const ev = (j && j.events) || [];
        if(!ev.length){ el.className="empty"; el.textContent="No activity yet."; return; }
        el.className=""; el.innerHTML = ev.map(e => {
          const d = e.detail || {};
          const proj = d.project_name ? `<span class="proj">${esc(d.project_name)}</span>` : "";
          return `<div class="row"><span class="dot ${esc(e.action)}"></span>
            <div><span class="who">${esc(e.actor_email||"someone")}</span>
            <span class="act">${esc(VERB[e.action]||e.action)}</span> ${proj}
            <span class="total">${money(d.total)}</span></div>
            <span class="when">${esc(when(e.created_at))}</span></div>`;
        }).join("");
      } catch(err){ el.className="empty"; el.textContent="Couldn't load history. "+(err.message||""); }
    }
    load();
  
