---
name: Treadwell Proposal Generator
description: Treadwell's own bid paperwork — intake to priced estimate to signed proposal, in minutes.
colors:
  signal-red: "#c8102e"
  oxblood: "#9e001f"
  cellar-red: "#6c0015"
  warm-red-tint: "#ffdad8"
  cool-red-tint: "#fbe9ec"
  red-wash: "#fdf5f6"
  template-red: "#a71320"
  near-black: "#1b1c1c"
  umber-ink: "#5c403f"
  muted-ink: "#8a857c"
  warm-paper: "#fbf9f8"
  card-white: "#ffffff"
  raised-paper: "#f5f3f3"
  warm-stone: "#e9e8e7"
  stone-dim: "#dbdad9"
  hairline: "#e4e2e2"
  umber-hairline: "rgba(92,64,63,.16)"
  ledger-green: "#0f7b34"
  caution-bronze: "#7a5c00"
  caution-ground: "#fdf6e3"
  danger-red: "#ba1a1a"
  amber: "#f59e0b"
  amber-ink: "#b26a00"
  overdue-red: "#b3261e"
  due-soon-bronze: "#9a5b00"
  calm-blue: "#4a6b8a"
  workbook-input: "#fff4a3"
  workbook-calc: "#c6efce"
  workbook-total: "#41ecff"
  workbook-border: "#b1b1b1"
typography:
  display:
    fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "34px"
    fontWeight: 800
    lineHeight: 1.1
  headline:
    fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    letterSpacing: "-0.01em"
  title:
    fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "13px"
    fontWeight: 700
  body:
    fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "10.5px"
    fontWeight: 700
    letterSpacing: "0.05em"
  numeric:
    fontFamily: "Consolas, 'SF Mono', ui-monospace, SFMono-Regular, Menlo, 'Roboto Mono', monospace"
    fontSize: "13px"
    fontWeight: 600
    fontFeature: "tabular-nums"
  document:
    fontFamily: "'Zetta Serif Book', 'Zetta Serif', Georgia, 'Times New Roman', serif"
    fontSize: "9pt"
    fontWeight: 400
    lineHeight: 1.32
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  pill: "999px"
  full: "50%"
spacing:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "12px"
  xl: "16px"
  xxl: "22px"
components:
  button-primary:
    backgroundColor: "{colors.signal-red}"
    textColor: "{colors.card-white}"
    rounded: "{rounded.md}"
    padding: "8px 14px"
    typography: "{typography.title}"
  button-primary-hover:
    backgroundColor: "{colors.oxblood}"
  button-primary-disabled:
    backgroundColor: "{colors.signal-red}"
    textColor: "{colors.card-white}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.umber-ink}"
    rounded: "{rounded.md}"
    padding: "8px 14px"
    typography: "{typography.title}"
  button-ghost-hover:
    backgroundColor: "{colors.raised-paper}"
    textColor: "{colors.signal-red}"
  chip:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.umber-ink}"
    rounded: "{rounded.pill}"
    padding: "6px 12px"
  chip-selected:
    backgroundColor: "{colors.oxblood}"
    textColor: "{colors.card-white}"
  badge:
    backgroundColor: "{colors.warm-stone}"
    textColor: "{colors.umber-ink}"
    rounded: "{rounded.pill}"
    padding: "1px 8px"
    typography: "{typography.label}"
  card:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.near-black}"
    rounded: "{rounded.lg}"
    padding: "16px"
  card-working:
    backgroundColor: "{colors.raised-paper}"
    textColor: "{colors.near-black}"
    rounded: "10px"
    padding: "15px"
  input:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.near-black}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
    height: "38px"
  input-focus:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.near-black}"
  nav-item:
    textColor: "{colors.near-black}"
    rounded: "7px"
    padding: "0 10px"
    height: "42px"
  nav-item-active:
    backgroundColor: "rgba(200,16,46,.1)"
    textColor: "{colors.oxblood}"
---

# Design System: Treadwell Proposal Generator

## Overview

**Creative North Star: "The Estimator's Desk"**

