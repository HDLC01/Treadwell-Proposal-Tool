// Externalized from trash.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
    function fmtDate(iso){ if(!iso) return "—"; const d=new Date(iso); return isNaN(d)?"—":d.toLocaleDateString(); }
    function money(n){ return (typeof n==="number") ? "$"+n.toLocaleString(undefined,{maximumFractionDigits:0}) : (n||""); }
    function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

    function tokenSoon() {
      return new Promise(res => {
        const t0 = Date.now();
        (function poll(){
          if (window.__TW_TOKEN) return res(true);
          if (Date.now() - t0 > 8000) return res(false);
          setTimeout(poll, 40);
        })();
      });
    }

    function render(projects) {
      const el = document.getElementById("list");
      if (!projects.length) { el.className="empty"; el.textContent="Trash is empty."; return; }
      el.className = "grid";
      el.innerHTML = projects.map(p => `
        <div class="card" data-id="${encodeURIComponent(p.id)}">
          <p class="pname">${esc(p.project_name||"(untitled)")}</p>
          <div class="meta">
            ${p.total!=null?`<span class="total">${money(p.total)}</span>`:""}
            ${p.work_type?`<span class="badge">${esc(p.work_type)}</span>`:""}
          </div>
          <div class="meta" style="margin-top:8px;">
            <span>by ${esc(p.owner_email||"—")}</span>
            <span class="trashed">trashed ${fmtDate(p.deleted_at)}</span>
          </div>
          <div class="card-foot">
            <button type="button" class="purge-btn" title="Delete permanently">Delete forever</button>
            <button type="button" class="restore-btn">↩ Restore</button>
          </div>
        </div>`).join("");
      el.querySelectorAll(".card").forEach(c => {
        c.querySelector(".restore-btn").addEventListener("click", () => restore(c));
        c.querySelector(".purge-btn").addEventListener("click", () => purge(c));
      });
    }

    function _name(c){ return (c.querySelector(".pname")||{}).textContent || c.dataset.id; }
    function _emptyIfNone(){
      const el = document.getElementById("list");
      if (el && !el.querySelector(".card")) { el.className="empty"; el.textContent="Trash is empty."; }
    }

    async function restore(c) {
      const id = decodeURIComponent(c.dataset.id);
      try {
        const r = await fetch("/api/draft/" + encodeURIComponent(id) + "/restore", { method:"POST", headers: TW.authHeaders() });
        const j = await r.json();
        if (!j || j.ok === false) { alert((j&&j.error)||"Restore failed."); return; }
        c.remove(); _emptyIfNone();
        try { sessionStorage.removeItem("tw_projects_cache"); } catch {}
      } catch (err) { alert("Restore failed. " + (err.message||"")); }
    }

    async function purge(c) {
      const id = decodeURIComponent(c.dataset.id);
      if (!confirm(`Permanently delete “${_name(c)}”?\n\nThis can't be undone.`)) return;
      try {
        const r = await fetch("/api/draft/" + encodeURIComponent(id) + "?permanent=true", { method:"DELETE", headers: TW.authHeaders() });
        const j = await r.json();
        if (!j || j.ok === false) { alert((j&&j.error)||"Delete failed."); return; }
        c.remove(); _emptyIfNone();
      } catch (err) { alert("Delete failed. " + (err.message||"")); }
    }

    async function load() {
      await tokenSoon();
      const el = document.getElementById("list");
      try {
        const r = await fetch("/api/trash", { headers: TW.authHeaders() });
        const j = await r.json();
        render((j && j.projects) || []);
      } catch (err) {
        el.className="empty"; el.textContent="Couldn't load trash. " + (err.message||"");
      }
    }
    load();
  
