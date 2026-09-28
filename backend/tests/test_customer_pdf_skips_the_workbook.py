"""The customer's PDF stops building a 653 KB workbook it never opens.

/api/admin/proposal-pdf is the route a customer's browser waits on when they click through to
their proposal. It reran the WHOLE generate pipeline -- estimate workbook included -- then read
`docx_download_url` and nothing else. The .xlsx was filled, cached under a token no one would ever
request, and expired unread, while the customer watched a spinner for about 3.2s of the ~3.5s the
request took.

WHAT THIS FILE HAS TO PROVE IS NOT THE SPEED. It is that the document did not change. A faster
render that hands a customer a different proposal is a far worse bug than a slow one, so the
headline test compares the exact bytes reaching the PDF renderer, with and without the workbook.

THIS IS NOT `want_cover_letter` COMING BACK. That flag changed the DOCUMENT: a customer received a
proposal with its first page missing and no way to tell. It was removed for that reason, and the
removal should stand. `want_estimate` changes no document -- only whether a file nobody reads is
built -- and the first test here is what makes that difference a fact rather than a claim.
"""
import io
import zipfile

import main
import pytest
from fastapi.testclient import TestClient

client = TestClient(main.app)

BASE = {
    "work_type": "polish",
    "audience": "GC",
    "values": {"job_name": "Skip The Workbook", "city_state": "Lenexa, KS",
               "polish_sf": "1000", "lump_sum": "$10,000"},
}


@pytest.fixture
def portal(monkeypatch):
    """The customer PDF route, with LibreOffice replaced by the identity function.

    docx_to_pdf returning its input is what makes the headline test possible: the response body
    IS the .docx that would have been rendered, so it can be compared byte for byte against the
    one the ordinary generate path produces. Stubbing the renderer is also the only way to run
    this at all -- LibreOffice is not installed on a CI runner."""
    calls = {"fill_estimate": 0}
    real_fill = main.estimate_writer.fill_estimate

    def counting_fill(*a, **k):
        calls["fill_estimate"] += 1
        return real_fill(*a, **k)

    monkeypatch.setattr(main.estimate_writer, "fill_estimate", counting_fill)
    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", lambda b: b)
    monkeypatch.setenv("SERVICE_TOKEN", "test-token")
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda did: {"data": {"project_name": "Skip The Workbook",
                                              "proposal_payload": BASE}})
    return calls


def _customer_docx(calls):
    r = client.get("/api/admin/proposal-pdf?draft_id=d1",
                   headers={"x-service-token": "test-token"})
    assert r.status_code == 200, r.text
    return r.content


def _estimator_docx():
    r = client.post("/api/generate", json=BASE)
    assert r.status_code == 200, r.text
    assert r.json()["xlsx_download_url"], "the estimator's own generate must still yield a workbook"
    return client.get(r.json()["docx_download_url"]).content


