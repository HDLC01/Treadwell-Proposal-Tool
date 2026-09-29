"""The ZAP baseline scan may look at our four apps and nothing else, and may never change them.

.github/workflows/zap-baseline.yml scans staging AND production (Hanz, 2026-09-29: "owasp should
scan production as well"). Production has real customers on it, so every property that keeps the
scan harmless is pinned here rather than left to whoever edits the workflow next:

  * the targets are exactly our four hosts, never the marketing site at the bare domain / www;
  * staging is scanned after a successful staging deploy, production after a successful main
    deploy, and a failed or foreign deploy triggers nothing;
  * no job holds more than `contents: read`, the image is pinned by digest and every action by
    commit SHA;
  * the spider never submits a form, runs two threads for one minute, and never requests the
    portal paths that write or send mail; there is no Ajax/browser spider and no active scan;
  * findings never fail the job;
  * the public step summary carries counts and alert names only, never a URL or evidence, and the
    full report is kept 7 days.

Several of these are EXECUTED rather than read: the workflow's `if:` expressions are evaluated
for every trigger, the exclusion regexes are matched against real URLs, and .zap/summarize.py is
run on a report full of canaries. A property that is only grepped for can be written correctly
and still not hold.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "zap-baseline.yml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"
PLAN = ROOT / ".zap" / "baseline.yaml"
RULES = ROOT / ".zap" / "rules.tsv"
SUMMARIZE = ROOT / ".zap" / "summarize.py"

STAGING = {"https://staging.proposals.wetreadwell.com", "https://staging.portal.wetreadwell.com"}
PRODUCTION = {"https://proposals.wetreadwell.com", "https://portal.wetreadwell.com"}
FOUR = STAGING | PRODUCTION
PORTALS = ("https://staging.portal.wetreadwell.com", "https://portal.wetreadwell.com")

# The portal is read beside this repo exactly as test_close_reason_vocabulary.py reads it; CI checks
# it out and points TW_PORTAL_REPO at it.
PORTAL = pathlib.Path(os.environ.get("TW_PORTAL_REPO") or (ROOT.parent / "treadwell-portal"))
PORTAL_MAIN = PORTAL / "backend" / "main.py"
_CI = (os.environ.get("CI", "").strip().lower() in ("1", "true", "yes")
       or bool(os.environ.get("GITHUB_ACTIONS"))
       or os.environ.get("TW_REQUIRE_PORTAL", "").strip() in ("1", "true", "yes"))


def _yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _workflow():
    return _yaml(WORKFLOW)


def _triggers(doc):
    # PyYAML follows YAML 1.1, where a bare `on` is the boolean True.
    return doc.get("on", doc.get(True))


def _jobs():
    return _workflow()["jobs"]


def _targets(job):
    return [m["target"] for m in job["strategy"]["matrix"]["include"]]


def _step(job, name_start):
    hits = [s for s in job["steps"] if (s.get("name") or "").startswith(name_start)]
    assert len(hits) == 1, "expected one step named %r..., found %d" % (name_start, len(hits))
    return hits[0]


def _scan_script(job):
    """The scan step's commands, without its comments (see _code)."""
    return _code(_step(job, "Scan")["run"])


def _plan():
    return _yaml(PLAN)


def test_the_files_exist():
    """A rename would make every assertion below vacuously pass."""
    for p in (WORKFLOW, PLAN, RULES, SUMMARIZE, DEPLOY):
        assert p.is_file(), p


# ── the targets ──────────────────────────────────────────────────────────────

def test_the_targets_are_exactly_our_four_apps():
    jobs = _jobs()
    assert set(jobs) == {"staging", "production"}, "a job was added or renamed: %s" % sorted(jobs)
    assert set(_targets(jobs["staging"])) == STAGING
    assert set(_targets(jobs["production"])) == PRODUCTION
    every = _targets(jobs["staging"]) + _targets(jobs["production"])
    assert sorted(every) == sorted(FOUR), "a target is duplicated or extra: %s" % every


def _code(text):
    """The text with `#` comments removed, YAML and shell alike: the prose explains what is
    forbidden by naming it, and matching the prose would make these tests fail on their own
    documentation."""
    return "\n".join(re.sub(r"(^|\s)#.*$", "", ln) for ln in text.splitlines())


