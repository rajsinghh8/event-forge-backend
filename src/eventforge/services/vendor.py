"""Pure vendor and payment service with budget safety invariants."""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from eventforge.domain.errors import ConflictError, NotFoundError
from eventforge.domain.vendor import Payment, Vendor, positive_amount
from eventforge.repository.vendor import VendorRepository


class VendorService:
    def __init__(self, repository: VendorRepository):
        self.repository = repository

    def create_vendor(self, event_id: str, name: str, cost: Decimal, service_description: str | None = None) -> Vendor:
        return self.repository.add_vendor(Vendor(str(uuid4()), event_id, name, cost, service_description))

    def update_vendor(self, vendor_id: str, *, name: str | None = None, cost: Decimal | None = None, service_description: str | None = None) -> Vendor:
        vendor = self.repository.get_vendor(vendor_id, lock=True)
        if vendor is None:
            raise NotFoundError("vendor not found")
        candidate = replace(vendor, name=name if name is not None else vendor.name,
                            cost=cost if cost is not None else vendor.cost,
                            service_description=service_description if service_description is not None else vendor.service_description)
        if self.repository.paid_total(vendor_id) > candidate.cost:
            raise ConflictError("vendor cost cannot be less than paid amount")
        return self.repository.update_vendor(candidate)

    def record_payment(self, vendor_id: str, amount: Decimal, paid_at: datetime, reference: str | None = None) -> Payment:
        # Locking the vendor serializes the total check with concurrent payments.
        vendor = self.repository.get_vendor(vendor_id, lock=True)
        if vendor is None:
            raise NotFoundError("vendor not found")
        payment_amount = positive_amount(amount, "payment amount")
        if self.repository.paid_total(vendor_id) + payment_amount > vendor.cost:
            raise ConflictError("paid amount cannot exceed vendor cost")
        return self.repository.add_payment(Payment(str(uuid4()), vendor_id, payment_amount, paid_at, reference))

    def delete_vendor(self, vendor_id: str) -> None:
        vendor = self.repository.get_vendor(vendor_id, lock=True)
        if vendor is None:
            raise NotFoundError("vendor not found")
        if self.repository.payments_for_vendor(vendor_id):
            raise ConflictError("vendor with payments cannot be deleted")
        if not self.repository.delete_vendor(vendor_id):
            raise NotFoundError("vendor not found")
