"""The deploy pipeline must never build the image on the production VPS.

That box is 1 core / 2 GB and hosts ~13 containers for other Treadwell sites. This image
bakes in Node, the Claude CLI and LibreOffice, so building it there spikes load to ~60 and
browns out every site on the machine — which is how production went down on 2026-06-24,
and retrying the deploy made it worse.

`--build` is one word, it reads as harmless, and the failure it causes lands on unrelated
applications rather than on this one. So it is pinned here rather than left to whoever
edits the workflow next.

The second half of this file (from "SUPPLY CHAIN" down) holds what the 2026-09-28 security
review asked for: every action and base image pinned to an immutable reference, a manual run
that can only deploy from main or staging, and each job's token cut to what it uses.
"""
import fnmatch
import os
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"
CODEQL = ROOT / ".github" / "workflows" / "codeql.yml"
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
DOCKERFILE = ROOT / "Dockerfile"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
COMPOSES = [ROOT / "docker-compose.yml", ROOT / "docker-compose.staging.yml"]
IMAGE = "ghcr.io/hdlc01/treadwell-proposal-tool"


def _workflow_image() -> str:
    """The `IMAGE:` env value from the workflow, exactly.

    Compared by EQUALITY rather than `"ghcr.io" in text`: CodeQL rightly flags a
    substring test against something URL-shaped, because that is the shape of a real
    vulnerability (`if "example.com" in url` is defeated by
    evil-example.com.attacker.net). Harmless in a test, but an exact match is a stronger
    assertion anyway — it would catch a typo'd or repointed registry, which a substring
    check would wave through."""
    for line in DEPLOY.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("IMAGE:"):
            return stripped.split(":", 1)[1].strip()
    raise AssertionError("the workflow declares no IMAGE")


def test_the_deploy_workflow_exists():
    """A rename would make every assertion below vacuously pass."""
    assert DEPLOY.is_file()


def test_no_deploy_step_builds_on_the_box():
    """THE rule. Both stacks live on the same VPS, so staging builds are just as capable
    of taking prod down as prod builds are."""
    # Comments stripped first: the prose above explains the outage using the very flag it
    # forbids, and each command carries a trailing `# NO --build`. Matching those would
    # make this test fail on its own documentation.
    code = [ln.split("#", 1)[0] for ln in DEPLOY.read_text(encoding="utf-8").splitlines()]
    offenders = [ln.strip() for ln in code if "docker compose" in ln and "--build" in ln]
    assert not offenders, ("a deploy step still builds on the VPS: " + "; ".join(offenders))


def test_the_image_is_built_on_a_runner_and_pushed():
    text = DEPLOY.read_text(encoding="utf-8")
    assert "docker/build-push-action" in text
    assert "push: true" in text
    assert _workflow_image() == IMAGE


def test_both_deploys_wait_for_the_build():
    """Without `needs: build` the SSH step could pull a tag that doesn't exist yet and
    fail — or worse, silently restart the OLD image and report success."""
    text = DEPLOY.read_text(encoding="utf-8")
    for job in ("staging:", "production:"):
        i = text.index("\n  " + job)
        block = text[i:i + 400]
        assert "needs: build" in block, f"{job} does not depend on the build job"


def test_every_build_gets_an_immutable_tag():
    """Rollback has to be one variable, not a revert commit and a rebuild: the moving
    staging/prod tag alone can't take you back to a specific known-good image."""
    text = DEPLOY.read_text(encoding="utf-8")
    assert "sha-${GITHUB_SHA::12}" in text


def test_the_runner_needs_packages_write():
    """Push to GHCR fails with a permissions error that reads like an auth problem."""
    text = DEPLOY.read_text(encoding="utf-8")
    assert "packages: write" in text


def test_no_long_lived_registry_credential():
    """The built-in GITHUB_TOKEN is job-scoped and expires. A PAT in secrets would sit
    on the VPS's docker config after the first deploy."""
    text = DEPLOY.read_text(encoding="utf-8")
    assert "secrets.GITHUB_TOKEN" in text
    assert "docker logout" in text, "the box keeps a registry login after deploying"


def test_the_build_runs_before_the_approval_gate():
    """A broken build should fail while nobody is waiting on it, and the reviewer should
    only ever approve an artifact that already exists."""
    text = DEPLOY.read_text(encoding="utf-8")
    assert text.index("\n  build:") < text.index("environment: production")


