"""The autofill subprocess must have no way to act.

`_autofill_via_cli` feeds UNTRUSTED text — a lead email, a pasted note, a
dictated transcript — to `claude -p`. The lead-inbox path runs it with no human
in the loop. So the subprocess is a text-in/JSON-out transform and gets no
tools and no MCP servers.

This was measured, not assumed. Without `--tools ""`, `claude -p` in this exact
shape reads a file off disk and runs a shell command when asked; the process it
runs in holds the OAuth token, the Dropbox credentials and SERVICE_TOKEN in its
environment, and every customer draft in /app/data/drafts.db.

These tests EXECUTE the real function and inspect the argv it builds, per
[[execute-the-renderer-not-its-source]]. A grep of main.py cannot see the
variadic trap that `test_tools_flag_is_terminated_by_another_flag` pins.
"""
import subprocess

import pytest

import main


class _FakeProc:
    returncode = 0
    stderr = ""
    stdout = '{"ok": true}'


@pytest.fixture
def argv(monkeypatch):
    """Run the real `_autofill_via_cli`, capturing the argv and stdin it used."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def _call(argv, text="lead notes from a stranger", **kw):
    assert main._autofill_via_cli(text, **kw) == {"ok": True}
    return argv["cmd"]


def test_every_builtin_tool_is_removed(argv):
    """`--tools ""` empties the available set. Not a permission rule: an
    unregistered tool cannot be granted back by a settings file or a prompt."""
    cmd = _call(argv)
    assert "--tools" in cmd, "the autofill subprocess can use tools"
    assert cmd[cmd.index("--tools") + 1] == "", (
        "--tools was given a value, so those tools are ENABLED — it must be the "
        "empty string to disable all of them")


def test_no_mcp_servers_are_reachable(argv):
    """A server configured in the mounted CLAUDE_CONFIG_DIR volume must not be
    able to hand tools to this session. `--strict-mcp-config` with no
    `--mcp-config` means zero servers."""
    cmd = _call(argv)
    assert "--strict-mcp-config" in cmd
    assert "--mcp-config" not in cmd, "an MCP server was loaded into an untrusted session"


def test_tools_flag_is_terminated_by_another_flag(argv):
    """The trap this file exists for. `--tools` is variadic, so it swallows every
    following bare value. Reorder the list so a plain argument lands after the
    empty string — `"--tools", "", "text"` — and `text` is parsed as a TOOL NAME
    instead of disabling everything, silently re-enabling nothing-in-particular
    while looking correct in a diff."""
    cmd = _call(argv)
    after = cmd[cmd.index("--tools") + 2]
    assert after.startswith("--"), (
        f"{after!r} follows the empty --tools value and will be parsed as a tool "
        f"name; --tools must be followed immediately by another flag")


def test_permission_checks_are_never_bypassed(argv):
    cmd = _call(argv)
    for flag in ("--dangerously-skip-permissions",
                 "--allow-dangerously-skip-permissions"):
        assert flag not in cmd
    if "--permission-mode" in cmd:
        assert cmd[cmd.index("--permission-mode") + 1] != "bypassPermissions"


def test_bare_is_not_used(argv):
    """`--bare` skips hooks and CLAUDE.md discovery, which reads as a hardening
    win — but it also stops the CLI reading OAuth, and this container
    authenticates with CLAUDE_CODE_OAUTH_TOKEN. It would take autofill down on
    prod, so it is barred here rather than discovered during a deploy."""
    assert "--bare" not in _call(argv)


def test_untrusted_text_goes_on_stdin_not_into_a_flag(argv):
    """In the user slot the lead text is data the model reasons about. Spliced
    into `--append-system-prompt` it would become instructions."""
    text = "UNIQUE-LEAD-BODY-8f21c properly untrusted"
    cmd = _call(argv, text=text)
    assert argv["kwargs"].get("input") == text, "the lead text no longer goes on stdin"
    for i, part in enumerate(cmd):
        assert text not in part, f"untrusted lead text was spliced into argv[{i}]"


def test_the_isolation_holds_for_the_lead_inbox_prompt(argv):
    """`system_prompt` is the only thing callers vary — the leads and verbal
    paths pass their own. The flags must not depend on which job is running,
    because the lead-inbox path is the one with no human in the loop."""
    cmd = _call(argv, system_prompt="a different job's prompt")
    assert "--tools" in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--append-system-prompt") + 1] == "a different job's prompt"


def test_no_app_credential_reaches_the_subprocess(argv, monkeypatch):
    """Layer 2. Every credential the backend reads must be absent from the
    child's environment.

    The names are the real ones, grepped out of `os.environ` reads across
    `backend/`. They are listed rather than derived so that adding a secret
    whose name defeats `_CLI_ENV_SECRET_HINTS` fails HERE, at the place that
    documents the guarantee, instead of passing a self-consistent test that
    only checks the pattern against itself
    ([[vacuous-invariant-needs-a-counterexample]])."""
    secrets = ("SERVICE_TOKEN", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_JWT_SECRET",
               "SUPABASE_ANON_KEY", "SUPABASE_DATA_KEY", "DROPBOX_APP_KEY",
               "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN",
               "DROPBOX_ACCESS_TOKEN", "BASISBOARD_API_KEY")
    for name in secrets:
        monkeypatch.setenv(name, f"REAL-VALUE-OF-{name}")

    _call(argv)
    env = argv["kwargs"].get("env")
    assert env is not None, (
        "no env= was passed, so the subprocess inherited every secret this "
        "process holds")
    leaked = [n for n in secrets if n in env]
    assert not leaked, f"the untrusted subprocess can read {leaked}"


def test_the_cli_can_still_authenticate(argv, monkeypatch):
    """The counterweight, and the reason this isn't an allowlist. Scrub the
    OAuth token and autofill dies on prod — a security fix that takes the
    feature down is not a fix."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-live")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/root/.claude")
    env = _call(argv) and argv["kwargs"]["env"]
    assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat01-live"
    assert env.get("CLAUDE_CONFIG_DIR") == "/root/.claude", (
        "the CLI lost the config dir on the persistent volume")


