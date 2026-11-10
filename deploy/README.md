# The GitHub deploy's box account

The Deploy workflow (`.github/workflows/deploy.yml`) used to log in to the VPS as **root**, with a
key that would run any script it was sent. Repository secrets reach a workflow run on any branch of
this repository, so that key was a root shell on a box that serves a dozen other sites.

Now it logs in as an account of the proposal tool's own (suggested name `tooldeploy`) with **one
key per environment**, and each key can run one program for its own environment only:

| What | Where |
|---|---|
| The account | `tooldeploy`: no password, not in the `docker` group (that is root on this box), not in `sudo`/`admin`/`wheel` |
| Its keys | two lines in its `authorized_keys`, `restrict,command="sudo -n /usr/local/sbin/treadwell-tool-deploy staging" ssh-ed25519 AAAA... tool-deploy-staging` and `restrict,command="sudo -n /usr/local/sbin/treadwell-tool-deploy main" ssh-ed25519 AAAA... tool-deploy-main` (two different keys). `restrict` turns off forwarding and the terminal; `command=` means whatever the client asks for, this program runs instead, with that key's environment. |
| The program | `/usr/local/sbin/treadwell-tool-deploy`, a root-owned **copy** of `deploy/remote-deploy.sh`. A commit cannot change what a key runs until a person re-runs the install script. It refuses a request for any environment but its key's: **the staging key can never deploy production.** |
| sudo | `/etc/sudoers.d/treadwell-tool-deploy`: that account may run that program as root with exactly `staging` or exactly `main` as its argument, keeping only `SSH_ORIGINAL_COMMAND` |
| The request | the workflow sends one line, `deploy <staging\|main> <commit> sha256:<digest> <job token>` or `pdf-smoke staging <commit> sha256:<digest>`. The program matches it with a regular expression and never runs it. |
| The image | always by **digest** (`ghcr.io/hdlc01/treadwell-proposal-tool@sha256:...`), the build job's output. A tag is a name anything allowed to push the package can re-point; a digest is the content. The build also records a signed provenance attestation for it. |
| Secrets | `VPS_HOST`, `VPS_PORT` (as before); `VPS_DEPLOY_USER`, `VPS_DEPLOY_KEY`, `VPS_FINGERPRINT` as **environment** secrets (step 4), never repository secrets |
| Installer | `deploy/install-deploy-account.sh` (idempotent; never touches packages, the firewall or a container) |

The box is reached only as `ssh treadwell-vps`. No address, port or key file name belongs in this
repo; `backend/tests/test_no_infra_in_repo.py` fails the build if one appears. Every `ssh
treadwell-vps '...'` below already runs as root (the alias's key is forced through the box's ops
wrapper), so there is no `sudo` in front.

## Why environment secrets, two keys and a digest

A **repository** secret reaches a workflow run on **any** branch, so anyone (or any agent) that can
push a branch could read one key that deploys both environments, send `deploy main ...` and skip the
production reviewer. Three things close that, and each needs the others:

- **Environment secrets with branch rules.** The `staging` environment releases its secrets only to
  branch `staging`; `Production` only to `main`, and only after the required reviewer approves.
- **Two keys, each forced to its environment on the box.** Even a run that holds the staging key
  (any commit merged into `staging`) cannot touch production.
- **The image by digest.** Package write access is per repository, not per branch: a workflow on
  any branch can push an image under `sha-<12 of the real commit>`. The box never pulls a tag.

And production **only moves forward**: a request for an older commit of `main` is refused. Going
back is a person's decision ("Roll back" below).

## What a deploy does on the box

`deploy staging <commit> <digest> <token>` works in `/opt/treadwell-staging` (branch `staging`,
compose file `docker-compose.staging.yml`, health on `127.0.0.1:8889/healthz`); `deploy main ...`
works in `/opt/treadwell` (branch `main`, `docker-compose.yml`, `127.0.0.1:8888/healthz`). In order:

1. **One deploy at a time on the box.** A lock (`/run/treadwell-tool-deploy.lock`, in root's `/run`,
   never the world-writable `/run/lock`) is shared by staging and production: they share the image
   store, the font folder and the housekeeping, and the workflow's concurrency group is per branch.
   It waits at most 8 minutes. From here on a dropped SSH session does not stop the run: the
   program ignores SIGHUP/SIGPIPE and also writes everything to `/var/log/treadwell-tool-deploy.log`
   (root only), so a timed-out step leaves the deploy or rollback to finish, and that log says how.
