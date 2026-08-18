// Externalized from admin.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
    let ME = null, USERS = [], PROJECTS = [];
    function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
    function fmtDate(iso){ if(!iso) return "—"; const d=new Date(iso); return isNaN(d)?"—":d.toLocaleDateString(); }
    async function api(path, opts){ const r = await fetch(path, Object.assign({ headers: TW.authHeaders() }, opts||{})); return r.json().catch(()=>({ok:false,error:"bad response", status:r.status})); }

    async function boot(){
      await window.TWAuth.ready;
      ME = window.TWAuth.user() || {};
      const root = document.getElementById("root");
      if (ME.role !== "admin" && ME.role !== "super_admin") {
        root.innerHTML = '<div class="denied">Admin access only. Redirecting…</div>';
        setTimeout(()=>window.location.assign("/projects.html"), 1500); return;
      }
      shell();
      await refresh();
    }

    function shell(){
      document.getElementById("root").innerHTML = `
        <div class="top"><img class="logo" src="/img/treadwell-bison.svg" width="51" height="32" alt="Treadwell" /><h1>Admin</h1>
          <span class="tag">${ME.role==="super_admin"?"SUPER ADMIN":"ADMIN"}</span></div>
        <p class="sub">User & project management + system overview</p>
        <div class="cards" id="cards"></div>
        <div class="panel">
          <div class="ph"><strong>Users</strong><span id="ucount" style="color:var(--ink-v)"></span>
            <span class="grow"></span>
            <input id="search" placeholder="Search email or name…" />
            <select id="rolefilter"><option value="">All roles</option><option value="user">Users</option><option value="admin">Admins</option><option value="super_admin">Super admins</option></select>
          </div>
          <div style="overflow-x:auto"><table><thead><tr>
            <th>Email</th><th>Name</th><th>Role</th><th title="Can be assigned proposals. Independent of role — somebody can be a member, an admin and an estimator at once.">Estimator</th><th>Status</th><th>Joined</th><th>Last change</th><th>Set role</th><th style="text-align:right">Actions</th>
          </tr></thead><tbody id="tbody"></tbody></table></div>
        </div>
        ${roleMatrixHtml()}
        <div class="panel" style="margin-top:18px;">
          <div class="ph"><strong>Projects</strong><span id="pcount" style="color:var(--ink-v)"></span>
            <span class="grow"></span>
            <input id="psearch" placeholder="Search project or owner…" />
          </div>
          <div style="overflow-x:auto"><table><thead><tr>
            <th>Project</th><th>Owner</th><th>Total</th><th>Work</th><th>Updated</th><th style="text-align:right">Actions</th>
          </tr></thead><tbody id="ptbody"></tbody></table></div>
        </div>`;
      document.getElementById("search").addEventListener("input", renderRows);
      document.getElementById("rolefilter").addEventListener("change", refresh);
      document.getElementById("psearch").addEventListener("input", renderProjects);
    }

    // ── What each role can see ──
    // Hanz, 2026-08-19: "can we actually show what sidebar tabs is can be present for the admins,
    // the members and the superadmin?"
    //
    // THE ROWS ARE NOT WRITTEN HERE. window.TWAuth.navMatrix() builds the sidebar's nav once per
    // role out of the menu's own markup and diffs the results, so this table is the menu rather
    // than a description of it. A hand-kept copy of the tab list would be wrong the first time
    // somebody adds a page — which is the whole failure this panel would otherwise introduce.
    // Every sentence under the table is computed from the same rows for the same reason: a
    // hardcoded "only the Admin tab differs" is a claim that rots silently.
    const ROLE_LABEL = { user:"Member", admin:"Admin", super_admin:"Super admin" };
    function roleLabelOf(r){ return ROLE_LABEL[r] || r; }

    function roleMatrixHtml(){
      const nav = (window.TWAuth && window.TWAuth.navMatrix) ? window.TWAuth.navMatrix() : null;
      if (!nav || !nav.rows.length) {
        return `<div class="panel" style="margin-top:18px;"><div class="ph"><strong>What each role can see</strong></div>
          <p class="rv-note">The sidebar didn't report its tabs, so there is nothing to show here.
          Reload the page; if it persists, auth.js failed to load.</p></div>`;
      }
      const roles = nav.roles, rows = nav.rows, mine = ME.role || "user";
      const seen = (r) => roles.filter(x => r.roles[x]).length;
      const differing = rows.filter(r => seen(r) !== roles.length);
      const count = {}; roles.forEach(x => { count[x] = rows.filter(r => r.roles[x]).length; });

      const head = roles.map(r =>
        `<th class="rv-h${r===mine?" rv-mine":""}">${esc(roleLabelOf(r))}` +
        `${r===mine?'<span class="you">you</span>':""}</th>`).join("");

      const body = rows.map(r => `<tr data-href="${esc(r.href)}" data-label="${esc(r.label)}">
          <td class="rv-sec">${esc(r.section)}</td>
          <td><span class="rv-ico">${esc(r.glyph)}</span>${esc(r.label)}${
            r.tag?`<span class="badge b-user" style="margin-left:6px">${esc(r.tag)}</span>`:""}
            <span class="rv-href">${esc(r.href)}</span></td>
          ${roles.map(x => `<td class="rv-cell" data-role="${esc(x)}">${
            r.roles[x]?'<span class="rv-yes">✓</span>':'<span class="rv-no">—</span>'}</td>`).join("")}
        </tr>`).join("");

      return `<div class="panel" style="margin-top:18px;">
        <div class="ph"><strong>What each role can see</strong>
          <span style="color:var(--ink-v)">${rows.length} sidebar tabs · ${differing.length}
            ${differing.length===1?"differs":"differ"} by role</span>
          <span class="grow"></span>
          <span class="rv-you">Your role: <strong>${esc(roleLabelOf(mine))}</strong></span>
        </div>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>Section</th><th>Sidebar tab</th>${head}</tr></thead>
          <tbody>${body}</tbody>
        </table></div>
        <div class="rv-note">
          <p>${roleDiffSentence(nav, count)}</p>
          <p><strong>This is the sidebar, not a permission model.</strong> Hiding a tab hides a
            link and nothing else — every page stays reachable by typing its URL. What actually
            stops someone is the server: <code>_require_admin</code> guards
            <code>/api/admin/*</code> (the users, stats and digest calls on this page, and admin
            project deletes), the Item Library's vendor / division / unit writes, and the
            notification-recipient writes.</p>
          <p>Three tabs everybody can open still gate controls <em>inside</em> the page on role:
            <strong>Items and Assemblies</strong> (only an admin edits vendors, divisions and
            units; everyone may pick from them), <strong>Notification Sending</strong> (only an
            admin adds, removes or toggles anyone but themselves) and <strong>Active
            Projects</strong> (only an admin reassigns someone else's project).</p>
        </div></div>`;
    }

    /** The one-line summary, computed — never asserted — so it cannot outlive the truth. */
    function roleDiffSentence(nav, count){
      const roles = nav.roles, rows = nav.rows;
      const only = (has, lacks) => rows.filter(r => r.roles[has] && !r.roles[lacks]);
      const names = (list) => list.map(r => `<strong>${esc(r.label)}</strong>`).join(", ");
      const total = rows.length;
      const adminExtra = only("admin", "user"), memberExtra = only("user", "admin");
      const superExtra = only("super_admin", "admin");
      const parts = [];
      if (!adminExtra.length && !memberExtra.length) {
        parts.push(`Members and admins see the same ${total} tabs.`);
      } else {
        parts.push(`Members see ${count.user} of the ${total} tabs.`);
        if (adminExtra.length) {
          parts.push(`${adminExtra.length===1?"The only tab":"The tabs"} an admin sees and a
            member does not: ${names(adminExtra)}.`);
        }
        if (memberExtra.length) parts.push(`Hidden from admins: ${names(memberExtra)}.`);
      }
      parts.push(superExtra.length
        ? `A super admin also sees ${names(superExtra)}.`
        : `A super admin's sidebar is identical to an admin's — the extra powers are on this page
           (only a super admin may grant the admin role, or act on another admin), not a tab
           of their own.`);
      return parts.join(" ");
    }

    async function refresh(){
      const role = document.getElementById("rolefilter").value;
      const s = await api("/api/admin/stats");
      if (s.ok) {
        const st = s.stats||{};
        document.getElementById("cards").innerHTML =
          card("Users", st.users) + card("Admins", st.admins) + card("Projects", st.projects) + card("Proposals generated", st.proposals_generated);
      }
      const u = await api("/api/admin/users" + (role?`?role=${role}`:""));
      USERS = (u && u.users) || [];
      document.getElementById("ucount").textContent = `${USERS.length} loaded`;
      renderRows();
      loadProjects();
    }
    function card(k,v){ return `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${v==null?"—":v}</div></div>`; }
    function money(n){ return (typeof n==="number") ? "$"+n.toLocaleString(undefined,{maximumFractionDigits:0}) : "—"; }

    // ── Projects (unified list) + admin delete ──
    async function loadProjects(){
      const r = await api("/api/drafts");
      PROJECTS = (r && r.projects) || [];
      document.getElementById("pcount").textContent = `${PROJECTS.length} loaded`;
      renderProjects();
    }
    function renderProjects(){
      const q = (document.getElementById("psearch").value||"").toLowerCase();
      const rows = PROJECTS.filter(p => !q
        || (p.project_name||"").toLowerCase().includes(q)
        || (p.owner_email||"").toLowerCase().includes(q));
      document.getElementById("ptbody").innerHTML = rows.map(p => `
        <tr data-id="${esc(p.id)}" data-name="${esc(p.project_name||"")}">
          <td>${esc(p.project_name||"(untitled)")}</td>
          <td>${p.owner_email?TWCrm.avatarHtml(p.owner_email)+esc(TWCrm.nameOf(p.owner_email)):"—"}</td>
          <td>${money(p.total)}</td>
          <td>${p.work_type?`<span class="badge b-user">${esc(p.work_type)}</span>`:"—"}</td>
          <td>${fmtDate(p.updated_at)}</td>
          <td style="text-align:right"><button class="act danger" data-act="delproj">🗑 Trash</button></td>
        </tr>`).join("") || '<tr><td colspan="6" style="color:#5c403f;padding:24px">No projects.</td></tr>';
      document.querySelectorAll("#ptbody [data-act='delproj']").forEach(el =>
        el.addEventListener("click", () => {
          const tr = el.closest("tr");
          doDeleteProject(tr.dataset.id, tr.dataset.name);
        }));
    }
    async function doDeleteProject(id, name){
      const ok = await TW.confirmDanger({ title:"Move to Trash?", before:"Move ", name:(name||id), after:" to Trash?",
        detail:"It leaves the shared Proposals Database but stays restorable from the Trash page.", confirmText:"Move to Trash", tone:"warn", icon:"🗑" });
      if (!ok) return;
      const r = await api(`/api/admin/projects/${encodeURIComponent(id)}`, { method:"DELETE" });
      if (!r || r.ok===false){ alert((r&&r.error)||"Move to Trash failed"); }
      refresh();
    }

    function roleBadge(r){ return `<span class="badge ${r==="super_admin"?"b-super":r==="admin"?"b-admin":"b-user"}">${r==="super_admin"?"super admin":r}</span>`; }
    function statusBadge(s){ return `<span class="badge ${s==="banned"?"b-banned":s==="paused"?"b-paused":"b-active"}">${esc(s||"active")}</span>`; }

    function renderRows(){
      const q = (document.getElementById("search").value||"").toLowerCase();
      const isSuper = ME.role==="super_admin";
      const rows = USERS.filter(u => !q || (u.email||"").toLowerCase().includes(q) || (u.full_name||"").toLowerCase().includes(q));
      document.getElementById("tbody").innerHTML = rows.map(u => {
        const isSelf = (u.email||"").toLowerCase() === (ME.email||"").toLowerCase();
        const tSuper = u.role==="super_admin", tAdmin = u.role==="admin";
        const canEdit = !isSelf && !tSuper && (isSuper || !tAdmin);
        const paused = u.status==="paused", banned = u.status==="banned";
        const opt = (val,label)=>`<option value="${val}" ${u.role===val?"selected":""} ${(val==="admin"&&!isSuper)?"disabled":""}>${label}</option>`;
        return `<tr data-id="${esc(u.id)}">
          <td>${TWCrm.avatarHtml(u.full_name||u.email)}${esc(u.email)}${isSelf?'<span class="you">you</span>':""}</td>
          <td>${esc(u.full_name||TWCrm.nameOf(u.email))}</td>
          <td>${roleBadge(u.role)}</td>
          <!-- Anyone an admin can see, an admin can flag: being assignable is not a
               privilege, so this is NOT gated by canEdit the way role/ban/delete are.
               An admin who also estimates must be able to tick their own box. -->
          <td><button class="est-tog ${u.is_estimator?"on":""}" data-act="estimator"
                      aria-pressed="${u.is_estimator?"true":"false"}"
                      title="${u.is_estimator?"Remove from the estimator roster":"Add to the estimator roster"}"
                >${u.is_estimator?"✓ Estimator":"Add"}</button></td>
          <td>${statusBadge(u.status)}</td>
          <td>${fmtDate(u.created_at)}</td>
          <td>${fmtDate(u.updated_at)}</td>
          <td><select class="role" ${canEdit?"":"disabled"} data-act="role">${opt("user","User")}${opt("admin","Admin")}${tSuper?'<option selected disabled>Super Admin</option>':""}</select></td>
          <td style="text-align:right">
            <button class="act" data-act="${paused?"resume":"pause"}" ${canEdit?"":"disabled"}>${paused?"Resume":"Pause"}</button>
            <button class="act" data-act="${banned?"unban":"ban"}" ${canEdit?"":"disabled"}>${banned?"Unban":"Ban"}</button>
            <button class="act danger" data-act="delete" ${canEdit?"":"disabled"}>Delete</button>
          </td></tr>`;
      }).join("") || '<tr><td colspan="9" style="color:#5c403f;padding:24px">No users.</td></tr>';

      document.querySelectorAll("#tbody [data-act]").forEach(el => {
        const act = el.dataset.act, id = el.closest("tr").dataset.id;
        if (act==="role") el.addEventListener("change", ()=>doRole(id, el.value));
        else el.addEventListener("click", ()=>doAction(act, id, el.closest("tr")));
      });
    }

    async function doRole(id, role){ const r = await api(`/api/admin/users/${id}/role`,{method:"PATCH",body:JSON.stringify({role})}); after(r); }
    async function doAction(act, id, tr){
      const email = tr.children[0].textContent;
      if (act==="delete" && !(await TW.confirmDanger({ title:"Delete user?", before:"Delete ", name:email, after:"?",
        detail:"This can't be undone.", confirmText:"Delete", tone:"danger" }))) return;
      if (act==="ban" && !(await TW.confirmDanger({ title:"Ban user?", before:"Ban ", name:email, after:"?",
        detail:"They won't be able to sign in.", confirmText:"Ban", tone:"danger" }))) return;
      let r;
      if (act==="pause") r = await api(`/api/admin/users/${id}/status`,{method:"PUT",body:JSON.stringify({status:"paused"})});
      else if (act==="resume") r = await api(`/api/admin/users/${id}/status`,{method:"PUT",body:JSON.stringify({status:"active"})});
      else if (act==="ban") r = await api(`/api/admin/users/${id}/ban`,{method:"POST",body:JSON.stringify({reason:""})});
      else if (act==="unban") r = await api(`/api/admin/users/${id}/unban`,{method:"POST",body:"{}"});
      else if (act==="delete") r = await api(`/api/admin/users/${id}`,{method:"DELETE"});
      else if (act==="estimator") {
        const on = tr.querySelector(".est-tog").getAttribute("aria-pressed") !== "true";
        r = await api(`/api/admin/users/${id}/estimator`,{method:"PUT",body:JSON.stringify({is_estimator:on})});
      }
      after(r);
    }
    function after(r){ if(!r || r.ok===false){ alert((r&&r.error)||"Action failed"); } refresh(); }

    boot();
  
