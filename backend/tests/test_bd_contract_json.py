"""docs/bd/api-contract.md: its examples are real JSON, its routes are listed once, and the BD pages
call only routes it lists (#809, BD's test_contract_json moved under /api/bd/).

The contract is the one thing the BD pages and the BD routes both code against, and it says so in its
first lines: "Every example below is real JSON (a test parses each fenced json block)". This is that
test, plus the ones that keep the route list honest:

  * every route heading is in the one form tests/_bd_routes.py reads, and unique (one route, one
    definition); a route named in the text (`POST /api/bd/...`) is one the contract documents;
  * every /api/bd/ path a BD page sends matches a documented route, with `{id}`-style segments as
    wildcards and the query string ignored. The paths are read from the source with
    tests/_bd_jstokens.py, from every script under frontend/bd/ and the /api/bd/ paths of
    frontend/auth.js (the sidebar's BD group asks /api/bd/me). A path is
      - a string literal, followed through `+` pieces: `(cond ? "/a" : "/b")` expands into both,
        anything else is a wildcard piece;
      - or BDApi.path("contacts", id, "interactions") (also through a page's `Api = window.BDApi`),
        which bd-api.js builds as /api/bd/ + its parts joined by "/".
    The METHOD is checked too wherever the source says it: BDApi.get/post/patch/put/del(path, ...),
    a local helper that hands its parameter to one (fetchAll(path)), `var p = "..."; BDApi.post(p)`,
    and a call whose first argument is the method (`f.req("POST", path, body)`).

bd-api.js itself is not scanned for literals: it is the door, it sends what the pages hand it. The
JSON shapes are compared with the serializers in test_bd_serialize.py.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from _bd_jstokens import HOLE, Tok, tokenize
from _bd_routes import METHODS, ROUTE_HEADING, contract_lines, documented

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
BD_FRONTEND = FRONTEND / "bd"
DOOR = BD_FRONTEND / "js" / "bd-api.js"

API_OBJECTS = {"BDApi", "Api"}
API_METHODS = {"get": "GET", "post": "POST", "patch": "PATCH", "put": "PUT", "del": "DELETE"}
BASE = "/api/bd/"
WILD = "\x01"     # one non-literal piece of a path expression


# ── the contract's own text ─────────────────────────────────────────────────────────────────
def json_blocks():
    """[(line of the opening fence, text)] for every ```json fence."""
    out, buf, start = [], None, 0
    for no, ln in enumerate(contract_lines(), 1):
        if buf is None and re.match(r"^```json\s*$", ln):
            buf, start = [], no
        elif buf is not None and re.match(r"^```\s*$", ln):
            out.append((start, "\n".join(buf)))
            buf = None
        elif buf is not None:
            buf.append(ln)
    assert buf is None, "a ```json fence opened at line %d is never closed" % start
    return out


def documented_routes():
    """[(METHOD, path, line)] for every route heading."""
    out = []
    for no, ln in enumerate(contract_lines(), 1):
        m = ROUTE_HEADING.match(ln)
        if m:
            out.append((m.group(1), m.group(2), no))
    return out


def test_contract_has_json_examples():
    # 60-odd today; a parse that finds a handful means the fence pattern broke, not the document.
    assert len(json_blocks()) >= 40


@pytest.mark.parametrize("line,text", json_blocks(), ids=["line%d" % b[0] for b in json_blocks()])
def test_every_json_block_parses(line, text):
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        pytest.fail("docs/bd/api-contract.md line %d: the ```json block is not valid JSON: %s (block line %d)"
                    % (line, e.msg, e.lineno), pytrace=False)


def test_route_headings_are_well_formed():
    """A `####` heading that names an /api route must be in the one form the other tests read: one
    route per heading, under /api/bd/, and who may call it in brackets."""
    bad = []
    for no, ln in enumerate(contract_lines(), 1):
        if ln.startswith("#### ") and "/api/" in ln and not ROUTE_HEADING.match(ln):
            bad.append("line %d: %s" % (no, ln))
    assert not bad, "route headings must read #### `METHOD /api/bd/path` (who):\n" + "\n".join(bad)


