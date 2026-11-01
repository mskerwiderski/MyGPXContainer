// Route detail: Leaflet map with the track (arrows the way it goes) and a
// uPlot elevation profile. Hovering the profile moves a marker along the map.
// Colours come from the msk-ui tokens (read once on load); base maps and
// arrows from map_base.js. When "Reverse direction" swaps #track (app.js),
// map and profile are drawn again.
// Way types (#ways, waytypes.py): asked after the page shows when they are
// not known yet (data-ways-url); a click on a type lights its stretches up
// in its colour and dims the rest, a second click ends it.
(function () {
  "use strict";
  var tok = window.mgcTok;
  var ACCENT = tok("--accent", "#4f8cff"), OK = tok("--ok", "#22c55e"),
      DANGER = tok("--danger", "#ef4444"), MUTED = tok("--muted", "#888"),
      LINE = tok("--line", "#333"), FG = tok("--fg", "#eee");
  var mapEl = document.getElementById("map"), profEl = document.getElementById("profile");
  var map = null, plot = null, track = null, line = [], cum = [0], lit = null;

  function draw() {
    var data = JSON.parse(document.getElementById("track").textContent);
    if (map) { map.remove(); map = null; }
    if (plot) { plot.destroy(); plot = null; }

    // ---------- map ----------
    map = L.map(mapEl, { scrollWheelZoom: false });
    window.mgcBaseMap(map, JSON.parse(mapEl.dataset.bases));
    line = data.line;
    cum = [0];
    for (var k = 1; k < line.length; k++) cum.push(cum[k - 1] + step(line[k - 1], line[k]));
    lit = null;
    track = L.polyline(line, { color: ACCENT, weight: 4, opacity: 0.9 }).addTo(map);
    map.fitBounds(track.getBounds(), { padding: [24, 24] });
    window.mgcArrows(map, line, ACCENT);
    L.circleMarker(line[line.length - 1], { radius: 7, color: FG, weight: 2, fillColor: DANGER,
      fillOpacity: 1 }).addTo(map);
    L.circleMarker(line[0], { radius: 7, color: FG, weight: 2, fillColor: OK, fillOpacity: 1 })
      .addTo(map);
    var cursor = L.circleMarker(line[0], { radius: 6, color: FG, weight: 2, fillColor: ACCENT,
      fillOpacity: 1 });

    // ---------- elevation profile ----------
    var prof = data.profile;
    profEl.hidden = !prof.km.length;
    if (!prof.km.length) return;
    plot = new uPlot({
      width: width(), height: 180,
      legend: { show: false },
      cursor: { y: false, points: { size: 8, fill: ACCENT } },
      scales: { x: { time: false } },
      axes: [
        { stroke: MUTED, grid: { stroke: LINE, width: 1 }, ticks: { stroke: LINE },
          values: function (u, vals) { return vals.map(function (v) { return v + " km"; }); } },
        { stroke: MUTED, grid: { stroke: LINE, width: 1 }, ticks: { stroke: LINE }, size: 56,
          values: function (u, vals) { return vals.map(function (v) { return v + " m"; }); } }
      ],
      series: [{}, { stroke: ACCENT, width: 2, fill: ACCENT + "33" }],
      hooks: {
        setCursor: [function (u) {
          var i = u.cursor.idx;
          if (i == null) { if (map.hasLayer(cursor)) map.removeLayer(cursor); return; }
          cursor.setLatLng([prof.lat[i], prof.lon[i]]);
          if (!map.hasLayer(cursor)) cursor.addTo(map);
          cursor.setStyle({ opacity: 1, fillOpacity: 1 });
        }]
      }
    }, [prof.km, prof.ele], profEl);
  }
  function width() { return profEl.clientWidth - 2; }

  // ---------- way types ----------
  function step(a, b) {          // metres, flat-earth - enough to cut by shares
    var k = Math.cos(a[0] * Math.PI / 180), dy = b[0] - a[0], dx = (b[1] - a[1]) * k;
    return Math.sqrt(dx * dx + dy * dy) * 111320;
  }
  function cut(f0, f1) {         // the stretch of the line between two shares
    var total = cum[cum.length - 1], a = f0 * total, z = f1 * total, out = [];
    function at(i, d) {
      var t = cum[i + 1] > cum[i] ? (d - cum[i]) / (cum[i + 1] - cum[i]) : 0;
      return [line[i][0] + (line[i + 1][0] - line[i][0]) * t,
              line[i][1] + (line[i + 1][1] - line[i][1]) * t];
    }
    for (var i = 0; i < line.length - 1; i++) {
      if (cum[i + 1] < a) continue;
      if (cum[i] > z) break;
      if (!out.length) out.push(cum[i] >= a ? line[i] : at(i, a));
      if (cum[i + 1] <= z) out.push(line[i + 1]);
      else { out.push(at(i, z)); break; }
    }
    return out;
  }
  function unlight() {
    if (lit) { map.removeLayer(lit); lit = null; }
    if (track) track.setStyle({ color: ACCENT, opacity: 0.9 });
    document.querySelectorAll(".ways-row[aria-pressed=true]").forEach(function (b) {
      b.setAttribute("aria-pressed", "false");
    });
  }
  function light(btn) {
    var src = document.getElementById("ways-data");
    if (!src || !map) return;
    var data = JSON.parse(src.textContent), kind = btn.dataset.kind, key = btn.dataset.key;
    var entry = (data[kind] || []).filter(function (e) { return e.key === key; })[0];
    if (!entry) return;
    var color = getComputedStyle(btn.querySelector(".ways-swatch")).backgroundColor;
    unlight();
    btn.setAttribute("aria-pressed", "true");
    track.setStyle({ color: MUTED, opacity: 0.45 });       // the rest grey, whatever the colour
    lit = L.layerGroup(entry.parts.map(function (p) {
      return L.polyline(cut(p[0], p[1]), { color: color, weight: 7, opacity: 1,
        lineCap: "round", interactive: false });
    })).addTo(map);
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".ways-row");
    if (!btn) return;
    if (btn.getAttribute("aria-pressed") === "true") unlight(); else light(btn);
  });
  function askWays() {
    var panel = document.querySelector("[data-ways-url]");
    if (!panel || !window.mgc) return;
    var url = panel.dataset.waysUrl;
    panel.removeAttribute("data-ways-url");
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) { window.mgc.swapFrom(html, ["ways"]); })
      .catch(function () { /* the panel keeps saying it is working; a reload asks again */ });
  }

  draw();
  window.addEventListener("resize", function () {
    if (plot) plot.setSize({ width: width(), height: 180 });
  });
  document.addEventListener("mgc:swapped", function (e) {
    if (e.detail.ids.indexOf("track") >= 0) draw();
    else if (e.detail.ids.indexOf("ways") >= 0) unlight();
    askWays();
  });
  document.addEventListener("DOMContentLoaded", askWays);   // app.js defines mgc by then
})();
