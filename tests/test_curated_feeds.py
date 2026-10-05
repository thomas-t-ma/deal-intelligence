from dealintel.providers.curated_feeds import (
    DEALNEWS_EDITORS,
    NINE_TO_FIVE_STEALS,
    parse_curated_feed,
)
from dealintel.services.search import parse_intent


def test_dealnews_feed_uses_first_price_and_reference():
    xml = """<?xml version='1.0'?><rss><channel><item>
    <title>LG 27-inch QHD IPS Monitor</title>
    <link>https://www.dealnews.com/deal/monitor</link>
    <guid>dn-1</guid>
    <description><![CDATA[Walmart has this monitor for $149.99 $249.99 with free shipping.
      <a href="https://www.walmart.com/ip/123">Buy Now</a>]]></description>
    </item></channel></rss>"""
    rows = parse_curated_feed(xml, DEALNEWS_EDITORS, parse_intent("27 inch monitor"))
    assert len(rows) == 1
    assert rows[0].price == 149.99
    assert rows[0].reference_price == 249.99
    assert rows[0].raw["source_label"] == "DealNews Editors' Choice"


def test_9to5_does_not_treat_amount_off_as_price():
    xml = """<?xml version='1.0'?><rss><channel><item>
    <title>Apple Watch Ultra clearance at nearly $200 off</title>
    <link>https://9to5toys.com/2026/10/05/watch-deal/</link>
    <guid>9to5-1</guid>
    <description><![CDATA[The watch is now down to $599 shipped from $799.
      <a href="https://www.amazon.com/dp/example">Amazon</a>]]></description>
    </item></channel></rss>"""
    rows = parse_curated_feed(xml, NINE_TO_FIVE_STEALS, parse_intent("Apple Watch"))
    assert len(rows) == 1
    assert rows[0].price == 599.0
    assert rows[0].reference_price == 799.0


def test_curated_feed_filters_irrelevant_query():
    xml = """<?xml version='1.0'?><rss><channel><item>
    <title>Kitchen mixer for $99</title>
    <link>https://www.dealnews.com/deal/mixer</link>
    <description>Kitchen appliance sale for $99</description>
    </item></channel></rss>"""
    rows = parse_curated_feed(xml, DEALNEWS_EDITORS, parse_intent("RTX 5090 desktop"))
    assert rows == []
