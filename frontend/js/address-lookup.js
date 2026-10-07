/* The address / business-location lookup, once, for every intake page.
 *
 * MOVED OUT OF js/index.js (2026-10-05) so the beta polish intake can carry the same lookup as the
 * live form without a second copy. The behaviour is the live form's, unchanged: as the estimator
 * types, a free public OSM database (Photon) is queried and the picked row fills Address, City,
 * State and Zip. No API key, nothing hosted by us.
 *
 *   TWAddress.mount({ address, business, city, state, zip })
 *
 * Each value is an element (or null for the optional `business`). The two dropdowns are looked up
 * by the ids the markup has always used: #address-results and #business-results.
 *
 * ONE DIFFERENCE FROM THE OLD INLINE VERSION, AND IT IS FOR THE BETA: a picked row now fires an
 * `input` event on City, State and Zip. The beta intake saves on `input` (it autosaves as you
 * type, js/polish-intake.js); a programmatic .value write fires nothing, so a picked address
 * would have sat in the boxes unsaved until the next keystroke. The event bubbles to the form, the
 * form's save reads every named field, and Address rides along with them. It is deliberately NOT
 * fired on Address or Project name: those two inputs own the lookup's own `input` listener, and
 * firing there would re-open the dropdown the pick just closed. On the live form nothing listens
 * for `input` on City, State or Zip, so Active behaves exactly as before.
 */
