# Cover Letter templates — FIRST DRAFT COPY, NOT SIGNED OFF

The optional cover letter shown to the customer in the portal **before** the
proposal itself. Seven files, generated — not hand-typed:

```
python backend/prepare_cover_letter_templates.py
```

```
Direct/Epoxy.docx   Direct/Polish.docx   Direct/Combo.docx
GC/Epoxy.docx       GC/Polish.docx       GC/Combo.docx
Gyp/Gyp.docx        (audience-agnostic)
```

That script copies `docs/Cover Letter/Treadwell Letterhead.docx` byte-for-byte
(logo, footer bar, page setup) and appends the body copy. **Edit the copy in the
script and re-run it — do not hand-edit these .docx files**, or the next
regeneration silently discards the change. The two reference files it reads live
under `docs/Cover Letter/` and are Hanz's originals; they are inputs to the
generator, not runtime files.

## Why audience folders

`cover_letter_writer.TEMPLATE_PICKER` is keyed on `(work_type, audience)` and
these folders mirror `proposal_writer.TEMPLATE_PICKER`'s — `Direct/`, `GC/`,
`Gyp/` — including its asymmetry: **gyp ignores audience** (`audience` is `None`
there and here) and **sealer / budget have no letter at all**, so
`pick_template` falls back to `Direct/Epoxy.docx` and `has_template()` returns
False for them.

Two deliberate departures from the proposal picker, both because these files are
generated and Kyle's are not:

- **GC gets its own `Combo.docx`.** The proposal reuses the GC resinous document
  for a GC combo bid because no GC combo Word file was ever made. A *letter*
  doing the same would tell a combo customer, in prose, that the pages behind it
  are an epoxy proposal — half the scope simply missing.
- **`GC/*` currently carries the SAME body copy as `Direct/*`.** Hanz's source
  PDF has no GC variant, and inventing contractor-flavoured sentences would put
  wording nobody approved in front of a customer. The files are separate so the
  copy pass can diverge them without a code change. **This is a question for the
  copy review: should the GC letter read differently?**

## The copy is a draft. It needs Hanz's review.

The wording is adapted from `1 Treadwell Proposal Cover Letter Templates.pdf`,
templates 1-4. Those were written as outbound **emails**; this is a portal
**document page**, so three things were changed deliberately:

| Source (email) | Here (document) |
|---|---|
| `Subject Line: TREADWELL Proposal - Epoxy Flooring - {Job_Name}` | A red underlined document title, `Epoxy / Resinous Flooring Proposal - {{job_name}}`. The "Subject Line:" label is gone; the heading itself is kept because Hanz's own `Treadwell Cover Letter - Example1.docx` opens with one. |
| "I've attached our Epoxy/Resinous Flooring proposal to this email." | "The pages that follow are our Epoxy / Resinous Flooring proposal for this project. A few things to note:" — there is no email and no attachment. |
| The cc note | Dropped. |

Templates 5 (the gyp addendum note) and 6 (BuildingConnected) were out of scope
and are not built.

## Placeholders that still need real wording

Every one of these prints **in italics, in square brackets**, so it is obvious on
the page. They are not `{{tokens}}` — nothing fills them; they are questions for
the copy pass. Square brackets rather than braces on purpose: a `{{token}}` would
be substituted or silently left behind, whereas `[THICKNESS - pick one: ...]`
prints as itself and reads as an instruction.

| Placeholder | In | Why it is not a token |
|---|---|---|
| `[THICKNESS - pick one: 1/8" / 3/16" / 1/4" nominal thickness with urethane topcoat.]` | Epoxy, Combo | The tool has no thickness field anywhere. |
| `[COVE HEIGHT - pick one: 4" / 6" / 8".]` | Epoxy, Combo | `cove_lf` gives the length, never the height. |
| `[AGGREGATE EXPOSURE - pick one: Class A ... / Class B ... / Class C ...]` | Polish, Combo | No aggregate-exposure field. |
| `[SHEEN - pick one: Level 2 (400 grit) / Level 3 (800 grit).]` | Polish, Combo | No sheen field. |
| `[SCHEDULE - assumes 1 mobilization per phase ...]` | all | Follows the filled `{{schedule_notes}}`; the mobilization assumption is not modelled. |
| `[OPTIONS - keep the lines that apply: ...]` | all | The proposal's priced options live in its own PRICE block; these are the unpriced "add for ..." notes from the source email, and there is no field behind them. |
| `[SOUND MAT - state the mat thickness and where it goes ...]` | Gyp | No sound-mat field. |
| `[NOTES - add the ones this job needs: spec thickness conflict / STC & IIC / excluded mat / GC storage]` | Gyp | Source template 4 lists four job-specific notes. Writing them as boilerplate would put claims about a spec nobody has read into a customer document, so they ship as one instruction line instead of four invented sentences. |
| `[ESTIMATOR EMAIL]` | all | `{{estimator_name}}` exists and is filled; there is no estimator-email token in the proposal vocabulary. Adding one is a small change to `computeTokenValues` + `_ensure_value_aliases` if Hanz wants the signature complete. |

## Tokens that ARE filled

Same vocabulary as the proposal templates, filled by the same substitution pass
(`proposal_writer._replace_in_paragraph` via `cover_letter_writer`):

`{{proposal_date}}`, `{{job_name}}`, `{{system_name}}`, `{{epoxy_system_name}}`
(Combo), `{{texture}}`, `{{epoxy_sf}}`, `{{polish_sf}}`, `{{cove_lf}}`,
`{{schedule_notes}}`, `{{estimator_name}}`, and the gyp set
`{{gyp_soft_thickness}}` / `{{gyp_soft_sf}}` / `{{gyp_hard_thickness}}` /
`{{gyp_hard_sf}}`.

`{{proposal_date}}` is the one the Proposal Review screen stamps at generate
time. A server-side replay (the portal's on-demand PDF) may not carry it, so
`cover_letter_writer._ensure_cover_letter_values` backfills it from the bid date
rather than from a clock — this box runs ~13 hours ahead of Central and
`datetime.now()` would date letters a day out.

## The date is a floating box, and it is the only one

`Treadwell Cover Letter - Example1.docx` floats the date in a small centred text
box anchored over the letterhead artwork rather than typing it on a line, and
these templates copy that box verbatim (`_install_date_box` lifts the whole
`<w:r>` out of the example and swaps the six runs spelling "8/26/26" for one
`{{proposal_date}}`, in both the `mc:Choice` and the `mc:Fallback` copy).

Consequences worth knowing before editing anything here:

- `/api/coverletter-template` reports it truthfully: exactly one block comes back
  with `in_txbx: true` and `txbx: 0`, and `geometry.boxes` has exactly one entry.
  It is the **last** id in the walk — `_iter_body_editable` visits body
  paragraphs before text boxes.
- There is no `box_overrides` channel on the cover letter. The estimator never
  moves or resizes the date, so no geometry is written back.
- A paragraph override on the date block edits the `mc:Choice` copy only; the
  VML fallback keeps the template's text. That is `_is_fallback_paragraph`'s
  existing behaviour, shared with the proposal, and it is harmless because the
  token fill (which is what actually sets the date) walks both.

## One deviation from `Treadwell Cover Letter - Example1.docx`

**Body text is 11pt, the example is 12pt.** Combo carries two full system
sections (six numbered items) and runs onto a second page at 12pt — and page two
has no letterhead artwork, because the art is anchored to page one. If the copy
pass shortens Combo, the size can go back to 12pt in
`prepare_cover_letter_templates.py` (`BODY_PT`).
