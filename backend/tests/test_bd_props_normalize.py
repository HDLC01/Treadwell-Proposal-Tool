"""normalize.py, generated (property) coverage on top of the example cases in test_bd_normalize.py.

Pure properties of normalize_company, clean_name and email_key, plus ONE batched node run that
checks normalize_company against frontend/bd/js/shared.js normalizeCompany on a generated list of
strings. Nothing here touches a database or the network; no dates are involved.

Each property is an invariant of the matching keys, not a copy of the code:
  * normalize_company: idempotent; output is only [a-z0-9] words joined by single spaces; blind to
    case, to surrounding whitespace and to which kind of space (ASCII, NBSP, figure, narrow NBSP)
    separates words; punctuation (any [^a-z0-9\\s]) never changes it, "&" acts as a word break;
    trailing company suffixes strip down to, but never past, one remaining word.
  * clean_name: same words in the same order as str.split(), joined by single spaces, case kept.
  * email_key: strip + lower, None for nothing.
"""
from __future__ import annotations

import json
import pathlib
import re
import string
import tempfile

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from _node import last_json_line, run_node
from _bd_pages import SHARED_JS, needs_bd_page_helpers
from bd.normalize import COMPANY_SUFFIXES, clean_name, email_key, normalize_company


ALNUM = string.ascii_letters + string.digits
ODD_SPACES = "   "
# Characters normalize_company must drop without a trace (none is a letter, digit, "&" or space);
# a few non-ASCII ones, because "Café Olé" -> "caf ol" is the documented behaviour.
NOISE = ".,;:!?'\"()[]{}-_/\\#@$%*+=~`|<>^—éñØ"
WHITESPACE = [" ", "  ", "\t", "\n", "\r\n", " ", " ", " ", " ", "　", "   "]

any_text = st.text(max_size=60)
whitespace = st.sampled_from(WHITESPACE)
words = st.lists(st.text(alphabet=ALNUM, min_size=1, max_size=8), min_size=1, max_size=6)
suffix_word = st.sampled_from(COMPANY_SUFFIXES)


@st.composite
def name_ish(draw):
    """A company-name-like string: words, suffixes in any case with punctuation, odd separators."""
    tokens = draw(st.lists(st.one_of(
        st.text(alphabet=ALNUM + NOISE + "&", max_size=8),
        suffix_word.flatmap(lambda s: st.sampled_from([s, s.upper(), s.title(), s + ".", s + ",", "(" + s + ")"])),
    ), max_size=7))
    seps = draw(st.lists(st.sampled_from([" ", "  ", ODD_SPACES[0], ODD_SPACES[1], ODD_SPACES[2], " & ", ", ", "\t"]),
                         min_size=len(tokens), max_size=len(tokens)))
    return "".join(t + s for t, s in zip(tokens, seps, strict=True))


@st.composite
def noisy_words(draw):
    """(plain words, the same words with junk punctuation sprinkled inside and around them but
    never in place of the single space between them)."""
    ws = draw(words)
    noisy = []
    for w in ws:
        frags = draw(st.lists(st.text(alphabet=NOISE, max_size=3), min_size=len(w) + 1, max_size=len(w) + 1))
        noisy.append("".join(frags[i] + w[i] for i in range(len(w))) + frags[-1])
    return ws, " ".join(noisy)


odd_things = st.one_of(
    st.none(), st.booleans(), st.integers(), st.floats(allow_nan=True, allow_infinity=True),
    st.binary(max_size=20), any_text, st.lists(st.integers(), max_size=3), st.builds(object),
)


# ── the suffix list is the frontend's, word for word ────────────────────────────────────────────
@needs_bd_page_helpers
def test_company_suffixes_match_the_frontend_list():
    src = SHARED_JS.read_text(encoding="utf-8")
    m = re.search(r"var COMPANY_SUFFIXES = \[([^\]]*)\]", src)
    assert m, "COMPANY_SUFFIXES not found in shared.js"
    assert tuple(re.findall(r'"([^"]+)"', m.group(1))) == tuple(COMPANY_SUFFIXES)
    assert set(COMPANY_SUFFIXES) == {"inc", "incorporated", "llc", "co", "corp", "corporation",
                                     "company", "ltd", "lc", "pllc"}
    assert all(s == s.lower() and s.isalnum() for s in COMPANY_SUFFIXES)   # the key is lower [a-z0-9]


# ── normalize_company ───────────────────────────────────────────────────────────────────────────
@given(st.one_of(any_text, name_ish()))
def test_normalize_company_is_idempotent(name):
    once = normalize_company(name)
    assert normalize_company(once) == once


