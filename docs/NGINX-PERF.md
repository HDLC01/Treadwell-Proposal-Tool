# nginx / transport performance audit

**What this is.** Everything below was measured against `https://proposals.wetreadwell.com`
on **2026-09-16** from a client in the **Philippines**. Nobody touched the VPS to produce it:
every number comes from the wire or from source in this repo. It is written for someone who
has SSH on the box and wants to know what to change, what it buys, and how to undo it.

**Tools used, and why it matters.** The `curl` on the dev box **cannot speak HTTP/2** — neither
the Git-Bash build (8.9.0) nor the Windows system build (8.21.0) lists `HTTP2` in
`curl --version` Features. A protocol claim made with that client would be worthless, so every
HTTP/2 and ALPN statement here was made with **OpenSSL 3.2.2** `s_client`, which does offer
ALPN. Sizes and timings come from curl; compression comparisons come from the `brotli` and
`gzip` CLIs run over bytes actually downloaded from production.

---

## 0. Two corrections before anything else

### 0.1 nginx is not doing the compression. The app is.

The brief asks whether `gzip_types` covers JSON and SVG. It is the wrong question for this box,
because **`gzip_types` is not in play at all**. Compression is done inside FastAPI:

    backend/main.py:114   app.add_middleware(GZipMiddleware, minimum_size=500)

Three independent lines of evidence:

1. **Header case.** nginx emits capitalised header names; uvicorn/Starlette emits lowercase.
   In one response you can see both layers at once:

   ```
   Server: nginx                        <- nginx
   Content-Type: text/javascript        <- nginx (normalised)
   Content-Security-Policy: ...         <- nginx add_header
   content-encoding: gzip               <- the app
   vary: Accept-Encoding                <- the app
   cache-control: no-store, ...         <- the app
   ```

2. **Source.** Starlette's `GZipMiddleware` has no content-type allowlist. Its only exclusion is
   `DEFAULT_EXCLUDED_CONTENT_TYPES = ("text/event-stream",)`. (Read from the locally installed
   starlette **1.0.0**; production pins **1.3.1** in `backend/requirements.txt` — the exclusion
   tuple has been stable across that range, but confirm on the box if it matters to you.)

3. **The 500-byte floor is visible on the wire.** `/api/public-config` is `application/json`,
   **325 bytes**, requested with `Accept-Encoding: gzip, br` — returned **uncompressed**.
   `/dropbox.html` is 664 bytes raw and **is** gzipped (to 420). Under the floor, nothing is
   compressed; over it, everything is.

**So the actual answer to the question asked:** SVG *is* compressed — `/img/treadwell-bison.svg`
comes back `content-encoding: gzip`, 5,816 raw to 2,428 on the wire. JSON *is* compressed too,
whenever a response clears 500 bytes. The one public JSON endpoint is 325 bytes, so it
legitimately is not. Nothing is excluded by type.

Whether nginx *also* has `gzip on` cannot be settled from outside, because the app's output
arrives at nginx already carrying `Content-Encoding`, and nginx will not recompress it. The two
sub-500-byte responses I could reach (`/healthz`, 11 B; `/api/public-config`, 325 B) both came
back uncompressed, which is consistent with nginx gzip being off or its `gzip_min_length` being
above 325. Settle it on the box with:

    nginx -T 2>/dev/null | grep -nE 'gzip|brotli'

**This single fact rewrites the brotli plan.** See section 2.

### 0.2 The biggest win is not in the brief

Every static asset is served `no-store`, **and conditional requests are deliberately broken**:

    backend/main.py:6800  class NoCacheStaticFiles(StaticFiles):
    backend/main.py:6806      def is_not_modified(...) -> bool:
    backend/main.py:6807          return False
    backend/main.py:6811      resp.headers["Cache-Control"] = "no-store, must-revalidate, max-age=0"

Confirmed on the wire — I sent the exact ETag back and got the whole file again, not a 304:

    If-None-Match: "7a4bc5dd..."  -> 200, 4018 bytes   (not 304)
    If-Modified-Since: <exact>    -> 200, 4018 bytes   (not 304)

The class comment says *"Cheap because the files are tiny."* That is no longer true.
`/js/portal.js` is **285,337 bytes raw / 92,645 gzipped**, and this is a multi-page app — every
screen change is a full navigation that re-downloads the whole set. Details and sizes in
section 3.4.

---

## 1. HTTP/2

### 1.1 Confirmed: the site is HTTP/1.1, and it is the server's choice

