// Lead Inbox — BasisBoard's unlinked messages, read through the JWT-gated
// /api/leads proxy (the BasisBoard key never reaches the browser). BasisBoard is
// READ-ONLY: qualifying, the AI score and the estimate drafted from a lead are
// all OUR state, merged onto the live message list server-side.
// Externalized (CSP: no inline scripts, no onclick).
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // BasisBoard scrapes best-effort, so any given message is missing half its
  // fields. One placeholder everywhere beats eight kinds of blank cell.
  const dash = (v) => { const s = String(v == null ? "" : v).trim(); return s || "—"; };
  const join = (sep, parts) => parts.map((p) => String(p == null ? "" : p).trim()).filter(Boolean).join(sep);
  // The AI's reasoning map is free-form JSON, so a value can arrive as a list or
  // a nested object; render those rather than "[object Object]".
  const flat = (v) => Array.isArray(v) ? v.join(", ")
    : (v && typeof v === "object" ? JSON.stringify(v) : String(v == null ? "" : v));
  const date = (iso) => (iso ? TW.fmtBizDate(iso) : "—");
  const stamp = (iso) => (iso ? TW.fmtBizDateTime(iso) : "—");

  // MERGE headers through TW.authHeaders — a caller passing its own `headers`
  // must not replace the bearer token (portal.js shipped exactly that 401 once).
  function api(path, opts) {
    opts = opts || {};
    return fetch(TW.resolveApiBase() + path, Object.assign({}, opts, { headers: TW.authHeaders(opts.headers) }));
  }
  async function readJSON(r) { try { return await r.json(); } catch { return {}; } }
  const errText = (r, j) => (j && (j.error || j.detail)) || ("HTTP " + r.status);

  // Resolve as soon as auth.js sets the token, so the list fetch runs in parallel
  // with the sidebar's own handshake instead of queueing behind it.
  function tokenSoon() {
    return new Promise((res) => {
      const t0 = Date.now();
      (function poll() {
        if (window.__TW_TOKEN) return res(true);
        if (Date.now() - t0 > 8000) return res(false);   // unauth → auth.js redirects
        setTimeout(poll, 40);
      })();
    });
  }

  const TYPE_LABEL = { bid_invite: "Bid invite", addendum: "Addendum", memos: "Memo",
    platform_update: "Update", response: "Reply" };
  const TYPE_CLASS = { bid_invite: "t-bid", response: "t-reply" };
  const PLATFORM_LABEL = { building_connected: "Building Connected", unknown: "Unknown" };
  const STATUS_LABEL = { new: "New", qualified: "Qualified", passed: "Passed",
    estimate_created: "Estimate drafted", trash: "Trash" };
  const REC_LABEL = { pursue: "Pursue", review: "Worth a look", pass: "Pass" };

  const LIVE = (r) => r.lead_status !== "trash";
  const VIEWS = [
    { key: "new", label: "New projects",
      test: (r) => r.communication_type === "bid_invite" && !r.is_spam && LIVE(r) },
    { key: "updates", label: "Updates & addenda",
      test: (r) => ["addendum", "memos", "platform_update"].includes(r.communication_type) && LIVE(r) },
    { key: "replies", label: "Replies",
      test: (r) => r.communication_type === "response" && LIVE(r) },
    { key: "all", label: "All", test: LIVE },
    { key: "trash", label: "Trash", test: (r) => r.lead_status === "trash" || r.is_spam },
  ];

  const CACHE_KEY = "tw_leads_cache";
  const VIEW_KEY = "tw_leads_view";
  const QUERY_KEY = "tw_leads_q";
  const ss = (k, d) => { try { const v = sessionStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
  const ssSet = (k, v) => { try { sessionStorage.setItem(k, v); } catch { /* private mode */ } };
  const readCache = () => { try { return JSON.parse(sessionStorage.getItem(CACHE_KEY) || "null"); } catch { return null; } };
  const writeCache = () => { try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ leads: ALL })); } catch { /* quota */ } };

  let ALL = [];
  let VIEW = VIEWS.some((v) => v.key === ss(VIEW_KEY, "")) ? ss(VIEW_KEY, "new") : "new";
  let QUERY = ss(QUERY_KEY, "");
  let CUR = null;          // id of the lead the drawer is showing
  let GEN = 0;             // bumped per open; async writes check it before touching the DOM
  const BODY = {};         // id → {state,text,error} — survives a drawer re-render
  const AI_FULL = {};      // id → the full prequal result (reasoning map included)
  const REASON_OPEN = {};  // id → is the reasoning disclosure expanded

  const byId = (id) => ALL.find((x) => x.id === id);

  // ── list ───────────────────────────────────────────────────────────────────
  function inView() {
    const v = VIEWS.find((x) => x.key === VIEW) || VIEWS[0];
    return ALL.filter(v.test);
  }
  function matches(r, tokens) {
    const hay = join(" ", [r.subject, r.project_name, r.company, r.city, r.address_line,
      r.location, r.region, r.from_email]).toLowerCase();
    return tokens.every((t) => hay.includes(t));
  }
  function shownRows() {
    const tokens = QUERY.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const list = inView();
    return tokens.length ? list.filter((r) => matches(r, tokens)) : list;
  }

  function scoreChip(r) {
    if (!r.has_ai) return "";
    const rec = String(r.ai_recommendation || "review");
    const cls = ["pursue", "review", "pass"].includes(rec) ? rec : "review";
    const score = (r.ai_score == null || r.ai_score === "") ? "—" : r.ai_score;
    return '<span class="score rec-' + cls + '" title="' + esc("AI fit " + score + " of 100 · " + (REC_LABEL[rec] || rec)) +
      '">AI ' + esc(score) + '</span>';
  }
  function statusBadge(r) {
    const s = String(r.lead_status || "new");
    const ok = (s === "qualified" || s === "estimate_created") ? " s-ok" : "";
    return '<span class="badge' + ok + '">' + esc(STATUS_LABEL[s] || s) + '</span>';
  }
  function typeBadge(r) {
    const t = String(r.communication_type || "");
    const cls = TYPE_CLASS[t] ? " " + TYPE_CLASS[t] : "";
    return '<span class="badge' + cls + '">' + esc(TYPE_LABEL[t] || t || "—") + '</span>';
  }

  function rowHTML(r) {
    const rel = Number(r.duplicate_count) > 0
      ? '<span class="rel" title="BasisBoard grouped related messages onto this one">+' + esc(r.duplicate_count) + ' related</span>' : "";
    const title = r.project_name || r.subject || "(no subject)";
    const second = (r.project_name && r.subject && r.project_name !== r.subject) ? r.subject : r.from_email;
    return '<tr data-id="' + esc(r.id) + '" tabindex="0">' +
      '<td><span class="subj">' + esc(title) + rel + '</span>' +
        (second ? '<span class="subj-sub">' + esc(second) + '</span>' : '') + '</td>' +
      '<td>' + esc(dash(r.company)) + '</td>' +
      '<td>' + esc(join(" · ", [r.address_line, r.city]) || dash(r.location)) + '</td>' +
      '<td class="nowrap">' + esc(date(r.bid_deadline_at)) + '</td>' +
      '<td class="nowrap muted">' + esc(join(" · ", [r.distance, r.travel_time]) || "—") + '</td>' +
      '<td>' + typeBadge(r) + '</td>' +
      '<td class="nowrap muted">' + esc(stamp(r.created_at)) + '</td>' +
      '<td class="nowrap">' + statusBadge(r) + " " + scoreChip(r) + '</td>' +
      '</tr>';
  }

  function emptyRow(text) {
    return '<tr><td class="cell-empty" colspan="8">' + esc(text) + '</td></tr>';
  }

  function paintChips() {
    $("views").innerHTML = VIEWS.map((v) =>
      '<button type="button" class="chip' + (v.key === VIEW ? " sel" : "") + '" data-view="' + v.key + '"' +
      ' aria-pressed="' + (v.key === VIEW ? "true" : "false") + '">' + esc(v.label) +
      '<span class="n">' + ALL.filter(v.test).length + '</span></button>').join("");
  }

  // Same guard as the Bid Pipeline board, for the same reason: `load()` paints once
  // from the cache and again when the fetch lands, and `paint()` replaces the list's
  // innerHTML wholesale — so an unchanged refresh blinked the whole queue and threw
  // away your scroll position. VIEW and QUERY are in the signature because they change
  // what is rendered, so switching tab or typing still repaints immediately.
  let LAST_SIG = "";

  function paint() {
    const sig = JSON.stringify([ALL, VIEW, QUERY]);
    if (sig === LAST_SIG) return;
    LAST_SIG = sig;

    paintChips();
    const list = shownRows();
    const total = inView().length;
    $("count").textContent = ALL.length
      ? (list.length + (list.length === total ? "" : " of " + total) + " shown · " +
         ALL.length + " message" + (ALL.length === 1 ? "" : "s") + " from BasisBoard")
      : "";
    $("lead-rows").innerHTML = list.length
      ? list.map(rowHTML).join("")
      : emptyRow(ALL.length ? "Nothing in this view." : "No lead email from BasisBoard yet.");
  }

  function showAlert(text) {
    const el = $("alert");
    el.textContent = text || "";
    el.hidden = !text;
  }

  function applyData(j) {
    ALL = Array.isArray(j.leads) ? j.leads : [];
    paint();
  }

  async function load() {
    // Stale-while-revalidate: paint the last view instantly, then revalidate. A
    // failed refresh leaves the cached rows on screen — the list is a work queue,
    // and blanking it on a blip is worse than showing something a minute old.
    const cached = readCache();
    const hadCache = cached && Array.isArray(cached.leads) && cached.leads.length > 0;
    if (hadCache) applyData(cached);

    await tokenSoon();
    let r, j;
    try {
      r = await api("/api/leads");
      j = await readJSON(r);
    } catch (err) {
      if (hadCache) showAlert("Couldn't refresh — showing the last loaded list. " + (err.message || ""));
      else $("lead-rows").innerHTML = emptyRow("Couldn't reach the server. " + (err.message || ""));
      return;
    }
    if (j && j.configured === false) {
      $("lead-rows").innerHTML = emptyRow(
        "Lead inbox isn't connected. Add the BasisBoard API key on the server (BASISBOARD_API_KEY) to pull the email list in.");
      showAlert("");
      return;
    }
    if (!r.ok || !j || j.ok === false) {
      const msg = errText(r, j);
      if (hadCache) showAlert("Couldn't refresh — showing the last loaded list. " + msg);
      else $("lead-rows").innerHTML = emptyRow("Couldn't load the lead inbox. " + msg);
      return;
    }
    showAlert("");
    applyData(j);
    writeCache();
  }

  // ── drawer ─────────────────────────────────────────────────────────────────
  function closeDrawer() {
    $("drawer").classList.remove("open");
    $("scrim").style.display = "none";
    CUR = null;
  }

  function field(k, v) {
    return '<div class="f"><div class="k">' + esc(k) + '</div><div class="v">' + esc(dash(v)) + '</div></div>';
  }

  function fieldsSec(r) {
    return '<div class="sec"><div class="lbl">Scraped by BasisBoard</div><div class="fgrid">' +
      field("Company", r.company) +
      field("From", r.from_email) +
      field("Location", join(" · ", [r.address_line, r.city, r.region]) || r.location) +
      field("Bid deadline", date(r.bid_deadline_at)) +
      field("Distance · travel", join(" · ", [r.distance, r.travel_time])) +
      field("Platform", PLATFORM_LABEL[r.platform] || r.platform) +
      field("Type", TYPE_LABEL[r.communication_type] || r.communication_type) +
      field("Received", stamp(r.created_at)) +
      '</div></div>';
  }

  function statusSec(r) {
    const cur = String(r.lead_status || "new");
    const b = (status, label) =>
      '<button type="button" class="btn btn-s' + (cur === status ? " on" : "") + '"' +
      ' data-act="status" data-status="' + status + '" aria-pressed="' + (cur === status ? "true" : "false") + '">' +
      esc(label) + '</button>';
    const reset = cur === "new" ? "" : b("new", "Reset to new");
    return '<div class="sec"><div class="lbl">Your call</div>' +
      '<div class="row3">' + b("qualified", "Qualify") + b("passed", "Pass") + b("trash", "Trash") + reset + '</div>' +
      '<p class="note" id="status-note">Currently <b>' + esc(STATUS_LABEL[cur] || cur) + '</b>' +
      (r.is_spam ? " · BasisBoard flagged this as spam" : "") + '.</p></div>';
  }

  function reasonHTML(ai) {
    const facts = [
      ["Work type", ai.work_type_guess],
      ["Audience", ai.audience_guess],
      ["Deadline", ai.deadline_days == null ? "" : ai.deadline_days + " days out" +
        (ai.deadline_feasible === false ? " · tight" : "")],
      ["Flooring scope", ai.flooring_scope_present == null ? "" : (ai.flooring_scope_present ? "Yes" : "No")],
      ["Signals", Array.isArray(ai.scope_signals) ? ai.scope_signals.join(", ") : ai.scope_signals],
    ].filter((p) => String(p[1] == null ? "" : p[1]).trim());
    const why = ai.reasoning && typeof ai.reasoning === "object" ? ai.reasoning : {};
    const rows = facts.map((p) => '<li><span class="k">' + esc(p[0]) + '</span>' + esc(flat(p[1])) + '</li>')
      .concat(Object.keys(why).map((k) =>
        '<li><span class="k">' + esc(k.replace(/_/g, " ")) + '</span>' + esc(flat(why[k])) + '</li>'));
    return rows.length ? '<ul class="kvs">' + rows.join("") + '</ul>'
      : '<p class="note">No reasoning was recorded for this score.</p>';
  }

  function aiSec(r) {
    let inner;
    if (r.has_ai) {
      const rec = String(r.ai_recommendation || "review");
      const cls = ["pursue", "review", "pass"].includes(rec) ? rec : "review";
      const open = !!REASON_OPEN[r.id];
      inner = '<div class="card ai">' +
        '<div class="aihead"><span class="big">' + esc(r.ai_score == null ? "—" : r.ai_score) + '</span>' +
        '<span class="of100">/ 100</span>' +
        '<span class="score rec-' + cls + '">' + esc(REC_LABEL[rec] || rec) + '</span>' +
        (r.category ? '<span class="badge">' + esc(r.category) + '</span>' : '') + '</div>' +
        (r.ai_summary ? '<p class="note">' + esc(r.ai_summary) + '</p>' : '') +
        '<div class="row3" style="margin-top:10px">' +
        '<button type="button" class="btn btn-s btn-xs" data-act="reason">' +
        (open ? "Hide reasoning" : "Show reasoning") + '</button>' +
        '<button type="button" class="btn btn-s btn-xs" data-act="prequalify" data-force="1">Re-run</button></div>' +
        '<div id="ai-reason"' + (open ? "" : " hidden") + '>' +
        (open && AI_FULL[r.id] ? reasonHTML(AI_FULL[r.id]) : "") + '</div></div>';
    } else {
      inner = '<button type="button" class="btn btn-p" data-act="prequalify">Prequalify with AI</button>' +
        '<p class="note">Reads the email and scores fit, work type and deadline. Takes about half a minute.</p>';
    }
    return '<div class="sec"><div class="lbl">AI prequalification</div>' + inner +
      '<p class="note warn" id="ai-alert"></p></div>';
  }

  function bodyHTML(st) {
    if (!st || st.state === "loading") return '<p class="note">Loading the email…</p>';
    if (st.state === "error") {
      return '<p class="note warn">Couldn\'t load the email. ' + esc(st.error || "") + '</p>' +
        '<button type="button" class="btn btn-s btn-xs" data-act="retry-body">Try again</button>';
    }
    return st.text ? '<pre class="email">' + esc(st.text) + '</pre>'
      : '<p class="note">The email had no readable text.</p>';
  }

  function bodySec(r) {
    return '<div class="sec"><div class="lbl">Email</div>' +
      '<div id="email-slot">' + bodyHTML(BODY[r.id]) + '</div></div>';
  }

  function groupedSec(r) {
    const g = Array.isArray(r.grouped) ? r.grouped : [];
    if (!g.length) return "";
    return '<div class="sec"><div class="lbl">Related messages (' + g.length + ')</div><ul class="kvs">' +
      g.map((m) => '<li><span class="k">' + esc(stamp(m.created_at)) + '</span>' +
        esc(m.subject || "(no subject)") + '</li>').join("") + '</ul></div>';
  }

  function actionSec(r) {
    if (r.draft_id) {
      const href = "/?d=" + encodeURIComponent(r.draft_id) + "&edit=1";
      return '<div class="sec"><div class="lbl">Estimate</div><div class="row3">' +
        '<a class="btn btn-p" href="' + esc(href) + '">Open estimate</a>' +
        (r.lead_auto ? '<span class="auto">Drafted automatically</span>' : '') + '</div>' +
        (r.lead_auto
          ? '<p class="note">The AI scored this lead a strong fit and drafted the estimate on its own — nobody has reviewed it yet. Check every number before it goes out.</p>'
          : '') + '</div>';
    }
    return '<div class="sec"><div class="lbl">Estimate</div>' +
      '<button type="button" class="btn btn-p" data-act="create">Create an estimate</button>' +
      '<p class="note">Prefills intake from what BasisBoard scraped plus the email text, then opens the project. Can take a minute and a half while the AI reads the email.</p>' +
      '<p class="note warn" id="create-alert"></p></div>';
  }

  function drawerHTML(r) {
    const title = r.project_name || r.subject || "Lead";
    const sub = (r.project_name && r.subject && r.project_name !== r.subject) ? r.subject : r.company;
    return '<div class="dhead"><div><h2>' + esc(title) + '</h2>' +
      (sub ? '<p class="dsub">' + esc(sub) + '</p>' : '') + '</div>' +
      '<button type="button" class="dclose" data-act="close" title="Close" aria-label="Close">&times;</button></div>' +
      '<div class="dbody">' + fieldsSec(r) + statusSec(r) + aiSec(r) + bodySec(r) + groupedSec(r) + actionSec(r) + '</div>';
  }

  function renderDrawer(r) { $("drawer").innerHTML = drawerHTML(r); }

  function openLead(id) {
    const r = byId(id);
    if (!r) return;
    CUR = id;
    const gen = ++GEN;
    $("scrim").style.display = "block";
    $("drawer").classList.add("open");
    $("drawer").scrollTop = 0;
    renderDrawer(r);
    // Cached text re-renders instantly; only a lead we haven't opened this
    // session costs a round-trip (and the signed .eml URL it hides behind).
    if (!BODY[id] || BODY[id].state !== "ok") loadBody(id, gen);
  }

  async function loadBody(id, gen) {
    BODY[id] = { state: "loading" };
    paintBody(id, gen);
    try {
      const r = await api("/api/leads/" + encodeURIComponent(id) + "/body");
      const j = await readJSON(r);
      if (!r.ok || j.ok === false) throw new Error(errText(r, j));
      BODY[id] = { state: "ok", text: String(j.text || "") };
    } catch (err) {
      // Non-fatal: everything else in the drawer still works without the body.
      BODY[id] = { state: "error", error: err.message || "" };
    }
    paintBody(id, gen);
  }
  function paintBody(id, gen) {
    if (CUR !== id || gen !== GEN) return;   // drawer moved on — don't write into it
    const slot = $("email-slot");
    if (slot) slot.innerHTML = bodyHTML(BODY[id]);
  }

  // A button that owns a slow call: disabled, with the seconds ticking up so a
  // 30-90s AI leg reads as progress rather than a hung page.
  function working(btn, label) {
    const orig = btn.textContent;
    const t0 = Date.now();
    btn.disabled = true;
    const tick = () => { btn.textContent = label + " " + Math.round((Date.now() - t0) / 1000) + "s"; };
    tick();
    const iv = setInterval(tick, 1000);
    return function stop(text) {
      clearInterval(iv);
      btn.disabled = false;
      btn.textContent = text || orig;
    };
  }

  function alertInto(id, text) { const el = $(id); if (el) el.textContent = text || ""; }

  // Patch the row we already hold and repaint, rather than re-fetching the whole
  // inbox: /api/leads goes back out to BasisBoard behind a 60s cache, so a reload
  // after every click would show stale state anyway. Split in two because a
  // caller mid-flow (create-estimate) still needs its own alert node on screen.
  function patchRow(id, fields) {
    const r = byId(id);
    if (!r) return null;
    Object.assign(r, fields);
    writeCache();
    paint();
    return r;
  }
  function updateRow(id, fields) {
    const r = patchRow(id, fields);
    if (r && CUR === id) renderDrawer(r);
    return r;
  }

  async function setStatus(r, status, btn) {
    const stop = working(btn, "Saving");
    try {
      const res = await api("/api/leads/" + encodeURIComponent(r.id) + "/status",
        { method: "POST", body: JSON.stringify({ lead_status: status }) });
      const j = await readJSON(res);
      if (!res.ok || j.ok === false) throw new Error(errText(res, j));
      stop();
      updateRow(r.id, { lead_status: status });
    } catch (err) {
      stop("Failed — retry");
      alertInto("status-note", "Couldn't save that. " + (err.message || ""));
    }
  }

  async function prequalify(r, btn, force) {
    alertInto("ai-alert", "");
    const stop = working(btn, force ? "Re-reading" : "Reading the email");
    try {
      const res = await api("/api/leads/" + encodeURIComponent(r.id) + "/prequalify" + (force ? "?force=1" : ""),
        { method: "POST" });
      const j = await readJSON(res);
      // 429 carries the server's own wording (how many runs, how long to wait) —
      // pass it straight through instead of inventing a second vocabulary.
      if (!res.ok || j.ok === false) throw new Error(errText(res, j));
      const ai = j.ai || {};
      AI_FULL[r.id] = ai;
      REASON_OPEN[r.id] = true;
      stop();
      updateRow(r.id, {
        has_ai: true,
        ai_score: ai.fit_score,
        ai_recommendation: ai.recommendation,
        ai_summary: ai.summary,
        category: r.category || ai.work_type_guess || null,
      });
    } catch (err) {
      stop();
      alertInto("ai-alert", err.message || "The AI couldn't score this lead.");
    }
  }

  async function toggleReason(r, btn) {
    const slot = $("ai-reason");
    if (!slot) return;
    if (!slot.hidden) {
      slot.hidden = true; REASON_OPEN[r.id] = false; btn.textContent = "Show reasoning";
      return;
    }
    slot.hidden = false; REASON_OPEN[r.id] = true; btn.textContent = "Hide reasoning";
    if (AI_FULL[r.id]) { slot.innerHTML = reasonHTML(AI_FULL[r.id]); return; }
    // The list row carries only score/recommendation/summary. The full reasoning
    // map comes from the prequalify endpoint's CACHED read — has_ai means the
    // server already stored a result, so expanding this never spends an AI run.
    slot.innerHTML = '<p class="note">Loading the reasoning…</p>';
    try {
      const res = await api("/api/leads/" + encodeURIComponent(r.id) + "/prequalify", { method: "POST" });
      const j = await readJSON(res);
      if (!res.ok || j.ok === false) throw new Error(errText(res, j));
      AI_FULL[r.id] = j.ai || {};
      const s = $("ai-reason");
      if (s && CUR === r.id) s.innerHTML = reasonHTML(AI_FULL[r.id]);
    } catch (err) {
      const s = $("ai-reason");
      if (s && CUR === r.id) s.innerHTML = '<p class="note warn">Couldn\'t load the reasoning. ' + esc(err.message || "") + '</p>';
    }
  }

  async function createEstimate(r, btn) {
    alertInto("create-alert", "");
    // No client-side timeout: the AI leg alone is allowed 60s server-side, so
    // aborting early would strand a draft the server went on to create.
    const stop = working(btn, "Building the estimate");
    let j;
    try {
      const res = await api("/api/leads/" + encodeURIComponent(r.id) + "/create-estimate", { method: "POST" });
      j = await readJSON(res);
      if (!res.ok || j.ok === false || !j.draft_id) throw new Error(errText(res, j));
    } catch (err) {
      stop();
      alertInto("create-alert", "Couldn't create the estimate. " + (err.message || ""));
      return;
    }
    const href = "/?d=" + encodeURIComponent(j.draft_id) + "&edit=1";
    if (j.ai_used === false) {
      // Still a usable draft — just thinner than usual. Say so, then go anyway.
      // Patch the LIST only: re-rendering the drawer here would swap out the very
      // node this warning is written into.
      stop("Opening the project…");
      btn.disabled = true;
      patchRow(r.id, { lead_status: "estimate_created", draft_id: j.draft_id });
      alertInto("create-alert", j.warning || "Prefilled from the scraped fields only — the AI couldn't read the email.");
      setTimeout(() => location.assign(href), 2200);
      return;
    }
    stop();
    updateRow(r.id, { lead_status: "estimate_created", draft_id: j.draft_id });
    location.assign(href);
  }

  // ── wiring ─────────────────────────────────────────────────────────────────
  // Delegated on the persistent #drawer node: renderDrawer replaces its innerHTML
  // after every action, so a per-button listener would die on the first save.
  $("drawer").addEventListener("click", (e) => {
    const el = e.target.closest("[data-act]");
    if (!el || !CUR) return;
    if (el.dataset.act === "close") return closeDrawer();
    const r = byId(CUR);
    if (!r) return;
    switch (el.dataset.act) {
      case "status": setStatus(r, el.dataset.status, el); break;
      case "prequalify": prequalify(r, el, el.dataset.force === "1"); break;
      case "reason": toggleReason(r, el); break;
      case "retry-body": loadBody(r.id, GEN); break;
      case "create": createEstimate(r, el); break;
    }
  });

  $("lead-rows").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (tr) openLead(tr.dataset.id);
  });
  $("lead-rows").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const tr = e.target.closest && e.target.closest("tr[data-id]");
    if (tr) { e.preventDefault(); openLead(tr.dataset.id); }
  });

  $("views").addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    VIEW = b.dataset.view;
    ssSet(VIEW_KEY, VIEW);
    paint();
  });

  const search = $("search");
  search.value = QUERY;
  search.addEventListener("input", () => { QUERY = search.value; ssSet(QUERY_KEY, QUERY); paint(); });
  search.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { search.value = ""; QUERY = ""; ssSet(QUERY_KEY, ""); paint(); }
  });

  $("scrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && CUR) closeDrawer(); });

  load();
  // New bid invites arrive without anyone reloading. 60s matches the server-side
  // cache in front of /api/leads, so a tighter interval would return identical
  // bytes. Skipped while a tab is hidden or a drawer is open (a repaint mid-triage
  // would move the row out from under the rep).
  setInterval(() => { if (!document.hidden && !CUR) load(); }, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !CUR) load(); });
})();
