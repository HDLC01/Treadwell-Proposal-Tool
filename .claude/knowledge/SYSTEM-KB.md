# Treadwell Proposal Tool - System Knowledge Base
_Auto-generated snapshot. Last updated: 2026-07-16 02:38:43_

## What this system is
Standalone FastAPI + vanilla-JS tool that fills Treadwell's estimate sheet
(.xlsx) and Word proposal (.docx), renders the proposal to PDF via LibreOffice,
and serves all three as downloads. Single Docker container on a Bluehost VPS
behind nginx + Let's Encrypt.

- Production: https://proposals.wetreadwell.com   (/opt/treadwell, :8888, branch main)
- Staging:    https://staging.proposals.wetreadwell.com  (/opt/treadwell-staging, :8889, branch staging, docker-compose.staging.yml)

## Current git state (2026-07-16 02:38:43)
- Branch: feat/work-notes-line  (local 27269ca / origin )
- Recent commits:
27269ca fix: preview parity ΓÇö itemize PRICE in the editor for polish/GC templates (#134)
970f32d fix: PRICE WYSIWYG parity ΓÇö double-space after Total + flush preview bullets (#133)
f85e7c0 fix: strip red-square bullets from the PRICE section (flush-left pricing) (#132)
0433f12 feat: base-bid tab's role drives the whole proposal (Phase B) (#131)
f09d43c fix: shrink-to-fit long text boxes so gyp's verbose WORK scope stops overlapping PRICE (#129)
d2a6150 fix: proposal PRICE rows use the template's RED SQUARE bullets (match Kyle's design) (#128)
aed0ff2 fix: bust /api/proposal-template ETag on block-schema changes (#127)
738a6e2 fix: proposal preview shows PRICE rows flush/bullet-less (match the docx) (#126)
6f9252c fix: remove the "Auto" base-bid chip from the estimate bid bar (#125)
66fb28e fix: default-notes fetch waits for auth token (no more 401 on fresh load) (#124)
6e67d74 fix: estimate/proposal batch ΓÇö %-cell flash, Auto chip, false cove note, PRICE bullets/bold, Options-heading order (#122)
4370c31 feat: Excel-style multi-cell range selection in the estimate grid (#120)

## Uncommitted working changes
 M "backend/templates/Direct/XX.XX TREADWELL EPOXY PROPOSAL - New Direct.docx"
 M "backend/templates/Direct/xx.xx TREADWELL POLISH PROPOSAL - NewDirect.docx"
 M "backend/templates/Gyp/xx TREADWELL UNDERLAYMENT PROPOSAL - xx.docx"
?? .claude/

## Ops quick-reference
- Staging deploy: cd /opt/treadwell-staging && git pull origin staging && docker compose -f docker-compose.staging.yml up -d --build
- Prod deploy:    cd /opt/treadwell && git pull && docker compose up -d --build
- Download tokens are in-memory; a container restart expires them (the Done page
  self-heals by re-generating). PDF export needs libreoffice-writer in the image.
- Full architecture, cell maps, and tokens: see CLAUDE.md in the repo root.
