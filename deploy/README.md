# The GitHub deploy's box account

The Deploy workflow (`.github/workflows/deploy.yml`) used to log in to the VPS as **root**, with a
key that would run any script it was sent. Repository secrets reach a workflow run on any branch of
this repository, so that key was a root shell on a box that serves a dozen other sites.

Now it logs in as an account of the proposal tool's own (suggested name `tooldeploy`), and that
account's one key can run one program:

| What | Where |
|---|---|
| The account | `tooldeploy`: no password, not in the `docker` group (that is root on this box), not in `sudo`/`admin`/`wheel` |
| Its key | one line in its `authorized_keys`: `restrict,command="sudo -n /usr/local/sbin/treadwell-tool-deploy" ssh-ed25519 AAAA... tool-deploy`. `restrict` turns off forwarding and the terminal; `command=` means whatever the client asks for, this program runs instead. |
| The program | `/usr/local/sbin/treadwell-tool-deploy`, a root-owned **copy** of `deploy/remote-deploy.sh`. A commit cannot change what the key runs until a person re-runs the install script. |
| sudo | `/etc/sudoers.d/treadwell-tool-deploy`: that account may run that program as root, **with no arguments**, keeping only `SSH_ORIGINAL_COMMAND` |
| The request | the workflow sends one line, `deploy <staging\|main> <commit> <job token>` or `pdf-smoke staging <commit>`. The program matches it with a regular expression and never runs it. |
| Secrets | `VPS_HOST`, `VPS_PORT` (as before), `VPS_DEPLOY_USER`, `VPS_DEPLOY_KEY`, `VPS_FINGERPRINT` (new) |
| Installer | `deploy/install-deploy-account.sh` (idempotent; never touches packages, the firewall or a container) |

The box is reached only as `ssh treadwell-vps`. No address, port or key file name belongs in this
repo; `backend/tests/test_no_infra_in_repo.py` fails the build if one appears. Every `ssh
treadwell-vps '...'` below already runs as root (the alias's key is forced through the box's ops
wrapper), so there is no `sudo` in front.

## What a deploy does on the box

`deploy staging <commit> <token>` works in `/opt/treadwell-staging` (branch `staging`, compose file
`docker-compose.staging.yml`, health on `127.0.0.1:8889/healthz`); `deploy main ...` works in
`/opt/treadwell` (branch `main`, `docker-compose.yml`, `127.0.0.1:8888/healthz`). In order:

1. **One deploy at a time on the box.** A lock (`/run/lock/treadwell-tool-deploy.lock`) is shared
   by staging and production: they share the image store, the font folder and the housekeeping,
   and the workflow's concurrency group is per branch.
2. **The checkout.** It must be on its branch (`staging` / `main`). The branch is fetched, and a
   commit that is not on it is refused. A checkout holding commits that are not on GitHub is
   refused too, rather than losing them.
3. **The font.** The checkout's copy of Zetta Serif is kept in `/opt/treadwell-fonts`, and the
   deploy stops while either file is missing there (`backend/fonts/README.md`).
