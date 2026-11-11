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

The last part ("THE LOCKED-DOWN DEPLOY ACCOUNT") pins the 2026-11 change that took root off the
deploy: the workflow sends one request line to an account whose key can run only
deploy/remote-deploy.sh, and that program is EXECUTED here against stub docker/curl and real git
checkouts (the same approach as the BD CRM's deploy tests).
"""
import fnmatch
import hashlib
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
REMOTE = ROOT / "deploy" / "remote-deploy.sh"
INSTALL = ROOT / "deploy" / "install-deploy-account.sh"
RUNBOOK = ROOT / "deploy" / "README.md"
DEPLOY_BIN = "/usr/local/sbin/treadwell-tool-deploy"
# One key per environment, each forced to the program WITH its environment.
FORCED = {env: 'restrict,command="sudo -n %s %s"' % (DEPLOY_BIN, env) for env in ("staging", "main")}


def _remote_code():
    """deploy/remote-deploy.sh without its comment lines."""
    return "\n".join(ln for ln in REMOTE.read_text(encoding="utf-8").splitlines()
                     if not ln.strip().startswith("#"))


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


def test_staging_applies_the_schema_it_just_pulled():
    """The staging deploy feeds backend/staging/schema_pg.sql from the checkout into psql. It
    used to read /docker-entrypoint-initdb.d/01_schema.sql, a single-file bind mount that goes
    stale as soon as `git pull` replaces the file, so from 2026-09-25 every deploy re-applied an
    old schema and reported success (library_labor.favorite never arrived on 2026-09-30). The
    deploy runs on the box now (deploy/remote-deploy.sh); the executed tests below check the
    schema that reaches psql is the deployed commit's."""
    code = _remote_code()
    assert "-v ON_ERROR_STOP=1 < backend/staging/schema_pg.sql" in code, "staging no longer applies the pulled schema"
    for path in (DEPLOY, REMOTE):
        text = " ".join(ln.split("#", 1)[0] for ln in path.read_text(encoding="utf-8").splitlines())
        assert "/docker-entrypoint-initdb.d/01_schema.sql" not in text, (
            "staging applies the schema through the bind mount again, which serves a stale copy")


def test_no_deploy_step_builds_on_the_box():
    """THE rule. Both stacks live on the same VPS, so staging builds are just as capable
    of taking prod down as prod builds are."""
    # Comments stripped first: the prose above explains the outage using the very flag it
    # forbids, and each command carries a trailing `# NO --build`. Matching those would
    # make this test fail on its own documentation.
    for path in (DEPLOY, REMOTE):
        code = [ln.split("#", 1)[0] for ln in path.read_text(encoding="utf-8").splitlines()]
        # `docker builder prune` is cleanup, not a build
        offenders = [ln.strip() for ln in code
                     if "--build" in ln or re.search(r"\b(?:docker|compose) build\b", ln)]
        assert not offenders, ("%s still builds on the VPS: " % path.name + "; ".join(offenders))
    # what the box does instead: pull the exact image (by digest, at most PULL_TIMEOUT), then `up -d`
    code = _remote_code()
    assert 'timeout "$PULL_TIMEOUT" docker pull --quiet "$image"' in code
    assert "compose up -d || up_ok=0" in code


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


def test_the_box_deploys_by_digest_never_by_a_tag():
    """Review 2026-11-11: GHCR write access is per repository, not per branch, so a workflow on ANY
    branch could push its own image under `sha-<12 of the real main HEAD>` (or re-push it while the
    production job waits for its reviewer), and a box that pulls by tag would run it with the full
    production .env. A digest is the content and cannot be re-pointed: the build job publishes it,
    each request carries it, and the box pulls, runs and health-checks exactly `<repo>@<digest>`."""
    wf = _load(DEPLOY)
    build = wf["jobs"]["build"]
    push = next(s for s in build["steps"] if s.get("uses", "").startswith("docker/build-push-action@"))
    assert push.get("id") == "build"
    assert build["outputs"]["digest"] == "${{ steps.build.outputs.digest }}"
    for name, scripts in REQUESTS.items():
        for script in scripts:
            assert " ${{ github.sha }} ${{ needs.build.outputs.digest }}" in script, (name, script)
    # the provenance of that digest is recorded by this workflow (gh attestation verify checks it)
    attest = next(s for s in build["steps"] if s.get("uses", "").startswith("actions/attest-build-provenance@"))
    assert build["steps"].index(attest) > build["steps"].index(push)
    assert attest["with"] == {"subject-name": "${{ env.IMAGE }}",
                              "subject-digest": "${{ steps.build.outputs.digest }}", "push-to-registry": False}
    assert build["permissions"]["id-token"] == "write" and build["permissions"]["attestations"] == "write"
    code = _remote_code()
    assert 'local image="$REPO@$DIGEST"' in code, "the deploy names its image by digest"
    assert code.count('"$REPO@$DIGEST"') == 2, "deploy and pdf-smoke, nothing else"
    assert "(sha256:[0-9a-f]{64})" in code
    deploy = code[code.index("run_deploy() {"):code.index("download_smoke_tools() {")]
    for line in deploy.splitlines():
        if "docker pull" in line or "TW_IMAGE=" in line or 'healthy "' in line:
            assert ":sha-" not in line and "$version" not in line, line.strip()


def test_the_runner_needs_packages_write():
    """Push to GHCR fails with a permissions error that reads like an auth problem."""
    text = DEPLOY.read_text(encoding="utf-8")
    assert "packages: write" in text


def test_no_long_lived_registry_credential():
    """The built-in GITHUB_TOKEN is job-scoped and expires. A PAT in secrets would sit
    on the VPS's docker config after the first deploy. On the box the login goes into a
    throw-away DOCKER_CONFIG that the program deletes on exit, never root's ~/.docker."""
    text = DEPLOY.read_text(encoding="utf-8")
    assert "secrets.GITHUB_TOKEN" in text
    code = _remote_code()
    assert "DOCKER_CONFIG=$(mktemp -d)" in code and "export DOCKER_CONFIG" in code
    assert """trap 'rm -rf "$DOCKER_CONFIG"' EXIT""" in code, "the box keeps a registry login after deploying"
    assert code.index("export DOCKER_CONFIG") < code.index("docker login")
    assert "--password-stdin" in code and ".docker/config.json" not in code


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
    # `id-token` + `attestations`: the signed build-provenance attestation of the image's digest.
    ("deploy.yml", "build"): {"packages", "id-token", "attestations"},
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
    """Their token IS the registry login on the VPS: it rides in the request line. Trimmed below
    `packages: read`, the pull fails on the box and nothing here would say why."""
    wf = _load(DEPLOY)
    for name in ("staging", "production"):
        job = wf["jobs"][name]
        assert job["permissions"] == {"packages": "read"}, (name, job["permissions"])
        deploys = [s["with"]["script"] for s in _ssh_steps(job) if s["with"]["script"].startswith("deploy ")]
        assert len(deploys) == 1 and deploys[0].endswith(" ${{ secrets.GITHUB_TOKEN }}"), (name, deploys)


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


# ── THE LOCKED-DOWN DEPLOY ACCOUNT ────────────────────────────────────────────────────────
#
# Until 2026-11 both deploy jobs logged in as root (VPS_USER / VPS_SSH_KEY) and ran a shell script
# they sent along. Repository secrets reach a workflow run on ANY branch of this repository, so that
# key was a root shell on a box that hosts a dozen other sites. Now each job sends ONE request line
# to an account of the proposal tool's own, whose only key is forced to /usr/local/sbin/
# treadwell-tool-deploy: a root-owned copy of deploy/remote-deploy.sh, installed by
# deploy/install-deploy-account.sh with one sudoers rule. deploy/README.md is the runbook.

SHA = "0123456789abcdef0123456789abcdef01234567"
TOKEN = "ghs_" + "Zz09" * 9
# The job token's CURRENT shape, measured (masked) on the BD CRM's first real deploy on 2026-11-05:
# ~377 characters, `ghs_` + a segment + `_` + 36 + `.` + ~330.
LONG_TOKEN = "ghs_" + "Ab1Cd" + "_" + "E2f3" * 9 + "." + "G4h5" * 83
DIGEST = "sha256:" + "0123456789abcdef" * 4
REQUESTS = {
    "staging": ["deploy staging ${{ github.sha }} ${{ needs.build.outputs.digest }} ${{ secrets.GITHUB_TOKEN }}",
                "pdf-smoke staging ${{ github.sha }} ${{ needs.build.outputs.digest }}"],
    "production": ["deploy main ${{ github.sha }} ${{ needs.build.outputs.digest }} ${{ secrets.GITHUB_TOKEN }}"],
}


def _filled(script, token=TOKEN):
    return (script.replace("${{ github.sha }}", SHA).replace("${{ needs.build.outputs.digest }}", DIGEST)
            .replace("${{ secrets.GITHUB_TOKEN }}", token))


def _ssh_steps(job):
    return [s for s in job.get("steps", []) if s.get("uses", "").startswith("appleboy/ssh-action@")]


def test_each_ssh_step_sends_one_request_line_as_the_deploy_account():
    """No `envs`, no `env`, no shell script: the `script:` is the one line the box program matches.
    The account and key are the NEW secrets, so this change could not half-work on the old root key."""
    wf = _load(DEPLOY)
    for name, expected in REQUESTS.items():
        steps = _ssh_steps(wf["jobs"][name])
        assert [s["with"]["script"].strip() for s in steps] == expected, name
        for step in steps:
            assert set(step["with"]) == {"host", "username", "key", "port", "fingerprint",
                                         "command_timeout", "script"}, (name, sorted(step["with"]))
            assert step["with"]["host"] == "${{ secrets.VPS_HOST }}"
            assert step["with"]["username"] == "${{ secrets.VPS_DEPLOY_USER }}"
            assert step["with"]["key"] == "${{ secrets.VPS_DEPLOY_KEY }}"
            assert step["with"]["port"] == "${{ secrets.VPS_PORT || '22' }}"
            assert step["with"]["fingerprint"] == "${{ secrets.VPS_FINGERPRINT }}", "an unchecked host key gets the token"
            assert "\n" not in step["with"]["script"].strip(), "one line, never a script"
            assert "env" not in step, "nothing is exported into a shell on the box"
    text = DEPLOY.read_text(encoding="utf-8")
    for old in ("secrets.VPS_USER", "secrets.VPS_SSH_KEY", "script_stop", "envs:"):
        assert not re.search(re.escape(old) + r"(?!\w)", text), "the root-era %s is still in deploy.yml" % old


def test_production_still_waits_for_its_reviewer():
    wf = _load(DEPLOY)
    prod = wf["jobs"]["production"]
    assert prod["environment"] == "production"
    assert prod["needs"] == "build" and prod["if"] == "github.ref == 'refs/heads/main'"
    assert wf["jobs"]["staging"]["needs"] == "build"


def test_the_deploy_secrets_are_environment_secrets_with_a_key_per_environment():
    """Review 2026-11-11 (blocker): a REPOSITORY secret reaches a workflow run on any branch, so one
    repo-level deploy key let anything that can push a branch send `deploy main` and skip the
    production reviewer. The keys live in the environments (staging -> branch staging, Production
    -> branch main + reviewer), one key each, and nothing but the two environment-bound jobs reads
    them. GitHub's settings cannot be tested from here; the runbook that sets them can."""
    wf = _load(DEPLOY)
    for name, job in wf["jobs"].items():
        uses_deploy_secrets = "secrets.VPS_DEPLOY_" in str(job)
        if uses_deploy_secrets:
            assert job.get("environment") in ("staging", "production"), (
                "%s reads a deploy secret without an environment, so it would need a repository-level one" % name)
    assert "secrets.VPS_DEPLOY_" not in str(wf["jobs"]["build"])
    assert wf["jobs"]["staging"]["environment"] == "staging"
    runbook = RUNBOOK.read_text(encoding="utf-8")
    sets = [ln.strip() for ln in runbook.splitlines() if re.match(r"\s*gh secret set VPS_", ln)]
    assert sets, "the runbook no longer says how to set the deploy secrets"
    for line in sets:
        assert re.search(r"--env (staging|Production)\b", line), "a repository-level secret: " + line
    keys = {re.search(r"--env (\w+)", ln).group(1): ln.split("<")[-1].strip()
            for ln in sets if " VPS_DEPLOY_KEY " in ln}
    assert set(keys) == {"staging", "Production"}, keys
    assert keys["staging"] != keys["Production"], "one key for both environments"
    for name in ("VPS_DEPLOY_USER", "VPS_FINGERPRINT"):
        assert {re.search(r"--env (\w+)", ln).group(1) for ln in sets if " %s " % name in ln} == {"staging", "Production"}
    # the branch rules and how to check them are in the runbook too
    assert "Selected branches and tags" in runbook and "deployment-branch-policies" in runbook
    assert "after the `production` environment approval, as before" not in runbook


def test_an_empty_account_or_fingerprint_secret_stops_the_deploy_before_ssh():
    """An empty fingerprint would make the SSH action accept ANY host key, so a spoofed endpoint
    could take the request and its registry token and answer "healthy"."""
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to execute the check with")
    wf = _load(DEPLOY)
    for name in REQUESTS:
        steps = wf["jobs"][name]["steps"]
        check = next(s for s in steps if "VPS_FINGERPRINT" in str(s.get("env", {})))
        assert steps.index(check) < steps.index(_ssh_steps(wf["jobs"][name])[0]), name
        assert check["env"] == {"VPS_DEPLOY_USER": "${{ secrets.VPS_DEPLOY_USER }}",
                                "VPS_FINGERPRINT": "${{ secrets.VPS_FINGERPRINT }}"}, "never the key itself"

        def rc(user, fingerprint):
            env = {**os.environ, "VPS_DEPLOY_USER": user, "VPS_FINGERPRINT": fingerprint}
            return subprocess.run([bash, "-c", check["run"]], capture_output=True, text=True,
                                  timeout=30, env=env).returncode
        assert rc("tooldeploy", "") != 0
        assert rc("", "SHA256:" + "A" * 43) != 0
        assert rc("tooldeploy", "SHA256:" + "A" * 43) == 0


def _patterns():
    text = REMOTE.read_text(encoding="utf-8")
    found = {name: re.search(r"^%s='([^']+)'$" % name, text, re.M) for name in ("DEPLOY_RE", "SMOKE_RE")}
    assert all(found.values()), found
    return {name: re.compile(m.group(1)) for name, m in found.items()}


def _matches(line):
    return [name for name, rx in _patterns().items() if rx.fullmatch(line)]


def test_the_request_patterns_match_what_the_workflow_sends_and_nothing_else():
    for scripts in REQUESTS.values():
        for script in scripts:
            for token in (TOKEN, LONG_TOKEN):
                line = _filled(script, token)
                assert len(_matches(line)) == 1, line[:60]
    D = DIGEST
    bad = [
        "deploy Staging %s %s %s" % (SHA, D, TOKEN), "deploy feature %s %s %s" % (SHA, D, TOKEN),
        "deploy staging %s %s %s" % (SHA[:12], D, TOKEN), "deploy staging %s %s %s; rm -rf /" % (SHA, D, TOKEN),
        "deploy staging $(id) %s %s" % (D, TOKEN), "deploy staging %s %s %s extra" % (SHA, D, TOKEN),
        "deploy staging %s %s" % (SHA, D), "deploy staging %s %s not-a-token" % (SHA, D),
        "pdf-smoke main %s %s" % (SHA, D), "pdf-smoke staging %s %s %s" % (SHA, D, TOKEN), "pdf-smoke staging $(id)",
        "bash -s", "", "deploy  staging %s %s %s" % (SHA, D, TOKEN),
        # the image must be a digest: never a tag, a short or upper-case digest, or missing
        "deploy staging %s %s" % (SHA, TOKEN), "pdf-smoke staging %s" % SHA,
        "deploy staging %s sha-%s %s" % (SHA, SHA[:12], TOKEN), "deploy staging %s sha256:%s %s" % (SHA, "ab" * 20, TOKEN),
        "deploy staging %s %s %s" % (SHA, D.upper(), TOKEN), "deploy staging %s %s:prod %s" % (SHA, D, TOKEN),
        "deploy staging %s %s@%s %s" % (SHA, IMAGE, D, TOKEN), "pdf-smoke staging %s sha256:%s" % (SHA, "0" * 63),
    ]
    bad += ["deploy staging %s %s %s" % (SHA, D, LONG_TOKEN + tail)
            for tail in (" x", ";id", "$(id)", "`id`", "'", '"', "|sh", "&&id")]
    for line in bad:
        assert not _matches(line), line[:80]


def test_the_request_is_matched_and_never_run():
    code = _remote_code()
    assert 'done <<< "${SSH_ORIGINAL_COMMAND:-}"' in code
    assert code.count("SSH_ORIGINAL_COMMAND") == 1, "the request is read in exactly one place"
    assert not re.search(r"\beval\b", code), "nothing is ever evaluated"
    assert "source " not in code and not re.search(r"(?m)^\s*\.\s", code)
    # the only `sh -c` is the fixed PDF smoke script, inside a throw-away container
    shells = [ln.strip() for ln in code.splitlines() if re.search(r"\b(?:ba)?sh -c\b", ln)]
    assert shells == ['sh -c "$smoke"'], shells
    assert "smoke=$(cat <<'SMOKE'" in code, "the smoke script is a quoted here-document, never expanded"
    assert '[ "${#TOKEN}" -le 2000 ]' in code
    assert "printf '%s' \"$TOKEN\" | docker login ghcr.io -u HDLC01 --password-stdin" in code
    assert code.count("$TOKEN") == 1, "the token goes nowhere but docker login"


def test_the_forced_command_is_the_same_everywhere():
    """authorized_keys (written by the install script), the program's header and the runbook agree,
    and the workflow names the program it reaches."""
    install = INSTALL.read_text(encoding="utf-8")
    assert """forced() { printf 'restrict,command="sudo -n %s %s"' "$DEPLOY_BIN" "$1"; }""" in install
    assert 'ENVIRONMENTS="staging main"' in install
    assert "DEPLOY_BIN=%s" % DEPLOY_BIN in install
    for forced in FORCED.values():
        assert forced in REMOTE.read_text(encoding="utf-8")
        assert forced in RUNBOOK.read_text(encoding="utf-8")
    assert DEPLOY_BIN in DEPLOY.read_text(encoding="utf-8")
    assert 'command="sudo -n %s"' % DEPLOY_BIN not in RUNBOOK.read_text(encoding="utf-8"), "the old single-key line"


def _install_code():
    return "\n".join(ln for ln in INSTALL.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))


