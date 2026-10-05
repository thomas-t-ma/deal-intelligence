# Deal Intelligence

**Good products that happen to be cheap — not cheap products.**

Deal Intelligence is a local-first, quality-aware price tracker and deal discovery web app. It is designed around a different question than a normal price-comparison site:

> Is this a genuinely unusual price on something worth buying?

The app tracks real observed prices, calculates effective price (including shipping, membership costs, coupons and cashback), separates condition classes, builds a conservative product identity, and scores deals using price anomaly, product quality, seller trust, evidence confidence and availability.

## What works now

- **Local web app** with a polished dashboard and no cloud account requirement.
- **Product URL tracking** using JSON-LD/schema.org or structured product metadata only.
- **Price history** in SQLite with WAL journaling.
- **Deal Score** with hard guardrails preventing low-quality or low-trust items from becoming “Absurd” deals.
- **Condition-aware history** (`new`, open-box, certified, refurbished, used, etc.).
- **Effective-price accounting** for shipping, memberships, coupons and cashback.
- **Conservative product identity resolution** using GTIN/model/MPN first and fuzzy titles only when identifiers do not conflict.
- **Natural-language shopping requests** with a deterministic parser and optional local Ollama enhancement.
- **Quick Search / Deep Search** with category-aware query expansion, retailer-targeted searches, review/community evidence, and market-aware ranking.
- **Bright Data Google Shopping + Search** as the recommended broad discovery backend for v0.4.
- **Zero-key curated signals** from Slickdeals Frontpage, DealNews Editors’ Choice, and 9to5Toys Steals; these are now secondary signals rather than the primary search universe.
- **SerpApi fallback** for Google Shopping when Bright Data is not configured.
- **Best Buy live search/open-box provider code** behind explicit terms acknowledgement; it is intentionally not the historical-data foundation.
- **Manual listing mode** for retailers that block automated access or do not expose trustworthy structured metadata.
- **Watch thresholds** by price and/or Deal Score.
- **Local alert history** plus optional SMTP email delivery.
- **Background refresh loop** while the service is running, plus `dealintel refresh` for schedulers/cron.
- **Docker / Compose** support.
- **42 automated tests** plus CI startup smoke tests on Python 3.11 and 3.13.

## Fastest setup on Windows

From PowerShell in the project folder:

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

The app opens at `http://127.0.0.1:8765`.

### Manual setup

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
dealintel init
dealintel run
```

On macOS/Linux:

```bash
./scripts/setup.sh
./scripts/run.sh
```

## Docker

```bash
docker compose up -d --build
```

Open `http://127.0.0.1:8765`. The database and local secrets live in the persistent `dealintel-data` volume.

## Zero-key mode

You can use the app without any external API keys:

1. Paste a product page URL into the Dashboard.
2. Deal Intelligence blocks local/private-network targets, fetches the page, and looks first for structured Product/Offer data, then schema microdata and supported mainstream-retailer price markup. `DEALINTEL_RESPECT_ROBOTS=true` can re-enable robots.txt enforcement if desired.
3. The first observation is stored.
4. Future refreshes build a real observed price history.
5. You can enter product-quality evidence and effective-price adjustments.
6. Create a watch for a target price or Deal Score.

If a retailer blocks ordinary HTTP fetching, use **manual listing mode**. The private-use configuration is intentionally pragmatic, but it still does not attempt CAPTCHA solving, credential bypass, or other access-control circumvention.

## Deep Search v0.4

The main search flow is now designed to answer:

> What are the best products for this need, and what is the best way to buy them right now?

**Quick Search** uses a compact plan for known products and simple shopping tasks. **Deep Search** expands the request into multiple shopping, retailer, review, and community queries. Results are ranked using separate **Fit**, **Quality**, **Deal**, and **Confidence** signals.

### Bright Data (recommended)

Add a Bright Data API token in **Settings** to activate the intended v0.4 search engine. The app uses Bright Data's SERP endpoint for both Google Shopping and targeted Google Search queries. The default SERP zone is `serp_api1`, but you can change it in Settings if your account uses another zone.

Do not paste the token into chat; store it directly in the local Settings page.

Without Bright Data (or SerpApi as fallback), search still runs but the UI explicitly marks the result as **limited discovery mode**.

### Curated deal feeds (built in, no key)

The **Ridiculous Deals** page and natural-language search scout three independent human-filtered sources automatically:

- **Slickdeals Frontpage** — community-ranked deals and merchant metadata.
- **DealNews Editors’ Choice** — staff-selected deals from DealNews’ official RSS feed.
- **9to5Toys Steals** — hand-curated standout price drops from the dedicated Steals RSS feed.

These feeds are discovery signals rather than historical truth. Your own tracked price history remains the higher-confidence evidence for deciding whether a current price is genuinely rare.

### SerpApi / Google Shopping

