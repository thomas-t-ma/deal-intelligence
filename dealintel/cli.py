from __future__ import annotations

import argparse
import asyncio
import webbrowser

import uvicorn

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

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