def test_the_customer_gets_the_same_document_byte_for_byte(portal, monkeypatch):
    """THE ONE THAT MATTERS. Skipping the workbook must not change a single byte of what the
    customer receives.

    Mutation: make want_estimate=False also skip something the .docx is built from, and this goes
    red rather than silently shipping a different proposal.

    THE COMPARISON IS THE SAME ROUTE WITH THE FLAG FLIPPED, and it has to be. Comparing this
    route against /api/generate looks equivalent and is not: the estimator's route knows who is
    signed in and fills {{estimator_name}}, while the server-to-server customer route has no user
    and leaves whatever the frozen payload carried. Those two documents differ by design, for a
    reason that has nothing to do with this change, so that comparison would fail forever and
    prove nothing. Forcing want_estimate=True through the SAME handler isolates the one variable.
    """
    real_generate = main._generate

    def forced(payload, request, **kw):
        kw["want_estimate"] = True          # override what the route asked for
        return real_generate(payload, request, **kw)

    monkeypatch.setattr(main, "_generate", forced)
    with_workbook = _customer_docx(portal)
    monkeypatch.setattr(main, "_generate", real_generate)
    without_workbook = _customer_docx(portal)

    # NOT a whole-file byte compare, and the reason is worth writing down: python-docx stamps
    # dcterms:modified into docProps/core.xml, so two renders that straddle a second boundary
    # differ by a few bytes at identical length. That assertion passes or fails on the clock,
    # which is the definition of a flaky test. Comparing every entry INDIVIDUALLY and excluding
    # only the timestamp file is both stabler and stricter: anything else that moves is named.
    VOLATILE = {"docProps/core.xml"}
    za = zipfile.ZipFile(io.BytesIO(with_workbook))
    zb = zipfile.ZipFile(io.BytesIO(without_workbook))
    assert za.namelist() == zb.namelist(), "the document gained or lost a part"
    differing = [n for n in za.namelist()
                 if n not in VOLATILE and za.read(n) != zb.read(n)]
    assert not differing, (
        "skipping the workbook changed the customer's document in: %s" % ", ".join(differing))
    # word/document.xml is the page itself. Named explicitly so that shrinking VOLATILE's
    # complement later cannot quietly stop checking the part that matters.
    assert za.read("word/document.xml") == zb.read("word/document.xml")


def test_the_workbook_is_not_built_for_the_customer_pdf(portal):
    """The saving itself. fill_estimate is the ~3.2s call, so 'not called' is the whole change.

    Mutation: drop want_estimate=False at the /api/admin/proposal-pdf call site."""
    _customer_docx(portal)
    assert portal["fill_estimate"] == 0, (
        "the customer PDF still filled the estimate workbook %d time(s)" % portal["fill_estimate"])


def test_the_estimators_own_generate_still_builds_one(portal):
    """The negative half, and not symmetry for its own sake: a flag defaulting the wrong way would
    take the .xlsx off the Done screen, where an estimator genuinely downloads it."""
    _estimator_docx()
    assert portal["fill_estimate"] == 1, (
        "expected exactly one workbook fill on the estimator's path, got %d"
        % portal["fill_estimate"])


def test_no_workbook_means_no_download_url_rather_than_a_broken_one():
    """An empty string, not '/api/file/'. A bare prefix is a link that looks real and 404s, which
    reads as a broken download instead of an absent one.

    Mutation: return f"/api/file/{xlsx_token}" unconditionally."""
    import inspect
    src = inspect.getsource(main._generate)
    assert 'xlsx_download_url=f"/api/file/{xlsx_token}" if xlsx_token else ""' in src, (
        "the empty-token guard on xlsx_download_url is gone")


def test_only_the_customer_pdf_opts_out_of_the_workbook():
    """The revision download returns the workbook's link, To-Dropbox uploads it by name and the
    Files page's downloads offer it. If any of them ever passed want_estimate=False it would file
    an empty-named download or upload nothing, so the opt-out is pinned to the two call sites that
    read the .docx alone: the customer's PDF, and Send, which freezes that PDF (2026-09-25).

    Mutation: add want_estimate=False to the revision, To-Dropbox or Files-page caller."""
    import pathlib
    src = pathlib.Path(main.__file__).read_text(encoding="utf-8", errors="replace")
    # The trailing paren is what makes this count CALL SITES. Without it this docstring and the
    # comment above the call match too, and the test passes at 3 while meaning nothing.
    assert src.count("want_estimate=False)") == 2, (
        "expected exactly two callers to skip the workbook, found %d"
        % src.count("want_estimate=False)"))
    import inspect
    for name in ("api_admin_proposal_pdf", "api_portal_publish"):
        assert "want_estimate=False)" in inspect.getsource(getattr(main, name)), name
    for name in ("api_draft_revision_files", "api_to_dropbox", "api_draft_documents"):
        assert "want_estimate=False)" not in inspect.getsource(getattr(main, name)), (
            "%s skips the workbook it hands out" % name)
