// Smoother pages without a framework (Michael 2026-10-27: a click must not
// reload the whole page or jump around).
//
// form[data-swap="id1,id2"]: sent with fetch; the server answers as always
// (redirect to a rendered page), and only the elements with these ids are
// taken from that page. A redirect to a DIFFERENT page (a new route, a
// sign-in) is followed normally. Without JS - or if fetch fails - the form
// is sent the classic way.
// form[data-auto]: sends itself on every change (text fields: after a pause)
// and keeps its state in the URL - without empty fields and without those
// still at their data-default.
// [data-sync-running] with data-refresh="ids": while something runs with
// Garmin, ask /garmin/status every 2 s and swap those ids once it is done -
// taken from data-refresh-url if set (a page sent by POST), else this page.
(function () {
  "use strict";

  function swapFrom(html, ids) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    ids.forEach(function (id) {
      var fresh = doc.getElementById(id), old = document.getElementById(id);
      if (fresh && old) old.replaceWith(document.importNode(fresh, true));
    });
    document.dispatchEvent(new CustomEvent("mgc:swapped", { detail: { ids: ids } }));
    watchSync();
  }

  function toast(text, kind) {
    var box = document.getElementById("toasts");
    if (!box) return;
    var t = document.createElement("div");
    t.className = "toast" + (kind ? " " + kind : "");
    t.textContent = text;
    box.appendChild(t);
    requestAnimationFrame(function () { t.classList.add("show"); });   // msk-ui fades it in
    setTimeout(function () { t.classList.remove("show"); }, 4500);
    setTimeout(function () { t.remove(); }, 5000);
  }

  var seq = 0;
  function send(form, submitter) {
    var ids = form.dataset.swap.split(",");
    var method = (form.getAttribute("method") || "get").toUpperCase();
    var data = new FormData(form);
    if (submitter && submitter.name) data.append(submitter.name, submitter.value);
    // the attribute, not form.action: a field named "action" shadows that property
    var url = new URL(form.getAttribute("action") || location.href, location.href).href;
    var opts = { method: method, credentials: "same-origin" };
    if (method === "GET") {
      var q = new URLSearchParams();
      Array.prototype.forEach.call(form.elements, function (el) {
        if (!el.name || el.disabled || el.value === "" || el.value === el.dataset.default) return;
        if ((el.type === "checkbox" || el.type === "radio") && !el.checked) return;
        if (el.type === "submit" || el.type === "button") return;
        q.append(el.name, el.value);
      });
      url = url.split("?")[0] + (q.toString() ? "?" + q : "");
    } else {
      opts.body = data;
    }
    var mine = ++seq;
    var busy = method === "GET" ? null : (submitter || form.querySelector("button[type=submit]"));
    if (busy) busy.classList.add("is-busy");
    return fetch(url, opts).then(function (r) {
      var to = new URL(r.url);
      if (r.redirected && (to.origin !== location.origin || to.pathname !== location.pathname)) {
        location.href = r.url;          // sent on to another page: go there
        return;
      }
      return r.text().then(function (html) {
        if (mine !== seq) return;       // an older answer that came late
        swapFrom(html, ids);
        if (method === "GET") history.replaceState(null, "", url);
      });
    }).finally(function () { if (busy) busy.classList.remove("is-busy"); });
  }

  // form[data-confirm]: asks first (no inline handlers - the pages run under
  // a Content-Security-Policy without 'unsafe-inline' scripts)
  document.addEventListener("submit", function (e) {
    var ask = e.target.dataset && e.target.dataset.confirm;
    if (ask && !e.defaultPrevented && !window.confirm(ask)) e.preventDefault();
  });
  // [data-select-on-focus]: a read-only field (an invitation link) is
  // selected as a whole when focused
  document.addEventListener("focusin", function (e) {
    if (e.target.matches && e.target.matches("[data-select-on-focus]")) e.target.select();
  });

  document.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-swap]");
    if (!form || e.defaultPrevented) return;
    e.preventDefault();
    send(form, e.submitter).catch(function () { form.submit(); });
  });

  // ---------- auto-submitting filter forms ----------
  var timer;
  function auto(form, delay) {
    clearTimeout(timer);
    timer = setTimeout(function () { form.requestSubmit(); }, delay);
  }
  document.addEventListener("change", function (e) {
    var form = e.target.closest("form[data-auto]");
    if (form) auto(form, 0);
  });
  document.addEventListener("input", function (e) {
    var form = e.target.closest("form[data-auto]");
    if (!form || e.target.type === "checkbox" || e.target.tagName === "SELECT") return;
    if (e.target.name === "place") {    // typing a place replaces "near me"
      form.elements.lat.value = ""; form.elements.lon.value = "";
    }
    auto(form, e.target.type === "search" || e.target.type === "number" ? 450 : 0);
  });

  // ---------- back links ----------
  // a[data-back="/path"]: if the page before was that page of this app, go
  // back in the history - the list keeps its filters and scroll position.
  // Otherwise (a shared link, the home-screen app) follow the href.
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[data-back]");
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey) return;
    var ref;
    try { ref = new URL(document.referrer); } catch (x) { return; }
    if (ref.origin === location.origin && ref.pathname === a.dataset.back && history.length > 1) {
      e.preventDefault();
      history.back();
    }
  });

  // ---------- polling a running Garmin sync ----------
  var polling = false;
  function watchSync() {
    var el = document.querySelector("[data-sync-running]");
    if (!el || polling) return;
    polling = true;
    (function tick() {
      setTimeout(function () {
        fetch("/garmin/status", { credentials: "same-origin" })
          .then(function (r) { return r.json(); })
          .then(function (s) {
            if (s.running) { tick(); return; }
            polling = false;
            return fetch(el.dataset.refreshUrl || location.href, { credentials: "same-origin" })
              .then(function (r) { return r.text(); })
              .then(function (html) { swapFrom(html, el.dataset.refresh.split(",")); });
          })
          .catch(function () { tick(); });
      }, 2000);
    })();
  }
  watchSync();

  window.mgc = { swapFrom: swapFrom, toast: toast };
})();
