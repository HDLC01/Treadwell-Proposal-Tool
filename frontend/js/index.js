// Externalized from index.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
  // Restore previous state if user clicked Back from screen 2
  const form = document.getElementById("intake-form");

  // ── Dynamic per-system Scope fields ───────────────────────────────
  // "Number of systems" controls how many {Epoxy SF, Polish SF, Cove LF}
  // groups appear. System 1 keeps the legacy field names so the existing
  // estimate-cell mappings keep working; systems 2+ use suffixed names.
  const numSystemsInput  = document.getElementById("num-systems-input");
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
      const tag = n > 1 ? `<div class="system-tag">System ${k}</div>` : "";
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

  // Render from saved state (default 1 system), then hydrate the whole form.
  renderSystems(parseInt(TW.getState().num_systems, 10) || 1);
  TW.writeForm(form, TW.getState());
  if (numSystemsInput) {
    numSystemsInput.addEventListener("input", () => renderSystems(numSystemsInput.value));
  }

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
  document.addEventListener("click", e => {
    if (!addrInput.contains(e.target) && !addrResults.contains(e.target))
      addrResults.classList.remove("open");
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const values = TW.readForm(form);
    // Keep a combined "City, ST" so the estimate sheet (C3), proposal
    // ({{city_state}}) and tax lookup keep working unchanged. Zip is new
    // and stored separately.
    const cs = [values.city, (values.state || "").toUpperCase()].filter(Boolean).join(", ");
    TW.setState({ ...values, city_state: cs, work_type: values.work_type || "epoxy" });
    window.location.assign("/estimate-review.html");
  });
