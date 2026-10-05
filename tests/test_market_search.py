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



def test_corpus_relevance_prefers_requested_product_over_shared_component_spec():
    intent = parse_intent("Cheap but quality RTX 5090 workstation under $5000")
    graphics_card = OfferCandidate(
        provider="brightdata",
        provider_item_id="gpu",
        title="ASUS ROG Astral GeForce RTX 5090 32GB GDDR7 OC Graphics Card",
        url="https://example.com/gpu",
        retailer="Example",
        price=1999,
        quality_score=95,
        quality_confidence=95,
        trust_score=95,
        extraction_confidence=95,
    )
    workstation = OfferCandidate(
        provider="brightdata",
        provider_item_id="pc",
        title="Creator Workstation Desktop Ryzen 9 RTX 5090 64GB RAM 2TB SSD",
        url="https://example.com/pc",
        retailer="Example",
        price=4499,
        quality_score=82,
        quality_confidence=80,
        trust_score=90,
        extraction_confidence=92,
    )

    rows = rank_search_results([graphics_card, workstation], intent)
    assert rows[0]["candidate"].provider_item_id == "pc"
    gpu_row = next(row for row in rows if row["candidate"].provider_item_id == "gpu")
    pc_row = next(row for row in rows if row["candidate"].provider_item_id == "pc")
    assert pc_row["retrieval_score"] > gpu_row["retrieval_score"]
    assert pc_row["fit_score"] > gpu_row["fit_score"]


def test_general_relevance_prefers_laptop_over_laptop_charger():
    intent = parse_intent("good laptop under $1200")
    laptop = OfferCandidate(
        provider="x", provider_item_id="laptop", title="Lenovo ThinkPad 14 Laptop",
        url="", retailer="A", price=999, quality_score=80, quality_confidence=75, trust_score=90
    )
    charger = OfferCandidate(
        provider="x", provider_item_id="charger", title="100W USB-C Laptop Charger Power Adapter",
        url="", retailer="B", price=39, quality_score=90, quality_confidence=90, trust_score=90
    )
    rows = rank_search_results([charger, laptop], intent)
    assert rows[0]["candidate"].provider_item_id == "laptop"


def test_general_relevance_prefers_monitor_over_monitor_stand():
    intent = parse_intent("27 inch QHD monitor under $250")
    monitor = OfferCandidate(
        provider="x", provider_item_id="monitor", title="Dell 27 QHD IPS Monitor",
        url="", retailer="A", price=219, quality_score=82, quality_confidence=80, trust_score=90
    )
    stand = OfferCandidate(
        provider="x", provider_item_id="stand", title="Dual 27 Inch Monitor Stand Desk Mount",
        url="", retailer="B", price=49, quality_score=88, quality_confidence=85, trust_score=90
    )
    rows = rank_search_results([stand, monitor], intent)
    assert rows[0]["candidate"].provider_item_id == "monitor"


def test_general_relevance_prefers_ssd_over_enclosure():
    intent = parse_intent("4TB NVMe SSD under $300")
    ssd = OfferCandidate(
        provider="x", provider_item_id="ssd", title="Crucial 4TB NVMe SSD PCIe 4.0",
        url="", retailer="A", price=249, quality_score=84, quality_confidence=80, trust_score=90
    )
    enclosure = OfferCandidate(
        provider="x", provider_item_id="enclosure", title="USB4 NVMe SSD Enclosure",
        url="", retailer="B", price=79, quality_score=90, quality_confidence=90, trust_score=90
    )
    rows = rank_search_results([enclosure, ssd], intent)
    assert rows[0]["candidate"].provider_item_id == "ssd"


def test_general_relevance_prefers_tv_over_soundbar():
    intent = parse_intent("OLED TV under $1000")
    tv = OfferCandidate(
        provider="x", provider_item_id="tv", title="LG 55 OLED Smart TV",
        url="", retailer="A", price=899, quality_score=86, quality_confidence=85, trust_score=90
    )
    soundbar = OfferCandidate(
        provider="x", provider_item_id="soundbar", title="Premium Soundbar for OLED TV",
        url="", retailer="B", price=199, quality_score=92, quality_confidence=90, trust_score=90
    )
    rows = rank_search_results([soundbar, tv], intent)
    assert rows[0]["candidate"].provider_item_id == "tv"
    tv_row = next(row for row in rows if row["candidate"].provider_item_id == "tv")
    soundbar_row = next(row for row in rows if row["candidate"].provider_item_id == "soundbar")
    assert tv_row["retrieval_score"] > soundbar_row["retrieval_score"]
