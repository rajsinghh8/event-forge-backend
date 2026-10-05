from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Settings:
    mysql_host: str; mysql_port: int; mysql_database: str; mysql_user: str; mysql_password: str
    jwt_secret: str; jwt_algorithm: str = "HS256"; jwt_exp_minutes: int = 60
    bcrypt_rounds: int = 12; page_limit: int = 20; port: int = 8000

def load_settings() -> Settings:
    secret = os.getenv("JWT_SECRET", "")
    if not secret: raise RuntimeError("JWT_SECRET is required")
    return Settings(os.getenv("MYSQL_HOST", "localhost"), int(os.getenv("MYSQL_PORT", "3306")),
      os.getenv("MYSQL_DATABASE", "eventforge"), os.getenv("MYSQL_USER", "eventforge"),
      os.getenv("MYSQL_PASSWORD", "eventforge"), secret, port=int(os.getenv("PORT", "8000")))
