from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import CredentialStore, load_config
from .db import get_session, init_db
from .models import AlertEvent, Listing, Product, Watch
from .providers import BestBuyProvider, SerpApiProvider, SlickdealsProvider
from .services.catalog import (
    add_url,
    dashboard_rows,
    product_detail,
    refresh_listing,
    ridiculous_rows,
    update_listing_adjustments,
    upsert_offer,
)
from .services.scheduler import RefreshScheduler
from .services.search import ollama_parse_intent, parse_intent, rank_search_results
from .trust import trust_for_url
from .types import OfferCandidate

BASE = Path(__file__).resolve().parent
config = load_config()
store = CredentialStore(config.secrets_path)
templates = Jinja2Templates(directory=str(BASE / "templates"))


def _csrf(request: Request, token: str) -> None:
    if not secrets.compare_digest(token or "", request.app.state.csrf_token):
        raise HTTPException(status_code=403, detail="Invalid form token")


def _base_context(request: Request) -> dict:
    return {
        "request": request,
        "csrf": request.app.state.csrf_token,
        "app_version": "0.1.0",
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.csrf_token = secrets.token_urlsafe(32)
    scheduler = RefreshScheduler(config, store)
    app.state.scheduler = scheduler
    scheduler.start()
    yield
    await scheduler.stop()


app = FastAPI(
    title="Deal Intelligence",
    version="0.1.0",
    description="Quality-aware deal discovery and price intelligence.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    rows = dashboard_rows(session)
    alerts = session.scalars(select(AlertEvent).order_by(AlertEvent.created_at.desc()).limit(8)).all()
    watches = session.scalar(select(func.count()).select_from(Watch)) or 0
    ctx = _base_context(request) | {
        "rows": rows,
        "alerts": alerts,
        "watches": watches,
        "product_count": len({row["product"].id for row in rows}),
        "listing_count": len(rows),
    }
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@app.get("/ridiculous", response_class=HTMLResponse)
async def ridiculous(request: Request, session: Session = Depends(get_session)):
    tracked = ridiculous_rows(session)
    live_rows = []
    live_error = None
    try:
        candidates = await SlickdealsProvider(config.user_agent).search(parse_intent(""), limit=36)
        live_rows = rank_search_results(candidates, parse_intent(""))[:24]
    except Exception as exc:
        live_error = f"{type(exc).__name__}: {exc}"
    ctx = _base_context(request) | {"rows": tracked, "live_rows": live_rows, "live_error": live_error}
    return templates.TemplateResponse(request, "ridiculous.html", ctx)


@app.post("/track-url")
async def track_url(
    request: Request,
    url: str = Form(...),
    csrf: str = Form(...),
    session: Session = Depends(get_session),
):
    _csrf(request, csrf)
    try:
        listing = await add_url(session, config, url.strip())
        return RedirectResponse(f"/product/{listing.product_id}?added=1", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/?error={quote(str(exc)[:500])}", status_code=303)


@app.post("/manual-add")
def manual_add(
    request: Request,
    title: str = Form(...),
    price: float = Form(...),
    retailer: str = Form("Manual"),
    url: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    condition: str = Form("new"),
    csrf: str = Form(...),
    session: Session = Depends(get_session),
):
    _csrf(request, csrf)
    candidate = OfferCandidate(
        provider="manual",
        provider_item_id=f"manual:{secrets.token_hex(10)}",
        title=title.strip()[:600],
        url=url.strip(),
        retailer=retailer.strip()[:180] or "Manual",
        price=max(0.0, price),
        brand=brand.strip()[:160] or None,
        model=model.strip()[:200] or None,
        condition=condition,
        trust_score=trust_for_url(url) if url.strip() else 55.0,
        extraction_confidence=100.0,
        raw={"source": "manual"},
    )
    listing = upsert_offer(session, candidate, refresh_minutes=config.refresh_minutes)
    listing.next_check_at = None
    session.commit()
    return RedirectResponse(f"/product/{listing.product_id}?added=1", status_code=303)


@app.get("/product/{product_id}", response_class=HTMLResponse)
def product_page(product_id: int, request: Request, session: Session = Depends(get_session)):
    try:
        product, rows, observations = product_detail(session, product_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Product not found") from None
    series = [
        {
            "t": obs.observed_at.isoformat(),
            "p": obs.effective_price,
            "available": obs.available,
        }
        for obs in observations
    ]
    watches = session.scalars(select(Watch).where(Watch.product_id == product_id)).all()
    ctx = _base_context(request) | {
        "product": product,
        "rows": rows,
        "series_json": json.dumps(series),
        "watches": watches,
    }
    return templates.TemplateResponse(request, "product.html", ctx)


@app.post("/listing/{listing_id}/refresh")
async def refresh_one(
    listing_id: int,
    request: Request,
    csrf: str = Form(...),
    session: Session = Depends(get_session),
):
    _csrf(request, csrf)
    listing = session.get(Listing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        await refresh_listing(session, config, listing)
        suffix = "?refreshed=1"
    except Exception as exc:
        suffix = f"?error={quote(str(exc)[:500])}"
    return RedirectResponse(f"/product/{listing.product_id}{suffix}", status_code=303)


@app.post("/listing/{listing_id}/adjust")
def adjust_listing(
    listing_id: int,
    request: Request,
    current_price: float = Form(...),
    shipping_price: float = Form(0.0),
    membership_cost: float = Form(0.0),
    coupon_value: float = Form(0.0),
    cashback_value: float = Form(0.0),
    condition: str = Form("new"),
    trust_score: float = Form(50.0),
    csrf: str = Form(...),
    session: Session = Depends(get_session),
):
    _csrf(request, csrf)
    listing = session.get(Listing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    update_listing_adjustments(
        session, listing, current_price=current_price, shipping_price=shipping_price,
        membership_cost=membership_cost, coupon_value=coupon_value,
        cashback_value=cashback_value, condition=condition, trust_score=trust_score,
    )
    return RedirectResponse(f"/product/{listing.product_id}?adjusted=1", status_code=303)


@app.post("/product/{product_id}/quality")
def set_quality(
    product_id: int,
    request: Request,
    score: float = Form(...),
    reason: str = Form("User-reviewed quality"),
    csrf: str = Form(...),
    session: Session = Depends(get_session),
):
    _csrf(request, csrf)
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.quality_score = max(0.0, min(100.0, score))
    product.quality_confidence = 100.0
    product.quality_reason = reason.strip()[:1000] or "User-reviewed quality"
    session.commit()
    return RedirectResponse(f"/product/{product_id}?quality=1", status_code=303)


@app.post("/product/{product_id}/watch")
def add_watch(
    product_id: int,
    request: Request,
    name: str = Form("Price/deal alert"),
    target_price: str = Form(""),
    min_deal_score: str = Form("80"),
    email: str = Form(""),
    csrf: str = Form(...),
    session: Session = Depends(get_session),
):
    _csrf(request, csrf)
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        target = float(target_price) if target_price.strip() else None
        min_score = float(min_deal_score) if min_deal_score.strip() else None
    except ValueError:
        return RedirectResponse(f"/product/{product_id}?error=Invalid+alert+threshold", status_code=303)
    session.add(
        Watch(
            product_id=product_id,
            name=name.strip()[:240] or "Price/deal alert",
            target_price=target,
            min_deal_score=min_score,
            email=email.strip()[:320] or None,
        )
    )
    session.commit()
    return RedirectResponse(f"/product/{product_id}?watch=1", status_code=303)


@app.post("/watch/{watch_id}/delete")
def delete_watch(
    watch_id: int,
    request: Request,
    csrf: str = Form(...),
    session: Session = Depends(get_session),
):
    _csrf(request, csrf)
    watch = session.get(Watch, watch_id)
    if not watch:
        raise HTTPException(status_code=404, detail="Watch not found")
    product_id = watch.product_id
    session.delete(watch)
    session.commit()
    return RedirectResponse(f"/product/{product_id}", status_code=303)


@app.post("/product/{product_id}/delete")
def delete_product(
    product_id: int,
    request: Request,
    csrf: str = Form(...),
    session: Session = Depends(get_session),
):
    _csrf(request, csrf)
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    session.delete(product)
    session.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    return templates.TemplateResponse(
        request,
        "search.html",
        _base_context(request) | {"rows": None, "query": "", "intent": None, "providers": []},
    )


@app.post("/search", response_class=HTMLResponse)
async def search_products(
    request: Request,
    query: str = Form(...),
    include_bestbuy: str = Form(""),
    csrf: str = Form(...),
):
    _csrf(request, csrf)
    intent = parse_intent(query)
    ollama_url = store.get("ollama_url")
    ollama_model = store.get("ollama_model", "qwen3.5:4b")
    if ollama_url and ollama_model:
        enhanced = await ollama_parse_intent(query, ollama_url, ollama_model)
        if enhanced:
            intent = enhanced

    providers = ["Slickdeals Frontpage"]
    tasks = [SlickdealsProvider(config.user_agent).search(intent, limit=40)]
    serp_key = store.get("serpapi_api_key")
    if serp_key:
        providers.append("Google Shopping via SerpApi")
        location = store.get("search_location", "Atlanta, Georgia, United States") or "Atlanta, Georgia, United States"
        tasks.append(SerpApiProvider(serp_key, location=location).search(intent, limit=30))

    bestbuy_key = store.get("bestbuy_api_key")
    bestbuy_ack = (store.get("bestbuy_terms_ack") or "").lower() in {"1", "true", "yes", "on"}
    if include_bestbuy and bestbuy_key and bestbuy_ack:
        providers.append("Best Buy live API")
        tasks.append(BestBuyProvider(bestbuy_key).search(intent, limit=30))

    candidates = []
    errors = []
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                errors.append(f"{type(result).__name__}: {result}")
            else:
                candidates.extend(result)
    rows = rank_search_results(candidates, intent)
    ctx = _base_context(request) | {
        "rows": rows,
        "query": query,
        "intent": intent,
        "providers": providers,
        "errors": errors,
        "serp_configured": bool(serp_key),
        "bestbuy_configured": bool(bestbuy_key and bestbuy_ack),
    }
    return templates.TemplateResponse(request, "search.html", ctx)


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    keys = [
        "serpapi_api_key", "bestbuy_api_key", "ollama_url", "ollama_model", "search_location",
        "smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_from", "alert_email",
    ]
    values = {key: store.masked(key) if "key" in key or "password" in key else (store.get(key) or "") for key in keys}
    ctx = _base_context(request) | {
        "values": values,
        "bestbuy_terms_ack": (store.get("bestbuy_terms_ack") or "").lower() in {"1", "true", "yes", "on"},
        "home": str(config.home),
        "db_path": str(config.db_path),
    }
    return templates.TemplateResponse(request, "settings.html", ctx)


@app.post("/settings")
async def save_settings(request: Request, csrf: str = Form(...)):
    _csrf(request, csrf)
    form = await request.form()
    updates = {}
    for key in store.ENV_MAP:
        if key == "bestbuy_terms_ack":
            continue
        if key in form:
            updates[key] = form.get(key)
    updates["bestbuy_terms_ack"] = "true" if form.get("bestbuy_terms_ack") else "false"
    store.update(updates)
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/clear/{key}")
def clear_setting(key: str, request: Request, csrf: str = Form(...)):
    _csrf(request, csrf)
    if key not in store.ENV_MAP:
        raise HTTPException(status_code=404, detail="Unknown setting")
    store.clear(key)
    return RedirectResponse("/settings?cleared=1", status_code=303)


@app.post("/scheduler/run")
async def scheduler_run(request: Request, csrf: str = Form(...)):
    _csrf(request, csrf)
    result = await request.app.state.scheduler.run_once()
    return RedirectResponse(f"/?scheduler={result['checked']}&failed={result['failed']}", status_code=303)


@app.get("/api/health")
def health(session: Session = Depends(get_session)):
    session.execute(select(1))
    return {
        "status": "ok",
        "version": "0.2.0",
        "database": str(config.db_path),
        "providers": {
            "url_tracker": True,
            "serpapi": bool(store.get("serpapi_api_key")),
            "bestbuy": bool(store.get("bestbuy_api_key")),
            "slickdeals": True,
            "ollama": bool(store.get("ollama_url")),
        },
    }


@app.get("/api/products")
def products_api(session: Session = Depends(get_session)):
    rows = dashboard_rows(session)
    return [
        {
            "product_id": row["product"].id,
            "title": row["product"].title,
            "listing_id": row["listing"].id,
            "retailer": row["listing"].retailer,
            "effective_price": row["listing"].effective_price,
            "deal_score": row["deal"].score,
            "deal_label": row["deal"].label,
            "available": row["listing"].available,
        }
        for row in rows
    ]
