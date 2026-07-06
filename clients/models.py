from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Optional, List
# pyrefly: ignore [missing-import]
from django.conf import settings
from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from core.models import TimeStampedModel
from core.utils import get_first_last_day_of_month
#Client types
CLIENT_TYPE_CHOICES = [
    ('corporate', 'Corporativo'),
    ('branch', 'Sucursal'),
]
PAYMENT_METHOD_CHOICES = [
    ('cash', 'Efectivo'),
    ('credit_card', 'Tarjeta de Crédito'),
    ('bank_transfer', 'Transferencia Bancaria'),
    ('balance', 'Saldo'),
    ('credit', 'Crédito'),
    ('other', 'Otro'),
]

PAYMENT_TERM_TYPE_CHOICES = [
    ('monthly_cutoff', 'Fecha de corte mensual'),
    ('invoice_due', 'Vencimiento posterior a factura'),
]

CREDIT_CUTOFF_DAY_CHOICES = [
    ('last_day', 'Último día del mes'),
] + [(str(day), f'Día {day}') for day in range(1, 32)]


WEEKDAY_CHOICES = [
    (0, 'Lunes'),
    (1, 'Martes'),
    (2, 'Miércoles'),
    (3, 'Jueves'),
    (4, 'Viernes'),
    (5, 'Sábado'),
    (6, 'Domingo'),
]

OCCURRENCE_CHOICES = [
    (1, 'Primer'),
    (2, 'Segundo'),
    (3, 'Tercer'),
    (4, 'Cuarto'),
    (-1, 'Último'),
]

REGIMEN_FISCAL_CHOICES = [
    ('601', '601 - Régimen General de Ley Personas Morales'),
    ('602', '602 - Régimen Simplificado de Ley Personas Morales'),
    ('603', '603 - Personas Morales con Fines no Lucrativos'),
    ('604', '604 - Régimen de Pequeños Contribuyentes'),
    ('605', '605 - Régimen de Sueldos y Salarios e Ingresos Asimilados a Salarios'),
    ('606', '606 - Régimen de Arrendamiento'),
    ('607', '607 - Régimen de Enajenación o Adquisición de Bienes'),
    ('608', '608 - Régimen de los Demás Ingresos'),
    ('609', '609 - Régimen de Consolidación'),
    ('610', '610 - Régimen Residentes en el Extranjero sin Establecimiento Permanente en México'),
    ('611', '611 - Régimen de Ingresos por Dividendos (socios y accionistas)'),
    ('612', '612 - Régimen de las Personas Físicas con Actividades Empresariales y Profesionales'),
    ('613', '613 - Régimen Intermedio de las Personas Físicas con Actividades Empresariales'),
    ('614', '614 - Régimen de los Ingresos por Intereses'),
    ('615', '615 - Régimen de los Ingresos por Obtención de Premios'),
    ('616', '616 - Sin Obligaciones Fiscales'),
    ('617', '617 - PEMEX'),
    ('618', '618 - Régimen Simplificado de Ley Personas Físicas'),
    ('619', '619 - Ingresos por la Obtención de Préstamos'),
    ('620', '620 - Sociedades Cooperativas de Producción que Optan por Diferir sus Ingresos'),
    ('621', '621 - Régimen de Incorporación Fiscal'),
    ('622', '622 - Régimen de Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras PM'),
    ('623', '623 - Régimen de Opcional para Grupos de Sociedades'),
    ('624', '624 - Régimen de los Coordinados'),
    ('625', '625 - Régimen de las Actividades Empresariales con Ingresos a través de Plataformas Tecnológicas'),
    ('626', '626 - Régimen Simplificado de Confianza'),
]

