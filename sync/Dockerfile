FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.13.5 && uv sync --frozen --no-dev --no-default-groups --group api --group harvest
COPY api ./api
COPY config ./config
COPY harvest ./harvest
COPY sync ./sync
COPY snapshots/sample ./snapshots/sample
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "sync"]
