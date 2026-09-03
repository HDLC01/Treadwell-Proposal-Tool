"""Which sidebar tabs a role may reach — a deny list, edited from the Admin page.

Hanz, 2026-08-19, looking at the read-only "What each role can see" matrix on the Admin page:
"I cant toggle these on and off?" Asked whether hiding the tab was enough or the page had to
actually refuse, he chose REAL BLOCKING.

SHIPS AS A PROVABLE NO-OP. He has not decided which tabs to restrict, so the file this module
reads does not exist on any box and nothing here changes a single response until somebody flips
a switch in the UI. Absent file, absent role, absent path, or a garbled file ALL mean nothing is
denied — today's behaviour, byte for byte. That is the property to protect above every other one
in this file, because it is what makes shipping this safe before the decision is made.

DENY LIST, NOT ALLOW LIST. An allow list has to name every tab just to preserve today's
behaviour, so a half-written file — or one written by a UI that predates a page added later —
locks people out of pages nobody meant to touch. A deny list's worst failure is "a tab somebody
wanted blocked is still open", which is exactly where we already are.

A FILE, not a database table, mirroring backend/pull_window.py deliberately: staff edit it from a
page, so an env var (a redeploy and somebody with SSH) is out; and the recovery path for a policy
that shut the wrong person out has to be ONE command, with no SQL, no DDL and no PostgREST schema
reload:

    docker exec treadwell-proposal-tool rm -f /app/data/nav_access.json

FAIL OPEN ON READ, LOUD ON WRITE — pull_window.py's posture, for a sharper reason here. This is an
internal tool with three accounts; a lockout is an outage the affected person cannot fix, and the
data behind these tabs is still behind the existing _require_admin gates. A failed WRITE is
raised, because a policy that "saved" into one container's memory and nowhere else is worse than
one that refused: the person who set it has no way to find out.

THE CAPABILITY TABLE BELOW IS KEYED ON HREF because href is the only identity the Admin matrix
has. auth.js's navMatrix() builds its rows by re-rendering the real sidebar per role and keying
them `byHref`; admin.js stamps `data-href` on each row. Keying on label would break the day
somebody renames a tab, and there is no id anywhere.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import atomic_json

log = logging.getLogger("treadwell.nav_access")

# Beside the drafts DB and the analytics pull window on the data volume — the same volume, for the
# same reason pull_window.py gives: it is the thing that survives `docker compose up -d --build`.
_DATA_DIR = Path(os.environ.get("DRAFTS_DB_PATH", "/app/data/drafts.db")).parent
_FILE = _DATA_DIR / "nav_access.json"

_LOCK = threading.Lock()

# The three roles profiles.py can store. Least privileged first, same order as auth.js's ROLES.
ROLES: Tuple[str, ...] = ("user", "admin", "super_admin")

# Nothing denied. The value returned for an absent, empty or unreadable file.
EMPTY: Dict[str, Any] = {"version": 1, "deny": {}, "updated_at": None, "updated_by": None}

_VERSION = 1


# ─── What each sidebar tab owns ────────────────────────────────────────────────
# `pages` — the .html shells whose own JS should refuse to paint for a denied role.
# `api`   — the API prefixes that belong to THIS TAB AND NO OTHER. An entry ending in "/" matches
#           children only; anything else is an exact path match.
#
# ONLY SINGLE-CALLER PREFIXES ARE LISTED, and the empty `api` tuples are the whole point of this
# comment. Per-tab API gating is incoherent for five of the fifteen tabs because the routes their
# pages read are read by other pages too, measured by grepping frontend/ for every /api/ string:
#
#   * bare /api/analytics       — analytics.js AND calendar.js (+ both -core files). Gating it
#                                 would blank the Bid Calendar, which reads the same payload.
#   * /api/library/items,
#     /api/library/assemblies   — library.js AND polish-estimate.js. Gating them would stop the
#                                 Polish beta pricing halfway through a bid, silently.
#   * /api/portal/pipeline      — portal.js AND notifications.js. Two tabs, one route.
#   * /api/notifications        — auth.js, on EVERY page, and it is what boots the lead autopilot.
#   * /api/draft/*, /api/drafts,
#     /api/estimators,
#     /api/generate, /api/file/* — the wizard, which has no sidebar row of its own. Gating any of
#                                 them stops the tool making proposals.
#
# So those five tabs are PAGE-REFUSAL ONLY: the tab leaves the menu and the page paints a refusal
# card, but their data stays reachable to somebody who types the URL and knows the route. The Admin
# page says that on screen in words rather than implying a lock it does not have.
#
# The near-miss worth recording: /api/portal/notify-overrides-all IS called only by
# notifications.js, so by the single-caller rule Notification Sending could own it. It is
# deliberately NOT gated, because the roster the same page is built around —
# /api/portal/notify-recipients — is shared with the CRM drawer in portal.js. Gating one leaf and
# not the other would 403 half of one page while protecting nothing, which is worse than a clean
# page refusal: it looks like a bug rather than a policy.
TABS: Dict[str, Dict[str, Any]] = {
    "/portal.html": {
        "label": "Active Projects",
        "pages": ("/portal.html",),
        "api": (),
    },
    "/leads.html": {
        "label": "Lead Inbox",
        # Both forms: the bare route is the inbox list, and the children are one message's body,
        # status, prequalify and create-estimate. An exact-only entry would leave the children open.
        "pages": ("/leads.html",),
        "api": ("/api/leads", "/api/leads/"),
    },
    "/crm.html": {
        "label": "Bid Pipeline",
        # Children only — there is no bare /api/basisboard route. status + projects, crm.js alone.
        "pages": ("/crm.html",),
        "api": ("/api/basisboard/",),
    },
    "/calendar.html": {
        "label": "Bid Calendar",
        # The calendar's OWN events, which only it reads or writes. It also reads bare
        # /api/analytics for the BasisBoard deadlines, and that stays open — see the note above.
        "pages": ("/calendar.html",),
        "api": ("/api/calendar/events", "/api/calendar/events/"),
    },
    "/info-sheet.html": {
        "label": "Info Sheet",
        # NO SIDEBAR ROW since 2026-08-20 — it moved into the project drawer's Proposal tab. The
        # entry stays anyway; see NO_SIDEBAR_TABS below for why deleting it would have been a
        # security regression rather than a tidy-up. Being in the menu is not what makes a tab
        # deniable, and this table is what gates the page and the routes below.
        # Children only: /{draft_id} and /generate. No bare route exists.
        "pages": ("/info-sheet.html",),
        "api": ("/api/info-sheet/",),
    },
    "/followups.html": {
        "label": "Follow-ups",
        # BACK IN THE SIDEBAR ON 2026-08-24 (Hanz reversed his own 2026-08-10 removal; auth.js
        # carries all three decisions). It had NO entry here at all while it was unlinked, which is
        # the opposite of the Info Sheet case below: that tab kept its entry when its row left, this
        # one had to GAIN one when its row came back, or the page would be the only sidebar row in
        # the menu that no policy could reach. It also came out of ALWAYS_OPEN_PAGES in the same
        # edit; a page cannot be both governed and never-governed.
        #
        # /api/portal/followups is the whole feed and followups.js is its ONLY caller (grep
        # frontend/ for the string). Exact match, no trailing slash: there are no children, and a
        # slashless prefix is exactly what keeps this from reaching /api/portal/proposal/{id}/...
        #
        # THE FOUR ROUTES THE PAGE ALSO CALLS ARE DELIBERATELY NOT LISTED. Its Send, Log a call and
        # the board's drag all post to /api/portal/proposal/{id}/{reply,followups,status,
        # followup-automation}, and every one of those is also the CRM drawer's (portal.js) and one
        # is notifications.js's. Claiming them would 403 the drawer on a page nobody restricted,
        # which is the single-caller rule this table is built on.
        "pages": ("/followups.html",),
        "api": ("/api/portal/followups",),
    },
    "/polish-intake.html": {
        "label": "Polish Estimate",
        # TWO PAGES on one sidebar row. Step 2 is opened directly from two places that are not this
        # tab — the beta link in the Estimate Review toolbar (estimate-review.html) and the step-2
        # link on polish-intake.html itself — so denying the row has to cover both or the door is
        # simply the other one. The row's href stays step 1 because that is what the menu links to.
        "pages": ("/polish-intake.html", "/polish-estimate.html"),
        "api": (),
    },
    "/analytics.html": {
        "label": "Analytics",
        # CHILDREN ONLY, and the trailing slash is load-bearing: /api/analytics/export and
        # /api/analytics/pull-window are analytics.js's alone, while the BARE /api/analytics is
        # also the Bid Calendar's data source and must keep answering.
        "pages": ("/analytics.html",),
        "api": ("/api/analytics/",),
    },
    "/projects.html": {
        "label": "Proposals Database",
        "pages": ("/projects.html",),
        "api": (),
    },
    "/library.html": {
        "label": "Items and Assemblies",
        "pages": ("/library.html",),
        "api": (),
    },
    "/markup.html": {
        "label": "Markup",
        # api: () DELIBERATELY — gating /api/markup would stop the Polish beta's pricing
        # halfway through a bid the moment a non-admin's read failed, silently. Reads stay open
        # to anyone signed in; writes are refused by _require_admin in main.py instead, which is
        # a separate mechanism from nav access. See the identical reasoning on /library.html
        # (Vendors) and /polish-intake.html above.
        "pages": ("/markup.html",),
        "api": (),
    },
    "/history.html": {
        "label": "History",
        "pages": ("/history.html",),
        "api": ("/api/history",),
    },
    "/trash.html": {
        "label": "Trash",
        # /api/trash is the listing and nothing else; the restore / permanent-delete calls go to
        # /api/draft/* which the wizard and the Database also use, so they stay open.
        "pages": ("/trash.html",),
        "api": ("/api/trash",),
    },
    "/notifications.html": {
        "label": "Notification Sending",
        "pages": ("/notifications.html",),
        "api": (),
    },
    "/followup-settings.html": {
        "label": "Auto Followups",
        # GET + PUT on the bare route, POST on /preview. The PUT is the one write in this app that
        # is not admin-gated and rewrites four emails that go to customers with no history, so this
        # is the tab where a real block is worth the most.
        "pages": ("/followup-settings.html",),
        "api": ("/api/followup-settings", "/api/followup-settings/"),
    },
    "/admin.html": {
        "label": "Admin",
        "pages": ("/admin.html",),
        # /api/admin/* is already behind _require_admin. Listing it here would let this policy take
        # the Admin page away from an admin, which is the one lockout with no way back in the UI.
        "api": (),
    },
}

# CANNOT BE DENIED TO ANYBODY, stripped inside save() rather than merely greyed out in the UI —
# a policy file is hand-editable and reaches the middleware whatever the browser did.
#
#   /admin.html  is where this policy is edited. Denying it removes the only door back.
#   /portal.html is HOME_PAGE in auth.js: signing in lands you there, so denying it would greet
#                somebody with a refusal card as the first thing they see after Google.
LOCKED: Tuple[str, ...] = ("/admin.html", "/portal.html")

# The super admin is bootstrapped from SUPER_ADMIN_EMAIL and cannot be granted or revoked from the
# UI; his role exists so somebody always has a way in. A policy that can deny it is a policy that
# can lock the owner out of his own tool.
LOCKED_ROLES: Tuple[str, ...] = ("super_admin",)

# Pages with no sidebar row, which this policy never touches. The four wizard screens plus the two
# unlinked-but-live pages. Listed so the next person does not have to work out why /done.html is
# absent from TABS and conclude it was forgotten.
#   index / estimate-review / proposal-review / done — the wizard; every proposal goes through them
#   dropbox.html     — reached from the wizard's step 5, never from the menu
#   login.html       — signing in cannot require being signed in
#
# /followups.html LEFT THIS LIST ON 2026-08-24 and took a TABS entry instead, because Hanz put it
# back in the sidebar (auth.js records all three decisions). The two lists are mutually exclusive by
# construction: everything here is ungovernable, and test_the_pages_with_no_sidebar_row_are_never_denied
# denies every tab in TABS at once and asserts these pages survive it. A page in both lists is a
# contradiction that test would report as a failure, which is the point of keeping them separate
# rather than deriving one from the other.
ALWAYS_OPEN_PAGES: Tuple[str, ...] = (
    "/", "/index.html", "/estimate-review.html", "/proposal-review.html", "/done.html",
    "/dropbox.html", "/login.html",
)

# GATED BUT NOT IN THE SIDEBAR — the exact opposite of ALWAYS_OPEN_PAGES above, and the reason both
# sets are spelled out rather than inferred from the menu.
#
#   ALWAYS_OPEN_PAGES have no sidebar row AND no TABS entry, so this policy can never reach them.
#   These have no sidebar row and KEEP their TABS entry: the tab stays deniable per role and still
#   owns its API prefixes. A tab lands here when its entry point moves somewhere that is not the
#   menu — a card, a drawer, another page's toolbar.
#
#   /info-sheet.html — moved into the project drawer's Proposal tab on 2026-08-20 (Hanz). The
#                      sidebar row opened a choose-a-project state; from the drawer the hand-off is
#                      one click on the job already in hand.
#
# WHY THE ENTRY DID NOT JUST COME OUT OF TABS. test_nav_access.py compares the sidebar's navItem()
# hrefs against this table, so deleting the entry is the shortest way to keep that test green — and
# it would silently drop the per-role gate on /api/info-sheet/*, leaving the page undeniable and its
# routes ungated. A security regression dressed as a test fix. The set below is the honest version:
# the tab is still governed, it simply is not drawn.
#
# The Admin page can still switch these, so a role cannot be denied a tab with no way to undo it:
# auth.js keeps a matching NO_SIDEBAR_TABS list and navMatrix appends a row for each whenever it is
# rendering a policy. The two lists are asserted equal in test_nav_access.py, because two copies of
# one list is how one of them rots.
NO_SIDEBAR_TABS: Tuple[str, ...] = ("/info-sheet.html",)


class NavAccessError(ValueError):
    """The policy a caller asked for is not a policy."""


class NavAccessWriteError(RuntimeError):
    """The policy could not be persisted, so nothing may act as though it was."""


# ─── normalising ──────────────────────────────────────────────────────────────
def _norm_href(value: Any) -> str:
    """A tab href, lowercased with a leading slash — or "" for anything unrecognised."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if not text.startswith("/"):
        text = "/" + text
    return text