4. **The image.** `docker login` with the job's short-lived token in a throw-away `DOCKER_CONFIG`
   (root's `~/.docker` is never read or written), then `docker pull` of exactly `sha-<12>`. A failed
   pull changes nothing.
5. **The checkout moves to exactly that commit and stays on its branch**: a fast-forward, or
   `git reset --keep` when an older commit of the branch is deployed again. Never a detached HEAD,
   because `deploy/ship.sh` and people still run `git pull --ff-only` in these folders.
6. **Staging only:** its Postgres up, `pg_isready`, `backend/staging/schema_pg.sql` fed from the
   checkout into `psql -v ON_ERROR_STOP=1`. A failure here puts the checkout back and stops; only
   the database container was touched.
7. `docker compose up -d` with `TW_IMAGE=<that sha image>`: **never a build**. Staging then tells
   PostgREST to reload its schema.
8. **Health:** `/healthz` must answer and the container must be running the new image.
   **When that fails, it rolls back by itself**: the previous checkout and the previous image go
   back up, their health is checked, and the run still ends red.
9. The moving tag (`:staging` / `:prod`) is re-pointed at the healthy image on the box, so a bare
   `docker compose up -d` there starts what was deployed.
10. **Housekeeping, this app only:** the three newest `treadwell-proposal-tool:sha-*` images are
    kept, older ones not used by a container are removed, and the dangling-image prune is limited
    to this image's label. There is no `docker builder prune` any more: nothing of ours is built on
    the box, so its build cache belongs to the other apps, and emptying it sends their next build
    into a cold start on one core.

`pdf-smoke staging <commit>` (the second staging step) runs the LibreOffice tests in a throw-away
container of the image staging was just deployed with, with the staging checkout and the font
mounted read-only. It refuses when the staging checkout is no longer at that commit.

## One-time setup (Hanz) — BEFORE the PR that adds this is merged

Merging into `staging` starts a staging deploy that uses the new secrets, so the box and the secrets
come first. Steps 1 to 3 change nothing that runs today: the old root deploy keeps working until
the PR is merged.

1. **The deploy key, on your PC, in Git Bash** (PowerShell 5.1 drops the empty `''`), in this repo's
   folder (or the PR's worktree, so the two scripts below are the PR's versions):

   ```bash
   ssh-keygen -t ed25519 -N '' -C tool-deploy -f tool-deploy
   ```

   A key of the proposal tool's own: never the BD CRM's deploy key, never your ops key.

2. **The account, the program, sudo and the key, on the box:**

   ```bash
   ssh treadwell-vps 'install -d -m 700 /root/tool-deploy-setup'
   scp deploy/remote-deploy.sh deploy/install-deploy-account.sh tool-deploy.pub treadwell-vps:/root/tool-deploy-setup/
   ssh treadwell-vps 'bash /root/tool-deploy-setup/install-deploy-account.sh --deploy-key /root/tool-deploy-setup/tool-deploy.pub'
   ```

   It prints each step (`[1/5]` to `[5/5]`), any `WARNING` (for example an sshd `AllowUsers` line
   that leaves the account out: add it there, `sshd -t && systemctl reload ssh`), and the box's
   host key fingerprints. Keep the `SHA256:...` of the ECDSA line for step 4. Then:

   ```bash
   ssh treadwell-vps 'rm -rf /root/tool-deploy-setup'
   ssh treadwell-vps 'git -C /opt/treadwell symbolic-ref --short HEAD; git -C /opt/treadwell-staging symbolic-ref --short HEAD'
   ```

   The second line must print `main` and then `staging`: the deploy refuses a checkout that is not
   on its branch.

3. **Try the key before GitHub has it.** From the PC, with the new key and account in place of the
   alias's own (`-o User=` on the command line wins over the alias):

   ```bash
   ssh -i ./tool-deploy -o IdentitiesOnly=yes -o User=tooldeploy treadwell-vps 'whoami'
   ssh -i ./tool-deploy -o IdentitiesOnly=yes -o User=tooldeploy treadwell-vps 'pdf-smoke staging 0000000000000000000000000000000000000000'
   ```

   The first must answer `refusing: the request must be exactly one line ...` (the key runs the
   program, not `whoami`). The second must answer `refusing: /opt/treadwell-staging is at <sha>,
   not 0000...`: reading that root-owned checkout proves sudo worked. Anything else (a shell, a
   password prompt, `Permission denied (publickey)`, `sudo: a password is required`) means step 2
   did not finish: see "When something goes wrong".

4. **The GitHub secrets.** From the same folder (the values never appear on screen or in a file):

   ```bash
   gh secret set VPS_DEPLOY_USER -R HDLC01/Treadwell-Proposal-Tool --body tooldeploy
   gh secret set VPS_DEPLOY_KEY  -R HDLC01/Treadwell-Proposal-Tool < tool-deploy
   gh secret set VPS_FINGERPRINT -R HDLC01/Treadwell-Proposal-Tool --body 'SHA256:<the ECDSA value from step 2>'
   rm tool-deploy tool-deploy.pub
   ```

   `VPS_HOST` and `VPS_PORT` exist already and stay as they are. Only the `SHA256:...` part goes
   into `VPS_FINGERPRINT`, not the `(ECDSA)` label. If the first deploy stops with
   `ssh: handshake failed: ssh: host key fingerprint mismatch`, put the ED25519 value in instead
   (the action checks whichever key type it negotiated).

5. **Merge the PR into `staging`** and watch Actions -> Deploy: both staging steps must be green.
   The production job uses the same account and secrets the next time `staging` is promoted to
   `main` (after the `production` environment approval, as before).

6. **Retire root's deploy key, after staging AND production have each deployed green once:**

   ```bash
   ssh treadwell-vps 'cd ~root/.ssh && grep -n github-actions-treadwell-ci authorized_keys'
   ```

   Delete that line (the key commented `github-actions-treadwell-ci 6aefcab`) from root's
   `authorized_keys`, then delete the old secrets:

   ```bash
   gh secret delete VPS_USER    -R HDLC01/Treadwell-Proposal-Tool
   gh secret delete VPS_SSH_KEY -R HDLC01/Treadwell-Proposal-Tool
   ```

   From then on nothing in this repository logs in as root, and root SSH login can be switched off
   as far as the proposal tool is concerned.

## After `deploy/remote-deploy.sh` changes

The box runs its installed copy, not the file in the checkout. A deploy prints
`::warning::the installed deploy program differs from deploy/remote-deploy.sh at <commit>` when
they differ. Once the change is on staging, re-install from the staging checkout:

```bash
ssh treadwell-vps 'bash /opt/treadwell-staging/deploy/install-deploy-account.sh'
```

Without `--deploy-key` it keeps the account's key and only checks that every key is forced.

## Roll back

A deploy whose health check fails rolls back to the previous image and checkout by itself. To go
back by hand to an older build (every build has its own tag; the box keeps the last three):

```bash
ssh treadwell-vps 'docker images ghcr.io/hdlc01/treadwell-proposal-tool'
ssh treadwell-vps 'cd /opt/treadwell && TW_IMAGE=ghcr.io/hdlc01/treadwell-proposal-tool:sha-<old> docker compose up -d'
ssh treadwell-vps 'cd /opt/treadwell-staging && TW_IMAGE=ghcr.io/hdlc01/treadwell-proposal-tool:sha-<old> docker compose -f docker-compose.staging.yml up -d'
```

The next Deploy run goes forward again. Re-running an older Deploy from the Actions tab works too:
the box moves the checkout back to that commit with `git reset --keep`, still on its branch.

## Undo this change

1. Revert the PR (into `staging`, then promote). The workflow goes back to `VPS_USER` /
   `VPS_SSH_KEY`, so this only works while those secrets and root's old key still exist (step 6
   above not done yet). After step 6, re-create them first.
