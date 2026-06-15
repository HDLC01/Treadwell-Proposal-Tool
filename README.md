# Treadwell Proposal Generator

A standalone web tool that fills Treadwell's estimate sheet and Word
proposal in one guided flow, then hands back ready-to-file downloads
(estimate `.xlsx`, proposal `.docx`, and a proposal **PDF**).

Built to replace the manual workflow of: open Excel, type project inputs,
copy values into the Word template, export, and file the results by hand.

**Live in production 24/7:** <https://proposals.wetreadwell.com>
· Staging: <https://staging.proposals.wetreadwell.com>

## What it does

Sign in with a Google `@wetreadwell.com` account, then walk a four-screen flow:

1. **Intake** — project name, address, contact, source, quick scope
   (Epoxy SF / Polish SF / Cove LF), audience (Direct customer vs General
   Contractor). Optional **AI Autofill**: paste the raw lead notes and the
   tool drafts the proposal narrative + sets the estimate flags (with a
   reasoning trail for each).
2. **Estimate Review** — edit any cell of Kyle's real estimate sheet; live
   totals recompute as you type (in-browser HyperFormula engine).
3. **Proposal Review** — narrative fields (scope, schedule, exclusions,
   texture, tax handling) layered on top of the locked canonical values from
   the estimate. The system name is auto-derived from the picked System 1/2.
4. **Done** — a pre-generate review card, then **Generate** produces three
   downloads: estimate `.xlsx`, proposal `.docx`, and proposal **PDF**.

Work type (Epoxy / Polish / Combo) is **auto-detected** from the SF inputs;
the estimator can override it on screen 2.

Every project is **saved as a draft** (the draft id rides in the URL as
`?d=<uuid>`, debounced-autosaved server-side) so work survives a tab close or
device switch. The **Projects** dashboard lists all saved projects with
Active/Inactive filtering, plus **History**, **Trash**, and an **Admin** view.

## Quick start (local)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # fill in the Supabase keys (see below)
uvicorn main:app --host 127.0.0.1 --port 8888 --reload
# then open http://127.0.0.1:8888
```

The FastAPI app serves **both** the API and the static frontend, so there's
no separate frontend server. `/api/*` is gated on a Supabase auth token, so
local dev needs the `SUPABASE_*` vars set to sign in.

Run the tests:

```bash
cd backend && python -m pytest -q     # hermetic — auth + Supabase are stubbed
```

## Deploy (production — Docker on a Bluehost VPS)

There is **one Docker container** (`treadwell-proposal-tool`) built from the
repo `Dockerfile`; FastAPI inside it serves the API **and** the static
frontend on `:8888`. **nginx** on the host reverse-proxies `80/443 → 8888`,
with **Let's Encrypt** SSL (auto-renews). The app lives at `/opt/treadwell`.
The image bakes in Python + **Node + the Claude CLI** (for AI Autofill) +
**LibreOffice** (for the `docx → PDF` export).

```bash
# on the VPS
cd /opt/treadwell && git pull && docker compose up -d --build   # deploy / update
docker compose restart                                          # restart
docker compose logs -f                                          # tail logs
```

### Staging

A parallel stack at <https://staging.proposals.wetreadwell.com> — container
`treadwell-staging` on `:8889` at `/opt/treadwell-staging`, tracking the
`staging` branch. Staging uses a **self-hosted Postgres + PostgREST** for
DATA and **cloud Supabase for AUTH only**, so test data never touches prod.

```bash
cd /opt/treadwell-staging && git pull origin staging \
  && docker compose -f docker-compose.staging.yml up -d --build
```

**All changes hit `staging` first, then promote to `main` / prod.**

### Environment variables

Configuration is via environment variables in `/opt/treadwell/.env` (prod) /
`.env.staging` (staging) — **never committed**. The variable list + setup live in
the deployment notes, not this public file.

## Source of truth for templates

The estimate workbook and Word proposal templates in `backend/templates/`
are **annotated copies** of Kyle's actual production files (the originals
live outside this repo). The copies are opened in memory and saved to bytes
on every request — the originals on disk are never modified.

Templates carry Jinja-style `{{token}}` placeholders (and repeatable blocks
like `{{#system}}` / `{{#price_line}}`) that the backend fills. To refresh a
template after Kyle updates it, copy the new file into `backend/templates/`
(preserve the `Direct/`, `GC/`, `Gyp/` structure) and re-annotate it.

## Architecture decisions

See [CLAUDE.md](./CLAUDE.md) for the authoritative, current-state set. Highlights:

- **Single Docker container on a Bluehost VPS** — FastAPI serves the API *and*
  the static frontend (same origin), behind nginx + Let's Encrypt. (The old
  Railway-backend / Vercel-frontend / ngrok dev setup was removed 2026-05-30.)
- **No React** — plain HTML + vanilla JS keeps the build trivial and the
  dependency surface tiny.
- **Supabase auth + persisted drafts** — Google sign-in (restricted to the
  `@wetreadwell.com` domain); projects autosave to Postgres/PostgREST (prod
  data on cloud Supabase, staging on a self-hosted VPS Postgres) with a local
  SQLite fallback. State also mirrors to `localStorage` for instant reloads.
- **AI Autofill is live** — the backend shells out to the Claude CLI
  (`claude -p`) to draft the proposal narrative + estimate flags from pasted
  lead notes. Humans always review before anything ships.
- **Download-only** — `/api/generate` returns the filled `.xlsx` / `.docx`
  plus an on-demand PDF (LibreOffice headless). The old Dropbox-folder upload
  was retired; the estimator files the downloads manually.
- **Templates are untouched** Kyle copies — every request clones to memory
  before editing.

## Repo layout

```
backend/                     FastAPI app — serves the API AND the static frontend
  main.py                    HTTP endpoints (generate, autofill, drafts, price, sheet, admin…)
  estimate_writer.py         openpyxl — fills the estimate workbook
  proposal_writer.py         python-docx — {{token}} + repeatable-block substitution
  pdf_writer.py              docx → PDF via LibreOffice headless
  pricing.py                 recipe pricing engine (cross-check / reference bid)
  drafts.py                  project/draft persistence (Supabase/PostgREST · SQLite)
  supabase_client.py         Google-JWT auth gate + data client
  templates/                 annotated estimate + proposal templates (Direct/ GC/ Gyp/)
  tests/                     pytest suite (hermetic)
frontend/                    static HTML + vanilla JS (served by FastAPI)
Dockerfile                   bakes Python + Node + Claude CLI + LibreOffice
docker-compose.yml           prod stack (:8888)
docker-compose.staging.yml   staging stack (:8889 + Postgres + PostgREST)
CLAUDE.md                    authoritative current-state context for AI sessions
```
