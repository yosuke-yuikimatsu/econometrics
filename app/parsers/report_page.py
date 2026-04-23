from __future__ import annotations

import re
from bs4 import BeautifulSoup, Tag

from app.models import ParsedReport, ParsedTable, ReportLinkRecord
from app.utils import normalize_space

FORM_CODE_RE = re.compile(r'(0409\d{3}|\b\d{3}\b)')


def parse_report_page(html: str, link: ReportLinkRecord) -> ParsedReport:
    soup = BeautifulSoup(html, 'lxml')
    root = soup.find('main') or soup.body or soup
    title = _first_text(root.select_one('h1'))
    metadata = _extract_key_value_metadata(root)
    unit = _extract_unit(root)
    form_code = link.form_code or _extract_form_code(title, metadata)
    text_blocks = _extract_text_blocks(root)
    tables = _extract_tables(root)
    sections = _extract_sections(root)
    raw_text = normalize_space(root.get_text('\n', strip=True))
    raw_html_snippet = str(root)[:1000000]
    return ParsedReport(
        ogrn=link.ogrn,
        reg_number=link.reg_number,
        name=link.bank_name,
        report_url=link.report_url,
        report_date=link.report_date,
        report_date_label=link.report_date_label,
        report_year=link.report_year,
        title=title,
        form_name=link.form_name,
        form_code=form_code,
        unit=unit,
        metadata=metadata,
        sections=sections,
        tables=tables,
        text_blocks=text_blocks,
        raw_text=raw_text,
        raw_html_snippet=raw_html_snippet,
    )


def _first_text(node: Tag | None) -> str | None:
    if node is None:
        return None
    text = normalize_space(node.get_text(' ', strip=True))
    return text or None


def _extract_key_value_metadata(root: Tag) -> dict[str, str]:
    meta: dict[str, str] = {}
    texts = [normalize_space(x.get_text(' ', strip=True)) for x in root.find_all(['p', 'div', 'dt', 'dd', 'li'], recursive=True)]
    i = 0
    while i < len(texts) - 1:
        key = texts[i]
        value = texts[i + 1]
        if key and value and len(key) < 120 and key.endswith((
            'организации',
            'номер',
            'кредитной организации',
            'Примечание',
            'Адрес (место нахождения) кредитной организации',
        )):
            meta[key] = value
            i += 2
        else:
            i += 1
    for heading in root.find_all(['h2', 'h3', 'h4']):
        txt = normalize_space(heading.get_text(' ', strip=True))
        if 'код формы' in txt.lower() and 'form_heading' not in meta:
            meta['form_heading'] = txt
    return meta


def _extract_unit(root: Tag) -> str | None:
    texts = [normalize_space(x.get_text(' ', strip=True)) for x in root.find_all(['p', 'div'])]
    for txt in texts[:50]:
        low = txt.lower()
        if any(unit in low for unit in ['тыс. рублей', 'млн руб', 'рублей', 'процентах', 'единиц']):
            return txt
    return None


def _extract_form_code(title: str | None, metadata: dict[str, str]) -> str | None:
    for src in [title or '', *metadata.values(), *metadata.keys()]:
        m = FORM_CODE_RE.search(src)
        if m:
            return m.group(1)
    return None


def _extract_sections(root: Tag) -> list[str]:
    out: list[str] = []
    for node in root.find_all(['h2', 'h3', 'h4']):
        text = normalize_space(node.get_text(' ', strip=True))
        if text:
            out.append(text)
    return out


def _extract_tables(root: Tag) -> list[ParsedTable]:
    tables: list[ParsedTable] = []
    html_tables = root.find_all('table')
    if html_tables:
        for idx, table in enumerate(html_tables):
            tables.append(_parse_html_table(table, idx))
        return tables

    synthetic = _build_synthetic_table_from_text(root)
    if synthetic is not None:
        tables.append(synthetic)
    return tables


def _parse_html_table(table: Tag, idx: int) -> ParsedTable:
    headers: list[list[str]] = []
    body_rows: list[list[str]] = []
    section_markers: list[str] = []
    caption = _first_text(table.find('caption'))
    for tr in table.find_all('tr'):
        cells = tr.find_all(['th', 'td'])
        row = [normalize_space(cell.get_text(' ', strip=True)) for cell in cells]
        if not any(row):
            continue
        if tr.find_all('th'):
            headers.append(row)
        else:
            body_rows.append(row)
            if len(row) == 1 and row[0] and len(row[0]) < 120:
                section_markers.append(row[0])
    section = _nearest_heading(table)
    return ParsedTable(
        table_index=idx,
        section=section,
        caption=caption,
        headers=headers,
        body_rows=body_rows,
        section_markers=section_markers,
        raw_html_snippet=str(table)[:250000],
        raw_text_fallback=normalize_space(table.get_text('\n', strip=True)),
    )


def _nearest_heading(node: Tag) -> str | None:
    cursor = node
    for _ in range(8):
        cursor = cursor.previous_sibling or cursor.parent
        if cursor is None:
            return None
        if isinstance(cursor, Tag) and cursor.name in {'h2', 'h3', 'h4'}:
            return normalize_space(cursor.get_text(' ', strip=True))
    return None


def _build_synthetic_table_from_text(root: Tag) -> ParsedTable | None:
    lines = [normalize_space(line) for line in root.get_text('\n').splitlines()]
    lines = [x for x in lines if x]
    if len(lines) < 8:
        return None
    start_idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if 'номер счета' in low or 'краткое наименование норматива' in low or 'порядковый номер' in low:
            start_idx = i
            break
    if start_idx is None:
        return None
    headers: list[list[str]] = []
    body: list[list[str]] = []
    section_markers: list[str] = []
    for line in lines[start_idx:start_idx + 5000]:
        if len(headers) < 3:
            headers.append([part for part in re.split(r'\s{2,}', line) if part] or [line])
            continue
        parts = [part for part in re.split(r'\s{2,}', line) if part]
        if len(parts) <= 1 and len(line) < 120:
            section_markers.append(line)
            body.append([line])
        else:
            body.append(parts or [line])
    return ParsedTable(
        table_index=0,
        section=None,
        caption=None,
        headers=headers,
        body_rows=body,
        section_markers=section_markers,
        raw_html_snippet=None,
        raw_text_fallback='\n'.join(lines[start_idx:start_idx + 5000]),
    )


def _extract_text_blocks(root: Tag) -> list[str]:
    blocks: list[str] = []
    for node in root.find_all(['p', 'li', 'div']):
        text = normalize_space(node.get_text(' ', strip=True))
        if text and 10 <= len(text) <= 2000:
            blocks.append(text)
    deduped: list[str] = []
    seen: set[str] = set()
    for b in blocks:
        if b in seen:
            continue
        seen.add(b)
        deduped.append(b)
    return deduped[:2000]
