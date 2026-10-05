from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from ..providers.bestbuy import BestBuyProvider
from ..providers.brightdata import BrightDataProvider
from ..providers.curated_feeds import (
    DEALNEWS_EDITORS,
    NINE_TO_FIVE_STEALS,
    CuratedFeedProvider,
)
from ..providers.serpapi import SerpApiProvider
from ..providers.slickdeals import SlickdealsProvider
from ..trust import trust_for_url
from ..types import EvidenceItem, OfferCandidate, SearchIntent, SearchOutcome
from .planner import build_search_plan
from .search import deduplicate_candidates, ollama_rerank_rows, rank_search_results

_PRICE_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)")
_RETAIL_HOSTS = {
    "amazon.com",
    "bestbuy.com",
    "microcenter.com",
    "newegg.com",
    "bhphotovideo.com",
    "walmart.com",
    "dell.com",
    "lenovo.com",
    "hp.com",
    "asus.com",
}


def _retailer_offer(item: EvidenceItem) -> OfferCandidate | None:
    host = (urlparse(item.url).hostname or "").lower().removeprefix("www.")
    if not any(host == domain or host.endswith("." + domain) for domain in _RETAIL_HOSTS):
        return None
    match = _PRICE_RE.search(f"{item.title} {item.snippet}")
    if not match:
        return None
    try:
        price = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    if not 1 <= price <= 250_000:
        return None
    retailer = host.split(".")[0].replace("-", " ").title()
    return OfferCandidate(
        provider="brightdata-web",
        provider_item_id=item.url,
        title=item.title,
        url=item.url,
        retailer=retailer,
        price=price,
        trust_score=trust_for_url(item.url),
        extraction_confidence=55.0,
        quality_confidence=20.0,
        raw={
            "source": "retailer-search-snippet",
            "description": item.snippet,
            "verification_needed": True,
        },
    )


async def run_search(
    intent: SearchIntent,
    *,
    mode: str,
    user_agent: str,
    brightdata: BrightDataProvider | None = None,
    serpapi: SerpApiProvider | None = None,
    bestbuy: BestBuyProvider | None = None,
    ollama_url: str | None = None,
    ollama_model: str | None = None,
    include_curated: bool = True,
) -> SearchOutcome:
    plan = build_search_plan(intent, mode)
    candidates: list[OfferCandidate] = []
    evidence: list[EvidenceItem] = []
    errors: list[str] = []
    providers: list[str] = []

    async def guarded(label: str, call: Callable[[], Awaitable[list]]) -> tuple[str, list | Exception]:
        try:
            return label, await call()
        except Exception as exc:
            return label, exc

    jobs: list[Awaitable[tuple[str, list | Exception]]] = []

    if brightdata:
        providers.append("Bright Data Google Shopping/Search")
        semaphore = asyncio.Semaphore(6)

        async def bright_shopping(query: str) -> list:
            async with semaphore:
                return await brightdata.search_query(query, limit=30)

        async def bright_web(query: str) -> list:
            async with semaphore:
                return await brightdata.evidence_query(query, limit=10)

        for spec in plan.queries:
            if spec.kind == "shopping":
                jobs.append(
                    guarded(
                        f"Bright Data shopping · {spec.query}",
                        lambda q=spec.query: bright_shopping(q),
                    )
                )
            else:
                jobs.append(
                    guarded(
                        f"Bright Data web · {spec.query}",
                        lambda q=spec.query: bright_web(q),
                    )
                )

    # SerpApi is a useful fallback, but we do not burn both providers across every expanded query.
    if serpapi and not brightdata:
        providers.append("Google Shopping via SerpApi")
        jobs.append(guarded("SerpApi", lambda: serpapi.search(intent, limit=40)))

    if bestbuy:
        providers.append("Best Buy live API")
        jobs.append(guarded("Best Buy", lambda: bestbuy.search(intent, limit=40)))

    if include_curated:
        providers.extend(["Slickdeals", "DealNews Editors' Choice", "9to5Toys Steals"])
        curated = [
            ("Slickdeals", SlickdealsProvider(user_agent).search(intent, limit=30)),
            (
                "DealNews",
                CuratedFeedProvider(DEALNEWS_EDITORS, user_agent).search(intent, limit=24),
            ),
            (
                "9to5Toys",
                CuratedFeedProvider(NINE_TO_FIVE_STEALS, user_agent).search(intent, limit=24),
            ),
        ]
        for label, coroutine in curated:
            jobs.append(guarded(label, lambda c=coroutine: c))

    raw_count = 0
    if jobs:
        results = await asyncio.gather(*jobs)
        for label, result in results:
            if isinstance(result, Exception):
                errors.append(f"{label}: {type(result).__name__}: {result}")
                continue
            raw_count += len(result)
            if result and isinstance(result[0], EvidenceItem):
                evidence.extend(result)
                if "retailer" in label.lower() or "web" in label.lower():
                    for item in result:
                        offer = _retailer_offer(item)
                        if offer:
                            candidates.append(offer)
            else:
                candidates.extend(result)

    deduped = deduplicate_candidates(candidates)
    rows = rank_search_results(deduped, intent, evidence=evidence)

    if ollama_url and ollama_model and rows:
        rows = await ollama_rerank_rows(rows, intent, ollama_url, ollama_model)

    return SearchOutcome(
        rows=rows,
        plan=plan,
        providers=providers,
        errors=list(dict.fromkeys(errors))[:12],
        candidate_count=raw_count + len(candidates),
        deduplicated_count=len(deduped),
        query_count=len(plan.queries),
    )
