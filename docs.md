# Technical notes

## Invariants

1. Affiliate economics never influence ranking.
2. Advertised/list price is weaker evidence than observed or cross-merchant market price.
3. Condition classes are never combined into one price baseline.
4. Strong identifier mismatch blocks fuzzy merging.
5. Search/discovery data and persistent historical tracking are separate concepts.
6. Review/search pages are evidence, not automatically purchasable offers.
7. A low-quality or poor-fit product cannot win solely because its advertised discount is large.
8. Missing product specifications reduce confidence rather than being silently invented.
9. LLM output may refine product fit/quality, but deterministic code owns price/deal calculations.

## v0.4 Deep Search pipeline

```text
natural-language need
        ↓
intent extraction
        ↓
Quick / Deep query planner
        ↓
┌──────────────────────────────────────────┐
│ Bright Data Google Shopping             │
│ Bright Data targeted Google Search      │
│ Best Buy API (when configured)          │
│ SerpApi fallback (when configured)      │
│ Slickdeals / DealNews / 9to5Toys signal │
└──────────────────────────────────────────┘
        ↓
offer normalization + evidence separation
        ↓
conservative product identity / dedup
        ↓
same-product live market distribution
        ↓
Fit · Quality · Deal · Confidence
        ↓
optional evidence-grounded Ollama rerank
        ↓
ranked purchasing shortlist
```

### Query modes

**Quick Search** deliberately stays small. It is intended for known products and straightforward category shopping.

**Deep Search** expands the request into category variants, retailer-targeted searches, professional review searches, and community evidence searches. Expanded queries are labeled by purpose so organic review pages are not confused with merchant offers.

### Market price

When two or more new-condition offers can be conservatively resolved to the same product identity, the median effective live price becomes the primary cross-merchant reference. Retailer MSRP/strikethrough prices remain weaker fallback evidence.

### Evidence

Web/review results become `EvidenceItem` records. Evidence is matched to a candidate by explicit model identifiers first and conservative title overlap second. Multiple independent matched sources increase confidence. In the optional Ollama stage, the model sees only the retrieved candidate/evidence packet and is explicitly told not to invent missing specifications.

## Provider roles

- **Bright Data SERP** — primary broad discovery for v0.4. Shopping queries discover offers; ordinary web queries discover retailer pages and evidence.
- **Best Buy** — live structured catalog source when a key is configured.
- **SerpApi** — fallback shopping source when Bright Data is not configured.
- **Curated feeds** — secondary human/community signal only, not the primary search universe.
- **Direct URL tracker** — long-term first-party price observations once a product is worth watching.

## Benchmark

`dealintel benchmark` runs ten representative shopping tasks through the same search engine used by the UI and writes a JSON report to `~/.dealintel/benchmark-v0.4.json`.

The benchmark records:

- whether each task returned a shortlist,
- top-five budget compliance,
- top-five retailer diversity,
- candidate/query counts,
- component scores for the top five,
- provider failures.

It is intentionally not treated as meaningful when no broad search provider is configured.

## Private-use sourcing

- Direct URL tracking uses JSON-LD first, then schema microdata, then pragmatic retailer-specific selectors for major stores.
- robots.txt enforcement is optional and defaults off in the private-use profile.
- SSRF/private-network/redirect protections remain mandatory because those protect the host machine.
- CAPTCHA, credential, or authentication bypass is not implemented in the local app; managed provider-side unblocking can be used through configured search/scraper services.
