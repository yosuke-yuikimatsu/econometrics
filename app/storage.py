from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import orjson
import structlog

from app.config import settings
from app.models import BankRecord, ParsedReport, ReportLinkRecord
from app.utils import ensure_parent, sha256_text

logger = structlog.get_logger(__name__)


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS banks (
    ogrn TEXT PRIMARY KEY,
    reg_number TEXT NOT NULL,
    name TEXT NOT NULL,
    license_status TEXT NOT NULL,
    org_type TEXT,
    legal_form TEXT,
    registration_date TEXT,
    address TEXT,
    source_url TEXT NOT NULL,
    reports_page_url TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    url_hash TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    page_kind TEXT NOT NULL,
    ogrn TEXT,
    reg_number TEXT,
    source_ref TEXT,
    html_path TEXT,
    html_sha256 TEXT,
    fetch_status TEXT NOT NULL DEFAULT 'pending',
    parse_status TEXT NOT NULL DEFAULT 'pending',
    fetch_attempts INTEGER NOT NULL DEFAULT 0,
    parse_attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    fetched_at TEXT,
    parsed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pages_ogrn ON pages(ogrn);
CREATE INDEX IF NOT EXISTS idx_pages_kind_fetch ON pages(page_kind, fetch_status);
CREATE INDEX IF NOT EXISTS idx_pages_kind_parse ON pages(page_kind, parse_status);
CREATE TABLE IF NOT EXISTS report_links (
    url_hash TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    ogrn TEXT NOT NULL,
    reg_number TEXT NOT NULL,
    bank_name TEXT NOT NULL,
    reports_page_url TEXT NOT NULL,
    section_name TEXT,
    form_name TEXT NOT NULL,
    form_code TEXT,
    form_meta_json BLOB,
    report_date TEXT,
    report_date_label TEXT,
    report_year INTEGER,
    title_hint TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_links_ogrn ON report_links(ogrn);
CREATE TABLE IF NOT EXISTS parsed_reports (
    url_hash TEXT PRIMARY KEY,
    ogrn TEXT NOT NULL,
    reg_number TEXT NOT NULL,
    form_code TEXT,
    form_name TEXT,
    report_date TEXT,
    parsed_json_path TEXT NOT NULL,
    title TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_parsed_reports_ogrn ON parsed_reports(ogrn);
CREATE TABLE IF NOT EXISTS metrics (
    metric_key TEXT PRIMARY KEY,
    metric_value INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage TEXT NOT NULL,
    url TEXT,
    ogrn TEXT,
    payload_json BLOB,
    error TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class StateStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.state_db_path
        ensure_parent(self.db_path)
        self._init_db()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=60, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def upsert_bank(self, bank: BankRecord, active: bool = True) -> None:
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO banks (ogrn, reg_number, name, license_status, org_type, legal_form, registration_date, address, source_url, reports_page_url, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ogrn) DO UPDATE SET
                    reg_number=excluded.reg_number,
                    name=excluded.name,
                    license_status=excluded.license_status,
                    org_type=excluded.org_type,
                    legal_form=excluded.legal_form,
                    registration_date=excluded.registration_date,
                    address=excluded.address,
                    source_url=excluded.source_url,
                    reports_page_url=excluded.reports_page_url,
                    active=excluded.active,
                    updated_at=excluded.updated_at
                """,
                (
                    bank.ogrn, bank.reg_number, bank.name, bank.license_status, bank.org_type, bank.legal_form,
                    bank.registration_date, bank.address, bank.source_url, bank.reports_page_url,
                    1 if active else 0, now, now,
                ),
            )

    def register_page(self, url: str, page_kind: str, ogrn: str | None = None, reg_number: str | None = None, source_ref: str | None = None) -> str:
        now = self._now()
        url_hash = sha256_text(url)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pages (url_hash, url, page_kind, ogrn, reg_number, source_ref, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url_hash) DO UPDATE SET
                    ogrn=COALESCE(excluded.ogrn, pages.ogrn),
                    reg_number=COALESCE(excluded.reg_number, pages.reg_number),
                    source_ref=COALESCE(excluded.source_ref, pages.source_ref),
                    updated_at=excluded.updated_at
                """,
                (url_hash, url, page_kind, ogrn, reg_number, source_ref, now, now),
            )
        return url_hash

    def mark_fetch_success(self, url: str, html_path: str, html_sha256: str) -> None:
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE pages
                SET html_path=?, html_sha256=?, fetch_status='fetched', fetched_at=?, fetch_attempts=fetch_attempts+1, updated_at=?
                WHERE url_hash=?
                """,
                (html_path, html_sha256, now, now, sha256_text(url)),
            )

    def mark_fetch_skipped_cached(self, url: str, html_path: str, html_sha256: str) -> None:
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE pages
                SET html_path=?, html_sha256=?, fetch_status='fetched', fetched_at=COALESCE(fetched_at, ?), updated_at=?
                WHERE url_hash=?
                """,
                (html_path, html_sha256, now, now, sha256_text(url)),
            )

    def mark_parse_success(self, url: str) -> None:
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE pages SET parse_status='parsed', parsed_at=?, parse_attempts=parse_attempts+1, updated_at=? WHERE url_hash=?",
                (now, now, sha256_text(url)),
            )

    def mark_error(self, stage: str, url: str | None, ogrn: str | None, payload: dict[str, Any] | None, error: str, incr_attempt_on_pages: bool = False) -> None:
        now = self._now()
        url_hash = sha256_text(url) if url else None
        payload_blob = orjson.dumps(payload or {})
        with self.connect() as conn:
            conn.execute(
                'INSERT INTO failures (stage, url, ogrn, payload_json, error, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                (stage, url, ogrn, payload_blob, error, now),
            )
            if url_hash:
                field = 'fetch_attempts' if stage.startswith('fetch') else 'parse_attempts'
                status_field = 'fetch_status' if stage.startswith('fetch') else 'parse_status'
                conn.execute(
                    f"UPDATE pages SET {status_field}='error', last_error=?, {field}={field}+?, updated_at=? WHERE url_hash=?",
                    (error[:4000], 1 if incr_attempt_on_pages else 0, now, url_hash),
                )

    def get_page(self, url: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM pages WHERE url_hash=?', (sha256_text(url),)).fetchone()
            return row

    def upsert_report_link(self, link: ReportLinkRecord) -> str:
        now = self._now()
        url_hash = sha256_text(link.report_url)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO report_links (url_hash, url, ogrn, reg_number, bank_name, reports_page_url, section_name, form_name, form_code, form_meta_json, report_date, report_date_label, report_year, title_hint, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url_hash) DO UPDATE SET
                    ogrn=excluded.ogrn,
                    reg_number=excluded.reg_number,
                    bank_name=excluded.bank_name,
                    reports_page_url=excluded.reports_page_url,
                    section_name=excluded.section_name,
                    form_name=excluded.form_name,
                    form_code=excluded.form_code,
                    form_meta_json=excluded.form_meta_json,
                    report_date=COALESCE(excluded.report_date, report_links.report_date),
                    report_date_label=COALESCE(excluded.report_date_label, report_links.report_date_label),
                    report_year=COALESCE(excluded.report_year, report_links.report_year),
                    title_hint=COALESCE(excluded.title_hint, report_links.title_hint),
                    updated_at=excluded.updated_at
                """,
                (
                    url_hash, link.report_url, link.ogrn, link.reg_number, link.bank_name, link.reports_page_url, link.section_name,
                    link.form_name, link.form_code, orjson.dumps(link.form_meta), link.report_date, link.report_date_label,
                    link.report_year, link.title_hint, now, now,
                ),
            )
        return url_hash

    def save_parsed_report(self, report: ParsedReport) -> Path:
        url_hash = sha256_text(report.report_url)
        path = settings.parsed_reports_dir / f'{url_hash}.json'
        ensure_parent(path)
        path.write_bytes(orjson.dumps(report.model_dump(), option=orjson.OPT_INDENT_2))
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO parsed_reports (url_hash, ogrn, reg_number, form_code, form_name, report_date, parsed_json_path, title, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url_hash) DO UPDATE SET
                    ogrn=excluded.ogrn,
                    reg_number=excluded.reg_number,
                    form_code=excluded.form_code,
                    form_name=excluded.form_name,
                    report_date=excluded.report_date,
                    parsed_json_path=excluded.parsed_json_path,
                    title=excluded.title,
                    updated_at=excluded.updated_at
                """,
                (url_hash, report.ogrn, report.reg_number, report.form_code, report.form_name, report.report_date, str(path), report.title, now),
            )
        return path

    def iter_active_banks(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute('SELECT * FROM banks WHERE active=1 ORDER BY ogrn').fetchall()

    def iter_report_links_for_bank(self, ogrn: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute('SELECT * FROM report_links WHERE ogrn=? ORDER BY form_name, report_date, url', (ogrn,)).fetchall()

    def iter_parsed_reports_for_bank(self, ogrn: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute('SELECT * FROM parsed_reports WHERE ogrn=? ORDER BY COALESCE(form_code, form_name), report_date, url_hash', (ogrn,)).fetchall()

    def counters(self) -> dict[str, int]:
        with self.connect() as conn:
            queries = {
                'banks_discovered': 'SELECT COUNT(*) FROM banks',
                'banks_active': 'SELECT COUNT(*) FROM banks WHERE active=1',
                'report_index_pages_fetched': "SELECT COUNT(*) FROM pages WHERE page_kind='reports_index' AND fetch_status='fetched'",
                'report_pages_fetched': "SELECT COUNT(*) FROM pages WHERE page_kind='report_page' AND fetch_status='fetched'",
                'report_pages_parsed': "SELECT COUNT(*) FROM pages WHERE page_kind='report_page' AND parse_status='parsed'",
                'errors': 'SELECT COUNT(*) FROM failures',
                'retries': "SELECT COALESCE(SUM(CASE WHEN fetch_attempts > 1 THEN fetch_attempts - 1 ELSE 0 END),0) + COALESCE(SUM(CASE WHEN parse_attempts > 1 THEN parse_attempts - 1 ELSE 0 END),0) FROM pages",
                'reports_discovered': 'SELECT COUNT(*) FROM report_links',
            }
            return {k: int(conn.execute(v).fetchone()[0]) for k, v in queries.items()}
