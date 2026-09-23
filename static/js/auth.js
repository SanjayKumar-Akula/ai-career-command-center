"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  const formError = (message) => { const el = $("form-error"); if (el) { el.textContent = message || ""; el.hidden = !message; } };
  const fieldErrors = (fields) => Object.entries(fields || {}).forEach(([key, value]) => { const el = document.querySelector(`[data-error="${key}"]`); if (el) el.textContent = value; });
  const busy = (form, on) => { const button = form.querySelector("button[type=submit]"); if (!button) return; button.disabled = on; const label = button.querySelector(".btn-label"); if (label) label.textContent = on ? "Working…" : (button.dataset.label || label.textContent); };
  const json = (form) => Object.fromEntries(new FormData(form).entries());
  async function submit(form, url, next) { form.addEventListener("submit", async (event) => { event.preventDefault(); formError(""); fieldErrors({}); busy(form, true); try { await ccApi.post(url, json(form)); window.location.href = next; } catch (error) { fieldErrors(error.fields); formError(error.message); } finally { busy(form, false); } }); }
  const login = $("login-form"); if (login) submit(login, "/api/auth/login", window.AUTH_NEXT || "/dashboard");
  const signup = $("signup-form"); if (signup) submit(signup, "/api/auth/signup", "/dashboard");
  const forgot = $("forgot-form"); if (forgot) forgot.addEventListener("submit", async (event) => { event.preventDefault(); formError(""); busy(forgot, true); try { const result = await ccApi.post("/api/auth/forgot-password", json(forgot)); const success = $("form-success"); success.textContent = result.data.message; success.hidden = false; } catch (error) { fieldErrors(error.fields); formError(error.message); } finally { busy(forgot, false); } });
  const reset = $("reset-form"); if (reset) reset.addEventListener("submit", async (event) => { event.preventDefault(); formError(""); busy(reset, true); try { await ccApi.post("/api/auth/reset-password", { token: window.RESET_TOKEN || "", ...json(reset) }); window.location.href = "/login"; } catch (error) { fieldErrors(error.fields); formError(error.message); } finally { busy(reset, false); } });
})();
