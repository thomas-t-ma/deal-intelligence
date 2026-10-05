from __future__ import annotations

import json
import re
from collections.abc import Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .trust import trust_for_url
from .types import OfferCandidate

CONDITION_MAP = {
    "http://schema.org/NewCondition": "new",
    "https://schema.org/NewCondition": "new",
    "newcondition": "new",
    "new": "new",
    "http://schema.org/RefurbishedCondition": "refurbished",
    "https://schema.org/RefurbishedCondition": "refurbished",
    "refurbishedcondition": "refurbished",
    "refurbished": "refurbished",
    "http://schema.org/UsedCondition": "used",
    "https://schema.org/UsedCondition": "used",
    "usedcondition": "used",
    "used": "used",
}


def parse_money(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def normalize_condition(value: object) -> str:
    if not value:
        return "new"
    raw = str(value).strip()
    return CONDITION_MAP.get(raw, CONDITION_MAP.get(raw.lower(), "unknown"))


def _iter_jsonld_nodes(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for node in graph:
                yield from _iter_jsonld_nodes(node)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_jsonld_nodes(item)


def _brand(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        name = value.get("name")
        return str(name).strip() if name else None
    return None


def _image(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return str(first.get("url") or first.get("contentUrl") or "") or None
    if isinstance(value, dict):
        return str(value.get("url") or value.get("contentUrl") or "") or None
    return None


def _offer_dict(offers: object) -> dict | None:
    if isinstance(offers, dict):
        if str(offers.get("@type", "")).lower() == "aggregateoffer":
            inner = offers.get("offers")
            if isinstance(inner, list) and inner:
                valid = [x for x in inner if isinstance(x, dict)]
                if valid:
                    return min(valid, key=lambda x: parse_money(x.get("price")) or float("inf"))
        return offers
    if isinstance(offers, list):
        valid = [x for x in offers if isinstance(x, dict) and parse_money(x.get("price"))]
        if valid:
            return min(valid, key=lambda x: parse_money(x.get("price")) or float("inf"))
    return None



def _node_value(node) -> str | None:
    if not node:
        return None
    for attr in ("content", "value", "src", "href"):
        value = node.get(attr) if hasattr(node, "get") else None
        if value:
            return str(value).strip()
    text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else str(node)
    return text.strip() or None


def _microdata_candidate(url: str, soup: BeautifulSoup, retailer: str) -> OfferCandidate | None:
    products = soup.select('[itemtype*="schema.org/Product"], [itemtype*="schema.org/product"]')
    roots = products or [soup]
    for root in roots:
        name_node = root.select_one('[itemprop="name"]')
        price_node = root.select_one('[itemprop="price"]')
        if not price_node:
            continue
        title = _node_value(name_node)
        price = parse_money(_node_value(price_node))
        if not title or price is None or price <= 0:
            continue
        availability_node = root.select_one('[itemprop="availability"]')
        availability = (_node_value(availability_node) or "").lower()
        brand_node = root.select_one('[itemprop="brand"]')
        model_node = root.select_one('[itemprop="model"]')
        sku_node = root.select_one('[itemprop="sku"]')
        gtin_node = root.select_one('[itemprop^="gtin"]')
        image_node = root.select_one('[itemprop="image"]')
        currency_node = root.select_one('[itemprop="priceCurrency"]')
        condition_node = root.select_one('[itemprop="itemCondition"]')
        identifier = _node_value(gtin_node) or _node_value(sku_node) or url
        return OfferCandidate(
            provider="url",
            provider_item_id=f"{retailer}:{identifier}",
            title=title,
            url=url,
            retailer=retailer,
            price=price,
            currency=_node_value(currency_node) or "USD",
            condition=normalize_condition(_node_value(condition_node)),
            available=not any(x in availability for x in ("outofstock", "soldout", "discontinued")),
            brand=_node_value(brand_node),
            model=_node_value(model_node),
            gtin=_node_value(gtin_node),
            image_url=_node_value(image_node),
            trust_score=trust_for_url(url),
            extraction_confidence=82.0,
            raw={"source": "schema-microdata"},
        )
    return None


def _first_price(soup: BeautifulSoup, selectors: tuple[str, ...]) -> float | None:
    for selector in selectors:
        for node in soup.select(selector)[:6]:
            value = _node_value(node)
            parsed = parse_money(value)
            if parsed is not None and 0 < parsed < 1_000_000:
                return parsed
    return None


def _retailer_fallback_candidate(url: str, soup: BeautifulSoup, retailer: str) -> OfferCandidate | None:
    """Pragmatic private-use fallback for pages that omit structured Product metadata.

    These selectors are deliberately lower-confidence than JSON-LD/microdata. They make the tracker
    useful on more mainstream retail pages without treating every dollar amount in arbitrary page
    text as a product price.
    """
    host = retailer.lower()
    rules: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    if "amazon." in host:
        rules.append((("#productTitle", "h1"), ("#corePrice_feature_div .a-offscreen", ".reinventPricePriceToPayMargin .a-offscreen", ".a-price .a-offscreen", "#priceblock_dealprice", "#priceblock_ourprice")))
    if "walmart." in host:
        rules.append((("h1[itemprop='name']", "h1"), ("[itemprop='price']", "[data-automation-id='product-price']", "[data-testid='price-wrap']")))
    if "microcenter." in host:
        rules.append((("h1", ".product-name"), ("[itemprop='price']", ".product-price", ".price")))
    if "newegg." in host:
        rules.append(((".product-title", "h1"), (".price-current", "[itemprop='price']")))
    if "bestbuy." in host:
        rules.append((("h1", "[data-testid='product-title']"), ("[data-testid='customer-price']", ".priceView-customer-price span[aria-hidden='true']", ".priceView-customer-price")))
    if "target." in host:
        rules.append((("[data-test='product-title']", "h1"), ("[data-test='product-price']", "[itemprop='price']")))

    # Generic but still semantically targeted fallback used after known-retailer rules.
    rules.append((("h1[itemprop='name']", "h1"), ("[itemprop='price']", "meta[itemprop='price']")))

    for title_selectors, price_selectors in rules:
        title = None
        for selector in title_selectors:
            node = soup.select_one(selector)
            title = _node_value(node)
            if title:
                break
        price = _first_price(soup, price_selectors)
        if not title or price is None:
            continue
        image = soup.select_one("meta[property='og:image']") or soup.select_one("[itemprop='image']")
        return OfferCandidate(
            provider="url",
            provider_item_id=url,
            title=title[:500],
            url=url,
            retailer=retailer,
            price=price,
            image_url=_node_value(image),
            trust_score=trust_for_url(url),
            extraction_confidence=64.0,
            raw={"source": "retailer-selector-fallback"},
        )
    return None

def extract_product_from_html(url: str, html: str) -> OfferCandidate:
    soup = BeautifulSoup(html, "html.parser")
    retailer = (urlparse(url).hostname or "unknown").removeprefix("www.")

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text(strip=True)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _iter_jsonld_nodes(parsed):
            node_type = node.get("@type")
            types = [node_type] if isinstance(node_type, str) else node_type or []
            if not any(str(t).lower() == "product" for t in types):
                continue
            offer = _offer_dict(node.get("offers"))
            if not offer:
                continue
            price = parse_money(offer.get("price") or offer.get("lowPrice"))
            if price is None or price <= 0:
                continue
            availability = str(offer.get("availability", "")).lower()
            available = not any(x in availability for x in ("outofstock", "soldout", "discontinued"))
            title = str(node.get("name") or "").strip()
            if not title:
                continue
            rating = node.get("aggregateRating") if isinstance(node.get("aggregateRating"), dict) else {}
            review_score = parse_money(rating.get("ratingValue")) if rating else None
            review_count = parse_money(rating.get("reviewCount")) if rating else None
            quality = None
            quality_conf = None
            quality_reason = None
            if review_score is not None:
                quality = max(30.0, min(92.0, 20.0 + review_score * 14.0))
                count = max(0.0, review_count or 0.0)
                quality_conf = min(85.0, 35.0 + 8.0 * (count + 1) ** 0.25)
                quality_reason = f"Retailer/customer aggregate rating {review_score:g}/5"
            identifier = (
                node.get("gtin13")
                or node.get("gtin12")
                or node.get("gtin14")
                or node.get("gtin")
                or node.get("sku")
                or url
            )
            return OfferCandidate(
                provider="url",
                provider_item_id=f"{retailer}:{identifier}",
                title=title,
                url=url,
                retailer=retailer,
                seller=str(offer.get("seller", {}).get("name", ""))
                if isinstance(offer.get("seller"), dict)
                else None,
                price=price,
                currency=str(offer.get("priceCurrency") or "USD"),
                reference_price=parse_money(offer.get("highPrice")),
                condition=normalize_condition(offer.get("itemCondition")),
                available=available,
                brand=_brand(node.get("brand")),
                model=str(node.get("model") or "").strip() or None,
                gtin=str(
                    node.get("gtin13")
                    or node.get("gtin12")
                    or node.get("gtin14")
                    or node.get("gtin")
                    or ""
                ).strip()
                or None,
                mpn=str(node.get("mpn") or "").strip() or None,
                category=str(node.get("category") or "").strip() or None,
                image_url=_image(node.get("image")),
                quality_score=quality,
                quality_confidence=quality_conf,
                quality_reason=quality_reason,
                trust_score=trust_for_url(url),
                extraction_confidence=93.0,
                raw={"source": "json-ld"},
            )

    # Structured meta fallback. We intentionally avoid arbitrary regex scraping because a random
    # dollar amount on a page is not reliable enough to become a price observation.
    def meta(*names: str) -> str | None:
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find(
                "meta", attrs={"name": name}
            ) or soup.find("meta", attrs={"itemprop": name})
            if tag and tag.get("content"):
                return str(tag.get("content")).strip()
        return None

    title = meta("og:title", "twitter:title", "name") or (soup.title.string.strip() if soup.title and soup.title.string else None)
    price = parse_money(meta("product:price:amount", "og:price:amount", "price"))
    if title and price and price > 0:
        return OfferCandidate(
            provider="url",
            provider_item_id=url,
            title=title,
            url=url,
            retailer=retailer,
            price=price,
            currency=meta("product:price:currency", "priceCurrency") or "USD",
            image_url=meta("og:image", "twitter:image"),
            trust_score=trust_for_url(url),
            extraction_confidence=72.0,
            raw={"source": "structured-meta"},
        )

    microdata = _microdata_candidate(url, soup, retailer)
    if microdata:
        return microdata

    fallback = _retailer_fallback_candidate(url, soup, retailer)
    if fallback:
        return fallback

    raise ValueError("No product price could be extracted from structured data or supported retailer markup.")
