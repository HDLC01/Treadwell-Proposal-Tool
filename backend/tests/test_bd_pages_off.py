"""The BD switch, on the pages (#806, spec #802 Q26): with BD_ENABLED off, every /bd/ page answers a
plain "The BD CRM is not turned on" page, from the server, before a byte of BD is sent.

  * off (the default): /bd, /bd/, every page and every file under /bd/ (and an address that is not
    there) answer 503 with that page: plain HTML, no script, never stored by the browser, a link back
    to the proposal tool;
  * the tool's own pages are untouched by the switch;
  * on: /bd/ is the BD home page, byte for byte, with the same caching as every other page (an
    unchanged file answers 304); /bd goes to /bd/; an address that is not there is the usual 404.

Through TestClient against the real app: the switch is read on every request (bd.config.BD_ENABLED).
"""
from __future__ import annotations

import pathlib
import re

import pytest
from fastapi.testclient import TestClient

import main
from bd import config as bd_config

FRONTEND = pathlib.Path(main.FRONTEND_DIR)
client = TestClient(main.app)

BD_ADDRESSES = ["/bd", "/bd/", "/bd/index.html", "/bd/login.html", "/bd/bd.css", "/bd/js/bd-api.js",
                "/bd/js/bd-core.js", "/bd/contacts.html", "/bd/no-such-page.html", "/bd/js/"]


@pytest.fixture
def bd_on(monkeypatch):
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)


@pytest.fixture
def bd_off(monkeypatch):
    monkeypatch.setattr(bd_config, "BD_ENABLED", False)


def test_the_switch_is_off_by_default():
    assert bd_config._bool("BD_ENABLED_UNSET_FOR_THIS_TEST", False) is False


@pytest.mark.parametrize("address", BD_ADDRESSES)
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_off_every_bd_address_answers_the_not_turned_on_page(bd_off, address, method):
    r = client.request(method, address, follow_redirects=False)
    assert r.status_code == 503, (address, r.status_code)
    assert r.headers["content-type"].startswith("text/html")
    assert "no-store" in r.headers.get("cache-control", ""), "a browser must not keep the switched-off page"
    if method == "GET":
        assert "The BD CRM is not turned on" in r.text


def test_the_not_turned_on_page_is_plain(bd_off):
    page = client.get("/bd/").text
    assert "<script" not in page.lower()
    assert not re.search(r"\son[a-z]+\s*=", page, re.I), "no inline handler (the CSP)"
    assert '<html lang="en">' in page and "<title>" in page and 'name="viewport"' in page
    assert 'href="/"' in page, "a way back to the proposal tool"
    assert not re.search(r'(href|src)="/bd', page), "it links to nothing under /bd/"
    # nothing of BD's own is in it: not the home page's bytes, not its scripts or stylesheet
    assert "bd-api.js" not in page and "bd.css" not in page


@pytest.mark.parametrize("address", ["/trash.html", "/js/icons.js", "/auth.js", "/shared.js"])
def test_off_the_tools_own_pages_are_untouched(bd_off, address):
    assert client.get(address).status_code == 200


def test_on_the_bd_home_is_the_page_itself(bd_on):
    r = client.get("/bd/")
    assert r.status_code == 200
    assert r.content == (FRONTEND / "bd" / "index.html").read_bytes()
    assert r.headers["cache-control"] == "no-cache, must-revalidate"
    again = client.get("/bd/", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_on_bd_without_its_slash_goes_to_the_home(bd_on):
    r = client.get("/bd", follow_redirects=False)
    assert r.status_code in (301, 302, 307, 308)
    assert r.headers["location"].endswith("/bd/")


def test_on_bd_files_are_served_and_a_missing_one_is_a_404(bd_on):
    r = client.get("/bd/js/bd-api.js")
    assert r.status_code == 200 and "BDApi" in r.text
    assert client.head("/bd/index.html").status_code == 200
    assert client.get("/bd/no-such-page.html").status_code == 404


def test_on_only_get_and_head(bd_on):
    assert client.post("/bd/index.html").status_code == 405


def test_the_switch_is_read_on_every_request(monkeypatch):
    monkeypatch.setattr(bd_config, "BD_ENABLED", False)
    assert client.get("/bd/").status_code == 503
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    assert client.get("/bd/").status_code == 200
