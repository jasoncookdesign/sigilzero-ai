up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

smoke:
	docker compose up -d --build sigilzeroai-api sigilzeroai-worker
	curl -sS http://localhost:8080/ | head
	curl -s -X POST "http://localhost:8080/jobs/run" -H "Content-Type: application/json" -d '{"job_ref":"jobs/ig-test-001/brief.yaml","params":{}}' -w "\nHTTP_STATUS=%{http_code}\n"

smoke_determinism:
	@echo "Running Phase 1.0 Determinism Smoke Tests..."
	docker exec sz_worker python /app/scripts/smoke_determinism.py

smoke_generation_modes:
	@echo "Running Stage 5 Generation Modes Smoke Tests..."
	docker exec sz_worker python /app/scripts/smoke_generation_modes_v2.py

smoke_retrieval:
	@echo "Running Stage 6 Retrieval Smoke Tests..."
	docker exec sz_worker python /app/scripts/smoke_retrieval.py

smoke_brand_compliance:
	@echo "Running Stage 7 Brand Compliance Scoring Smoke Tests..."
	docker exec sz_worker python /app/scripts/smoke_brand_compliance.py

smoke_chain:
	@echo "Running Stage 8 Chainable Pipeline Smoke Tests..."
	docker exec sz_worker python /app/scripts/smoke_brand_optimization.py

reindex:
	@echo "Rebuilding DB index from filesystem manifests..."
	docker exec -e DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/postgres sz_worker python /app/scripts/reindex_artifacts.py

reindex_verify:
	@echo "Reindex + integrity verification from filesystem manifests..."
	docker exec -e DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/postgres sz_worker python /app/scripts/reindex_artifacts.py --verify

cleanup_tmp:
	@echo "Cleaning stale tmp-* run directories older than 6 hours..."
	docker exec sz_worker python /app/scripts/cleanup_tmp.py --hours 6

smoke_registry:
	@echo "Running registry/governance smoke checks..."
	docker exec sz_worker python /app/scripts/smoke_registry.py