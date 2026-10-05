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
    assert looks_exact_product("PowerSpec G914")
    assert looks_exact_product("Sony WH-1000XM5")
    assert not looks_exact_product("Samsung SSD 4TB")
    assert not looks_exact_product("Dell laptop 32GB")
    assert not looks_exact_product("Cheap but quality RTX 5090 workstation")
    assert classify_category("Samsung 990 Pro 4TB NVMe SSD") == "ssd"


def test_category_classifier_uses_product_nouns_not_shared_specs():
    assert classify_category("Cheap but quality RTX 5090 workstation") == "workstation"
    assert classify_category("ASUS GeForce RTX 5090 32GB graphics card") == "gpu"
    assert classify_category("27 inch dual monitor stand") == "monitor_stand"
    assert classify_category("4TB NVMe SSD") == "ssd"
    assert classify_category("USB4 NVMe SSD Enclosure") == "ssd_enclosure"
    assert classify_category("Premium Soundbar for OLED TV") == "soundbar"
    assert classify_category("100W Charger for Dell Laptop") == "laptop_charger"


def test_planner_does_not_inject_case_specific_product_terms():
    plan = build_search_plan(parse_intent("Cheap but quality RTX 5090 workstation"), "deep")
    shopping_queries = [q.query.lower() for q in plan.queries if q.kind == "shopping"]
    assert shopping_queries
    assert shopping_queries[0] == "cheap but quality rtx 5090 workstation"
    assert all("complete desktop computer" not in query for query in shopping_queries)
