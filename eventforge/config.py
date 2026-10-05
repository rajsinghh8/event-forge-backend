from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60
    scheduler_enabled: bool = True
    @classmethod
    def from_env(cls) -> "Settings":
        database_url = os.getenv("DATABASE_URL")
        secret = os.getenv("JWT_SECRET")
        if not database_url or not secret:
            raise RuntimeError("DATABASE_URL and JWT_SECRET must be configured")
        return cls(database_url, secret, os.getenv("JWT_ALGORITHM", "HS256"), int(os.getenv("JWT_EXPIRY_MINUTES", "60")), os.getenv("SCHEDULER_ENABLED", "true").lower() == "true")
