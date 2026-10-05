from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class OfferCandidate:
    provider: str
    provider_item_id: str
    title: str
    url: str
    retailer: str
    price: float
    currency: str = "USD"
    shipping_price: float = 0.0
    membership_cost: float = 0.0
    coupon_value: float = 0.0
    cashback_value: float = 0.0
    reference_price: float | None = None
    condition: str = "new"
    available: bool = True
    brand: str | None = None
    model: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    category: str | None = None
    image_url: str | None = None
    seller: str | None = None
    quality_score: float | None = None
    quality_confidence: float | None = None
    quality_reason: str | None = None
    trust_score: float | None = None
    extraction_confidence: float = 70.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_price(self) -> float:
        return max(
            0.0,
            self.price
            + self.shipping_price
            + self.membership_cost
            - self.coupon_value
            - self.cashback_value,
        )


@dataclass(slots=True)
class DealScore:
    score: float
    label: str
    price_signal: float
    quality_signal: float
    trust_signal: float
    confidence_signal: float
    history_count: int
    typical_price: float | None
    discount_pct: float | None
    rarity_percentile: float | None
    explanation: str
    eligible_for_feed: bool


@dataclass(slots=True)
class SearchIntent:
    text: str
    max_unit_price: float | None = None
    total_budget: float | None = None
    quantity: int = 1
    min_quality: float = 55.0
    allowed_conditions: tuple[str, ...] = ("new", "open_box_excellent", "certified", "refurbished")
    required_terms: tuple[str, ...] = ()
    preferred_terms: tuple[str, ...] = ()
    excluded_terms: tuple[str, ...] = ()
    location: str | None = None
