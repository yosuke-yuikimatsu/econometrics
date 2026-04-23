from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class BankRecord(BaseModel):
    ogrn: str
    reg_number: str
    name: str
    license_status: str
    org_type: str | None = None
    legal_form: str | None = None
    registration_date: str | None = None
    address: str | None = None
    source_url: str
    reports_page_url: str


class ReportLinkRecord(BaseModel):
    ogrn: str
    reg_number: str
    bank_name: str
    reports_page_url: str
    section_name: str | None = None
    form_name: str
    form_code: str | None = None
    form_meta: dict[str, Any] = Field(default_factory=dict)
    report_date: str | None = None
    report_date_label: str | None = None
    report_year: int | None = None
    report_url: str
    title_hint: str | None = None


class ParsedTable(BaseModel):
    table_index: int
    section: str | None = None
    caption: str | None = None
    headers: list[list[str]] = Field(default_factory=list)
    body_rows: list[list[str]] = Field(default_factory=list)
    section_markers: list[str] = Field(default_factory=list)
    raw_html_snippet: str | None = None
    raw_text_fallback: str | None = None


class ParsedReport(BaseModel):
    ogrn: str
    reg_number: str
    name: str
    report_url: str
    report_date: str | None = None
    report_date_label: str | None = None
    report_year: int | None = None
    title: str | None = None
    form_name: str | None = None
    form_code: str | None = None
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    sections: list[str] = Field(default_factory=list)
    tables: list[ParsedTable] = Field(default_factory=list)
    text_blocks: list[str] = Field(default_factory=list)
    raw_text: str | None = None
    raw_html_snippet: str | None = None
