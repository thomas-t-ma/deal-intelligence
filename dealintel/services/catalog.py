from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import Config
from ..identity import resolve_product
from ..models import Listing, PriceObservation, Product
from ..providers.url_tracker import UrlTrackerProvider
from ..scoring import score_deal
from ..types import DealScore, OfferCandidate


def now_utc() -> datetime:
    return datetime.now(UTC)


def effective_price(
    price: float,
    shipping: float = 0.0,
    membership: float = 0.0,
    coupon: float = 0.0,
    cashback: float = 0.0,
) -> float:
    return max(0.0, price + shipping + membership - coupon - cashback)


def upsert_offer(session: Session, candidate: OfferCandidate, refresh_minutes: int = 180) -> Listing:
    product = resolve_product(session, candidate)
    listing = session.scalar(
        select(Listing).where(
            Listing.provider == candidate.provider,
            Listing.provider_item_id == candidate.provider_item_id,
        )
    )
    effective = candidate.effective_price
    now = now_utc()
    if listing is None:
        listing = Listing(
            product_id=product.id,
            provider=candidate.provider,
            provider_item_id=candidate.provider_item_id,
            retailer=candidate.retailer,
            seller=candidate.seller,
            url=candidate.url,
            condition=candidate.condition,
            currency=candidate.currency,
            current_price=candidate.price,
            shipping_price=candidate.shipping_price,
            membership_cost=candidate.membership_cost,
            coupon_value=candidate.coupon_value,
            cashback_value=candidate.cashback_value,
            effective_price=effective,
            reference_price=candidate.reference_price,
            available=candidate.available,
            trust_score=candidate.trust_score or 50.0,
            extraction_confidence=candidate.extraction_confidence,
            refresh_interval_minutes=refresh_minutes,
            next_check_at=now + timedelta(minutes=refresh_minutes),
            last_checked_at=now,
            raw_json=json.dumps(candidate.raw, ensure_ascii=False)[:20000],
        )
        session.add(listing)
        session.flush()
    else:
        listing.product_id = product.id
        listing.retailer = candidate.retailer
        listing.seller = candidate.seller
        listing.url = candidate.url
        listing.condition = candidate.condition
        listing.currency = candidate.currency
        listing.current_price = candidate.price
        listing.shipping_price = candidate.shipping_price
        listing.membership_cost = candidate.membership_cost
        listing.coupon_value = candidate.coupon_value
        listing.cashback_value = candidate.cashback_value
        listing.effective_price = effective
        listing.reference_price = candidate.reference_price or listing.reference_price
        listing.available = candidate.available
        listing.trust_score = candidate.trust_score or listing.trust_score
        listing.extraction_confidence = candidate.extraction_confidence
        listing.last_checked_at = now
        listing.next_check_at = now + timedelta(minutes=listing.refresh_interval_minutes)
        listing.last_error = None
        listing.consecutive_failures = 0
        listing.raw_json = json.dumps(candidate.raw, ensure_ascii=False)[:20000]

    if candidate.quality_score is not None and (
        candidate.quality_confidence or 0
    ) >= product.quality_confidence:
        product.quality_score = candidate.quality_score
        product.quality_confidence = candidate.quality_confidence or 30.0
        product.quality_reason = candidate.quality_reason
    if not product.image_url and candidate.image_url:
        product.image_url = candidate.image_url
    if not product.brand and candidate.brand:
        product.brand = candidate.brand
    if not product.model and candidate.model:
        product.model = candidate.model
    if not product.gtin and candidate.gtin:
        product.gtin = candidate.gtin
    if not product.mpn and candidate.mpn:
        product.mpn = candidate.mpn

    session.add(
        PriceObservation(
            listing_id=listing.id,
            observed_at=now,
            price=candidate.price,
            shipping_price=candidate.shipping_price,
            effective_price=effective,
            available=candidate.available,
        )
    )
    session.commit()
    session.refresh(listing)
    return listing


async def add_url(session: Session, config: Config, url: str) -> Listing:
    candidate = await UrlTrackerProvider(config).fetch(url)
    return upsert_offer(session, candidate, refresh_minutes=config.refresh_minutes)


