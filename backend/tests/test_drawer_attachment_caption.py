"""An attachment in the drawer thread has to say its own name, on the red bubble as well as the grey.

Hanz, 2026-08-26, on the staff drawer chat: "when sending out files and images, also fix how this
looks I cant see the name of the file well."

WHAT HE WAS LOOKING AT. Two separate faults in one screenshot, and only one of them was the
placeholder. The tile's whole content was `<img alt="Check-PNG-Image-File.png">` with no src, and a
src-less img is exactly how a browser draws a BROKEN image: a torn-page icon plus the alt text, laid
out inline. `.att-img` set no colour and no text-decoration of its own, so that alt text was painted
in the user agent's link colour with the user agent's underline -- BLUE AND UNDERLINED, on a dark red
bubble. The first half is a render bug; the second half is why it was illegible.

AND THE NAME WAS ONLY EVER IN A TOOLTIP. He reads this thread out in the sales meeting. A `title`
is no use to somebody who is not holding a mouse over each tile in turn, so every attachment carries
a VISIBLE caption now -- image tiles included, not just the chips that always had one.

TWO KINDS OF TEST, because two different things can break:

  * The renderer and its three states are EXECUTED, through drawer-render-harness.js. A
    source-text assertion cannot see an unbound identifier, and one of those took the production
    board down on 2026-08-12 with every test green.
  * The colours are resolved through the CASCADE, weight first and source order only as the
    tie-break. This is the fourth time this repo has been bitten by a cue that was declared and
    could never apply -- a class `display` rule beating the `hidden` attribute, `opacity: 0` still
    taking clicks, and an id-weighted tab tint beating three class-weighted state rules. A regex
    for "is the rule in the file" would have passed on all three.

WHAT THESE CANNOT SAY. The harness answers querySelector out of the markup the renderer just wrote,
so it proves what was rendered and mutated, not layout. The cascade tests read declared values, so
they prove which declaration wins, not what a GPU painted. The contrast ratios in the comments were
computed against the composited surfaces; they are recorded here so a later edit can see what floor
it is standing on.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "drawer-render-harness.js"
HTML = FRONTEND / "portal.html"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def att():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    # encoding="utf-8" explicitly: this box's locale is cp1252 and the drawer is full of characters
    # that bare text=True turns into mojibake or an outright decode error.
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert not out["errors"], out["errors"]
    return out["att"]


# ── 1. the caption exists, and it is the filename ────────────────────────────

@needs_node
def test_an_image_tile_shows_its_filename_as_text_not_as_a_tooltip(att):
    """THE ASK. The name has to be readable without hovering, so it is text inside the tile.

    Asserted as the text BETWEEN the spans rather than as an attribute, because that is the
    difference Hanz was complaining about: `title="IMG_4831.jpg"` was already there and it did not
    help him."""
    assert att["loading"]["captionNames"] == ["Slab-north-bay-before-grinding-2026-08-26.jpg"], (
        "an image tile rendered without a visible filename: %r" % (att["loading"],))
    assert att["loading"]["captionSizes"] == ["2.3 MB"], (
        "the size line is missing — the chips have always carried one and the tiles now match")


@needs_node
def test_both_kinds_of_attachment_carry_the_same_caption_pair(att):
    """A photo and a .docx in one message must read as two of the same thing.

    They are drawn differently on purpose — a picture is SHOWN and a document cannot be — but both
    use the same `.att-name` / `.att-size` pair, so neither becomes a fifth way of drawing a card.
    One tile, one chip, two names, two sizes."""
    both = att["both"]
    assert both["tiles"] == 1 and both["chips"] == 1, both
    assert both["names"] == ["Slab-north-bay-before-grinding-2026-08-26.jpg",
                             "Ridgeline-Cold-Storage-schedule-rev-C.docx"], both["names"]
    assert both["sizes"] == ["2.3 MB", "40 KB"], both["sizes"]


@needs_node
def test_the_full_name_survives_on_the_title_for_the_one_the_ellipsis_cuts(att):
    """Truncation is the CSS's job, and the untruncated name stays reachable.

    Both halves matter. If the renderer cut the string, the `title` could not give it back and the
    estimator would have no way at all to read a long name; if nothing truncated, a 45-character
    filename would wrap to three lines inside a 176px tile."""
    assert att["both"]["titles"] == att["both"]["names"], (
        "the title and the caption disagree, so one of them is not the real filename: %r"
        % (att["both"],))
    for tag in (att["loading"]["tileTag"], att["both"]["chipTag"]):
        assert 'title="' in tag, "no title to recover the untruncated name from: %r" % tag


@needs_node
def test_the_tile_has_no_aria_label_now_that_the_name_is_visible(att):
    """An aria-label on the anchor would OVERRIDE the visible text it now contains.

    It would announce the filename and swallow the size, to say the thing the eye can already read.
    The accessible name comes from the caption, which is the point of making it visible."""
    assert "aria-label" not in att["loading"]["tileTag"], (
        "the tile still carries an aria-label, which hides its own caption from a screen reader")


# ── 2. the three states, each with its own shape ─────────────────────────────

@needs_node
def test_a_loading_tile_never_renders_a_src_less_img(att):
    """THE ROOT CAUSE, pinned as a negative.

    A src-less `<img>` is how a browser draws a broken image. This tool authenticates with a bearer
    token and an `<img>` cannot send one, so the bytes arrive by fetch and the element is built
    afterwards — which means there is nothing to put a src on at render time, and the answer is to
    render no img at all rather than an empty one."""
    assert att["loading"]["srclessImgs"] == 0, (
        "a placeholder <img> with no src is back, and it draws as a broken image")
    assert att["loading"]["spins"] == 1, "the loading state has no spinner to explain the wait"


@needs_node
def test_a_loaded_thumbnail_lands_in_the_well_and_leaves_the_caption_alone(att):
    """WHERE the img is appended is the whole test.

    The anchor holds the caption now. The version of this that emptied the anchor and appended the
    img to it would take the filename out along with the spinner — the fix undoing itself on
    success, which is the state every attachment ends up in."""
    got = att["loaded"]
    assert got["imgsCreated"] == 1 and got["imgSrc"], got
    assert got["imgParentClasses"] == ["att-well"], (
        "the thumbnail was appended to %r, not to the image well" % (got["imgParentClasses"],))
    assert got["captionNames"] == ["Slab-north-bay-before-grinding-2026-08-26.jpg"], (
        "the caption did not survive hydration: %r" % (got["captionNames"],))
    assert got["imgAlt"] == "", (
        "the filename is back in alt — it is visible text now, and alt would announce it twice")
    assert got["tile"]["target"] == "_blank" and got["tile"]["href"].startswith("blob:"), got
    assert got["spinnerRemoved"], "the spinner outlived the thumbnail it was standing in for"


@needs_node
def test_a_failed_image_keeps_the_tile_and_says_so_in_the_caption(att):
    """A FAILURE MUST NOT RESIZE ANYTHING.

    The previous version turned the tile into a small chip, which shrinks the bubble — a reflow on
    the error path, in the feature whose entire purpose is not reflowing while the thread
    auto-scrolls. So the tile keeps its box, a class reveals the image-off glyph that shipped with
    the markup, and the caption's second line stops being a size and starts being the reason."""
    got = att["failedImage"]
    assert "att-img" in got["tile"]["classes"], (
        "a failed tile stopped being a tile (%r) — that is a reflow on the error path"
        % (got["tile"]["classes"],))
    assert "att-file" not in got["tile"]["classes"], got["tile"]
    assert "is-failed" in got["tile"]["classes"], got["tile"]
    assert got["note"] == "did not load", (
        "the caption does not say what happened: %r" % (got["note"],))
    assert got["brokeGlyphs"] == 1, "no image-off glyph — a torn page is what we were replacing"
    assert not got["tile"]["hasHref"], "a tile that did not load still navigates somewhere"
    assert got["imgsCreated"] == 0, "an <img> was built for a fetch that failed"


