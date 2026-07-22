// Externalized from index.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
  // Restore previous state if user clicked Back from screen 2
  const form = document.getElementById("intake-form");

  // ── Per-system Scope fields (fixed at two) ────────────────────────
  // The estimate sheet is a two-system model, so we always render exactly
  // two {Epoxy SF, Polish SF, Cove LF} groups. System 1 keeps the legacy
  // field names so the existing estimate-cell mappings keep working;
  // System 2 uses suffixed names and is optional (leave blank to skip it).
  const systemsContainer = document.getElementById("systems-container");

  function systemFieldNames(k) {
    return k === 1
      ? { epoxy: "system_1_sf", polish: "polish_sf",      cove: "cove_1_lf" }
      : { epoxy: `system_${k}_sf`, polish: `polish_${k}_sf`, cove: `cove_${k}_lf` };
  }

  function renderSystems(n) {
    n = Math.max(1, Math.min(6, parseInt(n, 10) || 1));
    // Preserve anything already typed before we rebuild the markup.
    const prev = {};
    systemsContainer.querySelectorAll("input[name]").forEach(i => { prev[i.name] = i.value; });
    let html = "";
    for (let k = 1; k <= n; k++) {
      const f = systemFieldNames(k);
      const label = k === 2 ? `System ${k} (optional)` : `System ${k}`;
      const tag = n > 1 ? `<div class="system-tag">${label}</div>` : "";
      html += `
        <div class="system-block">
          ${tag}
          <div class="row">
            <label>Epoxy floor SF
              <input type="number" name="${f.epoxy}" min="0" step="1" value="0">
            </label>
            <label>Polish floor SF
              <input type="number" name="${f.polish}" min="0" step="1" value="0">
            </label>
          </div>
          <div class="row">
            <label>Cove LF (epoxy)
              <input type="number" name="${f.cove}" min="0" step="1" value="0">
            </label>
          </div>
        </div>`;
    }
    systemsContainer.innerHTML = html;
    // Restore preserved values into the rebuilt fields.
    systemsContainer.querySelectorAll("input[name]").forEach(i => {
      if (prev[i.name] != null && prev[i.name] !== "") i.value = prev[i.name];
    });
  }

  // Always two systems (System 2 optional), then hydrate the whole form.
  renderSystems(2);
  TW.writeForm(form, TW.getState());

  // Gyp jobs use 3 SF buckets instead of the epoxy/polish system fields — show
  // the right scope inputs for the selected work type (and on a restored draft).
  const gypBox = document.getElementById("gyp-sf-container");
  function syncScopeToWorkType() {
    const wt = (form.querySelector("[name='work_type']:checked") || {}).value || "epoxy";
    const isGyp = wt === "gyp";
    if (gypBox) gypBox.style.display = isGyp ? "" : "none";
    if (systemsContainer) systemsContainer.style.display = isGyp ? "none" : "";
  }
  form.querySelectorAll("[name='work_type']").forEach(r => r.addEventListener("change", syncScopeToWorkType));
  syncScopeToWorkType();

  // Default the bid date to today so users don't have to think about it.
  const bidInput = form.querySelector("[name='bid_date']");
  if (bidInput && !bidInput.value) {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    bidInput.value = `${y}-${m}-${d}`;
  }

  // ── Address autocomplete (keyless — OpenStreetMap via Photon) ──────
  // Photon is a free public address database; we query it as the user
  // types and fill Address / City / State / Zip. No API key, nothing to
  // host, no scraping — just a fetch to a public endpoint.
  const addrInput   = document.getElementById("address-input");
  const addrResults = document.getElementById("address-results");
  const businessInput = document.getElementById("business-input");
  const businessResults = document.getElementById("business-results");
  const cityInput   = document.getElementById("city-input");
  const stateInput  = document.getElementById("state-input");
  const zipInput    = document.getElementById("zip-input");

  const STATE_ABBR = {Alabama:"AL",Alaska:"AK",Arizona:"AZ",Arkansas:"AR",California:"CA",
    Colorado:"CO",Connecticut:"CT",Delaware:"DE","District of Columbia":"DC",Florida:"FL",
    Georgia:"GA",Hawaii:"HI",Idaho:"ID",Illinois:"IL",Indiana:"IN",Iowa:"IA",Kansas:"KS",
    Kentucky:"KY",Louisiana:"LA",Maine:"ME",Maryland:"MD",Massachusetts:"MA",Michigan:"MI",
    Minnesota:"MN",Mississippi:"MS",Missouri:"MO",Montana:"MT",Nebraska:"NE",Nevada:"NV",
    "New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC",
    "North Dakota":"ND",Ohio:"OH",Oklahoma:"OK",Oregon:"OR",Pennsylvania:"PA","Rhode Island":"RI",
    "South Carolina":"SC","South Dakota":"SD",Tennessee:"TN",Texas:"TX",Utah:"UT",Vermont:"VT",
    Virginia:"VA",Washington:"WA","West Virginia":"WV",Wisconsin:"WI",Wyoming:"WY"};

  const fmtLine1 = p => [p.housenumber, p.street || p.name].filter(Boolean).join(" ") || p.name || "";

  function showAddrMsg(text) {
    addrResults.innerHTML = `<div class="addr-row addr-msg">${text}</div>`;
    addrResults.classList.add("open");
  }

  function renderAddr(features) {
    const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
    // Photon often returns several OSM objects for the same address — dedupe
    // on the displayed text so we don't show identical rows.
    const seen = new Set(), items = [];
    for (const f of features) {
      const p = f.properties;
      const l1 = fmtLine1(p);
      const l2 = [p.city || p.county, STATE_ABBR[p.state] || p.state, p.postcode].filter(Boolean).join(", ");
      if (!l1 && !l2) continue;
      const key = (l1 + "|" + l2).toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      items.push({ f, l1, l2 });
    }
    if (!items.length) { showAddrMsg("No matches — keep typing the address"); return; }
    addrResults.innerHTML = items.map((it, i) =>
      `<div class="addr-row" data-idx="${i}"><div class="addr-l1">${esc(it.l1)}</div><div class="addr-l2">${esc(it.l2)}</div></div>`
    ).join("");
    addrResults.classList.add("open");
    addrResults.querySelectorAll(".addr-row").forEach(row =>
      row.addEventListener("click", () => pickAddr(items[+row.dataset.idx].f)));
  }

  function pickAddr(f) {
    const p = f.properties;
    addrInput.value  = fmtLine1(p);
    cityInput.value  = p.city || p.county || "";
    stateInput.value = STATE_ABBR[p.state] || (p.state || "").slice(0, 2).toUpperCase();
    zipInput.value   = p.postcode || "";
    addrResults.classList.remove("open");
  }

  function fillLocation(p) {
    addrInput.value  = fmtLine1(p);
    cityInput.value  = p.city || p.county || "";
    stateInput.value = STATE_ABBR[p.state] || (p.state || "").slice(0, 2).toUpperCase();
    zipInput.value   = p.postcode || "";
  }

  function renderBusinesses(features) {
    const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
    const seen = new Set(), items = [];
    for (const f of features) {
      const p = f.properties || {};
      const name = (p.name || "").trim();
      const address = fmtLine1(p);
      const locality = [p.city || p.county, STATE_ABBR[p.state] || p.state, p.postcode].filter(Boolean).join(", ");
      if (!name || (!address && !locality)) continue;
      const key = (name + "|" + address + "|" + locality).toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      items.push({ f, name, address: [address, locality].filter(Boolean).join(", ") });
    }
    if (!items.length) {
      businessResults.innerHTML = '<div class="addr-row addr-msg">No business matches — enter the address manually</div>';
      businessResults.classList.add("open");
      return;
    }
    businessResults.innerHTML = items.map((it, i) =>
      `<div class="addr-row" data-idx="${i}"><div class="addr-l1">${esc(it.name)}</div><div class="addr-l2">${esc(it.address)}</div></div>`
    ).join("");
    businessResults.classList.add("open");
    businessResults.querySelectorAll(".addr-row").forEach(row => row.addEventListener("click", () => {
      // Keep the name Kyle entered (it can include a job description); this is
      // only a location lookup, not a replacement for the project name.
      fillLocation(items[+row.dataset.idx].f.properties || {});
      businessResults.classList.remove("open");
    }));
  }

  let addrTimer = null, addrSeq = 0;
  addrInput.addEventListener("input", () => {
    const q = addrInput.value.trim();
    if (addrTimer) clearTimeout(addrTimer);
    if (q.length < 4) { addrResults.classList.remove("open"); return; }
    addrTimer = setTimeout(async () => {
      const seq = ++addrSeq;
      try {
        // Bias toward the Kansas City metro (lat/lon); filter to US results.
        const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(q)}&limit=6&lang=en&lat=39.0997&lon=-94.5786`;
        const data = await (await fetch(url)).json();
        if (seq !== addrSeq) return;  // a newer keystroke already fired
        const feats = (data.features || []).filter(f => (f.properties.countrycode || "US") === "US");
        renderAddr(feats);
      } catch { addrResults.classList.remove("open"); }
    }, 300);  // debounce
  });
  let businessTimer = null, businessSeq = 0;
  if (businessInput && businessResults) businessInput.addEventListener("input", () => {
    const q = businessInput.value.trim();
    if (businessTimer) clearTimeout(businessTimer);
    if (q.length < 3) { businessResults.classList.remove("open"); return; }
    businessTimer = setTimeout(async () => {
      const seq = ++businessSeq;
      try {
        // Free OSM business/location search, biased toward the Kansas City metro.
        const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(q)}&limit=6&lang=en&lat=39.0997&lon=-94.5786`;
        const data = await (await fetch(url)).json();
        if (seq !== businessSeq) return;
        renderBusinesses((data.features || []).filter(f => (f.properties.countrycode || "US") === "US"));
      } catch { businessResults.classList.remove("open"); }
    }, 300);
  });
  document.addEventListener("click", e => {
    if (!addrInput.contains(e.target) && !addrResults.contains(e.target))
      addrResults.classList.remove("open");
    if (businessInput && businessResults && !businessInput.contains(e.target) && !businessResults.contains(e.target))
      businessResults.classList.remove("open");
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const values = TW.readForm(form);
    // Keep a combined "City, ST" so the estimate sheet (C3), proposal
    // ({{city_state}}) and tax lookup keep working unchanged. Zip is new
    // and stored separately.
    const cs = [values.city, (values.state || "").toUpperCase()].filter(Boolean).join(", ");
    // Non-gyp jobs clear the gyp SF buckets to "" (NOT delete — setState merges,
    // and "" is skipped by the estimate seeds + the .xlsx writer). Keeps a draft
    // toggled off Gyp from carrying stale gyp SFs into an epoxy/polish estimate.
    if ((values.work_type || "epoxy") !== "gyp") {
      values.gyp_soft_sf = ""; values.gyp_hard_sf = ""; values.gyp_corridor_sf = "";
    }
    // Bid date is now the single project date. Mirror it into `deadline` so the
    // Projects list, the notification bell's due-date reminders, and the Dropbox
    // folder date (all of which read `deadline`) keep tracking the bid date.
    // Fixed at two systems — the estimate sheet's model.
    TW.setState({
      ...values,
      city_state: cs,
      work_type: values.work_type || "epoxy",
      deadline: values.bid_date || values.deadline || "",
      num_systems: 2,
    });
    window.location.assign(TW.withDraft("/estimate-review.html"));
  });
