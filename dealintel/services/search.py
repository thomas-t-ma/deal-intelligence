from __future__ import annotations

import json
import re

import httpx

from ..identity import normalize_text
from ..scoring import score_deal
from ..types import OfferCandidate, SearchIntent


def parse_intent(text: str) -> SearchIntent:
    raw = " ".join(text.split()).strip()
    lower = raw.lower()
    quantity = 1
    qty_match = re.search(r"\b(?:need|want|buy|find)?\s*(\d+)\s*(?:x|×|units?|monitors?|laptops?|pcs?|items?)\b", lower)
    if qty_match:
        quantity = max(1, min(100, int(qty_match.group(1))))
    elif re.search(r"\b(two|pair of)\b", lower):
        quantity = 2

    total_budget = None
    max_unit_price = None
    budget_match = re.search(
        r"(?:total\s+budget|budget|under|less than|<=?|up to)\s*(?:of\s*)?\$?\s*([\d,]+(?:\.\d{1,2})?)",
        lower,
    )
    if budget_match:
        value = float(budget_match.group(1).replace(",", ""))
        if "total" in budget_match.group(0) or quantity > 1:
            total_budget = value
            max_unit_price = value / quantity
        else:
            max_unit_price = value

    excluded = []
    if "gaming irrelevant" in lower or "gaming performance irrelevant" in lower:
        excluded.extend(["gaming", "rgb"])
    allowed = ["new", "open_box_excellent", "certified", "refurbished"]
    if "used" in lower:
        allowed.append("used")

    return SearchIntent(
        text=raw,
        max_unit_price=max_unit_price,
        total_budget=total_budget,
        quantity=quantity,
        excluded_terms=tuple(excluded),
        allowed_conditions=tuple(allowed),
    )


async def ollama_parse_intent(text: str, url: str, model: str) -> SearchIntent | None:
    prompt = f"""Convert this shopping request into JSON only.
Keys: max_unit_price(number|null), total_budget(number|null), quantity(integer), min_quality(number 0-100), allowed_conditions(array from new,open_box_excellent,certified,refurbished,used), required_terms(array strings), preferred_terms(array strings), excluded_terms(array strings), location(string|null).
Request: {text}
"""
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json", "think": False}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(url.rstrip("/") + "/api/generate", json=payload)
            response.raise_for_status()
            content = response.json().get("response", "{}")
            data = json.loads(content)
    except Exception:
        return None
    deterministic = parse_intent(text)
    try:
        return SearchIntent(
            text=text,
            max_unit_price=data.get("max_unit_price") or deterministic.max_unit_price,
            total_budget=data.get("total_budget") or deterministic.total_budget,
            quantity=max(1, int(data.get("quantity") or deterministic.quantity)),
            min_quality=float(data.get("min_quality") or deterministic.min_quality),
            allowed_conditions=tuple(data.get("allowed_conditions") or deterministic.allowed_conditions),
            required_terms=tuple(str(x) for x in data.get("required_terms", [])),
            preferred_terms=tuple(str(x) for x in data.get("preferred_terms", [])),
            excluded_terms=tuple(str(x) for x in data.get("excluded_terms", deterministic.excluded_terms)),
            location=data.get("location"),
        )
    except (TypeError, ValueError):
        return deterministic


def score_search_candidate(candidate: OfferCandidate, intent: SearchIntent) -> dict:
    deal = score_deal(
        current_price=candidate.effective_price,
        history=[],
        reference_price=candidate.reference_price,
        quality_score=candidate.quality_score or 55.0,
        quality_confidence=candidate.quality_confidence or 30.0,
        trust_score=candidate.trust_score or 50.0,
        extraction_confidence=candidate.extraction_confidence,
        available=candidate.available,
        condition=candidate.condition,
    )
    norm_title = normalize_text(candidate.title)
    words = [w for w in normalize_text(intent.text).split() if len(w) > 2]
    overlap = sum(w in norm_title for w in words) / max(1, len(words))
    fit = 50 + 35 * overlap
    if intent.max_unit_price is not None:
        if candidate.effective_price <= intent.max_unit_price:
            fit += 10
        else:
            over = (candidate.effective_price - intent.max_unit_price) / max(intent.max_unit_price, 1)
            fit -= min(35, 80 * over)
    if candidate.condition not in intent.allowed_conditions:
        fit -= 30
    for term in intent.excluded_terms:
        if normalize_text(term) in norm_title:
            fit -= 10
    fit = max(0.0, min(100.0, fit))
    # Deal quality matters more than textual rank, but we still honor the request.
    combined = 0.62 * deal.score + 0.38 * fit
    return {
        "candidate": candidate,
        "deal": deal,
        "fit_score": round(fit, 1),
        "combined_score": round(combined, 1),
    }


def rank_search_results(candidates: list[OfferCandidate], intent: SearchIntent) -> list[dict]:
    rows = [score_search_candidate(candidate, intent) for candidate in candidates]
    rows.sort(key=lambda row: row["combined_score"], reverse=True)
    return rows
