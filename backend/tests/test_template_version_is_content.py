"""A deploy must never throw away an estimator's edits: the template version is its CONTENT.

Every document-editor override is keyed by a position in a walk over one .docx, so `_generate`
drops the whole set when the payload's `template_version` disagrees with the template's, and the
editor refuses to restore it. That version was the file's `st_mtime_ns`, and every deploy rewrites
every mtime in the image without changing a byte. Prod payloads carry about twenty different
versions for a Direct Epoxy template whose bytes last changed on 2026-07-16, each one a deploy.

What that did, on 2026-09-25: the portal re-renders a pinned revision through `_generate` on every
view, so seven open customer proposals showed the bare template instead of what Kyle sent. Viracor
rev 2 read "System: 0" and "~0 sf of polished concrete flooring" in place of his joint-filler
proposal. Reopening a proposal to revise it lost the same edits in the editor.

Everything here runs the real `_generate` and the real templates. The pre-hash stamps used below
are real values from prod payloads: 1788531288000000000 is the Viracor rev 2 pin (2026-09-04), and
1789401889000000000 is the cover-letter pin on a 2026-09-14 revision.
"""
import io
import os
import shutil

import docx
from docx import Document
from fastapi.testclient import TestClient

import cover_letter_writer as clw
import main
import proposal_writer as pw
import template_versions as tv

client = TestClient(main.app)

_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
VIRACOR_PIN = "1788531288000000000"       # polish Direct, pinned 2026-09-04
CL_PIN = "1789401889000000000"            # epoxy Direct cover letter, pinned 2026-09-14

VALUES = {
    "job_name": "Template Version QA", "project_name": "Template Version QA",
    "city_state": "Olathe, KS", "bid_date_formatted": "9/4/26", "site_visit_date": "9/4",
    "system_name": "HTS PE-85 Joint Filler", "texture": "Orange Peel",
    "epoxy_sf": "1,000", "polish_sf": "1,000", "cove_lf": "0",
    "lump_sum_formatted": "$6,307.00", "total_formatted": "$6,307.00",
    "work_description": "w", "area_description": "a", "disposal": "d",
}


def _rendered(docx_bytes):
    """Text of the paragraphs Word renders (mc:Choice), skipping the mc:Fallback duplicate."""
    d = Document(io.BytesIO(docx_bytes))
    out = []
    for p in d.element.xpath("//w:p"):
        if any(True for _ in p.iterancestors(f"{_MC}Fallback")):
            continue
        t = "".join(x.text or "" for x in p.xpath(".//w:t")).strip()
        if t:
            out.append(t)
    return "\n".join(out)


def _free_paragraph_id(path):
    """An editable paragraph outside every priced/repeatable region, with words in it."""
    d = docx.Document(str(path))
    for idx, _k, _p, in_block, text, _tb in pw.iter_editable_blocks(d):
        if in_block is None and len(text.strip()) > 12 and not text.strip()[0].isdigit():
            return idx
    raise AssertionError(f"no free editable paragraph in {path.name}")


def _generate(**extra):
    body = {"work_type": "polish", "audience": "Direct", "values": dict(VALUES)}
    body.update(extra)
    r = client.post("/api/generate", json=body)
    assert r.status_code == 200, r.text
    return _rendered(client.get(r.json()["docx_download_url"]).content)


# ── the version itself ──────────────────────────────────────────────────────────────────────────
def test_a_redeploy_of_identical_bytes_keeps_every_version(tmp_path):
    """THE bug, at its root. A copy with a new mtime is what a deploy produces."""
    for rel in tv.LEGACY_MTIME_FLOOR_S:
        src = tv.TEMPLATES_ROOT / rel
        copy = tmp_path / src.name
        shutil.copyfile(src, copy)
        st = os.stat(copy)
        os.utime(copy, ns=(st.st_atime_ns, st.st_mtime_ns + 86_400 * 10 ** 9))
        assert main._template_proposal_version(copy) == main._template_proposal_version(src), (
            f"{rel}: moving the mtime changed the version, so a deploy would drop every edit")


def test_changed_bytes_change_the_version(tmp_path):
    """The guard's whole job: a re-annotated template must look different."""
    src = pw.pick_template("epoxy", "Direct")
    copy = tmp_path / "t.docx"
    copy.write_bytes(src.read_bytes() + b"\0")
    assert main._template_proposal_version(copy) != main._template_proposal_version(src)
    assert main._template_proposal_version(src).startswith("sha256:")


