// Phones: swipe a route card to the left and a red "Delete" button shows up
// on its right, like in iOS; a tap on it deletes the route without a page
// load (the list is fetched again and #results swapped, app.js). Only rows
// the user may delete carry data-swipe-delete. One row open at a time; a
// tap anywhere else closes it.
(function () {
  "use strict";
  var OPEN = -96, TRIGGER = -48;
  var open = null, drag = null;

  function setX(row, x, animate) {
    row.style.transition = animate ? "transform .18s ease" : "none";
    row.style.transform = x ? "translateX(" + x + "px)" : "";
  }
  function close(row) { if (row) setX(row, 0, true); if (open === row) open = null; }

  document.addEventListener("pointerdown", function (e) {
    if (e.pointerType !== "touch" || document.body.classList.contains("selecting")) return;
    var row = e.target.closest("tr[data-swipe-delete]");
    if (open && open !== row) close(open);
    if (!row || e.target.closest(".swipe-del")) return;
    drag = { row: row, x0: e.clientX, y0: e.clientY, base: row === open ? OPEN : 0, moved: false };
  });

  document.addEventListener("pointermove", function (e) {
    if (!drag || e.pointerType !== "touch") return;
    var dx = e.clientX - drag.x0, dy = e.clientY - drag.y0;
    if (!drag.moved) {
      if (Math.abs(dy) > 10 && Math.abs(dy) > Math.abs(dx)) { drag = null; return; }  // scrolling
      if (Math.abs(dx) < 8) return;
      drag.moved = true;
    }
    setX(drag.row, Math.max(OPEN - 30, Math.min(0, drag.base + dx)), false);
  });

  function end(e) {
    if (!drag) return;
    var d = drag; drag = null;
    if (!d.moved) return;
    var x = d.base + (e.clientX - d.x0);
    if (x < TRIGGER) { setX(d.row, OPEN, true); open = d.row; }
    else close(d.row);
    // a click the browser may send right after the swipe must not open the
    // route; there may be none, so the guard only lives briefly
    var guard = function (ev) {
      if (ev.target.closest(".swipe-del")) return;
      ev.preventDefault(); ev.stopPropagation();
    };
    d.row.addEventListener("click", guard, { capture: true, once: true });
    setTimeout(function () { d.row.removeEventListener("click", guard, { capture: true }); }, 350);
  }
  document.addEventListener("pointerup", end);
  document.addEventListener("pointercancel", end);

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".swipe-del");
    if (!btn) {
      if (open && e.target.closest("tr") === open) { e.preventDefault(); close(open); }
      return;
    }
    var row = btn.closest("tr[data-swipe-delete]");
    var box = row.closest("[data-deleted]");
    btn.classList.add("is-busy");
    fetch(row.dataset.swipeDelete, { method: "POST", credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        row.classList.add("swipe-gone");
        open = null;
        if (window.mgc) window.mgc.toast(box.dataset.deleted, "ok");
        return fetch(location.href, { credentials: "same-origin" }).then(function (r2) { return r2.text(); });
      })
      .then(function (html) { setTimeout(function () { window.mgc.swapFrom(html, ["results"]); }, 220); })
      .catch(function () {
        btn.classList.remove("is-busy");
        if (window.mgc) window.mgc.toast(box.dataset.deleteFailed, "error");
      });
  });
})();