def test_route_headings_are_unique():
    routes = documented_routes()
    assert len(routes) >= 45, "found only %d route headings" % len(routes)
    seen, dups = {}, []
    for method, path, no in routes:
        key = (method, path)
        if key in seen:
            dups.append("%s %s at lines %d and %d" % (method, path, seen[key], no))
        seen[key] = no
    assert not dups, "a route is documented twice:\n" + "\n".join(dups)


_NAMED = re.compile(r"`(GET|POST|PATCH|PUT|DELETE) (/api/bd/[^`\s?]*)")


def test_every_route_named_in_the_text_is_documented():
    """`POST /api/bd/admin/weekly/run` in a sentence must be a route the contract documents."""
    docs = set(documented())
    bad = ["line %d: %s %s" % (no, m.group(1), m.group(2))
           for no, ln in enumerate(contract_lines(), 1) for m in _NAMED.finditer(ln)
           if (m.group(1), m.group(2)) not in docs]
    assert not bad, "the contract names routes it does not document:\n" + "\n".join(bad)


def test_no_route_is_documented_outside_api_bd():
    for ln in contract_lines():
        assert not re.search(r"`(GET|POST|PATCH|PUT|DELETE) /api/(?!bd/)", ln), ln


# ── the pages' calls ────────────────────────────────────────────────────────────────────────
def route_regex(path):
    return re.compile("^" + re.sub(r"\\\{[^/]*?\\\}", "[^/]+", re.escape(path)) + "$")


ROUTE_RES = [(m, p, route_regex(p)) for m, p, _ in documented_routes()]


def _close(toks, i):
    """Index of the bracket closing the one at toks[i]."""
    pair = {"(": ")", "[": "]", "{": "}"}
    want, depth = pair[toks[i].value], 0
    for j in range(i, len(toks)):
        v = toks[j].value if toks[j].kind == "punct" else None
        if v in pair:
            depth += 1
        elif v in pair.values():
            depth -= 1
            if depth == 0:
                assert v == want, "unbalanced brackets at line %d" % toks[j].line
                return j
    raise AssertionError("unclosed bracket at line %d" % toks[i].line)


def _is(t, kind, value=None):
    return t is not None and t.kind == kind and (value is None or t.value == value)


def _at(toks, i):
    return toks[i] if 0 <= i < len(toks) else None


def _postfix_end(toks, j):
    """Past any .name, [..] and (..) after the operand that ends just before j."""
    while j < len(toks):
        t = toks[j]
        if _is(t, "punct", ".") and _is(_at(toks, j + 1), "ident"):
            j += 2
        elif _is(t, "punct", "(") or _is(t, "punct", "["):
            j = _close(toks, j) + 1
        else:
            break
    return j


def _literal(t):
    """The text of a string or template token, a template's holes as WILD."""
    return t.value.replace(HOLE, WILD) if t.kind == "template" else t.value


def _is_path_call(toks, k):
    """True when toks[k] starts `BDApi.path(` (or `Api.path(`)."""
    return (_is(toks[k], "ident") and toks[k].value in API_OBJECTS and _is(_at(toks, k + 1), "punct", ".")
            and _is(_at(toks, k + 2), "ident", "path") and _is(_at(toks, k + 3), "punct", "("))


def _path_call_alternatives(toks, k):
    """(the path BDApi.path(...) at toks[k] builds, index past its closing bracket): /api/bd/ and its
    parts joined by "/", a part that is one string literal kept, any other part a WILD."""
    open_paren = k + 3
    end = _close(toks, open_paren)
    parts, start, depth = [], open_paren + 1, 0
    for j in range(open_paren + 1, end + 1):
        t = toks[j]
        if t.kind == "punct" and t.value in "([{":
            depth += 1
        elif t.kind == "punct" and t.value in ")]}" and j != end:
            depth -= 1
        if j == end or (depth == 0 and _is(t, "punct", ",")):
            piece = toks[start:j]
            parts.append(_literal(piece[0]) if len(piece) == 1 and piece[0].kind in ("str", "template") else WILD)
            start = j + 1
    return BASE + "/".join(parts), end + 1