This is a warm paper desk with two foreign documents lying open on it. The desk is the app: a
cream-white ground (`#fbf9f8`), brown-tinted ink, hairline rules, and a single red used sparingly
enough that it still means something. The two documents are Kyle's estimate workbook and the Word
proposal, and the governing idea of this whole system is that **neither one is redressed in the
app's clothes**. The estimate grid wears the workbook's own cell fills, lifted colour-for-colour
out of `estimate_sheet_5.7.xlsx`. The proposal preview renders at true 8–9pt in the template's own
serif, on white, with a paper shadow under it. An estimator looking at either one is looking at the
real artefact, not a re-skin of it. The app's job is to be the surface they sit on and the chrome
around them — and to stay out of the way.

The personality that follows is warm, dense, and plainly spoken. Dense because this is a daily
production tool for three or four people at a desk, not a landing page: rows are tight, labels are
small caps, and a screen is expected to hold a lot. Warm because that is the only thing separating
this from every grey estimating SaaS — the greys carry a brown cast, the shadows are mixed from
`rgba(60,50,40)` rather than black, and the secondary ink is `#5c403f`, a genuine umber. Plainly
spoken because the copy and the states do not hedge: a control that cannot affect the price says
so in words rather than disappearing, and a figure that was hand-edited carries a mark saying it
no longer matches the estimate.

What this system rejects is settled and confirmed: cool neutral-grey SaaS chrome, emoji standing
in for icons, a second type stack inside one page, and decorative elevation. Each of those was
tried here and removed, and the reasons are written into the source at the point of removal. The
palette and the type pairing are closed — new work extends this system, it does not propose a new
one.

**Key Characteristics:**
- Warm cream ground with umber-tinted greys; a cool hairline is the tell that something is off-system
- One red accent, rationed: active nav, primary action, focus ring — and nothing else
- Flat surfaces separated by hairlines and tonal steps, not by shadow
- Density over whitespace; small caps labels, 14px body, tight rows
- Figures are tabular-nums everywhere, always, without exception
- Two quarantined fidelity palettes — the workbook and the printed page — that the app palette never touches
- Icons are inline SVG at 24×24, stroke-only, taking their colour from the element they sit in

## Colors

A warm cream and umber neutral field with one rationed red accent, plus two quarantined palettes
that reproduce documents rather than express the brand.

### Primary

- **Signal Red** (`#c8102e`): The app accent, and the only colour in the system that is allowed to
  compete with content. It carries the active navigation row (as a 10% tint behind `#9e001f`
  text), the primary button at rest, every focus ring, the CRM board's scrollbar thumb, and
  notification badges. It is deliberately *not* the marketing logo red (`#e52b2e`, which lives
  only in `img/treadwell-bison.svg` and `img/treadwell-lockup.svg`); the two are different on
  purpose and both correct in their own context.
- **Oxblood** (`#9e001f`): The pressed and hovered state of Signal Red, and the colour of accent
  *text* on a light ground where Signal Red would be too bright to read. Primary buttons darken
  into it on hover; active nav labels are set in it. It is also the resting accent of the legacy
  four-screen wizard and the proposal editor, where it has been the accent since before Signal Red
  existed — that is history, not a second opinion.
- **Cellar Red** (`#6c0015`): The deepest tone, below Oxblood. Reserved for the wizard's headings
  and the darkest pressed states. Not for large areas.

### Secondary

There is no second accent hue, and inventing one would break the rationing that makes the red
work. What looks like a second accent family is three tints of the same red, used as grounds:

- **Warm Red Tint** (`#ffdad8`): The warm-family accent ground — selected rows in the county
  picker, hovered step pills, the toggled-on state in the formatting ribbon. Legible with Oxblood
  text on top.
- **Cool Red Tint** (`#fbe9ec`): The same role in the analytics and calendar family, which runs a
  fractionally cooler set. A live drift; prefer Warm Red Tint in new work.
- **Red Wash** (`#fdf5f6`): The faintest accent ground, for a whole row that needs to read as
  touched rather than selected.

### Tertiary

- **Template Red** (`#a71320`): Not an app colour. It is the Wingdings square red baked into
  Kyle's Word template list styles, mirrored on screen so the proposal preview's bullets match
  what prints. It appears in exactly two rules and must never be used as a UI colour.

### Neutral

- **Warm Paper** (`#fbf9f8`): The page ground under everything. The warmest note in the system and
  the single value most responsible for the app not reading as generic.
- **Card White** (`#ffffff`): Raised surfaces — cards, panels, the nav rail, inputs, the proposal
  sheet. White is *above* paper here, not below it.
