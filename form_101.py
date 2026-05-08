from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
import os

import orjson


PROJECT_DIR = Path(".").resolve()

INPUT_DIR = PROJECT_DIR / "data" / "parsed" / "banks"
OUTPUT_DIR = PROJECT_DIR / "data" / "parsed" / "101_forms"

START_YEAR = 2009
END_YEAR = 2019
EXPECTED_REPORTS = (END_YEAR - START_YEAR + 1) * 12

MAX_WORKERS = max(1, (os.cpu_count() or 2) - 1)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict:
    return orjson.loads(path.read_bytes())


def write_json(path: Path, data: dict) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(
        orjson.dumps(
            data,
            option=orjson.OPT_INDENT_2 | orjson.OPT_NON_STR_KEYS,
        )
    )
    tmp_path.replace(path)


def extract_report_date(report: dict) -> str | None:
    report_date = report.get("report_date")

    if isinstance(report_date, str) and report_date:
        return report_date

    return None


def extract_report_year(report: dict) -> int | None:
    report_year = report.get("report_year")

    if report_year is not None:
        try:
            return int(report_year)
        except (TypeError, ValueError):
            pass

    report_date = extract_report_date(report)

    if report_date:
        try:
            return datetime.strptime(report_date, "%Y-%m-%d").year
        except (TypeError, ValueError):
            pass

    return None


def extract_report_month_key(report: dict) -> str | None:
    report_date = extract_report_date(report)

    if not report_date:
        return None

    try:
        dt = datetime.strptime(report_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None

    if START_YEAR <= dt.year <= END_YEAR:
        return f"{dt.year:04d}-{dt.month:02d}"

    return None


def process_bank_file(json_path: Path) -> dict:
    data = read_json(json_path)

    filtered_forms = []
    skipped_without_date = 0
    duplicate_months = 0

    for form in data.get("forms", []):
        if form.get("form_name") != "Форма 101":
            continue

        reports_by_month: dict[str, dict] = {}

        for report in form.get("reports", []):
            report_year = extract_report_year(report)

            if report_year is None:
                skipped_without_date += 1
                continue

            if not (START_YEAR <= report_year <= END_YEAR):
                continue

            month_key = extract_report_month_key(report)

            if month_key is None:
                skipped_without_date += 1
                continue

            if month_key in reports_by_month:
                duplicate_months += 1
                continue

            reports_by_month[month_key] = report

        if len(reports_by_month) != EXPECTED_REPORTS:
            continue

        new_form = dict(form)
        new_form["reports"] = [
            reports_by_month[month_key]
            for month_key in sorted(reports_by_month)
        ]
        filtered_forms.append(new_form)

    if not filtered_forms:
        output_path = OUTPUT_DIR / json_path.name

        if output_path.exists():
            output_path.unlink()

        return {
            "status": "skipped_incomplete",
            "file": json_path.name,
            "forms_left": 0,
            "reports_left": 0,
            "skipped_without_date": skipped_without_date,
            "duplicate_months": duplicate_months,
            "error": None,
        }

    data["forms"] = filtered_forms

    output_path = OUTPUT_DIR / json_path.name
    write_json(output_path, data)

    total_reports = sum(len(form.get("reports", [])) for form in filtered_forms)

    return {
        "status": "processed",
        "file": json_path.name,
        "forms_left": len(filtered_forms),
        "reports_left": total_reports,
        "skipped_without_date": skipped_without_date,
        "duplicate_months": duplicate_months,
        "error": None,
    }


def main() -> None:
    json_files = sorted(INPUT_DIR.glob("*.json"))

    print(f"INPUT_DIR: {INPUT_DIR}")
    print(f"OUTPUT_DIR: {OUTPUT_DIR}")
    print(f"START_YEAR: {START_YEAR}")
    print(f"END_YEAR: {END_YEAR}")
    print(f"EXPECTED_REPORTS: {EXPECTED_REPORTS}")
    print(f"files_total: {len(json_files)}")
    print(f"MAX_WORKERS: {MAX_WORKERS}")
    print("-" * 80)

    processed = 0
    skipped_incomplete = 0
    failed = 0
    total_reports = 0

    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_bank_file, json_path): json_path
            for json_path in json_files
        }

        for i, future in enumerate(as_completed(futures), start=1):
            json_path = futures[future]

            try:
                result = future.result()
            except Exception as exc:
                failed += 1
                print(f"[{i}/{len(json_files)}] FAILED: {json_path.name}; error={exc}")
                continue

            if result["status"] == "processed":
                processed += 1
                total_reports += result["reports_left"]

                print(
                    f"[{i}/{len(json_files)}] KEEP: {result['file']}; "
                    f"forms left: {result['forms_left']}; "
                    f"reports left: {result['reports_left']}; "
                    f"skipped without date: {result['skipped_without_date']}; "
                    f"duplicate months: {result['duplicate_months']}"
                )
            else:
                skipped_incomplete += 1

                print(
                    f"[{i}/{len(json_files)}] DELETE/SKIP: {result['file']}; "
                    f"no complete Form 101 set for {START_YEAR}-{END_YEAR}; "
                    f"skipped without date: {result['skipped_without_date']}; "
                    f"duplicate months: {result['duplicate_months']}"
                )

    print("-" * 80)
    print(f"processed_complete_files: {processed}")
    print(f"skipped_incomplete_files: {skipped_incomplete}")
    print(f"failed_files: {failed}")
    print(f"total_reports_written: {total_reports}")
    print(f"expected_reports_per_complete_bank: {EXPECTED_REPORTS}")


if __name__ == "__main__":
    main()