USO_CFDI_CHOICES = [
    ('G01', 'G01 - Adquisición de mercancías'),
    ('G02', 'G02 - Devoluciones, descuentos o bonificaciones'),
    ('G03', 'G03 - Gastos en general'),
    ('I01', 'I01 - Construcciones'),
    ('I02', 'I02 - Mobilario y equipo de oficina por inversiones'),
    ('I03', 'I03 - Equipo de transporte'),
    ('I04', 'I04 - Equipo de computo y accesorios'),
    ('I05', 'I05 - Dados, troqueles, moldes, matrices y herramental'),
    ('I06', 'I06 - Comunicaciones telefónicas'),
    ('I07', 'I07 - Comunicaciones satelitales'),
    ('I08', 'I08 - Otra maquinaria y equipo'),
    ('D01', 'D01 - Honorarios médicos, dentales y gastos hospitalarios'),
    ('D02', 'D02 - Gastos médicos por incapacidad o discapacidad'),
    ('D03', 'D03 - Gastos funerales'),
    ('D04', 'D04 - Donativos'),
    ('D05', 'D05 - Intereses reales efectivamente pagados por créditos hipotecarios (casa habitación)'),
    ('D06', 'D06 - Aportaciones voluntarias al SAR'),
    ('D07', 'D07 - Primas por seguros de gastos médicos'),
    ('D08', 'D08 - Gastos de transportación escolar obligatoria'),
    ('D09', 'D09 - Depósitos en cuentas para el ahorro, primas que tengan como base planes de pensiones'),
    ('D10', 'D10 - Pagos por servicios educativos (colegiaturas)'),
    ('P01', 'P01 - Por definir'),
]