- **Raised Paper** (`#f5f3f3`): The recessed step — board columns, working panels, hovered rows,
  ghost-button hover. The second tonal level and the main alternative to a shadow.
- **Warm Stone** (`#e9e8e7`): Filled chips, count badges, scrollbar tracks — a neutral that reads
  as a container rather than a surface.
- **Stone Dim** (`#dbdad9`): Heavier dividers and the borders of form controls in the legacy
  wizard.
- **Hairline** (`#e4e2e2`): The default 1px rule. Every card, input, chip and table edge.
- **Umber Hairline** (`rgba(92,64,63,.16)`): The same rule, tinted with the ink instead of with
  black. Used on the Items and Markup pages and visibly warmer against cream. Preferred where a
  page is doing a lot of ruling.
- **Near Black** (`#1b1c1c`): Body and heading text. Not pure black.
- **Umber Ink** (`#5c403f`): Secondary text — labels, hints, captions, inactive nav, unit
  suffixes. The brown cast is the identity; a neutral grey here is the most common way a new
  screen ends up looking like somebody else's product.
- **Muted Ink** (`#8a857c`): Tertiary text and disabled labels, below Umber Ink.

### Status

Status colours are a separate scale from the brand red on purpose, so that ordinary page chrome
never reads as an alarm.

- **Ledger Green** (`#0f7b34`): Success, paid, approved, on.
- **Caution Bronze** (`#7a5c00`) on **Caution Ground** (`#fdf6e3`): The proposal is fine and the
  bid can still go out — look at this before sending. Never red.
- **Amber** (`#f59e0b`) and **Amber Ink** (`#b26a00`): Temporarily-unlocked cells and hand-edited
  lines that now differ from the computed estimate.
- **Danger Red** (`#ba1a1a`): Destructive confirmation only.
- **Overdue Red** (`#b3261e`), **Due Soon Bronze** (`#9a5b00`), **Calm Blue** (`#4a6b8a`): The bid
  calendar's own urgency scale, deliberately not the brand red.

### Quarantine

- **Workbook Input** (`#fff4a3`), **Workbook Calc** (`#c6efce`), **Workbook Total** (`#41ecff`),
  **Workbook Border** (`#b1b1b1`): Lifted cell-for-cell from `estimate_sheet_5.7.xlsx`, along with
  a bright-yellow toggle fill, a dark-green polish-labour fill, a light-purple note fill and a grey
  header fill. Kyle recognises his own sheet by these. They are a reproduction of a source
  document and are off-limits to every other surface in the app.

### Named Rules

**The Rationed Red Rule.** Signal Red appears on the active navigation row, the primary action,
and the focus ring. That is the list. Urgency, status, and emphasis each have their own scale
precisely so the accent keeps meaning "this is the thing to press".

**The Warm Cast Rule.** Every grey in this system carries warmth, and every shadow is mixed from
`rgba(60,50,40)` rather than from black. A cool neutral or a black shadow on a Treadwell screen is
the single most reliable sign that a rule came from somewhere else. When in doubt, pick the warmer
of two candidates.

**The Corrected-Pages Rule.** `frontend/library.html` and `frontend/markup.html` currently declare
`--red:#9e001f` as their primary and describe Signal Red in a comment as "a brighter substitute".
Those two pages are the ones that disagree with this file, not the other way around — Signal Red
is primary, confirmed against the fourteen pages and the global navigation that already use it.
Do not cite those comments as precedent, and do not propagate `#9e001f`-as-primary to a third
page. Correcting them is a separate, approved change; until it happens this file is the authority
and they are the exception.

**The Quarantine Rule.** The workbook palette and the printed-page palette reproduce documents.
They never leak outward into app chrome, and app tokens never leak inward into them. A "tidy-up"
that harmonises either one with the brand palette is a regression, not a cleanup.

## Typography