def test_no_file_names_any_other_host_of_ours():
    """The bare domain and www are the marketing WordPress site on other hosting: not ours to scan.
    Every host in the workflow and the plan is checked, not only the matrix, so a target smuggled
    in through an env var or a script is caught too."""
    allowed = {urlsplit(u).hostname for u in FOUR}
    for path in (WORKFLOW, PLAN):
        hosts = set(re.findall(r"[A-Za-z0-9.-]*wetreadwell\.com", _code(path.read_text(encoding="utf-8"))))
        assert hosts <= allowed, "%s names %s" % (path.name, sorted(hosts - allowed))
        assert not hosts & {"wetreadwell.com", "www.wetreadwell.com"}


def test_the_plan_scans_only_the_target_it_is_given():
    """The plan hard-codes no host: the context and the spider both take ${ZAP_TARGET}, and the one
    place that sets it is the scan step, from the matrix."""
    plan = _plan()
    (ctx,) = plan["env"]["contexts"]
    assert ctx["urls"] == ["${ZAP_TARGET}"]
    (spider,) = [j for j in plan["jobs"] if j["type"] == "spider"]
    assert spider["parameters"]["url"] == "${ZAP_TARGET}"
    for job in _jobs().values():
        assert _step(job, "Scan")["env"]["TARGET"] == "${{ matrix.target }}"
        assert '-e ZAP_TARGET="$TARGET"' in _scan_script(job)


# ── when it runs ─────────────────────────────────────────────────────────────

_TOKEN = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<op>&&|\|\||==|!=|!|\(|\))"
                    r"|(?P<call>[A-Za-z_]\w*)\(\)|(?P<ident>[A-Za-z_][\w.-]*))")


def _truthy(value):
    return value not in (None, False, "", 0)


def _evaluate(expr, ctx, cancelled=False):
    """Evaluate a GitHub Actions `if:` expression, for the small grammar these jobs use: string
    literals, dotted context lookups, == != ! && || and parentheses, and the status functions.
    As in Actions: `!` binds tighter than == and !=, which bind tighter than &&, then ||; string
    comparison ignores case; a missing property is null. Anything else is refused, not guessed."""
    toks, pos, text = [], 0, expr.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise AssertionError("cannot read %r at %r" % (text, text[pos:]))
        toks.append((m.lastgroup, m.group(m.lastgroup)))
        pos = m.end()
    at = [0]

    def peek():
        return toks[at[0]][1] if at[0] < len(toks) else None

    def take(expected=None):
        if at[0] >= len(toks) or (expected is not None and toks[at[0]][1] != expected):
            raise AssertionError("expected %r in %r" % (expected, text))
        at[0] += 1
        return toks[at[0] - 1]

    def primary():
        kind, tok = take()
        if tok == "(":
            value = either()
            take(")")
            return value
        if kind == "str":
            return tok[1:-1].replace("''", "'")
        if kind == "call":
            status = {"cancelled": cancelled, "always": True, "success": not cancelled, "failure": False}
            if tok not in status:
                raise AssertionError("unknown function %s() in %r" % (tok, text))
            return status[tok]
        if kind == "ident":
            value = ctx
            for part in tok.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            return value
        raise AssertionError("unexpected %r in %r" % (tok, text))

    def unary():
        if peek() == "!":
            take()
            return not _truthy(unary())
        return primary()

    def compare():
        left = unary()
        if peek() in ("==", "!="):
            op = take()[1]
            right = unary()
            fold = [v.lower() if isinstance(v, str) else v for v in (left, right)]
            return (fold[0] == fold[1]) == (op == "==")
        return left

    def both():
        value = compare()
        while peek() == "&&":
            take()
            right = compare()
            value = _truthy(value) and _truthy(right)
        return value

    def either():
        value = both()
        while peek() == "||":
            take()
            right = both()
            value = _truthy(value) or _truthy(right)
        return value

    result = either()
    if at[0] != len(toks):
        raise AssertionError("unread tokens in %r" % text)
    return _truthy(result)


def _ctx(event, inputs=None, conclusion=None, branch=None, repo="HDLC01/Treadwell-Proposal-Tool"):
    wr = None
    if event == "workflow_run":
        wr = {"conclusion": conclusion, "head_branch": branch, "head_repository": {"full_name": repo}}
    return {"github": {"event_name": event, "repository": "HDLC01/Treadwell-Proposal-Tool",
                       "event": {"workflow_run": wr} if wr else {}},
            "inputs": inputs or {}}


