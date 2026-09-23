# AI Career Guide & Resume Analyzer

An AI-powered career assistant for students and job seekers. One single-page Flask web app with two features:

1. **AI Career Guide** — a personalized 30-day career roadmap generated from your skills and target role, including skill-gap analysis, learning resources and job portals.
2. **Resume Analyzer** — upload a PDF resume, pick a target role, and get a deterministic ATS score (0–100) with a full breakdown plus AI-generated strengths, weaknesses, missing skills, improvement suggestions and ATS checks.

> "Build your career. Improve your resume. Get job-ready."

---

## ✨ Features

- **Single-page UI** — hero, AI Career Guide, Resume Analyzer and footer on one page; no navigation to other pages.
- **Career Guide** — full name + skills + target role → career overview, skills analysis, skill gaps and a structured **Week 1–4 roadmap** (topics / tasks / practice).
- **Resume Analyzer** — PDF upload → in-memory text extraction (PyMuPDF) → **deterministic ATS score** out of 100 with weighted factors:

  | Factor | Weight |
  |---|---|
  | Target-role keyword match | 30 |
  | Required skills match | 20 |
  | Experience / project relevance | 15 |
  | Education | 10 |
  | ATS formatting | 15 |
  | Section completeness | 10 |

- The same resume always produces the same score — the number is computed in Python, never invented by the AI. The AI only provides qualitative insights.
- **Honest ATS checks** — only text-verifiable signals are reported. Tables/graphics/columns cannot be reliably detected from parsed PDF text, and the app says so explicitly.
- **Curated links from local JSON** — learning resources (W3Schools, GeeksforGeeks, MDN, freeCodeCamp, official docs…), job portals (LinkedIn, Naukri, Indeed, Wellfound, Internshala) and resume builders (Canva, Novorésumé, Resume.io) are served from `data/resources.json`; the AI is never asked to invent URLs.
- **Robust error handling** — friendly messages for empty forms, non-PDF files, oversized uploads, scanned PDFs, AI timeouts, rate limits, invalid API keys and malformed AI responses. Stack traces never reach the user.
- **Security** — API key lives only on the backend (`.env`), never in HTML/CSS/JS; file type + size validation; `%PDF` magic-byte check; simple per-IP rate limiting; security headers; resumes processed in memory only.
- **Polished, accessible UI** — responsive layout (desktop/tablet/mobile), loading skeletons, progress ring, badges, inline SVG icons, semantic HTML, labels, `aria-live` regions and keyboard-friendly controls.

## 🧰 Technology Stack

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3, vanilla JavaScript (fetch/AJAX) |
| Backend | Python 3 + Flask |
| AI | Google Gemini REST API (default) or any OpenAI-compatible API — switchable via `.env` |
| PDF | PyMuPDF (`fitz`) text extraction |
| Config | python-dotenv (`.env`), JSON data files |

## 📁 Project Structure

```
10k coders/
├── app.py                  # Flask app: routes, validation, error handlers
├── requirements.txt        # Python dependencies
├── .env.example            # environment variable template (copy to .env)
├── .gitignore
├── README.md
├── data/
│   ├── resources.json      # curated learning resources / job portals / resume builders
│   └── role_keywords.json  # role → keywords/skills database for ATS scoring
├── services/
│   ├── ai_client.py        # provider-agnostic AI calls + safe JSON parsing
│   ├── career_guide.py     # career guide prompt + response shaping
│   ├── resume_analyzer.py  # deterministic ATS scoring + AI insights
│   ├── pdf_extractor.py    # PDF text extraction & cleaning
│   ├── validation.py       # input validation & sanitisation
│   ├── rate_limiter.py     # simple in-memory sliding-window limiter
│   └── resources.py        # data/resources.json loader
├── static/
│   ├── css/style.css
│   └── js/app.js
├── templates/
│   └── index.html          # the single page
└── uploads/                # kept empty — resumes are processed in memory
```

## 🚀 Installation & Running (Windows PowerShell)

```powershell
# 1. From the project folder
cd "c:\Users\sujia\OneDrive\Desktop\10k coders"

# 2. Create a virtual environment
python -m venv .venv

# 3. Activate it
.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt

# 5. Create your .env (copy the template, then paste your real key inside)
Copy-Item .env.example .env
notepad .env

# 6. Run the app
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

If PowerShell blocks script activation, run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.

## 🔐 Environment Variables

Create `.env` (never commit it — it is git-ignored):

| Variable | Required | Description |
|---|---|---|
| `AI_API_KEY` | yes* | Your AI provider API key. Stays on the server only. |
| `AI_PROVIDER` | no | `gemini` (default) or `openai` (any OpenAI-compatible endpoint). |
| `AI_MODEL` | no | Model name, e.g. `gemini-3.6-flash` / `gpt-4o-mini`. |
| `AI_BASE_URL` | no | Custom base URL for OpenAI-compatible providers. |
| `AI_TIMEOUT` | no | AI request timeout in seconds (default 60). |
| `RATE_LIMIT_PER_MINUTE` | no | Per-IP requests per minute (default 12). |
| `PORT` | no | Server port (default 5000). |
| `SECRET_KEY` | no | Flask secret key (auto-generated if empty). |
| `FLASK_DEBUG` | no | `1` to enable debug mode (development only). |

\* If `AI_API_KEY` is empty, the app falls back to `GEMINI_API_KEY` (for provider `gemini`) or `OPENAI_API_KEY` (for provider `openai`) from the system environment.

## 🖱️ How to Use

**Career Guide:** scroll to *AI Career Guide*, enter your full name, skill set (comma separated) and target role, then click **Generate Career Plan**. Your overview, skill gaps, 4-week roadmap, resources and job portals appear below the form — no page reload.

**Resume Analyzer:** scroll to *Resume Analyzer*, choose a **PDF** resume (max 5 MB), enter your target role and click **Analyze Resume**. The ATS score ring, factor breakdown, strengths, weaknesses, missing skills, improvement areas, ATS checks and job-portal/resume-builder links appear below the form.

## 🔌 API Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/` | — | The single-page UI |
| GET | `/api/health` | — | `{ status, ai_configured, ai_provider }` |
| POST | `/api/career-guide` | JSON `{ full_name, skills, target_role }` | Career overview, skills analysis, skill gaps, week 1–4 roadmap, tips + curated resources & job portals |
| POST | `/api/resume-analyzer` | multipart/form-data `resume` (PDF) + `target_role` | ATS score + factor breakdown, strengths, weaknesses, missing skills, improvement areas, ATS checks, role match, keywords + curated links |

All API responses use the shape `{ "success": true|false, "data": … | "error": { "message", "fields?" } }`.

## 🛡️ Security Notes

- The API key is read from `.env` on the server; it is never rendered into the page, JS or CSS, and never logged.
- Uploaded resumes are parsed **in memory** and discarded — nothing is written to disk.
- Uploads are limited to PDF files (extension + `%PDF` magic bytes) and 5 MB.
- Filenames are never used to build filesystem paths; upload streams are processed in memory only.
- Simple per-IP sliding-window rate limiting protects the AI endpoints.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) are set on every response; unexpected exceptions are logged server-side and never shown to users.
- All AI-provided text is HTML-escaped before rendering (XSS protection).

## 🔮 Future Improvements

- Support DOCX resumes alongside PDF.
- Database storage for saved career plans / resume history (login system).
- Streaming AI responses for faster perceived performance.
- Redis-backed rate limiting for multi-worker deployments.
- Unit + integration test suite (pytest) in CI.
- Additional ATS heuristics (date parsing, section ordering).


