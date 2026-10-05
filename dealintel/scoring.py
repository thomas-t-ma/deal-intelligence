from __future__ import annotations

import math
import statistics

from .types import DealScore

CONDITION_FACTORS = {
    "new": 1.00,
    "certified": 0.98,
    "open_box_excellent": 0.95,
    "open_box_good": 0.88,
    "refurbished": 0.88,
    "used_like_new": 0.86,
    "used": 0.78,
    "unknown": 0.82,
}


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def robust_typical(prices: list[float]) -> float | None:
    clean = sorted(p for p in prices if p > 0)
    if not clean:
        return None
    if len(clean) < 5:
        return statistics.median(clean)
    lo = int(len(clean) * 0.1)
    hi = max(lo + 1, int(len(clean) * 0.9))
    return statistics.median(clean[lo:hi])


def empirical_percentile(current: float, history: list[float]) -> float | None:
    clean = [p for p in history if p > 0]
    if not clean:
        return None
    # Percent of historical observations at or below current. Lower is rarer/better.
    return 100.0 * sum(p <= current for p in clean) / len(clean)


def _price_signal(
    current: float,
    history: list[float],
    reference_price: float | None,
) -> tuple[float, float | None, float | None, float | None, float]:
    typical = robust_typical(history)
    rarity = empirical_percentile(current, history)
    history_confidence = clamp(15 + 8 * len(history), 15, 100)

    if typical and typical > 0:
        discount = (typical - current) / typical
        discount_component = clamp(50 + 180 * discount)
        rarity_component = 50.0 if rarity is None else clamp(100 - rarity)
        signal = 0.7 * discount_component + 0.3 * rarity_component
        return clamp(signal), typical, discount, rarity, history_confidence

    if reference_price and reference_price > 0:
        discount = (reference_price - current) / reference_price
        # MSRP/list price is weaker evidence than observed history; don't let it create 95+ scores.
        signal = clamp(45 + 120 * discount, 15, 82)
        return signal, reference_price, discount, None, 35.0

    return 45.0, None, None, None, 20.0


def score_deal(
    *,
    current_price: float,
    history: list[float],
    reference_price: float | None,
    quality_score: float,
    quality_confidence: float,
    trust_score: float,
    extraction_confidence: float,
    available: bool,
    condition: str,
) -> DealScore:
    price_signal, typical, discount, rarity, history_confidence = _price_signal(
        current_price, history, reference_price
    )
    quality = clamp(quality_score)
    trust = clamp(trust_score)
    confidence = clamp(
        0.45 * history_confidence + 0.35 * extraction_confidence + 0.20 * quality_confidence
    )
    availability = 100.0 if available else 0.0
    condition_factor = CONDITION_FACTORS.get(condition, CONDITION_FACTORS["unknown"])

    # Weighted geometric mean: a weak quality or seller signal meaningfully suppresses hype.
    parts = [
        (max(price_signal, 1) / 100, 0.46),
        (max(quality, 1) / 100, 0.22),
        (max(trust, 1) / 100, 0.15),
        (max(confidence, 1) / 100, 0.12),
        (max(availability, 1) / 100, 0.05),
    ]
    weighted_log = sum(weight * math.log(value) for value, weight in parts)
    raw = 100 * math.exp(weighted_log) * condition_factor
    score = clamp(raw)

    # "No garbage" guardrails: low-quality or low-trust products cannot masquerade as absurd deals.
    if quality < 45:
        score = min(score, 58)
    if trust < 45:
        score = min(score, 55)
    if confidence < 35:
        score = min(score, 62)
    if not available:
        score = min(score, 20)

    if score >= 92 and quality >= 65 and trust >= 65 and confidence >= 50:
        label = "Absurd"
    elif score >= 82:
        label = "Exceptional"
    elif score >= 70:
        label = "Great"
    elif score >= 55:
        label = "Good"
    else:
        label = "Normal"

    eligible = available and quality >= 55 and trust >= 55 and confidence >= 35 and score >= 55

    bits: list[str] = []
    if discount is not None:
        bits.append(f"{abs(discount) * 100:.0f}% {'below' if discount >= 0 else 'above'} robust reference")
    if rarity is not None and len(history) >= 4:
        bits.append(f"at or below only {rarity:.0f}% of observed prices")
    bits.append(f"quality {quality:.0f}/100")
    bits.append(f"seller trust {trust:.0f}/100")
    if confidence < 50:
        bits.append("limited history, so confidence is still building")

    return DealScore(
        score=round(score, 1),
        label=label,
        price_signal=round(price_signal, 1),
        quality_signal=round(quality, 1),
        trust_signal=round(trust, 1),
        confidence_signal=round(confidence, 1),
        history_count=len(history),
        typical_price=round(typical, 2) if typical is not None else None,
        discount_pct=round(discount * 100, 1) if discount is not None else None,
        rarity_percentile=round(rarity, 1) if rarity is not None else None,
        explanation="; ".join(bits) + ".",
        eligible_for_feed=eligible,
    )
