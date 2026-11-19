"""phone.py: generated (property) coverage on top of the table in test_phone.py.

The module's contract, as invariants rather than examples:

  * digits() keeps ASCII 0-9 only, never grows its input, is idempotent and is additive over
    concatenation.
  * to_e164() is None or "+1" + exactly 10 digits; it accepts exactly 10 digits, or 11 starting
    with 1; formatting noise around the same 10 digits never changes the answer; it is idempotent
    through its own output; Unicode digits are not phone digits.
  * last10() is the last 10 digits of digits(), None below 10, and agrees with to_e164().
  * display() round-trips a US number to AAA-BBB-CCCC and leaves anything else as given.
  * nothing raises for a non-string input.
  * the frontend (shared.js BD.e164 / BD.fmtPhone) answers the same for a generated batch.

Numbers are fictional by construction (generated digits, no real list). No clock, database or
network is involved; the one node run is batched per example.
"""
from __future__ import annotations

import json
import pathlib
import re
import tempfile

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bd import phone
from _node import last_json_line, run_node

ROOT = pathlib.Path(__file__).resolve().parents[2]
# BD's page helpers file (BD's shared.js, which holds normalizeCompany, e164 and fmtPhone) moves
# with the BD pages in a later ticket of #802. Until it does, the frontend half of this parity
# check has no file to run. The ticket that moves it points SHARED_JS at the moved file and
# deletes BD_PAGE_HELPERS_NOT_MOVED.
SHARED_JS = ROOT / "frontend" / "bd" / "js" / "shared.js"
BD_PAGE_HELPERS_NOT_MOVED = pytest.mark.skip(
    reason="BD's page helpers (shared.js) move with the BD pages in a later ticket of #802")

ASCII_DIGITS = "0123456789"
SEPARATORS = " -.()\t/_"
# Digits that are NOT phone digits, written as escapes: Arabic-Indic, Devanagari, fullwidth,
# superscript two.
UNICODE_DIGITS = (
    "".join(chr(c) for c in range(0x0660, 0x066A))
    + "".join(chr(c) for c in range(0x0966, 0x0970))
    + "".join(chr(c) for c in range(0xFF10, 0xFF1A))
    + chr(0x00B2)
)
NOISE_CHARS = SEPARATORS + "+abcxt#" + UNICODE_DIGITS

digit_strings = st.text(alphabet=ASCII_DIGITS, max_size=30)
messy_text = st.text(alphabet=ASCII_DIGITS + NOISE_CHARS, max_size=40)
any_text = st.text(max_size=40)

ten_digits = st.tuples(
    st.integers(0, 999), st.integers(0, 999), st.integers(0, 9999)
).map(lambda t: "%03d%03d%04d" % t)

separator_runs = st.text(alphabet=SEPARATORS, max_size=3)
prefixes = st.sampled_from(["", "1", "+1", "1 ", "+1 ", "1-", "+1-", "+1 (", "1."])


@st.composite
def noisy_number(draw):
    """(the ten digits, a string that spells them with separators and an optional 1 / +1)."""
    ten = draw(ten_digits)
    parts = [draw(separator_runs) + ch for ch in ten]
    body = "".join(parts) + draw(separator_runs)
    return ten, draw(prefixes) + body


@st.composite
def templated_number(draw):
    """The same ten digits in the shapes people actually type, from area/exchange/line integers."""
    a = draw(st.integers(0, 999))
    e = draw(st.integers(0, 999))
    ln = draw(st.integers(0, 9999))
    shape = draw(st.sampled_from([
        "{a:03d}{e:03d}{l:04d}", "{a:03d}.{e:03d}.{l:04d}", "{a:03d}-{e:03d}-{l:04d}",
        "({a:03d}) {e:03d}-{l:04d}", "{a:03d} {e:03d} {l:04d}", "+1 {a:03d} {e:03d} {l:04d}",
        "+1 ({a:03d}) {e:03d}-{l:04d}", "1-{a:03d}-{e:03d}-{l:04d}", "1{a:03d}{e:03d}{l:04d}",
        "+1{a:03d}{e:03d}{l:04d}",
    ]))
    return "%03d%03d%04d" % (a, e, ln), shape.format(a=a, e=e, l=ln)


# -- digits() -------------------------------------------------------------------------------
@given(any_text)
def test_digits_is_only_ascii_digits_and_never_longer(s):
    d = phone.digits(s)
    assert re.fullmatch(r"[0-9]*", d)
    assert len(d) <= len(s)


@given(any_text)
def test_digits_is_idempotent(s):
    assert phone.digits(phone.digits(s)) == phone.digits(s)


@given(messy_text)
def test_digits_keeps_the_ascii_digits_in_order(s):
    # An independent reading of the rule: the subsequence of the characters that are 0-9.
    assert phone.digits(s) == "".join(ch for ch in s if ch in ASCII_DIGITS)


