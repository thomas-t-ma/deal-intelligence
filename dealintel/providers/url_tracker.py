from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..config import Config
from ..extractors import extract_product_from_html
from ..types import OfferCandidate


class UnsafeUrlError(ValueError):
    pass


class RobotsDeniedError(ValueError):
    pass


class UrlTrackerProvider:
    name = "url"
    _last_request: dict[str, float] = {}
    _lock = asyncio.Lock()

    def __init__(self, config: Config):
        self.config = config

    @staticmethod
    def _validate_sync(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise UnsafeUrlError("Only http:// and https:// product URLs are allowed.")
        if not parsed.hostname:
            raise UnsafeUrlError("URL has no hostname.")
        host = parsed.hostname.lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise UnsafeUrlError("Local/private hosts are blocked.")
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror as exc:
            raise UnsafeUrlError(f"Could not resolve hostname: {host}") from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                raise UnsafeUrlError("Private, loopback, link-local, or reserved addresses are blocked.")

    async def validate_url(self, url: str) -> None:
        await asyncio.to_thread(self._validate_sync, url)

    async def _rate_limit(self, host: str) -> None:
        async with self._lock:
            now = time.monotonic()
            last = self._last_request.get(host, 0.0)
            delay = 1.25 - (now - last)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request[host] = time.monotonic()

    async def _robots_allows(self, client: httpx.AsyncClient, url: str) -> bool:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        await self.validate_url(robots_url)
        try:
            response = await client.get(robots_url, headers={"User-Agent": self.config.user_agent})
        except httpx.HTTPError:
            return True
        if response.status_code >= 400:
            return True
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser.can_fetch(self.config.user_agent, url)

    async def _get(self, url: str) -> tuple[str, str]:
        await self.validate_url(url)
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.8",
        }
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            current = url
            for _ in range(6):
                await self.validate_url(current)
                parsed = urlparse(current)
                await self._rate_limit(parsed.hostname or "")
                if self.config.respect_robots and not await self._robots_allows(client, current):
                    raise RobotsDeniedError("The site robots.txt does not allow this tracker to fetch the page.")
                response = await client.get(current, headers=headers)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect response had no Location header.")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    raise ValueError(f"Expected HTML but received {content_type or 'unknown content type'}.")
                declared = response.headers.get("content-length")
                if declared and int(declared) > self.config.max_response_bytes:
                    raise ValueError("Product page is larger than the configured safety limit.")
                body = response.content
                if len(body) > self.config.max_response_bytes:
                    raise ValueError("Product page is larger than the configured safety limit.")
                return str(response.url), response.text
            raise ValueError("Too many redirects.")

    async def fetch(self, url: str) -> OfferCandidate:
        final_url, html = await self._get(url)
        return extract_product_from_html(final_url, html)
