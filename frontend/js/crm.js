// Externalized (CSP: no inline scripts). Read-only Basisboard pipeline (CRM view).
// Reads the JWT-gated /api/basisboard/* proxy — the Basisboard key stays on the
// server, never in the browser. Mirrors the old Treadwell CRM kanban: columns =
// stages, cards = projects.
(function () {
  function money(n) { return (typeof n === "number") ? "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 }) : ""; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

  // Resolve as soon as auth.js sets the token (runs in parallel with the sidebar).
  function tokenSoon() {
    return new Promise(res => {
      const t0 = Date.now();
      (function poll() {
        if (window.__TW_TOKEN) return res(true);
        if (Date.now() - t0 > 8000) return res(false);   // unauth → auth.js redirects
        setTimeout(poll, 40);
      })();
    });
  }

  let ALL = [];        // projects
  let STAGES = [];     // ordered stage columns [{id,name,color,order}]
  let QUERY = "";
  const board = () => document.getElementById("board");

  function filtered() {
    const q = QUERY.trim().toLowerCase();
    if (!q) return ALL;
    return ALL.filter(p =>
      (p.name || "").toLowerCase().includes(q) ||
      (p.location || "").toLowerCase().includes(q) ||
      (p.estimators || []).join(" ").toLowerCase().includes(q));
  }

  function card(p) {
    const est = (p.estimators || []).join(", ");
    const won = p.awarded ? '<span class="deal-won" title="Awarded">✓</span>' : "";
    return '<div class="deal">' +
      '<p class="deal-title">' + esc(p.name) + won + '</p>' +
      (p.location ? '<p class="deal-sub">' + esc(p.location) + '</p>' : '') +
      '<div class="deal-foot">' +
        '<span class="deal-est">' + esc(est) + '</span>' +
        (typeof p.value === "number" ? '<span class="deal-val">' + money(p.value) + '</span>' : '') +
      '</div></div>';
  }

  function column(name, color, items) {
    const head = '<div class="col-head"><span class="col-title">' +
      '<span class="col-dot" style="background:' + esc(color || "#5c403f") + '"></span>' + esc(name) +
      '</span><span class="col-count">' + items.length + '</span></div>';
    const body = items.length
      ? '<div class="cards">' + items.map(card).join("") + '</div>'
      : '<div class="empty-col">No projects</div>';
    return '<div class="col">' + head + body + '</div>';
  }

  function paint() {
    const list = filtered();
    const byStage = {};
    list.forEach(p => { const k = p.stage_id || "_unstaged"; (byStage[k] = byStage[k] || []).push(p); });

    let html = "";
    STAGES.forEach(s => { html += column(s.name, s.color, byStage[s.id] || []); });
    // Any project whose stage isn't in the stage list gets its own trailing column.
    const known = {}; STAGES.forEach(s => { known[s.id] = true; });
    const leftover = list.filter(p => !known[p.stage_id]);
    if (leftover.length) html += column("Unstaged", "#5c403f", leftover);

    const b = board();
    if (!STAGES.length && !leftover.length) {
      b.className = "empty"; b.textContent = "No projects in Basisboard yet.";
      return;
    }
    b.className = "board"; b.innerHTML = html;
  }

  async function load() {
    await tokenSoon();
    const b = board();
    try {
      const st = await (await fetch("/api/basisboard/status", { headers: TW.authHeaders() })).json();
      if (!st || !st.configured) {
        b.className = "empty";
        b.textContent = "Basisboard isn't connected yet. (Add the API key to enable the pipeline.)";
        return;
      }
    } catch (err) {
      b.className = "empty"; b.textContent = "Couldn't reach the server. " + (err.message || "");
      return;
    }
    try {
      const j = await (await fetch("/api/basisboard/projects", { headers: TW.authHeaders() })).json();
      if (!j || j.ok === false) {
        b.className = "empty"; b.textContent = (j && j.error) || "Couldn't load Basisboard.";
        return;
      }
      ALL = Array.isArray(j.projects) ? j.projects : [];
      STAGES = Array.isArray(j.stages) ? j.stages : [];
      paint();
    } catch (err) {
      b.className = "empty"; b.textContent = "Couldn't load the pipeline. " + (err.message || "");
    }
  }

  const search = document.getElementById("search");
  if (search) search.addEventListener("input", e => { QUERY = e.target.value || ""; paint(); });

  load();
})();
