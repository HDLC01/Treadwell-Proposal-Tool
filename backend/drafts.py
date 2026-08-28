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

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import cachetools

from supabase_client import get_client


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
_SERVER_OWNED_KEYS = ("is_test", "archived", "assigned_estimator")


def save_draft(draft_id: str, data: Dict[str, Any],
               owner_email: Optional[str] = None) -> Dict[str, str]:
    """Upsert a project. On first save, stamps owner_email + logs a `created`
    event. On update, preserves owner_email/created_at and the server-owned keys
    listed in `_SERVER_OWNED_KEYS`. Returns {id, updated_at}."""
    sb = get_client()
    now = _now_iso()
    existing = sb.table("drafts").select("id,data").eq("id", draft_id).limit(1).execute()

    if existing.data:
        # Carry forward what the server owns, unless this caller is deliberately setting it.
        # `is_test` is a tri-state, so `False` is a real value and `in` is the right test — a
        # `.get()` truthiness check would treat "somebody said this IS a real bid" as unset.
        prior = existing.data[0].get("data") or {}
        data = dict(data)
        for key in _SERVER_OWNED_KEYS:
            if key not in data and key in prior:
                data[key] = prior[key]
        sb.table("drafts").update({"data": data, "updated_at": now}).eq("id", draft_id).execute()
    else:
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
    Returns True if the project existed."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
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
                "handed_off_at:data->handed_off->>at")
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
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "deleted_at": row.get("deleted_at"),
    }
