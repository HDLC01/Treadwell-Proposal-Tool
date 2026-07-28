"""Lead autopilot: read the new bid invites, score them, draft the good ones.

One daemon thread. Every sweep it takes the already-cached Basisboard inbox,
picks the bid invites nobody (and no previous sweep) has scored yet, and runs
them through the same prequalify + create-estimate code the drawer buttons use.
Strong fits become a labelled draft in Projects and a bell item; everything else
just gets a score the estimator sees when they open the lead.

Why a thread and not a request: a `claude -p` run takes 20-30 s, so scoring
inline would hold an HTTP worker hostage. Why not a cron: the state that makes a
sweep safe to repeat already lives in Postgres.

  LEADS_AUTOPILOT           create | score | off      (default create)
  LEADS_AUTOCREATE_SCORE    fit_score needed to draft  (default 70)
  LEADS_AUTOPILOT_BATCH     leads scored per sweep     (default 3)
  LEADS_AUTOPILOT_INTERVAL  seconds between sweeps     (default 90)

Idempotency lives in the DB, not here: a scored lead has `ai`, a drafted lead
has `draft_id`, and both are checked before we spend anything. A restart in the
middle of a sweep therefore costs at most the one lead that was in flight.

Circular imports: this module never imports main. main hands it the two entry
points (`_prequalify_lead`, `_create_estimate_from_lead`) when it starts the
thread, so the autopilot and the buttons run the identical code with no import
cycle and no second copy of main's module state.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import basisboard_client
import leads
import notifications

log = logging.getLogger("proposal_tool.leads_worker")

# The autopilot is a server actor, not a person: it owns its drafts and its
# audit rows under this name, and it bypasses the per-user AI rate buckets
# (which exist to cap what one estimator can spend, not what the server does).
ACTOR = leads.AUTOPILOT_ACTOR

_MODES = ("create", "score", "off")
_SKIP_STATUSES = {"trash", "estimate_created"}
_BOOT_DELAY_S = 15          # let the request that started us finish first
_MAX_ATTEMPTS = 3           # tries per message per process, so one poison lead
                            # can't sit at the head of the queue forever
_MAX_QUIET_S = 30 * 60      # ceiling on the failure backoff

_START_LOCK = threading.Lock()
_THREAD: Optional[threading.Thread] = None
_HOOKS: Dict[str, Callable[..., Any]] = {}

# Touched only by the sweep thread.
_ATTEMPTS: Dict[str, int] = {}
_FAILS = 0
_QUIET_UNTIL = 0.0


# ── config ────────────────────────────────────────────────────────────
def _mode() -> str:
    mode = (os.environ.get("LEADS_AUTOPILOT") or "create").strip().lower()
    return mode if mode in _MODES else "create"


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.environ.get(name) or default)))
    except (TypeError, ValueError):
        return default


def _threshold() -> int:
    return _int_env("LEADS_AUTOCREATE_SCORE", 70, 0, 100)


def _batch() -> int:
    return _int_env("LEADS_AUTOPILOT_BATCH", 3, 1, 20)


def _interval() -> int:
    return _int_env("LEADS_AUTOPILOT_INTERVAL", 90, 30, 3600)


# ── candidate selection ───────────────────────────────────────────────
def _score_of(value: Any) -> float:
    """fit_score as a number. A missing or unparseable score reads as -1 so it
    can never clear the auto-create threshold by accident."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _candidates(messages: List[Dict[str, Any]],
                states: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Unscored bid invites, oldest first.

    Replies, addenda and platform updates are deliberately out: they're noise to
    an estimator and they'd triple what the autopilot spends. A lead already
    trashed or already turned into an estimate is done with us."""
    out: List[Dict[str, Any]] = []
    for msg in messages:
        mid = str(msg.get("id") or "")
        if not mid or msg.get("isSpam"):
            continue
        if str(msg.get("communicationType") or "") != "bid_invite":
            continue
        if _ATTEMPTS.get(mid, 0) >= _MAX_ATTEMPTS:
            continue
        row = states.get(mid) or {}
        if str(row.get("lead_status") or "new") in _SKIP_STATUSES:
            continue
        ai = row.get("ai")
        if isinstance(ai, dict) and ai:          # already scored — never re-run
            continue
        out.append(msg)
    out.sort(key=lambda m: str(m.get("createdAt") or ""))
    return out


# ── one lead ──────────────────────────────────────────────────────────
def _bell(msg: Dict[str, Any], draft_id: str, score: float) -> None:
    proj = msg.get("project") or {}
    company = ((msg.get("company") or {}).get("name") or "").strip()
    title = str(proj.get("name") or msg.get("subject") or "A lead")
    body = "Estimate drafted from a lead"
    if company:
        body += f" · {company}"
    if score >= 0:
        body += f" · fit {int(score)}"
    notifications.add_lead_estimate(draft_id, title, body)


def _process(msg: Dict[str, Any], mode: str) -> None:
    """Score one lead, and draft its estimate when it clears the bar."""
    mid = str(msg.get("id") or "")
    ai = _HOOKS["prequalify"](msg, actor_email=ACTOR) or {}
    score = _score_of(ai.get("fit_score"))
    rec = str(ai.get("recommendation") or "").strip().lower()
    log.info("lead autopilot: %s scored %s (%s) — %s", mid, score, rec or "?",
             str(ai.get("summary") or "")[:140])

    if mode != "create":
        return
    if rec != "pursue" or score < _threshold():
        log.info("lead autopilot: %s not auto-created (needs pursue + >=%s)",
                 mid, _threshold())
        return

    # The grouped-sibling check lives inside create_estimate, so a duplicate
    # invite comes back as `existing` instead of a second project.
    out = _HOOKS["create_estimate"](msg, actor_email=ACTOR, auto=True) or {}
    draft_id = str(out.get("draft_id") or "")
    if not out.get("ok") or not draft_id:
        log.warning("lead autopilot: %s create failed: %s", mid, out.get("error"))
        return
    if out.get("existing"):
        log.info("lead autopilot: %s already had draft %s", mid, draft_id)
        return
    log.info("lead autopilot: %s -> draft %s (score %s)", mid, draft_id, score)
    _bell(msg, draft_id, score)


# ── the sweep ─────────────────────────────────────────────────────────
def _sweep() -> None:
    """One pass over the inbox. Leads are handled SERIALLY — a CLI run is 20-30 s
    and the whole point of a single thread is that only one is ever in flight."""
    global _FAILS, _QUIET_UNTIL
    mode = _mode()
    if mode == "off" or time.time() < _QUIET_UNTIL:
        return

    data = basisboard_client.get_inbox()          # 60 s TTL — shared with the page
    if not data.get("ok"):
        return
    messages = data.get("messages") or []
    states = leads.get_lead_states([str(m.get("id")) for m in messages if m.get("id")])
    queue = _candidates(messages, states)[:_batch()]
    if not queue:
        return

    log.info("lead autopilot: %s lead(s) to score (mode=%s)", len(queue), mode)
    for msg in queue:
        mid = str(msg.get("id") or "")
        _ATTEMPTS[mid] = _ATTEMPTS.get(mid, 0) + 1
        try:
            _process(msg, mode)
        except Exception as exc:  # noqa: BLE001 — one bad lead can't end the thread
            _FAILS += 1
            # Failures here are usually systemic (CLI auth expired, DB down), and
            # the next two leads would fail the same way — so back off and end the
            # sweep. A single poison message is bounded separately by _ATTEMPTS.
            _QUIET_UNTIL = time.time() + min(_MAX_QUIET_S, _interval() * (2 ** min(_FAILS, 5)))
            log.warning("lead autopilot: %s failed (%s) — quiet for %ss",
                        mid, exc, int(_QUIET_UNTIL - time.time()))
            break
        else:
            _ATTEMPTS.pop(mid, None)     # scored: it'll never be a candidate again
            _FAILS = 0
            _QUIET_UNTIL = 0.0


def _run() -> None:
    time.sleep(_BOOT_DELAY_S)
    while True:
        try:
            _sweep()
        except Exception as exc:  # noqa: BLE001 — the loop outlives everything
            log.warning("lead autopilot sweep failed: %s", exc)
        time.sleep(_interval())


def ensure_started(create_estimate: Callable[..., Any],
                   prequalify: Callable[..., Any]) -> bool:
    """Start the sweep thread, once, on the first request that touches leads or
    the bell. Returns whether the autopilot is running.

    Lazy rather than a startup hook so the app doesn't spend AI runs unattended
    on a weekend nobody signs in; once someone opens any page, the bell poll
    keeps it alive until the container restarts. Never raises — a worker that
    can't start must not take a page down with it."""
    global _THREAD
    if _mode() == "off":
        return False
    if _THREAD is not None and _THREAD.is_alive():
        return True
    try:
        with _START_LOCK:
            if _THREAD is not None and _THREAD.is_alive():
                return True
            _HOOKS["create_estimate"] = create_estimate
            _HOOKS["prequalify"] = prequalify
            _THREAD = threading.Thread(target=_run, name="leads-autopilot", daemon=True)
            _THREAD.start()
        log.info("Lead autopilot started (mode=%s, threshold=%s, batch=%s, every %ss)",
                 _mode(), _threshold(), _batch(), _interval())
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Lead autopilot failed to start: %s", exc)
        return False
