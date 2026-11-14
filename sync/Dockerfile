FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.13.5 && uv sync --frozen --no-cache --no-dev --no-default-groups --group harvest
COPY harvest ./harvest
COPY sync ./sync
ENTRYPOINT ["uv", "run", "--no-sync", "python", "-m", "sync"]
