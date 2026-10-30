"""
Project (draft) persistence + activity log — Supabase Postgres.

Two tables (created via the Supabase MCP / SQL editor):

  drafts(id text pk, data jsonb, owner_email text, created_at timestamptz,
         updated_at timestamptz, deleted_at timestamptz)
      One row per project, keyed by the client UUID in the URL (?d=<uuid>).
      `data` is the whole client state blob (we never normalise it).
      deleted_at NULL = active; non-NULL = soft-deleted (in Trash, restorable).

  events(id bigint pk, project_id text, actor_email text, action text,
         detail jsonb, created_at timestamptz)
      Audit trail — who created / generated each proposal. `detail` denormalises
      the project name + total so the History feed needs no join.

The project list is UNIFIED: every signed-in user sees all projects (one
company view), attributed by owner_email.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import cachetools

import price_rules
from supabase_client import get_client

_log = logging.getLogger("drafts")


def _log_safe(value: object, limit: int = 200) -> str:
    """A caller-controlled value (a draft id off the URL, an exception carrying a typed sheet name)
    made safe for a log line: repr() writes a newline as the two characters \\n, so nobody can forge
    a log line. The same rule as main._log_safe, which this module cannot import."""
    text = "" if value is None else str(value)
    if len(text) > limit:
        text = text[:limit] + "…"
    return repr(text)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """No-op: the schema lives in Supabase (provisioned via MCP/SQL editor).
    Kept so the app-startup hook can call it unconditionally."""
    return None


# ── drafts ────────────────────────────────────────────────────────────
# Keys that live inside the `data` blob but are set by the SERVER, never by the form.
#
# The browser PUTs the whole blob on every autosave, so anything the server wrote into it is
# erased by the next save from a tab that loaded before the write. Concretely: mark a project as
# test, leave yesterday's tab open on it, and that tab's next autosave silently drops `is_test` —
# `_tribool` reads the absence as "nobody has said", the name heuristic gets its vote back, and a
# real bid named something like "Demo Only - Bldg C" vanishes from Active with nothing on screen
# to explain it. `archived` has had the same exposure since long before this.
#
# Preserved here rather than at each call site: the generate path already remembered to merge
# (main.py), the autosave path did not, and the next writer would have had to remember too.
#
# `scope_group` joined on 2026-10-24 (RJ's projects with no single base bid, see the scope-group
# block further down): it is the link that makes Breakroom, Lab 1 and Lab 2 one project with three
# proposals. It is written only by create_sibling, rename_scope and split_draft, and a stale tab
# that silently cleared it would detach a scope from the customer's combined email.
#
# `proposal_of`, `estimate_digest` and `estimate_synced_at` joined on 2026-10-27 ("Create Multiple
# Proposals", the proposals block further down): a proposal made from another draft's base bid says
# whose estimate it is a copy of, and which copy. Written only by fan_out_proposals and
# refresh_proposals; a stale tab that cleared them would cut the proposal off its estimate, and one
# that put an old digest back would hide an "Estimate changed" the estimator needs to see.
#
# `proposals_base_tab_id` joined on 2026-10-28 (PROPOSALS_BASE): the parent's base the proposals were
# last matched against, so the proposal a base swap leaves on Base Bid 1's sheet can take the sheet
# the parent gave up. Written only by fan_out_proposals and refresh_proposals; a stale tab that put
# an old one back would send that proposal to the wrong sheet.
#
# `starred` and `copied_from` joined on 2026-10-29 (Hanz: "the ability to Star a project and it always
# gets put up to the top of the pipeline", and "we should be able to copy a project"). The star is the
# whole team's, toggled from the board (set_starred), so a tab left open on the project from before
# somebody starred it must not take the star off with its next autosave. `copied_from` is written once,
# by copy_project, and is what keeps a copy with no files yet on the board's "Created but not sent"
# column (main._not_sent_rows); a browser save that dropped it would take the copy off the board.
_SERVER_OWNED_KEYS = ("is_test", "archived", "assigned_estimator", "scope_group",
                      "proposal_of", "estimate_digest", "estimate_synced_at", "proposals_base_tab_id",
                      "starred", "copied_from")

# Stamped on a draft the moment split_draft rewrites it, and carried by every copy of the draft that
# was read AFTER the split. A browser save whose blob does not carry the stamp the row has was built
# from the copy BEFORE the split, and storing it would put the three sheets back on the parent while
# the children also hold them (save_draft refuses it, StaleSplitWrite).
SPLIT_MARK = "split_at"

# Stamped on Base Bid 1's estimate each time rename_proposal renames one of its sheets from a
# proposal's tab (a server write that does not bump `updated_at`), and carried by every copy of the
# estimate read AFTER it. A browser save whose blob does not carry the stamp the row has was built
# from a copy read BEFORE the rename: storing it would put the old sheet name back, and the save's
# own sync (sync_proposal_labels) would then rename every proposal back after it. save_draft refuses
# it (StaleSheetNamesWrite), as it refuses a copy from before a split. Not server-owned, like
# SPLIT_MARK: TW.refreshServerOwned must never hand an old copy the new stamp.
SHEET_NAMES_MARK = "sheet_names_at"

# Server-owned keys a BROWSER'S save may not even seed on a row that has never had them (the rest of
# _SERVER_OWNED_KEYS may: "the blob may still seed a key the row has never had", save_draft). A scope
# group is joined only through create_sibling and split_draft. The beta's sandbox PUTs a copy of a real
# bid under a NEW id (polish-sandbox.js), and a copy that carried the real bid's group would join the
# customer's project: drawn beside its scopes, and holding the combined email back until the test copy
# was published too (the portal's scopes_not_published). The proposal keys likewise: a copy that
# carried `proposal_of` would be drawn as one more proposal tab of the real bid. A sandbox copy of a
# starred or copied bid likewise must not arrive starred, or on the board as a copy nobody made.
_NEVER_SEEDED_BY_A_BROWSER = ("scope_group", "proposal_of", "estimate_digest", "estimate_synced_at",
                              "proposals_base_tab_id", "starred", "copied_from")


class StaleSplitWrite(Exception):
    """A browser save of a copy of the draft read before split_draft rewrote it."""


class StaleProposalWrite(Exception):
    """A browser save of a copy of a proposal child read before refresh_proposals re-priced it.

    The child's estimate keys are browser-written, so a stale page's PUT would put the old price
    back, while `estimate_digest` (server-owned) kept the new one and hid the "Estimate changed"
    banner. `estimate_synced_at` is the fence, as SPLIT_MARK is for a split: a blob that does not
    carry the stamp the row has was read before the last refresh."""


class StaleSheetNamesWrite(Exception):
    """A browser save of a copy of an estimate read before rename_proposal renamed one of its sheets
    (SHEET_NAMES_MARK)."""


def save_draft(draft_id: str, data: Dict[str, Any],
               owner_email: Optional[str] = None,
               keep_server_owned: bool = False) -> Dict[str, str]:
    """Upsert a project. On first save, stamps owner_email + logs a `created`
    event. On update, preserves owner_email/created_at and the server-owned keys
    listed in `_SERVER_OWNED_KEYS`. Returns {id, updated_at}.

    `keep_server_owned` is the browser's save (PUT /api/draft/{id}): there the STORED value of a
    server-owned key wins even when the blob carries one. A browser's blob always does — a hydrate
    writes the server's copy into it — so it carries whatever this browser last saw: a tab that
    read the project before Troy reassigned it from the CRM put Kyle's name back on it with its
    next save, and filed a project Troy had marked as a test back as real (review of fix 4, round
    2). The blob may still seed a key the row has never had."""
    sb = get_client()
    now = _now_iso()
    existing = sb.table("drafts").select("id,data").eq("id", draft_id).limit(1).execute()

    if existing.data:
        # Carry forward what the server owns, unless this caller is deliberately setting it.
        # `is_test` is a tri-state, so `False` is a real value and `in` is the right test — a
        # `.get()` truthiness check would treat "somebody said this IS a real bid" as unset.
        prior = existing.data[0].get("data") or {}
        # A COPY FROM BEFORE A SPLIT IS NEVER STORED OVER ONE (see SPLIT_MARK). Only the browser's
        # own save is asked (keep_server_owned): the server's writers read the row they write.
        # Checked BEFORE the server-owned merge, which would otherwise hand the old copy the
        # current stamp and wave it through.
        if keep_server_owned and prior.get(SPLIT_MARK) and data.get(SPLIT_MARK) != prior.get(SPLIT_MARK):
            raise StaleSplitWrite(draft_id)
        if (keep_server_owned and prior.get(SHEET_NAMES_MARK)
                and data.get(SHEET_NAMES_MARK) != prior.get(SHEET_NAMES_MARK)):
            raise StaleSheetNamesWrite(draft_id)
        if (keep_server_owned and prior.get("estimate_synced_at")
                and data.get("estimate_synced_at") != prior.get("estimate_synced_at")):
            raise StaleProposalWrite(draft_id)
        data = dict(data)
        for key in _SERVER_OWNED_KEYS:
            if key in prior and (keep_server_owned or key not in data):
                data[key] = prior[key]
            elif keep_server_owned and key in _NEVER_SEEDED_BY_A_BROWSER:
                data.pop(key, None)
        sb.table("drafts").update({"data": data, "updated_at": now}).eq("id", draft_id).execute()
        # ONE NAME (Hanz, 2026-10-29): an estimate with proposals names each of them after its base
        # sheet, so a sheet renamed on the estimate renames its proposal here, on the save that
        # carried the new name (sync_proposal_labels). A save that changed ONLY sheet names takes the
        # names into every proposal that was up to date, which stays up to date (carry_sheet_names).
        # A failure never fails the save: the next save names them again (a proposal whose names
        # were not carried shows "Estimate changed", and Refresh copies them).
        if _may_have_proposals(data):
            try:
                carry_sheet_names(draft_id, prior, data)
            except Exception as exc:  # noqa: BLE001 — the estimate itself is saved
                _log.warning("save of %s: the sheet names were not carried into its proposals: %s",
                             _log_safe(draft_id), _log_safe(exc))
            try:
                sync_proposal_labels(draft_id, owner_email, parent=data)
            except Exception as exc:  # noqa: BLE001 — the estimate itself is saved
                _log.warning("save of %s: the proposals were not renamed after their sheets: %s",
                             _log_safe(draft_id), _log_safe(exc))
    else:
        if keep_server_owned:
            data = {k: v for k, v in data.items() if k not in _NEVER_SEEDED_BY_A_BROWSER}
        sb.table("drafts").insert({
            "id": draft_id, "data": data, "owner_email": owner_email,
            "created_at": now, "updated_at": now,
        }).execute()
        log_event(draft_id, owner_email, "created", _summary_detail(data))
    _cache_clear()
    return {"id": draft_id, "updated_at": now}


def load_draft(draft_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a project by id. Returns {id, data, created_at, updated_at} or None."""
    sb = get_client()
    res = sb.table("drafts").select("id,data,owner_email,created_at,updated_at") \
        .eq("id", draft_id).limit(1).execute()
    if not res.data:
        return None
    row = res.data[0]
    return {
        "id": row["id"],
        "data": row.get("data") or {},
        "owner_email": row.get("owner_email"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def draft_is_active(draft_id: str) -> bool:
    """True when the id resolves to a project that is NOT in the Trash.

    load_draft() deliberately still returns trashed rows — Trash has to read
    them to restore them. Callers asking "did this already become a usable
    project?" need the narrower question, or a trashed draft answers yes
    forever."""
    sb = get_client()
    res = (sb.table("drafts").select("id")
           .eq("id", draft_id).is_("deleted_at", "null").limit(1).execute())
    return bool(res.data)


def delete_draft(draft_id: str) -> bool:
    """Permanently remove a project (hard delete — 'Delete forever' from Trash).
    For normal deletes use trash_draft() so it lands in Trash first. Returns
    True if the project existed."""
    sb = get_client()
    res = sb.table("drafts").delete().eq("id", draft_id).execute()
    _cache_clear()
    return bool(res.data)


def trash_draft(draft_id: str, actor_email: Optional[str] = None) -> bool:
    """Soft-delete: stamp deleted_at so the project moves to Trash — hidden from
    the active list but restorable. Logs a `trashed` event. Returns True if the
    project existed."""
    sb = get_client()
    res = sb.table("drafts").update({"deleted_at": _now_iso()}).eq("id", draft_id).execute()
    rows = res.data or []
    if rows:
        name = (rows[0].get("data") or {}).get("project_name")
        log_event(draft_id, actor_email, "trashed", {"project_name": name, "id": draft_id})
    _cache_clear()
    return bool(rows)


def restore_draft(draft_id: str, actor_email: Optional[str] = None) -> bool:
    """Undo a soft-delete: clear deleted_at so the project returns to the active
    list. Logs a `restored` event. Returns True if the project existed."""
    sb = get_client()
    res = sb.table("drafts").update({"deleted_at": None}).eq("id", draft_id).execute()
    rows = res.data or []
    if rows:
        name = (rows[0].get("data") or {}).get("project_name")
        log_event(draft_id, actor_email, "restored", {"project_name": name, "id": draft_id})
    _cache_clear()
    return bool(rows)


def set_archived(draft_id: str, archived: bool,
                 actor_email: Optional[str] = None) -> bool:
    """Mark a project active/inactive (Kyle's "active/inactive" Projects filter).

    The flag lives INSIDE the `data` blob (`data.archived`) rather than a new
    column — that's backend-agnostic (works the same on cloud Supabase in prod
    and the VPS PostgREST in staging) and needs no schema migration. We
    read-modify-write the blob and deliberately DON'T bump `updated_at`, so
    archiving a finished project doesn't shuffle it to the top of the list.
    Returns True if the project existed."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
    data["archived"] = bool(archived)
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    log_event(draft_id, actor_email, "archived" if archived else "unarchived",
              {"project_name": data.get("project_name"), "id": draft_id})
    _cache_clear()
    return True


def set_test_flag(draft_id: str, is_test: bool,
                  actor_email: Optional[str] = None) -> bool:
    """Mark a project as test/demo, or as a real customer bid.

    Same posture as `set_archived`: inside the `data` blob, no migration, no `updated_at`
    bump (filing a project as test isn't work on the estimate).

    Why this exists at all: the Projects page already keeps test projects out of
    Active/Inactive/All, but it classified them by NAME — so "Testing", "test1" and
    "(untitled)" all read as real customer bids and cluttered Kyle's working list, while a
    genuine bid could in principle be misfiled by the same regex. The flag is the estimator's
    own decision and it survives a rename.

    Stored as a real bool BOTH ways on purpose. `False` is not the same as absent: absent
    means "nobody has said", so the name heuristic still gets a vote, while `False` means
    "somebody looked at this and said it's a real bid" and must beat the heuristic. That's
    what lets a genuinely-named project like "Test Treadwell" be pulled back into Active.

    A SCOPE OF A PROJECT IS NEVER FILED APART FROM ITS PROJECT (finding 7). A change that would put a
    Test scope beside real ones, or a real scope beside Test ones, in one scope group RAISES
    ScopeError test_mix (409) and writes nothing: the portal would quietly drop the odd one out of
    the project's email and its follow-ups, and the board would draw a project nobody can email.

    Returns True if the project existed."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
    mixed = _test_flag_mix(draft_id, data, bool(is_test))
    if mixed:
        raise ScopeError("test_mix", mixed, 409)
    data["is_test"] = bool(is_test)
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    log_event(draft_id, actor_email, "marked_test" if is_test else "marked_real",
              {"project_name": data.get("project_name"), "id": draft_id})
    _cache_clear()
    return True


def set_assigned_estimator(draft_id: str, email: str,
                           actor_email: Optional[str] = None) -> bool:
    """Name the estimator who owns this project's follow-up.

    Same posture as `set_archived` above: inside the `data` blob, no migration, and
    NO `updated_at` bump — handing a project to a colleague isn't work on the
    estimate and must not shuffle it to the top of the Projects list.

    This is the DRAFT's copy, which is what pre-fills the Files-page picker on the
    next send. A project the customer already has also keeps a copy on its portal
    row (that's the one the CRM board and the digest read), so the caller forwards
    there too — see `api_assign_draft`. Returns True if the project existed."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
    data["assigned_estimator"] = email
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    log_event(draft_id, actor_email, "assigned",
              {"project_name": data.get("project_name"), "id": draft_id, "to": email})
    _cache_clear()
    return True


def set_notify_picks(draft_id: str, add: List[str], mute: List[str],
                     actor_email: Optional[str] = None) -> bool:
    """Who on the team should hear about this project's next send.

    Hanz, 2026-08-19: "add the notif sending in this step of the CRM" — asked of the drawer for a
    project that has been CREATED BUT NOT SENT.

    It has to live on the draft rather than in the portal's per-project override table, for the same
    reason `set_assigned_estimator` does: `portal_notify_overrides.proposal_id` is a foreign key onto
    a proposal row that an unsent project does not have. So this is the intention, recorded before
    there is anywhere to apply it, and the Files screen carries it into the send that creates the
    row. A project the customer already has keeps the authoritative copy on the portal side, and
    `api_draft_notify` forwards there too.

    Stored as DEVIATIONS from the global roster, not as a recipient list. The roster changes — people
    join, leave, get toggled — and a stored list would freeze a decision about nine specific people
    made weeks before the send. "Include Will, exclude Troy" still means what it said.

    Same posture as the assignment: inside the `data` blob, no migration, and no `updated_at` bump.
    Choosing who to notify is not work on the estimate and must not shuffle the project to the top of
    the Projects list. Returns True if the project existed."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
    if add or mute:
        data["notify_picks"] = {"add": list(add), "mute": list(mute)}
    else:
        # Nothing deviates from the roster any more, so drop the key rather than storing two empty
        # lists that read as "somebody decided nothing".
        data.pop("notify_picks", None)
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    log_event(draft_id, actor_email, "notify_picked",
              {"project_name": data.get("project_name"), "id": draft_id,
               "add": list(add), "mute": list(mute)})
    _cache_clear()
    return True


def record_generate_result(draft_id: str, result: Dict[str, Any]) -> bool:
    """Record that this project's files have been built, when nothing has recorded it yet.

    `generate_result` is what `has_files` reads (see `_build_summaries`), and `has_files` is what
    puts a project in the Active Projects board's "Created but not sent" column. The Files page
    used to record it with TW.setState, which PUTs the page's WHOLE blob — and that page can be
    holding an older copy of the draft than the server's, so the write that recorded "files exist"
    also wrote a colleague's newer revision away. /api/draft/{id}/documents records it here instead,
    on the server's own copy, touching this one key.

    Only when absent or null (a Continue that changed the cover letter nulls it on purpose, and a
    build after that is a build). Never overwritten once present: only its existence is read.
    Same posture as `set_won`: no `updated_at` bump, because building files is not an edit.
    Returns True when it wrote."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
    if data.get("generate_result"):
        return False
    data["generate_result"] = result
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    _cache_clear()
    return True


def get_notify_picks(draft_id: str) -> Dict[str, Any]:
    """The stored deviations plus the project's owner: {"add": [...], "mute": [...], "owner_email"}.

    Read-only companion to set_notify_picks, serving two callers that both need one query:

      * AUTHORISATION — `_guard_notify_picks` compares what a caller submitted against what is
        already stored, so a non-admin can be held to changing only their own address.
      * THE RECONCILE LOOP in `api_draft_notify`, which clears overrides that no longer deviate and
        must SPARE the owner. The portal deliberately keeps the creator's override (Will, via Hanz,
        2026-08-13: the estimator who built the estimate should hear back about it), so a loop that
        cleared everything outside the submitted set would strip an override the portal set on
        purpose.

    A missing project reads as empty with no owner, which is the safe direction on both counts: every
    submitted address then counts as a change and has to clear the same check, and nothing is
    spared from clearing on a project that does not exist."""
    sb = get_client()
    cur = sb.table("drafts").select("data,owner_email").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return {"add": [], "mute": [], "owner_email": ""}
    row = cur.data[0]
    picks = (row.get("data") or {}).get("notify_picks") or {}
    out: Dict[str, Any] = {"owner_email": (row.get("owner_email") or "").strip()}
    for key in ("add", "mute"):
        raw = picks.get(key)
        out[key] = [str(e) for e in raw] if isinstance(raw, list) else []
    return out


def set_close_lost(draft_id: str, reason: Optional[str],
                   actor_email: Optional[str] = None, note: Optional[str] = None) -> bool:
    """Close an unsent project as lost, or reopen it. `reason` None reopens.

    Hanz, 2026-08-19: "Allow to mark a proposal as lost tho in the Created not sent category."

    Kyle needs it for the commonest dead bid there is: priced, paperwork generated, and then the GC
    went with somebody else before we ever sent it. Until now the only way to close a bid lost was
    the portal's `/status` route, and an unsent project has no `portal_proposals` row to close —
    the same wall `set_assigned_estimator` and `set_notify_picks` hit. So the answer is the same:
    the draft records it, and the board reads it back through the synthesised row.

    NOT archiving, which already exists and means something else. Archiving hides a project from
    the Projects list; this one keeps it, moves it to the Lost tab, and files it under a reason so
    it counts in the numbers Troy reads. A lost bid is data, not clutter.

    `updated_at` is deliberately NOT bumped, as with the other two: closing a bid is not work on the
    estimate, and shuffling it to the top of the Projects list on its way out would be backwards.

    THE `note` IS THE COMMENT, and it is required by the route rather than here. Hanz asked for it
    on 2026-08-20 and it is the tool's first required free-text field — every other note in this
    module is optional on purpose. It lives on the same blob key rather than a column of its own
    for the reason this whole family of writers exists: an unsent project has no portal row, and
    the SENT half stores its own copy in jsonb too (portal_followups.detail), so neither half
    needs DDL. Stored and logged on the event, and deliberately NOT put on the board's row: a card
    is 224px wide and this is a paragraph.

    REOPENING CLEARS THE HOLD AS WELL. "Active" is one word meaning one thing to the estimator
    pressing it: this bid is live again. A hold that survived reactivation would leave the card
    showing "Paused to ..." with no control left to clear it, because the drawer offers exactly one
    way back. See set_on_hold for why the two states are separate keys in the first place.

    Returns True if the project existed."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
    if reason:
        data["closed_lost"] = {"reason": str(reason), "by": actor_email or "",
                               "at": _now_iso(), "note": str(note or "")}
    else:
        data.pop("closed_lost", None)
        data.pop("on_hold", None)
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    log_event(draft_id, actor_email, "closed_lost" if reason else "reactivated",
              {"project_name": data.get("project_name"), "id": draft_id,
               "reason": str(reason) if reason else None,
               "note": str(note or "") if reason else None})
    _cache_clear()
    return True


def set_on_hold(draft_id: str, reason: str, note: str,
                actor_email: Optional[str] = None, until: str = "") -> bool:
    """Pause an unsent bid without killing it.

    Hanz, 2026-08-20: two of the eight answers on Kyle's close-out list — "Project on Hold" and
    "Small Bid <$25k - Pending" — are NOT losses. The card stays on the Active board and the
    reminder emails pause. A sent project gets that from the portal's own `delayed` status, which
    is where the route sends it; this function is the unsent half, where there is no portal row to
    pause and nothing chasing the bid in the first place.

    So what is it stored FOR? The board. `until` becomes the synthesised row's
    followup_state.paused_until (see _not_sent_rows in main.py), which is the field the existing
    "Paused to ..." chip already reads. One chip for both halves, rather than an on-hold vocabulary
    that only unsent cards can speak.

    A SEPARATE KEY from `closed_lost`, not a value inside it, for the same reason `won` is
    separate: these are different facts with different lifetimes, and one key holding a tri-state
    would turn "is this bid dead" into a string comparison in five readers instead of a presence
    test in one. Neither writer touches the other's key. A bid held and then genuinely lost carries
    both, and isLost wins everywhere, which is right — it is lost.

    `updated_at` is deliberately NOT bumped, as with the other blob writers here.

    Returns True if the project existed."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
    data["on_hold"] = {"reason": str(reason), "note": str(note or ""),
                       "by": actor_email or "", "at": _now_iso(), "until": str(until or "")}
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    log_event(draft_id, actor_email, "on_hold",
              {"project_name": data.get("project_name"), "id": draft_id,
               "reason": str(reason), "note": str(note or ""), "until": str(until or "")})
    _cache_clear()
    return True


def clear_outcome(draft_id: str, actor_email: Optional[str] = None) -> bool:
    """Bring a won or lost job back to the pipeline, in one write.

    Hanz, 2026-08-20: "if projects are both won and lost there should be an option to bring it back
    to its latest step in the CRM but before they do that there should be a prompt saying are they
    sure". The prompt is the drawer's; this is the write.

    THE COMBINED CLEAR EARNS ITS EXCEPTION. set_won's docstring argues that popping the other key
    would be a second rule agreeing with the first only by accident, and that still stands for the
    two NARROW undos, which each say what they undid. But a job marked won and THEN closed lost
    reads as Lost only (every reader asks isLost first), so clearing one mark leaves the card on the
    other tab and the button the estimator just pressed looks broken. "Bring it back" is one act,
    so it is one write and one event.

    NOTHING IS REMEMBERED ABOUT WHERE THE CARD CAME FROM, and that is the design rather than a
    shortcut. Closing a job lost never overwrote a pipeline timestamp, and stage() derives the
    column from those, so a card that stops being lost recomputes its own way back to the furthest
    step it genuinely reached. A "previous stage" field would be a second source of truth for a
    question the timestamps already answer, and it would be wrong the first time a deposit landed
    while the job was closed.

    IDEMPOTENT. Clearing keys that are not there is a no-op, which is what makes the route's second
    leg — forwarding "active" to the portal for a project that HAS been sent — safe to retry after
    a failure, rather than leaving the estimator with a half-reopened job and no way to finish.

    Returns True if the project existed."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
    # "handed_off" joined the list on 2026-08-28. A job that was handed to operations and then
    # closed lost has two marks on it, and Bring it back has to mean the same thing here as it does
    # for the other three: one press, one write, the card back on the live board. Leaving the
    # hand-off behind would put it straight back on the Handed Off tab, where the estimator who
    # just pressed Bring it back would not look for it.
    for key in ("closed_lost", "on_hold", "won", "handed_off"):
        data.pop(key, None)
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    log_event(draft_id, actor_email, "brought_back",
              {"project_name": data.get("project_name"), "id": draft_id})
    _cache_clear()
    return True


def set_won(draft_id: str, won: bool, actor_email: Optional[str] = None) -> bool:
    """Mark a project won by hand, or clear that mark. `won` False clears it.

    Hanz, 2026-08-19: "Is there any way to also mark as won for now other than after the deposit
    has been received".

    Won was DERIVED ONLY — approved AND the money question settled (`isWon` in crm-core.js). That is
    the honest definition of a FINISHED job and useless for the commonest way we learn we won one: a
    verbal yes on the phone, days before the customer clicks Approve and weeks before the deposit
    lands. Lost became markable by hand this morning (`set_close_lost` above); the asymmetry was the
    bug, because between the phone call and the deposit the board called a won job "Active".

    Stored on the draft blob beside `closed_lost`, for the same two reasons: an unsent project has
    no `portal_proposals` row to write to, and `proposal_status` is CHECK-constrained, so a "won"
    status value there would mean DDL on a column the portal owns.

    NOT made mutually exclusive with `closed_lost` here, deliberately. Lost-beats-Won has to live in
    the predicates regardless — a SENT project's closed_lost is the PORTAL's, which this function
    cannot see or clear — so popping the other key would be a second rule that can only ever agree
    with the first by accident, and it would destroy a reason somebody recorded. Neither writer
    touches the other's key; the board, the chip and the Won tab still show exactly one outcome,
    because every reader asks isLost first.

    `updated_at` is deliberately NOT bumped, as with the other three blob writers here: recording an
    outcome is not work on the estimate, and shuffling the project to the top of a list sorted by
    date-updated on its way OUT would be backwards.

    Returns True if the project existed."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
    if won:
        data["won"] = {"at": _now_iso(), "by": actor_email or ""}
    else:
        # Drop the key rather than storing `{"at": null}`: every reader tests the stamp's presence,
        # and an object with nothing in it reads as "somebody decided" when nobody did.
        data.pop("won", None)
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    log_event(draft_id, actor_email, "won" if won else "not_won",
              {"project_name": data.get("project_name"), "id": draft_id})
    _cache_clear()
    return True


def set_handed_off(draft_id: str, handed_off: bool, actor_email: Optional[str] = None) -> bool:
    """Hand a won project to operations, or undo that. `handed_off` False clears it.

    Hanz, 2026-08-28: "Once we receive the Contact Info, we indicate it as handed off... We need to
    add a button on the Project container in the Active project named as 'Hand it off'."

    THIS IS THE FIELD THAT REPLACED A DERIVED TAB. Between 2026-08-20 and today, winning a job took
    its card off the Active board by itself: isWon was the routing question, so the moment the
    numbers said won, the work still owed on the job (the deposit, the contacts) left the board the
    sales meeting is run from. Handing off is a HUMAN ACT with no timestamp anywhere else in either
    database to derive it from, which is precisely why it earns a stored field where "won" could
    have been computed.

    Stored on the draft blob beside `won` and `closed_lost`, for the same two reasons: an unsent
    project has no `portal_proposals` row to write to, and `proposal_status` is CHECK-constrained,
    so a "handed_off" status value there would mean DDL on a column the portal owns. Following that
    precedent exactly is the point — a third storage shape for a fourth outcome is how the word
    "lost" came to mean two things on two screens before crm-core existed.

    NOT GATED ON `won` HERE, deliberately, and the gate is in the UI instead. Hand it off is only
    rendered on a card isWon already accepts, so the button cannot be reached otherwise; putting a
    second copy of that rule in here would give the two a way to disagree, and it would reject a
    legitimate correction (a job handed off, then un-marked won, then re-marked) for no gain. What
    the API must not do is invent state, and it does not: it records who pressed the button.

    `updated_at` is deliberately NOT bumped, as with the other blob writers here: recording an
    outcome is not work on the estimate, and shuffling the project to the top of a list sorted by
    date-updated on its way OUT would be backwards.

    Returns True if the project existed."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
    if handed_off:
        data["handed_off"] = {"at": _now_iso(), "by": actor_email or ""}
    else:
        # Drop the key rather than storing `{"at": null}`: every reader tests the stamp's presence,
        # and an object with nothing in it reads as "somebody decided" when nobody did.
        data.pop("handed_off", None)
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    log_event(draft_id, actor_email, "handed_off" if handed_off else "not_handed_off",
              {"project_name": data.get("project_name"), "id": draft_id})
    _cache_clear()
    return True


STAR_TRIES = 4


class StarBusy(Exception):
    """set_starred found the project saved again between its read and its write, STAR_TRIES times."""


def set_starred(draft_id: str, starred: bool, actor_email: Optional[str] = None) -> bool:
    """Star a project, or take its star off. `starred` False clears it.

    Hanz, 2026-10-29: "We must have the ability to Star a project and it always gets put up to the
    top of the pipeline." ONE STAR PER PROJECT, the whole team's: anybody can put it on or take it
    off, and everybody sees it, because the board is the sales meeting's and a star only one person
    could see would not move anything up the board the meeting is reading.

    Stored on the draft blob beside `won` and `handed_off`, for the same reasons: an unsent project
    has no portal row, and a sent one's row belongs to the portal. Server-owned (_SERVER_OWNED_KEYS),
    so a tab that read the project before somebody starred it cannot take the star off with its
    next whole-blob save. ONE CARD, NOT ITS SIBLINGS: a project split into several proposals is one
    card per proposal, each moving through the columns on its own, so a star pins the card it was
    pressed on and no other.

    `updated_at` is NOT bumped: a star is not work on the estimate, and the board's "Last activity"
    sort must not call a project active because somebody starred it. Returns True if it existed.

    THE WRITE IS FENCED ON `updated_at` (review of the copy-and-star branch, 2026-10-30). The star is
    written as the whole blob, read a moment before; an estimator's autosave (save_draft, which does
    bump `updated_at`) landing between that read and this write would otherwise be overwritten by
    the older blob, and the edits lost. So the write applies only if the row has not been saved
    since it was read, and is re-read and tried again when it has (STAR_TRIES, then StarBusy, a 409).
    THE OTHER ORDER IS STILL OPEN: an autosave that read the row BEFORE this write and stores AFTER
    it drops the star (save_draft keeps a server-owned key only if the row it read had one), and the
    History keeps this "starred" line. That window is the length of one save request, not a stale
    tab; closing it needs a single-key jsonb update in the database (an RPC: DDL on both databases),
    which this does not add."""
    sb = get_client()
    for _try in range(STAR_TRIES):
        cur = sb.table("drafts").select("data,updated_at").eq("id", draft_id).limit(1).execute()
        if not cur.data:
            return False
        data = dict(cur.data[0].get("data") or {})
        if starred:
            data["starred"] = {"at": _now_iso(), "by": actor_email or ""}
        else:
            data.pop("starred", None)
        q = sb.table("drafts").update({"data": data}).eq("id", draft_id)
        seen = cur.data[0].get("updated_at")
        if seen:
            q = q.eq("updated_at", seen)
        if q.execute().data:
            break
    else:
        raise StarBusy(draft_id)
    log_event(draft_id, actor_email, "starred" if starred else "unstarred",
              {"project_name": data.get("project_name"), "id": draft_id})
    _cache_clear()
    return True


# ── scope groups: one project, several separately approved proposals ──
# RJ, 2026-10-24: a client gets a few separately priced scopes (Breakroom polish, Lab 1 epoxy, Lab 2
# epoxy) under one project name and address, and each is its OWN proposal the customer approves on
# its own. Each scope is an ordinary draft going through the ordinary single-proposal pipeline; what
# makes them one project is `data.scope_group = {"id": <shared>, "label": <this scope's name>}`.
#
# THE SHAPE IS THE PORTAL'S CONTRACT (treadwell-portal backend/main.py `_scope_of`): the portal's
# publish reads it straight out of this table, refuses a malformed one with invalid_scope_group, and
# decides who is in the group for the ONE combined customer email by what each draft's own blob says.
# So the id rule and the label cap below are the portal's, character for character.
#
# Written only by the three functions in this block (a new scope, a rename, a split), and owned by
# the server for the reason the block above _SERVER_OWNED_KEYS gives.
SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SCOPE_LABEL_MAX = 80
# The live estimate's own limit on copied sheets; a project split into more proposals than that is a
# typing accident, not a bid.
MAX_SCOPES = 12


class ScopeError(Exception):
    """A scope-group write refused, with the code the route answers and the sentence it says."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def scope_group_problem(raw: Any) -> Optional[str]:
    """Why `raw` (a draft's `scope_group`) is not the portal's shape, or None when it is (or absent).

    THE PORTAL'S RULE, so a malformed group is refused HERE with a sentence the estimator can act on,
    rather than surfacing as the portal's bare 400 through the publish proxy."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return "the scope group is not an object"
    gid = raw.get("id")
    if not isinstance(gid, str) or not SCOPE_ID_RE.match(gid):
        return "the scope group's id is not 1-64 letters, digits, - or _"
    label = raw.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > SCOPE_LABEL_MAX):
        return "the scope's name is not text of %d characters or fewer" % SCOPE_LABEL_MAX
    return None


def _scope_of(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """(group id, label) of a draft blob, (None, None) for an ungrouped or malformed one."""
    raw = (data or {}).get("scope_group")
    if raw is None or scope_group_problem(raw):
        return None, None
    return raw["id"], (raw.get("label") or None)


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def clean_scope_label(raw: Any) -> str:
    """A scope's name as it is stored: text, control characters dropped, spaces squeezed. RAISES
    ScopeError for an empty one or one over the portal's cap (refused rather than cut: a name cut
    at 80 is a name nobody typed)."""
    text = re.sub(r"\s+", " ", _CONTROL_CHARS.sub(" ", str(raw if raw is not None else ""))).strip()
    if not text:
        raise ScopeError("invalid_label", "Give the scope a name, like “Lab 1”.")
    if len(text) > SCOPE_LABEL_MAX:
        raise ScopeError("invalid_label",
                         "A scope's name can have %d characters at most." % SCOPE_LABEL_MAX)
    return text


# WHAT A NEW SCOPE TAKES FROM THE PROJECT IT IS A SCOPE OF: the project's identity, its place and its
# people, and NOTHING about what is being priced or proposed. An explicit allow-list rather than "the
# parent minus a deny-list", because the blob grows a new key every few weeks and a deny-list would
# copy every one nobody thought about (a cover letter, a revision's pins, a price override) onto a
# proposal that never asked for it.
#
# `is_test` IS INHERITED, not re-derived: a scope of a test project is a test, and a scope of a real
# bid is real, whatever its own name looks like. A parent that has never said (the key absent) gives
# a child that has never said, so the name heuristic reads the same name the same way for both.
SIBLING_INTAKE_KEYS = (
    "project_name", "audience", "is_test", "assigned_estimator",
    "bid_date", "deadline", "approx_start_date",
    "address", "city", "state", "zip", "city_state",
    "county", "county_tax_rate", "county_remodel_rate", "county_notes",
    "architect", "drawings_dated", "addenda_count", "spec_section", "finish_tag", "plan_sheet",
    "contact_name", "contact_email", "contact_phone", "source", "contact_notes",
)
# The JOB's conditions, as the workbook cells both intakes read back (the cell wins over the model:
# js/work-types.js CONDITIONS, polish-estimate.js adopt). Local, prevailing wage, taxable, remodel tax
# and new/renovation describe the job site, so every scope of it shares them. Dye, joint filler and
# the bulk discount describe ONE floor and are left for each scope to answer.
SIBLING_CONDITION_CELLS = (
    "Epoxy!B4", "Polish!B4", 'Gyp (USG 1-8")!B5', "Gyp (FR)!B5", "Seal!B4",
    "Epoxy!D5",
    "Epoxy!B6", "Polish!B6", "Leveling!B6", 'Gyp (USG 1-8")!B8', "Gyp (FR)!B8",
    "Epoxy!D6", "Polish!D6", 'Gyp (USG 1-8")!D8',
    "Epoxy!B10", "Polish!B10", "Seal!B10",
)
# Inside a v2 estimate (polish_estimate, version 2) the job-level keys a scope shares: the driving
# distance to the site (with the address it was measured for, so the new scope's page does not
# measure again) and the prevailing-wage rates. NOT `travel`: Lodging and Per Diem quantities belong
# to one crew, and a copy would bill the first scope's nights on every other.
SIBLING_MODEL_KEYS = ("distance", "prevailing")


def sibling_intake(parent: Dict[str, Any]) -> Dict[str, Any]:
    """The blob a new scope of `parent` starts from (see the three allow-lists above). A NEW dict;
    nothing of `parent` is shared with it."""
    parent = parent or {}
    out = {k: copy.deepcopy(parent[k]) for k in SIBLING_INTAKE_KEYS if k in parent}
    cells = parent.get("cell_values")
    if isinstance(cells, dict):
        kept = {k: cells[k] for k in SIBLING_CONDITION_CELLS if k in cells}
        if kept:
            out["cell_values"] = kept
    pe = parent.get("polish_estimate")
    if isinstance(pe, dict) and pe.get("version") == 2:
        # A v2 model that states no labor is a NEW bid to the estimate page (bid-model laborUnstated),
        # so the scope opens seeded from the library like any new estimate, at the job's distance.
        model: Dict[str, Any] = {"version": 2}
        for k in SIBLING_MODEL_KEYS:
            if k in pe:
                model[k] = copy.deepcopy(pe[k])
        out["polish_estimate"] = model
    return out


def default_scope_label(data: Dict[str, Any]) -> str:
    """A name for a project's FIRST scope when it gets a sibling and nobody named it: its base sheet's
    name on the estimate (what the Sheets strip calls it, "Breakroom"), else its work type, else
    "Scope 1". Never raises; the result is not checked for clashes (the caller does)."""
    data = data or {}
    pe = data.get("polish_estimate")
    if isinstance(pe, dict):
        tabs = pe.get("tabs") if isinstance(pe.get("tabs"), dict) else {}
        base = data.get("base_tab_id")
        names: List[Any] = []
        if isinstance(base, str) and isinstance(tabs.get(base), dict):
            names.append(tabs[base].get("label") or tabs[base].get("sheet") or base)
        if pe.get("kind") not in ("off", "option"):
            names.append(pe.get("label") or "Polish")
        names.extend((s.get("label") or s.get("sheet") or k) for k, s in tabs.items()
                     if isinstance(s, dict) and s.get("kind") == "base")
        for n in names:
            try:
                return clean_scope_label(n)
            except ScopeError:
                continue
    wt = str(data.get("work_type") or "").strip()
    return wt.capitalize() if wt else "Scope 1"


# The Projects page's name heuristic (crm-core.js nameLooksLikeTest), character for character, and the
# portal's (treadwell-portal scope_groups._TEST_WORD/_DELETE_ME/_ZZ). It decides test-ness only when
# nobody has said: a stored `is_test` true or false wins in both directions. Narrow on purpose: "demo"
# lives inside "demolition".
_TEST_NAME_WORD = re.compile(r"\b(sample|test|verify|demo|qa|bugtest)\b", re.I)
_TEST_NAME_DELETE_ME = re.compile(r"delete me", re.I)
_TEST_NAME_ZZ = re.compile(r"^\s*zz", re.I)


def draft_is_test(state: Any) -> bool:
    """Is a draft a Test project? THE PORTAL'S RULE (scope_groups.draft_is_test), exactly, so the
    tool and the portal agree about who is in a project (finding 7).

    `state` is the draft's {is_test, project_name}, read off the STORED draft (the server's own
    flag, never a request's). An explicit `is_test` wins either way; when nobody has said, a
    test-looking project name makes it a test. A bare flag (not a dict) is judged by the flag alone,
    as a draft with no name."""
    if isinstance(state, dict):
        flag, name = state.get("is_test"), state.get("project_name")
    else:
        flag, name = state, None
    said = _tribool(flag)
    if said is not None:
        return said
    name = str(name or "")
    return bool(_TEST_NAME_WORD.search(name) or _TEST_NAME_DELETE_ME.search(name)
                or _TEST_NAME_ZZ.search(name))


def live_scope_members(members: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """THE ONE "LIVE MEMBER" RULE for a scope group, oldest first (created_at, id).

    `members` are the group's NOT-DELETED drafts as {id, created_at, archived, is_test,
    project_name, ...} (a deleted draft never reaches this: every caller reads `deleted_at is
    null`). THE PORTAL'S split_members, ported exactly (finding 7): live = not archived, and of the
    group's kind. A group is a REAL project as soon as ONE active draft in it is real, and then a
    Test draft is never a member of it; a group whose active drafts are all Test is a test group, and
    a real draft is never in one. tests/scope_member_cases.json holds the cases both repos assert.
    Before 2026-10-25 the tool let the HOME (earliest scope) decide the kind and ignored the name
    check, and disagreed with the portal in four of five mixed cases."""
    kept = [m for m in members if not _truthy(m.get("archived"))]
    kept.sort(key=lambda m: (str(m.get("created_at") or ""), str(m.get("id"))))
    if not kept:
        return []
    group_is_test = all(draft_is_test(m) for m in kept)
    return [m for m in kept if draft_is_test(m) == group_is_test]


def _group_rows_all(group_id: str) -> List[Dict[str, Any]]:
    """Every NOT-DELETED draft in a scope group, archived and test ones included, as {id, label,
    created_at, archived, is_test, project_name}, oldest first. Callers want `_group_rows` (the live
    members) unless they are checking the test rule itself.

    ONE SMALL OBJECT PER DRAFT, never the blob: the projection names data->scope_group and three
    scalars only (the project name is the test rule's fallback, draft_is_test), and the group is
    found in Python (the ids are a few hundred rows, the objects a few dozen bytes each)."""
    res = (get_client().table("drafts")
           .select("id,created_at,scope_group:data->scope_group,archived:data->>archived,"
                   "is_test:data->>is_test,project_name:data->>project_name,"
                   # Whose base bid this proposal was made from (fan_out_proposals), or None.
                   "proposal_of:data->>proposal_of,"
                   # The sheet it prices, which names it (sync_proposal_labels).
                   "base_tab_id:data->>base_tab_id")
           .is_("deleted_at", "null").execute())
    out = []
    for r in res.data or []:
        blob = r.get("data") or {}
        sg = r["scope_group"] if "scope_group" in r else blob.get("scope_group")
        if isinstance(sg, dict) and not scope_group_problem(sg) and sg.get("id") == group_id:
            out.append({"id": r["id"], "label": sg.get("label") or "",
                        "proposal_of": (r["proposal_of"] if "proposal_of" in r
                                        else blob.get("proposal_of")) or None,
                        "base_tab_id": (r["base_tab_id"] if "base_tab_id" in r
                                        else blob.get("base_tab_id")) or None,
                        "created_at": r.get("created_at") or "",
                        "archived": _truthy(r["archived"] if "archived" in r else blob.get("archived")),
                        "is_test": r["is_test"] if "is_test" in r else blob.get("is_test"),
                        "project_name": (r["project_name"] if "project_name" in r
                                         else blob.get("project_name"))})
    out.sort(key=lambda m: (str(m["created_at"]), str(m["id"])))
    return out


def _group_rows(group_id: str) -> List[Dict[str, Any]]:
    """Every LIVE member of a scope group (live_scope_members), as {id, label, created_at, archived,
    is_test}, oldest first."""
    return live_scope_members(_group_rows_all(group_id))


def scope_test_mix(draft_id: str, state: Any, group_id: str) -> Optional[str]:
    """The sentence refusing to put a Test project and a real one in one scope group, or None.

    `state` is the STORED draft blob of `draft_id` (its is_test and project_name, read off its row,
    never off a request; a bare flag is judged alone, see draft_is_test). Every other not-deleted,
    not-archived draft of the group must be the same kind, both directions: a test scope must not be
    emailed beside a real customer's scopes, and a real bid must not sit in a test project where
    nobody chases it."""
    mine = draft_is_test(state)
    for m in _group_rows_all(group_id):
        if m["id"] == draft_id or m["archived"]:
            continue
        if draft_is_test(m) != mine:
            return ("This is a Test project, and other scopes of this project are real customer "
                    "proposals." if mine else
                    "This is a real customer proposal, and other scopes of this project are Test "
                    "projects.") + " A Test project and a real one cannot be one project: mark them " \
                                   "the same way on the Projects page first."
    return None


def _test_flag_mix(draft_id: str, data: Dict[str, Any], want_test: bool) -> Optional[str]:
    """The sentence refusing set_test_flag, or None: the stored draft `data` is a scope of a group,
    marking it `want_test` changes its kind (draft_is_test), and another not-archived scope of the
    group is of the other kind. A change that leaves its kind as it was (marking a test-named scope
    Test by hand) never mixes anything and is allowed."""
    gid, _label = _scope_of(data)
    if not gid or draft_is_test(data) == want_test:
        return None
    for m in _group_rows_all(gid):
        if m["id"] == draft_id or m["archived"]:
            continue
        if draft_is_test(m) != want_test:
            return ("Nothing changed: this is one proposal of a project with several, and the "
                    "others are %s. A Test project and a real one cannot be one project. To file "
                    "the whole project %s, move its other scopes to Inactive first, change each "
                    "one, then make them active again."
                    % (("real customer proposals", "as a test") if want_test
                       else ("Test projects", "as a real bid")))
    return None


def _free_label(want: str, taken: set) -> str:
    """`want`, or `want 2`, `want 3`… — the first that no scope in `taken` (lower-cased) has."""
    if want.lower() not in taken:
        return want
    for i in range(2, 100):
        suffix = " %d" % i
        cand = want[:SCOPE_LABEL_MAX - len(suffix)] + suffix
        if cand.lower() not in taken:
            return cand
    return want


def create_sibling(parent_id: str, label: Any, actor: Optional[str] = None) -> Dict[str, Any]:
    """A NEW SCOPE OF A PROJECT (tier A0): a fresh draft that shares the project's intake and its
    scope group, priced and sent through the ordinary single-proposal pipeline.

    The parent joins a group when it is not in one (a new id is minted), and is named when it has no
    name yet (default_scope_label). Neither write bumps the parent's `updated_at`: naming the project's
    scopes is not work on its estimate, and a page that checked its copy before this still holds the
    copy the document was built from. The child is inserted as its own row, owned by `actor`.

    Returns {"id", "group_id", "label", "parent_label"}. RAISES ScopeError: not_found (404),
    invalid_label (400), invalid_scope_group (400, the parent's own group is malformed), label_taken
    and too_many_scopes (409)."""
    sb = get_client()
    cur = sb.table("drafts").select("id,data").eq("id", parent_id).limit(1).execute()
    if not cur.data:
        raise ScopeError("not_found", "That project is not there any more.", 404)
    parent = dict(cur.data[0].get("data") or {})
    want = clean_scope_label(label)
    existing = parent.get("scope_group")
    if existing is not None and scope_group_problem(existing):
        raise ScopeError("invalid_scope_group",
                         "This project's scope group cannot be read (%s)." % scope_group_problem(existing))
    gid = existing["id"] if isinstance(existing, dict) else uuid.uuid4().hex
    # THE TEST RULE (scope_test_mix): the new scope inherits the parent's is_test, so the only way
    # this mixes kinds is a parent that differs from the group it is already in.
    if isinstance(existing, dict):
        mixed = scope_test_mix(parent_id, parent, gid)
        if mixed:
            raise ScopeError("test_mix", mixed, 409)
    members = [m for m in (_group_rows(gid) if existing else []) if m["id"] != parent_id]
    if len(members) + 2 > MAX_SCOPES:
        raise ScopeError("too_many_scopes",
                         "A project can be split into %d proposals at most." % MAX_SCOPES, 409)
    taken = {m["label"].lower() for m in members if m["label"]}
    parent_label = (existing or {}).get("label") or _free_label(default_scope_label(parent),
                                                                 taken | {want.lower()})
    taken.add(parent_label.lower())
    if want.lower() in taken:
        raise ScopeError("label_taken",
                         "“%s” is already the name of a scope of this project." % want, 409)

    child_id = str(uuid.uuid4())
    child = sibling_intake(parent)
    child["scope_group"] = {"id": gid, "label": want}
    now = _now_iso()
    sb.table("drafts").insert({"id": child_id, "data": child, "owner_email": actor,
                               "created_at": now, "updated_at": now}).execute()
    log_event(child_id, actor, "created", _summary_detail(child))
    log_event(child_id, actor, "scope_added", {"project_name": child.get("project_name"),
                                               "id": child_id, "group": gid, "label": want,
                                               "from": parent_id})
    if not isinstance(existing, dict) or existing.get("label") != parent_label:
        parent["scope_group"] = {"id": gid, "label": parent_label}
        sb.table("drafts").update({"data": parent}).eq("id", parent_id).execute()
        log_event(parent_id, actor, "scope_grouped", {"project_name": parent.get("project_name"),
                                                      "id": parent_id, "group": gid,
                                                      "label": parent_label})
    _cache_clear()
    return {"id": child_id, "group_id": gid, "label": want, "parent_label": parent_label}


def rename_scope(draft_id: str, label: Any, actor: Optional[str] = None) -> Dict[str, Any]:
    """Rename one scope of a project. Same posture as create_sibling: the group is the server's, and
    `updated_at` is not bumped. Returns {"group_id", "label"}. RAISES ScopeError: not_found (404),
    not_grouped and invalid_label (400), label_taken (409)."""
    sb = get_client()
    cur = sb.table("drafts").select("id,data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        raise ScopeError("not_found", "That project is not there any more.", 404)
    data = dict(cur.data[0].get("data") or {})
    gid, old = _scope_of(data)
    if not gid:
        raise ScopeError("not_grouped", "This project is not split into scopes, so it has no "
                                        "scope name to change.")
    want = clean_scope_label(label)
    taken = {m["label"].lower() for m in _group_rows(gid) if m["id"] != draft_id and m["label"]}
    if want.lower() in taken:
        raise ScopeError("label_taken",
                         "“%s” is already the name of a scope of this project." % want, 409)
    if want != old:
        data["scope_group"] = {"id": gid, "label": want}
        sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
        log_event(draft_id, actor, "scope_renamed", {"project_name": data.get("project_name"),
                                                     "id": draft_id, "group": gid,
                                                     "from": old, "to": want})
        _cache_clear()
    return {"group_id": gid, "label": want}


# WHAT A SPLIT TAKES OFF THE PARENT when it rewrites it as its first scope (tier A1). Every key here
# describes the bid AS SEVERAL SHEETS WITH ONE BASE: the lump sum and its taxes, the priced tabs the
# proposal lists, the per-sheet proposal settings and notes, the lines and words typed over the
# proposal's figures, the document payload built from all of it, and the record of the files built
# from that payload. Left behind, the parent's proposal would print the old base's lump sum beside
# the old options while its estimate priced one sheet.
#
# `generate_result` GOES TOO, and it is the one with a trap: `has_files` reads it, and the board's
# "Created but not sent" column is has_files. Here that is right rather than a bug: the files it
# records were built for the combined bid and are no longer this proposal's, and the Files page
# would rebuild them from a payload that is gone. The board keeps the scope visible anyway, as "files
# not built yet" (main.py _not_sent_rows' `files_pending`).
#
# THE COMBINED BID'S DROPBOX RECORD AND ITS NARRATIVE GO TOO (2026-10-24 review, finding 39).
# `dropbox_result` described the combined estimate and proposal filed under the project's old,
# unscoped names: left on the parent it showed the Dropbox step as already filed (green) for files
# that are no longer this proposal's. The narrative (scope notes, schedule, exclusions, the system
# name and texture) was written for the WHOLE job, naming Lab 1 and Lab 2, and would have printed on
# a Breakroom-only proposal; cleared, the proposal step drafts this scope's own defaults again.
#
# SPLIT_HAD_FILES keeps the board honest about the one thing clearing `generate_result` loses: the
# project WAS in "Created but not sent" (finding 26). main._scope_pending reads it so the split
# project stays on the board, each scope as "files not built yet", instead of vanishing.
SPLIT_CLEARS = (
    "rooms", "base_tab_id", "priced_tabs", "computed_bid",
    "proposal_lump_sum", "proposal_sales_tax", "proposal_remodel_tax", "proposal_taxable",
    "proposal_remodel_on", "polish_sf", "polish_2_sf", "lump_sum_display", "sheet_area",
    "cost_snapshot", "cove_height_v2", "phase_price",
    "tab_opts", "tab_notes", "tab_labels", "tab_copies", "tab_order",
    "price_lines", "price_overrides", "paragraph_overrides", "box_overrides", "system_overrides",
    "proposal_payload", "generate_result", "generated_lump_sum",
    "dropbox_result", "scope_notes", "schedule_notes", "exclusions", "system_name",
    "system_name_manual", "texture",
)
SPLIT_HAD_FILES = "split_had_files"
# What the estimate page sends for each scope of a split: the one-sheet model (bid-model splitOut)
# and the save the page's own buildSavePatch composes from it (the work type and base the template
# and the Dropbox name follow, the priced snapshot the card's money reads). Nothing else from the
# request reaches a draft.
SPLIT_CHILD_KEYS = (
    "polish_estimate", "work_type", "base_tab_id", "cell_values", "computed_bid", "priced_tabs",
    "proposal_lump_sum", "proposal_sales_tax", "proposal_remodel_tax", "proposal_taxable",
    "proposal_remodel_on", "polish_sf", "polish_2_sf", "cove_height_v2", "sheet_area",
    "cost_snapshot", "phase_price", "tab_opts",
)


def _split_fields(data: Any) -> Dict[str, Any]:
    src = data if isinstance(data, dict) else {}
    return {k: copy.deepcopy(src[k]) for k in SPLIT_CHILD_KEYS if k in src}


def _undo_split_children(sb: Any, ids: List[str]) -> None:
    """Take back the children a failed split minted: delete each, or, when the delete itself fails,
    strip its scope group so it can never join the project, hold a scope's name or be expected by the
    combined email. Never raises (the caller is already reporting a failure)."""
    for cid in ids:
        try:
            sb.table("drafts").delete().eq("id", cid).execute()
            continue
        except Exception:  # noqa: BLE001 — fall back to detaching it
            pass
        try:
            cur = sb.table("drafts").select("id,data").eq("id", cid).limit(1).execute()
            blob = dict((cur.data or [{}])[0].get("data") or {})
            blob.pop("scope_group", None)
            blob["split_failed"] = True
            blob["archived"] = True
            sb.table("drafts").update({"data": blob}).eq("id", cid).execute()
        except Exception:  # noqa: BLE001 — nothing more can be done from here
            pass
    _cache_clear()


def _split_landed(sb: Any, parent_id: str, stamp: str) -> Optional[bool]:
    """Did the parent's split update commit? True when the stored parent carries THIS split's mark,
    False when it does not, None when the parent cannot be read back (the caller must not guess)."""
    try:
        cur = sb.table("drafts").select("id,data").eq("id", parent_id).limit(1).execute()
    except Exception:  # noqa: BLE001 — unknown, said as such
        return None
    if not cur.data:
        return False
    return (cur.data[0].get("data") or {}).get(SPLIT_MARK) == stamp


def split_draft(parent_id: str, children: List[Dict[str, Any]],
                actor: Optional[str] = None) -> Dict[str, Any]:
    """SPLIT ONE ESTIMATE INTO SEPARATE PROPOSALS (tier A1): `children[0]` becomes the parent itself,
    every other child a new draft in the parent's scope group (minted when it has none).

    `children` is [{"label", "data"}] in the order the page lists them; `data` is filtered through
    SPLIT_CHILD_KEYS. The parent loses SPLIT_CLEARS and is stamped SPLIT_MARK, which is what refuses a
    stale copy of it afterwards (save_draft); its `updated_at` IS bumped, because this is an edit of
    the estimate and every page that checked the old copy must be told so (_stored_since).

    The children are written FIRST: a failure part way leaves the parent exactly as it was, never a
    parent that lost a sheet no child holds, and the children already minted are taken back
    (_undo_split_children), so a retry finds the project as it was.

    Returns {"group_id", "parent": {"id", "label", "data", "updated_at"}, "children": [{"id",
    "label"}]}. RAISES ScopeError (not_found, invalid_label, label_taken, too_many_scopes,
    invalid_scope_group, split_failed, split_unconfirmed). An error from the parent's update is
    checked against the stored parent first (_split_landed): a write that committed is a split that
    happened, never one whose children are taken back."""
    sb = get_client()
    cur = sb.table("drafts").select("id,data").eq("id", parent_id).limit(1).execute()
    if not cur.data:
        raise ScopeError("not_found", "That project is not there any more.", 404)
    parent = dict(cur.data[0].get("data") or {})
    existing = parent.get("scope_group")
    if existing is not None and scope_group_problem(existing):
        raise ScopeError("invalid_scope_group",
                         "This project's scope group cannot be read (%s)." % scope_group_problem(existing))
    gid = existing["id"] if isinstance(existing, dict) else uuid.uuid4().hex
    others = [m for m in (_group_rows(gid) if existing else []) if m["id"] != parent_id]
    if len(others) + len(children) > MAX_SCOPES:
        raise ScopeError("too_many_scopes",
                         "A project can be split into %d proposals at most." % MAX_SCOPES, 409)
    labels = [clean_scope_label(c.get("label")) for c in children]
    taken = {m["label"].lower() for m in others if m["label"]}
    seen: set = set()
    for lab in labels:
        if lab.lower() in taken or lab.lower() in seen:
            raise ScopeError("label_taken",
                             "“%s” names two scopes of this project. Give each sheet its "
                             "own name first." % lab, 409)
        seen.add(lab.lower())

    stamp = _now_iso()
    intake = sibling_intake(parent)
    made: List[Dict[str, Any]] = []
    # THE CHILD WHOSE INSERT IS IN FLIGHT (finding 24). Like the parent's update below, an insert
    # can COMMIT and lose its answer (a read timeout, a 5xx after the write), so the id is on the
    # cleanup list BEFORE the insert is sent: deleting an id that was never written is harmless,
    # and a committed child left behind would join the project and hold a name a retry needs.
    in_flight: List[str] = []
    rewritten = {k: v for k, v in parent.items() if k not in SPLIT_CLEARS}
    rewritten.update(_split_fields(children[0].get("data")))
    rewritten["scope_group"] = {"id": gid, "label": labels[0]}
    rewritten[SPLIT_MARK] = stamp
    if parent.get("generate_result") or parent.get(SPLIT_HAD_FILES):
        rewritten[SPLIT_HAD_FILES] = True
    try:
        for c, lab in zip(children[1:], labels[1:]):
            cid = str(uuid.uuid4())
            d = copy.deepcopy(intake)
            d.update(_split_fields(c.get("data")))
            d["scope_group"] = {"id": gid, "label": lab}
            d["split_from"] = parent_id
            in_flight[:] = [cid]
            sb.table("drafts").insert({"id": cid, "data": d, "owner_email": actor,
                                       "created_at": stamp, "updated_at": stamp}).execute()
            log_event(cid, actor, "created", _summary_detail(d))
            made.append({"id": cid, "label": lab})
            in_flight[:] = []
        sb.table("drafts").update({"data": rewritten, "updated_at": stamp}).eq("id", parent_id).execute()
    except Exception as exc:  # noqa: BLE001 — re-raised as a named refusal once cleaned up
        # AN ERROR FROM THE PARENT'S UPDATE IS AMBIGUOUS: PostgREST may have committed it and the
        # answer been lost (a read timeout, a 5xx after the write). The parent then already holds
        # only children[0]'s sheet, so the children are the ONLY copy of the other sheets: taking
        # them back would lose them for good. Read the parent back and let its split mark decide.
        landed = _split_landed(sb, parent_id, stamp) if len(made) == len(children) - 1 else False
        if landed is None:
            raise ScopeError("split_unconfirmed", "The database did not confirm the split. Nothing "
                                                  "was removed: reload the board to see whether the "
                                                  "proposals were made before trying again.",
                             503) from exc
        if not landed:
            # A HALF-FAILED SPLIT TAKES BACK WHAT IT MINTED (finding 27). A child left behind
            # carries the group's id and a sheet's name: it would join the project, hold the name a
            # retry needs (label_taken) and be expected by the combined email for ever. Deleted
            # outright; a child that will not delete is stripped of its group instead.
            _undo_split_children(sb, [m["id"] for m in made] + in_flight)
            raise ScopeError("split_failed", "Nothing was split: the database did not take every "
                                             "part of it, and the parts that were made have been "
                                             "removed. Try again in a minute.", 503) from exc
    log_event(parent_id, actor, "split_into_scopes",
              {"project_name": parent.get("project_name"), "id": parent_id, "group": gid,
               "scopes": [labels[0]] + [m["label"] for m in made],
               "ids": [parent_id] + [m["id"] for m in made]})
    _cache_clear()
    return {"group_id": gid,
            "parent": {"id": parent_id, "label": labels[0], "data": rewritten, "updated_at": stamp},
            "children": made}


# ── one estimate, several proposals ("Create Multiple Proposals", 2026-10-27) ──
# Hanz: the estimator fills ONE intake, prices the rooms as sheets of ONE estimate, ticks several
# sheets as base bids ("Base Bid 1", "Base Bid 2"...) and presses Create Multiple Proposals on the
# proposal page. The customer portal knows one proposal as one row of `drafts` (its own link,
# approval, deposit and follow-ups), so every base bid after the first is backed by a draft row of
# its own, made and kept up to date by the server from the parent: a CHILD. The parent is the one
# working estimate and is also Base Bid 1's proposal.
#
# A child is an ordinary scope of the parent's scope group to the board and the portal, plus three
# server-owned keys: `proposal_of` (the parent's id), `estimate_digest` (PROPOSAL_ESTIMATE_KEYS'
# digest of the parent when the child was copied from it) and `estimate_synced_at`. Children are
# found by their rows (proposal_children), never by a list on the parent.
#
# WHAT A CHILD COPIES FROM THE PARENT: the job and the whole estimate (every sheet, so its workbook
# and its options are the parent's), and the money of ITS base sheet read off `priced_tabs` with the
# Proposal step's rule (proposal-review.js rebuildPricing). WHAT IT OWNS: its words and its option
# picks (PROPOSAL_NARRATIVE_KEYS), which start empty and survive every refresh.
PROPOSAL_ESTIMATE_KEYS = SIBLING_INTAKE_KEYS + (
    "cell_values", "tab_copies", "tab_labels", "tab_order", "tab_structs", "lock_overrides",
    "extras", "priced_tabs", "polish_estimate", "hf_lump_sums", "tax_flags_per_sheet",
    "cove_height_v2",
)
# Intake keys a REFRESH leaves as the child has them: both are server-owned on the child itself (a
# person can file one proposal of the project, or hand it to another estimator, from the board).
PROPOSAL_REFRESH_SKIPS = ("is_test", "assigned_estimator")
# The base sheet's money, derived from priced_tabs[base] (_child_money).
PROPOSAL_MONEY_KEYS = (
    "proposal_lump_sum", "proposal_sales_tax", "proposal_remodel_tax", "proposal_taxable",
    "proposal_remodel_on", "sheet_area", "polish_sf", "phase_price", "cost_snapshot",
)
# What a child is as a proposal of ONE base sheet, set on every copy.
PROPOSAL_BASE_KEYS = ("base_tab_id", "base_tab_ids", "work_type", "computed_bid", "rooms")
# A child's OWN proposal: its words, its option picks and the files built from them. Never copied
# from the parent (a new child starts with `tab_opts: {}` and none of the rest), and exactly what a
# refresh keeps.
PROPOSAL_NARRATIVE_KEYS = (
    "tab_opts", "tab_notes", "price_lines", "price_overrides",
    "paragraph_overrides", "paragraph_overrides_all", "paragraph_overrides_meta",
    "box_overrides", "box_overrides_all", "box_overrides_meta", "system_overrides",
    "notes", "notes_text", "notes_seed", "scope_notes", "schedule_notes", "exclusions",
    "system_name", "system_name_manual", "system_name_polish", "system_name_epoxy", "texture",
    "cover_letter_enabled", "cover_letter_writer", "cover_letter_template_version",
    "cover_letter_paragraph_overrides", "cover_letter_paragraph_overrides_all",
    "cover_letter_paragraph_overrides_meta",
    "tax_layout", "tax_inclusion", "proposal_payload", "proposal_payload_key",
    "generate_result", "generated_lump_sum", "lump_sum_display", "dropbox_result",
)
# The Proposal step never offers these as a base: v1 refuses Seal (proposal-review.js
# OPTION_ONLY_ROLES), v2 refuses Seal and Leveling (work-types.js optionOnly, bid-model pickBase).
_V1_OPTION_ONLY_ROLES = ("seal",)
_V2_OPTION_ONLY_ROLES = ("seal", "leveling")
_V2_ROOT_TAB = "Polish"                 # bid-model.js ROOT_TAB: the root section IS the model
_V2_COPY_ID = re.compile(r"^Copy[1-9]\d*$")
_V2_OPTION_ONLY_SHEETS = ("Seal", "Seal (+Jnts)", "Leveling")


def _is_v2(data: Dict[str, Any]) -> bool:
    pe = (data or {}).get("polish_estimate")
    return isinstance(pe, dict) and pe.get("version") == 2


def _priced_tabs(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{tab id: its priced_tabs entry}, in the estimate's order (dicts keep it)."""
    out: Dict[str, Dict[str, Any]] = {}
    for t in (data or {}).get("priced_tabs") or []:
        if isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"] not in out:
            out[t["id"]] = t
    return out


def estimate_digest(data: Dict[str, Any]) -> str:
    """sha256 of a draft's ESTIMATE (PROPOSAL_ESTIMATE_KEYS less PROPOSAL_REFRESH_SKIPS): what a
    child copies on a refresh, so the digest moves exactly when a refresh would change something.

    Not `updated_at`: every browser save bumps that, and the parent is also Base Bid 1's proposal,
    so typing its wording would call every other proposal stale. Keys sorted, so a jsonb read-back
    (which reorders keys) gives the same answer."""
    src = data or {}
    picked = {k: src[k] for k in PROPOSAL_ESTIMATE_KEYS
              if k not in PROPOSAL_REFRESH_SKIPS and k in src}
    blob = json.dumps(picked, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _num(v: Any) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0.0
    return n if n == n else 0.0                # NaN reads as 0, like the page's N()


def _child_money(parent: Dict[str, Any], tab: str) -> Dict[str, Any]:
    """The money of a proposal whose ONE base is `tab`, off the parent's priced_tabs: rebuildPricing's
    rule for an explicit base (proposal-review.js), so the child's figure is the parent's figure for
    that sheet. A v2 sheet the estimate could not price stays None (composePricingSnapshot's null);
    a v1 one is 0 (the page's N()). `polish_sf`, `phase_price` and `cost_snapshot` come off the tab
    when its snapshot carries them (sf.polish_sf, phase, costs and man_hours), else the parent's own
    figure for the parent's own base, else nothing that would print another sheet's cost."""
    t = _priced_tabs(parent).get(tab) or {}
    v2 = _is_v2(parent)

    def money(k: str) -> Any:
        v = t.get(k)
        if v is None and v2:
            return None
        return _num(v)

    out: Dict[str, Any] = {
        "proposal_lump_sum": money("total"),
        "proposal_sales_tax": money("sales_tax"),
        "proposal_remodel_tax": money("remodel"),
        "proposal_taxable": t["taxable"] if isinstance(t.get("taxable"), bool) else None,
        "proposal_remodel_on": t["remodel_on"] if isinstance(t.get("remodel_on"), bool) else None,
    }
    sf = t.get("sf") if isinstance(t.get("sf"), dict) else {}
    out["sheet_area"] = {k: _num(v) for k, v in sf.items()}
    if "polish_sf" in sf:
        out["polish_sf"] = sf["polish_sf"]
    elif "polish_sf" in parent:
        out["polish_sf"] = copy.deepcopy(parent["polish_sf"])
    own_base = parent.get("base_tab_id") == tab
    if "phase" in t:
        out["phase_price"] = _num(t.get("phase"))
    elif own_base and "phase_price" in parent:
        out["phase_price"] = copy.deepcopy(parent["phase_price"])
    else:
        out["phase_price"] = 0
    if "costs" in t or "man_hours" in t:
        out["cost_snapshot"] = {"costs": _num(t.get("costs")),
                                "man_hours": int(round(_num(t.get("man_hours"))))}
    elif own_base and isinstance(parent.get("cost_snapshot"), dict):
        out["cost_snapshot"] = copy.deepcopy(parent["cost_snapshot"])
    else:
        out["cost_snapshot"] = {"costs": 0, "man_hours": 0}
    return out


def _v2_sections(pe: Dict[str, Any]) -> Dict[str, Tuple[str, str]]:
    """{section id: (sheet, kind)} of a v2 model, the root first (estimate_writer.group_member_sheet's
    reading: the root's kind is the model's own `kind`, a missing key being base)."""
    out: Dict[str, Tuple[str, str]] = {
        _V2_ROOT_TAB: (_V2_ROOT_TAB, pe.get("kind") if pe.get("kind") in ("off", "option") else "base")}
    tabs = pe.get("tabs") if isinstance(pe.get("tabs"), dict) else {}
    for sid, sec in tabs.items():
        if not isinstance(sec, dict) or sid == _V2_ROOT_TAB:
            continue
        sheet = sec.get("sheet") if _V2_COPY_ID.match(str(sid)) else sid
        out[str(sid)] = (str(sheet or ""), str(sec.get("kind") or ""))
    return out


def _v2_child_model(pe: Dict[str, Any], tab: str) -> Dict[str, Any]:
    """The parent's v2 model with `tab` as its ONE base: a deep copy in which `tab` is made base and
    every other base an option (bid-model.js withSectionKind, as pickBase applies it); options and
    sheets that are off stay as they are. The parent's model is not touched.

    RAISES ScopeError: no_such_sheet (the model has no such section, or it is off), option_only_base
    (Seal or Leveling, never a base), combined_base (the parent's base is two sheets priced together)."""
    if not (isinstance(pe, dict) and pe.get("version") == 2):
        raise ScopeError("no_such_sheet", "This bid has no Estimating Tool v2 estimate to copy.")
    sections = _v2_sections(pe)
    if tab not in sections or sections[tab][1] == "off":
        raise ScopeError("no_such_sheet", "The estimate has no sheet “%s” that is part of the bid."
                         % tab)
    if sections[tab][0] in _V2_OPTION_ONLY_SHEETS:
        raise ScopeError("option_only_base", "%s is an option on a bid and never a base bid of its "
                                             "own." % sections[tab][0])
    if sum(1 for _s, kind in sections.values() if kind == "base") > 1:
        raise ScopeError("combined_base", "The base bid is an Epoxy and a Polish sheet priced "
                                          "together. Make one sheet the base first.")
    out = copy.deepcopy(pe)
    for sid, (_sheet, kind) in sections.items():
        want = "base" if sid == tab else ("option" if kind == "base" else kind)
        if want == kind:
            continue
        if sid == _V2_ROOT_TAB:
            if want == "base":
                out.pop("kind", None)
            else:
                out["kind"] = want
        else:
            out["tabs"][sid] = dict(out["tabs"][sid], kind=want)
    return out


_V2_COVE_ID = re.compile(r"^wb-epoxy-cove-[a-z]+-(\d+)in(?:-|$)")
_JS_NUM = re.compile(r"^-?\d*\.?\d+$")


def _measured(raw: Any) -> float:
    """excel-math.js num(), which bid-model reads a takeoff measurement with: "$1,200" and
    " 12,500 " are numbers, a boolean or anything else is 0."""
    if isinstance(raw, bool) or raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return _num(raw) if raw not in (float("inf"), float("-inf")) else 0.0
    s = re.sub(r"[$,\s]", "", str(raw))
    return float(s) if _JS_NUM.match(s) else 0.0


def _v2_cove_height(pe: Dict[str, Any], tab: str) -> str:
    """The cove height of section `tab` of a v2 model: bid-model.js coveHeightOf over that one
    section (the first LF takeoff row that is on, measured above 0, whose assembly names a cove
    system's height), "" for none. The parent's `cove_height_v2` is its OWN base's cove, so a
    child whose base is another section reads its own."""
    section = pe if tab == _V2_ROOT_TAB else ((pe.get("tabs") or {}).get(tab) or {})
    rows = section.get("takeoff") if isinstance(section, dict) else None
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or r.get("unit") != "LF" or r.get("enabled") is False \
                or not _measured(r.get("measurement")) > 0:
            continue
        m = _V2_COVE_ID.match(str(r.get("assembly_id") or ""))
        if m:
            return m.group(1)
    return ""


def _v2_texture(parent: Dict[str, Any], tab: str) -> str:
    """The texture the estimate gives section `tab` of a v2 parent (bid-model.js sectionTexture: the
    section's own `texture`, trimmed), "" for none, for the root (a Polish sheet has no texture) and
    for a v1 draft. What a child whose base is `tab` starts its Proposal step's texture from."""
    if not _is_v2(parent) or tab == _V2_ROOT_TAB:
        return ""
    tabs = parent["polish_estimate"].get("tabs")
    sec = tabs.get(tab) if isinstance(tabs, dict) else None
    tex = sec.get("texture") if isinstance(sec, dict) else None
    return tex.strip() if isinstance(tex, str) else ""


def _seed_texture(child: Dict[str, Any], texture: str) -> None:
    """Give `child` its base sheet's texture (in place), bid-model.js textureFill's rule: only while
    its own `texture` is empty or still the one last seeded (`texture_from_estimate`), so a texture
    picked on the child's Proposal step is never overwritten. Nothing is written when nothing would
    change."""
    held = child.get("texture")
    held = held.strip() if isinstance(held, str) else ("" if held is None else None)
    seeded = child.get("texture_from_estimate")
    seeded = seeded if isinstance(seeded, str) else None
    if held is None or not (held == "" or (seeded is not None and held == seeded)):
        return
    if seeded is None and texture == "":
        return
    child["texture"] = texture
    child["texture_from_estimate"] = texture


def _proposal_copy(parent: Dict[str, Any], tab: str, refresh: bool) -> Dict[str, Any]:
    """Everything a child of `parent` whose base is `tab` copies from it: the estimate
    (PROPOSAL_ESTIMATE_KEYS, less PROPOSAL_REFRESH_SKIPS on a refresh), the base's money and what
    makes it a one-base proposal (PROPOSAL_BASE_KEYS). A NEW object, sharing nothing with `parent`.
    A v2 child's model and its priced_tabs' kinds are the kind-flipped copy (_v2_child_model)."""
    skip = PROPOSAL_REFRESH_SKIPS if refresh else ()
    out = {k: copy.deepcopy(parent[k]) for k in PROPOSAL_ESTIMATE_KEYS
           if k in parent and k not in skip}
    priced = _priced_tabs(parent)
    role = str((priced.get(tab) or {}).get("role") or "").lower()
    if _is_v2(parent):
        out["polish_estimate"] = _v2_child_model(parent["polish_estimate"], tab)
        flipped = _v2_sections(out["polish_estimate"])
        if isinstance(out.get("priced_tabs"), list):
            for t in out["priced_tabs"]:
                if isinstance(t, dict) and t.get("id") in flipped:
                    t["kind"] = flipped[t["id"]][1]
        out["cove_height_v2"] = _v2_cove_height(out["polish_estimate"], tab)
    out.update(_child_money(parent, tab))
    out["base_tab_id"] = tab
    out["base_tab_ids"] = [tab]
    out["work_type"] = role or str(parent.get("work_type") or "") or None
    out["computed_bid"] = None
    out["rooms"] = []
    return out


# The name fan-out gave a proposal before 2026-10-27 ("Base Bid 2"): a POSITION, not a name. A stored
# label that is exactly this was never typed by a person, so the strip shows the sheet's name instead.
_OLD_DEFAULT_LABEL = re.compile(r"^Base Bid \d+$")


def proposal_sheet_label(data: Dict[str, Any], tab: Any) -> Optional[str]:
    """The name the estimate gives sheet `tab` of `data`, as a scope's name (clean_scope_label, cut to
    the portal's cap), or None when `tab` is not a sheet id. A v2 estimate names its sections in the
    model (bid-model.js: the root's `label`, else "Polish"; a section's `label`, else its `sheet`),
    the spreadsheet in `tab_labels` (estimate-review.js labelFor); either falls back to the name the
    price snapshot recorded (priced_tabs[].name) and then to the id itself."""
    if not isinstance(tab, str) or not tab:
        return None
    data = data or {}
    names: List[Any] = []
    pe = data.get("polish_estimate")
    if _is_v2(data):
        if tab == _V2_ROOT_TAB:
            names.append(pe.get("label") or _V2_ROOT_TAB)
        else:
            sec = (pe.get("tabs") or {}).get(tab) if isinstance(pe.get("tabs"), dict) else None
            if isinstance(sec, dict):
                names.extend([sec.get("label"), sec.get("sheet")])
    else:
        labels = data.get("tab_labels")
        if isinstance(labels, dict):
            names.append(labels.get(tab))
    names.extend([(_priced_tabs(data).get(tab) or {}).get("name"), tab])
    for n in names:
        if not isinstance(n, str) or not n.strip():
            continue
        text = re.sub(r"\s+", " ", _CONTROL_CHARS.sub(" ", n)).strip()
        if text:
            return text[:SCOPE_LABEL_MAX].rstrip()
    return None


def _money_or_none(v: Any) -> Optional[float]:
    """A stored figure as a number, None for none (a missing, null, boolean or non-number value)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def proposal_children(parent_id: str, group_id: Optional[str]) -> List[Dict[str, Any]]:
    """The LIVE members of `group_id` made from `parent_id`'s base bids (proposal_of), oldest first.
    [] for a draft in no group."""
    if not group_id:
        return []
    return [m for m in _group_rows(group_id)
            if m.get("proposal_of") == parent_id and m["id"] != parent_id]


def _proposal_rows(parent_id: str, group_id: Optional[str],
                   members: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """proposal_children, each with its stored blob ({id, label, created_at, data}); a child deleted
    or moved out between the two reads is left out. `members` is the group's _group_rows when the
    caller has read them already (they are not read again)."""
    out = []
    kids = (proposal_children(parent_id, group_id) if members is None else
            [m for m in members if m.get("proposal_of") == parent_id and m["id"] != parent_id])
    for m in kids:
        row = load_draft(m["id"])
        data = (row or {}).get("data") or {}
        if not row or data.get("proposal_of") != parent_id:
            continue
        out.append({"id": m["id"], "label": m.get("label") or "", "created_at": m.get("created_at"),
                    "updated_at": row.get("updated_at"), "data": data})
    return out


def _stamp_at(base: datetime, i: int) -> str:
    """`base` + i microseconds, ISO: the children are made in Base Bid order and the board orders a
    group by created_at, so each gets its own instant."""
    return (base + timedelta(microseconds=i)).isoformat()


# ── each proposal prices its own sheet (Hanz, 2026-10-28) ────────────────────────────────────────
# "Why is there an extra epoxy tab when we only have Epoxy and Polish?" Polish was Base Bid 1 (the
# parent) and Epoxy Base Bid 2 (a child); "Make Base Bid 1" on Epoxy moved the PARENT to Epoxy and
# the old base Polish into the ticked list, and the child stayed on Epoxy: two proposals priced one
# sheet and Polish had none. A child is matched to its sheet by its own base_tab_id, so nothing
# followed a base swap. Create Multiple Proposals and Refresh now RECONCILE first: the sheets the
# children should price are the parent's base bids after Base Bid 1 (_wanted_sheets); a child on any
# other sheet is OUT OF STEP (_out_of_step) and, unless the customer has it, takes a wanted sheet
# that has no child (_plan_reconcile), keeping its wording, its link and its portal identity. One
# that cannot move is reported and left as it is, never deleted.

# THE OLD BASE (review of this fix, finding 2). The child a swap leaves on Base Bid 1's sheet belongs
# on the sheet the parent gave up, and the parent's list cannot say which that was: TWPrice.moveBaseId
# with `keep` sorts every sheet after Base Bid 1 into tab-strip order, so with tabs Epoxy, Room 2,
# Polish and Polish swapped for Epoxy the list reads [Epoxy, Copy1, Polish] and the first free sheet
# is Room 2. So the parent records, server-owned, the base its proposals were last matched against
# (_matched_base), and _plan_reconcile gives the swap's partner that sheet while it is free.
PROPOSALS_BASE = "proposals_base_tab_id"


def _matched_base(parent: Dict[str, Any], kids: List[Dict[str, Any]], left: set) -> Optional[str]:
    """What the parent's PROPOSALS_BASE says after a press: its base, now that the proposals are
    matched against it, unless a child is still out of step on that very sheet (`left`: the ids a
    press did not move, a sent one or a failed write), whose partner is still the sheet the old
    record names. None when there is nothing to record."""
    base = parent.get("base_tab_id")
    if any(c["id"] in left and c["data"].get("base_tab_id") == base for c in kids):
        return parent.get(PROPOSALS_BASE)
    return base if isinstance(base, str) and base else parent.get(PROPOSALS_BASE)


# THE BASE-PICK RULE ON A MOVED PROPOSAL (review of this fix, finding 1). A move is a base change, and
# every base change in the browser runs TWPrice.applyBasePick over the draft's price_overrides: the
# oldest editor's per-field buckets reset (the document prints single_bid.amount as the base bid
# outright, main.py's base_bid_formatted), and the lines that print the base bid follow the new
# base. Kept as they were, the Polish proposal printed the Epoxy sheet's typed $20,000 while the card
# and the portal booked $9,000. _rebase_price_overrides is applyBasePick as a caller that names no
# base phrase runs it (no `opts.basePhrase`, no `opts.roles`); test_multi_proposals.py runs both
# over one matrix.
_BASE_ROW_WORDS = {"sales_tax": "Material Sales Tax", "remodel": "Remodel Tax", "total": "Total"}


def _base_desc(work_type: Any, role: Any) -> str:
    """TWPrice.baseDesc: the base line's words for the system it prices."""
    wt = str(work_type or "epoxy").lower()
    r = str(role or "").lower()
    eff = "combo" if wt == "combo" else (r if r in ("epoxy", "polish", "gyp") else wt)
    noun = {"polish": "Polished Concrete Flooring", "combo": "Epoxy & Polished Concrete flooring",
            "sealer": "Sealed Concrete", "gyp": "Gypsum Underlayment System"}.get(eff, "Epoxy flooring")
    return noun + " as described above"


def _js_cents(v: Any) -> int:
    """TWPrice.cents (Number(), Math.round) of a tab figure or a money string."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        n = float(v)
        return int(math.floor(n * 100 + 0.5)) if math.isfinite(n) else 0
    return price_rules._js_cents(v)


def _usd(c: int) -> str:
    """TWPrice.usd: cents in the documents' money style ("$7,447", "$1,870.50")."""
    neg = c < 0
    c = -c if neg else c
    frac = c % 100
    return ("-" if neg else "") + "$" + "{:,}".format(c // 100) + ("." + "%02d" % frac if frac else "")


def _tab_figures(tabs: List[Any], key: str) -> List[str]:
    """TWPrice.tabFigures for a base key: every figure a tab prices that line at."""
    seen: set = set()
    out: List[str] = []

    def add(c: int) -> None:
        if c > 0 and c not in seen:
            seen.add(c)
            out.append(_usd(c))
    for t in tabs:
        if not isinstance(t, dict):
            continue
        tot, s, r = _js_cents(t.get("total")), _js_cents(t.get("sales_tax")), _js_cents(t.get("remodel"))
        if key == "sales_tax":
            add(s)
        elif key == "remodel":
            add(r)
        elif key == "total":
            add(tot)
        else:
            add(tot)
            add(tot - s)
            add(tot - r)
            add(tot - s - r)
    return out


def _amount_at(s: str) -> Optional[Tuple[int, str]]:
    """TWPrice.amountAt: the line's first plain dollar figure, (at, text), or None."""
    return next(price_rules._money_hits(s), None)


def _amount_is_one_of(s: str, figures: List[str]) -> bool:
    a = _amount_at(s)
    if a is None:
        return False
    c = price_rules._js_cents(a[1])
    return any(re.fullmatch(r"\$[0-9,]+(?:\.[0-9]+)?", f) and price_rules._js_cents(f) == c
               for f in figures)


def _mark_amount(s: str) -> str:
    at, text = _amount_at(s)
    return s[:at] + price_rules.AMOUNT_MARK + s[at + len(text):]


def _migrate_base_line(legacy: str, figs: List[str], slot: bool) -> Tuple[Optional[str], list, list]:
    """TWPrice.migrateLine with only `others` (and `slot`) given: (main, before, after), main None
    when the line is dropped."""
    lines = re.sub(r"\r\n?", "\n", legacy).split("\n")

    def shaped(line: str) -> bool:
        return bool(price_rules._PRICE_SHAPE_RE.search(line)) or any(
            p in line for p in price_rules.KNOWN_PHRASES)
    steps = (lambda l: shaped(l) and _amount_is_one_of(l, figs), shaped,
             lambda l: bool(price_rules._MONEY_AT_RE.search(l)),
             lambda l: bool(price_rules._JS_TRIM_RE.sub("", l)))
    mi = next((i for step in steps for i, line in enumerate(lines) if step(line)), -1)
    if mi < 0:
        return None, [], []
    main = lines[mi]
    if price_rules.AMOUNT_MARK not in main and _amount_is_one_of(main, figs):
        main = _mark_amount(main)
    if slot:
        for p in price_rules.KNOWN_PHRASES:
            j = main.find(p)
            if j >= 0:
                main = main[:j] + price_rules.TAX_MARK + main[j + len(p):]
                break
    return main, lines[:mi], lines[mi + 1:]


def _rebase_price_overrides(pov: Any, frm: Optional[str], to: Optional[str], tabs: List[Any],
                            work_type: Any) -> bool:
    """TWPrice.applyBasePick(pov, frm, to, tabs, {workType}) in place: single_bid, rows and combo
    reset; each line that prints the base bid (base, sales_tax, remodel, total) keeps his words, a
    figure a tab prices it at becomes the live amount, the old base's system words become the new
    base's, an old-shape line is migrated, and one that reads exactly as the tool prints it goes.
    Nothing else is touched. Returns whether anything changed."""
    if not isinstance(pov, dict):
        return False
    changed = False
    for b in ("single_bid", "rows", "combo"):
        m = pov.get(b)
        if isinstance(m, (dict, list)) and len(m):
            changed = True
        pov[b] = {}

    def role_of(tid: Optional[str]) -> str:
        if tid is None or tid == "":
            return ""
        t = next((t for t in tabs if isinstance(t, dict) and t.get("id") == tid), None)
        return (t.get("role") or "") if t else ""
    desc_from, desc_to = _base_desc(work_type, role_of(frm)), _base_desc(work_type, role_of(to))
    legacy = pov.get("lines") if isinstance(pov.get("lines"), dict) else None
    live = pov.get("lines2") if isinstance(pov.get("lines2"), dict) else None
    amount, tax = price_rules.AMOUNT_MARK, price_rules.TAX_MARK
    for k in ("base", "sales_tax", "remodel", "total"):
        figs = _tab_figures(tabs, k)
        has_live = (live is not None and isinstance(live.get(k), str)
                    and bool(price_rules._JS_TRIM_RE.sub("", live[k])))
        text = live[k] if has_live else None
        if legacy is not None and isinstance(legacy.get(k), str):
            if not has_live:
                main, before, after = _migrate_base_line(legacy[k], figs, k == "base")
                for side, rows in (("before", before), ("after", after)):
                    if not rows:
                        continue
                    bucket = pov.get(side)
                    if not isinstance(bucket, dict):
                        bucket = pov[side] = {}
                    if not isinstance(bucket.get(k), list) or not bucket[k]:
                        bucket[k] = list(rows)
                        props = pov.get(side + "_props")
                        if isinstance(props, dict) and k in props:
                            del props[k]
                            changed = True
                if main is not None and not price_rules._JS_TRIM_RE.sub("", main):
                    main = None
                at = _amount_at(main) if main is not None and k != "base" else None
                if at is not None and price_rules._js_cents(at[1]) == 0:
                    main = None                                  # the old sweep's "$0 – Total"
                text = main
            del legacy[k]
            changed = True
        if text is None:
            continue
        nxt = text
        if amount not in nxt and _amount_is_one_of(nxt, figs):
            nxt = _mark_amount(nxt)
        if k == "base" and desc_from != desc_to and desc_from in nxt:
            nxt = nxt.replace(desc_from, desc_to)
        canon = (amount + " – " + desc_to + " " + tax if k == "base"
                 else amount + " – " + _BASE_ROW_WORDS[k])
        if nxt == canon:
            if has_live:
                del live[k]
                changed = True
            continue
        if not has_live or live[k] != nxt:
            if live is None:
                live = pov["lines2"] = {}
            live[k] = nxt
            changed = True
    return changed


# Why a child is out of step, as the strip and the sentences say it.
_OUT_OF_STEP_WHY = {
    "same_as_base": "now prices the same sheet as Base Bid 1",
    "duplicate": "prices the same sheet as another proposal of this project",
    "not_base": "prices a sheet that is not a base bid any more",
    "sheet_gone": "prices a sheet that is not on the estimate any more",
}


def _wanted_sheets(parent: Dict[str, Any], ids: Optional[List[str]] = None) -> Optional[List[str]]:
    """The sheets the children of `parent` should price, in Base Bid order: its base bids
    (`ids`, else its stored `base_tab_ids`) less Base Bid 1 (its own `base_tab_id`), each once, each a
    priced sheet that can be a base. None when the parent keeps no list at all: nothing is
    reconciled then, and every child is taken as it is (the shape before Create Multiple Proposals)."""
    raw = parent.get("base_tab_ids") if ids is None else ids
    if not isinstance(raw, list):
        return None
    base = parent.get("base_tab_id")
    priced = _priced_tabs(parent)
    only = _V2_OPTION_ONLY_ROLES if _is_v2(parent) else _V1_OPTION_ONLY_ROLES
    out: List[str] = []
    for t in raw:
        if (isinstance(t, str) and t and t != base and t not in out and t in priced
                and str(priced[t].get("role") or "").lower() not in only):
            out.append(t)
    return out


def _out_of_step(parent: Dict[str, Any], kids: List[Dict[str, Any]],
                 wanted: Optional[List[str]]) -> Dict[str, str]:
    """{child id: why} for every child of `kids` (oldest first) that does not price a wanted sheet of
    its own: `same_as_base` (its sheet is Base Bid 1's, a base swap), `duplicate` (an older child
    prices it), `sheet_gone` (the estimate has no such priced sheet), `not_base` (its sheet was
    switched to Option or Off). {} when `wanted` is None."""
    if wanted is None:
        return {}
    base = parent.get("base_tab_id")
    priced = _priced_tabs(parent)
    claimed: set = set()
    out: Dict[str, str] = {}
    for c in kids:
        tab = c["data"].get("base_tab_id")
        if isinstance(tab, str) and tab in wanted and tab not in claimed:
            claimed.add(tab)
            continue
        if isinstance(tab, str) and tab and tab == base:
            out[c["id"]] = "same_as_base"
        elif tab in claimed:
            out[c["id"]] = "duplicate"
        elif not isinstance(tab, str) or tab not in priced:
            out[c["id"]] = "sheet_gone"
        else:
            out[c["id"]] = "not_base"
    return out


def _shown_label(stored: str, sheet: Optional[str]) -> str:
    """What a proposal's tab says: a name a person typed is kept; the old "Base Bid N" default (or
    none) shows its sheet's."""
    if stored and not _OLD_DEFAULT_LABEL.match(stored):
        return stored
    return sheet or stored


def _is_sheet_label(stored: Any, parent: Dict[str, Any]) -> bool:
    """Was `stored` given by the sheet rule rather than typed by a person: none, the old "Base Bid N"
    default, or the name of a sheet of `parent`'s estimate (a clash's " 2" included, _free_label)?
    Such a name follows its proposal to another sheet; a typed one never changes."""
    if not isinstance(stored, str) or not stored.strip() or _OLD_DEFAULT_LABEL.match(stored):
        return True
    names = {(proposal_sheet_label(parent, t) or "").lower() for t in _priced_tabs(parent)}
    names.discard("")
    low = stored.lower()
    if low in names:
        return True
    m = re.match(r"^(.*) \d+$", low)
    return bool(m) and m.group(1) in names


def _plan_reconcile(parent: Dict[str, Any], kids: List[Dict[str, Any]], wanted: Optional[List[str]],
                    is_sent: Callable[[str], bool]) -> Dict[str, Any]:
    """Which child prices which sheet. Returns {"keep": [child], "moves": [(child, sheet)],
    "stuck": [{"id", "label", "code", "message"}], "free": [sheet with no child]}.

    An out-of-step child (_out_of_step) the customer does not have (`is_sent` false) takes a free
    wanted sheet, pairing deterministically: the child on Base Bid 1's own sheet first (a swap's
    partner), to the OLD BASE (the parent's PROPOSALS_BASE, the base the proposals were last matched
    against) when that sheet is free; then the others oldest first, each to the next free sheet in
    Base Bid order (the swap's partner too when no old base is recorded or it is not free). Base Bid
    order alone is not the old base: TWPrice.moveBaseId puts every sheet after Base Bid 1 in tab-strip
    order. A SENT one never moves (code `sent`); one with no free sheet left stays (its why). `is_sent`
    is asked of out-of-step children only, and before anything is written, so a portal that cannot
    answer stops the whole press. It may raise; this does not catch it."""
    why = _out_of_step(parent, kids, wanted)
    keep = [c for c in kids if c["id"] not in why]
    claimed = {c["data"].get("base_tab_id") for c in keep}
    free = [t for t in (wanted or []) if t not in claimed]
    late = sorted((c for c in kids if c["id"] in why),
                  key=lambda c: 0 if why[c["id"]] == "same_as_base" else 1)
    old_base = parent.get(PROPOSALS_BASE)
    moves: List[Tuple[Dict[str, Any], str]] = []
    stuck: List[Dict[str, Any]] = []
    for c in late:
        name = _shown_label(c["label"], proposal_sheet_label(parent, c["data"].get("base_tab_id")))
        what = _OUT_OF_STEP_WHY[why[c["id"]]]
        if is_sent(c["id"]):
            stuck.append({"id": c["id"], "label": c["label"], "code": "sent",
                          "message": "%s (the copy the customer has) %s. Close it or keep it; "
                                     "nothing was changed." % (name, what)})
        elif free:
            # Once taken the old base is not free any more, so only the first partner gets it.
            to = old_base if why[c["id"]] == "same_as_base" and old_base in free else free[0]
            free.remove(to)
            moves.append((c, to))
        elif why[c["id"]] == "sheet_gone":
            stuck.append({"id": c["id"], "label": c["label"], "code": "sheet_gone"})
        else:
            stuck.append({"id": c["id"], "label": c["label"], "code": "out_of_step",
                          "message": "%s %s and no other base bid is free for it, so it was left as "
                                     "it was. Delete it, or set another sheet to Base bid and "
                                     "Refresh." % (name, what)})
    return {"keep": keep, "moves": moves, "stuck": stuck, "free": free}


# What a refresh or a move REPLACES on a child: its estimate, its money and its base.
_REFRESH_REPLACED = frozenset((set(PROPOSAL_ESTIMATE_KEYS) - set(PROPOSAL_REFRESH_SKIPS))
                              | set(PROPOSAL_MONEY_KEYS) | set(PROPOSAL_BASE_KEYS))


def _recopied(parent: Dict[str, Any], data: Dict[str, Any], tab: str, digest: str) -> Dict[str, Any]:
    """A child blob `data` copied afresh from `parent` as the proposal of sheet `tab`: its estimate,
    money and base replaced (_proposal_copy, refresh), everything else of it kept (its words, option
    picks, group and server keys), the digest and `estimate_synced_at` stamped (moved on a coarse
    clock tick: the stamp is the fence StaleProposalWrite reads). RAISES ScopeError as
    _proposal_copy does."""
    fresh = _proposal_copy(parent, tab, refresh=True)
    out = {k: v for k, v in data.items() if k not in _REFRESH_REPLACED}
    out.update(fresh)
    now = _now_iso()
    if now == data.get("estimate_synced_at"):
        # The stamp is the fence against a page holding the copy before this one
        # (StaleProposalWrite), so it must move even when the clock has not (a coarse tick).
        now = _stamp_at(datetime.fromisoformat(now), 1)
    out["estimate_digest"] = digest
    out["estimate_synced_at"] = now
    return out


def _local_sent(draft_id: str) -> bool:
    """The store's own proof that a draft was sent (a revision); the routes ask the portal too."""
    return bool(latest_revision_no(draft_id))


# WHO SIGNS A NEW PROPOSAL OF CREATE MULTIPLE PROPOSALS (Hanz, 2026-10-28): the same person as
# Base Bid 1, so every proposal of one project is signed alike. The Proposal step signs with the
# draft's `estimator_name` (proposal-review.js prefillEstimator), else the name its last document was
# signed with, else whoever has the page open; and at the address its last document carried for that
# name, else the viewer's (computeTokenValues). A child has neither a name nor a document, so it was
# signed by whoever opened it, or, built by Send all's walk, by whoever pressed Send all.
#
# `estimator_signer` pairs the address with the NAME it belongs to, so a name typed over it later
# never signs with Base Bid 1's address. Set once, when the child is made: a refresh replaces only
# _REFRESH_REPLACED, so a signer changed on the child stays.
PROPOSAL_SIGNER_KEYS = ("estimator_name", "estimator_signer")


def _parent_signer(parent: Dict[str, Any]) -> Dict[str, Any]:
    """{estimator_name, estimator_signer: {name, email}} of `parent`'s signature, the keys it has.
    {} when the parent names nobody."""
    pp = parent.get("proposal_payload")
    signed = (pp.get("values") if isinstance(pp, dict) else None) or {}
    signed = signed if isinstance(signed, dict) else {}
    own = parent.get("estimator_name")
    name = (own.strip() if isinstance(own, str) else "") or str(signed.get("estimator_name") or "").strip()
    if not name:
        return {}
    out: Dict[str, Any] = {"estimator_name": name}
    email = ""
    if str(signed.get("estimator_name") or "").strip().lower() == name.lower():
        email = str(signed.get("estimator_email") or "").strip()
    held = parent.get("estimator_signer")
    if not email and isinstance(held, dict) and str(held.get("name") or "").strip().lower() == name.lower():
        email = str(held.get("email") or "").strip()     # a parent that was itself seeded so
    if email:
        out["estimator_signer"] = {"name": name, "email": email}
    return out


# ── ONE NAME: a proposal is called what its base sheet is called (Hanz, 2026-10-29) ──────────────
# "I changed the label on these sheets and it didn't change. Whatever the sheet name is, that would
# be the name of the proposals, so we have it unified throughout all the steps." A proposal's name was
# stored once, when Create Multiple Proposals made it (its sheet's name THEN), so a sheet renamed on
# the estimate later left the proposal on the old name, and step 3 said "Polish (Polish Room)".
#
# THE RULE (proposal_names): every proposal of an estimate is named after ITS base sheet on the
# PARENT's estimate (proposal_sheet_label of its base_tab_id; Base Bid 1 after its own base), in the
# strip's order, a clash numbered by _free_label ("Room", "Room 2"), the names of the group's other
# scopes (RJ's scopes, which are not proposals of this estimate) kept free. A name typed by hand is
# not kept: renaming a proposal renames its sheet (rename_proposal), so the two never disagree.
#
# WHERE IT LIVES: scope_group.label, as before, so the board, the drawer, the Dropbox file names and
# the portal (which reads it at a publish, and the combined email, which reads it at a send) are
# unchanged. sync_proposal_labels stores it after every save of the parent's estimate (save_draft),
# before every publish (adopt_sheet_label) and before Send all; proposals_view shows the same rule,
# so the strip never waits for a save. Nothing here calls the portal or emails anybody.
SHEET_NAME_MAX = 31                        # a workbook's own limit (estimate-review / bid-model)
_SHEET_NAME_BAD = re.compile(r'[!:\\/?*\[\]"]')


def _may_have_proposals(data: Dict[str, Any]) -> bool:
    """Could this blob be an estimate with proposals (Create Multiple Proposals' parent)? Read off
    the blob alone, so a save of any other draft asks the database nothing more: it is in a scope
    group, is no proposal of another draft, and has been fanned out (PROPOSALS_BASE) or keeps a list
    of base bids."""
    data = data or {}
    return (isinstance(data.get("scope_group"), dict) and not data.get("proposal_of")
            and (PROPOSALS_BASE in data or isinstance(data.get("base_tab_ids"), list)))


def _strip_rank(parent: Dict[str, Any]) -> Callable[[Any, Any], Tuple[int, str]]:
    """The strip's order of the children of `parent`: by their sheet's place in its base bids, then
    oldest first. rank(base_tab_id, created_at)."""
    order = [t for t in (parent.get("base_tab_ids") or []) if isinstance(t, str)]

    def rank(tab: Any, created_at: Any) -> Tuple[int, str]:
        return (order.index(tab) if tab in order else len(order), str(created_at or ""))
    return rank


def proposal_names(parent: Dict[str, Any], members: List[Dict[str, Any]],
                   reserved: Any = ()) -> Dict[str, str]:
    """THE ONE NAME of each of `members` ([{id, label, base_tab_id}], the strip's order, Base Bid 1
    first): its base sheet's name on `parent`'s estimate, made free of `reserved` (names taken by
    the group's other scopes) and of the members before it. A member whose base names no sheet (a
    combined base) keeps its stored name; one with neither is "Base Bid N". Returns {id: name}."""
    taken = {str(x).lower() for x in reserved if x}
    out: Dict[str, str] = {}
    for i, m in enumerate(members, start=1):
        want = (proposal_sheet_label(parent, m.get("base_tab_id"))
                or str(m.get("label") or "").strip() or "Base Bid %d" % i)
        name = _free_label(want, taken)
        taken.add(name.lower())
        out[m["id"]] = name
    return out


def _proposal_family(parent_id: str, parent: Dict[str, Any],
                     rows: Optional[List[Dict[str, Any]]] = None
                     ) -> Optional[Tuple[str, List[Dict[str, Any]], set]]:
    """(group id, members, reserved) of the estimate `parent_id` (blob `parent`): Base Bid 1 then its
    live children in the strip's order, each {id, label, base_tab_id, created_at}, and the names of
    the group's other live scopes. None when it is no estimate with proposals. `rows` is the group's
    _group_rows when the caller has read them."""
    gid, plabel = _scope_of(parent)
    if not gid or (parent or {}).get("proposal_of"):
        return None
    rows = _group_rows(gid) if rows is None else rows
    kids = [m for m in rows if m.get("proposal_of") == parent_id and m["id"] != parent_id]
    if not kids:
        return None
    rank = _strip_rank(parent)
    kids.sort(key=lambda m: rank(m.get("base_tab_id"), m.get("created_at")))
    members = [{"id": parent_id, "label": plabel or "", "base_tab_id": parent.get("base_tab_id"),
                "created_at": None}] + [
        {"id": m["id"], "label": m.get("label") or "", "base_tab_id": m.get("base_tab_id"),
         "created_at": m.get("created_at")} for m in kids]
    ids = {m["id"] for m in members}
    reserved = {m["label"] for m in rows if m["id"] not in ids and m.get("label")}
    return gid, members, reserved


def _sync_names(parent_id: str, parent: Dict[str, Any], actor: Optional[str]
                ) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """sync_proposal_labels' work: ({id: the one name}, [{id, from, to}] of what was written)."""
    fam = _proposal_family(parent_id, parent)
    if fam is None:
        return {}, []
    gid, members, reserved = fam
    names = proposal_names(parent, members, reserved)
    sb = get_client()
    changed: List[Dict[str, Any]] = []
    for m in members:
        new = names[m["id"]]
        if new == m["label"]:
            continue
        # The row as it is now, so nothing else of it is written back (only its name changes).
        cur = sb.table("drafts").select("id,data").eq("id", m["id"]).limit(1).execute()
        if not cur.data:
            continue
        data = dict(cur.data[0].get("data") or {})
        sg = data.get("scope_group")
        if not isinstance(sg, dict) or sg.get("id") != gid or sg.get("label") == new:
            continue
        old = sg.get("label")
        data["scope_group"] = dict(sg, label=new)
        sb.table("drafts").update({"data": data}).eq("id", m["id"]).execute()
        log_event(m["id"], actor, "scope_renamed", {"project_name": data.get("project_name"),
                                                    "id": m["id"], "group": gid, "from": old,
                                                    "to": new, "sheet": m.get("base_tab_id")})
        changed.append({"id": m["id"], "from": old, "to": new})
    if changed:
        _cache_clear()
    return names, changed


def sync_proposal_labels(parent_id: str, actor: Optional[str] = None,
                         parent: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """STORE THE ONE NAME (proposal_names) on every proposal of the estimate `parent_id` whose stored
    name differs, Base Bid 1 included: scope_group.label only, each row re-read before it is written
    so nothing else of it changes, `updated_at` NOT bumped (a name is not work on a proposal, and the
    publish's draft_version check reads it), each logged as scope_renamed. `parent` is the estimate's
    blob when the caller holds it (save_draft has just stored it). Never calls the portal.

    Returns [{id, from, to}] of what was renamed; [] for a draft that is no estimate with proposals."""
    if parent is None:
        cur = get_client().table("drafts").select("id,data").eq("id", parent_id).limit(1).execute()
        if not cur.data:
            return []
        parent = cur.data[0].get("data") or {}
    return _sync_names(parent_id, parent, actor)[1]


def _sheet_names(data: Dict[str, Any]) -> Dict[str, str]:
    """{sheet id: its name} of an estimate, as its own page names the sheets: a v2 model's sections
    (bid-model.js sectionsOf: the root's `label` else "Polish", a section's `label` else its id), a
    spreadsheet's tabs (estimate-review.js labelFor: tab_labels[id] else the id)."""
    data = data or {}
    out: Dict[str, str] = {}

    def named(v: Any, fallback: str) -> str:
        return v if isinstance(v, str) and v.strip() else fallback
    if _is_v2(data):
        pe = data["polish_estimate"]
        out[_V2_ROOT_TAB] = named(pe.get("label"), _V2_ROOT_TAB)
        tabs = pe.get("tabs") if isinstance(pe.get("tabs"), dict) else {}
        for sid, sec in tabs.items():
            if isinstance(sec, dict) and sid != _V2_ROOT_TAB:
                out[str(sid)] = named(sec.get("label"), str(sid))
        return out
    labels = data.get("tab_labels") if isinstance(data.get("tab_labels"), dict) else {}
    copies = data.get("tab_copies")
    ids: List[Any] = list(data.get("tab_order") or []) if isinstance(data.get("tab_order"), list) else []
    ids += [t.get("id") for t in (data.get("priced_tabs") or []) if isinstance(t, dict)]
    if isinstance(copies, dict):
        ids += list(copies)
    elif isinstance(copies, list):
        ids += [c.get("id") for c in copies if isinstance(c, dict)]
    ids += list(labels)
    for t in ids:
        if isinstance(t, str) and t and t not in out:
            out[t] = named(labels.get(t), t)
    return out


def _sheet_name_problem(names: Dict[str, str], tab: str, want: str) -> Optional[Tuple[str, str]]:
    """(code, sentence) when `want` will not do as the name of sheet `tab` (the estimate pages' own
    rules: 31 characters at most, none of ! : \\ / ? * [ ] ", not another sheet's name, any case),
    else None. The name the sheet already has always does."""
    if want.lower() == (names.get(tab) or "").lower():
        return None
    if len(want) > SHEET_NAME_MAX:
        return "invalid_label", "A sheet name can have %d characters at most." % SHEET_NAME_MAX
    if _SHEET_NAME_BAD.search(want):
        return "invalid_label", 'A sheet name cannot have any of these: ! : \\ / ? * [ ] "'
    if any(t != tab and n.lower() == want.lower() for t, n in names.items()):
        return "label_taken", "“%s” is already the name of a sheet on this estimate." % want
    return None


def _renamed_sheet(parent: Dict[str, Any], tab: str, want: str) -> Dict[str, Any]:
    """The keys of `parent` that call sheet `tab` `want`, as new objects: the v2 section's `label`
    (the root's own `label`), or tab_labels[tab]; and the price snapshot's name of it
    (priced_tabs[].name), which the proposal's option lines print."""
    patch: Dict[str, Any] = {}
    if _is_v2(parent):
        pe = copy.deepcopy(parent["polish_estimate"])
        if tab == _V2_ROOT_TAB:
            pe["label"] = want
        else:
            pe["tabs"][tab] = dict(pe["tabs"][tab], label=want)
        patch["polish_estimate"] = pe
    else:
        labels = parent.get("tab_labels")
        patch["tab_labels"] = dict(labels if isinstance(labels, dict) else {}, **{tab: want})
    priced = parent.get("priced_tabs")
    if isinstance(priced, list) and any(isinstance(t, dict) and t.get("id") == tab for t in priced):
        patch["priced_tabs"] = [dict(t, name=want) if isinstance(t, dict) and t.get("id") == tab
                                else copy.deepcopy(t) for t in priced]
    return patch


# ── A NAME IS NOT A NEW ESTIMATE (review of the one-name change) ──────────────────────────────────
# estimate_digest hashes the sheets' names too (tab_labels, priced_tabs[].name, a v2 section's
# `label`), so a sheet renamed on the estimate, or from a proposal's tab, called every proposal of it
# "Estimate changed", Send all refused the never-built ones and Generate Files re-copied the estimate
# into sent ones, while each proposal's own copy (the option lines and workbook tab names its
# documents print) kept the old name. The digest's formula is NOT changed (every stored digest would
# then read as stale): instead a change of the estimate that is ONLY names is carried into each
# proposal that was up to date with it, which is given the new digest in the same write.
def _nameless_estimate(data: Dict[str, Any]) -> Dict[str, Any]:
    """What estimate_digest hashes, less the sheets' names: tab_labels, every priced_tabs `name`
    and, on a v2 model, the root's and each section's `label`. Only compared, never stored: it shares
    `data`'s values (no deep copy, which an estimate's every save would pay for) and changes none."""
    src = data or {}
    out = {k: src[k] for k in PROPOSAL_ESTIMATE_KEYS
           if k not in PROPOSAL_REFRESH_SKIPS and k in src}
    out.pop("tab_labels", None)
    if isinstance(out.get("priced_tabs"), list):
        out["priced_tabs"] = [{k: v for k, v in t.items() if k != "name"} if isinstance(t, dict)
                              else t for t in out["priced_tabs"]]
    if _is_v2(src):
        pe = {k: v for k, v in src["polish_estimate"].items() if k != "label"}
        if isinstance(pe.get("tabs"), dict):
            pe["tabs"] = {sid: ({k: v for k, v in sec.items() if k != "label"}
                                if isinstance(sec, dict) else sec)
                          for sid, sec in pe["tabs"].items()}
        out["polish_estimate"] = pe
    return out


def _named_as(child: Dict[str, Any], parent: Dict[str, Any]) -> Dict[str, Any]:
    """The keys of proposal `child` that name its sheets, as `parent` names them now: tab_labels,
    priced_tabs[].name and a v2 model's root and section labels; only those that differ, as new
    objects. Nothing else of them changes (a v2 child's kinds stay its own, _v2_child_model)."""
    patch: Dict[str, Any] = {}
    want = parent.get("tab_labels")
    if isinstance(want, dict) and child.get("tab_labels") != want:
        patch["tab_labels"] = copy.deepcopy(want)
    names = {t["id"]: t.get("name") for t in parent.get("priced_tabs") or []
             if isinstance(t, dict) and isinstance(t.get("id"), str)}
    priced = child.get("priced_tabs")
    if isinstance(priced, list):
        out = []
        for t in priced:
            t = copy.deepcopy(t)
            if isinstance(t, dict) and t.get("id") in names:
                if names[t["id"]] is None:
                    t.pop("name", None)
                else:
                    t["name"] = names[t["id"]]
            out.append(t)
        if out != priced:
            patch["priced_tabs"] = out
    if _is_v2(parent) and _is_v2(child):
        ppe, pe = parent["polish_estimate"], copy.deepcopy(child["polish_estimate"])

        def take(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
            if "label" in src:
                dst["label"] = copy.deepcopy(src["label"])
            else:
                dst.pop("label", None)
        take(pe, ppe)
        ptabs = ppe.get("tabs") if isinstance(ppe.get("tabs"), dict) else {}
        for sid, sec in (pe.get("tabs") or {}).items() if isinstance(pe.get("tabs"), dict) else ():
            if isinstance(sec, dict) and isinstance(ptabs.get(sid), dict):
                take(sec, ptabs[sid])
        if pe != child["polish_estimate"]:
            patch["polish_estimate"] = pe
    return patch


def carry_sheet_names(parent_id: str, before: Dict[str, Any], after: Dict[str, Any]
                      ) -> Dict[str, Dict[str, Any]]:
    """WHEN THE ESTIMATE `parent_id` CHANGED FROM `before` TO `after` ONLY IN ITS SHEETS' NAMES,
    take the names into every proposal of it that was up to date with `before` (its
    `estimate_digest` is `before`'s): its naming keys (_named_as) and the new digest in ONE write, so
    it never reads as "Estimate changed" for a name. `estimate_synced_at` moves too (the fence
    against a page holding the copy with the old names, StaleProposalWrite); `updated_at` does not
    (a name is no work on a proposal, and the publish's draft_version check reads it). A proposal
    already behind the estimate is left for Refresh, which copies the names with the rest; one saved
    meanwhile is left as it is (compare-and-set on its `updated_at`). No event: the name itself is
    logged by sync_proposal_labels.

    Returns {proposal id: the keys written}; {} when the change was more than names, or none."""
    old_d, new_d = estimate_digest(before), estimate_digest(after)
    if old_d == new_d or _nameless_estimate(before) != _nameless_estimate(after):
        return {}
    gid, _label = _scope_of(after)
    sb = get_client()
    out: Dict[str, Dict[str, Any]] = {}
    for m in proposal_children(parent_id, gid):
        row = load_draft(m["id"])
        data = (row or {}).get("data") or {}
        if not row or data.get("proposal_of") != parent_id or data.get("estimate_digest") != old_d:
            continue
        patch = _named_as(data, after)
        now = _now_iso()
        if now == data.get("estimate_synced_at"):
            now = _stamp_at(datetime.fromisoformat(now), 1)      # the fence must move (a coarse tick)
        patch["estimate_digest"] = new_d
        patch["estimate_synced_at"] = now
        q = sb.table("drafts").update({"data": dict(data, **patch)}).eq("id", m["id"])
        if row.get("updated_at"):
            q = q.eq("updated_at", row["updated_at"])
        if q.execute().data:
            out[m["id"]] = patch
    if out:
        _cache_clear()
    return out


def rename_proposal(draft_id: str, label: Any, actor: Optional[str] = None) -> Dict[str, Any]:
    """RENAME A PROPOSAL ON ITS TAB = RENAME ITS SHEET (the one-name rule above): the base sheet of
    `draft_id` (Base Bid 1 or a child) is renamed on the PARENT's estimate (tab_labels, or the v2
    section's label, and its priced_tabs name), and every proposal of it is then named after its
    sheet (sync_proposal_labels), so the tab, the estimate and the board say the same. A draft that
    is no proposal of an estimate with proposals (an RJ scope) is renamed as before (rename_scope),
    and so is Base Bid 1 when its base is two sheets priced together (no one sheet to name).

    The parent is written only if it has not been stored since it was read (its `updated_at`), and
    its `updated_at` is not bumped; it is stamped SHEET_NAMES_MARK, so a page still holding its copy
    from before cannot save the old name back (StaleSheetNamesWrite). Every proposal that was up to
    date with the estimate takes the new name into its own copy and stays up to date
    (carry_sheet_names): a name is no reason for "Estimate changed".

    Returns {group_id, label (this draft's name now), parent_id, sheet: {id, label}, parent_patch
    (the parent's keys as stored, the stamp included, for a page holding the parent), patches
    ({draft id: the keys written to it}, the parent's and every proposal's, so the page that asked
    takes its own), renamed: [{id, from, to}]}. RAISES ScopeError: not_found (404), not_grouped and
    invalid_label (400), label_taken, parent_gone, sheet_gone and parent_changed (409)."""
    row = load_draft(draft_id)
    if not row:
        raise ScopeError("not_found", "That project is not there any more.", 404)
    data = row.get("data") or {}
    gid, _old = _scope_of(data)
    if not gid:
        raise ScopeError("not_grouped", "This project is not split into scopes, so it has no "
                                        "scope name to change.")
    pid = data.get("proposal_of")
    if isinstance(pid, str) and pid and pid != draft_id:
        prow = load_draft(pid) if draft_is_active(pid) else None
        if not prow:
            raise ScopeError("parent_gone", "Base Bid 1's estimate is not there any more, so this "
                                            "proposal's sheet cannot be renamed.", 409)
    else:
        pid, prow = draft_id, row
        if _proposal_family(pid, data) is None:
            return rename_scope(draft_id, label, actor)
    parent = prow.get("data") or {}
    tab = data.get("base_tab_id")
    if pid == draft_id and not (isinstance(tab, str) and tab):
        return rename_scope(draft_id, label, actor)
    names = _sheet_names(parent)
    if not isinstance(tab, str) or tab not in names:
        raise ScopeError("sheet_gone", "This proposal's sheet is not on the estimate any more, so "
                                       "it has no sheet name to change. Press Refresh first.", 409)
    want = clean_scope_label(label)
    why = _sheet_name_problem(names, tab, want)
    if why:
        raise ScopeError(why[0], why[1], 409 if why[0] == "label_taken" else 400)
    patch: Dict[str, Any] = {}
    patches: Dict[str, Dict[str, Any]] = {}
    if want != names[tab]:
        before = parent
        patch = _renamed_sheet(parent, tab, want)
        stamp = _now_iso()
        if stamp == parent.get(SHEET_NAMES_MARK):
            stamp = _stamp_at(datetime.fromisoformat(stamp), 1)      # the fence must move
        patch[SHEET_NAMES_MARK] = stamp
        parent = dict(parent, **patch)
        q = get_client().table("drafts").update({"data": parent}).eq("id", pid)
        if prow.get("updated_at"):
            q = q.eq("updated_at", prow["updated_at"])
        if not q.execute().data:
            raise ScopeError("parent_changed", "Base Bid 1's estimate was saved again while this "
                                               "was renaming its sheet. Reload the page and try "
                                               "again.", 409)
        _cache_clear()
        patches[pid] = patch
        try:
            patches.update(carry_sheet_names(pid, before, parent))
        except Exception as exc:  # noqa: BLE001 — the sheet is renamed; Refresh copies the name
            _log.warning("rename of %s's sheet: the name was not carried into its proposals: %s",
                         pid, exc)
    names_now, changed = _sync_names(pid, parent, actor)
    return {"group_id": gid, "label": names_now.get(draft_id) or _scope_of(data)[1] or want,
            "parent_id": pid, "sheet": {"id": tab, "label": want}, "parent_patch": patch,
            "patches": patches, "renamed": changed}


def adopt_sheet_label(draft_id: str, actor: Optional[str] = None) -> Optional[str]:
    """THE NAME THE CUSTOMER READS, stored before a publish (Hanz, 2026-10-28; generalised
    2026-10-29). The portal reads the STORED label at a publish, so a proposal is given THE ONE NAME
    first: for a proposal of an estimate with proposals, every proposal of it is named after its
    sheet (sync_proposal_labels) whenever its stored name differs, a typed one included. Otherwise,
    a draft still stored as "Base Bid N" (_OLD_DEFAULT_LABEL) is named after its base sheet off the
    parent's estimate when it has one, a clash numbered (_free_label).

    Returns this draft's new label, or None when its own name did not change. Same posture as
    rename_scope: `updated_at` is not bumped (the publish's draft_version check reads it), and the
    event is scope_renamed. Never calls the portal: the publish that follows carries the name."""
    sb = get_client()
    cur = sb.table("drafts").select("id,data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return None
    data = dict(cur.data[0].get("data") or {})
    gid, old = _scope_of(data)
    if not gid:
        return None
    family_id, family = draft_id, data
    parent_id = data.get("proposal_of")
    if isinstance(parent_id, str) and parent_id and parent_id != draft_id:
        prow = sb.table("drafts").select("id,data").eq("id", parent_id).limit(1).execute()
        family_id, family = parent_id, ((prow.data[0].get("data") or data) if prow.data else None)
    if family is not None and _proposal_family(family_id, family) is not None:
        changed = _sync_names(family_id, family, actor)[1]
        return next((c["to"] for c in changed if c["id"] == draft_id), None)
    if not old or not _OLD_DEFAULT_LABEL.match(old):
        return None
    source = data if family is None else family
    sheet = proposal_sheet_label(source, data.get("base_tab_id"))
    if not sheet or sheet == old:
        return None
    taken = {m["label"].lower() for m in _group_rows(gid) if m["id"] != draft_id and m["label"]}
    want = _free_label(sheet, taken)
    if want.lower() in taken:
        return None
    data["scope_group"] = dict(data["scope_group"], label=want)
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    log_event(draft_id, actor, "scope_renamed", {"project_name": data.get("project_name"),
                                                 "id": draft_id, "group": gid,
                                                 "from": old, "to": want})
    _cache_clear()
    return want


def fan_out_proposals(parent_id: str, base_ids: List[Any], actor: Optional[str] = None,
                      sent: bool = False,
                      child_sent: Optional[Callable[[str], bool]] = None,
                      leave_out: Optional[List[Any]] = None) -> Dict[str, Any]:
    """CREATE MULTIPLE PROPOSALS: one child draft per base bid of `parent_id` after the first.

    `base_ids` are the ticked base sheets in Base Bid order; `base_ids[0]` must be the parent's own
    base (it stays Base Bid 1's proposal). IDEMPOTENT: a child already made for a sheet is kept as it
    is (`created: false`), so pressing the button twice makes nothing twice. RECONCILED FIRST
    (_plan_reconcile): a child out of step with the ticked sheets (a base swap left it on Base Bid 1's
    sheet, or its sheet is no base bid any more) that the customer does not have (`child_sent`, the
    route's portal check; the store's revisions without one) takes a ticked sheet with no child
    instead of a new child being made for it (`created: false`, `moved_from`); one that cannot move
    is reported in `out_of_step` and left as it is. Children are written FIRST and taken back when
    anything after fails (_undo_split_children; a moved one gets its old blob back); the parent last:
    it joins a group (named after its base sheet when unnamed, still the old "Base Bid N" default, or,
    on a parent the customer does not have, the name of a sheet that is no longer its base; every new
    or moved child is named after ITS sheet, proposal_sheet_label, unless a person named it), records
    `base_tab_ids` and the base the children are matched against (PROPOSALS_BASE, _matched_base),
    and on a parent the customer does not have yet its children's sheets stop being
    options of it (`tab_opts[id].is_option` False). A `sent` parent's tab_opts and name are never
    edited. The parent's `updated_at` is NOT bumped.

    Returns {"group_id", "parent": {"id", "label"}, "children": [{"id", "label", "base_tab_id",
    "created"[, "moved_from"]}], "out_of_step": [{"id", "label", "code"[, "message"]}]}. RAISES
    ScopeError: not_found (404); too_few_bases, no_such_sheet, option_only_base, combined_base,
    base_order, not_fanned_from_child, invalid_scope_group (400); test_mix, label_taken,
    too_many_scopes (409); split_failed (503). `child_sent` may raise; nothing is written then.

    `leave_out`: base bids of `base_ids` that get NO NEW child this time, though they stay ticked
    (`base_tab_ids` records every one). 3 · Generate Files names those whose proposal is in the Trash
    (proposals_view `trashed`; Hanz, 2026-10-30: a deleted proposal is not made again). A live child
    already on such a sheet is kept, and one out of step may still move to it; Base Bid 1 is never
    left out. Each left out is listed in `left_out` and in no `children` entry."""
    skip = {str(t) for t in (leave_out or []) if isinstance(t, str) and t}
    sb = get_client()
    cur = sb.table("drafts").select("id,data").eq("id", parent_id).limit(1).execute()
    if not cur.data:
        raise ScopeError("not_found", "That project is not there any more.", 404)
    parent = copy.deepcopy(cur.data[0].get("data") or {})
    if parent.get("proposal_of"):
        raise ScopeError("not_fanned_from_child",
                         "This proposal was made from Base Bid 1's estimate. Base bids are picked "
                         "on Base Bid 1's tab.")
    existing = parent.get("scope_group")
    if existing is not None and scope_group_problem(existing):
        raise ScopeError("invalid_scope_group",
                         "This project's scope group cannot be read (%s)." % scope_group_problem(existing))
    ids = [str(x) for x in (base_ids or []) if isinstance(x, str) and x]
    if len(ids) < 2 or len(set(ids)) != len(ids) or len(ids) != len(base_ids or []):
        raise ScopeError("too_few_bases", "Tick two base bids or more, each its own sheet, to make "
                                          "several proposals.")
    priced = _priced_tabs(parent)
    v2 = _is_v2(parent)
    only = _V2_OPTION_ONLY_ROLES if v2 else _V1_OPTION_ONLY_ROLES
    for tab in ids:
        if tab not in priced:
            raise ScopeError("no_such_sheet", "The estimate has no priced sheet “%s”. Reload the "
                                              "page and try again." % tab)
        if str(priced[tab].get("role") or "").lower() in only:
            raise ScopeError("option_only_base", "“%s” is an option on a bid and never a base bid "
                                                 "of its own." % (priced[tab].get("name") or tab))
    base = parent.get("base_tab_id")
    if not base:
        if v2 or str(parent.get("work_type") or "").lower() == "combo":
            raise ScopeError("combined_base", "The base bid is an Epoxy and a Polish sheet priced "
                                              "together. Make one sheet the base first.")
        raise ScopeError("base_order", "Base Bid 1 must be this proposal's own base sheet. Reload "
                                       "the page and try again.")
    if ids[0] != base:
        raise ScopeError("base_order", "Base Bid 1 must be this proposal's own base sheet. Reload "
                                       "the page and try again.")
    copies = {tab: _proposal_copy(parent, tab, refresh=False) for tab in ids[1:]}

    gid = existing["id"] if isinstance(existing, dict) else uuid.uuid4().hex
    if isinstance(existing, dict):
        mixed = scope_test_mix(parent_id, parent, gid)
        if mixed:
            raise ScopeError("test_mix", mixed, 409)
    kids = _proposal_rows(parent_id, gid) if isinstance(existing, dict) else []
    rec = _plan_reconcile(parent, kids, _wanted_sheets(parent, ids), child_sent or _local_sent)
    kept = {c["data"]["base_tab_id"]: c for c in rec["keep"]}
    moved = {tab: c for c, tab in rec["moves"]}
    members = [m for m in (_group_rows(gid) if isinstance(existing, dict) else [])
               if m["id"] != parent_id]
    skip.discard(ids[0])
    new_tabs = [t for t in ids[1:] if t not in kept and t not in moved and t not in skip]
    if len(members) + len(new_tabs) + 1 > MAX_SCOPES:
        raise ScopeError("too_many_scopes",
                         "A project can be split into %d proposals at most." % MAX_SCOPES, 409)
    # A moved child named by the sheet rule takes its new sheet's name, so its old one is free.
    renamed = {c["id"] for c in moved.values() if _is_sheet_label(c["label"], parent)}
    taken = {m["label"].lower() for m in members if m["label"] and m["id"] not in renamed}
    # NAMED BY SHEET (Hanz, 2026-10-27): each proposal is called what its base sheet is called on the
    # estimate, so the tabs, the board and the customer's portal say "Breakroom", not "Base Bid 2".
    # A parent keeps a name a person gave it; an unset one, or the old "Base Bid N" default, becomes
    # its sheet's, and so does (when the customer does not have it) the name of a sheet that is no
    # longer its base. Two sheets of one name are told apart by _free_label ("Room", "Room 2").
    parent_label = (existing or {}).get("label")
    psheet = proposal_sheet_label(parent, base)
    if not parent_label or _OLD_DEFAULT_LABEL.match(parent_label) or (
            not sent and _is_sheet_label(parent_label, parent)
            and parent_label.lower() != (psheet or "").lower()):
        parent_label = _free_label(psheet or "Base Bid 1", taken)
    if parent_label.lower() in taken:
        raise ScopeError("label_taken",
                         "“%s” is already the name of a scope of this project." % parent_label, 409)
    taken.add(parent_label.lower())
    plan: List[Tuple[str, str]] = []
    moves: List[Tuple[Dict[str, Any], str, str]] = []
    for pos, tab in enumerate(ids[1:], start=2):
        if tab in kept or (tab in skip and tab not in moved):
            continue
        if tab in moved and moved[tab]["id"] not in renamed:
            moves.append((moved[tab], tab, moved[tab]["label"]))
            continue
        lab = _free_label(proposal_sheet_label(parent, tab) or "Base Bid %d" % pos, taken)
        if lab.lower() in taken:
            raise ScopeError("label_taken",
                             "“%s” is already the name of a scope of this project." % lab, 409)
        taken.add(lab.lower())
        if tab in moved:
            moves.append((moved[tab], tab, lab))
        else:
            plan.append((tab, lab))

    now = datetime.now(timezone.utc)
    digest = estimate_digest(parent)
    signer = _parent_signer(parent)
    made: List[Dict[str, Any]] = []
    in_flight: List[str] = []
    shifted: List[Dict[str, Any]] = []
    try:
        for i, (tab, lab) in enumerate(plan, start=1):
            cid = str(uuid.uuid4())
            d = copies[tab]
            d["tab_opts"] = {}
            d["scope_group"] = {"id": gid, "label": lab}
            d["proposal_of"] = parent_id
            d["estimate_digest"] = digest
            d["estimate_synced_at"] = now.isoformat()
            # Its own words start empty (PROPOSAL_NARRATIVE_KEYS), but its texture starts as ITS sheet's.
            _seed_texture(d, _v2_texture(parent, tab))
            # And it is signed by whoever signs Base Bid 1 (_parent_signer).
            d.update(signer)
            stamp = _stamp_at(now, i)
            in_flight[:] = [cid]
            sb.table("drafts").insert({"id": cid, "data": d, "owner_email": actor,
                                       "created_at": stamp, "updated_at": stamp}).execute()
            in_flight[:] = []
            log_event(cid, actor, "created", _summary_detail(d))
            made.append({"id": cid, "label": lab, "base_tab_id": tab, "created": True})
        for c, tab, lab in moves:
            _move_child(sb, parent, c, tab, lab, digest, actor, parent_id)
            shifted.append(c)
        rewritten = copy.deepcopy(parent)
        rewritten["scope_group"] = {"id": gid, "label": parent_label}
        rewritten["base_tab_ids"] = list(ids)
        matched = _matched_base(parent, kids, {s["id"] for s in rec["stuck"]})
        if matched is not None:
            rewritten[PROPOSALS_BASE] = matched
        if not sent and isinstance(rewritten.get("tab_opts"), dict):
            for tab in ids[1:]:
                entry = rewritten["tab_opts"].get(tab)
                if isinstance(entry, dict) and entry.get("is_option"):
                    rewritten["tab_opts"][tab] = dict(entry, is_option=False)
        sb.table("drafts").update({"data": rewritten}).eq("id", parent_id).execute()
    except Exception as exc:  # noqa: BLE001 — re-raised as a named refusal once cleaned up
        _undo_split_children(sb, [m["id"] for m in made] + in_flight)
        _undo_moves(sb, shifted)
        raise ScopeError("split_failed", "No proposals were made: the database did not take every "
                                         "part of it, and the parts that were made have been "
                                         "removed. Try again in a minute.", 503) from exc
    log_event(parent_id, actor, "proposals_created",
              {"project_name": parent.get("project_name"), "id": parent_id, "group": gid,
               "base_tab_ids": list(ids), "ids": [m["id"] for m in made],
               "moved": [c["id"] for c, _t, _l in moves]})
    _cache_clear()
    by_tab = {m["base_tab_id"]: m for m in made}
    by_move = {tab: (c, lab) for c, tab, lab in moves}
    children = []
    for tab in ids[1:]:
        if tab in kept:
            children.append({"id": kept[tab]["id"], "label": kept[tab]["label"], "base_tab_id": tab,
                             "created": False})
        elif tab in by_move:
            c, lab = by_move[tab]
            children.append({"id": c["id"], "label": lab, "base_tab_id": tab, "created": False,
                             "moved_from": c["data"].get("base_tab_id")})
        elif tab in by_tab:
            children.append(by_tab[tab])
    return {"group_id": gid, "parent": {"id": parent_id, "label": parent_label},
            "children": children, "out_of_step": rec["stuck"],
            "left_out": [t for t in ids[1:] if t in skip and t not in kept and t not in by_move]}


def _move_child(sb: Any, parent: Dict[str, Any], c: Dict[str, Any], tab: str, label: str,
                digest: str, actor: Optional[str], parent_id: str) -> Dict[str, Any]:
    """Write child `c` (a _proposal_rows entry) as the proposal of sheet `tab` (_recopied), named
    `label`: its wording, link and portal identity stay, its `updated_at` is bumped (its document
    must be rebuilt), and its new base is never one of its own options. Its price lines follow the
    new base as a base pick's do (_rebase_price_overrides, on a copy: `c["data"]` is what a failed
    press puts back), read against the figures of the sheets it was priced from and of the estimate
    now. Returns the stored blob. RAISES what _recopied and the write raise."""
    out = _recopied(parent, c["data"], tab, digest)
    pov = out.get("price_overrides")
    if isinstance(pov, dict):
        pov = copy.deepcopy(pov)
        tabs: List[Any] = []
        for src in (c["data"], parent):
            if isinstance(src.get("priced_tabs"), list):
                tabs.extend(src["priced_tabs"])
        if _rebase_price_overrides(pov, c["data"].get("base_tab_id"), tab, tabs,
                                   c["data"].get("work_type")):
            out["price_overrides"] = pov
    opts = out.get("tab_opts")
    if isinstance(opts, dict) and isinstance(opts.get(tab), dict) and opts[tab].get("is_option"):
        out["tab_opts"] = dict(opts, **{tab: dict(opts[tab], is_option=False)})
    if isinstance(out.get("scope_group"), dict) and out["scope_group"].get("label") != label:
        out["scope_group"] = dict(out["scope_group"], label=label)
    now = out["estimate_synced_at"]
    sb.table("drafts").update({"data": out, "updated_at": now}).eq("id", c["id"]).execute()
    log_event(c["id"], actor, "proposal_moved",
              {"project_name": out.get("project_name"), "id": c["id"], "from": parent_id,
               "from_sheet": c["data"].get("base_tab_id"), "to_sheet": tab})
    return out


def _undo_moves(sb: Any, rows: List[Dict[str, Any]]) -> None:
    """Put back the blob and `updated_at` of every child a failed press had moved (_move_child).
    Never raises (the caller is already reporting a failure)."""
    for c in rows:
        try:
            sb.table("drafts").update({"data": c["data"], "updated_at": c.get("updated_at")}) \
                .eq("id", c["id"]).execute()
        except Exception:  # noqa: BLE001 — nothing more can be done from here
            pass
    _cache_clear()


def _resolve_parent(draft_id: str) -> Optional[Dict[str, Any]]:
    """The stored row of the draft whose estimate `draft_id` is a proposal of: its parent for a
    child (when the parent is still there), else the draft itself. None when `draft_id` is gone."""
    row = load_draft(draft_id)
    if not row:
        return None
    pid = (row.get("data") or {}).get("proposal_of")
    if isinstance(pid, str) and pid and pid != draft_id and draft_is_active(pid):
        parent = load_draft(pid)
        if parent:
            return parent
    return row


def refresh_proposals(draft_id: str, actor: Optional[str] = None,
                      is_sent: Optional[Callable[[str], bool]] = None) -> Dict[str, Any]:
    """CATCH EVERY PROPOSAL UP WITH THE ESTIMATE ("Estimate changed" -> Refresh). `draft_id` is the
    parent or any child of it.

    Per child: its estimate and money (PROPOSAL_ESTIMATE_KEYS less PROPOSAL_REFRESH_SKIPS,
    PROPOSAL_MONEY_KEYS, PROPOSAL_BASE_KEYS) are replaced by a fresh copy of the parent's, everything
    else (its words and option picks, PROPOSAL_NARRATIVE_KEYS, its group, its server keys) is kept,
    the digest and `estimate_synced_at` are stamped, and its `updated_at` IS bumped: its document
    must be rebuilt, and a Files page that checked the old copy is refused (_stored_since). A child
    whose base sheet is no longer priced is skipped (`sheet_gone`).

    RECONCILED FIRST (_plan_reconcile, the parent's stored base bids): a child OUT OF STEP with them
    (a base swap left it on Base Bid 1's sheet, or its sheet is no base bid any more) that the
    customer does not have (`is_sent`, the route's portal check; the store's revisions without one)
    is MOVED to a base bid with no proposal, copied afresh as that sheet's and, unless a person named
    it, named after it (`moved`). One the customer has is never moved (`skipped`, code `sent`, with
    the sentence saying so); one with no free base bid is left as it is (`out_of_step`), never
    deleted. A moved child's price lines follow its new base (_move_child). When a child moved, a
    parent the customer does not have whose name is still another sheet's takes its own sheet's
    name, and the parent records the base its proposals are matched against now when that changed
    (PROPOSALS_BASE, _matched_base: the old one stays while a child is still out of step on Base Bid
    1's sheet); its `updated_at` is never bumped, and nothing else of it is touched.

    Returns {"parent_id", "estimate_digest", "refreshed": [ids], "skipped": [{"id", "label", "code"
    [, "message"]}], "moved": [{"id", "label", "from", "to"}]}. RAISES ScopeError not_found (404);
    `is_sent` may raise, and nothing is written then."""
    prow = _resolve_parent(draft_id)
    if prow is None:
        raise ScopeError("not_found", "That project is not there any more.", 404)
    parent_id, parent = prow["id"], prow.get("data") or {}
    gid, plabel = _scope_of(parent)
    digest = estimate_digest(parent)
    priced = _priced_tabs(parent)
    replaced = _REFRESH_REPLACED
    sb = get_client()
    refreshed: List[str] = []
    skipped: List[Dict[str, Any]] = []
    moved_out: List[Dict[str, Any]] = []
    sent = is_sent or _local_sent
    kids = _proposal_rows(parent_id, gid)
    rec = _plan_reconcile(parent, kids, _wanted_sheets(parent), sent)
    # Every name is settled, and every portal question asked, before anything is written.
    moves: List[Tuple[Dict[str, Any], str, str]] = []
    new_plabel: Optional[str] = None
    if rec["moves"]:
        renamed = {c["id"] for c, _t in rec["moves"] if _is_sheet_label(c["label"], parent)}
        taken = {m["label"].lower() for m in _group_rows(gid)
                 if m["label"] and m["id"] not in renamed and m["id"] != parent_id}
        psheet = proposal_sheet_label(parent, parent.get("base_tab_id"))
        if plabel and psheet and plabel.lower() != psheet.lower() \
                and _is_sheet_label(plabel, parent) and not sent(parent_id):
            new_plabel = _free_label(psheet, taken)
        taken.add((new_plabel or plabel or "").lower())
        for c, tab in rec["moves"]:
            lab = c["label"]
            if c["id"] in renamed:
                lab = _free_label(proposal_sheet_label(parent, tab) or lab or tab, taken)
            taken.add(lab.lower())
            moves.append((c, tab, lab))
    left = {s["id"] for s in rec["stuck"]}
    for c, tab, lab in moves:
        try:
            _move_child(sb, parent, c, tab, lab, digest, actor, parent_id)
        except ScopeError as exc:
            skipped.append({"id": c["id"], "label": c["label"], "code": exc.code})
            left.add(c["id"])
            continue
        refreshed.append(c["id"])
        moved_out.append({"id": c["id"], "label": lab, "from": c["data"].get("base_tab_id"),
                          "to": tab})
    # The parent's own keys this press settles: its sheet's name (only when a child moved) and the
    # base its proposals are matched against now (PROPOSALS_BASE, only when it changed).
    pkeys: Dict[str, Any] = {}
    if new_plabel and moved_out:
        pkeys["scope_group"] = dict(parent["scope_group"], label=new_plabel)
    matched = _matched_base(parent, kids, left) if kids else None
    if matched is not None and matched != parent.get(PROPOSALS_BASE):
        pkeys[PROPOSALS_BASE] = matched
    if pkeys:
        sb.table("drafts").update({"data": dict(parent, **pkeys)}).eq("id", parent_id).execute()
    skipped.extend(rec["stuck"])
    for c in rec["keep"]:
        data = c["data"]
        tab = data.get("base_tab_id")
        if not isinstance(tab, str) or tab not in priced:
            skipped.append({"id": c["id"], "label": c["label"], "code": "sheet_gone"})
            continue
        try:
            fresh = _proposal_copy(parent, tab, refresh=True)
        except ScopeError as exc:
            skipped.append({"id": c["id"], "label": c["label"], "code": exc.code})
            continue
        out = {k: v for k, v in data.items() if k not in replaced}
        out.update(fresh)
        # The sheet's texture follows the estimate until one is picked on this proposal's own step.
        _seed_texture(out, _v2_texture(parent, tab))
        now = _now_iso()
        if now == data.get("estimate_synced_at"):
            # The stamp is the fence against a page holding the copy before this one
            # (StaleProposalWrite), so it must move even when the clock has not (a coarse tick).
            now = _stamp_at(datetime.fromisoformat(now), 1)
        out["estimate_digest"] = digest
        out["estimate_synced_at"] = now
        sb.table("drafts").update({"data": out, "updated_at": now}).eq("id", c["id"]).execute()
        log_event(c["id"], actor, "proposal_refreshed",
                  {"project_name": out.get("project_name"), "id": c["id"], "from": parent_id})
        refreshed.append(c["id"])
    _cache_clear()
    return {"parent_id": parent_id, "estimate_digest": digest, "refreshed": refreshed,
            "skipped": skipped, "moved": moved_out}


def _document_total(data: Dict[str, Any]) -> Optional[str]:
    """The Total a proposal's built document prints: its saved proposal_payload's
    `values.total_formatted`, as written ("$15,000.50"), the figure the Files page shows for the
    proposal it is on (done.js paintLumpSum). None when nothing was built or it holds no digit."""
    pp = (data or {}).get("proposal_payload")
    values = pp.get("values") if isinstance(pp, dict) else None
    total = values.get("total_formatted") if isinstance(values, dict) else None
    if not isinstance(total, str) or not re.search(r"\d", total):
        return None
    return total.strip()


def proposals_view(draft_id: str) -> Optional[Dict[str, Any]]:
    """The proposal page's tab strip: the parent first, then its children in the parent's
    `base_tab_ids` order, each {id, label, display_label, sheet_label, lump_sum, index, is_parent,
    base_tab_id, stale, out_of_step, estimate_synced_at}; `stale` is a child whose digest is not the
    parent's current one; `out_of_step` is None, or why a child prices no base bid of its own
    (_out_of_step: same_as_base, duplicate, not_base, sheet_gone). `label` is the stored scope name;
    `display_label` is what the strip shows: THE ONE NAME (proposal_names: its base sheet's name on
    the parent's estimate, a clash numbered), which sync_proposal_labels stores on the next save, so
    the strip never waits for one. `sheet_label` is the sheet's own name. `lump_sum` is that
    proposal's own proposal_lump_sum (a number, or None when it has none yet). `document_total` is
    the Total its built document prints (_document_total), None before it is built. `draft_id` is the
    parent or any child of it. None when it is gone.

    Returns {"parent_id", "group_id", "estimate_digest", "members", "group_others"}; a draft with no
    children answers its own row alone. `group_others` is the rest of its scope group
    (_group_others), [] for a draft in none."""
    prow = _resolve_parent(draft_id)
    if prow is None:
        return None
    parent_id, parent = prow["id"], prow.get("data") or {}
    gid, plabel = _scope_of(parent)
    digest = estimate_digest(parent)
    rows = _group_rows(gid) if gid and not parent.get("proposal_of") else []
    kids = _proposal_rows(parent_id, gid, rows) if not parent.get("proposal_of") else []
    # Read oldest first, before the strip's order: the oldest child on a sheet is the one that keeps it.
    why = _out_of_step(parent, kids, _wanted_sheets(parent))
    rank = _strip_rank(parent)
    kids.sort(key=lambda c: rank(c["data"].get("base_tab_id"), c.get("created_at")))
    fam = _proposal_family(parent_id, parent, rows) if kids else None
    names = proposal_names(parent, fam[1], fam[2]) if fam else {}

    psheet = proposal_sheet_label(parent, parent.get("base_tab_id"))
    pstored = plabel or ("Base Bid 1" if kids else "")
    members = [{"id": parent_id, "label": pstored, "index": 1,
                "display_label": names.get(parent_id) or pstored,
                "sheet_label": psheet, "lump_sum": _money_or_none(parent.get("proposal_lump_sum")),
                "document_total": _document_total(parent),
                "is_parent": True, "base_tab_id": parent.get("base_tab_id"), "stale": False,
                "out_of_step": None, "estimate_synced_at": None}]
    for i, c in enumerate(kids, start=2):
        tab = c["data"].get("base_tab_id")
        sheet = proposal_sheet_label(parent, tab)
        members.append({"id": c["id"], "label": c["label"], "index": i,
                        "display_label": names.get(c["id"]) or _shown_label(c["label"], sheet),
                        "sheet_label": sheet,
                        "lump_sum": _money_or_none(c["data"].get("proposal_lump_sum")),
                        "document_total": _document_total(c["data"]),
                        "is_parent": False, "base_tab_id": tab,
                        "stale": c["data"].get("estimate_digest") != digest,
                        # OUT OF STEP: this proposal does not price a base bid of its own (a base swap
                        # left it on Base Bid 1's sheet, or its sheet is an Option or Off now). The
                        # strip says so and Refresh moves it (refresh_proposals).
                        "out_of_step": why.get(c["id"]),
                        "estimate_synced_at": c["data"].get("estimate_synced_at")})
    return {"parent_id": parent_id, "group_id": gid, "estimate_digest": digest, "members": members,
            "group_others": _group_others(rows, {m["id"] for m in members}),
            "trashed": _trashed_proposals(parent_id, parent, members)}


def _trashed_proposals(parent_id: str, parent: Dict[str, Any],
                       members: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The base bids of `parent` whose proposal is IN THE TRASH (a draft with deleted_at set and
    proposal_of `parent_id`) and that no live proposal prices, each {id, base_tab_id, sheet_label},
    in Base Bid order. 3 · Generate Files makes a base bid's missing proposal (fan_out_proposals),
    except these: a proposal somebody deleted is not made again (Hanz, 2026-10-30). Read only when
    the parent has a base bid to make one for, as a small projection; [] when it has none, or when
    the Trash cannot be read (logged)."""
    wanted = _wanted_sheets(parent) or []
    live = {m.get("base_tab_id") for m in members}
    open_tabs = [t for t in wanted if t not in live]
    if not open_tabs or parent.get("proposal_of"):
        return []
    try:
        res = (get_client().table("drafts")
               .select("id,deleted_at,proposal_of:data->>proposal_of,base_tab_id:data->>base_tab_id")
               .not_.is_("deleted_at", "null").execute())
    except Exception as exc:  # noqa: BLE001 — the strip still answers; step 3 then asks as before
        _log.warning("the Trash could not be read for draft %s: %s", _log_safe(parent_id), type(exc).__name__)
        return []
    binned: Dict[str, str] = {}
    for r in res.data or []:
        blob = r.get("data") or {}
        of = r["proposal_of"] if "proposal_of" in r else blob.get("proposal_of")
        tab = r["base_tab_id"] if "base_tab_id" in r else blob.get("base_tab_id")
        if of == parent_id and tab in open_tabs and tab not in binned and r.get("id"):
            binned[tab] = str(r["id"])
    return [{"id": binned[t], "base_tab_id": t, "sheet_label": proposal_sheet_label(parent, t) or t}
            for t in open_tabs if t in binned]


def _group_others(rows: List[Dict[str, Any]], mine: set) -> List[Dict[str, Any]]:
    """The scope group's LIVE members that are not in this strip (`mine`), oldest first: the other
    scopes of a project split into scopes (#711), and the proposals made from THEIR estimates. "Send
    all proposals in one email" sends every live member (main.py _send_all_publish reads the same
    _group_rows), so the Files page lists and names these too, never a smaller set than it sends.
    Each is {id, label, lump_sum, document_total}; `label` is the name the press says
    (main.py _send_all_label). Only these are loaded, so a strip with none costs nothing."""
    out = []
    for m in rows or []:
        if m["id"] in mine:
            continue
        row = load_draft(m["id"])
        data = (row or {}).get("data") or {}
        if not row:
            continue
        stored = m.get("label") or ""
        out.append({"id": m["id"],
                    "label": _shown_label(stored, proposal_sheet_label(data, data.get("base_tab_id")))
                    or "A proposal",
                    "lump_sum": _money_or_none(data.get("proposal_lump_sum")),
                    "document_total": _document_total(data)})
    return out


# ── copy a project (Hanz, 2026-10-29) ────────────────────────────────────────────────────────────
# "In the pipeline, both we should be able to copy a project. For example, we want to copy the
# Multiple Proposals Project but there is no way. When we copy a project, the copied project should
# live under Created but not sent."
#
# A COPY IS THE JOB WITHOUT ITS SEND HISTORY. It keeps the customer, the intake, the estimate and
# every proposal's own wording (the blob, deep-copied), and gets a new id for everything. What it
# drops is what happened to the ORIGINAL after it was priced: the files built and filed (the board's
# has_files reads generate_result), the outcome marks, the hand-off paperwork of a won job, the
# board's own marks on the original's card, and the fences recording the original's splits and
# renames. The portal row, its link, the follow-ups and the revisions live in other tables keyed by
# the original's id, so a new id leaves every one of them behind.
COPY_SUFFIX = " (copy)"
COPY_DROPS = (
    # the files built for a send, filed to Dropbox, and the message it went with
    "generate_result", "generated_lump_sum", "dropbox_result", "portal_message",
    # the outcome marks (set_won, set_close_lost, set_on_hold, set_handed_off)
    "won", "closed_lost", "on_hold", "handed_off",
    # a won job's hand-off paperwork: its job number and its Project Info Sheet
    "job_number", "info_cell_values", "info_tab_structs", "info_template_version",
    # the board's marks on the original's card (a copy is active, unstarred, and copied_from is set
    # afresh below)
    "archived", "starred", "copied_from",
    # the original's own history: a split's fence and record, a rename's fence
    SPLIT_MARK, SPLIT_HAD_FILES, "split_from", "split_failed", SHEET_NAMES_MARK,
)
# The keys holding another DRAFT'S id, which a copy points at the copy of that draft instead.
_COPY_PROPOSAL_KEYS = ("proposal_of", "estimate_digest", "estimate_synced_at")


def _copy_name(name: Any) -> str:
    base = re.sub(r"\s+", " ", str(name or "")).strip() or "Untitled project"
    return base + COPY_SUFFIX


def _renamed_copy(src: Dict[str, Any], new_name: str) -> Dict[str, Any]:
    """`src` less COPY_DROPS, deep-copied (nothing shared with `src`), named `new_name` wherever it
    carried its old name: the project, the job-name alias and the composed document's values."""
    old = src.get("project_name")
    out = {k: copy.deepcopy(v) for k, v in src.items() if k not in COPY_DROPS}
    out["project_name"] = new_name
    if old is not None and out.get("job_name") == old:
        out["job_name"] = new_name
    values = (out.get("proposal_payload") or {}).get("values") if isinstance(
        out.get("proposal_payload"), dict) else None
    if isinstance(values, dict):
        for k in ("project_name", "job_name"):
            if old is not None and values.get(k) == old:
                values[k] = new_name
    return out


def _copy_left_closed(blob: Dict[str, Any]) -> Optional[str]:
    """Why a proposal of a project is left out of its copy, or None: the board closed it lost or put
    it on hold (the draft-side marks, set_close_lost / set_on_hold, the two #748 keeps out of Send
    all)."""
    if blob.get("closed_lost"):
        return "closed_lost"
    if blob.get("on_hold"):
        return "on_hold"
    return None


def copy_project(draft_id: str, actor: Optional[str] = None,
                 closed_ids: Optional[Callable[[], Any]] = None) -> Dict[str, Any]:
    """COPY A PROJECT: a new, unsent draft of the same job, named "<project> (copy)", owned by
    `actor`, in the board's "Created but not sent" column straight away (main._not_sent_rows reads
    `copied_from`).

    A PROJECT OF SEVERAL PROPOSALS IS COPIED WHOLE, whichever of its cards was pressed: every LIVE
    member of its scope group (live_scope_members: not trashed, not archived, of the group's kind)
    becomes a member of ONE NEW group, in the same order. Create Multiple Proposals' children point at
    the copy of their parent (`proposal_of`), and a child that was up to date with its parent's
    estimate is up to date with the copy's (its `estimate_digest` is the copy's), so no copy says
    "Estimate changed"; one that was out of date stays out of date, since its numbers still differ.
    RJ's scope groups (#711, members with no `proposal_of`) are copied the same way, as one project.
    A draft that is in no live group (or is pressed while archived) is copied on its own.

    A PROPOSAL THE CUSTOMER DECLINED OR THAT IS PAUSED IS LEFT OUT (review of this branch,
    2026-10-30), unless it is the card that was pressed: one closed lost or on hold on the board
    (_copy_left_closed), or closed lost on the portal (`closed_ids`, called only when the project has
    more than one proposal, answers the ids the portal's pipeline calls closed_lost). The copy drops
    every outcome mark, so a declined scope copied along would come back as a live unsent proposal,
    and the copy's Send all would email the customer the proposal they already turned down: the
    thing #748 stops on the original. Pressing Copy ON the lost card copies it, since that is asking
    for it. A child whose parent was left out is copied as a proposal of its own (no `proposal_of`,
    as an RJ scope is): it keeps its own copy of the estimate and its sheet's name, and is never
    re-priced from an estimate the copy does not have.

    Kept: everything of the job (the blob less COPY_DROPS), `assigned_estimator` (the same job, so
    the same estimator chases it), `audience` (Direct stays Direct, GC stays GC), the kind (`is_test`
    is stored as the original's draft_is_test, so a Test project's copy is Test and a real one's is
    real whatever the new name looks like). Each proposal is named after its sheet (proposal_names).

    Every row is inserted FIRST-TO-LAST and taken back when one fails (_undo_split_children). Each
    copy gets ONE event, `copied`. Returns {"id" (the copy of `draft_id`), "ids" (every copy, in
    order), "project_name", "group_id", "from", "left_out" ([{"id", "label", "why"}] of the original's
    proposals not copied for being closed: closed_lost or on_hold)}. RAISES ScopeError not_found (404), copy_failed (503)."""
    sb = get_client()
    cur = sb.table("drafts").select("id,data,deleted_at").eq("id", draft_id).limit(1).execute()
    if not cur.data or cur.data[0].get("deleted_at"):
        raise ScopeError("not_found", "That project is not there any more.", 404)
    src = cur.data[0].get("data") or {}
    gid, _label = _scope_of(src)
    order = [draft_id]
    if gid:
        live = [m["id"] for m in _group_rows(gid)]
        if draft_id in live:
            order = live
        else:
            gid = None
    blobs: Dict[str, Dict[str, Any]] = {}
    for i in order:
        if i == draft_id:
            blobs[i] = src
            continue
        row = load_draft(i)
        if row:
            blobs[i] = row.get("data") or {}
    order = [i for i in order if i in blobs]
    # Declined or paused neighbours stay behind (see the docstring); the pressed card never does.
    portal_lost = set(closed_ids() or ()) if closed_ids and len(order) > 1 else set()
    left_out: List[Dict[str, Any]] = []
    for i in order:
        why = None if i == draft_id else (
            _copy_left_closed(blobs[i]) or ("closed_lost" if i in portal_lost else None))
        if why:
            left_out.append({"id": i, "why": why,
                             "label": str((blobs[i].get("scope_group") or {}).get("label") or "")})
    order = [i for i in order if i not in {x["id"] for x in left_out}]

    new_id = {i: str(uuid.uuid4()) for i in order}
    new_gid = uuid.uuid4().hex if gid else None
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    out: Dict[str, Dict[str, Any]] = {}
    fresh: set = set()
    for i in order:
        old = blobs[i]
        d = _renamed_copy(old, _copy_name(old.get("project_name")))
        d["is_test"] = draft_is_test(old)
        if gid:
            d["scope_group"] = dict(old["scope_group"], id=new_gid)
        else:
            d.pop("scope_group", None)
        parent = old.get("proposal_of")
        if gid and parent in new_id and parent != i:
            d["proposal_of"] = new_id[parent]
            # Up to date with its parent before, up to date with the copy of its parent now.
            # Its digest is set below, from the parent's FINAL copy; an out-of-date one keeps its own.
            if old.get("estimate_digest") == estimate_digest(blobs[parent]):
                fresh.add(i)
            d["estimate_synced_at"] = stamp
        else:
            for k in _COPY_PROPOSAL_KEYS:
                d.pop(k, None)
        if "__draft_id" in d:
            d["__draft_id"] = new_id[i]
        d["copied_from"] = {"id": i, "project_name": old.get("project_name") or "", "at": stamp,
                            "by": actor or ""}
        out[i] = d
    # The digests last, once every parent copy is final.
    for i in fresh:
        out[i]["estimate_digest"] = estimate_digest(out[blobs[i]["proposal_of"]])
    # THE ONE NAME (proposal_names): each proposal of an estimate is named after its base sheet.
    created = {i: _stamp_at(now, n) for n, i in enumerate(order)}
    if gid:
        for p in order:
            kids = [i for i in order if blobs[i].get("proposal_of") == p and i != p
                    and out[i].get("proposal_of") == new_id[p]]
            if not kids or out[p].get("proposal_of"):
                continue
            rank = _strip_rank(out[p])
            kids.sort(key=lambda i: rank(out[i].get("base_tab_id"), created[i]))
            fam = [p] + kids
            label = lambda i: str((out[i].get("scope_group") or {}).get("label") or "")  # noqa: E731
            members = [{"id": i, "label": label(i), "base_tab_id": out[i].get("base_tab_id")}
                       for i in fam]
            reserved = {label(i) for i in order if i not in fam and label(i)}
            for i, name in proposal_names(out[p], members, reserved).items():
                out[i]["scope_group"] = dict(out[i]["scope_group"], label=name)

    made: List[str] = []
    try:
        for i in order:
            # On the cleanup list BEFORE the insert, as split_draft does: an insert can commit and
            # lose its answer, and deleting an id that was never written is harmless.
            made.append(new_id[i])
            sb.table("drafts").insert({"id": new_id[i], "data": out[i], "owner_email": actor,
                                       "created_at": created[i], "updated_at": created[i]}).execute()
    except Exception as exc:  # noqa: BLE001 — re-raised as a named refusal once cleaned up
        _undo_split_children(sb, made)
        raise ScopeError("copy_failed", "Nothing was copied: the database did not take every part "
                                        "of it, and the parts that were made have been removed. "
                                        "Try again in a minute.", 503) from exc
    for i in order:
        log_event(new_id[i], actor, "copied",
                  {"project_name": out[i].get("project_name"), "id": new_id[i], "from": i,
                   "from_name": blobs[i].get("project_name") or ""})
    _cache_clear()
    return {"id": new_id[draft_id], "ids": [new_id[i] for i in order],
            "project_name": out[draft_id].get("project_name"), "group_id": new_gid,
            "from": draft_id, "left_out": left_out}


def list_drafts(limit: int = 300) -> List[Dict[str, Any]]:
    """Unified ACTIVE project list (all owners), newest-updated first."""
    return _list_summaries(trashed=False, limit=limit)


def list_trashed(limit: int = 300) -> List[Dict[str, Any]]:
    """Trashed (soft-deleted) projects, newest-trashed first — powers Trash."""
    return _list_summaries(trashed=True, limit=limit)


# ── in-memory list cache ──────────────────────────────────────────────
# list_drafts/list_trashed hit Supabase/PostgREST on EVERY call, and the Projects
# dashboard refetches on each load — that round-trip is the load delay the user
# feels. Cache the computed summaries in-process (TTLCache, same lib as the
# download-token cache) and clear on ANY write, so a save/archive/trash/restore
# shows up immediately while idle reloads come from memory. Prod runs a single
# uvicorn worker, so one cache is shared across requests; the TTL backstops any
# out-of-band change. Empty/failed reads are NOT cached (so a transient blip
# can't pin "no projects").
_LIST_CACHE: cachetools.TTLCache = cachetools.TTLCache(maxsize=8, ttl=60)


def _cache_clear() -> None:
    """Drop the cached project lists — called after every write."""
    _LIST_CACHE.clear()


def _list_summaries(trashed: bool, limit: int) -> List[Dict[str, Any]]:
    """Cached wrapper over _build_summaries (60 s TTL + clear-on-write)."""
    key = (trashed, limit)
    cached = _LIST_CACHE.get(key)
    if cached is not None:
        return cached
    out = _build_summaries(trashed, limit)
    if out:                                  # never cache an empty/failed read
        _LIST_CACHE[key] = out
    return out


def _sent_revisions(ids: List[str]) -> Dict[str, int]:
    """{project_id: highest revision_no} for the given projects, 0 when never sent.

    One extra query for the whole page rather than per card. Best-effort: the
    projects list must still render if draft_revisions is missing (a database that
    hasn't had the DDL applied yet) — the badge just won't appear."""
    if not ids:
        return {}
    try:
        res = (get_client().table("draft_revisions").select("project_id, revision_no")
               .in_("project_id", ids).execute())
    except Exception:  # noqa: BLE001 — table absent / PostgREST cache cold
        return {}
    out: Dict[str, int] = {}
    for r in res.data or []:
        pid, no = r.get("project_id"), int(r.get("revision_no") or 0)
        if pid and no > out.get(pid, 0):
            out[pid] = no
    return out


def _build_summaries(trashed: bool, limit: int) -> List[Dict[str, Any]]:
    """Shared list builder; `trashed` selects deleted vs active via deleted_at.

    Selects only the card fields (+ the small computed_bid object) via JSON
    extraction instead of the FULL state blob — the blob also holds every edited
    grid cell, so as projects accumulate the old `select=data` ballooned the
    payload. Falls back to the full read on any PostgREST quirk. If the
    deleted_at column doesn't exist yet (pre-migration), the active list degrades
    to unfiltered and the trash list returns []."""
    sb = get_client()
    order_col = "deleted_at" if trashed else "updated_at"

    def _filtered(q):
        # active = deleted_at IS NULL; trash = deleted_at IS NOT NULL
        return q.not_.is_("deleted_at", "null") if trashed else q.is_("deleted_at", "null")

    try:
        cols = ("id,owner_email,created_at,updated_at,deleted_at,"
                "project_name:data->>project_name,"
                "work_type:data->>work_type,"
                # Direct or GC, the New Project form's own radio. It decides which BOARD a project
                # is on (pipelines.pipeline_of): Direct Projects or General Contractor. Named here for
                # the reason `won_at` spells out below - this select names JSON paths, so a key it
                # does not name reaches no card, and every GC project would sit on the Direct board.
                "audience:data->>audience,"
                "deadline:data->>deadline,"
                "archived:data->>archived,"
                # Test/demo, as set by hand on the Projects page. Tri-state (see _tribool):
                # absent leaves the name heuristic in charge for legacy rows.
                "is_test:data->>is_test,"
                # Which step 2 this project was priced in. The beta polish calculator stamps
                # polish_estimate.version = 2, and the Projects page has to know before it
                # opens a card: resuming a beta bid on the live (spreadsheet) intake is the
                # bug this exists to stop. One scalar out of the object, not the object —
                # polish_estimate carries every area, material and crew line.
                "polish_beta:data->polish_estimate->>version,"
                # Who owns the follow-up. Persisted on the draft when staff send,
                # so the Projects list can say who is chasing each bid without
                # asking the portal for every row.
                "assigned_estimator:data->>assigned_estimator,"
                # Who the proposal was addressed to. The Active Projects board needs it for the
                # "Created but not sent" column, where there is no portal row to read it off.
                "contact_email:data->>contact_email,"
                # Whether Generate has ever run for this project. Selected as ONE SCALAR from
                # inside the blob rather than the blob itself: generate_result carries three
                # download URLs and a totals object, and this list is read 300 rows at a time on
                # every Projects page load. work_type is always present when the object is (see
                # GenerateOut), so its presence is the cheapest honest existence test.
                "has_files:data->generate_result->>work_type,"
                # The card's money. The base tab's TOTAL LUMP SUM as a scalar, plus the legacy
                # engine object for the drafts that predate it — see _bid_total for why the
                # order matters and what showing only the second one cost.
                "proposal_lump_sum:data->>proposal_lump_sum,"
                "computed_bid:data->computed_bid,"
                # Closed lost before it was ever sent — see set_close_lost.
                "closed_lost_reason:data->closed_lost->>reason,"
                "closed_lost_at:data->closed_lost->>at,"
                # …and the sentence somebody had to write to close it. Selected because it has to be
                # READABLE, not only stored: it is the tool's one required free-text field and the
                # reason for requiring it was that a reason on its own tells the next person nothing.
                # It reaches the DRAWER, never the card — see _not_sent_rows.
                "closed_lost_note:data->closed_lost->>note,"
                # On hold before it was ever sent — see set_on_hold. Named here for the reason
                # `won_at` spells out below: this projection selects named JSON paths, so a key
                # nobody names reaches no card, and the hold would appear to save and vanish.
                "on_hold_reason:data->on_hold->>reason,"
                "on_hold_until:data->on_hold->>until,"
                "on_hold_note:data->on_hold->>note,"
                # Marked won by hand — see set_won. Selected by NAME like every other field on this
                # projection, which is exactly why it has to be listed here: this path selects named
                # JSON paths rather than the blob, so a key that is not named reaches no card. The
                # fast path is the one that serves every real page load; the full-blob `_summary`
                # below only runs when PostgREST refuses this select.
                "won_at:data->won->>at,"
                # Handed to operations — see set_handed_off. Named for exactly the reason above,
                # and it is the field the Handed Off TAB routes on, so an unnamed key here does not
                # degrade the board, it empties a tab.
                "handed_off_at:data->handed_off->>at,"
                # The scope group this project is one proposal of (RJ, 2026-10-24: Breakroom, Lab
                # 1 and Lab 2 under one project name) and what this scope is called. Named for the
                # reason `won_at` gives above: a key this projection does not name reaches no
                # card, and the board would draw three unrelated projects with one name.
                "scope_group_id:data->scope_group->>id,"
                "scope_label:data->scope_group->>label,"
                # Whose base bid this proposal was made from (fan_out_proposals). Named for the
                # reason `won_at` gives: the board opens such a scope on its proposal page.
                "proposal_of:data->>proposal_of,"
                # A split cleared this project's files, which were on the board (SPLIT_HAD_FILES).
                "split_had_files:data->>split_had_files,"
                # Starred (set_starred) and copied (copy_project). Named for the reason `won_at`
                # gives: a key this projection does not name reaches no card, and the star would
                # appear to save and the copy would never reach "Created but not sent".
                "starred_at:data->starred->>at,"
                "copied_from:data->copied_from->>id")
        try:
            res = _filtered(sb.table("drafts").select(cols)) \
                .order(order_col, desc=True).limit(limit).execute()
        except Exception:  # deleted_at column missing (pre-migration)
            if trashed:
                return []
            res = sb.table("drafts").select(cols).order("updated_at", desc=True).limit(limit).execute()
        rows = res.data or []
        sent = _sent_revisions([r["id"] for r in rows])
        return [{
            "id": r["id"],
            "project_name": r.get("project_name") or "(untitled)",
            "total": _bid_total({"proposal_lump_sum": r.get("proposal_lump_sum"),
                                 "computed_bid": r.get("computed_bid"),
                                 # Already selected for the card's own beta badge; passed in so
                                 # the fast path resolves money in the same order as the slow one.
                                 "polish_beta": _polish_beta(r.get("polish_beta"))}),
            "work_type": r.get("work_type"),
            "audience": r.get("audience"),
            "deadline": r.get("deadline"),
            "archived": _truthy(r.get("archived")),
            "is_test": _tribool(r.get("is_test")),
            "polish_beta": _polish_beta(r.get("polish_beta")),
            "owner_email": r.get("owner_email"),
            "assigned_estimator": r.get("assigned_estimator"),
            "contact_email": r.get("contact_email"),
            "has_files": bool(r.get("has_files")),
            "closed_lost_reason": r.get("closed_lost_reason") or None,
            "closed_lost_at": r.get("closed_lost_at") or None,
            "closed_lost_note": r.get("closed_lost_note") or None,
            "on_hold_reason": r.get("on_hold_reason") or None,
            "on_hold_until": r.get("on_hold_until") or None,
            "on_hold_note": r.get("on_hold_note") or None,
            "won_at": r.get("won_at") or None,
            "handed_off_at": r.get("handed_off_at") or None,
            "scope_group_id": r.get("scope_group_id") or None,
            "scope_label": r.get("scope_label") or None,
            "proposal_of": r.get("proposal_of") or None,
            "split_had_files": _truthy(r.get("split_had_files")),
            "starred_at": r.get("starred_at") or None,
            "copied_from": r.get("copied_from") or None,
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "deleted_at": r.get("deleted_at"),
            # Which version the customer has, or 0 if this was never sent. Lets the
            # card say so, instead of every project looking like a fresh draft and
            # nobody knowing which ones are live with a customer.
            "sent_revision": sent.get(r["id"], 0),
        } for r in rows]
    except Exception:  # noqa: BLE001 — fall back to the full-blob read
        try:
            res = _filtered(
                sb.table("drafts").select("id,data,owner_email,created_at,updated_at,deleted_at")
            ).order(order_col, desc=True).limit(limit).execute()
        except Exception:
            if trashed:
                return []
            res = sb.table("drafts").select("id,data,owner_email,created_at,updated_at") \
                .order("updated_at", desc=True).limit(limit).execute()
        return [_summary(row) for row in (res.data or [])]


# ── events (history log) ──────────────────────────────────────────────
def log_event(project_id: Optional[str], actor_email: Optional[str],
              action: str, detail: Optional[Dict[str, Any]] = None) -> None:
    """Append an audit event (best-effort; never breaks the main flow)."""
    try:
        get_client().table("events").insert({
            "project_id": project_id,
            "actor_email": actor_email,
            "action": action,
            "detail": detail or {},
            "created_at": _now_iso(),
        }).execute()
    except Exception:  # noqa: BLE001 — logging must not break save/generate
        pass


# ── revisions ─────────────────────────────────────────────────────────
# A project keeps ONE id, one portal row, one token and one chat thread for its
# whole life. When staff send it to the customer we snapshot the entire `data`
# blob as revision N, so a changed estimate reuses the project instead of forcing
# a duplicate — and every version that was ever sent stays readable for basis and
# transparency. The customer's portal view is pinned to the snapshot they were
# actually sent, which also means editing a draft can no longer silently rewrite
# a proposal somebody has already received.
#
# The blob is 5-35 kB, so a full copy per send is cheaper than one PDF.

def create_revision(draft_id: str, data: Dict[str, Any],
                    created_by: Optional[str] = None) -> int:
    """Snapshot `data` as the next revision and return its number.

    Numbering is per project and gapless-by-intent (max + 1). A unique constraint
    on (project_id, revision_no) makes a concurrent double-send collide rather
    than silently share a number; we retry once, which is enough for two clicks."""
    sb = get_client()
    for attempt in range(2):
        prev = (sb.table("draft_revisions").select("revision_no")
                .eq("project_id", draft_id).order("revision_no", desc=True)
                .limit(1).execute())
        next_no = int((prev.data or [{}])[0].get("revision_no") or 0) + 1 + attempt
        try:
            sb.table("draft_revisions").insert({
                "project_id": draft_id, "revision_no": next_no,
                "data": data, "created_by": created_by, "created_at": _now_iso(),
            }).execute()
            return next_no
        except Exception:  # noqa: BLE001 — unique violation on a concurrent send
            if attempt:
                raise
    raise RuntimeError("could not allocate a revision number")


def list_revisions(draft_id: str) -> List[Dict[str, Any]]:
    """Every revision of a project, newest first — the Files-page history.

    Deliberately does NOT return the blobs: the list is a UI table, and shipping
    N × 35 kB to render four rows would be gratuitous. The total is derived the
    same way the projects list derives it, so the two always agree."""
    sb = get_client()
    res = (sb.table("draft_revisions").select("revision_no, created_by, created_at, data")
           .eq("project_id", draft_id).order("revision_no", desc=True).execute())
    out: List[Dict[str, Any]] = []
    for r in res.data or []:
        data = r.get("data") or {}
        out.append({
            "revision_no": r["revision_no"],
            "created_by": r.get("created_by"),
            "created_at": r.get("created_at"),
            "total": _bid_total(data),
            "project_name": data.get("project_name"),
            # Whether this snapshot can regenerate documents. A project sent
            # before the estimator ever hit Generate has no payload to replay.
            "has_documents": bool(data.get("proposal_payload")),
        })
    return out


def get_revision(draft_id: str, revision_no: int) -> Optional[Dict[str, Any]]:
    """One revision including its full `data` blob, or None."""
    sb = get_client()
    res = (sb.table("draft_revisions").select("*")
           .eq("project_id", draft_id).eq("revision_no", int(revision_no))
           .limit(1).execute())
    rows = res.data or []
    return rows[0] if rows else None


def delete_revision(draft_id: str, revision_no: int) -> None:
    """Remove a snapshot. Used to compensate when the publish call that the
    snapshot was taken FOR then fails — better a gap in the numbering than a
    revision the customer was never sent."""
    (get_client().table("draft_revisions").delete()
     .eq("project_id", draft_id).eq("revision_no", int(revision_no)).execute())


def latest_revision_no(draft_id: str) -> Optional[int]:
    sb = get_client()
    res = (sb.table("draft_revisions").select("revision_no")
           .eq("project_id", draft_id).order("revision_no", desc=True).limit(1).execute())
    rows = res.data or []
    return int(rows[0]["revision_no"]) if rows else None


# ── revision documents: the exact files a sent revision's customer was given ──
# A revision stores the INPUTS (above). This stores the OUTPUT: the .docx and the PDF rendered at
# send time, so the customer's copy of revision N never changes again whatever later code or
# template changes land. The portal still asks /api/admin/proposal-pdf for draft + revision; that
# route now answers from here when a row exists and re-renders only for revisions sent before this
# table did.
#
# BASE64 IN A TEXT COLUMN, NOT bytea. PostgREST carries bytea as a "\x…" hex string in JSON, so
# every write and read would double the bytes on the wire and need hand-rolled hex on both sides;
# base64 is a third larger, is plain JSON through supabase-py, the staging PostgREST and the test
# fake alike, and decodes with one call. The sha256 columns say which bytes are meant.
_REVISION_DOCUMENTS = "draft_revision_documents"


def store_revision_documents(draft_id: str, revision_no: int, *, payload_sha256: str,
                             docx: bytes, pdf: bytes, created_by: Optional[str] = None) -> None:
    """Keep the files revision `revision_no` was sent with. Replaces any row already there.

    A row can only pre-exist as an orphan: a failed rollback leaves one behind, and the next send
    reuses the revision number (numbering is max + 1). Deleted first so that orphan can never be
    served for the new revision — delete-then-insert rather than an upsert, because every store
    this module talks to supports both calls and not all of them take an `on_conflict`."""
    sb = get_client()
    (sb.table(_REVISION_DOCUMENTS).delete()
     .eq("project_id", draft_id).eq("revision_no", int(revision_no)).execute())
    sb.table(_REVISION_DOCUMENTS).insert({
        "project_id": draft_id, "revision_no": int(revision_no),
        "payload_sha256": payload_sha256,
        "docx_b64": base64.b64encode(docx).decode("ascii"),
        "docx_sha256": hashlib.sha256(docx).hexdigest(),
        "pdf_b64": base64.b64encode(pdf).decode("ascii"),
        "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        "created_by": created_by, "created_at": _now_iso(),
    }).execute()


def get_revision_documents(draft_id: str, revision_no: int) -> Optional[Dict[str, Any]]:
    """`{"docx": bytes, "pdf": bytes, "payload_sha256": str}` for a revision sent with stored
    files, None for one sent before they were stored. Raises when the store cannot be read: the
    caller decides what an unreadable table means."""
    res = (get_client().table(_REVISION_DOCUMENTS)
           .select("payload_sha256, docx_b64, pdf_b64")
           .eq("project_id", draft_id).eq("revision_no", int(revision_no))
           .limit(1).execute())
    rows = res.data or []
    if not rows:
        return None
    row = rows[0]
    return {"docx": base64.b64decode(row["docx_b64"]), "pdf": base64.b64decode(row["pdf_b64"]),
            "payload_sha256": row.get("payload_sha256")}


def delete_revision_documents(draft_id: str, revision_no: int) -> None:
    """Undo `store_revision_documents` — the partner of `delete_revision` when a send fails."""
    (get_client().table(_REVISION_DOCUMENTS).delete()
     .eq("project_id", draft_id).eq("revision_no", int(revision_no)).execute())


def list_events(limit: int = 100) -> List[Dict[str, Any]]:
    """Recent activity, newest first — powers the History view."""
    sb = get_client()
    res = sb.table("events").select("*").order("created_at", desc=True).limit(limit).execute()
    return res.data or []


# ── helpers: pull display fields out of the state blob ────────────────
def _truthy(v: Any) -> bool:
    """Coerce a `data->>archived` value (text "true"/"false"/null, or a real
    bool from the full-blob fallback) to a Python bool."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "t", "1", "yes")


def _tribool(v: Any) -> Optional[bool]:
    """Like `_truthy`, but keeps "nobody has said" separate from "said no".

    `data.is_test` has three meaningful states and the Projects page depends on all three:
    absent lets the name heuristic decide, `True` forces the Test tab, `False` forces the
    project back into Active even when its name looks like a test. Coercing absent to False
    would silently promote every legacy project to "confirmed real bid" and switch the
    heuristic off for the whole list."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "t", "1", "yes"):
        return True
    if s in ("false", "f", "0", "no"):
        return False
    return None                      # "null", "", or anything unrecognised = nobody has said


def _polish_beta(version: Any) -> bool:
    """Does `data.polish_estimate.version` say this project belongs to the beta calculator?

    ONE helper for BOTH read paths, because they see different types for the same value:
    PostgREST hands `data->polish_estimate->>version` back as TEXT (so the fast path in
    `_build_summaries` sees the string "2"), while `_summary` reads the parsed blob and sees the
    int 2. Two separate coercions would eventually disagree, and the disagreement would show up
    as "resuming this project from the Projects page lands on the wrong step 2, but only
    sometimes" — the fallback path only runs when PostgREST is already misbehaving.

    Absent/None is False on purpose: a v1 polish estimate (the spreadsheet workflow) and a
    project with no polish estimate at all both belong to the live intake."""
    if version is None or isinstance(version, bool):
        return False
    try:
        return float(str(version).strip()) == 2.0
    except ValueError:
        return False


def _pos_num(v: Any) -> Optional[float]:
    """A positive number, or None. Accepts the string a `->>` projection returns."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _bid_total(data: Dict[str, Any]) -> Optional[float]:
    """The money on a card, resolved the way the proposal itself resolves it.

    `proposal_lump_sum` FIRST, because that is the estimate sheet's own TOTAL LUMP SUM for the
    base tab (D88/D82) — the figure the estimator is looking at and the one the proposal prints.
    `computed_bid` is the removed Reference Bid engine and is the FALLBACK ONLY, which is the
    precedence proposal-review.js has documented all along (see its comment at the `#tb-total`
    stash). This function had only the fallback, and the consequences were both halves bad:

      - 21 of 31 live drafts (2026-08-19) were priced but showed no money at all, because
        estimate-review.js nulls `computed_bid` on the way out of step 2 — Kyle's "why not all
        containers have the dollar amount?".
      - the 6 that did show one showed the WRONG one. Every row where both figures exist
        disagrees, in both directions: draft 17117b50 showed $30,960 against a real bid of
        $45,629, and 89b3498b showed $11,573 against $7,861. The engine is known to be ~30% out
        on polish, which is why it was removed.

    Sharing one order with the proposal is the point: a card can no longer name a price the
    document would not.

    THE ORDER INVERTS FOR A POLISH BETA PROJECT, and it has to. That calculator prices itself and
    writes `computed_bid` on every save (polish-estimate.js:202) but never touches
    `proposal_lump_sum` — so on a project that was first priced on the spreadsheet and then
    re-priced in the beta, the lump sum is the STALE figure and the engine object is the live one.
    Preferring the lump sum there would show the old spreadsheet number on a bid nobody quotes
    any more, which is the same class of leak the beta's own file header warns about."""
    data = data or {}
    beta = data.get("polish_beta")
    if beta is None:
        beta = _polish_beta((data.get("polish_estimate") or {}).get("version"))

    def engine() -> Optional[float]:
        cb = data.get("computed_bid") or {}
        fb = cb.get("full_bid") or {}
        if isinstance(fb.get("total_base_bid"), (int, float)):
            return float(fb["total_base_bid"])
        if isinstance(cb.get("grand_total"), (int, float)):
            return float(cb["grand_total"])      # material-only mode, as on Proposal Review
        return None

    order = (engine, lambda: _pos_num(data.get("proposal_lump_sum"))) if beta else \
            (lambda: _pos_num(data.get("proposal_lump_sum")), engine)
    for src in order:
        got = src()
        if got is not None:
            return got
    return None


def _summary_detail(data: Dict[str, Any]) -> Dict[str, Any]:
    """Compact project descriptor stored on events so History needs no join."""
    return {
        "project_name": (data or {}).get("project_name"),
        "total": _bid_total(data),
    }


def _summary(row: Dict[str, Any]) -> Dict[str, Any]:
    data = row.get("data") or {}
    return {
        "id": row["id"],
        "project_name": data.get("project_name") or "(untitled)",
        "deadline": data.get("deadline"),
        "city_state": data.get("city_state"),
        "work_type": data.get("work_type"),
        "audience": data.get("audience"),
        "total": _bid_total(data),
        "archived": _truthy(data.get("archived")),
        "is_test": _tribool(data.get("is_test")),
        # Same question as the fast path's jsonb scalar, asked of the parsed blob: was this
        # priced in the beta calculator (polish_estimate.version 2) rather than the spreadsheet.
        "polish_beta": _polish_beta((data.get("polish_estimate") or {}).get("version")),
        "lump_sum_display": data.get("lump_sum_display"),
        "owner_email": row.get("owner_email"),
        "assigned_estimator": data.get("assigned_estimator"),
        "contact_email": data.get("contact_email"),
        # Same meaning as the fast path's jsonb scalar: has Generate ever run here.
        "has_files": bool(data.get("generate_result")),
        # Closed lost before it was ever sent — see set_close_lost. The reason, or None. The
        # Active Projects board turns this into the same closed_lost state a portal row carries,
        # so one dead bid reads the same whether or not the customer ever saw it.
        "closed_lost_reason": ((data.get("closed_lost") or {}).get("reason") or None),
        "closed_lost_at": ((data.get("closed_lost") or {}).get("at") or None),
        "closed_lost_note": ((data.get("closed_lost") or {}).get("note") or None),
        # On hold — see set_on_hold. Both summary paths expose it for the reason the won mark
        # gives below: one path serves every real page load and the other serves the day
        # PostgREST refuses the projection, and a field on only one of them is a bug that
        # reproduces once a month.
        "on_hold_reason": ((data.get("on_hold") or {}).get("reason") or None),
        "on_hold_until": ((data.get("on_hold") or {}).get("until") or None),
        "on_hold_note": ((data.get("on_hold") or {}).get("note") or None),
        # Marked won by hand — see set_won. Same key, same meaning as the fast projection's jsonb
        # scalar: both paths have to expose it or the Won mark reaches the card on some page loads
        # and not others, which is indistinguishable from the mark not having saved.
        "won_at": ((data.get("won") or {}).get("at") or None),
        # Handed to operations — see set_handed_off. Both paths, same argument as the won mark
        # above, and with more at stake: this one decides which TAB the project appears on, so a
        # field on only one path would move a project between tabs depending on which query ran.
        "handed_off_at": ((data.get("handed_off") or {}).get("at") or None),
        # The scope group — see the fast path's note. Both paths, for the reason the won mark gives.
        "scope_group_id": (_scope_of(data)[0]),
        "scope_label": (_scope_of(data)[1]),
        "proposal_of": data.get("proposal_of") or None,
        "split_had_files": _truthy(data.get(SPLIT_HAD_FILES)),
        # Starred and copied — both paths, for the reason the won mark gives.
        "starred_at": ((data.get("starred") or {}).get("at") or None)
        if isinstance(data.get("starred"), dict) else None,
        "copied_from": ((data.get("copied_from") or {}).get("id") or None)
        if isinstance(data.get("copied_from"), dict) else None,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "deleted_at": row.get("deleted_at"),
    }
