from dealintel.trust import trust_for_url


def test_known_retailer_high_trust():
    assert trust_for_url("https://www.bestbuy.com/site/x") > 90


def test_unknown_https_is_moderate():
    score = trust_for_url("https://example-shop.com/product")
    assert 45 <= score <= 75


def test_suspicious_hostname_penalty():
    a = trust_for_url("https://shop.example.com/x")
    b = trust_for_url("https://super-cheap-free-5090-deals.example/x")
    assert b < a
