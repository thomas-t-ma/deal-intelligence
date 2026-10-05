from dealintel.services.search import parse_intent, rank_search_results
from dealintel.types import OfferCandidate


def _offer(item_id, retailer, price, model="MZ-V9P4T0"):
    return OfferCandidate(
        provider="test",
        provider_item_id=item_id,
        title="Samsung 990 PRO 4TB NVMe SSD",
        url=f"https://{retailer.lower()}.example/{item_id}",
        retailer=retailer,
        price=price,
        brand="Samsung",
        model=model,
        quality_score=90,
        quality_confidence=85,
        trust_score=90,
        extraction_confidence=95,
    )


def test_same_product_market_median_becomes_reference():
    rows = rank_search_results(
        [_offer("a", "One", 300), _offer("b", "Two", 250), _offer("c", "Three", 200)],
        parse_intent("Samsung 990 Pro 4TB"),
    )
    cheapest = next(row for row in rows if row["candidate"].price == 200)
    assert cheapest["market_typical"] == 250
    assert cheapest["market_offer_count"] == 3
    assert cheapest["market_discount_pct"] == 20


def test_wrong_major_gpu_is_suppressed():
    intent = parse_intent("RTX 5090 workstation under $5000")
    good = OfferCandidate(
        provider="x", provider_item_id="1", title="RTX 5090 workstation 64GB",
        url="", retailer="A", price=4500, quality_score=80, quality_confidence=80, trust_score=90
    )
    wrong = OfferCandidate(
        provider="x", provider_item_id="2", title="RTX 5080 workstation 64GB",
        url="", retailer="B", price=3000, quality_score=90, quality_confidence=90, trust_score=90
    )
    rows = rank_search_results([wrong, good], intent)
    assert rows[0]["candidate"].provider_item_id == "1"
    assert rows[0]["fit_score"] > rows[1]["fit_score"]


def test_google_product_cluster_groups_title_variants():
    a = OfferCandidate(
        provider="brightdata",
        provider_item_id="a",
        title="Samsung 990 PRO 4TB SSD",
        url="https://one.example/a",
        retailer="One",
        price=220,
        quality_score=88,
        quality_confidence=80,
        trust_score=90,
        raw={"google_product_id": "gp-123"},
    )
    b = OfferCandidate(
        provider="brightdata",
        provider_item_id="b",
        title="Samsung 990 PRO 4TB PCIe 4.0 NVMe M.2",
        url="https://two.example/b",
        retailer="Two",
        price=260,
        quality_score=88,
        quality_confidence=80,
        trust_score=90,
        raw={"google_product_id": "gp-123"},
    )
    rows = rank_search_results([a, b], parse_intent("Samsung 990 Pro 4TB"))
    assert rows[0]["market_typical"] == 240
    assert rows[0]["market_offer_count"] == 2
