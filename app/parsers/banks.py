from __future__ import annotations

import re
from bs4 import BeautifulSoup

from app.models import BankRecord
from app.utils import abs_url, normalize_space


def parse_banks_list(html: str, source_url: str) -> list[BankRecord]:
    soup = BeautifulSoup(html, 'lxml')
    table = soup.find('table')
    if table is None:
        # CBR often renders a large data block without <table>; fall back to sequential row parsing.
        return _parse_from_text_grid(soup, source_url)

    rows = table.find_all('tr')
    banks: list[BankRecord] = []
    for row in rows[1:]:
        cells = row.find_all(['td', 'th'])
        if len(cells) < 8:
            continue
        link = row.find('a', href=True)
        if not link:
            continue
        texts = [normalize_space(c.get_text(' ', strip=True)) for c in cells]
        name = normalize_space(link.get_text(' ', strip=True))
        ogrn = _extract_ogrn(texts)
        reg_number = _extract_regnum(texts)
        license_status = _extract_license_status(texts)
        org_type = texts[1] if len(texts) > 8 else None
        legal_form = texts[4] if len(texts) > 4 else None
        registration_date = texts[5] if len(texts) > 5 else None
        address = texts[-1] if texts else None
        if not ogrn or not reg_number:
            continue
        detail_url = abs_url(source_url, link.get('href')) or source_url
        reports_page_url = f'https://www.cbr.ru/finorg/foinfo/reports/?ogrn={ogrn}'
        banks.append(BankRecord(
            ogrn=ogrn,
            reg_number=reg_number,
            name=name,
            license_status=license_status or '',
            org_type=org_type,
            legal_form=legal_form,
            registration_date=registration_date,
            address=address,
            source_url=detail_url,
            reports_page_url=reports_page_url,
        ))
    return banks


def _extract_ogrn(texts: list[str]) -> str | None:
    for t in texts:
        m = re.fullmatch(r'\d{13}', t.replace(' ', ''))
        if m:
            return m.group(0)
    return None


def _extract_regnum(texts: list[str]) -> str | None:
    for t in texts:
        s = t.replace(' ', '')
        if re.fullmatch(r'\d{1,6}', s):
            return s
    return None


def _extract_license_status(texts: list[str]) -> str:
    for t in texts:
        low = t.lower()
        if any(key in low for key in ['действующ', 'отозван', 'аннулирован', 'рег']):
            return t
    return ''


def _parse_from_text_grid(soup: BeautifulSoup, source_url: str) -> list[BankRecord]:
    banks: list[BankRecord] = []
    for a in soup.select('a[href]'):
        name = normalize_space(a.get_text(' ', strip=True))
        href = a.get('href')
        prev = a.previous_sibling or ''
        next_text = a.parent.get_text(' ', strip=True)
        row_text = normalize_space(f'{prev} {next_text}')
        numbers = re.findall(r'\d{1,6}|\d{13}', row_text)
        ogrn = next((x for x in numbers if len(x) == 13), None)
        regnum = next((x for x in numbers if len(x) < 13), None)
        if not ogrn or not regnum:
            continue
        status = 'Действующая' if 'действующ' in row_text.lower() else ('Отозванная' if 'отозван' in row_text.lower() else '')
        banks.append(BankRecord(
            ogrn=ogrn,
            reg_number=regnum,
            name=name,
            license_status=status,
            source_url=abs_url(source_url, href) or source_url,
            reports_page_url=f'https://www.cbr.ru/finorg/foinfo/reports/?ogrn={ogrn}',
        ))
    return banks