class Client(TimeStampedModel):
    name = models.CharField(max_length=100, db_index=True, verbose_name="Nombre del cliente")
    active = models.BooleanField(default=True, verbose_name="Activo")
    note = models.TextField(blank=True, null=True, verbose_name="Notas")
    type = models.CharField(max_length=50, choices=CLIENT_TYPE_CHOICES, default='branch', verbose_name="Tipo de cliente")
    corporate = models.ForeignKey('Client', related_name='branches', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Cliente corporativo", limit_choices_to={'type': 'corporate'})
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Saldo a favor", help_text="Monto prepagado disponible para usar en pedidos")
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Límite de crédito", help_text="Máximo monto que el cliente puede deber")
    current_debt = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Deuda actual", help_text="Monto actual que debe el cliente")
    can_pay_with_credit = models.BooleanField(default=True, verbose_name="Puede pagar con crédito", help_text="Si está deshabilitado, el cliente no podrá usar crédito para pagos cuando su saldo disponible sea 0")
    address_link = models.CharField(max_length=255, blank=True, null=True, verbose_name="Enlace de dirección", help_text="Enlace a Google Maps u otro servicio de mapas")
    requires_billing = models.BooleanField(default=False, verbose_name="Requiere facturación", help_text="Indica si el cliente necesita facturación formal")
    external_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="ID externo", help_text="ID del cliente en sistemas externos (ERP, CRM, etc.)")
    credit_override_enabled = models.BooleanField(
        default=False,
        verbose_name="Usar datos propios de crédito",
        help_text="Si está habilitado, la sucursal podrá usar una configuración de crédito propia en lugar de la copiada del corporativo"
    )
    #Notification sent 
    last_first_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    last_second_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    last_cancellation_sent_at = models.DateTimeField(null=True, blank=True)
    external_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="ID externo", help_text="ID del cliente en sistemas externos (ERP, CRM, etc.)")
    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        indexes = [
            models.Index(fields=['name'], name='clients_client_name_idx'),
            models.Index(fields=['active'], name='clients_client_active_idx'),
            models.Index(fields=['type'], name='clients_client_type_idx'),
        ]
    
    def __str__(self):
        return self.name
    # Validate that if type is 'branch', corporate must be set
    def clean(self):
        super().clean()

        errors = {}
        from django.core.exceptions import ValidationError

        # Existing validations
        if self.type == 'branch' and not self.corporate:
            errors['corporate'] = 'Cliente sucursal debe tener un cliente corporativo asociado.'
        if self.type == 'corporate' and self.corporate:
            errors['corporate'] = 'Cliente corporativo no puede tener un padre corporativo.'
        
        existing_client_qs = Client.objects.filter(name=self.name, deleted_at__isnull=True)
        existing_client_qs = existing_client_qs.exclude(pk=self.pk)
        if existing_client_qs.exists():
                errors['name'] = 'Ya existe un cliente con este nombre. Los nombres de clientes deben ser únicos.'
        if self.credit_override_enabled and self.type != 'branch':
            errors['credit_override_enabled'] = 'Solo las sucursales pueden habilitar datos propios de crédito.'
        
        if self.credit_override_enabled and self.type == 'branch' and not self.corporate:
            errors['credit_override_enabled'] = 'No se puede habilitar datos propios de crédito sin un corporativo asociado.'

        # NOTE: Removed hard validation for billing setup.
        # Clients can now enable requires_billing without having complete billing data.
        # Use get_missing_billing_components() and get_billing_setup_status() helper methods
        # to check for missing components and display warnings in the admin interface.

        # NOTE: delivery address validation removed - it was too strict for admin workflow.
        # Branches must have their own delivery address (they don't inherit from corporate),
        # but this should be validated at the business logic level (e.g., when creating orders)
        # rather than at the model level, to allow proper admin inline workflow.

        # if self.current_debt > self.credit_limit:
        #     errors['current_debt'] = 'La deuda actual no puede exceder el límite de crédito.'

        try:
            credit_config = self.credit_config
        except ObjectDoesNotExist:
            credit_config = None

        if (
            credit_config
            and credit_config.payment_term_type == 'invoice_due'
            and not self.requires_billing
        ):
            errors['requires_billing'] = (
                'No se puede deshabilitar la facturación recurrente mientras el plazo de crédito '
                'dependa de la emisión de factura.'
            )

        if errors:
            raise ValidationError(errors)

    # Balance and Credit State Methods (pure state queries, no side effects)
    def get_available_credit(self):
        """Get remaining credit available"""
        return float(self.credit_limit) - float(self.current_debt)
    
    def can_use_credit_for_payment(self):
        """
        Check if client can use credit for payments based on their settings and available credit
        
        Returns:
            bool: True if client can use credit, False otherwise
        """
        # If credit payment is disabled for this client
        return self.can_pay_with_credit and self.get_available_credit() > 0
    
    def validate_credit_payment(self, amount, note=None):
        """
        Validate if a credit payment can be processed
        
        Args:
            amount: Amount to be paid with credit
            note: Optional note provided for the transaction
            
        Returns:
            dict: Validation result with success status and error message if applicable
        """
        # Check if client can use credit
        if not self.can_use_credit_for_payment():
            return {
                'success': False,
                'error': 'Cliente no puede pagar con credito',
                'error_code': 'CREDIT_DISABLED'
            }
        
        available_credit = self.get_available_credit()
        if available_credit < amount:
            return {
                'success': False,
                'error': f'Crédito insuficiente. Disponible: ${available_credit:.2f}.',
                'error_code': 'CREDIT_LIMIT_EXCEEDED',
            }
        
        return {'success': True}
    def has_billing_frequency(self):
        """Check if client has an active billing frequency set"""
        has_frequency = hasattr(self, 'invoice_schedule')
        return has_frequency
        
    def can_afford_order(self, order_amount):
        """Check if client can afford an order using balance + available credit"""
        available_balance = self.balance
        available_credit = 0
        
        # Only include available credit if client can use credit for payments
        if self.can_use_credit_for_payment():
            available_credit = self.get_available_credit()
        
        return (available_balance + available_credit) >= order_amount

    # Billing Information - Centralized API (no caching to avoid stale data)
    @property
    def billing_info(self):
        """Build billing info on demand to reflect latest state."""
        from clients.invoice_info import InvoiceInfo
        return InvoiceInfo(self)

    def get_products(self):
        return self.product_prices.select_related('product').all()
    # Backwards-compatible helpers
    def get_effective_billing_data(self):
        return self.billing_info.effective.data

    def get_effective_billing_address(self):
        return self.billing_info.effective.address

    def get_effective_billing_frequency(self):
        return self.billing_info.effective.frequency

    def get_billing_source(self):
        return self.billing_info.source

    def has_complete_billing_setup(self):
        return self.billing_info.is_complete

    def has_billing_address(self):
        """Check if client has at least one billing address"""
        return self.addresses.filter(type='billing').exists()

    def has_delivery_address(self):
        """Check if client has at least one active delivery address"""
        return self.addresses.filter(type='delivery', active=True).exists()

    def can_receive_orders(self):
        """
        Check if client is ready to receive orders.
        Branches require their own delivery address (they don't inherit from corporate).

        Returns:
            tuple: (bool, str) - (can_receive, error_message)
        """
        if self.type == 'branch':
            if not self.has_delivery_address():
                return False, 'La sucursal debe tener un domicilio de envío (ubicación física) antes de recibir pedidos.'

        # Add other validations as needed
        if not self.active:
            return False, 'El cliente no está activo.'

        return True, ''


