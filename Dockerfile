# Treadwell Proposal Generator — production container
# Serves frontend (static files) and backend (FastAPI) from a single
# uvicorn process on port 8888. Designed to live behind nginx on the
# host, which terminates HTTPS and reverse-proxies to this container.

#
# PINNED, all of it (2026-09-29, after the security review). Both images are pinned by DIGEST
# (the tag stays in the reference and in the comment above it, for reading), and the Claude CLI
# by exact version. A tag, or an unversioned `npm install`, is whatever the registry serves on
# the day: two builds of one commit could differ, and a bad upstream publish would reach
# production with nothing changing here. Dependabot (.github/dependabot.yml, `docker`) proposes
# the digest bumps; the CLI version is bumped by hand, below.
# (backend/tests/test_deploy_pipeline.py holds every one of these pins.)

# Node.js for the Claude CLI, COPIED out of the official image instead of the old
# `curl https://deb.nodesource.com/setup_20.x | bash -`, which ran an unpinned script from a
# third-party host as root and added its apt repository. Same Node the nodesource build gave
# production (v20.20.2), on the same Debian release (trixie) as the python base below.
# node:20.20.2-trixie-slim
FROM node:20.20.2-trixie-slim@sha256:abfbe12cc943141a0c9e8c0a57d710df1dadd95d35e8662cc02958b284d1f35b AS node

# python:3.11-slim
FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e

# System deps — tini for proper signal handling, curl for healthcheck, media-types for
# /etc/mime.types. The nodesource `nodejs` package used to bring media-types in by the back
# door (nodejs -> python3 -> libpython3.13-stdlib -> media-types). Without that file Python's
# mimetypes falls back to its built-in table: StaticFiles then serves the frontend's .js as
# `application/javascript` (no charset) instead of production's `text/javascript; charset=utf-8`,
# and .docx/.xlsx/.woff2/.webp/.md with no type at all.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini curl ca-certificates media-types \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Node + npm from the stage above. npm's bin entries are symlinks into its own package, so they
# are recreated here rather than copied (a copied npm-cli.js cannot find its lib/). Then the
# Claude CLI: the npm package @anthropic-ai/claude-code powers /api/autofill via subprocess.
# EXACT version: 2.1.197 is what the production container ran on 2026-09-29. Bump it on
# purpose, and check `claude -p` autofill on staging when you do.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && npm install -g @anthropic-ai/claude-code@2.1.197

# LibreOffice (headless) renders the filled .docx proposal to PDF for the
# "Download as PDF" button (see backend/pdf_writer.py). The Writer-only subset
# keeps the image as small as this feature allows (no Calc/Impress). Carlito is
# metric-compatible with Calibri and Liberation with Arial/Times/Courier, so the
# rendered PDF lays out like Word even though those Microsoft fonts aren't shipped.
# Caladea is the same for Cambria, the face of every Terms & Conditions clause and of
# anything set in the templates' theme font (the REGARDS name): without it LibreOffice
# printed them in Liberation Sans. Nothing else is needed: fontconfig's metric aliases
# and LibreOffice's own font replacement table both map Cambria to Caladea (checked in
# this base on 2026-10-02: `fc-match Cambria` -> Caladea, and the PDF names Caladea).
# Apache-2.0, so unlike Zetta it may live in the image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Treadwell's brand font (Zetta Serif) is NOT in this image. The proposal templates are
# typeset in it, but it is LICENSED and this image is pushed to a registry, so the SERVER
# supplies it at runtime: both compose files bind-mount the host's /opt/treadwell-fonts
# read-only onto the directory made here, empty, as the mount point (.dockerignore also
# keeps every font file out of the `COPY backend/` below).
#
# No fc-cache at container start. The cache built here records this directory EMPTY, with
# its build-time mtime; a mount has a different mtime, and fontconfig rescans a directory
# whose mtime no longer matches its cache. So LibreOffice sees the mounted files on its
# first conversion, in every entry path (the CI smoke run overrides CMD). Checked in a real
# container on 2026-09-26. Without the mount the app still boots and logs one WARNING
# (backend/proposal_fonts.py).
RUN mkdir -p /usr/share/fonts/truetype/treadwell \
 && fc-cache -f

WORKDIR /app

# Install Python deps first (separate layer = cache-friendly)
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the app code
COPY backend/ /app/
COPY frontend/ /app/frontend/

# uvicorn listens on 8888 — nginx on the host will proxy 80/443 to this
EXPOSE 8888

# tini as PID 1 → handles SIGTERM correctly when docker stops the container
ENTRYPOINT ["/usr/bin/tini", "--"]

# Health check — nginx will fail fast if container goes unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8888/healthz || exit 1

# Run uvicorn pointed at main:app, single worker (small VPS, the I/O
# work is mostly async anyway — multi-worker would just fight for CPU)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8888", "--workers", "1"]
