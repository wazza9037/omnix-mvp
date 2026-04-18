"""
App-wide configuration.

All env-configurable knobs live here so the rest of the code reads from a
single typed settings object rather than calling os.getenv scattered around.

Supports dev/staging/prod profiles via OMNIX_ENV.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    v = os.getenv(key)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # ── Environment ──
    env: str = _env("OMNIX_ENV", "development")  # development | staging | production

    # ── HTTP server ──
    host: str = _env("OMNIX_HOST", "0.0.0.0")
    port: int = _env_int("OMNIX_PORT", 8765)

    # ── WebSocket server ──
    ws_enabled: bool = _env_bool("OMNIX_WS_ENABLED", True)
    ws_port: int = _env_int("OMNIX_WS_PORT", 8766)

    # ── Logging ──
    log_level: str = _env("OMNIX_LOG_LEVEL", "INFO")
    log_json: bool = _env_bool("OMNIX_LOG_JSON", False)

    # ── Authentication ──
    jwt_secret: str = _env("OMNIX_JWT_SECRET", "")  # Auto-generated if empty
    jwt_expiry: int = _env_int("OMNIX_JWT_EXPIRY", 86400)  # 24 hours
    jwt_refresh_expiry: int = _env_int("OMNIX_JWT_REFRESH_EXPIRY", 604800)  # 7 days
    guest_mode: bool = _env_bool("OMNIX_GUEST_MODE", True)
    admin_user: str = _env("OMNIX_ADMIN_USER", "admin")
    admin_password: str = _env("OMNIX_ADMIN_PASSWORD", "omnix-admin")
    admin_email: str = _env("OMNIX_ADMIN_EMAIL", "admin@omnix.local")

    # ── Database ──
    db_backend: str = _env("OMNIX_DB_BACKEND", "memory")  # memory | sqlite | postgres
    db_path: str = _env("OMNIX_DB_PATH", "omnix.db")      # SQLite file path
    db_url: str = _env("OMNIX_DB_URL", "")                 # Postgres connection URL

    # ── Security ──
    cors_origins: str = _env("OMNIX_CORS_ORIGINS", "*")
    rate_limit_auth: int = _env_int("OMNIX_RATE_LIMIT_AUTH", 10)  # per minute
    rate_limit_api: int = _env_int("OMNIX_RATE_LIMIT_API", 100)   # per minute
    max_request_size: int = _env_int("OMNIX_MAX_REQUEST_SIZE", 20 * 1024 * 1024)  # 20MB

    # ── Telemetry / polling ──
    telemetry_cache_ms: int = _env_int("OMNIX_TELEMETRY_CACHE_MS", 200)
    workspace_telemetry_window: int = _env_int("OMNIX_TELEMETRY_WINDOW", 120)

    # ── Connectors ──
    connector_tick_seconds: float = _env_float("OMNIX_CONNECTOR_TICK_S", 0.5)
    connector_reconnect_max_backoff: float = _env_float("OMNIX_RECONNECT_MAX_S", 30.0)
    connector_reconnect_initial_backoff: float = _env_float("OMNIX_RECONNECT_INITIAL_S", 1.0)
    connector_heartbeat_timeout: float = _env_float("OMNIX_HEARTBEAT_TIMEOUT_S", 10.0)

    # ── Simulation ──
    simulation_tick_seconds: float = _env_float("OMNIX_SIM_TICK_S", 0.05)
    simulation_max_duration: float = _env_float("OMNIX_SIM_MAX_DURATION_S", 120.0)

    # ── Wikipedia enrichment ──
    wikipedia_timeout: float = _env_float("OMNIX_WIKI_TIMEOUT_S", 4.0)

    # ── Feature flags ──
    use_numpy: bool = _env_bool("OMNIX_USE_NUMPY", True)

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_development(self) -> bool:
        return self.env == "development"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
