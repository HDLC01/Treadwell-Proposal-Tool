// Inline-SVG chart kit — every function returns a string of markup.
// Externalized from analytics.html (CSP: drop script-src 'unsafe-inline').
// Do not add inline scripts.
//
// Hand-rolled rather than a charting library: the dashboard needs five simple
// single-series forms, the app has no build step, and a CDN bundle would arrive
// with its own fonts, colours and animations to fight. Every mark is a string,
// so the whole kit is testable without a browser.
//
// No handlers live in the markup (CSP). Interactive marks carry `data-idx` and
// the page delegates clicks from the container.
//
// House rules this kit follows:
//   · One series = one colour and NO legend — the card title says what's plotted.
//   · Text never wears the data colour. Values and labels use ink tokens; the
//     coloured mark beside them carries the identity.
//   · Bars cap at 24px with a rounded data-end and a square baseline; adjacent
//     marks are separated by a gap in the surface colour, never by a stroke.
//   · Labels are placed only where they measurably fit. Nothing is clipped.
(function (root, factory) {
  var api = factory();
  root.TWCharts = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Validated 2026-07-31 against the page surface #fbf9f8 (light only — the app
  // ships no dark theme). Adjacent CVD ΔE 9.2, normal-vision ΔE 19.6, all eight
  // inside the lightness band. Slot 1 is the Treadwell red. Three slots sit under
  // 3:1 on this surface, which is why every donut carries a labelled legend and
  // a List view: identity never rests on hue alone.
  var PALETTE = ["#c8102e", "#2a78d6", "#1baf7a", "#eb6834",
                 "#4a3aa7", "#eda100", "#e87ba4", "#008300"];
  var SERIES = "#c8102e";          // the single-series hue
  var SURFACE = "#ffffff";         // card background — the gaps and rings are cut in this
  // Warm neutrals to match the page. Gridlines sit one step off the card so they
  // stay behind the data instead of competing with it.
  var GRID = "#ece8e0";
  var AXIS_INK = "#8a857c";
  var LABEL_INK = "#57534a";
  var BAR_MAX = 24;                // never fill the slot; the leftover is air
  var BAR_GAP = 2;                 // surface gap between touching bars
  var RADIUS = 4;                  // rounded data-end

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // ── formatters ──────────────────────────────────────────────────────
  function fmtMoney(v) {
    var n = Math.round(Number(v) || 0);
    return (n < 0 ? "-$" : "$") + Math.abs(n).toLocaleString("en-US");
  }
  function fmtMoneyShort(v) {
    var n = Number(v) || 0, a = Math.abs(n), s = n < 0 ? "-" : "";
    if (a >= 1e9) return s + "$" + trim(a / 1e9) + "B";
    if (a >= 1e6) return s + "$" + trim(a / 1e6) + "M";
    if (a >= 1e3) return s + "$" + trim(a / 1e3) + "K";
    return s + "$" + Math.round(a);
  }
  function trim(x) {
    var r = x >= 100 ? Math.round(x) : Math.round(x * 10) / 10;
    return String(r);
  }
  function fmtInt(v) { return (Math.round(Number(v) || 0)).toLocaleString("en-US"); }
  function fmtPct(r) {
    if (r === null || r === undefined) return "—";     // no denominator, no answer
    return (Math.round(r * 1000) / 10) + "%";
  }
  var FMT = { money: fmtMoney, moneyShort: fmtMoneyShort, int: fmtInt, pct: fmtPct };

  /** A round number at or above the peak, so the axis reads 0 / 500K / 1M. */
  function niceMax(v) {
    if (!(v > 0)) return 1;
    var mag = Math.pow(10, Math.floor(Math.log10(v)));
    var step = [1, 2, 2.5, 5, 10].find(function (s) { return v <= s * mag; }) || 10;
    return step * mag;
  }

  function emptyNote(msg) {
    return '<p class="chart-empty">' + esc(msg || "Nothing to show for these filters.") + "</p>";
  }

  /** A bar giving a percentage a shape. Over 100% fills the track rather than
   *  overflowing it — the figure beside it already says the real number, and a
   *  meter that ran past its own end would read as a rendering fault. */
  function meter(ratio) {
    if (ratio === null || ratio === undefined) return "";
    var pct = Math.max(0, Math.min(1, ratio)) * 100;
    return '<div class="meter"><i style="width:' + pct.toFixed(1) + '%"></i></div>';
  }

  /** `hex` at `alpha`, for a tinted pill behind its own solid dot. */
  function tint(hex, alpha) {
    var h = String(hex || "").replace("#", "");
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    if (h.length !== 6) return "rgba(0,0,0," + alpha + ")";
    var n = parseInt(h, 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + alpha + ")";
  }

  /** A darker step of `hex`, so text on a tint of it still clears contrast. */
  function darken(hex, amount) {
    var h = String(hex || "").replace("#", "");
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    if (h.length !== 6) return "#000";
    var n = parseInt(h, 16), k = 1 - (amount === undefined ? 0.45 : amount);
    var r = Math.round(((n >> 16) & 255) * k), g = Math.round(((n >> 8) & 255) * k),
        b = Math.round((n & 255) * k);
    return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
  }

  /** A bar with a rounded data-end and a square baseline. */
  function barPath(x, y, w, h) {
    var r = Math.min(RADIUS, w / 2, h);
    if (h <= 0.5) return "";
    return "M" + x + "," + (y + h) +
           "V" + (y + r) + "Q" + x + "," + y + " " + (x + r) + "," + y +
           "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) +
           "V" + (y + h) + "Z";
  }

  function gridlines(w, top, plotH, max, fmt, pad) {
    var out = "", n = 4;
    for (var i = 0; i <= n; i++) {
      var y = top + plotH - (plotH * i / n);
      out += '<line x1="' + pad + '" y1="' + y + '" x2="' + w + '" y2="' + y +
             '" stroke="' + GRID + '" stroke-width="1" />';
      out += '<text x="' + (pad - 6) + '" y="' + (y + 3.5) + '" text-anchor="end" ' +
             'font-size="10" fill="' + AXIS_INK + '" ' +
             'style="font-variant-numeric:tabular-nums">' + esc(fmt(max * i / n)) + "</text>";
    }
    return out;
  }

  function truncate(s, n) {
    s = String(s === null || s === undefined ? "" : s);
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  var LAB_SIZE = 9.5;
  var CHAR_W = 5.3;                 // ~advance per character at LAB_SIZE
  var LAB_ROT = 40;                 // degrees; shallow enough to stay readable

  /** How the x axis should carry its labels for this many bands.
   *
   *  Horizontal while they fit, diagonal when they don't, and thinned when even
   *  diagonal would collide — "All time" is ninety-odd months, and at that width
   *  every label drawn is a label unread. */
  function xAxisPlan(items, band) {
    var longest = 0;
    for (var i = 0; i < items.length; i++) {
      longest = Math.max(longest, String(items[i].label || "").length);
    }
    var flat = longest * CHAR_W + 8;              // width a horizontal label needs
    var rotated = band < flat;
    // Turned on the diagonal a label only has to clear its neighbour's baseline,
    // which costs a line height rather than a whole word — but that clearance is
    // measured perpendicular to the text, so the horizontal room it needs is the
    // line height divided by sin(angle).
    var pitch = rotated
      ? (LAB_SIZE * 1.15) / Math.sin(LAB_ROT * Math.PI / 180)
      : flat;
    return {
      rotated: rotated,
      step: Math.max(1, Math.ceil(pitch / band)),
      chars: rotated ? 12 : Math.max(4, Math.floor(band / CHAR_W)),
      // Room under the axis for the diagonal to descend into.
      bottom: rotated ? 56 : 26,
    };
  }

  function xLabel(text, cx, baseY, plan) {
    var t = esc(truncate(text, plan.chars));
    if (!plan.rotated) {
      return '<text x="' + cx + '" y="' + baseY + '" text-anchor="middle" font-size="' +
        LAB_SIZE + '" fill="' + AXIS_INK + '">' + t + "</text>";
    }
    // Anchored at its end so the text runs up-and-left from the band it labels.
    return '<text x="' + cx + '" y="' + baseY + '" text-anchor="end" font-size="' + LAB_SIZE +
      '" fill="' + AXIS_INK + '" transform="rotate(-' + LAB_ROT + " " + cx + " " + baseY +
      ')">' + t + "</text>";
  }

  /** Vertical bars — a measure over months. Single series, so no legend. */
  function bar(opts) {
    var items = opts.items || [];
    if (!items.length) return emptyNote(opts.empty);
    var fmt = FMT[opts.fmt] || fmtMoneyShort;
    var axisFmt = opts.fmt === "int" ? fmtInt : fmtMoneyShort;
    var W = 640, PAD = 54, TOP = 18;
    var plotW = W - PAD;
    var band = plotW / items.length;
    var plan = xAxisPlan(items, band);
    // The plot keeps its height; the chart grows to make room for a diagonal.
    var plotH = (opts.height || 200) - TOP - 26;
    var H = TOP + plotH + plan.bottom;
    var max = niceMax(Math.max.apply(null, items.map(function (d) { return d.value || 0; })));
    var bw = Math.max(2, Math.min(BAR_MAX, band - BAR_GAP - Math.min(10, band * 0.25)));
    // A value only sits on the cap when it fits the BAND (it's centred on the
    // bar and may be wider than it). ~6 units per character at this size;
    // otherwise the gridlines carry it and the hover gives the exact figure.
    var labelCaps = band >= 48 && items.length <= 14;
    var labelY = TOP + plotH + (plan.rotated ? 13 : 17);

    var marks = "";
    for (var i = 0; i < items.length; i++) {
      var d = items[i];
      var h = max ? (Math.max(0, d.value || 0) / max) * plotH : 0;
      var x = PAD + band * i + (band - bw) / 2;
      var y = TOP + plotH - h;
      var cx = PAD + band * i + band / 2;
      marks += '<g class="ch-mark" data-idx="' + i + '">' +
        '<title>' + esc(d.label) + " · " + esc(fmt(d.value)) + "</title>" +
        '<rect x="' + (PAD + band * i) + '" y="' + TOP + '" width="' + band +
          '" height="' + plotH + '" fill="transparent" />' +   // a hit target bigger than the mark
        (h > 0.5 ? '<path d="' + barPath(x, y, bw, h) + '" fill="' + SERIES + '" />' : "") +
        (labelCaps && (d.value || 0) > 0
          ? '<text x="' + (x + bw / 2) + '" y="' + (y - 5) + '" text-anchor="middle" ' +
            'font-size="9.5" fill="' + LABEL_INK + '">' + esc(fmt(d.value)) + "</text>"
          : "") +
        (i % plan.step ? "" : xLabel(d.label, cx, labelY, plan)) +
        "</g>";
    }
    return svg(W, H, opts.aria || "Bar chart", gridlines(W, TOP, plotH, max, axisFmt, PAD) + marks);
  }

  /** Horizontal bars — a measure across a dimension, longest first. */
  function hbar(opts) {
    var all = opts.items || [];
    if (!all.length) return emptyNote(opts.empty);
    var fmt = FMT[opts.fmt] || fmtMoneyShort;
    var cap = opts.max || 12;
    var items = all.slice(0, cap);
    var W = 640, LAB = 150, ROW = 28, TOP = 6;
    var H = TOP * 2 + ROW * items.length + (all.length > cap ? 18 : 0);
    var max = Math.max.apply(null, items.map(function (d) { return Math.abs(d.value) || 0; })) || 1;
    var trackW = W - LAB - 86;

    var marks = "";
    for (var i = 0; i < items.length; i++) {
      var d = items[i];
      var bh = Math.min(BAR_MAX, ROW - 8);
      var y = TOP + ROW * i + (ROW - bh) / 2;
      var w = Math.max(0, (Math.abs(d.value) || 0) / max) * trackW;
      marks += '<g class="ch-mark" data-idx="' + i + '" data-key="' + esc(d.key) + '">' +
        "<title>" + esc(d.label) + " · " + esc(fmt(d.value)) + "</title>" +
        '<rect x="0" y="' + (TOP + ROW * i) + '" width="' + W + '" height="' + ROW +
          '" fill="transparent" />' +
        '<text x="0" y="' + (y + bh / 2 + 3.5) + '" font-size="11" fill="' + LABEL_INK + '">' +
          esc(truncate(d.label, 24)) + "</text>" +
        (w > 0.5
          ? '<path d="' + hbarPath(LAB, y, w, bh) + '" fill="' + (d.color || SERIES) + '" />'
          : "") +
        '<text x="' + (LAB + trackW + 8) + '" y="' + (y + bh / 2 + 3.5) + '" font-size="10.5" ' +
          'fill="' + LABEL_INK + '" style="font-variant-numeric:tabular-nums">' +
          esc(fmt(d.value)) + "</text>" +
        "</g>";
    }
    if (all.length > cap) {
      marks += '<text x="' + LAB + '" y="' + (H - 5) + '" font-size="10" fill="' + AXIS_INK + '">' +
        "+" + (all.length - cap) + " more — switch to List to see them all</text>";
    }
    return svg(W, H, opts.aria || "Bar chart", marks);
  }

  function hbarPath(x, y, w, h) {
    var r = Math.min(RADIUS, h / 2, w);
    if (w <= 0.5) return "";
    return "M" + x + "," + y +
           "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) +
           "V" + (y + h - r) + "Q" + (x + w) + "," + (y + h) + " " + (x + w - r) + "," + (y + h) +
           "H" + x + "Z";
  }

  /** A trend over months. 2px line, dots ringed in the surface colour. */
  function line(opts) {
    var items = opts.items || [];
    if (!items.length) return emptyNote(opts.empty);
    var fmt = FMT[opts.fmt] || fmtMoneyShort;
    var axisFmt = opts.fmt === "int" ? fmtInt : fmtMoneyShort;
    var W = 640, PAD = 54, TOP = 18;
    var plotW = W - PAD;
    var plan = xAxisPlan(items, plotW / items.length);
    var plotH = (opts.height || 200) - TOP - 26;
    var H = TOP + plotH + plan.bottom;
    var max = niceMax(Math.max.apply(null, items.map(function (d) { return d.value || 0; })));
    var step = items.length > 1 ? plotW / (items.length - 1) : 0;
    var xs = items.map(function (_, i) { return PAD + (items.length > 1 ? step * i : plotW / 2); });
    var ys = items.map(function (d) { return TOP + plotH - (max ? (Math.max(0, d.value || 0) / max) * plotH : 0); });

    var pts = xs.map(function (x, i) { return x + "," + ys[i]; }).join(" ");
    var marks = '<polyline points="' + pts + '" fill="none" stroke="' + SERIES +
      '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />';
    for (var i = 0; i < items.length; i++) {
      marks += '<g class="ch-mark" data-idx="' + i + '">' +
        "<title>" + esc(items[i].label) + " · " + esc(fmt(items[i].value)) + "</title>" +
        '<circle cx="' + xs[i] + '" cy="' + ys[i] + '" r="11" fill="transparent" />' +
        '<circle cx="' + xs[i] + '" cy="' + ys[i] + '" r="4" fill="' + SERIES +
          '" stroke="' + SURFACE + '" stroke-width="2" />' + "</g>";
    }
    // Only the last point is labelled — a number on every dot goes unread.
    var last = items.length - 1;
    if (last >= 0 && (items[last].value || 0) > 0) {
      marks += '<text x="' + Math.min(xs[last], W - 4) + '" y="' + (ys[last] - 10) +
        '" text-anchor="end" font-size="9.5" fill="' + LABEL_INK + '">' +
        esc(fmt(items[last].value)) + "</text>";
    }
    var labelY = TOP + plotH + (plan.rotated ? 13 : 17);
    for (var j = 0; j < items.length; j++) {
      if (j % plan.step) continue;
      marks += xLabel(items[j].label, xs[j], labelY, plan);
    }
    return svg(W, H, opts.aria || "Line chart", gridlines(W, TOP, plotH, max, axisFmt, PAD) + marks);
  }

  /** Share of a whole. Always ships its legend — the slice colours alone are
   *  not the identity channel. */
  function donut(opts) {
    var all = (opts.items || []).filter(function (d) { return (d.value || 0) > 0; });
    if (!all.length) return emptyNote(opts.empty);
    var fmt = FMT[opts.fmt] || fmtMoneyShort;
    var cap = opts.maxSlices || 8;
    var items = all.slice(0, cap);
    if (all.length > cap) {
      var rest = all.slice(cap).reduce(function (t, d) { return t + (d.value || 0); }, 0);
      if (rest > 0) items = items.concat([{ key: "__other__", label: "Other", value: rest }]);
    }
    var total = items.reduce(function (t, d) { return t + (d.value || 0); }, 0) || 1;

    var SZ = 168, R = 76, INNER = 46, C = SZ / 2;
    var GAP_DEG = items.length > 1 ? 1.4 : 0;         // the surface gap, as an angle
    var a = -90, slices = "", legend = "";
    for (var i = 0; i < items.length; i++) {
      var d = items[i], frac = (d.value || 0) / total;
      var sweep = frac * 360;
      // An item can bring its own colour — an estimator keeps the same one in
      // every chart, so the eye can follow a person across the page.
      var color = d.color || PALETTE[i % PALETTE.length];
      var a0 = a + GAP_DEG / 2, a1 = a + sweep - GAP_DEG / 2;
      if (a1 > a0) {
        slices += '<g class="ch-mark" data-idx="' + i + '" data-key="' + esc(d.key) + '">' +
          "<title>" + esc(d.label) + " · " + esc(fmt(d.value)) + " · " +
            fmtPct(frac) + "</title>" +
          '<path d="' + arcPath(C, C, R, INNER, a0, a1) + '" fill="' + color + '" />' + "</g>";
      }
      a += sweep;
      legend += '<li><span class="sw" style="background:' + color + '"></span>' +
        '<span class="lg-l">' + esc(d.label) + "</span>" +
        '<span class="lg-v">' + esc(fmt(d.value)) + "</span>" +
        '<span class="lg-p">' + fmtPct(frac) + "</span></li>";
    }
    return '<div class="ch-donut">' +
      '<svg viewBox="0 0 ' + SZ + " " + SZ + '" width="' + SZ + '" height="' + SZ +
        '" role="img" aria-label="' + esc(opts.aria || "Share of total") + '">' + slices + "</svg>" +
      '<ul class="ch-legend">' + legend + "</ul></div>";
  }

  function arcPath(cx, cy, r, ri, a0, a1) {
    var rad = Math.PI / 180;
    var x0 = cx + r * Math.cos(a0 * rad), y0 = cy + r * Math.sin(a0 * rad);
    var x1 = cx + r * Math.cos(a1 * rad), y1 = cy + r * Math.sin(a1 * rad);
    var xi1 = cx + ri * Math.cos(a1 * rad), yi1 = cy + ri * Math.sin(a1 * rad);
    var xi0 = cx + ri * Math.cos(a0 * rad), yi0 = cy + ri * Math.sin(a0 * rad);
    var big = (a1 - a0) > 180 ? 1 : 0;
    // A full circle can't be drawn as one arc — split it.
    if (a1 - a0 >= 359.9) {
      return "M" + (cx + r) + "," + cy + "A" + r + "," + r + " 0 1 1 " + (cx - r) + "," + cy +
             "A" + r + "," + r + " 0 1 1 " + (cx + r) + "," + cy + "Z" +
             "M" + (cx + ri) + "," + cy + "A" + ri + "," + ri + " 0 1 0 " + (cx - ri) + "," + cy +
             "A" + ri + "," + ri + " 0 1 0 " + (cx + ri) + "," + cy + "Z";
    }
    return "M" + x0 + "," + y0 +
           "A" + r + "," + r + " 0 " + big + " 1 " + x1 + "," + y1 +
           "L" + xi1 + "," + yi1 +
           "A" + ri + "," + ri + " 0 " + big + " 0 " + xi0 + "," + yi0 + "Z";
  }

  /** The table view. Every chart can become one — it's the fallback that makes
   *  colour optional rather than load-bearing. */
  function listTable(opts) {
    var rows = opts.rows || [];
    if (!rows.length) return emptyNote(opts.empty);
    var cols = opts.columns || [];
    var head = cols.map(function (c) {
      return '<th' + (c.align === "right" ? ' class="r"' : "") + ">" + esc(c.label) + "</th>";
    }).join("");
    var body = rows.map(function (r, i) {
      var tds = cols.map(function (c) {
        // A row may hand over a ready-made cell — an estimator's coloured chip,
        // a stage pill — for the column the caller marks as `html`.
        var pre = c.html && r[c.html];
        if (pre) return '<td' + (c.align === "right" ? ' class="r"' : "") + ">" + pre + "</td>";
        var raw = r[c.key];
        var text = c.fmt ? (FMT[c.fmt] || String)(raw) : raw;
        var dot = (c.dot && r.color)
          ? '<span class="sw" style="background:' + esc(r.color) + '"></span>' : "";
        return '<td' + (c.align === "right" ? ' class="r"' : "") + ">" + dot + esc(text) + "</td>";
      }).join("");
      return '<tr class="ch-mark" data-idx="' + i + '" data-key="' + esc(r.key) + '">' + tds + "</tr>";
    }).join("");
    return '<div class="tablewrap"><table class="ch-table"><thead><tr>' + head +
      "</tr></thead><tbody>" + body + "</tbody></table></div>";
  }

  // A viewBox with the default (uniform) preserveAspectRatio: the chart scales to
  // its card without stretching the type. Non-uniform scaling would render every
  // label at a different width to the one it was measured at.
  function svg(w, h, aria, body) {
    return '<svg viewBox="0 0 ' + w + " " + h + '" width="100%" role="img" ' +
      'aria-label="' + esc(aria) + '" class="ch-svg">' + body + "</svg>";
  }

  return {
    PALETTE: PALETTE, SERIES: SERIES,
    esc: esc, fmtMoney: fmtMoney, fmtMoneyShort: fmtMoneyShort,
    fmtInt: fmtInt, fmtPct: fmtPct, niceMax: niceMax, truncate: truncate,
    bar: bar, hbar: hbar, line: line, donut: donut, listTable: listTable,
    emptyNote: emptyNote, meter: meter, tint: tint, darken: darken,
  };
});
