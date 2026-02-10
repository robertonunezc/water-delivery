"""
Centralized billing information logic for Client model.

This module provides a clean, single-entry-point API for all billing-related
queries, separating "what exists" (own data) from "what's effective" (inherited or own).
"""
from typing import Optional, List
from django.db import models


class OwnBillingData:
    """Container for client's own billing components (not inherited)."""
    
    __slots__ = ('data', 'address', 'frequency')
    
    def __init__(self, client: 'Client'):
        """
        Extract client's own billing components.
        
        Args:
            client: Client instance to check
        """
        self.data = getattr(client, 'billing_data', None) if hasattr(client, 'billing_data') else None
        self.address = client.addresses.filter(type='billing', active=True).first() if client.pk else None
        self.frequency = getattr(client, 'billing_frecuency', None) if hasattr(client, 'billing_frecuency') else None
    
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
    def is_complete(self) -> bool:
        """Check if client has all three billing components."""
        return self.has_data and self.has_address and self.has_frequency
    
    @property
    def has_any(self) -> bool:
        """Check if client has at least one billing component."""
        return self.has_data or self.has_address or self.has_frequency


class EffectiveBillingData:
    """Container for effective billing components (own or inherited from corporate)."""
    
    __slots__ = ('data', 'address', 'frequency', '_client')
    
    def __init__(self, client: 'Client', own: OwnBillingData):
        """
        Resolve effective billing data considering inheritance.
        
        Args:
            client: Client instance
            own: Client's own billing data container
        """
        self._client = client
        
        # Resolve each component with inheritance logic
        self.data = self._resolve_data(client, own)
        self.address = self._resolve_address(client, own)
        self.frequency = self._resolve_frequency(client, own)
    
    def _resolve_data(self, client: 'Client', own: OwnBillingData):
        """Resolve effective billing data."""
        if own.has_data:
            return own.data
        
        # Check inheritance (branch without override enabled)
        if (client.type == 'branch' and 
            client.corporate and 
            not client.billing_override_enabled):
            # Recursive call to get corporate's effective data
            return client.corporate.billing_info.effective.data
        
        return None
    
    def _resolve_address(self, client: 'Client', own: OwnBillingData):
        """Resolve effective billing address."""
        if own.has_address:
            return own.address
        
        # Check inheritance (branch without override enabled)
        if (client.type == 'branch' and 
            client.corporate and 
            not client.billing_override_enabled):
            # Recursive call to get corporate's effective address
            return client.corporate.billing_info.effective.address
        
        return None
    
    def _resolve_frequency(self, client: 'Client', own: OwnBillingData):
        """Resolve effective billing frequency."""
        if own.has_frequency:
            return own.frequency
        
        # Check inheritance (branch without override enabled)
        if (client.type == 'branch' and 
            client.corporate and 
            not client.billing_override_enabled):
            # Recursive call to get corporate's effective frequency
            return client.corporate.billing_info.effective.frequency
        
        return None
    
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
    def is_complete(self) -> bool:
        """Check if effective billing setup is complete (all 3 components)."""
        return self.has_data and self.has_address and self.has_frequency
    
    @property
    def has_any(self) -> bool:
        """Check if at least one effective component exists."""
        return self.has_data or self.has_address or self.has_frequency


class BillingInfo:
    """
    Centralized billing information for a client.
    
    Provides clear separation between:
    - own: What THIS client has (no inheritance)
    - effective: What will be used (own or inherited from corporate)
    - Metadata: source, completeness, missing components, etc.
    
    Usage:
        billing = client.billing_info
        
        # Check completeness
        if billing.is_complete:
            create_invoice()
        
        # Get effective data
        rfc = billing.effective.data.rfc
        
        # Check source
        if billing.source == 'corporate':
            show_inheritance_warning()
        
        # Check missing components
        if billing.missing_components:
            show_warning(f"Missing: {', '.join(billing.missing_components)}")
    """
    
    __slots__ = ('_client', 'own', 'effective')
    
    def __init__(self, client: 'Client'):
        """
        Initialize billing info for a client.
        
        Args:
            client: Client instance to analyze
        """
        self._client = client
        
        # Extract own and effective billing data
        self.own = OwnBillingData(client)
        self.effective = EffectiveBillingData(client, self.own)
    
    @property
    def source(self) -> str:
        """
        Determine where billing data comes from.
        
        Returns:
            'own': Client uses its own complete billing data
            'corporate': Branch inherits from corporate
            'none': No billing data available
        """
        # If client has all three components of own data, it's 'own'
        if self.own.is_complete:
            return 'own'
        
        # If branch with override enabled and has ANY own data, it's 'own' (not inheriting)
        if (self._client.type == 'branch' and 
            self._client.billing_override_enabled and 
            self.own.has_any):
            return 'own'
        
        # Check if inheriting from corporate (only if override not enabled)
        if (self._client.type == 'branch' and 
            self._client.corporate and 
            not self._client.billing_override_enabled):
            
            corporate_billing = self._client.corporate.billing_info
            if corporate_billing.own.has_any:
                return 'corporate'
        
        return 'none'
    
    @property
    def uses_inheritance(self) -> bool:
        """Check if client is using inherited billing data from corporate."""
        return self.source == 'corporate'
    
    @property
    def is_complete(self) -> bool:
        """Check if effective billing setup is complete (all 3 components present)."""
        return self.effective.is_complete
    
    @property
    def can_create_invoice(self) -> bool:
        """
        Check if client can create invoices.
        
        Requires complete billing setup (data + address + frequency).
        """
        return self.is_complete
    
    @property
    def missing_components(self) -> List[str]:
        """
        Get list of missing billing component names.
        
        Returns:
            List of missing component names: 'billing_data', 'billing_address', 'billing_frequency'
        """
        missing = []
        
        if not self.effective.has_data:
            missing.append('billing_data')
        
        if not self.effective.has_address:
            missing.append('billing_address')
        
        if not self.effective.has_frequency:
            missing.append('billing_frequency')
        
        return missing
    
    def get_setup_status(self) -> dict:
        """
        Get comprehensive billing setup status.
        
        This method maintains backward compatibility with get_billing_setup_status().
        
        Returns:
            dict with keys:
                - is_complete (bool): All components present
                - source (str): 'own', 'corporate', or 'none'
                - missing_components (list): Component names that are missing
        """
        return {
            'is_complete': self.is_complete,
            'source': self.source,
            'missing_components': self.missing_components,
        }
    
    def get_override_validation_warnings(self) -> List[str]:
        """
        Get validation warnings for billing_override_enabled flag.
        
        When override is enabled, branch should have all 3 components.
        This is a soft validation - returns warnings but doesn't prevent saving.
        
        Returns:
            List of warning messages
        """
        warnings = []
        
        # Only validate for branches with override enabled
        if not (self._client.type == 'branch' and self._client.billing_override_enabled):
            return warnings
        
        # Check if branch has all required components
        if not self.own.has_data:
            warnings.append(
                'Datos de facturación propios requeridos: debe agregar RFC y Razón Social.'
            )
        
        if not self.own.has_address:
            warnings.append(
                'Dirección fiscal propia requerida: debe agregar una dirección de tipo "Fiscal".'
            )
        
        if not self.own.has_frequency:
            warnings.append(
                'Frecuencia de facturación propia requerida: debe configurar la frecuencia.'
            )
        
        return warnings
