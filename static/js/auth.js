"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  const formError = (message) => { const el = $("form-error"); if (el) { el.textContent = message || ""; el.hidden = !message; } };
  const fieldErrors = (fields) => Object.entries(fields || {}).forEach(([key, value]) => { const el = document.querySelector(`[data-error="${key}"]`); if (el) el.textContent = value; });
  /* One shared loading state (ccBusy in api.js): spinner + label while in
     flight, disabled to block a double submit, always restored afterwards. */
  const busy = (form, on, busyText) => {
    const button = form && form.querySelector("button[type=submit]");
    ccBusy(button, on, busyText);
  };
  const json = (form) => Object.fromEntries(new FormData(form).entries());
  async function submit(form, url, next, busyText) { form.addEventListener("submit", async (event) => { event.preventDefault(); formError(""); fieldErrors({}); busy(form, true, busyText); try { await ccApi.post(url, json(form)); window.location.href = next; } catch (error) { fieldErrors(error.fields); formError(error.message); } finally { busy(form, false, busyText); } }); }
  const login = $("login-form"); if (login) submit(login, "/api/auth/login", window.AUTH_NEXT || "/home", "Signing in…");
  const signup = $("signup-form"); if (signup) submit(signup, "/api/auth/signup", "/home", "Creating account…");
  const forgot = $("forgot-form"); if (forgot) forgot.addEventListener("submit", async (event) => { event.preventDefault(); formError(""); busy(forgot, true, "Sending reset link…"); try { const result = await ccApi.post("/api/auth/forgot-password", json(forgot)); const success = $("form-success"); success.textContent = result.data.message; success.hidden = false; } catch (error) { fieldErrors(error.fields); formError(error.message); } finally { busy(forgot, false, "Sending reset link…"); } });
  const reset = $("reset-form"); if (reset) reset.addEventListener("submit", async (event) => { event.preventDefault(); formError(""); busy(reset, true, "Updating password…"); try { await ccApi.post("/api/auth/reset-password", { token: window.RESET_TOKEN || "", ...json(reset) }); window.location.href = "/login"; } catch (error) { fieldErrors(error.fields); formError(error.message); } finally { busy(reset, false, "Updating password…"); } });

  /* Password show/hide. Only the input's `type` is toggled, so the field's
     name, id, required flag, autocomplete and validation are untouched. */
  document.querySelectorAll('input[type="password"]').forEach((input) => {
    if (input.dataset.toggleReady) return;
    input.dataset.toggleReady = "1";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "link-btn";
    button.textContent = "Show";
    button.setAttribute("aria-label", "Show password");
    button.setAttribute("aria-controls", input.id || "");
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => {
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.textContent = show ? "Hide" : "Show";
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
      button.setAttribute("aria-pressed", show ? "true" : "false");
    });
    input.insertAdjacentElement("afterend", button);
  });
})();
