# Treadwell Proposal Tool - System Knowledge Base
_Auto-generated snapshot. Last updated: 2026-10-23 23:09:09_

## What this system is
Standalone FastAPI + vanilla-JS tool that fills Treadwell's estimate sheet
(.xlsx) and Word proposal (.docx), renders the proposal to PDF via LibreOffice,
and serves all three as downloads. Single Docker container on a Bluehost VPS
behind nginx + Let's Encrypt.

- Production: https://proposals.wetreadwell.com   (/opt/treadwell, :8888, branch main)
- Staging:    https://staging.proposals.wetreadwell.com  (/opt/treadwell-staging, :8889, branch staging, docker-compose.staging.yml)

## Current git state (2026-10-23 23:09:09)
- Branch: feat/joint-filler-dye-editable-rate  (local 2195432 / origin )
- Recent commits:
2195432 Merge pull request #568 from HDLC01/fix/options-gap-real-lines
f810a86 fix(proposal): the gap above "Options" is real, editable blank lines on every template
26357d1 Merge pull request #567 from HDLC01/fix/send-equals-download
88c5ba0 fix(proposal): no eviction saves over a moved-on copy; two tabs claim nothing; a click keeps no door writes
746bec1 Merge pull request #566 from HDLC01/fix/estimate-bar-repaints-on-base-pick
4bbebc4 fix(estimate): picking a base bid repaints the bottom Total bar at once
517a697 Merge pull request #565 from HDLC01/fix/files-card-shows-document-total
e2ff7b3 fix(estimate): the bottom Total bar follows the base bid tab
8e91cec fix(files): the price card shows the total of the document it builds
7e50c21 Merge pull request #564 from HDLC01/fix/send-equals-download
8702963 fix(proposal): no filing, door trip or other tab puts an old copy back; a stopped door is the estimator's page
ce08ca9 fix(proposal): no Files-page write, eviction or door save puts an older copy back; Send holds to the draft it checked

## Uncommitted working changes
?? .claude/knowledge/
?? .claude/settings.json
?? .codex/
?? .gitattributes
?? .graphifyignore
?? AGENTS.md
?? "GC Templates/"
?? bash.exe.stackdump
?? console-debug.txt
?? docs/template-text/
?? graphify-out/
?? grep.exe.stackdump
?? raken-gps-timecard-audit-SKILL.md
?? s4-full.yml
?? s5-snap.yml
?? "v2 Test/"

## Ops quick-reference
- Staging deploy: cd /opt/treadwell-staging && git pull origin staging && docker compose -f docker-compose.staging.yml up -d --build
- Prod deploy:    cd /opt/treadwell && git pull && docker compose up -d --build
- Download tokens are in-memory; a container restart expires them (the Done page
  self-heals by re-generating). PDF export needs libreoffice-writer in the image.
- Full architecture, cell maps, and tokens: see CLAUDE.md in the repo root.
