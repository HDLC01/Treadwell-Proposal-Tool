"""The public repo must not publish how to reach the server.

The repos stay public (Hanz, 2026-09-28). An address, a login name or a key filename in a
committed file hands anyone scanning GitHub the box and the account to try. Those details live
in the owner's SSH config under the alias `treadwell-vps`, and `deploy/ship.sh` points at the
alias. Git history still holds the old values; these tests pin the files, not the past.

The scan covers the files people write infrastructure down in (docs, scripts, CI, compose).
Python sources are left out: test fixtures carry real mail-server addresses on purpose.

The last two tests keep local tool output (knowledge snapshot, graphify graph, crash dumps)
ignored, so a stray `git add -A` cannot publish it either.
"""
import ipaddress
import pathlib
import re
import shlex
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SHIP = ROOT / "deploy" / "ship.sh"
ALIAS = "treadwell-vps"

SUFFIXES = {".md", ".sh", ".yml", ".yaml", ".conf", ".txt", ".ps1", ".example", ".toml",
            ".ini", ".cfg", ".env"}
NO_SUFFIX_DIRS = ("deploy", "ops")
# Four dotted numbers, not part of a longer dotted run (a five-part version string).
IPV4 = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?!\.?\w)")
ROOT_LOGIN = re.compile(r"\broot@")
# A key file under ~/.ssh names the key. `~/.ssh/config` is where the alias lives, so it may be named.
KEY_PATH = re.compile(r"\.ssh/(?!config\b)[\w.-]+")


def _tracked_text_files():
    try:
        proc = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("git is not available")
    if proc.returncode != 0:
        pytest.skip("not a git checkout")
    for rel in filter(None, proc.stdout.decode("utf-8").split("\0")):
        p = pathlib.PurePosixPath(rel)
        if p.suffix.lower() in SUFFIXES or p.name.startswith("Dockerfile") or p.parts[0] in NO_SUFFIX_DIRS:
            yield rel


def _findings(rel, text):
    for number, line in enumerate(text.splitlines(), 1):
        for m in IPV4.finditer(line):
            try:
                public = ipaddress.ip_address(m.group(1)).is_global
            except ValueError:
                continue
            if public:
                yield "%s:%d public IP address" % (rel, number)
        if ROOT_LOGIN.search(line):
            yield "%s:%d root@ login" % (rel, number)
        if KEY_PATH.search(line):
            yield "%s:%d SSH key file path" % (rel, number)


def test_no_tracked_doc_or_script_says_how_to_reach_the_server():
    scanned, found = 0, []
    for rel in _tracked_text_files():
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        found.extend(_findings(rel, text))
    # The scan has to have read the files it exists for, or an empty `found` means nothing.
    assert scanned > 20, "the scan read almost nothing"
    assert not found, "use the `treadwell-vps` SSH alias instead:\n" + "\n".join(found)


def test_the_scan_flags_each_kind_of_detail():
    """A green scan only means something if it can go red on the shapes it looks for."""
    text = "\n".join([
        "ssh root@<vps-ip>",
        'VPS_HOST="${VPS_HOST:-8.8.8.8}"',
        'SSH_KEY="$HOME/.ssh/some_key"',
        "fine: 127.0.0.1, 10.0.0.5, 203.0.113.9, v1.2.3.4.5, ~/.ssh/config, ssh treadwell-vps",
    ])
    assert list(_findings("x.md", text)) == [
        "x.md:1 root@ login", "x.md:2 public IP address", "x.md:3 SSH key file path"]


def _bash():
    """A bash that can run a script. On Windows the first `bash` on PATH is often the WSL
    stub, which fails without a distro, so Git for Windows' own bash is tried as well."""
    candidates = [shutil.which("bash")]
    git = shutil.which("git")
    if git:
        git_root = pathlib.Path(git).resolve().parents[1]
        candidates += [str(git_root / "bin" / "bash.exe"), str(git_root / "usr" / "bin" / "bash.exe")]
    for exe in filter(None, candidates):
        try:
            probe = subprocess.run([exe, "-c", "echo ok"], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0 and probe.stdout.strip() == b"ok":
            return exe
    pytest.skip("no bash that can run a script here")


def _ship_ssh_argv(**env):
    """Run ship.sh's own settings block (everything before it cds to the repo root) and return
    the ssh command it would use. Values are set inside the script, not through the process
    environment, so a bash that does not inherit Windows variables still sees them."""
    text = SHIP.read_text(encoding="utf-8")  # universal newlines: a CRLF checkout reads as LF
    head, sep, _ = text.partition('\ncd "$(dirname "$0")/.."')
    assert sep, "ship.sh no longer cds to the repo root, so its settings cannot be isolated"
    lines = ["unset VPS_HOST VPS_USER SSH_KEY TW_IMAGE"]
    lines += ["export %s=%s" % (k, shlex.quote(v)) for k, v in env.items()]
    body = "\n".join(lines) + "\n" + head + '\nprintf "%s\\n" "${SSH[@]}"\n'
    proc = subprocess.run([_bash(), "-s"], input=body.encode("utf-8"), capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return proc.stdout.decode("utf-8").replace("\r", "").splitlines()


def test_the_manual_deploy_reaches_the_box_through_the_ssh_alias():
    # Only the alias: no user, port or key on the command line, so ~/.ssh/config supplies them.
    assert _ship_ssh_argv() == ["ssh", "-o", "ConnectTimeout=20", ALIAS]


def test_the_manual_deploy_still_takes_an_explicit_box_user_and_key():
    argv = _ship_ssh_argv(VPS_HOST="203.0.113.9", VPS_USER="deploy", SSH_KEY="/keys/a key")
    assert argv == ["ssh", "-o", "ConnectTimeout=20", "-i", "/keys/a key", "deploy@203.0.113.9"]


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("git is not available")


# Local tool output that sat untracked in the root checkout, one `git add -A` from being published.
@pytest.mark.parametrize("path", [
    ".claude/knowledge/SYSTEM-KB.md", ".codex/state.json", "graphify-out/graph.json",
    "walk2/step1.png", "console-debug.txt", "bash.exe.stackdump", "grep.exe.stackdump",
])
def test_local_tool_output_is_ignored(path):
    proc = _git("check-ignore", "-q", "--no-index", path)
    if proc.returncode == 128:
        pytest.skip("not a git checkout")
    assert proc.returncode == 0, "%s is not ignored" % path


def test_no_tracked_file_is_ignored():
    """An ignore rule that matches a committed file hides that file's next edit from `git status`."""
    proc = _git("ls-files", "--cached", "--ignored", "--exclude-standard")
    if proc.returncode != 0:
        pytest.skip("not a git checkout")
    assert proc.stdout.decode("utf-8").split() == []