@given(st.one_of(any_text, name_ish()))
def test_normalize_company_output_is_single_spaced_lowercase_alphanumerics(name):
    out = normalize_company(name)
    assert re.fullmatch(r"(?:[a-z0-9]+(?: [a-z0-9]+)*)?", out), repr(out)


@given(name_ish())
def test_normalize_company_ignores_case(name):
    # name_ish is ASCII except for NOISE letters, which are dropped in every case form
    want = normalize_company(name)
    assert normalize_company(name.upper()) == want
    assert normalize_company(name.lower()) == want
    assert normalize_company(name.swapcase()) == want


@given(st.one_of(any_text, name_ish()), whitespace, whitespace)
def test_normalize_company_ignores_surrounding_whitespace(name, left, right):
    assert normalize_company(left + name + right) == normalize_company(name)


@given(name_ish(), st.lists(st.sampled_from(list(ODD_SPACES) + [" "]), min_size=1, max_size=8))
def test_normalize_company_treats_every_kind_of_space_alike(name, spaces):
    """Each ASCII space may be swapped for NBSP / figure space / narrow NBSP: the key is the same."""
    it = iter(spaces * (len(name) + 1))
    swapped = "".join(next(it) if ch == " " else ch for ch in name)
    assert normalize_company(swapped) == normalize_company(name)


@given(noisy_words())
@example((["Acme", "Inc"], "Acme, Inc."))
@example((["St", "Lukes", "Hospital"], "St. Luke's Hospital"))
@example((["OBrienSmith", "Corp"], "O'Brien-Smith Corp."))
def test_punctuation_only_differences_are_equal(pair):
    plain, noisy = pair
    assert normalize_company(noisy) == normalize_company(" ".join(plain))


def test_the_documented_punctuation_pairs():
    assert normalize_company("Acme, Inc.") == normalize_company("Acme Inc") == "acme"
    assert normalize_company("Acme, Inc.") == normalize_company("ACME INC")


@given(words)
def test_ampersand_is_a_word_break_not_a_letter(ws):
    want = normalize_company(" ".join(ws))
    assert normalize_company(" & ".join(ws)) == want
    assert normalize_company("&".join(ws)) == want      # "Halvorsen&Pike" is two words, not one
    assert normalize_company("&" + " & ".join(ws) + " &") == want


@given(st.one_of(any_text, name_ish()), st.lists(suffix_word, min_size=1, max_size=4), st.data())
def test_appended_suffix_words_never_change_a_real_name(name, suffixes, data):
    base = normalize_company(name)
    spelled = [data.draw(st.sampled_from([s, s.upper(), s.title(), s + ".", s + ","])) for s in suffixes]
    got = normalize_company(name + " " + " ".join(spelled))
    if base:
        assert got == base
    else:
        # nothing but punctuation before them: the first appended word is what is left, never ""
        assert got == suffixes[0]


@given(suffix_word, st.lists(suffix_word, max_size=3))
def test_a_lone_suffix_word_is_kept(first, more):
    assert normalize_company(" ".join([first] + more)) == first
    assert normalize_company(first.upper() + ".") == first


@given(st.one_of(any_text, name_ish()))
def test_suffix_stripping_is_trailing_maximal_and_never_empties_a_name(name):
    got = normalize_company(name)
    # "zzqx" is not a suffix, so appending it exposes every word the name has, unstripped.
    full = normalize_company(name + " zzqx").split(" ")
    assert full[-1] == "zzqx"
    base = full[:-1]
    kept = got.split(" ") if got else []
    assert kept == base[: len(kept)]                               # only the tail is ever removed
    assert all(w in COMPANY_SUFFIXES for w in base[len(kept):])    # and only suffix words are
    assert bool(kept) == bool(base)                                # never the last remaining word
    if len(kept) > 1:
        assert kept[-1] not in COMPANY_SUFFIXES                    # nothing strippable is left behind


@given(words, suffix_word)
def test_a_suffix_in_the_middle_of_a_name_stays(ws, suffix):
    typed = [ws[0], suffix] + ws[1:] + ["zzqx"]       # a real last word, so nothing trails off
    assert normalize_company(" ".join(typed)) == " ".join(w.lower() for w in typed)


@given(odd_things)
def test_normalize_company_never_raises_and_always_returns_a_string(value):
    out = normalize_company(value)
    assert isinstance(out, str)
    assert out == ("" if value is None else normalize_company(str(value)))


@given(st.one_of(any_text, name_ish()))
def test_the_key_of_a_stored_name_is_the_key_of_what_was_typed(name):
    """companies.name is stored with clean_name; the duplicate key must not depend on that."""
    assert normalize_company(clean_name(name)) == normalize_company(name)