def sanitize(deny: Any) -> Dict[str, List[str]]:
    """The one authority on what a deny map may contain. Never raises; drops what it cannot use.

    Applied on the way OUT as well as the way IN. Both directions are tested separately, because a
    strip that exists only on write is one hand-edited file away from being no strip at all — and
    the write path is not the only way bytes get onto that volume.

    Dropped rather than rejected, because this runs on READ where the fail-open rule applies: a
    stale file naming a page that has since been deleted must mean "nothing to deny", not "no
    policy at all" and certainly not an exception on the way to a page.
    """
    out: Dict[str, List[str]] = {}
    if not isinstance(deny, dict):
        return out
    for role, paths in deny.items():
        role_name = str(role or "").strip().lower()
        if role_name not in ROLES or role_name in LOCKED_ROLES:
            continue
        if isinstance(paths, (str, bytes)) or not isinstance(paths, Iterable):
            continue
        keep: List[str] = []
        for raw in paths:
            href = _norm_href(raw)
            if href and href in TABS and href not in LOCKED and href not in keep:
                keep.append(href)
        if keep:
            out[role_name] = keep
    return out


# ─── the store ────────────────────────────────────────────────────────────────
def _read() -> Dict[str, Any]:
    if not _FILE.is_file():
        return dict(EMPTY)
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        return {"version": _VERSION, "deny": sanitize(raw.get("deny")),
                "updated_at": raw.get("updated_at") or None,
                "updated_by": raw.get("updated_by") or None}
    except Exception as exc:  # noqa: BLE001 — a bad file denies nothing; it never breaks a page
        log.warning("nav access policy unreadable (%s); nothing is denied", exc)
        return dict(EMPTY)


