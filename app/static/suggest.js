// Route suggestions (/suggest): loop or A to B, "My location", places and
// addresses while typing (/suggest/places, Photon), distance chips per sport
// group, a busy button while the server asks GraphHopper, and the map with the
// three routes in the colours of their cards (msk-ui tokens). The form goes out
// via fetch and swaps #suggestions (app.js).
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
  // typing clears them, so the server looks the text up itself.
  form.querySelectorAll("input[data-ac]").forEach(function (input) {
    var names = input.dataset.ac.split(",");
    var list = document.createElement("ul");
    list.className = "ac-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;
    input.parentNode.appendChild(list);
    var timer, seq = 0, active = -1, hits = [];

    function set(lat, lon) {
      form.elements[names[0]].value = lat; form.elements[names[1]].value = lon;
    }
    function close() { list.hidden = true; active = -1; }
    function choose(i) {
      var h = hits[i];
      if (!h) return;
      input.value = h.label;
      set(h.lat, h.lon);
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
      set("", "");
      if (input.name === "place") {
        var locate = form.querySelector("[data-locate]");
        if (locate) locate.classList.remove("active");
      }
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
  });

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
    [data.start, data.finish].forEach(function (pt, i) {
      if (!pt) return;
      L.circleMarker(pt, { radius: 7, color: tok("--fg", "#eee"), weight: 2,
        fillColor: i ? tok("--fg", "#222") : tok("--surface", "#fff"), fillOpacity: 1,
        interactive: false }).addTo(map);
    });
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });
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
