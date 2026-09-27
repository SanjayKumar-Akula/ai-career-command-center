"use strict";
(function () { const form = document.getElementById("vault-upload-form"); const error = document.getElementById("resume-upload-error"); const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); /* Never trust an id when building a download URL: only a positive integer
   is allowed into the href, and only when the file actually exists. */
const resumeId = x => { const n = Number(x && x.id); return Number.isInteger(n) && n > 0 ? n : null; };
const atsTone = score => score >= 80 ? "green" : score >= 60 ? "amber" : "red";
const noValue = '<span class="muted-block">—</span>';
const actionBtn = (attr, id, cls, text, title, label) => `<button class="btn ${cls} btn-sm" data-${attr}="${id}" title="${title}" aria-label="${label}">${text}</button>`;
/* Row actions drive the existing resume endpoints. The id is re-validated by
   the click handlers, so only a positive integer can ever reach a URL. */
function rowActions(x, id) {
if (id === null) return "";
const name = esc(x.filename);
const buttons = [];
if (!x.is_primary) buttons.push(actionBtn("primary", id, "btn-outline", "Set primary", "Use this resume as your primary", `Set ${name} as primary resume`));
buttons.push(actionBtn("analyze", id, "btn-outline", "Re-analyze", "Analyze this resume again", `Re-analyze ${name}`));
buttons.push(actionBtn("delete", id, "btn-danger", "Delete", "Delete this resume", `Delete ${name}`));
return buttons.join(" ");
}
function row(x) {
const id = resumeId(x);
const raw = Number(x.ats_score);
const score = (x.ats_score === null || x.ats_score === undefined || isNaN(raw)) ? null : raw;
const ats = score === null ? noValue : `<span class="pill ${atsTone(score)}">${esc(score)}</span>`;
const primary = x.is_primary ? ' <span class="pill indigo">Primary</span>' : "";
const role = x.target_role ? esc(x.target_role) : noValue;
const action = (id !== null && x.has_file !== false)
? `<a class="btn btn-outline btn-sm" href="/api/resumes/${id}/download" download>Download</a>`
: '<span class="muted-block">File unavailable</span>';
return `<tr><td><strong>${esc(x.filename)}</strong>${primary}</td><td>${role}</td><td>${ats}</td><td>v${esc(x.version)}</td><td>${[action, rowActions(x, id)].filter(Boolean).join(" ")}</td></tr>`;
}
function render(items) { const area = document.getElementById("resume-vault"); area.innerHTML = items.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>File</th><th>Role</th><th>ATS</th><th>Version</th><th></th></tr></thead><tbody>${items.map(row).join("")}</tbody></table></div>` : '<div class="empty-state"><h3>No resumes yet</h3><p>Upload a text-based PDF to start ATS history and skill extraction.</p></div>'; document.getElementById("resume-vault-state").hidden = true; area.hidden = false; document.querySelectorAll("[data-primary]").forEach(btn => btn.addEventListener("click", async () => { const id = resumeId({id: btn.dataset.primary}); if (id === null) return; try { const result = await ccApi.post(`/api/resumes/${id}/primary`); render(result.data.resumes); ccToast?.("Primary resume updated"); } catch (e) { ccToast?.(e.message, "error"); } })); document.querySelectorAll("[data-analyze]").forEach(btn => btn.addEventListener("click", async () => { const id = resumeId({id: btn.dataset.analyze}); if (id === null) return; try { const result = await ccApi.post(`/api/resumes/${id}/analyze`); render(result.data.resumes); ccToast?.("Resume re-analyzed"); } catch (e) { ccToast?.(e.message, "error"); } })); document.querySelectorAll("[data-delete]").forEach(btn => btn.addEventListener("click", async () => { const id = resumeId({id: btn.dataset.delete}); if (id === null) return; if (!confirm("Delete this resume?")) return; try { const result = await ccApi.delete(`/api/resumes/${id}`); render(result.data.resumes); ccToast?.("Resume deleted"); } catch (e) { ccToast?.(e.message, "error"); } })); } async function load() { try { render((await ccApi.get("/api/resumes")).data.resumes); } catch (e) { document.getElementById("resume-vault-state").className = "form-error"; document.getElementById("resume-vault-state").textContent = e.message; } } form?.addEventListener("submit", async e => { e.preventDefault(); error.hidden = true; const data = new FormData(form); try { const result = await ccApi.post("/api/resumes", data); render(result.data.resumes); form.reset(); ccToast?.("Resume analyzed and saved"); } catch (e) { error.textContent = e.message; error.hidden = false; } }); load(); })();