def test_every_legacy_entry_still_describes_its_template():
    """If this fails, the template was edited. Delete ITS entry from
    template_versions.LEGACY_MTIME_FLOOR_S (every pre-hash stamp for it was captured against the old
    paragraphs, so none may be accepted any more). Never re-point the hash at the new content."""
    for rel, (digest, floor_s) in tv.LEGACY_MTIME_FLOOR_S.items():
        assert tv.content_version(tv.TEMPLATES_ROOT / rel) == digest, rel
        assert tv.legacy_floor_s(tv.TEMPLATES_ROOT / rel) == floor_s, rel
    picked = {pw.TEMPLATE_PICKER[k] for k in pw.TEMPLATE_PICKER} | {
        clw.TEMPLATE_PICKER[k] for k in clw.TEMPLATE_PICKER}
    assert picked <= set(tv.LEGACY_MTIME_FLOOR_S), picked - set(tv.LEGACY_MTIME_FLOOR_S)


def test_legacy_stamps_are_accepted_only_from_the_second_the_content_landed():
    path = pw.pick_template("polish", "Direct")
    floor = tv.legacy_floor_s(path)
    assert floor > 0
    assert tv.accepts(str(floor * 10 ** 9), path)
    assert not tv.accepts(str(floor * 10 ** 9 - 1), path), "a stamp from older content was accepted"
    assert tv.accepts(VIRACOR_PIN, path)
    assert tv.accepts(tv.content_version(path), path)
    for junk in ("STALE-NOPE", "0", "123", "sha256:0000000000000000", "-1788531288000000000"):
        assert not tv.accepts(junk, path), junk


def test_a_template_the_table_does_not_know_accepts_no_legacy_stamp(tmp_path):
    """A changed template, or any file outside the table, honours only its own hash."""
    copy = tmp_path / "t.docx"
    shutil.copyfile(pw.pick_template("polish", "Direct"), copy)
    assert tv.legacy_floor_s(copy) == 0
    assert not tv.accepts(VIRACOR_PIN, copy)
    assert tv.accepts(tv.content_version(copy), copy)


def test_the_editor_is_told_the_same_version_and_floor():
    j = client.get("/api/proposal-template?work_type=polish&audience=Direct").json()
    path = pw.pick_template("polish", "Direct")
    assert j["template_version"] == tv.content_version(path)
    assert j["template_version_legacy_floor_s"] == tv.legacy_floor_s(path) > 0
    cl = client.get("/api/coverletter-template?work_type=epoxy&audience=Direct").json()
    cl_path = clw.pick_template("epoxy", "Direct")
    assert cl["template_version"] == "epoxy:Direct@" + tv.content_version(cl_path)
    assert cl["template_version_legacy_floor_s"] == tv.legacy_floor_s(cl_path) > 0


# ── end to end: what the customer's PDF is built from ───────────────────────────────────────────
def test_a_revision_pinned_before_this_change_keeps_its_edits():
    """Viracor, reproduced: a polish Direct payload pinned on 2026-09-04 carries Kyle's edit.
    On the mtime guard, the first deploy after the pin dropped it from every re-render."""
    pid = _free_paragraph_id(pw.pick_template("polish", "Direct"))
    ov = [{"id": pid, "text": "KYLE-EDIT-SURVIVES-THE-DEPLOY 280 LF of removal"}]
    assert "KYLE-EDIT-SURVIVES-THE-DEPLOY" in _generate(
        paragraph_overrides=ov, template_version=VIRACOR_PIN)


def test_a_current_hash_keeps_its_edits_and_older_content_still_drops_them():
    path = pw.pick_template("polish", "Direct")
    pid = _free_paragraph_id(path)
    ov = [{"id": pid, "text": "HASH-PINNED-EDIT"}]
    assert "HASH-PINNED-EDIT" in _generate(
        paragraph_overrides=ov, template_version=tv.content_version(path))
    before = str(tv.legacy_floor_s(path) * 10 ** 9 - 10 ** 9)
    assert "HASH-PINNED-EDIT" not in _generate(paragraph_overrides=ov, template_version=before)
    assert "HASH-PINNED-EDIT" not in _generate(
        paragraph_overrides=ov, template_version="sha256:0000000000000000")


def test_a_cover_letter_pinned_before_this_change_keeps_its_edits():
    cl_path = clw.pick_template("epoxy", "Direct")
    cid = _free_paragraph_id(cl_path)
    body = {"work_type": "epoxy", "cover_letter_enabled": True,
            "cover_letter_paragraph_overrides": {str(cid): {"text": "CL-EDIT-SURVIVES-THE-DEPLOY"}}}
    assert "CL-EDIT-SURVIVES-THE-DEPLOY" in _generate(
        **body, cover_letter_template_version="epoxy:Direct@" + CL_PIN)
    # Same stamp, another variant's letter: refused, as it always was.
    assert "CL-EDIT-SURVIVES-THE-DEPLOY" not in _generate(
        **body, cover_letter_template_version="polish:Direct@" + CL_PIN)
    # A stamp from before this letter's content landed: refused.
    old = str(tv.legacy_floor_s(cl_path) * 10 ** 9 - 10 ** 9)
    assert "CL-EDIT-SURVIVES-THE-DEPLOY" not in _generate(
        **body, cover_letter_template_version="epoxy:Direct@" + old)


