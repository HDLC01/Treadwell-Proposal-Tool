# Cover Letter templates — Direct is Will's wording; GC and Gyp are still draft

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
- **`Direct/*` and `GC/*` have diverged — as of 2026-09-03 they are different
  copy.** They shipped identical because the source PDF had no GC variant, and
  inventing contractor-flavoured sentences would have put wording nobody approved
  in front of a customer; the separate files existed so a copy pass could diverge
  them without a code change. That pass happened for Direct only. Will Buchanan
  sent the Direct text verbatim — *"In addition to what Greg sent you for GC
  projects please use the text template below for direct projects. The highlighted
  text should be pulled from the intake form"* — and `DIRECT_COPY` in the generator
  is it, to the comma. **GC still waits on Greg's text**, which has not reached this
  repo; `spec_for()` hands GC and Gyp the shared `COPY` until it does. The same
  rule as before applies to it: do not invent it.

## The copy is a draft. It needs Hanz's review.

The wording is adapted from `1 Treadwell Proposal Cover Letter Templates.pdf`,
templates 1-4. Those were written as outbound **emails**; this is a portal
**document page**, so three things were changed deliberately:

| Source (email) | Here (document) |
|---|---|
| `Subject Line: TREADWELL Proposal - Epoxy Flooring - {Job_Name}` | A red underlined document title, `Epoxy / Resinous Flooring Proposal - {{job_name}}`. The "Subject Line:" label is gone; the heading itself is kept because Hanz's own `Treadwell Cover Letter - Example1.docx` opens with one. |
| "I've attached our Epoxy/Resinous Flooring proposal to this email." | **GC and Gyp:** "The pages that follow are our Epoxy / Resinous Flooring proposal for this project. A few things to note:" — there is no email and no attachment. **Direct:** just "A few things to note:", per Will's text. He is right that the first half was redundant — the red underlined title one line above already names the proposal that follows, so the letter was saying it twice. |
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
| `[THICKNESS - pick one: 1/8" / 3/16" / 1/4" nominal thickness with urethane topcoat.]` | **GC** Epoxy, Combo | Nothing captured a thickness when this shipped. **Direct no longer has it**: the intake form asks (`system_thickness`), and `{{cover_system_line}}` prints the answer. Retiring it on the GC side is a copy decision waiting on Greg's text, not a code change. |
| `[COVE HEIGHT - pick one: 4" / 6" / 8".]` | **GC** Epoxy, Combo | `cove_lf` gives the length, never the height. **Direct no longer has it** — `{{cover_system_line}}` appends `6" Integral Cove Base` from `cove_height`, and drops the clause entirely when `cove_lf` is 0. |
| `[AGGREGATE EXPOSURE - pick one: Class A ... / Class B ... / Class C ...]` | Polish, Combo (**both** audiences) | No aggregate-exposure field. Kept on Direct on purpose: Will's Materials / System line is an epoxy one and he wrote nothing about polished concrete, so Direct's polish letter takes his *structure* — the Area line, the fixed Schedule sentence, the closings — and keeps its own system wording. Exposure and sheen are real spec decisions; guessing them is not a copy edit. |
| `[SHEEN - pick one: Level 2 (400 grit) / Level 3 (800 grit).]` | Polish, Combo (**both** audiences) | No sheen field. Same reasoning as the row above. |
| `[SCHEDULE - assumes 1 mobilization per phase ...]` | **GC and Gyp** | Follows the filled `{{schedule_notes}}`; the mobilization assumption is not modelled. **Direct no longer has it, and no longer prints `{{schedule_notes}}` either** — Hanz's call was a fixed sentence, and Will wrote the whole thing out: it states the assumption the price was built on and invites the customer to correct it, which a filled-in note cannot do. The proposal behind the letter still carries `{{schedule_notes}}`, and the estimator can edit this paragraph in the document editor for a job that phases differently. |
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

**Which letter uses which is no longer uniform.** Direct's epoxy letter states no
square footage at all — Will's Materials / System line replaced the sentence that
carried `{{epoxy_sf}}`, `{{cove_lf}}` and `{{texture}}`, so on a job where the
estimator types real area words the SF figure appears only in the proposal behind
the letter. That is his text and his call; it is recorded here because it is the
kind of omission that looks like a bug six months from now.

## The three Direct tokens are COMPUTED, and computed TWICE

`{{greeting}}`, `{{work_areas}}` and `{{cover_system_line}}` are not draft fields
copied through. Each is derived, and each is derived in **two** places that must
agree:

| Where | Serves |
|---|---|
| `computeTokenValues` in `frontend/js/proposal-review.js` | the cover-letter editor's on-screen preview (`clTokens()` borrows the function) |
| `_ensure_cover_letter_values` in `backend/cover_letter_writer.py` | generate, **and** the portal's server-side replay of a pinned revision |

A token resolved on only one side previews as a raw `{{token}}` over a correct PDF
— exactly the bug PR #431 fixed for `{{proposal_date_short}}` — and an estimator
proofreading on screen cannot tell that from a broken document. Change one side,
change the other; a test asserts they agree.

- **`{{greeting}}`** — the contact's first name and nothing else, `"Brandon,"`.
  Falls back to `"Hello,"` rather than a bare comma, and treats an email address
  or a lone initial in the contact box as *not* a first name. `"brandon"` is
  capitalised; `"McDonald"` is left exactly as typed.
- **`{{work_areas}}`** — the estimator's own words for what the floor covers
  (`work_areas` on the intake form). Falls back to `area_description`, the SF
  line, rather than printing an empty `Area:` — the letter's list items are
  static paragraphs and `cover_letter_writer` deliberately does not port the
  `{{#block}}` expansion that could drop one.
- **`{{cover_system_line}}`** — `1/4" MACRO Flake Single Broadcast with 6"
  Integral Cove Base`, composed from `system_thickness`, `system_name`,
  `cove_lf` and `cove_height`. Two behaviours no template text can express:
  the thickness prefix is **skipped when Kyle's system name already states one**
  (three of his fifteen do, e.g. `3/16" Urethne Cement With Color Fast (SLB)` —
  an inch fraction already in the name wins, so a disagreeing pick cannot print
  two contradictory thicknesses), and the whole cove clause is **dropped on a
  job with no cove** rather than printing the "0 LF" the proposal body still
  does.

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
