"""The values `polish_estimate.version` can hold, and whether each one says "this is a v2 estimate".

ONE TABLE, TWO READERS. backend/drafts.py `_polish_beta` answers it for the Projects page (a card
opens on the intake it was built on) and frontend/shared.js `isV2Draft` answers it for every page that
has to decide the same thing from the draft in its hand. They are two implementations of one rule, in
two languages, and the rule has to hold on every spelling a version can arrive in: PostgREST hands the
server the version as TEXT, the browser has the number. This table is what both are held to.

  * test_beta_intake_routing.py checks the Python side against it (`VERSION_CASES`).
  * test_v2_routing_guard.py runs the JavaScript side and the Python side on all of it
    (`VERSION_CASES + MIRRORED_CASES`) and requires them to agree, case for case.

Every `expect` here is what the SERVER says today. A case is added when a spelling is found that
matters, and an expectation is never edited to make the JavaScript pass.
"""

# The cases test_beta_intake_routing.py has always pinned for the server.
VERSION_CASES = [
    (2, True), ("2", True), (" 2 ", True), ("2.0", True),
    (1, False), ("1", False), (3, False), ("3", False),
    (None, False), ("", False), ("null", False), ("v2", False), ("banana", False),
    (True, False), (False, False), ({}, False),
]

# The rest of what Python's float() makes of a string, and the other types a stored value can be,
# that the JavaScript port is written to agree with. JSON-shaped, because they travel to node as JSON.
MIRRORED_CASES = [
    # spellings of 2
    (2.0, True), ("+2", True), ("2e0", True), (".2e1", True), ("2.", True), ("20e-1", True),
    ("2E0", True), ("0.2e1", True), ("00002", True), ("2e+0", True), ("2e-0", True),
    ("0_2", True), ("2.0_0", True), ("2e0_0", True),
    ("\t2\n", True), ("\u00a02\u00a0", True), ("\r\n2\r\n", True),
    ("1.9999999999999999", True), ("2.00000000000000001", True),
    # not 2
    (0, False), (-2, False), (20, False), (2.5, False), ("-2", False), ("2.5", False), ("1e0", False),
    ("0x2", False), ("0b10", False), ("0o2", False),
    ("1_0", False), ("2_", False), ("_2", False), ("2__0", False), ("1_.5", False), ("1._5", False),
    ("inf", False), ("infinity", False), ("nan", False), ("Infinity", False), ("-Infinity", False),
    ("2,0", False), ("2.0.0", False), ("2e", False), ("e2", False), ("2 0", False),
    ("+-2", False), ("++2", False), ("--2", False), ("2e1e1", False), ("2f", False), ("2d", False),
    ("true", False), ("True", False), (" ", False), ("   ", False), ("\t", False),
    ([2], False), ([], False), ({"version": 2}, False),
]

# The numbers JSON cannot carry, as the harness's tagged form, with Python's own value.
NUMBER_CASES = [
    ("nan", float("nan"), False),
    ("inf", float("inf"), False),
    ("-inf", float("-inf"), False),
]