# ── the editor applies the same rule ────────────────────────────────────────────────────────────
import json
import pathlib
import re
import subprocess

import pytest

_FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "js"


def _lift(path, name):
    """One function out of a page script, by brace-matching (the pages cannot be required)."""
    src = path.read_text(encoding="utf-8")
    m = re.search(r"^  function " + re.escape(name) + r"\b", src, re.M)
    assert m, f"{name} not found in {path.name}"
    depth, j = 0, src.index("{", m.start())
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[m.start():k + 1]
    raise AssertionError("unterminated " + name)


def _node(script):
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_proposal_editor_restores_what_the_backend_would_apply():
    """Run the SHIPPED savedVersionMatches against the backend's own answers for the same stamps."""
    path = pw.pick_template("polish", "Direct")
    cur, floor = tv.content_version(path), tv.legacy_floor_s(path)
    stamps = [cur, "sha256:0000000000000000", VIRACOR_PIN, str(floor * 10 ** 9),
              str(floor * 10 ** 9 - 1), "", "STALE-NOPE", "0"]
    got = _node(_lift(_FRONTEND / "proposal-review.js", "savedVersionMatches") + f"""
let templateVersion = {json.dumps(cur)}; let templateLegacyFloorS = {floor};
console.log(JSON.stringify({json.dumps(stamps)}.map(savedVersionMatches)));""")
    want = [tv.accepts(s, path) if s else False for s in stamps]
    assert got == want


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_cover_letter_editor_restores_what_the_backend_would_apply():
    path = clw.pick_template("epoxy", "Direct")
    cur = "epoxy:Direct@" + tv.content_version(path)
    floor = tv.legacy_floor_s(path)
    stamps = [cur, "epoxy:Direct@" + CL_PIN, "polish:Direct@" + CL_PIN, CL_PIN,
              "epoxy:Direct@" + str(floor * 10 ** 9 - 1), "epoxy:Direct@sha256:0000000000000000", ""]
    got = _node(_lift(_FRONTEND / "coverletter-editor.js", "clVersionMatches") + f"""
let templateVersion = {json.dumps(cur)}; let templateLegacyFloorS = {floor};
console.log(JSON.stringify({json.dumps(stamps)}.map(clVersionMatches)));""")
    want = [tv.accepts_prefixed(s, "epoxy:Direct", path) for s in stamps]
    assert got == want
    assert got == [True, True, False, False, False, False, False]


# ── what must still refuse ──────────────────────────────────────────────────────────────────────
def test_a_template_whose_content_changed_refuses_every_legacy_stamp(monkeypatch):
    """The rule that keeps an old mtime from replaying onto re-annotated paragraphs: the table
    entry only counts while the file still has the recorded content. Simulated by recording a
    different hash for the real file, which is exactly what an edited template looks like."""
    path = pw.pick_template("polish", "Direct")
    rel = path.resolve().relative_to(tv.TEMPLATES_ROOT.resolve()).as_posix()
    _, floor = tv.LEGACY_MTIME_FLOOR_S[rel]
    monkeypatch.setitem(tv.LEGACY_MTIME_FLOOR_S, rel, ("sha256:0000000000000000", floor))
    assert tv.legacy_floor_s(path) == 0
    assert not tv.accepts(VIRACOR_PIN, path)
    pid = _free_paragraph_id(path)
    assert "CHANGED-CONTENT-EDIT" not in _generate(
        paragraph_overrides=[{"id": pid, "text": "CHANGED-CONTENT-EDIT"}], template_version=VIRACOR_PIN)


def test_a_stamp_of_non_ascii_digits_is_refused_not_a_500():
    """str.isdigit() accepts superscripts, which int() then refuses."""
    path = pw.pick_template("polish", "Direct")
    assert not tv.accepts("\u00b9" * 19, path)
    pid = _free_paragraph_id(path)
    assert "SUPERSCRIPT" not in _generate(
        paragraph_overrides=[{"id": pid, "text": "SUPERSCRIPT"}], template_version="\u00b9" * 19,
        cover_letter_enabled=True, cover_letter_template_version="polish:Direct@" + "\u00b9" * 19)


# The id walk's source, fingerprinted. An override id is a POSITION in this walk, so a change here
# can land every saved edit on a different paragraph even with the template bytes untouched.
_WALK_FINGERPRINT = "8b4a7b1cb4e6cb4e"


