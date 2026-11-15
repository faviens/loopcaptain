// Two small things, no library: reload the page when a loop's files change, and copy the protocol.
(function () {
  "use strict";
  var body = document.body;
  var url = body.getAttribute("data-pulse-url");
  var seen = body.getAttribute("data-pulse");
  var POLL_MS = 4000;

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
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (data && data.pulse !== seen && !busy()) window.location.reload();
      })
      .catch(function () { /* the board is restarting; the next poll tries again */ });
  }

  if (url) window.setInterval(poll, POLL_MS);

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
