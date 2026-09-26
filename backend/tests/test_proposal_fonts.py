"""The proposal typeface reaches the editor and the PDF, and nobody who is not signed in -- and
since 2026-09-26 it lives on the SERVER, not in git and not in the image.

Hanz, 2026-09-26: "why are the fonts and font sizes still not fixed?"

WHAT WAS WRONG: the Proposal Review editor (styles.css .tw-page, and every run the .docx carries)
names "Zetta Serif Book", and nothing ever loaded it. There was no @font-face anywhere, so on any
machine without the font installed the editor drew Georgia while the PDF (LibreOffice in the
container) printed Zetta Serif. Georgia is wider, so the editor wrapped, shrank and clipped boxes
the PDF does not.

NOW: /api/proposal-font/<name> serves the two files to a signed-in user (backend/proposal_fonts.py),
frontend/js/proposal-fonts.js fetches them with the bearer token and registers them with FontFace,
and proposal-review.js re-fits every box once, when they are in.

Zetta Serif is LICENSED. Hanz approved serving it to staff only if it stays behind the login, and
then decided "Move font off GitHub": the repo is public, and it had carried the files since 67942d0.
So the files are in neither git nor any image any more; the host mounts them at runtime. Most of
this file is about who does NOT get the bytes and where they must NOT be.

NONE OF THE SECURITY COVERAGE NEEDS THE LICENSED BYTES. CI never has them, and a test that skips
there protects nothing. The route, whitelist, auth, cache-header and no-public-URL tests read
SYNTHETIC fonts (built below: a real OpenType header with `name` and `OS/2` tables, and no glyph
anyone licensed). Only the checks that are ABOUT the real files -- their name tables and their
pinned hashes -- need them, and those skip with a reason when the files are not on the machine.

The loader is EXECUTED (js/proposal-fonts-harness.js runs the real file, plus the refit hook lifted
out of proposal-review.js). The families and weights it must register are pinned in EXPECTED, and
EXPECTED is checked against the real binaries' own tables wherever the real binaries exist.
"""
import hashlib
import json
import logging
import pathlib
import posixpath
import re
import shutil
import struct
import subprocess
import zipfile
from collections import Counter

import pytest
import yaml
from fastapi.testclient import TestClient

import main
import proposal_fonts
import supabase_client

client = TestClient(main.app)

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "proposal-fonts-harness.js"
MOUNT = "%s:%s:ro" % (proposal_fonts.HOST_DIR, proposal_fonts.MOUNT_DIR.as_posix())

# What each file must be, and so what the loader must register it as. Pinned here, not read out of
# the loader (which would make the loader check itself) and not read out of the binaries (which CI
# does not have). test_the_real_files_are_what_the_loader_registers ties it to the binaries.
EXPECTED = {
    "zetta-serif-book": ("Zetta Serif Book", 345),
    "zetta-serif": ("Zetta Serif", 400),
}

# Pinned so a changed font file cannot ship under the old URL. The responses are cached for a
# year (`immutable`), so a browser holding the old bytes keeps them until the URL changes: when a
# font file on the server changes, bump VERSION in frontend/js/proposal-fonts.js AND update these.
PINNED = {
    "zetta-serif-book": ("646d78aa67025a11814d95e7f39ca7151ee1f52e6fb9d6aaca702e852963c581", "1"),
    "zetta-serif": ("e4bcfb85ab4a059b4800a68317b4468d2df6d0abe96e79a9ad90b2a8d59971ac", "1"),
}

# First four bytes of every font container a browser or fontconfig would load.
FONT_MAGIC = (b"OTTO", b"\x00\x01\x00\x00", b"true", b"typ1", b"ttcf", b"wOFF", b"wOF2")
FONT_SUFFIXES = (".otf", ".otc", ".ttf", ".ttc", ".woff", ".woff2", ".eot", ".pfb", ".pfa")


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


