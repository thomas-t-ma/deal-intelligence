from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Product
from .types import OfferCandidate

NOISE = {
    "new", "sale", "online", "free", "shipping", "with", "and", "the", "for", "inch",
    "in", "black", "white", "silver", "gray", "grey", "bundle", "model",
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(part for part in text.split() if part and part not in NOISE)


def normalize_identifier(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return cleaned or None


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _strong_identifier_match(session: Session, candidate: OfferCandidate) -> Product | None:
    gtin = normalize_identifier(candidate.gtin)
    mpn = normalize_identifier(candidate.mpn)
    model = normalize_identifier(candidate.model)
    clauses = []
    if gtin:
        clauses.append(Product.gtin == gtin)
    if mpn and candidate.brand:
        clauses.append(Product.mpn == mpn)
    if model and candidate.brand:
        clauses.append(Product.model == model)
    if not clauses:
        return None
    products = session.scalars(select(Product).where(or_(*clauses))).all()
    if not products:
        return None
    normalized_brand = normalize_text(candidate.brand)
    for product in products:
        if gtin and product.gtin == gtin:
            return product
        if normalized_brand and normalize_text(product.brand) == normalized_brand:
            return product
    return None


def resolve_product(session: Session, candidate: OfferCandidate) -> Product:
    """Resolve a candidate conservatively.

    Strong identifiers auto-link. Fuzzy title matching only auto-links at a deliberately high
    threshold and with matching brand so similar model variants do not collapse together.
    """
    candidate.gtin = normalize_identifier(candidate.gtin)
    candidate.mpn = normalize_identifier(candidate.mpn)
    candidate.model = normalize_identifier(candidate.model)

    existing = _strong_identifier_match(session, candidate)
    if existing:
        return existing

    normalized_brand = normalize_text(candidate.brand)
    if normalized_brand:
        possible = session.scalars(select(Product).where(Product.brand.is_not(None))).all()
        same_brand = [p for p in possible if normalize_text(p.brand) == normalized_brand]
        safe_candidates = []
        for product in same_brand:
            # A disclosed identifier mismatch is stronger negative evidence than a similar title.
            # This prevents adjacent variants (e.g. 27QN600 vs 27QN650) from sharing history.
            if candidate.model and product.model and normalize_identifier(candidate.model) != normalize_identifier(product.model):
                continue
            if candidate.mpn and product.mpn and normalize_identifier(candidate.mpn) != normalize_identifier(product.mpn):
                continue
            safe_candidates.append(product)
        ranked = sorted(
            ((title_similarity(candidate.title, p.title), p) for p in safe_candidates),
            reverse=True,
            key=lambda x: x[0],
        )
        if ranked and ranked[0][0] >= 0.965:
            return ranked[0][1]

    product = Product(
        title=candidate.title.strip(),
        brand=candidate.brand.strip() if candidate.brand else None,
        model=candidate.model,
        gtin=candidate.gtin,
        mpn=candidate.mpn,
        category=candidate.category,
        image_url=candidate.image_url,
        quality_score=candidate.quality_score if candidate.quality_score is not None else 55.0,
        quality_confidence=(
            candidate.quality_confidence if candidate.quality_confidence is not None else 30.0
        ),
        quality_reason=candidate.quality_reason,
    )
    session.add(product)
    session.flush()
    return product
