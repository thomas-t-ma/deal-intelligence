# Deal Intelligence

A local price tracker and shopping search tool.

> **Status:** Archived. This repository is no longer under active development.

## Features

- Track product pages and store price history in SQLite.
- Compare effective prices after shipping, coupons, cashback, and membership costs.
- Search with Bright Data, SerpApi, Best Buy, and a few curated deal feeds.
- Rank results using fit, product quality, seller trust, price, and confidence.
- Create price/deal alerts.
- Optionally use a local Ollama model for search parsing and reranking.
- Run locally, with Docker, or from the included setup scripts.

## Run locally

### Windows

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

### macOS / Linux

```bash
./scripts/setup.sh
./scripts/run.sh
```

Open `http://127.0.0.1:8765`.

## Manual setup

```bash
python -m venv .venv
python -m pip install -e .
dealintel init
dealintel run
```

Provider keys and optional SMTP/Ollama settings can be entered in the app's Settings page or supplied through environment variables. See `.env.example`.

## Commands

```text
dealintel init
dealintel run
dealintel refresh
dealintel benchmark
```

## Development

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check dealintel tests
```

## Notes

The app is server-side Python and uses SQLite, scheduled refreshes, and external provider calls. It is not a static-site application.

Tracked data and local secrets are stored under `~/.dealintel` by default.

## License

MIT. Third-party services and data remain subject to their own terms.
