// Route detail: Leaflet map with the track (arrows the way it goes) and a
// uPlot elevation profile. Hovering the profile moves a marker along the map.
// Colours come from the msk-ui tokens (read once on load); base maps and
// arrows from map_base.js. When "Reverse direction" swaps #track (app.js),
// map and profile are drawn again.
(function () {
  "use strict";
  var tok = window.mgcTok;
  var ACCENT = tok("--accent", "#4f8cff"), OK = tok("--ok", "#22c55e"),
      DANGER = tok("--danger", "#ef4444"), MUTED = tok("--muted", "#888"),
      LINE = tok("--line", "#333"), FG = tok("--fg", "#eee");
  var mapEl = document.getElementById("map"), profEl = document.getElementById("profile");
  var map = null, plot = null;

  function draw() {
    var data = JSON.parse(document.getElementById("track").textContent);
    if (map) { map.remove(); map = null; }
    if (plot) { plot.destroy(); plot = null; }

    // ---------- map ----------
    map = L.map(mapEl, { scrollWheelZoom: false });
    window.mgcBaseMap(map, JSON.parse(mapEl.dataset.bases));
    var line = data.line;
    var track = L.polyline(line, { color: ACCENT, weight: 4, opacity: 0.9 }).addTo(map);
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

  draw();
  window.addEventListener("resize", function () {
    if (plot) plot.setSize({ width: width(), height: 180 });
  });
  document.addEventListener("mgc:swapped", function (e) {
    if (e.detail.ids.indexOf("track") >= 0) draw();
  });
})();
