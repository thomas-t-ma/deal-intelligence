from dealintel.services.planner import build_search_plan, classify_category, looks_exact_product
from dealintel.services.search import parse_intent


def test_deep_plan_expands_retailers_and_evidence():
    intent = parse_intent("Best RTX 5090 workstation under $5000 with 64 GB RAM")
    plan = build_search_plan(intent, "deep")
    assert plan.category == "workstation"
    assert len(plan.queries) > 10
    assert any(q.purpose == "retailer-discovery" for q in plan.queries)
    assert any(q.purpose == "quality-evidence" for q in plan.queries)
    assert any(q.kind == "shopping" for q in plan.queries)


def test_quick_plan_stays_small():
    plan = build_search_plan(parse_intent("4TB NVMe SSD under $250"), "quick")
    assert plan.category == "ssd"
    assert len(plan.queries) <= 7


def test_exact_product_detection():
    assert looks_exact_product("Samsung 990 Pro 4TB")
    assert classify_category("Samsung 990 Pro 4TB NVMe SSD") == "ssd"
