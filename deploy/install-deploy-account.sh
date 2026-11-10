#!/usr/bin/env bash
#
# Treadwell Proposal Tool - give the GitHub deploy its own locked-down box account. Run it ON the
# box, as root. Safe to run again: every step checks first and skips or rewrites what is there.
#
# The Deploy workflow (.github/workflows/deploy.yml) logs in with the VPS_DEPLOY_USER /
# VPS_DEPLOY_KEY secrets, held as ENVIRONMENT secrets: the `staging` environment holds the staging
# key, the `Production` environment the production key (never one repository-level key: those reach
# a workflow on any branch). This script makes each key worth exactly one thing: running
# deploy/remote-deploy.sh for ITS environment, which deploys a commit that is already on that
# branch. The staging key can never deploy production.
#
#   1. the account (default `tooldeploy`): created with a disabled password when missing; refused
#      when it is root, in the docker group (that is root on this box) or in a sudo/admin/wheel
#      group; its login shell must be a real shell, because sshd runs the forced command through it;
#   2. /usr/local/sbin/treadwell-tool-deploy: a root-owned COPY (0755) of the remote-deploy.sh that
#      sits next to this script, so a commit can never change what a key runs until a person
#      re-runs this script;
#   3. /etc/sudoers.d/treadwell-tool-deploy: the account may run that one program as root with
#      exactly `staging` or exactly `main` as its argument (no other argument list), keeping only
#      SSH_ORIGINAL_COMMAND (the one-line request it parses). Checked with `visudo -cf` before it
#      is installed and with `visudo -c` after;
#   4. the account's authorized_keys: one key per environment, each forced to the program WITH
#      its environment, which the program checks the request against:
#          restrict,command="sudo -n /usr/local/sbin/treadwell-tool-deploy staging" ssh-ed25519 AAAA... tool-deploy-staging
#          restrict,command="sudo -n /usr/local/sbin/treadwell-tool-deploy main" ssh-ed25519 AAAA... tool-deploy-main
#      --staging-key FILE / --main-key FILE (PUBLIC halves) write that environment's line and keep
#      the other's. Every key there must be one of these two forced lines, and the two keys must
#      differ (one key for both would let the staging copy deploy production);
#   5. a check that sshd lets the account in at all (AllowUsers / AllowGroups), and the host key
#      fingerprints for the VPS_FINGERPRINT secret.
#
# Unlike deploy/install-vps.sh (the original whole-box setup), nothing here installs packages,
# builds an image, starts a container or touches the firewall. In particular it never opens port
# 22: SSH moved off it on 2026-09-28.
#
# Before this change is merged, the box has no checkout holding these files, so copy both files
# over into a folder only root can read and run them there (deploy/README.md, "One-time setup"):
#     ssh treadwell-vps 'install -d -m 700 /root/tool-deploy-setup'
#     scp deploy/remote-deploy.sh deploy/install-deploy-account.sh tool-deploy-staging.pub tool-deploy-main.pub treadwell-vps:/root/tool-deploy-setup/
#     ssh treadwell-vps 'bash /root/tool-deploy-setup/install-deploy-account.sh --staging-key /root/tool-deploy-setup/tool-deploy-staging.pub --main-key /root/tool-deploy-setup/tool-deploy-main.pub'
# Later, after deploy/remote-deploy.sh changes, from the staging checkout:
#     ssh treadwell-vps 'bash /opt/treadwell-staging/deploy/install-deploy-account.sh'
#
# Options:
#   --account NAME          the deploy account (default tooldeploy)
#   --staging-key FILE      the staging deploy key's PUBLIC half (its line replaces staging's)
#   --main-key FILE         the production deploy key's PUBLIC half (likewise, for main)
#   --print-sudoers         print the sudoers rule and stop (no root needed, nothing changed)
#   --print-key-line ENV FILE
#                           print the authorized_keys line of FILE for ENV (staging or main) and
#                           stop (likewise)
#   --check-keys FILE       check an authorized_keys file the way step 4 does, and stop (likewise)
set -euo pipefail

