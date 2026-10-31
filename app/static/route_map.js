// Route detail: Leaflet map with the track and a uPlot elevation profile.
// Hovering the profile moves a marker along the map. Colours come from the
// msk-ui tokens (read once on load); base maps from map_base.js.
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("track").textContent);
  var tok = window.mgcTok;
  var ACCENT = tok("--accent", "#4f8cff"), OK = tok("--ok", "#22c55e"),
      DANGER = tok("--danger", "#ef4444"), MUTED = tok("--muted", "#888"),
      LINE = tok("--line", "#333"), FG = tok("--fg", "#eee");

  // ---------- map ----------
  var mapEl = document.getElementById("map");
  var map = L.map(mapEl, { scrollWheelZoom: false });
  window.mgcBaseMap(map, JSON.parse(mapEl.dataset.bases));

  var line = data.line;
  var track = L.polyline(line, { color: ACCENT, weight: 4, opacity: 0.9 }).addTo(map);
  L.circleMarker(line[line.length - 1], { radius: 7, color: FG, weight: 2, fillColor: DANGER,
    fillOpacity: 1 }).addTo(map);
  L.circleMarker(line[0], { radius: 7, color: FG, weight: 2, fillColor: OK, fillOpacity: 1 })
    .addTo(map);
  map.fitBounds(track.getBounds(), { padding: [24, 24] });
  var cursor = L.circleMarker(line[0], { radius: 6, color: FG, weight: 2, fillColor: ACCENT,
    fillOpacity: 1 });

  // ---------- elevation profile ----------
  var prof = data.profile, profEl = document.getElementById("profile");
  if (!prof.km.length) { profEl.hidden = true; return; }
  function width() { return profEl.clientWidth - 2; }
  var plot = new uPlot({
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
  window.addEventListener("resize", function () { plot.setSize({ width: width(), height: 180 }); });
})();
