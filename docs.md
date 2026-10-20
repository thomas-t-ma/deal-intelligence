# Technical notes

## Storage

- SQLite database under `~/.dealintel`.
- Local credentials are stored in `secrets.json`.
- Environment variables override saved settings.

## Tracking

- Product pages are read from structured product metadata when possible.
- URL fetching blocks private, loopback, link-local, and reserved addresses.
- Redirect targets are rechecked.
- Product matching prefers GTIN, model, and MPN before fuzzy title matching.
- Different conditions are kept separate when evaluating prices.

## Search

Search can use:

- Bright Data Google Shopping/Search
- SerpApi
- Best Buy
- Slickdeals
- DealNews
- 9to5Toys

Search results are normalized, deduplicated, compared against the request, and ranked. Review/search pages are treated as supporting evidence rather than purchasable offers.

An optional local Ollama model can refine intent and rerank results. Price and deal calculations remain deterministic.

## Alerts

Alerts can trigger from a target effective price or minimum deal score. SMTP delivery is optional.

## Benchmark

`dealintel benchmark` runs the included shopping cases and writes a JSON report to `~/.dealintel/benchmark-v0.4.json`.