def test_install_restricts_the_deploy_account_to_one_program():
    code = _install_code()
    assert 'install -o root -g root -m 0755 "$SOURCE" "$DEPLOY_BIN"' in code
    assert 'SOURCE="$HERE/remote-deploy.sh"' in code
    assert 'Defaults:$ACCOUNT env_keep += "SSH_ORIGINAL_COMMAND"' in code
    assert '$ACCOUNT ALL=(root) NOPASSWD: $DEPLOY_BIN staging, $DEPLOY_BIN main' in code, \
        "exactly these two argument lists, no wildcard"
    assert "NOPASSWD: $DEPLOY_BIN *" not in code and 'NOPASSWD: $DEPLOY_BIN ""' not in code
    assert 'visudo -cf "$rule"' in code and 'install -o root -g root -m 0440 "$rule" "$SUDOERS"' in code
    assert "SUDOERS=/etc/sudoers.d/treadwell-tool-deploy" in code
    assert code.index('visudo -cf "$rule"') < code.index('install -o root -g root -m 0440 "$rule" "$SUDOERS"')
    assert "visudo -c >/dev/null" in code, "the whole sudo configuration is re-checked with the rule in it"
    assert '*" docker "*) stop' in code, "a deploy account in the docker group is root"
    assert '*" sudo "*|*" admin "*|*" wheel "*|*" root "*)' in code
    assert 'install -o "$ACCOUNT" -g "$ACCOUNT" -m 0600 "$new" "$keys"' in code
    assert code.index('( check_keys "$new" )') < code.index('-m 0600 "$new" "$keys"'), "checked before it is installed"
    assert 'check_keys "$keys"' in code, "any other key in that account stops the script"
    assert "adduser --disabled-password" in code and "ACCOUNT=tooldeploy" in code


