from __future__ import annotations

from urllib.parse import urlparse

TRUSTED_DOMAINS: dict[str, float] = {
    "bestbuy.com": 94,
    "microcenter.com": 95,
    "bhphotovideo.com": 95,
    "costco.com": 95,
    "apple.com": 96,
    "dell.com": 92,
    "lenovo.com": 92,
    "hp.com": 90,
    "amazon.com": 88,
    "walmart.com": 86,
    "target.com": 90,
    "newegg.com": 84,
    "ebay.com": 74,
    "woot.com": 84,
    "adorama.com": 93,
    "homedepot.com": 91,
    "lowes.com": 91,
}


def registrable_ish(hostname: str) -> str:
    host = hostname.lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    # Good enough for the US-focused first release; avoids another dependency.
    return ".".join(parts[-2:])


def trust_for_url(url: str) -> float:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    root = registrable_ish(host)
    if root in TRUSTED_DOMAINS:
        return TRUSTED_DOMAINS[root]
    score = 52.0
    if parsed.scheme == "https":
        score += 6
    if host and not any(ch.isdigit() for ch in host.split(".")[0]):
        score += 2
    if len(host) > 45 or host.count("-") >= 4:
        score -= 12
    return max(20.0, min(75.0, score))