@given(any_text, any_text)
def test_digits_is_additive_over_concatenation(a, b):
    assert phone.digits(a + b) == phone.digits(a) + phone.digits(b)


@given(digit_strings)
def test_digits_of_a_pure_digit_string_is_itself(s):
    assert phone.digits(s) == s


# -- to_e164() ------------------------------------------------------------------------------
@given(messy_text)
def test_to_e164_is_none_or_plus_one_and_ten_digits(s):
    e = phone.to_e164(s)
    assert e is None or re.fullmatch(r"\+1[0-9]{10}", e)


@given(digit_strings)
def test_to_e164_accepts_exactly_ten_digits_or_eleven_starting_with_one(d):
    got = phone.to_e164(d)
    if len(d) == 10:
        assert got == "+1" + d
    elif len(d) == 11 and d[0] == "1":
        assert got == "+1" + d[1:]
    else:
        assert got is None


@given(messy_text)
def test_to_e164_is_idempotent_through_its_own_output(s):
    once = phone.to_e164(s)
    assert phone.to_e164(once) == once


@given(ten_digits)
def test_a_ten_digit_number_starting_with_one_is_not_mistaken_for_a_country_code(ten):
    # "1" + 9 more digits is a 10-digit number; its own +1 form must not lose a digit.
    n = "1" + ten[1:]
    assert phone.to_e164(n) == "+1" + n
    assert phone.to_e164(phone.to_e164(n)) == "+1" + n
    assert phone.to_e164("1" + n) == "+1" + n


@given(noisy_number())
def test_formatting_noise_never_changes_the_answer(case):
    ten, spelled = case
    assert phone.to_e164(spelled) == "+1" + ten
    assert phone.to_e164(spelled) == phone.to_e164(ten)


@given(templated_number())
def test_the_usual_typed_shapes_all_give_the_same_number(case):
    ten, typed = case
    assert phone.to_e164(typed) == "+1" + ten
    assert phone.last10(typed) == ten
    assert phone.display(typed) == "%s-%s-%s" % (ten[:3], ten[3:6], ten[6:])


@given(ten_digits, st.integers(0, 9))
def test_one_digit_too_many_or_too_few_is_not_a_number(ten, extra):
    # 11 digits only qualify when they START with 1; appending a digit to a number that does not
    # start with 1 can never give one.
    if ten[0] != "1":
        assert phone.to_e164(ten + str(extra)) is None
    assert phone.to_e164(ten[:-1]) is None            # 9 digits
    assert phone.to_e164("22" + ten) is None          # 12 digits
    assert phone.to_e164("1" + ten + str(extra)) is None   # 12 digits starting with 1


@given(ten_digits, st.lists(st.sampled_from(UNICODE_DIGITS), min_size=1, max_size=6), st.data())
def test_unicode_digits_are_not_phone_digits(ten, foreign, data):
    # Sprinkling non-ASCII digits into a valid number changes nothing...
    chars = list(ten)
    for ch in foreign:
        chars.insert(data.draw(st.integers(0, len(chars))), ch)
    assert phone.to_e164("".join(chars)) == "+1" + ten
    # ...and a number written entirely in them is not a number at all.
    assert phone.to_e164("".join(foreign) * 4) is None
    assert phone.digits("".join(foreign)) == ""


# -- last10() -------------------------------------------------------------------------------
@given(messy_text)
def test_last10_is_the_last_ten_digits_or_none(s):
    d = phone.digits(s)
    got = phone.last10(s)
    if len(d) >= 10:
        assert got == d[len(d) - 10:]
        assert re.fullmatch(r"[0-9]{10}", got)
    else:
        assert got is None


@given(messy_text)
def test_last10_is_the_tail_of_to_e164_whenever_there_is_one(s):
    e = phone.to_e164(s)
    if e is not None:
        assert phone.last10(s) == e[-10:]
    if phone.last10(s) is None:
        assert e is None


@given(noisy_number())
def test_last10_ignores_the_country_code_and_the_noise(case):
    ten, spelled = case
    assert phone.last10(spelled) == ten


@given(digit_strings, ten_digits)
def test_last10_only_looks_at_the_tail(head, ten):
    # Whatever precedes the last ten digits (an extension, a country code) is not part of the key.
    assert phone.last10(head + ten) == ten


# -- display() ------------------------------------------------------------------------------
@given(noisy_number())
def test_display_round_trips_a_us_number_to_aaa_bbb_cccc(case):
    ten, spelled = case
    shown = phone.display(spelled)
    assert re.fullmatch(r"[0-9]{3}-[0-9]{3}-[0-9]{4}", shown)
    assert shown.replace("-", "") == ten
    assert phone.display(phone.to_e164(spelled)) == shown
    assert phone.display(shown) == shown            # stable on its own output
    assert phone.to_e164(shown) == phone.to_e164(spelled)


