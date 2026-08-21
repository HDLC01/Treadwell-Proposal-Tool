"""One way to write a small JSON file on the data volume, so there is one place to fix it.

WHY THIS MODULE EXISTS. Five places wrote a JSON file the same three-line way - a temp file beside
the target, then `os.replace` over it - and each one had the same two problems:

    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(_FILE)

1. THE TEMP NAME IS FIXED, so it is shared. The module-level lock each caller holds covers threads
   in ITS OWN process and nothing else. A second process - a worker, a second uvicorn, a test runner
   under xdist - writing the same path can truncate our half-written file before either rename, and
   the loser's rename then publishes a partial file.

2. THE RENAME HAS NO RETRY. `os.replace` is atomic, but on Windows it raises PermissionError
   (WinError 5) whenever anything holds a handle on either path for the instant of the rename; an
   antivirus scanning the file we just wrote is the usual cause. Production is Linux and does not
   have that failure mode, so this is mostly a dev-experience problem - but it made the test suite
   fail about half the time under `-n auto`, and a red run on an unrelated branch reads as that
   branch's fault.

The fix was written into nav_access.py first, and then pull_window.py failed the SAME way on the
next merge - same bug, sibling module, its thread-safety test even has the same name. Copying the
retry a fourth and fifth time is how the sixth instance gets written without it, so it lives here
instead and every caller routes through it.

WHAT THIS DELIBERATELY DOES NOT DO. It does not swallow errors. Every caller has its own opinion
about a failed write - nav_access raises NavAccessWriteError because an admin must not believe they
locked a tab down when they did not; the notification and digest state files log and carry on
because losing a "last sent" marker costs a duplicate email, not correctness. Those are real
differences and they stay with the callers.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

# Three tries over ~45ms. Long enough to outlast a scanner holding the file, far below the point a
# human notices, and short enough that a genuinely stuck path still fails inside one request.
_TRIES = 3
_BACKOFF_S = 0.015


def temp_path_for(target: Path) -> Path:
    """A temp path beside `target` that no other writer can be using at the same time.

    The pid separates processes, which is the collision the callers' locks cannot prevent. The
    thread id is there so that removing one of those locks later does not silently reintroduce the
    bug within a process.
    """
    return target.with_suffix(".tmp.%d.%d" % (os.getpid(), threading.get_ident()))


def write_json(target: Path, payload: Any, *, make_parent: bool = True) -> None:
    """Serialise `payload` and put it at `target` atomically. Raises on failure.

    Callers decide what a failure means; this only decides how the bytes land.
    """
    if make_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_path_for(target)
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    try:
        replace_with_retry(tmp, target)
    except Exception:
        # Do not leave our own temp file behind on the volume. Best effort: if this fails too there
        # is nothing useful left to do, and the original error is the one worth raising.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def replace_with_retry(tmp: Path, target: Path) -> None:
    """`tmp.replace(target)`, retried past a transient PermissionError.

    ONLY PermissionError is retried. A disk-full or a bad path is not going to be different in 15
    milliseconds, and retrying it three times just delays the error the caller needs to see.
    """
    for attempt in range(_TRIES):
        try:
            tmp.replace(target)
            return
        except PermissionError:
            if attempt == _TRIES - 1:
                raise
            time.sleep(_BACKOFF_S * (attempt + 1))
