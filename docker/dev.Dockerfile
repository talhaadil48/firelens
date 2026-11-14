# Development image: Python 3.12 + uv + Node 22 + make + git.
# Used by compose.yaml (api, web, dev services) and .devcontainer/.
# Source code is bind-mounted at runtime; nothing from the repo is baked in.
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends make git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# Node 22 (matches .nvmrc) copied from the official image.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# uv pinned to the same version as api/Dockerfile and sync/Dockerfile.
RUN pip install --no-cache-dir uv==0.13.5

# Keep the virtualenv outside the bind-mounted repo so it never collides with a
# host .venv (Windows) and survives in a named volume.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /workspace
