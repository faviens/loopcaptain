// A few small things, no library: reload the page when a loop's files change, show a message once,
// keep tabs and answers out of the browser's history, and copy the protocol.
(function () {
  "use strict";
  var body = document.body;
  var url = body.getAttribute("data-pulse-url");
  var seen = body.getAttribute("data-pulse");
  var POLL_MS = 4000;

  // A message shows once: out of the address it goes, so a reload or a copied link does not repeat it.
  var here = new URL(window.location.href);
  var shown = ["note", "error", "seal"].filter(function (name) { return here.searchParams.has(name); });
  if (shown.length && window.history.replaceState) {
    shown.forEach(function (name) { here.searchParams.delete(name); });
    window.history.replaceState(null, "", here.pathname + here.search + here.hash);
  }

  function busy() {
    // Never reload under someone who is typing an answer or reading a check's history.
    var typed = Array.prototype.some.call(document.querySelectorAll("textarea[name]"), function (field) {
      return field.value.trim() !== "" || field === document.activeElement;
    });
    return typed || document.querySelector("table.items details[open]") !== null;
  }

  function poll() {
    if (document.hidden) return;
    fetch(url, { cache: "no-store" })
      .then(function (response) {
        // 401: the board was started again and no longer knows this browser; the reload says so.
        if (response.status === 401) return { pulse: null };
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (data && data.pulse !== seen && !busy()) window.location.reload();
      })
      .catch(function () { /* the board is restarting; the next poll tries again */ });
  }

  if (url) window.setInterval(poll, POLL_MS);

  // A repository folded away on the first page stays folded across the page's own reloads.
  var FOLDED = "loopcaptain.folded";
  function folded() {
    try { return JSON.parse(window.localStorage.getItem(FOLDED) || "[]"); } catch (e) { return []; }
  }
  Array.prototype.forEach.call(document.querySelectorAll("details[data-fold]"), function (section) {
    var key = section.getAttribute("data-fold");
    if (folded().indexOf(key) !== -1) section.open = false;
    section.addEventListener("toggle", function () {
      var keys = folded().filter(function (name) { return name !== key; });
      if (!section.open) keys.push(key);
      try { window.localStorage.setItem(FOLDED, JSON.stringify(keys)); } catch (e) { /* private mode */ }
    });
  });

  // Back leads back: a tab, a round, an answer or a button replaces the page in the history instead of
  // adding one, so one press of Back from a loop's page reaches the list it was opened from.
  document.querySelectorAll("nav.tabs a, th.rnd a").forEach(function (link) {
    link.addEventListener("click", function (event) {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      window.location.replace(link.href);
    });
  });

  function sendTheOldWay(form, button) {
    // form.submit() leaves out the pressed button, which may carry the choice.
    if (button && button.name) {
      var carried = document.createElement("input");
      carried.type = "hidden";
      carried.name = button.name;
      carried.value = button.value;
      form.appendChild(carried);
    }
    form.submit();
  }

  if (window.fetch && window.FormData) {
    document.querySelectorAll('form[method="post"]').forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var data = new FormData(form);
        var button = event.submitter;
        if (button && button.name) data.append(button.name, button.value);
        if (button) button.disabled = true;
        fetch(form.action, { method: "POST", body: data, credentials: "same-origin" })
          .then(function (response) {
            if (response.ok && response.redirected) {
              window.location.replace(response.url);
            } else if (response.status >= 400 && response.status < 500) {
              // Refused, so nothing changed: send it the old way and show the board's own answer.
              sendTheOldWay(form, button);
            } else {
              // Something may have been written: show the page as it is now rather than send twice.
              window.location.reload();
            }
          })
          // The answer was lost, not the request: it may have been written, so never send it twice.
          .catch(function () { window.location.reload(); });
      });
    });
  }

  // Every copy button copies its own source and says so beside itself.
  if (navigator.clipboard) {
    document.querySelectorAll("[data-copy-from]").forEach(function (button) {
      button.addEventListener("click", function () {
        var source = document.getElementById(button.getAttribute("data-copy-from"));
        navigator.clipboard.writeText(source.value).then(function () {
          var done = button.parentNode.querySelector("[data-copied]");
          if (done) done.hidden = false;
        });
      });
    });
  }
})();
