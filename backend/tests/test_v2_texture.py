"""An Epoxy sheet's texture on the v2 estimate (Hanz, 2026-10-27: "please put a texture setting in this").

WHAT CHANGED. The Material step of an Epoxy sheet (an Epoxy job's, a Combo's Epoxy sheet, an Epoxy option) has a Texture select
with the Proposal step's own choices. The pick is kept on the SECTION (`polish_estimate.tabs[id].texture`), so two Epoxy sheets
can differ. A save hands the Proposal step the PRICING BASE's texture (bid-model.js textureFill) while its `texture` is empty or
still the one last filled (`texture_from_estimate`); a texture picked on the Proposal step is never overwritten. Create Multiple
Proposals seeds each child with ITS base sheet's texture, and a Refresh moves it only while the child has not picked its own.

PROVEN BY EXECUTION. tests/js/v2-texture-harness.js boots js/polish-estimate.js whole on the real js/bid-model.js and reads what the
page drew, held and saved, including a reopen of the saved draft as jsonb hands it back. The proposal-step parity runs the real
proposal-review.js buildTextureControl through escape-page-text-harness.js. The server half runs drafts.fan_out_proposals and
refresh_proposals on the fake store. Every check is shown to go red when the change it covers is taken out.
"""
from __future__ import annotations

import copy
import pathlib

import pytest

import drafts
from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from test_multi_proposals import V2, _row, _seed, _tab

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "v2-texture-harness.js"
ESCAPE = TESTS / "js" / "escape-page-text-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]
CHOICES = ["", "Smooth", "Orange Peel", "Light", "Medium", "Heavy"]


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    return run()


def values(sel):
    return [o["value"] for o in sel["options"]]


# ── the select ────────────────────────────────────────────────────────────────
def test_an_epoxy_sheets_material_step_has_the_texture_select_with_the_proposal_steps_choices(ran):
    e = ran["epoxy"]
    assert e["step"] == 0
    assert e["select"] is not None, "the Epoxy sheet's Material step has no Texture select"
    assert values(e["select"]) == CHOICES and e["select"]["options"][0]["text"] == "—"
    assert e["select"]["value"] == "" and e["select"]["aria"] == "Texture"


def test_the_choices_are_the_proposal_steps_own(ran):
    """The real proposal-review.js buildTextureControl, run on an on-list texture, offers the same values in the same order."""
    proc = run_node(ESCAPE, FRONTEND)
    assert proc.returncode == 0, proc.stderr
    proposal = last_json_line(proc.stdout)["texture"]["proposal"]["onList"]["options"]
    assert [o["value"] for o in proposal] == CHOICES == values(ran["epoxy"]["select"])
    assert [o["text"] for o in proposal] == [o["text"] for o in ran["epoxy"]["select"]["options"]]


def test_only_an_epoxy_sheet_has_it(ran):
    assert ran["polish"]["select"] is None, "a Polish job's Material step"
    assert ran["combo"]["polishSelect"] is None, "a Combo's Polish sheet"
    assert ran["combo"]["epoxySelect"] is True, "a Combo's Epoxy sheet"
    assert ran["seal"]["panelIsSeal"] is True and ran["seal"]["select"] is None, "a Seal option"
    assert ran["option"]["select"] is True, "an Epoxy option is still an Epoxy sheet"


def test_an_off_list_texture_is_kept_as_its_own_option_and_escaped(ran):
    o = ran["offList"]
    assert values(o["select"])[:2] == ["", "Satin &lt;b&gt;&quot;glow&quot;&lt;/b&gt;"], "kept first, after the blank, escaped"
    assert values(o["select"])[2:] == CHOICES[1:]
    assert o["select"]["value"] == 'Satin <b>"glow"</b>' and o["rawTag"] is False


def test_a_pick_is_kept_on_the_section_saved_and_does_not_rebuild_the_panel(ran):
    e = ran["epoxy"]
    assert e["rebuiltOnPick"] is False, "the panel was rebuilt under the select, which throws the keyboard focus away"
    assert e["sectionTexture"] == e["savedSectionTexture"] == "Orange Peel"
    assert e["rootTexture"] == "absent", "the texture is the sheet's, not the model's"


def test_it_survives_a_jsonb_reload_and_clearing_takes_the_key_off(ran):
    r = ran["reload"]
    assert r["select"]["value"] == "Orange Peel" and r["sectionTexture"] == "Orange Peel"
    assert [o["value"] for o in r["select"]["options"] if o["selected"]] == ["Orange Peel"]
    assert r["savesOnOpen"] == 0, "reopening writes nothing"
    assert r["cleared"]["hasKey"] is False and r["cleared"]["saved"] is False