# (what happened, context, jobs that must run). Both outcomes appear for both jobs, so the
# evaluator cannot pass by answering the same thing every time.
SCENARIOS = [
    ("weekly schedule", _ctx("schedule"), {"staging", "production"}),
    ("manual: staging", _ctx("workflow_dispatch", {"environment": "staging"}), {"staging"}),
    ("manual: production", _ctx("workflow_dispatch", {"environment": "production"}), {"production"}),
    ("manual: both", _ctx("workflow_dispatch", {"environment": "both"}), {"staging", "production"}),
    ("staging deploy succeeded", _ctx("workflow_run", conclusion="success", branch="staging"), {"staging"}),
    ("main deploy succeeded", _ctx("workflow_run", conclusion="success", branch="main"), {"production"}),
    ("staging deploy failed", _ctx("workflow_run", conclusion="failure", branch="staging"), set()),
    ("main deploy failed", _ctx("workflow_run", conclusion="failure", branch="main"), set()),
    ("main deploy rejected at the gate", _ctx("workflow_run", conclusion="cancelled", branch="main"), set()),
    ("main deploy skipped", _ctx("workflow_run", conclusion="skipped", branch="main"), set()),
    ("a deploy of some other branch", _ctx("workflow_run", conclusion="success", branch="feat/x"), set()),
    ("a 'main' deploy from a fork", _ctx("workflow_run", conclusion="success", branch="main",
                                          repo="someone/Treadwell-Proposal-Tool"), set()),
    ("a 'staging' deploy from a fork", _ctx("workflow_run", conclusion="success", branch="staging",
                                             repo="someone/Treadwell-Proposal-Tool"), set()),
    ("an unrelated event", _ctx("push"), set()),
]


@pytest.mark.parametrize("what, ctx, expected", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_each_trigger_scans_the_right_environment(what, ctx, expected):
    jobs = _jobs()
    ran = {name for name, job in jobs.items() if _evaluate(job["if"], ctx)}
    assert ran == expected, "%s: %s ran, expected %s" % (what, sorted(ran), sorted(expected))


def test_a_cancelled_run_starts_no_production_scan():
    """`!cancelled()` lets production run after a skipped or failed staging job. It must not also
    let it run when somebody cancelled the whole run."""
    job = _jobs()["production"]
    assert _evaluate(job["if"], _ctx("schedule"), cancelled=False)
    assert not _evaluate(job["if"], _ctx("schedule"), cancelled=True)


def test_production_waits_for_staging():
    """One scan at a time on a 1-core VPS that hosts a dozen sites."""
    jobs = _jobs()
    assert jobs["production"]["needs"] in ("staging", ["staging"])
    for job in jobs.values():
        assert job["strategy"]["max-parallel"] == 1
        assert job["strategy"]["fail-fast"] is False


def test_the_triggers():
    on = _triggers(_workflow())
    assert set(on) == {"schedule", "workflow_dispatch", "workflow_run"}
    assert on["workflow_run"]["workflows"] == ["Deploy"]
    assert on["workflow_run"]["types"] == ["completed"]
    assert set(on["workflow_run"]["branches"]) == {"staging", "main"}
    choice = on["workflow_dispatch"]["inputs"]["environment"]
    assert choice["type"] == "choice" and set(choice["options"]) == {"staging", "production", "both"}
    # `workflows: [Deploy]` matches the deploy workflow's NAME. Renaming it would silently stop
    # every post-deploy scan.
    assert _yaml(DEPLOY)["name"] == "Deploy"


def test_the_schedule_is_off_the_hour_in_the_small_hours_on_sunday():
    (entry,) = _triggers(_workflow())["schedule"]
    minute, hour, dom, month, dow = entry["cron"].split()
    assert (dom, month, dow) == ("*", "*", "0"), "weekly, on Sunday"
    assert int(minute) not in (0, 30), "off-minute, so it does not queue behind every other :00 job"
    central = ZoneInfo("America/Chicago")
    for day in (datetime(2026, 1, 4, tzinfo=timezone.utc), datetime(2026, 7, 5, tzinfo=timezone.utc)):
        local = day.replace(hour=int(hour), minute=int(minute)).astimezone(central)
        assert local.weekday() == 6 and 0 <= local.hour < 6, "not before dawn in Central: %s" % local


def test_nothing_checks_out_the_deploys_code():
    """A workflow_run job that checks out the triggering commit is the classic way to run a fork's
    code with the base repo's permissions. Only the default branch's .zap/ is checked out, and no
    credential is left in .git for the container to read."""
    for job in _jobs().values():
        (checkout,) = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]
        w = checkout.get("with") or {}
        assert "ref" not in w and "repository" not in w
        assert w.get("persist-credentials") is False
        assert w.get("sparse-checkout") == ".zap"


