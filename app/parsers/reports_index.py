from __future__ import annotations

import re
from bs4 import BeautifulSoup, Tag

from app.models import ReportLinkRecord
from app.utils import abs_url, normalize_space, parse_russian_date_label

FORM_CODE_RE = re.compile(r'(?:ОКУД\s*)?(0409\d{3}|\d{3})')
YEAR_RE = re.compile(r'(20\d{2})')


def parse_reports_index(html: str, reports_page_url: str, ogrn: str, reg_number: str, bank_name: str) -> list[ReportLinkRecord]:
    soup = BeautifulSoup(html, 'lxml')
    content_root = soup.find('main') or soup.body or soup
    links: list[ReportLinkRecord] = []
    current_section: str | None = None
    current_form_name: str | None = None
    current_form_code: str | None = None
    current_year: int | None = None

    for node in content_root.descendants:
        if not isinstance(node, Tag):
            continue
        tag_name = node.name.lower()
        if tag_name == 'h2':
            current_section = normalize_space(node.get_text(' ', strip=True))
        elif tag_name == 'h3':
            current_form_name = normalize_space(node.get_text(' ', strip=True))
            m = FORM_CODE_RE.search(current_form_name)
            current_form_code = m.group(1) if m else _extract_form_code_from_neighbors(node)
        elif tag_name in {'p', 'div'}:
            text = normalize_space(node.get_text(' ', strip=True))
            year_match = YEAR_RE.findall(text)
            if year_match and 'год' in text.lower() and len(text) < 400:
                # Multiple years can appear in the same block; anchors following each year are still processed via href patterns.
                pass
        elif tag_name == 'a' and node.get('href'):
            href = abs_url(reports_page_url, node.get('href'))
            if not href:
                continue
            anchor_text = normalize_space(node.get_text(' ', strip=True))
            if not _looks_like_report_link(href, anchor_text):
                continue
            inferred_year = _extract_year_from_href_or_context(href, node) or current_year or _nearest_year(node)
            report_date = _extract_iso_date_from_href(href) or parse_russian_date_label(anchor_text, inferred_year)
            links.append(ReportLinkRecord(
                ogrn=ogrn,
                reg_number=reg_number,
                bank_name=bank_name,
                reports_page_url=reports_page_url,
                section_name=current_section,
                form_name=current_form_name or anchor_text,
                form_code=current_form_code,
                form_meta={},
                report_date=report_date,
                report_date_label=anchor_text,
                report_year=inferred_year,
                report_url=href,
                title_hint=current_section,
            ))
    return _dedupe_links(links)


def _extract_form_code_from_neighbors(node: Tag) -> str | None:
    sib_texts = []
    for sib in list(node.next_siblings)[:3]:
        if isinstance(sib, Tag):
            sib_texts.append(normalize_space(sib.get_text(' ', strip=True)))
        else:
            sib_texts.append(normalize_space(str(sib)))
    joined = ' '.join(filter(None, sib_texts))
    m = FORM_CODE_RE.search(joined)
    return m.group(1) if m else None


def _looks_like_report_link(href: str, text: str) -> bool:
    return ('/banking_sector/credit/coinfo/' in href or '/finorg/foinfo/' in href) and ('на ' in text.lower() or 'по состоянию' in text.lower())


def _extract_iso_date_from_href(href: str) -> str | None:
    m = re.search(r'dt=(\d{4}-\d{2}-\d{2})', href)
    return m.group(1) if m else None


def _extract_year_from_href_or_context(href: str, node: Tag) -> int | None:
    date_m = re.search(r'dt=(20\d{2})-\d{2}-\d{2}', href)
    if date_m:
        return int(date_m.group(1))
    return _nearest_year(node)


def _nearest_year(node: Tag) -> int | None:
    cursor = node
    for _ in range(10):
        cursor = cursor.previous_sibling or cursor.parent
        if cursor is None:
            return None
        text = normalize_space(cursor.get_text(' ', strip=True) if isinstance(cursor, Tag) else str(cursor))
        years = YEAR_RE.findall(text)
        if years:
            return int(years[-1])
    return None


def _dedupe_links(links: list[ReportLinkRecord]) -> list[ReportLinkRecord]:
    seen: set[str] = set()
    out: list[ReportLinkRecord] = []
    for item in links:
        if item.report_url in seen:
            continue
        seen.add(item.report_url)
        out.append(item)
    return out
