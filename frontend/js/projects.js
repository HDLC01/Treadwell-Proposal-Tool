// Externalized from projects.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
    document.getElementById("new-project").addEventListener("click", (e) => {
      e.preventDefault();
      // Fresh start: clear LOCAL state only (server copies are kept) so intake
      // mints a new draft id. Does NOT delete any saved project.
      try { localStorage.removeItem("treadwell.proposal_tool.state"); } catch {}
      try { localStorage.removeItem("treadwell.proposal_tool.draft_id"); } catch {}
      try { sessionStorage.removeItem("treadwell.proposal_tool.hydrated_once"); } catch {}
      window.location.assign("/");
    });

    function fmtDate(iso){ if(!iso) return "—"; const d=new Date(iso); return isNaN(d)?"—":d.toLocaleDateString(); }
    function money(n){ return (typeof n==="number") ? "$"+n.toLocaleString(undefined,{maximumFractionDigits:0}) : (n||""); }

    // Resolve as soon as auth.js sets the token (right after getSession) so the
    // projects fetch runs in PARALLEL with the sidebar's /api/me + render —
    // instead of waiting for the whole auth handshake (saves a round-trip).
    function tokenSoon() {
      return new Promise(res => {
        const t0 = Date.now();
        (function poll(){
          if (window.__TW_TOKEN) return res(true);
          if (Date.now() - t0 > 8000) return res(false);  // unauth → auth.js redirects
          setTimeout(poll, 40);
        })();
      });
    }

    const CACHE_KEY = "tw_projects_cache";
    const FILTER_KEY = "tw_projects_filter";
    let ALL_PROJECTS = [];
    // Default to "active" so the working list isn't cluttered by finished jobs;
    // existing projects have no `archived` flag → treated as active (nothing
    // disappears). Remember the last-used filter across visits.
    let CURRENT_FILTER = (() => {
      try { return sessionStorage.getItem(FILTER_KEY) || "active"; } catch { return "active"; }
    })();

    // Test/demo projects are segregated into their OWN "Test" tab and kept OUT
    // of Active / Inactive / All, so the working list only shows real customer
    // bids. Classified by name: anything containing sample/test/verify/demo/qa/
    // bugtest, "delete me", or starting with "zz". Rename a project to move it
    // in or out of the Test bucket.
    function isTest(p) {
      const n = String((p && p.project_name) || "");
      return /\b(sample|test|verify|demo|qa|bugtest)\b/i.test(n)
          || /delete me/i.test(n)
          || /^\s*zz/i.test(n);
    }
    function isActive(p)   { return !p.archived; }
    function isInactive(p) { return !!p.archived; }
    function applyFilter(list) {
      if (CURRENT_FILTER === "test") return list.filter(isTest);
      const real = list.filter(p => !isTest(p));   // test projects never show in active/inactive/all
      if (CURRENT_FILTER === "inactive") return real.filter(isInactive);
      if (CURRENT_FILTER === "all")      return real;
      return real.filter(isActive);  // "active"
    }

    function renderChips() {
      const f = document.getElementById("filters");
      const real = ALL_PROJECTS.filter(p => !isTest(p));   // Active/Inactive/All count real bids only
      const nActive = real.filter(isActive).length;
      const nInactive = real.filter(isInactive).length;
      const nTest = ALL_PROJECTS.filter(isTest).length;
      const defs = [
        ["active",   "Active",   nActive],
        ["inactive", "Inactive", nInactive],
        ["all",      "All",      real.length],
        ["test",     "Test",     nTest],
      ];
      f.hidden = ALL_PROJECTS.length === 0;
      f.innerHTML = defs.map(([key,label,n]) =>
        `<button type="button" class="chip ${key===CURRENT_FILTER?"sel":""}" data-filter="${key}">${label}<span class="n">${n}</span></button>`
      ).join("");
      f.querySelectorAll(".chip").forEach(ch => ch.addEventListener("click", () => {
        CURRENT_FILTER = ch.dataset.filter;
        try { sessionStorage.setItem(FILTER_KEY, CURRENT_FILTER); } catch {}
        paint();
      }));
    }

    // Re-draw chips + the filtered grid from ALL_PROJECTS (single source of truth).
    function paint() {
      renderChips();
      const el = document.getElementById("list");
      const shown = applyFilter(ALL_PROJECTS);
      if (!shown.length) {
        el.className = "empty";
        el.textContent = ALL_PROJECTS.length
          ? (CURRENT_FILTER === "inactive" ? "No inactive projects."
             : CURRENT_FILTER === "test"   ? "No test projects."
             : "No active projects.")
          : "No projects yet. Click “+ New project” to start.";
        return;
      }
      el.className = "grid";
      el.innerHTML = shown.map(p => `
        <div class="card" data-id="${encodeURIComponent(p.id)}">
          <button type="button" class="status-toggle ${p.archived?"is-inactive":"is-active"}"
                  data-archived="${p.archived?1:0}"
                  title="Click to mark ${p.archived?"active":"inactive"}">${p.archived?"Inactive":"Active"}</button>
          <p class="pname">${esc(p.project_name||"(untitled)")}</p>
          <div class="meta">
            ${p.total!=null?`<span class="total">${money(p.total)}</span>`:""}
            ${p.work_type?`<span class="badge">${esc(p.work_type)}</span>`:""}
            ${p.deadline?`<span>due ${esc(p.deadline)}</span>`:""}
          </div>
          <div class="meta" style="margin-top:8px;">
            <span>by ${esc(p.owner_email||"—")}</span>
            <span>updated ${fmtDate(p.updated_at)}</span>
          </div>
          <div class="card-foot">
            <button type="button" class="trash-btn" title="Move to Trash">🗑 Trash</button>
            <div class="foot-actions">
              <button type="button" class="files-btn" title="Generate + download the files (no need to re-walk intake)">📄 Files</button>
              <button type="button" class="open-btn">Open / Edit →</button>
            </div>
          </div>
        </div>`).join("");
      const open = (c) => window.location.assign("/?d=" + c.dataset.id);
      el.querySelectorAll(".card").forEach(c => {
        c.addEventListener("click", () => open(c));
        const btn = c.querySelector(".open-btn");
        if (btn) btn.addEventListener("click", (e) => { e.stopPropagation(); open(c); });
        const tb = c.querySelector(".trash-btn");
        if (tb) tb.addEventListener("click", (e) => { e.stopPropagation(); trashCard(c); });
        const st = c.querySelector(".status-toggle");
        if (st) st.addEventListener("click", (e) => { e.stopPropagation(); toggleStatus(c, st); });
        const fb = c.querySelector(".files-btn");
        if (fb) fb.addEventListener("click", (e) => {
          e.stopPropagation();
          // c.dataset.id is already encodeURIComponent'd. files=1 → done.html
          // generates + shows downloads without the intake walk.
          window.location.assign("/done.html?d=" + c.dataset.id + "&files=1");
        });
      });
    }

    function cacheProjects() { try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(ALL_PROJECTS)); } catch {} }

    async function toggleStatus(c, btn) {
      const id = decodeURIComponent(c.dataset.id);
      const next = btn.dataset.archived !== "1";   // currently active → mark inactive
      btn.disabled = true;
      try {
        const r = await fetch("/api/draft/" + encodeURIComponent(id) + "/archive", {
          method: "POST", headers: TW.authHeaders(), body: JSON.stringify({ archived: next }),
        });
        const j = await r.json();
        if (!j || j.ok === false) { alert((j&&j.error)||"Couldn't update status."); btn.disabled=false; return; }
        const p = ALL_PROJECTS.find(x => x.id === id);
        if (p) p.archived = next;
        cacheProjects();
        paint();   // re-filter: a now-inactive card leaves the Active view
      } catch (err) { alert("Couldn't update status. " + (err.message||"")); btn.disabled=false; }
    }

    async function trashCard(c) {
      const id = decodeURIComponent(c.dataset.id);
      const name = (c.querySelector(".pname")||{}).textContent || id;
      if (!confirm(`Move “${name}” to Trash?\n\nIt leaves the active list but stays restorable from the Trash page.`)) return;
      try {
        const r = await fetch("/api/draft/" + encodeURIComponent(id), { method:"DELETE", headers: TW.authHeaders() });
        const j = await r.json();
        if (!j || j.ok === false) { alert((j&&j.error)||"Couldn't move to Trash."); return; }
        ALL_PROJECTS = ALL_PROJECTS.filter(p => p.id !== id);
        cacheProjects();
        paint();
      } catch (err) { alert("Couldn't move to Trash. " + (err.message||"")); }
    }

    function setProjects(list) { ALL_PROJECTS = Array.isArray(list) ? list : []; paint(); }

    async function load() {
      // Stale-while-revalidate: paint the last-known list instantly (perceived
      // 0ms), then fetch fresh in the background and update. The list is shared,
      // so we always revalidate — the cache only removes the spinner.
      try {
        const cached = JSON.parse(sessionStorage.getItem(CACHE_KEY) || "null");
        if (Array.isArray(cached) && cached.length) setProjects(cached);
      } catch {}
      await tokenSoon();
      const el = document.getElementById("list");
      try {
        const r = await fetch("/api/drafts", { headers: TW.authHeaders() });
        const j = await r.json();
        const projects = (j && j.projects) || [];
        setProjects(projects);
        cacheProjects();
      } catch (err) {
        if (el.className !== "grid") { el.className="empty"; el.textContent="Couldn't load projects. " + (err.message||""); }
      }
    }
    function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
    load();
  
