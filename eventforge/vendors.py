"""Vendor and vendor-payment resource module.

The module deliberately uses psycopg SQL (rather than an ORM).  It is mounted by
calling :func:`create_vendor_blueprint` with the application's injected database.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from flask import Blueprint, g, jsonify, request
from psycopg.rows import dict_row


VENDOR_FIELDS = (
    "name", "category", "contact_name", "contact_email", "contact_phone",
    "contract_amount", "contract_status", "contract_url", "notes",
)
PAYMENT_FIELDS = ("amount", "payment_date", "payment_method", "reference", "notes", "status")
VENDOR_SORTS = {"created_at", "updated_at", "name", "category", "contract_amount", "contract_status"}
PAYMENT_SORTS = {"created_at", "updated_at", "payment_date", "amount", "status"}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status


def _user_id() -> str:
    value = getattr(g, "user_id", None)
    if not value:
        raise ApiError("Authentication required", 401)
    return str(value)


def _money(value: Any, field: str = "amount", *, required: bool = False) -> Decimal | None:
    if value is None or value == "":
        if required:
            raise ApiError(f"{field} is required")
        return None
    # Decimal(str(...)) avoids accidental binary-float rounding.
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ApiError(f"{field} must be a decimal string") from None
    if not amount.is_finite() or amount < 0:
        raise ApiError(f"{field} must be a non-negative decimal")
    if amount.as_tuple().exponent < -2:
        raise ApiError(f"{field} may have at most two decimal places")
    return amount.quantize(Decimal("0.01"))


def _decimal_string(value: Any) -> str | None:
    if value is None:
        return None
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01")), "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _vendor_projection(row: dict[str, Any]) -> dict[str, Any]:
    result = {key: _json_value(value) for key, value in row.items()}
    # Keep the API useful even where no payment has been made.
    result["paid_amount"] = _decimal_string(row.get("paid_amount") or 0)
    result["remaining_amount"] = _decimal_string(row.get("remaining_amount") or row.get("contract_amount") or 0)
    return result


def _payment_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in row.items()}


def _payload() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object")
    return data


def _pagination(allowed: set[str]) -> tuple[int, int, int, str, str]:
    try:
        page = int(request.args.get("page", 1))
        size = int(request.args.get("size", 20))
    except ValueError:
        raise ApiError("page and size must be integers") from None
    if page < 1 or size < 1 or size > 100:
        raise ApiError("page must be positive and size must be between 1 and 100")
    sort = request.args.get("sort", "created_at")
    direction = request.args.get("order", "desc").lower()
    if sort not in allowed or direction not in {"asc", "desc"}:
        raise ApiError("Invalid sort or order")
    return page, size, (page - 1) * size, sort, direction


class VendorRepository:
    """SQL repository.  ``db`` may be a psycopg connection or a DB wrapper.

    The project DB wrapper exposes ``connection()``; accepting a bare connection
    also makes the repository straightforward to integration-test.
    """
    def __init__(self, db: Any):
        self.db = db

    @contextmanager
    def transaction(self):
        if hasattr(self.db, "connection"):
            with self.db.connection() as conn:
                with conn.transaction():
                    yield conn
        else:
            with self.db.transaction():
                yield self.db

    @staticmethod
    def one(conn: Any, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        # The shared Database exposes fetchone/fetchall; support a bare psycopg
        # connection too for direct repository tests.
        if hasattr(conn, "fetchone"):
            return conn.fetchone(sql, params)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    @staticmethod
    def all(conn: Any, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        if hasattr(conn, "fetchall"):
            return conn.fetchall(sql, params)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def owned_event(self, conn: Any, event_id: str, user_id: str, *, lock: bool = False) -> dict[str, Any]:
        suffix = " FOR UPDATE" if lock else ""
        event = self.one(conn, f"SELECT id FROM events WHERE id = %s AND owner_id = %s{suffix}", (event_id, user_id))
        if not event:
            raise ApiError("Event not found", 404)
        return event

    def vendor(self, conn: Any, vendor_id: str, user_id: str, *, lock: bool = False) -> dict[str, Any]:
        # PostgreSQL cannot apply FOR UPDATE to a grouped aggregate. Lock the
        # vendor row first, then calculate its payment projection while held.
        if lock:
            locked = self.one(conn, """
                SELECT v.id FROM vendors v JOIN events e ON e.id = v.event_id
                WHERE v.id = %s AND e.owner_id = %s FOR UPDATE OF v
            """, (vendor_id, user_id))
            if not locked:
                raise ApiError("Vendor not found", 404)
        row = self.one(conn, """
            SELECT v.*, COALESCE(SUM(vp.amount) FILTER (WHERE vp.status <> 'void'), 0) AS paid_amount,
                   GREATEST(v.contract_amount - COALESCE(SUM(vp.amount) FILTER (WHERE vp.status <> 'void'), 0), 0) AS remaining_amount
              FROM vendors v JOIN events e ON e.id = v.event_id
              LEFT JOIN vendor_payments vp ON vp.vendor_id = v.id
             WHERE v.id = %s AND e.owner_id = %s
             GROUP BY v.id
        """, (vendor_id, user_id))
        if not row:
            raise ApiError("Vendor not found", 404)
        return row

    def audit(self, conn: Any, user_id: str, event_id: str, action: str, entity_id: str, details: dict[str, Any] | None = None, resource_type: str = "vendor") -> None:
        # jsonb accepts a JSON text parameter without relying on a global adapter.
        import json
        self.one(conn, """
            INSERT INTO audit_logs (id, event_id, actor_user_id, resource_type, resource_id, action, details, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, NOW()) RETURNING id
        """, (str(uuid4()), event_id, user_id, resource_type, entity_id, action, json.dumps(details or {}, default=str)))


class VendorService:
    def __init__(self, repository: VendorRepository):
        self.repo = repository

    def create_vendor(self, event_id: str, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        name = str(data.get("name", "")).strip()
        if not name:
            raise ApiError("name is required")
        amount = _money(data.get("contract_amount", "0"), "contract_amount", required=True)
        values = {field: data.get(field) for field in VENDOR_FIELDS if field in data}
        values.update(name=name, contract_amount=amount, contract_status=values.get("contract_status") or "draft")
        unknown = set(data) - set(VENDOR_FIELDS)
        if unknown:
            raise ApiError("Unknown field: " + sorted(unknown)[0])
        with self.repo.transaction() as conn:
            self.repo.owned_event(conn, event_id, user_id)
            columns = ["id", "event_id", *values.keys(), "created_at", "updated_at"]
            placeholders = ", ".join(["%s"] * (len(columns) - 2) + ["NOW()", "NOW()"])
            row = self.repo.one(conn, f"INSERT INTO vendors ({', '.join(columns)}) VALUES ({placeholders}) RETURNING *",
                                (str(uuid4()), event_id, *values.values()))
            self.repo.audit(conn, user_id, event_id, "vendor.created", row["id"], {"name": name})
            return _vendor_projection({**row, "paid_amount": Decimal("0"), "remaining_amount": amount})

    def update_vendor(self, vendor_id: str, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        unknown = set(data) - set(VENDOR_FIELDS)
        if unknown or not data:
            raise ApiError("Unknown field" if unknown else "No fields supplied")
        if "name" in data and not str(data["name"]).strip():
            raise ApiError("name cannot be empty")
        if "contract_amount" in data:
            data = {**data, "contract_amount": _money(data["contract_amount"], "contract_amount", required=True)}
        with self.repo.transaction() as conn:
            vendor = self.repo.vendor(conn, vendor_id, user_id, lock=True)
            if "contract_amount" in data and data["contract_amount"] < Decimal(str(vendor["paid_amount"])):
                raise ApiError("contract_amount cannot be less than payments", 409)
            assignments = ", ".join(f"{field} = %s" for field in data) + ", updated_at = NOW()"
            row = self.repo.one(conn, f"UPDATE vendors SET {assignments} WHERE id = %s RETURNING *", (*data.values(), vendor_id))
            self.repo.audit(conn, user_id, row["event_id"], "vendor.updated", vendor_id, {"fields": sorted(data)})
            return _vendor_projection({**row, "paid_amount": vendor["paid_amount"], "remaining_amount": Decimal(str(row["contract_amount"])) - Decimal(str(vendor["paid_amount"]))})

    def delete_vendor(self, vendor_id: str, user_id: str) -> None:
        with self.repo.transaction() as conn:
            vendor = self.repo.vendor(conn, vendor_id, user_id, lock=True)
            payment = self.repo.one(conn, "SELECT id FROM vendor_payments WHERE vendor_id = %s LIMIT 1", (vendor_id,))
            if payment:
                raise ApiError("Vendor with payments cannot be deleted", 409)
            self.repo.one(conn, "DELETE FROM vendors WHERE id = %s RETURNING id", (vendor_id,))
            self.repo.audit(conn, user_id, vendor["event_id"], "vendor.deleted", vendor_id)

    def create_payment(self, vendor_id: str, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        unknown = set(data) - set(PAYMENT_FIELDS)
        if unknown:
            raise ApiError("Unknown field: " + sorted(unknown)[0])
        amount = _money(data.get("amount"), "amount", required=True)
        values = {field: data.get(field) for field in PAYMENT_FIELDS if field in data}
        values.update(amount=amount, status=values.get("status") or "paid")
        with self.repo.transaction() as conn:
            # Locks vendor and payment aggregation while the cap is checked.
            vendor = self.repo.vendor(conn, vendor_id, user_id, lock=True)
            paid = Decimal(str(vendor["paid_amount"]))
            if values["status"] != "void" and paid + amount > Decimal(str(vendor["contract_amount"])):
                raise ApiError("Payment exceeds remaining contract amount", 409)
            columns = ["id", "vendor_id", *values.keys(), "created_at", "updated_at"]
            placeholders = ", ".join(["%s"] * (len(columns) - 2) + ["NOW()", "NOW()"])
            row = self.repo.one(conn, f"INSERT INTO vendor_payments ({', '.join(columns)}) VALUES ({placeholders}) RETURNING *",
                                (str(uuid4()), vendor_id, *values.values()))
            self.repo.audit(conn, user_id, vendor["event_id"], "vendor_payment.created", row["id"], {"vendor_id": vendor_id, "amount": _decimal_string(amount)}, "vendor_payment")
            return _payment_projection(row)

    def update_payment(self, payment_id: str, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        unknown = set(data) - set(PAYMENT_FIELDS)
        if unknown or not data:
            raise ApiError("Unknown field" if unknown else "No fields supplied")
        if "amount" in data:
            data = {**data, "amount": _money(data["amount"], "amount", required=True)}
        with self.repo.transaction() as conn:
            payment = self.repo.one(conn, """
                SELECT vp.*, v.event_id FROM vendor_payments vp JOIN vendors v ON v.id = vp.vendor_id
                JOIN events e ON e.id = v.event_id WHERE vp.id = %s AND e.owner_id = %s FOR UPDATE OF vp
            """, (payment_id, user_id))
            if not payment:
                raise ApiError("Vendor payment not found", 404)
            vendor = self.repo.vendor(conn, payment["vendor_id"], user_id, lock=True)
            effective_amount = data.get("amount", payment["amount"])
            effective_status = data.get("status", payment["status"])
            paid_excluding = Decimal(str(vendor["paid_amount"])) - (Decimal(str(payment["amount"])) if payment["status"] != "void" else Decimal("0"))
            if effective_status != "void" and paid_excluding + Decimal(str(effective_amount)) > Decimal(str(vendor["contract_amount"])):
                raise ApiError("Payment exceeds remaining contract amount", 409)
            assignments = ", ".join(f"{field} = %s" for field in data) + ", updated_at = NOW()"
            row = self.repo.one(conn, f"UPDATE vendor_payments SET {assignments} WHERE id = %s RETURNING *", (*data.values(), payment_id))
            self.repo.audit(conn, user_id, payment["event_id"], "vendor_payment.updated", payment_id, {"fields": sorted(data)}, "vendor_payment")
            return _payment_projection(row)

    def delete_payment(self, payment_id: str, user_id: str) -> None:
        with self.repo.transaction() as conn:
            payment = self.repo.one(conn, """
                SELECT vp.*, v.event_id FROM vendor_payments vp JOIN vendors v ON v.id = vp.vendor_id
                JOIN events e ON e.id = v.event_id WHERE vp.id = %s AND e.owner_id = %s FOR UPDATE OF vp
            """, (payment_id, user_id))
            if not payment:
                raise ApiError("Vendor payment not found", 404)
            self.repo.vendor(conn, payment["vendor_id"], user_id, lock=True)
            self.repo.one(conn, "DELETE FROM vendor_payments WHERE id = %s RETURNING id", (payment_id,))
            self.repo.audit(conn, user_id, payment["event_id"], "vendor_payment.deleted", payment_id, resource_type="vendor_payment")


class _InjectedDatabase:
    """Late-bound adapter used by the conventional module-level blueprint."""
    def _db(self) -> Any:
        from flask import current_app
        db = current_app.extensions.get("db") or current_app.extensions.get("database")
        if db is None:
            raise RuntimeError("Database has not been injected")
        return db

    def transaction(self):
        return self._db().transaction()

    def fetchone(self, sql: str, params: tuple = ()):
        return self._db().fetchone(sql, params)

    def fetchall(self, sql: str, params: tuple = ()):
        return self._db().fetchall(sql, params)


def create_vendor_blueprint(db: Any) -> Blueprint:
    repo, service = VendorRepository(db), VendorService(VendorRepository(db))
    bp = Blueprint("vendors", __name__)

    @bp.errorhandler(ApiError)
    def _api_error(error: ApiError):
        return jsonify({"error": error.message}), error.status

    def vendor_or_404(vendor_id: str) -> dict[str, Any]:
        with repo.transaction() as conn:
            return _vendor_projection(repo.vendor(conn, vendor_id, _user_id()))

    @bp.post("/events/<event_id>/vendors")
    def create_vendor(event_id: str):
        return jsonify(service.create_vendor(event_id, _user_id(), _payload())), 201

    @bp.get("/events/<event_id>/vendors")
    def list_vendors(event_id: str):
        page, size, offset, sort, order = _pagination(VENDOR_SORTS)
        user_id = _user_id()
        clauses, params = ["v.event_id = %s", "e.owner_id = %s"], [event_id, user_id]
        for field in ("category", "contract_status"):
            if request.args.get(field):
                clauses.append(f"v.{field} = %s"); params.append(request.args[field])
        if request.args.get("q"):
            clauses.append("v.name ILIKE %s"); params.append("%" + request.args["q"] + "%")
        where = " AND ".join(clauses)
        with repo.transaction() as conn:
            repo.owned_event(conn, event_id, user_id)
            total = repo.one(conn, f"SELECT COUNT(*) AS total FROM vendors v JOIN events e ON e.id=v.event_id WHERE {where}", tuple(params))["total"]
            rows = repo.all(conn, f"""SELECT v.*, COALESCE(SUM(vp.amount) FILTER (WHERE vp.status <> 'void'),0) paid_amount,
                 GREATEST(v.contract_amount-COALESCE(SUM(vp.amount) FILTER (WHERE vp.status <> 'void'),0),0) remaining_amount
                 FROM vendors v JOIN events e ON e.id=v.event_id LEFT JOIN vendor_payments vp ON vp.vendor_id=v.id
                 WHERE {where} GROUP BY v.id ORDER BY v.{sort} {order} LIMIT %s OFFSET %s""", tuple(params + [size, offset]))
        return jsonify({"items": [_vendor_projection(r) for r in rows], "total": total, "page": page, "size": size})

    @bp.get("/vendors/<vendor_id>")
    def get_vendor(vendor_id: str):
        return jsonify(vendor_or_404(vendor_id))

    @bp.get("/events/<event_id>/vendors/<vendor_id>")
    def get_event_vendor(event_id: str, vendor_id: str):
        vendor = vendor_or_404(vendor_id)
        if str(vendor["event_id"]) != event_id:
            raise ApiError("Vendor not found", 404)
        return jsonify(vendor)

    @bp.patch("/vendors/<vendor_id>")
    def update_vendor(vendor_id: str):
        return jsonify(service.update_vendor(vendor_id, _user_id(), _payload()))

    @bp.delete("/vendors/<vendor_id>")
    def delete_vendor(vendor_id: str):
        service.delete_vendor(vendor_id, _user_id()); return "", 204

    @bp.patch("/events/<event_id>/vendors/<vendor_id>")
    def update_event_vendor(event_id: str, vendor_id: str):
        vendor = vendor_or_404(vendor_id)
        if str(vendor["event_id"]) != event_id:
            raise ApiError("Vendor not found", 404)
        return jsonify(service.update_vendor(vendor_id, _user_id(), _payload()))

    @bp.delete("/events/<event_id>/vendors/<vendor_id>")
    def delete_event_vendor(event_id: str, vendor_id: str):
        # Confirm the parent path before deleting; prevents cross-event IDs.
        vendor = vendor_or_404(vendor_id)
        if str(vendor["event_id"]) != event_id:
            raise ApiError("Vendor not found", 404)
        service.delete_vendor(vendor_id, _user_id()); return "", 204

    @bp.post("/vendors/<vendor_id>/payments")
    def create_payment(vendor_id: str):
        return jsonify(service.create_payment(vendor_id, _user_id(), _payload())), 201

    @bp.post("/events/<event_id>/vendors/<vendor_id>/payments")
    def create_event_payment(event_id: str, vendor_id: str):
        vendor = vendor_or_404(vendor_id)
        if str(vendor["event_id"]) != event_id:
            raise ApiError("Vendor not found", 404)
        return jsonify(service.create_payment(vendor_id, _user_id(), _payload())), 201

    @bp.get("/vendors/<vendor_id>/payments")
    def list_payments(vendor_id: str):
        page, size, offset, sort, order = _pagination(PAYMENT_SORTS)
        with repo.transaction() as conn:
            repo.vendor(conn, vendor_id, _user_id())
            params: list[Any] = [vendor_id]
            where = "vendor_id = %s"
            if request.args.get("status"):
                where += " AND status = %s"; params.append(request.args["status"])
            total = repo.one(conn, f"SELECT COUNT(*) total FROM vendor_payments WHERE {where}", tuple(params))["total"]
            rows = repo.all(conn, f"SELECT * FROM vendor_payments WHERE {where} ORDER BY {sort} {order} LIMIT %s OFFSET %s", tuple(params + [size, offset]))
        return jsonify({"items": [_payment_projection(r) for r in rows], "total": total, "page": page, "size": size})

    @bp.get("/events/<event_id>/vendors/<vendor_id>/payments")
    def list_event_payments(event_id: str, vendor_id: str):
        vendor = vendor_or_404(vendor_id)
        if str(vendor["event_id"]) != event_id:
            raise ApiError("Vendor not found", 404)
        return list_payments(vendor_id)

    @bp.get("/vendor-payments/<payment_id>")
    def get_payment(payment_id: str):
        with repo.transaction() as conn:
            row = repo.one(conn, "SELECT vp.* FROM vendor_payments vp JOIN vendors v ON v.id=vp.vendor_id JOIN events e ON e.id=v.event_id WHERE vp.id=%s AND e.owner_id=%s", (payment_id, _user_id()))
            if not row: raise ApiError("Vendor payment not found", 404)
            return jsonify(_payment_projection(row))

    @bp.patch("/vendor-payments/<payment_id>")
    def update_payment(payment_id: str):
        return jsonify(service.update_payment(payment_id, _user_id(), _payload()))

    @bp.delete("/vendor-payments/<payment_id>")
    def delete_payment(payment_id: str):
        service.delete_payment(payment_id, _user_id()); return "", 204

    return bp


# Conventional export for app factories that discover and register blueprints.
vendor_bp = create_vendor_blueprint(_InjectedDatabase())
