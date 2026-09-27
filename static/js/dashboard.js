"use strict";
(function () { const $ = id => document.getElementById(id); const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); const empty = (title, text, link) => `<div class="empty-state"><h3>${title}</h3><p>${text}</p>${link ? `<a class="btn btn-outline btn-sm" href="${link[0]}">${link[1]}</a>` : ""}</div>`; const metric = (label, value, note) => `<article class="card metric-card"><span class="section-label">${label}</span><div class="metric-value">${esc(value)}</div><div class="metric-note">${esc(note)}</div></article>`; /* "Your career progress" — latest analysis vs the one before it. Every value
   comes from the saved history block; nothing is estimated in the browser. */
const asNumber = (value, suffix) => (value === null || value === undefined) ? "—" : `${value}${suffix || ""}`;
const tag = (text, tone) => `<span class="pill${tone ? " " + tone : ""}">${esc(text)}</span>`;
const changeTag = delta => (delta === null || delta === undefined) ? "" : tag(`${delta > 0 ? "+" : ""}${delta}`, delta > 0 ? "green" : delta < 0 ? "red" : "");
const nameTags = names => names.length ? names.map(n => tag(n, "indigo")).join(" ") : "None recorded";
const progressTile = (label, value, note) => `<article class="card metric-card"><span class="section-label">${label}</span><div class="metric-value">${esc(value)}</div><div class="metric-note">${note}</div></article>`;
const progressRow = (label, detail, right) => `<div class="data-row"><span><strong>${esc(label)}</strong><small>${detail}</small></span>${right || ""}</div>`;
function renderProgress(h, stats) {
  if (!h || !h.current) return empty("No analysis yet", (h && h.message) || "Upload your first resume to start tracking your progress over time.", ["/resume", "Upload resume"]);
  const current = h.current, previous = h.previous, skills = h.skills || {}, gaps = h.gaps || {}, road = h.roadmap_progress || {};
  const added = h.skills_added || [], removed = h.skills_removed || [], closed = h.gaps_closed || [], opened = h.gaps_opened || [];
  const previousSkills = (skills.previous_total === null || skills.previous_total === undefined) ? null : skills.previous_total;
  const roadmapNow = (road.current === null || road.current === undefined) ? null : road.current;
  const tiles = [
    progressTile("ATS score", asNumber(current.ats_score), previous ? `Previous ${esc(previous.ats_score)} ${changeTag(h.ats_delta)}` : "First analysis — no earlier score yet"),
    progressTile("Skills", asNumber(skills.current_total), previousSkills === null ? "Saved capabilities" : `Previous ${esc(previousSkills)} ${changeTag(skills.delta)}`),
    progressTile("Skill gaps", asNumber(gaps.current_missing), h.has_previous ? `${closed.length} closed · ${opened.length} new` : "Reported by your latest analysis"),
    progressTile("Roadmap", roadmapNow === null ? "—" : `${esc(roadmapNow)}%`, roadmapNow === null ? "No roadmap yet" : (road.has_previous ? `From ${esc(road.previous)}% ${changeTag(road.delta)}` : "Completion"))
  ];
  const when = current.created_at ? `${current.resume_name || "Resume"} · version ${current.version ?? "—"} · ${new Date(current.created_at).toLocaleDateString()}` : "";
  const head = (when ? `<p class="muted-block">Latest analysis: ${esc(when)}</p>` : "") + (h.has_previous ? "" : `<div class="notice">${esc(h.message || "Complete another resume analysis to see your progress over time.")}</div>`);
  const grid = `<div class="page-grid three">${tiles.join("")}</div>`;
  if (!h.has_previous) return head + grid;
  const rows = [progressRow("Skills added since last analysis", nameTags(added), tag(added.length, "indigo"))];
  if (removed.length) rows.push(progressRow("Skills removed since last analysis", nameTags(removed), tag(removed.length, "red")));
  rows.push(progressRow("Skill gaps closed", nameTags(closed), tag(closed.length, "green")));
  rows.push(progressRow("New skill gaps", nameTags(opened), tag(opened.length, "amber")));
  (h.factors || []).filter(f => f.delta).forEach(f => rows.push(progressRow(`${f.label} (score factor)`, `Previous ${esc(f.previous)} → current ${esc(f.current)}`, changeTag(f.delta))));
  if (h.activities_since_previous) rows.push(progressRow("Career actions logged", "Since your previous analysis", tag(h.activities_since_previous, "")));
  return head + grid + `<div class="data-list">${rows.join("")}</div>`;
}

/* "Current resume" — the newest (or primary) resume the dashboard already
   returns. Every value comes from the existing /api/dashboard payload and the
   download link points at the existing secure backend endpoint, which keeps its
   own authentication and ownership checks. The file is never fetched in JS. */
const resumeId = x => { const n = Number(x && x.id); return Number.isInteger(n) && n > 0 ? n : null; };
const dayLabel = iso => { if (!iso) return ""; const d = new Date(iso); return isNaN(d.getTime()) ? "" : d.toLocaleDateString(); };
const downloadUrl = id => `/api/resumes/${id}/download`;
const canDownload = x => resumeId(x) !== null && x.has_file !== false;
const pickCurrentResume = list => (list || []).find(x => x && x.is_primary) || (list || [])[0] || null;

function renderCurrentResume(d) {
  const box = $("current-resume-content");
  if (!box) return;
  const resume = pickCurrentResume(d.latest_resumes);
  const id = resumeId(resume);
  if (!resume || id === null) {
    box.innerHTML = empty("No resume yet", "Upload your first resume to unlock Career Intelligence.", ["/resume", "Upload resume"]);
    return;
  }
  const analysis = (d.history && d.history.current) || null;
  // Use the stored analysis date when it belongs to this very resume.
  const analysedOn = (analysis && analysis.resume_id === id) ? dayLabel(analysis.created_at) : "";
  const when = analysedOn || dayLabel(resume.created_at) || dayLabel(resume.updated_at);
  const ats = (resume.ats_score === null || resume.ats_score === undefined) ? "—" : `${resume.ats_score}/100`;
  const facts = [`Version ${resume.version ?? "—"}`, `ATS ${ats}`]
    .concat(when ? [`Analysed ${when}`] : []).join(" · ");
  const action = canDownload(resume)
    ? `<a class="btn btn-primary" href="${downloadUrl(id)}" download>Download resume</a>`
    : `<span class="metric-note">The original file is no longer available.</span>`;
  const badges = [resume.is_primary ? tag("Primary", "green") : "", resume.target_role ? tag(resume.target_role, "blue") : ""].filter(Boolean).join(" ");
  const details = badges
    ? `<div class="data-list"><div class="data-row"><span>${badges}</span><a class="btn btn-outline btn-sm" href="/resume">View all resumes</a></div></div>`
    : `<div class="data-list"><div class="data-row"><span></span><a class="btn btn-outline btn-sm" href="/resume">View all resumes</a></div></div>`;
  box.innerHTML = `<div class="data-list"><div class="data-row"><span><strong>${esc(resume.filename)}</strong><small>${esc(facts)}</small></span>${action}</div></div>` + details;
}

async function load() { try { const result = await ccApi.get("/api/dashboard"); const d = result.data; $("dashboard-metrics").innerHTML = [metric("ATS score", d.stats.ats_score || "—", d.stats.ats_score ? "Latest resume" : "Upload a resume to begin"), metric("Skills", d.stats.skills, "Saved capabilities"), metric("Skill gaps", d.stats.skill_gaps, d.stats.target_role || "Set a target role"), metric("Resumes", d.stats.resumes, "Saved versions"), metric("Roadmap", `${d.stats.roadmap_progress}%`, "Completion"), metric("Target role", d.stats.target_role || "Not set", "Career direction")].join(""); const readiness = d.readiness || {}; $("readiness-card").innerHTML = `<div class="ring-wrap"><div class="ring" style="--pct:${readiness.readiness || 0};--ring-color:var(--primary)" data-label="${readiness.readiness || 0}"></div><div><strong>${readiness.readiness || 0}/100 readiness</strong><p class="muted-block">ATS ${readiness.components?.ats || 0} · Skills ${readiness.components?.skills || 0} · Roadmap ${readiness.components?.roadmap || 0}</p></div></div>`; $("dashboard-insight").textContent = d.insight || "Your next best move will appear as your profile develops."; renderCurrentResume(d); $("dashboard-activity").innerHTML = d.recent_activity?.length ? `<ul class="data-list">${d.recent_activity.map(x => `<li class="data-row"><span><strong>${esc(x.message)}</strong><small>${new Date(x.created_at).toLocaleString()}</small></span></li>`).join("")}</ul>` : empty("No activity yet", "Upload a resume or add a skill to start your timeline.", ["/resume", "Open Resume Vault"]); $("dashboard-resumes").innerHTML = d.latest_resumes?.length ? `<ul class="data-list">${d.latest_resumes.map(x => { const rid = resumeId(x); const action = canDownload(x) ? `<a href="${downloadUrl(rid)}" download>Download</a>` : `<a href="/resume">View</a>`; return `<li class="data-row"><span><strong>${esc(x.filename)}</strong><small>Version ${x.version} · ATS ${x.ats_score ?? "—"}</small></span>${action}</li>`; }).join("")}</ul>` : empty("No resume yet", "Upload your first resume to unlock Career Intelligence.", ["/resume", "Upload resume"]); const progressBox = $("dashboard-progress"); if (progressBox) progressBox.innerHTML = renderProgress(d.history, d.stats); $("dashboard-state").hidden = true; $("dashboard-content").hidden = false; } catch (error) { $("dashboard-state").className = "form-error"; $("dashboard-state").textContent = error.message; } } load(); })();
