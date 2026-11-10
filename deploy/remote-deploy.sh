#!/usr/bin/env bash
#
# Treadwell Proposal Tool - the GitHub deploy, ON THE BOX. This is the ONLY thing the deploy key
# can run.
#
# WHY IT EXISTS. The Deploy workflow used to log in as root and run a shell script it sent along,
# so the VPS_SSH_KEY secret was a root shell on a box that serves a dozen other sites. GitHub hands
# repository secrets to every workflow run on every branch of this repository (only pull requests
# from forks are cut off), so anyone or anything that can push a branch here could read that key.
# The key must therefore be worth nothing more than "deploy a commit that is already on staging or
# main". It belongs to a box account of its own (the proposal tool's, never the BD CRM's), and its
# authorized_keys line forces this program:
#
#     restrict,command="sudo -n /usr/local/sbin/treadwell-tool-deploy" ssh-ed25519 AAAA... tool-deploy
#
# deploy/install-deploy-account.sh installs a COPY of this file there (root:root 0755), so a commit
# can never change what the key runs until a person re-runs the install script, and a sudoers rule
# lets the deploy account run that one file as root, with no arguments, keeping only
# SSH_ORIGINAL_COMMAND. The account is not in the docker or sudo group and cannot get a shell
# through the key. Git runs as root in here because both checkouts' .git folders are root's.
#
# THE REQUEST (SSH_ORIGINAL_COMMAND, sent by .github/workflows/deploy.yml) is ONE line, one of:
#
#     deploy <staging|main> <40-hex commit> <the job's GitHub token>
#     pdf-smoke staging <40-hex commit>
#
# It is matched by a regular expression and NEVER executed or evaluated. Any other line the SSH
# action adds around it is ignored; two matching lines are refused.
#
# `deploy`, in order (staging = /opt/treadwell-staging on branch staging, port 8889;
#                     main = /opt/treadwell on branch main, port 8888):
#   1. one deploy at a time on this box (a lock shared by staging and production);
#   2. the checkout: fetch the branch, refuse a commit that is not on it, refuse a checkout that is
#      not on its branch or holds commits that are not on GitHub;
#   3. the font: keep the checkout's copy of Zetta Serif in /opt/treadwell-fonts, and stop while
#      either file is missing there (the image carries no font; compose mounts the host folder);
#   4. the image: a throw-away DOCKER_CONFIG (never root's ~/.docker), `docker login` with the job
#      token, `docker pull` of exactly sha-<12>. A failed pull changes nothing;
#   5. the checkout moved to exactly that commit WHILE STAYING ON ITS BRANCH (a fast-forward, or a
#      `reset --keep` back to an older commit of the branch), never a detached HEAD: deploy/ship.sh
#      and people still run `git pull --ff-only` in these folders;
#   6. staging only: its Postgres up, pg_isready, backend/staging/schema_pg.sql fed from the
#      checkout (idempotent, additive DDL);
#   7. `docker compose up -d` with TW_IMAGE=<that sha image> (NEVER a build), staging's PostgREST
#      told to reload its schema, then a health loop: /healthz answers AND the container runs the
#      new image;
#   8. a failed health check ROLLS BACK: the previous checkout and the previous image go back up,
#      their health is checked, and the run still ends red;
#   9. the moving tag (staging / prod) re-pointed at the healthy image on this box, so a bare
#      `docker compose up -d` here starts what was deployed;
#  10. housekeeping: the three newest sha images of this app are kept, nothing of any other app.
#
# `pdf-smoke`: the LibreOffice tests CI cannot run, in a throw-away container of the image staging
# was just deployed with, the staging checkout mounted read-only (see run_pdf_smoke below).
set -euo pipefail

REPO=ghcr.io/hdlc01/treadwell-proposal-tool
# Overridable for the tests only. sudo's env_reset drops every variable but SSH_ORIGINAL_COMMAND
# (the one env_keep of the sudoers rule), so nothing that arrives over SSH can set these.
PROD_DIR="${TOOL_PROD_DIR:-/opt/treadwell}"
STAGING_DIR="${TOOL_STAGING_DIR:-/opt/treadwell-staging}"
FONT_DIR="${TOOL_FONT_DIR:-/opt/treadwell-fonts}"
LOCK="${TOOL_DEPLOY_LOCK:-/run/lock/treadwell-tool-deploy.lock}"
LOCK_WAIT="${TOOL_LOCK_WAIT:-1200}"
TRIES="${TOOL_HEALTH_TRIES:-24}"
PAUSE="${TOOL_HEALTH_PAUSE:-5}"

