"""Deposit invoice — fills Kyle's real `Invoice_Deposit.docx`.

The template is built like the proposal templates: the page design is artwork
(EMF images) and every piece of text lives in a floating text box
(`w:txbxContent`), not in body paragraphs or tables. Two consequences drive this
module:

  1. **Every string exists TWICE.** Word wraps each shape in
     `mc:AlternateContent`: a modern `mc:Choice` copy and a legacy VML
     `mc:Fallback` copy. Fill only one and LibreOffice may render the other, so
     the document must be rewritten everywhere the placeholder appears — never
     stop at the first match.
  2. **Values are split across runs.** Word breaks "23.150-01" into runs "23"
     and ".150-01" (spell-check/formatting artifacts), so matching has to happen
     on the paragraph's concatenated text, not run by run.

Placeholders are matched on the paragraph's full text, which keeps them
unambiguous ("23.150" the job number vs "23.150-01" the invoice number vs the
"2023" inside the date).
"""
from __future__ import annotations

import copy
import io
import re
from datetime import date, datetime
from typing import Any, Optional

from docx import Document
from docx.oxml.ns import qn

TEMPLATE_NAME = "Invoice_Deposit.docx"

# Exact placeholder text in the shipped template → the field that replaces it.
# Keyed on the paragraph's concatenated text (see module docstring).
_PLACEHOLDERS: dict[str, str] = {
    "Customer Name":                            "customer_name",
    "Customer Address":                         "customer_address",
    "City State":                               "city_state",
    "Deposit (25% of $xxxxx contract value)":   "deposit_line",
    "$650.00":                                  "deposit_amount",
    "$xxxx":                                    "total_due",
    "xxxxxx":                                   "job_name",   # the JOB NAME slot
    "23.150-01":                                "invoice_no",
    "12/6/2023":                                "invoice_date",
    "23.150":                                   "job_number",
}


def _money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return ""


def _fmt_date(d) -> str:
    """M/D/YYYY, matching the template's own 12/6/2023 style."""
    if isinstance(d, datetime):
        d = d.date()
    elif isinstance(d, str):
        try:
            d = datetime.fromisoformat(d.replace("Z", "+00:00")).date()
        except ValueError:
            d = None
    if not isinstance(d, date):
        d = date.today()
    return f"{d.month}/{d.day}/{d.year}"


def invoice_fields(src: dict[str, Any]) -> dict[str, str]:
    """Every string that lands on the invoice. Pure — no I/O, no DB.

    `src` carries whatever the caller knows (project, customer, amounts) plus any
    staff EDITS made on the review screen; edits win, because the whole point of
    the review step is that a human can correct the document before it goes out.
    """
    deposit = src.get("deposit_amount")
    contract = src.get("contract_value")
    pct = src.get("deposit_pct") or 25

    def pick(key: str, fallback: str = "") -> str:
        v = src.get(key)
        return fallback if v is None or str(v).strip() == "" else str(v).strip()

    deposit_line = pick(
        "deposit_line",
        f"Deposit ({pct:g}% of {_money(contract)} contract value)" if contract not in (None, "")
        else f"Deposit ({pct:g}% of contract value)",
    )
    return {
        "customer_name":    pick("customer_name", "Customer Name"),
        "customer_address": pick("customer_address"),
        "city_state":       pick("city_state"),
        "deposit_line":     deposit_line,
        "deposit_amount":   pick("deposit_amount_text", _money(deposit)),
        "total_due":        pick("total_due_text", _money(src.get("total_due", deposit))),
        "job_name":         pick("job_name"),
        "invoice_no":       pick("invoice_no"),
        "invoice_date":     pick("invoice_date_text", _fmt_date(src.get("invoice_date"))),
        "job_number":       pick("job_number"),
    }


# ─── docx plumbing ────────────────────────────────────────────────────
def _p_text(p_elem) -> str:
    """Concatenated text of a <w:p>, ignoring run boundaries."""
    return "".join(t.text or "" for t in p_elem.iter(qn("w:t")))


def _set_p_text(p_elem, text: str) -> None:
    """Write `text` into a paragraph, keeping the FIRST run's formatting and
    emptying the rest. Word splits a value across runs; collapsing into run one
    preserves the template's font/size/colour while replacing the whole value."""
    ts = list(p_elem.iter(qn("w:t")))
    if not ts:
        return
    ts[0].text = text
    ts[0].set(qn("xml:space"), "preserve")
    for t in ts[1:]:
        t.text = ""
        t.set(qn("xml:space"), "preserve")


def _fill(doc: Document, values: dict[str, str]) -> int:
    """Replace every placeholder paragraph, in BOTH the mc:Choice and the VML
    mc:Fallback copy of each shape. Returns how many paragraphs were rewritten
    (0 means the template changed shape and the caller should shout)."""
    hits = 0
    root = doc.element.body
    for txbx in root.iter(qn("w:txbxContent")):
        for p_elem in txbx.iter(qn("w:p")):
            key = _p_text(p_elem).strip()
            field = _PLACEHOLDERS.get(key)
            if field is None:
                continue
            val = values.get(field, "")
            _set_p_text(p_elem, val)
            hits += 1
    return hits


def build_invoice_docx(src: dict[str, Any], template_path) -> bytes:
    """Fill the template and return .docx bytes. The template on disk is never
    modified — python-docx loads it and we save to a buffer."""
    doc = Document(str(template_path))
    hits = _fill(doc, invoice_fields(src))
    if not hits:
        raise RuntimeError(
            f"{TEMPLATE_NAME}: no placeholders matched — the template's text "
            "changed. Update _PLACEHOLDERS to match the new wording."
        )
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_invoice_pdf(src: dict[str, Any], template_path) -> bytes:
    """Fill the template and render it to PDF via LibreOffice (same path the
    proposal export uses)."""
    import pdf_writer

    return pdf_writer.docx_to_pdf(build_invoice_docx(src, template_path))