def test_install_never_touches_the_firewall_packages_or_containers():
    """SSH moved off 22 on 2026-09-28; deploy/install-vps.sh (the original whole-box setup) still
    runs `ufw allow 22/tcp`, which re-opens it. This script must not copy that, nor do anything
    beyond the account, the program, sudo and the key."""
    code = _install_code()
    for word in ("ufw", "allow 22", "iptables", "apt-get", "apt ", "docker compose", "docker run",
                 "systemctl restart", "--build", "curl -"):
        assert word not in code, word
    assert "sshd_config" not in code, "sshd is only read (sshd -T), never edited"


def _run_install(*args, **env):
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to run the install script with")
    return subprocess.run([bash, INSTALL.as_posix(), *args], capture_output=True, text=True, timeout=60,
                          env={**os.environ, **env})


def test_install_prints_the_sudoers_rule_it_installs(tmp_path):
    proc = _run_install("--print-sudoers")
    assert proc.returncode == 0, proc.stderr
    rule = [ln for ln in proc.stdout.splitlines() if ln and not ln.startswith("#")]
    assert rule == ['Defaults:tooldeploy env_keep += "SSH_ORIGINAL_COMMAND"',
                    'tooldeploy ALL=(root) NOPASSWD: {0} staging, {0} main'.format(DEPLOY_BIN)]
    other = _run_install("--print-sudoers", "--account", "tw-deploy")
    assert "tw-deploy ALL=(root) NOPASSWD: {0} staging, {0} main".format(DEPLOY_BIN) in other.stdout
    visudo = shutil.which("visudo")
    if visudo:
        rule_file = tmp_path / "tool-deploy-sudoers"
        rule_file.write_text(proc.stdout, encoding="utf-8")
        check = subprocess.run([visudo, "-cf", str(rule_file)], capture_output=True, text=True)
        assert check.returncode == 0, check.stdout + check.stderr