@given(messy_text)
def test_display_leaves_a_non_number_exactly_as_given(s):
    if phone.to_e164(s) is None:
        assert phone.display(s) == s
    else:
        assert phone.display(s) == phone.display(phone.to_e164(s))


@given(any_text)
def test_display_leaves_any_non_number_untouched_whatever_its_characters(s):
    # Letters of both cases, whitespace and Unicode are all returned as typed: no strip(), no case
    # folding, no normalising.
    if phone.to_e164(s) is None:
        assert phone.display(s) == s
    else:
        assert re.fullmatch(r"[0-9]{3}-[0-9]{3}-[0-9]{4}", phone.display(s))


@given(any_text)
def test_display_keeps_the_padding_of_a_non_number(s):
    padded = "  " + s + " \x09\x0a"
    if phone.to_e164(padded) is None:
        assert phone.display(padded) == padded


# -- inputs that are not strings ------------------------------------------------------------
NON_STRINGS = st.one_of(
    st.none(), st.integers(), st.floats(allow_nan=True, allow_infinity=True), st.booleans(),
    st.binary(max_size=12), st.lists(st.integers(), max_size=4),
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=2),
)


@given(NON_STRINGS)
def test_a_non_string_never_raises_and_keeps_the_types(x):
    d = phone.digits(x)
    assert isinstance(d, str) and re.fullmatch(r"[0-9]*", d)
    e = phone.to_e164(x)
    assert e is None or re.fullmatch(r"\+1[0-9]{10}", e)
    k = phone.last10(x)
    assert k is None or re.fullmatch(r"[0-9]{10}", k)
    assert isinstance(phone.display(x), str)
    if x is None:
        assert (d, e, k, phone.display(x)) == ("", None, None, "")


@given(NON_STRINGS)
def test_a_non_string_is_read_as_its_str_form(x):
    # None is "nothing"; everything else is judged by str(x), including a falsy 0 / 0.0 / False.
    if x is not None:
        assert phone.digits(x) == phone.digits(str(x))
        assert phone.to_e164(x) == phone.to_e164(str(x))
        assert phone.last10(x) == phone.last10(str(x))


def test_a_zero_is_the_digit_zero_not_nothing():
    assert phone.digits(0) == "0"
    assert phone.digits(0.0) == "00"
    assert phone.digits(False) == ""      # str(False) == "False": no digits
    assert phone.digits(None) == "" and phone.digits("") == ""


@given(st.integers(min_value=10**9, max_value=10**10 - 1))
def test_a_ten_digit_integer_is_a_number(n):
    assert phone.to_e164(n) == "+1%d" % n
    assert phone.last10(n) == "%d" % n


@given(st.integers(min_value=0, max_value=10**9 - 1))
def test_a_short_integer_is_not_a_number(n):
    assert phone.to_e164(n) is None
    assert phone.last10(n) is None


@given(st.integers(min_value=-(10**12), max_value=10**12))
def test_the_sign_of_an_integer_is_noise_not_a_digit(n):
    assert phone.digits(n) == phone.digits(abs(n))
    assert phone.to_e164(n) == phone.to_e164(abs(n))


# -- the frontend gives the same answers ----------------------------------------------------
_NODE_SCRIPT = r"""
const fs = require("fs"), vm = require("vm");
const ctx = {}; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const raws = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
// Escape every non-ASCII character: last_json_line() splits stdout with str.splitlines(), which
// also breaks at U+2028, U+0085 and the like that JSON.stringify leaves raw.
const out = JSON.stringify(raws.map((r) => [ctx.BD.e164(r), ctx.BD.fmtPhone(r)]));
console.log(out.replace(/[\u007f-\uffff]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0")));
"""

batches = st.lists(
    st.one_of(noisy_number().map(lambda t: t[1]), templated_number().map(lambda t: t[1]),
              messy_text, digit_strings, any_text),
    min_size=100, max_size=200,
)


@BD_PAGE_HELPERS_NOT_MOVED
@settings(max_examples=5, deadline=None, suppress_health_check=list(HealthCheck))
@given(batches)
def test_python_and_the_frontend_agree_on_a_generated_batch(raws):
    with tempfile.TemporaryDirectory() as tmp:
        js = pathlib.Path(tmp) / "e164.js"
        data = pathlib.Path(tmp) / "raws.json"
        js.write_text(_NODE_SCRIPT, encoding="utf-8")
        data.write_text(json.dumps(raws), encoding="utf-8")
        proc = run_node(js, SHARED_JS, data)
    assert proc.returncode == 0, proc.stderr
    got = last_json_line(proc.stdout)
    assert [r[0] for r in got] == [phone.to_e164(r) for r in raws]
    assert [r[1] for r in got] == [phone.display(r) for r in raws]