@needs_node
def test_a_failed_file_chip_stays_a_chip(att):
    """The other kind, and the easier half: a chip that fails changes nothing but its second line.

    Worth its own test because `attFailed` is now one function for both shapes. A version that
    special-cased the tile and rebuilt the chip would pass the test above and lose this."""
    got = att["failedFile"]
    assert got["chip"]["classes"] == ["att-file", "is-failed"], got["chip"]
    assert got["note"] == "did not load", got
    assert not got["chip"]["hasHref"], "a file that did not load still offers a download"


# ── 3. the cascade: no link blue, no wrap, no opacity-thinned small text ─────
#
# Weight first, source order only as the tie-break, because that is how the cascade actually
# resolves. Written this way after a tab tint declared EARLIER in the file beat three state rules
# declared later, on an id it out-weighed them with, and the test that was supposed to catch it
# compared line numbers and passed.


INHERITED = ("color",)   # the ones an ancestor's rule reaches this element through


def _rules(css):
    """Every `selector { body }` in the page's own stylesheet, in source order.

    Comments are stripped FIRST, and that is not tidiness. Without it the selector capture starts
    at the newline after the previous rule and swallows the comment block in between, so every
    `.att-size` written in English inside a comment reads as part of the next rule's selector — and
    the first version of this file duly reported a rule as unmatched because its "selector" was
    four sentences of prose.
    """
    css = re.sub(r"/\*[\s\S]*?\*/", "", css)
    return [(m.start(), m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}@][^{}]*?)\{([^{}]*)\}", css)]