def test_install_prints_the_forced_key_line_and_refuses_anything_else(tmp_path):
    pub = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample tool-deploy"
    (tmp_path / "k.pub").write_text(pub + "\n", encoding="utf-8")
    for env in ("staging", "main"):
        proc = _run_install("--print-key-line", env, (tmp_path / "k.pub").as_posix())
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == FORCED[env] + " " + pub
    for env in ("prod", "", "staging main", "feature"):
        assert _run_install("--print-key-line", env, (tmp_path / "k.pub").as_posix()).returncode == 1, env
    (tmp_path / "k").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n",
                                encoding="utf-8")
    private = _run_install("--print-key-line", "staging", (tmp_path / "k").as_posix())
    assert private.returncode == 1 and "PRIVATE key" in private.stderr
    (tmp_path / "rsa.pub").write_text("ssh-rsa AAAAB3Nza tool-deploy\n", encoding="utf-8")
    assert _run_install("--print-key-line", "main", (tmp_path / "rsa.pub").as_posix()).returncode == 1
    (tmp_path / "evil.pub").write_text(pub + ' ,command="sh"\n', encoding="utf-8")
    assert _run_install("--print-key-line", "main", (tmp_path / "evil.pub").as_posix()).returncode == 1
    gone = _run_install("--deploy-key", (tmp_path / "k.pub").as_posix())
    assert gone.returncode == 1 and "--staging-key" in gone.stderr, "the single shared key is gone"


def test_install_accepts_only_one_distinct_forced_key_per_environment(tmp_path):
    """Review 2026-11-11: one key and one forced command for both environments let any holder of the
    staging copy (no reviewer) deploy production, or roll it back. Each key is forced to its own
    environment, the two keys must differ, and nothing else may sit in the account's keys."""
    a = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIStagingStagingStagingStagingStagingStag tool-deploy-staging"
    b = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMainMainMainMainMainMainMainMainMainMain tool-deploy-main"

    def check(*lines):
        path = tmp_path / "authorized_keys"
        path.write_text("".join(ln + "\n" for ln in lines), encoding="utf-8", newline="\n")
        return _run_install("--check-keys", path.as_posix())

    good = check("# the deploy keys", FORCED["staging"] + " " + a, FORCED["main"] + " " + b)
    assert good.returncode == 0, good.stderr
    assert check(FORCED["main"] + " " + b).returncode == 0, "one environment alone is allowed (with a warning on install)"
    same = check(FORCED["staging"] + " " + a, FORCED["main"] + " " + a)
    assert same.returncode == 1 and "ONE key for both environments" in same.stderr
    for bad in ([FORCED["staging"] + " " + a, FORCED["staging"] + " " + b],          # two for staging
                ['restrict,command="sudo -n %s" %s' % (DEPLOY_BIN, a)],             # the old single-key line
                [a],                                                                # unforced: a shell
                [a + " " + FORCED["staging"]],                                      # forced only in a comment
                ['restrict,command="sudo -n %s staging main" %s' % (DEPLOY_BIN, a)],
                ['restrict,command="sudo -n %s prod" %s' % (DEPLOY_BIN, a)]):
        proc = check(*bad)
        assert proc.returncode == 1 and "STOP:" in proc.stderr, bad
    for bad in ("root", "Bad Name", "x;id"):
        proc = _run_install("--print-sudoers", "--account", bad)
        assert proc.returncode == 1 and "STOP:" in proc.stderr, bad


def test_install_refuses_to_change_anything_unless_root():
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("running as root: the refusal cannot be observed")
    proc = _run_install()
    assert proc.returncode == 1 and "run this as root" in proc.stderr


def test_housekeeping_keeps_three_and_keeps_the_box_from_filling_up():
    """The box runs ~11 other apps' containers, and other apps still BUILD on it (roadmap, news
    feed, assess) or `docker load` (the portal). The old steps ran a bare `docker image prune -f`
    and `docker builder prune -f` on every deploy, which made this pipeline the box's only disk
    cleaner: build cache had grown to ~15GB on 2026-08-11 and took staging and production down.
    Review 2026-11-11: removing the builder prune left the box with no cleanup at all. Now: this
    repository's sha images (three newest kept), a prune limited to this image's label, and a
    box-wide prune of dangling images and build cache OLDER THAN A WEEK. Never -a / system /
    volume / network prunes."""
    code = _remote_code()
    assert "REPO=ghcr.io/hdlc01/treadwell-proposal-tool" in code
    assert 'docker images "$REPO"' in code and 'grep "^$REPO:sha-"' in code and "head -3" in code
    for path in (DEPLOY, REMOTE):
        text = "\n".join(ln.split("#", 1)[0] for ln in path.read_text(encoding="utf-8").splitlines())
        for word in ("prune -a", "prune --all", "system prune", "volume prune", "network prune"):
            assert word not in text, (path.name, word)
    prunes = [ln.strip() for ln in code.splitlines() if "prune" in ln]
    assert prunes == [
        'docker image prune -f --filter "label=org.opencontainers.image.title=treadwell-proposal-tool" >/dev/null 2>&1 || true',
        'docker image prune -f --filter "until=168h" >/dev/null 2>&1 || true',
        'docker builder prune -f --filter "until=168h" >/dev/null 2>&1 || true',
    ], prunes
    # an image a container still runs is kept even when it is not among the three newest: compared
    # by image ID, because a container started by digest names its image `<repo>@sha256:...`
    assert "xargs -r docker inspect -f '{{.Image}}'" in code and "docker image inspect -f '{{.Id}}' \"$img\"" in code
    assert re.search(r'(?m)^LABEL org\.opencontainers\.image\.title="treadwell-proposal-tool"\s*$',
                     DOCKERFILE.read_text(encoding="utf-8"))
    assert "df -h /" in code
    deploy = code[code.index("run_deploy() {"):]
    assert deploy.index('healthy "$image"') < deploy.index("housekeeping"), "housekeeping only after a healthy deploy"


def _default(name):
    m = re.search(r'^%s="\$\{TOOL_\w+:-([^}]+)\}"$' % name, REMOTE.read_text(encoding="utf-8"), re.M)
    assert m, name
    return m.group(1)


def test_one_deploy_at_a_time_and_the_checkout_stays_on_its_branch():
    code = _remote_code()
    # Review 2026-11-11: /run/lock (and /tmp) are world-writable with the sticky bit, so any local
    # account could create the lock file first (protected_regular then denies root's open) or hold
    # the lock forever. The lock lives where only root can create files.
    lock = _default("LOCK")
    assert lock == "/run/treadwell-tool-deploy.lock", lock
    assert not lock.startswith(("/run/lock/", "/tmp/", "/var/tmp/", "/dev/shm/")), lock
    assert 'flock -w "$LOCK_WAIT" 9' in code
    main = code[code.index("main() {"):]
    assert main.index("take_lock") < main.index("run_deploy") and main.index("take_lock") < main.index("run_pdf_smoke")
    # never detached: a fast-forward, or `reset --keep` back to an older commit of the branch
    assert "--detach" not in code and not re.search(r"git_in checkout\b", code)
    assert 'git_in merge --ff-only --quiet "$1"' in code and 'git_in reset --quiet --keep "$1"' in code
    assert 'git_in merge-base --is-ancestor "$COMMIT" "origin/$BRANCH" || refuse' in code


# ── deploy/remote-deploy.sh, EXECUTED against stub docker / curl / flock and real git ──────