# NOTE: BranchClient model is deprecated - Client model handles branch/corporate relationships
# through the 'type' and 'corporate' fields. Commented out due to model conflicts.
# class BranchClient(TimeStampedModel):
#     """
#     Model to link branch clients to their corporate parent clients
#     """
#     corporate_client = models.ForeignKey('Client', related_name='branches', on_delete=models.CASCADE, verbose_name="Cliente Corporativo")
#     class Meta:
#         verbose_name = 'Cliente Sucursal'
#         verbose_name_plural = 'Clientes Sucursales'
#         unique_together = ('corporate_client', 'branch_client')
#
#     def __str__(self):
#         return f"{self.branch_client.name} (Sucursal de {self.corporate_client.name})"

class BalanceTransaction(TimeStampedModel):
    """
    Track all balance-related transactions for complete audit trail
    """
    TRANSACTION_TYPES = [
        ('deposit', 'Depósito'),           # Client adds money
        ('payment', 'Pago con saldo'),     # Using balance for order payment
        ('added_in_order', 'Saldo agregado en venta'), # Using balance for deferred payment
        ('payment_reversal', 'Reversión de pago con saldo'),
        ('added_in_order_reversal', 'Reversión de saldo agregado en venta'),
        ('refund', 'Reembolso'),           # Money returned to balance
        ('adjustment', 'Ajuste manual'),   # Manual adjustment
        ('transfer_in', 'Transferencia recibida'),   # Transfer from another client
        ('transfer_out', 'Transferencia enviada'),   # Transfer to another client
        ('correction', 'Corrección'),      # Error correction
    ]

    client = models.ForeignKey('Client', related_name='balance_transactions', on_delete=models.PROTECT, verbose_name="Cliente")
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES, verbose_name="Tipo de Transacción")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto")
    balance_before = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Saldo Anterior")
    balance_after = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Saldo Posterior")
    notes = models.TextField(blank=True, null=True, verbose_name="Notas adicionales")
    
    # References to related objects
    reference_order = models.ForeignKey('orders.Order', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Orden relacionada")
    reference_payment = models.ForeignKey('payment.Payment', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Pago relacionado")
    transfer_to_client = models.ForeignKey('Client', null=True, blank=True, on_delete=models.SET_NULL, related_name='balance_transfers_received', verbose_name="Cliente destino (transferencia)")
    
    # Audit fields
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Creado por")

    # Manager
    from clients.managers import BalanceTransactionManager
    objects = BalanceTransactionManager()

    class Meta:
        verbose_name = 'Transacción de Saldo'
        verbose_name_plural = 'Transacciones de Saldo'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['client', '-created_at'], name='balance_tx_client_date_idx'),
            models.Index(fields=['transaction_type'], name='balance_tx_type_idx'),
            models.Index(fields=['created_at'], name='balance_tx_date_idx'),
            models.Index(fields=['reference_order'], name='balance_tx_order_idx'),
            models.Index(fields=['reference_payment'], name='balance_tx_payment_idx'),
        ]

    def __str__(self):
        return f"{self.client.name} - {self.get_transaction_type_display()} - ${self.amount:.2f} ({self.created_at.date()})"
    
    def clean(self):
        """Validate transaction data"""
        from django.core.exceptions import ValidationError
        
        # Validate amount is positive
        if self.amount <= 0:
            raise ValidationError({'amount': 'El monto debe ser mayor a cero.'})
        
        # Validate balance calculation
        if self.transaction_type in ['deposit', 'refund', 'transfer_in', 'adjustment', 'payment_reversal']:
            # Additions to balance
            if self.balance_after != self.balance_before + self.amount:
                raise ValidationError('Error en cálculo de saldo: adición incorrecta.')
        else:
            # Deductions from balance
            if self.balance_after != self.balance_before - self.amount:
                raise ValidationError('Error en cálculo de saldo: deducción incorrecta.')
        
        # Validate sufficient balance for deductions
        if (
            self.transaction_type in ['payment', 'transfer_out', 'added_in_order_reversal']
            and self.balance_before < self.amount
        ):
            raise ValidationError({'amount': f'Saldo insuficiente. Disponible: ${self.balance_before:.2f}'})


