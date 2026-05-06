# CBR bank reports parser

Production-grade parser for credit organization reports from cbr.ru.

## Start

### *Increase concurrency for worker-parser. In the current setup it takes more than an hour to just parse*

```bash
cp .env.example .env
mkdir -p data/raw data/parsed/reports data/parsed/banks data/manifests
docker compose build --no-cache
docker compose up -d postgres redis
docker compose run --rm bootstrap python -m app.cli init-db
docker compose up -d worker_bootstrap worker_fetch worker_parse worker_aggregate
docker compose run --rm bootstrap
```

## Smoke test

Set one of these in `.env`:

```env
BANK_LIMIT=1
# or
ONLY_OGRN=1022200525841
```

Then run bootstrap again.

## Full run

```env
BANK_LIMIT=0
ONLY_OGRN=
```

```bash
docker compose run --rm bootstrap
```

## Final JSON

```bash
docker compose run --rm bootstrap python -m app.cli finalize
```

Output:

`data/parsed/all_banks_reports.json`

## Progress

```bash
docker compose logs -f worker_fetch worker_parse worker_aggregate
watch -n 10 'df -h; echo; find data/parsed/banks -type f | wc -l; du -sh data/parsed/banks data/parsed/all_banks_reports.json 2>/dev/null; ls -lh data/parsed/all_banks_reports.json 2>/dev/null'(VM specific)
```


## Architecture and performance
See `docs/PERFORMANCE.md` for PostgreSQL/Celery pipeline details and tuning notes.