I offered both protocols in ALPN and the server picked the old one:

    openssl s_client -alpn h2,http/1.1 -connect proposals.wetreadwell.com:443 \
      -servername proposals.wetreadwell.com </dev/null 2>&1 | grep ALPN

    ALPN protocol: http/1.1

That is the real test. A client that cannot offer `h2` proves nothing, which is why the dev box's
curl was not used here.

### 1.2 What it costs today, measured

Six cold-connection samples of `/portal.html`, `Accept-Encoding: gzip` (seconds):

| | DNS | TCP connect | TLS complete | TTFB | total |
|---|---|---|---|---|---|
| mean of 6 | 0.006 | **0.236** | **0.476** | **0.934** | 0.940 |
| range | 0.005-0.010 | 0.226-0.246 | 0.454-0.488 | 0.893-0.958 | 0.899-0.961 |

Read that as: **RTT is ~0.236 s** (the TCP handshake is one round trip), TLS 1.3 adds one more
(0.476 - 0.236 = 0.240), so **a brand-new connection costs ~0.476 s before the first request byte
leaves**. My TTFB (mean 0.934 s) is **higher than the 0.75 s in the brief** — I am reporting what
I measured, not what I was told.

Connection reuse works, and shows exactly what a warm connection is worth. Six assets fetched
over one connection:

    /auth.js                  connect=0.236  ttfb=0.932  total=0.938   <- cold
    /shared.js                connect=0.000  ttfb=0.235  total=0.236
    /js/crm-core.js           connect=0.000  ttfb=0.235  total=0.235
    /js/icons.js              connect=0.000  ttfb=0.233  total=0.233
    /js/portal.js             connect=0.000  ttfb=0.240  total=0.473
    /img/treadwell-bison.svg  connect=0.000  ttfb=0.233  total=0.233

A request on a warm connection costs ~1 RTT. A request that has to open a connection costs
~3 RTT before its first byte.

### 1.3 Assets per page, counted

| page | same-origin subresources | cross-origin | total |
|---|---|---|---|
| `portal.html` | 6 | 1 (jsdelivr) | **7** |
| `estimate-review.html` | 8 | 2 (jsdelivr) | **10** |
| `proposal-review.html` | 8 | 2 | **10** |
| `library.html` | — | — | **8** |

The brief said 6-8; I measured **7-10**. `estimate-review.html` pulls a second CDN script
(HyperFormula) on top of supabase-js.

### 1.4 The saving, and the reasoning — including the part I got wrong

HTTP/1.1 opens up to six connections per origin. `portal.html` needs 6 same-origin subresources;
one can reuse the HTML's connection, so the browser opens **5 more**, each paying TCP+TLS. They
are opened in **parallel**, so the wall-clock cost is one handshake round, not five:

    HTML done              ~0.95 s   (measured TTFB 0.934 + transfer)
    + 5 new handshakes     +0.476 s  (measured, parallel)
    + first byte           +0.236 s  (measured, 1 RTT)

HTTP/2 multiplexes all 6 onto the connection that is already open, so the `+0.476 s` disappears.

**I initially assumed TCP slow-start would add more on top, and measured it instead of assuming.
It does not.** `/js/portal.js` (92,645 B gzipped) transfers in 0.243-0.257 s on a cold connection
and 0.233 s on a warm one — the difference is inside the noise. So there is no meaningful
slow-start penalty to recover here, and I am **not** claiming one.

**Estimated saving: ~0.45-0.50 s on a cold page load**, which is the one parallel handshake round
that HTTP/2 removes. That is it. It is a real half-second on a ~2.4 s load, but it is one effect,
not three.

