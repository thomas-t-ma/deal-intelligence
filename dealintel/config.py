from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    home: Path
    host: str
    port: int
    refresh_minutes: int
    respect_robots: bool
    request_timeout_seconds: float
    max_response_bytes: int
    user_agent: str

    @property
    def db_path(self) -> Path:
        return self.home / "dealintel.sqlite3"

    @property
    def secrets_path(self) -> Path:
        return self.home / "secrets.json"


def load_config() -> Config:
    home = Path(os.getenv("DEALINTEL_HOME", "~/.dealintel")).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    return Config(
        home=home,
        host=os.getenv("DEALINTEL_HOST", "127.0.0.1"),
        port=int(os.getenv("DEALINTEL_PORT", "8765")),
        refresh_minutes=max(15, int(os.getenv("DEALINTEL_REFRESH_MINUTES", "180"))),
        respect_robots=_env_bool("DEALINTEL_RESPECT_ROBOTS", False),
        request_timeout_seconds=float(os.getenv("DEALINTEL_REQUEST_TIMEOUT", "15")),
        max_response_bytes=int(os.getenv("DEALINTEL_MAX_RESPONSE_BYTES", str(5 * 1024 * 1024))),
        user_agent=os.getenv(
            "DEALINTEL_USER_AGENT",
            "Mozilla/5.0 (compatible; DealIntelligence/0.2; personal price tracker)",
        ),
    )


class CredentialStore:
    """Tiny local secret store.

    This deliberately avoids a cloud secret dependency. On POSIX systems the file is
    chmod 0600. Environment variables override stored values for deployment use.
    """

    ENV_MAP = {
        "serpapi_api_key": "DEALINTEL_SERPAPI_API_KEY",
        "bestbuy_api_key": "DEALINTEL_BESTBUY_API_KEY",
        "bestbuy_terms_ack": "DEALINTEL_BESTBUY_TERMS_ACK",
        "search_location": "DEALINTEL_SEARCH_LOCATION",
        "ollama_url": "DEALINTEL_OLLAMA_URL",
        "ollama_model": "DEALINTEL_OLLAMA_MODEL",
        "smtp_host": "DEALINTEL_SMTP_HOST",
        "smtp_port": "DEALINTEL_SMTP_PORT",
        "smtp_username": "DEALINTEL_SMTP_USERNAME",
        "smtp_password": "DEALINTEL_SMTP_PASSWORD",
        "smtp_from": "DEALINTEL_SMTP_FROM",
        "alert_email": "DEALINTEL_ALERT_EMAIL",
    }

    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return {str(k): str(v) for k, v in data.items() if v not in (None, "")}

    def get(self, key: str, default: str | None = None) -> str | None:
        env_name = self.ENV_MAP.get(key)
        if env_name and os.getenv(env_name):
            return os.getenv(env_name)
        return self._read().get(key, default)

    def masked(self, key: str) -> str:
        value = self.get(key)
        if not value:
            return ""
        if len(value) <= 8:
            return "•" * len(value)
        return f"{value[:4]}…{value[-4:]}"

    def update(self, values: dict[str, Any]) -> None:
        data = self._read()
        for key, value in values.items():
            if key not in self.ENV_MAP:
                continue
            if value is None:
                continue
            value = str(value).strip()
            if not value or "•" in value or "…" in value:
                continue
            data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def clear(self, key: str) -> None:
        data = self._read()
        data.pop(key, None)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
