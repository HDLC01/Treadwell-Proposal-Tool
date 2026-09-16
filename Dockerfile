# Treadwell Proposal Generator — production container
# Serves frontend (static files) and backend (FastAPI) from a single
# uvicorn process on port 8888. Designed to live behind nginx on the
# host, which terminates HTTPS and reverse-proxies to this container.

FROM python:3.11-slim

# System deps — tini for proper signal handling, curl for healthcheck,
# Node.js for the Claude CLI (npm package @anthropic-ai/claude-code
# powers /api/autofill via subprocess).
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini curl ca-certificates gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @anthropic-ai/claude-code \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# LibreOffice (headless) renders the filled .docx proposal to PDF for the
# "Download as PDF" button (see backend/pdf_writer.py). The Writer-only subset
# keeps the image as small as this feature allows (no Calc/Impress). Carlito is
# metric-compatible with Calibri and Liberation with Arial/Times/Courier, so the
# rendered PDF lays out like Word even though those Microsoft fonts aren't shipped.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer fonts-crosextra-carlito fonts-liberation \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Treadwell's brand font (Zetta Serif Book) — the proposal templates are typeset
# in it. Install so the LibreOffice PDF export renders in the real font instead of
# substituting a fallback serif (the .docx already carries the font name).
COPY backend/fonts/ /usr/share/fonts/truetype/treadwell/
RUN fc-cache -f

WORKDIR /app

# Install Python deps first (separate layer = cache-friendly)
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the app code
COPY backend/ /app/
COPY frontend/ /app/frontend/

# Strip the comments out of the SERVED copy of the frontend. The files in the repo are not
# touched -- only the bytes inside this image. 44.7% of the raw bytes of frontend/**/*.js
# are comments and 53.1% of styles.css, and gzip does not make that free: measured against
# Content-Length on the wire, this takes the JS+CSS a browser downloads from 817,605
# gzipped bytes to 355,992, and the whole proposal-review page from 261,145 to 102,028.
#
# It strips COMMENTS and nothing else -- no terser, no mangling. The harnesses under
# backend/tests/js/ lift functions out of the real frontend files with line-anchored
# regexes, and against a terser-minified tree 1,797 of the suite's 2,786 assertions stop
# working. tools/strip-comments.js keeps every line, every line ending and every mtime
# (the last one because Starlette's ETag is md5("<mtime>-<size>"), and NoCacheStaticFiles
# in main.py needs an unchanged file to keep answering 304 after a deploy).
# backend/tests/test_frontend_comment_strip.py re-proves all of that on every CI run.
#
# In this stage rather than a separate build stage on purpose: Node is already installed
# above, and this VPS runs ~13 containers off one disk, so pulling a second base image to
# run one script is a cost the box actually feels. acorn is installed and deleted inside
# the same layer, so nothing of it survives into the image.
COPY tools/strip-comments.js /tmp/strip-comments.js
RUN cd /tmp \
 && npm install --no-save --no-audit --no-fund acorn@8.18.0 \
 && node /tmp/strip-comments.js /app/frontend \
 && rm -rf /tmp/node_modules /tmp/strip-comments.js /tmp/package.json /tmp/package-lock.json

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
