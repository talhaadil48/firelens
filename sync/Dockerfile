FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
# The pipeline writes snapshots with the API's models and the checker loads them with the API's
# loaders, so the job needs both the harvest and the api dependency groups.
RUN pip install --no-cache-dir uv==0.13.5 \
    && uv sync --frozen --no-dev --no-default-groups --group api --group harvest
COPY api ./api
COPY config ./config
COPY harvest ./harvest
COPY scripts ./scripts
COPY sync ./sync
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "sync"]
