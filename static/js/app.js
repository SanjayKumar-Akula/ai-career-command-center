/* ============================================================
   AI Career Guide & Resume Analyzer — frontend logic
   Vanilla JS + fetch. All dynamic text is HTML-escaped before
   rendering to keep the page safe (no raw AI/HTML injection).
   ============================================================ */
"use strict";

const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5 MB — matches the Flask limit
const API_TIMEOUT_MS = 150000;          // generous timeout for AI generation

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function showFieldError(fieldId, errorId, message) {
  const field = $(fieldId);
  const error = $(errorId);
  if (!field || !error) return;
  if (message) {
    error.textContent = message;
    error.hidden = false;
    field.setAttribute("aria-invalid", "true");
    field.setAttribute("aria-describedby", errorId);
  } else {
    error.textContent = "";
    error.hidden = true;
    field.removeAttribute("aria-invalid");
    field.removeAttribute("aria-describedby");
  }
}

function showFormError(errorId, message) {
  const box = $(errorId);
  if (!box) return;
  box.textContent = message || "";
  box.hidden = !message;
}

function setLoading(button, isLoading, busyText) {
  if (!button) return;
  const label = button.querySelector(".btn-label");
  if (isLoading) {
    button.dataset.originalLabel = label ? label.textContent : button.textContent;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    if (label) {
      label.innerHTML =
        '<span class="spinner" aria-hidden="true"></span> ' +
        escapeHtml(busyText || "Loading…");
    }
  } else {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    if (label) label.textContent = button.dataset.originalLabel || label.textContent;
  }
}

function scrollToResult(elementId) {
  const el = $(elementId);
  if (!el) return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
}

async function apiFetch(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* non-JSON response */ }
    if (!response.ok || (payload && payload.success === false)) {
      const message =
        payload && payload.error && payload.error.message
          ? payload.error.message
          : "The server could not process the request. Please try again.";
      const error = new Error(message);
      error.fields = payload && payload.error ? payload.error.fields : null;
      error.status = response.status;
      throw error;
    }
    return payload;
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("The request timed out. Please check your connection and try again.");
    }
    if (err instanceof TypeError) {
      throw new Error("Could not reach the server. Is Flask running? Restart it and try again.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

function skeletonHtml() {
  return (
    '<div class="card skeleton-card" role="status" aria-label="Loading results">' +
    '<div class="skeleton-title"></div>' +
    '<div class="skeleton-line w80"></div><div class="skeleton-line w60"></div>' +
    '<div class="skeleton-line w80"></div><div class="skeleton-line w40"></div>' +
    '<div class="skeleton-line w60"></div></div>'
  );
}

/* ---------- header health pill ---------- */
async function initHealthPill() {
  const pill = $("health-pill");
  const text = $("health-text");
  if (!pill || !text) return;
  try {
    const data = await apiFetch("/api/health");
    if (data && data.ai_configured) {
      pill.classList.add("ok");
      text.textContent = "AI connected";
    } else {
      pill.classList.add("bad");
      text.textContent = "AI key missing";
    }
  } catch (_) {
    pill.classList.add("bad");
    text.textContent = "Server offline";
  }
}

/* ---------- resume file input (validation + drag & drop) ---------- */
function initResumeFileInput() {
  const input = $("resume-input");
  const fileName = $("resume-file-name");
  const drop = $("resume-drop");
  if (!input || !fileName || !drop) return;

  const setFile = (file) => {
    showFieldError("resume-input", "resume-file-error", "");
    if (!file) {
      fileName.textContent = "Choose PDF";
      drop.classList.remove("has-file");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      showFieldError("resume-input", "resume-file-error",
        "Only PDF files are supported. Please choose a .pdf file.");
      input.value = "";
      fileName.textContent = "Choose PDF";
      drop.classList.remove("has-file");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      showFieldError("resume-input", "resume-file-error",
        "That file is larger than 5 MB. Please upload a smaller PDF.");
      input.value = "";
      fileName.textContent = "Choose PDF";
      drop.classList.remove("has-file");
      return;
    }
    fileName.textContent = file.name;
    drop.classList.add("has-file");
  };

  input.addEventListener("change", () => setFile(input.files && input.files[0]));

  ["dragenter", "dragover"].forEach((evt) =>
    drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((evt) =>
    drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.remove("dragover"); }));
  drop.addEventListener("drop", (e) => {
    const files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length) {
      try { input.files = files; } catch (_) { /* browser refuses — user can pick manually */ }
      setFile(files[0]);
    }
  });
}

