# Ops — emergency kill switch

Simple **manual** commands to take the live tool offline and back on. They run
on the VPS as standard `docker compose` actions. There is intentionally **no
automatic "shut down if hacked"** — that can't reliably tell an attacker from a
real user and would let anyone knock the tool offline (a self-inflicted DoS).
Stopping is a deliberate human decision.

## If you're under attack / need it down NOW

```bash
ssh root@<vps-ip>     # (uses the treadwell_vps key)
tw-down                   # site goes offline instantly (visitors get an error)
```

Bring it back when clear:

```bash
tw-up                     # back online in ~10s
tw-status                 # confirm it's running + healthy
```

## Installing on the VPS (already done; re-run if the box is rebuilt)

```bash
sudo install -m 755 ops/tw-down ops/tw-up ops/tw-status /usr/local/bin/
```

## Stronger protection (not yet enabled)

The site is currently public with no login. The highest-impact next step is a
**password/login** (HTTP basic auth at nginx) plus **rate limiting** on
`/api/autofill` and `/api/generate`. Ask to enable when ready.