def test_the_child_keeps_the_environment_it_needs_to_run(argv, monkeypatch):
    """`_cli_env` is a subtraction, not an allowlist, precisely so an
    unpredicted host doesn't lose PATH and fail with 'claude: not found'."""
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    monkeypatch.setenv("HOME", "/root")
    env = _call(argv) and argv["kwargs"]["env"]
    for name in ("PATH", "HOME"):
        assert name in env, f"{name} was stripped; the subprocess may not start"


def test_a_credential_added_later_is_scrubbed_without_touching_this_file(monkeypatch):
    """The point of the name pattern. A secret nobody has thought of yet is
    covered as long as it is NAMED like one — which is the house convention
    every existing credential already follows."""
    for invented in ("STRIPE_SECRET_KEY", "TWILIO_AUTH_TOKEN", "SMTP_PASSWORD",
                     "DATABASE_URL", "GCP_CREDENTIAL_JSON"):
        monkeypatch.setenv(invented, "x")
        assert invented not in main._cli_env(), (
            f"{invented} would reach the untrusted subprocess")


def test_there_is_still_only_one_place_that_builds_a_claude_argv():
    """A canary, deliberately source-level: the tests above secure the ONE
    construction site, and five call sites rely on it being the only one. A
    second `subprocess.run(["claude", ...])` elsewhere would be unguarded and
    invisible to every test in this file."""
    from pathlib import Path
    src = Path(main.__file__).read_text(encoding="utf-8")
    assert src.count('"claude", "-p"') == 1, (
        "another module now shells out to the Claude CLI; give it the same "
        "--tools/--strict-mcp-config treatment or route it through "
        "_autofill_via_cli")