SerpApi remains supported as an optional fallback. When Bright Data is configured, Deal Intelligence does not burn both providers across every expanded query.

### Best Buy

Best Buy publishes a Products API plus a Buying Options/Open Box API. Their developer documentation also places restrictions on API content caching and other uses. For that reason:

- Best Buy is **live discovery only** in this release.
- The integration does not become the app's historical-price database.
- The UI requires you to acknowledge that you reviewed the current Best Buy developer terms before enabling it.

Do not turn this into a public commercial Best Buy comparison service without reviewing the current terms and, if appropriate, getting legal advice / retailer approval.

## Local AI (optional)

If you run Ollama, configure its URL and model in Settings. A small local model can turn requests such as:

> Find two bright 27-inch QHD monitors under $300 total. HDMI required. Gaming performance is irrelevant.

into structured purchasing constraints. If Ollama is unavailable, search falls back automatically to deterministic parsing.

The app does **not** require an LLM to calculate Deal Scores.

## Deal Score design

Deal Score is a weighted geometric score rather than a simple advertised-discount percentage. Signals include:

- **Price anomaly** — robust median history, empirical rarity, and reference-price evidence when history is sparse.
- **Product quality** — review-derived evidence or a user-reviewed override.
- **Seller trust** — conservative domain prior, editable per listing.
- **Evidence confidence** — history depth, extraction quality, and quality confidence.
- **Availability** — unavailable items cannot be high-scoring deals.
- **Condition** — new/open-box/refurbished/used are not mixed as though they are identical.

Hard caps enforce the product principle: a low-quality product, untrusted seller, unavailable listing, or weak evidence cannot receive a top-tier score solely because the price looks dramatic.

### Why the history is conservative

Product identity is the easiest way to poison a price tracker. Two adjacent monitor variants can have nearly identical names but different panels/specs/prices. Deal Intelligence therefore:

1. Links exact GTIN/strong identifiers first.
2. Uses model/MPN plus brand when available.
3. Refuses fuzzy merging when disclosed model/MPN values conflict.
4. Uses fuzzy titles only at a very high threshold and matching brand.

This intentionally prefers duplicate products over incorrectly merged products. False merges are much more damaging than false splits.

## Data & privacy

Default application state lives under:

- Windows: `%USERPROFILE%\.dealintel` (via `~/.dealintel`)
- macOS/Linux: `~/.dealintel`

Files:

- `dealintel.sqlite3` — products, listings, observations, watches, alert events.
- `secrets.json` — optional local provider/SMTP credentials. POSIX mode is set to `0600` when possible.

Environment variables override stored settings for server deployments. See `.env.example`.

The app defaults to `127.0.0.1`, so it is not exposed to your LAN unless you explicitly change the host.

## Security choices

The URL tracker:

- accepts only HTTP(S),
- resolves hostnames and blocks loopback/private/link-local/reserved IPs,
- re-validates redirects,
- can respect robots.txt when `DEALINTEL_RESPECT_ROBOTS=true`,
- limits response size,
- rate-limits requests per host,
- only records structured product prices,
- does not attempt CAPTCHA or anti-bot bypasses.

If you expose the app publicly, add authentication and run it behind a production reverse proxy. The current product is intentionally **local-first**, not a multi-tenant SaaS auth system.

## Commands

```text
dealintel init       Initialize the database
dealintel run        Start the web app and background refresher
dealintel refresh    Refresh currently-due URL listings and evaluate alerts once
```

Useful for Windows Task Scheduler / cron if you do not keep the web process running continuously:

```bash
dealintel refresh
```

## Development

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check dealintel tests
```

GitHub Actions runs tests on Python 3.11 and 3.13.

## Architecture

```text
                 shopping request
                       ↓
                intent + query plan
                       ↓
     ┌─────────────────┼─────────────────┐
     │                 │                 │
 Bright Data       retailer APIs      curated feeds
 Shopping/Search    / direct URLs     (secondary)
     └─────────────────┼─────────────────┘
                       ↓
          offers separated from evidence
                       ↓
          identity + same-product market
                       ↓
       Fit · Quality · Deal · Confidence
                       ↓
               ranked shortlist
                       ↓
            tracking / watches
```

## What is deliberately *not* in v0.4

- CAPTCHA / anti-bot bypassing.
- A brittle home-grown scraper for every retailer; broad discovery is delegated to configured search/scraper providers.
- Automatic checkout/purchasing.
- Affiliate ranking influence (future affiliate links must never alter Deal Score).
- Multi-user SaaS authentication/billing.
- Claims that MSRP/strikethrough pricing is historical truth.
- Automatic fuzzy merging when model identifiers conflict.

Those omissions protect reliability and keep the personal tool cheap to operate. They are not shortcuts in the core scoring/tracking design.

## License

MIT for the application code. Third-party data/API usage remains subject to each provider's current terms.
