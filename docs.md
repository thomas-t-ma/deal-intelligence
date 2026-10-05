# Technical notes

## Invariants

1. A deal score is independent of affiliate economics.
2. Advertised/list price is weaker evidence than observed historical price.
3. Condition classes are never combined into one price baseline.
4. Strong identifier mismatch blocks fuzzy merging.
5. Search/discovery data and persistent historical tracking are separate concepts.
6. The app never bypasses access controls to obtain a price.
7. A low-quality or untrusted product cannot be promoted as an exceptional deal solely due to price.

## Provider contract

Discovery providers return `OfferCandidate` objects. Persistent refresh is only enabled when a provider has an explicit, compliant refresh strategy. This makes it possible to add affiliate feeds or approved retailer feeds without modifying scoring, history, identity, watches, or UI logic.

## Future production path

If the project becomes a public service, migrate SQLite to PostgreSQL, move scheduled work to a queue/worker, add account authentication, encrypt external-provider credentials, add provider-specific retention rules, and obtain explicit data/affiliate permissions before scaling source ingestion.


## v0.2 private-use sourcing

- Slickdeals Frontpage RSS is enabled as a zero-key discovery source for both natural-language search and the live Ridiculous Deals scout.
- Direct URL tracking uses JSON-LD first, then schema microdata, then conservative retailer-specific selectors for major stores.
- robots.txt enforcement is optional and defaults off in the private-use profile; SSRF/redirect protections remain mandatory.
- CAPTCHA or authentication bypass is intentionally not implemented.
