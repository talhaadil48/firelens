FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
# --no-cache keeps uv's download cache out of the image (smaller pull on scale-from-zero).
RUN pip install --no-cache-dir uv==0.13.5 \
 && uv sync --frozen --no-cache --no-dev --no-default-groups --group api \
 && pip uninstall -y uv
COPY api ./api
COPY config ./config
# The hourly PSI catalogue check reuses the harvester's PSI constants (httpx only).
COPY harvest/__init__.py harvest/psi.py ./harvest/
# Baked-in snapshots: the committed v1 plus the Phase 2 sample. A storage outage or a
# missing Blob pointer falls back to these (plan: Data freshness, 3).
COPY snapshots ./snapshots
RUN useradd --create-home --uid 1000 firelens && chown -R firelens /app
USER firelens
ENV PATH="/app/.venv/bin:$PATH" \
    FIRELENS_MODE=snapshot \
    FIRELENS_SNAPSHOT_DIR=/app/snapshots \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
