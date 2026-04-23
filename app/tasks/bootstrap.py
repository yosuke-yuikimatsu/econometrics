from __future__ import annotations

import math

from celery import shared_task
import structlog

from app.http_client import AsyncFetcher
from app.models import BankRecord
from app.parsers.banks import parse_banks_list
from app.storage import StateStore
from app.config import settings

logger = structlog.get_logger(__name__)
store = StateStore()


def _is_active_license(status: str) -> bool:
    low = (status or '').strip().lower()
    return low in {'', 'действующая'} or 'действующ' in low


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=600, retry_jitter=True, max_retries=7)
def discover_banks(self) -> dict[str, int]:
    async def _run() -> str:
        fetcher = AsyncFetcher()
        try:
            result = await fetcher.fetch_one(settings.cbr_full_list_url)
            return result.text
        finally:
            await fetcher.aclose()

    html = __import__('asyncio').run(_run())
    banks = parse_banks_list(html, settings.cbr_full_list_url)
    filtered: list[BankRecord] = []

    only_ogrn = {x.strip() for x in settings.only_ogrn.split(',') if x.strip()}
    for bank in banks:
        active = _is_active_license(bank.license_status)
        store.upsert_bank(bank, active=active)
        if not active:
            continue
        if only_ogrn and bank.ogrn not in only_ogrn:
            continue
        filtered.append(bank)

    if settings.bank_limit > 0:
        filtered = filtered[: settings.bank_limit]

    batch_size = max(1, settings.fetch_bank_batch_size)
    total_batches = math.ceil(len(filtered) / batch_size) if filtered else 0
    for i in range(0, len(filtered), batch_size):
        batch = [bank.model_dump() for bank in filtered[i:i + batch_size]]
        from app.tasks.fetch import fetch_report_index_batch
        fetch_report_index_batch.delay(batch)

    logger.info('banks_discovered', total=len(banks), active=len(filtered), batches=total_batches)
    return {'banks_total': len(banks), 'banks_active': len(filtered), 'batches': total_batches}
