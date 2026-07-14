"""One-off: add the "Add for additional phase" row ($4,500 default) to the
estimate template — Epoxy B91/C91 and Polish B85/C85.

Done as raw-zip surgery on ONLY the two worksheet XML parts (every other part
copied byte-identical). We must NOT round-trip the workbook through openpyxl:
`estimate_writer._parse_x14_data_validations` reads the x14 <extLst> dropdown
validations straight from the template zip, and an openpyxl save would strip
them ("Data Validation extension is not supported and will be removed") —
killing most of Kyle's grid dropdowns. The target cells already exist empty and
pre-styled in the template, so we only inject content into the existing <c>
elements (reusing their style ids).

Idempotent: re-running is a no-op (the pre-edit empty cells are gone). Run once
from the backend/ dir: `python add_phase_row.py`.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

TEMPLATE = Path(__file__).parent / "templates" / "estimate_sheet_5.7.xlsx"
LABEL = "Add for additional phase"
DEFAULT = "4500"

# (part, empty-cell literal, replacement) — exact string swaps, each must hit once.
EDITS = [
    # Epoxy (sheet1): B91 label (style 835), C91 value (style 836)
    ("xl/worksheets/sheet1.xml",
     '<c r="B91" s="835"/>',
     f'<c r="B91" s="835" t="inlineStr"><is><t xml:space="preserve">{LABEL}</t></is></c>'),
    ("xl/worksheets/sheet1.xml",
     '<c r="C91" s="836"/>',
     f'<c r="C91" s="836"><v>{DEFAULT}</v></c>'),
    # Polish (sheet2): B85 label (style 600), C85 value (style 836)
    ("xl/worksheets/sheet2.xml",
     '<c r="B85" s="600"/>',
     f'<c r="B85" s="600" t="inlineStr"><is><t xml:space="preserve">{LABEL}</t></is></c>'),
    ("xl/worksheets/sheet2.xml",
     '<c r="C85" s="836"/>',
     f'<c r="C85" s="836"><v>{DEFAULT}</v></c>'),
]


def main() -> int:
    if not TEMPLATE.exists():
        print(f"!! template not found: {TEMPLATE}")
        return 1

    with zipfile.ZipFile(TEMPLATE, "r") as zin:
        names = zin.namelist()
        parts = {n: zin.read(n) for n in names}
        infos = {n: zin.getinfo(n) for n in names}

    edited_parts: dict[str, str] = {}
    for part, find, repl in EDITS:
        if part not in parts:
            print(f"!! missing part: {part}")
            return 1
        xml = edited_parts.get(part) or parts[part].decode("utf-8")
        n = xml.count(find)
        if n != 1:
            print(f"!! expected exactly 1 of {find!r} in {part}, found {n} — ABORT (already run? template changed?)")
            return 1
        edited_parts[part] = xml.replace(find, repl)

    tmp = TEMPLATE.with_suffix(TEMPLATE.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            data = edited_parts[n].encode("utf-8") if n in edited_parts else parts[n]
            # preserve the original compression type per entry
            info = infos[n]
            zi = zipfile.ZipInfo(n, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)

    shutil.move(str(tmp), str(TEMPLATE))
    print(f"OK — injected phase row into {TEMPLATE.name} "
          f"(Epoxy B91/C91, Polish B85/C85; {len(EDITS)} cell edits).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
