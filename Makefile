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