class CreditTransaction(TimeStampedModel):
    """
    Track all credit-related transactions for complete audit trail
    """
    TRANSACTION_TYPES = [
        ('purchase', 'Compra a crédito'),     # Adding debt
        ('payment', 'Pago de deuda'),         # Reducing debt
        ('payment_from_balance', 'Pago con Saldo'),  # Payment using client's balance
        ('purchase_reversal', 'Reversión de compra a crédito'),
        ('payment_reversal', 'Reversión de pago de deuda'),
        ('adjustment', 'Ajuste manual'),      # Manual debt adjustment
        ('limit_change', 'Cambio de límite'), # Credit limit modification
        ('interest', 'Interés aplicado'),     # Interest charges
        ('fee', 'Cargo adicional'),           # Additional fees
        ('forgiveness', 'Condonación'),       # Debt forgiveness
        ('correction', 'Corrección'),         # Error correction
    ]
    
    client = models.ForeignKey('Client', related_name='credit_transactions', on_delete=models.PROTECT, verbose_name="Cliente")
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, verbose_name="Tipo de Transacción")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto")
    debt_before = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Deuda Anterior")
    debt_after = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Deuda Posterior")
    credit_limit_before = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Límite Anterior")
    credit_limit_after = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Límite Posterior")
    notes = models.TextField(blank=True, null=True, verbose_name="Notas adicionales")
    
    # References to related objects
    reference_order = models.ForeignKey('orders.Order', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Orden relacionada")
    reference_payment = models.ForeignKey('payment.Payment', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Pago relacionado")
    
    # Audit fields
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Creado por")

    # Manager
    from clients.managers import CreditTransactionManager
    objects = CreditTransactionManager()

    class Meta:
        verbose_name = 'Transacción de Crédito'
        verbose_name_plural = 'Transacciones de Crédito'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['client', '-created_at'], name='credit_tx_client_date_idx'),
            models.Index(fields=['transaction_type'], name='credit_tx_type_idx'),
            models.Index(fields=['created_at'], name='credit_tx_date_idx'),
            models.Index(fields=['reference_order'], name='credit_tx_order_idx'),
            models.Index(fields=['reference_payment'], name='credit_tx_payment_idx'),
        ]

    def __str__(self):
        return f"{self.client.name} - {self.get_transaction_type_display()} - ${self.amount:.2f} ({self.created_at.date()})"
    
    def clean(self):
        """Validate transaction data"""
        from django.core.exceptions import ValidationError
        
        # Validate amount is positive
        if self.amount <= 0:
            raise ValidationError({'amount': 'El monto debe ser mayor a cero.'})
        
        # Validate debt calculation
        if self.transaction_type in ['purchase', 'interest', 'fee', 'adjustment', 'payment_reversal']:
            # Additions to debt
            if self.debt_after != self.debt_before + self.amount:
                raise ValidationError('Error en cálculo de deuda: adición incorrecta.')
        else:
            # Reductions from debt (including payment_from_balance)
            if self.debt_after != self.debt_before - self.amount:
                raise ValidationError('Error en cálculo de deuda: reducción incorrecta.')
        
        # Validate debt doesn't go negative
        if self.debt_after < 0:
            raise ValidationError({'amount': 'La deuda no puede ser negativa.'})
        
        # Validate balance availability for payment_from_balance transactions
        if self.transaction_type == 'payment_from_balance':
            if self.client and self.client.balance < self.amount:
                raise ValidationError({
                    'amount': f'Saldo insuficiente. Disponible: ${self.client.balance:.2f}, Requerido: ${self.amount:.2f}'
                })
        
        # Validate credit limit constraints for purchases
        if self.transaction_type == 'purchase' and self.credit_limit_after is not None:
            if self.debt_after > self.credit_limit_after:
                raise ValidationError({'amount': f'Excede límite de crédito. Límite: ${self.credit_limit_after:.2f}'})


