"""The 6 AM digest: at most five proposals per estimator, worth chasing today.

One daemon thread. Once a day, after 6 AM Central, it reads the portal pipeline,
scores every live proposal on how badly it needs a human, keeps the top five per
assigned estimator, asks Claude for one sentence on each, and posts them to the
portal to render and send.

WHY A HEURISTIC RANKS AND CLAUDE ONLY WRITES. Ranking has to be stable and
explainable — "why is this one first?" must have an answer that survives being
questioned by Kyle, and must not change because a model was feeling different
today. So the score is arithmetic in `score()`, and the model's only job is
turning the facts we already computed into a readable sentence. If it fails, a
templated sentence says the same thing less gracefully and THE DIGEST STILL
SENDS: a missing email is a proposal nobody chases, which is the failure this
whole system exists to prevent.

WHY IT RUNS FROM A STARTUP HOOK, unlike the lead autopilot. Nobody opens a page
at 6 AM, so a lazy first-request start would mean the digest never went out until
somebody signed in — by which time they no longer need it.

AT MOST ONCE A DAY. `last_run` in digest_state.json is the whole idempotency
story: a container that restarts at 7:15 still sends (the hour has passed and
today isn't stamped), and one that restarts at 6:05 having already sent does
not. The file lives on the same Docker volume as the drafts DB, so it survives
`up -d --build`.

  DIGEST_ENABLED    on | off              (default on)
  DIGEST_HOUR       hour in Central       (default 6)
  DIGEST_MIN_SCORE  needed to recommend   (default 40)
  DIGEST_MAX_ITEMS  per estimator         (default 5)

Circular imports: this module never imports main. main hands it `portal` (the
service-token caller) and `run_claude` when it starts the thread, exactly like
leads_worker.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("proposal_tool.digest_worker")

try:                                        # py3.9+ stdlib; matches the rest of the app
    from zoneinfo import ZoneInfo
except ImportError:                         # pragma: no cover
    ZoneInfo = None  # type: ignore

BIZ_TZ = "America/Chicago"

_DATA_DIR = Path(os.environ.get("DRAFTS_DB_PATH", "/app/data/drafts.db")).parent
_STATE_FILE = _DATA_DIR / "digest_state.json"
_MEM_STATE: Dict[str, Any] = {}             # fallback when the volume isn't writable

_TICK_S = 300                               # 5 min — the hour boundary is the trigger
_BOOT_DELAY_S = 20                          # let startup finish before the first look

_START_LOCK = threading.Lock()
_THREAD: Optional[threading.Thread] = None
_HOOKS: Dict[str, Callable[..., Any]] = {}

# ── scoring weights ───────────────────────────────────────────────────
# Module constants rather than inline numbers so "why did this rank first" is a
# readable answer and tuning is one edit in one place. Each term is capped, so no
# single signal can dominate: a 900k proposal that went out yesterday must not
# outrank a 40k one the customer has been silent on for three weeks.
W_VALUE_MAX = 25.0          # 25 at $50k+ — money matters, but it isn't urgency
VALUE_FULL_AT = 50_000.0
W_AGE_PER_DAY = 2.0
W_AGE_MAX = 20.0
W_UNVIEWED = 15.0           # never opened, 3+ days — the email may have been missed
UNVIEWED_AFTER_DAYS = 3
W_STALLED = 10.0            # read but not approved for a week
STALLED_AFTER_DAYS = 7
W_SILENCE_PER_DAY = 2.5     # since the customer last did anything
W_SILENCE_MAX = 20.0
W_NEGLECT_PER_DAY = 1.5     # since WE last chased them
W_NEGLECT_MAX = 15.0
W_UNREAD_BASE = 10.0        # an unanswered customer message outranks most things
W_UNREAD_PER = 5.0
W_UNREAD_MAX = 25.0

QUIET_DAYS = 2              # chased within this many days → leave it alone today

REASON_MAX_WORDS = 25


# ── config ────────────────────────────────────────────────────────────
def _enabled() -> bool:
    return (os.environ.get("DIGEST_ENABLED") or "on").strip().lower() not in ("off", "0", "false", "no")


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.environ.get(name) or default)))
    except (TypeError, ValueError):
        return default


def _hour() -> int:
    return _int_env("DIGEST_HOUR", 6, 0, 23)


def _min_score() -> int:
    return _int_env("DIGEST_MIN_SCORE", 40, 0, 100)


def _max_items() -> int:
    return _int_env("DIGEST_MAX_ITEMS", 5, 1, 25)


# ── time ──────────────────────────────────────────────────────────────
def _biz_tz():
    return ZoneInfo(BIZ_TZ) if ZoneInfo else timezone.utc


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def biz_now(now: Optional[datetime] = None) -> datetime:
    return (now or now_utc()).astimezone(_biz_tz())


def _parse(ts: Any) -> Optional[datetime]:
    """An ISO timestamp from the portal → aware datetime, or None.

    Naive values are read as UTC: the portal stamps `timestamptz` and psycopg
    hands back an offset, but a hand-built payload (a test, a manual trigger)
    may not, and guessing local time there would shift every age by hours."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def days_since(ts: Any, now: datetime) -> Optional[float]:
    d = _parse(ts)
    if not d:
        return None
    # Never negative: a clock skew between the portal and here would otherwise
    # read as a proposal sent in the future and score it as brand new.
    return max(0.0, (now - d).total_seconds() / 86400.0)


