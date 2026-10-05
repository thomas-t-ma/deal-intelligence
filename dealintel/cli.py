from __future__ import annotations

import argparse
import asyncio
import webbrowser
from pathlib import Path

import uvicorn

from .benchmark import run_and_save
from .config import CredentialStore, load_config
from .db import init_db
from .services.scheduler import RefreshScheduler


def cmd_run(args) -> int:  # noqa: ANN001
    config = load_config()
    host = args.host or config.host
    port = args.port or config.port
    if args.open_browser and host in {"127.0.0.1", "localhost"}:
        # Browser opening happens after a tiny delay in a daemon thread via stdlib timer.
        import threading

        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run("dealintel.web:app", host=host, port=port, reload=args.reload)
    return 0


def cmd_init(_args) -> int:  # noqa: ANN001
    config = load_config()
    init_db()
    print(f"Initialized Deal Intelligence at {config.home}")
    print(f"Database: {config.db_path}")
    return 0


def cmd_refresh(_args) -> int:  # noqa: ANN001
    config = load_config()
    init_db()
    scheduler = RefreshScheduler(config, CredentialStore(config.secrets_path))
    result = asyncio.run(scheduler.run_once())
    print(f"Refreshed {result['checked']} listing(s); {result['failed']} failed.")
    return 0 if result["failed"] == 0 else 2



def cmd_benchmark(args) -> int:  # noqa: ANN001
    output = Path(args.output).expanduser().resolve() if args.output else None
    report, path = run_and_save(mode=args.mode, output=output)
    summary = report["summary"]
    print(f"Benchmark saved to {path}")
    print(
        f"Cases: {summary['cases']} | nonempty: {summary['nonempty_fraction']:.0%} | "
        f"broad search configured: {report['broad_search_configured']}"
    )
    if not report["broad_search_configured"]:
        print("WARNING: benchmark ran without Bright Data or SerpApi; discovery metrics are not meaningful.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="dealintel", description="Deal Intelligence")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the local web app")
    run.add_argument("--host", default=None)
    run.add_argument("--port", type=int, default=None)
    run.add_argument("--reload", action="store_true", help="Development auto-reload")
    run.add_argument("--no-browser", dest="open_browser", action="store_false")
    run.set_defaults(func=cmd_run, open_browser=True)

    init = sub.add_parser("init", help="Initialize the local database")
    init.set_defaults(func=cmd_init)

    refresh = sub.add_parser("refresh", help="Refresh due tracked URLs and evaluate alerts once")
    refresh.set_defaults(func=cmd_refresh)

    benchmark = sub.add_parser("benchmark", help="Run the v0.4 real-shopping benchmark suite")
    benchmark.add_argument("--mode", choices=["quick", "deep"], default="deep")
    benchmark.add_argument("--output", default=None, help="Optional JSON report path")
    benchmark.set_defaults(func=cmd_benchmark)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
