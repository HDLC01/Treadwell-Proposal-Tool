#!/usr/bin/env bash
#
# Treadwell Proposal Tool - give the GitHub deploy its own locked-down box account. Run it ON the
# box, as root. Safe to run again: every step checks first and skips or rewrites what is there.
#
# The Deploy workflow (.github/workflows/deploy.yml) logs in with the VPS_DEPLOY_USER /
# VPS_DEPLOY_KEY secrets. This script makes that login worth exactly one thing: running
# deploy/remote-deploy.sh, which deploys a commit that is already on staging or main.
#
#   1. the account (default `tooldeploy`): created with a disabled password when missing; refused
#      when it is root, in the docker group (that is root on this box) or in a sudo/admin/wheel
#      group; its login shell must be a real shell, because sshd runs the forced command through it;
#   2. /usr/local/sbin/treadwell-tool-deploy: a root-owned COPY (0755) of the remote-deploy.sh that
#      sits next to this script, so a commit can never change what the key runs until a person
#      re-runs this script;
#   3. /etc/sudoers.d/treadwell-tool-deploy: the account may run that one program as root, with
#      no arguments (the ""), keeping only SSH_ORIGINAL_COMMAND (the one-line request it parses).
#      Checked with `visudo -cf` before it is installed and with `visudo -c` after;
#   4. the account's authorized_keys: with --deploy-key FILE (the PUBLIC half), replaced by the one
#      line below; without it, every key already there must be forced the same way:
#          restrict,command="sudo -n /usr/local/sbin/treadwell-tool-deploy" ssh-ed25519 AAAA... tool-deploy
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
#     scp deploy/remote-deploy.sh deploy/install-deploy-account.sh tool-deploy.pub treadwell-vps:/root/tool-deploy-setup/
#     ssh treadwell-vps 'bash /root/tool-deploy-setup/install-deploy-account.sh --deploy-key /root/tool-deploy-setup/tool-deploy.pub'
# Later, after deploy/remote-deploy.sh changes, from the staging checkout:
#     ssh treadwell-vps 'bash /opt/treadwell-staging/deploy/install-deploy-account.sh'
#
# Options:
#   --account NAME          the deploy account (default tooldeploy)
#   --deploy-key FILE       the deploy key's PUBLIC half; replaces the account's keys with it
#   --print-sudoers         print the sudoers rule and stop (no root needed, nothing changed)
#   --print-key-line FILE   print the authorized_keys line for FILE and stop (likewise)
set -euo pipefail

ACCOUNT=tooldeploy
DEPLOY_BIN=/usr/local/sbin/treadwell-tool-deploy
SUDOERS=/etc/sudoers.d/treadwell-tool-deploy
FORCED='restrict,command="sudo -n /usr/local/sbin/treadwell-tool-deploy"'
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SOURCE="$HERE/remote-deploy.sh"

say() { printf '%s\n' "$*"; }
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }

sudoers_rule() {
  cat <<RULE
# Treadwell Proposal Tool (deploy/install-deploy-account.sh): the GitHub deploy account runs ONE
# program as root, with no arguments (the ""), keeping only SSH_ORIGINAL_COMMAND, the one-line
# request that program parses and never runs.
Defaults:$ACCOUNT env_keep += "SSH_ORIGINAL_COMMAND"
$ACCOUNT ALL=(root) NOPASSWD: $DEPLOY_BIN ""
RULE
}

key_line() {  # the authorized_keys line for the public key in $1
  local pub
  [ -f "$1" ] || stop "$1 does not exist."
  if grep -q 'PRIVATE KEY' "$1"; then
    stop "$1 is a PRIVATE key. Pass the .pub file; the private half goes into the VPS_DEPLOY_KEY secret only."
  fi
  pub=$(grep -m1 -E '^ssh-ed25519 [A-Za-z0-9+/=]+( [A-Za-z0-9@._-]+)?$' "$1" || true)
  [ -n "$pub" ] || stop "$1 is not an ed25519 public key (one line: ssh-ed25519 AAAA... comment)."
  printf '%s %s\n' "$FORCED" "$pub"
}

DEPLOY_KEY=""
PRINT=""
PRINT_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --account) shift; ACCOUNT="${1:-}" ;;
    --deploy-key) shift; DEPLOY_KEY="${1:-}"; [ -n "$DEPLOY_KEY" ] || stop "--deploy-key needs a file" ;;
    --print-sudoers) PRINT=sudoers ;;
    --print-key-line) shift; PRINT=key; PRINT_FILE="${1:-}" ;;
    *) stop "unknown option $1 (see the top of this script)" ;;
  esac
  shift
done
[[ "$ACCOUNT" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || stop "'$ACCOUNT' is not a valid account name."
[ "$ACCOUNT" != root ] || stop "the deploy account must never be root."

case "$PRINT" in
  sudoers) sudoers_rule; exit 0 ;;
  key) key_line "$PRINT_FILE"; exit 0 ;;
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
say "[3/5] $SUDOERS lets $ACCOUNT run $DEPLOY_BIN, with no arguments, as root."

# ── 4. the key ───────────────────────────────────────────────────────────────────────────────
home=$(getent passwd "$ACCOUNT" | cut -d: -f6)
ssh_dir="$home/.ssh"
keys="$ssh_dir/authorized_keys"
if [ -n "$DEPLOY_KEY" ]; then
  line=$(key_line "$DEPLOY_KEY")
  install -d -o "$ACCOUNT" -g "$ACCOUNT" -m 0700 "$ssh_dir"
  printf '%s\n' "$line" > "$keys"
  chown "$ACCOUNT": "$keys"
  chmod 600 "$keys"
  say "[4/5] $ACCOUNT's authorized_keys is now the one forced deploy key."
fi
if [ -f "$keys" ]; then
  # Every key of this account must be forced to the deploy program, so none of them is a shell.
  if grep -vE '^[[:space:]]*(#|$)' "$keys" | grep -vqF "$FORCED "; then
    stop "$keys holds a key that is not forced to $DEPLOY_BIN. Remove it, or run this again with --deploy-key FILE."
  fi
  [ -n "$DEPLOY_KEY" ] || say "[4/5] every key of $ACCOUNT is forced to $DEPLOY_BIN."
else
  say "[4/5] $ACCOUNT has no deploy key yet. Run this again with --deploy-key FILE (the .pub), or put"
  say "      exactly this line, with the public key filled in, in $keys:"
  say "      $FORCED ssh-ed25519 AAAA... tool-deploy"
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
say "Next (deploy/README.md): the GitHub repository secrets VPS_DEPLOY_USER = $ACCOUNT,"
say "VPS_DEPLOY_KEY = the deploy key's private half, VPS_FINGERPRINT = the SHA256:... above."
