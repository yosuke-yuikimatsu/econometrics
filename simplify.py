import json
import re
from pathlib import Path
from datetime import datetime


PROJECT_DIR = Path(".").resolve()

INPUT_DIR = PROJECT_DIR / "data" / "parsed" / "101_forms"
OUTPUT_DIR = PROJECT_DIR / "data" / "parsed" / "101_accounts"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


START_NEW_FORMAT_YEAR = 2008

ACCOUNT_RE = re.compile(r"^\d{3,5}(?:\.\d+)?$")


def parse_number(value):
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    value = value.replace("\xa0", " ")
    value = value.replace(" ", "")
    value = value.replace(",", ".")

    try:
        number = float(value)
    except ValueError:
        return None

    if number.is_integer():
        return int(number)

    return number


def is_account_code(value):
    if value is None:
        return False

    value = str(value).strip()

    return bool(ACCOUNT_RE.match(value))


def extract_year(report):
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


def extract_account_from_new_format_row(row):
    """
    Формат 2008+.

    Пример строки:

    [
        "20202",
        "114 213",
        "42 552",
        "156 765",
        ...
        "124 986",
        "43 127",
        "168 113"
    ]

    Индекс 0  -> номер счета.
    Индекс 12 -> исходящий остаток итого.
    """

    if len(row) < 13:
        return None, None

    account = str(row[0]).strip()

    if not is_account_code(account):
        return None, None

    value = parse_number(row[12])

    if value is None:
        return None, None

    return account, value


def extract_account_from_old_format_row(row):
    """
    Формат до 2007 включительно.

    Пример активного счета:

    [
        "Касса кредитных организаций",
        "20202",
        "19 291,0000",
        ""
    ]

    Пример пассивного счета:

    [
        "негосударственным организациям",
        "10204",
        "",
        "104 783,0000"
    ]

    Индекс 1 -> номер счета.
    Индекс 2 -> остаток по активу.
    Индекс 3 -> остаток по пассиву.

    В итоговый словарь кладем непустое значение.
    """

    if len(row) < 4:
        return None, None

    account = str(row[1]).strip()

    if not is_account_code(account):
        return None, None

    active_value = parse_number(row[2])
    passive_value = parse_number(row[3])

    if active_value is not None:
        return account, active_value

    if passive_value is not None:
        return account, passive_value

    return None, None


def extract_accounts_from_report(report):
    report_year = extract_year(report)

    if report_year is None:
        print(
            "Не удалось определить год отчёта, отчёт пропущен:",
            report.get("report_url")
        )
        return {}

    accounts = {}

    for table in report.get("tables", []):
        for row in table.get("body_rows", []):
            if report_year >= START_NEW_FORMAT_YEAR:
                account, value = extract_account_from_new_format_row(row)
            else:
                account, value = extract_account_from_old_format_row(row)

            if account is None:
                continue

            if account in accounts:
                print(
                    "Дублирующийся счет в одном отчёте:",
                    account,
                    report.get("report_date"),
                    report.get("report_url")
                )

            accounts[account] = value

    return accounts


def simplify_report(report):
    accounts = extract_accounts_from_report(report)

    if not accounts:
        return None

    return {
        "report_date": report.get("report_date"),
        "report_date_label": report.get("report_date_label"),
        "report_year": report.get("report_year"),
        "title": report.get("title"),
        "form_name": report.get("form_name"),
        "form_code": report.get("form_code"),
        "report_url": report.get("report_url"),
        "metadata": report.get("metadata", {}),
        "sections": report.get("sections", []),
        "accounts": accounts,
    }


def simplify_bank(data):
    simplified_reports = []

    for form in data.get("forms", []):
        if form.get("form_name") != "Форма 101":
            continue

        for report in form.get("reports", []):
            simplified_report = simplify_report(report)

            if simplified_report is None:
                print(
                    "Не удалось извлечь счета из отчёта:",
                    data.get("ogrn"),
                    report.get("report_date"),
                    report.get("report_url")
                )
                continue

            simplified_reports.append(simplified_report)

    return {
        "ogrn": data.get("ogrn"),
        "reg_number": data.get("reg_number"),
        "name": data.get("name"),
        "license_status": data.get("license_status"),
        "source_url": data.get("source_url"),
        "reports_page_url": data.get("reports_page_url"),
        "reports": simplified_reports,
    }


total_files = 0
total_reports = 0
total_accounts = 0

for json_path in sorted(INPUT_DIR.glob("*.json")):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    simplified = simplify_bank(data)

    if not simplified["reports"]:
        print(f"Skipped: {json_path.name}, no simplified reports")
        continue

    output_path = OUTPUT_DIR / json_path.name

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(simplified, f, ensure_ascii=False, indent=2)

    file_reports = len(simplified["reports"])
    file_accounts = sum(len(report["accounts"]) for report in simplified["reports"])

    total_files += 1
    total_reports += file_reports
    total_accounts += file_accounts

    print(
        f"Processed: {json_path.name}; "
        f"reports: {file_reports}; "
        f"accounts: {file_accounts}"
    )

print()
print("Done")
print(f"Files written: {total_files}")
print(f"Reports parsed: {total_reports}")
print(f"Account values extracted: {total_accounts}")
print(f"Output directory: {OUTPUT_DIR}")