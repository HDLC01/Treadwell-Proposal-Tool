#!/usr/bin/env bash
# Run OWASP ZAP's baseline scan BY HAND, from Hanz's Windows PC (Git Bash + Docker Desktop),
# against ONE of the four Treadwell targets — the same pinned image and the same
# .zap/baseline.yaml plan .github/workflows/zap-baseline.yml runs in CI.
#
# Usage:
#   bash deploy/zap-scan.sh [target-url]
#   default target: https://staging.proposals.wetreadwell.com
#
# WHY THIS EXISTS: the CI workflow keeps only a step summary (counts per risk level and alert
# names) because the repository is public and a ZAP report names every weak URL, parameter and
# attack string on a real, named site — not something to hand a signed-in GitHub stranger. This
# script is where that detail lives instead: the full HTML + JSON report, written to zap-reports/
# at the repo root (gitignored — same reason). Nothing here is uploaded or shared automatically.
#
# EXACTLY THE FOUR TARGETS THE WORKFLOW SCANS, and nothing else: this refuses any target that is
# not one of them byte-for-byte, https only. Never point this at the marketing site (the bare
# wetreadwell.com / www — that's the WordPress site on other hosting) and never at anything that
# merely CONTAINS one of the four names (proposals.wetreadwell.com.evil.com is not
# proposals.wetreadwell.com).
#
# The image, the add-on and its checksum are read out of the workflow file rather than copied
# here a second time, so bumping a pin in one place is bumping it everywhere — a second, silently
# stale copy is exactly the kind of drift the workflow's own pins exist to prevent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="$ROOT/.github/workflows/zap-baseline.yml"
PLAN="$ROOT/.zap/baseline.yaml"
SUMMARIZE="$ROOT/.zap/summarize.py"
RULES="$ROOT/.zap/rules.tsv"

# ── the target, checked before ANYTHING else runs (no Docker call yet) ───────────────────────
ALLOWED_TARGETS=(
  "https://staging.proposals.wetreadwell.com"
  "https://staging.portal.wetreadwell.com"
  "https://proposals.wetreadwell.com"
  "https://portal.wetreadwell.com"
)
target="${1:-https://staging.proposals.wetreadwell.com}"
target="${target%/}"     # a trailing slash is still the same target

is_allowed=0
for t in "${ALLOWED_TARGETS[@]}"; do
  if [ "$target" = "$t" ]; then
    is_allowed=1
    break
  fi
done
if [ "$is_allowed" -ne 1 ]; then
  echo "Refused: '$target' is not one of the four scan targets (https://staging.proposals," \
       "https://staging.portal, https://proposals or https://portal .wetreadwell.com, exactly," \
       "no path, no port). Not scanning it." >&2
  exit 1
fi

for f in "$WORKFLOW" "$PLAN" "$SUMMARIZE" "$RULES"; do
  [ -f "$f" ] || { echo "Refused: missing $f" >&2; exit 1; }
done

# ── Docker Desktop must be up ─────────────────────────────────────────────────────────────────
if ! docker info >/dev/null 2>&1; then
  echo "Refused: Docker does not answer (is Docker Desktop running?). Start it and try again." >&2
  exit 1
fi

# ── the same pins the workflow uses, read out of it rather than duplicated here ──────────────
zap_image=$(grep -m1 '^  ZAP_IMAGE:' "$WORKFLOW" | sed -E 's/^\s*ZAP_IMAGE:\s*([^[:space:]]+).*/\1/')
beta_url=$(grep -m1 '^  ZAP_BETA_RULES_URL:' "$WORKFLOW" | sed -E 's/^\s*ZAP_BETA_RULES_URL:\s*([^[:space:]]+).*/\1/')
beta_sha=$(grep -m1 '^  ZAP_BETA_RULES_SHA256:' "$WORKFLOW" | sed -E 's/^\s*ZAP_BETA_RULES_SHA256:\s*([^[:space:]]+).*/\1/')
for name_val in "zap_image=$zap_image" "beta_url=$beta_url" "beta_sha=$beta_sha"; do
  [ -n "${name_val#*=}" ] || { echo "Refused: could not read a pin out of $WORKFLOW ($name_val)" >&2; exit 1; }
done

# ── one output folder per target + run, so two runs never clobber each other ────────────────
host="${target#https://}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$ROOT/zap-reports/${host}-${stamp}"
mkdir -p "$out"
cp "$PLAN" "$out/baseline.yaml"
chmod 0777 "$out"          # the image runs as uid 1000 (zap); Docker Desktop's bind mount needs this

echo "==> Scanning $target"
echo "==> Report directory: $out"

echo "==> Pulling $zap_image ..."
docker pull --quiet "$zap_image" > /dev/null

echo "==> Fetching the pinned add-on (pscanrulesBeta) and checking its SHA-256 ..."
beta="$out/${beta_url##*/}"
curl -fsSL --retry 3 -o "$beta" "$beta_url"
echo "$beta_sha  $beta" | sha256sum --check --quiet -

echo "==> Running ZAP (this takes a few minutes; passive scan + a 1-minute spider) ..."
rc=0
# Git Bash (MSYS) rewrites any argument that LOOKS like a POSIX path before handing it to a
# non-MSYS program — docker.exe here — which mangles a container-side path such as
# `/zap/wrk/baseline.yaml` into something like `C:/Program Files/Git/zap/wrk/baseline.yaml`, and
# corrupts a `-v host:container:mode` spec by turning its colons into semicolons. Measured on this
# box: without this, ZAP reported "Cannot access file: /zap/C:/Program Files/Git/zap/wrk/
# baseline.yaml" and `docker inspect` showed a garbled mount. MSYS_NO_PATHCONV=1 turns that
# rewriting off for this one command only — set globally it also stops curl's own -o path (a
# few lines up) from being translated to a real Windows path, which broke that write instead. It
# does nothing on real Linux/macOS bash, where this variable is not read.
MSYS_NO_PATHCONV=1 timeout --kill-after=30s 15m \
  docker run --rm -e ZAP_TARGET="$target" -v "$out:/zap/wrk:rw" \
    -v "$beta:/zap/plugin/${beta##*/}:ro" "$zap_image" \
    zap.sh -cmd -autorun /zap/wrk/baseline.yaml \
  > "$out/zap.log" 2>&1 || rc=$?
echo "ZAP finished with exit code $rc."

echo ""
summary_rc=0
python3 "$SUMMARIZE" "$out/report.json" "$RULES" "$target" "$rc" || summary_rc=$?

echo ""
echo "Full report: $out/report.html and $out/report.json"
echo "ZAP's own log: $out/zap.log"
exit "$summary_rc"
