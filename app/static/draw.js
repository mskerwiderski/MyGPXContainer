// Editing a route's way on the map (/routes/{id}/draw, v1.6.0). The browser
// holds the points ([lat, lon], the way the route goes) and changes them:
//   reroute  tap the start and the end of a section, then where it should go
//            (or "without a detour") - over roads, or straight
//   delete   tap the start and the end, confirm: the section goes, the ends
//            are joined (over roads, or straight)
//   trim     tap a point: start or end there
//   extend   tap the map: on from the end (or the start) to there
// A tap on the route snaps to its nearest point (within SNAP_PX). Roads come
// from POST draw/leg (our GraphHopper), km/climb/profile from POST
// draw/preview (the elevation model). Undo/redo keep every state. Saving
// posts the points (drawing.py); leaving unsaved asks first.
(function () {
  "use strict";
  var root = document.getElementById("draw");
  if (!root) return;
  var data = JSON.parse(document.getElementById("draw-data").textContent);
  var steps = JSON.parse(root.dataset.steps);
  var base = location.pathname;                   // /routes/<id>/draw
  var SNAP_PX = 30, HISTORY = 60;
  var tok = window.mgcTok, ACCENT = tok("--accent", "#4f8cff"), WARN = tok("--warn", "#e7b53d"),
      DANGER = tok("--danger", "#ff5d57"), OK = tok("--ok", "#35c08a"), FG = tok("--fg", "#eee");

  var line = data.points.slice();                 // THE way; changed in place
  var past = [], future = [], saved = true;
  var sel = { a: null, b: null };                // indices on the line
  var busy = false;

  // ---------- map ----------
  var map = L.map(document.getElementById("draw-map"), { scrollWheelZoom: true });
  window.mgcBaseMap(map, JSON.parse(root.dataset.bases));
  var track = L.polyline(line, { color: ACCENT, weight: 4, opacity: 0.9 }).addTo(map);
  map.fitBounds(track.getBounds(), { padding: [24, 24] });
  var arrows = window.mgcArrows(map, line, ACCENT);
  var marks = L.layerGroup().addTo(map);
  var ends = L.layerGroup().addTo(map);

  function drawLine() {
    track.setLatLngs(line);
    arrows.redraw();
    ends.clearLayers();
    L.circleMarker(line[line.length - 1], { radius: 7, color: FG, weight: 2, fillColor: DANGER,
      fillOpacity: 1, interactive: false }).addTo(ends);
    L.circleMarker(line[0], { radius: 7, color: FG, weight: 2, fillColor: OK, fillOpacity: 1,
      interactive: false }).addTo(ends);
    drawMarks();
  }
  function drawMarks() {
    marks.clearLayers();
    if (sel.a !== null && sel.b !== null) {
      var lo = Math.min(sel.a, sel.b), hi = Math.max(sel.a, sel.b);
      L.polyline(line.slice(lo, hi + 1), { color: tool() === "delete" ? DANGER : WARN, weight: 8,
        opacity: 0.85, interactive: false }).addTo(marks);
    }
    [sel.a, sel.b].forEach(function (i) {
      if (i === null) return;
      L.circleMarker(line[i], { radius: 8, color: FG, weight: 2, fillColor: WARN, fillOpacity: 1,
        interactive: false }).addTo(marks);
    });
  }

  // ---------- tools and steps ----------
  function tool() { return document.querySelector("input[name=tool]:checked").value; }
  function straight() { return document.getElementById("straight").checked; }
  function where() { return document.querySelector("input[name=end]:checked").value; }
  function choices(names) {
    var box = document.getElementById("draw-choice");
    box.hidden = !names.length;
    box.querySelectorAll("[data-choice]").forEach(function (b) {
      b.hidden = names.indexOf(b.dataset.choice) < 0;
    });
  }
  function step() {
    var t = tool(), text, shown = [];
    if (busy) { text = steps.busy; }
    else if (t === "reroute") {
      text = sel.a === null ? steps.reroute1 : sel.b === null ? steps.reroute2 : steps.reroute3;
      if (sel.b !== null) shown = ["direct", "cancel"]; else if (sel.a !== null) shown = ["cancel"];
    } else if (t === "delete") {
      text = sel.a === null ? steps.delete1 : sel.b === null ? steps.delete2 : steps.delete3;
      if (sel.b !== null) shown = ["delete", "cancel"]; else if (sel.a !== null) shown = ["cancel"];
    } else if (t === "trim") {
      text = sel.a === null ? steps.trim1 : steps.trim2;
      if (sel.a !== null) shown = ["start", "end", "cancel"];
    } else {
      text = steps.extend1;
    }
    document.getElementById("draw-step").textContent = text;
    choices(busy ? [] : shown);
    root.querySelector(".draw-end").hidden = t !== "extend";
    drawMarks();
  }
  function reset() { sel = { a: null, b: null }; step(); }
  document.querySelectorAll("input[name=tool]").forEach(function (r) {
    r.addEventListener("change", reset);
  });

  // nearest point of the line to a tap, if close enough (screen pixels)
  function snap(latlng) {
    var p = map.latLngToLayerPoint(latlng), best = -1, bestD = Infinity;
    for (var i = 0; i < line.length; i++) {
      var d = p.distanceTo(map.latLngToLayerPoint(line[i]));
      if (d < bestD) { bestD = d; best = i; }
    }
    return bestD <= SNAP_PX ? best : null;
  }

  map.on("click", function (e) {
    if (busy) return;
    var t = tool(), at = [round(e.latlng.lat), round(e.latlng.lng)];
    if (t === "extend") { extend(at); return; }
    if ((t === "reroute" || t === "delete") && sel.b !== null) {
      if (t === "reroute") reroute(at);
      return;
    }
    var i = snap(e.latlng);
    if (i === null) return;
    if (sel.a === null) sel.a = i;
    else if (t !== "trim") sel.b = i;
    else sel.a = i;
    if (sel.b !== null && sel.b === sel.a) sel.b = null;
    step();
  });

  document.getElementById("draw-choice").addEventListener("click", function (e) {
    var b = e.target.closest("[data-choice]");
    if (!b) return;
    var c = b.dataset.choice;
    if (c === "cancel") reset();
    else if (c === "direct") reroute(null);
    else if (c === "delete") remove();
    else if (c === "start") change(line.slice(sel.a));
    else if (c === "end") change(line.slice(0, sel.a + 1));
  });

  // ---------- the edits ----------
  function round(x) { return Math.round(x * 1e6) / 1e6; }
  function section() { return [Math.min(sel.a, sel.b), Math.max(sel.a, sel.b)]; }

  // the way between points: over roads (draw/leg), or straight
  function way(points) {
    if (straight()) return Promise.resolve(points);
    busy = true; step();
    return fetch(base + "/leg", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ points: points })
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok || !j.points) throw new Error(j.problem || "HTTP " + r.status);
        return j.points;
      });
    }).finally(function () { busy = false; });
  }
  function failed(err) {
    if (window.mgc) window.mgc.toast(err.message, "error");
    step();
  }
  function reroute(via) {
    var s = section(), from = line[s[0]], to = line[s[1]];
    way(via ? [from, via, to] : [from, to]).then(function (mid) {
      change(line.slice(0, s[0]).concat(mid, line.slice(s[1] + 1)));
    }).catch(failed);
  }
  function remove() {
    var s = section();
    way([line[s[0]], line[s[1]]]).then(function (mid) {
      change(line.slice(0, s[0]).concat(mid, line.slice(s[1] + 1)));
    }).catch(failed);
  }
  function extend(at) {
    if (where() === "end") {
      way([line[line.length - 1], at]).then(function (more) {
        change(line.concat(more.slice(1)));
      }).catch(failed);
    } else {
      way([at, line[0]]).then(function (more) {
        change(more.slice(0, -1).concat(line));
      }).catch(failed);
    }
  }

  // ---------- states: change, undo, redo ----------
  function setLine(points) {
    line.length = 0;
    Array.prototype.push.apply(line, points);
    sel = { a: null, b: null };
    drawLine(); step(); figures();
  }
  function change(points) {
    if (points.length < 2) return;
    past.push(line.slice());
    if (past.length > HISTORY) past.shift();
    future = [];
    saved = false;
    setLine(points);
  }
  function buttons() {
    root.querySelector("[data-undo]").disabled = !past.length;
    root.querySelector("[data-redo]").disabled = !future.length;
    document.querySelectorAll("#draw-save button").forEach(function (b) { b.disabled = saved; });
  }
  root.querySelector("[data-undo]").addEventListener("click", function () {
    if (!past.length) return;
    future.push(line.slice());
    setLine(past.pop());
    saved = !past.length;
    buttons();
  });
  root.querySelector("[data-redo]").addEventListener("click", function () {
    if (!future.length) return;
    past.push(line.slice());
    setLine(future.pop());
    saved = false;
    buttons();
  });
  document.addEventListener("keydown", function (e) {
    if (!(e.ctrlKey || e.metaKey) || e.target.matches("input, textarea")) return;
    if (e.key === "z" && !e.shiftKey) { e.preventDefault(); root.querySelector("[data-undo]").click(); }
    if ((e.key === "z" && e.shiftKey) || e.key === "y") {
      e.preventDefault(); root.querySelector("[data-redo]").click();
    }
  });

  // ---------- figures and profile (draw/preview, debounced) ----------
  var timer, seq = 0;
  function figures() {
    buttons();
    clearTimeout(timer);
    timer = setTimeout(function () {
      var mine = ++seq;
      fetch(base + "/preview", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ points: line })
      }).then(function (r) { return r.json(); }).then(function (f) {
        if (mine !== seq || f.km === undefined) return;
        var num = function (x, d) {
          return x === null || x === undefined ? "–"
            : x.toLocaleString(document.documentElement.lang, { maximumFractionDigits: d || 0 });
        };
        root.querySelector("[data-stat=km]").textContent = num(f.km, 1) + " km";
        root.querySelector("[data-stat=up]").textContent = f.up === null ? "–" : num(f.up) + " m";
        root.querySelector("[data-stat=down]").textContent = f.down === null ? "–" : num(f.down) + " m";
        var shape = root.querySelector("[data-stat=loop]");
        shape.textContent = f.loop ? shape.dataset.loop : shape.dataset.oneway;
        profile(f.profile);
      }).catch(function () { /* the figures stay as they were */ });
    }, 300);
  }
  function profile(p) {
    var svg = document.getElementById("draw-profile");
    svg.hidden = !p || p.km.length < 2;
    if (svg.hidden) return;
    var lo = Math.min.apply(null, p.ele), hi = Math.max.apply(null, p.ele);
    var pad = Math.max(0, 60 - (hi - lo)) / 2; lo -= pad; hi += pad;
    var last = p.km[p.km.length - 1] || 1;
    var d = p.km.map(function (k, i) {
      return (i ? "L" : "M") + (k / last * 100).toFixed(2) + " " + (30 - (p.ele[i] - lo) / (hi - lo) * 30).toFixed(2);
    }).join(" ");
    svg.querySelector(".line").setAttribute("d", d);
    svg.querySelector(".area").setAttribute("d", d + " L100 30 L0 30 Z");
  }

  // ---------- saving, leaving ----------
  var form = document.getElementById("draw-save");
  form.addEventListener("submit", function () {
    form.elements.points.value = JSON.stringify(line);
    saved = true;
  });
  window.addEventListener("beforeunload", function (e) {
    if (!saved) { e.preventDefault(); e.returnValue = steps.unsaved; }
  });

  drawLine(); step(); figures();
})();
