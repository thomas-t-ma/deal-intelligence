from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ..trust import trust_for_url
from ..types import OfferCandidate, SearchIntent
from .base import DiscoveryProvider

_MONEY_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)")
_STOPWORDS = {
    "find",
    "me",
    "a",
    "an",
    "the",
    "for",
    "with",
    "and",
    "or",
    "under",
    "below",
    "over",
    "above",
    "total",
    "budget",
    "good",
    "best",
    "deal",
    "deals",
    "please",
    "want",
    "need",
    "looking",
    "something",
    "that",
    "this",
    "my",
    "to",
    "of",
    "is",
    "are",
    "be",
    "performance",
    "irrelevant",
    "required",
    "prefer",
    "preferred",
    "around",
    "about",
}


def _plain(value: str) -> str:
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def _money_values(text: str) -> list[tuple[float, int, int]]:
    output: list[tuple[float, int, int]] = []
    for match in _MONEY_RE.finditer(text or ""):
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if 0 < value < 1_000_000:
            output.append((value, match.start(), match.end()))
    return output


def _price_from_text(text: str) -> float | None:
    patterns = [
        r"(?:on\s+sale\s+for|sale\s+for|priced?\s+at|drops?\s+to|down\s+to|for|from|now|at)\s+(?:just\s+|only\s+|nearly\s+)?\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)",
        r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)\s*(?:shipped|each|ea\b|today\b)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text or "", flags=re.I):
            tail = (text or "")[match.end() : match.end() + 12].lower()
            if re.match(r"\s*(?:off|discount)", tail):
                continue
            try:
                value = float(match.group(1).replace(",", ""))
            except ValueError:
                continue
            if 0 < value < 1_000_000:
                return value
    return None


def _pick_prices(
    title: str,
    description: str,
    *,
    allow_first_value_fallback: bool,
) -> tuple[float | None, float | None]:
    combined = f"{title} {description}".strip()
    current = _price_from_text(description) or _price_from_text(title)
    values = _money_values(combined)
    if current is None and allow_first_value_fallback and values:
        first, _start, end = values[0]
        tail = combined[end : end + 12].lower()
        if not re.match(r"\s*(?:off|discount)", tail):
            current = first
    if current is None:
        return None, None
    larger = [value for value, _start, _end in values if value >= current * 1.03]
    reference = min(larger) if larger else None
    return current, reference


def _query_terms(intent: SearchIntent) -> list[str]:
    words = re.findall(r'[A-Za-z0-9][A-Za-z0-9.+\-/"]*', intent.text.lower())
    return [
        word
        for word in words
        if len(word) > 2
        and word not in _STOPWORDS
        and not re.fullmatch(r"\$?\d+(?:\.\d+)?", word)
    ][:10]


def _external_link(html: str, source_host: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html or "", "html.parser")
    ignored_hosts = {
        source_host,
        f"www.{source_host}",
        "facebook.com",
        "www.facebook.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "youtube.com",
        "www.youtube.com",
    }
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        parsed = urlparse(href)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host or host in ignored_hosts:
            continue
        if host.endswith(source_host):
            continue
        label = anchor.get_text(" ", strip=True)
        return href, label or None
    return None, None


def _image_url(item: ET.Element, html: str) -> str | None:
    for child in item:
        tag = child.tag.lower()
        if tag.endswith("thumbnail") or tag.endswith("content"):
            url = child.attrib.get("url")
            if url:
                return str(url)
        if tag.endswith("enclosure") and child.attrib.get("type", "").startswith("image/"):
            url = child.attrib.get("url")
            if url:
                return str(url)
    soup = BeautifulSoup(html or "", "html.parser")
    image = soup.find("img", src=True)
    return str(image.get("src")) if image else None


@dataclass(frozen=True)
class CuratedFeedSpec:
    name: str
    label: str
    url: str
    source_host: str
    quality_score: float
    quality_confidence: float
    extraction_confidence: float
    first_value_fallback: bool = False


DEALNEWS_EDITORS = CuratedFeedSpec(
    name="dealnews",
    label="DealNews Editors' Choice",
    url="https://www.dealnews.com/f1682/Staff-Pick/?rss=1",
    source_host="dealnews.com",
    quality_score=89.0,
    quality_confidence=91.0,
    extraction_confidence=82.0,
    first_value_fallback=True,
)

NINE_TO_FIVE_STEALS = CuratedFeedSpec(
    name="9to5toys",
    label="9to5Toys Steals",
    url="https://9to5toys.com/steals/feed",
    source_host="9to5toys.com",
    quality_score=87.0,
    quality_confidence=88.0,
    extraction_confidence=80.0,
)


def parse_curated_feed(
    xml: str,
    spec: CuratedFeedSpec,
    intent: SearchIntent,
    limit: int = 30,
) -> list[OfferCandidate]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"{spec.label} returned an unreadable RSS feed") from exc

    items = root.findall("./channel/item")
    if not items:
        items = [node for node in root.iter() if node.tag.lower().endswith("entry")]

    terms = _query_terms(intent)
    output: list[OfferCandidate] = []
    for item in items:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not link:
            for child in item:
                if child.tag.lower().endswith("link") and child.attrib.get("href"):
                    link = str(child.attrib["href"]).strip()
                    break

        description = ""
        for child in item:
            tag = child.tag.lower()
            if tag.endswith("description") or tag.endswith("summary") or tag.endswith("content"):
                value = child.text or ""
                if len(value) > len(description):
                    description = value

        guid = (item.findtext("guid") or item.findtext("id") or link or title).strip()
        if not title or not link:
            continue

        plain_description = _plain(description)
        searchable = f"{title} {plain_description}".lower()
        if terms and not any(term in searchable for term in terms):
            continue

        price, reference = _pick_prices(
            title,
            plain_description,
            allow_first_value_fallback=spec.first_value_fallback,
        )
        if price is None:
            continue

        outbound, outbound_label = _external_link(description, spec.source_host)
        merchant_url = outbound or link
        merchant_host = (urlparse(merchant_url).hostname or spec.source_host).removeprefix("www.")
        retailer = outbound_label or merchant_host.split(".")[0].replace("-", " ").title()
        if len(retailer) > 50:
            retailer = merchant_host.split(".")[0].replace("-", " ").title()
        trust = trust_for_url(merchant_url) if outbound else 82.0

        output.append(
            OfferCandidate(
                provider=spec.name,
                provider_item_id=guid,
                title=title[:600],
                url=link,
                retailer=retailer,
                price=price,
                reference_price=reference,
                image_url=_image_url(item, description),
                quality_score=spec.quality_score,
                quality_confidence=spec.quality_confidence,
                quality_reason=f"Human-curated discovery signal from {spec.label}",
                trust_score=trust,
                extraction_confidence=spec.extraction_confidence,
                raw={
                    "source": f"{spec.name}-rss",
                    "source_label": spec.label,
                    "source_url": link,
                    "outbound_url": outbound,
                    "description": plain_description[:1500],
                },
            )
        )
        if len(output) >= max(1, limit):
            break
    return output


class CuratedFeedProvider(DiscoveryProvider):
    def __init__(
        self,
        spec: CuratedFeedSpec,
        user_agent: str = "DealIntelligence/0.3 (personal deal scout)",
    ):
        self.spec = spec
        self.user_agent = user_agent
        self.name = spec.name

    async def search(self, intent: SearchIntent, limit: int = 30) -> list[OfferCandidate]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(
                self.spec.url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/rss+xml, application/xml, text/xml, application/atom+xml",
                },
            )
            response.raise_for_status()
        return parse_curated_feed(response.text, self.spec, intent, limit=limit)
