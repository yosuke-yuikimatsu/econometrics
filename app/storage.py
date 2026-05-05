from __future__ import annotations


from psycopg.types.json import Jsonb

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import orjson
import structlog
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings
from app.models import BankRecord, ParsedReport, ReportLinkRecord
from app.utils import ensure_parent, sha256_text

logger = structlog.get_logger(__name__)


SCHEMA = """
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
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
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
    fetched_at TIMESTAMPTZ,
    parsed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
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
    form_meta_json JSONB,
    report_date TEXT,
    report_date_label TEXT,
    report_year INTEGER,
    title_hint TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
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
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_parsed_reports_ogrn ON parsed_reports(ogrn);
CREATE TABLE IF NOT EXISTS failures (
    id BIGSERIAL PRIMARY KEY,
    stage TEXT NOT NULL,
    url TEXT,
    ogrn TEXT,
    payload_json JSONB,
    error TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
"""


class StateStore:
    def __init__(self, init_schema: bool = False) -> None:
        self.pool = ConnectionPool(
            conninfo=settings.database_url,
            kwargs={"row_factory": dict_row},
            min_size=1,
            max_size=settings.db_pool_max_size,
        )
        if init_schema:
            self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[Any]:
        with self.pool.connection() as conn:
            yield conn

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def init_schema(self) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA)

    def upsert_bank(self, bank: BankRecord, active: bool = True) -> None:
        now = self._now()
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO banks (ogrn, reg_number, name, license_status, org_type, legal_form, registration_date, address, source_url, reports_page_url, active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                (bank.ogrn, bank.reg_number, bank.name, bank.license_status, bank.org_type, bank.legal_form, bank.registration_date, bank.address, bank.source_url, bank.reports_page_url, active, now, now),
            )

    def register_pages_bulk(self, records: list[dict[str, str | None]]) -> None:
        now = self._now()
        values = [(sha256_text(r['url']), r['url'], r['page_kind'], r.get('ogrn'), r.get('reg_number'), r.get('source_ref'), now, now) for r in records]
        with self.connect() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO pages (url_hash, url, page_kind, ogrn, reg_number, source_ref, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(url_hash) DO UPDATE SET
                    ogrn=COALESCE(excluded.ogrn, pages.ogrn),
                    reg_number=COALESCE(excluded.reg_number, pages.reg_number),
                    source_ref=COALESCE(excluded.source_ref, pages.source_ref),
                    updated_at=excluded.updated_at
                """,
                values,
            )

    def get_pages_by_urls(self, urls: list[str]) -> dict[str, dict[str, Any]]:
        if not urls:
            return {}
        hashes = [sha256_text(u) for u in urls]
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM pages WHERE url_hash = ANY(%s)", (hashes,))
            rows = cur.fetchall()
        return {row['url']: row for row in rows}

    def mark_fetch_success_bulk(self, items: list[dict[str, str]]) -> None:
        now = self._now()
        values = [(it['html_path'], it['html_sha256'], now, now, sha256_text(it['url'])) for it in items]
        with self.connect() as conn, conn.cursor() as cur:
            cur.executemany("UPDATE pages SET html_path=%s, html_sha256=%s, fetch_status='fetched', fetched_at=%s, fetch_attempts=fetch_attempts+1, updated_at=%s WHERE url_hash=%s", values)

    def mark_fetch_skipped_cached(self, url: str, html_path: str, html_sha256: str) -> None:
        now = self._now()
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE pages SET html_path=%s, html_sha256=%s, fetch_status='fetched', fetched_at=COALESCE(fetched_at, %s), updated_at=%s WHERE url_hash=%s", (html_path, html_sha256, now, now, sha256_text(url)))

    def mark_parse_success(self, url: str) -> None:
        now = self._now()
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE pages SET parse_status='parsed', parsed_at=%s, parse_attempts=parse_attempts+1, updated_at=%s WHERE url_hash=%s", (now, now, sha256_text(url)))

    def upsert_report_links_bulk(self, links: list[ReportLinkRecord]) -> None:
        if not links:
            return

        now = self._now()
        values = [
            (
                sha256_text(l.report_url),
                l.report_url,
                l.ogrn,
                l.reg_number,
                l.bank_name,
                l.reports_page_url,
                l.section_name,
                l.form_name,
                l.form_code,
                Jsonb(l.form_meta),
                l.report_date,
                l.report_date_label,
                l.report_year,
                l.title_hint,
                now,
                now,
            )
            for l in links
        ]

        with self.connect() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO report_links (
                    url_hash, url, ogrn, reg_number, bank_name, reports_page_url,
                    section_name, form_name, form_code, form_meta_json,
                    report_date, report_date_label, report_year, title_hint,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                values,
            )

    def save_parsed_report(self, report: ParsedReport) -> Path:
        url_hash = sha256_text(report.report_url)
        path = settings.parsed_reports_dir / f'{url_hash}.json'
        ensure_parent(path)
        path.write_bytes(orjson.dumps(report.model_dump()))
        now = self._now()
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO parsed_reports (url_hash, ogrn, reg_number, form_code, form_name, report_date, parsed_json_path, title, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(url_hash) DO UPDATE SET ogrn=excluded.ogrn,reg_number=excluded.reg_number,form_code=excluded.form_code,form_name=excluded.form_name,report_date=excluded.report_date,parsed_json_path=excluded.parsed_json_path,title=excluded.title,updated_at=excluded.updated_at""", (url_hash, report.ogrn, report.reg_number, report.form_code, report.form_name, report.report_date, str(path), report.title, now))
        return path

    def iter_active_banks(self) -> list[dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT * FROM banks WHERE active=TRUE ORDER BY ogrn')
            return cur.fetchall()

    def iter_report_links_for_bank(self, ogrn: str) -> list[dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT * FROM report_links WHERE ogrn=%s ORDER BY form_name, report_date, url', (ogrn,))
            return cur.fetchall()

    def iter_parsed_reports_for_bank(self, ogrn: str) -> list[dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT * FROM parsed_reports WHERE ogrn=%s ORDER BY COALESCE(form_code, form_name), report_date, url_hash', (ogrn,))
            return cur.fetchall()
    def iter_unfetched_report_links(self, limit: int | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT
                rl.url AS report_url,
                rl.ogrn,
                rl.reg_number,
                rl.bank_name,
                rl.reports_page_url,
                rl.section_name,
                rl.form_name,
                rl.form_code,
                rl.form_meta_json AS form_meta,
                rl.report_date,
                rl.report_date_label,
                rl.report_year,
                rl.title_hint
            FROM report_links rl
            LEFT JOIN pages p ON p.url_hash = rl.url_hash
            WHERE
                p.url_hash IS NULL
                OR p.fetch_status <> 'fetched'
                OR p.html_path IS NULL
            ORDER BY rl.ogrn, rl.form_code, rl.form_name, rl.report_date, rl.url
        """
        params: tuple[Any, ...] = ()

        if limit is not None:
            query += " LIMIT %s"
            params = (limit,)

        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()
    
    def iter_fetched_unparsed_report_pages(self, limit: int | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT
                rl.url AS report_url,
                rl.ogrn,
                rl.reg_number,
                rl.bank_name,
                rl.reports_page_url,
                rl.section_name,
                rl.form_name,
                rl.form_code,
                rl.form_meta_json AS form_meta,
                rl.report_date,
                rl.report_date_label,
                rl.report_year,
                rl.title_hint,
                p.html_path
            FROM report_links rl
            JOIN pages p ON p.url_hash = rl.url_hash
            LEFT JOIN parsed_reports pr ON pr.url_hash = rl.url_hash
            WHERE
                p.page_kind = 'report_page'
                AND p.fetch_status = 'fetched'
                AND p.html_path IS NOT NULL
                AND p.parse_status <> 'parsed'
                AND pr.url_hash IS NULL
            ORDER BY rl.ogrn, rl.form_code, rl.form_name, rl.report_date, rl.url
        """
        params: tuple[Any, ...] = ()

        if limit is not None:
            query += " LIMIT %s"
            params = (limit,)

        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()
        
    def iter_fetched_unparsed_report_indexes(self, limit: int | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT
                b.ogrn,
                b.reg_number,
                b.name,
                b.license_status,
                b.org_type,
                b.legal_form,
                b.registration_date,
                b.address,
                b.source_url,
                b.reports_page_url,
                p.html_path
            FROM banks b
            JOIN pages p ON p.url = b.reports_page_url
            WHERE
                b.active = TRUE
                AND p.page_kind = 'reports_index'
                AND p.fetch_status = 'fetched'
                AND p.html_path IS NOT NULL
                AND p.parse_status <> 'parsed'
            ORDER BY b.ogrn
        """
        params: tuple[Any, ...] = ()

        if limit is not None:
            query += " LIMIT %s"
            params = (limit,)

        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def counters(self) -> dict[str, int | float]:
        out: dict[str, int | float] = {}

        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE active=TRUE) AS banks_active,
                    COUNT(*) AS banks_discovered
                FROM banks
                """
            )
            row = cur.fetchone()
            out["banks_discovered"] = int(row["banks_discovered"])
            out["banks_active"] = int(row["banks_active"])

            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE page_kind='reports_index') AS report_index_total,
                    COUNT(*) FILTER (WHERE page_kind='reports_index' AND fetch_status='fetched') AS report_index_fetched,
                    COUNT(*) FILTER (WHERE page_kind='reports_index' AND parse_status='parsed') AS report_index_parsed,

                    COUNT(*) FILTER (WHERE page_kind='report_page') AS report_pages_total,
                    COUNT(*) FILTER (WHERE page_kind='report_page' AND fetch_status='fetched') AS report_pages_fetched,
                    COUNT(*) FILTER (WHERE page_kind='report_page' AND parse_status='parsed') AS report_pages_parsed,

                    COUNT(*) FILTER (WHERE fetch_status='error') AS fetch_errors,
                    COUNT(*) FILTER (WHERE parse_status='error') AS parse_errors
                FROM pages
                """
            )
            row = cur.fetchone()

            for key in [
                "report_index_total",
                "report_index_fetched",
                "report_index_parsed",
                "report_pages_total",
                "report_pages_fetched",
                "report_pages_parsed",
                "fetch_errors",
                "parse_errors",
            ]:
                out[key] = int(row[key] or 0)

            total = int(row["report_pages_total"] or 0)
            fetched = int(row["report_pages_fetched"] or 0)
            parsed = int(row["report_pages_parsed"] or 0)

            out["report_pages_fetch_remaining"] = max(total - fetched, 0)
            out["report_pages_parse_remaining"] = max(total - parsed, 0)

            out["report_pages_fetch_pct"] = round(100.0 * fetched / total, 2) if total else 0.0
            out["report_pages_parse_pct"] = round(100.0 * parsed / total, 2) if total else 0.0

            cur.execute("SELECT COUNT(*) AS cnt FROM report_links")
            out["reports_discovered"] = int(cur.fetchone()["cnt"])

            cur.execute("SELECT COUNT(*) AS cnt FROM parsed_reports")
            out["parsed_reports_saved"] = int(cur.fetchone()["cnt"])

            cur.execute("SELECT COUNT(*) AS cnt FROM failures")
            out["errors"] = int(cur.fetchone()["cnt"])

            cur.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN fetch_attempts > 1 THEN fetch_attempts - 1 ELSE 0 END), 0)
                    +
                    COALESCE(SUM(CASE WHEN parse_attempts > 1 THEN parse_attempts - 1 ELSE 0 END), 0)
                    AS cnt
                FROM pages
                """
            )
            out["retries"] = int(cur.fetchone()["cnt"])

        return out
