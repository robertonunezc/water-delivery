"""Centralized billing information logic for Client model, kept lean for clarity."""
from dataclasses import dataclass
from typing import List, Optional, Set

from clients.models import Client


@dataclass
class BillingComponents:
    """Simple container for billing parts."""

    data: Optional[object]
    address: Optional[object]
    frequency: Optional[object]

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
        return self.has_data and self.has_address and self.has_frequency


class BillingInfo:
    """Resolved billing info for a client (own + effective + source)."""

    def __init__(self, client: Client):
        self._client = client
        self.own = self._get_own_components(client)
        self.effective, self.source = self._resolve_effective(client, self.own)

    def _get_own_components(self, client: Client) -> BillingComponents:
        data = getattr(client, 'billing_data', None) if hasattr(client, 'billing_data') else None
        address = client.addresses.filter(type='billing', active=True).first() if client.pk else None
        frequency = getattr(client, 'billing_frecuency', None) if hasattr(client, 'billing_frecuency') else None
        return BillingComponents(data=data, address=address, frequency=frequency)

    def _resolve_effective(self, client: Client, own: BillingComponents):
        """Resolve effective billing without recursive calls deep into corporate chains."""
        visited: Set[int] = set()

        def resolve(current: Client, current_own: BillingComponents):
            if current.pk and current.pk in visited:
                return BillingComponents(None, None, None), 'none'
            if current.pk:
                visited.add(current.pk)

            # Non-branches use only their own setup
            if current.type != 'branch':
                return current_own, 'own' if current_own.is_complete else 'none'

            # Branch with override enabled prefers own; otherwise fall back to corporate
            if current.billing_override_enabled and current_own.has_any:
                return current_own, 'own'

            if current.corporate:
                corporate_own = self._get_own_components(current.corporate)
                corporate_effective, corporate_source = resolve(current.corporate, corporate_own)
                if corporate_effective.has_any:
                    return corporate_effective, 'corporate'

            # No usable data
            return BillingComponents(None, None, None), 'none'

        return resolve(client, own)

    @property
    def is_complete(self) -> bool:
        return self.effective.is_complete

    @property
    def uses_inheritance(self) -> bool:
        return self.source == 'corporate'

    @property
    def missing_components(self) -> List[str]:
        missing = []
        if not self.effective.has_data:
            missing.append('billing_data')
        if not self.effective.has_address:
            missing.append('billing_address')
        if not self.effective.has_frequency:
            missing.append('billing_frequency')
        return missing

    def get_setup_status(self) -> dict:
        return {
            'is_complete': self.is_complete,
            'source': self.source,
            'missing_components': self.missing_components,
        }

    def get_override_validation_warnings(self) -> List[str]:
        warnings: List[str] = []
        if not (self._client.type == 'branch' and self._client.billing_override_enabled):
            return warnings

        if not self.own.has_data:
            warnings.append('Datos de facturación propios requeridos: debe agregar RFC y Razón Social.')
        if not self.own.has_address:
            warnings.append('Dirección fiscal propia requerida: debe agregar una dirección de tipo "Fiscal".')
        if not self.own.has_frequency:
            warnings.append('Frecuencia de facturación propia requerida: debe configurar la frecuencia.')
        return warnings
