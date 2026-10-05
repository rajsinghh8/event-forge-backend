"""Event-scoped vendor and vendor-payment API module."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from typing import Any
from uuid import uuid4

from flask import Blueprint, current_app, g, jsonify, request
from psycopg.rows import dict_row

from .errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from .security import require_auth

VENDOR_FIELDS = ("name", "category", "contact_name", "contact_email", "contact_phone", "contract_amount", "contract_status", "contract_url", "notes")
PAYMENT_FIELDS = ("amount", "payment_date", "payment_method", "reference", "notes", "status")
VENDOR_SORTS = {"created_at", "updated_at", "name", "category", "contract_amount", "contract_status"}
PAYMENT_SORTS = {"created_at", "updated_at", "payment_date", "amount", "status"}


def _user_id() -> str:
    value = getattr(g, "user_id", None)
    if value is None:
        # This is defensive; every public handler is decorated below.
        raise AuthenticationError()
    return str(value)


def _money(value: Any, field: str, *, required: bool = False, positive: bool = False) -> Decimal | None:
    if value is None or value == "":
        if required:
            raise ValidationError(f"{field} is required")
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{field} must be a decimal string") from exc
    if not amount.is_finite() or amount < 0 or (positive and amount <= 0):
        raise ValidationError(f"{field} must be {'positive' if positive else 'non-negative'}")
    if amount.as_tuple().exponent < -2:
        raise ValidationError(f"{field} may have at most two decimal places")
    return amount.quantize(Decimal("0.01"))


def _wire(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01")), "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _vendor_projection(row: dict[str, Any]) -> dict[str, Any]:
    result = {key: _wire(value) for key, value in row.items()}
    paid = Decimal(str(row.get("paid_amount") or 0))
    outstanding = Decimal(str(row.get("remaining_amount") if row.get("remaining_amount") is not None else row.get("contract_amount") or 0))
    # Retain the original snake-case fields while exposing the declared projections.
    result["paid_amount"] = result["totalPaid"] = _wire(paid)
    result["remaining_amount"] = result["outstanding"] = _wire(outstanding)
    return result


def _payment_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _wire(value) for key, value in row.items()}


def _payload() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")
    return data


def _pagination(allowed: set[str]) -> tuple[int, int, int, str, str]:
    try:
        page, size = int(request.args.get("page", 1)), int(request.args.get("size", 20))
    except ValueError as exc:
        raise ValidationError("page and size must be integers") from exc
    if page < 1 or not 1 <= size <= 100:
        raise ValidationError("page must be positive and size must be between 1 and 100")
    sort, order = request.args.get("sort", "created_at"), request.args.get("order", "desc").lower()
    if sort not in allowed or order not in {"asc", "desc"}:
        raise ValidationError("Invalid sort or order")
    return page, size, (page - 1) * size, sort, order


class VendorRepository:
    def __init__(self, db: Any):
        self.db = db

    @contextmanager
    def transaction(self):
        if hasattr(self.db, "connection"):
            with self.db.connection() as conn:
                with conn.transaction():
                    yield conn
        else:
            with self.db.transaction() as conn:
                yield conn

    @staticmethod
    def one(conn: Any, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        if hasattr(conn, "fetchone"):
            return conn.fetchone(sql, params)
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    @staticmethod
    def all(conn: Any, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        if hasattr(conn, "fetchall"):
            return conn.fetchall(sql, params)
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def event(self, conn: Any, event_id: str, user_id: str, *, lock: bool = False) -> dict[str, Any]:
        event = self.one(conn, f"SELECT id, owner_id FROM events WHERE id = %s{' FOR UPDATE' if lock else ''}", (event_id,))
        if event is None:
            raise NotFoundError("Event not found")
        if str(event["owner_id"]) != str(user_id):
            raise AuthorizationError("You do not own this event")
        return event

    def vendor(self, conn: Any, event_id: str, vendor_id: str, *, lock: bool = False) -> dict[str, Any]:
        if lock:
            locked = self.one(conn, "SELECT id FROM vendors WHERE id=%s AND event_id=%s FOR UPDATE", (vendor_id, event_id))
            if locked is None:
                raise NotFoundError("Vendor not found")
        row = self.one(conn, """
            SELECT v.*, COALESCE(SUM(vp.amount) FILTER (WHERE vp.status <> 'void'), 0) AS paid_amount,
                   GREATEST(v.contract_amount - COALESCE(SUM(vp.amount) FILTER (WHERE vp.status <> 'void'), 0), 0) AS remaining_amount
            FROM vendors v LEFT JOIN vendor_payments vp ON vp.vendor_id=v.id
            WHERE v.id=%s AND v.event_id=%s GROUP BY v.id
        """, (vendor_id, event_id))
        if row is None:
            raise NotFoundError("Vendor not found")
        return row

    def payment(self, conn: Any, vendor_id: str, payment_id: str, *, lock: bool = False) -> dict[str, Any]:
        row = self.one(conn, f"SELECT * FROM vendor_payments WHERE id=%s AND vendor_id=%s{' FOR UPDATE' if lock else ''}", (payment_id, vendor_id))
        if row is None:
            raise NotFoundError("Vendor payment not found")
        return row

    def audit(self, conn: Any, user_id: str, event_id: str, action: str, resource_id: str, details: dict[str, Any], resource_type: str) -> None:
        self.one(conn, """INSERT INTO audit_logs
            (id,event_id,actor_user_id,resource_type,resource_id,action,details,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,NOW()) RETURNING id""",
            (str(uuid4()), event_id, user_id, resource_type, resource_id, action, json.dumps(details, default=str)))


class VendorService:
    def __init__(self, repository: VendorRepository):
        self.repo = repository

    @staticmethod
    def _fields(data: dict[str, Any], allowed: tuple[str, ...]) -> None:
        unknown = set(data) - set(allowed)
        if unknown:
            raise ValidationError("Unknown field: " + sorted(unknown)[0])

    def create_vendor(self, event_id: str, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self._fields(data, VENDOR_FIELDS)
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValidationError("name is required")
        amount = _money(data.get("contract_amount", "0"), "contract_amount", required=True)
        values = {field: data[field] for field in VENDOR_FIELDS if field in data}
        values.update(name=name, contract_amount=amount, contract_status=values.get("contract_status") or "draft")
        with self.repo.transaction() as conn:
            self.repo.event(conn, event_id, user_id)
            columns = ["id", "event_id", *values, "created_at", "updated_at"]
            placeholders = ", ".join(["%s"] * (len(columns) - 2) + ["NOW()", "NOW()"]) 
            row = self.repo.one(conn, f"INSERT INTO vendors ({', '.join(columns)}) VALUES ({placeholders}) RETURNING *", (str(uuid4()), event_id, *values.values()))
            self.repo.audit(conn, user_id, event_id, "create", row["id"], {"name": name}, "vendor")
            return _vendor_projection({**row, "paid_amount": Decimal("0"), "remaining_amount": amount})

    def update_vendor(self, event_id: str, vendor_id: str, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self._fields(data, VENDOR_FIELDS)
        if not data:
            raise ValidationError("No fields supplied")
        if "name" in data and not str(data["name"]).strip():
            raise ValidationError("name cannot be empty")
        if "contract_amount" in data:
            data = {**data, "contract_amount": _money(data["contract_amount"], "contract_amount", required=True)}
        with self.repo.transaction() as conn:
            self.repo.event(conn, event_id, user_id)
            vendor = self.repo.vendor(conn, event_id, vendor_id, lock=True)
            if "contract_amount" in data and data["contract_amount"] < Decimal(str(vendor["paid_amount"])):
                raise ConflictError("contract_amount cannot be less than payments")
            assignments = ", ".join(f"{field}=%s" for field in data) + ", updated_at=NOW()"
            row = self.repo.one(conn, f"UPDATE vendors SET {assignments} WHERE id=%s RETURNING *", (*data.values(), vendor_id))
            action = "status_change" if "contract_status" in data and data["contract_status"] != vendor["contract_status"] else "update"
            self.repo.audit(conn, user_id, event_id, action, vendor_id, {"fields": sorted(data)}, "vendor")
            return _vendor_projection({**row, "paid_amount": vendor["paid_amount"], "remaining_amount": Decimal(str(row["contract_amount"])) - Decimal(str(vendor["paid_amount"]))})

    def delete_vendor(self, event_id: str, vendor_id: str, user_id: str) -> None:
        with self.repo.transaction() as conn:
            self.repo.event(conn, event_id, user_id)
            self.repo.vendor(conn, event_id, vendor_id, lock=True)
            if self.repo.one(conn, "SELECT id FROM vendor_payments WHERE vendor_id=%s LIMIT 1", (vendor_id,)):
                raise ConflictError("Vendor with payments cannot be deleted")
            self.repo.one(conn, "DELETE FROM vendors WHERE id=%s RETURNING id", (vendor_id,))
            self.repo.audit(conn, user_id, event_id, "delete", vendor_id, {}, "vendor")

    def create_payment(self, event_id: str, vendor_id: str, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self._fields(data, PAYMENT_FIELDS)
        amount = _money(data.get("amount"), "amount", required=True, positive=True)
        values = {field: data[field] for field in PAYMENT_FIELDS if field in data}
        values.update(amount=amount, status=values.get("status") or "paid")
        if not values.get("payment_date"):
            raise ValidationError("payment_date is required")
        with self.repo.transaction() as conn:
            self.repo.event(conn, event_id, user_id)
            vendor = self.repo.vendor(conn, event_id, vendor_id, lock=True)
            if values["status"] != "void" and Decimal(str(vendor["paid_amount"])) + amount > Decimal(str(vendor["contract_amount"])):
                raise ConflictError("Payment exceeds remaining contract amount")
            # ``paid_on`` is retained by the original schema; payment_date is
            # its public/API spelling and both columns must remain consistent.
            columns = ["id", "vendor_id", "paid_on", *values, "created_at", "updated_at"]
            placeholders = ", ".join(["%s"] * (len(columns) - 2) + ["NOW()", "NOW()"]) 
            row = self.repo.one(conn, f"INSERT INTO vendor_payments ({', '.join(columns)}) VALUES ({placeholders}) RETURNING *", (str(uuid4()), vendor_id, values["payment_date"], *values.values()))
            self.repo.audit(conn, user_id, event_id, "create", row["id"], {"vendor_id": vendor_id, "amount": _wire(amount)}, "vendor_payment")
            return _payment_projection(row)

    def update_payment(self, event_id: str, vendor_id: str, payment_id: str, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self._fields(data, PAYMENT_FIELDS)
        if not data:
            raise ValidationError("No fields supplied")
        if "amount" in data:
            data = {**data, "amount": _money(data["amount"], "amount", required=True, positive=True)}
        with self.repo.transaction() as conn:
            self.repo.event(conn, event_id, user_id)
            payment = self.repo.payment(conn, vendor_id, payment_id, lock=True)
            vendor = self.repo.vendor(conn, event_id, vendor_id, lock=True)
            amount, status = data.get("amount", payment["amount"]), data.get("status", payment["status"])
            paid_without_current = Decimal(str(vendor["paid_amount"])) - (Decimal(str(payment["amount"])) if payment["status"] != "void" else Decimal("0"))
            if status != "void" and paid_without_current + Decimal(str(amount)) > Decimal(str(vendor["contract_amount"])):
                raise ConflictError("Payment exceeds remaining contract amount")
            update_values = dict(data)
            if "payment_date" in update_values:
                update_values["paid_on"] = update_values["payment_date"]
            assignments = ", ".join(f"{field}=%s" for field in update_values) + ", updated_at=NOW()"
            row = self.repo.one(conn, f"UPDATE vendor_payments SET {assignments} WHERE id=%s RETURNING *", (*update_values.values(), payment_id))
            action = "status_change" if "status" in data and data["status"] != payment["status"] else "update"
            self.repo.audit(conn, user_id, event_id, action, payment_id, {"fields": sorted(data)}, "vendor_payment")
            return _payment_projection(row)

    def delete_payment(self, event_id: str, vendor_id: str, payment_id: str, user_id: str) -> None:
        with self.repo.transaction() as conn:
            self.repo.event(conn, event_id, user_id)
            self.repo.vendor(conn, event_id, vendor_id, lock=True)
            self.repo.payment(conn, vendor_id, payment_id, lock=True)
            self.repo.one(conn, "DELETE FROM vendor_payments WHERE id=%s RETURNING id", (payment_id,))
            self.repo.audit(conn, user_id, event_id, "delete", payment_id, {}, "vendor_payment")


def create_vendor_blueprint(db: Any) -> Blueprint:
    repo, service = VendorRepository(db), VendorService(VendorRepository(db))
    bp = Blueprint("vendors", __name__)

    @bp.get("/events/<event_id>/vendors")
    @require_auth
    def list_vendors(event_id: str):
        page, size, offset, sort, order = _pagination(VENDOR_SORTS)
        user_id = _user_id()
        clauses, params = ["v.event_id=%s"], [event_id]
        for field in ("category", "contract_status"):
            if request.args.get(field): clauses.append(f"v.{field}=%s"); params.append(request.args[field])
        if request.args.get("q"): clauses.append("v.name ILIKE %s"); params.append("%" + request.args["q"] + "%")
        where = " AND ".join(clauses)
        with repo.transaction() as conn:
            repo.event(conn, event_id, user_id)
            total = repo.one(conn, f"SELECT COUNT(*) total FROM vendors v WHERE {where}", tuple(params))["total"]
            rows = repo.all(conn, f"""SELECT v.*, COALESCE(SUM(vp.amount) FILTER (WHERE vp.status <> 'void'),0) paid_amount,
                GREATEST(v.contract_amount-COALESCE(SUM(vp.amount) FILTER (WHERE vp.status <> 'void'),0),0) remaining_amount
                FROM vendors v LEFT JOIN vendor_payments vp ON vp.vendor_id=v.id WHERE {where}
                GROUP BY v.id ORDER BY v.{sort} {order} LIMIT %s OFFSET %s""", tuple(params + [size, offset]))
        return jsonify({"items": [_vendor_projection(row) for row in rows], "total": total, "page": page, "size": size})

    @bp.post("/events/<event_id>/vendors")
    @require_auth
    def create_vendor(event_id: str): return jsonify(service.create_vendor(event_id, _user_id(), _payload())), 201

    @bp.get("/events/<event_id>/vendors/<vendor_id>")
    @require_auth
    def get_vendor(event_id: str, vendor_id: str):
        with repo.transaction() as conn:
            repo.event(conn, event_id, _user_id())
            return jsonify(_vendor_projection(repo.vendor(conn, event_id, vendor_id)))

    @bp.patch("/events/<event_id>/vendors/<vendor_id>")
    @require_auth
    def update_vendor(event_id: str, vendor_id: str): return jsonify(service.update_vendor(event_id, vendor_id, _user_id(), _payload()))

    @bp.delete("/events/<event_id>/vendors/<vendor_id>")
    @require_auth
    def delete_vendor(event_id: str, vendor_id: str): service.delete_vendor(event_id, vendor_id, _user_id()); return "", 204

    @bp.get("/events/<event_id>/vendors/<vendor_id>/payments")
    @require_auth
    def list_payments(event_id: str, vendor_id: str):
        page, size, offset, sort, order = _pagination(PAYMENT_SORTS)
        with repo.transaction() as conn:
            repo.event(conn, event_id, _user_id()); repo.vendor(conn, event_id, vendor_id)
            params: list[Any] = [vendor_id]; where = "vendor_id=%s"
            if request.args.get("status"): where += " AND status=%s"; params.append(request.args["status"])
            total = repo.one(conn, f"SELECT COUNT(*) total FROM vendor_payments WHERE {where}", tuple(params))["total"]
            rows = repo.all(conn, f"SELECT * FROM vendor_payments WHERE {where} ORDER BY {sort} {order} LIMIT %s OFFSET %s", tuple(params + [size, offset]))
        return jsonify({"items": [_payment_projection(row) for row in rows], "total": total, "page": page, "size": size})

    @bp.post("/events/<event_id>/vendors/<vendor_id>/payments")
    @require_auth
    def create_payment(event_id: str, vendor_id: str): return jsonify(service.create_payment(event_id, vendor_id, _user_id(), _payload())), 201

    @bp.get("/events/<event_id>/vendors/<vendor_id>/payments/<payment_id>")
    @require_auth
    def get_payment(event_id: str, vendor_id: str, payment_id: str):
        with repo.transaction() as conn:
            repo.event(conn, event_id, _user_id()); repo.vendor(conn, event_id, vendor_id)
            return jsonify(_payment_projection(repo.payment(conn, vendor_id, payment_id)))

    @bp.patch("/events/<event_id>/vendors/<vendor_id>/payments/<payment_id>")
    @require_auth
    def update_payment(event_id: str, vendor_id: str, payment_id: str): return jsonify(service.update_payment(event_id, vendor_id, payment_id, _user_id(), _payload()))

    @bp.delete("/events/<event_id>/vendors/<vendor_id>/payments/<payment_id>")
    @require_auth
    def delete_payment(event_id: str, vendor_id: str, payment_id: str): service.delete_payment(event_id, vendor_id, payment_id, _user_id()); return "", 204

    return bp


class _InjectedDatabase:
    def transaction(self):
        db = current_app.extensions.get("db") or current_app.extensions.get("database")
        if db is None: raise RuntimeError("Database has not been injected")
        return db.transaction()


vendor_bp = create_vendor_blueprint(_InjectedDatabase())