_DOCKER_STUB = r"""#!/usr/bin/env bash
# A stand-in for docker: logs every call; a container's running image lives in running.<name>.
printf '%s|TW_IMAGE=%s|DOCKER_CONFIG=%s\n' "$*" "${TW_IMAGE:-}" "${DOCKER_CONFIG:-}" >> "$STUB/docker.log"
case "$1" in
  login)
    cat > "$STUB/login.stdin"
    if [ -n "${DOCKER_CONFIG:-}" ] && [ -d "$DOCKER_CONFIG" ]; then echo "$DOCKER_CONFIG" > "$STUB/login.config"; fi ;;
  pull) [ ! -f "$STUB/pull.fails" ] || exit 1; echo "$3" >> "$STUB/pulled" ;;
  inspect) if [ -f "$STUB/running.$4" ]; then cat "$STUB/running.$4"; else exit 1; fi ;;
  image) if [ "$2" = inspect ]; then grep -qxF "$3" "$STUB/pulled" 2>/dev/null || exit 1; fi ;;
  run)
    case "$*" in
      *" pip download "*) [ ! -f "$STUB/download.fails" ] || exit 1 ;;
      *) [ ! -f "$STUB/smoke.fails" ] || exit 1 ;;
    esac ;;
  compose)
    shift
    file=docker-compose.yml
    if [ "$1" = -f ]; then file="$2"; shift 2; fi
    container=treadwell-proposal-tool
    if [ "$file" = docker-compose.staging.yml ]; then container=treadwell-staging; fi
    case "$*" in
      "up -d")
        [ ! -f "$STUB/up.fails" ] || exit 1
        # up.stale: `up` "succeeds" but leaves the old container serving (only the rollback's
        # `up`, to the image already running, changes nothing either way)
        if [ -f "$STUB/up.stale" ] && [ -f "$STUB/running.$container" ]; then exit 0; fi
        printf '%s\n' "$TW_IMAGE" > "$STUB/running.$container" ;;
      *pg_isready*) [ ! -f "$STUB/db.down" ] || exit 1 ;;
      *" -c "*) echo "$*" >> "$STUB/notify"; [ ! -f "$STUB/notify.fails" ] || exit 1 ;;
      *psql*) cat > "$STUB/schema.in" ;;
    esac ;;
esac
exit 0
"""

_CURL_STUB = r"""#!/usr/bin/env bash
# A stand-in for curl on /healthz: healthy unless the container's image is listed as broken.
url="${@: -1}"
case "$url" in *:8889/*) c=treadwell-staging ;; *) c=treadwell-proposal-tool ;; esac
img=$(cat "$STUB/running.$c" 2>/dev/null || true)
[ -n "$img" ] || exit 7
if [ -f "$STUB/broken" ] && grep -qxF "$img" "$STUB/broken"; then exit 22; fi
echo '{"ok": true}'
"""

_FLOCK_STUB = r"""#!/usr/bin/env bash
echo "$*" >> "$STUB/flock.log"
exit 0
"""


def _git(cwd, *args):
    # core.autocrlf off, as on the Linux box: a Windows dev PC's global `true` would turn the
    # clone's files into CRLF copies of what was committed.
    return subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=60, check=True).stdout.strip()


def _digest(commit):
    """A stand-in for the build job's digest of `commit`'s image."""
    return "sha256:" + hashlib.sha256(commit.encode()).hexdigest()


def _image(commit):
    """What the box pulls and runs: the image BY DIGEST."""
    return "%s@%s" % (IMAGE, _digest(commit))


def _deploy(branch, commit, token=None):
    return "deploy %s %s %s %s" % (branch, commit, _digest(commit), token or TOKEN)


def _smoke(commit):
    return "pdf-smoke staging %s %s" % (commit, _digest(commit))


@pytest.fixture
def box(tmp_path):
    """An origin with `staging` and `main` (commits old -> new) and a `feature` commit on neither,
    the box's two checkouts (staging on `staging`, prod on `main`, both at old), the env files, the
    font folder, and stub docker / curl / flock on PATH."""
    bash = _bash()
    if bash is None or shutil.which("git") is None:
        pytest.skip("no bash or git to run deploy/remote-deploy.sh with")
    work, origin, staging, prod, fonts, stub = (tmp_path / n for n in
                                                 ("work", "origin.git", "staging", "prod", "fonts", "stub"))
    for d in (work, fonts, stub):
        d.mkdir()
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "init", "-q", str(work))
    for k, v in (("user.email", "ci@example.com"), ("user.name", "ci"), ("commit.gpgsign", "false"),
                 ("core.autocrlf", "false")):
        _git(work, "config", k, v)

    def write(rel, body):
        path = work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")

    (work / "deploy").mkdir()
    shutil.copy(REMOTE, work / "deploy" / "remote-deploy.sh")
    write("docker-compose.yml", "# v1\n")
    write("docker-compose.staging.yml", "# v1\n")
    write("backend/staging/schema_pg.sql", "-- schema v1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "one")
    _git(work, "branch", "-M", "staging")
    old = _git(work, "rev-parse", "HEAD")
    write("docker-compose.yml", "# v2\n")
    write("docker-compose.staging.yml", "# v2\n")
    write("backend/staging/schema_pg.sql", "-- schema v2\n")
    _git(work, "commit", "-q", "-am", "two")
    new = _git(work, "rev-parse", "HEAD")
    _git(work, "branch", "main")
    _git(work, "checkout", "-q", "-b", "feature")
    write("docker-compose.yml", "# not reviewed\n")
    _git(work, "commit", "-q", "-am", "feature")
    feature = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "-q", str(origin), "staging", "main", "feature")
    for path, branch, env_file in ((staging, "staging", ".env.staging"), (prod, "main", ".env")):
        _git(tmp_path, "clone", "-q", "--config", "core.autocrlf=false", "--branch", branch, str(origin), str(path))
        _git(path, "reset", "-q", "--hard", old)          # on its branch, one commit behind
        (path / env_file).write_text("X=1\n", encoding="utf-8", newline="\n")
    for name in ("Zetta Serif-Book.otf", "Zetta Serif.otf"):
        (fonts / name).write_bytes(b"OTTO font")
    for name, body in (("docker", _DOCKER_STUB), ("curl", _CURL_STUB), ("flock", _FLOCK_STUB)):
        (stub / name).write_text(body, encoding="utf-8", newline="\n")
        (stub / name).chmod(0o755)

    def environ(request, extra):
        return {**os.environ, "SSH_ORIGINAL_COMMAND": request,
                "TOOL_STAGING_DIR": staging.as_posix(), "TOOL_PROD_DIR": prod.as_posix(),
                "TOOL_FONT_DIR": fonts.as_posix(), "TOOL_DEPLOY_LOCK": (tmp_path / "deploy.lock").as_posix(),
                "TOOL_DEPLOY_LOG": (tmp_path / "deploy.log").as_posix(),
                "TOOL_HEALTH_TRIES": "2", "TOOL_HEALTH_PAUSE": "0", "STUB": stub.as_posix(),
                "PATH": str(stub) + os.pathsep + os.environ.get("PATH", ""), **extra}

    def key_args(request, key):
        # The forced command's argument: the environment of the key that sent the request. By
        # default the request's own (the normal case); key=None runs with no argument at all.
        if key == "auto":
            key = "main" if request.lstrip().startswith("deploy main") else "staging"
        return [] if key is None else ([key] if isinstance(key, str) else list(key))

    def run(request, key="auto", **extra):
        proc = subprocess.run([bash, REMOTE.as_posix(), *key_args(request, key)], capture_output=True,
                              text=True, timeout=120, env=environ(request, extra))
        log = (stub / "docker.log").read_text(encoding="utf-8") if (stub / "docker.log").exists() else ""
        return proc, log

    def popen(request, key="auto", **extra):
        return subprocess.Popen([bash, REMOTE.as_posix(), *key_args(request, key)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=environ(request, extra))

    return {"run": run, "popen": popen, "staging": staging, "prod": prod, "fonts": fonts, "stub": stub,
            "log": tmp_path / "deploy.log", "old": old, "new": new, "feature": feature}


def _running(box, container):
    path = box["stub"] / ("running." + container)
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _set_running(box, container, image):
    (box["stub"] / ("running." + container)).write_text(image + "\n", encoding="utf-8")


def _where(checkout):
    """(commit, branch) of a box checkout; branch is "" when HEAD is detached."""
    head = _git(checkout, "rev-parse", "HEAD")
    branch = subprocess.run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=str(checkout),
                            capture_output=True, text=True).stdout.strip()
    return head, branch


