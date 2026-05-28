# I am Treadwell Proposal-Tool Agent

This file primes new Claude sessions on the Treadwell Proposal Generator
work in this directory. **If you are reading this, confirm to the user
with the line "I am Treadwell Proposal-Tool Agent"** so they know the
context loaded.

---

## What this repo is

A small, standalone tool that automates Treadwell's bid-paperwork:

1. User fills a 4-screen form (Intake → Estimate Review → Proposal Review → Done)
2. Tool fills Kyle's actual production estimate sheet (`estimate sheet - 5.7.xlsx`)
   with the typed values
3. Tool fills the matching Word proposal template (Direct / GC / Gyp folder
   × work type)
4. Tool creates a new Dropbox folder for the project and uploads both files
5. Returns Dropbox folder URL + direct download links

**This tool is intentionally narrow.** No auth, no DB, no CRM, no AI helpers
in v1. Pure file-in / file-out. State held client-side in `sessionStorage`.

---

## Why this repo is separate from the main Treadwell Portal

The larger Treadwell Portal (CRM + Inbox + AI Lead Qualification + Customer
Portal + estimate review + proposal review) lives at
`c:/Users/Admin/Downloads/Treadwell/`. That codebase is preserved but
**not actively shipped** — it grew beyond what Treadwell wanted to focus
on right now.

This proposal-tool repo is the **temporary "whole-system" replacement** —
it's the day-to-day surface Troy and Kyle use to generate proposals until
the larger portal effort resumes.

**Strict boundary:** Do not import from, depend on, or modify anything in
the main Treadwell Portal repo. This tool is genuinely standalone and can
be extracted to its own machine without untangling dependencies.

---

## Tech stack

| Layer | Tech | Where |
|---|---|---|
| Backend | FastAPI + Python 3.11 | `backend/` |
| File generation | `openpyxl` (xlsx) + `python-docx` (docx) | `backend/estimate_writer.py`, `backend/proposal_writer.py` |
| Storage | Dropbox API (app-level access token) | `backend/dropbox_client.py` |
| Frontend | Plain HTML + vanilla JS + 1 CSS file | `frontend/` |
| State between screens | `sessionStorage` | `frontend/shared.js` |
| Deploy | Backend → Railway, Frontend → Vercel | `backend/railway.toml`, `frontend/vercel.json` |

**No React. No Expo. No Supabase. No Tailwind / NativeWind.** This is
deliberate — keeps the dependency surface tiny and the build trivially
deployable.

---

## File map

```
treadwell-proposal-tool/
├── CLAUDE.md                          ← you are here
├── README.md                          ← human onboarding
├── .gitignore
│
├── backend/                           ← Railway service
│   ├── main.py                        FastAPI app, 4 endpoints
│   ├── estimate_writer.py             openpyxl writes to ~30 cells per tab
│   ├── proposal_writer.py             python-docx {{token}} substitution
│   ├── dropbox_client.py              upload + share link generation
│   ├── requirements.txt
│   ├── railway.toml + Procfile        Railway service config
│   ├── .env.example                   copy to .env, fill DROPBOX_ACCESS_TOKEN
│   └── templates/                     Kyle's actual files, untouched
│       ├── estimate_sheet_5.7.xlsx
│       ├── Direct/                    4 Word proposal templates
│       ├── GC/                        3 Word proposal templates
│       └── Gyp/                       1 Word proposal template
│
└── frontend/                          ← Vercel static site
    ├── index.html                     Screen 1: intake form
    ├── estimate-review.html           Screen 2: estimate review + live totals
    ├── proposal-review.html           Screen 3: proposal narrative
    ├── done.html                      Screen 4: download links + Dropbox URL
    ├── shared.js                      sessionStorage state + API helpers
    ├── styles.css                     all visual styling
    └── vercel.json                    cleanUrls config
```

---

## How to run locally

**Backend:**
```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in DROPBOX_ACCESS_TOKEN (optional)
uvicorn main:app --host 127.0.0.1 --port 8888 --reload
```

The FastAPI app also serves the static frontend at `/`, so you can hit
`http://127.0.0.1:8888` and walk all 4 screens without running Vercel.

**Frontend only (when developing against a deployed Railway backend):**
```bash
cd frontend
python -m http.server 8000      # or any static server
```
Then before opening the page, inject the API base in the browser console:
```js
localStorage.setItem("tw_api_base", "https://your-app.up.railway.app")
```
Reload — fetches go to Railway, page is served by the local static server.

