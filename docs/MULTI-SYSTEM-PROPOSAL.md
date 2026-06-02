# Multi-System Proposals

How `backend/proposal_writer.py` fills ONE proposal that lists more than one
flooring system (e.g. a Combo bid offering both an Epoxy option and a Polished
Concrete option), and how Kyle annotates a template so it can repeat a section
once per system.

This is additive. Every existing single-system template keeps working with
zero changes — see "Backward compatibility" at the bottom.

---

## The two token layers

### 1. Flat tokens (v1, unchanged)
`{{token}}` is replaced from the flat `values` dict, exactly as before:

```
{{job_name}}  {{city_state}}  {{bid_date_formatted}}  {{lump_sum_formatted}}  …
```

These work anywhere in the doc — body, tables, headers/footers, and floating
text boxes. Nothing about them changed.

### 2. Per-system block (v2, new)
A **repeatable block** is the chunk of the proposal that should appear once for
each system. You wrap it between two marker paragraphs:

```
{{#system}}
System:   {{system.system_name}}
Texture:  {{system.texture}}
Area:     ~{{system.sqft}} SF
Price:    {{system.lump_sum}}
{{/system}}
```

For each system in the list, the writer clones every paragraph **between** the
markers, substitutes the `{{system.field}}` tokens for that system, and drops
the two marker paragraphs. Two systems → the block appears twice; three → three
times; one → once.

`field` is just the key in that system's dict. Anything the backend puts on a
system dict is addressable: `system.system_name`, `system.texture`,
`system.scope_notes`, `system.sqft`, `system.lump_sum`, etc.

---

## Marker rules (read this before annotating)

1. **`{{#system}}` and `{{/system}}` must each be on their own paragraph.**
   They are matched per-paragraph and the whole marker paragraph is deleted, so
   don't put real content on the same line as a marker.

2. **Both markers must be siblings in the SAME container.** A container is one
   of: the document body, a single table cell, or a single text box
   (`<w:txbxContent>`). The repeatable block cannot start in one text box and
   end in another, and it cannot straddle a text-box boundary. In practice:
   put the whole `{{#system}} … {{/system}}` block inside **one** text box (or
   one table cell, or the body).

3. **Only the FIRST block per container is expanded.** If a single text box
   needs two independent repeating regions, split them into two text boxes (or
   two table cells). The Treadwell templates only need one block apiece, so this
   isn't a real constraint today.

4. **Bare `{{field}}` inside a block:** if the key exists on the system dict it
   is filled per-system; otherwise it falls through to the normal flat pass
   against `values`. Prefer the explicit `{{system.field}}` form inside blocks
   so intent is obvious. A `{{system.field}}` whose key is missing is left
   visible (e.g. `{{system.nope}}`) so the gap is obvious in the draft — same
   philosophy as flat tokens.

---

## How Kyle annotates a template (same manual workflow as flat tokens)

You do this **once per template**, in Word — the tool never binary-edits the
`.docx` files.

1. Open the `.docx` in Word.
2. Find the section that today lists the systems by hand. In the Direct **Combo**
   template that's the two hardcoded blocks:
   - in the **scope text box**: `Option 1: Epoxy System …` / `Option 2: Polished
     Concrete …`
   - in the **pricing text box**: `$xx,xxx – Option 1 …` / `$xx,xxx – Option 2 …`
3. Replace the repeated, hand-numbered "Option 1 / Option 2" lines with **one**
   generic copy of the block, wrapped in the markers. For the scope box:

   ```
   {{#system}}
   {{system.system_name}}
   Texture: {{system.texture}}
   ~{{system.sqft}} SF, {{system.lf}} LF
   {{/system}}
   ```

   For the pricing box:

   ```
   {{#system}}
   {{system.lump_sum_formatted}} – {{system.system_name}} as described above (material sales tax INCLUDED)
   {{system.tax_amount_formatted}} – {{system.state_name}} Remodel Tax
   {{system.total_formatted}} – Total
   {{/system}}
   ```

4. Put `{{#system}}` on its own line at the top of the block and `{{/system}}`
   on its own line at the bottom. Press Enter to make sure each marker is its
   own paragraph (not a soft line break — use a real paragraph return).
5. Keep everything OUTSIDE the markers (headers, terms, schedule, exclusions)
   exactly as today; those stay single and keep using flat `{{tokens}}`.
6. Save. Done — no code change needed to add or annotate a block.

> Why text box and not a body table? The Direct templates have **no body
> tables** — every block lives in a floating text box. The writer clones the
> plain `<w:p>` paragraphs **inside** the text box; it never deep-copies the
> drawing/shape itself, so there are no drawing-ID collisions and no VML-fallback
> duplication problems. (Each text box is stored twice in the file — a DrawingML
> copy and a VML fallback copy — and the writer expands the block in both so the
> two renderings stay identical.) If you ever build a template that DOES use a
> body table, the same `{{#system}} … {{/system}}` markers work there too: put
> them in one table cell, or put `{{#system}}`/`{{/system}}` markers in their own
> paragraphs spanning the rows you want repeated within a single cell.

---

## How the backend calls it

`fill_proposal` gained one optional keyword argument:

```python
proposal_writer.fill_proposal(
    work_type="combo",
    audience="Direct",
    values=values,            # flat dict — same as v1
    systems=[                 # NEW, optional
        {
            "system_name": "Epoxy flooring",
            "texture": "Orange Peel",
            "sqft": "12,000", "lf": "450",
            "lump_sum_formatted": "$48,000",
            "tax_amount_formatted": "$0",
            "total_formatted": "$48,000",
            "state_name": "Kansas",
        },
        {
            "system_name": "Polished Concrete",
            "texture": "High Sheen, cream finish",
            "sqft": "12,000", "lf": "450",
            "lump_sum_formatted": "$31,000",
            "tax_amount_formatted": "$0",
            "total_formatted": "$31,000",
            "state_name": "Kansas",
        },
    ],
)
```

Processing order inside `fill_proposal`:

1. **Phase 1 — block expansion.** Only if `systems` is non-empty *and* the
   template actually contains a `{{#system}}` marker. Clones the block once per
   system and substitutes `{{system.field}}` tokens.
2. **Phase 2 — flat substitution.** The unchanged v1 pass. Fills every remaining
   `{{token}}` (including any flat tokens that were inside the cloned block) from
   `values`.

---

## Backward compatibility

- `systems` defaults to `None`. The existing caller in `backend/main.py`
  (which passes only `work_type`, `audience`, `values`) is unaffected.
- `systems=None` and `systems=[]` both skip Phase 1 entirely. Output is
  **byte-identical** to v1 for the current single-system templates (verified).
- A template with no `{{#system}}` marker is never modified by Phase 1, even if
  a `systems` list is passed — it just falls through to the flat pass.
- A block-annotated template called with a **single** system renders the block
  exactly once, so converting the Combo template to use a block does not break
  single-option bids.
