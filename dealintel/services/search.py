from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict

import httpx

from ..identity import normalize_identifier, normalize_text
from ..scoring import score_deal
from ..types import EvidenceItem, OfferCandidate, SearchIntent

_MAJOR_TOKEN_PATTERNS = (
    re.compile(r"\brtx\s*\d{4}(?:\s*ti|\s*super)?\b", re.I),
    re.compile(r"\brx\s*\d{4}(?:\s*xtx|\s*xt)?\b", re.I),
    re.compile(r"\b\d+(?:\.\d+)?\s*tb\b", re.I),
    re.compile(r"\b\d+\s*gb\s*(?:ram|memory|ddr\d*)?\b", re.I),
    re.compile(r"\b\d{2}\s*(?:inch|\")\b", re.I),
    re.compile(r"\b(?:4k|uhd|qhd|1440p|1080p|oled|mini[- ]?led)\b", re.I),
)


def parse_intent(text: str) -> SearchIntent:
    raw = " ".join(text.split()).strip()
    lower = raw.lower()
    quantity = 1
    qty_match = re.search(
        r"\b(?:need|want|buy|find)?\s*(\d+)\s*(?:x|×|units?|monitors?|laptops?|pcs?|items?)\b",
        lower,
    )
    if qty_match:
        quantity = max(1, min(100, int(qty_match.group(1))))
    elif re.search(r"\b(two|pair of)\b", lower):
        quantity = 2

    total_budget = None
    max_unit_price = None
    budget_match = re.search(
        r"(?:total\s+budget|budget|under|less than|<=?|up to)\s*(?:of\s*)?\$?\s*([\d,]+(?:\.\d{1,2})?)",
        lower,
    )
    if budget_match:
        value = float(budget_match.group(1).replace(",", ""))
        if "total" in budget_match.group(0) or quantity > 1:
            total_budget = value
            max_unit_price = value / quantity
        else:
            max_unit_price = value

    excluded: list[str] = []
    if "gaming irrelevant" in lower or "gaming performance irrelevant" in lower:
        excluded.extend(["gaming", "rgb"])
    if "no rgb" in lower:
        excluded.append("rgb")

    required: list[str] = []
    for match in re.finditer(
        r"\b(hdmi|displayport|usb[- ]?c|thunderbolt|wifi\s*7|oled|ips)\s+(?:required|needed|must)\b",
        lower,
    ):
        required.append(match.group(1))

    preferred: list[str] = []
    for term in ("bright", "quiet", "silent", "reliable", "upgradable", "upgradeable"):
        if term in lower:
            preferred.append(term)

    allowed = ["new", "open_box_excellent", "certified", "refurbished"]
    if "used" in lower:
        allowed.append("used")

    return SearchIntent(
        text=raw,
        max_unit_price=max_unit_price,
        total_budget=total_budget,
        quantity=quantity,
        excluded_terms=tuple(dict.fromkeys(excluded)),
        preferred_terms=tuple(dict.fromkeys(preferred)),
        required_terms=tuple(dict.fromkeys(required)),
        allowed_conditions=tuple(allowed),
    )


async def ollama_parse_intent(text: str, url: str, model: str) -> SearchIntent | None:
    prompt = f"""Convert this shopping request into JSON only.
Keys: max_unit_price(number|null), total_budget(number|null), quantity(integer), min_quality(number 0-100), allowed_conditions(array from new,open_box_excellent,certified,refurbished,used), required_terms(array strings), preferred_terms(array strings), excluded_terms(array strings), location(string|null), category(string|null), exact_product(boolean).
Preserve explicit product identifiers and hard requirements. Do not invent requirements.
Request: {text}
"""
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json", "think": False}
    try:
        async with httpx.AsyncClient(timeout=18) as client:
            response = await client.post(url.rstrip("/") + "/api/generate", json=payload)
            response.raise_for_status()
            data = json.loads(response.json().get("response", "{}"))
    except Exception:
        return None
    deterministic = parse_intent(text)
    try:
        return SearchIntent(
            text=text,
            max_unit_price=data.get("max_unit_price") or deterministic.max_unit_price,
            total_budget=data.get("total_budget") or deterministic.total_budget,
            quantity=max(1, int(data.get("quantity") or deterministic.quantity)),
            min_quality=float(data.get("min_quality") or deterministic.min_quality),
            allowed_conditions=tuple(data.get("allowed_conditions") or deterministic.allowed_conditions),
            required_terms=tuple(data.get("required_terms") or deterministic.required_terms),
            preferred_terms=tuple(data.get("preferred_terms") or deterministic.preferred_terms),
            excluded_terms=tuple(data.get("excluded_terms") or deterministic.excluded_terms),
            location=data.get("location") or deterministic.location,
            category=data.get("category") or deterministic.category,
            exact_product=bool(data.get("exact_product") or deterministic.exact_product),
        )
    except (TypeError, ValueError):
        return deterministic