def _weigh(sel):
    """(ids, classes+attrs+pseudos) for one selector. Nothing in this block uses !important or an
    inline style, so the pair decides every comparison here."""
    return (len(re.findall(r"#[\w-]+", sel)),
            len(re.findall(r"\.[\w-]+|\[[^\]]+\]|:[\w-]+", sel)))


def _tokens(compound):
    """One compound selector as a set: its classes (dot kept, so a class named `img` can never be
    read as the element type), plus `tag:x` when it names an element type."""
    got = set("." + c for c in re.findall(r"\.([\w-]+)", compound))
    tag = re.match(r"^([a-zA-Z][\w-]*)", compound)
    if tag:
        got.add("tag:" + tag.group(1).lower())
    return got


def _matches(sel, chain):
    """Does `sel` match the last element of `chain`?

    `chain` is the ancestry as a list of token sets, outermost first, ending with the element
    itself. THE LAST COMPOUND OF THE SELECTOR MUST TARGET THE ELEMENT — everything before it walks
    the ancestors in order. That distinction is the whole reason this is not a set-subset test:
    `.msg.staff { color:#fff }` out-weighs `.att-img { color:inherit }` on paper, but they are not
    competing, because one paints the bubble and the other paints the anchor inside it. Treating
    them as rivals reported the tile as taking its colour from the wrong rule.
    """
    compounds = [_tokens(c) for c in sel.split() if c.strip()]
    if not compounds or not compounds[-1] or not compounds[-1] <= chain[-1]:
        return False
    i = 0
    for want in compounds[:-1]:
        while i < len(chain) - 1 and not want <= chain[i]:
            i += 1
        if i >= len(chain) - 1:
            return False
        i += 1
    return True


def _resolve(css, chain, prop):
    """The declaration of `prop` that wins for the last element of `chain`.

    For an inherited property, a rule that targets an ancestor is a FALLBACK: it only decides the
    value when nothing targets the element itself. That is what `inherit` on the element means, and
    modelling it any other way makes the two look like a conflict.
    """
    best = own = None
    for at, sel, body in _rules(css):
        for one in sel.split(","):
            one = one.strip()
            if not one:
                continue
            m = re.search(r"(?:^|;)\s*" + prop + r"\s*:\s*([^;]+)", body)
            if not m:
                continue
            value = m.group(1).strip()
            if _matches(one, chain):
                key = _weigh(one) + (at,)
                if own is None or key > own[0]:
                    own = (key, one, value)
            elif prop in INHERITED and _matches(one, chain[:-1]):
                key = _weigh(one) + (at,)
                if best is None or key > best[0]:
                    best = (key, one, value)
    return own or best


