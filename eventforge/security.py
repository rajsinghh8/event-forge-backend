from __future__ import annotations
from datetime import UTC, datetime, timedelta
from typing import Any
import bcrypt, jwt
from eventforge.errors import AuthenticationError
from eventforge.config import Settings

def hash_password(password: str, rounds: int = 12) -> str: return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()
def verify_password(password: str, password_hash: str) -> bool: return bcrypt.checkpw(password.encode(), password_hash.encode())
def issue_token(user_id: int, settings: Settings) -> str:
    now=datetime.now(UTC); return jwt.encode({"sub":str(user_id),"iat":now,"exp":now+timedelta(minutes=settings.jwt_exp_minutes)},settings.jwt_secret,algorithm=settings.jwt_algorithm)
def decode_token(token: str, settings: Settings) -> int:
    try:
        claims=jwt.decode(token,settings.jwt_secret,algorithms=[settings.jwt_algorithm],options={"require":["sub","exp"]}); return int(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc: raise AuthenticationError("invalid or expired bearer token") from exc
def authenticated_user_id(handler: Any) -> int:
    header=handler.request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or len(header.split()) != 2: raise AuthenticationError("bearer token is required")
    return decode_token(header.split()[1], handler.settings)