def _calls(log):
    return [ln.split("|")[0] for ln in log.splitlines()]


@pytest.mark.parametrize("request_line", [
    "",
    "deploy staging 0123 x",
    "deploy feature %s %s %s" % (SHA, DIGEST, TOKEN),
    "deploy staging %s %s %s; touch /tmp/pwned" % (SHA, DIGEST, TOKEN),
    "deploy staging %s %s %s\ndeploy main %s %s %s" % (SHA, DIGEST, TOKEN, SHA, DIGEST, TOKEN),
    "deploy staging %s %s %s\npdf-smoke staging %s %s" % (SHA, DIGEST, TOKEN, SHA, DIGEST),
    "pdf-smoke main %s %s" % (SHA, DIGEST),
    "deploy staging %s %s" % (SHA, TOKEN),
    "deploy staging %s %s:sha-%s %s" % (SHA, IMAGE, SHA[:12], TOKEN),
    "bash -i",
])
def test_a_malformed_request_is_refused_before_anything_runs(box, request_line):
    proc, log = box["run"](request_line)
    assert proc.returncode == 2, proc.stderr
    assert "refusing: the request must be exactly one line" in proc.stderr
    assert log == "", "docker ran for a refused request"
    assert not (box["stub"] / "flock.log").exists(), "not even the lock is taken"


def test_a_commit_that_is_not_on_the_branch_is_refused(box):
    proc, log = box["run"](_deploy("staging", box["feature"]))
    assert proc.returncode == 2 and "is not on staging" in proc.stderr, proc.stderr
    assert log == ""
    assert _where(box["staging"]) == (box["old"], "staging"), "the checkout moved"


def test_a_staging_deploy_pulls_applies_the_schema_and_stays_on_its_branch(box):
    old_image, new_image = _image(box["old"]), _image(box["new"])
    _set_running(box, "treadwell-staging", old_image)
    # Extra lines an SSH action may add around the request are ignored, never run.
    proc, log = box["run"]("export FOO=bar\n%s\n" % _deploy("staging", box["new"]))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = _calls(log)
    order = ["login ghcr.io -u HDLC01 --password-stdin", "pull --quiet " + new_image,
             "compose -f docker-compose.staging.yml up -d db",
             "compose -f docker-compose.staging.yml exec -T db pg_isready -U postgres -d treadwell",
             "compose -f docker-compose.staging.yml exec -T db psql -U postgres -d treadwell -v ON_ERROR_STOP=1",
             "compose -f docker-compose.staging.yml up -d",
             "tag %s %s:sha-%s" % (new_image, IMAGE, box["new"][:12]),
             "tag %s %s:staging" % (new_image, IMAGE)]
    assert not any(c.startswith("pull ") and ":sha-" in c for c in calls), "never a pull by tag"
    assert [c for c in order if c not in calls] == [], calls
    assert [calls.index(c) for c in order] == sorted(calls.index(c) for c in order), calls
    assert not any(re.search(r"\bbuild\b|--build", c) for c in calls), calls
    up = next(ln for ln in log.splitlines() if ln.startswith("compose -f docker-compose.staging.yml up -d|"))
    assert "TW_IMAGE=" + new_image + "|" in up
    assert _running(box, "treadwell-staging") == new_image and "staging healthy on " + new_image in proc.stdout
    # PostgREST told to reload, and the schema that reached psql is the DEPLOYED commit's
    assert "notify pgrst" in (box["stub"] / "notify").read_text(encoding="utf-8")
    assert (box["stub"] / "schema.in").read_text(encoding="utf-8") == "-- schema v2\n"
    # exactly the dispatched commit, and still ON the branch: `git pull --ff-only` keeps working
    assert _where(box["staging"]) == (box["new"], "staging")
    assert _where(box["prod"]) == (box["old"], "main"), "production's checkout was not touched"
    # the token went in on stdin, into a DOCKER_CONFIG that existed for this run only
    assert (box["stub"] / "login.stdin").read_text(encoding="utf-8") == TOKEN
    config_dir = (box["stub"] / "login.config").read_text(encoding="utf-8").strip()
    assert config_dir and "/.docker" not in config_dir
    after_login = log[log.index("login ghcr.io"):].splitlines()
    assert all("DOCKER_CONFIG=" + config_dir in ln for ln in after_login), "one config for the whole run"
    assert not pathlib.Path(config_dir).exists(), "the throw-away DOCKER_CONFIG is removed"
    assert TOKEN not in proc.stdout + proc.stderr
    assert "-w 480 9" in (box["stub"] / "flock.log").read_text(encoding="utf-8"), "the box lock is taken"
    # the run is also in the root-only log, so a dropped session still leaves a record
    assert "staging healthy on " + new_image in box["log"].read_text(encoding="utf-8")
    assert TOKEN not in box["log"].read_text(encoding="utf-8")


def test_a_production_deploy_uses_its_own_checkout_compose_and_tag(box):
    new_image = _image(box["new"])
    _set_running(box, "treadwell-proposal-tool", _image(box["old"]))
    proc, log = box["run"](_deploy("main", box["new"], LONG_TOKEN))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = _calls(log)
    assert "compose -f docker-compose.yml up -d" in calls
    assert not any("staging" in c or "pg_isready" in c or "psql" in c for c in calls), calls
    assert "tag %s %s:prod" % (new_image, IMAGE) in calls
    assert _running(box, "treadwell-proposal-tool") == new_image and "prod healthy on" in proc.stdout
    assert _where(box["prod"]) == (box["new"], "main")
    assert _where(box["staging"]) == (box["old"], "staging")


def test_a_failed_health_check_rolls_back_to_the_previous_image_and_checkout(box):
    old_image, new_image = _image(box["old"]), _image(box["new"])
    _set_running(box, "treadwell-proposal-tool", old_image)
    (box["stub"] / "broken").write_text(new_image + "\n", encoding="utf-8")
    proc, log = box["run"](_deploy("main", box["new"]))
    assert proc.returncode == 1
    assert "prod post-deploy healthcheck failed" in proc.stdout + proc.stderr
    ups = [ln for ln in log.splitlines() if ln.startswith("compose -f docker-compose.yml up -d|")]
    assert len(ups) == 2 and "TW_IMAGE=" + old_image + "|" in ups[1], ups
    assert _running(box, "treadwell-proposal-tool") == old_image and "rolled back" in proc.stdout
    assert _where(box["prod"]) == (box["old"], "main"), "the previous checkout is back, on its branch"
    assert " tag " not in " " + " ".join(_calls(log)) and "rmi" not in log, "no re-tag, no housekeeping"


def test_a_failing_up_rolls_back_too(box):
    old_image = _image(box["old"])
    _set_running(box, "treadwell-staging", old_image)
    (box["stub"] / "up.fails").write_text("", encoding="utf-8")
    proc, log = box["run"](_deploy("staging", box["new"]))
    assert proc.returncode == 1 and "post-deploy healthcheck failed" in proc.stdout + proc.stderr
    assert _where(box["staging"]) == (box["old"], "staging")


def test_a_failed_first_deploy_says_there_is_nothing_to_roll_back_to(box):
    (box["stub"] / "broken").write_text(_image(box["new"]) + "\n", encoding="utf-8")
    proc, log = box["run"](_deploy("staging", box["new"]))
    assert proc.returncode == 1 and "no previous container" in proc.stdout + proc.stderr
    assert len([ln for ln in log.splitlines() if ln.startswith("compose -f docker-compose.staging.yml up -d|")]) == 1