Two honest limits on that number: I did not run a real browser trace (curl's scheduling is not
Chrome's), and HTTP/2 does nothing for the cross-origin CDN scripts — those need their own
connection regardless. For what it is worth the CDN is not the problem: jsdelivr answered in
**0.112 s total** (connect 0.034, TLS 0.075) because Cloudflare has a nearby PoP, and it already
serves **brotli**. Our own origin is the slow half.

### 1.5 The change

Check the nginx version first — the directive changed in 1.25.1:

    nginx -v
    nginx -V 2>&1 | tr ' ' '\n' | grep -c with-http_v2_module    # must be 1

nginx **>= 1.25.1** (Ubuntu 24.04 ships 1.24 from the archive, 1.26+ from nginx.org, so check):

    # inside the server { } block for proposals.wetreadwell.com
    http2 on;

nginx **< 1.25.1**:

    listen 443 ssl http2;    # replaces the existing `listen 443 ssl;`

What else has to be true, all of which I confirmed is already true:

- **ALPN** — required for h2 over TLS. Already working: the server parsed my ALPN list and
  selected from it. Needs OpenSSL >= 1.0.2; the box is far past that.
- **TLS >= 1.2** — h2 forbids TLS 1.1 and below. Confirmed: TLS 1.3 negotiated by default,
  TLS 1.2 available (`ECDHE-ECDSA-AES256-GCM-SHA384`).
- **`ngx_http_v2_module` compiled in** — the `nginx -V` check above.

Do **not** put `http2 on;` in the `http { }` block unless you want it on every vhost on this box;
there are ~13 containers behind this nginx and other server blocks will inherit it.

### 1.6 Verify it took

    openssl s_client -alpn h2,http/1.1 -connect proposals.wetreadwell.com:443 \
      -servername proposals.wetreadwell.com </dev/null 2>&1 | grep ALPN
    # want: ALPN protocol: h2

Do not try to verify with the dev box's curl — it cannot negotiate h2 and will report
`http/1.1` no matter what the server does.

### 1.7 Rollback

    # /etc/nginx/... : delete the `http2 on;` line (or drop `http2` from the listen line)
    nginx -t && nginx -s reload

Config-only, **no container rebuild, no image pull, no docker compose**. `nginx -t` validates
before anything is applied, and `reload` is graceful — in-flight requests finish on the old
workers. Rollback is the same two commands. This is the safest change in this document, which is
a large part of why it ranks where it does.

---

## 2. Brotli

### 2.1 Confirmed: gzip is served even when brotli is offered

| `Accept-Encoding:` sent | `Content-Encoding` returned |
|---|---|
| `br` | *(none — 69,564 bytes raw)* |
| `gzip` | `gzip` |
| `br, gzip` | `gzip` |
| `zstd, br, gzip` | `gzip` |

Offering `br` alone gets you **no compression at all**, which is the clearest possible proof that
nothing in the stack can produce brotli.

### 2.2 Is the module installed? Here is how to find out

Three checks, in order:

    nginx -V 2>&1 | tr ' ' '\n' | grep -i brotli          # statically compiled in?
    ls /usr/lib/nginx/modules/ | grep -i brotli           # dynamic module present?
    grep -rn load_module /etc/nginx/nginx.conf /etc/nginx/modules-enabled/ 2>/dev/null

I cannot run these — no VPS access. Given the server answers `Server: nginx` with no version
(`server_tokens off`) and serves no brotli, assume it is **not** installed until one of those
commands says otherwise.

If it is missing, on Ubuntu 24.04 use the distro packages rather than compiling:

    apt-get install libnginx-mod-http-brotli-filter libnginx-mod-http-brotli-static

Prefer this to building from source. Compiling nginx on this box means a long build on a host
that already runs ~13 containers, and a hung build here has taken production down once before.

### 2.3 The catch that makes this not worth doing yet

**nginx will not brotli a response that already has `Content-Encoding: gzip`** — and per section
0.1, every response over 500 bytes arrives at nginx already gzipped by the app. So adding
`brotli on;` would compress **only the responses under 500 bytes**, which is close to nothing.

To actually get brotli you must first stop the app compressing:

- remove or neutralise `app.add_middleware(GZipMiddleware, minimum_size=500)` in
  `backend/main.py`, then
- let nginx do **both** gzip and brotli, so clients without brotli still get gzip.

That is an application change plus a **container rebuild** — exactly the operation that is risky
on this host. `brotli_static` is not an escape hatch either: the frontend files live inside the
container and nginx reverse-proxies to `:8888` rather than serving them from disk, so there is no
directory of `.br` files for it to find.

### 2.4 What it would actually buy, measured against the real files

I downloaded the seven `portal.html` assets from production and recompressed the exact bytes.
`srv_gzip` is what production returned; `br5`/`br11` are brotli quality 5 and 11 locally.

| asset | raw | srv gzip | br q5 | br q11 | q11 vs gzip |
|---|---|---|---|---|---|
| `portal.html` | 69,564 | 22,305 | 21,350 | 18,752 | 15.9% |
| `auth.js` | 67,139 | 23,528 | 22,641 | 20,066 | 14.7% |
| `shared.js` | 59,394 | 20,853 | 20,144 | 17,866 | 14.3% |
| `js/crm-core.js` | 37,551 | 13,987 | 13,470 | 11,952 | 14.5% |
| `js/icons.js` | 11,250 | 4,018 | 3,826 | 3,311 | 17.6% |
| `js/portal.js` | 285,337 | 92,645 | 85,414 | 74,709 | 19.4% |
| `img/treadwell-bison.svg` | 5,816 | 2,428 | 2,269 | 2,114 | 12.9% |
| **TOTAL** | **536,051** | **179,764** | **169,114** | **148,770** | **17.2%** |

The brief's 15-20% is **confirmed — but only at quality 11**: 17.2%, 30,994 bytes.

**At the quality you would actually run on-the-fly it is 5.9%, not 17.2%.** `brotli_comp_level 5`
saves 10,650 bytes total. Quality 11 is far too slow for dynamic compression and is only sane for
pre-compressed static files, which section 2.3 explains this setup cannot serve.

And 31 KB is worth less time than it looks. Measured throughput on this path is ~397 KB/s
(92,645 bytes of `portal.js` in 0.233 s), so **the full 17.2% is worth about 0.08 s** — against
0.45-0.50 s for HTTP/2, for far more work and more risk.

### 2.5 The config, if you do it anyway

    # http { } or the server block
    brotli on;
    brotli_comp_level 5;
    brotli_types text/plain text/css text/xml text/javascript
                 application/json application/javascript application/xml
                 image/svg+xml;

Keep `gzip on;` alongside it — brotli is not universal, and nginx picks per request from
`Accept-Encoding`.

### 2.6 Rollback

    # comment out the brotli directives
    nginx -t && nginx -s reload

If you also removed `GZipMiddleware`, that half needs the app redeployed to come back, and
**that** is the risky half. Roll the nginx side back first and confirm `Content-Encoding: gzip`
returns before touching the container.

---

## 3. What else the headers reveal

### 3.1 TLS session resumption — working, leave it alone

`-reconnect` reported 0 reused, which is a known false negative for TLS 1.3, so I tested it
properly with an exported session:

    openssl s_client ... -sess_out sess.pem </dev/null
    openssl s_client ... -sess_in  sess.pem </dev/null
    # Reused, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384

Confirmed **working**. Session tickets are issued with a 24-hour lifetime hint
(`TLS session ticket lifetime hint: 86400`), two per connection. `Max Early Data: 0`, so 0-RTT is
off — which is the correct setting for an app with authenticated state-changing requests. No
change recommended.

### 3.2 OCSP stapling — off, and probably no longer worth turning on

    openssl s_client -status ... | head -2
    OCSP response: no response sent

Stapling is **off**. The usual fix is:

    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/letsencrypt/live/<domain>/chain.pem;
    resolver 127.0.0.53 valid=300s;
    resolver_timeout 5s;

**But check whether it still does anything before bothering.** The certificate is Let's Encrypt
(`issuer=C=US, O=Let's Encrypt, CN=YE1`, ECDSA P-256), and Let's Encrypt has been winding down
OCSP responder service in favour of CRLs. If their responder is gone, `ssl_stapling on` is a
no-op that fills the error log with fetch failures. Verify first; treat this as the lowest-value
item here. Chrome does not use OCSP for these certs anyway (it ships CRLSets).

### 3.3 Certificate chain — 1.8 KB of it does not need to be sent

    0 s:CN=proposals.wetreadwell.com                   933 B
    1 s:C=US, O=Let's Encrypt, CN=YE1                  655 B
    2 s:C=US, O=ISRG, CN=Root YE                       682 B
    3 s:C=US, O=Internet Security Research Group,
         CN=ISRG Root X2                              1140 B
    ----------------------------------------------------------
    TOTAL sent                                        3410 B
    roots that need not be sent                       1822 B

The server sends **four** certificates, two of which are roots that a client either already
trusts or will not trust for being sent. Trimming to leaf + intermediate saves ~1.8 KB on every
fresh handshake.

**Do not just do it.** Let's Encrypt publishes more than one chain, and the longer one exists for
older clients that lack ISRG Root X2 and need the cross-signed path. The saving is ~1.8 KB on
connections only — it does not affect warm requests at all, and 1.8 KB is well inside the initial
congestion window so it likely costs no extra round trip. **Low value, non-zero compatibility
risk. Listed for completeness; I would not do it.**

### 3.4 Caching — this is the real finding

Every static asset, `.html` / `.js` / `.css` / `.svg` alike:

    cache-control: no-store, must-revalidate, max-age=0
    pragma: no-cache
    expires: 0
    etag: "..."            <- present but useless
    last-modified: ...     <- present but useless

`no-store` forbids the browser from keeping the response at all, so it can never revalidate, so
the ETag can never be used. And even if it could, section 0.2 shows the server returns **200 with
the full body** for a matching `If-None-Match`, because `is_not_modified()` is hardcoded to
`False`.

**Cost: 179,764 gzipped bytes re-downloaded on every single navigation**, plus 6-9 requests. In a
multi-page app where Intake to Estimate Review to Proposal Review to Done are four full page
loads, that is four times over for one project.

**This is an app-side header, not an nginx one** — note the lowercase `cache-control`, and
`backend/main.py:6811`. The correct fix is in `NoCacheStaticFiles`, and it is deliberately **not**
made here: this branch is documentation only, and four other agents are working in `backend/main.py`
right now, including on the root route immediately below that class at line 6817.

Two routes when someone picks it up:

- **Proper fix (app):** stop overriding `is_not_modified()` and serve `no-cache` instead of
  `no-store`. `no-cache` still revalidates on **every** request, so there is **zero staleness
  risk**, but a match returns a bodyless 304 instead of 92 KB. This is the change to make.
- **nginx stopgap:** `proxy_hide_header Cache-Control;` plus `add_header Cache-Control "..."` in
  a `location` scoped to the static paths. This works without a rebuild, but note the assets have
  **no content hashes in their filenames** (`/js/portal.js`, not `/js/portal.a1b2c3.js`), so any
  positive `max-age` serves stale JavaScript after a deploy for the length of the window. If you
  do this, keep the window short (60 s) and never use `immutable`.

Rollback for the nginx stopgap is `nginx -t && nginx -s reload` after removing the location block.

### 3.5 Keepalive — working client-side; check the upstream side

Client-side keepalive is confirmed working: `Connection: keep-alive`, and five consecutive
requests reused one connection with `connect=0.000` (section 1.2). Nothing to fix.

**Worth checking on the box:** nginx does not reuse connections to the *upstream* unless it is
told to. Without this, every proxied request opens a fresh TCP connection to the container:

    upstream treadwell {
        server 127.0.0.1:8888;
        keepalive 32;
    }
    location / {
        proxy_pass http://treadwell;
        proxy_http_version 1.1;          # default is 1.0 — required for upstream keepalive
        proxy_set_header Connection "";  # must clear it, or 1.0-style close is forwarded
    }

Confirm the current state with `nginx -T | grep -A5 upstream`. This is loopback so the win is
small (no RTT involved, just syscalls and sockets), but it is free and it reduces `TIME_WAIT`
churn on a host running ~13 containers.

### 3.6 Two smaller observations

- **`gzip` compression level is 9.** Starlette's default. My local `gzip -9` output matches the
  served bytes to within a few bytes across all seven assets, which is what confirms the level.
  Level 6 costs **275 bytes on `portal.js`** (92,729 vs 92,454 — 0.3%) for appreciably less CPU
  per request. On a box with ~13 containers that trade looks wrong at 9. One-line app change,
  not made here for the same reason as 3.4.
- **~0.2 s unexplained between TLS-complete and first byte on cold connections.** `TTFB minus
  TLS-complete` is ~0.46 s where one RTT is ~0.236 s, yet the same file on a warm connection
  returns in ~0.233 s (about one RTT, so effectively no server time). I could not resolve this
  from outside and I am **not** going to guess at a cause. If you want the next real win after
  the items below, profile it on the box — it is larger than brotli.

---

## 4. Ordered list — biggest win first

| # | Change | Measured value | Risk | Rollback |
|---|---|---|---|---|
| 1 | **Make static assets cacheable** (§3.4) | **179,764 B + 6-9 requests saved on every navigation after the first** | **Medium.** App change + container rebuild — the risky operation on this host. Staleness risk is real with unhashed filenames; `no-cache` avoids it entirely, a positive `max-age` does not. | Revert the commit, redeploy. The nginx stopgap rolls back with `nginx -t && nginx -s reload`. |
| 2 | **Enable HTTP/2** (§1.5) | **~0.45-0.50 s off a cold page load** | **Low.** One directive, config-only, no rebuild. `nginx -t` catches errors before they apply; `reload` is graceful. Scope it to the server block, not `http { }`, or all ~13 vhosts inherit it. | Delete the line, `nginx -t && nginx -s reload`. |
| 3 | **Upstream keepalive to the container** (§3.5) | Small — loopback, no RTT. Fewer sockets and less `TIME_WAIT`. | **Low.** Config-only. `proxy_http_version 1.1` also changes how the upstream sees the request; confirm nothing depends on 1.0 framing. | Remove the three lines, `nginx -t && nginx -s reload`. |
| 4 | **gzip level 9 to 6** (§3.6) | 0.3% more bytes, appreciably less CPU per request | **Low**, but app change + rebuild, so it should ride along with #1 rather than justify its own deploy. | Revert the one-line change. |
| 5 | **Brotli** (§2) | **17.2% (30,994 B, ~0.08 s)** at q11 — unreachable here; **5.9% (10,650 B)** at the q5 you would actually run | **Medium-high.** Needs `GZipMiddleware` removed first, so a rebuild, plus a new nginx module. Most work and most risk in this table for the smallest measured gain. | nginx side: comment out, `nginx -t && nginx -s reload`. App side needs a redeploy — roll nginx back first and confirm gzip returns. |
| 6 | **OCSP stapling** (§3.2) | Probably zero — Let's Encrypt is retiring OCSP | **Low**, but may just fill the error log. | Remove the directives, reload. |
| 7 | **Trim the cert chain** (§3.3) | ~1.8 KB per fresh handshake, likely no extra round trip | **Low but non-zero** — breaks older clients lacking ISRG Root X2. **I would not do it.** | Point `ssl_certificate` back at the full `fullchain.pem`, reload. |

### Sequencing, given this host

Items 2, 3, 6 and 7 are **nginx-only**: `nginx -t` then `nginx -s reload`, no Docker involved,
instantly reversible, no build to hang. **Do #2 first** — it is the best ratio in the table and
it cannot take production down the way a rebuild can.

Items 1, 4 and 5 all require rebuilding the container. **Batch them into one deploy** rather than
three. Do not retry a hung build; let it finish or stop it, and prune the build cache first.

---

## Appendix: reproducing this

Nothing here needs VPS access.

    # HTTP/2 / ALPN — needs OpenSSL, NOT the dev box's curl (no HTTP2 feature)
    openssl s_client -alpn h2,http/1.1 -connect proposals.wetreadwell.com:443 \
      -servername proposals.wetreadwell.com </dev/null 2>&1 | grep ALPN

    # OCSP stapling
    openssl s_client -status -connect proposals.wetreadwell.com:443 \
      -servername proposals.wetreadwell.com </dev/null 2>&1 | head -2

    # session resumption (two commands; -reconnect lies under TLS 1.3)
    openssl s_client -connect proposals.wetreadwell.com:443 \
      -servername proposals.wetreadwell.com -sess_out /tmp/s.pem </dev/null >/dev/null 2>&1
    openssl s_client -connect proposals.wetreadwell.com:443 \
      -servername proposals.wetreadwell.com -sess_in /tmp/s.pem </dev/null 2>&1 | grep -E '^(New|Reused)'

    # cert chain
    openssl s_client -showcerts -connect proposals.wetreadwell.com:443 \
      -servername proposals.wetreadwell.com </dev/null 2>&1 | grep -E '^ *[0-9] s:'

    # encoding negotiation (--raw stops curl decompressing, so sizes are wire sizes)
    curl -sS --raw -H 'Accept-Encoding: br' -o /dev/null -D - \
      https://proposals.wetreadwell.com/portal.html | grep -i 'content-\(encoding\|length\)'

    # timings
    curl -sS --raw -H 'Accept-Encoding: gzip' -o /dev/null \
      -w 'connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' \
      https://proposals.wetreadwell.com/portal.html

    # 304 handling — send back the ETag the server just gave you
    curl -sS -H 'If-None-Match: "<etag>"' -o /dev/null -w '%{response_code} %{size_download}\n' \
      https://proposals.wetreadwell.com/js/icons.js

    # brotli vs gzip on the real bytes
    curl -sS --raw -o portal.js https://proposals.wetreadwell.com/js/portal.js
    gzip -9 -c portal.js | wc -c
    brotli -f -q 5  -c portal.js | wc -c
    brotli -f -q 11 -c portal.js | wc -c

### What is deliberately not in this branch

No code changed. `docs/NGINX-PERF.md` is the only file added. The two app-side fixes this audit
found (§3.4 caching, §3.6 gzip level) both live in `backend/main.py`, which other agents are
editing concurrently — they are written up above with file and line numbers so whoever owns that
file can make the change cleanly.