def _synthetic_otf(family, weight, salt):
    """A tiny file with a genuine OpenType/CFF header and real `name` and `OS/2` tables, and no
    outline anyone licensed: what the route serves and the loader registers in these tests."""
    fam = family.encode("utf-16-be")
    name = struct.pack(">HHH", 0, 1, 6 + 12) + struct.pack(">6H", 3, 1, 0x409, 1, len(fam), 0) + fam
    os2 = bytearray(78)                                   # OS/2 version 0
    struct.pack_into(">H", os2, 4, weight)                # usWeightClass
    struct.pack_into(">H", os2, 62, 0x40)                 # fsSelection: REGULAR, upright
    tables = [(b"CFF ", b"\x01\x00\x04\x01" + salt), (b"OS/2", bytes(os2)), (b"name", name)]
    head = b"OTTO" + struct.pack(">4H", len(tables), 32, 1, 16 * len(tables) - 32)
    directory, body, offset = b"", b"", 12 + 16 * len(tables)
    for tag, data in tables:
        directory += tag + struct.pack(">III", 0, offset + len(body), len(data))
        body += data + b"\0" * (-len(data) % 4)
    return head + directory + body


def _real_files():
    """The licensed files wherever the server would read them (the mount, else backend/fonts/).
    Resolved at collection, before any test patches FONT_DIRS."""
    found = {}
    for name, filename in proposal_fonts.FONTS.items():
        for folder in proposal_fonts.FONT_DIRS:
            if (folder / filename).is_file():
                found[name] = folder / filename
                break
    return found


REAL = _real_files()
needs_real = pytest.mark.skipif(
    len(REAL) < len(proposal_fonts.FONTS),
    reason="the licensed Zetta Serif files are not on this machine: CI never has them, the VPS "
           "mounts them from /opt/treadwell-fonts, a dev box keeps them in backend/fonts/")


@pytest.fixture(scope="module")
def synthetic_dir(tmp_path_factory):
    folder = tmp_path_factory.mktemp("synthetic-fonts")
    for name, filename in proposal_fonts.FONTS.items():
        family, weight = EXPECTED[name]
        (folder / filename).write_bytes(_synthetic_otf(family, weight, name.encode("ascii")))
    return folder


@pytest.fixture
def fonts(monkeypatch, synthetic_dir):
    """The app reads the synthetic files, and only them, whatever this machine has installed.
    Returns {public name: the bytes the route must serve}."""
    monkeypatch.setattr(proposal_fonts, "FONT_DIRS", (synthetic_dir,))
    proposal_fonts.cache_clear()
    yield {name: (synthetic_dir / filename).read_bytes()
           for name, filename in proposal_fonts.FONTS.items()}
    proposal_fonts.cache_clear()


@pytest.fixture
def no_fonts(monkeypatch, tmp_path):
    """A box without the files: an empty mount (what Docker makes of a missing host dir) and an
    empty dev directory."""
    mount, dev = tmp_path / "mount", tmp_path / "dev"
    mount.mkdir()
    dev.mkdir()
    monkeypatch.setattr(proposal_fonts, "FONT_DIRS", (mount, dev))
    monkeypatch.setattr(proposal_fonts, "_reported", False)
    proposal_fonts.cache_clear()
    yield mount, dev
    proposal_fonts.cache_clear()


@pytest.fixture
def signed_out(monkeypatch, real_verify_token):
    """The genuine auth gate, with nobody signed in."""
    monkeypatch.setattr(supabase_client, "verify_token", real_verify_token)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setattr(supabase_client, "ALLOWED_DOMAIN", "wetreadwell.com")


# ═══ the files ═════════════════════════════════════════════════════════════════════════
def test_the_whitelist_is_the_two_files_the_readme_tells_the_server_to_hold():
    """The names are the contract with whoever copies the files onto the box: the README says
    these two names, the deploy checks these two names, and the route serves these two names."""
    assert proposal_fonts.FONTS == {"zetta-serif-book": "Zetta Serif-Book.otf",
                                    "zetta-serif": "Zetta Serif.otf"}
    readme = (BACKEND / "fonts" / "README.md").read_text(encoding="utf-8")
    for filename in proposal_fonts.FONTS.values():
        assert "`%s`" % filename in readme, filename
    assert proposal_fonts.HOST_DIR in readme


# Treadwell's own kit in the team Dropbox. On 2026-09-26 both files there hashed to PINNED.
DROPBOX_KIT = "/2023 Treadwell Team Folder/Office/Technology/Fonts/Zetta_ForText/"