@pytest.fixture(scope="module")
def css():
    html = HTML.read_text(encoding="utf-8")
    return "\n".join(re.findall(r"<style>([\s\S]*?)</style>", html))


# The real ancestry of every attachment surface, outermost first. `.msg.staff` is our own red
# bubble in the drawer; `.msg.customer` is the grey one. (The customer portal has them the other
# way round — same two colours, opposite speaker.)
def _chain(bubble, *rest):
    return [{".msg", "." + bubble}] + [set("." + c for c in r) for r in rest]


RED_TILE = _chain("staff", ["att-img"])
NEUTRAL_TILE = _chain("customer", ["att-img"])
RED_CHIP = _chain("staff", ["att-file"])
NEUTRAL_CHIP = _chain("customer", ["att-file"])
RED_TILE_SIZE = _chain("staff", ["att-img"], ["att-cap"], ["att-size"])
NEUTRAL_TILE_SIZE = _chain("customer", ["att-img"], ["att-cap"], ["att-size"])
RED_CHIP_SIZE = _chain("staff", ["att-file"], ["att-size"])
NEUTRAL_CHIP_SIZE = _chain("customer", ["att-file"], ["att-size"])
RED_TILE_NAME = _chain("staff", ["att-img"], ["att-cap"], ["att-name"])
RED_FAIL_TILE_SIZE = _chain("staff", ["att-img", "is-failed"], ["att-cap"], ["att-size"])
NEUTRAL_FAIL_TILE_SIZE = _chain("customer", ["att-img", "is-failed"], ["att-cap"], ["att-size"])
RED_FAIL_CHIP_SIZE = _chain("staff", ["att-file", "is-failed"], ["att-size"])
NEUTRAL_FAIL_CHIP_SIZE = _chain("customer", ["att-file", "is-failed"], ["att-size"])


def test_no_attachment_anchor_is_left_with_the_browsers_link_styling(css):
    """HALF OF WHY THE SCREENSHOT WAS UNREADABLE: blue, underlined, on dark red.

    An anchor inherits the user agent's link colour and underline unless something says otherwise,
    and `.att-img` never did — it only ever contained an `<img>`, right up until that img failed to
    render and the browser drew its alt text instead. Now both anchors carry a caption, so both
    have to answer for their text."""
    for name, chain in (("red tile", RED_TILE), ("red chip", RED_CHIP),
                        ("neutral tile", NEUTRAL_TILE), ("neutral chip", NEUTRAL_CHIP)):
        colour = _resolve(css, chain, "color")
        assert colour, "no rule sets a colour on the %s at all" % name
        assert colour[2] in ("inherit", "currentColor"), (
            "the %s pins its own colour (%r via %s) instead of taking the bubble's — which is how "
            "an anchor ends up blue on red" % (name, colour[2], colour[1]))
        deco = _resolve(css, chain, "text-decoration")
        assert deco and deco[2] == "none", (
            "the %s keeps the user agent underline (%r)" % (name, deco))


def test_a_long_filename_truncates_instead_of_wrapping(css):
    """Three lines of filename inside a chat bubble is worse than an ellipsis.

    All three declarations are needed and any one of them missing breaks it differently: without
    nowrap it wraps, without overflow:hidden the ellipsis never appears, without text-overflow it
    clips mid-glyph. The width has to be fixed too, or a long name simply widens the tile."""
    for prop, want in (("white-space", "nowrap"),
                       ("overflow", "hidden"),
                       ("text-overflow", "ellipsis")):
        got = _resolve(css, RED_TILE_NAME, prop)
        assert got and got[2] == want, (
            "the caption's %s resolves to %r, so a long name does not truncate" % (prop, got))
    width = _resolve(css, RED_TILE, "width")
    assert width and width[2].endswith("px"), (
        "the tile has no fixed width, so a long filename widens it: %r" % (width,))