def test_the_id_walk_has_not_changed_without_a_walk_version_bump():
    """If this fails you changed how paragraphs are numbered (or bumped python-docx). Bump
    template_versions.WALK_VERSION (every saved stamp is then refused, which is the point), delete
    every LEGACY_MTIME_FLOOR_S entry, then update _WALK_FINGERPRINT here. If the change provably
    cannot renumber any paragraph, update only the fingerprint, and say why in the commit."""
    import hashlib
    import inspect
    # Every function that decides which paragraph gets which id, plus the python-docx PIN (the
    # declared dependency, not the installed one: a local venv can lag the container).
    src = "\n".join(inspect.getsource(f) for f in (
        pw.iter_editable_blocks, pw._iter_body_editable, pw._iter_txbx,
        pw._is_fallback_paragraph, pw._own_text))
    src += pw.BLOCK_START_RE.pattern + pw.BLOCK_END_RE.pattern
    reqs = (pathlib.Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
    src += "python-docx==" + re.search(r"(?m)^python-docx==(\S+)", reqs).group(1)
    assert hashlib.sha256(src.encode()).hexdigest()[:16] == _WALK_FINGERPRINT


def test_the_walk_version_is_part_of_every_version():
    path = pw.pick_template("epoxy", "Direct")
    before = tv.content_version(path)
    old = tv.WALK_VERSION
    try:
        tv.WALK_VERSION = "bumped-for-test"
        tv._HASHES.clear()
        assert tv.content_version(path) != before
        assert tv.legacy_floor_s(path) == 0, "a walk bump must refuse every legacy stamp too"
    finally:
        tv.WALK_VERSION = old
        tv._HASHES.clear()
    assert tv.content_version(path) == before


# ── the Project Info Sheet carried the same bug ─────────────────────────────────────────────────
def test_the_info_sheet_version_survives_a_redeploy(tmp_path, monkeypatch):
    """info-sheet.js throws away saved row/column edits whenever this version moves, and it was
    the file's mtime, so every deploy would have wiped them."""
    import info_sheet_writer as isw
    before = isw.template_version()
    copy = tmp_path / "project_info_sheet.xlsx"
    shutil.copyfile(isw.TEMPLATE_PATH, copy)
    st = os.stat(copy)
    os.utime(copy, ns=(st.st_atime_ns, st.st_mtime_ns + 86_400 * 10 ** 9))
    monkeypatch.setattr(isw, "TEMPLATE_PATH", copy)
    assert isw.template_version() == before


def test_a_walk_version_bump_leaves_the_info_sheet_alone(monkeypatch):
    """The Info Sheet's saved edits are workbook row/column offsets, not .docx walk positions, so
    following the walk-bump instructions above must not discard every draft's Info Sheet edits."""
    import info_sheet_writer as isw
    before = isw.template_version()
    monkeypatch.setattr(tv, "WALK_VERSION", "bumped-for-test")
    tv._HASHES.clear()
    try:
        assert isw.template_version() == before
    finally:
        tv._HASHES.clear()


def test_the_block_code_fingerprint_is_computed_from_the_builders_source():
    """Not a constant someone could forget: it must equal the hash of the three files at import."""
    import hashlib
    from pathlib import Path
    want = hashlib.sha256(b"\0".join(
        Path(m).read_bytes() for m in (main.__file__, pw.__file__, clw.__file__))).hexdigest()[:12]
    assert main._BLOCK_CODE_VERSION == want


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("page,url", [
    ("proposal-review.js", "/api/proposal-template?work_type=polish&audience=Direct"),
    ("coverletter-editor.js", "/api/coverletter-template?work_type=epoxy&audience=Direct"),
])
def test_each_editor_reads_the_floor_the_server_sends(page, url):
    """The load-time line that picks the floor up, RUN against the endpoint's real response: a
    renamed key on either side, or a deleted line, leaves the floor at 0 and every pre-hash stamp
    refused again, which is the bug itself."""
    src = (_FRONTEND / page).read_text(encoding="utf-8")
    m = re.search(r"^\s*templateLegacyFloorS = [^\n;]+;", src, re.M)
    assert m, f"{page} never reads the legacy floor from the template response"
    body = client.get(url).json()
    assert body["template_version_legacy_floor_s"] > 0
    got = _node("let templateLegacyFloorS = 0; const j = %s;\n%s\nconsole.log(JSON.stringify(templateLegacyFloorS));"
                % (json.dumps({"template_version_legacy_floor_s": body["template_version_legacy_floor_s"]}),
                   m.group(0)))
    assert got == body["template_version_legacy_floor_s"]