# InvoiceSchedule has been moved to billing.models
# Import it from there for backward compatibility
from invoice.models import InvoiceSchedule
ClientBillingFrecuency = InvoiceSchedule  # backward compat alias

class Contact(TimeStampedModel):
    client = models.ForeignKey('Client', related_name='contacts', on_delete=models.CASCADE)
    name = models.CharField(max_length=100, verbose_name="Nombre")
    email = models.EmailField(blank=True, null=True, verbose_name="Correo electrónico")
    phone = models.CharField(max_length=15, blank=True, null=True, db_index=True, verbose_name="Teléfono")
    position = models.CharField(max_length=100, blank=True, null=True, verbose_name="Puesto")

    class Meta:
        verbose_name = 'Contacto'
        verbose_name_plural = 'Contactos'
        indexes = [
            models.Index(fields=['phone'], name='clients_contact_phone_idx'),
            models.Index(fields=['email'], name='clients_contact_email_idx'),
        ]

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Address(TimeStampedModel):
    client = models.ForeignKey('Client', related_name='addresses', on_delete=models.PROTECT, verbose_name="Cliente")
    type = models.CharField(max_length=50, choices=[('billing', 'Fiscal'), ('delivery', 'Entrega'), ('other', 'Otro')], default='delivery', verbose_name="Tipo")
    street = models.CharField(max_length=255, verbose_name="Calle")
    exterior_number = models.CharField(max_length=20, blank=True, null=True, verbose_name="No. Exterior")
    interior_number = models.CharField(max_length=20, blank=True, null=True, verbose_name="No. Interior")
    locality = models.CharField(max_length=100, verbose_name="Colonia", default='Querétaro')
    municipality = models.CharField(max_length=100,default='Querétaro', verbose_name="Delegación o Municipio")
    state = models.CharField(max_length=100, default='Querétaro', verbose_name="Estado")
    zip_code = models.CharField(max_length=20, default='76000', verbose_name="Código Postal")
    country = models.CharField(max_length=100, default='Mexico', verbose_name="País")
    reference = models.TextField(blank=True, null=True, verbose_name="Referencia")
    active = models.BooleanField(default=True, verbose_name="Activo")
    # note = models.TextField(blank=True, null=True, verbose_name="Notas")
    
    class Meta:
        verbose_name = 'Domicilio'
        verbose_name_plural = 'Domicilios'
        indexes = [
            models.Index(fields=['municipality'], name='clients_address_munic_idx'),
            models.Index(fields=['state'], name='clients_address_state_idx'),
            models.Index(fields=['active'], name='clients_address_active_idx'),
        ]

    def __str__(self):
        return f"{self.street}, {self.municipality}, {self.state}, {self.zip_code}, {self.country}"
    
    def clean(self):
        """Validate that each client has only one address of type billing"""
        from django.core.exceptions import ValidationError
        super().clean()
        errors = {}
        # Only validate uniqueness for billing type
        # delivery and other types can have multiple addresses per client
        if self.type != 'billing':
            return
        
        # Build query to find existing addresses of the same type for this client
        existing_query = Address.objects.filter(
            client=self.client,
            type=self.type
        )
        
        # Exclude current instance if updating (not creating)
        if self.pk:
            existing_query = existing_query.exclude(pk=self.pk)
        
        # Check if another address of this type exists
        if existing_query.exists():
            type_display = self.get_type_display()
            raise ValidationError({
            '__all__': f'No se puede guardar: dirección duplicada de tipo "{type_display}"',
            'type': f'El cliente ya tiene una dirección de tipo "{type_display}". '
                    f'Solo se permite una dirección fiscal por cliente.'
        })



