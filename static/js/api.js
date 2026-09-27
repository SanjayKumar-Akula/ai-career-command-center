"use strict";

(function () {
  const csrf = () => document.body?.dataset.csrf || "";
  async function request(url, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const headers = new Headers(options.headers || {});
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) headers.set("X-CSRF-Token", csrf());
    const response = await fetch(url, { ...options, method, headers, credentials: "same-origin" });
    let payload = null;
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok || (payload && payload.success === false)) {
      const error = new Error(payload?.error?.message || "The request could not be completed.");
      error.status = response.status; error.fields = payload?.error?.fields || {};
      throw error;
    }
    return payload;
  }
  window.ccApi = { request, get: (url) => request(url), post: (url, body) => request(url, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body || {}) }), put: (url, body) => request(url, { method: "PUT", body: JSON.stringify(body || {}) }), patch: (url, body) => request(url, { method: "PATCH", body: JSON.stringify(body || {}) }), delete: (url) => request(url, { method: "DELETE" }) };

  /* ---------------------------------------------------------------------
     One shared button loading state for the whole app (CSS in app.css).

     ccBusy(button, true, "Saving…")  -> spinner + meaningful label,
                                         disabled (no double submit),
                                         aria-busy, and the current width
                                         pinned so the button never jumps.
     ccBusy(button, false)            -> always restores the original label,
                                         width and enabled state, on both
                                         success and failure.
     --------------------------------------------------------------------- */
  const SPIN = '<span class="cc-spin" aria-hidden="true"></span>';
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c]));

  function ccBusy(button, on, busyText) {
    if (!button) return;
    const label = button.querySelector(".btn-label") || button;
    if (on) {
      if (button.dataset.ccBusy === "1") return;      // already in flight
      button.dataset.ccBusy = "1";
      button.dataset.ccLabel = label.textContent;
      if (button.offsetWidth) button.style.minWidth = button.offsetWidth + "px";
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      label.innerHTML = SPIN + " " + esc(busyText || "Loading…");
    } else {
      if (button.dataset.ccBusy !== "1") return;
      delete button.dataset.ccBusy;
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.style.minWidth = "";
      if (button.dataset.ccLabel !== undefined) label.textContent = button.dataset.ccLabel;
      delete button.dataset.ccLabel;
    }
  }

  window.ccBusy = ccBusy;
})();
