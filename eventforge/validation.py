from __future__ import annotations
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from eventforge.errors import ValidationError

def json_body(raw: bytes) -> dict[str, Any]:
    try: value=json.loads(raw.decode() or "{}")
    except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise ValidationError("body must be valid JSON") from exc
    if not isinstance(value,dict): raise ValidationError("body must be a JSON object")
    return value
def require_text(value: Any, name: str) -> str:
    if not isinstance(value,str) or not value.strip(): raise ValidationError(f"{name} is required")
    return value.strip()
def decimal_value(value: Any, name: str) -> Decimal:
    if isinstance(value,float) or not isinstance(value,(str,int,Decimal)): raise ValidationError(f"{name} must be a decimal string")
    try: result=Decimal(str(value))
    except (InvalidOperation,ValueError) as exc: raise ValidationError(f"{name} must be a valid decimal") from exc
    if not result.is_finite(): raise ValidationError(f"{name} must be finite")
    return result.quantize(Decimal("0.01"))
def parse_date(value: Any, name: str) -> date:
    try: return date.fromisoformat(require_text(value,name))
    except ValueError as exc: raise ValidationError(f"{name} must be an ISO date") from exc
def parse_datetime(value: Any, name: str) -> datetime:
    try: return datetime.fromisoformat(require_text(value,name).replace("Z","+00:00"))
    except ValueError as exc: raise ValidationError(f"{name} must be an ISO datetime") from exc
def pagination(arguments: dict[str,list[bytes]], default: int=20) -> tuple[int,int]:
    def val(n:str,d:int)->int:
      raw=arguments.get(n,[str(d).encode()])[0]
      try:return int(raw)
      except ValueError as exc:raise ValidationError(f"{n} must be an integer") from exc
    limit,offset=val("limit",default),val("offset",0)
    if not 1<=limit<=100 or offset<0: raise ValidationError("limit must be 1..100 and offset must be non-negative")
    return limit,offset
def sort_field(value: str|None, allowed: set[str]) -> str:
    if value is None:return next(iter(allowed))
    if value.lstrip("-") not in allowed:raise ValidationError("unsupported sort field")
    return value
