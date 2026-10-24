---
name: "raken-gps-timecard-audit"
description: "Audit Raken Review > Issues GPS timecard entries for a target date, verify only needed map pins, and return a compact flagged-employee report."
---

# Raken GPS Timecard Audit

Use this skill when the user asks to audit Raken timecard GPS/location issues for a specific date.

The goal is a fast, low-token report of employees who need a flag or note. Do not turn this into a full browser bookkeeping job.

## Fast Defaults

- Work from Raken's `Review > Issues` page for the target date. It already narrows the audit to entries with location issues.
- Do not scan all Time Cards unless the Issues page is unavailable or the user asks for a full reconciliation.
- Do not create or edit Google Sheets by default.
- Do not open Apps Script.
- Do not use browser automation to format checkboxes, resize columns, or build a spreadsheet unless the user explicitly asks for a live Sheet after seeing the report.
- Produce the report in chat as a Markdown table plus a CSV block that can be pasted or imported into Sheets.
- Keep a compact working ledger. Do not paste full page text, screenshots, map tile logs, or long intermediate reasoning into chat.

If the user explicitly wants a Google Sheet, first ask whether a CSV is enough. If they still want a live Sheet, use simple paste/import steps only; never use Apps Script.

## Stop Conditions

Avoid two-hour sessions:

- If Raken navigation loops, authentication blocks you, or the Issues page cannot be filtered after two attempts, ask the user for a screenshot/export of the Issues list.
- If a map page fails to render after two reloads, mark that row `Ambiguous - map would not render` and ask for user review.
- If a pin is close to the boundary and cannot be judged after one visual check plus one scale check, mark that event ambiguous instead of continuing to fight the map.
- If there are more than 25 issue rows, first enumerate all rows and ask whether to audit all rows or only rows that are clearly outside/unclear.

## Workflow

### 1. Confirm Inputs

Require a target date. If missing, ask for it.

Use this report schema:

`Last Name, First Name, Clock In Outside, Clock Out Outside, Different Project, Notes`

Only include employees with at least one checked flag or a note.

### 2. Enumerate Issues Before Opening Maps

Go to Raken: `app.rakenapp.com`.

Navigate to `Review > Issues`, set the date/pay period so the target date is included, and enumerate every issue row for the target date across all pages before auditing maps.

For each issue row, capture only:

- employee name
- project name
- clock-in / clock-out times if shown
- issue type or warning text if shown
- whether the employee appears more than once that date
- the row's `View on map` URL if available

Prefer page text/accessibility extraction over screenshots. Use screenshots only for unclear rows.

Do not click row bodies. If an Edit Time Card modal opens, cancel it and retry using the row's exact three-dot menu.

### 3. Open Only the Needed Map Views

For each issue row that may affect the final report:

1. Open the row's three-dot menu and choose `View on map`.
2. Copy the resulting map URL if possible: `https://app.rakenapp.com/projects/{projectId}/map/{entryId}?date=YYYY-MM-DD`.
3. Reopen the map URL directly if the view looks stale or cluttered.
4. Wait briefly for map tiles to load before judging.

On the map page, use the Events panel:

- Click the specific `Clock in` event before judging clock-in.
- Click the specific `Clock out` event before judging clock-out.
- Never assume the default-visible pin is the event being audited.

Map controls are unreliable. Avoid repeated zooming. If needed, pan with drag and use the DOM/map-scale label for a quick distance estimate. Do not call Raken backend APIs; that path is not worth the token/time cost.

### 4. Flagging Rules

Evaluate clock-in and clock-out independently.

A pin is OK if it is:

- inside the assigned project geofence circle, or
- within roughly 300 meters of the circle edge, or
- at/very near the Treadwell office exception location described below.

Flag the specific field only when the pin is clearly farther than the tolerance.

Do not trust Raken's red triangle by itself. It is a lead, not the decision.

### 5. Treadwell Office / Overhead Exception

Treadwell office / Overhead Office:

`1707 E 123rd Terrace, Olathe, KS`

Rules:

- If the assigned project circle is the Overhead/Office Job and the pin is outside that circle, flag normally and add note `Overhead/Office Job`.
- If the assigned project is elsewhere but the pin is at or very close to the Treadwell office, do not flag that event.
- Do not confuse the Treadwell office with River Market / downtown Kansas City.
- Do not navigate to Raken Settings to verify this address unless the user explicitly asks.

### 6. Special Cases

- Missing clock-out: do not check `Clock Out Outside`. Add note `Missing Clock Out Time`.
- Duplicate entries for the same employee/date/project/times: consolidate into one employee row and add note `Duplicated time entries`.
- Different projects: if an employee clocked into two or more different job sites on the same date, check `Different Project`.
- Multiple entries for one employee: consolidate into one report row. If any entry has a flagged clock-in, set Clock In Outside true. If any entry has a flagged clock-out, set Clock Out Outside true. Preserve important notes.
- Ambiguous row: include a short note beginning `Ambiguous:` and ask the user to decide that row.

## Final Report Format

Sort alphabetically by last name.

Markdown table:

| Last Name | First Name | Clock In Outside | Clock Out Outside | Different Project | Notes |
|---|---|---:|---:|---:|---|

Use `TRUE` / `FALSE` for the three flag columns. Keep notes brief.

Then provide a CSV block:

```csv
Last Name,First Name,Clock In Outside,Clock Out Outside,Different Project,Notes
```

Do not include a title row, color coding, extra columns, screenshots, or the full working ledger in the final unless the user asks.

## Review Cycle

If the user corrects a pin as close enough, at the Treadwell office, or otherwise OK, accept that as ground truth and update the row. If that removes all flags/notes for an employee, remove the employee from the report.

If the user gives a general correction such as "X is close, don't flag" and that employee only has location flags, clear those flags without asking which field. Ask only when the employee also has another note/flag that makes the correction ambiguous.

## Model Guidance for Claude

Use Claude Sonnet 5.5 for normal audits: it is the best balance of speed, reasoning, and cost for browser work plus a structured report.

Use Claude Haiku 5.5 only for post-processing an already-collected Issues list into CSV/table form.

Use Claude Opus 5.5 only when the map data is messy, many rows are ambiguous, or the audit has already failed once on Sonnet.
