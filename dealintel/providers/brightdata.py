from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

from ..trust import trust_for_url
from ..types import EvidenceItem, OfferCandidate, SearchIntent
from .base import DiscoveryProvider

_PRICE_RE = re.compile(r"(?<!\d)\$?\s*([0-9][0-9,]*(?:\.\d{1,2})?)")


def _number(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        match = _PRICE_RE.search(value.replace("\u00a0", " "))
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                return None
    return None


def _int_number(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _unpack_json(value: Any) -> Any:
    for _ in range(3):
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith(("{", "[")):
                try:
                    value = json.loads(stripped)
                    continue
                except json.JSONDecodeError:
                    return value
        if isinstance(value, dict):
            for key in ("body", "content", "response", "data"):
                nested = value.get(key)
                if isinstance(nested, str) and nested.strip().startswith(("{", "[")):
                    try:
                        value = json.loads(nested)
                        break
                    except json.JSONDecodeError:
                        pass
            else:
                return value
            continue
        return value
    return value


def _lists_for_keys(value: Any, keys: set[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in keys and isinstance(child, list):
                output.extend(item for item in child if isinstance(item, dict))
            elif isinstance(child, (dict, list)):
                output.extend(_lists_for_keys(child, keys))
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (dict, list)):
                output.extend(_lists_for_keys(child, keys))
    return output


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", []):
            return value
    return None


def parse_shopping_payload(payload: Any, provider: str = "brightdata") -> list[OfferCandidate]:
    data = _unpack_json(payload)
    items = _lists_for_keys(
        data,
        {
            "shopping_results",
            "shopping",
            "products",
            "product_results",
            "items",
        },
    )
    if not items and isinstance(data, list):
        items = [item for item in data if isinstance(item, dict)]

    results: list[OfferCandidate] = []
    seen: set[tuple[str, str, float]] = set()
    for position, item in enumerate(items):
        title = str(_first(item, "title", "name", "product_title") or "").strip()
        price = _number(_first(item, "extracted_price", "price", "current_price", "sale_price"))
        link = str(_first(item, "product_link", "link", "url", "product_url") or "").strip()
        if not title or price is None or price <= 0:
            continue
        source = str(_first(item, "source", "seller", "merchant", "store", "retailer") or "Google Shopping")
        key = (title.casefold(), source.casefold(), round(price, 2))
        if key in seen:
            continue
        seen.add(key)

        rating = _number(_first(item, "rating", "stars", "review_rating"))
        reviews = _int_number(_first(item, "reviews", "reviews_count", "review_count")) or 0
        quality = None
        quality_conf = None
        reason = None
        if rating is not None and 0 < rating <= 5:
            quality = max(25.0, min(94.0, 18.0 + rating * 15.2))
            quality_conf = min(90.0, 30.0 + 8.5 * (reviews + 1) ** 0.25)
            reason = f"Shopping aggregate rating {rating:g}/5 ({reviews} reviews)"

        old_price = _number(_first(item, "extracted_old_price", "old_price", "original_price", "list_price"))
        condition_text = str(_first(item, "condition", "second_hand_condition") or "").lower()
        condition = "new"
        if "refurb" in condition_text:
            condition = "refurbished"
        elif "open" in condition_text:
            condition = "open_box_excellent"
        elif "used" in condition_text or "pre-owned" in condition_text:
            condition = "used"

        trust = trust_for_url(link) if urlparse(link).hostname else 58.0
        results.append(
            OfferCandidate(
                provider=provider,
                provider_item_id=str(
                    _first(item, "product_id", "id", "offer_id", "position") or f"{position}:{title}"
                ),
                title=title[:600],
                url=link,
                retailer=source[:180],
                price=price,
                reference_price=old_price,
                condition=condition,
                brand=_first(item, "brand", "manufacturer"),
                model=_first(item, "model", "model_number", "mpn"),
                gtin=str(_first(item, "gtin", "upc", "ean") or "") or None,
                mpn=_first(item, "mpn"),
                image_url=_first(item, "thumbnail", "image", "image_url"),
                seller=str(_first(item, "seller", "merchant") or "") or None,
                quality_score=quality,
                quality_confidence=quality_conf,
                quality_reason=reason,
                trust_score=trust,
                extraction_confidence=88.0,
                raw={"source": source, "brightdata": item, "google_product_id": _first(item, "product_id")},
            )
        )
    return results


def parse_web_payload(payload: Any, provider: str = "brightdata") -> list[EvidenceItem]:
    data = _unpack_json(payload)
    items = _lists_for_keys(
        data,
        {
            "organic",
            "organic_results",
            "results",
            "search_results",
        },
    )
    if not items and isinstance(data, list):
        items = [item for item in data if isinstance(item, dict)]

    output: list[EvidenceItem] = []
    seen: set[str] = set()
    for item in items:
        title = str(_first(item, "title", "name") or "").strip()
        link = str(_first(item, "link", "url") or "").strip()
        snippet = str(_first(item, "snippet", "description", "text") or "").strip()
        if not title or not link or link in seen:
            continue
        seen.add(link)
        host = (urlparse(link).hostname or "").lower().removeprefix("www.")
        kind = "community" if host in {"reddit.com", "slickdeals.net"} else "review"
        score = None if kind == "community" else _review_score(f"{title} {snippet}")
        output.append(
            EvidenceItem(
                source=host or provider,
                title=title[:500],
                url=link,
                snippet=snippet[:1200],
                kind=kind,
                score=score,
                raw={"brightdata": item},
            )
        )
    return output


class BrightDataProvider(DiscoveryProvider):
    name = "brightdata"

    def __init__(
        self,
        api_key: str,
        zone: str = "serp_api1",
        country: str = "us",
        language: str = "en",
    ):
        self.api_key = api_key
        self.zone = zone or "serp_api1"
        self.country = country.lower()
        self.language = language.lower()

    async def _request(self, query: str, *, shopping: bool) -> Any:
        suffix = "&tbm=shop" if shopping else ""
        url = (
            "https://www.google.com/search?"
            f"q={quote_plus(query)}&gl={quote_plus(self.country)}&hl={quote_plus(self.language)}{suffix}"
        )
        payload = {"zone": self.zone, "url": url, "format": "json"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post("https://api.brightdata.com/request", headers=headers, json=payload)
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                return response.text

    async def search_query(self, query: str, limit: int = 30) -> list[OfferCandidate]:
        data = await self._request(query, shopping=True)
        return parse_shopping_payload(data, provider=self.name)[: max(1, limit)]

    async def evidence_query(self, query: str, limit: int = 10) -> list[EvidenceItem]:
        data = await self._request(query, shopping=False)
        return parse_web_payload(data, provider=self.name)[: max(1, limit)]

    async def search(self, intent: SearchIntent, limit: int = 20) -> list[OfferCandidate]:
        return await self.search_query(intent.text, limit=limit)