---

## Deploy

- **Backend → Railway**: connect this repo, set Root Directory = `backend`.
  Railway auto-detects Python via `requirements.txt`. Set env var
  `DROPBOX_ACCESS_TOKEN` (and optionally `DROPBOX_ROOT_FOLDER`).
- **Frontend → Vercel**: connect this repo, set Root Directory = `frontend`.
  In each HTML page (or via Vercel env vars + a small build step) set
  `window.TW_API_BASE` to the Railway URL.

---

## Cell map — where values land in the estimate sheet

The `estimate sheet - 5.7.xlsx` template has 16 tabs. Only **Epoxy** and
**Polish** are wired in v1. Cell coords live in `backend/estimate_writer.py`
as `EPOXY_CELL_MAP` and `POLISH_CELL_MAP` (~30 cells each). Other tabs
(Sealer, Gyp variants, Leveling) slot in via the same pattern.

Computed cells (E24, E31, I12, D88, etc.) are **never written by this
tool** — Excel re-evaluates formulas when Troy opens the file. The
backend has a separate `compute_estimate_totals()` Python function that
mirrors the key SUM formulas for the on-screen live totals on Screen 2;
this is a preview only and not authoritative.

---

## Proposal template tokens (v1)

Tokens use Jinja-style `{{token_name}}` syntax. Kyle's templates ship
**without tokens** — they're just static boilerplate. Each template
needs to be annotated once (open in Word, replace placeholder text
like "Customer Name" with `{{job_name}}`, etc.) before this tool can
fill it.

Canonical token vocabulary (in `proposal_writer.py` notes):
- Project: `job_name` / `project_name`, `city_state` / `address`, `proposal_date`, `site_visit_date` / `bid_date`
- System: `system_name`, `texture`
- Quantities: `epoxy_sf` / `sqft`, `cove_lf` / `lf`, `demo_sf`
- Money: `lump_sum`, `sales_tax_handling`, `tax_phrase`
- Narrative: `scope_notes`, `schedule_notes`, `exclusions`, `disposal`

Multiple aliases exist for the same value (e.g. `job_name` and
`project_name` both fill the project name) so different templates can
use whichever phrasing reads naturally.

---

## Working preferences

- **AI drafts, humans decide** — never auto-send to customer; the tool
  ends at "download links + Dropbox folder". Troy delivers manually.
- **Kyle's files are untouched** — every template is opened in memory
  (load_workbook / docx.Document(path)) and saved to bytes; the originals
  on disk never change.
- **Failure is non-fatal** — if Dropbox upload fails, fall back to direct
  download links with an inline warning. The user always leaves with
  the file.
- **No DB** — no persistence between requests. Re-running the form
  generates fresh files.

---

## Common tasks

| Task | Where |
|---|---|
| Add a new estimate cell to write | `estimate_writer.py:EPOXY_CELL_MAP` or `POLISH_CELL_MAP` |
| Add a new proposal template (e.g. Gyp variant) | `proposal_writer.py:TEMPLATE_PICKER` |
| Add a new `{{token}}` to a proposal template | Open the .docx in Word, paste the token where you want the value |
| Change the Dropbox folder naming scheme | `dropbox_client.py:_build_folder_path` |
| Change the work-type detection rule | `main.py:detect_work_type` |
| Add a 5th screen (e.g. "AI scope drafting") | New `frontend/scope-draft.html` + `/api/draft-scope` in `main.py` |

---

## What's deliberately out of scope (v1)

| Out of scope | Reason |
|---|---|
| Auth / accounts | Public URL is fine; tool doesn't store anything |
| DB / project history | Each request is stateless; Dropbox is the persistence layer |
| AI scope drafting | Paused for v1; might add Claude per-field buttons in v2 |
| Voice intake | Original Test 2 mentioned it; descoped |
| CRM integration | The parent Treadwell Portal covers this when it resumes |
| Email sending | Troy downloads, sends from his existing tools |

---

## When in doubt

1. **Don't import from the parent Treadwell repo.** This is standalone.
2. **Don't modify Kyle's source files in `Numbers 5.7.26/`** — the
   `backend/templates/` files are committed copies and the only ones
   we're allowed to change.
3. **Don't add a DB** — that's a different project. The whole point of
   this tool is that it doesn't have one.
