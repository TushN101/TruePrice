"""Application configuration loaded from environment variables.

All thresholds, tolerances, secrets, and connection strings are configurable
via environment variables with sensible development defaults.  See
``.env.example`` at the repository root for a template.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _get_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    # ── MongoDB ──────────────────────────────────────────────────────────
    mongo_uri: str
    mongo_db: str

    # ── JWT ──────────────────────────────────────────────────────────────
    jwt_secret: str
    jwt_access_expires: int      # seconds
    jwt_refresh_expires: int     # seconds

    # ── Reputation ───────────────────────────────────────────────────────
    reputation_initial: float
    reputation_min: float
    reputation_max: float
    reputation_reward: float
    reputation_penalty: float
    reputation_strength_factor: float  # how much consensus strength scales updates

    # ── Consensus ────────────────────────────────────────────────────────
    price_tolerance: float           # relative, e.g. 0.02 = 2 %
    trusted_client_threshold: float  # fraction, e.g. 0.6 = 60 %

    # ── Validation triggers ─────────────────────────────────────────────
    validation_random_rate: float    # fraction of hours validated at random (0.3 = 30 %)
    validation_min_observations: int # hours with fewer observations always validate

    # ── History ──────────────────────────────────────────────────────────
    history_retention_days: int
    max_hours_per_request: int       # cap on hours computed in one request

    # ── Flask ────────────────────────────────────────────────────────────
    flask_host: str
    flask_port: int
    flask_debug: bool

    # ── Platform / Validator ─────────────────────────────────────────────
    platform: str                    # "ebay" (only supported value for now)
    ebay_base_url: str
    validator_user_agent: str
    validator_timeout: int

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            mongo_uri=os.getenv("MONGO_URI", "mongodb://localhost:27017"),
            mongo_db=os.getenv("MONGO_DB", "truePriceDb"),

            jwt_secret=os.getenv("JWT_SECRET", "dev-secret-change-in-production"),
            jwt_access_expires=int(os.getenv("JWT_ACCESS_EXPIRES", "3600")),
            jwt_refresh_expires=int(os.getenv("JWT_REFRESH_EXPIRES", "2592000")),

            reputation_initial=float(os.getenv("REPUTATION_INITIAL", "0.5")),
            reputation_min=float(os.getenv("REPUTATION_MIN", "0.1")),
            reputation_max=float(os.getenv("REPUTATION_MAX", "0.9")),
            reputation_reward=float(os.getenv("REPUTATION_REWARD", "0.05")),
            reputation_penalty=float(os.getenv("REPUTATION_PENALTY", "0.05")),
            reputation_strength_factor=float(os.getenv("REPUTATION_STRENGTH_FACTOR", "0.10")),

            price_tolerance=float(os.getenv("PRICE_TOLERANCE", "0.02")),
            trusted_client_threshold=float(os.getenv("TRUSTED_CLIENT_THRESHOLD", "0.6")),

            validation_random_rate=float(os.getenv("VALIDATION_RANDOM_RATE", "0.3")),
            validation_min_observations=int(os.getenv("VALIDATION_MIN_OBSERVATIONS", "3")),

            history_retention_days=int(os.getenv("HISTORY_RETENTION_DAYS", "30")),
            max_hours_per_request=int(os.getenv("MAX_HOURS_PER_REQUEST", "720")),

            flask_host=os.getenv("FLASK_HOST", "0.0.0.0"),
            flask_port=int(os.getenv("FLASK_PORT", "5000")),
            flask_debug=_get_bool("FLASK_DEBUG", "false"),

            platform=os.getenv("PLATFORM", "ebay"),
            ebay_base_url=os.getenv("EBAY_BASE_URL", "https://www.ebay.com"),
            validator_user_agent=os.getenv(
                "VALIDATOR_USER_AGENT",
                "TruePrice-Validator/1.0 (+college project; contact: project-owner)",
            ),
            validator_timeout=int(os.getenv("VALIDATOR_TIMEOUT", "10")),
        )


# Module-level singleton — imported throughout the codebase as ``from config import config``.
config = Config.from_env()