# The token: GitHub's job token. Measured on the BD CRM's first real deploy (2026-11-05): no longer
# the short `ghs_` + 36 letters/digits but ~380 characters with `_` and a `.` in it. Letters,
# digits, `_`, `.` and `-` only (no space, quote, `$`, `;` or backtick can pass), at most 2000
# characters (checked after the match: bash's regex allows repeat counts up to 255 only), and it
# only ever reaches `docker login --password-stdin`.
DEPLOY_RE='^deploy (staging|main) ([0-9a-f]{40}) (gh[a-z]_[A-Za-z0-9_.-]{20,})$'
SMOKE_RE='^pdf-smoke staging ([0-9a-f]{40})$'

refuse() { printf 'refusing: %s\n' "$*" >&2; exit 2; }
fail() { printf '::error::%s\n' "$*" >&2; exit 1; }

parse_request() {
  local line found=0
  VERB="" BRANCH="" COMMIT="" TOKEN=""
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    if [[ "$line" =~ $DEPLOY_RE ]]; then
      found=$((found + 1))
      VERB=deploy
      BRANCH="${BASH_REMATCH[1]}"
      COMMIT="${BASH_REMATCH[2]}"
      TOKEN="${BASH_REMATCH[3]}"
    elif [[ "$line" =~ $SMOKE_RE ]]; then
      found=$((found + 1))
      VERB=pdf-smoke
      BRANCH=staging
      COMMIT="${BASH_REMATCH[1]}"
      TOKEN=""
    fi
  done <<< "${SSH_ORIGINAL_COMMAND:-}"
  [ "$found" = 1 ] || refuse "the request must be exactly one line: deploy <staging|main> <commit> <token>, or pdf-smoke staging <commit>"
  [ "${#TOKEN}" -le 2000 ] || refuse "the token is longer than 2000 characters"
}

select_environment() {
  case "$BRANCH" in
    main)
      LABEL=prod APP_DIR="$PROD_DIR" COMPOSE_FILE=docker-compose.yml ENV_FILE=.env
      SERVICE=proposal-tool CONTAINER=treadwell-proposal-tool PORT=8888 MOVE="$REPO:prod" ;;
    staging)
      LABEL=staging APP_DIR="$STAGING_DIR" COMPOSE_FILE=docker-compose.staging.yml ENV_FILE=.env.staging
      SERVICE=app CONTAINER=treadwell-staging PORT=8889 MOVE="$REPO:staging" ;;
    *) refuse "unknown branch $BRANCH" ;;
  esac
  HEALTH_URL="http://127.0.0.1:$PORT/healthz"
}

# Every compose call names the environment's own file, from inside its checkout.
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

git_in() { git -C "$APP_DIR" "$@"; }

take_lock() {
  # Staging and production share this box's image store (one repository, both environments'
  # sha tags), the font folder and the housekeeping below; the workflow's concurrency group is per
  # branch, so without this a staging and a production deploy could interleave. A lock held by a
  # dead process is released by the kernel with its file descriptor.
  command -v flock >/dev/null 2>&1 || fail "flock is missing on this box (util-linux)."
  exec 9>"$LOCK" || fail "cannot open the lock file $LOCK"
  flock -w "$LOCK_WAIT" 9 || fail "another proposal-tool deploy held the lock for ${LOCK_WAIT}s; re-run this one."
}

# The checkout can move to $1 without losing anything and without leaving its branch: it is there
# already, it is behind $1 (a fast-forward), or $1 is an older commit of the branch and HEAD itself
# is on GitHub's branch (a `reset --keep` back to it).
can_move_to() {
  local head
  head=$(git_in rev-parse HEAD)
  [ "$head" = "$1" ] && return 0
  git_in merge-base --is-ancestor "$head" "$1" && return 0
  git_in merge-base --is-ancestor "$1" "$head" && git_in merge-base --is-ancestor "$head" "origin/$BRANCH"
}

move_checkout_to() {
  local head
  head=$(git_in rev-parse HEAD)
  if [ "$head" = "$1" ]; then return 0; fi
  if git_in merge-base --is-ancestor "$head" "$1"; then
    git_in merge --ff-only --quiet "$1"
  else
    git_in reset --quiet --keep "$1"
  fi
}

