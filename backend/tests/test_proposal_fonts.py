"""The proposal typeface reaches the editor, and nobody who is not signed in.

Hanz, 2026-09-26: "why are the fonts and font sizes still not fixed?"

WHAT WAS WRONG: the Proposal Review editor (styles.css .tw-page, and every run the .docx carries)
names "Zetta Serif Book", and nothing ever loaded it. There was no @font-face anywhere, so on any
machine without the font installed the editor drew Georgia while the PDF (LibreOffice in the
container, fonts from backend/fonts/) printed Zetta Serif. Georgia is wider, so the editor wrapped,
shrank and clipped boxes the PDF does not.

NOW: /api/proposal-font/<name> serves the two files to a signed-in user (backend/proposal_fonts.py),
frontend/js/proposal-fonts.js fetches them with the bearer token and registers them with FontFace,
and proposal-review.js re-fits every box once, when they are in.

Zetta Serif is LICENSED. Hanz approved serving it to staff only if it stays behind the login, so
half of this file is about who does NOT get the bytes.

The loader is EXECUTED (js/proposal-fonts-harness.js runs the real file, plus the refit hook lifted
out of proposal-review.js). The families and weights it must register are read out of the font
binaries themselves below, not copied from its comments.
"""
import fnmatch
import hashlib
import json
import pathlib
import re
import shutil
import struct
import subprocess
import zipfile
from collections import Counter

import pytest
from fastapi.testclient import TestClient

import main
import proposal_fonts
import supabase_client

client = TestClient(main.app)

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "proposal-fonts-harness.js"

# The repo copy, which is what the image copies to /app/fonts.
FONT_FILES = {name: proposal_fonts.FONT_DIRS[0] / filename
              for name, filename in proposal_fonts.FONTS.items()}

# Pinned so a changed font file cannot ship under the old URL. The responses are cached for a
# year (`immutable`), so a browser holding the old bytes keeps them until the URL changes: when a
# file in backend/fonts/ changes, bump VERSION in frontend/js/proposal-fonts.js AND update these.
PINNED = {
    "zetta-serif-book": ("646d78aa67025a11814d95e7f39ca7151ee1f52e6fb9d6aaca702e852963c581", "1"),
    "zetta-serif": ("e4bcfb85ab4a059b4800a68317b4468d2df6d0abe96e79a9ad90b2a8d59971ac", "1"),
}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _otf_facts(data):
    """Family (nameID 1, Windows English), usWeightClass and the italic/oblique bits, read
    straight out of an OpenType file's `name` and `OS/2` tables. Twenty lines rather than a
    fontTools dependency the image does not otherwise need."""
    num_tables = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for i in range(num_tables):
        rec = data[12 + 16 * i: 28 + 16 * i]
        _checksum, off, length = struct.unpack(">III", rec[4:16])
        tables[rec[:4].decode("latin-1")] = (off, length)
    off = tables["name"][0]
    _fmt, count, str_off = struct.unpack(">HHH", data[off:off + 6])
    names = {}
    for i in range(count):
        pid, eid, lid, nid, ln, so = struct.unpack(
            ">HHHHHH", data[off + 6 + 12 * i: off + 18 + 12 * i])
        if pid == 3 and eid in (0, 1, 10) and lid == 0x409:
            start = off + str_off + so
            names[nid] = data[start:start + ln].decode("utf-16-be")
    os2 = tables["OS/2"][0]
    weight = struct.unpack(">H", data[os2 + 4: os2 + 6])[0]
    fs_selection = struct.unpack(">H", data[os2 + 62: os2 + 64])[0]
    return {"family": names[1], "weight": weight,
            "italic": bool(fs_selection & 0x1), "oblique": bool(fs_selection & 0x200)}


@pytest.fixture
def signed_out(monkeypatch, real_verify_token):
    """The genuine auth gate, with nobody signed in."""
    monkeypatch.setattr(supabase_client, "verify_token", real_verify_token)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setattr(supabase_client, "ALLOWED_DOMAIN", "wetreadwell.com")


# ═══ the files ═════════════════════════════════════════════════════════════════════════
def test_the_whitelist_is_the_two_files_the_pdf_prints_with():
    """Both files the Dockerfile installs for LibreOffice, and nothing else, by a public name."""
    assert set(proposal_fonts.FONTS.values()) == {
        p.name for p in (BACKEND / "fonts").iterdir() if p.suffix.lower() == ".otf"}
    for name, path in FONT_FILES.items():
        assert path.is_file(), name
        assert path.read_bytes()[:4] == b"OTTO", "%s is not an OpenType/CFF file" % path.name


