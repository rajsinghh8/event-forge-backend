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

def optional_text(value: Any, name: str) -> str | None:
    if value is None: return None
    return require_text(value, name)

def decimal_value(value: Any, name: str) -> Decimal:
    if isinstance(value,bool) or isinstance(value,float) or not isinstance(value,(str,int,Decimal)): raise ValidationError(f"{name} must be a decimal string")
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

def _arg(arguments: dict[str,list[bytes]], name: str) -> str | None:
    raw=arguments.get(name)
    if not raw: return None
    try: return raw[0].decode("utf-8")
    except UnicodeDecodeError as exc: raise ValidationError(f"{name} must be text") from exc

def pagination(arguments: dict[str,list[bytes]], default: int=20) -> tuple[int,int]:
    """Accept page/size while retaining the limit/offset compatibility contract."""
    def integer(name: str, default_value: int) -> int:
        raw=_arg(arguments,name)
        if raw is None:return default_value
        try:
            # int('1.0') is intentionally rejected.
            if not raw or raw.strip()!=raw:return (_ for _ in ()).throw(ValueError())
            return int(raw)
        except ValueError as exc: raise ValidationError(f"{name} must be an integer") from exc
    size=integer("size", integer("limit",default)); page_raw=_arg(arguments,"page")
    if page_raw is not None:
        page=integer("page",1)
        if page < 1: raise ValidationError("page must be positive")
        offset=(page-1)*size
    else: offset=integer("offset",0)
    if not 1<=size<=100 or offset<0: raise ValidationError("size/limit must be 1..100 and offset must be non-negative")
    return size,offset

def sort_field(value: str|None, allowed: set[str], default: str | None=None) -> str:
    if value is None:return default or sorted(allowed)[0]
    if not isinstance(value,str) or value.lstrip("-") not in allowed:raise ValidationError("unsupported sort field")
    return value

def query_options(arguments: dict[str,list[bytes]], *, allowed_sort: set[str], allowed_filters: set[str], default_sort: str) -> dict[str, Any]:
    result: dict[str, Any]={"sort":sort_field(_arg(arguments,"sort"),allowed_sort,default_sort)}
    for key in allowed_filters:
        value=_arg(arguments,key)
        if value is None: continue
        if key in {"startDate","endDate"}: result[key]=parse_date(value,key).isoformat()
        else: result[key]=require_text(value,key)
    if "startDate" in result and "endDate" in result and result["startDate"] > result["endDate"]:
        raise ValidationError("startDate must not be after endDate")
    return result
