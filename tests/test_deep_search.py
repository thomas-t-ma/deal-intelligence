import asyncio

from dealintel.services.deep_search import run_search
from dealintel.services.search import parse_intent
from dealintel.types import EvidenceItem, OfferCandidate


class FakeBrightData:
    async def search_query(self, query, limit=30):
        return [
            OfferCandidate(
                provider="brightdata",
                provider_item_id=query,
                title="Samsung 990 PRO 4TB NVMe SSD",
                url=f"https://example.com/{abs(hash(query))}",
                retailer="Example",
                price=219.0,
                brand="Samsung",
                model="MZ-V9P4T0",
                quality_score=88,
                quality_confidence=80,
                trust_score=85,
            )
        ]

    async def evidence_query(self, query, limit=10):
        return [
            EvidenceItem(
                source="tomshardware.com",
                title="Samsung 990 PRO 4TB review",
                url="https://tomshardware.com/review/example",
                snippet="Samsung 990 PRO 4TB reviewed in detail.",
            )
        ]


def test_deep_search_orchestrates_planned_queries():
    outcome = asyncio.run(
        run_search(
            parse_intent("Samsung 990 Pro 4TB under $250"),
            mode="deep",
            user_agent="test",
            brightdata=FakeBrightData(),
            include_curated=False,
        )
    )
    assert outcome.query_count > 5
    assert outcome.rows
    assert outcome.providers == ["Bright Data Google Shopping/Search"]
    assert outcome.rows[0]["fit_score"] >= 50