# ── what the jobs can touch ──────────────────────────────────────────────────

def test_every_permission_is_read_only():
    doc = _workflow()
    assert doc["permissions"] == {"contents": "read"}
    for name, job in doc["jobs"].items():
        assert job.get("permissions", {"contents": "read"}) == {"contents": "read"}, name
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text, "the scan needs no secret and must be given none"
    assert "github.token" not in text and "GITHUB_TOKEN" not in text


def test_the_image_is_pinned_by_digest():
    image = _workflow()["env"]["ZAP_IMAGE"]
    assert re.fullmatch(r"(ghcr\.io/zaproxy/zaproxy|zaproxy/zap-stable)@sha256:[0-9a-f]{64}", image), image
    line = next(ln for ln in WORKFLOW.read_text(encoding="utf-8").splitlines()
                if ln.strip().startswith("ZAP_IMAGE:"))
    assert re.search(r"#\s*stable \(\d+\.\d+\.\d+\)", line), "the tag belongs in a comment beside the digest"
    for job in _jobs().values():
        script = _scan_script(job)
        runs = re.findall(r"docker (?:run|pull)\b[^\n]*(?:\\\n[^\n]*)*", script)
        assert len(runs) == 2, runs
        for r in runs:
            assert '"$ZAP_IMAGE"' in r, "a docker command uses an image other than the pinned one: %s" % r


def test_every_action_is_pinned_to_a_commit():
    uses = re.findall(r"^\s*(?:-\s*)?uses:\s*(\S+)(.*)$", WORKFLOW.read_text(encoding="utf-8"), re.M)
    assert uses, "no actions found at all"
    for ref, tail in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), "not pinned to a full SHA: " + ref
        assert re.search(r"#\s*v\d+\.\d+\.\d+", tail), "no version comment beside " + ref
        # The zaproxy actions take the repo token and can open issues.
        assert not ref.lower().startswith("zaproxy/"), ref


# ── the scan itself ──────────────────────────────────────────────────────────

def test_the_plan_is_passive_spider_only():
    """A baseline: spider, passive rules, reports. No active scan, no Ajax spider, no browser
    (client) spider, and nothing that could request a URL on its own."""
    kinds = [j["type"] for j in _plan()["jobs"]]
    assert set(kinds) <= {"passiveScan-config", "spider", "passiveScan-wait", "report"}, kinds
    assert kinds.count("spider") == 1


def test_the_spider_never_submits_a_form_and_stays_small():
    """Measured on the pinned image: without these the spider submitted a GET and a POST form and
    ran 32 requests in flight. zap-baseline.py's -config options do not reach it (see the plan's
    header), which is why they are job parameters here."""
    (spider,) = [j for j in _plan()["jobs"] if j["type"] == "spider"]
    p = spider["parameters"]
    assert p["processForm"] is False
    assert p["postForm"] is False
    assert p["threadCount"] <= 2
    assert p["maxDuration"] == 1
    (wait,) = [j for j in _plan()["jobs"] if j["type"] == "passiveScan-wait"]
    assert 0 < wait["parameters"]["maxDuration"] <= 5


def test_the_scan_runs_this_plan_and_nothing_else():
    for job in _jobs().values():
        script = _scan_script(job)
        assert "cp .zap/baseline.yaml" in script
        assert "-autorun /zap/wrk/baseline.yaml" in script
        for other in ("zap-baseline.py", "zap-full-scan", "zap-api-scan", "spiderAjax", "spiderClient",
                      "activeScan", "-ajax", " -j "):
            assert other not in script, "the scan step mentions %r" % other


