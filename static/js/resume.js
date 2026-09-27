"use strict";
(function () { const form = document.getElementById("vault-upload-form"); const error = document.getElementById("resume-upload-error"); const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); /* Never trust an id when building a download URL: only a positive integer
   is allowed into the href, and only when the file actually exists. */
const resumeId = x => { const n = Number(x && x.id); return Number.isInteger(n) && n > 0 ? n : null; };
const atsTone = score => score >= 80 ? "green" : score >= 60 ? "amber" : "red";
const noValue = '<span class="muted-block">—</span>';
const DASH = "—";
const actionBtn = (attr, id, cls, text, title, label) => `<button class="btn ${cls} btn-sm" data-${attr}="${id}" title="${title}" aria-label="${label}">${text}</button>`;
/* Row actions drive the existing resume endpoints. The id is re-validated by
   the click handlers, so only a positive integer can ever reach a URL. */
function rowActions(x, id) {
if (id === null) return "";
const name = esc(x.filename);
const buttons = [];
if (openDetailId === id) buttons.push(actionBtn("detail", id, "btn-outline", "Hide details", "Hide this analysis", `Hide details for ${name}`));
else buttons.push(actionBtn("detail", id, "btn-outline", "Details", "Show the stored analysis", `Show details for ${name}`));
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
/* ---- Details panel: the stored analysis behind GET /api/resumes/<id> ------ */
let openDetailId = null;   // which resume the panel is currently showing
let lastItems = [];        // last rendered list, so the row labels can re-render
const FACTOR_ROWS = [["Keywords", "keyword_score"], ["Skills", "skills_score"],
                     ["Experience", "experience_score"], ["Education", "education_score"],
                     ["Formatting", "formatting_score"], ["Sections", "sections_score"]];
/* Insight lists hold plain strings OR objects such as {"skill": "…"}, so they
   are flattened to text — a value must never render as [object Object]. */
const listText = items => {
if (!Array.isArray(items)) return [];
return items.map(item => {
if (item === null || item === undefined) return "";
if (typeof item === "string") return item;
if (typeof item === "object") {
const v = item.skill || item.name || item.label || item.title || item.text || item.value;
return (typeof v === "string" || typeof v === "number") ? String(v) : "";
}
return String(item);
}).filter(Boolean);
};
const detailRow = (label, value) => `<div class="data-row"><span><strong>${esc(label)}</strong><small>${value}</small></span></div>`;
const detailListRow = (label, items) => { const text = listText(items); return detailRow(label, text.length ? text.map(t => esc(t)).join(", ") : noValue); };
const detailScore = v => (v === null || v === undefined || v === "" || isNaN(v)) ? esc(DASH) : esc(v);
function renderDetail(d) {
const data = d || {};
const resume = data.resume || {};
const analysis = data.analysis || null;              // null when never analyzed
const insights = (analysis && analysis.insights) || {};
const ai = analysis && analysis.ai_enhanced ? '<span class="pill green">AI enhanced</span>' : "";
const stamp = analysis && analysis.created_at ? new Date(analysis.created_at) : null;
const when = stamp && !isNaN(stamp) ? stamp.toLocaleDateString() : DASH;
const words = (resume.word_count === null || resume.word_count === undefined) ? DASH : resume.word_count;
const head = `<div class="data-row"><span><strong>${esc(resume.filename || "")}</strong><small>${esc(resume.target_role || DASH)}${resume.version ? " · v" + esc(resume.version) : ""}</small></span>${ai}</div>`;
const tiles = `<div class="page-grid two">`
+ `<article class="card metric-card"><span class="section-label">ATS score</span><div class="metric-value">${analysis ? detailScore(analysis.ats_score) : esc(DASH)}</div><div class="metric-note">Analysed ${esc(when)}</div></article>`
+ `<article class="card metric-card"><span class="section-label">Resume text</span><div class="metric-value">${esc(words)}</div><div class="metric-note">words extracted</div></article></div>`;
const rows = FACTOR_ROWS.map(([label, key]) => detailRow(label, analysis ? detailScore(analysis[key]) : noValue)).join("")
+ detailListRow("Strengths", insights.strengths)
+ detailListRow("Weaknesses", insights.weaknesses)
+ detailListRow("Missing skills", insights.missing_skills)
+ detailListRow("Improvement areas", insights.improvement_areas)
+ detailListRow("Detected skills (read-only)", data.detected_skills);
return head + tiles + `<div class="data-list">${rows}</div>`;
}
async function toggleDetail(btn) {
const id = resumeId({id: btn.dataset.detail});        // never trust the DOM value
if (id === null) return;
const box = document.getElementById("resume-detail");
if (!box) return;
if (openDetailId === id) {                            // hide: no API call
openDetailId = null;
box.hidden = true;
box.innerHTML = "";
render(lastItems);
return;
}
box.hidden = false;
box.innerHTML = '<div class="skeleton big"></div>';     // loading state
try {
const detail = (await ccApi.get(`/api/resumes/${id}`)).data;
openDetailId = id;
box.innerHTML = renderDetail(detail);
render(lastItems);                                    // row now reads "Hide details"
} catch (e) {
openDetailId = null;
box.hidden = true;
box.innerHTML = "";
ccToast?.(e.message, "error");                        // table left untouched
}
}
function render(items) { lastItems = items; const area = document.getElementById("resume-vault"); area.innerHTML = items.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>File</th><th>Role</th><th>ATS</th><th>Version</th><th></th></tr></thead><tbody>${items.map(row).join("")}</tbody></table></div>` : '<div class="empty-state"><h3>No resumes yet</h3><p>Upload a text-based PDF to start ATS history and skill extraction.</p></div>'; document.getElementById("resume-vault-state").hidden = true; area.hidden = false; document.querySelectorAll("[data-primary]").forEach(btn => btn.addEventListener("click", async () => { const id = resumeId({id: btn.dataset.primary}); if (id === null) return; try { const result = await ccApi.post(`/api/resumes/${id}/primary`); render(result.data.resumes); ccToast?.("Primary resume updated"); } catch (e) { ccToast?.(e.message, "error"); } })); document.querySelectorAll("[data-analyze]").forEach(btn => btn.addEventListener("click", async () => { const id = resumeId({id: btn.dataset.analyze}); if (id === null) return; try { const result = await ccApi.post(`/api/resumes/${id}/analyze`); render(result.data.resumes); ccToast?.("Resume re-analyzed"); } catch (e) { ccToast?.(e.message, "error"); } })); document.querySelectorAll("[data-delete]").forEach(btn => btn.addEventListener("click", async () => { const id = resumeId({id: btn.dataset.delete}); if (id === null) return; if (!confirm("Delete this resume?")) return; try { const result = await ccApi.delete(`/api/resumes/${id}`); render(result.data.resumes); ccToast?.("Resume deleted"); } catch (e) { ccToast?.(e.message, "error"); } })); document.querySelectorAll("[data-detail]").forEach(btn => btn.addEventListener("click", () => toggleDetail(btn))); } async function load() { try { render((await ccApi.get("/api/resumes")).data.resumes); } catch (e) { document.getElementById("resume-vault-state").className = "form-error"; document.getElementById("resume-vault-state").textContent = e.message; } } form?.addEventListener("submit", async e => { e.preventDefault(); error.hidden = true; const data = new FormData(form); try { const result = await ccApi.post("/api/resumes", data); render(result.data.resumes); form.reset(); ccToast?.("Resume analyzed and saved"); } catch (e) { error.textContent = e.message; error.hidden = false; } }); load(); })();
