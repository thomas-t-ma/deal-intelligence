from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dealintel.db import Base
from dealintel.identity import (
    normalize_identifier,
    normalize_text,
    resolve_product,
    title_similarity,
)
from dealintel.types import OfferCandidate


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def candidate(**kw):
    base = dict(
        provider="test", provider_item_id="1", title="LG 27QN600-B 27 inch QHD IPS Monitor",
        url="https://example.com", retailer="Example", price=179.0, brand="LG", model="27QN600-B",
    )
    base.update(kw)
    return OfferCandidate(**base)


def test_normalization():
    assert normalize_identifier("27qn600-b") == "27QN600B"
    assert "black" not in normalize_text("LG monitor black")


def test_title_similarity():
    assert title_similarity("LG 27QN600-B QHD Monitor", "LG 27QN600 QHD monitor") > 0.8


def test_exact_gtin_links():
    s = session()
    p1 = resolve_product(s, candidate(gtin="0123456789012"))
    s.commit()
    p2 = resolve_product(s, candidate(provider_item_id="2", title="Different retailer title", gtin="0123456789012"))
    assert p1.id == p2.id


def test_close_variant_does_not_merge_by_model():
    s = session()
    p1 = resolve_product(s, candidate(model="27QN600-B"))
    s.commit()
    p2 = resolve_product(s, candidate(provider_item_id="2", model="27QN650-B", title="LG 27QN650-B 27 inch QHD IPS Monitor"))
    s.commit()
    assert p1.id != p2.id


def test_identical_title_brand_can_merge_conservatively():
    s = session()
    p1 = resolve_product(s, candidate(model=None))
    s.commit()
    p2 = resolve_product(s, candidate(provider_item_id="2", model=None, title="LG 27QN600-B 27 inch QHD IPS Monitor"))
    assert p1.id == p2.id
