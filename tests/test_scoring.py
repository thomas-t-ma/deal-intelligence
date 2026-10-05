from dealintel.scoring import empirical_percentile, robust_typical, score_deal


def test_robust_typical_resists_outliers():
    prices = [250, 249, 251, 248, 252, 9999, 10]
    assert 248 <= robust_typical(prices) <= 252


def test_empirical_percentile_low_price_is_rare():
    assert empirical_percentile(50, [50, 100, 110, 120]) == 25.0


def test_strong_real_deal_scores_high():
    deal = score_deal(
        current_price=170,
        history=[250, 240, 260, 245, 255, 250, 265, 235],
        reference_price=279,
        quality_score=88,
        quality_confidence=85,
        trust_score=95,
        extraction_confidence=95,
        available=True,
        condition="new",
    )
    assert deal.score >= 75
    assert deal.eligible_for_feed
    assert deal.discount_pct > 25


def test_garbage_guardrail_caps_low_quality():
    deal = score_deal(
        current_price=10,
        history=[100, 100, 100, 100, 100],
        reference_price=100,
        quality_score=20,
        quality_confidence=90,
        trust_score=95,
        extraction_confidence=95,
        available=True,
        condition="new",
    )
    assert deal.score <= 58
    assert not deal.eligible_for_feed


def test_low_trust_caps_hype():
    deal = score_deal(
        current_price=100,
        history=[1000] * 8,
        reference_price=1000,
        quality_score=95,
        quality_confidence=95,
        trust_score=20,
        extraction_confidence=95,
        available=True,
        condition="new",
    )
    assert deal.score <= 55


def test_unavailable_is_not_deal():
    deal = score_deal(
        current_price=100,
        history=[200] * 8,
        reference_price=200,
        quality_score=90,
        quality_confidence=90,
        trust_score=90,
        extraction_confidence=90,
        available=False,
        condition="new",
    )
    assert deal.score <= 20
    assert not deal.eligible_for_feed


def test_reference_only_has_limited_confidence():
    deal = score_deal(
        current_price=50,
        history=[],
        reference_price=100,
        quality_score=80,
        quality_confidence=70,
        trust_score=90,
        extraction_confidence=80,
        available=True,
        condition="new",
    )
    assert deal.history_count == 0
    assert deal.confidence_signal < 60
