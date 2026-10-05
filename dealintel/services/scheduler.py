from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import or_, select

from ..config import Config, CredentialStore
from ..db import SessionLocal
from ..models import Listing
from .alerts import evaluate_watches
from .catalog import refresh_listing


class RefreshScheduler:
    def __init__(self, config: Config, store: CredentialStore):
        self.config = config
        self.store = store
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._loop(), name="dealintel-refresh")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def run_once(self) -> dict[str, int]:
        checked = 0
        failed = 0
        with SessionLocal() as session:
            now = datetime.now(UTC)
            due = session.scalars(
                select(Listing)
                .where(
                    Listing.provider == "url",
                    or_(Listing.next_check_at.is_(None), Listing.next_check_at <= now),
                )
                .limit(20)
            ).all()
            for listing in due:
                try:
                    await refresh_listing(session, self.config, listing)
                    checked += 1
                except Exception:
                    failed += 1
            evaluate_watches(session, self.store)
        return {"checked": checked, "failed": failed}

    async def _loop(self) -> None:
        await asyncio.sleep(2)
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                # A scheduler failure must never take down the web app.
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except TimeoutError:
                continue