(function () {
  "use strict";

  var STATE_ABBR = {Alabama:"AL",Alaska:"AK",Arizona:"AZ",Arkansas:"AR",California:"CA",
    Colorado:"CO",Connecticut:"CT",Delaware:"DE","District of Columbia":"DC",Florida:"FL",
    Georgia:"GA",Hawaii:"HI",Idaho:"ID",Illinois:"IL",Indiana:"IN",Iowa:"IA",Kansas:"KS",
    Kentucky:"KY",Louisiana:"LA",Maine:"ME",Maryland:"MD",Massachusetts:"MA",Michigan:"MI",
    Minnesota:"MN",Mississippi:"MS",Missouri:"MO",Montana:"MT",Nebraska:"NE",Nevada:"NV",
    "New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC",
    "North Dakota":"ND",Ohio:"OH",Oklahoma:"OK",Oregon:"OR",Pennsylvania:"PA","Rhode Island":"RI",
    "South Carolina":"SC","South Dakota":"SD",Tennessee:"TN",Texas:"TX",Utah:"UT",Vermont:"VT",
    Virginia:"VA",Washington:"WA","West Virginia":"WV",Wisconsin:"WI",Wyoming:"WY"};

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c];
    });
  }

  function fmtLine1(p) {
    return [p.housenumber, p.street || p.name].filter(Boolean).join(" ") || p.name || "";
  }

  function stateOf(p) {
    return STATE_ABBR[p.state] || (p.state || "").slice(0, 2).toUpperCase();
  }

  function localityOf(p) {
    return [p.city || p.county, STATE_ABBR[p.state] || p.state, p.postcode].filter(Boolean).join(", ");
  }

  /** Photon often returns several OSM objects for the same address, so dedupe on the displayed
   *  text. Pure: features in, rows out. Exported for the harness. */
  function addressRows(features) {
    var seen = {}, items = [];
    (features || []).forEach(function (f) {
      var p = f.properties || {};
      var l1 = fmtLine1(p);
      var l2 = localityOf(p);
      if (!l1 && !l2) return;
      var key = (l1 + "|" + l2).toLowerCase();
      if (seen[key]) return;
      seen[key] = true;
      items.push({ f: f, l1: l1, l2: l2 });
    });
    return items;
  }

  function businessRows(features) {
    var seen = {}, items = [];
    (features || []).forEach(function (f) {
      var p = f.properties || {};
      var name = (p.name || "").trim();
      var address = fmtLine1(p);
      var locality = localityOf(p);
      if (!name || (!address && !locality)) return;
      var key = (name + "|" + address + "|" + locality).toLowerCase();
      if (seen[key]) return;
      seen[key] = true;
      items.push({ f: f, name: name, address: [address, locality].filter(Boolean).join(", ") });
    });
    return items;
  }

  function mount(els) {
    els = els || {};
    var addrInput = els.address, addrResults = document.getElementById("address-results");
    var businessInput = els.business || null;
    var businessResults = document.getElementById("business-results");
    var cityInput = els.city, stateInput = els.state, zipInput = els.zip;
    if (!addrInput || !addrResults) return;

    function ping(el) {
      if (el) el.dispatchEvent(new Event("input", { bubbles: true }));
    }

    function showAddrMsg(text) {
      addrResults.innerHTML = '<div class="addr-row addr-msg">' + text + "</div>";
      addrResults.classList.add("open");
    }

    function fillLocation(p) {
      addrInput.value  = fmtLine1(p);
      cityInput.value  = p.city || p.county || "";
      stateInput.value = stateOf(p);
      zipInput.value   = p.postcode || "";
      ping(cityInput); ping(stateInput); ping(zipInput);
    }

    function renderAddr(features) {
      var items = addressRows(features);
      if (!items.length) { showAddrMsg("No matches — keep typing the address"); return; }
      addrResults.innerHTML = items.map(function (it, i) {
        return '<div class="addr-row" data-idx="' + i + '"><div class="addr-l1">' + esc(it.l1) +
          '</div><div class="addr-l2">' + esc(it.l2) + "</div></div>";
      }).join("");
      addrResults.classList.add("open");
      addrResults.querySelectorAll(".addr-row").forEach(function (row) {
        row.addEventListener("click", function () {
          fillLocation(items[+row.dataset.idx].f.properties || {});
          addrResults.classList.remove("open");
        });
      });
    }

    function renderBusinesses(features) {
      var items = businessRows(features);
      if (!items.length) {
        businessResults.innerHTML = '<div class="addr-row addr-msg">No business matches — enter the address manually</div>';
        businessResults.classList.add("open");
        return;
      }
      businessResults.innerHTML = items.map(function (it, i) {
        return '<div class="addr-row" data-idx="' + i + '"><div class="addr-l1">' + esc(it.name) +
          '</div><div class="addr-l2">' + esc(it.address) + "</div></div>";
      }).join("");
      businessResults.classList.add("open");
      businessResults.querySelectorAll(".addr-row").forEach(function (row) {
        row.addEventListener("click", function () {
          // Keep the name Kyle entered (it can include a job description); this is
          // only a location lookup, not a replacement for the project name.
          fillLocation(items[+row.dataset.idx].f.properties || {});
          businessResults.classList.remove("open");
        });
      });
    }

    // Bias toward the Kansas City metro (lat/lon); filter to US results.
    function lookup(q) {
      var url = "https://photon.komoot.io/api/?q=" + encodeURIComponent(q) +
        "&limit=6&lang=en&lat=39.0997&lon=-94.5786";
      return fetch(url).then(function (r) { return r.json(); }).then(function (data) {
        return (data.features || []).filter(function (f) {
          return (f.properties.countrycode || "US") === "US";
        });
      });
    }

    var addrTimer = null, addrSeq = 0;
    addrInput.addEventListener("input", function () {
      var q = addrInput.value.trim();
      if (addrTimer) clearTimeout(addrTimer);
      if (q.length < 4) { addrResults.classList.remove("open"); return; }
      addrTimer = setTimeout(function () {
        var seq = ++addrSeq;
        lookup(q).then(function (feats) {
          if (seq !== addrSeq) return;  // a newer keystroke already fired
          renderAddr(feats);
        }).catch(function () { addrResults.classList.remove("open"); });
      }, 300);  // debounce
    });

    var businessTimer = null, businessSeq = 0;
    if (businessInput && businessResults) businessInput.addEventListener("input", function () {
      var q = businessInput.value.trim();
      if (businessTimer) clearTimeout(businessTimer);
      if (q.length < 3) { businessResults.classList.remove("open"); return; }
      businessTimer = setTimeout(function () {
        var seq = ++businessSeq;
        lookup(q).then(function (feats) {
          if (seq !== businessSeq) return;
          renderBusinesses(feats);
        }).catch(function () { businessResults.classList.remove("open"); });
      }, 300);
    });

    document.addEventListener("click", function (e) {
      if (!addrInput.contains(e.target) && !addrResults.contains(e.target))
        addrResults.classList.remove("open");
      if (businessInput && businessResults && !businessInput.contains(e.target) &&
          !businessResults.contains(e.target))
        businessResults.classList.remove("open");
    });
  }

  window.TWAddress = { mount: mount, addressRows: addressRows, businessRows: businessRows,
                       fmtLine1: fmtLine1, STATE_ABBR: STATE_ABBR };
})();
