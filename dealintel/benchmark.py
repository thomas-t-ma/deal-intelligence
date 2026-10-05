from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from .config import CredentialStore, load_config
from .providers import BestBuyProvider, BrightDataProvider, SerpApiProvider
from .services.deep_search import run_search
from .services.search import parse_intent


DEFAULT_CASES = [
    "Best RTX 5090 workstation under $5000 with at least 64 GB RAM",
    "Best 4TB NVMe SSD under $250",
    "Two bright 27-inch QHD monitors under $300 total with HDMI required",
    "Quiet full-size linear keyboard under $100",
    "Good 2TB SSD under $130",
    "Samsung 990 Pro 4TB",
    "Open-box OLED TV under $1000",
    "Best value laptop under $1200 for programming and school",
    "Used Sony A7 IV body under $1600",
    "Reliable surge protector at least 1000 joules under $30",
]


def _case_metrics(query: str, rows: list[dict]) -> dict:
    intent = parse_intent(query)
    top = rows[:5]
    within_budget = None
    if intent.max_unit_price is not None and top:
        within_budget = sum(
            row["candidate"].effective_price <= intent.max_unit_price for row in top
        ) / len(top)
    retailers = len({row["candidate"].retailer for row in top})
    return {
        "query": query,
        "top5_count": len(top),
        "top5_within_budget_fraction": within_budget,
        "top5_unique_retailers": retailers,
        "top5": [
            {
                "title": row["candidate"].title,
                "retailer": row["candidate"].retailer,
                "price": row["candidate"].effective_price,
                "overall": row["overall_score"],
                "fit": row["fit_score"],
                "quality": row["quality_score"],
                "deal": row["deal"].score,
                "confidence": row["confidence_score"],
            }
            for row in top
        ],
    }


async def run_benchmark(
    *,
    cases: list[str] | None = None,
    mode: str = "deep",
) -> dict:
    config = load_config()
    store = CredentialStore(config.secrets_path)

    bright_key = store.get("brightdata_api_key")
    bright = (
        BrightDataProvider(
            bright_key,
            zone=store.get("brightdata_zone", "serp_api1") or "serp_api1",
        )
        if bright_key
        else None
    )
    serp_key = store.get("serpapi_api_key")
    location = store.get("search_location", "Atlanta, Georgia, United States") or "Atlanta, Georgia, United States"
    serp = SerpApiProvider(serp_key, location=location) if serp_key else None

    bestbuy_key = store.get("bestbuy_api_key")
    bestbuy_ack = (store.get("bestbuy_terms_ack") or "").lower() in {"1", "true", "yes", "on"}
    bestbuy = BestBuyProvider(bestbuy_key) if bestbuy_key and bestbuy_ack else None

    ollama_url = store.get("ollama_url")
    ollama_model = store.get("ollama_model", "qwen3.5:4b")

    results = []
    for query in cases or DEFAULT_CASES:
        intent = parse_intent(query)
        outcome = await run_search(
            intent,
            mode=mode,
            user_agent=config.user_agent,
            brightdata=bright,
            serpapi=serp,
            bestbuy=bestbuy,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
            include_curated=True,
        )
        metrics = _case_metrics(query, outcome.rows)
        metrics["query_count"] = outcome.query_count
        metrics["candidate_count"] = outcome.deduplicated_count
        metrics["providers"] = outcome.providers
        metrics["errors"] = outcome.errors
        results.append(metrics)

    nonempty = sum(bool(item["top5"]) for item in results)
    budget_values = [
        item["top5_within_budget_fraction"]
        for item in results
        if item["top5_within_budget_fraction"] is not None
    ]
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "version": "0.4.0",
        "mode": mode,
        "broad_search_configured": bool(bright or serp),
        "summary": {
            "cases": len(results),
            "nonempty_fraction": nonempty / max(1, len(results)),
            "mean_top5_budget_compliance": (
                sum(budget_values) / len(budget_values) if budget_values else None
            ),
        },
        "cases": results,
    }


def save_benchmark(report: dict, output: Path | None = None) -> Path:
    config = load_config()
    target = output or (config.home / "benchmark-v0.4.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return target


def run_and_save(mode: str = "deep", output: Path | None = None) -> tuple[dict, Path]:
    report = asyncio.run(run_benchmark(mode=mode))
    return report, save_benchmark(report, output)
