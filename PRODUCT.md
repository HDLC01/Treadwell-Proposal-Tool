# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Plain HTML + vanilla JS + one CSS file per page/shared `styles.css`. No framework (no React, no
Vue, no build step) — deliberate, to keep the dependency surface tiny and the deploy trivial
(FastAPI serves the static frontend directly). Backend is FastAPI + Python 3.11. Deployed as a
single Docker container on a Bluehost VPS behind nginx, with a parallel staging stack. Auth +
primary data via Supabase (self-hosted Postgres+PostgREST on staging for data, cloud Supabase for
auth). This is an established, multi-month-old production codebase, not a greenfield build —
treat the stack as fixed, not as an open decision.

## Users

Treadwell's own estimating staff (Kyle, Troy, Hanz and others) — the people who price and send
construction bids (epoxy flooring, polished concrete, gypsum underlayment). They use this tool
daily, at a desk, to turn a lead into a priced estimate and a signed proposal. A secondary
audience is Treadwell's customers, who view and approve proposals through a companion customer
portal (a separate repository, `treadwell-portal`) that shares this tool's data contract for
drafts/events.

## Product Purpose

Automates Treadwell's bid paperwork end to end: a staff member fills a guided intake, the tool
prices the job (increasingly pricing itself against an internal items/assemblies library rather
than reading Kyle's original spreadsheet), fills the real proposal Word template, and hands back
downloadable files (and, historically, a Dropbox filing step). Success is a correct, on-brand
proposal produced in minutes instead of by hand in Excel/Word, with the pricing math verifiably
matching Kyle's original workbook.

## Positioning

Not a generic form builder or generic estimating SaaS — it is Treadwell's own pricing logic
(transcribed and pinned against the real estimate workbook, `estimate_sheet_5.7.xlsx`) wearing a
guided multi-step UI, with a CRM board, an AI lead inbox, and a customer portal built around the
same data. A competitor's generic tool could not reproduce Treadwell's exact markup chain,
tax handling, or document templates without redoing this transcription work.

## Operating Context

A staff member's daily tool, used at a desk during and after a sales call: Intake → Estimate
Review → Proposal Review → Done, plus a CRM board that runs the sales meeting, a lead inbox, and
(newer) a from-scratch "Polish beta" estimator that prices itself rather than driving the legacy
spreadsheet. Every fix and feature ships to a staging environment first
(`staging.proposals.wetreadwell.com`) and is verified live there before promotion to production —
this is a standing, non-negotiable release discipline, not a suggestion.

## Capabilities and Constraints

- Work types: Epoxy, Polish (polished concrete), Gypsum underlayment, and Combo jobs; audiences
  Direct and GC (general contractor), each with their own proposal/cover-letter wording.
- Generates real `.xlsx` (via openpyxl) and `.docx` (via python-docx) files matching Kyle's actual
  templates byte-for-byte where untouched; PDF export via headless LibreOffice.
- Pricing must match the real estimate workbook's formulas — this is tested and pinned, not
  approximate. The workbook is a pinned reference to audit against, not (for the newer Polish
  beta) the live pricing engine itself.
- No new external icon/component library, no new color palette, no framework — see Brand
  Commitments and existing design-system tokens.
- CSP is strict (`script-src 'self' https://cdn.jsdelivr.net`, no `unsafe-eval`) — no inline
  `<script>`, no `eval`/`new Function` in shipped frontend code.
- Multi-repo workspace: this repo owns `drafts`/`events`; the customer portal
  (`treadwell-portal`) owns `portal_*` and shares this repo's production Postgres contract.

## Brand Commitments

Name: Treadwell. App accent color is `#C8102E` (distinct from the marketing-brand logo red
`#E52B2E` — the two are deliberately different and both correct in their own context). Existing
warm, cream-leaning surface palette and Inter/Zetta font pairing are settled (approved after
several iterations) — new visual work should extend this system, not propose a new one. A small
hand-rolled inline-SVG icon set already exists for CSP reasons; no icon font, no emoji as UI
chrome.

## Evidence on Hand

Live production system with real customers, real estimators, and a real revenue-generating
workflow (proposals.wetreadwell.com). Extensive existing design/engineering decision history is
recorded in this repo's own `CLAUDE.md` and in per-session memory notes — treat those as durable
prior art, not something to rediscover from scratch.

## Product Principles

- Staging first, always: every change is verified live on staging before it reaches production.
- The pricing math is the product's credibility — never approximate or silently diverge from
  Kyle's real workbook without an explicit, tested reason.
- Small dependency surface over convenience: plain HTML/JS/CSS, no framework, deploys as one
  container.
- AI drafts, humans decide: the tool prepares documents; a person still reviews and sends.
- Existing visual system is settled — extend it, don't replace it.

## Accessibility & Inclusion

No formally required standard on record. Existing interaction-state conventions (disabled vs.
read-only, focus-visible, tabular-nums on money columns) should be preserved in new work.
