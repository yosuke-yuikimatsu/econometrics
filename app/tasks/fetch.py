from __future__ import annotations

import asyncio
from pathlib import Path

from celery import shared_task
import structlog

from app.config import settings
from app.http_client import AsyncFetcher
from app.storage import StateStore
from app.utils import ensure_parent, sha256_bytes, sha256_text

logger = structlog.get_logger(__name__)
store = StateStore()


def _raw_path(url: str, page_kind: str) -> Path:
    return settings.raw_dir / page_kind / f'{sha256_text(url)}.html'


async def _fetch_and_cache(records: list[dict], page_kind: str) -> list[dict]:
    fetcher = AsyncFetcher()
    try:
        store.register_pages_bulk(records)
        rows = store.get_pages_by_urls([r['url'] for r in records])
        urls_to_fetch: list[str] = []
        prepared: list[dict] = []
        for rec in records:
            row = rows.get(rec['url'])
            if row and row['fetch_status'] == 'fetched' and row['html_path'] and Path(row['html_path']).exists():
                html_bytes = Path(row['html_path']).read_bytes()
                store.mark_fetch_skipped_cached(rec['url'], row['html_path'], row['html_sha256'] or sha256_bytes(html_bytes))
                prepared.append({**rec, 'html_path': row['html_path'], 'cached': True})
            else:
                urls_to_fetch.append(rec['url'])

        fetched_map: dict[str, dict] = {}
        mark_items: list[dict[str, str]] = []
        if urls_to_fetch:
            for item in await fetcher.fetch_many(urls_to_fetch):
                raw_path = _raw_path(item.url, page_kind)
                ensure_parent(raw_path)
                html_bytes = item.text.encode('utf-8')
                raw_path.write_bytes(html_bytes)
                html_sha = sha256_bytes(html_bytes)
                fetched_map[item.url] = {'html_path': str(raw_path), 'cached': False}
                mark_items.append({'url': item.url, 'html_path': str(raw_path), 'html_sha256': html_sha})
            store.mark_fetch_success_bulk(mark_items)

        for rec in records:
            if rec['url'] in fetched_map:
                prepared.append({**rec, **fetched_map[rec['url']]})
        return prepared
    finally:
        await fetcher.aclose()


@shared_task(bind=True, ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=600, retry_jitter=True, max_retries=7)
def fetch_report_index_batch(self, bank_batch: list[dict]) -> None:
    records = [
        {'url': bank['reports_page_url'], 'ogrn': bank['ogrn'], 'reg_number': bank['reg_number'], 'source_ref': bank['source_url'], 'page_kind': 'reports_index', 'bank': bank}
        for bank in bank_batch
    ]
    prepared = asyncio.run(_fetch_and_cache(records, 'reports_index'))
    from app.tasks.parse import parse_report_index
    for item in prepared:
        parse_report_index.delay(item['bank'], item['html_path'])
    logger.info('report_index_fetch_batch_done', total=len(prepared))


@shared_task(bind=True, ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=600, retry_jitter=True, max_retries=7)
def fetch_report_pages_batch(self, report_batch: list[dict]) -> None:
    records = [
        {'url': item['report_url'], 'ogrn': item['ogrn'], 'reg_number': item['reg_number'], 'source_ref': item['reports_page_url'], 'page_kind': 'report_page', 'payload': item}
        for item in report_batch
    ]
    prepared = asyncio.run(_fetch_and_cache(records, 'report_page'))
    from app.tasks.parse import parse_report_page
    for item in prepared:
        parse_report_page.delay(item['payload'], item['html_path'])
    logger.info('report_pages_fetch_batch_done', total=len(prepared))
