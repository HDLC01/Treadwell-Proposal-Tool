// Externalized from history.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
    const VERB = { created:"created", generated:"generated", role_changed:"changed the role on",
      status_changed:"changed status on", banned:"banned", unbanned:"unbanned", deleted_user:"deleted",
      deleted_project:"deleted project" };
    function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
    function money(n){ return (typeof n==="number") ? " — $"+n.toLocaleString(undefined,{maximumFractionDigits:0}) : ""; }
    function when(iso){ if(!iso) return ""; const d=new Date(iso); return isNaN(d)?"":d.toLocaleString(); }

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
  