/* ============================================================
   AI CAREER GUIDE
   ============================================================ */
function validateCareerForm() {
  const name = $("full-name").value.trim();
  const skills = $("skills").value.trim();
  const role = $("career-role").value.trim();
  let ok = true;

  showFieldError("full-name", "full-name-error", "");
  showFieldError("skills", "skills-error", "");
  showFieldError("career-role", "career-role-error", "");

  if (name.length < 2) {
    showFieldError("full-name", "full-name-error",
      "Please enter your full name (at least 2 characters).");
    ok = false;
  }
  if (!skills) {
    showFieldError("skills", "skills-error",
      "Please enter at least one skill (e.g., Python, SQL, HTML).");
    ok = false;
  }
  if (role.length < 3) {
    showFieldError("career-role", "career-role-error",
      "Please enter a target role (e.g., Software Developer).");
    ok = false;
  }
  return ok ? { full_name: name, skills: skills, target_role: role } : null;
}

function linkCards(items, wide) {
  const cards = (items || []).map((item) => {
    const url = escapeHtml(item.url || "#");
    const name = escapeHtml(item.name || "Resource");
    const desc = item.description
      ? '<span class="desc">' + escapeHtml(item.description) + "</span>"
      : "";
    return (
      '<a class="link-card" href="' + url + '" target="_blank" rel="noopener noreferrer">' +
      '<span class="name">' + name + " ↗</span>" + desc + "</a>"
    );
  }).join("");
  return '<div class="link-grid' + (wide ? " wide" : "") + '">' + cards + "</div>";
}

function renderCareerResult(data) {
  const area = $("career-result");
  const weeks = data.roadmap || {};

  const weekBlock = (key, num) => {
    const items = Array.isArray(weeks[key]) ? weeks[key] : [];
    const rows = items.map((item) => {
      if (typeof item === "string") return "<li>" + escapeHtml(item) + "</li>";
      const topic = escapeHtml(item.topic || item.title || "Focus");
      const tasks = escapeHtml(item.tasks || item.task || "");
      const practice = escapeHtml(item.practice || item.practise || "");
      return (
        "<li>" + topic +
        (tasks ? '<span class="subtle"><b>Tasks:</b> ' + tasks + "</span>" : "") +
        (practice ? '<span class="subtle"><b>Practice:</b> ' + practice + "</span>" : "") +
        "</li>"
      );
    }).join("");
    return (
      '<div class="week-card"><h4><span class="week-num" aria-hidden="true">' + num +
      "</span>Week " + num + "</h4>" +
      (rows ? '<ul class="week-lines">' + rows + "</ul>"
            : '<p class="muted">No items for this week.</p>') +
      "</div>"
    );
  };

  const gaps = (data.skill_gaps || []).map((g) => {
    if (typeof g === "string") return "<li>" + escapeHtml(g) + "</li>";
    const skill = escapeHtml(g.skill || g.name || "");
    const why = escapeHtml(g.why || g.reason || "");
    const priority = String(g.priority || "").toLowerCase();
    const cls = ["high", "medium", "low"].includes(priority) ? priority : "medium";
    return (
      '<li><span class="item-title">' + skill +
      (priority ? ' <span class="pill ' + cls + '">' + escapeHtml(priority) + "</span>" : "") +
      "</span>" + (why ? '<span class="subtle">' + why + "</span>" : "") + "</li>"
    );
  }).join("");

  const skills = (data.skills_analysis || []).map((s) => {
    if (typeof s === "string") return '<span class="chip">' + escapeHtml(s) + "</span>";
    const name = escapeHtml(s.skill || s.name || "");
    const level = String(s.level || "").toLowerCase();
    const cls = ["beginner", "intermediate", "advanced"].includes(level) ? " level-" + level : "";
    const comment = s.comment ? ' title="' + escapeHtml(s.comment) + '"' : "";
    return '<span class="chip' + cls + '"' + comment + ">" + name +
      (level ? " · " + escapeHtml(level) : "") + "</span>";
  }).join("");

  const tips = (data.pro_tips || data.tips || []).map((t) => "<li>" + escapeHtml(t) + "</li>").join("");

  area.innerHTML =
    '<div class="card result-card">' +
      '<h3><span class="icon">🧭</span>Personalized Career Overview</h3>' +
      '<p class="overview-text">' + escapeHtml(data.career_overview || "") + "</p>" +
    "</div>" +
    '<div class="card result-card">' +
      '<h3><span class="icon">🎯</span>Target Role &amp; Current Skills Analysis</h3>' +
      '<div class="result-header"><span class="chip">🎯 ' + escapeHtml(data.target_role || "Target role") + "</span></div>" +
      (skills ? '<div class="chip-row">' + skills + "</div>"
              : '<p class="muted">No skill analysis was returned.</p>') +
    "</div>" +
    '<div class="card result-card">' +
      '<h3><span class="icon">🧩</span>Skill Gaps</h3>' +
      (gaps ? '<ul class="item-list">' + gaps + "</ul>"
            : '<p class="muted">No skill gaps identified — great job!</p>') +
    "</div>" +
    '<div class="card result-card">' +
      '<h3><span class="icon">🗓️</span>30-Day Career Roadmap</h3>' +
      '<div class="roadmap-grid">' +
        weekBlock("week_1", 1) + weekBlock("week_2", 2) +
        weekBlock("week_3", 3) + weekBlock("week_4", 4) +
      "</div>" +
    "</div>" +
    (tips
      ? '<div class="card result-card"><h3><span class="icon">💡</span>Pro Tips</h3>' +
        '<ul class="item-list">' + tips + "</ul></div>"
      : "") +
    '<div class="card result-card">' +
      '<h3><span class="icon">📚</span>Recommended Learning Resources</h3>' +
      linkCards(data.resources || [], true) +
    "</div>" +
    '<div class="card result-card">' +
      '<h3><span class="icon">💼</span>Job Portals</h3>' +
      linkCards(data.job_portals || []) +
    "</div>";
}