# ── the Proposal step's texture ──────────────────────────────────────────────
def test_the_proposal_step_gets_the_base_sheets_texture_and_follows_it(ran):
    assert ran["epoxy"]["proposal"] == {"texture": "Orange Peel", "from": "Orange Peel"}
    assert ran["reload"]["proposal"] == {"texture": "Orange Peel", "from": "Orange Peel"}
    assert ran["reload"]["afterRepick"] == {"texture": "Heavy", "from": "Heavy"}
    assert ran["reload"]["cleared"]["proposal"] == {"texture": "", "from": ""}


def test_a_texture_picked_on_the_proposal_step_is_never_overwritten(ran):
    assert ran["typed"]["section"] == "Smooth" and ran["typed"]["proposal"] == {"texture": "Medium", "from": "absent"}
    assert ran["movedOnProposal"]["section"] == "Heavy"
    assert ran["movedOnProposal"]["proposal"] == {"texture": "Light", "from": "Smooth"}
    # emptied there: the sheet's fills it again
    assert ran["emptiedOnProposal"]["proposal"] == {"texture": "Light", "from": "Light"}


def test_a_combo_uses_its_epoxy_sheet_and_an_epoxy_option_is_not_the_base(ran):
    c = ran["combo"]
    assert c["section"] == "Light" and c["proposal"] == {"texture": "Light", "from": "Light"}
    assert c["rootHasTexture"] is False
    o = ran["option"]
    assert o["section"] == "Medium" and o["proposal"] == {"texture": "absent", "from": "absent"}, (
        "an Epoxy option's texture is not the base bid's")


def test_the_models_rule(ran):
    m = ran["model"]
    assert [o["value"] for o in m["choices"]] == CHOICES and [o["value"] for o in m["none"]] == CHOICES
    assert [o["value"] for o in m["offList"]] == ["", "Velvet"] + CHOICES[1:]
    assert m["base"] == "Smooth"
    assert m["fillEmpty"] == {"texture": "Smooth", "texture_from_estimate": "Smooth"}
    assert m["fillTyped"] == {} and m["fillSame"] == {}
    assert m["fillNothing"] == {}, "a bid with no texture anywhere saves the keys it always did"
    assert m["fillCleared"] == {"texture": "", "texture_from_estimate": ""}


# ── each check goes red without its change ──────────────────────────────────
BREAKS = {
    "no select": ("js/polish-estimate.js", "var html = textureCard() + (gypSec ? gypCard(gypSec) : \"\");",
                  "var html = (gypSec ? gypCard(gypSec) : \"\");",
                  lambda o: o["epoxy"]["select"] is None),
    "pick not kept": ("js/polish-estimate.js", "if (v) e.section.texture = v; else delete e.section.texture;",
                      "if (false) e.section.texture = v; else delete e.section.texture;",
                      lambda o: o["epoxy"].get("sectionTexture") != "Orange Peel"),
    "rebuilt on pick": ("js/polish-estimate.js", "      setTexture(el.value);",
                        "      setTexture(el.value); renderPanel();",
                        lambda o: o["epoxy"]["rebuiltOnPick"] is True),
    "select on every sheet": ("js/polish-estimate.js", "    if (!e || e.role !== \"epoxy\") return \"\";\n    var cur",
                              "    if (!e) return \"\";\n    var cur",
                              None),
    "no proposal fill": ("js/bid-model.js", "    }, rest, textureFill(model, state));", "    }, rest);",
                         lambda o: o["epoxy"]["proposal"]["texture"] == "absent"),
    "typed overwritten": ("js/bid-model.js",
                          "    if (held === null || !(held === \"\" || (from !== null && held === from))) return {};",
                          "    if (held === null) return {};",
                          lambda o: o["typed"]["proposal"]["texture"] != "Medium"),
    "any base sheet": ("js/bid-model.js", "      if (list[i].role === \"epoxy\") return sectionTexture(list[i].section);",
                       "      return sectionTexture(list[i].section);",
                       lambda o: o["combo"]["proposal"]["texture"] != "Light"),
    "an option is the base": ("js/bid-model.js", "      if (!isBaseEntry(list[i])) continue;",
                              "      if (false) continue;",
                              lambda o: o["option"]["proposal"]["texture"] != "absent"),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_change_is_taken_out(tmp_path, name):
    require_node()
    rel, old, new, noticed = BREAKS[name]
    if "\n" in old:
        src = (FRONTEND / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")
        assert src.count(old) == 1, name
        target = tmp_path / "frontend" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.replace(old, new).encode("utf-8"))
        frontend = tmp_path / "frontend"
    else:
        frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend)
    if proc.returncode != 0:
        return                                               # a crash is the loudest way to go red
    out = last_json_line(proc.stdout)
    if noticed is None:                                      # the select drawn on sheets that are not Epoxy
        assert (out["polish"]["select"] is not None or out["seal"]["select"] is not None
                or out["combo"]["polishSelect"] is not None), "the checks did not notice: " + name
        return
    assert noticed(out), "the checks did not notice: " + name