def test_a_failed_pull_changes_nothing(box):
    (box["stub"] / "pull.fails").write_text("", encoding="utf-8")
    proc, log = box["run"](_deploy("staging", box["new"]))
    assert proc.returncode != 0
    assert "compose" not in log
    assert _where(box["staging"]) == (box["old"], "staging")


def test_a_staging_database_that_never_answers_puts_the_checkout_back(box):
    _set_running(box, "treadwell-staging", _image(box["old"]))
    (box["stub"] / "db.down").write_text("", encoding="utf-8")
    proc, log = box["run"](_deploy("staging", box["new"]))
    assert proc.returncode == 1 and "staging database" in proc.stderr
    assert "compose -f docker-compose.staging.yml up -d" not in _calls(log), "the app was not restarted"
    assert _where(box["staging"]) == (box["old"], "staging")


def test_a_missing_font_stops_the_deploy_before_anything_changes(box):
    for f in box["fonts"].iterdir():
        f.unlink()
    proc, log = box["run"](_deploy("staging", box["new"]))
    assert proc.returncode == 1 and "Dropbox" in proc.stdout
    assert log == "" and _where(box["staging"]) == (box["old"], "staging")


def test_a_checkout_off_its_branch_or_ahead_of_github_is_refused(box):
    _git(box["prod"], "checkout", "-q", "--detach", box["old"])
    proc, log = box["run"](_deploy("main", box["new"]))
    assert proc.returncode == 1 and "not main" in proc.stderr and log == ""
    _git(box["prod"], "checkout", "-q", "main")
    (box["prod"] / "local.txt").write_text("x\n", encoding="utf-8")
    _git(box["prod"], "add", "local.txt")
    _git(box["prod"], "-c", "user.email=ci@example.com", "-c", "user.name=ci", "-c", "commit.gpgsign=false",
         "commit", "-q", "-m", "made on the box")
    local = _git(box["prod"], "rev-parse", "HEAD")
    proc, log = box["run"](_deploy("main", box["new"]))
    assert proc.returncode == 1 and "not on origin/main" in proc.stderr and log == ""
    assert _where(box["prod"]) == (local, "main"), "the box's own commit is never thrown away"


def test_re_deploying_an_older_commit_moves_back_and_stays_on_the_branch(box):
    _set_running(box, "treadwell-staging", _image(box["new"]))
    _git(box["staging"], "merge", "-q", "--ff-only", box["new"])
    proc, _ = box["run"](_deploy("staging", box["old"]))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _where(box["staging"]) == (box["old"], "staging")
    assert _running(box, "treadwell-staging") == _image(box["old"])


def test_production_only_moves_forward(box):
    """Review 2026-11-11: the program accepted `deploy main <any older commit of main>` and
    `reset --keep` production back to it (say, to before a security fix), and its tag went with it.
    Production pairs with the shared production database, so going back is a person's decision,
    done by hand (deploy/README.md, Roll back); a request is refused before anything changes."""
    _set_running(box, "treadwell-proposal-tool", _image(box["new"]))
    _git(box["prod"], "merge", "-q", "--ff-only", box["new"])
    proc, log = box["run"](_deploy("main", box["old"]))
    assert proc.returncode == 2 and "production only moves forward" in proc.stderr, proc.stdout + proc.stderr
    assert log == "", "nothing was pulled or restarted"
    assert _where(box["prod"]) == (box["new"], "main")
    assert _running(box, "treadwell-proposal-tool") == _image(box["new"])
    proc, _ = box["run"](_deploy("main", box["new"]))         # the same commit again is fine
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("key, request_of", [
    ("staging", lambda b: _deploy("main", b["new"])),    # the staging key asks for production
    ("main", lambda b: _deploy("staging", b["new"])),    # and the reverse
    ("main", lambda b: _smoke(b["new"])),                # pdf-smoke is staging's
])
def test_each_key_deploys_only_its_own_environment(box, key, request_of):
    """Review 2026-11-11: one key and one forced command covered both environments and the request
    chose, so anything holding the staging copy (no reviewer; any commit merged to staging) could
    deploy or roll back production. Each key is forced with its environment, and the program
    refuses a request for the other one before it takes the lock or touches anything."""
    _set_running(box, "treadwell-proposal-tool", _image(box["old"]))
    _set_running(box, "treadwell-staging", _image(box["old"]))
    proc, log = box["run"](request_of(box), key=key)
    assert proc.returncode == 2 and "this key deploys %s only" % key in proc.stderr, proc.stderr
    assert log == "" and not (box["stub"] / "flock.log").exists()
    assert _where(box["prod"]) == (box["old"], "main") and _where(box["staging"]) == (box["old"], "staging")


@pytest.mark.parametrize("key", [None, "prod", ("staging", "main"), ("main", "extra"), ""])
def test_the_program_refuses_to_run_without_exactly_its_environment(box, key):
    """The old forced command passed no argument; a box still holding that line must not deploy."""
    proc, log = box["run"](_deploy("staging", box["new"]), key=key)
    assert proc.returncode == 2 and "refusing:" in proc.stderr, proc.stderr
    assert log == "" and _where(box["staging"]) == (box["old"], "staging")


def test_a_container_left_on_the_old_image_is_a_failed_deploy(box):
    """`up -d` can "succeed" and leave the OLD container serving, and /healthz answers from it. The
    health check also wants the container to run the new image; without that this deploy would be
    reported green, re-tagged and never rolled back."""
    old_image, new_image = _image(box["old"]), _image(box["new"])
    _set_running(box, "treadwell-staging", old_image)
    (box["stub"] / "up.stale").write_text("", encoding="utf-8")
    proc, log = box["run"](_deploy("staging", box["new"]))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "staging post-deploy healthcheck failed (wanted %s)" % new_image in proc.stdout + proc.stderr
    assert "rolling back to " + old_image in proc.stdout
    assert _where(box["staging"]) == (box["old"], "staging"), "the checkout went back too"
    assert " tag " not in " " + " ".join(_calls(log)), "a stale container is never re-tagged as deployed"


def test_a_failed_schema_reload_ends_red_after_a_healthy_deploy(box):
    """PostgREST not reloading its schema is not worth a rollback (the app is healthy), but the run
    must not be green: staging would serve the old schema with nothing saying so."""
    new_image = _image(box["new"])
    _set_running(box, "treadwell-staging", _image(box["old"]))
    (box["stub"] / "notify.fails").write_text("", encoding="utf-8")
    proc, log = box["run"](_deploy("staging", box["new"]))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "PostgREST did not take the schema reload" in proc.stderr
    assert _running(box, "treadwell-staging") == new_image, "no rollback for a reload"
    assert "tag %s %s:staging" % (new_image, IMAGE) in _calls(log)
    assert _where(box["staging"]) == (box["new"], "staging")


def test_a_dropped_session_never_stops_a_deploy_halfway(box):
    """Review 2026-11-11: when the SSH step times out the session closes, and the next write to it
    killed bash (or docker, or compose) with SIGPIPE wherever it was, possibly between moving the
    checkout and `up -d`. Here the reader goes away before the program writes anything: the deploy
    must still finish, and the root-only log says how it ended."""
    new_image = _image(box["new"])
    _set_running(box, "treadwell-proposal-tool", _image(box["old"]))
    proc = box["popen"](_deploy("main", box["new"]))
    proc.stdout.close()
    proc.stderr.close()
    assert proc.wait(timeout=120) == 0
    assert _running(box, "treadwell-proposal-tool") == new_image
    assert _where(box["prod"]) == (box["new"], "main")
    assert "prod healthy on " + new_image in box["log"].read_text(encoding="utf-8")


