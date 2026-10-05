"""Vendor/payment persistence ports and direct Oracle named-bind SQL."""
from decimal import Decimal
from typing import Any, Protocol

from eventforge.domain.vendor import Payment, Vendor


class VendorRepository(Protocol):
    def get_vendor(self, vendor_id: str, *, lock: bool = False) -> Vendor | None: ...
    def add_vendor(self, vendor: Vendor) -> Vendor: ...
    def update_vendor(self, vendor: Vendor) -> Vendor: ...
    def delete_vendor(self, vendor_id: str) -> bool: ...
    def add_payment(self, payment: Payment) -> Payment: ...
    def payments_for_vendor(self, vendor_id: str) -> list[Payment]: ...
    def paid_total(self, vendor_id: str, *, lock: bool = False) -> Decimal: ...

GET_VENDOR_SQL = "SELECT id, event_id, name, cost, service_description FROM vendors WHERE id = :id"
INSERT_VENDOR_SQL = """INSERT INTO vendors (id, event_id, name, cost, service_description)
VALUES (:id, :event_id, :name, :cost, :service_description)"""
INSERT_PAYMENT_SQL = """INSERT INTO vendor_payments (id, vendor_id, amount, paid_at, reference)
VALUES (:id, :vendor_id, :amount, :paid_at, :reference)"""
PAYMENTS_SQL = "SELECT id, vendor_id, amount, paid_at, reference FROM vendor_payments WHERE vendor_id = :vendor_id ORDER BY paid_at, id"
PAID_TOTAL_SQL = "SELECT NVL(SUM(amount), 0) FROM vendor_payments WHERE vendor_id = :vendor_id"


class OracleVendorRepository:
    def __init__(self, connection: Any):
        self.connection = connection

    @staticmethod
    def _params(value: Any) -> dict[str, Any]:
        return {name: getattr(value, name) for name in value.__dataclass_fields__}

    def get_vendor(self, vendor_id: str, *, lock: bool = False) -> Vendor | None:
        cursor = self.connection.cursor()
        cursor.execute(GET_VENDOR_SQL + (" FOR UPDATE" if lock else ""), {"id": vendor_id})
        row = cursor.fetchone()
        return Vendor(*row) if row else None

    def add_vendor(self, vendor: Vendor) -> Vendor:
        self.connection.cursor().execute(INSERT_VENDOR_SQL, self._params(vendor))
        return vendor

    def update_vendor(self, vendor: Vendor) -> Vendor:
        self.connection.cursor().execute("UPDATE vendors SET name=:name, cost=:cost, service_description=:service_description WHERE id=:id", self._params(vendor))
        return vendor

    def delete_vendor(self, vendor_id: str) -> bool:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM vendors WHERE id = :id", {"id": vendor_id})
        return cursor.rowcount == 1

    def add_payment(self, payment: Payment) -> Payment:
        self.connection.cursor().execute(INSERT_PAYMENT_SQL, self._params(payment))
        return payment

    def payments_for_vendor(self, vendor_id: str) -> list[Payment]:
        cursor = self.connection.cursor()
        cursor.execute(PAYMENTS_SQL, {"vendor_id": vendor_id})
        return [Payment(*row) for row in cursor]

    def paid_total(self, vendor_id: str, *, lock: bool = False) -> Decimal:
        # The locked vendor row is acquired by service before this aggregate query.
        cursor = self.connection.cursor()
        cursor.execute(PAID_TOTAL_SQL, {"vendor_id": vendor_id})
        value = cursor.fetchone()[0]
        return Decimal(str(value))