keep_and_check_fonts() {
  # THE FONT BEFORE THE IMAGE. Zetta Serif is licensed, so since 2026-09-26 no image carries it:
  # compose bind-mounts it from the host. Without the files Docker mounts an EMPTY directory and
  # every PDF prints in a substitute font with nothing failing. So stop here, before anything is
  # pulled or restarted; the running container keeps serving. First, keep this checkout's copy:
  # until its first move past the change that untracked the files, git still has them here, and the
  # move below deletes them. Never over a file the box already has.
  # (backend/tests/test_proposal_fonts.py runs this block against temp directories.)
  local f
  TW_FONT_DIR="$FONT_DIR"
  TW_FONT_SEED="$APP_DIR/backend/fonts"
  for f in "Zetta Serif-Book.otf" "Zetta Serif.otf"; do
    if [ ! -s "$TW_FONT_DIR/$f" ] && [ -s "$TW_FONT_SEED/$f" ]; then
      if mkdir -p "$TW_FONT_DIR" && cp "$TW_FONT_SEED/$f" "$TW_FONT_DIR/$f"; then
        echo "Kept $TW_FONT_SEED/$f in $TW_FONT_DIR before the checkout moves past it."
      fi
    fi
    if [ ! -s "$TW_FONT_DIR/$f" ]; then
      echo "::error::$TW_FONT_DIR/$f is missing on the VPS. Copy both Zetta Serif files there from the team Dropbox (see backend/fonts/README.md), then re-run this deploy."
      exit 1
    fi
  done
}

healthy() {  # $1: the image the container must be running (as compose was given it)
  local running
  for _ in $(seq 1 "$TRIES"); do
    running=$(docker inspect -f '{{.Config.Image}}' "$CONTAINER" 2>/dev/null || true)
    if [ "$running" = "$1" ] && curl -fsS -m 10 "$HEALTH_URL" >/dev/null 2>&1; then return 0; fi
    sleep "$PAUSE"
  done
  return 1
}

staging_database() {
  # Keep staging's self-hosted Postgres schema in step with the code. The initdb mount only runs
  # on a fresh Docker volume; these statements are idempotent so deploys can apply additive DDL.
  local db_ok=0
  compose up -d db
  for _ in $(seq 1 "$TRIES"); do
    if compose exec -T db pg_isready -U postgres -d treadwell >/dev/null; then db_ok=1; break; fi
    sleep "$PAUSE"
  done
  [ "$db_ok" = 1 ] || return 1
  # FED FROM THE CHECKOUT, NOT READ THROUGH THE MOUNT. The db container sees schema_pg.sql through
  # a single-file bind mount, and a checkout move replaces the file with a new inode, so the mounted
  # path kept serving the 2026-09-25 copy: every deploy after that applied a stale schema and
  # reported success (found 2026-09-30 when library_labor.favorite never arrived).
  compose exec -T db psql -U postgres -d treadwell -v ON_ERROR_STOP=1 < backend/staging/schema_pg.sql
}

housekeeping() {
  # Each deploy leaves a ~1.7GB image behind, and on 2026-08-11 there were FIFTY of them. AFTER the
  # health check, deliberately: a deploy that failed still has its predecessor to roll back to.
  # Keeps the three newest sha images of THIS app (staging's and production's share the
  # repository), so the documented rollback resolves locally instead of reaching for ghcr.
  #
  # NARROWER THAN IT USED TO BE, on purpose. This box runs ~11 other apps' containers:
  #   * `docker images "$REPO"` and the exact `^$REPO:sha-` match touch this repository only;
  #   * the dangling-image prune is limited to this image's label (the Dockerfile sets it), where
  #     the old bare `docker image prune -f` removed every app's untagged images;
  #   * no `docker builder prune` at all: nothing of ours is ever built here (images come from the
  #     runner), so the build cache on this box belongs to other apps, and emptying it sends their
  #     next build into a cold start on one core, which is the brown-out this pipeline exists to
  #     avoid;
  #   * never `image prune -a` or `system prune`: those reach other apps' images and volumes.
  local keep newest img
  keep=$(docker ps -a --format '{{.Image}}' | sort -u)
  newest=$(docker images "$REPO" --format '{{.CreatedAt}}|{{.Repository}}:{{.Tag}}' \
           | grep "|$REPO:sha-" | sort -r | head -3 | cut -d'|' -f2 || true)
  for img in $(docker images "$REPO" --format '{{.Repository}}:{{.Tag}}' | grep "^$REPO:sha-" || true); do
    if echo "$keep" | grep -qx "$img"; then continue; fi
    if echo "$newest" | grep -qx "$img"; then continue; fi
    docker rmi "$img" >/dev/null 2>&1 || true
  done
  docker image prune -f --filter "label=org.opencontainers.image.title=treadwell-proposal-tool" >/dev/null 2>&1 || true
  df -h / | tail -1
}

