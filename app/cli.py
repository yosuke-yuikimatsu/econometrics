from __future__ import annotations

import argparse
import time

from app.celery_app import celery_app
from app.logging_utils import configure_logging
from app.storage import StateStore

configure_logging()
store = StateStore()


def cmd_bootstrap() -> None:
    res = celery_app.send_task("app.tasks.bootstrap.discover_banks", queue="bootstrap", routing_key="bootstrap")
    print(f"bootstrap task queued: {res.id}")


def cmd_finalize() -> None:
    res = celery_app.send_task("app.tasks.aggregate.finalize_all", queue="aggregate", routing_key="aggregate")
    print(f"finalize task queued: {res.id}")


def _print_summary() -> None:
    counters = store.counters()
    for k, v in counters.items():
        print(f"{k}: {v}")


def cmd_summary(watch: bool) -> None:
    if not watch:
        _print_summary()
        return
    while True:
        print("---")
        _print_summary()
        time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap")
    sub.add_parser("finalize")
    s = sub.add_parser("summary")
    s.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    if args.cmd == "bootstrap":
        cmd_bootstrap()
    elif args.cmd == "finalize":
        cmd_finalize()
    elif args.cmd == "summary":
        cmd_summary(args.watch)


if __name__ == "__main__":
    main()