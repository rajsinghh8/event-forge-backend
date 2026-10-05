from __future__ import annotations
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable
import bcrypt
import jwt
from flask import current_app, g, request
from .errors import AuthenticationError

def hash_password(password: str) -> str: return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
def verify_password(password: str, encoded: str) -> bool: return bcrypt.checkpw(password.encode(), encoded.encode())
def token_for(user_id: str) -> str:
    settings = current_app.extensions['settings']; now = datetime.now(timezone.utc)
    return jwt.encode({'sub': str(user_id), 'iat': now, 'exp': now + timedelta(minutes=settings.jwt_expiry_minutes)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
def require_auth(handler: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(handler)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        value = request.headers.get('Authorization', '')
        if not value.startswith('Bearer '): raise AuthenticationError('Missing or malformed bearer token')
        try:
            claims = jwt.decode(value[7:], current_app.extensions['settings'].jwt_secret, algorithms=[current_app.extensions['settings'].jwt_algorithm])
            g.user_id = claims['sub']
        except (jwt.PyJWTError, KeyError) as exc: raise AuthenticationError('Invalid or expired bearer token') from exc
        return handler(*args, **kwargs)
    return wrapped
