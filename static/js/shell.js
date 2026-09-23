"use strict";

(function () {
  const byId = (id) => document.getElementById(id);
  const toast = (message, type = "") => { const stack = byId("toast-stack"); if (!stack) return; const item = document.createElement("div"); item.className = `toast ${type}`; item.textContent = message; stack.appendChild(item); setTimeout(() => item.remove(), 4200); };
  window.ccToast = toast;
  const sidebar = byId("sidebar"); const scrim = byId("sidebar-scrim");
  const close = () => { sidebar?.classList.remove("open"); scrim?.classList.remove("visible"); };
  byId("sidebar-toggle")?.addEventListener("click", () => { sidebar?.classList.add("open"); scrim?.classList.add("visible"); }); byId("sidebar-close")?.addEventListener("click", close); scrim?.addEventListener("click", close);
  byId("logout-btn")?.addEventListener("click", async () => { try { await ccApi.post("/api/auth/logout"); location.href = "/"; } catch (error) { toast(error.message, "error"); } });
  const renderNotifications = (items) => { const list = byId("notif-list"); if (!list) return; list.innerHTML = items?.length ? items.map(n => `<li class="${n.is_read ? "read" : "unread"}"><span class="n-dot"></span><span>${escapeHtml(n.message)}<small class="n-time">${new Date(n.created_at).toLocaleString()}</small></span></li>`).join("") : '<li class="empty">No notifications yet.</li>'; };
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  byId("notif-toggle")?.addEventListener("click", async () => { const panel = byId("notif-panel"); if (!panel) return; panel.hidden = !panel.hidden; if (!panel.hidden) { try { const result = await ccApi.get("/api/notifications"); renderNotifications(result.data.notifications); byId("notif-badge").hidden = !result.data.unread; if (result.data.unread) byId("notif-badge").textContent = result.data.unread; } catch (error) { toast(error.message, "error"); } } });
  byId("notif-mark-all")?.addEventListener("click", async () => { try { await ccApi.post("/api/notifications/read-all"); byId("notif-badge").hidden = true; renderNotifications([]); } catch (error) { toast(error.message, "error"); } });
})();
