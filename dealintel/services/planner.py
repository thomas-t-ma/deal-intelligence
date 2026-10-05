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
    ("workstation", ("workstation", "desktop computer", "desktop pc", "gaming pc", "prebuilt pc", "computer tower"), ("desktop", "prebuilt", "tower")),
    ("gpu", ("graphics card", "video card", "gpu", "geforce", "radeon"), ("rtx", "rx")),
    ("monitor_stand", ("monitor stand", "display stand", "monitor arm"), ("stand", "arm")),
    ("monitor", ("monitor", "computer display"), ("display", "qhd", "1440p", "4k")),
    ("ssd_enclosure", ("ssd enclosure", "nvme enclosure", "drive enclosure"), ("enclosure",)),
    ("ssd", ("solid state drive", "nvme ssd", "ssd"), ("nvme", "m 2", "pcie")),
    ("laptop_charger", ("laptop charger", "notebook charger", "power adapter"), ("charger", "ac adapter")),
    ("laptop", ("laptop", "notebook", "ultrabook", "macbook"), ()),
    ("keyboard", ("keyboard", "mechanical keyboard"), ("linear switch", "silent linear")),
    ("mouse", ("computer mouse", "gaming mouse"), ("mouse",)),
    ("soundbar", ("soundbar", "sound bar"), ("home theater bar",)),
    ("headphones", ("headphones", "headset", "earbuds"), ("anc",)),
    ("tv", ("television", "smart tv", "oled tv", "qled tv", "mini led tv"), ("tv", "oled", "qled")),
    ("surge_protector", ("surge protector", "surge suppressor"), ("power strip", "joules")),
    ("camera_lens", ("camera lens", "zoom lens", "prime lens"), ("lens",)),
    ("camera", ("mirrorless camera", "digital camera", "camera body"), ("camera",)),
)

_CATEGORY_EXPANSIONS = {
    "workstation": ("best value", "prebuilt", "creator workstation", "AI workstation"),
    "gpu": ("graphics card", "best value GPU"),
    "monitor": ("IPS", "bright display", "best value monitor"),
    "ssd": ("PCIe 4.0", "best value NVMe", "high endurance SSD"),
    "laptop": ("best value laptop", "laptop sale"),
    "keyboard": ("quiet keyboard", "best value keyboard"),
    "mouse": ("best value mouse",),
    "headphones": ("best value headphones", "headphones sale"),
    "tv": ("best value TV", "TV sale"),
    "surge_protector": ("high joule rating", "best value surge protector"),
    "camera": ("best value camera",),
    "camera_lens": ("best value lens",),
    "general": ("best value",),
}

_REVIEW_SOURCES = (
    "reddit.com",
    "rtings.com",
    "tomshardware.com",
    "pcmag.com",
    "techpowerup.com",
)


def _phrase_present(text: str, phrase: str) -> bool:
    words = [re.escape(part) for part in phrase.lower().split() if part]
    if not words:
        return False
    return re.search(r"\b" + r"\s+".join(words) + r"\b", text) is not None


def classify_category(text: str) -> str:
    """Infer a broad product class from product nouns, not from a specific search case."""
    lower = " ".join(text.lower().split())
    best = ("general", 0.0)
    for category, strong_terms, weak_terms in _CATEGORY_RULES:
        score = 0.0
        for phrase in strong_terms:
            if _phrase_present(lower, phrase):
                score += 3.0 + 1.5 * len(phrase.split())
        for phrase in weak_terms:
            if _phrase_present(lower, phrase):
                score += 1.0
        if score > best[1]:
            best = (category, score)
    return best[0]


def looks_exact_product(text: str) -> bool:
    lower = text.lower()
    # Exact-product mode is conservative: require a SKU/model-like token that
    # contains letters and digits in the same token (G914, WH-1000XM5, MZ-V9P4T0),
    # or a strong brand/family/capacity combination. Separate spec tokens such as
    # "RTX 5090" do not become exact products just because they contain a number.
    if re.search(r"\b(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]*\d)[a-z0-9-]{4,}\b", lower):
        return True
    brands = ("samsung", "sony", "lg", "dell", "lenovo", "asus", "apple", "wd", "crucial")
    if any(brand in lower for brand in brands) and re.search(r'\b\d+(?:tb|gb|inch|")\b', lower):
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
