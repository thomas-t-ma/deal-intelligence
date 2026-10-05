from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from ..types import OfferCandidate, SearchIntent
from .base import DiscoveryProvider


class BestBuyProvider(DiscoveryProvider):
    """Live-only Best Buy source.

    The app does not automatically persist search results from this provider because Best Buy's
    developer terms restrict caching. It is intended for live discovery/open-box inspection after
    the user has obtained a developer key and confirmed their use complies with those terms.
    """

    name = "bestbuy"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, intent: SearchIntent, limit: int = 20) -> list[OfferCandidate]:
        terms = [t for t in re.findall(r"[A-Za-z0-9.+-]+", intent.text) if len(t) > 1][:8]
        if not terms:
            return []
        query = "&".join(f"search={quote(term)}" for term in terms)
        endpoint = f"https://api.bestbuy.com/v1/products({query})"
        params = {
            "format": "json",
            "show": ",".join(
                [
                    "sku", "name", "salePrice", "regularPrice", "url", "image",
                    "manufacturer", "modelNumber", "customerReviewAverage",
                    "customerReviewCount", "onlineAvailability", "upc",
                ]
            ),
            "pageSize": min(max(limit, 1), 50),
            "apiKey": self.api_key,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
        output: list[OfferCandidate] = []
        for item in data.get("products", []):
            price = item.get("salePrice")
            if not isinstance(price, int | float):
                continue
            rating = item.get("customerReviewAverage")
            reviews = item.get("customerReviewCount") or 0
            quality = None
            confidence = None
            reason = None
            if isinstance(rating, int | float | str):
                try:
                    rating_f = float(rating)
                    quality = max(30.0, min(94.0, 20.0 + rating_f * 14.5))
                    confidence = min(90.0, 35.0 + 8.0 * (float(reviews) + 1) ** 0.25)
                    reason = f"Best Buy customer rating {rating_f:g}/5 ({int(reviews)} reviews)"
                except ValueError:
                    pass
            output.append(
                OfferCandidate(
                    provider=self.name,
                    provider_item_id=str(item.get("sku")),
                    title=str(item.get("name") or ""),
                    url=str(item.get("url") or ""),
                    retailer="Best Buy",
                    price=float(price),
                    reference_price=float(item["regularPrice"])
                    if isinstance(item.get("regularPrice"), int | float)
                    else None,
                    brand=item.get("manufacturer"),
                    model=item.get("modelNumber"),
                    gtin=str(item.get("upc") or "") or None,
                    image_url=item.get("image"),
                    available=bool(item.get("onlineAvailability", True)),
                    quality_score=quality,
                    quality_confidence=confidence,
                    quality_reason=reason,
                    trust_score=94.0,
                    extraction_confidence=96.0,
                    raw={"sku": item.get("sku")},
                )
            )
        return output

    async def open_box(self, sku: str) -> list[OfferCandidate]:
        endpoint = f"https://api.bestbuy.com/beta/products/{quote(str(sku))}/openBox"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(endpoint, params={"apiKey": self.api_key})
            response.raise_for_status()
            data = response.json()
        offers: list[OfferCandidate] = []
        for result in data.get("results", []):
            title = result.get("names", {}).get("title", f"Best Buy SKU {sku}")
            link = result.get("links", {}).get("web", "")
            review = result.get("customerReviews", {})
            try:
                rating = float(review.get("averageScore"))
            except (TypeError, ValueError):
                rating = None
            for idx, offer in enumerate(result.get("offers", [])):
                price = offer.get("prices", {}).get("current")
                if not isinstance(price, int | float):
                    continue
                condition_raw = str(offer.get("condition") or "").lower()
                condition = "certified" if condition_raw == "certified" else "open_box_excellent"
                quality = max(30.0, min(94.0, 20.0 + rating * 14.5)) if rating else None
                offers.append(
                    OfferCandidate(
                        provider="bestbuy-openbox",
                        provider_item_id=f"{sku}:{condition}:{idx}",
                        title=title,
                        url=link,
                        retailer="Best Buy",
                        price=float(price),
                        reference_price=float(result.get("prices", {}).get("current") or 0) or None,
                        condition=condition,
                        image_url=result.get("images", {}).get("standard"),
                        quality_score=quality,
                        quality_confidence=75.0 if rating else 30.0,
                        quality_reason=f"Best Buy customer rating {rating:g}/5" if rating else None,
                        trust_score=94.0,
                        extraction_confidence=98.0,
                        raw={"sku": sku, "condition": condition_raw},
                    )
                )
        return offers