def get() -> Dict[str, Any]:
    """The whole policy. Always a full dict; EMPTY when unset or unusable."""
    with _LOCK:
        return _read()


def save(deny: Any, by: str = "") -> Dict[str, Any]:
    """Persist a deny map and return the stored policy.

    Raises NavAccessWriteError if it could not be written. Nothing here validates the caller —
    that is main.py's job, which also refuses a change that would shut the caller's own role out.
    """
    clean = sanitize(deny)
    out = {"version": _VERSION, "deny": clean,
           "updated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "updated_by": (by or "").strip() or None}
    with _LOCK:
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            # THE WRITE ITSELF LIVES IN atomic_json, because four other modules had this same
            # three-line pattern and the same two bugs in it - a shared temp name that only a
            # same-process lock protects, and a rename with no retry past a transient Windows
            # PermissionError. pull_window.py failed identically on the very next merge after this
            # was fixed here, which is what moved it out. The ERROR SEMANTICS stay here on purpose:
            # a failed policy write must raise, because an admin who thinks they locked a tab down
            # and did not is worse than an error message.
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            atomic_json.write_json(_FILE, out, make_parent=False)
        except Exception as exc:  # noqa: BLE001
            raise NavAccessWriteError(str(exc)) from exc
    log.info("nav access policy set by %s: %s", out["updated_by"] or "?",
             json.dumps(clean) if clean else "(nothing denied)")
    return out


# ─── reading the policy ───────────────────────────────────────────────────────
def denied_paths(role: str, policy: Optional[Dict[str, Any]] = None) -> List[str]:
    """The tab hrefs `role` may not reach. [] for an unknown role — the default is allow."""
    pol = get() if policy is None else policy
    deny = pol.get("deny") if isinstance(pol, dict) else None
    if not isinstance(deny, dict):
        return []
    return list(deny.get(str(role or "").strip().lower()) or [])


def denied_pages(role: str, policy: Optional[Dict[str, Any]] = None) -> List[str]:
    """The .html paths `role` may not open, expanded from the denied tabs' `pages`."""
    out: List[str] = []
    for href in denied_paths(role, policy):
        for page in TABS.get(href, {}).get("pages", ()):
            if page not in out:
                out.append(page)
    return out


def denied_api_prefixes(role: str, policy: Optional[Dict[str, Any]] = None) -> List[str]:
    """The API prefixes `role` may not call. Only single-caller prefixes are ever in here."""
    out: List[str] = []
    for href in denied_paths(role, policy):
        for prefix in TABS.get(href, {}).get("api", ()):
            if prefix not in out:
                out.append(prefix)
    return out


def prefix_matches(path: str, prefix: str) -> bool:
    """Does `path` fall under `prefix`? Trailing slash = CHILDREN ONLY, else an exact match.

    The distinction is not cosmetic. "/api/analytics/" must own `export` and `pull-window` while
    the BARE /api/analytics keeps answering, because the Bid Calendar reads that same payload — so
    a startswith() on a slashless prefix would blank a page nobody restricted.
    """
    p = str(path or "")
    if prefix.endswith("/"):
        return p.startswith(prefix)
    return p == prefix


def is_api_denied(role: str, path: str, policy: Optional[Dict[str, Any]] = None) -> bool:
    """True when `role` must be refused `path`."""
    for prefix in denied_api_prefixes(role, policy):
        if prefix_matches(path, prefix):
            return True
    return False


def page_denied(role: str, path: str, policy: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """The tab href that blocks `path` for `role`, or None. Page paths are matched exactly."""
    page = str(path or "").lower()
    if page.endswith("/"):
        page = page + "index.html"
    for href in denied_paths(role, policy):
        if page in TABS.get(href, {}).get("pages", ()):
            return href
    return None


def denied_page_map(role: str, policy: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """{page path: the denied tab href that owns it} for `role`.

    The client gets this rather than working the expansion out for itself, because ONE tab owns TWO
    pages (/polish-intake.html also owns /polish-estimate.html) and a second copy of that mapping in
    auth.js is the copy that goes stale. The href comes back so the refusal card can name the tab.
    """
    out: Dict[str, str] = {}
    for href in denied_paths(role, policy):
        for page in TABS.get(href, {}).get("pages", ()):
            out.setdefault(page, href)
    return out


def newly_denied(current: Any, proposed: Any, role: str) -> List[str]:
    """Paths `role` would LOSE by moving from `current` to `proposed`. [] if it only widens.

    Pure, so main.py can refuse a self-lockout without reimplementing set arithmetic. Removing a
    denial is always allowed: it can only give access back.
    """
    was = set(sanitize(current).get(role, ()))
    now = set(sanitize(proposed).get(role, ()))
    return sorted(now - was)


def locked_requested(deny: Any) -> Dict[str, List[str]]:
    """What a caller asked for that can never be granted: {"pages": [...], "roles": [...]}.

    save() strips these regardless. This exists so the API can REFUSE the request instead, because
    a switch that appears to have worked and did not is the worst of the three outcomes — worse than
    a greyed-out switch and worse than an error.
    """
    pages: List[str] = []
    roles: List[str] = []
    if not isinstance(deny, dict):
        return {"pages": pages, "roles": roles}
    for role, paths in deny.items():
        role_name = str(role or "").strip().lower()
        if role_name in LOCKED_ROLES and role_name not in roles:
            roles.append(role_name)
        if isinstance(paths, (str, bytes)) or not isinstance(paths, Iterable):
            continue
        for raw in paths:
            href = _norm_href(raw)
            if href in LOCKED and href not in pages:
                pages.append(href)
    return {"pages": sorted(pages), "roles": sorted(roles)}


def capability_table() -> List[Dict[str, Any]]:
    """The table above, as JSON for the Admin page: which pages and API prefixes each tab owns.

    The Admin page needs `api` to tell the truth on screen about the five tabs that own none —
    switching those off hides the tab and blocks the page, and leaves their data reachable.

    `no_sidebar` says the tab has no menu row at all (NO_SIDEBAR_TABS): its switch is real and its
    routes are refused, but "hide the tab" is not part of what it does, because there is nothing to
    hide. Served so the page can say that rather than the browser having to know it.
    """
    return [{"href": href, "label": tab["label"], "pages": list(tab["pages"]),
             "api": list(tab["api"]), "locked": href in LOCKED,
             "no_sidebar": href in NO_SIDEBAR_TABS}
            for href, tab in TABS.items()]
