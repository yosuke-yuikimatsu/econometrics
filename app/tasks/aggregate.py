from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from celery import shared_task
import orjson
import structlog

from app.config import settings
from app.storage import StateStore

logger = structlog.get_logger(__name__)
store = StateStore()


def _load_json(path: str) -> dict:
    return orjson.loads(Path(path).read_bytes())


@shared_task(bind=True)
def update_bank_snapshot(self, ogrn: str) -> dict[str, str]:
    banks = {row['ogrn']: row for row in store.iter_active_banks()}
    bank = banks.get(ogrn)
    if bank is None:
        return {'status': 'skipped', 'ogrn': ogrn}

    report_links = store.iter_report_links_for_bank(ogrn)
    parsed_rows = store.iter_parsed_reports_for_bank(ogrn)
    parsed_by_hash = {row['url_hash']: _load_json(row['parsed_json_path']) for row in parsed_rows if Path(row['parsed_json_path']).exists()}

    forms_map: dict[tuple[str | None, str], dict] = {}
    for link_row in report_links:
        key = (link_row['form_code'], link_row['form_name'])
        if key not in forms_map:
            forms_map[key] = {
                'form_name': link_row['form_name'],
                'form_code': link_row['form_code'],
                'reports': [],
            }
        report_data = parsed_by_hash.get(link_row['url_hash'])
        if report_data is not None:
            forms_map[key]['reports'].append(report_data)

    for form in forms_map.values():
        form['reports'].sort(key=lambda x: ((x.get('report_date') or ''), x.get('report_url') or ''))

    bank_json = {
        'ogrn': bank['ogrn'],
        'reg_number': bank['reg_number'],
        'name': bank['name'],
        'license_status': bank['license_status'],
        'source_url': bank['source_url'],
        'reports_page_url': bank['reports_page_url'],
        'forms': sorted(forms_map.values(), key=lambda x: ((x.get('form_code') or ''), x.get('form_name') or '')),
    }
    out_path = settings.parsed_banks_dir / f'{ogrn}.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(orjson.dumps(bank_json, option=orjson.OPT_INDENT_2))
    return {'status': 'ok', 'ogrn': ogrn, 'path': str(out_path)}


@shared_task(bind=True)
def finalize_all(self) -> dict[str, str | int]:
    banks_out = []
    reports_total = 0
    for bank in store.iter_active_banks():
        bank_path = settings.parsed_banks_dir / f"{bank['ogrn']}.json"
        if not bank_path.exists():
            update_bank_snapshot.apply(args=[bank['ogrn']])
        if bank_path.exists():
            payload = orjson.loads(bank_path.read_bytes())
            reports_total += sum(len(form.get('reports', [])) for form in payload.get('forms', []))
            banks_out.append(payload)
    result = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source': 'cbr.ru',
        'banks_total': len(banks_out),
        'reports_total': reports_total,
        'banks': banks_out,
    }
    out_path = settings.data_dir / 'parsed' / 'all_banks_reports.json'
    out_path.write_bytes(orjson.dumps(result, option=orjson.OPT_INDENT_2))
    logger.info('finalize_done', path=str(out_path), banks_total=len(banks_out), reports_total=reports_total)
    return {'path': str(out_path), 'banks_total': len(banks_out), 'reports_total': reports_total}