# ── state ─────────────────────────────────────────────────────────────
def load_state() -> Dict[str, Any]:
    try:
        if _STATE_FILE.is_file():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 — a garbled file must not stop the digest
        log.warning("digest state read failed: %s", exc)
    return dict(_MEM_STATE)


def save_state(state: Dict[str, Any]) -> None:
    global _MEM_STATE
    _MEM_STATE = dict(state)                 # in-process copy is always current
    try:
        if _DATA_DIR.is_dir() and os.access(_DATA_DIR, os.W_OK):
            tmp = _STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            tmp.replace(_STATE_FILE)         # atomic
    except Exception as exc:  # noqa: BLE001
        log.warning("digest state write failed: %s", exc)


def should_run(state: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """Has today's digest hour arrived, and today's digest not gone out?

    Deliberately "hour has passed" rather than "hour is now": a container down at
    6:00 and back at 7:15 should still send the morning's digest. It's late, not
    void."""
    b = biz_now(now)
    if b.hour < _hour():
        return False
    return str(state.get("last_run") or "") != b.date().isoformat()


# ── eligibility ───────────────────────────────────────────────────────
def _fu(p: Dict[str, Any]) -> Dict[str, Any]:
    return p.get("followup_state") or {}


def eligible(p: Dict[str, Any], now: datetime) -> bool:
    """Is this proposal something an estimator could usefully act on today?

    Everything excluded here is excluded because chasing it would be wrong, not
    merely unproductive: a booked job is done, a closed-lost one was declined, and
    a paused one was paused BY THE CUSTOMER — putting it back in front of an
    estimator invites exactly the call they asked us not to make."""
    status = str(p.get("proposal_status") or "")
    if status in ("closed_lost", "approved"):
        # Approved but unpaid still needs chasing — it just isn't THIS list's job;
        # the deposit column and its own reminders own that.
        return False
    if str(p.get("schedule_status") or "") == "scheduled":
        return False
    # Compared as plain dates in Central. `paused_until` is a DATE column, so
    # parsing it as a timestamp and shifting timezones is how a pause silently
    # expires a day early for whoever is running the server.
    paused = str(_fu(p).get("paused_until") or "")[:10]
    if paused and paused >= biz_now(now).date().isoformat():
        return False
    # Chased in the last couple of days: whoever did it is on the case, and a
    # reminder now would read as the system not noticing their work.
    d = days_since(p.get("last_followup_at"), now)
    if d is not None and d < QUIET_DAYS:
        return False
    return True


# ── scoring ───────────────────────────────────────────────────────────
def score(p: Dict[str, Any], now: datetime) -> Tuple[int, List[str]]:
    """0–100, plus the plain-English facts behind it.

    The facts travel with the score because they are what the email says and what
    Claude is given to write from — recomputing them anywhere else would let the
    number and the sentence drift apart."""
    pts = 0.0
    facts: List[str] = []

    total = p.get("approved_total")
    if isinstance(total, (int, float)) and total > 0:
        pts += W_VALUE_MAX * min(1.0, float(total) / VALUE_FULL_AT)
        facts.append("worth ${:,.0f}".format(float(total)))

    age = days_since(p.get("sent_at"), now)
    if age is not None:
        pts += min(W_AGE_MAX, W_AGE_PER_DAY * age)
        facts.append("sent {} day{} ago".format(int(age), "" if int(age) == 1 else "s"))

    viewed = p.get("last_viewed_at") or p.get("viewed_at")
    if not viewed:
        if age is not None and age >= UNVIEWED_AFTER_DAYS:
            pts += W_UNVIEWED
            facts.append("never opened it")
    else:
        seen = days_since(viewed, now)
        if seen is not None and seen >= STALLED_AFTER_DAYS:
            pts += W_STALLED
            facts.append("read it {} days ago and hasn't decided".format(int(seen)))

    quiet = days_since(p.get("last_activity_at"), now)
    if quiet is not None and quiet >= 1:
        pts += min(W_SILENCE_MAX, W_SILENCE_PER_DAY * quiet)
        facts.append("no movement for {} day{}".format(int(quiet), "" if int(quiet) == 1 else "s"))

    # Never chased at all is the worst case, so it scores as the full weight
    # rather than falling through as "no data".
    chased = days_since(p.get("last_followup_at"), now)
    if chased is None:
        pts += W_NEGLECT_MAX
        facts.append("nobody has followed up yet")
    elif chased >= 1:
        pts += min(W_NEGLECT_MAX, W_NEGLECT_PER_DAY * chased)
        facts.append("last chased {} day{} ago".format(int(chased), "" if int(chased) == 1 else "s"))

    unread = int(p.get("unread") or 0)
    if unread > 0:
        pts += min(W_UNREAD_MAX, W_UNREAD_BASE + W_UNREAD_PER * unread)
        facts.append("{} unanswered message{}".format(unread, "" if unread == 1 else "s"))

    return int(round(max(0.0, min(100.0, pts)))), facts


# ── selection ─────────────────────────────────────────────────────────
def pick(rows: List[Dict[str, Any]], now: datetime,
         state: Optional[Dict[str, Any]] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Group the worth-chasing proposals by estimator, best first, capped.

    UNASSIGNED PROPOSALS ARE SKIPPED, not dumped on everyone. A digest addressed to
    the whole roster is a digest nobody owns — and the publish flow now refuses to
    send without an estimator, so the only rows here are legacy ones. They stay
    visible on the board, which is where an unowned proposal should be noticed."""
    state = state or {}
    streaks = state.get("streaks") or {}
    by: Dict[str, List[Dict[str, Any]]] = {}
    for p in rows:
        who = str(p.get("assigned_estimator") or "").strip().lower()
        if not who or not eligible(p, now):
            continue
        pts, facts = score(p, now)
        if pts < _min_score():
            continue
        pid = str(p.get("proposal_id") or "")
        by.setdefault(who, []).append({
            "proposal_id": pid,
            "project_name": p.get("project_name") or "Proposal",
            "customer": p.get("customer_name") or p.get("customer_email") or "",
            "total": p.get("approved_total"),
            "stage": _stage_label(p),
            "unread": int(p.get("unread") or 0),
            "score": pts,
            "facts": facts,
            # "Third morning running" is the part that makes a repeat feel like a
            # nudge rather than a duplicate email.
            "streak": int(streaks.get(pid) or 0) + 1,
        })
        # No links in the payload: the portal owns both the customer URL (it has the
        # token) and the CRM deep link (it has PROPOSAL_TOOL_PUBLIC_URL), and it
        # already builds them for every other staff email.
    cap = _max_items()
    for who in by:
        by[who].sort(key=lambda x: (-x["score"], x["project_name"].lower()))
        dropped = len(by[who]) - cap
        by[who] = by[who][:cap]
        if dropped > 0:
            # Never silently: five is a readable morning list, but the estimator
            # should know the queue behind it is longer.
            by[who][-1]["and_more"] = dropped
            log.info("digest: %s has %s more over the bar than fit in the email", who, dropped)
    return by


def _stage_label(p: Dict[str, Any]) -> str:
    """A short phrase for where it stands. Mirrors the board's own vocabulary so
    the email and the screen don't name the same state differently."""
    if int(p.get("unread") or 0) > 0:
        return "Waiting on your reply"
    if str(p.get("deposit_status") or "") == "submitted":
        return "Deposit submitted"
    if str(p.get("proposal_status") or "") == "viewed":
        return "Viewed, not approved"
    return "Sent, not opened" if not (p.get("last_viewed_at") or p.get("viewed_at")) else "Viewed"


def next_streaks(by: Dict[str, List[Dict[str, Any]]]) -> Dict[str, int]:
    """What tomorrow inherits. Only what we recommended TODAY carries a streak —
    a proposal that dropped off the list has been dealt with (or paused, or lost),
    and resurrecting its old count would misstate how long it has been waiting."""
    out: Dict[str, int] = {}
    for items in by.values():
        for it in items:
            out[it["proposal_id"]] = int(it.get("streak") or 1)
    return out


# ── the sentence ──────────────────────────────────────────────────────
def fallback_reason(item: Dict[str, Any]) -> str:
    """The sentence when Claude is unavailable. Says the same facts, less
    gracefully — which is the correct trade against not sending at all."""
    facts = [f for f in (item.get("facts") or [])]
    if item.get("unread"):
        lead = "They're waiting on a reply"
        rest = [f for f in facts if "unanswered" not in f][:2]
    else:
        lead = "Worth a nudge"
        rest = facts[:3]
    return (lead + (" — " + ", ".join(rest) if rest else "") + ".").replace(" —  —", " —")


def _reason_prompt(items: List[Dict[str, Any]]) -> str:
    """What Claude gets: the facts we already computed, and nothing else.

    Deliberately no access to the estimate, the customer's messages or the price
    breakdown. The sentence is a summary of known facts, so giving it more room to
    reason is giving it room to invent — and this email is read as fact by the
    person about to phone the customer."""
    lines = []
    for it in items:
        lines.append(json.dumps({
            "id": it["proposal_id"],
            "project": it["project_name"],
            "customer": it["customer"],
            "stage": it["stage"],
            "facts": it["facts"],
        }))
    return "\n".join(lines)


_REASON_SYSTEM = (
    "You write one sentence per proposal for a concrete contractor's morning "
    "follow-up list. Each input line is JSON with an id and a list of already-verified "
    "facts.\n"
    "Rules:\n"
    "- Use ONLY the facts given. Never invent a detail, a name, a number or a reason.\n"
    f"- At most {REASON_MAX_WORDS} words per sentence. Plain, direct, no greeting, no sign-off.\n"
    "- Say what to do or why it matters, not a restatement of the whole list.\n"
    "- Address the estimator as 'you'; the customer is 'they'.\n"
    'Reply with STRICT JSON and nothing else: {"reasons": {"<id>": "<sentence>"}}'
)


def claude_reasons(items: List[Dict[str, Any]]) -> Dict[str, str]:
    """One batched CLI call for every sentence in this run.

    Batched because a per-item call would be 20-30 s each and a ten-item morning
    would take five minutes of a thread and ten times the spend. ANY failure —
    non-zero exit, garbage JSON, a model that answers in prose — returns {} and the
    caller templates instead. Never raises."""
    if not items or "run_claude" not in _HOOKS:
        return {}
    try:
        out = _HOOKS["run_claude"](_reason_prompt(items), _REASON_SYSTEM) or {}
        reasons = out.get("reasons") if isinstance(out, dict) else None
        if not isinstance(reasons, dict):
            log.warning("digest: reasons payload was %s, not a mapping", type(reasons).__name__)
            return {}
        clean: Dict[str, str] = {}
        wanted = {it["proposal_id"] for it in items}
        for pid, text in reasons.items():
            # Only ids we asked about, and only strings: a hallucinated key would
            # otherwise ride along into an email as a sentence about nothing.
            if str(pid) in wanted and isinstance(text, str) and text.strip():
                clean[str(pid)] = " ".join(text.split())[:240]
        return clean
    except Exception as exc:  # noqa: BLE001 — the digest must send regardless
        log.warning("digest: Claude reasons failed (%s) — using templated text", exc)
        return {}


def with_reasons(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach a sentence to every item. Every item gets one — a blank line in the
    email is worse than a plain one."""
    got = claude_reasons(items)
    for it in items:
        it["reason"] = got.get(it["proposal_id"]) or fallback_reason(it)
    return items


# ── one run ───────────────────────────────────────────────────────────
def build(rows: List[Dict[str, Any]], now: Optional[datetime] = None,
          state: Optional[Dict[str, Any]] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Pipeline rows → what each estimator's email should contain. Pure apart from
    the Claude call, so a manual trigger and the 6 AM thread produce the same thing."""
    now = now or now_utc()
    by = pick(rows, now, state or load_state())
    # ONE call for the whole morning, not one per estimator.
    flat = [it for items in by.values() for it in items]
    with_reasons(flat)
    return by


def run_once(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Build and send today's digest. Returns a summary for the manual trigger.

    The date is stamped BEFORE the sends: a crash halfway through must not mean a
    second full round of emails on the next tick. Some estimators missing today's
    digest is recoverable; two copies of it is the thing that gets the feature
    switched off."""
    now = now or now_utc()
    state = load_state()
    rows = (_HOOKS["portal"]("/api/admin/pipeline", "GET") or {}).get("proposals") or []
    by = build(rows, now, state)

    state["last_run"] = biz_now(now).date().isoformat()
    state["streaks"] = next_streaks(by)
    save_state(state)

    sent, failed = [], []
    for who, items in sorted(by.items()):
        try:
            _HOOKS["portal"]("/api/admin/send-digest", "POST",
                             {"estimator_email": who, "items": items})
            sent.append(who)
        except Exception as exc:  # noqa: BLE001 — one bad address can't stop the rest
            failed.append(who)
            log.warning("digest: send to %s failed: %s", who, exc)
    log.info("digest: %s estimator(s) emailed, %s failed, %s proposal(s) total",
             len(sent), len(failed), sum(len(v) for v in by.values()))
    return {"ok": True, "date": state["last_run"], "sent": sent, "failed": failed,
            "counts": {k: len(v) for k, v in by.items()}}


# ── the thread ────────────────────────────────────────────────────────
def _tick() -> None:
    if not _enabled():
        return
    if not should_run(load_state()):
        return
    run_once()


def _run() -> None:
    time.sleep(_BOOT_DELAY_S)
    while True:
        try:
            _tick()
        except Exception as exc:  # noqa: BLE001 — the loop outlives every failure
            log.warning("digest tick failed: %s", exc)
        time.sleep(_TICK_S)


def ensure_started(portal: Callable[..., Any], run_claude: Callable[..., Any]) -> bool:
    """Start the digest thread, once, from the app's startup hook.

    Never raises — a digest that can't start must not take the app down with it."""
    global _THREAD
    import sys
    # Under pytest a background thread that reaches for the portal turns a 1.5 s
    # suite into minutes of connection timeouts. The tests call the pure functions
    # and run_once() directly.
    if "pytest" in sys.modules or not _enabled():
        return False
    if _THREAD is not None and _THREAD.is_alive():
        return True
    try:
        with _START_LOCK:
            if _THREAD is not None and _THREAD.is_alive():
                return True
            _HOOKS["portal"] = portal
            _HOOKS["run_claude"] = run_claude
            _THREAD = threading.Thread(target=_run, name="digest", daemon=True)
            _THREAD.start()
        log.info("Digest worker started (%s:00 %s, min score %s, max %s per estimator)",
                 _hour(), BIZ_TZ, _min_score(), _max_items())
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Digest worker failed to start: %s", exc)
        return False


def set_hooks(portal: Callable[..., Any], run_claude: Callable[..., Any]) -> None:
    """Wire the hooks without starting the thread — for the manual trigger, which
    has to work on staging whether or not the schedule is running."""
    _HOOKS["portal"] = portal
    _HOOKS["run_claude"] = run_claude