2. On the box:

   ```bash
   ssh treadwell-vps 'rm -f /etc/sudoers.d/treadwell-tool-deploy /usr/local/sbin/treadwell-tool-deploy && visudo -c && deluser --remove-home tooldeploy'
   ```

3. Delete `VPS_DEPLOY_USER`, `VPS_DEPLOY_KEY` and `VPS_FINGERPRINT` in GitHub.

## When something goes wrong

- **`refusing: <commit> is not on staging`.** The commit is not on the branch on GitHub (a
  force-push?). Run Deploy again from the branch.
- **`... is on 'x', not staging` (or `main`).** Someone switched the box's checkout to another
  branch. `ssh treadwell-vps 'git -C /opt/treadwell-staging checkout staging'`, then re-run.
- **`... has commits that are not on origin/staging`.** Someone committed on the box. Look with
  `ssh treadwell-vps 'git -C /opt/treadwell-staging log origin/staging..HEAD'`; move them to a PR
  or drop them, then re-run.
- **`post-deploy healthcheck failed`.** The step prints `docker compose ps` and the app's last log
  lines, then rolls back ("rolled back: ... is serving again"). If it says the rollback is not
  healthy either, or there is no previous container, the site is down: see "Roll back".
- **`another proposal-tool deploy held the lock`.** The other environment's deploy took more than
  20 minutes. Re-run once it has finished.
- **`Permission denied (publickey)`.** The account is missing from an sshd `AllowUsers` line (the
  install script warns about it), or `VPS_DEPLOY_KEY` is not the private half of the key installed
  in step 2.
- **`sudo: a password is required`.** `/etc/sudoers.d/treadwell-tool-deploy` is missing or names
  another account: re-run the install script (step 2, or "After `deploy/remote-deploy.sh`
  changes").
- **`handshake failed` / `fingerprint mismatch`.** `VPS_FINGERPRINT` is the other host key type
  (step 4), or the box's host key changed: check on the box before you change the secret.
- **The pull answers 403 or "denied".** The job token cannot read the package: GitHub -> HDLC01's
  Packages -> `treadwell-proposal-tool` -> Package settings -> Manage Actions access must list this
  repository. Nothing on the box has changed when this happens.