def _excludes():
    return [re.compile(p) for p in _plan()["env"]["contexts"][0]["excludePaths"]]


def _excluded(url):
    # ZAP applies a context exclusion with Java's Matcher.matches(): the WHOLE url must match.
    return any(p.fullmatch(url) for p in _excludes())


@pytest.mark.parametrize("path", ["/p/0123456789abcdef", "/p/0123456789abcdef?utm=email",
                                  "/p/0123456789abcdef#proposal", "/api/auth/request-code",
                                  "/api/auth/verify-code", "/api/auth/logout"])
def test_the_portal_paths_that_write_are_never_requested(path):
    """GET /p/{token} stamps link_clicked on a real proposal; /api/auth/* emails a sign-in code or
    revokes a session. Checked on both portals."""
    for base in PORTALS:
        assert _excluded(base + path), base + path


@pytest.mark.parametrize("path", ["/", "/healthz", "/login.js", "/static/img/treadwell-bison.svg",
                                  "/api/public-config", "/api/portal/abc"])
def test_the_exclusions_do_not_swallow_the_site(path):
    """The other half: an exclusion broad enough to match everything would make the scan a no-op
    that still reports green."""
    for base in sorted(FOUR):
        assert not _excluded(base + path), base + path


def test_the_tools_logged_out_surface_is_the_audited_one():
    """The route check behind the exclusions, kept current. Every GET this app serves without the
    Google sign-in was read for writes and mail on 2026-09-29, and nothing was found; /api/admin/
    proposal-pdf answers 401 without the service token before it reads anything. A new route in
    this list has to be read the same way, then added here (or to the plan's excludePaths)."""
    import main
    from starlette.routing import Mount

    public = set()
    for r in main.app.routes:
        if isinstance(r, Mount):
            continue
        if "GET" in (getattr(r, "methods", None) or ()) and main._auth_is_public(r.path, "GET"):
            public.add(r.path)
    assert public == {"/", "/healthz", "/api/public-config", "/api/admin/proposal-pdf"}, sorted(public)


# Every GET the portal serves, and why the scan may request it. Read on 2026-09-29 from the
# portal's main (0517735): "session" = needs the customer's signed-in cookie, which the scan never
# has; "service" = needs the X-Service-Token header; "excluded" = never requested.
PORTAL_GETS = {
    "/healthz": "static",
    "/": "static (login.html)",
    "/{asset}": "static (an allow-list of files)",
    "/api/public-config": "read-only",
    "/p/{token}": "EXCLUDED: stamps link_clicked for a real token",
    "/api/me/notifications": "session",
    "/api/me/proposals": "session",
    "/api/portal/{token}": "session",
    "/api/portal/{token}/messages": "session",
    "/api/portal/{token}/file/{file_id}": "session",
    "/api/portal/{token}/pdf": "session",
    "/api/portal/{token}/deposit-invoice.pdf": "session",
    "/api/portal/{token}/signed-contract.pdf": "session",
    "/api/admin/pipeline": "service",
    "/api/admin/recent-messages": "service",
    "/api/admin/proposal/{proposal_id}": "service",
    "/api/admin/settings/followups": "service",
    "/api/admin/proposal/{proposal_id}/followups": "service",
    "/api/admin/proposal/{proposal_id}/file/{file_id}": "service",
    "/api/admin/signed-contract.pdf": "service",
    "/api/admin/notify-recipients": "service",
    "/api/admin/notify-overrides": "service",
    "/api/admin/proposal/{proposal_id}/notify-overrides": "service",
}


def test_the_portals_logged_out_surface_is_the_audited_one():
    """The same check across the repo boundary. A GET route added to the portal fails this until
    somebody has read it for writes and mail and recorded the verdict above."""
    if not PORTAL_MAIN.exists():
        if _CI:
            pytest.fail("the portal is not checked out at %s, so its routes cannot be audited" % PORTAL)
        pytest.skip("the customer portal is not checked out beside this repo")
    src = PORTAL_MAIN.read_text(encoding="utf-8")
    assert not re.search(r"@app\.(api_route|head)\(|add_api_route\(|add_route\(", src), (
        "the portal registers a route in a way this audit does not read")
    gets = set(re.findall(r"@app\.get\(\s*\"([^\"]+)\"", src))
    assert gets == set(PORTAL_GETS), ("new: %s, gone: %s" % (sorted(gets - set(PORTAL_GETS)),
                                                              sorted(set(PORTAL_GETS) - gets)))
    for route, verdict in PORTAL_GETS.items():
        if verdict.startswith("EXCLUDED"):
            sample = re.sub(r"\{[^}]+\}", "0123456789abcdef", route)
            for base in PORTALS:
                assert _excluded(base + sample), "%s is marked excluded but the plan requests it" % route