ACCOUNT=tooldeploy
DEPLOY_BIN=/usr/local/sbin/treadwell-tool-deploy
SUDOERS=/etc/sudoers.d/treadwell-tool-deploy
ENVIRONMENTS="staging main"
# The forced command of the key for environment $1; the program refuses any other environment.
forced() { printf 'restrict,command="sudo -n %s %s"' "$DEPLOY_BIN" "$1"; }
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SOURCE="$HERE/remote-deploy.sh"

say() { printf '%s\n' "$*"; }
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }

sudoers_rule() {
  cat <<RULE
# Treadwell Proposal Tool (deploy/install-deploy-account.sh): the GitHub deploy account runs ONE
# program as root, with exactly "staging" or exactly "main" as its argument (each deploy key is
# forced to one of them), keeping only SSH_ORIGINAL_COMMAND, the one-line request that program
# parses and never runs.
Defaults:$ACCOUNT env_keep += "SSH_ORIGINAL_COMMAND"
$ACCOUNT ALL=(root) NOPASSWD: $DEPLOY_BIN staging, $DEPLOY_BIN main
RULE
}

valid_env() { case "$1" in staging|main) return 0 ;; *) return 1 ;; esac; }

key_line() {  # the authorized_keys line for environment $1 and the public key in $2
  local pub
  valid_env "$1" || stop "'$1' is not an environment: staging or main."
  [ -f "$2" ] || stop "$2 does not exist."
  if grep -q 'PRIVATE KEY' "$2"; then
    stop "$2 is a PRIVATE key. Pass the .pub file; the private half goes into the $1 environment's VPS_DEPLOY_KEY secret only."
  fi
  pub=$(grep -m1 -E '^ssh-ed25519 [A-Za-z0-9+/=]+( [A-Za-z0-9@._-]+)?$' "$2" || true)
  [ -n "$pub" ] || stop "$2 is not an ed25519 public key (one line: ssh-ed25519 AAAA... comment)."
  printf '%s %s\n' "$(forced "$1")" "$pub"
}

# The lines of file $2 that START with environment $1's forced command. A forced command that only
# appears later in a line (say, in the comment of an unforced key) does not count.
lines_for() { awk -v p="$(forced "$1") " 'index($0, p) == 1' "$2"; }
# The lines on stdin that start with neither environment's forced command.
others() { awk -v s="$(forced staging) " -v m="$(forced main) " 'index($0, s) != 1 && index($0, m) != 1'; }

# The key material of each ed25519 line on stdin.
key_blobs() { awk '{ for (i = 1; i <= NF; i++) if ($i == "ssh-ed25519") { print $(i + 1); break } }'; }

check_keys() {  # every key line in file $1 is one environment's forced line; one per environment, all different
  local rest env n total distinct
  rest=$(grep -vE '^[[:space:]]*(#|$)' "$1" | others || true)
  for env in $ENVIRONMENTS; do
    n=$(lines_for "$env" "$1" | grep -c . || true)
    [ "${n:-0}" -le 1 ] || stop "$1 holds $n keys for $env; keep one."
  done
  if [ -n "${rest//[[:space:]]/}" ]; then
    stop "$1 holds a key that is not forced to $DEPLOY_BIN with its environment (staging or main): an older single-key line, or a shell. Run this again with --staging-key FILE --main-key FILE."
  fi
  total=$(grep -vE '^[[:space:]]*(#|$)' "$1" | key_blobs | grep -c . || true)
  distinct=$(grep -vE '^[[:space:]]*(#|$)' "$1" | key_blobs | sort -u | grep -c . || true)
  [ "$total" = "$distinct" ] \
    || stop "$1 uses ONE key for both environments: then the staging copy could deploy production. Make a key per environment."
}

