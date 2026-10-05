from dealintel.services.search import parse_intent, rank_search_results
from dealintel.types import OfferCandidate


def test_parse_total_budget_and_quantity():
    intent = parse_intent("I need two monitors under $300 total budget. Gaming performance irrelevant.")
    assert intent.quantity == 2
    assert intent.total_budget == 300
    assert intent.max_unit_price == 150
    assert "gaming" in intent.excluded_terms


def test_parse_unit_budget():
    intent = parse_intent("Find a laptop under $1200")
    assert intent.quantity == 1
    assert intent.max_unit_price == 1200


def test_rank_penalizes_over_budget():
    intent = parse_intent("monitor under $200")
    a = OfferCandidate(provider="x", provider_item_id="a", title="Monitor A", url="", retailer="x", price=150, trust_score=90, quality_score=80, quality_confidence=80)
    b = OfferCandidate(provider="x", provider_item_id="b", title="Monitor B", url="", retailer="x", price=500, trust_score=90, quality_score=80, quality_confidence=80)
    rows = rank_search_results([b, a], intent)
    assert rows[0]["candidate"].provider_item_id == "a"
