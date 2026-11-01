// Route suggestions (/suggest): loop or A to B, "My location", places and
// addresses while typing (/suggest/places, Photon), distance chips per sport
// group, a busy button while the server asks GraphHopper, and the map with the
// three routes in the colours of their cards (msk-ui tokens). The form goes out
// via fetch and swaps #suggestions (app.js).
// Stops on the way (v1.3.0): any number, in order; each is a place field and a
// hidden "via" = "lat,lon,label" (lat/lon empty while nobody picked a hit).
// Drag the handle (mouse or finger, pointer events) or use the arrow keys on
// it to change the order; more than COLLAPSE_AT stops fold to the first and
// the last. Each stop's "⋯" menu makes it the start or the destination - they
// swap places, nothing is lost.
// "Choose on the map" (v1.3.2): one map for start, stops and destination; the
// switch above it says what a tap sets and moves on by itself (start ->
// destination -> stops); /suggest/where names a tapped point from the local
// place list.
(function () {
  "use strict";
  var form = document.getElementById("suggest-form");
  if (!form) return;

  // ---------- loop or A to B: only the fields of the kind count ----------
  function kind() {
    var checked = form.querySelector("input[name=kind]:checked");
    return checked ? checked.value : "loop";
  }
  function showKind() {
    var k = kind();
    form.querySelectorAll("[data-kind]").forEach(function (box) {
      box.hidden = box.dataset.kind !== k;
      box.querySelectorAll("input").forEach(function (i) { i.disabled = box.hidden; });
    });
    document.querySelectorAll("[data-kind-only]").forEach(function (el) {
      el.hidden = el.dataset.kindOnly !== k;
    });
    setMode(nextMode());          // e.g. A to B without a destination: a tap sets it
    drawPicks();
  }
  form.addEventListener("change", function (e) { if (e.target.name === "kind") showKind(); });

  // ---------- my location ----------
  document.addEventListener("click", function (e) {
    var locate = e.target.closest("[data-locate]");
    if (locate && navigator.geolocation) {
      locate.classList.add("is-busy");
      navigator.geolocation.getCurrentPosition(function (pos) {
        locate.classList.remove("is-busy");
        locate.classList.add("active");
        form.elements.place.value = "";
        form.elements.lat.value = pos.coords.latitude.toFixed(5);
        form.elements.lon.value = pos.coords.longitude.toFixed(5);
      }, function () {
        locate.classList.remove("is-busy");
        if (window.mgc) window.mgc.toast(locate.dataset.denied || "Location not available", "error");
      }, { timeout: 10000, maximumAge: 300000 });
    }
    var chip = e.target.closest("[data-km]");
    if (chip) { form.elements.km.value = chip.dataset.km; markChips(); }
  });

  // the chip of the distance typed or picked stands out
  function markChips() {
    form.querySelectorAll("[data-km]").forEach(function (c) {
      c.classList.toggle("active", c.dataset.km === form.elements.km.value);
    });
  }
  form.elements.km.addEventListener("input", markChips);
  markChips();

  // ---------- places and addresses while typing ----------
  // input[data-ac="latName,lonName"]: picking a hit fills these hidden fields;
  // typing clears them, so the server looks the text up itself. A stop gets
  // the same with its own pick/type handlers (autocomplete()).
  form.querySelectorAll("input[data-ac]").forEach(function (input) {
    var names = input.dataset.ac.split(",");
    autocomplete(input, function (h) {
      form.elements[names[0]].value = h.lat; form.elements[names[1]].value = h.lon;
    }, function () {
      form.elements[names[0]].value = ""; form.elements[names[1]].value = "";
      if (input.name === "place") {
        var locate = form.querySelector("[data-locate]");
        if (locate) locate.classList.remove("active");
      }
    });
  });

  function autocomplete(input, onPick, onType) {
    mskAutocomplete(input, {
      onPick: onPick,
      onType: onType,
      url: function (q) {
        var url = "/suggest/places?q=" + encodeURIComponent(q);
        if (input.name !== "place" && form.elements.lat.value) {
          url += "&lat=" + form.elements.lat.value + "&lon=" + form.elements.lon.value;
        }
        return url;
      }
    });
  }

  // ---------- stops on the way ----------
  var COLLAPSE_AT = 5;
  var stops = document.getElementById("stops"), expanded = false;
  function stopItems() { return Array.prototype.slice.call(stops.querySelectorAll("li.stop")); }
  function wire(li) {
    var input = li.querySelector(".stop-input"), value = li.querySelector("input[name=via]");
    autocomplete(input, function (h) {
      value.value = h.lat + "," + h.lon + "," + h.label;
      changed();
    }, function () { value.value = ",," + input.value.trim(); });
  }
  function addStop(label, lat, lon) {
    var li = document.getElementById("stop-tpl").content.firstElementChild.cloneNode(true);
    stops.appendChild(li);
    wire(li);
    if (label) {
      li.querySelector(".stop-input").value = label;
      li.querySelector("input[name=via]").value = lat + "," + lon + "," + label;
    }
    changed();
    return li;
  }
  // numbers, folding, the hint, the markers on the pick map
  function changed() {
    var items = stopItems(), n = items.length;
    var fold = n >= COLLAPSE_AT && !expanded;
    items.forEach(function (li, i) {
      li.querySelector(".stop-no").textContent = i + 1;
      li.hidden = fold && i > 0 && i < n - 1;
    });
    var toggle = stops.querySelector(".stops-toggle");
    if (n >= COLLAPSE_AT) {
      if (!toggle) {
        toggle = document.createElement("li");
        toggle.className = "stops-toggle";
        toggle.innerHTML = '<button type="button" class="btn-ghost btn-sm"></button>';
      }
      var btn = toggle.firstElementChild;
      btn.textContent = expanded ? stops.dataset.less : stops.dataset.more.replace("{n}", n);
      btn.setAttribute("aria-expanded", String(expanded));
      if (fold) stops.insertBefore(toggle, items[n - 1]); else stops.appendChild(toggle);
    } else if (toggle) {
      toggle.remove();
    }
    document.getElementById("stops-hint").hidden = !n;
    drawPicks();
  }
  stopItems().forEach(wire);
  changed();

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-stop-add]")) {
      addStop().querySelector(".stop-input").focus();
      return;
    }
    var remove = e.target.closest(".stop-remove");
    if (remove) { remove.closest("li.stop").remove(); changed(); return; }
    var menuBtn = e.target.closest(".stop-menu-btn");
    if (menuBtn) { toggleMenu(menuBtn); return; }
    var as = e.target.closest("[data-stop-as]");
    if (as) {
      var li = as.closest("li.stop");
      closeMenus();
      swapWith(li, as.dataset.stopAs);
      changed();
      return;
    }
    if (!e.target.closest(".stop-menu")) closeMenus();
    if (e.target.closest(".stops-toggle button")) { expanded = !expanded; changed(); return; }
    if (e.target.closest("[data-pick-map]")) togglePickMap(e.target.closest("[data-pick-map]"));
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMenus(); });

  // ---------- a stop's "⋯" menu: start, destination, remove ----------
  function closeMenus() {
    document.querySelectorAll(".stop-menu").forEach(function (m) {
      m.hidden = true;
      m.previousElementSibling.setAttribute("aria-expanded", "false");
    });
  }
  function toggleMenu(btn) {
    var menu = btn.nextElementSibling, open = menu.hidden;
    closeMenus();
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    menu.querySelectorAll("[data-kind-only]").forEach(function (el) {
      el.hidden = el.dataset.kindOnly !== kind();
    });
    if (open) menu.querySelector("button:not([hidden])").focus();
  }
  // a point of the form: {label, lat, lon} (lat/lon "" when not picked)
  function endPoint(which) {
    var f = form.elements;
    if (which === "start") {
      var located = form.querySelector("[data-locate].active");
      return { label: f.place.value || (located && f.lat.value ? pick.dataset.myLocation : ""),
               lat: f.lat.value, lon: f.lon.value };
    }
    return { label: f.to_place.value, lat: f.to_lat.value, lon: f.to_lon.value };
  }
  function setEndPoint(which, p) {
    var f = form.elements;
    if (which === "start") {
      f.place.value = p.label; f.lat.value = p.lat; f.lon.value = p.lon;
      var locate = form.querySelector("[data-locate]");
      if (locate) locate.classList.remove("active");
    } else {
      f.to_place.value = p.label; f.to_lat.value = p.lat; f.to_lon.value = p.lon;
    }
  }
  function stopPoint(li) {
    var v = li.querySelector("input[name=via]").value.split(",");
    return { label: v.slice(2).join(",") || li.querySelector(".stop-input").value,
             lat: v[0] || "", lon: v[1] || "" };
  }
  function setStop(li, p) {
    li.querySelector(".stop-input").value = p.label;
    li.querySelector("input[name=via]").value = p.lat + "," + p.lon + "," + p.label;
  }
  // the stop becomes the start (or the destination); what was there takes
  // the stop's place in the list - or the stop goes, if there was nothing
  function swapWith(li, which) {
    var was = endPoint(which), now = stopPoint(li);
    setEndPoint(which, now);
    if (was.label || was.lat) setStop(li, was); else li.remove();
  }

  // drag the handle: mouse and finger alike (pointer events, no HTML5 drag,
  // which phones do not do); the arrow keys on the handle move one place
  var dragging = null;
  stops.addEventListener("pointerdown", function (e) {
    var handle = e.target.closest(".stop-handle");
    if (!handle) return;
    e.preventDefault();
    if (!expanded && stopItems().length >= COLLAPSE_AT) { expanded = true; changed(); }
    dragging = handle.closest("li.stop");
    dragging.classList.add("dragging");
    handle.setPointerCapture(e.pointerId);
  });
  stops.addEventListener("pointermove", function (e) {
    if (!dragging) return;
    var before = stopItems().filter(function (li) {
      if (li === dragging) return false;
      var r = li.getBoundingClientRect();
      return e.clientY < r.top + r.height / 2;
    })[0];
    if (before) { if (dragging.nextElementSibling !== before) stops.insertBefore(dragging, before); }
    else { var items = stopItems(); var last = items[items.length - 1];
      if (last !== dragging) stops.insertBefore(dragging, last.nextSibling); }
  });
  function drop() {
    if (!dragging) return;
    dragging.classList.remove("dragging");
    dragging = null;
    changed();
  }
  stops.addEventListener("pointerup", drop);
  stops.addEventListener("pointercancel", drop);
  stops.addEventListener("keydown", function (e) {
    var handle = e.target.closest(".stop-handle");
    if (!handle || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault();
    var li = handle.closest("li.stop"), items = stopItems(), i = items.indexOf(li);
    var j = e.key === "ArrowUp" ? i - 1 : i + 1;
    if (j < 0 || j >= items.length) return;
    if (j < i) stops.insertBefore(li, items[j]); else stops.insertBefore(li, items[j].nextSibling);
    changed();
    handle.focus();
  });

  // ---------- choosing points on the map ----------
  var pick = document.getElementById("pick"), pickMap = null, pickLayer = null;
  function pickMode() {
    var c = document.querySelector("input[name=pick]:checked");
    return c ? c.value : "stop";
  }
  function setMode(mode) {
    var r = document.querySelector("input[name=pick][value=" + mode + "]");
    if (r) r.checked = true;
  }
  // what a tap should set next: the start first, then (A to B) the
  // destination, then stops
  function nextMode() {
    if (!form.elements.lat.value && !form.elements.place.value) return "start";
    if (kind() === "oneway" && !form.elements.to_lat.value && !form.elements.to_place.value) {
      return "finish";
    }
    return "stop";
  }
  function togglePickMap(btn) {
    var box = document.getElementById("pick-box");
    box.hidden = !box.hidden;
    btn.setAttribute("aria-expanded", String(!box.hidden));
    btn.classList.toggle("active", !box.hidden);
    if (box.hidden) return;
    setMode(nextMode());
    if (pickMap) { pickMap.invalidateSize(); drawPicks(); return; }
    var el = document.getElementById("pick-map");
    pickMap = L.map(el, { scrollWheelZoom: false });
    window.mgcBaseMap(pickMap, JSON.parse(el.dataset.bases));
    pickLayer = L.layerGroup().addTo(pickMap);
    var lat = parseFloat(form.elements.lat.value), lon = parseFloat(form.elements.lon.value);
    pickMap.setView(isNaN(lat) ? [48.14, 11.58] : [lat, lon], 11);
    pickMap.on("click", function (e) {
      var mode = pickMode();
      fetch("/suggest/where?lat=" + e.latlng.lat + "&lon=" + e.latlng.lng,
            { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (w) {
          if (!w.label) return;
          if (mode === "stop") addStop(w.label, w.lat, w.lon);
          else { setEndPoint(mode, { label: w.label, lat: w.lat, lon: w.lon }); setMode(nextMode()); }
          drawPicks();
        });
    });
    drawPicks();
  }
  function pin(latlng, text, cls) {
    return L.marker(latlng, { interactive: false, keyboard: false, icon: L.divIcon({
      className: "stop-pin " + (cls || ""), iconSize: [22, 22], iconAnchor: [11, 11],
      html: "<span>" + text + "</span>" }) });
  }
  function drawPicks() {
    if (!pickMap) return;
    pickLayer.clearLayers();
    var tok = window.mgcTok, way = [];
    function at(p) { var a = parseFloat(p.lat), b = parseFloat(p.lon);
      return isNaN(a) || isNaN(b) ? null : [a, b]; }
    var start = at(endPoint("start")), finish = kind() === "oneway" ? at(endPoint("finish")) : null;
    if (start) { pin(start, "▶", "pin-start").addTo(pickLayer); way.push(start); }
    stopItems().forEach(function (li, i) {
      var p = at(stopPoint(li));
      if (p) { pin(p, String(i + 1)).addTo(pickLayer); way.push(p); }
    });
    if (finish) { pin(finish, "⚑", "pin-finish").addTo(pickLayer); way.push(finish); }
    else if (start && way.length > 1) way.push(start);           // a loop comes back
    if (way.length > 1) L.polyline(way, { color: tok("--accent", "#4f8cff"), weight: 2,
      dashArray: "4 6", interactive: false }).addTo(pickLayer);
  }
  // typing or picking in the start/destination field moves the pins too
  form.addEventListener("input", function () { setTimeout(drawPicks, 0); });

  // the chips and the longest route of the chosen sport
  form.elements.sport.addEventListener("change", function () {
    var opt = form.elements.sport.selectedOptions[0];
    var group = opt ? opt.dataset.group : "";
    form.querySelectorAll(".km-chips").forEach(function (c) { c.hidden = c.dataset.group !== group; });
    if (opt && opt.dataset.limit) {
      form.elements.km.max = opt.dataset.limit;
      form.querySelectorAll("[data-limit-hint]").forEach(function (p) {
        p.textContent = p.dataset.limitHint.replace("{max}", opt.dataset.limit);
      });
    }
  });

  var button = form.querySelector("button[type=submit]");
  form.addEventListener("submit", function () { button.classList.add("is-busy"); });

  // ---------- the map ----------
  var map = null;
  function draw() {
    button.classList.remove("is-busy");
    var el = document.getElementById("suggest-map");
    if (map) { map.remove(); map = null; }
    if (!el) return;
    var data = JSON.parse(document.getElementById("suggest-lines").textContent);
    var tok = window.mgcTok;
    var COLORS = [tok("--accent", "#4f8cff"), tok("--warn", "#f0a020"), tok("--ok", "#35c08a")];
    map = L.map(el, { scrollWheelZoom: false });
    window.mgcBaseMap(map, JSON.parse(el.dataset.bases));
    var bounds = L.latLngBounds([]);
    var lines = data.loops.map(function (lp, i) {
      var line = L.polyline(lp.line, { color: COLORS[i], weight: 4, opacity: 0.85 }).addTo(map);
      bounds.extend(line.getBounds());
      return line;
    });
    (data.stops || []).forEach(function (pt, i) {
      L.marker(pt, { interactive: false, keyboard: false, icon: L.divIcon({
        className: "stop-pin", iconSize: [22, 22], iconAnchor: [11, 11],
        html: "<span>" + (i + 1) + "</span>" }) }).addTo(map);
    });
    [data.start, data.finish].forEach(function (pt, i) {
      if (!pt) return;
      L.circleMarker(pt, { radius: 7, color: tok("--fg", "#eee"), weight: 2,
        fillColor: i ? tok("--fg", "#222") : tok("--surface", "#fff"), fillOpacity: 1,
        interactive: false }).addTo(map);
    });
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });
    data.loops.forEach(function (lp, i) { window.mgcArrows(map, lp.line, COLORS[i], 140); });
    // a card shows its route on top and thicker
    document.querySelectorAll(".suggest-card").forEach(function (card) {
      var line = lines[Number(card.dataset.index)];
      if (!line) return;
      card.addEventListener("mouseenter", function () { line.setStyle({ weight: 7, opacity: 1 }); line.bringToFront(); });
      card.addEventListener("mouseleave", function () { line.setStyle({ weight: 4, opacity: 0.85 }); });
    });
  }
  draw();
  document.addEventListener("mgc:swapped", function (e) {
    if (e.detail.ids.indexOf("suggestions") >= 0) draw();
  });
})();