def test_the_readme_names_the_lasting_copy_and_the_hash_to_check_one_against():
    """Review, 2026-09-26: once git stops tracking the files, every checkout loses them at its next
    pull or checkout, and `git worktree remove` takes an ignored copy with it. "Ask Hanz" was the
    README's only pointer to a copy that survives. It must name the Dropbox folder that holds the
    kit, and give each file's hash in that file's own row: the hashes pinned in this module."""
    readme = (BACKEND / "fonts" / "README.md").read_text(encoding="utf-8")
    assert DROPBOX_KIT in readme
    for name, filename in proposal_fonts.FONTS.items():
        row = next(ln for ln in readme.splitlines() if ln.startswith("| `%s`" % filename))
        assert "`%s`" % PINNED[name][0] in row, (filename, row)


def test_the_synthetic_fonts_carry_what_the_tests_read(synthetic_dir):
    """Without this the synthetic files could be anything and every test below would still pass."""
    for name, filename in proposal_fonts.FONTS.items():
        data = (synthetic_dir / filename).read_bytes()
        assert data[:4] == b"OTTO"
        facts = _otf_facts(data)
        assert (facts["family"], facts["weight"]) == EXPECTED[name]
        assert not facts["italic"] and not facts["oblique"]
        assert _sha(data) != PINNED[name][0], "a synthetic file must never be the licensed one"


@needs_real
def test_the_real_files_are_what_the_loader_registers():
    """The two ends of the chain: the loader registers EXPECTED (checked against synthetic
    files in CI), and here EXPECTED is checked against the licensed binaries' own tables.

    The weight is the file's usWeightClass, not 700 for anything: neither file has a bold face, so
    the PDF's bold lead-ins are synthesised by LibreOffice and must be synthesised by the browser
    too, which it only does for a face registered as the regular weight it is."""
    for name, path in REAL.items():
        data = path.read_bytes()
        assert data[:4] == b"OTTO", "%s is not an OpenType/CFF file" % path.name
        facts = _otf_facts(data)
        assert (facts["family"], facts["weight"]) == EXPECTED[name], (path, facts)
        assert not facts["italic"] and not facts["oblique"], path


@needs_real
def test_a_changed_font_file_cannot_ship_under_the_old_url(ran):
    """The URL carries VERSION; the bytes are cached a year under it."""
    for name, path in REAL.items():
        sha, version = PINNED[name]
        assert _sha(path.read_bytes()) == sha and ran["ok"]["version"] == version, (
            "%s changed: bump VERSION in frontend/js/proposal-fonts.js and update PINNED here, or "
            "every browser keeps the old bytes for a year" % path)


@needs_real
@pytest.mark.parametrize("name", sorted(proposal_fonts.FONTS))
def test_the_route_serves_the_files_this_machine_has_installed(name):
    """Unpatched: the real directories, the real files."""
    proposal_fonts.cache_clear()
    try:
        r = client.get("/api/proposal-font/" + name)
        assert r.status_code == 200 and r.content == REAL[name].read_bytes()
    finally:
        proposal_fonts.cache_clear()


# ═══ off GitHub, out of the image, from the host ═══════════════════════════════════════
def _git_ls_files():
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    proc = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True)
    if proc.returncode != 0:
        pytest.skip("not a git checkout: " + proc.stderr.decode("utf-8", "replace"))
    return [p for p in proc.stdout.decode("utf-8").split("\0") if p]


def test_git_tracks_no_font_file():
    """Hanz, 2026-09-26: "Move font off GitHub." The repo is PUBLIC, so a font in the index is a
    font on raw.githubusercontent.com. By name AND by content, so a renamed copy is caught too."""
    tracked = _git_ls_files()
    assert "backend/proposal_fonts.py" in tracked, "the listing is not this repository"
    named = [p for p in tracked if p.lower().endswith(FONT_SUFFIXES)]
    assert named == [], named
    sniffed = []
    for rel in tracked:
        path = REPO / rel
        if path.is_file():
            with open(path, "rb") as fh:
                if fh.read(4) in FONT_MAGIC:
                    sniffed.append(rel)
    assert sniffed == [], "font files tracked under other names: %s" % sniffed


