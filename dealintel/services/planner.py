from __future__ import annotations

import re

from ..types import QuerySpec, SearchIntent, SearchPlan

_RETAILERS = (
    "amazon.com",
    "bestbuy.com",
    "microcenter.com",
    "newegg.com",
    "bhphotovideo.com",
    "walmart.com",
)

_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "workstation",
        ("workstation", "desktop", "pc", "rtx 5090", "rtx 5080", "local ai", "llm"),
        ("prebuilt", "desktop pc", "workstation pc"),
    ),
    (
        "monitor",
        ("monitor", "display", "qhd", "4k", "1440p", "ips", "oled"),
        ("monitor", "display"),
    ),
    (
        "ssd",
        ("ssd", "nvme", "m.2", "pcie 4", "pcie 5", "storage"),
        ("nvme ssd", "solid state drive"),
    ),
    (
        "laptop",
        ("laptop", "notebook", "ultrabook", "macbook"),
        ("laptop", "notebook"),
    ),
    (
        "keyboard",
        ("keyboard", "mechanical", "linear switch", "silent linear"),
        ("keyboard", "mechanical keyboard"),
    ),
    (
        "headphones",
        ("headphones", "headset", "earbuds", "anc"),
        ("headphones", "headset"),
    ),
    (
        "tv",
        ("tv", "television", "oled tv", "mini-led", "qled"),
        ("tv", "television"),
    ),
)

_CATEGORY_EXPANSIONS = {
    "workstation": (
        "best value",
        "prebuilt",
        "creator workstation",
        "AI workstation",
    ),
    "monitor": (
        "IPS",
        "bright display",
        "best value monitor",
    ),
    "ssd": (
        "PCIe 4.0",
        "best value NVMe",
        "high endurance SSD",
    ),
    "laptop": (
        "best value laptop",
        "laptop sale",
    ),
    "keyboard": (
        "quiet keyboard",
        "best value keyboard",
    ),
    "headphones": (
        "best value headphones",
        "headphones sale",
    ),
    "tv": (
        "best value TV",
        "TV sale",
    ),
    "general": ("best value",),
}

_REVIEW_SOURCES = (
    "reddit.com",
    "rtings.com",
    "tomshardware.com",
    "pcmag.com",
    "techpowerup.com",
)


def classify_category(text: str) -> str:
    lower = text.lower()
    best = ("general", 0)
    for category, needles, _aliases in _CATEGORY_RULES:
        score = sum(1 for needle in needles if needle in lower)
        if score > best[1]:
            best = (category, score)
    return best[0]


def looks_exact_product(text: str) -> bool:
    lower = text.lower()
    # Model-like identifiers strongly suggest an exact-product search.
    if re.search(r"\b[a-z]{1,6}[- ]?\d{3,}[a-z0-9-]*\b", lower):
        return True
    # Brand + product family + capacity/size often indicates a known SKU/family.
    brands = ("samsung", "sony", "lg", "dell", "lenovo", "asus", "apple", "wd", "crucial")
    if any(brand in lower for brand in brands) and re.search(r"\b\d+(?:tb|gb|inch|\")\b", lower):
        return True
    return False


def _core_query(intent: SearchIntent) -> str:
    text = " ".join(intent.text.split()).strip()
    # Strip conversational lead-ins while preserving the user's actual constraints.
    text = re.sub(
        r"^(?:please\s+)?(?:find|get|show|help me find|i need|i want|looking for)\s+(?:me\s+)?",
        "",
        text,
        flags=re.I,
    ).strip()
    return text or intent.text.strip()


def _unique(specs: list[QuerySpec]) -> list[QuerySpec]:
    seen: set[tuple[str, str]] = set()
    out: list[QuerySpec] = []
    for spec in specs:
        key = (spec.kind, spec.query.casefold().strip())
        if not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(spec)
    return out


def build_search_plan(intent: SearchIntent, mode: str = "quick") -> SearchPlan:
    mode = "deep" if mode == "deep" else "quick"
    category = intent.category or classify_category(intent.text)
    exact = intent.exact_product or looks_exact_product(intent.text)
    core = _core_query(intent)

    specs: list[QuerySpec] = [
        QuerySpec(core, "shopping", "primary", 1.0),
    ]

    if exact:
        specs.append(QuerySpec(f'"{core}"', "shopping", "exact-product", 1.15))
    else:
        expansions = _CATEGORY_EXPANSIONS.get(category, _CATEGORY_EXPANSIONS["general"])
        for suffix in expansions[: 1 if mode == "quick" else 4]:
            specs.append(QuerySpec(f"{core} {suffix}", "shopping", "category-expansion", 0.9))

    # A few retailer-focused queries catch products that generic shopping results miss.
    retailer_count = 2 if mode == "quick" else len(_RETAILERS)
    for domain in _RETAILERS[:retailer_count]:
        specs.append(QuerySpec(f"site:{domain} {core}", "web", "retailer-discovery", 0.85))

    # Evidence queries are not treated as product offers. They are used for quality/confidence.
    specs.append(QuerySpec(f"{core} review", "web", "quality-evidence", 0.75))
    if mode == "deep":
        specs.append(QuerySpec(f"{core} reddit", "web", "community-evidence", 0.72))
        for domain in _REVIEW_SOURCES[:4]:
            specs.append(QuerySpec(f"site:{domain} {core}", "web", "quality-evidence", 0.72))

    specs = _unique(specs)
    cap = 7 if mode == "quick" else 22
    specs = specs[:cap]

    return SearchPlan(
        mode=mode,
        intent=intent,
        queries=specs,
        category=category,
        exact_product=exact,
        explanation=(
            f"{mode.title()} search: {sum(q.kind == 'shopping' for q in specs)} shopping "
            f"queries + {sum(q.kind == 'web' for q in specs)} targeted web/evidence queries; "
            f"category={category}; exact_product={'yes' if exact else 'no'}."
        ),
    )
