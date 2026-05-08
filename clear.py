from pathlib import Path
import hashlib
import json

DATA_DIR = Path("data")
BANKS_DIR = DATA_DIR / "parsed" / "banks"
REPORTS_DIR = DATA_DIR / "parsed" / "reports"

DRY_RUN = False


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def iter_reports_from_bank_snapshot(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))

    for form in data.get("forms", []):
        for report in form.get("reports", []):
            url = report.get("report_url")
            if url:
                yield url


def main():
    bank_files = sorted(BANKS_DIR.glob("*.json"))

    candidate_paths = set()

    for bank_path in bank_files:
        for report_url in iter_reports_from_bank_snapshot(bank_path):
            report_hash = sha256_text(report_url)
            report_path = REPORTS_DIR / f"{report_hash}.json"
            if report_path.exists():
                candidate_paths.add(report_path)

    total_size = sum(p.stat().st_size for p in candidate_paths)

    print(f"bank_snapshots: {len(bank_files)}")
    print(f"report_files_to_delete: {len(candidate_paths)}")
    print(f"bytes_to_free: {total_size}")
    print(f"gb_to_free: {total_size / 1024 / 1024 / 1024:.2f}")

    if DRY_RUN:
        print("DRY_RUN=True, ничего не удалено.")
        return

    for path in candidate_paths:
        path.unlink()

    print("Удаление завершено.")


if __name__ == "__main__":
    main()