from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(600), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(160), index=True)
    model: Mapped[str | None] = mapped_column(String(200), index=True)
    gtin: Mapped[str | None] = mapped_column(String(32), index=True)
    mpn: Mapped[str | None] = mapped_column(String(100), index=True)
    category: Mapped[str | None] = mapped_column(String(200), index=True)
    image_url: Mapped[str | None] = mapped_column(Text)
    quality_score: Mapped[float] = mapped_column(Float, default=55.0)
    quality_confidence: Mapped[float] = mapped_column(Float, default=30.0)
    quality_reason: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    listings: Mapped[list[Listing]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    watches: Mapped[list[Watch]] = relationship(back_populates="product", cascade="all, delete-orphan")


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("provider", "provider_item_id", name="uq_provider_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    provider_item_id: Mapped[str] = mapped_column(String(500))
    retailer: Mapped[str] = mapped_column(String(180), index=True)
    seller: Mapped[str | None] = mapped_column(String(180))
    url: Mapped[str] = mapped_column(Text)
    condition: Mapped[str] = mapped_column(String(50), default="new", index=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    current_price: Mapped[float] = mapped_column(Float)
    shipping_price: Mapped[float] = mapped_column(Float, default=0.0)
    membership_cost: Mapped[float] = mapped_column(Float, default=0.0)
    coupon_value: Mapped[float] = mapped_column(Float, default=0.0)
    cashback_value: Mapped[float] = mapped_column(Float, default=0.0)
    effective_price: Mapped[float] = mapped_column(Float)
    reference_price: Mapped[float | None] = mapped_column(Float)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    trust_score: Mapped[float] = mapped_column(Float, default=50.0)
    extraction_confidence: Mapped[float] = mapped_column(Float, default=50.0)
    refresh_interval_minutes: Mapped[int] = mapped_column(Integer, default=180)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    raw_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    product: Mapped[Product] = relationship(back_populates="listings")
    observations: Mapped[list[PriceObservation]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )
    watches: Mapped[list[Watch]] = relationship(back_populates="listing")


class PriceObservation(Base):
    __tablename__ = "price_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    price: Mapped[float] = mapped_column(Float)
    shipping_price: Mapped[float] = mapped_column(Float, default=0.0)
    effective_price: Mapped[float] = mapped_column(Float)
    available: Mapped[bool] = mapped_column(Boolean, default=True)

    listing: Mapped[Listing] = relationship(back_populates="observations")


class Watch(Base):
    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    target_price: Mapped[float | None] = mapped_column(Float)
    min_deal_score: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[str | None] = mapped_column(String(320))
    cooldown_hours: Mapped[int] = mapped_column(Integer, default=24)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship(back_populates="watches")
    listing: Mapped[Listing | None] = relationship(back_populates="watches")


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    deal_score: Mapped[float] = mapped_column(Float)
    effective_price: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_error: Mapped[str | None] = mapped_column(Text)


class SearchSnapshot(Base):
    __tablename__ = "search_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query: Mapped[str] = mapped_column(String(1000), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