@pytest.mark.parametrize("path", COMPOSES, ids=lambda p: p.name)
def test_compose_resolves_a_registry_image(path):
    text = path.read_text(encoding="utf-8")
    # Exact default, not a substring: the point is that compose resolves the image the
    # workflow actually pushes. A near-miss would start something else, or nothing.
    default = re.search(r"image: \$\{TW_IMAGE:-([^}]+)\}", text)
    assert default, "compose does not resolve an overridable image"
    repo, _, tag = default.group(1).rpartition(":")
    assert repo == IMAGE
    assert tag in ("prod", "staging")


@pytest.mark.parametrize("path", COMPOSES, ids=lambda p: p.name)
def test_compose_keeps_a_build_block_as_the_escape_hatch(path):
    """Kept on purpose: `deploy/ship.sh` and a local `up --build` have to keep working when
    CI or the registry is down. Compose only builds when explicitly asked."""
    text = path.read_text(encoding="utf-8")
    assert re.search(r"build:\s*\n\s*context: \.", text)


def test_the_manual_fallback_still_exists_and_says_what_it_is_for():
    ship = (ROOT / "deploy" / "ship.sh").read_text(encoding="utf-8")
    assert "MANUAL FALLBACK" in ship
    # It must tag what compose will start, or `up -d` quietly runs the old image.
    assert IMAGE in ship
    assert "up -d" in ship and "--build" not in ship.split("docker compose")[-1]


# ── SUPPLY CHAIN ──────────────────────────────────────────────────────────────────────────
#
# The deploy steps are handed the VPS deploy key, and the image runs as root on that VPS. So
# anything that decides WHICH code runs in either place has to be an immutable reference, not a
# name somebody else can repoint: an action tag, an image tag and an unversioned `npm install`
# are all "whatever upstream serves today".

def _load(path):
    """The workflow as GitHub reads it. PyYAML takes the bare key `on:` for the boolean True
    (YAML 1.1), so it is put back under its real name."""
    wf = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in wf:
        wf["on"] = wf.pop(True)
    return wf


_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")
_SHA_REF = re.compile(r"[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}")
_TAG_COMMENT = re.compile(r"\s+#\s+v\d+(?:\.\d+){0,2}\s*")


def _uses_as_text():
    """(where, ref, rest-of-line) for every `uses:` line. Read as TEXT because the version
    comment Dependabot keys on is a comment, which a YAML parser throws away."""
    out = []
    for path in WORKFLOWS:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = _USES.match(line)
            if m:
                out.append((f"{path.name}:{n}", m.group(1), m.group(2)))
    return out


def _uses_as_parsed():
    out = []
    for path in WORKFLOWS:
        for job in _load(path)["jobs"].values():
            if "uses" in job:                       # a reusable workflow at job level
                out.append(job["uses"])
            out.extend(step["uses"] for step in job.get("steps", []) if "uses" in step)
    return out


def test_every_action_is_pinned_to_a_full_commit_sha():
    """A tag is a pointer its owner can move; a 40-hex commit is the code itself. The trailing
    `# vX.Y.Z` is what Dependabot reads to propose the next SHA, so it is required too."""
    found = _uses_as_text()
    # Not vacuous: the text scan must see exactly what GitHub will run, in order. A `uses:`
    # written in a shape the line regex misses would otherwise escape the check entirely.
    assert [ref for _, ref, _ in found] == _uses_as_parsed()
    assert len(found) >= 16, found
    assert any(ref.startswith("appleboy/ssh-action@") for _, ref, _ in found), (
        "the step that is handed the deploy key is no longer seen by this check")
    unpinned = [f"{where} {ref}" for where, ref, _ in found if not _SHA_REF.fullmatch(ref)]
    assert not unpinned, "actions not pinned to a commit SHA: " + "; ".join(unpinned)
    untagged = [f"{where} {ref}{rest}" for where, ref, rest in found if not _TAG_COMMENT.fullmatch(rest)]
    assert not untagged, "pinned without the `# vX.Y.Z` comment Dependabot needs: " + "; ".join(untagged)


def test_the_same_action_is_pinned_to_one_sha_per_version():
    """Two different SHAs under one version comment means one of them is not what it says."""
    seen = {}
    for where, ref, rest in _uses_as_text():
        name, sha = ref.split("@")
        key = (name, rest.strip())
        assert seen.setdefault(key, sha) == sha, f"{where}: {name} {rest.strip()} has two SHAs"


# Writes a job may hold. Everything else is read or nothing: `packages: write` is the GHCR push,
# `security-events: write` is CodeQL uploading its results.
_ALLOWED_WRITES = {
    ("deploy.yml", "build"): {"packages"},
    ("codeql.yml", "analyze"): {"security-events"},
}