2. **The checkout.** It must be on its branch (`staging` / `main`). The branch is fetched, and a
   commit that is not on it is refused. A checkout holding commits that are not on GitHub is
   refused too, rather than losing them. **On production, a commit older than the one deployed is
   refused.**
3. **The font.** The checkout's copy of Zetta Serif is kept in `/opt/treadwell-fonts`, and the
   deploy stops while either file is missing there (`backend/fonts/README.md`).
4. **The image.** `docker login` with the job's short-lived token in a throw-away `DOCKER_CONFIG`
   (root's `~/.docker` is never read or written), then `docker pull` of exactly
   `<image>@sha256:<digest>`, for at most 10 minutes. A failed pull changes nothing.
5. **The checkout moves to exactly that commit and stays on its branch**: a fast-forward, or (staging
   only) `git reset --keep` when an older commit of the branch is deployed again. Never a detached
   HEAD, because `deploy/ship.sh` and people still run `git pull --ff-only` in these folders.
6. **Staging only:** its Postgres up, `pg_isready`, `backend/staging/schema_pg.sql` fed from the
   checkout into `psql -v ON_ERROR_STOP=1`. A failure here puts the checkout back and stops; only
   the database container was touched.
7. `docker compose up -d` with `TW_IMAGE=<image>@sha256:<digest>`: **never a build**. Staging then
   tells PostgREST to reload its schema (if that fails, the run ends red after a healthy deploy).
8. **Health:** `/healthz` must answer and the container must be running the new image.
   **When that fails, it rolls back by itself**: the previous checkout and the previous image go
   back up, their health is checked, and the run still ends red.
9. The healthy image is tagged on the box as `sha-<12 of the commit>` (for "Roll back") and as the
   moving tag (`:staging` / `:prod`), so a bare `docker compose up -d` there starts what was deployed.
10. **Housekeeping.** This app: the three newest `treadwell-proposal-tool:sha-*` images are kept,
    older ones no container uses are removed. **The whole box** (this pipeline has been its disk
    cleaner since 2026-08-11, when ~15GB of build cache took staging and production down): dangling
    images and unused build cache **older than a week**, of every app, are pruned
    (`docker image prune -f --filter until=168h`, `docker builder prune -f --filter until=168h`).
    A week keeps every app's recent cache warm; never `-a`, `system prune` or a volume prune.

`pdf-smoke staging <commit> <digest>` (the second staging step) runs the LibreOffice tests in a
throw-away container of the image staging was just deployed with. Only `backend/` and the font are
mounted, read-only (never the checkout's `.env.staging`), and that container has **no network**: a
first container, which sees nothing of the checkout, downloads the test tools as wheels pinned by
version and sha256 (`SMOKE_REQUIREMENTS` in `deploy/remote-deploy.sh`). It refuses when the staging
checkout is no longer at that commit.

## One-time setup (Hanz) — BEFORE the PR that adds this is merged

Merging into `staging` starts a staging deploy that uses the new secrets, so the box and the secrets
come first. Steps 1 to 4 change nothing that runs today: the old root deploy keeps working until
the PR is merged.

1. **Two deploy keys, on your PC, in Git Bash** (PowerShell 5.1 drops the empty `''`), in this
   repo's folder (or the PR's worktree, so the two scripts below are the PR's versions):

   ```bash
   ssh-keygen -t ed25519 -N '' -C tool-deploy-staging -f tool-deploy-staging
   ssh-keygen -t ed25519 -N '' -C tool-deploy-main    -f tool-deploy-main
   ```

   Keys of the proposal tool's own: never the BD CRM's deploy key, never your ops key, and never one
   key for both environments (the install script refuses that).

2. **The account, the program, sudo and the keys, on the box:**

   ```bash
   ssh treadwell-vps 'install -d -m 700 /root/tool-deploy-setup'
   scp deploy/remote-deploy.sh deploy/install-deploy-account.sh tool-deploy-staging.pub tool-deploy-main.pub treadwell-vps:/root/tool-deploy-setup/
   ssh treadwell-vps 'bash /root/tool-deploy-setup/install-deploy-account.sh --staging-key /root/tool-deploy-setup/tool-deploy-staging.pub --main-key /root/tool-deploy-setup/tool-deploy-main.pub'
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

3. **Try the keys before GitHub has them.** From the PC, with a new key and the account in place of
   the alias's own (`-o User=` on the command line wins over the alias):

   ```bash
   Z=0000000000000000000000000000000000000000
   D=sha256:0000000000000000000000000000000000000000000000000000000000000000
   ssh -i ./tool-deploy-staging -o IdentitiesOnly=yes -o User=tooldeploy treadwell-vps 'whoami'
   ssh -i ./tool-deploy-staging -o IdentitiesOnly=yes -o User=tooldeploy treadwell-vps "pdf-smoke staging $Z $D"
   ssh -i ./tool-deploy-main    -o IdentitiesOnly=yes -o User=tooldeploy treadwell-vps "pdf-smoke staging $Z $D"
   ```

   The first must answer `refusing: the request must be exactly one line ...` (the key runs the
   program, not `whoami`). The second must answer `refusing: /opt/treadwell-staging is at <sha>,
   not 0000...`: reading that root-owned checkout proves sudo worked. The third must answer
   `refusing: this key deploys main only, not staging`: the keys are bound to their environments.
   Anything else (a shell, a password prompt, `Permission denied (publickey)`, `sudo: a password is
   required`) means step 2 did not finish: see "When something goes wrong".

4. **The GitHub environments and their secrets.** Never repository secrets: a repository secret
   reaches a workflow on any branch, and the whole design rests on each key reaching only its own
   branch's runs.

   a. **Deployment branches**, in GitHub -> Settings -> Environments: open `staging` ->
      "Deployment branches and tags" -> **Selected branches and tags** -> add the branch rule
      `staging` (nothing else). Open `Production` -> the same -> add `main` (nothing else), and keep
      its required reviewer (HDLC01). Check both:

      ```bash
      gh api repos/HDLC01/Treadwell-Proposal-Tool/environments --jq '.environments[] | {name, deployment_branch_policy, rules: [.protection_rules[].type]}'
      gh api repos/HDLC01/Treadwell-Proposal-Tool/environments/staging/deployment-branch-policies --jq '.branch_policies[].name'
      gh api repos/HDLC01/Treadwell-Proposal-Tool/environments/Production/deployment-branch-policies --jq '.branch_policies[].name'
      ```

      Both `deployment_branch_policy` values must show `"custom_branch_policies": true`, the two
      lists must print exactly `staging` and exactly `main`, and Production must list
      `required_reviewers`.

   b. **The secrets**, from the same folder (the values never appear on screen or in a file):

      ```bash
      R=HDLC01/Treadwell-Proposal-Tool
      gh secret set VPS_DEPLOY_USER -R $R --env staging    --body tooldeploy
      gh secret set VPS_DEPLOY_USER -R $R --env Production --body tooldeploy
      gh secret set VPS_FINGERPRINT -R $R --env staging    --body 'SHA256:<the ECDSA value from step 2>'
      gh secret set VPS_FINGERPRINT -R $R --env Production --body 'SHA256:<the ECDSA value from step 2>'
      gh secret set VPS_DEPLOY_KEY  -R $R --env staging    < tool-deploy-staging
      gh secret set VPS_DEPLOY_KEY  -R $R --env Production < tool-deploy-main
      rm tool-deploy-staging tool-deploy-staging.pub tool-deploy-main tool-deploy-main.pub
      gh secret list -R $R                      # must NOT list any VPS_DEPLOY_* at repository level
      ```

      `VPS_HOST` and `VPS_PORT` exist already and stay as they are. Only the `SHA256:...` part goes
      into `VPS_FINGERPRINT`, not the `(ECDSA)` label. If the first deploy stops with
      `ssh: handshake failed: ssh: host key fingerprint mismatch`, put the ED25519 value in instead
      (the action checks whichever key type it negotiated).

5. **Merge the PR into `staging`** and watch Actions -> Deploy: both staging steps must be green.
   The production job uses the production key the next time `staging` is promoted to `main`. Its
   secrets are released only after the `Production` environment approval, and only to `main`, so
   that approval now protects production's key, not just the normal path.

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

Without `--staging-key` / `--main-key` it keeps the account's keys and only checks that every key is
forced to its own environment. To replace one key, pass only that one: the other's line is kept.

## Roll back

A deploy whose health check fails rolls back to the previous image and checkout by itself. To go
back by hand to an older build, **by digest** (a tag can be re-pointed by anything that can push the
package; the box keeps the last three builds, tagged `sha-<12>` locally):

```bash
ssh treadwell-vps 'docker images --digests ghcr.io/hdlc01/treadwell-proposal-tool'
ssh treadwell-vps 'cd /opt/treadwell && TW_IMAGE=ghcr.io/hdlc01/treadwell-proposal-tool@sha256:<old digest> docker compose up -d'
ssh treadwell-vps 'cd /opt/treadwell-staging && TW_IMAGE=ghcr.io/hdlc01/treadwell-proposal-tool@sha256:<old digest> docker compose -f docker-compose.staging.yml up -d'
```

The digest of any build is in its Deploy run (the build job's "Build and push" step), and before
using one from outside the box, check where it came from:

```bash
gh attestation verify oci://ghcr.io/hdlc01/treadwell-proposal-tool@sha256:<old digest> --repo HDLC01/Treadwell-Proposal-Tool --signer-workflow HDLC01/Treadwell-Proposal-Tool/.github/workflows/deploy.yml
```

The next Deploy run goes forward again. On **staging**, re-running an older Deploy from the Actions
tab works too: the box moves the checkout back to that commit with `git reset --keep`, still on its
branch. On **production** the box refuses an older commit (`production only moves forward`): use
the commands above, and to keep it, revert on `main`.

## Undo this change

1. Revert the PR (into `staging`, then promote). The workflow goes back to `VPS_USER` /
   `VPS_SSH_KEY`, so this only works while those secrets and root's old key still exist (step 6
   above not done yet). After step 6, re-create them first.
2. On the box:

   ```bash
   ssh treadwell-vps 'rm -f /etc/sudoers.d/treadwell-tool-deploy /usr/local/sbin/treadwell-tool-deploy && visudo -c && deluser --remove-home tooldeploy'
   ```

3. Delete `VPS_DEPLOY_USER`, `VPS_DEPLOY_KEY` and `VPS_FINGERPRINT` from both environments in GitHub.

## When something goes wrong

- **`refusing: <commit> is not on staging`.** The commit is not on the branch on GitHub (a
  force-push?). Run Deploy again from the branch.
- **`refusing: this key deploys staging only, not main`** (or the reverse). The environment holds
  the other environment's key, or its own `VPS_DEPLOY_KEY` is missing and a repository-level one
  (which must not exist) was used instead:
  `gh secret list -R HDLC01/Treadwell-Proposal-Tool --env Production` and the same without `--env`.
- **`refusing: this program takes exactly one argument`.** The account's `authorized_keys` still has
  the old single-key line: re-run the install script with `--staging-key` and `--main-key`.
- **`production only moves forward`.** The run asked for an older commit of `main` than the one
  deployed. That is a rollback: "Roll back" above.
- **`... is on 'x', not staging` (or `main`).** Someone switched the box's checkout to another
  branch. `ssh treadwell-vps 'git -C /opt/treadwell-staging checkout staging'`, then re-run.
- **`... has commits that are not on origin/staging`.** Someone committed on the box. Look with
  `ssh treadwell-vps 'git -C /opt/treadwell-staging log origin/staging..HEAD'`; move them to a PR
  or drop them, then re-run.
- **`post-deploy healthcheck failed`.** The step prints `docker compose ps` and the app's last log
  lines, then rolls back ("rolled back: ... is serving again"). If it says the rollback is not
  healthy either, or there is no previous container, the site is down: see "Roll back".
- **`PostgREST did not take the schema reload`.** Staging is up on the new image, but PostgREST may
  serve the old schema: `ssh treadwell-vps 'cd /opt/treadwell-staging && docker compose -f docker-compose.staging.yml restart postgrest'`.
- **`another proposal-tool deploy held the lock`.** The other environment's deploy took more than
  8 minutes. Re-run once it has finished.
- **The step timed out.** The box carried on without the session. Read how it ended:
  `ssh treadwell-vps 'tail -50 /var/log/treadwell-tool-deploy.log'`.
- **`Permission denied (publickey)`.** The account is missing from an sshd `AllowUsers` line (the
  install script warns about it), or the environment's `VPS_DEPLOY_KEY` is not the private half of
  that environment's key installed in step 2.
- **`sudo: a password is required`.** `/etc/sudoers.d/treadwell-tool-deploy` is missing or names
  another account: re-run the install script (step 2, or "After `deploy/remote-deploy.sh`
  changes").
- **`handshake failed` / `fingerprint mismatch`.** `VPS_FINGERPRINT` is the other host key type
  (step 4), or the box's host key changed: check on the box before you change the secret.
- **The pull answers 403 or "denied".** The job token cannot read the package: GitHub -> HDLC01's
  Packages -> `treadwell-proposal-tool` -> Package settings -> Manage Actions access must list this
  repository. Nothing on the box has changed when this happens.
- **`could not download the pinned PDF test tools`.** PyPI was unreachable, or a wheel's hash no
  longer matches `SMOKE_REQUIREMENTS` (never "fix" that by dropping the hash: find out why).
