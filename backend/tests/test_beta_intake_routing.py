"""Getting into the polish beta from intake, and back into it from the Projects page.

Hanz, 2026-08-17: *"When I click on intake on the Polish beta then click on the red button below
it leads me to the old estimate sheet with excel not the Beta. So add another button for the Beta
Estimating sheet / or the New estimate calculator not using the excel estimate sheet."*

The red button is right to do that. It belongs to the SPREADSHEET workflow, per his earlier rule
("The current polish excel sheet and the beta shuold be two different workflows okay?"), and
test_polish_estimate_page.py::test_the_old_estimate_review_still_exists_and_is_untouched_as_a_route
pins its target. So the fix is a SECOND button, and the thing to prove is that the two doors stay
told apart:

  * the beta button saves the project and walks into /polish-intake.html;
  * the red one still walks into /estimate-review.html;
  * only a polish job is offered the beta at all;
  * and a beta project resumed from the Projects page opens on the beta intake, not on the live
    one, because there is no spreadsheet behind its numbers.

EXECUTED, NOT GREPPED. Both handlers navigate and both destinations are strings in one file, so a
grep cannot tell you which handler holds which — and crossing the two is the likeliest mistake
anyone makes here. `tests/js/beta-routing-harness.js` runs the real index.js top to bottom against
a DOM stub, flips the real radios, fires the real handlers, and reports where the page went. The
same harness executes the real `open()` out of projects.js. See its header for why each check has
to be run rather than read.

The Python half covers the flag that router reads. It has TWO producers in drafts.py — the
PostgREST projection (fast path, TEXT) and `_summary` (fallback, parsed JSON) — and they must
answer the same question about the same draft or "resume" would depend on which read path served
the page.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import drafts

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "beta-routing-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the button exists, is wired, and is styled by something real ─────────────
@needs_node
def test_the_beta_button_is_on_the_page_and_has_a_handler(ran):
    """`document.getElementById` in the harness returns null for an id index.html does not
    carry, so a typo'd or deleted button shows up here as "nothing was ever wired" rather than
    as a page that renders and does nothing when clicked."""
    assert ran["boot"]["buttonIsInTheMarkup"], "#beta-continue is not in index.html"
    assert ran["boot"]["clickListeners"] == 1, (
        "the beta button has %d click handlers" % ran["boot"]["clickListeners"])
    assert ran["boot"]["typeIsButton"], (
        'the beta button is not type="button", so it submits the form and the browser follows '
        "the spreadsheet handler instead")


@needs_node
def test_it_is_the_lesser_action_next_to_the_red_one(ran):
    """A second primary would put two red buttons in the bar and settle nothing. The class also
    has to be one the stylesheet defines, or the button ships unstyled."""
    assert ran["boot"]["className"] == "btn-secondary", ran["boot"]["className"]
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert ".btn-secondary {" in css, "btn-secondary is not defined in styles.css"


@needs_node
def test_the_label_names_the_calculator_and_is_marked_beta(ran):
    """Same posture as the sidebar entry and the estimate-review link: an unmarked door reads as
    a finished feature. The chip class comes from auth.js's injected stylesheet, which every page
    that loads auth.js gets."""
    label = ran["boot"]["label"] or ""
    assert "Continue with Beta Calculator" in label, label
    assert ">BETA<" in label, "the button is not marked BETA: %r" % label
    assert "—" not in label, "em dash in UI copy (house rule)"
    auth = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    assert ".tw-nav-tag{" in auth, "the chip class the button uses is not defined in auth.js"


# ── who is offered the beta ──────────────────────────────────────────────────
@needs_node
def test_the_button_ships_hidden(ran):
    """Before any script runs the work type is epoxy (the checked radio), and there is no beta
    calculator for an epoxy bid. The estimate-review beta link learned this the hard way: an
    element that is only hidden by JS is visible for as long as the JS takes to arrive."""
    assert ran["boot"]["shipsHidden"], "#beta-continue is not display:none in the markup"


@needs_node
def test_only_a_polish_job_is_offered_the_beta(ran):
    """Driven through the REAL syncScopeToWorkType by flipping the real radios and firing their
    real change listener — not by re-stating the rule here, which would only prove the test
    agrees with itself."""
    v = ran["visibility"]
    assert v["polish"] != "none", "a polish job is not offered the beta calculator"
    for wt in ("epoxy", "combo", "gyp"):
        assert v[wt] == "none", (
            "%s jobs are offered a beta calculator that cannot price them" % wt)


@needs_node
def test_the_door_comes_back_when_the_work_type_comes_back(ran):
    """Hidden, never removed — the convention the quantity fields on this page already follow.
    A removed button would also lose its listener, so both are checked."""
    assert ran["visibility"]["polishAgainAfterEpoxy"] != "none"
    assert ran["visibility"]["buttonStillWired"] == 1, (
        "the button was re-created rather than re-shown, so its click handler is gone")


@needs_node
def test_the_live_intake_still_gates_its_fields_the_way_it_did(ran):
    """The visibility hook went INSIDE syncScopeToWorkType, which is also what shows the gyp
    buckets and the per-work-type quantity fields. Read off the rendered nodes after the real
    function ran, so a hook that broke its host fails here."""
    live = ran["liveIntakeUnchanged"]
    assert live["epoxy"]["shownScopes"] == ["epoxy", "cove"]
    assert live["polish"]["shownScopes"] == ["polish"], "polish is being asked for cove again"
    assert live["combo"]["shownScopes"] == ["epoxy", "polish", "cove"]
    assert live["gyp"]["shownScopes"] == []
    assert live["gyp"]["gypBuckets"] != "none" and live["gyp"]["systems"] == "none"
    assert live["epoxy"]["gypBuckets"] == "none"


# ── where each door goes ─────────────────────────────────────────────────────
@needs_node
def test_the_beta_door_goes_to_the_beta_intake_with_the_draft_id(ran):
    """Through the real TW.withDraft (lifted out of shared.js), because shared.js's anchor
    rewriter covers the four wizard pages only — a bare path opens the beta with no project."""
    assert ran["nav"]["beta"] == ["/polish-intake.html?d=d1e2f3a4"], ran["nav"]["beta"]


@needs_node
def test_the_red_button_still_goes_to_the_spreadsheet(ran):
    """THE regression this file exists for, from the other side. Both destinations live in one
    file; only running both handlers can tell you they are not crossed."""
    assert ran["nav"]["submit"] == ["/estimate-review.html?d=d1e2f3a4"], ran["nav"]["submit"]


@needs_node
def test_the_two_doors_do_not_share_a_destination(ran):
    assert ran["nav"]["beta"] != ran["nav"]["submit"]
    assert "/estimate-review.html" not in ran["nav"]["beta"][0]
    assert "/polish-intake.html" not in ran["nav"]["submit"][0]


# ── both doors save the same project ────────────────────────────────────────
@needs_node
def test_the_beta_door_saves_the_project_before_it_leaves(ran):
    """Otherwise the beta intake opens on whatever was in localStorage from last time."""
    assert ran["saves"]["betaCount"] == 1, "the beta handler saved %d times" % ran["saves"]["betaCount"]
    saved = ran["saves"]["beta"]
    assert saved["project_name"] == "Nearman Creek Polish"
    assert saved["polish_sf"] == 2875, "the quantity was saved as a string, not a number"


@needs_node
def test_the_two_handlers_save_byte_for_byte_the_same_blob(ran):
    """The beta handler carries its own copy of the composition (the submit handler owns the live
    path for epoxy, combo and gyp and was not restructured for the beta's sake). This is what
    stops the two copies drifting: edit one and not the other, and this fails."""
    assert ran["saves"]["identical"], (
        "the two doors save different state.\nbeta-only keys: %s\nsubmit-only keys: %s\n"
        "beta: %s\nsubmit: %s" % (ran["saves"]["betaOnlyKeys"], ran["saves"]["submitOnlyKeys"],
                                  ran["saves"]["beta"], ran["saves"]["submit"]))


@needs_node
def test_the_composition_the_estimate_sheet_depends_on_survives_the_beta_door(ran):
    """city_state feeds the sheet's C3, the proposal's {{city_state}} and the tax lookup;
    `deadline` is what the Projects list, the bell's reminders and the folder date read."""
    saved = ran["saves"]["beta"]
    assert saved["city_state"] == "Overland Park, KS", saved["city_state"]
    assert saved["deadline"] == saved["bid_date"] and saved["deadline"], saved["deadline"]
    assert saved["work_type"] == "polish"
    assert saved["num_systems"] == 2


@needs_node
def test_the_beta_door_is_not_a_way_round_the_required_fields(ran):
    """type="button" never triggers the browser's own check, so without reportValidity() the
    beta path would accept a project with no name and no bid date where Continue refuses."""
    v = ran["validation"]
    assert v["asked"] == 1, "the beta handler never validated the form"
    assert v["navigated"] == 0, "an invalid form still navigated to the beta"
    assert v["saved"] == 0, "an invalid form was saved anyway"


# ── resuming a project from the Projects page ───────────────────────────────
@needs_node
def test_a_beta_project_resumes_on_the_beta_intake(ran):
    """The real `open()` out of projects.js, executed. It is what every card and every table row
    navigates through."""
    assert ran["projectsOpen"]["beta"] == "/polish-intake.html?d=beta-1"


@needs_node
def test_every_other_project_still_resumes_on_the_live_intake(ran):
    """The swapped-branch failure: sending spreadsheet bids to the beta intake would be a worse
    bug than the one being fixed. `polish_beta: false` and a row with no flag at all (which is
    every project that existed before this shipped) both stay put."""
    assert ran["projectsOpen"]["sheet"] == "/?d=sheet-1&edit=1"
    assert ran["projectsOpen"]["legacy"] == "/?d=legacy-1&edit=1"
    assert ran["projectsOpen"]["unknown"] == "/?d=never-heard-of-it&edit=1", (
        "a project that is not in the in-memory list broke the router instead of falling back")


@needs_node
def test_the_id_reaches_the_url_still_encoded(ran):
    """Ids arrive already encodeURIComponent'd from the card markup; the lookup has to decode to
    match the record without un-encoding what goes in the URL."""
    assert ran["projectsOpen"]["encodedBeta"] == "/polish-intake.html?d=beta%202"


# ══ the flag itself: backend/drafts.py ══════════════════════════════════════
# Two producers, one question. The fast path selects a jsonb scalar and gets TEXT; the fallback
# reads the parsed blob and gets an int. A fake that returned whole rows would let the fast path
# read None for every project and pass without the projection existing at all, so this one applies
# the projection the way PostgREST does.
def _as_text(v):
    """PostgREST's `->>`: the JSON value rendered as TEXT, or SQL NULL."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return v
    return json.dumps(v)


def _extract(row, expr):
    """Evaluate a `data->a->>b` selector against a row, like PostgREST does."""
    tokens = re.findall(r"->>|->|[A-Za-z_][A-Za-z0-9_]*", expr)
    cur, last_op = row.get(tokens[0]), None
    i = 1
    while i < len(tokens) - 1:
        last_op, key = tokens[i], tokens[i + 1]
        cur = (cur or {}).get(key) if isinstance(cur, dict) else None
        i += 2
    return _as_text(cur) if last_op == "->>" else cur


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, rows):
        self.rows, self.cols = rows, "*"

    def select(self, cols="*"):
        self.cols = cols
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def in_(self, k, vals):
        self.rows = [r for r in self.rows if r.get(k) in list(vals)]
        return self

    def eq(self, k, v):
        self.rows = [r for r in self.rows if r.get(k) == v]
        return self

    @property
    def not_(self):
        self._negate = True
        return self

    def is_(self, k, v):
        neg = getattr(self, "_negate", False)
        self._negate = False
        self.rows = [r for r in self.rows if (r.get(k) is not None) == neg]
        return self

    def execute(self):
        if self.cols == "*":
            return _Result(list(self.rows))
        out = []
        for row in self.rows:
            shaped = {}
            for entry in [c.strip() for c in self.cols.split(",") if c.strip()]:
                if ":" in entry:
                    alias, expr = entry.split(":", 1)
                    shaped[alias] = _extract(row, expr.strip())
                else:
                    shaped[entry] = row.get(entry)
            out.append(shaped)
        return _Result(out)


class _Client:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Table(list(self.store.get(name, [])))


DRAFTS = [
    # The beta, saved from the browser where JSON numbers can arrive either way.
    {"id": "int-2", "data": {"project_name": "Beta Int",
                             "polish_estimate": {"version": 2, "areas": [{"sf": 2875}]}}},
    {"id": "str-2", "data": {"project_name": "Beta Str",
                             "polish_estimate": {"version": "2", "areas": []}}},
    # A v1 polish estimate: the spreadsheet workflow, priced through the workbook.
    {"id": "v1", "data": {"project_name": "Sheet Polish", "polish_estimate": {"areas": []}}},
    # Every other project in the database.
    {"id": "plain", "data": {"project_name": "Epoxy Job", "work_type": "epoxy"}},
]
for _r in DRAFTS:
    _r.update({"owner_email": "kyle@wetreadwell.com", "created_at": "2026-08-01",
               "updated_at": "2026-08-02", "deleted_at": None})

EXPECTED = {"int-2": True, "str-2": True, "v1": False, "plain": False}


@pytest.fixture()
def fast(monkeypatch):
    """The fast projection path, run for real against a PostgREST-shaped fake."""
    monkeypatch.setattr(drafts, "get_client",
                        lambda: _Client({"drafts": [dict(r) for r in DRAFTS]}))
    return {row["id"]: row for row in drafts._build_summaries(False, 300)}


def test_the_fake_hands_the_fast_path_text_the_way_postgrest_does():
    """If this fake returned an int, `_polish_beta` would never be tested against the string the
    production read path actually produces, and the coercion could be dropped unnoticed."""
    assert _extract(DRAFTS[0], "data->polish_estimate->>version") == "2"
    assert _extract(DRAFTS[0], "data->>project_name") == "Beta Int"
    assert _extract(DRAFTS[3], "data->polish_estimate->>version") is None


@pytest.mark.parametrize("pid,expect", sorted(EXPECTED.items()))
def test_the_projection_path_reports_whether_a_draft_is_a_beta_bid(fast, pid, expect):
    assert fast[pid]["polish_beta"] is expect


@pytest.mark.parametrize("pid,expect", sorted(EXPECTED.items()))
def test_the_fallback_shaper_reports_it_too(pid, expect):
    """_build_summaries drops to a full-blob read on any PostgREST quirk. If only the fast path
    knew about this flag, resuming a beta project would open the spreadsheet intake in exactly
    the conditions where somebody is already debugging something else."""
    row = next(r for r in DRAFTS if r["id"] == pid)
    assert drafts._summary(row)["polish_beta"] is expect


@pytest.mark.parametrize("pid", sorted(EXPECTED))
def test_the_two_read_paths_agree_about_every_draft(fast, pid):
    """One reads TEXT out of jsonb, the other a Python dict. Disagreement would make "resume"
    depend on which read path served the page — the worst kind of intermittent."""
    row = next(r for r in DRAFTS if r["id"] == pid)
    assert fast[pid]["polish_beta"] is drafts._summary(row)["polish_beta"]


@pytest.mark.parametrize("raw,expect", [
    (2, True), ("2", True), (" 2 ", True), ("2.0", True),
    (1, False), ("1", False), (3, False), ("3", False),
    (None, False), ("", False), ("null", False), ("v2", False), ("banana", False),
    (True, False), (False, False), ({}, False),
])
def test_the_version_coercion_reads_a_string_and_a_number_the_same_way(raw, expect):
    """One helper for both paths, so they cannot drift. `True` is not version 2 — a bool arriving
    here means somebody stored the wrong thing, and guessing would file the project wrongly."""
    assert drafts._polish_beta(raw) is expect


def test_the_list_payload_does_not_carry_the_whole_polish_estimate(fast):
    """polish_estimate holds every area, material and crew line for the bid, and this list is
    read 300 rows at a time on every Projects page load. One scalar, not the object — the same
    rule has_files follows."""
    blob = json.dumps(fast["int-2"])
    assert "areas" not in blob, "the polish_estimate object is being shipped in the list payload"
    assert fast["int-2"]["polish_beta"] is True


def test_adding_the_flag_did_not_disturb_the_rest_of_the_card(fast):
    """The projection is one string; a mis-placed comma there empties a column on the Projects
    page rather than failing loudly."""
    row = fast["plain"]
    assert row["project_name"] == "Epoxy Job"
    assert row["work_type"] == "epoxy"
    assert row["archived"] is False
    assert row["is_test"] is None, "the tri-state collapsed to a bool"
    assert row["owner_email"] == "kyle@wetreadwell.com"
    assert row["total"] is None
    assert row["has_files"] is False
