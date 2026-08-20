// Externalized from admin.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
    let ME = null, USERS = [], PROJECTS = [];
    // The stored tab policy: { deny, locked_pages, locked_roles, tabs, updated_at, updated_by }.
    // null until boot() fetches it, and null again if that fetch fails — in which case the matrix
    // renders READ-ONLY and says so, rather than drawing switches that would save nothing.
    let NAV_POLICY = null;
    function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
    function fmtDate(iso){ if(!iso) return "—"; const d=new Date(iso); return isNaN(d)?"—":d.toLocaleDateString(); }
    async function api(path, opts){ const r = await fetch(path, Object.assign({ headers: TW.authHeaders() }, opts||{})); return r.json().catch(()=>({ok:false,error:"bad response", status:r.status})); }
    // api() throws away the status, which is fine for the routes that answer {ok:false,error}. The
    // tab-policy route refuses with FastAPI's {detail:…} and a 400/403/500, and the reason it gives
    // ("you can't take that away from your own role") is the whole value of the refusal — so it needs
    // a call that keeps both.
    async function apiFull(path, opts){
      const r = await fetch(path, Object.assign({ headers: TW.authHeaders() }, opts||{}));
      const body = await r.json().catch(()=>({}));
      return { status: r.status, ok: r.ok, body: body||{} };
    }
    function errText(res){
      return (res.body && (res.body.detail || res.body.error)) || ("HTTP " + res.status);
    }

    async function boot(){
      await window.TWAuth.ready;
      ME = window.TWAuth.user() || {};
      const root = document.getElementById("root");
      if (ME.role !== "admin" && ME.role !== "super_admin") {
        root.innerHTML = '<div class="denied">Admin access only. Redirecting…</div>';
        setTimeout(()=>window.location.assign("/projects.html"), 1500); return;
      }
      // BEFORE shell(): the matrix is rendered by re-rendering the sidebar once per role, so the
      // policy has to be in TWAuth's hands before that happens or the first paint shows every
      // switch on and then corrects itself.
      await loadNavPolicy();
      shell();
      wireRoleMatrix();
      await refresh();
    }

    async function loadNavPolicy(){
      const res = await apiFull("/api/admin/nav-access");
      NAV_POLICY = res.ok && res.body && res.body.deny ? res.body : null;
      // Hand the whole map to auth.js so navMatrix() renders the sidebar for EVERY role under it.
      // /api/me only carried this viewer's own row, which is all an ordinary page needs.
      try { window.TWAuth.setNavDeny((NAV_POLICY && NAV_POLICY.deny) || {}); } catch (e) {}
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
    // the members and the superadmin?" — then, looking at the read-only table: "I cant toggle these
    // on and off?" Asked whether hiding the tab was enough or the page had to actually refuse, he
    // chose REAL BLOCKING. So the cells are switches now, and the server enforces what they say.
    //
    // THE ROWS ARE STILL NOT WRITTEN HERE. window.TWAuth.navMatrix(deny) builds the sidebar's nav
    // once per role out of the menu's own markup, UNDER THE STORED POLICY, and diffs the results —
    // so the ticks and the switches are one render rather than two opinions, and a hand-kept copy of
    // the tab list cannot drift from the menu. Every sentence under the table is computed from the
    // same rows for the same reason: a hardcoded "only the Admin tab differs" is a claim that rots.
    const ROLE_LABEL = { user:"Member", admin:"Admin", super_admin:"Super admin" };
    function roleLabelOf(r){ return ROLE_LABEL[r] || r; }

    // `policy` is optional, and that is deliberate: backend/tests/js/nav-visibility-harness.js lifts
    // this function out on its own to prove the table IS the menu, and with no policy it renders
    // exactly today's read-only panel. shell() calls it with no argument and it falls back to the
    // module's NAV_POLICY — the typeof guard is what lets the lifted copy run, where that variable
    // does not exist at all.
    function roleMatrixHtml(policy){
      const pol = policy || (typeof NAV_POLICY === "undefined" ? null : NAV_POLICY) || {};
      const deny = pol.deny || null;
      // ALWAYS A POLICY QUESTION, EVEN WHEN THERE IS NO POLICY. navMatrix appends the rows for tabs
      // that have no sidebar entry only when it is handed a deny map, so this hands it an empty one
      // when the fetch failed. Passing nothing dropped exactly the row that matters most on a
      // degraded page: the one tab that cannot be reached from the menu is the one whose only
      // visible switch is in this table, so a vanished row is a denial with nothing on screen to
      // undo it. What an empty map cannot say is whether those tabs are ON, which is what
      // policyKnown below is for.
      const nav = (window.TWAuth && window.TWAuth.navMatrix)
        ? window.TWAuth.navMatrix(deny || {}) : null;
      if (!nav || !nav.rows.length) {
        return `<div class="panel" id="rv-panel" style="margin-top:18px;"><div class="ph"><strong>What each role can see</strong></div>
          <p class="rv-note">The sidebar didn't report its tabs, so there is nothing to show here.
          Reload the page; if it persists, auth.js failed to load.</p></div>`;
      }
      const roles = nav.roles, rows = nav.rows, mine = ME.role || "user";
      // Did the stored policy actually arrive? Every row built by rendering the menu is true either
      // way. The rows for tabs with NO menu entry are read off the deny map instead, so with no map
      // their state is genuinely not known, and saying so is the only honest thing this page can do
      // with them: a cell that looks on for a tab that is in fact denied is the one error nobody
      // can catch from this screen.
      const policyKnown = !!deny;
      const rowless = rows.filter(r => r.noSidebar);
      const unknown = (r) => !!r.noSidebar && !policyKnown;
      // Counted over the rows this render can speak for, so the tally in the header and the
      // sentence under the table stay claims it backs. Under a loaded policy that is every row.
      const known = rows.filter(r => !unknown(r));
      const seen = (r) => roles.filter(x => r.roles[x]).length;
      const differing = known.filter(r => seen(r) !== roles.length);
      const count = {}; roles.forEach(x => { count[x] = known.filter(r => r.roles[x]).length; });

      // What each tab actually owns, from the server's capability table. Absent (the lifted copy, or
      // a failed policy fetch) means read-only: no switches, and the note says why.
      const caps = {}; (pol.tabs || []).forEach(t => { caps[t.href] = t; });
      const editable = !!(pol.tabs && pol.tabs.length);
      const lockedRoles = pol.locked_roles || [];
      const hideOnly = (pol.tabs || []).filter(t => !t.locked && !(t.api||[]).length);

      // Named rather than named-and-described: which page a rowless tab is opened from is not in
      // any of the data this table reads, and a sentence here saying where one lives would be a
      // second copy of that fact with nothing to keep it true.
      const NO_ROW_WHY = "This tab is governed here and is not drawn in the left menu. It is "
        + "opened from inside the app instead, and it can still be refused per role, so its switch "
        + "has to be somewhere an admin can find it.";
      const NOT_KNOWN_WHY = "Not known. This tab has no sidebar row to read, and the tab "
        + "permissions did not load. Reload the page.";
      // The header used to read "N sidebar tabs", which stopped being true the day a tab could be
      // governed without being drawn: the number counts ROWS, and one row is a tab with no menu
      // entry. So it counts tabs, and names the ones the menu does not carry rather than letting
      // the total quietly absorb them.
      const rowlessNote = !rowless.length ? "" :
        (' · <span title="Governed by this table, not drawn in the left menu.">' +
         rowless.map(r => esc(r.label)).join(", ") +
         (rowless.length === 1 ? " has" : " have") + " no sidebar row" +
         (policyKnown ? "" : ", and its state did not load") + "</span>");

      // Both helpers are LOCAL because nav-visibility-harness.js lifts this function out on its own
      // to prove the table is the menu; anything it reaches for from the file's top level would be a
      // ReferenceError in that run, and stubbing it there would be stubbing the thing under test.
      const shortDate = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleDateString(); };
      /** The chip beside a tab's name saying how much a switch there really does. */
      const scopeChip = (cap) => {
        if (!editable || !cap) return "";
        // "not deniable" rather than "always on": the Admin row's member cell is a dash, because a
        // member genuinely does not get that tab — the ROLE gate in the sidebar decides that, and
        // this policy is a separate thing that simply cannot reach either page.
        if (cap.locked) return `<span class="rv-lock" title="This policy cannot take this page away. It is where the setting is edited from, or where signing in lands — denying it would remove the way back.">not deniable</span>`;
        if (!(cap.api||[]).length) return `<span class="rv-thin" title="Every API route this page reads is read by another page too, so refusing them would break a page nobody restricted. Switching this tab off hides it and blocks the page; the data stays reachable to somebody who knows the URL.">hides the tab only</span>`;
        return `<span class="rv-hard" title="${esc((cap.api||[]).join(", "))}">blocks its data</span>`;
      };

      const head = roles.map(r =>
        `<th class="rv-h${r===mine?" rv-mine":""}">${esc(roleLabelOf(r))}` +
        `${r===mine?'<span class="you">you</span>':""}</th>`).join("");

      // ONE cell renderer for both modes, so the tick can never disagree with the switch beside it:
      // there is no switch beside it — the glyph is INSIDE the button.
      function cellHtml(r, role){
        // A governed tab with no menu row, on a page whose policy fetch failed. There is no render
        // behind this cell and no map to read, so it says so; a tick here would be the default-allow
        // of an empty map dressed up as a fact.
        if (unknown(r)) return `<td class="rv-cell" data-role="${esc(role)}"` +
          `><span class="rv-no" title="${esc(NOT_KNOWN_WHY)}">?</span></td>`;
        const on = !!r.roles[role];
        const glyph = on ? '<span class="rv-yes">✓</span>' : '<span class="rv-no">—</span>';
        const cap = caps[r.href];
        if (!editable) return `<td class="rv-cell" data-role="${esc(role)}">${glyph}</td>`;
        // Three reasons a switch cannot be touched, each with its own explanation on hover:
        //  * the page is locked outright — /admin.html is where this policy is edited and
        //    /portal.html is where signing in lands, so denying either removes the way back;
        //  * the role is locked — the super admin is bootstrapped from an env var and is the account
        //    that always has a way in;
        //  * it is YOUR role and it is currently on — the server refuses that too, because every
        //    self-lockout starts with somebody testing the toggle on themselves. Turning your own
        //    role's tab back ON stays allowed: widening can only give access back.
        let why = "";
        if (!cap || cap.locked) why = "Always on. This is the page this setting is edited from, or the page signing in lands on — denying it would remove the way back.";
        else if (lockedRoles.indexOf(role) !== -1) why = "A super admin cannot be restricted. That role is set from the server's environment, so it is the account that always has a way in.";
        else if (role === mine && on) why = "You can't take a tab away from your own role. Ask another admin, or change it for a different role.";
        const scope = cap && !(cap.api||[]).length
          ? "Switching this off hides the tab and blocks the page. Its data stays reachable to somebody who types the URL — every route its page reads is read by another page too."
          : (cap ? ("Switching this off also refuses " + (cap.api||[]).join(", ") + ", which only this tab uses.") : "");
        const title = why || ((on ? "Switch off for " : "Switch on for ") + roleLabelOf(role) + ". " + scope);
        return `<td class="rv-cell" data-role="${esc(role)}">` +
          `<button class="rv-sw${on?" rv-on":""}"${why?" disabled":""} data-act="nav"` +
          ` data-href="${esc(r.href)}" data-role="${esc(role)}" data-on="${on?"1":"0"}"` +
          ` aria-pressed="${on?"true":"false"}" title="${esc(title)}">${glyph}</button></td>`;
      }

      // The section is printed once per group rather than on all three of its rows: repeated
      // LEADS & BIDS down a column reads as three sections. The heading still belongs to the row
      // in the data, which is what the matrix is checked against.
      const body = rows.map((r, i) => `<tr data-href="${esc(r.href)}" data-label="${esc(r.label)}"
          data-section="${esc(r.section)}">
          <td class="rv-sec">${i && rows[i-1].section === r.section ? "" : esc(r.section)}</td>
          <td><span class="rv-ico">${esc(r.glyph)}</span>${esc(r.label)}${
            r.tag?`<span class="badge b-user" style="margin-left:6px">${esc(r.tag)}</span>`:""}
            <span class="rv-href">${esc(r.href)}</span>${scopeChip(caps[r.href])}${
              r.noSidebar?`<span class="badge b-user" style="margin-left:8px"
                title="${esc(NO_ROW_WHY)}">no sidebar row</span>`:""}</td>
          ${roles.map(x => cellHtml(r, x)).join("")}
        </tr>`).join("");

      return `<div class="panel" id="rv-panel" style="margin-top:18px;">
        <div class="ph"><strong>What each role can see</strong>
          <span style="color:var(--ink-v)">${rows.length} tabs · ${differing.length}
            ${differing.length===1?"differs":"differ"} by role${rowlessNote}</span>
          <span class="grow"></span>
          ${pol.updated_at?`<span class="rv-you">Last changed ${esc(shortDate(pol.updated_at))}${
            pol.updated_by?" by "+esc(pol.updated_by):""}</span>`:""}
          <span class="rv-you">Your role: <strong>${esc(roleLabelOf(mine))}</strong></span>
        </div>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>Section</th><th>Tab</th>${head}</tr></thead>
          <tbody>${body}</tbody>
        </table></div>
        <div class="rv-note" id="rv-note">
          <p>${roleDiffSentence({ roles: roles, rows: known }, count)}</p>
          ${editable ? "" : `<p><strong>Read-only right now.</strong> The tab permissions didn't
            load, so this is showing the menu as it stands with no switches. Reload the page.</p>`}
          ${rowless.length?`<p><strong>${rowless.length===1
            ?"One tab is governed here with no row in the left menu"
            :`${rowless.length} tabs are governed here with no row in the left menu`}:</strong>
            ${rowless.map(r=>`<strong>${esc(r.label)}</strong>`).join(", ")}. Reached from inside
            the app instead of from the menu, and still refusable per role, so the switch has to sit
            somewhere an admin can find it: a denial nobody can see is a denial nobody can lift.${
            policyKnown?"":` Those cells read a question mark because the permissions did not load,
            not because the tab is switched off.`}</p>`:""}
          <p><strong>A tab switched off is a real block, but the page is still served.</strong>
            There is no session cookie in this app — the only credential is a header the browser
            attaches to API calls — so a page is still reachable by typing its URL, and what it
            paints for a blocked role is a refusal card instead of its own content. What refuses the
            DATA is the server, on the tabs marked <em>blocks its data</em> below. The sidebar on its
            own is not a permission model, and never was: <code>_require_admin</code> guards every
            <code>/api/admin/*</code> route (this page's users and stats, admin project deletes, the
            digest run and preview), the Item Library's vendor / division / unit writes, and the
            notification-recipient writes, switches or no switches.</p>
          ${hideOnly.length?`<p><strong>${hideOnly.length} ${hideOnly.length===1?"tab":"tabs"} can
            only be hidden, not sealed:</strong> ${hideOnly.map(t=>`<strong>${esc(t.label)}</strong>`)
              .join(", ")}. Every API route their pages read is read by another page too — the
            Analytics payload is also the Bid Calendar's, the Item Library's assemblies also price
            the Polish beta, the pipeline feeds both Active Projects and Notification Sending — so
            refusing those routes would break a page nobody restricted. Switching one off removes
            the tab and blocks the page; somebody who knows the route can still read the data.</p>`:""}
          <p><strong>Auto Followups is the exception worth knowing about.</strong> Saving it is not
            admin-gated: any signed-in member may rewrite the four recurring customer emails, and
            the save replaces the settings row with no history. The sidebar and the server agree
            here — it is the permission itself that is broader than the ones above.</p>
          <p>Three tabs everybody can open still gate controls <em>inside</em> the page on role:
            <strong>Items and Assemblies</strong> (only an admin edits vendors, divisions and
            units; everyone may pick from them), <strong>Notification Sending</strong> (only an
            admin adds, removes or toggles anyone but themselves) and <strong>Active
            Projects</strong> (only an admin reassigns someone else's project).</p>
        </div></div>`;
    }

    function wireRoleMatrix(){
      document.querySelectorAll('#rv-panel [data-act="nav"]').forEach(el =>
        el.addEventListener("click", () =>
          toggleNav(el.dataset.href, el.dataset.role, el.dataset.on !== "1")));
    }

    function renderRoleMatrix(){
      const el = document.getElementById("rv-panel");
      if (!el) return;
      el.outerHTML = roleMatrixHtml();
      wireRoleMatrix();
    }

    /** Flip one tab for one role and save the WHOLE map, which is what the route takes. */
    async function toggleNav(href, role, on){
      const deny = {};
      Object.keys((NAV_POLICY && NAV_POLICY.deny) || {}).forEach(r => {
        deny[r] = ((NAV_POLICY.deny[r]) || []).slice();
      });
      const list = deny[role] || (deny[role] = []);
      const at = list.indexOf(href);
      if (on) { if (at !== -1) list.splice(at, 1); }        // ON = the denial comes off
      else if (at === -1) list.push(href);
      const res = await apiFull("/api/admin/nav-access",
        { method:"PUT", body: JSON.stringify({ deny: deny }) });
      if (!res.ok || !res.body.deny) {
        // The refusal's REASON is the point — "you can't take that away from your own role" is
        // actionable; "Action failed" sends somebody to the logs.
        alert(errText(res));
        return;
      }
      NAV_POLICY = res.body;
      try { window.TWAuth.setNavDeny(NAV_POLICY.deny || {}); } catch (e) {}
      renderRoleMatrix();
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
  
