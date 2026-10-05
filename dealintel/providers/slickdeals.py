from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from ..trust import trust_for_url
from ..types import OfferCandidate, SearchIntent
from .base import DiscoveryProvider

_FRONT_PAGE_RSS = "https://slickdeals.net/newsearch.php"
_MONEY_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)")
_THUMBS_RE = re.compile(r"Thumb\s+Score:\s*\+?(-?\d+)", re.I)
_STOPWORDS = {
    "find", "me", "a", "an", "the", "for", "with", "and", "or", "under", "below",
    "over", "above", "total", "budget", "good", "best", "deal", "deals", "please", "want",
    "need", "looking", "something", "that", "this", "my", "to", "of", "is", "are", "be",
    "performance", "irrelevant", "required", "prefer", "preferred", "around", "about",
}


def _money_values(text: str) -> list[float]:
    values: list[float] = []
    for raw in _MONEY_RE.findall(text or ""):
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if value > 0:
            values.append(value)
    return values


def _pick_price(title: str, description: str) -> tuple[float | None, float | None]:
    # The RSS description often says "for $X" or "on sale for $X"; prefer that over
    # arbitrary amounts in a title (which can contain pack sizes or multiple variants).
    desc_patterns = [
        r"(?:on\s+sale\s+for|sale\s+for|for|from|now)\s*\*?\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)",
        r"\*?\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)\*?",
    ]
    current = None
    for pattern in desc_patterns:
        match = re.search(pattern, description or "", flags=re.I)
        if match:
            try:
                current = float(match.group(1).replace(",", ""))
            except ValueError:
                current = None
            if current and current > 0:
                break
    title_values = _money_values(title)
    if current is None and title_values:
        current = title_values[0]
    if current is None:
        return None, None

    candidates = _money_values(f"{title} {description}")
    larger = [value for value in candidates if value >= current * 1.03]
    reference = min(larger) if larger else None
    return current, reference


def _clean_title(title: str) -> str:
    cleaned = re.sub(r"\s+\$\s*[0-9][0-9,]*(?:\.\d{1,2})?(?:\s*\+.*)?$", "", title).strip()
    return cleaned or title.strip()


def _query(intent: SearchIntent) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9.+\-/\"]*", intent.text)
    useful = [w for w in words if w.lower() not in _STOPWORDS and not re.fullmatch(r"\$?\d+(?:\.\d+)?", w)]
    return " ".join(useful[:8]).strip()



def parse_slickdeals_feed(xml: str, limit: int = 30) -> list[OfferCandidate]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("Slickdeals returned an unreadable RSS feed") from exc

    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    output: list[OfferCandidate] = []
    for item in root.findall("./channel/item")[: max(1, limit)]:
        raw_title = (item.findtext("title") or "").strip()
        thread_url = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        encoded = (item.findtext("content:encoded", namespaces=ns) or "").strip()
        guid = (item.findtext("guid") or thread_url or raw_title).strip()
        if not raw_title or not thread_url:
            continue

        price, reference = _pick_price(raw_title, description)
        if price is None:
            continue

        content_soup = BeautifulSoup(encoded, "html.parser") if encoded else BeautifulSoup("", "html.parser")
        content_text = content_soup.get_text(" ", strip=True)
        thumbs_match = _THUMBS_RE.search(content_text)
        thumbs = int(thumbs_match.group(1)) if thumbs_match else 0

        outbound = None
        merchant_domain = None
        retailer = "Slickdeals"
        for anchor in content_soup.find_all("a", href=True):
            domain = anchor.get("data-product-exitwebsite") or anchor.get("data-product-exitWebsite")
            if domain:
                merchant_domain = str(domain).strip().lower()
                outbound = str(anchor.get("href"))
                label = anchor.get_text(" ", strip=True)
                if label:
                    retailer = label.split(" via ")[-1].strip() or retailer
                break
        if merchant_domain:
            if retailer.lower() in {merchant_domain, f"www.{merchant_domain}"} or len(retailer) > 45:
                retailer = merchant_domain.removeprefix("www.").split(".")[0].replace("-", " ").title()
            merchant_url = f"https://{merchant_domain}/"
            trust = trust_for_url(merchant_url)
        else:
            merchant_url = thread_url
            trust = 72.0

        image = content_soup.find("img", src=True)
        image_url = str(image.get("src")) if image else None

        positive = max(0, thumbs)
        quality = min(90.0, 72.0 + 6.0 * math.log10(positive + 1))
        quality_conf = min(92.0, 62.0 + 8.0 * math.log10(positive + 1))
        if thumbs < 0:
            quality = max(35.0, 68.0 + thumbs * 0.5)
            quality_conf = 65.0

        output.append(
            OfferCandidate(
                provider="slickdeals",
                provider_item_id=guid,
                title=_clean_title(raw_title),
                url=thread_url,
                retailer=retailer,
                price=price,
                reference_price=reference,
                condition="new",
                image_url=image_url,
                quality_score=quality,
                quality_confidence=quality_conf,
                quality_reason=f"Slickdeals Frontpage/community signal (Thumb Score {thumbs:+d})",
                trust_score=trust,
                extraction_confidence=86.0,
                raw={
                    "source": "slickdeals-frontpage-rss",
                    "thumb_score": thumbs,
                    "merchant_domain": merchant_domain,
                    "merchant_url": merchant_url,
                    "outbound_url": outbound,
                    "description": BeautifulSoup(description, "html.parser").get_text(" ", strip=True)[:1500],
                },
            )
        )
    return output


class SlickdealsProvider(DiscoveryProvider):
    """Free discovery from Slickdeals' public Frontpage RSS feed."""

    name = "slickdeals"

    def __init__(self, user_agent: str = "DealIntelligence/0.2 (personal deal scout)"):
        self.user_agent = user_agent

    async def search(self, intent: SearchIntent, limit: int = 30) -> list[OfferCandidate]:
        params = {
            "mode": "frontpage",
            "searcharea": "deals",
            "searchin": "first",
            "rss": "1",
        }
        query = _query(intent)
        if query:
            params["q"] = query

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(
                _FRONT_PAGE_RSS,
                params=params,
                headers={"User-Agent": self.user_agent, "Accept": "application/rss+xml, application/xml, text/xml"},
            )
            response.raise_for_status()
        return parse_slickdeals_feed(response.text, limit=limit)