def test_the_image_ships_the_fonts_where_the_app_reads_them():
    """In the container the app runs from /app, and `COPY backend/ /app/` puts backend/fonts/ at
    /app/fonts -- which is FONT_DIRS[0] there, because it is resolved next to proposal_fonts.py.
    Nothing in .dockerignore may drop them on the way (checked with fnmatch, whose `*` also
    crosses `/`, so it over-matches rather than under-matches)."""
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"(?m)^WORKDIR /app\s*$", dockerfile)
    assert re.search(r"(?m)^COPY backend/ /app/\s*$", dockerfile)
    assert proposal_fonts.FONT_DIRS[0] == pathlib.Path(proposal_fonts.__file__).resolve().parent / "fonts"
    # The LibreOffice copy is the fallback directory, so the two must name the same place.
    m = re.search(r"(?m)^COPY backend/fonts/ (\S+)\s*$", dockerfile)
    assert m, "the Dockerfile no longer installs backend/fonts/ for LibreOffice"
    assert m.group(1).rstrip("/") == proposal_fonts.FONT_DIRS[1].as_posix()
    patterns = [ln.strip() for ln in (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
    for target in ["backend/fonts"] + ["backend/fonts/" + f for f in proposal_fonts.FONTS.values()]:
        for pat in patterns:
            bare = pat[3:] if pat.startswith("**/") else pat
            hit = fnmatch.fnmatch(target, pat) or fnmatch.fnmatch(target, bare) \
                or fnmatch.fnmatch(target.rsplit("/", 1)[-1], bare)
            assert not hit, ".dockerignore %r drops %s from the image" % (pat, target)


def test_a_changed_font_file_cannot_ship_under_the_old_url(ran):
    """The URL carries VERSION; the bytes are cached a year under it."""
    for name, path in FONT_FILES.items():
        sha, version = PINNED[name]
        assert _sha(path.read_bytes()) == sha and ran["ok"]["version"] == version, (
            "backend/fonts/%s changed: bump VERSION in frontend/js/proposal-fonts.js and update "
            "PINNED here, or every browser keeps the old bytes for a year" % path.name)


# ═══ the endpoint, signed in ═══════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", sorted(proposal_fonts.FONTS))
def test_a_signed_in_request_gets_the_real_bytes(name):
    r = client.get("/api/proposal-font/" + name)
    assert r.status_code == 200
    assert r.content == FONT_FILES[name].read_bytes()
    assert r.headers["content-type"].split(";")[0] == "font/otf"
    assert r.headers["x-content-type-options"] == "nosniff"
    cc = [d.strip() for d in r.headers["cache-control"].split(",")]
    assert "private" in cc and "public" not in cc, (
        "a licensed font a shared cache could hand to somebody who is not signed in")
    max_age = next(int(d.split("=", 1)[1]) for d in cc if d.startswith("max-age="))
    assert max_age >= 30 * 86400, "the editor would re-download 190 KB on every open"


@pytest.mark.parametrize("name", sorted(proposal_fonts.FONTS))
def test_a_revalidation_sends_no_body(name):
    etag = client.get("/api/proposal-font/" + name).headers["etag"]
    r = client.get("/api/proposal-font/" + name, headers={"If-None-Match": etag})
    assert r.status_code == 304 and not r.content


# ═══ the endpoint, signed out ══════════════════════════════════════════════════════════
@pytest.mark.parametrize("auth", [None, "Bearer not-a-real-token", "Basic dXNlcjpwYXNz"])
@pytest.mark.parametrize("name", sorted(proposal_fonts.FONTS))
def test_nobody_signed_out_gets_the_font(signed_out, name, auth):
    headers = {"Authorization": auth} if auth else {}
    r = client.get("/api/proposal-font/" + name, headers=headers)
    assert r.status_code == 401
    assert b"OTTO" not in r.content


@pytest.mark.parametrize("url", [
    "/fonts/Zetta%20Serif.otf", "/fonts/Zetta%20Serif-Book.otf",
    "/backend/fonts/Zetta%20Serif.otf", "/Zetta%20Serif.otf", "/Zetta%20Serif-Book.otf",
    "/js/../fonts/Zetta%20Serif.otf", "/..%2Ffonts%2FZetta%20Serif.otf",
    "/api/proposal-font/zetta-serif", "/api/proposal-font/zetta-serif-book",
    "/api/proposal-font/zetta-serif?v=1", "/api/proposal-template/media?name=Zetta%20Serif.otf",
])
def test_no_url_of_the_app_returns_the_font_bytes_signed_out(signed_out, url):
    """This app's own URLs only. The same bytes are public on GitHub and in the GHCR images,
    which no test here can reach: see the end of the proposal_fonts.py docstring."""
    r = client.get(url)
    fonts = {p.read_bytes() for p in FONT_FILES.values()}
    assert r.content not in fonts and not r.content.startswith(b"OTTO"), url


def test_no_copy_of_the_font_sits_in_the_public_static_tree():
    """The static mount serves frontend/ to anyone. A copy of the font there would be a public
    URL no route test can see."""
    fonts = {p.stat().st_size: _sha(p.read_bytes()) for p in FONT_FILES.values()}
    for p in FRONTEND.rglob("*"):
        if p.is_file() and p.stat().st_size in fonts:
            assert _sha(p.read_bytes()) != fonts[p.stat().st_size], p


# ═══ the whitelist ═════════════════════════════════════════════════════════════════════
EVIL = ["Zetta Serif.otf", "Zetta Serif-Book.otf", "zetta-serif.otf", "ZETTA-SERIF", "zetta-serif ",
        " zetta-serif", "Zetta%20Serif.otf", "..%2Fmain.py", "main.py", "fonts", "..", ".",
        "__init__", "keys", "get", "zetta-serif-bookx", "zetta"]


@pytest.mark.parametrize("name", EVIL)
def test_any_other_name_is_refused(name):
    r = client.get("/api/proposal-font/" + name)
    assert r.status_code != 200 and b"OTTO" not in r.content, name


def test_no_request_name_reaches_the_filesystem(monkeypatch):
    """The name is a dictionary key. Anything that is not one is refused before a path exists,
    and a whitelisted name reads exactly its own file."""
    reads = []
    real = pathlib.Path.read_bytes
    monkeypatch.setattr(pathlib.Path, "read_bytes", lambda self: reads.append(self) or real(self))
    proposal_fonts.cache_clear()
    try:
        for name in EVIL + [None, 1, ("zetta-serif",), b"zetta-serif", "../fonts/Zetta Serif.otf"]:
            assert proposal_fonts.load(name) is None, name
        assert reads == []
        data, _etag = proposal_fonts.load("zetta-serif")
        assert data == real(FONT_FILES["zetta-serif"])
        assert [p.name for p in reads] == ["Zetta Serif.otf"]
    finally:
        proposal_fonts.cache_clear()


# ═══ the loader, executed ══════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    files = {name: str(path) for name, path in FONT_FILES.items()}
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND), json.dumps(files)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed; read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_each_face_is_registered_from_its_bytes_as_what_the_file_really_is(ran):
    """Family and weight from the file's own tables, upright, from an ArrayBuffer (a url() load
    could not carry the bearer token, and a blob: URL is refused by nginx's `font-src 'self'`).

    The weight is the file's usWeightClass, not 700 for anything: neither file has a bold face, so
    the PDF's bold lead-ins are synthesised by LibreOffice and must be synthesised by the browser
    too, which it only does for a face registered as the regular weight it is."""
    by_sha = {_sha(p.read_bytes()): p for p in FONT_FILES.values()}
    faces = ran["ok"]["faces"]
    assert len(faces) == len(proposal_fonts.FONTS)
    for face in faces:
        assert face["arrayBuffer"] is True, face
        path = by_sha[face["sha"]]
        facts = _otf_facts(path.read_bytes())
        assert face["family"] == facts["family"], (path.name, face)
        assert face["descriptors"].get("weight") == str(facts["weight"]), (path.name, face)
        assert not facts["italic"] and not facts["oblique"]
        assert face["descriptors"].get("style") == "normal", (path.name, face)
    assert sorted(a["family"] for a in ran["ok"]["added"]) == sorted(f["family"] for f in faces)
    assert all(a["status"] == "loaded" for a in ran["ok"]["added"]), (
        "a face went into document.fonts before it had loaded")


def test_the_fonts_are_fetched_same_origin_with_the_staff_token(ran):
    fetches = ran["ok"]["fetches"]
    assert sorted(f["name"] for f in fetches) == sorted(proposal_fonts.FONTS)
    for f in fetches:
        assert f["url"].startswith("/api/proposal-font/"), f
        assert f["auth"] == "Bearer tok-123", f
        assert f["credentials"] == "same-origin", f


def test_nothing_is_fetched_before_the_token_exists(ran):
    """The /api/default-notes 401 race (#124): a fetch that fires before the token 401s."""
    assert ran["gated"] == {"before": 0, "after": 2, "fit": 1}


def test_the_page_refits_every_box_once_through_the_caret_safe_pager(ran):
    """Once: after both faces are in, not per face. Through scheduleRepaginate, never
    repaginateTerms directly -- the scheduler is what waits out a caret in the terms. A registrant
    that arrives late still runs, once, off the load already done."""
    ok = ran["ok"]
    assert ok["ok"] is True
    assert ok["repaginate"] == [0] and ok["fit"] == 1 and ok["directRepaginate"] == 0
    assert ok["late"] == 1 and ok["fitAfterLate"] == 1, "the late registrant re-ran the page's refit"
    assert ok["fetchesAfterLate"] == 2 and ok["startAgain"] is True, "the font was fetched twice"
    assert ok["warns"] == [] and ok["errors"] == []


@pytest.mark.parametrize("case", ["unauthorized", "offline", "badBytes", "noFontFace", "noToken"])
def test_a_failed_load_keeps_the_fallback_and_says_so_once(ran, case):
    got = ran[case]
    assert got["ok"] is False
    assert got["added"] == [] and got["fit"] == 0 and got["repaginate"] == []
    assert len(got["warns"]) == 1 and "fallback" in got["warns"][0], got["warns"]
    assert got["errors"] == []


def test_one_face_is_enough_to_refit(ran):
    got = ran["partial"]
    assert [a["family"] for a in got["added"]] == ["Zetta Serif"]
    assert got["fit"] == 1 and got["repaginate"] == [0]
    assert len(got["warns"]) == 1 and "Zetta Serif Book" in got["warns"][0]


def test_no_rejection_escapes_the_loader(ran):
    assert ran["unhandled"] == []


# ═══ the page ══════════════════════════════════════════════════════════════════════════
def _script_srcs(page):
    html = (FRONTEND / page).read_text(encoding="utf-8")
    return [m.group(1).split("?", 1)[0] for m in re.finditer(r'<script\b[^>]*\bsrc="([^"]+)"', html)]


def test_the_loader_is_on_the_pages_that_draw_the_proposal_and_before_their_script():
    """Proposal Review is the page that draws the .docx (its cover letter shares the canvas). The
    loader has to run first: the page's own script hands it the refit as it runs."""
    pages = sorted(p.name for p in FRONTEND.glob("*.html")
                   if "/js/proposal-fonts.js" in _script_srcs(p.name))
    drawing = sorted(p.name for p in FRONTEND.glob("*.html")
                     if "/js/proposal-review.js" in _script_srcs(p.name))
    assert pages == drawing == ["proposal-review.html"]
    srcs = _script_srcs("proposal-review.html")
    assert srcs.index("/js/proposal-fonts.js") < srcs.index("/js/proposal-review.js")
    assert srcs.index("/shared.js") < srcs.index("/js/proposal-fonts.js")


def test_the_loader_registers_the_family_the_page_and_the_document_ask_for(ran):
    """The CSS asks for "Zetta Serif Book" then "Zetta Serif", and the templates' runs are set in
    "Zetta Serif Book". A family registered under any other name loads and is never used."""
    families = {f["family"] for f in ran["ok"]["faces"]}
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    rule = re.search(r"(?m)^\.tw-page\s*\{([^}]*)\}", css).group(1)
    chain = [f.strip().strip('"\'') for f in
             re.search(r"font-family:\s*([^;]+);", rule).group(1).split(",")]
    assert set(chain[:2]) == families, chain
    for sub in ("Direct", "GC", "Gyp"):
        for docx in (BACKEND / "templates" / sub).glob("*.docx"):
            xml = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8", "ignore")
            used = Counter(re.findall(r'w:rFonts [^>]*w:ascii="([^"]+)"', xml))
            assert used and used.most_common(1)[0][0] in families, (docx.name, used.most_common(3))
