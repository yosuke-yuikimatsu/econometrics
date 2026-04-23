from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_space(text: str) -> str:
    text = text.replace(' ', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def abs_url(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    return urljoin(base_url, href)


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    path = re.sub(r'//+', '/', parts.path)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ''))


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def parse_russian_date_label(label: str, year: int | None = None) -> str | None:
    months = {
        'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
        'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
    }
    m = re.search(r'(\d{1,2})\s+([а-яё]+)', label.lower())
    if not m or year is None:
        return None
    day = int(m.group(1))
    month = months.get(m.group(2))
    if month is None:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None
