from __future__ import annotations

from celery import shared_task
import structlog

from app.config import settings
from app.store_provider import get_store

logger = structlog.get_logger(__name__)


def _chunks(items: list[dict], size: int) -> list[list[dict]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


@shared_task(bind=True)
def resume_fetch_report_pages(self, limit: int | None = None) -> dict[str, int]:
    store = get_store()
    links = store.iter_unfetched_report_links(limit=limit)

    from app.tasks.fetch import fetch_report_pages_batch

    batch_size = max(1, settings.fetch_report_batch_size)
    batches = _chunks(links, batch_size)

    for batch in batches:
        fetch_report_pages_batch.delay(batch)

    logger.info(
        "resume_fetch_report_pages_queued",
        links=len(links),
        batches=len(batches),
    )
    return {"links": len(links), "batches": len(batches)}


@shared_task(bind=True)
def resume_parse_report_pages(self, limit: int | None = None) -> dict[str, int]:
    store = get_store()
    rows = store.iter_fetched_unparsed_report_pages(limit=limit)

    from app.tasks.parse import parse_report_page

    count = 0
    for row in rows:
        html_path = row.pop("html_path")
        parse_report_page.delay(row, html_path)
        count += 1

    logger.info("resume_parse_report_pages_queued", pages=count)
    return {"pages": count}


@shared_task(bind=True)
def resume_parse_report_indexes(self, limit: int | None = None) -> dict[str, int]:
    store = get_store()
    rows = store.iter_fetched_unparsed_report_indexes(limit=limit)

    from app.tasks.parse import parse_report_index

    count = 0
    for row in rows:
        html_path = row.pop("html_path")
        parse_report_index.delay(row, html_path)
        count += 1

    logger.info("resume_parse_report_indexes_queued", indexes=count)
    return {"indexes": count}


@shared_task(bind=True)
def resume_all(self, limit: int | None = None) -> dict[str, int]:
    idx = resume_parse_report_indexes.apply(args=[limit]).get()
    fetch = resume_fetch_report_pages.apply(args=[limit]).get()
    parse = resume_parse_report_pages.apply(args=[limit]).get()

    result = {
        "indexes_queued": idx["indexes"],
        "fetch_links_queued": fetch["links"],
        "fetch_batches_queued": fetch["batches"],
        "parse_pages_queued": parse["pages"],
    }

    logger.info("resume_all_done", **result)
    return result