def test_every_job_declares_its_own_minimal_permissions():
    """Without a `permissions:` block a job's token gets the repository default, which is set in
    the GitHub UI and can be widened there without any change to these files."""
    jobs = 0
    for path in WORKFLOWS:
        wf = _load(path)
        assert not isinstance(wf.get("permissions"), str), (
            f"{path.name} grants a blanket `{wf.get('permissions')}` to every job")
        for name, job in wf["jobs"].items():
            jobs += 1
            perms = job.get("permissions")
            assert isinstance(perms, dict), f"{path.name}:{name} has no permissions block of its own"
            assert set(perms.values()) <= {"read", "write", "none"}, (path.name, name, perms)
            writes = {scope for scope, level in perms.items() if level == "write"}
            assert writes == _ALLOWED_WRITES.get((path.name, name), set()), (path.name, name, perms)
    assert jobs >= 7, "fewer jobs than the three workflows define: the scan is looking elsewhere"


def test_both_deploy_jobs_can_still_pull_the_image():
    """Their token IS the registry login on the VPS (GHCR_TOKEN). Trimmed below `packages: read`,
    `docker compose pull` fails on the box and nothing here would say why."""
    wf = _load(DEPLOY)
    for name in ("staging", "production"):
        job = wf["jobs"][name]
        assert job["permissions"] == {"packages": "read"}, (name, job["permissions"])
        tokens = [s["env"]["GHCR_TOKEN"] for s in job["steps"] if "GHCR_TOKEN" in s.get("env", {})]
        assert tokens == ["${{ secrets.GITHUB_TOKEN }}"], (name, tokens)


# ── the manual-run guard, EVALUATED ───────────────────────────────────────────────────────

_TOKEN = re.compile(r"\s*(\|\||&&|==|!=|!|\(|\)|'(?:[^']|'')*'|[A-Za-z_][\w.-]*)")


def _expr(source, ctx):
    """The subset of GitHub's expression language these job `if:`s use, evaluated the way
    GitHub does: `==` and `!=` IGNORE CASE (GitHub's documented rule for strings). Anything
    outside the subset raises, so a new construct fails this test instead of being misread."""
    source = source.strip()
    if source.startswith("${{") and source.endswith("}}"):
        source = source[3:-2]
    tokens, pos = [], 0
    while pos < len(source.rstrip()):
        m = _TOKEN.match(source, pos)
        assert m and m.end() > pos, f"unsupported expression syntax at {source[pos:]!r}"
        tokens.append(m.group(1))
        pos = m.end()
    i = 0

    def peek():
        return tokens[i] if i < len(tokens) else None

    def take():
        nonlocal i
        i += 1
        return tokens[i - 1]

    def atom():
        tok = take()
        if tok == "(":
            value = either()
            assert take() == ")", source
            return value
        if tok.startswith("'"):
            return tok[1:-1].replace("''", "'")
        if tok in ("true", "false"):
            return tok == "true"
        assert tok in ctx, f"the guard reads {tok!r}, which this evaluator does not model"
        return ctx[tok]

    def compare():
        left = atom()
        if peek() in ("==", "!="):
            op, right = take(), atom()
            same = str(left).lower() == str(right).lower()
            return same if op == "==" else not same
        return left

    def negate():
        if peek() == "!":
            take()
            return not negate()
        return compare()

    def both():
        value = negate()
        while peek() == "&&":
            take()
            value = negate() and value
        return value

    def either():
        value = both()
        while peek() == "||":
            take()
            value = both() or value
        return value

    result = either()
    assert i == len(tokens), f"trailing tokens in {source!r}"
    return bool(result)


def _bash():
    """A bash that can run a script: POSIX anywhere, Git for Windows' on a dev box (never
    System32's, which is the WSL launcher). Same lookup as test_proposal_fonts.py."""
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


def _ref_guards(job):
    """The steps that refuse a ref: every `run:` that reads $GITHUB_REF."""
    return [s for s in job.get("steps", []) if "GITHUB_REF" in s.get("run", "").replace("GITHUB_REF_", "")]