def _major_tokens(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for pattern in _MAJOR_TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            found.append(normalize_text(match.group(0)))
    return tuple(dict.fromkeys(token for token in found if token))


def _identity_key(candidate: OfferCandidate) -> str:
    google_product_id = candidate.raw.get("google_product_id")
    if google_product_id:
        return f"google-product:{google_product_id}"
    if candidate.gtin:
        return f"gtin:{normalize_identifier(candidate.gtin)}"
    brand = normalize_text(candidate.brand)
    if candidate.model:
        return f"model:{brand}:{normalize_identifier(candidate.model)}"
    if candidate.mpn:
        return f"mpn:{brand}:{normalize_identifier(candidate.mpn)}"
    title = normalize_text(candidate.title)
    modelish = re.findall(r"\b(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]*\d)[a-z0-9-]{5,}\b", title)
    if modelish:
        return f"title-model:{brand}:{'|'.join(modelish[:3])}"
    # Deliberately strict fallback. False splits are safer than merging different variants.
    return f"title:{title}"


def deduplicate_candidates(candidates: list[OfferCandidate]) -> list[OfferCandidate]:
    seen_urls: set[str] = set()
    seen_offer: set[tuple[str, str, int]] = set()
    output: list[OfferCandidate] = []
    for candidate in candidates:
        url = candidate.url.strip()
        if url and url in seen_urls:
            continue
        key = (
            _identity_key(candidate),
            normalize_text(candidate.retailer),
            int(round(candidate.effective_price * 100)),
        )
        if key in seen_offer:
            continue
        if url:
            seen_urls.add(url)
        seen_offer.add(key)
        output.append(candidate)
    return output


def _market_references(candidates: list[OfferCandidate]) -> dict[str, tuple[float, int]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for candidate in candidates:
        if candidate.condition != "new" or not candidate.available or candidate.effective_price <= 0:
            continue
        grouped[_identity_key(candidate)].append(candidate.effective_price)
    refs: dict[str, tuple[float, int]] = {}
    for key, prices in grouped.items():
        if len(prices) >= 2:
            refs[key] = (statistics.median(prices), len(prices))
    return refs


def _candidate_search_text(candidate: OfferCandidate) -> str:
    extras = " ".join(
        str(value)
        for value in (
            candidate.brand,
            candidate.model,
            candidate.mpn,
            candidate.category,
            candidate.raw.get("description"),
            candidate.raw.get("specifications"),
        )
        if value
    )
    return normalize_text(f"{candidate.title} {extras}")


def _workstation_product_type(candidate: OfferCandidate, intent: SearchIntent) -> tuple[bool, bool, bool]:
    """Return (system_requested, complete_system_visible, standalone_gpu_component)."""
    request = normalize_text(intent.text)
    system_requested = intent.category == "workstation" or bool(
        re.search(r"\b(?:workstation|desktop|prebuilt|gaming pc|desktop pc|computer tower)\b", request)
    )
    if not system_requested:
        return False, False, False

    text = _candidate_search_text(candidate)
    complete_system_visible = any(
        cue in text
        for cue in (
            "workstation",
            "desktop",
            "prebuilt",
            "gaming pc",
            "desktop pc",
            "tower pc",
            "computer system",
        )
    )
    cpu_visible = bool(
        re.search(
            r"\b(?:ryzen|threadripper|xeon|intel core|core ultra|i[579][ -]?\d{4,5})\b",
            text,
        )
    )
    system_memory_or_storage = bool(re.search(r"\b\d+\s*gb\s+ram\b", text)) or " ssd" in f" {text}"
    if cpu_visible and system_memory_or_storage:
        complete_system_visible = True

    gpu_family_visible = bool(re.search(r"\b(?:rtx|rx)\s*\d{4}\b", text))
    component_cue = any(
        cue in text
        for cue in (
            "graphics card",
            "video card",
            "founders edition",
            "gpu only",
            "graphics board",
            "gddr7",
            "gddr6",
        )
    )
    standalone_gpu_component = gpu_family_visible and component_cue and not complete_system_visible
    return system_requested, complete_system_visible, standalone_gpu_component


def _matched_evidence(candidate: OfferCandidate, evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    if not evidence:
        return []
    model = normalize_text(candidate.model)
    title_words = [w for w in normalize_text(candidate.title).split() if len(w) >= 4][:6]
    matched: list[EvidenceItem] = []
    for item in evidence:
        haystack = normalize_text(f"{item.title} {item.snippet}")
        if model and model in haystack:
            matched.append(item)
            continue
        overlap = sum(word in haystack for word in title_words)
        if overlap >= max(2, min(4, len(title_words) // 2)):
            matched.append(item)
    return matched[:8]


def _fit_score(candidate: OfferCandidate, intent: SearchIntent) -> tuple[float, list[str]]:
    text = _candidate_search_text(candidate)
    query_words = [w for w in normalize_text(intent.text).split() if len(w) > 2]
    overlap = sum(word in text for word in query_words) / max(1, len(query_words))
    score = 48.0 + 34.0 * overlap
    reasons: list[str] = []

    system_requested, complete_system_visible, standalone_gpu_component = _workstation_product_type(
        candidate, intent
    )
    if standalone_gpu_component:
        score -= 90
        reasons.append("standalone graphics card, not a complete PC")
    elif system_requested and complete_system_visible:
        score += 12
        reasons.append("complete PC/workstation visible")
    elif system_requested:
        score -= 18
        reasons.append("complete PC/workstation not verified")

    query_major = _major_tokens(intent.text)
    candidate_major = set(_major_tokens(candidate.title + " " + str(candidate.raw)))
    for token in query_major:
        if token in candidate_major or token in text:
            score += 5
        else:
            # GPU/capacity/size mismatches are much more important than generic word overlap.
            score -= 28
            reasons.append(f"major requested spec not visible: {token}")

    if intent.max_unit_price is not None:
        if candidate.effective_price <= intent.max_unit_price:
            score += 10
            reasons.append("within budget")
        else:
            over = (candidate.effective_price - intent.max_unit_price) / max(intent.max_unit_price, 1)
            score -= min(55, 110 * over)
            reasons.append(f"{over * 100:.0f}% over unit budget")

    if candidate.condition not in intent.allowed_conditions:
        score -= 35
        reasons.append(f"condition {candidate.condition.replace('_', ' ')} not requested")

    for term in intent.excluded_terms:
        normalized = normalize_text(term)
        if normalized and normalized in text:
            score -= 18
            reasons.append(f"contains excluded feature: {term}")

    for term in intent.required_terms:
        normalized = normalize_text(term)
        if normalized and normalized in text:
            score += 4
        else:
            # Missing from a shopping title means unknown, not necessarily absent.
            score -= 5
            reasons.append(f"required feature not verified: {term}")

    return max(0.0, min(100.0, score)), reasons


def score_search_candidate(
    candidate: OfferCandidate,
    intent: SearchIntent,
    *,
    market_reference: float | None = None,
    market_count: int = 0,
    evidence: list[EvidenceItem] | None = None,
) -> dict:
    matched = _matched_evidence(candidate, evidence or [])
    source_count = len({item.source for item in matched})

    quality = candidate.quality_score if candidate.quality_score is not None else 58.0
    quality_conf = candidate.quality_confidence if candidate.quality_confidence is not None else 25.0
    evidence_scores = [item.score for item in matched if item.score is not None]
    if evidence_scores:
        review_quality = statistics.mean(evidence_scores)
        if candidate.quality_score is None:
            quality = review_quality
        else:
            quality = 0.65 * quality + 0.35 * review_quality
        quality_conf = min(95.0, quality_conf + min(30.0, len(evidence_scores) * 10.0))
    if source_count:
        quality_conf = min(95.0, quality_conf + min(28.0, source_count * 7.0))

    reference = market_reference or candidate.reference_price
    deal = score_deal(
        current_price=candidate.effective_price,
        history=[],
        reference_price=reference,
        quality_score=quality,
        quality_confidence=quality_conf,
        trust_score=candidate.trust_score or 50.0,
        extraction_confidence=candidate.extraction_confidence,
        available=candidate.available,
        condition=candidate.condition,
    )
    fit, fit_notes = _fit_score(candidate, intent)
    _system_requested, _complete_system, hard_mismatch = _workstation_product_type(candidate, intent)

    market_discount = None
    if market_reference and market_reference > 0:
        market_discount = (market_reference - candidate.effective_price) / market_reference * 100

    confidence = deal.confidence_signal
    if market_count >= 2:
        confidence = min(100.0, confidence + min(20.0, market_count * 3.0))
    if source_count:
        confidence = min(100.0, confidence + min(15.0, source_count * 3.0))

    # Product quality and fit dominate. A dramatic markdown cannot rescue a poor fit.
    overall = 0.38 * fit + 0.28 * quality + 0.22 * deal.score + 0.12 * confidence
    if fit < 45:
        overall = min(overall, 55)
    if hard_mismatch:
        overall = min(overall, 25)
    if quality < intent.min_quality:
        overall = min(overall, 62)
    if intent.max_unit_price and candidate.effective_price > intent.max_unit_price * 1.25:
        overall = min(overall, 48)

    reasons = []
    if market_discount is not None:
        reasons.append(f"{market_discount:.0f}% vs median of {market_count} same-product offers")
    if candidate.quality_reason:
        reasons.append(candidate.quality_reason)
    if source_count:
        reasons.append(f"{source_count} independent review/community sources matched")
    reasons.extend(fit_notes[:2])

    return {
        "candidate": candidate,
        "deal": deal,
        "fit_score": round(fit, 1),
        "quality_score": round(quality, 1),
        "confidence_score": round(confidence, 1),
        "overall_score": round(max(0.0, min(100.0, overall)), 1),
        "combined_score": round(max(0.0, min(100.0, overall)), 1),
        "market_typical": round(market_reference, 2) if market_reference else None,
        "market_offer_count": market_count,
        "market_discount_pct": round(market_discount, 1) if market_discount is not None else None,
        "evidence": matched,
        "reasons": reasons,
        "hard_mismatch": hard_mismatch,
    }


def rank_search_results(
    candidates: list[OfferCandidate],
    intent: SearchIntent,
    evidence: list[EvidenceItem] | None = None,
) -> list[dict]:
    candidates = deduplicate_candidates(candidates)
    market = _market_references(candidates)
    rows = []
    for candidate in candidates:
        reference, count = market.get(_identity_key(candidate), (None, 0))
        rows.append(
            score_search_candidate(
                candidate,
                intent,
                market_reference=reference,
                market_count=count,
                evidence=evidence,
            )
        )
    rows.sort(
        key=lambda row: (
            row["overall_score"],
            row["fit_score"],
            -row["candidate"].effective_price,
        ),
        reverse=True,
    )
    return rows


async def ollama_rerank_rows(
    rows: list[dict],
    intent: SearchIntent,
    url: str,
    model: str,
    limit: int = 12,
) -> list[dict]:
    top = rows[:limit]
    if not top:
        return rows
    compact = []
    for index, row in enumerate(top):
        candidate = row["candidate"]
        compact.append(
            {
                "index": index,
                "title": candidate.title,
                "price": candidate.effective_price,
                "retailer": candidate.retailer,
                "condition": candidate.condition,
                "base_fit": row["fit_score"],
                "base_quality": row["quality_score"],
                "evidence": [
                    {"source": item.source, "title": item.title, "snippet": item.snippet[:300]}
                    for item in row["evidence"][:4]
                ],
            }
        )
    prompt = f"""Evaluate shopping candidates against the user's request using ONLY the supplied candidate/evidence data.
Return JSON object with key "items", an array of objects:
index(integer), fit(number 0-100), quality(number 0-100), confidence(number 0-100), reason(string <=240 chars), tradeoffs(array <=3 strings).
Do not infer unprovided specs. Unknown requirements should reduce confidence, not be treated as failures.
User request: {intent.text}
Candidates: {json.dumps(compact)}
"""
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json", "think": False}
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post(url.rstrip("/") + "/api/generate", json=payload)
            response.raise_for_status()
            data = json.loads(response.json().get("response", "{}"))
    except Exception:
        return rows

    by_index = {item.get("index"): item for item in data.get("items", []) if isinstance(item, dict)}
    for index, row in enumerate(top):
        item = by_index.get(index)
        if not item:
            continue
        try:
            fit = max(0.0, min(100.0, float(item["fit"])))
            quality = max(0.0, min(100.0, float(item["quality"])))
            confidence = max(0.0, min(100.0, float(item["confidence"])))
        except (KeyError, TypeError, ValueError):
            continue
        # AI can refine fit/quality, but price/deal math stays deterministic.
        row["fit_score"] = round(0.35 * row["fit_score"] + 0.65 * fit, 1)
        if row.get("hard_mismatch"):
            # An LLM must not resurrect a clearly wrong product class.
            row["fit_score"] = min(row["fit_score"], 10.0)
        row["quality_score"] = round(0.45 * row["quality_score"] + 0.55 * quality, 1)
        row["confidence_score"] = round(min(row["confidence_score"], confidence), 1)
        row["overall_score"] = round(
            0.38 * row["fit_score"]
            + 0.28 * row["quality_score"]
            + 0.22 * row["deal"].score
            + 0.12 * row["confidence_score"],
            1,
        )
        if row.get("hard_mismatch"):
            row["overall_score"] = min(row["overall_score"], 25.0)
        row["combined_score"] = row["overall_score"]
        row["ai_reason"] = str(item.get("reason") or "")[:240]
        row["tradeoffs"] = [str(x)[:160] for x in item.get("tradeoffs", [])[:3]]

    rows.sort(key=lambda row: row["overall_score"], reverse=True)
    return rows
