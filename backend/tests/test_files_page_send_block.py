"""The Files page's send block: the screen an estimator makes an irreversible decision on.

This block grew a control at a time — recipients, then a message, then attachments, then the
assigned estimator, then the notification roster, then the deposit — and every one of them
arrived as a `<label class="hint">` with an inline `style=`. The page ended up carrying 38 of
those, no media query anywhere among them, and six ways of spacing the same field. The 25%
DEPOSIT, which decides whether the customer is invoiced on approval, was a 12px grey label
sitting between two other 12px grey labels, halfway up the block.

It drifted that far because nothing here was tested. `test_recipients_row` pins the recipient
rows, `test_dropbox_picker_ui` pins the folder chooser — between them sat the send itself, and
a redesign could have dropped a control, an id or the drift warning with the suite green.

WHAT THIS FILE PINS, and why each one rather than "the page looks right":

  * EVERY ID done.js AND dropbox.js LOOK UP EXISTS. Derived by parsing the JavaScript, never
    typed out here: a hand-written list rots the moment somebody adds a control, and a missing
    id is not a cosmetic bug — `document.getElementById("portal-btn").addEventListener` on null
    throws as the page boots and nothing after it runs. This is the guard that would have caught
    a redesign losing one, and it guards the next redesign too.
  * THE DEPOSIT IS A BOUNDED BLOCK AND ITS STATE IS DRAWN BY CSS. `:has(input:checked)` means
    the checkbox, its id and `readRequireDeposit()` stay exactly as they were — no class to
    keep in sync, nothing for a second code path to get wrong on a re-send.
  * THE FOUR GROUPS ARE THERE, IN ORDER, and the deposit is the last thing before Send. The
    order is the argument: the final thing worth re-reading is the one that costs money.
  * THE TWO BREAKPOINTS EXIST. Inline styles carry no media query, so the block had none at
    all; a half-width window squashed the lot.
"""
import pathlib
import re
from html.parser import HTMLParser

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
DONE_HTML = (FRONTEND / "done.html").read_text(encoding="utf-8")
DONE_JS = (FRONTEND / "js" / "done.js").read_text(encoding="utf-8")
DROPBOX_JS = (FRONTEND / "js" / "dropbox.js").read_text(encoding="utf-8")
STYLES = (FRONTEND / "styles.css").read_text(encoding="utf-8")

VOID = {"input", "img", "br", "hr", "link", "meta", "path", "circle", "source"}