def _jobs_that_complete(event, ref, bash):
    """Which deploy.yml jobs get past their own gates for this trigger, the way the runner
    decides it: the event's filter, then per job its `needs`, its `if:`, and the ref-guard
    steps, which are EXECUTED with the ref the runner would export."""
    wf = _load(DEPLOY)
    trigger = wf["on"]
    if event not in trigger:
        return set()
    if event == "push":
        branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else None
        if branch is None or not any(fnmatch.fnmatchcase(branch, b) for b in trigger["push"]["branches"]):
            return set()
    ctx = {"github.event_name": event, "github.ref": ref, "github.ref_name": ref.split("/", 2)[2]}
    done = set()
    for name, job in wf["jobs"].items():
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        if not all(n in done for n in needs):
            continue
        if "if" in job and not _expr(job["if"], ctx):
            continue
        refused = False
        for step in _ref_guards(job):
            proc = subprocess.run([bash, "-c", step["run"]], capture_output=True, text=True, timeout=30,
                                  env={**os.environ, "GITHUB_REF": ref})
            refused = refused or proc.returncode != 0
        if not refused:
            done.add(name)
    return done


@pytest.mark.parametrize("event,ref,expected", [
    # the two real deploys, by push and by hand
    ("push", "refs/heads/staging", {"build", "staging"}),
    ("push", "refs/heads/main", {"build", "production"}),
    ("workflow_dispatch", "refs/heads/staging", {"build", "staging"}),
    ("workflow_dispatch", "refs/heads/main", {"build", "production"}),
    # "Run workflow" from anywhere else: nothing built, nothing pushed, nothing deployed
    ("workflow_dispatch", "refs/heads/feature/pin-pipeline", set()),
    # a TAG named main: `github.ref_name` is "main" for it too, which the deploy jobs used to key on
    ("workflow_dispatch", "refs/tags/main", set()),
    ("workflow_dispatch", "refs/tags/staging", set()),
    # a branch that differs only in case: GitHub's `==` passes it, the bash guard does not
    ("workflow_dispatch", "refs/heads/Main", set()),
    ("workflow_dispatch", "refs/heads/STAGING", set()),
    # a push elsewhere never starts the workflow
    ("push", "refs/heads/feature/pin-pipeline", set()),
    ("pull_request", "refs/pull/1/merge", set()),
])
def test_a_deploy_runs_only_from_main_or_staging(event, ref, expected):
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to execute the ref guard with")
    assert _jobs_that_complete(event, ref, bash) == expected


def test_the_ref_guard_runs_before_anything_is_built():
    """The guard has to be FIRST: a checkout is harmless, but a guard after build-push would
    refuse the deploy only once the image was already pushed under the moving `staging` tag."""
    steps = _load(DEPLOY)["jobs"]["build"]["steps"]
    guards = _ref_guards({"steps": steps})
    assert guards and steps[0] is guards[0], [s.get("name") or s.get("uses") for s in steps]
    # and the job-level `if:`s name their branches by FULL ref, so a tag can never satisfy one
    jobs = _load(DEPLOY)["jobs"]
    assert "refs/heads/main" in jobs["build"]["if"] and "refs/heads/staging" in jobs["build"]["if"]
    for name in ("build", "staging", "production"):
        assert "ref_name" not in jobs[name]["if"], (name, jobs[name]["if"])


def test_the_expression_evaluator_is_not_vacuous():
    """The parametrized cases above lean on `_expr`; pin its semantics on known answers."""
    ctx = {"github.ref": "refs/heads/Main", "github.event_name": "push"}
    assert _expr("github.ref == 'refs/heads/main'", ctx)            # GitHub ignores case
    assert not _expr("github.ref != 'refs/heads/main'", ctx)
    assert _expr("${{ github.event_name == 'push' && (github.ref == 'x' || !false) }}", ctx)
    assert not _expr("github.event_name == 'push' && github.ref == 'x'", ctx)
    assert not _expr("github.ref == 'refs/heads/staging' || github.ref == 'refs/tags/main'", ctx)
    with pytest.raises(AssertionError):
        _expr("startsWith(github.ref, 'refs/heads/')", ctx)


# ── CodeQL ────────────────────────────────────────────────────────────────────────────────

def test_codeql_scans_the_javascript_frontend_as_well_as_python():
    """The frontend is plain JS that builds `innerHTML` strings; a Python-only scan cannot see
    the DOM-XSS class of bug the 2026-09-28 review found there."""
    job = _load(CODEQL)["jobs"]["analyze"]
    langs = [entry["language"] for entry in job["strategy"]["matrix"]["include"]]
    assert "python" in langs
    assert "javascript-typescript" in langs or "javascript" in langs, langs
    assert job["strategy"].get("fail-fast") is False, "one language failing would cancel the other"
    init = next(s for s in job["steps"] if "/codeql-action/init@" in s.get("uses", ""))
    assert init["with"]["languages"] == "${{ matrix.language }}"
    assert init["with"]["build-mode"] == "none"
    analyze = next(s for s in job["steps"] if "/codeql-action/analyze@" in s.get("uses", ""))
    assert analyze["with"]["category"] == "/language:${{ matrix.language }}"
    # the python leg still reports under the name and category it always had
    assert job["name"].replace("${{ matrix.language }}", "python") == "Analyze (python)"


