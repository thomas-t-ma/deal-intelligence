from dealintel.providers.slickdeals import _pick_price, _query, parse_slickdeals_feed
from dealintel.types import SearchIntent


def test_query_removes_shopping_filler():
    q = _query(SearchIntent(text='Find me two bright 27 inch QHD monitors under $300 total'))
    assert 'QHD' in q
    assert 'monitors' in q
    assert 'Find' not in q


def test_pick_price_prefers_description():
    price, ref = _pick_price('Great Monitor $179 $279', 'Store has this monitor on sale for $169.99 today.')
    assert price == 169.99
    assert ref == 179.0


def test_parse_frontpage_item():
    xml = '''<?xml version="1.0"?>
    <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
      <channel><item>
        <title><![CDATA[ThermoMaven Torch $23.90 $40]]></title>
        <link>https://slickdeals.net/f/123-test</link>
        <description><![CDATA[Culinary Science via Amazon has it on sale for $23.90.]]></description>
        <content:encoded><![CDATA[<div><img src="https://img.example/x.jpg"></div><div>Thumb Score: +222</div><div><a href="https://slickdeals.net/click?x=1" data-product-exitWebsite="amazon.com">Amazon</a></div>]]></content:encoded>
        <guid>thread-123</guid>
      </item></channel>
    </rss>'''
    rows = parse_slickdeals_feed(xml)
    assert len(rows) == 1
    row = rows[0]
    assert row.provider == 'slickdeals'
    assert row.price == 23.90
    assert row.reference_price == 40.0
    assert row.retailer == 'Amazon'
    assert row.raw['thumb_score'] == 222
    assert row.quality_score > 80
    assert row.trust_score >= 85
