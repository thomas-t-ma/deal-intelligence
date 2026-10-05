from __future__ import annotations

import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import CredentialStore
from ..models import AlertEvent, Watch
from .catalog import deal_score_for_listing


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _send_email(store: CredentialStore, recipient: str, subject: str, body: str) -> None:
    host = store.get("smtp_host")
    username = store.get("smtp_username")
    password = store.get("smtp_password")
    sender = store.get("smtp_from") or username
    port = int(store.get("smtp_port", "587") or "587")
    if not host or not sender:
        raise RuntimeError("SMTP is not configured.")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls()
        if username:
            server.login(username, password or "")
        server.send_message(msg)


def evaluate_watches(session: Session, store: CredentialStore) -> list[AlertEvent]:
    watches = session.scalars(
        select(Watch).where(Watch.enabled.is_(True)).options(joinedload(Watch.product), joinedload(Watch.listing))
    ).unique().all()
    created: list[AlertEvent] = []
    for watch in watches:
        listings = [watch.listing] if watch.listing else list(watch.product.listings)
        listings = [x for x in listings if x and x.available]
        if not listings:
            continue
        scored = [(deal_score_for_listing(session, listing), listing) for listing in listings]
        scored.sort(key=lambda item: item[0].score, reverse=True)
        deal, listing = scored[0]
        price_hit = watch.target_price is not None and listing.effective_price <= watch.target_price
        score_hit = watch.min_deal_score is not None and deal.score >= watch.min_deal_score
        if not (price_hit or score_hit):
            continue
        last = _aware(watch.last_triggered_at)
        if last and _now() - last < timedelta(hours=watch.cooldown_hours):
            continue
        message = (
            f"{watch.product.title} is ${listing.effective_price:,.2f} at {listing.retailer}. "
            f"Deal Score {deal.score:.0f}/100 ({deal.label}). {deal.explanation}"
        )
        event = AlertEvent(
            watch_id=watch.id,
            deal_score=deal.score,
            effective_price=listing.effective_price,
            message=message,
        )
        session.add(event)
        watch.last_triggered_at = _now()
        session.commit()
        session.refresh(event)
        recipient = watch.email or store.get("alert_email")
        if recipient:
            try:
                _send_email(store, recipient, f"Deal alert: {watch.product.title[:80]}", message)
                event.delivered = True
            except Exception as exc:
                event.delivery_error = f"{type(exc).__name__}: {exc}"[:1000]
            session.commit()
        created.append(event)
    return created
