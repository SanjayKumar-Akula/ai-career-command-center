"use strict";
(function () { const form = document.getElementById("vault-upload-form"); const error = document.getElementById("resume-upload-error"); const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); /* Never trust an id when building a download URL: only a positive integer
   is allowed into the href, and only when the file actually exists. */
const resumeId = x => { const n = Number(x && x.id); return Number.isInteger(n) && n > 0 ? n : null; };
const atsTone = score => score >= 80 ? "green" : score >= 60 ? "amber" : "red";
const noValue = '<span class="muted-block">—</span>';
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
return `<tr><td><strong>${esc(x.filename)}</strong>${primary}</td><td>${role}</td><td>${ats}</td><td>v${esc(x.version)}</td><td>${action}</td></tr>`;
}
function render(items) { const area = document.getElementById("resume-vault"); area.innerHTML = items.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>File</th><th>Role</th><th>ATS</th><th>Version</th><th></th></tr></thead><tbody>${items.map(row).join("")}</tbody></table></div>` : '<div class="empty-state"><h3>No resumes yet</h3><p>Upload a text-based PDF to start ATS history and skill extraction.</p></div>'; document.getElementById("resume-vault-state").hidden = true; area.hidden = false; } async function load() { try { render((await ccApi.get("/api/resumes")).data.resumes); } catch (e) { document.getElementById("resume-vault-state").className = "form-error"; document.getElementById("resume-vault-state").textContent = e.message; } } form?.addEventListener("submit", async e => { e.preventDefault(); error.hidden = true; const data = new FormData(form); try { const result = await ccApi.post("/api/resumes", data); render(result.data.resumes); form.reset(); ccToast?.("Resume analyzed and saved"); } catch (e) { error.textContent = e.message; error.hidden = false; } }); load(); })();