class _El:
    __slots__ = ("tag", "attrs", "kids", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.kids, self.parent = tag, dict(attrs), [], parent

    @property
    def id(self):
        return self.attrs.get("id", "")

    @property
    def classes(self):
        return set((self.attrs.get("class") or "").split())

    def walk(self):
        for k in self.kids:
            yield k
            for g in k.walk():
                yield g

    def find_id(self, node_id):
        return next((e for e in self.walk() if e.id == node_id), None)

    def find_class(self, cls):
        return next((e for e in self.walk() if cls in e.classes), None)

    def __repr__(self):                                    # only ever read from a failure
        return "<%s%s%s>" % (self.tag, " #" + self.id if self.id else "",
                             " ." + ".".join(sorted(self.classes)) if self.classes else "")


class _Tree(HTMLParser):
    """The page as a tree, so a claim about structure is checked against structure.

    A regex can confirm that `class="fp-dep"` and `id="portal-require-deposit"` both appear in
    the file; only a tree can say the checkbox is INSIDE the label that draws its state, which
    is the whole mechanism.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _El("#document", {}, None)
        self.cur = self.root
        self.feed(DONE_HTML)

    def handle_starttag(self, tag, attrs):
        el = _El(tag, attrs, self.cur)
        self.cur.kids.append(el)
        if tag not in VOID:
            self.cur = el

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(_El(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node.parent is not None and node.tag != tag:
            node = node.parent
        if node.parent is not None:
            self.cur = node.parent


DOC = _Tree().root
POST = DOC.find_id("post-generate")
SEND = POST.find_class("fp-panel--send")


def _rule(css, selector):
    """One rule BODY, matched on the WHOLE selector.

    A character window around a selector reaches into the neighbouring rule — the trap
    `test_recipients_row` records, where a 400-char slice picked up the next rule's own
    `display: flex` and let a mutation through. And the selector has to start at a boundary,
    or `.fp-panel` happily matches the tail of `.success-card.fp-panel` and reports the
    modifier as a card in its own right.
    """
    m = re.search(r"(?:^|[}{;\n])\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css, re.M)
    return m.group(1) if m else None


def _media(css, query):
    """Everything inside one @media block, brace-counted rather than sliced."""
    i = css.find(query)
    if i < 0:
        return None
    depth, j = 0, css.index("{", i)
    for k in range(j, len(css)):
        if css[k] == "{":
            depth += 1
        elif css[k] == "}":
            depth -= 1
            if depth == 0:
                return css[j + 1:k]
    return None


# ── the guard: nothing the JS reaches for may go missing ──────────────────────
def _ids_looked_up(src, dollar_is_get_by_id=False):
    found = set(re.findall(r'getElementById\(\s*"([^"]+)"\s*\)', src))
    if dollar_is_get_by_id:
        # dropbox.js opens with `const $ = (id) => document.getElementById(id);`
        assert "const $ = (id) => document.getElementById(id)" in src, (
            "dropbox.js's $() is no longer getElementById — this parser is reading it wrong")
        found |= set(re.findall(r'\$\(\s*"([^"]+)"\s*\)', src))
    return found


def test_every_id_the_page_scripts_look_up_is_in_the_page():
    """DERIVED FROM THE JAVASCRIPT, never listed here. A hand-typed list stops covering the
    control somebody adds next week, and this is precisely the failure a redesign makes: the
    markup is rewritten, one id is dropped, and `getElementById(...).addEventListener` throws
    on boot so every control BELOW it goes dead too. Nothing renders wrong — the page just
    stops working, which no visual review catches."""
    have = set(re.findall(r'id="([^"]+)"', DONE_HTML))
    want = _ids_looked_up(DONE_JS) | _ids_looked_up(DROPBOX_JS, dollar_is_get_by_id=True)
    assert len(want) > 30, "the parser found almost nothing — done.js changed shape"
    assert sorted(want - have) == [], "done.html is missing ids its own scripts look up"


def test_the_empty_state_still_has_the_two_nodes_viewfiles_rewrites():
    """`viewFiles()` reaches into the empty state by TAG and CLASS, not by id — it rewrites the
    h1 to "Preparing files…" and the .lede underneath it. An id sweep cannot see either."""
    empty = DOC.find_id("empty-state")
    assert empty.find_class("lede") is not None, "no .lede for viewFiles to write the status into"
    assert any(e.tag == "h1" for e in empty.walk()), "no h1 for viewFiles to rewrite"
    assert 'emptyEl.querySelector("h1")' in DONE_JS and 'querySelector(".lede")' in DONE_JS


# ── the deposit decision ─────────────────────────────────────────────────────
def test_the_deposit_checkbox_lives_inside_the_block_that_draws_its_state():
    """`:has(input:checked)` only reaches a checkbox that is a DESCENDANT of the block. Lift the
    input out to a sibling — the obvious tidy-up — and the tint, the title colour and the pill
    all silently stop responding while the send still works, so the estimator gets no signal at
    all about the one decision on this page that moves money."""
    box = SEND.find_id("portal-require-deposit")
    assert box is not None and box.attrs.get("type") == "checkbox"
    dep = box.parent
    assert "fp-dep" in dep.classes, "the checkbox's parent is not the deposit block: %r" % (dep,)
    assert dep.tag == "label", "the block has to be the label, or clicking the text toggles nothing"
    assert dep.attrs.get("for") == "portal-require-deposit"


def test_the_deposit_block_says_what_ticking_it_does_and_shows_the_answer_from_across_the_desk():
    """A 12px "Require deposit" said what the control was called, not what it did. The title,
    the consequence and a state pill are three different jobs, which is why they are three
    elements rather than one string — and the pills are a PAIR: exactly one is ever visible, so
    "No deposit" is as loud as "Deposit required" and neither state can be read as the default."""
    dep = SEND.find_class("fp-dep")
    assert dep.find_class("fp-dep-t") is not None, "no title"
    assert dep.find_class("fp-dep-d") is not None, "no consequence line"
    pills = [e for e in dep.walk() if "fp-pill" in e.classes]
    assert {"fp-pill--on", "fp-pill--off"} == {c for p in pills for c in p.classes if "--" in c}
    # The hint span mountRequireDeposit() writes ("(25% on approval)" / "(off by default for GC
    # work)") has to sit in the TITLE, where it completes a sentence, not in the description.
    assert dep.find_class("fp-dep-t").find_id("portal-require-deposit-hint") is not None
    assert 'getElementById("portal-require-deposit-hint")' in DONE_JS


def test_the_deposit_state_is_drawn_by_css_off_checked():
    """The alternative was a `classList.toggle` on change, and that is a second source of truth:
    it has to be re-run on mount, on a re-send and after mountRequireDeposit() sets .checked
    from the draft — three places to forget. CSS off `:checked` cannot fall out of step, which
    is why mountRequireDeposit() and readRequireDeposit() are untouched by this redesign."""
    for state in ("", " .fp-dep-t", " .fp-pill--on", " .fp-pill--off"):
        sel = ".fp-dep:has(input:checked)" + state
        assert _rule(DONE_HTML, sel) is not None, "no CSS draws " + sel
    assert "display: block" in _rule(DONE_HTML, ".fp-dep:has(input:checked) .fp-pill--on")
    assert "display: none" in _rule(DONE_HTML, ".fp-dep:has(input:checked) .fp-pill--off")
    assert "display: none" in _rule(DONE_HTML, ".fp-pill--on"), "the ON pill must start hidden"
    # And the JS still only sets `.checked` — no class, no style, nothing to keep in sync.
    mount = DONE_JS[DONE_JS.index("function mountRequireDeposit()"):]
    mount = mount[:mount.index("\n  }")]
    assert "el.checked =" in mount
    assert "classList" not in mount and ".style" not in mount, (
        "mountRequireDeposit is painting the state itself again: " + mount)


# ── the four groups, in the order the decision is made ───────────────────────
def test_the_send_lane_holds_its_four_groups_in_the_order_they_are_decided():
    """Who it goes to, what it says, who owns it, what it costs — then the button. The order is
    the argument: the deposit is LAST because it is the final thing worth re-reading before an
    irreversible click, and it was previously buried above the notify chips where nothing about
    it said money was at stake."""
    groups = [e for e in SEND.kids if "fp-grp" in e.classes]
    assert len(groups) == 3, "expected three hairline groups above the deposit, got %r" % (groups,)
    assert groups[0].find_id("portal-recipients") is not None, "group 1 is the recipients"
    assert groups[1].find_id("portal-message") is not None, "group 2 is the customer's message"
    assert groups[1].find_id("send-atts") is not None and groups[1].find_id("send-file") is not None
    assert groups[1].find_id("send-attach") is not None, "nothing opens the file picker"
    assert groups[2].find_id("portal-estimator") is not None, "group 3 is who owns it"
    assert groups[2].find_id("notify-pick") is not None, "...and who else hears about it"
    # The fourth group is the deposit, and it is the last thing before Send.
    order = [e for e in SEND.kids if "fp-grp" in e.classes or "fp-dep" in e.classes
             or e.id in ("portal-btn", "portal-result")]
    assert [("grp" if "fp-grp" in e.classes else "fp-dep" if "fp-dep" in e.classes else e.id)
            for e in order] == ["grp", "grp", "grp", "fp-dep", "portal-btn", "portal-result"]


def test_the_roster_can_still_hide_itself():
    """`mountNotifyRoster` sets `box.hidden = true` when nobody is configured — saying nothing
    beats an empty control that implies the send tells no one. A class `display` rule beats the
    `hidden` attribute outright (four live instances of that in this app), so the column layout
    this block now sits in has to hand `hidden` back."""
    pick = SEND.find_id("notify-pick")
    assert "hidden" in pick.attrs, "the roster no longer starts hidden"
    assert "fp-field" in pick.classes
    assert "display: flex" in _rule(DONE_HTML, ".fp-field")
    assert "display: none" in _rule(DONE_HTML, ".fp-field[hidden]"), (
        "the column rule defeats `hidden`, so an unconfigured roster renders as an empty box")
    assert "box.hidden = true" in DONE_JS
    # Same trap, same fix, for the attachment strip — shared with the CRM drawer, so in styles.css.
    assert "display: none" in _rule(STYLES, ".att-strip[hidden]")
    assert "strip.hidden = !items.length" in DONE_JS


# ── the rules the inline styles never had ────────────────────────────────────
def test_the_two_lanes_collapse_before_they_squash():
    """Every inline `style=` this block carried came with no media query at all, so a half-width
    window squeezed the send lane down to nothing while the rail kept its share. The send panel
    keeps the top of the single column afterwards, which is what source order buys."""
    assert "minmax(0, 1.55fr) minmax(0, 1fr)" in _rule(DONE_HTML, ".fp-lanes")
    narrow = _media(DONE_HTML, "@media (max-width: 1080px)")
    assert narrow, "the lanes have no breakpoint at all"
    assert "grid-template-columns: minmax(0, 1fr)" in _rule(narrow, ".fp-lanes")
    lanes = POST.find_class("fp-lanes")
    assert lanes.kids[0] is SEND, "the send panel must be first, or it lands under the rail"


def test_the_paired_controls_stack_and_the_pill_drops_under_its_text():
    """Two 1fr columns of select-plus-chips inside a lane that is already narrow is how the
    estimator picker ends up 120px wide. At 820px the pairs stack, and the deposit gives up its
    fourth column so the pill sits under the sentence instead of squeezing it."""
    pairs = _media(DONE_HTML, "@media (max-width: 820px)")
    assert pairs, "the paired controls have no breakpoint"
    assert "grid-template-columns: minmax(0, 1fr)" in _rule(pairs, ".fp-2col")
    assert "grid-template-columns: auto auto 1fr" in _rule(pairs, ".fp-dep")
    assert "grid-column: 3" in _rule(pairs, ".fp-pill")
    assert "flex-direction: column" in _rule(pairs, ".fp-ready"), (
        "the ready strip keeps its row, so the three downloads squeeze the project name")


def test_the_send_screen_carries_no_inline_style_but_the_boot_state():
    """38 inline styles is what happens when there is nowhere else to put one. The only ones
    left are `display:none` — the state JS toggles, which genuinely belongs on the element
    because it is what the page looks like before any script has run."""
    block = DONE_HTML[DONE_HTML.index('id="post-generate"'):DONE_HTML.index('id="empty-state"')]
    strays = [s for s in re.findall(r'style="([^"]*)"', block)
              if s.replace(" ", "").strip(";") != "display:none"]
    assert strays == [], "inline styles are back on the send screen: %r" % strays


# ── the buttons ──────────────────────────────────────────────────────────────
def test_the_downloads_are_the_outline_variant_and_it_finally_has_a_hover():
    """Three solid-red buttons at the top of the page competed with the one irreversible action
    at the bottom of it. `.secondary` has been sitting unused in styles.css the whole time — and
    with no working hover, because `.download-link:hover` and `.download-link.secondary` are
    both (0,2,0) and the variant, declared second, painted the button back to white on contact.

    FOUR since 2026-08-28 — the optional cover letter's .docx joined the row, and it is in the list
    rather than exempt from it for the same reason the other three are: a solid fourth would
    compete with Send just as hard."""
    dl = POST.find_class("fp-dl")
    kinds = [e.id for e in dl.kids if e.tag == "button"]
    assert kinds == ["dl-xlsx", "dl-docx", "dl-pdf", "dl-cover"]
    assert all({"download-link", "secondary"} <= e.classes for e in dl.kids if e.tag == "button")
    assert _rule(STYLES, ".download-link.secondary:hover"), "the outline button has no hover state"


def test_no_button_the_javascript_rewrites_carries_an_icon():
    """Every one of these has its label REPLACED by textContent — "Downloading…", "Sending…",
    "✓ Sent to customer portal", "File into this folder", "…". An inline <svg> inside one is
    deleted by the first click and never comes back, so the icon is not a styling choice here,
    it is a bug with a delay on it. Icons go in section heads and on the two buttons nothing
    rewrites (Add a photo or file, Start a new project)."""
    rewritten = ("dl-xlsx", "dl-docx", "dl-pdf", "dl-cover", "portal-btn", "gen-btn", "dbx-go")
    for node_id in rewritten:
        el = DOC.find_id(node_id)
        assert el is not None, node_id
        assert not any(k.tag == "svg" for k in el.walk()), (
            node_id + " holds an <svg>, and its own JS overwrites the label with textContent")
    # `.rev-dl` is built by done.js and download-revision rewrites it the same way.
    revs = DONE_JS[DONE_JS.index('list.innerHTML = revs.map'):]
    revs = revs[:revs.index('.join("")')]
    assert "<svg" not in revs, "a revision download button grew an icon its own handler deletes"
    assert 'button.textContent = "…"' in DONE_JS


def test_the_folder_button_keeps_the_label_the_picker_writes():
    """`dbxGoLabel` is the only thing allowed to word this button, because it is reporting the
    state of the choice above it — "Choose a folder above" IS the disabled reason. The markup's
    own label is only what shows before dropbox.js runs, so it has to be one of its answers."""
    go = DOC.find_id("dbx-go")
    assert "disabled" in go.attrs, "the button must start disabled — nothing is chosen yet"
    assert 'dbxGoLabel' in DROPBOX_JS and '"File into this folder"' in DROPBOX_JS
    assert '"Choose a folder above"' in DROPBOX_JS
    assert "go.textContent = dbxGoLabel(st)" in DROPBOX_JS


def test_the_field_caption_rule_cannot_reach_the_folder_rows():
    """Every candidate the picker renders is a <label> INSIDE `#dbx-folder-field.dbx-field`, so
    a descendant rule for the field's caption lands on all of them: `.dbx-field label` at (0,1,1)
    beat `.dbx-folder` at (0,1,0) and rendered Kyle's whole folder list as 11px UPPERCASE block
    labels — the parent line, the badge and the italic create row all flattened with it. The
    child combinator reaches the caption and nothing else.

    Its own stylesheet cannot defend against this, which is why the guard lives here: the rule
    doing the damage is in the PAGE, and `test_dropbox_picker_ui` renders the rows against a DOM
    stub with no CSS at all."""
    assert _rule(DONE_HTML, ".dbx-field label") is None, (
        "a descendant rule is styling every folder row as a field caption again")
    caption = _rule(DONE_HTML, ".dbx-field > label")
    assert caption and "text-transform:uppercase" in caption.replace(" ", "")
    # The captions the rule IS for are direct children; the rows are not.
    field = DOC.find_id("dbx-folder-field")
    assert any(k.tag == "label" for k in field.kids), "the Project folder caption moved out"
    assert DOC.find_id("dbx-folders").parent is not field, (
        "the folder list is a direct child again, so the caption rule reaches its rows")


def test_the_card_is_the_apps_card_and_not_a_fifth_one():
    """CLAUDE.md: "A fifth way to draw a card is a bug." Every panel on the send screen is a
    `.success-card` wearing a modifier that makes it dense and left-aligned; the modifier owns
    two declarations and no background, border or radius of its own."""
    panels = [e for e in POST.walk() if "fp-panel" in e.classes]
    assert len(panels) >= 5, "expected the ready strip, the send lane, two rail cards and Dropbox"
    assert all("success-card" in p.classes for p in panels), (
        "a panel dropped .success-card and is now drawing its own card: %r"
        % [p for p in panels if "success-card" not in p.classes])
    body = _rule(DONE_HTML, ".success-card.fp-panel")
    assert body and "background" not in body and "border-radius" not in body
    assert _rule(DONE_HTML, ".fp-panel") is None, "the modifier grew into a card of its own"