async def refresh_listing(session: Session, config: Config, listing: Listing) -> Listing:
    if listing.provider != "url":
        raise ValueError(f"Provider {listing.provider!r} does not support persistent refresh in v0.1.")
    try:
        candidate = await UrlTrackerProvider(config).fetch(listing.url)
        # Keep the existing listing identity even when a site's SKU metadata changes.
        candidate.provider = listing.provider
        candidate.provider_item_id = listing.provider_item_id
        return upsert_offer(session, candidate, refresh_minutes=listing.refresh_interval_minutes)
    except Exception as exc:
        listing.consecutive_failures += 1
        listing.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        backoff = min(24 * 60, listing.refresh_interval_minutes * (2 ** min(listing.consecutive_failures, 4)))
        listing.next_check_at = now_utc() + timedelta(minutes=backoff)
        listing.last_checked_at = now_utc()
        session.commit()
        raise



def update_listing_adjustments(
    session: Session,
    listing: Listing,
    *,
    current_price: float | None = None,
    shipping_price: float | None = None,
    membership_cost: float | None = None,
    coupon_value: float | None = None,
    cashback_value: float | None = None,
    condition: str | None = None,
    trust_score: float | None = None,
) -> Listing:
    if current_price is not None:
        listing.current_price = max(0.0, current_price)
    if shipping_price is not None:
        listing.shipping_price = max(0.0, shipping_price)
    if membership_cost is not None:
        listing.membership_cost = max(0.0, membership_cost)
    if coupon_value is not None:
        listing.coupon_value = max(0.0, coupon_value)
    if cashback_value is not None:
        listing.cashback_value = max(0.0, cashback_value)
    if condition:
        listing.condition = condition
    if trust_score is not None:
        listing.trust_score = max(0.0, min(100.0, trust_score))
    listing.effective_price = effective_price(
        listing.current_price, listing.shipping_price, listing.membership_cost,
        listing.coupon_value, listing.cashback_value
    )
    listing.updated_at = now_utc()
    session.add(PriceObservation(
        listing_id=listing.id,
        observed_at=now_utc(),
        price=listing.current_price,
        shipping_price=listing.shipping_price,
        effective_price=listing.effective_price,
        available=listing.available,
    ))
    session.commit()
    session.refresh(listing)
    return listing

def history_for_listing(session: Session, listing: Listing, days: int = 365) -> list[float]:
    cutoff = now_utc() - timedelta(days=days)
    rows = session.scalars(
        select(PriceObservation.effective_price)
        .join(Listing, PriceObservation.listing_id == Listing.id)
        .where(
            Listing.product_id == listing.product_id,
            Listing.condition == listing.condition,
            PriceObservation.observed_at >= cutoff,
            PriceObservation.available.is_(True),
        )
        .order_by(PriceObservation.observed_at.asc())
    ).all()
    # Exclude the current observation from its own baseline when possible.
    values = [float(x) for x in rows]
    return values[:-1] if len(values) > 1 else []


def deal_score_for_listing(session: Session, listing: Listing) -> DealScore:
    product = listing.product or session.get(Product, listing.product_id)
    return score_deal(
        current_price=listing.effective_price,
        history=history_for_listing(session, listing),
        reference_price=listing.reference_price,
        quality_score=product.quality_score,
        quality_confidence=product.quality_confidence,
        trust_score=listing.trust_score,
        extraction_confidence=listing.extraction_confidence,
        available=listing.available,
        condition=listing.condition,
    )


def dashboard_rows(session: Session) -> list[dict]:
    listings = session.scalars(
        select(Listing)
        .options(joinedload(Listing.product))
        .order_by(Listing.updated_at.desc())
    ).unique().all()
    rows = []
    for listing in listings:
        deal = deal_score_for_listing(session, listing)
        rows.append({"listing": listing, "product": listing.product, "deal": deal})
    rows.sort(key=lambda row: row["deal"].score, reverse=True)
    return rows


def ridiculous_rows(session: Session, limit: int = 24) -> list[dict]:
    return [row for row in dashboard_rows(session) if row["deal"].eligible_for_feed][:limit]


def product_detail(session: Session, product_id: int) -> tuple[Product, list[dict], list[PriceObservation]]:
    product = session.scalar(
        select(Product).where(Product.id == product_id).options(joinedload(Product.listings))
    )
    if not product:
        raise KeyError(product_id)
    rows = []
    for listing in product.listings:
        rows.append({"listing": listing, "deal": deal_score_for_listing(session, listing)})
    observations = session.scalars(
        select(PriceObservation)
        .join(Listing)
        .where(Listing.product_id == product_id)
        .order_by(PriceObservation.observed_at.asc())
    ).all()
    return product, rows, observations
