"""What order a browser RUNS a page's scripts in: the one place that knows.

The app's pages are plain HTML with script tags and no bundler, so "which file loaded first" is the
whole dependency system, and a mistake in it is silent: the page renders, a global is `undefined`, and
the first thing that touches it throws, or the page sits on its loading message for ever. Tests that
need the order (test_bid_model_rename.py, test_core_boot_order.py) read it from here.

A real HTML parser, not a pattern. A script tag inside an HTML comment is not a script tag, and a
regular expression cannot tell the two apart (the tests are not allowed to strip markup with one).
Only the page's own scripts are returned; an address on another host (the Supabase client) is not a
file in this repository.
"""
from __future__ import annotations

import html.parser


class _ScriptTags(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts = []          # (src without its query string, runs after the page is parsed)

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        a = dict(attrs)
        if a.get("src"):
            deferred = "defer" in a or a.get("type") == "module"
            self.scripts.append((a["src"].split("?")[0], deferred))


def execution_order(page_html: str):
    """The script addresses of a page in the order a browser RUNS them: scripts without `defer` first,
    in document order, then the deferred ones in document order. Addresses as written, e.g. "/js/x.js"."""
    tags = _ScriptTags()
    tags.feed(page_html)
    tags.close()
    return ([src for src, deferred in tags.scripts if not deferred] +
            [src for src, deferred in tags.scripts if deferred])


def local_scripts(page_html: str):
    """`execution_order`, kept to this repository's own files, as paths under frontend/ ("js/x.js")."""
    return [src.lstrip("/") for src in execution_order(page_html)
            if src.startswith("/") and not src.startswith("//")]
