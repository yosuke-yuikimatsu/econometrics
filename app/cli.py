from __future__ import annotations

import argparse
import time

from app.celery_app import celery_app
from app.logging_utils import configure_logging
from app.storage import StateStore

import shutil
from pathlib import Path
from app.config import settings
import subprocess

configure_logging()
store = StateStore()

def _format_bytes(n: int) -> str:
    value = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} PB"


def _dir_size(path: Path) -> str:
    try:
        result = subprocess.run(
            ["du", "-sh", path],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return "n/a"
        return result.stdout.split()[0]
    except Exception:
        return "n/a"


def cmd_resume(limit: int | None) -> None:
    res = celery_app.send_task(
        "app.tasks.resume.resume_all",
        args=[limit],
        queue="bootstrap",
        routing_key="bootstrap",
    )
    print(f"resume task queued: {res.id}")


def cmd_resume_fetch(limit: int | None) -> None:
    res = celery_app.send_task(
        "app.tasks.resume.resume_fetch_report_pages",
        args=[limit],
        queue="bootstrap",
        routing_key="bootstrap",
    )
    print(f"resume-fetch task queued: {res.id}")


def cmd_resume_parse(limit: int | None) -> None:
    res = celery_app.send_task(
        "app.tasks.resume.resume_parse_report_pages",
        args=[limit],
        queue="bootstrap",
        routing_key="bootstrap",
    )
    print(f"resume-parse task queued: {res.id}")


def cmd_bootstrap() -> None:
    res = celery_app.send_task("app.tasks.bootstrap.discover_banks", queue="bootstrap", routing_key="bootstrap")
    print(f"bootstrap task queued: {res.id}")


def cmd_finalize() -> None:
    res = celery_app.send_task("app.tasks.aggregate.finalize_all", queue="aggregate", routing_key="aggregate")
    print(f"finalize task queued: {res.id}")


def _print_summary() -> None:
    store = StateStore()
    counters = store.counters()

    for k, v in counters.items():
        print(f"{k}: {v}")

    usage = shutil.disk_usage(settings.data_dir)
    print(f"disk_total: {_format_bytes(usage.total)}")
    print(f"disk_used: {_format_bytes(usage.used)}")
    print(f"disk_free: {_format_bytes(usage.free)}")

    print(f"data_dir_size: {_format_bytes(_dir_size(settings.data_dir))}")
    print(f"raw_dir_size: {_format_bytes(_dir_size(settings.raw_dir))}")
    print(f"parsed_reports_dir_size: {_format_bytes(_dir_size(settings.parsed_reports_dir))}")


def cmd_summary(watch: bool) -> None:
    if not watch:
        _print_summary()
        return
    while True:
        print("---")
        _print_summary()
        time.sleep(5)

def cmd_init_db() -> None:
    store = StateStore(init_schema=True)
    print("database schema initialized")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap")
    sub.add_parser("finalize")
    sub.add_parser("init-db")
    s = sub.add_parser("summary")
    s.add_argument("--watch", action="store_true")
    r = sub.add_parser("resume")
    r.add_argument("--limit", type=int, default=None)

    rf = sub.add_parser("resume-fetch")
    rf.add_argument("--limit", type=int, default=None)

    rp = sub.add_parser("resume-parse")
    rp.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.cmd == "bootstrap":
        cmd_bootstrap()
    elif args.cmd == "finalize":
        cmd_finalize()
    elif args.cmd == "summary":
        cmd_summary(args.watch)
    elif args.cmd == "init-db":
        cmd_init_db()
    elif args.cmd == "resume":
        cmd_resume(args.limit)
    elif args.cmd == "resume-fetch":
        cmd_resume_fetch(args.limit)
    elif args.cmd == "resume-parse":
        cmd_resume_parse(args.limit)
    


if __name__ == "__main__":
    main()