# ── clean_name ──────────────────────────────────────────────────────────────────────────────────
@given(st.one_of(any_text, name_ish()))
def test_clean_name_is_idempotent(name):
    once = clean_name(name)
    assert clean_name(once) == once


@given(st.one_of(any_text, name_ish()))
def test_clean_name_is_trimmed_and_single_spaced(name):
    out = clean_name(name)
    assert out == out.strip()
    assert "  " not in out
    assert all(not ch.isspace() or ch == " " for ch in out)       # no tab, newline or odd space left


@given(st.one_of(any_text, name_ish()))
def test_clean_name_keeps_every_non_space_character_in_order(name):
    out = clean_name(name)
    assert [c for c in out if not c.isspace()] == [c for c in name if not c.isspace()]
    assert out == " ".join(name.split())          # the same words, str.split()'s idea of a space
    assert len(out) <= len(name)


@given(st.text(alphabet=ALNUM, min_size=1, max_size=10), whitespace, whitespace, whitespace)
def test_clean_name_collapses_runs_to_one_space(word, a, b, c):
    assert clean_name(a + word + b + word.upper() + c) == word + " " + word.upper()


@given(any_text)
def test_clean_name_never_changes_case_or_punctuation(name):
    # unlike the key: "Northvane Plastics Inc." stays exactly that
    assert clean_name(name + " Inc.") == (clean_name(name) + " Inc.").strip()


@given(odd_things)
def test_clean_name_never_raises_and_always_returns_a_string(value):
    out = clean_name(value)
    assert isinstance(out, str)
    assert out == ("" if value is None else clean_name(str(value)))


# ── email_key ───────────────────────────────────────────────────────────────────────────────────
@given(any_text)
def test_email_key_is_none_exactly_for_blank_and_else_stripped_lowercase(raw):
    key = email_key(raw)
    if raw.strip() == "":
        assert key is None
    else:
        assert key == raw.strip().lower()
        assert key == key.strip() and key


@given(any_text)
def test_email_key_is_idempotent(raw):
    once = email_key(raw)
    assert email_key(once) == once          # None stays None, a key stays itself


@given(st.text(alphabet=ALNUM + "._+-@", min_size=1, max_size=30), whitespace, whitespace)
def test_email_key_ignores_case_and_surrounding_whitespace(addr, left, right):
    want = email_key(addr)
    assert want == addr.lower()
    assert email_key(addr.upper()) == want
    assert email_key(left + addr + right) == want
    assert email_key(left + addr.swapcase() + right) == want


@given(st.one_of(st.none(), whitespace, st.lists(whitespace, max_size=4).map("".join)))
def test_email_key_of_nothing_is_none(raw):
    assert email_key(raw) is None


def test_email_key_keeps_what_is_inside():
    assert email_key(" Dana.Whitfield@Example.COM ") == "dana.whitfield@example.com"
    assert email_key("a b@example.com") == "a b@example.com"      # inner characters are never touched


@given(odd_things)
def test_email_key_never_raises(value):
    key = email_key(value)
    assert key is None or (isinstance(key, str) and key)
    if value is None:
        assert key is None


# ── python and the frontend agree on a generated list (ONE node run per example) ────────────────
JS_ALPHABET = ALNUM + "&.,-' " + ODD_SPACES + "éñøΩßÉ"
js_string = st.lists(st.one_of(
    st.text(alphabet=JS_ALPHABET, max_size=8),
    st.sampled_from(list(COMPANY_SUFFIXES) + ["Inc.", "LLC", "Co.", "& Co", "Corp,"]),
), max_size=4).map(lambda ws: " ".join(ws))

_BATCH_SCRIPT = """
const fs = require("fs"), vm = require("vm");
const ctx = {}; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const raws = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
console.log(JSON.stringify(raws.map((r) => ctx.BD.normalizeCompany(r))));
"""


@needs_bd_page_helpers
@settings(max_examples=5, suppress_health_check=list(HealthCheck))
@given(st.lists(js_string, min_size=100, max_size=200))
def test_python_and_the_frontend_agree_on_generated_names(raws):
    with tempfile.TemporaryDirectory() as tmp:
        js = pathlib.Path(tmp) / "norm.js"
        data = pathlib.Path(tmp) / "raws.json"
        js.write_text(_BATCH_SCRIPT, encoding="utf-8")
        data.write_text(json.dumps(raws), encoding="utf-8")
        proc = run_node(js, SHARED_JS, data)
    assert proc.returncode == 0, proc.stderr
    got = last_json_line(proc.stdout)
    want = [normalize_company(r) for r in raws]
    bad = [(r, g, w) for r, g, w in zip(raws, got, want, strict=True) if g != w]
    assert not bad, bad[:5]