def path_alternatives(toks, k):
    """The path expression that starts at toks[k] (a string literal, or BDApi.path(...)), as every
    literal it can be: a non-literal piece becomes WILD, a parenthesised `c ? "x" : "y"` both."""
    if _is_path_call(toks, k):
        first, j = _path_call_alternatives(toks, k)
        alts = [first]
    else:
        alts = [_literal(toks[k])]
        j = k + 1
    while _is(_at(toks, j), "punct", "+"):
        j += 1
        t = toks[j]
        if t.kind in ("str", "template") and _postfix_end(toks, j + 1) == j + 1:
            alts = [a + _literal(t) for a in alts]
            j += 1
            continue
        if _is(t, "punct", "("):
            e = _close(toks, j)
            inner = toks[j + 1:e]
            choice = None
            q = next((n for n, x in enumerate(inner) if _is(x, "punct", "?")), None)
            if q is not None and len(inner) == q + 4 and inner[q + 1].kind == "str" \
                    and _is(inner[q + 2], "punct", ":") and inner[q + 3].kind == "str":
                choice = [inner[q + 1].value, inner[q + 3].value]
            after = _postfix_end(toks, e + 1)
            if choice and after == e + 1:
                alts = [a + c for a in alts for c in choice]
            else:
                alts = [a + WILD for a in alts]
            j = after
            continue
        # any other operand: a name, a call, a member chain, a number
        alts = [a + WILD for a in alts]
        j = _postfix_end(toks, j + 1)
    return alts


def _enclosing_call(toks, k):
    """(index of the "(" of the call whose argument list holds toks[k], argument index) or None."""
    depth, arg = 0, 0
    for j in range(k - 1, -1, -1):
        t = toks[j]
        if t.kind != "punct":
            continue
        if t.value in ")]}":
            depth += 1
        elif t.value in "([{":
            if depth == 0:
                return (j, arg) if t.value == "(" else None
            depth -= 1
        elif t.value == "," and depth == 0:
            arg += 1
        elif t.value == ";" and depth == 0:
            return None
    return None


def _api_call_at(toks, open_paren):
    """"POST" when toks[open_paren] is the "(" of BDApi.post( / Api.post(, else None."""
    name, dot, obj = _at(toks, open_paren - 1), _at(toks, open_paren - 2), _at(toks, open_paren - 3)
    if _is(name, "ident") and name.value in API_METHODS and _is(dot, "punct", ".") \
            and _is(obj, "ident") and obj.value in API_OBJECTS:
        return API_METHODS[name.value]
    return None


def _api_calls_sending(toks, start, end, ident):
    """Methods of every BDApi call in toks[start:end] whose first argument begins with `ident`."""
    out = set()
    for j in range(start, end):
        if _is(toks[j], "punct", "(") and _is(_at(toks, j + 1), "ident", ident):
            m = _api_call_at(toks, j)
            if m:
                out.add(m)
    return out


