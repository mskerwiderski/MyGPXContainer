// Route suggestions (/suggest): loop or A to B, "My location", places and
// addresses while typing (/suggest/places, Photon), distance chips per sport
// group, a busy button while the server asks GraphHopper, and the map with the
// three routes in the colours of their cards (msk-ui tokens). The form goes out
// via fetch and swaps #suggestions (app.js).
// Stops on the way (v1.3.0): any number, in order; each is a place field and a
// hidden "via" = "lat,lon,label" (lat/lon empty while nobody picked a hit).
// Drag the handle (mouse or finger, pointer events) or use the arrow keys on
// it to change the order; more than COLLAPSE_AT stops fold to the first and
// the last; "Pick on the map" opens a map where a tap adds a stop
// (/suggest/where names it from the local place list).
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
    var list = document.createElement("ul");
    list.className = "ac-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;
    input.parentNode.appendChild(list);
    var timer, seq = 0, active = -1, hits = [];

    function close() { list.hidden = true; active = -1; }
    function choose(i) {
      var h = hits[i];
      if (!h) return;
      input.value = h.label;
      onPick(h);
      close();
    }
    function mark(i) {
      active = i;
      list.querySelectorAll("li").forEach(function (li, j) { li.classList.toggle("active", j === i); });
    }
    function show(found) {
      hits = found;
      list.textContent = "";
      found.forEach(function (h, i) {
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        li.textContent = h.label;
        // pointerdown: before the input loses the focus (and the list closes)
        li.addEventListener("pointerdown", function (e) { e.preventDefault(); choose(i); });
        list.appendChild(li);
      });
      list.hidden = !found.length;
      active = -1;
    }
    input.addEventListener("input", function () {
      onType();
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 3) { close(); return; }
      timer = setTimeout(function () {
        var mine = ++seq;
        var url = "/suggest/places?q=" + encodeURIComponent(q);
        if (input.name !== "place" && form.elements.lat.value) {
          url += "&lat=" + form.elements.lat.value + "&lon=" + form.elements.lon.value;
        }
        fetch(url, { credentials: "same-origin" })
          .then(function (r) { return r.ok ? r.json() : []; })
          .then(function (found) { if (mine === seq) show(found); })
          .catch(function () { close(); });
      }, 250);
    });
    input.addEventListener("keydown", function (e) {
      if (list.hidden) return;
      if (e.key === "ArrowDown") { e.preventDefault(); mark(Math.min(active + 1, hits.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); mark(Math.max(active - 1, 0)); }
      else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(active); }
      else if (e.key === "Escape") { close(); }
    });
    input.addEventListener("blur", function () { setTimeout(close, 150); });
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
    if (e.target.closest(".stops-toggle button")) { expanded = !expanded; changed(); return; }
    if (e.target.closest("[data-stop-map]")) togglePickMap(e.target.closest("[data-stop-map]"));
  });

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

  // ---------- picking stops on the map ----------
  var pickMap = null, pickLayer = null;
  function togglePickMap(btn) {
    var el = document.getElementById("stops-map");
    el.hidden = !el.hidden;
    btn.setAttribute("aria-expanded", String(!el.hidden));
    btn.classList.toggle("active", !el.hidden);
    if (el.hidden || pickMap) { if (pickMap) pickMap.invalidateSize(); return; }
    pickMap = L.map(el, { scrollWheelZoom: false });
    window.mgcBaseMap(pickMap, JSON.parse(el.dataset.bases));
    pickLayer = L.layerGroup().addTo(pickMap);
    var lat = parseFloat(form.elements.lat.value), lon = parseFloat(form.elements.lon.value);
    pickMap.setView(isNaN(lat) ? [48.14, 11.58] : [lat, lon], 11);
    pickMap.on("click", function (e) {
      var url = "/suggest/where?lat=" + e.latlng.lat + "&lon=" + e.latlng.lng;
      fetch(url, { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (w) { if (w.label) addStop(w.label, w.lat, w.lon); });
    });
    drawPicks();
  }
  function drawPicks() {
    if (!pickMap) return;
    pickLayer.clearLayers();
    var tok = window.mgcTok, pts = [];
    var lat = parseFloat(form.elements.lat.value), lon = parseFloat(form.elements.lon.value);
    if (!isNaN(lat)) {
      L.circleMarker([lat, lon], { radius: 7, color: tok("--fg", "#eee"), weight: 2,
        fillColor: tok("--surface", "#fff"), fillOpacity: 1, interactive: false }).addTo(pickLayer);
      pts.push([lat, lon]);
    }
    stopItems().forEach(function (li, i) {
      var v = li.querySelector("input[name=via]").value.split(",");
      var a = parseFloat(v[0]), b = parseFloat(v[1]);
      if (isNaN(a) || isNaN(b)) return;
      pts.push([a, b]);
      L.marker([a, b], { interactive: false, keyboard: false, icon: L.divIcon({
        className: "stop-pin", iconSize: [22, 22], iconAnchor: [11, 11],
        html: "<span>" + (i + 1) + "</span>" }) }).addTo(pickLayer);
    });
    if (pts.length > 1) L.polyline(pts, { color: tok("--accent", "#4f8cff"), weight: 2,
      dashArray: "4 6", interactive: false }).addTo(pickLayer);
  }

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
