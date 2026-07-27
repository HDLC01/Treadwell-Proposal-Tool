// Externalized from trash.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
    const fmtDate = (iso) => TW.fmtBizDate(iso);   // business timezone (Central), see shared.js
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
          <label class="card-pick"><input type="checkbox" class="pick"> Select</label>
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
        c.querySelector(".pick").addEventListener("change", (e) => {
          c.classList.toggle("is-picked", e.target.checked);
          syncBulk();
        });
      });
      syncBulk();
    }

    function _name(c){ return (c.querySelector(".pname")||{}).textContent || c.dataset.id; }
    function _cards(){ return Array.from(document.querySelectorAll("#list .card")); }
    function _picked(){ return _cards().filter(c => c.querySelector(".pick")?.checked); }
    function _emptyIfNone(){
      const el = document.getElementById("list");
      if (el && !el.querySelector(".card")) { el.className="empty"; el.textContent="Trash is empty."; }
      syncBulk();
    }

    // ── bulk actions ───────────────────────────────────────────────────────────
    /** Keep the toolbar in step with the cards: hidden when empty, counts + the
     *  select-all tri-state derived from the checkboxes themselves (single source
     *  of truth, so a removed card can never leave a stale count behind). */
    function syncBulk() {
      const bar = document.getElementById("bulkbar");
      if (!bar) return;
      const all = _cards(), sel = _picked();
      bar.hidden = all.length === 0;
      const cnt = document.getElementById("bulk-count");
      if (cnt) cnt.textContent = sel.length ? `${sel.length} of ${all.length} selected` : `${all.length} in trash`;
      const btn = document.getElementById("purge-selected");
      if (btn) { btn.disabled = !sel.length; btn.textContent = sel.length ? `Delete selected (${sel.length})` : "Delete selected"; }
      const master = document.getElementById("select-all");
      if (master) {
        master.checked = all.length > 0 && sel.length === all.length;
        master.indeterminate = sel.length > 0 && sel.length < all.length;
      }
    }

    /** Permanently delete a list of cards. One confirm covers the whole batch;
     *  requests run a few at a time so emptying a big trash isn't serial, and any
     *  failures are reported rather than silently leaving cards behind. */
    async function purgeMany(cards, { title, detail }) {
      if (!cards.length) return;
      const ok = await TW.confirmDanger({
        title,
        name: cards.length === 1 ? _name(cards[0]) : `${cards.length} projects`,
        after: " will be permanently deleted.",
        detail,
        confirmText: cards.length === 1 ? "Delete forever" : `Delete ${cards.length} forever`,
        tone: "danger",
      });
      if (!ok) return;
      const bar = document.getElementById("bulkbar");
      const btns = bar ? Array.from(bar.querySelectorAll("button")) : [];
      btns.forEach(b => { b.disabled = true; });
      cards.forEach(c => { const b = c.querySelector(".purge-btn"); if (b) { b.disabled = true; b.textContent = "Deleting…"; } });

      const failed = [];
      const queue = cards.slice();
      const worker = async () => {
        while (queue.length) {
          const c = queue.shift();
          const id = decodeURIComponent(c.dataset.id);
          try {
            const r = await fetch("/api/draft/" + encodeURIComponent(id) + "?permanent=true",
                                  { method: "DELETE", headers: TW.authHeaders() });
            const j = await r.json();
            if (!j || j.ok === false) throw new Error((j && j.error) || "delete failed");
            c.remove();
          } catch (err) {
            failed.push(_name(c));
            const b = c.querySelector(".purge-btn"); if (b) { b.disabled = false; b.textContent = "Delete forever"; }
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(4, cards.length) }, worker));
      btns.forEach(b => { b.disabled = false; });
      _emptyIfNone();
      if (failed.length) alert(`Couldn't delete ${failed.length} project(s):\n` + failed.join("\n"));
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
      const ok = await TW.confirmDanger({
        title: "Delete forever?",
        name: _name(c), after: " will be permanently deleted.",
        detail: "This removes the project and its files for everyone — it can't be undone.",
        confirmText: "Delete forever",
        tone: "danger",
      });
      if (!ok) return;
      const btn = c.querySelector(".purge-btn"); if (btn) { btn.disabled = true; btn.textContent = "Deleting…"; }
      try {
        const r = await fetch("/api/draft/" + encodeURIComponent(id) + "?permanent=true", { method:"DELETE", headers: TW.authHeaders() });
        const j = await r.json();
        if (!j || j.ok === false) { alert((j&&j.error)||"Delete failed."); if (btn) { btn.disabled=false; btn.textContent="Delete forever"; } return; }
        c.remove(); _emptyIfNone();
      } catch (err) { alert("Delete failed. " + (err.message||"")); if (btn) { btn.disabled=false; btn.textContent="Delete forever"; } }
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
    document.getElementById("select-all").addEventListener("change", (e) => {
      _cards().forEach(c => {
        const cb = c.querySelector(".pick");
        if (cb) { cb.checked = e.target.checked; c.classList.toggle("is-picked", e.target.checked); }
      });
      syncBulk();
    });

    document.getElementById("purge-selected").addEventListener("click", () => purgeMany(_picked(), {
      title: "Delete selected forever?",
      detail: "This removes the projects and their files for everyone — it can't be undone.",
    }));

    document.getElementById("purge-all").addEventListener("click", () => purgeMany(_cards(), {
      title: "Empty the trash?",
      detail: "Every project in the trash will be permanently removed for everyone — it can't be undone.",
    }));

    load();
  