async function handleCareerSubmit(event) {
  event.preventDefault();
  showFormError("career-form-error", "");
  const payload = validateCareerForm();
  if (!payload) {
    showFormError("career-form-error",
      "Please fill in all required fields before generating your plan.");
    return;
  }

  const button = $("career-submit");
  const area = $("career-result");
  setLoading(button, true, "Generating your plan…");
  area.innerHTML = skeletonHtml();
  scrollToResult("career-result");

  try {
    const data = await apiFetch("/api/career-guide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderCareerResult(data.data || {});
    scrollToResult("career-result");
  } catch (err) {
    area.innerHTML = "";
    if (err.fields) {
      Object.keys(err.fields).forEach((key) => {
        if (key === "full_name") showFieldError("full-name", "full-name-error", err.fields[key]);
        if (key === "skills") showFieldError("skills", "skills-error", err.fields[key]);
        if (key === "target_role") showFieldError("career-role", "career-role-error", err.fields[key]);
      });
    }
    showFormError("career-form-error", err.message);
  } finally {
    setLoading(button, false);
  }
}

/* ============================================================
   RESUME ANALYZER
   ============================================================ */
function validateResumeForm() {
  showFieldError("resume-input", "resume-file-error", "");
  showFieldError("resume-role", "resume-role-error", "");
  const file = $("resume-input").files && $("resume-input").files[0];
  const role = $("resume-role").value.trim();
  let ok = true;

  if (!file) {
    showFieldError("resume-input", "resume-file-error",
      "Please choose a PDF resume to upload.");
    ok = false;
  }
  if (role.length < 3) {
    showFieldError("resume-role", "resume-role-error",
      "Please enter a target role (e.g., Software Developer).");
    ok = false;
  }
  return ok ? file : null;
}

function ringSvg(score) {
  const radius = 66;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.min(Math.max(score, 0), 100);
  const offset = circumference * (1 - clamped / 100);
  const color = score >= 75 ? "#16a34a" : score >= 50 ? "#d97706" : "#dc2626";
  return (
    '<div class="ring-wrap" role="img" aria-label="ATS score ' + score + " out of 100\">" +
    '<svg viewBox="0 0 160 160" aria-hidden="true">' +
    '<defs><linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">' +
    '<stop offset="0" stop-color="' + color + '"/>' +
    '<stop offset="1" stop-color="' + color + '" stop-opacity="0.65"/>' +
    "</defs>" +
    '<circle class="ring-track" cx="80" cy="80" r="' + radius + '"/>' +
    '<circle class="ring-value" cx="80" cy="80" r="' + radius + '"' +
    ' stroke-dasharray="' + circumference + '" stroke-dashoffset="' + circumference + '"' +
    ' data-target-offset="' + offset.toFixed(1) + '"/>' +
    "</svg>" +
    '<div class="ring-label"><span class="ring-score">' + score +
    " <small>/ 100</small></span>" +
    '<span class="ring-caption">ATS Score</span></div></div>'
  );
}

function animateScore() {
  requestAnimationFrame(() => {
    const ring = document.querySelector(".ring-value");
    if (ring) ring.style.strokeDashoffset = ring.dataset.targetOffset;
    document.querySelectorAll(".bar-fill").forEach((bar) => {
      bar.style.width = bar.dataset.width;
    });
  });
}

function renderResumeResult(data) {
  const area = $("resume-result");
  const score = Number(data.ats_score) || 0;

  const breakdown = (data.score_breakdown || []).map((item) => {
    const pct = item.max ? Math.round((item.score / item.max) * 100) : 0;
    const low = pct < 55 ? " low" : "";
    return (
      '<div class="legend-item"><span class="name">' + escapeHtml(item.label) + "</span>" +
      '<span class="bar"><span class="bar-fill' + low + '" data-width="' +
      Math.max(0, Math.min(100, pct)) + '%"></span></span>' +
      '<span class="val">' + item.score + " / " + item.max + "</span>" +
      '<span class="legend-note">' + escapeHtml(item.note || "") + "</span></div>"
    );
  }).join("");

  const keywordChips = (list, cls) =>
    (list || []).map((k) => '<span class="chip ' + cls + '">' + escapeHtml(k) + "</span>").join("");
  const matched = keywordChips(data.matched_keywords, "hit");
  const missing = keywordChips(data.missing_keywords, "miss");

  const checks = (data.ats_checks || []).map((check) => {
    const status = ["pass", "fail", "warn"].includes(check.status) ? check.status : "warn";
    const icon = status === "pass" ? "✓" : status === "fail" ? "✗" : "!";
    return (
      '<li><span class="check-icon ' + status + '" aria-hidden="true">' + icon + "</span>" +
      "<span><b>" + escapeHtml(check.label) + "</b>" +
      (check.note ? '<span class="check-note">' + escapeHtml(check.note) + "</span>" : "") +
      "</span></li>"
    );
  }).join("");

  const strengths = (data.strengths || []).map((s) => "<li>" + escapeHtml(s) + "</li>").join("");
  const weaknesses = (data.weaknesses || []).map((s) => "<li>" + escapeHtml(s) + "</li>").join("");
  const missingSkills = (data.missing_skills || []).map((s) => {
    if (typeof s === "string") return "<li>" + escapeHtml(s) + "</li>";
    return (
      '<li><span class="item-title">' + escapeHtml(s.skill || "") + "</span>" +
      (s.why ? '<span class="subtle">' + escapeHtml(s.why) + "</span>" : "") + "</li>"
    );
  }).join("");
  const improvements = (data.improvement_areas || []).map((s) => {
    if (typeof s === "string") return "<li>" + escapeHtml(s) + "</li>";
    return (
      '<li><span class="item-title">' + escapeHtml(s.area || "") + "</span>" +
      (s.suggestion ? '<span class="subtle">' + escapeHtml(s.suggestion) + "</span>" : "") + "</li>"
    );
  }).join("");
  const recKeywords = keywordChips(data.recommended_keywords, "");

  area.innerHTML =
    (data.ai_notice
      ? '<div class="notice-banner">⚠️ ' + escapeHtml(data.ai_notice) + "</div>"
      : "") +
    '<div class="card result-card">' +
      '<div class="result-header"><h3><span class="icon">📊</span>ATS Score — ' +
        escapeHtml(data.target_role || "") + "</h3></div>" +
      '<div class="score-panel">' + ringSvg(score) +
        '<div class="score-legend">' + breakdown +
          '<p class="legend-note">Deterministic scoring — Keyword 30 · Skills 20 · Experience/Projects 15 · Education 10 · ATS Formatting 15 · Sections 10. The same resume always gets the same score.</p>' +
        "</div>" +
      "</div>" +
    "</div>" +
    '<div class="card result-card">' +
      '<h3><span class="icon">✅</span>ATS-Friendly Check</h3>' +
      '<ul class="check-list">' + checks + "</ul>" +
    "</div>" +
    '<div class="two-col">' +
      '<div class="card result-card"><h3><span class="icon">💪</span>Strengths</h3>' +
        '<ul class="item-list">' + (strengths || '<li class="muted">None identified.</li>') + "</ul></div>" +
      '<div class="card result-card"><h3><span class="icon">⚠️</span>Weaknesses</h3>' +
        '<ul class="item-list">' + (weaknesses || '<li class="muted">None identified.</li>') + "</ul></div>" +
    "</div>" +
    '<div class="card result-card"><h3><span class="icon">🧩</span>Missing Skills</h3>' +
      (missingSkills ? '<ul class="item-list">' + missingSkills + "</ul>"
                     : '<p class="muted">No missing skills identified.</p>') +
    "</div>" +
    '<div class="card result-card"><h3><span class="icon">🛠️</span>Resume Improvement Areas</h3>' +
      '<ul class="item-list">' + (improvements || '<li class="muted">No suggestions available.</li>') + "</ul>" +
    "</div>" +
    ((matched || missing)
      ? '<div class="card result-card"><h3><span class="icon">🔑</span>Target Role Keywords</h3>' +
        (matched ? '<p class="muted">Matched:</p><div class="chip-row">' + matched + "</div>" : "") +
        (missing ? '<p class="muted" style="margin-top:10px">Missing:</p><div class="chip-row">' + missing + "</div>" : "") +
        "</div>"
      : "") +
    (recKeywords
      ? '<div class="card result-card"><h3><span class="icon">🚀</span>Recommended Keywords to Add</h3>' +
        '<div class="chip-row">' + recKeywords + "</div></div>"
      : "") +
    (data.target_role_match
      ? '<div class="card result-card"><h3><span class="icon">🎯</span>Target Role Match</h3>' +
        '<p class="overview-text">' + escapeHtml(data.target_role_match) + "</p></div>"
      : "") +
    '<div class="card result-card"><h3><span class="icon">💼</span>Recommended Job Portals</h3>' +
      linkCards(data.job_portals || []) + "</div>" +
    '<div class="card result-card"><h3><span class="icon">📝</span>ATS-Friendly Resume Builders</h3>' +
      linkCards(data.resume_builder_links || [], true) + "</div>";

  animateScore();
}

async function handleResumeSubmit(event) {
  event.preventDefault();
  showFormError("resume-form-error", "");
  const file = validateResumeForm();
  if (!file) {
    showFormError("resume-form-error",
      "Please choose a PDF resume and enter a target role before analyzing.");
    return;
  }

  const button = $("resume-submit");
  const area = $("resume-result");
  const formData = new FormData();
  formData.append("resume", file);
  formData.append("target_role", $("resume-role").value.trim());

  setLoading(button, true, "Analyzing resume…");
  area.innerHTML = skeletonHtml();
  scrollToResult("resume-result");

  try {
    const data = await apiFetch("/api/resume-analyzer", {
      method: "POST",
      body: formData,
    });
    renderResumeResult(data.data || {});
    scrollToResult("resume-result");
  } catch (err) {
    area.innerHTML = "";
    if (err.fields) {
      if (err.fields.resume) showFieldError("resume-input", "resume-file-error", err.fields.resume);
      if (err.fields.target_role) showFieldError("resume-role", "resume-role-error", err.fields.target_role);
    }
    showFormError("resume-form-error", err.message);
  } finally {
    setLoading(button, false);
  }
}

/* ============================================================
   INIT
   ============================================================ */
function init() {
  initHealthPill();
  initResumeFileInput();
  const careerForm = $("career-form");
  if (careerForm) careerForm.addEventListener("submit", handleCareerSubmit);
  const resumeForm = $("resume-form");
  if (resumeForm) resumeForm.addEventListener("submit", handleResumeSubmit);
}

document.addEventListener("DOMContentLoaded", init);






