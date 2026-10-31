// Route list: filter panel toggle, list/map switch, "near me", and the
// overview map with every filtered route as a line (drawn again whenever
// app.js swaps #results). Without JS the panel simply stays open.
(function () {
  "use strict";
  var form = document.getElementById("filters");

  var panel = document.getElementById("filter-panel");
  var toggle = document.querySelector("[data-toggle=filter-panel]");
  if (panel && panel.hasAttribute("data-start-closed")) panel.hidden = true;

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-toggle=filter-panel]") && panel) {
      panel.hidden = !panel.hidden;
      toggle.setAttribute("aria-expanded", String(!panel.hidden));
      return;
    }
    var chip = e.target.closest("[data-folder]");
    if (chip && form) {
      form.elements.folder.value = chip.dataset.folder;
      form.requestSubmit();
      return;
    }
    if (e.target.closest("[data-select-toggle]")) {
      document.body.classList.toggle("selecting");
      if (!document.body.classList.contains("selecting")) clearSelection();
      count();
      return;
    }
    if (e.target.closest("[data-select-all]")) {
      var boxes = document.querySelectorAll("input[name=ids]");
      var all = Array.prototype.every.call(boxes, function (b) { return b.checked; });
      boxes.forEach(function (b) { b.checked = !all; });
      count();
      return;
    }
    // selecting: a tap on a card ticks it instead of opening the route
    var row = document.body.classList.contains("selecting") && e.target.closest(".route-table tbody tr");
    if (row && !e.target.matches("input[name=ids]")) {
      e.preventDefault();
      var box = row.querySelector("input[name=ids]");
      box.checked = !box.checked;
      count();
      return;
    }
    var sw = e.target.closest("[data-view-switch]");
    if (sw && form) {
      form.elements.view.value = sw.dataset.viewSwitch;
      document.querySelectorAll("[data-view-switch]").forEach(function (b) {
        b.classList.toggle("active", b === sw);
        b.setAttribute("aria-pressed", String(b === sw));
      });
      form.requestSubmit();
      return;
    }
    if (e.target.closest("[data-reset]") && form) {
      e.preventDefault();
      Array.prototype.forEach.call(form.elements, function (el) {
        if (el.name === "view" || !el.name) return;
        if (el.type === "checkbox") el.checked = false;
        else el.value = el.dataset.default || "";
      });
      form.requestSubmit();
      return;
    }
    var near = e.target.closest("[data-near-me]");
    if (near && form && navigator.geolocation) {
      near.classList.add("is-busy");
      navigator.geolocation.getCurrentPosition(function (pos) {
        near.classList.remove("is-busy");
        form.elements.place.value = "";
        form.elements.lat.value = pos.coords.latitude.toFixed(5);
        form.elements.lon.value = pos.coords.longitude.toFixed(5);
        form.elements.sort.value = "near";
        form.requestSubmit();
      }, function () {
        near.classList.remove("is-busy");
        if (window.mgc) window.mgc.toast(near.dataset.denied || "Location not available", "error");
      }, { timeout: 10000, maximumAge: 300000 });
    }
  });

  // ---------- selection ----------
  function clearSelection() {
    document.querySelectorAll("input[name=ids]").forEach(function (b) { b.checked = false; });
  }
  function count() {
    var n = document.querySelectorAll("input[name=ids]:checked").length;
    var label = document.querySelector(".bulk-count");
    if (label) label.textContent = label.dataset.countText.replace("{n}", n);
    document.querySelectorAll("[data-needs-selection]").forEach(function (b) { b.disabled = !n; });
  }
  document.addEventListener("change", function (e) {
    if (e.target.matches("input[name=ids]")) count();
  });
  // deleting several asks first; this listener comes before app.js's, which
  // sends nothing once the event is prevented
  document.addEventListener("submit", function (e) {
    var btn = e.submitter;
    if (!btn || btn.value !== "delete" || !btn.dataset.confirm) return;
    var n = document.querySelectorAll("input[name=ids]:checked").length;
    if (!window.confirm(btn.dataset.confirm.replace("{n}", n))) e.preventDefault();
  });
  document.addEventListener("mgc:swapped", function (e) {
    if (e.detail.ids.indexOf("results") < 0) return;
    // after a bulk action the selection mode ends; after filtering it stays
    if (document.querySelector("[data-bulk-done]")) document.body.classList.remove("selecting");
    count();
  });
  count();

  // ---------- overview map ----------
  var map = null;
  function draw() {
    var el = document.getElementById("overview-map");
    if (map) { map.remove(); map = null; }
    if (!el) return;
    var starts = JSON.parse(document.getElementById("starts").textContent);
    var tok = window.mgcTok, ACCENT = tok("--accent", "#4f8cff"), FG = tok("--fg", "#eee");
    // one colour per route, so overlapping ones stay apart (msk-ui tokens only)
    var COLORS = [ACCENT, tok("--accent-2", "#7b6cff"), tok("--ok", "#35c08a"),
                  tok("--warn", "#f0a020"), tok("--danger", "#ff5d57")];
    map = L.map(el, { scrollWheelZoom: false });
    window.mgcBaseMap(map, JSON.parse(el.dataset.bases));
    var bounds = L.latLngBounds([]);
    var lines = [];
    starts.forEach(function (s, i) {
      var color = COLORS[i % COLORS.length];
      var box = document.createElement("div");
      var a = document.createElement("a");
      a.href = "/routes/" + s.id; a.textContent = s.name; a.className = "pop-name";
      var meta = document.createElement("div");
      meta.className = "pop-meta";
      meta.textContent = s.km.toLocaleString(document.documentElement.lang) + " km"
        + (s.up != null ? " · ↗ " + s.up.toLocaleString(document.documentElement.lang) + " m" : "");
      box.appendChild(a); box.appendChild(meta);
      // the route itself; a wide invisible twin makes it easy to hit with a finger
      var line = L.polyline(s.line, { color: color, weight: 3, opacity: 0.8 }).addTo(map);
      var hit = L.polyline(s.line, { color: color, weight: 16, opacity: 0 }).addTo(map);
      hit.bindPopup(box);
      hit.on("mouseover", function () { line.setStyle({ weight: 6, opacity: 1 }); line.bringToFront(); });
      hit.on("mouseout", function () { line.setStyle({ weight: 3, opacity: 0.8 }); });
      lines.push(line);
      bounds.extend(line.getBounds());
    });
    // start points on top (several routes often share one: home)
    var seen = {};
    starts.forEach(function (s) {
      var k = s.lat.toFixed(4) + "," + s.lon.toFixed(4);
      if (seen[k]) return;
      seen[k] = true;
      L.circleMarker([s.lat, s.lon], { radius: 6, color: FG, weight: 2, fillColor: ACCENT,
        fillOpacity: 1, interactive: false }).addTo(map);
    });
    var center = JSON.parse(el.dataset.center);
    if (center) {
      var ring = L.circle(center, { radius: Number(el.dataset.radius) * 1000, color: ACCENT,
        weight: 1, fill: false, dashArray: "4 6", interactive: false }).addTo(map);
      bounds.extend(ring.getBounds());
    }
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 });
    else map.setView([48.14, 11.58], 9);
    // which way each route goes (after the view is set: the arrows need pixels)
    starts.forEach(function (s, i) {
      window.mgcArrows(map, s.line, COLORS[i % COLORS.length], 150);
    });
  }
  draw();
  document.addEventListener("mgc:swapped", function (e) {
    if (e.detail.ids.indexOf("results") >= 0) draw();
  });
})();