run_deploy() {
  local version="sha-${COMMIT:0:12}"
  local image="$REPO:$version" prev_commit prev_image

  # 2. the checkout: the commit must already be on the branch, and the folder must be on it too.
  local on_branch
  on_branch=$(git_in symbolic-ref --quiet --short HEAD || true)
  [ "$on_branch" = "$BRANCH" ] || fail "$APP_DIR is on '${on_branch:-a detached HEAD}', not $BRANCH. Put it back first: sudo git -C $APP_DIR checkout $BRANCH"
  git_in fetch --quiet origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
  git_in merge-base --is-ancestor "$COMMIT" "origin/$BRANCH" || refuse "$COMMIT is not on $BRANCH"
  can_move_to "$COMMIT" || fail "$APP_DIR has commits that are not on origin/$BRANCH; it cannot move to $COMMIT without losing them. Look with: sudo git -C $APP_DIR log origin/$BRANCH..HEAD"
  prev_commit=$(git_in rev-parse HEAD)

  # 3. the font, before anything changes.
  keep_and_check_fonts

  # 4. the image, with a registry credential that lives only as long as this run.
  prev_image=$(docker inspect -f '{{.Config.Image}}' "$CONTAINER" 2>/dev/null || true)
  DOCKER_CONFIG=$(mktemp -d)
  export DOCKER_CONFIG
  trap 'rm -rf "$DOCKER_CONFIG"' EXIT
  printf '%s' "$TOKEN" | docker login ghcr.io -u HDLC01 --password-stdin >/dev/null
  docker pull --quiet "$image"

  # 5. the configuration of exactly that commit, on its branch.
  move_checkout_to "$COMMIT"
  echo "$APP_DIR is at $COMMIT on $BRANCH"
  local self="${BASH_SOURCE[0]}"
  if [ -f "$APP_DIR/deploy/remote-deploy.sh" ] && ! cmp -s "$self" "$APP_DIR/deploy/remote-deploy.sh"; then
    echo "::warning::the installed deploy program differs from deploy/remote-deploy.sh at $COMMIT; re-run deploy/install-deploy-account.sh on the box (deploy/README.md)"
  fi

  # 6. staging's database and schema. A failure here has restarted nothing but the database, so
  # the checkout goes back to where it was and the run ends red.
  if [ "$BRANCH" = staging ] && ! staging_database; then
    move_checkout_to "$prev_commit" || true
    fail "staging database healthcheck or schema apply failed; nothing else was restarted"
  fi

  # 7. up, NEVER a build, and the new image must answer.
  # A failing `up` (a port taken, a bad compose file) is handled like a failed health check: it
  # rolls back too, instead of ending the run with the old container possibly gone.
  local up_ok=1 notify_failed=0
  export TW_IMAGE="$image"
  compose up -d || up_ok=0
  if [ "$BRANCH" = staging ] && [ "$up_ok" = 1 ]; then
    compose exec -T db psql -U postgres -d treadwell -c "notify pgrst, 'reload schema';" || notify_failed=1
  fi
  if [ "$up_ok" != 1 ] || ! healthy "$image"; then
    echo "::error::$LABEL post-deploy healthcheck failed (wanted $image)"
    compose ps || true
    compose logs --tail 60 "$SERVICE" || true
    # 8. roll back to what was running.
    if [ -n "$prev_image" ] && [ "$prev_image" != "$image" ]; then
      echo "rolling back to $prev_image (checkout $prev_commit)"
      move_checkout_to "$prev_commit" || echo "::error::could not put $APP_DIR back on $prev_commit"
      export TW_IMAGE="$prev_image"
      if compose up -d && healthy "$prev_image"; then
        echo "rolled back: $prev_image is serving again"
      else
        echo "::error::the rollback to $prev_image is not healthy either (deploy/README.md, Roll back)"
      fi
    else
      echo "::error::there is no previous container to go back to (or it ran this same image)"
    fi
    exit 1
  fi
  # 9. a bare `docker compose up -d` on the box now starts this image.
  docker tag "$image" "$MOVE"
  echo "$LABEL healthy on $image"

  # 10. housekeeping.
  housekeeping

  if [ "$notify_failed" != 0 ]; then
    fail "staging is healthy on $image, but PostgREST did not take the schema reload (notify pgrst failed)."
  fi
}

