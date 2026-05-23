# AskPicky backend + bot — one image, two entrypoints.
#
# Base image: official Playwright Python image, noble variant.
# - `noble` (Ubuntu 24.04 LTS) ships Python 3.12; `jammy` ships 3.10
#   which is below our pyproject.toml floor of >=3.11.
# - Chromium + the ~30 libs Playwright needs are pre-installed, so we
#   skip the manual `playwright install` step + ~200MB of duplicate
#   Debian deps.
# - The Playwright Python SDK version must match the chromium bundled
#   in the image, so `requirements.txt` pins `playwright==1.55.0`
#   to the same minor as this tag.
#
# Build:
#   docker build -t askpicky:latest .
#
# Run API:
#   docker run --rm -p 8000:8000 --env-file .env -v askpicky-data:/data askpicky:latest
#
# Run bot:
#   docker run --rm --env-file .env -v askpicky-data:/data askpicky:latest bot
#
# docker-compose.yml handles the multi-container orchestration.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data

WORKDIR /app

# Install Python deps first so source edits don't bust the layer cache.
COPY requirements.txt requirements-dev.txt pyproject.toml /app/
RUN pip install -r requirements.txt

# Source last — most-frequently-changing layer.
COPY src/ /app/src/
COPY scripts/ /app/scripts/
RUN pip install -e . --no-deps

# Persistent state mount. The compose file mounts a named volume here
# so SQLite + FAISS + gov-data parquets survive container restarts.
VOLUME ["/data"]

EXPOSE 8000

# Default to the API. `docker run ... bot` switches to the Telegram
# long-poller. `docker run ... shell` drops into bash.
COPY docker/entrypoint.sh /usr/local/bin/askpicky-entrypoint
RUN chmod +x /usr/local/bin/askpicky-entrypoint
ENTRYPOINT ["askpicky-entrypoint"]
CMD ["api"]
