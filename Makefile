.PHONY: setup spike harvest normalize precompute snapshot api web test lint contracts fixtures docker-api docker-sync
setup:
	uv sync --frozen
	cd web && npm ci
spike:
	uv run python -m harvest.spike
harvest: spike
normalize:
	uv run python -m harvest.pipeline normalize
precompute:
	uv run python -m harvest.pipeline precompute
snapshot:
	uv run python -m harvest.pipeline snapshot
api:
	uv run uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
web:
	cd web && npm run dev -- --host 127.0.0.1
lint:
	uv run ruff check .
	uv run ruff format --check .
	cd web && npm run lint
contracts:
	uv run python -m scripts.export_contracts
fixtures:
	uv run python -m scripts.build_fixtures --fetch
test:
	uv run pytest
	cd web && npm test
	cd web && npm run build
docker-api:
	docker build -f api/Dockerfile -t firelens-api .
docker-sync:
	docker build -f sync/Dockerfile -t firelens-sync .
