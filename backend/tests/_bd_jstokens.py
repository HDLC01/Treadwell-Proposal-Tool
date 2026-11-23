"""A small JavaScript tokenizer for BD's guard tests (the BD page-shell and contract-JSON checks).

It is NOT a parser. It splits a source file into strings, template literals, regex literals,
identifiers, numbers and single punctuation characters, with comments dropped, which is all the
guard tests need: "which string literals does this file contain" and "which `/api/...` paths does it
hand to BDApi". Comments are dropped so a sentence in a comment ("no onclick= attributes", a route
named in prose) is never mistaken for code.

The regex-literal rule is the same as tests/js/bd/_lib.js: after one of `(,=:[!&|?{};+-*%<>~^` or a
keyword like `return`, a `/` starts a regular expression; anywhere else it divides.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

REGEX_AFTER_CHAR = set("(,=:[!&|?{};+-*%<>~^")
REGEX_AFTER_WORD = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw",
                    "case", "do", "else", "yield", "await"}
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_NUMBER = re.compile(r"(?:0[xX][0-9a-fA-F_]+|\d[\d_]*(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)n?")
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}

#: Stands for one ${...} hole in a template literal's text.
HOLE = "\x00"


@dataclass
class Tok:
    kind: str       # "str" | "template" | "regex" | "ident" | "num" | "punct"
    value: str      # decoded text for str/template, source text otherwise
    line: int       # 1-based line where the token starts
    pos: int        # index into the source


def _decode_escape(src: str, j: int) -> tuple[str, int]:
    """The character(s) an escape at src[j] == '\\' stands for, and the index after it."""
    c = src[j + 1] if j + 1 < len(src) else ""
    if c in _SIMPLE_ESCAPES:
        return _SIMPLE_ESCAPES[c], j + 2
    if c == "u":
        if src[j + 2:j + 3] == "{":
            end = src.index("}", j + 3)
            return chr(int(src[j + 3:end], 16)), end + 1
        return chr(int(src[j + 2:j + 6], 16)), j + 6
    if c == "x":
        return chr(int(src[j + 2:j + 4], 16)), j + 4
    if c == "\r" and src[j + 2:j + 3] == "\n":
        return "", j + 3
    if c == "\n":
        return "", j + 2
    return c, j + 2


def _skip_quoted(src: str, i: int) -> int:
    """Index just past the string literal whose quote is at src[i] (no decoding)."""
    q = src[i]
    j = i + 1
    while j < len(src) and src[j] != q:
        j += 2 if src[j] == "\\" else 1
    return j + 1


def _template_end(src: str, i: int) -> tuple[str, int]:
    """(text with every ${...} as HOLE, index past the closing backtick) for a template at src[i]."""
    out = []
    j = i + 1
    n = len(src)
    while j < n and src[j] != "`":
        if src[j] == "\\":
            ch, j = _decode_escape(src, j)
            out.append(ch)
            continue
        if src.startswith("${", j):
            depth = 1
            j += 2
            while j < n and depth:
                c = src[j]
                if c in "\"'":
                    j = _skip_quoted(src, j)
                    continue
                if c == "`":
                    _, j = _template_end(src, j)
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                j += 1
            out.append(HOLE)
            continue
        out.append(src[j])
        j += 1
    return "".join(out), j + 1


def tokenize(src: str) -> list[Tok]:
    src = src.replace("\r\n", "\n").lstrip("﻿")
    toks: list[Tok] = []
    i, n, line = 0, len(src), 1

    def regex_allowed() -> bool:
        if not toks:
            return True
        t = toks[-1]
        if t.kind == "punct":
            return t.value in REGEX_AFTER_CHAR
        if t.kind == "ident":
            return t.value in REGEX_AFTER_WORD
        return False

    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\f\v ﻿":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            line += src.count("\n", i, j)
            i = j
            continue
        start, start_line = i, line
        if c in "\"'":
            out = []
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    ch, j = _decode_escape(src, j)
                    out.append(ch)
                else:
                    out.append(src[j])
                    j += 1
            i = j + 1
            toks.append(Tok("str", "".join(out), start_line, start))
            line += src.count("\n", start, i)
            continue
        if c == "`":
            text, i = _template_end(src, i)
            toks.append(Tok("template", text, start_line, start))
            line += src.count("\n", start, i)
            continue
        if c == "/" and regex_allowed():
            j = i + 1
            in_class = False
            while j < n:
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "\n":
                    break
                if in_class:
                    if ch == "]":
                        in_class = False
                elif ch == "[":
                    in_class = True
                elif ch == "/":
                    break
                j += 1
            j += 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            toks.append(Tok("regex", src[i:j], start_line, start))
            i = j
            continue
        m = _IDENT.match(src, i)
        if m:
            toks.append(Tok("ident", m.group(0), start_line, start))
            i = m.end()
            continue
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            m = _NUMBER.match(src, i)
            if m and m.end() > i:
                toks.append(Tok("num", m.group(0), start_line, start))
                i = m.end()
                continue
        toks.append(Tok("punct", c, start_line, start))
        i += 1
    return toks


def string_literals(src: str) -> list[Tok]:
    """Every string and template literal in some JavaScript, comments left out."""
    return [t for t in tokenize(src) if t.kind in ("str", "template")]