STAGING_KEY=""
MAIN_KEY=""
PRINT=""
PRINT_ENV=""
PRINT_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --account) shift; ACCOUNT="${1:-}" ;;
    --staging-key) shift; STAGING_KEY="${1:-}"; [ -n "$STAGING_KEY" ] || stop "--staging-key needs a file" ;;
    --main-key) shift; MAIN_KEY="${1:-}"; [ -n "$MAIN_KEY" ] || stop "--main-key needs a file" ;;
    --deploy-key) stop "--deploy-key is gone: one key for both environments let staging deploy production. Pass --staging-key FILE and --main-key FILE." ;;
    --print-sudoers) PRINT=sudoers ;;
    --check-keys) shift; PRINT=check; PRINT_FILE="${1:-}" ;;
    --print-key-line) shift; PRINT=key; PRINT_ENV="${1:-}"; [ $# -gt 0 ] && shift; PRINT_FILE="${1:-}" ;;
    *) stop "unknown option $1 (see the top of this script)" ;;
  esac
  [ $# -gt 0 ] && shift
done
[[ "$ACCOUNT" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || stop "'$ACCOUNT' is not a valid account name."
[ "$ACCOUNT" != root ] || stop "the deploy account must never be root."

case "$PRINT" in
  sudoers) sudoers_rule; exit 0 ;;
  key) key_line "$PRINT_ENV" "$PRINT_FILE"; exit 0 ;;
  check) [ -f "$PRINT_FILE" ] || stop "$PRINT_FILE does not exist."; check_keys "$PRINT_FILE"; say "$PRINT_FILE: every key is forced to its own environment."; exit 0 ;;
esac

# Everything below changes accounts, sudoers and a program root runs.
[ "$(id -u)" -eq 0 ] || stop "run this as root (through ssh treadwell-vps, or with sudo)."
[ -f "$SOURCE" ] || stop "$SOURCE is missing: keep remote-deploy.sh next to this script."
bash -n "$SOURCE" || stop "$SOURCE does not parse; not installing it."
grep -q '^DEPLOY_RE=' "$SOURCE" || stop "$SOURCE is not the proposal tool's deploy program."
for tool in adduser visudo flock git docker curl; do
  command -v "$tool" >/dev/null 2>&1 || stop "$tool is not installed on this box."
done

# ── 1. the account ───────────────────────────────────────────────────────────────────────────
if id "$ACCOUNT" >/dev/null 2>&1; then
  say "[1/5] the account $ACCOUNT exists."
else
  # --disabled-password, not a locked one: sshd refuses even key logins for a `!`-locked account
  # when PAM is off, and the account never needs a password.
  adduser --disabled-password --gecos "" "$ACCOUNT" >/dev/null
  say "[1/5] created the account $ACCOUNT (no password)."
fi
[ "$(id -u "$ACCOUNT")" != 0 ] || stop "$ACCOUNT has uid 0: that is root under another name."
groups_of=" $(id -nG "$ACCOUNT") "
case "$groups_of" in
  *" docker "*) stop "$ACCOUNT is in the docker group (that is root on this box). Remove it: gpasswd -d $ACCOUNT docker" ;;
esac
case "$groups_of" in
  *" sudo "*|*" admin "*|*" wheel "*|*" root "*)
    stop "$ACCOUNT is in a group that may use sudo for anything (or root's). Remove it; it gets one sudoers rule here." ;;
esac
shell=$(getent passwd "$ACCOUNT" | cut -d: -f7)
case "$shell" in
  */nologin|*/false|"") stop "$ACCOUNT's shell is '${shell:-none}'. sshd runs the forced command through the login shell, so set one: usermod -s /bin/bash $ACCOUNT (the key still cannot open a shell)." ;;
esac

# ── 2. the program ───────────────────────────────────────────────────────────────────────────
install -o root -g root -m 0755 "$SOURCE" "$DEPLOY_BIN"
say "[2/5] installed $DEPLOY_BIN from $SOURCE."

# ── 3. the sudoers rule ──────────────────────────────────────────────────────────────────────
rule=$(mktemp)
sudoers_rule > "$rule"
visudo -cf "$rule" >/dev/null || { rm -f "$rule"; stop "the sudoers rule did not validate."; }
install -o root -g root -m 0440 "$rule" "$SUDOERS"
rm -f "$rule"
if ! visudo -c >/dev/null 2>&1; then
  rm -f "$SUDOERS"
  stop "sudo's whole configuration did not validate with $SUDOERS in it; removed it again."