# ── Create Multiple Proposals: each child starts with its base sheet's texture ──────────────────────────────────────
def _textured():
    data = copy.deepcopy(V2)
    data["polish_estimate"]["tabs"]["Copy1"]["texture"] = " Orange Peel "
    data["polish_estimate"]["tabs"]["Epoxy"]["texture"] = "Heavy"
    return data


def _fan_textured(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, _textured())
    out = drafts.fan_out_proposals("p1", ["Polish", "Copy1", "Epoxy"])
    lab2, lab1 = (_row(store, c["id"])["data"] for c in out["children"])
    return store, out, lab2, lab1


def test_fan_out_seeds_each_child_with_its_own_base_sheets_texture(fake_supabase, monkeypatch):
    store, _out, lab2, lab1 = _fan_textured(fake_supabase, monkeypatch)
    assert (lab2["texture"], lab2["texture_from_estimate"]) == ("Orange Peel", "Orange Peel")
    assert (lab1["texture"], lab1["texture_from_estimate"]) == ("Heavy", "Heavy")
    assert _row(store, "p1")["data"]["texture"] == "T", "the parent's own texture is not touched"


def test_a_child_whose_base_has_no_texture_gets_no_texture_key(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, copy.deepcopy(V2))
    out = drafts.fan_out_proposals("p1", ["Polish", "Copy1"])
    child = _row(store, out["children"][0]["id"])["data"]
    assert "texture" not in child and "texture_from_estimate" not in child


def test_refresh_follows_the_sheet_and_keeps_a_childs_own_texture(fake_supabase, monkeypatch):
    store, out, _lab2, _lab1 = _fan_textured(fake_supabase, monkeypatch)
    lab2_id, lab1_id = (c["id"] for c in out["children"])
    # Lab 1's estimator picks a texture on its own Proposal step
    _row(store, lab1_id)["data"]["texture"] = "Smooth"
    tabs = _row(store, "p1")["data"]["polish_estimate"]["tabs"]
    tabs["Copy1"]["texture"] = "Light"
    tabs["Epoxy"]["texture"] = "Medium"
    drafts.refresh_proposals("p1")
    lab2, lab1 = _row(store, lab2_id)["data"], _row(store, lab1_id)["data"]
    assert (lab2["texture"], lab2["texture_from_estimate"]) == ("Light", "Light"), "an untouched child follows its sheet"
    assert lab1["texture"] == "Smooth", "a texture picked on the child's Proposal step was overwritten by the refresh"
    # the sheet cleared: the untouched child empties with it
    del tabs["Copy1"]["texture"]
    drafts.refresh_proposals("p1")
    assert (_row(store, lab2_id)["data"]["texture"], _row(store, lab2_id)["data"]["texture_from_estimate"]) == ("", "")


def test_the_server_helpers():
    assert drafts._v2_texture(_textured(), "Copy1") == "Orange Peel"
    assert drafts._v2_texture(_textured(), "Polish") == ""
    assert drafts._v2_texture({"priced_tabs": [_tab("Epoxy", "epoxy", 1)]}, "Epoxy") == "", "a v1 draft"
    child = {}
    drafts._seed_texture(child, "")
    assert child == {}
    drafts._seed_texture(child, "Smooth")
    assert child == {"texture": "Smooth", "texture_from_estimate": "Smooth"}
    child["texture"] = "Heavy"
    drafts._seed_texture(child, "Light")
    assert child["texture"] == "Heavy"


def test_the_server_checks_go_red_without_the_change(fake_supabase, monkeypatch):
    # no seeding at fan-out or refresh
    monkeypatch.setattr(drafts, "_seed_texture", lambda child, texture: None)
    with pytest.raises((AssertionError, KeyError)):
        test_fan_out_seeds_each_child_with_its_own_base_sheets_texture(fake_supabase, monkeypatch)
    # a seed that ignores what the child picked
    monkeypatch.setattr(drafts, "_seed_texture", lambda child, texture: child.update(
        {"texture": texture, "texture_from_estimate": texture}))
    with pytest.raises(AssertionError):
        test_refresh_follows_the_sheet_and_keeps_a_childs_own_texture(fake_supabase, monkeypatch)