run_pdf_smoke() {
  # A handful of tests need LibreOffice, because the PDF every customer receives is produced by
  # `soffice --headless`, not by Word. Installing it on the runner would add minutes to every build,
  # so those tests carry a skipif and were silently skipping in CI AND on the dev box.
  #
  # Runs in a THROWAWAY container from the image staging was just deployed with, with the checkout
  # and the font mounted read-only, so a test run can never disturb the live staging service.
  # It FAILS the run when the check fails or silently skips: staging is deployed and healthy by
  # now, so failing rolls nothing back; it buys a red run somebody notices. The one tolerated
  # non-failure is pip being unable to reach the index (infrastructure, not the product).
  #
  # Inside the container: `set -e` only AFTER the pip block (its `exit 0` is the deliberate skip).
  # test_box_resize.py (size), test_box_move.py (position) and test_docx_merge.py (the cover letter
  # merged onto the front of the proposal) are the files with LibreOffice-gated tests. The gate is
  # `-k "pdf or libreoffice"` (the merge renderer test is named for the renderer), it fails on a
  # skip and on zero passes, and the merge test is asserted BY NAME so a rename breaks loudly.
  local image="$REPO:sha-${COMMIT:0:12}" head smoke
  head=$(git_in rev-parse HEAD)
  [ "$head" = "$COMMIT" ] || refuse "$APP_DIR is at $head, not $COMMIT: a newer staging deploy ran, and its own run checks the PDFs"
  docker image inspect "$image" >/dev/null 2>&1 || fail "$image is not on this box (did the deploy step run?)"
  smoke=$(cat <<'SMOKE'
pip install --quiet --no-input pytest pymupdf >/dev/null 2>&1 || {
  echo "could not install pytest/pymupdf - skipping"; exit 0; }
cd /src/backend
set -e
python -m pytest tests/test_box_resize.py tests/test_box_move.py \
  tests/test_docx_merge.py \
  -q -p no:cacheprovider -p no:warnings
python -m pytest tests/test_box_resize.py tests/test_box_move.py \
  tests/test_docx_merge.py \
  -p no:cacheprovider -p no:warnings -q \
  -k "pdf or libreoffice" 2>&1 | tee /tmp/pdf.out
grep -qE "[0-9]+ passed" /tmp/pdf.out || {
  echo "PDF fidelity tests did not RUN (skipped or missing)"; exit 1; }
if grep -q "skipped" /tmp/pdf.out; then
  echo "a PDF fidelity test SKIPPED in the image that has LibreOffice"
  exit 1
fi
python -m pytest tests/test_docx_merge.py -k libreoffice \
  -p no:cacheprovider -p no:warnings -q 2>&1 | tee /tmp/merge.out
grep -qE "^1 passed" /tmp/merge.out || {
  echo "the cover-letter merge renderer test did not run+pass (renamed? errored?)"
  exit 1; }
SMOKE
)
  docker run --rm \
    -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp \
    -v "$APP_DIR:/src:ro" \
    -v "$FONT_DIR:/usr/share/fonts/truetype/treadwell:ro" \
    "$image" \
    sh -c "$smoke"
}

main() {
  parse_request
  select_environment
  cd "$APP_DIR" 2>/dev/null || fail "$APP_DIR is missing."
  [ -d .git ] || fail "$APP_DIR is not a git checkout."
  [ -f "$COMPOSE_FILE" ] || fail "$APP_DIR is not the proposal tool's $LABEL checkout (no $COMPOSE_FILE)."
  [ -f "$ENV_FILE" ] || fail "$APP_DIR/$ENV_FILE is missing."
  # 1. one at a time.
  take_lock
  case "$VERB" in
    deploy) run_deploy ;;
    pdf-smoke) run_pdf_smoke ;;
  esac
}

# Everything runs from inside main, so bash has parsed the whole file before the checkout can
# replace its own copy of it on disk.
main "$@"
exit 0