**Display / Body Font:** Inter, falling back to `system-ui`, `-apple-system`, Segoe UI, Roboto
**Numeric Font:** Consolas / SF Mono / ui-monospace stack
**Document Font:** Zetta Serif Book (the Word template's own face; falls back to Georgia)

**Character:** One neutral, high-legibility sans doing all the work, with a monospace reserved for
figures and a serif reserved for the printed page. There is no display face and no pairing to
admire — the type is a delivery mechanism for dense information, and its restraint is what lets
the numbers and the red carry all the emphasis.

**A fact this file records rather than idealises: Inter is not shipped.** There is no `@font-face`
rule and no font CDN link anywhere in the codebase, so Inter renders only on a machine that
already has it installed and otherwise resolves to Segoe UI on Windows. Roughly a hundred rules
also specify bare `system-ui`, skipping the Inter stack entirely. The stack is the intent; the
system face is the everyday reality. Design to the fallback.

### Hierarchy

- **Display** (800, 34px, 1.1): A single headline figure — the analytics hero number. Rare by
  design.
- **Headline** (700, 20px, −0.01em): Page titles across the app shell. The legacy wizard sets its
  `h1` larger (800, 28px) in Cellar Red; new pages follow the 20px form.
- **Title** (700, 13px): Section headings, card headers, drawer section labels, button text.
- **Body** (400, 14px, 1.55): Everything else. Prose is held to roughly 62ch where it appears in
  panels.
- **Label** (700, 10.5px, 0.05em, uppercase): Field labels, column headers, nav section headings,
  eyebrow text. The dominant small-text form in the app.
- **Numeric** (600, 13px, tabular-nums): Money, rates, quantities, cell references, percentages.
- **Document** (400, 9pt, 1.32): The proposal preview only, at the template's true point sizes.

### Named Rules

**The One Stack Rule.** A page sets one type family and uses it for headings, buttons, body and
totals alike. A total set in one face beside the sentence explaining it in another is the defect
this rule exists to prevent — it has been fixed once already and should not return.

**The Tabular Money Rule.** Every figure that could ever sit above or below another figure gets
`font-variant-numeric: tabular-nums`. Seventy-nine declarations across seventeen files already
honour this without a single exception; it is the most consistent convention in the codebase.
Figures that do not align down a column are a bug in an estimating tool, not a style preference.

**The Fallback-First Rule.** Never rely on a metric only Inter provides — no optical letter-spacing
tuned to Inter's widths, no layout that breaks if the face is 2% wider. The page must look correct
in Segoe UI, because on most of these machines that is what it is.

## Layout

The app has two spatial models. The **document surfaces** (proposal editor, estimate grid) are
full-bleed working canvases with fixed side rails and their own scroll containers. Everything else
is a **centred single column** on the warm paper ground: a max-width, `margin: 0 auto`, and
generous bottom padding for a sticky action bar. Observed container widths cluster at 1100px for
ordinary pages, 1660px for the wide board and table pages, 1000px for the polish estimator, 880px
for the legacy wizard, and 560px for narrow forms.

Density is deliberately high. Body padding runs `26–28px` at the sides, cards take `15–20px`
internally, and rows are tight. The spacing rhythm is an 8px-leaning scale in practice — gaps of
8px, 6px, 10px, 12px and 14px account for the overwhelming majority of every gap in the app — but
**no spacing token exists in the codebase**; every value is a literal. The `spacing` scale in this
file's frontmatter is the observed rhythm written down so new work has something to reuse, not a
variable that can be referenced today.

The workspace navigation is a fixed 240px rail that shifts the page body with `margin-left` at
768px and above, and becomes an overlay drawer with a backdrop below it. Anything `position: fixed`
must track the rail itself — margin cannot move a fixed element, and a fixed panel that ignores
this sits underneath the open nav.

Breakpoints are not yet a scale. Sixteen distinct widths are live (480, 520, 560, 600, 640, 700,
760, 767, 768, 820, 900, 940, 1000, 1080, 1100, 1400), and both 767px and 768px appear in
quantity. 768px is the real hinge — it is where the nav switches between rail and drawer — and
767px is the same decision spelled differently.

### Named Rules

**The 768 Rule.** 768px is the app's one structural breakpoint, because it is where navigation
changes form. Write `max-width: 767px` / `min-width: 768px` and nothing in between. Do not
introduce a seventeenth near-miss width for a single component; find the nearest existing one.

**The Rail-Aware Fixed Rule.** Any `position: fixed` element on a page with the workspace nav must
offset itself under `html.tw-nav-open` using the rail's own width variable. Margin on `body` moves
the flow; it does not move a fixed panel.

## Elevation & Depth

**This is a flat system.** Depth is carried by a tonal stack and a hairline, not by shadow: Warm
Paper is the ground, Card White sits above it, Raised Paper sits recessed within it, and a 1px
Hairline separates anything that needs separating. The overwhelming majority of surfaces in this
app have no `box-shadow` at all, and that is the correct default.

Shadow is a response, not a resting property, and it comes in exactly two legitimate registers.
The first is a **warm ambient lift**, mixed from `rgba(60,50,40)` rather than black, applied when
a card answers the pointer. The second is a **hard overlay shadow** in true black, reserved for
things that genuinely float above the page — the drawer, the context menu, the notification panel,
a modal, a card mid-drag. There is a third thing that looks like a shadow and is not: the
proposal sheet's own paper shadow, which is representational. It is a picture of a sheet of paper
and casts the shadow a sheet of paper casts.

### Shadow Vocabulary

- **Ambient rest** (`box-shadow: 0 1px 2px rgba(60,50,40,.05), 0 4px 16px rgba(60,50,40,.055)`):
  The warm baseline for a card that participates in hover. Barely visible by design.
- **Ambient lift** (`box-shadow: 0 2px 4px rgba(60,50,40,.06), 0 10px 28px rgba(60,50,40,.10)`):
  The hover answer to Ambient rest, usually paired with `transform: translateY(-1px)`.
- **Overlay** (`box-shadow: 0 16px 48px rgba(0,0,0,.30)`): Drawers, modals, and panels that cover
  the page. Black is correct here — this shadow says "there is a gap between this and the page".
- **Menu** (`box-shadow: 0 6px 20px rgba(0,0,0,.18)`): Context menus and dropdowns, a smaller
  member of the overlay family.
- **Paper** (`box-shadow: 0 1px 3px rgba(0,0,0,0.16), 0 4px 14px rgba(0,0,0,0.10)`): The rendered
  proposal page only. Representational, not a UI token.

### Named Rules

**The Flat-By-Default Rule.** A surface is flat at rest. Shadow appears in response to state —
hover, drag, float — or not at all. Elevation with nothing under it is decoration, and a card is
for something that is genuinely a separate object.

**The Warm Shadow Rule.** An in-page shadow is mixed from `rgba(60,50,40, …)`. Only an element
that floats clear of the page gets a black one. A black ambient shadow on a card is cold light on
a warm desk.

**The Seven Strays Rule.** Seven resting cards currently carry a plain
`box-shadow: 0 1px 3px rgba(0,0,0,.05)` — a cold shadow on a surface that is not responding to
anything. That is an inconsistency to be cleaned up, not a third register. Do not copy it into a
new component; use a hairline, or Ambient rest if the card genuinely hovers.

## Shapes

Soft-cornered, fully rounded where something is a token and gently rounded where something is a
surface. The form language has four steps and one special case: pills at `999px` for anything that
labels, counts or filters; `6px` for small controls; `8px` for buttons and inputs; `12px` for
cards and containers; and `50%` for avatars and status dots. Pills are the most consistent shape
in the app — over fifty declarations, essentially no drift — and they are what makes a chip read
as a chip at a glance.

Borders do a great deal of the work that shadow does elsewhere. The default is a 1px hairline;
beyond that, a **3–4px left border** is the app's established status channel, used for calendar
cards' urgency, alert severity, the locked canonical block on proposal review, and AI-flagged
lead cards. A left bar says "this row has a state"; it never says "this row is important".

The radius vocabulary is the one place where this codebase has visibly drifted. Six token names
are live with conflicting values — `--r:12px`, `--r-lg:12px`, `--r-md:8px`, `--r-s:7px`,
`--r-sm:6px`, `--radius:14px` — and `--r-s` and `--r-sm` differ by one letter and one pixel. That
pair is the fingerprint of a model that could not find an existing token and invented a neighbour.

### Named Rules

**The Pill Rule.** If it counts, labels, filters or tags, it is `999px`. If it contains content,
it is `8px` or `12px`. There is no middle case.

**The No Near-Miss Rule.** Reuse a radius name that exists, or say in review that you could not
find one. Never coin `--r-s` beside `--r-sm`, `--surface-2` beside `--surf-high`, or any other
one-letter variant of a live token. A fifth way to draw a card is a bug.

## Components

### Buttons

Buttons are the loudest thing on a Treadwell screen and they are still quiet. Solid, small, and
confident; no gradients, no glow, and a 1px press that makes them feel like real keys.

- **Shape:** Gently rounded (`8px`); the portal's larger touch-target variant uses `7px`.
- **Primary:** Signal Red fill, white text, no border, `8px 14px` padding, 13px/600. The portal's
  full-width form buttons raise this to a 42px minimum height and 700 weight for touch.
- **Hover / Focus:** Hover darkens to Oxblood. Focus-visible is a 2px Signal Red outline at 2px
  offset — never `outline: none` without a replacement.
- **Active:** `transform: translateY(1px)`. A real, small press.
- **Ghost:** Transparent fill, Umber Ink text, hairline border. On hover the text and the border
  both go to Signal Red and the ground goes to Raised Paper — the border and the label move
  together, never one without the other.
- **Disabled:** `opacity: .5` plus `cursor: not-allowed`. Use `cursor: wait` only when the button
  actually started something that is still running.

### Chips

- **Style:** Pill (`999px`), hairline border, white or Warm Stone ground, Umber Ink text, 600
  12.5px, `inline-flex` with a 6px gap. A count rides inside as a second nested pill.
- **State:** Selected fills with Oxblood and turns the label white; the nested count goes to a 24%
  white wash so it stays readable on the fill. Hovered-but-unselected moves the border and the
  text to Signal Red without filling.

### Cards / Containers

- **Corner Style:** Gently curved (`12px`; 8–10px on denser boards).
- **Background:** Card White for a card that presents a record; **Raised Paper for a working
  panel** — an input group, a calculator section, a step in the estimator. The distinction is
  real: white means "this is a thing", recessed means "this is where you work".
- **Shadow Strategy:** None at rest. See Elevation & Depth; add Ambient rest only if the card
  genuinely responds to the pointer.
- **Border:** 1px Hairline, or Umber Hairline on heavily ruled pages. A 3px left border adds a
  status channel.
- **Internal Padding:** `15–20px`; `12px` on board cards.

### Inputs / Fields

- **Style:** Card White ground, 1px Hairline border, `8px` radius, `8px 10px` padding, and
  `font: inherit` — always. Minimum height 36px, 38–42px where touch matters.
- **Focus:** Border moves to Signal Red and a 2px Signal Red outline appears at 2px offset. Inside
  the spreadsheet grid the offset goes negative (`-2px`) so the ring sits on the cell edge rather
  than over its neighbour.
- **Read-only:** Keeps full contrast, loses the affordance — the value stays legible in Umber Ink
  and the cursor goes to `default`. A read-only field's focus ring is muted to the hairline colour
  rather than the red edit cue.
- **Disabled:** Drops to `opacity: .45–.5`. Read-only and disabled must never look the same.
- **Validation:** On blur, not on keystroke. Never scold someone mid-word.

### Navigation

A fixed 240px white rail with a hairline right edge, injected on every page. Section headings are
Label type in Umber Ink at 70% opacity. Rows are 42px (48px under 768px) with a `7px` radius, a
20px icon slot, and an optional tag pill pushed to the right margin. Hover fills with Raised
Paper. **Active is a 10% Signal Red tint with Oxblood text at 600 weight, and the row's icon
recolours with the label** — the icon inherits, it is not separately coloured. Below 768px the
rail becomes a drawer over a backdrop, and a closed drawer is genuinely inert: `visibility: hidden`
plus `pointer-events: none`, not merely translated off-screen.

### Icons

The app has exactly one icon set: `frontend/js/icons.js`, seventy-five hand-rolled inline SVG
glyphs. Every one is a 24×24 viewBox with `fill="none"`, `stroke="currentColor"`, stroke-width 2,
round caps and joins, `aria-hidden="true"`, and a default rendered size of 16px. `currentColor` is
the entire point: a danger button's icon is red because the button is red, and a disabled row's
icon dims with the row. Glyphs are not click targets — `pointer-events: none` — and they sit on
the text's optical centre via `vertical-align: -.16em`.

### The Proposal Editor (signature)

The proposal review surface is a to-scale preview of a printed page: the template's own letterhead
artwork painted underneath, and Word's floating text boxes positioned at their real anchors, all
contenteditable at true point sizes under a zoom transform. It has one inviolable rule. **Every
on-screen cue is `background`, `box-shadow` or `outline` — never a border, never padding, never a
width.** A cue that reflows the text by a pixel is a worse bug than the one it is reporting,
because the geometry on screen is the geometry that prints. The vocabulary: a yellow wash for a
value pulled from the estimate, an amber wash plus a warning mark for a line hand-edited away from
the computed figure, a thin red inset bar for a dirty paragraph, and a 30%-red outline on the one
text box that currently has focus.

### The Estimate Grid (signature)

A CSS-grid reproduction of Kyle's worksheet, complete with a formula bar, column letters, row
numbers and the workbook's own cell fills. Locked cells are marked with a 45° hatch overlay drawn
as an `::after` and a dimmed input — **never a background override**, because the cell's fill
arrives inline and would win. Temporarily unlocked cells take a warm amber ring. Formula
references highlight in a six-colour cycle, the way Excel's own coloured reference borders do.

### Named Rules

**The Inert-Not-Hidden Rule.** A control that cannot currently affect the outcome is dimmed to
55% and says why in words. It is not removed. Hiding it loses what the estimator already typed and
takes away their ability to see that the setting exists.

**The Read-Only Is Not Disabled Rule.** Read-only keeps full contrast and loses its affordance.
Disabled sits at 38–50% opacity. These are different states and must not look the same; conflating
them is how a value the estimator is meant to read gets mistaken for one the system has switched
off.

**The Resting State Is Not Finished Rule.** A control ships with hover, focus-visible, active,
disabled and — where it starts work — loading. A component with only a resting state is unfinished,
and every list ships with a designed empty state and a designed error state rather than a
defaulted one.

## Do's and Don'ts

### Do:

- **Do** use the app's own warm tokens — Warm Paper (`#fbf9f8`) ground, Umber Ink (`#5c403f`)
  secondary text, warm hairlines — and treat the palette and type pairing as closed.
- **Do** ration Signal Red (`#c8102e`) to the active nav row, the primary action, and the focus
  ring, and reach for the dedicated status scales for everything else.
- **Do** put `font-variant-numeric: tabular-nums` on every money and quantity figure, without
  exception.
- **Do** draw every glyph as inline SVG from `frontend/js/icons.js` at 24×24, stroke-only,
  `currentColor`, stroke-width 2, round caps.
- **Do** reuse the existing class vocabulary before inventing one — `.btn` / `.btn.ghost`, `.card`,
  `.tk` for a working panel, `.chip`, `.att-chip`, the drawer's `.sec` / `.lbl` / `.row3` / `.note`
  set — and say in review when nothing existing fits.
- **Do** validate on blur, and keep read-only (full contrast, no affordance) visually distinct from
  disabled (38–50% opacity).
- **Do** use `min-height: 100dvh` rather than `100vh` on anything full-height, and `text-wrap:
  balance` on headings.
- **Do** win on specificity rather than on source order. Twenty-one pages load their own `<style>`
  block *after* `styles.css`, so a tie in specificity is decided by which file happened to load
  last.
- **Do** design the empty state and the error state for every list before the populated one.

### Don't:

- **Don't** introduce a new palette, a new type pairing, a CSS framework, or an icon library. There
  is no Tailwind, no React and no build step here, and that is deliberate.
- **Don't** use emoji as UI. An emoji is drawn by whatever font the machine has, cannot take the
  row's colour, and ignores every size token on the page.
- **Don't** coin a near-miss of an existing token name. `--r-s` beside `--r-sm` is how this
  codebase acquired six conflicting radius names.
- **Don't** put a black ambient shadow on a resting card. Flat by default; warm lift on response;
  black only for what floats.
- **Don't** let a cool grey or a neutral-black hairline onto a Treadwell screen. That is the exact
  detail that makes a page read as somebody else's product.
- **Don't** change geometry on the proposal editor — no borders, no padding, no widths on a cue.
  Background, outline and box-shadow only.
- **Don't** harmonise the workbook fills or the printed-page styling with the app palette. They
  reproduce real documents and are quarantined on purpose.
- **Don't** rely on `hidden` alone to hide something: a class `display` rule beats the attribute,
  and this app has shipped that bug four times. Pair it with `[hidden] { display: none }` at
  sufficient specificity.
- **Don't** hide an element with `opacity: 0` and leave it hit-testable. An invisible element still
  steals the click.
- **Don't** cite `frontend/library.html` or `frontend/markup.html`'s `--red:#9e001f` as precedent.
  Those two pages are the exception awaiting correction; Signal Red is primary.
