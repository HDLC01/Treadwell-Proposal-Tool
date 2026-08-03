"""The deploy pipeline must never build the image on the production VPS.

That box is 1 core / 2 GB and hosts ~13 containers for other Treadwell sites. This image
bakes in Node, the Claude CLI and LibreOffice, so building it there spikes load to ~60 and
browns out every site on the machine — which is how production went down on 2026-06-24,
and retrying the deploy made it worse.

`--build` is one word, it reads as harmless, and the failure it causes lands on unrelated
applications rather than on this one. So it is pinned here rather than left to whoever
edits the workflow next.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"
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
