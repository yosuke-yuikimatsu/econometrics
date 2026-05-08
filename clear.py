from pathlib import Path
import argparse
import hashlib
import json
import os
import time


DATA_DIR = Path("data")
BANKS_DIR = DATA_DIR / "parsed" / "banks"
REPORTS_DIR = DATA_DIR / "parsed" / "reports"
STATE_PATH = DATA_DIR / "manifests" / "cleanup_reports_state.jsonl"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_done_ogrns() -> set[str]:
    if not STATE_PATH.exists():
        return set()

    done = set()
    with STATE_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("status") == "done" and row.get("ogrn"):
                done.add(str(row["ogrn"]))

    return done


def append_state(row: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def iter_report_urls_from_bank(bank_path: Path):
    with bank_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    for form in data.get("forms", []):
        for report in form.get("reports", []):
            url = report.get("report_url")
            if url:
                yield url


def cleanup_bank(bank_path: Path, dry_run: bool) -> dict:
    ogrn = bank_path.stem

    seen_hashes = set()
    deleted = 0
    missing = 0
    bytes_freed = 0

    for report_url in iter_report_urls_from_bank(bank_path):
        url_hash = sha256_text(report_url)

        if url_hash in seen_hashes:
            continue
        seen_hashes.add(url_hash)

        report_path = REPORTS_DIR / f"{url_hash}.json"

        if not report_path.exists():
            missing += 1
            continue

        size = report_path.stat().st_size
        bytes_freed += size

        if not dry_run:
            report_path.unlink()

        deleted += 1

    return {
        "ogrn": ogrn,
        "status": "done",
        "deleted": deleted,
        "missing": missing,
        "bytes_freed": bytes_freed,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-size", type=int, default=25)
    parser.add_argument("--limit-banks", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    start = time.time()

    bank_files = sorted(BANKS_DIR.glob("*.json"))

    done_ogrns = set() if args.no_resume else load_done_ogrns()

    pending = [
        p for p in bank_files
        if p.stem not in done_ogrns
    ]

    if args.limit_banks is not None:
        pending = pending[:args.limit_banks]

    total_deleted = 0
    total_missing = 0
    total_bytes = 0
    processed = 0

    print(f"bank_snapshots_total: {len(bank_files)}")
    print(f"already_done: {len(done_ogrns)}")
    print(f"pending_this_run: {len(pending)}")
    print(f"chunk_size: {args.chunk_size}")
    print(f"dry_run: {args.dry_run}")
    print("---")

    for chunk_start in range(0, len(pending), args.chunk_size):
        chunk = pending[chunk_start:chunk_start + args.chunk_size]

        chunk_deleted = 0
        chunk_missing = 0
        chunk_bytes = 0

        for bank_path in chunk:
            try:
                row = cleanup_bank(bank_path, dry_run=args.dry_run)
            except Exception as exc:
                append_state({
                    "ogrn": bank_path.stem,
                    "status": "error",
                    "error": repr(exc),
                    "ts": time.time(),
                })
                print(f"ERROR {bank_path.name}: {exc}")
                continue

            processed += 1
            chunk_deleted += row["deleted"]
            chunk_missing += row["missing"]
            chunk_bytes += row["bytes_freed"]

            total_deleted += row["deleted"]
            total_missing += row["missing"]
            total_bytes += row["bytes_freed"]

            if not args.dry_run:
                row["ts"] = time.time()
                append_state(row)

        elapsed = time.time() - start
        print(
            f"processed={processed}/{len(pending)} | "
            f"chunk_deleted={chunk_deleted} | "
            f"chunk_freed={chunk_bytes / 1024 / 1024 / 1024:.2f} GB | "
            f"total_deleted={total_deleted} | "
            f"total_freed={total_bytes / 1024 / 1024 / 1024:.2f} GB | "
            f"elapsed={elapsed:.1f}s"
        )

    print("---")
    print(f"done_processed: {processed}")
    print(f"deleted_files: {total_deleted}")
    print(f"missing_files: {total_missing}")
    print(f"bytes_freed: {total_bytes}")
    print(f"gb_freed: {total_bytes / 1024 / 1024 / 1024:.2f}")


if __name__ == "__main__":
    main()