def test_the_secondary_caption_line_stops_being_thinned_by_opacity(css):
    """THE MEASURED DEFECT. `.att-size { opacity: .65 }` inside a staff bubble is white at 65% over
    #9e001f, which is 3.4:1 — under the 4.5:1 floor for 12px text. It looked fine to whoever wrote
    it because it was only ever checked on the grey bubble, where the same rule is 4.9:1.

    So the size line takes a real colour per context and puts the opacity back to 1. Both halves
    are asserted: a colour with the multiplier still applied would take 6.7:1 back down to 4.4:1
    and the fix would be undone by the rule it was written to replace."""
    for name, chain in (("red tile", RED_TILE_SIZE), ("neutral tile", NEUTRAL_TILE_SIZE),
                        ("red chip", RED_CHIP_SIZE), ("neutral chip", NEUTRAL_CHIP_SIZE)):
        op = _resolve(css, chain, "opacity")
        assert op and op[2] == "1", (
            "the %s caption's size line is still thinned by opacity %r" % (name, op))
        colour = _resolve(css, chain, "color")
        assert colour and colour[2] not in ("inherit", "currentColor"), (
            "the %s caption's size line has no colour of its own (%r)" % (name, colour))


def test_the_tile_is_lifted_off_our_red_bubble_and_recessed_into_theirs(css):
    """FOUND IN A BROWSER, AND ONLY THERE.

    The first version gave the caption one neutral `rgba(0,0,0,.06)` plate for both bubbles, on the
    argument that a black wash reads as inset whatever it sits on. It does not. Over #9e001f that
    plate measures 1.08:1 AGAINST THE BUBBLE — the same colour, to the eye — because darkening
    something already dark barely moves its luminance. So on the red bubble the caption floated
    with nothing holding it to its picture, while the identical rule read perfectly on the grey.

    The chip had already learned this and carried a white wash for our bubble; the tile now does
    too. Both take the same value, from one pair of rules, so "what colour is an attachment on this
    bubble" has a single answer."""
    for chain, want, why in (
            (RED_TILE, "rgba(255,255,255", "our own bubble needs the surface LIFTED off it"),
            (RED_CHIP, "rgba(255,255,255", "our own bubble needs the surface LIFTED off it"),
            (NEUTRAL_TILE, "rgba(0,0,0", "their bubble is light, so the surface is recessed"),
            (NEUTRAL_CHIP, "rgba(0,0,0", "their bubble is light, so the surface is recessed")):
        got = _resolve(css, chain, "background")
        assert got and got[2].replace(" ", "").startswith(want), (
            "%s — resolved to %r" % (why, got))
    assert (_resolve(css, RED_TILE, "background")[2]
            == _resolve(css, RED_CHIP, "background")[2]), (
        "the tile and the chip are different colours on the same bubble")
    assert (_resolve(css, NEUTRAL_TILE, "background")[2]
            == _resolve(css, NEUTRAL_CHIP, "background")[2]), (
        "the tile and the chip are different colours on the same bubble")


def test_did_not_load_is_legible_on_the_red_bubble_and_not_only_on_the_grey(css):
    """The old failure note was `#9e001f` — the bubble's own colour, on the bubble. 1.4:1. Invisible.

    The palette already had the answer: --red-light (#ffdad8, styles.css's --treadwell-red-light)
    reads 4.7:1 on the lifted chip and 6.6:1 on the bubble, so nothing new had to be invented. The
    grey bubble keeps --red-dark at 6.1:1, because there a dark red is the legible one.

    Four classes on the winning rules, deliberately, so they out-WEIGH the three-class staff rules
    rather than merely following them in the file."""
    for chain in (RED_FAIL_TILE_SIZE, RED_FAIL_CHIP_SIZE):
        got = _resolve(css, chain, "color")
        assert got and got[2] == "var(--red-light)", (
            "the failure note on a red bubble resolves to %r — check it is not the bubble's own "
            "colour again" % (got,))
    for chain in (NEUTRAL_FAIL_TILE_SIZE, NEUTRAL_FAIL_CHIP_SIZE):
        got = _resolve(css, chain, "color")
        assert got and got[2] == "var(--red-dark)", (
            "the failure note on a neutral bubble resolves to %r" % (got,))
    assert "--red-light:#ffdad8" in css.replace(" ", ""), (
        "--red-light is gone from the drawer's token block, so every rule above it is unresolved")
