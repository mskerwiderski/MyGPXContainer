// "Send to Garmin" and "My Garmin": a box with data-all="<name>" ticks every
// box of that name (and follows them), buttons with data-needs-selection
// wait for a ticked "ids", and a button with data-confirm asks first ({n} =
// ticked "ids"). Its submit listener runs before app.js's, which sends
// nothing once the event is prevented.
(function () {
  "use strict";

  function boxes(name) {
    return Array.prototype.slice.call(document.querySelectorAll("input[name='" + name + "']"));
  }
  function update() {
    document.querySelectorAll("[data-all]").forEach(function (all) {
      var each = boxes(all.dataset.all);
      all.checked = each.length > 0 && each.every(function (b) { return b.checked; });
    });
    var n = boxes("ids").filter(function (b) { return b.checked; }).length;
    document.querySelectorAll("[data-needs-selection]").forEach(function (b) { b.disabled = !n; });
  }

  document.addEventListener("change", function (e) {
    var all = e.target.closest("[data-all]");
    if (all) boxes(all.dataset.all).forEach(function (b) { b.checked = all.checked; });
    update();
  });
  document.addEventListener("submit", function (e) {
    var btn = e.submitter;
    if (!btn || !btn.dataset.confirm) return;
    var n = boxes("ids").filter(function (b) { return b.checked; }).length;
    if (!window.confirm(btn.dataset.confirm.replace("{n}", n))) e.preventDefault();
  });
  document.addEventListener("mgc:swapped", function () { update(); check(); });
  update();

  // My Garmin comes at once with what is known; the state Garmin Connect
  // has now follows from data-check-url and is swapped in. A failed check
  // just drops the "Checking…" note - the page still shows the last state.
  function check() {
    var panel = document.querySelector("[data-check-url]");
    if (!panel || !window.mgc) return;
    var url = panel.dataset.checkUrl;
    panel.removeAttribute("data-check-url");
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw r; return r.text(); })
      .then(function (html) { window.mgc.swapFrom(html, [panel.id]); })
      .catch(function () {
        var note = panel.querySelector("[data-checking]");
        if (note) note.remove();
      });
  }
  // app.js (deferred) defines window.mgc before DOMContentLoaded
  document.addEventListener("DOMContentLoaded", check);
})();