def _method_of(toks, k):
    """The HTTP method the path expression at toks[k] is sent with, or None when the source does not say."""
    call = _enclosing_call(toks, k)
    if call:
        open_paren, arg = call
        m = _api_call_at(toks, open_paren)
        if m:
            return m if arg == 0 else None
        first, comma = _at(toks, open_paren + 1), _at(toks, open_paren + 2)
        if arg == 1 and _is(first, "str") and first.value in METHODS and _is(comma, "punct", ","):
            return first.value                          # req("POST", path, body)
        fname = _at(toks, open_paren - 1)
        if _is(fname, "ident") and not _is(_at(toks, open_paren - 2), "punct", "."):
            # a local helper: function fname(a, b, path) { ... Api.get(path ...) ... }
            for j in range(len(toks) - 3):
                if _is(toks[j], "ident", "function") and _is(toks[j + 1], "ident", fname.value) \
                        and _is(toks[j + 2], "punct", "("):
                    pe = _close(toks, j + 2)
                    params = [t.value for t in toks[j + 3:pe] if t.kind == "ident"]
                    if arg < len(params) and _is(_at(toks, pe + 1), "punct", "{"):
                        methods = _api_calls_sending(toks, pe + 1, _close(toks, pe + 1), params[arg])
                        if len(methods) == 1:
                            return methods.pop()
        return None
    # var path = "/api/bd/..." + ...;  ... BDApi.post(path, ...)
    if _is(_at(toks, k - 1), "punct", "=") and _is(_at(toks, k - 2), "ident"):
        name = toks[k - 2].value
        stop = next((j for j in range(k, len(toks)) if _is(toks[j], "ident", "function")), len(toks))
        methods = _api_calls_sending(toks, k, stop, name)
        if len(methods) == 1:
            return methods.pop()
    return None


def paths_in(src):
    """[(line, METHOD or None, path with WILD pieces)] for every /api/bd/ path expression in `src`."""
    toks = tokenize(src)
    out = []
    for k, t in enumerate(toks):
        if (t.kind in ("str", "template") and _literal(t).startswith("/api/bd")) or _is_path_call(toks, k):
            method = _method_of(toks, k)
            for alt in path_alternatives(toks, k):
                out.append((t.line, method, alt))
    return out


def scanned_files():
    files = sorted(p for p in BD_FRONTEND.rglob("*.js") if p != DOOR)
    return files + [FRONTEND / "auth.js"]


def frontend_api_paths():
    """[(file, line, METHOD or None, path)] for every /api/bd/ path a BD page sends."""
    out = []
    for f in scanned_files():
        rel = f.relative_to(FRONTEND).as_posix()
        for line, method, path in paths_in(f.read_text(encoding="utf-8")):
            out.append((rel, line, method, path))
    return out


def _candidates(path):
    """The concrete paths a WILD-bearing path is checked as."""
    p = path.split("?", 1)[0]
    outs = {p.replace(WILD, "7")}
    if p.endswith(WILD) and not p.endswith("/" + WILD):
        outs.add(p.rstrip(WILD).replace(WILD, "7"))      # "/api/bd/x" + qs: the piece may be a query
    return outs


def matches(method, path):
    for concrete in _candidates(path):
        for m, _, rx in ROUTE_RES:
            if rx.match(concrete) and (method is None or method == m):
                return True
    return False


def test_scanner_finds_the_calls():
    """The scanner is only worth something if it sees the calls; pin some that need each rule."""
    found = {(m, p.replace(WILD, "{x}")) for _, _, m, p in frontend_api_paths()}
    assert len(found) >= 40, sorted(found)
    for want in [
        (None, "/api/bd/me"),                                          # auth.js: fetch(apiBase() + "/api/bd/me")
        ("POST", "/api/bd/week/ten-more"),                             # a direct call
        ("GET", "/api/bd/companies"),                                  # fetchAll("/api/bd/companies")
        ("PATCH", "/api/bd/admin/users/{x}"),                          # Api.patch(Api.path("admin", "users", id))
        ("POST", "/api/bd/admin/unmatched-calls/{x}/attach"),
        ("POST", "/api/bd/interactions/{x}/recommend"),                # f.req("POST", BDApi.path(...))
        ("POST", "/api/bd/recommendations/{x}/confirm"),
        ("DELETE", "/api/bd/interactions/{x}"),                        # Api.del(Api.path("interactions", id))
        ("GET", "/api/bd/review/candidates?status=all"),               # Potential BD Contacts
        ("GET", "/api/bd/analytics/export.csv?{x}"),                   # Analytics' CSV
        ("POST", "/api/bd/admin/import"),                              # Admin > Imports
    ]:
        assert want in found, "the scanner no longer sees %s %s" % want
    files = {f for f, _l, _m, _p in frontend_api_paths()}
    assert {"auth.js", "bd/js/bd-admin.js", "bd/js/bd-review.js", "bd/js/bd-analytics.js",
            "bd/js/bd-week.js", "bd/js/bd-call.js", "bd/js/bd-contact.js", "bd/js/bd-add.js"} <= files


