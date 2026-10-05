from dealintel.providers.brightdata import parse_shopping_payload, parse_web_payload


def test_parse_brightdata_shopping_payload():
    payload = {
        "shopping_results": [
            {
                "position": 1,
                "title": "Samsung 990 PRO 4TB NVMe SSD",
                "extracted_price": 249.99,
                "extracted_old_price": 319.99,
                "source": "Best Buy",
                "product_link": "https://www.bestbuy.com/site/example",
                "rating": 4.8,
                "reviews": 1234,
                "product_id": "abc",
            }
        ]
    }
    rows = parse_shopping_payload(payload)
    assert len(rows) == 1
    assert rows[0].price == 249.99
    assert rows[0].reference_price == 319.99
    assert rows[0].quality_score > 80
    assert rows[0].retailer == "Best Buy"


def test_parse_brightdata_nested_json_body():
    payload = {"body": '{"shopping_results":[{"title":"SSD","price":"$199.99","source":"Store","link":"https://example.com/x"}]}'}
    rows = parse_shopping_payload(payload)
    assert rows[0].price == 199.99


def test_parse_brightdata_web_evidence():
    payload = {
        "organic": [
            {
                "title": "Review of the product",
                "link": "https://www.rtings.com/example",
                "snippet": "Detailed measurements and testing.",
            },
            {
                "title": "Owner discussion",
                "link": "https://www.reddit.com/r/example/comments/1/x",
                "snippet": "Long-term owner feedback.",
            },
        ]
    }
    evidence = parse_web_payload(payload)
    assert len(evidence) == 2
    assert evidence[0].kind == "review"
    assert evidence[1].kind == "community"
