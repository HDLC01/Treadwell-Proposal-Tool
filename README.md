# Treadwell Proposal Generator

A standalone web tool that fills Treadwell's estimate sheet and Word
proposal in one guided flow, then saves both to a new Dropbox folder.

Built to replace the manual workflow of: open Excel, type project
inputs, copy values into Word template, save to a Dropbox folder.

## What it does

Four-screen flow:

1. **Intake** — project name, address, contact, source, quick scope (Epoxy SF / Polish SF / Cove LF), audience (Direct customer vs General Contractor).
2. **Estimate Review** — mirrors the v2 portal's estimate-review page; edit any cell, live totals update as you type.
3. **Proposal Review** — narrative fields (scope, schedule, exclusions, system name, texture, tax handling) layered on top of locked canonical values from the estimate.
4. **Done** — Dropbox folder link + two direct download buttons (.xlsx + .docx).

Work type (Epoxy / Polish / Combo) is **auto-detected** from the SF inputs.
Troy can override on screen 2 if needed.

## Quick start (local)

```bash
# 1. Backend
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # fill DROPBOX_ACCESS_TOKEN (optional)
uvicorn main:app --host 127.0.0.1 --port 8888 --reload

# 2. Browser
open http://127.0.0.1:8888
```

The FastAPI app serves both the API and the static frontend during local
dev — no separate frontend server needed.

## Deploy

| Layer | Host | How |
|---|---|---|
| Backend | [Railway](https://railway.app) | Connect repo, set Root Directory = `backend` |
| Frontend | [Vercel](https://vercel.com) | Connect repo, set Root Directory = `frontend` |

After Railway deploys, copy the backend URL (e.g. `https://your-app.up.railway.app`).
In each HTML file in `frontend/`, add this `<script>` block right before
`<script src="/shared.js">`:

```html
<script>window.TW_API_BASE = "https://your-app.up.railway.app";</script>
```

(or set it via a small build step that env-substitutes the URL).

### Environment variables (Railway)

| Var | Required | Default | Purpose |
|---|---|---|---|
| `DROPBOX_ACCESS_TOKEN` | No (graceful fallback) | unset | Long-lived app token from https://www.dropbox.com/developers/apps. Without it the tool returns direct download links only. |
| `DROPBOX_ROOT_FOLDER` | No | `/Proposals` | Root folder under the Dropbox app where each project's subfolder is created. |

## Source of truth for templates

The estimate workbook and Word proposal templates in `backend/templates/`
are **copies** of Kyle's actual production files (originals in
`c:/Users/Admin/Downloads/Treadwell/Numbers 5.7.26/`). The copies are
opened in memory and saved to bytes on every request — the originals are
never modified.

To refresh templates after Kyle updates them: copy the new files into
`backend/templates/` (preserve the folder structure: `Direct/`, `GC/`,
`Gyp/`).

## Architecture decisions

See [CLAUDE.md](./CLAUDE.md) for the full set. Highlights:

- **No auth, no DB**: pure file-in / file-out, state held in browser `sessionStorage`.
- **No React**: plain HTML + vanilla JS keeps the deploy trivial.
- **No AI in v1**: scope-drafting / extraction buttons are paused; might add later.
- **Backend on Railway, Frontend on Vercel**: separate origins, CORS configured permissively on the backend.
- **Templates are untouched** Kyle copies — every request clones to memory before editing.

## Repo layout

```
backend/    FastAPI app (Railway)
frontend/   Static HTML + JS (Vercel)
CLAUDE.md   Context for AI-assistance sessions
```
