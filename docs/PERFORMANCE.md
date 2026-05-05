# Performance and architecture notes

## Services
- `redis`: Celery broker/result backend.
- `postgres`: central transactional storage (replaces SQLite single-writer bottleneck).
- `bootstrap`: starts bank discovery pipeline.
- `worker_bootstrap`, `worker_fetch`, `worker_parse`, `worker_aggregate`: dedicated queues.
- `monitor`: `summary --watch` UI.

## Queues
- `bootstrap`
- `fetch`
- `parse`
- `aggregate`

## Data flow
`discover_banks -> fetch_report_index_batch -> parse_report_index -> fetch_report_pages_batch -> parse_report_page -> finalize_all`

## Why SQLite was slow
SQLite (even with WAL) serializes writers. With many Celery processes, this caused lock contention and many short transactions.

## What changed
- Storage moved to PostgreSQL + `psycopg_pool.ConnectionPool`.
- Added bulk DB methods for page registration/fetch success/report-link upsert.
- JSON columns moved to `jsonb` (`report_links.form_meta_json`, `failures.payload_json`).
- Removed per-page aggregation trigger from `parse_report_page`; aggregation now runs during `finalize_all`/aggregate phase.
- Intermediate parsed report JSON is now compact (no indent), final `all_banks_reports.json` remains pretty-printed.
- Celery mass tasks use `ignore_result=True`; `result_expires` configured.

## Fetch/rate-limit note
`AsyncFetcher` reuses one `httpx.AsyncClient` per batch task. Current rate limiter is local to worker task instance, not global cluster-wide.

## Env vars
- `DATABASE_URL`
- `DB_POOL_MAX_SIZE`
- `BROKER_URL`
- `RESULT_BACKEND`
- `BANK_LIMIT`
- `ONLY_OGRN`
- HTTP and Celery tuning vars from `app/config.py`

## Run
```bash
docker compose up --build
docker compose run --rm bootstrap
docker compose run --rm monitor
```

Optional:
```bash
docker compose run --rm bootstrap python -m app.cli finalize
```

## Smoke check
1. Set `BANK_LIMIT=1` (or `ONLY_OGRN=...`).
2. `docker compose up -d redis postgres worker_bootstrap worker_fetch worker_parse worker_aggregate`
3. `docker compose run --rm bootstrap`
4. Verify rows in Postgres:
   - `docker compose exec postgres psql -U postgres -d cbr_reports -c "select count(*) from banks;"`
   - `docker compose exec postgres psql -U postgres -d cbr_reports -c "select count(*) from parsed_reports;"`
5. Verify output files:
   - `data/parsed/reports/*.json`
   - `data/parsed/all_banks_reports.json`
