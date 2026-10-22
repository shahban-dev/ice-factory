/* Ice Factory — small client-side helpers. */

(function () {
  // Send the CSRF token on every HTMX request (defence in depth: the
  // hx-headers attribute on <body> already sets it; this covers requests
  // built without it).
  document.body.addEventListener("htmx:configRequest", function (event) {
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
    if (match) {
      event.detail.headers["X-CSRFToken"] = decodeURIComponent(match[1]);
    }
  });

  // Show a toast on any failed HTMX request instead of failing silently.
  function showError(message) {
    var body = document.getElementById("errorToastBody");
    var toastEl = document.getElementById("errorToast");
    if (body) body.textContent = message || "Something went wrong.";
    if (toastEl && window.bootstrap) {
      bootstrap.Toast.getOrCreateInstance(toastEl).show();
    }
  }
  document.body.addEventListener("htmx:responseError", function (event) {
    if (event.detail.xhr.status === 403) {
      showError("You are not allowed to do that.");
    } else {
      showError("Request failed (" + event.detail.xhr.status + "). Please try again.");
    }
  });
  document.body.addEventListener("htmx:sendError", function () {
    showError("No connection. Please check your internet and try again.");
  });

  // Phone keyboards: numeric keypad for amounts, telephone keypad for
  // phone numbers. (Server-side rendering stays unchanged; this is a
  // progressive enhancement for touch devices.)
  document.querySelectorAll('input[type="number"]').forEach(function (input) {
    input.setAttribute("inputmode", "decimal");
  });
  document.querySelectorAll('input[name="phone"]').forEach(function (input) {
    input.setAttribute("inputmode", "tel");
    input.setAttribute("autocomplete", "tel");
  });

  // Register the service worker. It only serves the friendly no-connection
  // page; it never caches app pages or data.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () {
        /* PWA is a nice-to-have; the app works fine without it. */
      });
    });
  }
})();

  // Double-submit guard: on a slow phone, a second tap on Save is
  // easy. The first submit goes through untouched (so the clicked
  // button's name/value still posts, e.g. "Save and print"); any
  // later submit of the same form is stopped, and the buttons show
  // they are working. The server-side idempotency token is the real
  // guarantee — this only stops the accidental second tap. Only
  // plain POST forms are guarded; HTMX forms are left alone.
  document.querySelectorAll('form[method="post"]').forEach(function (form) {
    if (form.hasAttribute("hx-post") || form.hasAttribute("hx-get")) {
      return;
    }
    form.addEventListener("submit", function (event) {
      if (form.dataset.submitted === "true") {
        event.preventDefault();
        return;
      }
      form.dataset.submitted = "true";
      form.querySelectorAll('button[type="submit"], input[type="submit"]')
        .forEach(function (button) {
          button.classList.add("disabled");
          if (button.tagName === "BUTTON" && button.textContent.trim()) {
            button.textContent = "Saving…";
          }
        });
    });
  });
