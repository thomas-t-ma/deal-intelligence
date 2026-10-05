from __future__ import annotations

from urllib.parse import urlparse

import httpx

from ..trust import trust_for_url
from ..types import OfferCandidate, SearchIntent
from .base import DiscoveryProvider


class SerpApiProvider(DiscoveryProvider):
    name = "serpapi"

    def __init__(self, api_key: str, location: str = "Atlanta, Georgia, United States"):
        self.api_key = api_key
        self.location = location

    async def search(self, intent: SearchIntent, limit: int = 20) -> list[OfferCandidate]:
        params = {
            "engine": "google_shopping",
            "q": intent.text,
            "api_key": self.api_key,
            "gl": "us",
            "hl": "en",
            "location": intent.location or self.location,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get("https://serpapi.com/search.json", params=params)
            response.raise_for_status()
            data = response.json()
        results: list[OfferCandidate] = []
        for item in data.get("shopping_results", [])[: max(1, limit)]:
            price = item.get("extracted_price")
            if price is None:
                continue
            link = item.get("product_link") or item.get("link") or ""
            source = str(item.get("source") or "Google Shopping")
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            rating = item.get("rating")
            reviews = item.get("reviews")
            quality = None
            quality_conf = None
            quality_reason = None
            if isinstance(rating, int | float):
                quality = max(30.0, min(92.0, 20.0 + float(rating) * 14.0))
                count = float(reviews or 0)
                quality_conf = min(80.0, 30.0 + 7.0 * (count + 1) ** 0.25)
                quality_reason = f"Shopping aggregate rating {float(rating):g}/5"
            old_price = item.get("extracted_old_price")
            condition = "used" if item.get("second_hand_condition") else "new"
            merchant_url = link
            root = (urlparse(merchant_url).hostname or "").lower()
            trust = trust_for_url(merchant_url) if root else 58.0
            results.append(
                OfferCandidate(
                    provider=self.name,
                    provider_item_id=str(item.get("product_id") or item.get("position") or title),
                    title=title,
                    url=link,
                    retailer=source,
                    price=float(price),
                    reference_price=float(old_price) if isinstance(old_price, int | float) else None,
                    condition=condition,
                    image_url=item.get("thumbnail"),
                    quality_score=quality,
                    quality_confidence=quality_conf,
                    quality_reason=quality_reason,
                    trust_score=trust,
                    extraction_confidence=78.0,
                    raw={
                        "rating": rating,
                        "reviews": reviews,
                        "delivery": item.get("delivery"),
                        "tag": item.get("tag"),
                        "badge": item.get("badge"),
                        "source": source,
                    },
                )
            )
        return results
