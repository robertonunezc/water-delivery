"""Centralized invoice information logic for Client model, kept lean for clarity."""
from dataclasses import dataclass
from typing import List, Optional, Set

from invoice.models import InvoiceSchedule
from clients.models import Address, Client, InvoiceData


@dataclass
class InvoiceComponents:
    """Simple container for invoice parts."""

    data: Optional[InvoiceData]
    address: Optional[Address]
    frequency: Optional[InvoiceSchedule]

    @property
    def has_data(self) -> bool:
        return self.data is not None

    @property
    def has_address(self) -> bool:
        return self.address is not None

    @property
    def has_frequency(self) -> bool:
        return self.frequency is not None

    @property
    def has_any(self) -> bool:
        return self.has_data or self.has_address or self.has_frequency

    @property
    def is_complete(self) -> bool:
        return self.has_data and self.has_address


class InvoiceInfo:
    """Resolved invoice info for a client (own + effective + source)."""

    def __init__(self, client: Client):
        self._client = client
        self.own = self._get_own_components(client)
        self.effective, self.source = self._resolve_effective(client, self.own)

    def _get_own_components(self, client: Client) -> InvoiceComponents:
        data = getattr(client, "invoice_data", None) if hasattr(client, "invoice_data") else None
        address = client.addresses.filter(type="billing", active=True).first() if client.pk else None
        frequency = getattr(client, "invoice_schedule", None) if hasattr(client, "invoice_schedule") else None
        return InvoiceComponents(data=data, address=address, frequency=frequency)

    def _resolve_effective(self, client: Client, own: InvoiceComponents):
        """Resolve effective billing without recursive calls deep into corporate chains."""
        visited: Set[int] = set()

        def resolve(current: Client, current_own: InvoiceComponents):
            if current.pk and current.pk in visited:
                return InvoiceComponents(None, None, None), "none"
            if current.pk:
                visited.add(current.pk)

            # Non-branches use only their own setup
            if current.type != "branch":
                return current_own, "own" if current_own.is_complete else "none"

            if current.corporate:
                corporate_own = self._get_own_components(current.corporate)
                corporate_effective, _corporate_source = resolve(current.corporate, corporate_own)
                if corporate_effective.has_any:
                    return corporate_effective, "corporate"

            # No usable data
            return InvoiceComponents(None, None, None), "none"

        return resolve(client, own)

    @property
    def is_complete(self) -> bool:
        return self.effective.is_complete

    @property
    def uses_inheritance(self) -> bool:
        return self.source == "corporate"

    @property
    def missing_components(self) -> List[str]:
        missing = []
        if not self.effective.has_data:
            missing.append("invoice_data")
        if not self.effective.has_address:
            missing.append("billing_address")
        if self._client.requires_billing and not self.effective.has_frequency:
            missing.append("billing_frequency")
        return missing

    def get_setup_status(self) -> dict:
        return {
            "is_complete": self.is_complete,
            "source": self.source,
            "missing_components": self.missing_components,
        }

    def get_override_validation_warnings(self) -> List[str]:
        return []