def _dockerignore_rules():
    """.dockerignore as Docker's own matcher (moby/patternmatcher) reads it: `#` lines skipped,
    a leading `!` inverts, the pattern is cleaned and a leading `/` dropped, `**` spans any number
    of directories (even none), `*` and `?` never cross a `/`, and the LAST matching rule wins."""
    rules = []
    for raw in (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        pat = posixpath.normpath(line[1:].strip() if negate else line).lstrip("/")
        rx, i = "", 0
        while i < len(pat):
            c = pat[i]
            if pat.startswith("**", i):
                i += 2
                if pat.startswith("/", i):
                    i += 1
                rx += ".*" if i >= len(pat) else "(.*/)?"
                continue
            rx += {"*": "[^/]*", "?": "[^/]"}.get(c, re.escape(c))
            i += 1
        rules.append((negate, re.compile("^" + rx + "$")))
    return rules


def _docker_excludes(rel, rules):
    """Docker's MatchesOrParentMatches: a rule matching the path OR any parent directory."""
    parts = rel.split("/")
    candidates = [rel] + ["/".join(parts[:i]) for i in range(1, len(parts))]
    excluded = False
    for negate, rx in rules:
        if any(rx.match(c) for c in candidates):
            excluded = not negate
    return excluded


def test_no_font_reaches_the_image_even_from_a_working_tree_that_has_one():
    """git no longer tracks the files, but deploy/ship.sh builds from the local working tree,
    where backend/fonts/ still holds them for local dev. .dockerignore is what keeps them out of
    `COPY backend/ /app/`. Checked against Docker's matching rules, with controls that must stay
    IN, so a rule that excluded everything could not pass this."""
    rules = _dockerignore_rules()
    out = ["backend/fonts/" + f for f in proposal_fonts.FONTS.values()] + [
        "Zetta Serif.otf", "frontend/fonts/zetta.woff2", "frontend/zetta.woff",
        "backend/templates/Direct/stray.ttf", "backend/fonts/other.ttc"]
    kept = ["backend/main.py", "backend/proposal_fonts.py", "backend/fonts/README.md",
            "frontend/js/proposal-fonts.js", "frontend/styles.css", "backend/requirements.txt",
            "backend/templates/Direct/Treadwell Proposal Template - Epoxy.docx"]
    assert [p for p in out if not _docker_excludes(p, rules)] == []
    assert [p for p in kept if _docker_excludes(p, rules)] == []
    # The matcher itself, on rules whose Docker meaning is documented, so it cannot drift into
    # agreeing with anything: `*.md` is root-only, a directory rule takes its children.
    assert _docker_excludes("README.md", rules) and not _docker_excludes("backend/x.md", rules)
    assert _docker_excludes("backend/.venv/lib/site.py", rules)


def test_the_dockerfile_copies_no_font_and_leaves_the_mount_point_empty():
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    code = [ln for ln in dockerfile.splitlines() if not ln.lstrip().startswith("#")]
    assert not [ln for ln in code if re.match(r"\s*(COPY|ADD)\b.*fonts", ln)], (
        "the Dockerfile copies fonts into the image again")
    assert any(re.search(r"\bmkdir -p %s\b" % re.escape(proposal_fonts.MOUNT_DIR.as_posix()), ln)
               for ln in code), "the mount point is no longer made in the image"
    assert any("fc-cache" in ln for ln in code), "the system font cache is no longer built"
    # The app tree still goes in; .dockerignore (above) is what keeps fonts out of it.
    assert re.search(r"(?m)^COPY backend/ /app/\s*$", dockerfile)


@pytest.mark.parametrize("compose,service", [("docker-compose.yml", "proposal-tool"),
                                             ("docker-compose.staging.yml", "app")])
def test_both_stacks_mount_the_host_fonts_read_only(compose, service):
    """Read-only, and from the same host directory the deploy checks and the warning names."""
    spec = yaml.safe_load((REPO / compose).read_text(encoding="utf-8"))
    assert MOUNT in spec["services"][service]["volumes"], spec["services"][service]["volumes"]


def test_the_module_reads_the_mount_first_then_the_dev_copy():
    assert proposal_fonts.FONT_DIRS == (
        proposal_fonts.MOUNT_DIR,
        pathlib.Path(proposal_fonts.__file__).resolve().parent / "fonts")
    # Under /usr/share/fonts, so LibreOffice's fontconfig finds the very files the route serves.
    assert proposal_fonts.MOUNT_DIR.as_posix().startswith("/usr/share/fonts/")


def _deploy_scripts():
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8"))
    return {(job, step.get("name", "")): step["with"]["script"]
            for job in ("staging", "production")
            for step in wf["jobs"][job]["steps"]
            if "script" in step.get("with", {})}


def test_the_ci_pdf_smoke_run_mounts_the_fonts_too():
    """It overrides CMD with its own `sh -c` in a throwaway container, and its tests count how many
    lines LibreOffice fits in a box: a question about the real face, which only the mount has."""
    script = next(s for (job, name), s in _deploy_scripts().items() if name.startswith("PDF fidelity"))
    run = script[script.index("docker run"):script.index('"$TW_IMAGE"')]
    assert "-v " + MOUNT in run, run


def _font_checks():
    """Every deploy path's font check, as the text that runs on the VPS."""
    checks = {}
    for (job, name), script in _deploy_scripts().items():
        if "TW_FONT_DIR=" in script:
            lines = script.splitlines()
            start = next(i for i, ln in enumerate(lines) if ln.startswith("TW_FONT_DIR="))
            end = next(i for i in range(start, len(lines)) if lines[i].strip() == "done")
            checks[job] = ("\n".join(lines[start:end + 1]), script)
    ship = (REPO / "deploy" / "ship.sh").read_text(encoding="utf-8")
    m = re.search(r"""\n"\$\{SSH\[@\]\}" '(for f in [^']*done)'\n""", ship)
    assert m, "deploy/ship.sh no longer checks the font on the box"
    checks["ship.sh"] = (m.group(1), ship)
    return checks


def _seed(where, block, script):
    """The directory a deploy path copies a missing file from: the checkout it is about to pull,
    plus /backend/fonts. Read from the script's own `cd` before its `git pull`, not pinned, so a
    path that copied from some OTHER checkout (staging's from prod's) fails here."""
    if where == "ship.sh":
        pulled = re.search(r'^APP_DIR="([^"]+)"$', script, re.M).group(1)
        assert re.search(r"^\s*cd \$APP_DIR\n\s*git pull\b", script, re.M), "ship.sh pulls elsewhere"
    else:
        pulled = re.search(r"^cd (\S+)\ngit pull\b", script, re.M).group(1)
    seed = pulled + "/backend/fonts"
    assert seed in block, "%s does not keep %s's copy before pulling it" % (where, pulled)
    return seed


def _runnable(where, host, checkout):
    """A deploy path's font block as bash will run it, with the host dir and the checkout's
    backend/fonts/ swapped for temp ones (and nothing else changed)."""
    block, script = _font_checks()[where]
    seed = _seed(where, block, script)
    code = "set -euo pipefail\n" + (block.replace(proposal_fonts.HOST_DIR, host.as_posix())
                                    .replace(seed, checkout.as_posix()))
    assert proposal_fonts.HOST_DIR not in code and seed not in code
    assert host.as_posix() in code and checkout.as_posix() in code
    return code


def test_every_deploy_path_checks_the_font_before_it_changes_anything():
    """The image needs the host's files, so each path that starts an image checks for them first:
    before its `git pull` (which deletes the checkout's tracked copy, see the next test), before
    the first `docker compose` in the CI deploys, before the build in ship.sh."""
    checks = _font_checks()
    assert set(checks) == {"staging", "production", "ship.sh"}
    for where, (block, script) in checks.items():
        for filename in proposal_fonts.FONTS.values():
            assert '"%s"' % filename in block, (where, filename)
        assert proposal_fonts.HOST_DIR in block, where
        first = script.index("docker build" if where == "ship.sh" else "docker compose")
        assert script.index(block) < first, "%s checks the font after it has started" % where
        pull = re.search(r"^\s*git pull\b", script, re.M).start()
        assert script.index(block) < pull, "%s pulls before it keeps and checks the font" % where


def _bash():
    """A bash that can read a temp path: POSIX anywhere, Git for Windows' on a dev box (never
    System32's, which is the WSL launcher and cannot see C:\\)."""
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    git = shutil.which("git")
    if git:
        for up in pathlib.Path(git).resolve().parents[:3]:
            for cand in (up / "bin" / "bash.exe", up / "usr" / "bin" / "bash.exe"):
                if cand.is_file():
                    return str(cand)
    return None


@pytest.mark.parametrize("where", ["staging", "production", "ship.sh"])
def test_the_deploy_font_check_refuses_a_box_without_the_files(where, tmp_path, synthetic_dir):
    """EXECUTED, with only the host path swapped for a temp one. A box missing either file, or
    holding an empty placeholder, stops the deploy; a box with both goes ahead."""
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to run the check with")
    host = tmp_path / "treadwell-fonts"
    host.mkdir()
    checkout = tmp_path / "checkout" / "backend" / "fonts"     # already pulled: no font left
    checkout.mkdir(parents=True)
    code = _runnable(where, host, checkout)

    def run():
        return subprocess.run([bash, "-c", code], capture_output=True, text=True, timeout=60)

    names = list(proposal_fonts.FONTS.values())
    empty = run()
    assert empty.returncode != 0 and names[0] in empty.stdout, (empty.stdout, empty.stderr)
    assert "Dropbox" in empty.stdout, "the refusal must say where a lasting copy is"
    shutil.copy(synthetic_dir / names[0], host / names[0])
    one = run()
    assert one.returncode != 0 and names[1] in one.stdout, (one.stdout, one.stderr)
    (host / names[1]).write_bytes(b"")
    placeholder = run()
    assert placeholder.returncode != 0 and names[1] in placeholder.stdout
    shutil.copy(synthetic_dir / names[1], host / names[1])
    both = run()
    assert both.returncode == 0, (both.stdout, both.stderr)
    assert list(checkout.iterdir()) == [], "the check never writes into the checkout"


@pytest.mark.parametrize("where", ["staging", "production", "ship.sh"])
def test_the_first_deploy_keeps_the_checkouts_copy_before_its_pull_deletes_it(
        where, tmp_path, synthetic_dir):
    """Review, 2026-09-26: untracking the files deletes them from every checkout at its next pull,
    the two VPS checkouts included, and before this change those checkouts were the only copies on
    the box. So each deploy path copies a missing file from the checkout it is about to pull, before
    it pulls. EXECUTED, with the host dir not made yet (a box that never had one) and the checkout
    still tracking both files, which is every VPS checkout before its first pull past this change."""
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to run the check with")
    host = tmp_path / "treadwell-fonts"
    checkout = tmp_path / "checkout" / "backend" / "fonts"
    checkout.mkdir(parents=True)
    names = list(proposal_fonts.FONTS.values())
    for filename in names:
        shutil.copy(synthetic_dir / filename, checkout / filename)
    code = _runnable(where, host, checkout)

    def run():
        return subprocess.run([bash, "-c", code], capture_output=True, text=True, timeout=60)

    def is_real(filename):
        return (host / filename).read_bytes() == (synthetic_dir / filename).read_bytes()

    first = run()
    assert first.returncode == 0, (first.stdout, first.stderr)
    assert all(is_real(f) for f in names), sorted(p.name for p in host.iterdir())
    # What the box already holds wins: the checkout's copy never replaces a file that is there...
    (checkout / names[0]).write_bytes(b"OTTO but not the font the box holds")
    again = run()
    assert again.returncode == 0 and is_real(names[0]), (again.stdout, again.stderr)
    # ...but an empty placeholder is no font, and the checkout's real file takes its place.
    (host / names[1]).write_bytes(b"")
    healed = run()
    assert healed.returncode == 0 and is_real(names[1]), (healed.stdout, healed.stderr)
    # Once the pull has deleted the checkout's copy, only a copy from Dropbox lets a deploy on.
    for filename in names:
        (host / filename).unlink()
        (checkout / filename).unlink()
    gone = run()
    assert gone.returncode != 0 and "Dropbox" in gone.stdout, (gone.stdout, gone.stderr)


# ═══ a box without the font ════════════════════════════════════════════════════════════
def _font_warnings(caplog):
    return [r for r in caplog.records
            if r.levelno == logging.WARNING and "PROPOSAL FONT" in r.getMessage()]


def test_a_box_without_the_font_says_so_once_at_startup(no_fonts, caplog):
    """Docker turns a missing host directory into an EMPTY mount: the container boots, passes
    /healthz and prints every PDF in a substitute font. The startup hook is the only thing on
    the box that says so -- once per process, however often the app starts up in it."""
    assert main._report_proposal_font in main.app.router.on_startup
    caplog.set_level(logging.INFO)
    main._report_proposal_font()
    main._report_proposal_font()
    warned = _font_warnings(caplog)
    assert len(warned) == 1, [r.getMessage() for r in warned]
    msg = warned[0].getMessage()
    assert warned[0].name == "proposal_tool"
    assert "neither Zetta Serif file" in msg
    for filename in proposal_fonts.FONTS.values():
        assert filename in msg
    assert proposal_fonts.HOST_DIR in msg and "substitute font" in msg


def test_one_missing_file_is_named(no_fonts, caplog, synthetic_dir):
    mount, _dev = no_fonts
    shutil.copy(synthetic_dir / "Zetta Serif-Book.otf", mount / "Zetta Serif-Book.otf")
    caplog.set_level(logging.INFO)
    main._report_proposal_font()
    warned = _font_warnings(caplog)
    assert len(warned) == 1
    msg = warned[0].getMessage()
    assert "Zetta Serif.otf is in" in msg and "neither" not in msg


def test_an_installed_font_is_one_quiet_info_line(fonts, monkeypatch, caplog):
    monkeypatch.setattr(proposal_fonts, "_reported", False)
    caplog.set_level(logging.INFO)
    main._report_proposal_font()
    assert _font_warnings(caplog) == []
    assert [r.getMessage() for r in caplog.records if "Proposal font" in r.getMessage()] == [
        "Proposal font: Zetta Serif is installed (Zetta Serif-Book.otf, Zetta Serif.otf)."]


@pytest.mark.parametrize("name", sorted(proposal_fonts.FONTS))
def test_a_missing_file_is_a_clean_404(no_fonts, name):
    """The editor keeps its fallback serif on any failure; it needs an answer, not a 500."""
    r = client.get("/api/proposal-font/" + name)
    assert r.status_code == 404
    assert r.json() == {"detail": "No such font"}


def test_healthz_never_looks_at_the_font(no_fonts, monkeypatch):
    """/healthz must stay cheap and never flap (the Basisboard outage): a missing font is a
    warning and a 404, never an unhealthy container that compose restarts in a loop."""
    def boom(*_a, **_k):
        raise AssertionError("/healthz touched the font")
    monkeypatch.setattr(proposal_fonts, "load", boom)
    monkeypatch.setattr(proposal_fonts, "missing", boom)
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_a_file_placed_after_start_is_served_without_a_restart(no_fonts, synthetic_dir):
    """Only a hit is cached, so copying the files onto a running box is enough for the editor
    (fontconfig rescans the changed directory for LibreOffice on its own)."""
    mount, _dev = no_fonts
    assert client.get("/api/proposal-font/zetta-serif").status_code == 404
    shutil.copy(synthetic_dir / "Zetta Serif.otf", mount / "Zetta Serif.otf")
    r = client.get("/api/proposal-font/zetta-serif")
    assert r.status_code == 200 and r.content == (synthetic_dir / "Zetta Serif.otf").read_bytes()


def test_the_mount_wins_over_the_dev_copy_and_the_dev_copy_still_works(no_fonts):
    """The order FONT_DIRS promises, as load() actually walks it: a dev box (no mount) reads
    backend/fonts/, and a server that has both serves the mount -- the copy LibreOffice prints."""
    mount, dev = no_fonts
    dev_bytes = _synthetic_otf("Zetta Serif Book", 345, b"dev")
    (dev / "Zetta Serif-Book.otf").write_bytes(dev_bytes)
    r = client.get("/api/proposal-font/zetta-serif-book")
    assert r.status_code == 200 and r.content == dev_bytes
    mount_bytes = _synthetic_otf("Zetta Serif Book", 345, b"mount")
    (mount / "Zetta Serif-Book.otf").write_bytes(mount_bytes)
    proposal_fonts.cache_clear()
    r = client.get("/api/proposal-font/zetta-serif-book")
    assert r.status_code == 200 and r.content == mount_bytes


# ═══ the endpoint, signed in ═══════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", sorted(proposal_fonts.FONTS))
def test_a_signed_in_request_gets_the_bytes(fonts, name):
    r = client.get("/api/proposal-font/" + name)
    assert r.status_code == 200
    assert r.content == fonts[name]
    assert r.headers["content-type"].split(";")[0] == "font/otf"
    assert r.headers["x-content-type-options"] == "nosniff"
    cc = [d.strip() for d in r.headers["cache-control"].split(",")]
    assert "private" in cc and "public" not in cc, (
        "a licensed font a shared cache could hand to somebody who is not signed in")
    max_age = next(int(d.split("=", 1)[1]) for d in cc if d.startswith("max-age="))
    assert max_age >= 30 * 86400, "the editor would re-download 190 KB on every open"


@pytest.mark.parametrize("name", sorted(proposal_fonts.FONTS))
def test_a_revalidation_sends_no_body(fonts, name):
    etag = client.get("/api/proposal-font/" + name).headers["etag"]
    r = client.get("/api/proposal-font/" + name, headers={"If-None-Match": etag})
    assert r.status_code == 304 and not r.content


# ═══ the endpoint, signed out ══════════════════════════════════════════════════════════
@pytest.mark.parametrize("auth", [None, "Bearer not-a-real-token", "Basic dXNlcjpwYXNz"])
@pytest.mark.parametrize("name", sorted(proposal_fonts.FONTS))
def test_nobody_signed_out_gets_the_font(fonts, signed_out, name, auth):
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
def test_no_url_of_the_app_returns_the_font_bytes_signed_out(fonts, signed_out, url):
    """This app's own URLs. Git and new images no longer hold the files at all (the tests above);
    what history and older GHCR images still hold is outside any test: see proposal_fonts.py."""
    r = client.get(url)
    assert r.content not in set(fonts.values()) and not r.content.startswith(b"OTTO"), url


def test_no_font_sits_in_the_public_static_tree():
    """The static mount serves frontend/ to anyone, and ship.sh builds from the working tree, so
    any font file on disk there -- tracked or not -- would be a public URL no route test can see.
    By content, so it needs no licensed bytes to compare against."""
    hits = []
    for p in FRONTEND.rglob("*"):
        if p.is_file():
            with open(p, "rb") as fh:
                if fh.read(4) in FONT_MAGIC or p.name.lower().endswith(FONT_SUFFIXES):
                    hits.append(str(p))
    assert hits == []


# ═══ the whitelist ═════════════════════════════════════════════════════════════════════
EVIL = ["Zetta Serif.otf", "Zetta Serif-Book.otf", "zetta-serif.otf", "ZETTA-SERIF", "zetta-serif ",
        " zetta-serif", "Zetta%20Serif.otf", "..%2Fmain.py", "main.py", "fonts", "..", ".",
        "__init__", "keys", "get", "zetta-serif-bookx", "zetta"]


@pytest.mark.parametrize("name", EVIL)
def test_any_other_name_is_refused(fonts, name):
    r = client.get("/api/proposal-font/" + name)
    assert r.status_code != 200 and b"OTTO" not in r.content, name


def test_no_request_name_reaches_the_filesystem(fonts, monkeypatch, synthetic_dir):
    """The name is a dictionary key. Anything that is not one is refused before a path exists,
    and a whitelisted name reads exactly its own file."""
    reads = []
    real = pathlib.Path.read_bytes
    monkeypatch.setattr(pathlib.Path, "read_bytes", lambda self: reads.append(self) or real(self))
    for name in EVIL + [None, 1, ("zetta-serif",), b"zetta-serif", "../fonts/Zetta Serif.otf"]:
        assert proposal_fonts.load(name) is None, name
    assert reads == []
    data, _etag = proposal_fonts.load("zetta-serif")
    assert data == fonts["zetta-serif"]
    assert reads == [synthetic_dir / "Zetta Serif.otf"]


# ═══ the loader, executed ══════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def ran(synthetic_dir):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    files = {name: str(synthetic_dir / filename) for name, filename in proposal_fonts.FONTS.items()}
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND), json.dumps(files)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed; read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_each_face_is_registered_from_its_bytes_as_what_the_file_really_is(ran, synthetic_dir):
    """Family and weight as the file's own tables give them (EXPECTED, which the real-file test
    ties to the licensed binaries), upright, from an ArrayBuffer (a url() load could not carry the
    bearer token, and a blob: URL is refused by nginx's `font-src 'self'`). Each face carries the
    bytes of ITS file: the sha ties the registration to the file whose tables name that family."""
    by_sha = {_sha((synthetic_dir / f).read_bytes()): synthetic_dir / f
              for f in proposal_fonts.FONTS.values()}
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
    assert sorted(f["family"] for f in faces) == sorted(fam for fam, _w in EXPECTED.values())
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