fi
say "[3/5] $SUDOERS lets $ACCOUNT run '$DEPLOY_BIN staging' and '$DEPLOY_BIN main', nothing else, as root."

# ── 4. the key ───────────────────────────────────────────────────────────────────────────────
home=$(getent passwd "$ACCOUNT" | cut -d: -f6)
ssh_dir="$home/.ssh"
keys="$ssh_dir/authorized_keys"
if [ -n "$STAGING_KEY$MAIN_KEY" ]; then
  # The new file: the given environment(s)' lines, and the other environment's existing line kept.
  new=$(mktemp)
  for env in $ENVIRONMENTS; do
    file=$STAGING_KEY; [ "$env" = main ] && file=$MAIN_KEY
    if [ -n "$file" ]; then
      key_line "$env" "$file" >> "$new"
    elif [ -f "$keys" ]; then
      lines_for "$env" "$keys" >> "$new" || true
    fi
  done
  ( check_keys "$new" ) || { rm -f "$new"; exit 1; }
  install -d -o "$ACCOUNT" -g "$ACCOUNT" -m 0700 "$ssh_dir"
  install -o "$ACCOUNT" -g "$ACCOUNT" -m 0600 "$new" "$keys"
  rm -f "$new"
  say "[4/5] $ACCOUNT's authorized_keys was rewritten with the forced deploy key(s) given."
fi
if [ -f "$keys" ]; then
  # Every key of this account must be forced to the deploy program with its environment, so none of
  # them is a shell and the staging key never reaches production.
  check_keys "$keys"
  for env in $ENVIRONMENTS; do
    lines_for "$env" "$keys" | grep -q . || say "WARNING: $ACCOUNT has no $env key yet; that environment cannot deploy. Run this again with --$env-key FILE."
  done
  say "[4/5] every key of $ACCOUNT is forced to $DEPLOY_BIN with its own environment."
else
  say "[4/5] $ACCOUNT has no deploy keys yet. Run this again with --staging-key FILE --main-key FILE"
  say "      (the .pub files), or put exactly these lines, with the public keys filled in, in $keys:"
  for env in $ENVIRONMENTS; do say "      $(forced "$env") ssh-ed25519 AAAA... tool-deploy-$env"; done
fi

# ── 5. can sshd let it in? ───────────────────────────────────────────────────────────────────
if command -v sshd >/dev/null 2>&1; then
  allow_users=$(sshd -T 2>/dev/null | awk '$1 == "allowusers" { $1 = ""; print }' | tr '\n' ' ')
  allow_groups=$(sshd -T 2>/dev/null | awk '$1 == "allowgroups" { $1 = ""; print }' | tr '\n' ' ')
  if [ -n "${allow_users// /}" ] && ! printf ' %s ' "$allow_users" | grep -q " $ACCOUNT "; then
    say "WARNING: sshd has AllowUsers ($allow_users) without $ACCOUNT, so the deploy cannot log in."
    say "         Add $ACCOUNT to that line in the sshd config, then: sshd -t && systemctl reload ssh"
  fi
  if [ -n "${allow_groups// /}" ]; then
    say "NOTE: sshd has AllowGroups ($allow_groups); $ACCOUNT is in:$groups_of"
  fi
fi
say "[5/5] the host key fingerprints (one goes into the VPS_FINGERPRINT secret, ECDSA first):"
for f in /etc/ssh/ssh_host_ecdsa_key.pub /etc/ssh/ssh_host_ed25519_key.pub; do
  if [ -f "$f" ]; then say "      $(ssh-keygen -l -E sha256 -f "$f" | awk '{print $2, $NF}')"; fi
done

say ""
say "Next (deploy/README.md, step 4): ENVIRONMENT secrets, never repository secrets. In BOTH the"
say "staging and the Production environment: VPS_DEPLOY_USER = $ACCOUNT, VPS_FINGERPRINT = the"
say "SHA256:... above; VPS_DEPLOY_KEY = the staging key's private half in staging ONLY, the main"
say "key's private half in Production ONLY. Deployment branches: staging -> staging, Production -> main."
