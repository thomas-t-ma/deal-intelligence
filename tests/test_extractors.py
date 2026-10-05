import pytest

from dealintel.extractors import extract_product_from_html, parse_money


def test_parse_money():
    assert parse_money("$1,249.99") == 1249.99
    assert parse_money(None) is None


def test_jsonld_product_extraction():
    html = '''<html><head><script type="application/ld+json">{
      "@context":"https://schema.org","@type":"Product","name":"Acme QHD 27",
      "brand":{"@type":"Brand","name":"Acme"},"model":"Q27","gtin13":"1234567890123",
      "image":"https://example.com/a.jpg",
      "aggregateRating":{"ratingValue":"4.7","reviewCount":"400"},
      "offers":{"@type":"Offer","price":"179.99","priceCurrency":"USD","availability":"https://schema.org/InStock","itemCondition":"https://schema.org/NewCondition"}
    }</script></head></html>'''
    c = extract_product_from_html("https://example.com/p/1", html)
    assert c.title == "Acme QHD 27"
    assert c.price == 179.99
    assert c.brand == "Acme"
    assert c.model == "Q27"
    assert c.gtin == "1234567890123"
    assert c.available
    assert c.extraction_confidence >= 90
    assert c.quality_score > 80


def test_meta_fallback():
    html = '''<html><head><title>Fallback Product</title>
    <meta property="product:price:amount" content="99.50">
    <meta property="product:price:currency" content="USD">
    <meta property="og:image" content="https://example.com/x.jpg"></head></html>'''
    c = extract_product_from_html("https://shop.example.com/p", html)
    assert c.price == 99.5
    assert c.raw["source"] == "structured-meta"


def test_unstructured_page_is_rejected():
    html = "<html><body><h1>Product</h1><p>Only $99.99 today!</p></body></html>"
    with pytest.raises(ValueError):
        extract_product_from_html("https://example.com/p", html)


def test_schema_microdata_fallback():
    html = '''<html><body><div itemscope itemtype="https://schema.org/Product">
      <h1 itemprop="name">Acme Widget</h1>
      <span itemprop="brand">Acme</span><span itemprop="model">W100</span>
      <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
        <span itemprop="price">$79.99</span><meta itemprop="priceCurrency" content="USD">
      </div></div></body></html>'''
    c = extract_product_from_html('https://shop.example.com/widget', html)
    assert c.price == 79.99
    assert c.title == 'Acme Widget'
    assert c.raw['source'] == 'schema-microdata'


def test_amazon_style_selector_fallback():
    html = '''<html><body><span id="productTitle">Example Headphones</span>
      <div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">$129.99</span></span></div>
      </body></html>'''
    c = extract_product_from_html('https://www.amazon.com/dp/example', html)
    assert c.price == 129.99
    assert c.title == 'Example Headphones'
    assert c.raw['source'] == 'retailer-selector-fallback'
