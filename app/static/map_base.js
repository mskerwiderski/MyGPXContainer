// Base maps shared by the route page, the overview and the suggestions: four keyless tile
// sets, picked with small preview tiles (MFC's pattern); the choice is kept
// per browser (mgc_map_base), otherwise the map follows the system mode.
(function () {
  "use strict";
  var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  var THUMBS = {
    map: "https://a.tile.openstreetmap.org/11/1088/710.png",
    satellite: ESRI + "World_Imagery/MapServer/tile/11/710/1088",
    terrain: "https://a.tile.opentopomap.org/11/1088/710.png",
    dark: ESRI + "Canvas/World_Dark_Gray_Base/MapServer/tile/11/710/1088"
  };

  window.mgcBaseMap = function (map, labels) {
    var bases = {
      map: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, attribution: "© OpenStreetMap contributors" }),
      satellite: L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", {
        maxZoom: 19, attribution: "Tiles © Esri — Maxar, Earthstar Geographics" }),
      terrain: L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
        maxZoom: 17, attribution: "© OpenTopoMap (CC-BY-SA), © OpenStreetMap" }),
      // Esri dark canvas: CARTO stamps its free tiles with "API KEY REQUIRED" (MFC)
      dark: L.layerGroup([
        L.tileLayer(ESRI + "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
          maxZoom: 19, maxNativeZoom: 16, attribution: "Tiles © Esri — Esri, DeLorme, HERE" }),
        L.tileLayer(ESRI + "Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {
          maxZoom: 19, maxNativeZoom: 16 })])
    };
    var start = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "map";
    try { var saved = localStorage.getItem("mgc_map_base"); if (bases[saved]) start = saved; }
    catch (e) { /* storage blocked */ }
    bases[start].addTo(map);

    var Thumbs = L.Control.extend({
      options: { position: "topright" },
      onAdd: function () {
        var box = L.DomUtil.create("div", "basethumbs leaflet-control");
        Object.keys(bases).forEach(function (name) {
          var btn = L.DomUtil.create("button", "basethumb" + (name === start ? " active" : ""), box);
          btn.type = "button";
          btn.title = (labels && labels[name]) || name;
          btn.setAttribute("aria-label", btn.title);
          btn.style.backgroundImage = "url('" + THUMBS[name] + "')";
          L.DomEvent.on(btn, "click", function () {
            Object.keys(bases).forEach(function (n) {
              if (n !== name && map.hasLayer(bases[n])) map.removeLayer(bases[n]);
            });
            if (!map.hasLayer(bases[name])) bases[name].addTo(map);
            try { localStorage.setItem("mgc_map_base", name); } catch (e) { /* blocked */ }
            Array.prototype.forEach.call(box.querySelectorAll(".basethumb"),
              function (x) { x.classList.toggle("active", x === btn); });
          });
          L.DomEvent.disableClickPropagation(btn);
        });
        return box;
      }
    });
    map.addControl(new Thumbs());
  };

  // Arrows along a route line, every `spacing` screen pixels, pointing the
  // way it goes (v1.1.0); drawn again after every zoom. Returns the layer.
  function arrowIcon(color, deg) {
    return L.divIcon({ className: "route-arrow", iconSize: [22, 22], iconAnchor: [11, 11],
      html: '<svg width="22" height="22" viewBox="-11 -11 22 22" style="transform:rotate(' +
        Math.round(deg) + 'deg)"><path d="M-6 -7 L8 0 L-6 7 L-2.5 0 Z" fill="' + color +
        '" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>' });
  }
  window.mgcArrows = function (map, line, color, spacing) {
    var group = L.layerGroup().addTo(map), gap = spacing || 110;
    function draw() {
      group.clearLayers();
      var pts = line.map(function (p) { return map.latLngToLayerPoint(p); });
      var next = gap / 2, run = 0;
      for (var i = 1; i < pts.length; i++) {
        var a = pts[i - 1], b = pts[i], d = a.distanceTo(b);
        while (d > 0 && run + d >= next) {
          var t = (next - run) / d;
          var at = L.point(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t);
          group.addLayer(L.marker(map.layerPointToLatLng(at), {
            icon: arrowIcon(color, Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI),
            interactive: false, keyboard: false }));
          next += gap;
        }
        run += d;
      }
    }
    map.on("zoomend", draw);
    draw();
    return group;
  };

  window.mgcTok = function (name, fallback) {
    return (getComputedStyle(document.documentElement).getPropertyValue(name) || "").trim()
      || fallback;
  };
})();
