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
})();
