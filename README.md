# AI Career Command Center

AI Career Command Center is a Flask-based career intelligence workspace for students and job seekers. It combines deterministic resume scoring with Google Gemini insights, persistent career data, skill-gap analysis, roadmaps, coaching, and fact-constrained resume generation.

The project preserves a public, anonymous Career Guide and Resume Analyzer while adding an authenticated command-center experience for saved profiles, skills, resumes, progress, history, and generated documents.

Project links: [GitHub repository](https://github.com/SanjayKumar-Akula/ai-career-command-center) · [Live project](https://sanjaykumar-akula.github.io/ai-career-command-center/)

## How It Works

1. Create an account and complete a career profile.
2. Add skills manually or extract them from an uploaded PDF resume.
3. Select a target role and compare saved skills with role requirements.
4. Review deterministic skill gaps and optional Gemini guidance.
5. Generate a personalized roadmap and track task progress.
6. Upload improved resume versions and compare ATS history.
7. Use the Career Coach and fact-constrained Resume Builder for next steps.
8. Download an ATS-friendly PDF or DOCX generated from the user's saved facts.

## Features

### Public career tools

- Career Guide with full name, skills, target role, career overview, skill analysis, skill gaps, four-week roadmap, pro tips, and curated links.
- Resume Analyzer for PDF uploads up to 5 MB.
- Deterministic ATS score from 0 to 100.
- AI-generated resume strengths, weaknesses, missing skills, improvements, and ATS checks.
- Trusted learning resources, job portals, and resume-builder links from `data/resources.json`.

### Authenticated command center

- Signup, login, logout, password reset, persistent sessions, and CSRF-protected writes.
- Persistent career profile with education, college, degree, graduation year, experience, target role, career goal, and job type.
- Resume Vault with PDF storage, versioning, primary-resume selection, re-analysis, downloads, detected skills, and ownership checks.
- Automatic deterministic skill extraction plus optional Gemini-assisted detection.
- Skill management with normalized catalog entries, source labels, proficiency, add/remove/update operations, and skill-growth history.
- Deterministic skill-gap analysis with cached AI enrichment.
- Personalized four-week and extended roadmap generation with task states and progress percentage.
- ATS analysis history and resume-to-resume comparison, including score, factor, keyword, skill, and gap changes.
- AI Career Coach with private per-user conversation history and deterministic fallback responses.
- Fact-constrained AI Resume Builder that does not invent employers, dates, qualifications, metrics, or achievements.
- ATS-friendly PDF and DOCX generation from validated user-provided content.
- Activity timeline and in-app notifications.
- Responsive authenticated SaaS shell with dashboard, sidebar navigation, loading states, empty states, error states, progress indicators, and mobile navigation.

## ATS Scoring

The numeric ATS score is computed in Python and does not depend on Gemini. The same resume text and target role produce the same score.

| Factor | Weight |
|---|---:|
| Target-role keyword match | 30 |
| Required skills match | 20 |
| Experience and project relevance | 15 |
| Education | 10 |
| ATS formatting signals | 15 |
| Section completeness | 10 |
| **Total** | **100** |

The scorer uses role data from `data/role_keywords.json`, checks measurable text signals, and clearly marks limitations such as tables, graphics, and columns that cannot be reliably assessed from extracted PDF text.

## AI Functionality

Google Gemini is used server-side for:

- Career Guide generation
- Resume qualitative insights
- Optional resume skill detection
- Skill-gap explanations and practice guidance
- Personalized roadmap generation
- AI Career Coach replies
- Resume Builder drafts

The AI client requests structured JSON, supports fenced JSON responses, validates unexpected response structures, handles invalid JSON, applies bounded retry and fallback behavior for temporary provider failures, and returns safe user-facing errors. URLs are never invented by the AI; trusted URLs are merged from local JSON data.

The browser never receives the Gemini API key and never calls Gemini directly.

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| Frontend | HTML5, CSS3, vanilla JavaScript, Fetch API |
| AI | Google Gemini REST API with provider/model fallback handling |
| ORM and database | Flask-SQLAlchemy, SQLite by default |
| PDF extraction and PDF generation | PyMuPDF (`pymupdf`/`fitz`) |
| DOCX generation | Local WordprocessingML ZIP generation; `python-docx` is included as a project dependency |
| Configuration | `python-dotenv` and `.env` |
| Static data | JSON role, skill, learning-resource, and job-portal catalogs |

> ReportLab is not currently used by the implementation. PDF generation is implemented with PyMuPDF, so ReportLab is intentionally not listed as an active dependency.

## Project Structure

```text
10k coders/
├── app.py                         # Flask app, legacy APIs, database and blueprint registration
├── requirements.txt               # Python dependencies
├── README.md
├── .env.example                   # Secret-free configuration template
├── .gitignore                     # Ignores .env, database, uploads, logs and environments
├── career_center.db               # Local SQLite database, created at runtime
├── data/
│   ├── resources.json             # Curated learning, job and resume-builder links
│   └── role_keywords.json         # ATS roles, aliases, keywords, skills and education terms
├── models/
│   └── __init__.py                # SQLAlchemy models and additive database initialization
├── routes/
│   ├── __init__.py                # Blueprint and API registration
│   ├── auth_api.py                # Signup, login, logout and password-reset APIs
│   ├── auth_pages.py              # Authentication page routes
│   ├── pages.py                   # Authenticated page routes
│   ├── api_helpers.py             # API response, CSRF, rate-limit and error helpers
│   ├── api_profile_skills.py      # Profile, skills and gap APIs
│   ├── api_resumes.py             # Resume Vault, detection, comparison and download APIs
│   ├── api_roadmap.py             # Roadmap, progress and resource APIs
│   └── api_misc.py                # Dashboard, history, notifications, coach and builder APIs
├── services/
│   ├── ai_client.py               # Gemini/OpenAI-compatible calls, retries and JSON parsing
│   ├── career_guide.py             # Career Guide prompt and response shaping
│   ├── resume_analyzer.py          # Deterministic ATS scoring and AI insights
│   ├── resume_store.py             # Persistent resume versions and analyses
│   ├── pdf_extractor.py            # PDF validation, extraction and text cleaning
│   ├── resume_pdf.py               # PDF and DOCX document generation
│   ├── resume_builder.py           # Fact-constrained resume drafting
│   ├── skill_service.py            # Skill catalog, extraction, CRUD and growth
│   ├── gap_engine.py               # Deterministic gaps and cached AI guidance
│   ├── roadmap_service.py          # Roadmap generation and task progress
│   ├── coach_service.py            # Private AI coach and fallback responses
│   ├── user_service.py             # Password hashing, sessions and reset tokens
│   ├── web_security.py             # Authentication decorators and CSRF protection
│   ├── activity_service.py         # Activity timeline, notifications and readiness
│   ├── resources.py                # Trusted JSON resource loader
│   ├── validation.py               # Input and upload validation
│   └── rate_limiter.py             # In-memory sliding-window rate limiter
├── templates/
│   ├── index.html                  # Public Career Guide and Resume Analyzer
│   ├── _app_base.html              # Authenticated application shell
│   ├── login.html, signup.html     # Authentication screens
│   ├── forgot_password.html
│   ├── reset_password.html
│   ├── dashboard.html, profile.html, settings.html
│   ├── skills.html, resume.html, roadmap.html
│   └── coach.html, history.html, resources.html
├── static/
│   ├── css/style.css                # Public-site styling
│   ├── css/app.css                  # Authenticated SaaS styling
│   └── js/                          # Shared shell, API, auth and page modules
└── uploads/
    └── .gitkeep                     # Runtime upload directory; public uploads are processed in memory
```

## Local Installation and Running

Windows PowerShell:

```powershell
cd "C:\Users\sujia\OneDrive\Desktop\10k coders"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python app.py
```

Open:

- Public app: http://127.0.0.1:5000/
- Login: http://127.0.0.1:5000/login
- Dashboard: http://127.0.0.1:5000/dashboard

If PowerShell blocks activation, use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` for the current terminal session.

## Environment Variables

Create `.env` locally from `.env.example`. Never commit `.env` or put a real key in README, HTML, JavaScript, or logs.

```env
AI_API_KEY=your_api_key_here
AI_PROVIDER=gemini
AI_MODEL=gemini-3.6-flash
AI_TIMEOUT=75
SECRET_KEY=generate-a-long-random-value
PORT=5000
FLASK_DEBUG=0
SESSION_COOKIE_SECURE=0
RATE_LIMIT_PER_MINUTE=12
AUTH_RATE_LIMIT_PER_MINUTE=10
DATA_RATE_LIMIT_PER_MINUTE=240
AI_RATE_LIMIT_PER_MINUTE=20
```

Important configuration behavior:

- `AI_API_KEY` is loaded by `python-dotenv` on the backend.
- `AI_PROVIDER=gemini` selects Gemini.
- `AI_MODEL` controls the primary model; the AI client can use supported fallback models for temporary failures.
- `SESSION_COOKIE_SECURE=0` keeps local HTTP development working. Set it to `1` only when serving through HTTPS.
- `DATABASE_URL` can override the default local SQLite database connection.
- The `.env.example` file contains placeholders only.

## API Overview

All JSON APIs generally use:

```json
{
  "success": true,
  "data": {}
}
```

Errors use a safe shape such as:

```json
{
  "success": false,
  "error": {"message": "...", "fields": {}}
}
```

### Public APIs

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Service and AI configuration status |
| POST | `/api/career-guide` | Generate a career plan from name, skills and target role |
| POST | `/api/resume-analyzer` | Analyze a PDF and return ATS score plus insights |

### Authentication APIs

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/signup` | Create an account and establish a session |
| POST | `/api/auth/login` | Authenticate an existing account |
| POST | `/api/auth/logout` | End the current session |
| GET | `/api/auth/me` | Return the current authenticated user |
| POST | `/api/auth/forgot-password` | Create a password-reset request |
| POST | `/api/auth/reset-password` | Redeem a reset token and set a new password |

### Authenticated page routes

`/dashboard`, `/resume`, `/skills`, `/roadmap`, `/coach`, `/history`, `/resources`, `/profile`, and `/settings` require login. `/login`, `/signup`, `/forgot-password`, and `/reset-password/<token>` provide account screens.

### Authenticated data APIs

| Area | Routes |
|---|---|
| Dashboard and history | `GET /api/dashboard`, `GET /api/history` |
| Profile | `GET /api/profile`, `POST/PUT /api/profile` |
| Skills | `GET /api/skills`, `GET /api/skills/catalog`, `GET /api/skills/growth`, `POST /api/skills`, `PUT/PATCH/DELETE /api/skills/<id>` |
| Skill gaps | `GET /api/gaps?target_role=...` |
| Resume Vault | `GET/POST /api/resumes`, `GET /api/resumes/<id>`, `POST /api/resumes/<id>/analyze`, `GET /api/resumes/<id>/download`, `DELETE /api/resumes/<id>`, `POST /api/resumes/<id>/primary` |
| Resume skills | `GET/POST /api/resumes/<id>/detected` |
| Resume comparison | `GET /api/resumes/compare?older=<id>&newer=<id>` |
| Roadmap | `GET/POST /api/roadmap`, `POST /api/roadmap/task`, `GET /api/progress` |
| Resources | `GET /api/resources` |
| Notifications | `GET /api/notifications`, `POST /api/notifications/<id>/read`, `POST /api/notifications/read-all` |
| Career Coach | `GET/POST/DELETE /api/coach` |
| Resume Builder | `GET/POST/PUT/PATCH /api/builder`, `POST /api/builder/download` |

State-changing authenticated requests require the session CSRF token in the `X-CSRF-Token` header. The shared frontend API client supplies credentials and this header automatically.

## Security

- API keys stay server-side in `.env` and are never sent to browser code.
- Passwords use Werkzeug password hashing.
- Sessions store a server-validated user ID and use HTTP-only, `SameSite=Lax` cookies.
- `SESSION_COOKIE_SECURE` is configurable for HTTPS without breaking local HTTP development.
- State-changing authenticated requests require CSRF protection.
- User-owned data queries are scoped by authenticated `user_id`.
- Password reset tokens are hashed, time-limited, and single-use.
- Authentication, data, and AI endpoints have rate limiting.
- Uploads require PDF extension, `%PDF` magic bytes, readable text, and a 5 MB limit.
- Resume files are scoped to their owner in the Resume Vault.
- Security headers include `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy`.
- User input and AI output are escaped before public frontend rendering to reduce XSS risk.
- AI failures return friendly messages while technical diagnostics remain server-side.

## Database

SQLite is the default local database at `career_center.db`. SQLAlchemy models cover users, career profiles, skills, user skills, resumes, resume analyses, roadmaps, progress, activities, notifications, coach messages, password reset tokens, skill history, cached gap guidance, and generated resumes.

Database initialization is additive: missing tables and supported missing columns are created without dropping tables or deleting existing records. Production migration tooling is intentionally deferred for a later stage.

## Project Status and Future Work

The current repository contains the public tools and the first authenticated command-center experience. Possible future improvements include formal Alembic/Flask-Migrate migrations, a production database and object storage, distributed rate limiting, email delivery for password resets, account deletion/export, stronger production headers such as CSP, automated pytest coverage, and deployment-specific observability.

## License and Project Context

This repository is a college software project and portfolio application demonstrating Flask backend development, REST API design, authentication, database-backed workflows, deterministic scoring, AI integration, document processing, and responsive frontend engineering.


