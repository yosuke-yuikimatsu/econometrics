import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent

INPUT_DIR = PROJECT_DIR / "data" / "parsed" / "banks"
OUTPUT_DIR = PROJECT_DIR / "data" / "parsed" / "101_forms"

START_YEAR = 2009
END_YEAR = 2019

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


for json_path in INPUT_DIR.glob("*.json"):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    filtered_forms = []

    for form in data.get("forms", []):
        if form.get("form_name") != "Форма 101":
            continue

        reports_101 = [
            report for report in form.get("reports", [])
            if START_YEAR <= int(report.get("report_year", 0)) <= END_YEAR
        ]

        if reports_101:
            form["reports"] = reports_101
            filtered_forms.append(form)

    data["forms"] = filtered_forms

    output_path = OUTPUT_DIR / json_path.name

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Processed: {json_path.name}, forms: {len(filtered_forms)}")