import json
from pathlib import Path
from datetime import datetime


PROJECT_DIR = Path(".").resolve()

INPUT_DIR = PROJECT_DIR / "data" / "parsed" / "banks"
OUTPUT_DIR = PROJECT_DIR / "data" / "parsed" / "101_forms"

START_YEAR = 2009
END_YEAR = 2019

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def extract_report_year(report):
    report_year = report.get("report_year")

    if report_year is not None:
        try:
            return int(report_year)
        except (TypeError, ValueError):
            pass

    report_date = report.get("report_date")

    if report_date:
        try:
            return datetime.strptime(report_date, "%Y-%m-%d").year
        except (TypeError, ValueError):
            pass

    return None


for json_path in INPUT_DIR.glob("*.json"):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    filtered_forms = []
    skipped_without_date = 0

    for form in data.get("forms", []):
        if form.get("form_name") != "Форма 101":
            continue

        filtered_reports = []

        for report in form.get("reports", []):
            report_year = extract_report_year(report)

            if report_year is None:
                skipped_without_date += 1
                print(
                    f"Не удалось отфильтровать по дате: "
                    f"{json_path.name}, "
                    f"report_url={report.get('report_url')}"
                )
                continue

            if START_YEAR <= report_year <= END_YEAR:
                filtered_reports.append(report)

        if filtered_reports:
            form["reports"] = filtered_reports
            filtered_forms.append(form)

    data["forms"] = filtered_forms

    if not filtered_forms:
        print(f"Skipped: {json_path.name}, no Form 101 reports in 2009-2019")
        continue

    output_path = OUTPUT_DIR / json_path.name

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    total_reports = sum(len(form.get("reports", [])) for form in filtered_forms)

    print(
        f"Processed: {json_path.name}; "
        f"forms left: {len(filtered_forms)}; "
        f"reports left: {total_reports}; "
        f"reports skipped without date: {skipped_without_date}"
    )