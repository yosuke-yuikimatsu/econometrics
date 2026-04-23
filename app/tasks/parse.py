from __future__ import annotations

from pathlib import Path

from celery import shared_task
import structlog

from app.config import settings
from app.models import ReportLinkRecord
from app.parsers.report_page import parse_report_page as parse_report_page_html
from app.parsers.reports_index import parse_reports_index
from app.storage import StateStore

logger = structlog.get_logger(__name__)
store = StateStore()


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=600, retry_jitter=True, max_retries=7)
def parse_report_index(self, bank: dict, html_path: str) -> dict[str, int]:
    html = Path(html_path).read_text('utf-8')
    links = parse_reports_index(
        html=html,
        reports_page_url=bank['reports_page_url'],
        ogrn=bank['ogrn'],
        reg_number=bank['reg_number'],
        bank_name=bank['name'],
    )
    for link in links:
        store.upsert_report_link(link)
        store.register_page(link.report_url, page_kind='report_page', ogrn=link.ogrn, reg_number=link.reg_number, source_ref=link.reports_page_url)
    store.mark_parse_success(bank['reports_page_url'])

    batches = [links[i:i + settings.fetch_report_batch_size] for i in range(0, len(links), settings.fetch_report_batch_size)]
    from app.tasks.fetch import fetch_report_pages_batch
    for batch in batches:
        fetch_report_pages_batch.delay([item.model_dump() for item in batch])

    logger.info('report_index_parsed', ogrn=bank['ogrn'], reports=len(links), batches=len(batches))
    return {'reports_discovered': len(links), 'batches': len(batches)}


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=600, retry_jitter=True, max_retries=7)
def parse_report_page(self, link_payload: dict, html_path: str) -> dict[str, str]:
    link = ReportLinkRecord(**link_payload)
    html = Path(html_path).read_text('utf-8')
    report = parse_report_page_html(html, link)
    out_path = store.save_parsed_report(report)
    store.mark_parse_success(link.report_url)
    from app.tasks.aggregate import update_bank_snapshot
    update_bank_snapshot.delay(link.ogrn)
    logger.info('report_page_parsed', ogrn=link.ogrn, url=link.report_url, output=str(out_path))
    return {'ogrn': link.ogrn, 'report_url': link.report_url, 'output': str(out_path)}