class InvoiceData(TimeStampedModel):
    client = models.OneToOneField('Client', related_name='invoice_data', on_delete=models.CASCADE)
    rfc = models.CharField(max_length=255, db_index=True)
    razon_social = models.TextField()
    curp = models.CharField(max_length=255, blank=True, null=True, verbose_name="CURP")
    #uso_cfdi = models.CharField(max_length=10, choices=USO_CFDI_CHOICES, verbose_name="Uso de CFDI", null=True, blank=True)
    #metodo_pago = models.CharField(max_length=255, choices=PAYMENT_METHOD_CHOICES, default='other', verbose_name="Forma de pago")
    #address = models.ForeignKey('Address', related_name='billing_data', on_delete=models.CASCADE)
    #regimen_fiscal = models.CharField(max_length=10, choices=REGIMEN_FISCAL_CHOICES, blank=True, null=True, verbose_name="Régimen Fiscal")
    class Meta:
        db_table = 'clients_billingdata'  # Keep existing table name to avoid migration
        verbose_name = 'Datos de facturación'
        verbose_name_plural = 'Datos de facturación'
        indexes = [
            models.Index(fields=['rfc'], name='clients_billing_rfc_idx'),
        ]
    
    def __str__(self):
        return f"Invoice data for {self.client.name}"
    
class ClientCreditConfig(TimeStampedModel):
    client = models.OneToOneField(Client, related_name='credit_config', on_delete=models.CASCADE)
    payment_term_type = models.CharField(
        max_length=20,
        choices=PAYMENT_TERM_TYPE_CHOICES,
        default='monthly_cutoff',
        verbose_name='Modalidad de pago del crédito',
    )
    cutoff_day = models.CharField(
        max_length=10,
        choices=CREDIT_CUTOFF_DAY_CHOICES,
        default='last_day',
        verbose_name='Día de corte mensual',
    )
    max_payment_days = models.PositiveIntegerField(default=30, verbose_name="Días naturales máximos para pagar")
    first_notification_days = models.PositiveIntegerField(default=5, verbose_name="Días antes del vencimiento para la primera notificación")
    second_notification_days = models.PositiveIntegerField(default=2, verbose_name="Días antes del vencimiento para la segunda notificación")
    overdue_notification_days = models.PositiveIntegerField(default=1, verbose_name="Días después del vencimiento para notificación de morosidad")

    def clean(self):
        super().clean()
        if (
            self.client_id
            and self.payment_term_type == 'invoice_due'
            and not self.client.requires_billing
        ):
            from django.core.exceptions import ValidationError

            raise ValidationError({
                'payment_term_type': (
                    'El vencimiento posterior a factura solo está disponible para '
                    'clientes con facturación recurrente.'
                ),
            })