# ── report only, and nothing private in public ───────────────────────────────

def test_findings_never_fail_the_job():
    """The -I of zap-baseline.py, here: the plan fails on its own errors only, it has no
    exitStatus or outputSummary job (the ones that turn alerts into an exit code or print them),
    and the scan step records ZAP's exit code instead of dying on it."""
    params = _plan()["env"]["parameters"]
    assert params["failOnWarning"] is False
    assert params["failOnError"] is True
    assert params["progressToStdout"] is False
    kinds = {j["type"] for j in _plan()["jobs"]}
    assert not kinds & {"exitStatus", "outputSummary"}
    for job in _jobs().values():
        script = _scan_script(job)
        assert '> "$wrk/zap.log" 2>&1 || rc=$?' in script, "ZAP's output must go to a file and its exit code be kept"
        assert re.search(r"timeout\b[^\n]*\d+m", script), "the scan has no time limit of its own"
        assert 0 < job["timeout-minutes"] <= 30


def test_the_two_environments_run_identical_steps():
    """So a safety change cannot reach staging and miss production, or the reverse."""
    jobs = _jobs()
    assert jobs["staging"]["steps"] == jobs["production"]["steps"]


def test_scans_of_one_app_never_overlap():
    for job in _jobs().values():
        c = job["concurrency"]
        assert "${{ matrix.name }}" in c["group"]
        assert c["cancel-in-progress"] is False
        names = [m["name"] for m in job["strategy"]["matrix"]["include"]]
        assert len(set(names)) == len(names)


def test_the_full_report_is_kept_seven_days():
    for job in _jobs().values():
        uploads = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
        assert len(uploads) == 1
        w = uploads[0]["with"]
        assert int(w["retention-days"]) == 7
        assert "report.html" in w["path"] and "report.json" in w["path"]
        assert uploads[0]["if"] == "always()"


def test_the_summary_step_prints_only_what_summarize_py_prints():
    """The step summary is written by .zap/summarize.py and by nothing else: no step echoes the
    report, and no other step writes to $GITHUB_STEP_SUMMARY."""
    for job in _jobs().values():
        writers = [s for s in job["steps"] if "GITHUB_STEP_SUMMARY" in (s.get("run") or "")]
        assert len(writers) == 1
        assert writers[0]["run"].startswith("python3 .zap/summarize.py ")
        for s in job["steps"]:
            run = s.get("run") or ""
            assert "report.json" not in run.replace('"$RUNNER_TEMP/zap/report.json"', ""), s.get("name")
            assert "cat " not in run and "jq " not in run, s.get("name")


CANARIES = {
    "uri": "https://portal.wetreadwell.com/p/CANARYTOKEN0001?e=CANARY-QS",
    "param": "CANARY-PARAM",
    "attack": "CANARY-ATTACK<script>",
    "evidence": "CANARY-EVIDENCE Set-Cookie: s=CANARYCOOKIE",
    "otherinfo": "CANARY-OTHERINFO",
}


def _report(tmp_path, alerts, extra=None):
    doc = {
        "@programName": "ZAP", "@version": "2.17.0",
        "insights": [{"site": "https://CANARY-INSIGHT.example", "description": "CANARY-INSIGHT"}],
        "site": [{"@name": "https://CANARY-SITE.example", "@host": "CANARY-HOST", "alerts": alerts}],
    }
    doc.update(extra or {})
    p = tmp_path / "report.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _alert(pluginid, ref, risk, name, count=3):
    return {"pluginid": pluginid, "alertRef": ref, "riskcode": str(risk), "name": name, "alert": name,
            "count": str(count), "desc": "<p>CANARY-DESC</p>", "solution": "CANARY-SOLUTION",
            "reference": "https://CANARY-REFERENCE.example/x", "cweid": "1", "wascid": "2",
            "instances": [dict(CANARIES)]}