# ── the image ─────────────────────────────────────────────────────────────────────────────

def _docker_code():
    """Dockerfile instructions only, continuation lines joined, comments dropped (the header
    comment quotes the `curl | bash` it replaced)."""
    lines = [ln for ln in DOCKERFILE.read_text(encoding="utf-8").splitlines()
             if not ln.lstrip().startswith("#")]
    return re.sub(r"\\\n", " ", "\n".join(lines)).splitlines()


def test_every_base_image_is_pinned_by_digest():
    froms = [ln.split() for ln in _docker_code() if re.match(r"(?i)^FROM\s", ln)]
    assert len(froms) >= 2, "expected the node stage and the python base"
    for parts in froms:
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", parts[1]), (
            "not pinned by digest (keep the tag for reading): " + " ".join(parts))
    # the container is Python 3.11 on purpose (no PEP 701 f-strings in this codebase)
    assert froms[-1][1].startswith("python:3.11-slim@sha256:"), froms[-1]
    # a `COPY --from=` naming an IMAGE would be an unpinned pull the check above never sees
    stages = {parts[3].lower() for parts in froms if len(parts) >= 4 and parts[2].upper() == "AS"}
    sources = re.findall(r"--from=(\S+)", "\n".join(_docker_code()))
    assert sources and set(sources) <= stages, (sources, stages)


def test_the_claude_cli_is_pinned_to_an_exact_version():
    """`npm install -g @anthropic-ai/claude-code` with no version is whatever npm serves the day
    the image builds, running as root with the autofill OAuth token in its environment."""
    code = "\n".join(_docker_code())
    installs = re.findall(r"npm install -g\s+([^&\n]+)", code)
    assert installs, "the Dockerfile no longer installs the Claude CLI"
    packages = [p for chunk in installs for p in chunk.split() if not p.startswith("-")]
    assert any(p.startswith("@anthropic-ai/claude-code@") for p in packages), packages
    loose = [p for p in packages if not re.fullmatch(r"(?:@[\w.-]+/)?[\w.-]+@\d+\.\d+\.\d+", p)]
    assert not loose, "npm packages without an exact version: " + ", ".join(loose)


def test_nothing_is_piped_from_the_network_into_a_shell():
    code = "\n".join(_docker_code())
    assert not re.search(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b", code), (
        "the Dockerfile runs a downloaded script again")
    assert "deb.nodesource.com" not in code
    # Node itself still arrives, from the pinned stage: the CLI cannot run without it.
    assert re.search(r"(?m)^COPY --from=\S+ /usr/local/bin/node /usr/local/bin/node\s*$", code)


def test_the_image_keeps_the_mime_table_the_frontend_is_served_from():
    """Debian's `media-types` package is what writes /etc/mime.types. The nodesource `nodejs`
    package used to pull it in (nodejs -> python3 -> libpython3.13-stdlib -> media-types), so it
    was never listed here. With Node copied from the node image it has to be asked for: without
    the file, Python's mimetypes (and so Starlette's StaticFiles) serves /shared.js as
    `application/javascript` with no charset instead of production's
    `text/javascript; charset=utf-8`, and .docx/.xlsx/.woff2/.webp/.md with no type at all."""
    code = "\n".join(_docker_code())
    packages = {p for chunk in re.findall(r"apt-get install\b([^&\n]+)", code)
                for p in chunk.split("#")[0].split() if not p.startswith("-")}
    assert "tini" in packages, "could not read the apt-get install lines: " + repr(sorted(packages))
    assert "media-types" in packages, (
        "media-types is no longer installed, so the image has no /etc/mime.types: "
        + repr(sorted(packages)))


def test_dependabot_moves_every_kind_of_pin():
    """A pin nobody bumps stops taking security fixes. The actions and the base images each
    need their ecosystem; the Claude CLI's RUN-line pin is bumped by hand (see the Dockerfile)."""
    updates = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))["updates"]
    ecosystems = {(u["package-ecosystem"], u["directory"]) for u in updates}
    assert {("github-actions", "/"), ("docker", "/")} <= ecosystems, ecosystems
    docker = next(u for u in updates if u["package-ecosystem"] == "docker")
    held = {i["dependency-name"]: set(i["update-types"]) for i in docker.get("ignore", [])}
    # digest bumps yes; a move off Python 3.11 is a decision, not a weekly PR
    assert "version-update:semver-minor" in held.get("python", set()), held
