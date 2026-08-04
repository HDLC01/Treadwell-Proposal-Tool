"""The proposal preview must survive a base-bid switch.

Reported from production 2026-08-04: an estimate built from the EPOXY template. Choosing the
Polish sheet as the base bid rendered correctly; switching BACK to the Epoxy sheet rendered
nothing at all in the PRICE box.

THE MECHANISM, because it is not obvious from the symptom. The live price rows
(`base-bid-row`, `total-row`, `rooms-block`, …) are real DOM nodes that live in
`#price-preview-staging` and are **moved** into the rendered document by
`mountRegionPreviews` — `appendChild` moves a node, it does not copy it. A re-render then
began with `docSurface.innerHTML = ""`, which DESTROYED them. `REGION_MOUNTS` re-resolves
them by `getElementById` on every render, so from that point on it got `null` and mounted
nothing — silently, because of its own `if (el)` guard.

WHY IT LOOKED ONE-DIRECTIONAL. Epoxy's PRICE box is built entirely from those mounted
regions, so it collapsed to an empty frame. Polish's base bid is a plain template paragraph,
so it still rendered and looked fine (only its tax rows were quietly missing). Hence "Polish
works, Epoxy doesn't".

`systemPreviewEl` / `notesPreviewEl` were never affected: they are held in JS consts, so a
wipe detaches them but the references survive. The id-addressed rows had no such anchor —
they needed somewhere to be detached TO, which is what `clearDocSurface()` now provides.

These are source-text assertions, the same style as test_followups_page.py and
test_drawer_followup.py: the bug is a DOM-lifetime bug, so it cannot be reproduced without a
browser. What CAN be pinned is the invariant that made it possible — that no code path wipes
the document surface without first reclaiming the islands.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
JS = FRONTEND / "js" / "proposal-review.js"


@pytest.fixture(scope="module")
def src():
    return JS.read_text(encoding="utf-8")


def test_the_file_is_there(src):
    """A rename would make every assertion below vacuously pass."""
    assert "REGION_MOUNTS" in src and "mountRegionPreviews" in src


def test_there_is_a_reclaiming_clear_helper(src):
    assert "function clearDocSurface()" in src, (
        "clearDocSurface is the only thing standing between a re-render and the "
        "blank-preview bug")


def _code_only(src: str) -> str:
    """Source with `//` comments stripped.

    Needed because the explanation of this bug necessarily quotes the very line it forbids,
    so a naive count matches its own documentation. (Made exactly this mistake once already
    in test_deploy_pipeline.py, where the prose explaining an outage contained the flag the
    test banned.) Line comments are enough — the offending pattern never appears in a block
    comment or a string."""
    return "\n".join(ln.split("//", 1)[0] for ln in src.splitlines())


def test_no_code_path_wipes_the_surface_without_reclaiming_first(src):
    """THE rule. Any new `docSurface.innerHTML = ""` outside the helper reintroduces the
    bug, and it would look like a rendering problem rather than a lifetime one."""
    wipes = re.findall(r'docSurface\.innerHTML\s*=\s*""', _code_only(src))
    assert len(wipes) == 1, (
        f"found {len(wipes)} direct surface wipes; there must be exactly one, inside "
        f"clearDocSurface(). Route new ones through that helper.")
    # And that one lives in the helper: take the helper's body and check it's there.
    body = src[src.index("function clearDocSurface()"):]
    body = body[:body.index("\n  }") + 4]
    assert 'docSurface.innerHTML = ""' in body


def test_both_render_paths_use_the_helper(src):
    """The positioned renderer and the flow fallback both clear the surface. Fixing one and
    not the other leaves the bug alive on whichever path a failing template takes."""
    for fn in ("function renderPositioned(", "function renderFlow("):
        i = src.index(fn)
        block = src[i:i + 900]
        assert "clearDocSurface()" in block, f"{fn} does not reclaim before clearing"


def test_every_id_mounted_by_a_region_is_reclaimed(src):
    """The two lists have to agree. An id added to REGION_MOUNTS but not to ISLAND_IDS is a
    node that gets destroyed on the next render — the original bug, one element at a time."""
    mounts = src[src.index("const REGION_MOUNTS = {"):src.index("// ── keeping the mounted")]
    mounted = set(re.findall(r'getElementById\("([a-z-]+)"\)', mounts))
    mounted |= set(re.findall(r'"([a-z-]+)"(?=,\s*"|\s*\]\s*\n\s*\.map)', mounts))
    ids_block = src[src.index("const ISLAND_IDS = ["):]
    ids_block = ids_block[:ids_block.index("];") + 2]
    reclaimed = set(re.findall(r'"([a-z-]+)"', ids_block))
    missing = mounted - reclaimed
    assert not missing, f"mounted but never reclaimed (will be destroyed on re-render): {missing}"


def test_the_staging_panel_itself_is_put_back(src):
    """The error path re-parents the whole staging panel INTO the surface. Without putting it
    back, the next successful render deletes the staging area and every island with it —
    the same bug one level up."""
    body = src[src.index("function clearDocSurface()"):]
    body = body[:body.index("\n  }") + 4]
    assert "stagingHome" in body


def test_a_failed_render_is_not_silent(src):
    """This is why the bug took so long to find. The only user-facing hook was #doc-loading,
    which lives inside #doc-surface and is destroyed by the first successful render — so a
    failure on any LATER render showed nothing and logged nothing."""
    i = src.index("Proposal preview failed to render")
    assert "console.error" in src[i - 120:i + 60], "the render failure is not logged"


def test_a_failed_re_render_can_still_show_a_message(src):
    """Not just logged — visible. The catch has to be able to CREATE its message node,
    because the original one no longer exists by then."""
    catch = src[src.index("Proposal preview failed to render"):]
    catch = catch[:2000]
    assert 'createElement("div")' in catch and 'doc-loading' in catch, (
        "the error path cannot rebuild its message node, so a late failure is invisible")


def test_the_reload_comment_no_longer_claims_idempotence(src):
    """The comment on reloadForWorkType asserted initDocumentEditor was "idempotent and safe
    to re-run". That claim is what licensed the bug, and a future reader acting on it would
    reintroduce it."""
    i = src.index("function reloadForWorkType()")
    comment = src[max(0, i - 1400):i]
    assert "idempotent and recomputes tokens" not in comment, (
        "the false idempotence claim is back in the comment above reloadForWorkType")


def test_the_terms_band_cache_is_keyed_by_work_type(src):
    """Templates reuse PNG filenames (image1.png) — which is exactly why artUrl() keys its
    cache by work type, and says so. measureTermsBand did not, so a base-bid switch reserved
    the previous template's top band on the T&C page."""
    i = src.index("function measureTermsBand(")
    block = src[i:i + 300]
    assert "effectiveWorkType()" in block, (
        "measureTermsBand keys on the media name alone; templates share image1.png")