def _summarize(tmp_path, report, rules=None, target="https://portal.wetreadwell.com", code="0"):
    rules_path = RULES if rules is None else rules
    return subprocess.run([sys.executable, str(SUMMARIZE), str(report), str(rules_path), target, code],
                          capture_output=True, text=True, encoding="utf-8")


def test_the_public_summary_never_carries_a_url_or_evidence(tmp_path):
    report = _report(tmp_path, [
        _alert("10035", "10035-3", 1, "Strict-Transport-Security Multiple Header Entries"),
        _alert("10055", "10055-6", 2, "CSP: style-src unsafe-inline"),
        _alert("10055", "10055-5", 2, "CSP: script-src unsafe-inline"),
        _alert("40012", "40012", 3, "Cross Site Scripting https://CANARY-NAMEURL.example/a?b=1"),
        _alert("10027", "10027", 0, "Information Disclosure - Suspicious Comments", count=9),
        _alert("10096", "10096", -1, "A false positive"),
    ])
    r = _summarize(tmp_path, report)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "CANARY" not in out, out
    assert "://" not in out.replace("https://portal.wetreadwell.com", ""), out
    assert "<" not in out and "Set-Cookie" not in out
    # the counts, with the deliberate ignore left out of them but still shown with its reason
    assert "| High | 1 | 3 |" in out
    assert "| Medium | 1 | 3 |" in out           # script-src counts; style-src is ignored
    assert "| Low | 1 | 3 |" in out
    assert "| Informational | 1 | 9 |" in out
    assert "CSP: script-src unsafe-inline [10055-5]" in out
    ignored = out.split("Ignored on purpose", 1)[1]
    assert "CSP: style-src unsafe-inline [10055-6]" in ignored and "5b9b71f" in ignored
    assert "false positive" not in out.lower()


def test_findings_do_not_change_the_summary_exit_code(tmp_path):
    report = _report(tmp_path, [_alert("40012", "40012", 3, "Cross Site Scripting (Reflected)")])
    assert _summarize(tmp_path, report).returncode == 0


@pytest.mark.parametrize("code", ["1", "124", "none"])
def test_a_scan_that_did_not_happen_fails_loudly(tmp_path, code):
    """No report, or ZAP broke: the job must go red, so silence can never pass for a clean scan."""
    missing = _summarize(tmp_path, tmp_path / "nope.json", code=code)
    assert missing.returncode == 1 and "did not produce a report" in missing.stdout
    broken = _summarize(tmp_path, _report(tmp_path, []), code=code)
    assert broken.returncode == 1 and "ZAP exited with code" in broken.stdout


def test_a_bad_rules_line_is_an_error_not_a_silent_miss(tmp_path):
    """A misspelt level would otherwise stop ignoring; an ignore with no reason is not allowed."""
    report = _report(tmp_path, [])
    for bad in ("10055-6\tIGNORE\tCSP: style-src unsafe-inline\t\n",
                "10055-6\tIGNOER\tCSP: style-src unsafe-inline\treason\n",
                "10055-6\tIGNORE\treason only\n",
                "http://x\tIGNORE\tname\treason\n"):
        rules = tmp_path / "rules.tsv"
        rules.write_text(bad, encoding="utf-8")
        assert _summarize(tmp_path, report, rules=rules).returncode != 0, bad


def _rules():
    rows = []
    for line in RULES.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            rows.append(line.split("\t"))
    return rows


def test_the_rules_ignore_only_what_has_a_reason():
    rows = _rules()
    assert rows, "the rules file is empty; the CSP style-src ignore is gone"
    for row in rows:
        assert len(row) == 4, row
        key, level, name, reason = row
        assert level == "IGNORE"
        assert re.fullmatch(r"\d+(-\d+)?", key), key
        assert name.strip() and len(reason.strip()) >= 20, "an ignore needs a real reason: %r" % row
    keys = {r[0] for r in rows}
    assert "10055-6" in keys, "CSP style-src 'unsafe-inline' is kept on purpose (5b9b71f)"
    # 10055 is ONE rule that raises every CSP alert. Ignoring it whole would also hide
    # script-src 'unsafe-inline' coming back, which is what 5b9b71f took out.
    assert "10055" not in keys