def test_every_bd_page_call_is_documented():
    bad = ["%s:%d %s %s" % (f, line, m or "(any method)", p.replace(WILD, "{x}"))
           for f, line, m, p in frontend_api_paths() if not matches(m, p)]
    assert not bad, ("these BD page calls match no route in docs/bd/api-contract.md (add the route "
                     "there, or fix the path):\n" + "\n".join(bad))


def test_no_bd_page_names_an_api_path_in_its_html():
    """The pages have no inline script (CSP); an /api/ path in markup (a link, a form's action) would be
    a call nobody checks. An HTML comment may name a route: it is prose, like a script's comments."""
    for page in sorted(BD_FRONTEND.rglob("*.html")):
        markup = re.sub(r"<!--.*?-->", "", page.read_text(encoding="utf-8"), flags=re.S)
        assert "/api/" not in markup, page.name


def test_the_door_builds_paths_as_the_scanner_reads_them():
    """bd-api.js's path(): /api/bd/ and the parts, each encoded, joined by "/" (test_bd_api_js runs it)."""
    src = DOOR.read_text(encoding="utf-8")
    assert 'var BASE = "/api/bd/";' in src
    assert re.search(r"return BASE \+ Array\.prototype\.map\.call\(arguments, .*?\)\.join\(\"/\"\);", src)


def test_scanner_rules():
    """The expression rules on small inputs, so a failure above is about the pages, not the scanner."""
    W = WILD
    assert [(m, p) for _l, m, p in paths_in('BDApi.get("/api/bd/contacts/" + c.id + "/interactions");')] == \
        [("GET", "/api/bd/contacts/" + W + "/interactions")]
    assert [(m, p) for _l, m, p in paths_in('Api.post(Api.path("admin", "unmatched-calls", u.id, "dismiss"), {});')] == \
        [("POST", "/api/bd/admin/unmatched-calls/" + W + "/dismiss")]
    assert [(m, p) for _l, m, p in paths_in('f.req("PATCH", BDApi.path("interactions", f.iid), {summary: x});')] == \
        [("PATCH", "/api/bd/interactions/" + W)]
    assert [(m, p) for _l, m, p in paths_in('var p = "/api/bd/r/" + id + (k === "a" ? "/add" : "/ignore"); BDApi.post(p, {});')] == \
        [("POST", "/api/bd/r/" + W + "/add"), ("POST", "/api/bd/r/" + W + "/ignore")]
    assert [(m, p) for _l, m, p in paths_in('function f(p) { return Api.get(p + "?x=1"); } f("/api/bd/companies");')] == \
        [("GET", "/api/bd/companies")]
    assert [(m, p) for _l, m, p in paths_in('// BDApi.get("/api/bd/in-a-comment")\nfoo("/api/bd/a?" + q());')] == \
        [(None, "/api/bd/a?" + W)]
    assert [(m, p) for _l, m, p in paths_in('Api.get(Api.path("contacts", 7) + "?limit=1");')] == \
        [("GET", "/api/bd/contacts/" + W + "?limit=1")]
    assert paths_in('Api.get("/api/price");') == []                     # the tool's own routes are not BD's
    assert matches("GET", "/api/bd/analytics?" + W)
    assert matches("GET", "/api/bd/contacts/" + W)
    assert not matches("DELETE", "/api/bd/contacts/" + W)
    assert not matches("PATCH", "/api/bd/admin/users")
    assert not matches(None, "/api/bd/nope")
    assert isinstance(tokenize("x = /a\"b/g; y = 'c';")[2], Tok)
    assert [t.value for t in tokenize("x = /a\"b/g; y = 'c';") if t.kind == "str"] == ["c"]
