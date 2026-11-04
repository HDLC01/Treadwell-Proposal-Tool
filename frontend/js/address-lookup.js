/* The address / business-location lookup, once, for every intake page.
 *
 * MOVED OUT OF js/index.js (2026-10-05) so the beta polish intake can carry the same lookup as the
 * live form without a second copy. As the estimator types, a free public OSM database (Photon) is
 * queried and the picked row fills Address, City, State and Zip. No API key.
 *
 *   TWAddress.mount({ address, business, city, state, zip, onPick })
 *
 * `onPick({county, state, place})` is optional: called after a picked row has filled the boxes
 * (js/county-autofill.js hooks the county remodel tax box onto it).
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
 *
 * NEAREST FIRST (Hanz, 2026-11-05: "it is suggesting places that are far away from Kansas... the
 * first suggestions should be the nearest ones... some addresses are missing... when we type in
 * Treadwell it's in Delaware, Berryville, Murray, Aquila"). What changed, measured live that day:
 *   - The Treadwell office is pinned as the first row when the text names it (OSM does not know it
 *     by that name: it calls 1707 East 123rd Terrace "Surface Experts Overland Park - Olathe").
 *   - Photon is asked around the OFFICE, inside a US box, with a bigger limit, and the rows that
 *     come back are re-ranked here by straight-line miles from the office. The old call asked for 6
 *     and dropped foreign rows AFTER the limit, so "8200 Nieman" came back as France and Finland
 *     and then as nothing at all.
 *   - Bus stops, platforms and railway rows are dropped: nobody bids a floor at a bus stop.
 *   - Street-type abbreviations are spelled out for the query (Photon finds "Nieman Road" but not
 *     "Nieman Rd"). The box keeps what was typed.
 *   - OSM lacks many house numbers, so a typed "8200 Nieman Rd" that Photon cannot number is
 *     asked of OUR server (POST /api/address-suggest), which asks the US Census geocoder. Those
 *     rows land on top when they arrive. The browser itself still only talks to Photon and to us.
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

  /** THE OFFICE, the one place the page knows it. backend/distance.py OFFICE_ADDRESS / OFFICE_LAT /
   *  OFFICE_LON are the server's copy; tests/test_polish_intake_page.py pins the two together so
   *  they can never drift. lat/lon are also the centre every Photon query is asked around. */
  var OFFICE = { name: "Treadwell office", line1: "1707 E 123rd Ter", city: "Olathe", state: "KS",
                 zip: "66061", county: "Johnson", lat: 38.90391, lon: -94.79032 };

  /** THE PHOTON QUESTION. Chosen from live calls on 2026-11-05 (miles = nearest row returned):
   *    "Oak Street"   zoom 10: 11 mi   zoom 12: 3 mi   zoom 14: 1 mi
   *    "Main Street"  zoom 10: 11 mi   zoom 12: 9 mi   zoom 14: 2 mi
   *  and the far ones still come back at zoom 14: "Wichita" (the city, 162 mi), "Douglas Avenue
   *  Wichita" (155 mi), "Kansas Avenue Topeka" (48 mi). location_bias_scale 0.1 / 0.2 / 0.3 made
   *  no difference at the same zoom; 0.0 makes text relevance collapse ("Oak St" answered 101st
   *  Street), so it is never 0. The bbox is the continental US: it removes Europe (the "8200 Nieman"
   *  France/Finland rows) but still lets southern Ontario in, so the US filter below stays. limit
   *  15 so the filtering does not starve the list; at most MAX_ROWS are shown. */
  var PHOTON = { url: "https://photon.komoot.io/api/", limit: 15, zoom: 14, bias: 0.2,
                 bbox: "-125,24,-66,50" };
  var MAX_ROWS = 8;
  var CENSUS_DELAY_MS = 600;   // later than Photon's 300 ms, so typing does not fire one per keystroke
  var CENSUS_TIMEOUT_MS = 8000;

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

  // -- the query ---------------------------------------------------------------------------------

  /** Street types, spelled out for Photon (it does not expand them: "Nieman Rd" finds nothing,
   *  "Nieman Road" finds the street). St is handled on its own below. */
  var STREET_TYPES = { rd: "Road", ave: "Avenue", av: "Avenue", blvd: "Boulevard", ter: "Terrace",
    terr: "Terrace", dr: "Drive", ln: "Lane", ct: "Court", pkwy: "Parkway", hwy: "Highway",
    pl: "Place", cir: "Circle", trl: "Trail", sq: "Square", expy: "Expressway" };
  var DIRECTIONS = { n: "North", s: "South", e: "East", w: "West", ne: "Northeast", nw: "Northwest",
    se: "Southeast", sw: "Southwest" };

  /** The text Photon is asked, from the text typed. Pure; the box keeps what was typed.
   *
   *  A street type is spelled out only as a whole word that FOLLOWS a street word (a token with a
   *  letter in it), so "Dr Martin Luther King Jr Blvd" keeps its Dr and "100 St Louis Ave" keeps
   *  its St. "St" is Street only in that position AND when it ends the street: at the end, before a
   *  comma, or before another word when typed without a period ("Main St Olathe"). "St." with a
   *  period before another word is Saint ("Lake St. Louis", "Port St. Lucie"), and "St. Joseph" at
   *  the start is never touched. A lone direction letter right after the house number or at the
   *  start, with a word after it, is spelled out too ("1707 e 123rd ter" -> "1707 East 123rd
   *  Terrace"): OSM writes East, and Photon matched that row only with the word. */
  function expandQuery(q) {
    var parts = String(q == null ? "" : q).split(/(\s+)/);   // keeps the spacing as typed
    var words = [];
    for (var i = 0; i < parts.length; i++) if (!/^\s*$/.test(parts[i])) words.push(i);
    words.forEach(function (idx, w) {
      var raw = parts[idx];
      var m = /^([A-Za-z]+)(\.?)(,?)$/.exec(raw);
      if (!m) return;
      var key = m[1].toLowerCase(), dot = m[2], comma = m[3];
      var prev = w > 0 ? parts[words[w - 1]] : "";
      var next = w + 1 < words.length ? parts[words[w + 1]] : "";
      var afterStreetWord = w > 0 && /[A-Za-z]/.test(prev) && !/,$/.test(prev);
      var afterNumberOrStart = w === 0 || /^\d+[A-Za-z]?$/.test(prev);
      if (DIRECTIONS[key] && afterNumberOrStart && next && /[A-Za-z0-9]/.test(next) && !comma &&
          (w > 0 || words.length > 1)) {
        parts[idx] = DIRECTIONS[key] + comma;
        return;
      }
      if (!afterStreetWord) return;
      if (STREET_TYPES[key]) { parts[idx] = STREET_TYPES[key] + comma; return; }
      if (key === "st") {
        var endsStreet = !next || comma || !dot;
        if (endsStreet) parts[idx] = "Street" + comma;
      }
    });
    return parts.join("");
  }

  /** "8200" for "8200 Nieman Rd": a house number followed by a street (two letters somewhere after
   *  it, so "8200 W 75th" counts and "8200 N" does not yet). "" otherwise. */
  function houseNumberOf(q) {
    var m = /^\s*(\d+[A-Za-z]?)\s+(?=.*[A-Za-z]{2})/.exec(String(q || ""));
    return m ? m[1].toLowerCase() : "";
  }

  /** The text names the office: "Treadwell" anywhere, or its street number and street. */
  function isOfficeQuery(q) {
    var s = String(q || "").toLowerCase();
    return s.indexOf("treadwell") >= 0 || /^\s*1707\s+(e\.?|east)\s+123/.test(s);
  }

  function photonUrl(q) {
    return PHOTON.url + "?q=" + encodeURIComponent(q) + "&limit=" + PHOTON.limit + "&lang=en" +
      "&lat=" + OFFICE.lat + "&lon=" + OFFICE.lon + "&zoom=" + PHOTON.zoom +
      "&location_bias_scale=" + PHOTON.bias + "&bbox=" + PHOTON.bbox;
  }

  // -- the answer --------------------------------------------------------------------------------

  /** Straight-line miles from the office, or Infinity when the row has no usable point. */
  function milesFromOffice(lat, lon) {
    lat = +lat; lon = +lon;
    if (!isFinite(lat) || !isFinite(lon) || (lat === 0 && lon === 0)) return Infinity;
    var r = Math.PI / 180, R = 3958.8;
    var dLat = (lat - OFFICE.lat) * r, dLon = (lon - OFFICE.lon) * r;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(OFFICE.lat * r) * Math.cos(lat * r) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  function featureMiles(f) {
    var c = f && f.geometry && f.geometry.coordinates;
    return (c && c.length >= 2) ? milesFromOffice(c[1], c[0]) : Infinity;
  }

  function fmtMiles(mi) {
    if (!isFinite(mi)) return "";
    return mi < 1 ? "under 1 mi" : Math.round(mi) + " mi";
  }

  /** A stop or a station, not a place anyone pours a floor: bus stops and platforms, every
   *  public_transport row (stop positions, stations, platforms), and every railway row (stations,
   *  halts, stops, junctions, the yard as landuse=railway). */
  function isTransit(p) {
    var k = p.osm_key, v = p.osm_value;
    if (k === "public_transport" || k === "railway") return true;
    if (k === "highway" && (v === "bus_stop" || v === "platform")) return true;
    if (k === "amenity" && v === "bus_station") return true;
    if (k === "landuse" && v === "railway") return true;
    return false;
  }

  /** The office's own OSM row (a tenant's name on 1707 East 123rd Terrace): the pinned row already
   *  says it, so the copy is dropped when the pin is shown. */
  function isOfficeFeature(p) {
    return String(p.housenumber || "") === "1707" && /123rd/i.test(String(p.street || ""));
  }

  function plain(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim(); }

  /** Words that say nothing about WHICH street: directions and street types, both spellings, and
   *  St / Saint (a typed "St Joseph Ave" is about Joseph, whether OSM spells it St or Saint). */
  var NOT_A_NAME = { st: 1, street: 1, saint: 1 };
  Object.keys(STREET_TYPES).forEach(function (k) { NOT_A_NAME[k] = 1; NOT_A_NAME[STREET_TYPES[k].toLowerCase()] = 1; });
  Object.keys(DIRECTIONS).forEach(function (k) { NOT_A_NAME[k] = 1; NOT_A_NAME[DIRECTIONS[k].toLowerCase()] = 1; });

  /** The word that names the street (or the business): the first word after the house number and
   *  before any comma that is not a direction or a street type. "123 Main St, Lees Summit" -> "main",
   *  "8200 W 75th St" -> "75th", "N Oak Street" -> "oak", "Treadwell office" -> "treadwell". The
   *  city after a comma is never it. Falls back to the first word when every word is a type ("N St"). */
  function keyWordOf(q) {
    var words = plain(expandQuery(q).split(",")[0]).split(" ").filter(Boolean);
    if (houseNumberOf(q)) words.shift();
    var named = words.filter(function (w) { return !NOT_A_NAME[w]; });
    return named[0] || words[0] || "";
  }

  /** `text` holds a word that starts with `word` (a word still being typed counts: "Niem"). */
  function textHas(text, word) {
    if (!word) return false;
    return plain(text).split(" ").some(function (w) { return w.indexOf(word) === 0; });
  }

  /** The row IS the typed address: the typed house number AND the typed street. A number alone is
   *  not enough (review, 2026-11-05): "123 Main St, Lees Summit" brought back a bar at 123 SE 3rd
   *  Street, which then ranked first AND stopped the Census question that had 123 NE Main St. One
   *  predicate, used by the ranking and by the Census step, so the two can never disagree. */
  function hasTypedNumber(p, q) {
    var hn = houseNumberOf(q);
    if (!hn || String((p && p.housenumber) || "").toLowerCase() !== hn) return false;
    return textHas(p.street || p.name, keyWordOf(q));
  }

  /** Photon's rows, US only, no transit, nearest first. Pure; exported for the harness.
   *
   *  THE ORDER, four groups, nearest first inside each:
   *    0. the typed address: the typed house number on the typed street ("8200 Nieman Rd" puts
   *       8200 Nieman Road above every bare street; 8200 on another street is not it);
   *    1. a town or city (osm_key=place) whose name is what was typed, or what is being typed
   *       ("Wichi" / "Wichita" / "Wichita, KS"): typing a town's name means the town, and a road
   *       named after it 26 miles away must not push it to the bottom of the list;
   *    2. the row's shown street (the business name, in the business box) carries the typed word.
   *       Photon also matches shops and buildings on their own NAME ("Oak St" -> Smokin Oak Pizza
   *       on W 119th St); by distance alone those came first, showing streets nobody typed, and
   *       pushed the real Red Oak Street past the 8-row cut (review, 2026-11-05);
   *    3. everything else.
   *  Rows with no point sort last in their group. The result is [{f, miles}].
   *
   *  GROUP 1 ONLY WITHIN TOWN_BOOST_MILES (browser walk, 2026-11-05): "Treadwell" lifted the
   *  Treadwell hamlets in Georgia, Virginia and New York (617-1,059 mi) above Treadwell Drive in
   *  Galesburg (274 mi), the far-away suggestions Hanz complained of. A town that far is ranked by
   *  distance like everything else; Wichita (162 mi) keeps its lift. */
  var TOWN_BOOST_MILES = 300;
  function rankFeatures(features, q, opts) {
    opts = opts || {};
    var typed = plain(q), word = keyWordOf(q);
    var out = [];
    (features || []).forEach(function (f, i) {
      var p = (f && f.properties) || {};
      if ((p.countrycode || "US") !== "US") return;
      if (isTransit(p)) return;
      if (opts.dropOffice && isOfficeFeature(p)) return;
      var nm = plain(p.name), group = 3, miles = featureMiles(f);
      if (hasTypedNumber(p, q)) group = 0;
      else if (p.osm_key === "place" && typed && nm && miles <= TOWN_BOOST_MILES &&
               (typed.indexOf(nm) === 0 || nm.indexOf(typed) === 0)) group = 1;
      else if (textHas(opts.business ? p.name : (p.street || p.name), word)) group = 2;
      out.push({ f: f, miles: miles, group: group, i: i });
    });
    out.sort(function (a, b) {
      if (a.group !== b.group) return a.group - b.group;
      if (a.miles !== b.miles) return a.miles < b.miles ? -1 : 1;
      return a.i - b.i;
    });
    return out.map(function (r) { return { f: r.f, miles: r.miles }; });
  }

  function withMiles(text, mi) {
    var m = fmtMiles(mi);
    return m ? (text ? text + " · " + m : m) : text;
  }

  /** Photon often returns several OSM objects for the same address, so dedupe on the displayed
   *  text. Pure: features (or ranked {f, miles}) in, rows out. Exported for the harness. */
  function addressRows(features) {
    var seen = {}, items = [];
    (features || []).forEach(function (x) {
      var f = x && x.f ? x.f : x;
      var mi = x && x.f ? x.miles : featureMiles(f);
      var p = (f && f.properties) || {};
      var l1 = fmtLine1(p);
      var l2 = localityOf(p);
      if (!l1 && !l2) return;
      var key = (l1 + "|" + l2).toLowerCase();
      if (seen[key]) return;
      seen[key] = true;
      // A shop or a building Photon matched on its own name shows ITS street on line 1, which on its
      // own reads like a street nobody typed ("Oak St" -> "15241 West 119th Street"). Its name goes
      // in front of line 2 so the row says why it is there. Streets and towns are their own name.
      var nameHint = (p.name && p.street && p.osm_key !== "highway" && p.osm_key !== "place" &&
                      plain(p.name) !== plain(p.street)) ? p.name : "";
      items.push({ f: f, l1: l1, l2: withMiles([nameHint, l2].filter(Boolean).join(" · "), mi), miles: mi });
    });
    return items;
  }

  function businessRows(features) {
    var seen = {}, items = [];
    (features || []).forEach(function (x) {
      var f = x && x.f ? x.f : x;
      var mi = x && x.f ? x.miles : featureMiles(f);
      var p = (f && f.properties) || {};
      var name = (p.name || "").trim();
      var address = fmtLine1(p);
      var locality = localityOf(p);
      if (!name || (!address && !locality)) return;
      var key = (name + "|" + address + "|" + locality).toLowerCase();
      if (seen[key]) return;
      seen[key] = true;
      items.push({ f: f, name: name, address: withMiles([address, locality].filter(Boolean).join(", "), mi),
                   miles: mi });
    });
    return items;
  }

  /** A row from POST /api/address-suggest, checked: anything malformed is dropped. */
  function censusRow(r) {
    if (!r || typeof r !== "object") return null;
    var line1 = String(r.line1 || "").trim(), city = String(r.city || "").trim();
    var st = String(r.state || "").trim().toUpperCase(), zip = String(r.zip || "").trim();
    if (!line1 || !/^[A-Z]{2}$/.test(st)) return null;
    return { line1: line1, city: city, state: st, zip: zip,
             miles: milesFromOffice(r.lat, r.lon) };
  }

  /** Ask OUR server for the house numbers OSM lacks (it asks the US Census). Resolves to a list of
   *  checked rows, [] for ANY failure; never rejects. Same request shape as js/county-autofill.js. */
  async function askServer(q) {
    try {
      var TW = window.TW;
      if (!TW || typeof TW.resolveApiBase !== "function") return [];
      if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready;
      var res = await fetch(TW.resolveApiBase() + "/api/address-suggest", {
        method: "POST",
        headers: TW.authHeaders ? TW.authHeaders({ "Content-Type": "application/json" })
                                : { "Content-Type": "application/json" },
        body: JSON.stringify({ q: q }),
        signal: (typeof AbortSignal !== "undefined" && AbortSignal.timeout)
          ? AbortSignal.timeout(CENSUS_TIMEOUT_MS) : undefined
      });
      var j = await res.json();
      if (!j || j.ok !== true || !Array.isArray(j.rows)) return [];
      return j.rows.map(censusRow).filter(Boolean).slice(0, 3);
    } catch (e) { return []; }
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

    /** THE LIST BELONGS TO THE BOX THAT ASKED FOR IT (browser walk on staging, 2026-10-20): an address typed and then
     *  Tab-bed out of left the list open over City, State and Zip; Escape did nothing, and a click on those boxes landed on
     *  the list's rows. Leaving the box closes its list, an answer that lands after the box was left never opens it, and
     *  Escape closes it. A press on a row keeps the focus in the box (its mousedown is not let through), so leaving the box
     *  can never swallow the pick. `left` starts false, so a box that never reported focus behaves as before. */
    function leaveCloses(input, results) {
      var left = false;
      if (!input || !results) return function () { return true; };
      input.addEventListener("focus", function () { left = false; });
      input.addEventListener("blur", function () { left = true; results.classList.remove("open"); });
      input.addEventListener("keydown", function (e) {
        if (e && e.key === "Escape" && results.classList.contains("open")) {
          results.classList.remove("open");
          if (e.preventDefault) e.preventDefault();
        }
      });
      results.addEventListener("mousedown", function (e) { if (e && e.preventDefault) e.preventDefault(); });
      return function () { return !left; };
    }
    var addrMayOpen = leaveCloses(addrInput, addrResults);
    var businessMayOpen = leaveCloses(businessInput, businessResults);

    // What the address list holds for the text now in the box: the office pin, the Census rows
    // (when they have come back) and Photon's rows. Drawn again whenever one of them lands.
    var addr = { gen: 0, q: "", office: false, census: [], photon: null, photonDone: null };
    var addrTimer = null, censusTimer = null, businessTimer = null, businessSeq = 0;

    /** Fill the four boxes, tell the form, then the page's hook. `loc` is
     *  {line1, city, state, zip, county, place}. A hook that throws must not undo the pick.
     *
     *  A PICK ENDS EVERY QUESTION STILL OUT (review, 2026-11-05). The Census is the slow one (600 ms
     *  wait + ~1.6 s), so a person picks a Photon street while it is on its way; when it landed it
     *  re-opened the list over City, State and Zip, and a second click overwrote the pick. Bumping the
     *  generations makes every answer for the old text fail its own `gen` / `seq` check. */
    function fillBoxes(loc) {
      addr.gen++; businessSeq++;
      if (addrTimer) clearTimeout(addrTimer);
      if (censusTimer) clearTimeout(censusTimer);
      if (businessTimer) clearTimeout(businessTimer);
      addrInput.value  = loc.line1;
      cityInput.value  = loc.city;
      stateInput.value = loc.state;
      zipInput.value   = loc.zip;
      ping(cityInput); ping(stateInput); ping(zipInput);
      // js/county-autofill.js uses the hook to fill the county from this pick; the county here is an
      // instant first guess (Photon's, the office's own, or "" for a Census row, which the autofill
      // then looks up itself).
      if (typeof els.onPick === "function") {
        try { els.onPick({ county: loc.county || "", state: loc.state, place: loc.place || "" }); }
        catch (e) { /* the pick stands */ }
      }
    }

    function fillLocation(p) {
      fillBoxes({ line1: fmtLine1(p), city: p.city || p.county || "", state: stateOf(p),
                  zip: p.postcode || "", county: p.county || "", place: p.city || "" });
    }

    function fillOffice() {
      fillBoxes({ line1: OFFICE.line1, city: OFFICE.city, state: OFFICE.state, zip: OFFICE.zip,
                  county: OFFICE.county, place: OFFICE.city });
    }

    function fillCensus(r) {
      fillBoxes({ line1: r.line1, city: r.city, state: r.state, zip: r.zip, county: "", place: r.city });
    }

    /** Draw a list of {l1, l2, pick} into `results`, or the message when there are none. */
    function draw(results, mayOpen, rows, emptyText) {
      if (!mayOpen()) return;              // the box was left while the answer was on its way
      if (!rows.length) {
        results.innerHTML = '<div class="addr-row addr-msg">' + emptyText + "</div>";
        results.classList.add("open");
        return;
      }
      rows = rows.slice(0, MAX_ROWS);
      results.innerHTML = rows.map(function (it, i) {
        return '<div class="addr-row" data-idx="' + i + '"><div class="addr-l1">' + esc(it.l1) +
          '</div><div class="addr-l2">' + esc(it.l2) + "</div></div>";
      }).join("");
      results.classList.add("open");
      results.querySelectorAll(".addr-row").forEach(function (row) {
        row.addEventListener("click", function () {
          var it = rows[+row.dataset.idx];
          if (it) it.pick();
          results.classList.remove("open");
        });
      });
    }

    function officeRow(business) {
      return { l1: business ? OFFICE.name : OFFICE.line1,
               l2: OFFICE.city + ", " + OFFICE.state + " " + OFFICE.zip, pick: fillOffice };
    }

    function renderAddr() {
      var rows = [];
      if (addr.office) rows.push(officeRow(false));
      addr.census.forEach(function (r) {
        rows.push({ l1: r.line1, l2: withMiles([r.city, r.state, r.zip].filter(Boolean).join(", "), r.miles) +
                    " · US Census", pick: function () { fillCensus(r); } });
      });
      addressRows(addr.photon || []).forEach(function (it) {
        rows.push({ l1: it.l1, l2: it.l2, pick: function () { fillLocation(it.f.properties || {}); } });
      });
      draw(addrResults, addrMayOpen, rows, "No matches — keep typing the address");
    }

    function renderBusinesses(q, ranked) {
      var rows = [];
      if (isOfficeQuery(q)) rows.push(officeRow(true));
      businessRows(ranked).forEach(function (it) {
        // Keep the name Kyle entered (it can include a job description); this is
        // only a location lookup, not a replacement for the project name.
        rows.push({ l1: it.name, l2: it.address, pick: function () { fillLocation(it.f.properties || {}); } });
      });
      draw(businessResults, businessMayOpen, rows, "No business matches — enter the address manually");
    }

    /** Photon, asked around the office, answered as ranked {f, miles} rows. */
    function lookup(q, office, business) {
      return fetch(photonUrl(q)).then(function (r) { return r.json(); }).then(function (data) {
        return rankFeatures((data && data.features) || [], q, { dropOffice: office, business: business });
      });
    }

    /** The Census step, for the text the box held when it was armed. It waits for Photon's answer
     *  for the same text, and asks only when Photon has no row with the typed house number. Its rows
     *  are drawn only if the box still holds that text (the generation has not moved on) and the
     *  list may open (the box was not left; draw() checks). */
    function censusStep(gen) {
      if (gen !== addr.gen) return;
      var q = addr.q;
      (addr.photonDone || Promise.resolve([])).then(function (ranked) {
        if (gen !== addr.gen) return null;
        // The typed number on the typed STREET; the number on some other street does not count.
        var numbered = (ranked || []).some(function (x) {
          return hasTypedNumber((x.f || {}).properties || {}, q);
        });
        if (numbered) return null;
        return askServer(q);
      }).then(function (rows) {
        if (gen !== addr.gen || !rows || !rows.length) return;
        addr.census = rows;
        renderAddr();
      }).catch(function () { /* a convenience: no rows */ });
    }

    addrInput.addEventListener("input", function () {
      var q = addrInput.value.trim();
      if (addrTimer) clearTimeout(addrTimer);
      if (censusTimer) clearTimeout(censusTimer);
      var gen = ++addr.gen;
      addr.q = q; addr.census = []; addr.photon = null; addr.photonDone = null;
      if (q.length < 4) { addrResults.classList.remove("open"); return; }
      addr.office = isOfficeQuery(q);
      addrTimer = setTimeout(function () {
        if (gen !== addr.gen) return;   // a newer keystroke already owns the box
        var done = lookup(expandQuery(q), addr.office);
        addr.photonDone = done.catch(function () { return []; });
        done.then(function (ranked) {
          if (gen !== addr.gen) return;
          addr.photon = ranked;
          renderAddr();
        }).catch(function () {
          if (gen !== addr.gen) return;
          // Photon is down: the office pin or Census rows still stand; with neither, close.
          if (addr.office || addr.census.length) { addr.photon = []; renderAddr(); }
          else addrResults.classList.remove("open");
        });
      }, 300);  // debounce
      if (!addr.office && houseNumberOf(q)) {
        censusTimer = setTimeout(function () { censusStep(gen); }, CENSUS_DELAY_MS);
      }
    });

    if (businessInput && businessResults) businessInput.addEventListener("input", function () {
      var q = businessInput.value.trim();
      if (businessTimer) clearTimeout(businessTimer);
      if (q.length < 3) { businessResults.classList.remove("open"); return; }
      businessTimer = setTimeout(function () {
        var seq = ++businessSeq;
        // A business name is asked as typed: "Dr Pepper" and "St. Luke's" are names, not streets.
        lookup(q, isOfficeQuery(q), true).then(function (ranked) {
          if (seq !== businessSeq) return;
          renderBusinesses(q, ranked);
        }).catch(function () {
          if (seq !== businessSeq) return;
          if (isOfficeQuery(q)) renderBusinesses(q, []);
          else businessResults.classList.remove("open");
        });
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
                       fmtLine1: fmtLine1, STATE_ABBR: STATE_ABBR, OFFICE: OFFICE, PHOTON: PHOTON,
                       expandQuery: expandQuery, houseNumberOf: houseNumberOf,
                       isOfficeQuery: isOfficeQuery, rankFeatures: rankFeatures,
                       keyWordOf: keyWordOf, hasTypedNumber: hasTypedNumber,
                       milesFromOffice: milesFromOffice, photonUrl: photonUrl };
})();
