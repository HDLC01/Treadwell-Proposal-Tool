"""Turn one ZAP JSON report into the PUBLIC step summary: counts and alert names, nothing else.

    python3 .zap/summarize.py <report.json> <rules.tsv> <target> <zap exit code>  >> $GITHUB_STEP_SUMMARY

THE REPOSITORY IS PUBLIC, so the step summary and the run log can be read by anyone. A ZAP report
is a list of places our apps are weak, with the exact URL, parameter, attack string and evidence
for each. None of that may leave this script. What does: the target we were asked to scan (it is
already in the workflow file), how many alerts there were at each risk level, and each alert's
name and ZAP rule id, which are ZAP's own fixed strings. The full report is never kept in CI at
all (no artifact, nothing else printed) — for that, run deploy/zap-scan.sh locally, which writes
it to zap-reports/ on the machine that ran it.

It is built by COPYING OUT the few fields it prints, never by filtering the report down, so a field
a newer ZAP adds cannot leak through by default. Names are still scrubbed of anything URL-shaped
and of Markdown and HTML, in case a rule ever puts a URL in its name.

Alerts listed in rules.tsv as IGNORE are deliberate. They are left out of the counts and listed
underneath with the reason from the file, so an ignore is always visible and always explained.

Exit status: 0 when a report was read (whatever it found: this scan is report-only), 1 when there
was no report to read or ZAP failed, so a scan that did not happen can never look like a clean one.
"""
import json
import re
import sys

RISKS = ((3, "High"), (2, "Medium"), (1, "Low"), (0, "Informational"))
KEY_RE = re.compile(r"^\d{1,6}(?:-\d{1,3})?$")
URLISH = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S*|\bwww\.\S+|/\S*/\S*")
UNSAFE = re.compile(r"[^A-Za-z0-9 .,:;'()&+\-\"]")
# ZAP's automation run: 0 = fine, 2 = the plan raised warnings (not findings; findings never change
# the exit code here). Anything else, including 124 from `timeout`, means the scan broke.
OK_EXITS = {"0", "2"}


def clean(text, limit=120):
    """A name safe to print in public Markdown: no URLs, no markup, one line, bounded."""
    text = URLISH.sub("", str(text or ""))
    text = UNSAFE.sub(" ", text)
    text = " ".join(text.split())
    return (text[:limit].rstrip() or "(unnamed)")


def load_rules(path):
    """{key: reason} for every IGNORE line. Anything else in the file is an error on purpose: a
    misspelt level must not quietly stop ignoring, and an ignore without a reason is not allowed."""
    rules = {}
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 4:
                raise ValueError("rules line %d: want 4 TAB-separated fields, got %d" % (n, len(parts)))
            key, level, _name, reason = (p.strip() for p in parts)
            if not KEY_RE.match(key):
                raise ValueError("rules line %d: %r is not a ZAP rule id or alertRef" % (n, key))
            if level != "IGNORE":
                raise ValueError("rules line %d: only IGNORE is supported, got %r" % (n, level))
            if not reason:
                raise ValueError("rules line %d: an IGNORE needs a reason" % n)
            rules[key] = reason
    return rules


def _alerts(report):
    """(key, rule id, risk, name, instances) for each alert, copied out field by field."""
    for site in report.get("site") or []:
        for a in (site or {}).get("alerts") or []:
            try:
                risk = int(a.get("riskcode"))
            except (TypeError, ValueError):
                continue
            if risk not in (0, 1, 2, 3):
                continue                                   # -1 = false positive
            pid = str(a.get("pluginid") or "").strip()
            ref = str(a.get("alertRef") or pid).strip()
            pid = pid if KEY_RE.match(pid) else "?"
            ref = ref if KEY_RE.match(ref) else pid
            try:
                count = max(0, int(a.get("count") or 0))
            except (TypeError, ValueError):
                count = 0
            yield ref, pid, risk, clean(a.get("name") or a.get("alert")), count


def render(report, rules, target, zap_exit):
    out = ["### ZAP baseline: %s" % _target(target), ""]
    if report is None:
        out += ["**The scan did not produce a report** (ZAP exit code %s). Nothing was checked; "
                "re-run with deploy/zap-scan.sh against the same target for the full log." % clean(zap_exit, 10), ""]
        return "\n".join(out)
    merged = {}
    ignored = {}
    for ref, pid, risk, name, count in _alerts(report):
        reason = rules.get(ref) or rules.get(pid)
        bucket = ignored if reason else merged
        slot = bucket.setdefault((ref, name), {"risk": risk, "count": 0, "reason": reason})
        slot["risk"] = max(slot["risk"], risk)
        slot["count"] += count
    out += ["| Risk | Alerts | Instances |", "|---|---:|---:|"]
    for code, label in RISKS:
        rows = [v for v in merged.values() if v["risk"] == code]
        out.append("| %s | %d | %d |" % (label, len(rows), sum(v["count"] for v in rows)))
    out.append("")
    for code, label in RISKS:
        names = sorted("%s [%s]" % (name, ref) for (ref, name), v in merged.items() if v["risk"] == code)
        if names:
            out.append("**%s:** %s" % (label, "; ".join(names)))
    if ignored:
        out += ["", "Ignored on purpose (`.zap/rules.tsv`), not counted above:"]
        for (ref, name), v in sorted(ignored.items()):
            out.append("- %s [%s]: %s" % (name, ref, clean(v["reason"], 240)))
    if str(zap_exit) not in OK_EXITS:
        out += ["", "**ZAP exited with code %s**, so this report may be incomplete." % clean(zap_exit, 10)]
    out += ["", "Where each alert was found is not here: this repository is public. Run "
            "deploy/zap-scan.sh against the same target for the full HTML/JSON report.", ""]
    return "\n".join(out)


def _target(target):
    """The URL we were told to scan, reduced to scheme and host. It comes from the workflow's own
    matrix, not from the report, but it is scrubbed the same way all the same."""
    m = re.match(r"^(https?)://([A-Za-z0-9.-]+)(?::\d+)?/?$", str(target or "").strip())
    return "%s://%s" % (m.group(1), m.group(2).lower()) if m else "(unrecognised target)"


def main(argv):
    if len(argv) != 5:
        sys.stderr.write("usage: summarize.py <report.json> <rules.tsv> <target> <zap exit code>\n")
        return 2
    report_path, rules_path, target, zap_exit = argv[1:]
    rules = load_rules(rules_path)
    try:
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
        if not isinstance(report, dict):
            report = None
    except (OSError, ValueError):
        report = None
    sys.stdout.write(render(report, rules, target, zap_exit))
    sys.stdout.write("\n")
    return 0 if report is not None and str(zap_exit) in OK_EXITS else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