def test_the_time_budget_fits_the_ssh_step(box):
    """Review 2026-11-11: a 20-minute lock wait came out of the same 30-minute command_timeout as a
    deploy that can need ~12 minutes to fail and roll back, plus an unbounded pull. The worst case
    of one box run must fit the step's timeout."""
    text = REMOTE.read_text(encoding="utf-8")
    lock, pull = int(_default("LOCK_WAIT")), int(_default("PULL_TIMEOUT"))
    tries, pause = int(_default("TRIES")), int(_default("PAUSE"))
    health = tries * (10 + pause)                          # curl -m 10, then the pause
    database = tries * (10 + pause)                        # staging's pg_isready loop
    worst = lock + pull + database + 2 * health + 180      # + compose, logs, schema, housekeeping
    assert "curl -fsS -m 10 " in text
    timeouts = {s["with"]["command_timeout"] for j in ("staging", "production") for s in _ssh_steps(_load(DEPLOY)["jobs"][j])}
    assert len(timeouts) == 1
    minutes = int(timeouts.pop().rstrip("m"))
    assert worst < minutes * 60, (worst, minutes)
    assert "trap '' HUP PIPE" in text and 'tee -p -a "$LOG_FILE"' in text
    main = _remote_code()[_remote_code().index("main() {"):]
    assert main.index("survive_a_dropped_session") < main.index("take_lock")
    assert _default("LOG_FILE").startswith("/var/log/") and "umask 077" in text


def test_a_missing_env_file_stops_with_a_plain_message(box):
    (box["staging"] / ".env.staging").unlink()
    proc, log = box["run"](_deploy("staging", box["new"]))
    assert proc.returncode == 1 and ".env.staging is missing" in proc.stderr
    assert log == ""


def test_the_pdf_smoke_runs_the_deployed_image_against_the_deployed_checkout(box):
    """Review 2026-11-11: the smoke mounted the WHOLE staging checkout, .env.staging included (cloud
    auth keys, the real Dropbox credential, the Claude token), into a container that first ran an
    unpinned `pip install` from PyPI with full network. Now only backend/ (and the font) is mounted,
    that container has no network, and the test tools are wheels pinned by version and sha256,
    fetched by a separate container that sees nothing of the checkout."""
    proc, _ = box["run"](_deploy("staging", box["new"]))
    assert proc.returncode == 0, proc.stderr
    proc, log = box["run"](_smoke(box["new"]))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # each docker call is logged as "<args>|TW_IMAGE=..."; the smoke script's newlines are in <args>
    runs = re.findall(r"(?ms)^(run --rm .*?)\|TW_IMAGE=", log)
    assert len(runs) == 2, runs
    download, run = runs
    staging = box["staging"].as_posix()
    # the download: network, no checkout, wheels only, hash-checked
    assert " pip download " in download and "--require-hashes" in download and "--only-binary :all:" in download
    assert staging not in download and "/src" not in download and "--network none" not in download
    # the tests: no network, backend/ only, never the checkout's top level
    assert run.startswith("run --rm --network none "), run
    assert "-v %s/backend:/src/backend:ro" % staging in run
    assert "-v %s:/src" % staging not in run and ".env" not in run
    assert "-v %s:/usr/share/fonts/truetype/treadwell:ro" % box["fonts"].as_posix() in run
    assert " %s sh -c " % _image(box["new"]) in run and "pytest" in run and "--build" not in run
    assert "--no-index" in run and "--require-hashes" in run
    work = re.search(r"-v (\S+)/req:/req:ro", download).group(1)
    assert work in run and not pathlib.Path(work).exists(), "the wheel folder is removed after the run"
    (box["stub"] / "smoke.fails").write_text("", encoding="utf-8")
    proc, _ = box["run"](_smoke(box["new"]))
    assert proc.returncode != 0, "a failed smoke turns the run red"
    (box["stub"] / "smoke.fails").unlink()
    (box["stub"] / "download.fails").write_text("", encoding="utf-8")
    seen = len((box["stub"] / "docker.log").read_text(encoding="utf-8"))
    proc, log = box["run"](_smoke(box["new"]))
    assert proc.returncode == 1 and "could not download the pinned PDF test tools" in proc.stderr
    assert " pip download " in log[seen:] and "--network none" not in log[seen:], "no test run without its pinned tools"


def test_the_pdf_smoke_pins_its_tools_and_keeps_its_gates():
    """Every tool the network-less test container installs is pinned to a version AND a sha256
    (pip refuses anything unlisted under --require-hashes), and the smoke script keeps its three
    gates: the LibreOffice selection, failing on a skip, and the merge test asserted by name."""
    text = REMOTE.read_text(encoding="utf-8")
    m = re.search(r"^SMOKE_REQUIREMENTS='(.*?)'$", text, re.S | re.M)
    assert m, "no SMOKE_REQUIREMENTS"
    lines = m.group(1).splitlines()
    names = []
    for line in lines:
        assert re.fullmatch(r"[a-z][a-z0-9_-]*==[0-9][0-9.]* --hash=sha256:[0-9a-f]{64}", line), line
        names.append(line.split("==")[0])
    assert {"pytest", "pymupdf", "iniconfig", "packaging", "pluggy", "pygments"} <= set(names), names
    assert len(set(names)) == len(names)
    smoke = text[text.index("smoke=$(cat <<'SMOKE'"):text.index("\nSMOKE\n")]
    assert smoke.splitlines()[1] == "set -e", "a failed install must stop the smoke"
    assert "--no-index --no-deps --find-links /wheels --require-hashes" in smoke
    assert '-k "pdf or libreoffice"' in smoke
    assert 'grep -q "skipped" /tmp/pdf.out' in smoke
    assert 'grep -qE "[0-9]+ passed" /tmp/pdf.out' in smoke
    assert 'grep -qE "^1 passed" /tmp/merge.out' in smoke
    assert "tests/test_docx_merge.py -k libreoffice" in smoke
    assert "pip install --quiet --no-input pytest" not in text, "the unpinned install is back"


def test_the_pdf_smoke_refuses_a_commit_staging_is_no_longer_at(box):
    proc, log = box["run"](_smoke(box["new"]))      # staging is still at old
    assert proc.returncode == 2 and "is at %s, not %s" % (box["old"], box["new"]) in proc.stderr
    assert "run --rm" not in log
    _git(box["staging"], "merge", "-q", "--ff-only", box["new"])
    proc, log = box["run"](_smoke(box["new"]))      # at new, but never pulled
    assert proc.returncode == 1 and "is not on this box" in proc.stderr and "run --rm" not in log


def test_the_program_says_when_its_installed_copy_is_stale(box):
    """The box runs a COPY (install-deploy-account.sh); after a commit changes
    deploy/remote-deploy.sh the deploy warns that the copy must be re-installed."""
    proc, _ = box["run"](_deploy("staging", box["new"]))
    assert proc.returncode == 0 and "re-run deploy/install-deploy-account.sh" not in proc.stdout
    script = box["staging"] / "deploy" / "remote-deploy.sh"
    script.write_text(script.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8", newline="\n")
    _git(box["staging"], "-c", "user.email=ci@example.com", "-c", "user.name=ci", "-c", "commit.gpgsign=false",
         "commit", "-q", "-am", "changed")
    changed = _git(box["staging"], "rev-parse", "HEAD")
    _git(box["staging"], "push", "-q", "origin", "HEAD:refs/heads/staging")
    _git(box["staging"], "reset", "-q", "--hard", box["new"])
    proc, _ = box["run"](_deploy("staging", changed))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "re-run deploy/install-deploy-account.sh" in proc.stdout
