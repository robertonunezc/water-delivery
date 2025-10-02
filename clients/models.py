from calendar import monthrange
from datetime import date, datetime
from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from core.models import TimeStampedModel
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
BILLING_FREQUENCY_CHOICES = [
    ('monthly', 'Mensual'),
    ('bimonthly', 'Bimestral'),
    ('quarterly', 'Trimestral'),
    ('semiannual', 'Semestral'),
    ('annual', 'Anual'),
    ('other', 'Otro'),
]
BILLING_DATE_CHOICES = [
    ('specific_date', 'Fecha específica del mes'),
    ('last_day', 'Último día del mes'),
    ('first_day', 'Primer día del mes'),
    ('weekday_occurrence', 'Día específico de la semana'),
    ('other', 'Otro'),
]

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
class Client(TimeStampedModel):
    name = models.CharField(max_length=100, db_index=True, verbose_name="Nombre del cliente")
    active = models.BooleanField(default=True, verbose_name="Activo")
    note = models.TextField(blank=True, null=True, verbose_name="Notas")
    type = models.CharField(max_length=50, choices=CLIENT_TYPE_CHOICES, default='individual', verbose_name="Tipo de cliente")
    corporate = models.ForeignKey('Client', related_name='branches', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Cliente corporativo")
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Saldo a favor", help_text="Monto prepagado disponible para usar en pedidos")
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Límite de crédito", help_text="Máximo monto que el cliente puede deber")
    current_debt = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Deuda actual", help_text="Monto actual que debe el cliente")
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
    
    # Balance and Credit Management Methods
    def add_balance(self, amount):
        """Add money to client's balance"""
        self.balance += amount
        self.save()
        return self.balance
    
    def deduct_balance(self, amount):
        """Deduct money from client's balance. Returns True if successful, False if insufficient balance"""
        if self.balance >= amount:
            self.balance -= amount
            self.save()
            return True
        return False
    
    def add_debt(self, amount):
        """Add to client's debt. Returns True if within credit limit, False otherwise"""
        new_debt = self.current_debt + amount
        if new_debt <= self.credit_limit:
            self.current_debt = new_debt
            self.save()
            return True
        return False
    
    def pay_debt(self, amount):
        """Pay down client's debt"""
        payment_amount = min(amount, self.current_debt)
        self.current_debt -= payment_amount
        self.save()
        return payment_amount
    
    def get_available_credit(self):
        """Get remaining credit available"""
        return self.credit_limit - self.current_debt
    
    def can_afford_order(self, order_amount):
        """Check if client can afford an order using balance + available credit"""
        return (self.balance + self.get_available_credit()) >= order_amount
    
    def process_order_payment(self, order_amount, preferred_method='auto'):
        """
        Process payment for an order using different strategies
        preferred_method: 'auto', 'balance', 'credit', 'mixed'
        """
        remaining_amount = order_amount
        balance_used = 0
        credit_used = 0
        
        if preferred_method == 'balance':
            # Try to pay entirely with balance
            if self.balance >= order_amount:
                balance_used = order_amount
                remaining_amount = 0
            else:
                return {
                    'success': False,
                    'error': f'Insufficient balance. Available: ${self.balance:.2f}, Required: ${order_amount:.2f}',
                    'balance_used': 0,
                    'credit_used': 0
                }
                
        elif preferred_method == 'credit':
            # Try to pay entirely with credit
            available_credit = self.get_available_credit()
            if available_credit >= order_amount:
                credit_used = order_amount
                remaining_amount = 0
            else:
                return {
                    'success': False,
                    'error': f'Insufficient credit. Available: ${available_credit:.2f}, Required: ${order_amount:.2f}',
                    'balance_used': 0,
                    'credit_used': 0
                }
                
        else:  # 'auto' or 'mixed'
            # First, use available balance
            balance_used = min(self.balance, remaining_amount)
            remaining_amount -= balance_used
            
            # Then, use credit if needed and available
            if remaining_amount > 0:
                available_credit = self.get_available_credit()
                credit_used = min(available_credit, remaining_amount)
                remaining_amount -= credit_used
        
        # Check if we can cover the full amount
        if remaining_amount > 0:
            return {
                'success': False,
                'error': f'Insufficient funds. Need additional ${remaining_amount:.2f}',
                'balance_used': 0,
                'credit_used': 0,
                'balance_available': self.balance,
                'credit_available': self.get_available_credit()
            }
        
        # Actually process the payment (deduct balance and add debt)
        if balance_used > 0:
            self.deduct_balance(balance_used)
        if credit_used > 0:
            self.add_debt(credit_used)
        
        return {
            'success': True,
            'balance_used': balance_used,
            'credit_used': credit_used,
            'remaining_balance': self.balance,
            'current_debt': self.current_debt,
            'available_credit': self.get_available_credit()
        }
    
    def create_payment_for_order(self, order, payment_method='auto'):
        """
        Create payment records for an order based on how the payment was processed
        """
        from payment.models import Payment
        
        order_amount = order.total_amount
        payment_result = self.process_order_payment(order_amount, payment_method)
        
        if not payment_result['success']:
            return {'success': False, 'error': payment_result['error']}
        
        payments_created = []
        
        # Create balance payment if balance was used
        if payment_result['balance_used'] > 0:
            balance_payment = Payment.objects.create(
                amount=payment_result['balance_used'],
                method='balance',
                client=self,
                order=order,
                status='completed',
                balance_used=payment_result['balance_used']
            )
            payments_created.append(balance_payment)
        
        # Create credit payment if credit was used
        if payment_result['credit_used'] > 0:
            credit_payment = Payment.objects.create(
                amount=payment_result['credit_used'],
                method='credit',
                client=self,
                order=order,
                status='completed',
                credit_used=payment_result['credit_used']
            )
            payments_created.append(credit_payment)
        
        return {
            'success': True,
            'payments': payments_created,
            'payment_breakdown': payment_result
        }
    
    # Validate that if type is 'branch', corporate must be set
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.type == 'branch' and not self.corporate:
            raise ValidationError({'corporate': 'Cliente corporativo debe ser establecido.'})
        if self.type == 'corporate' and self.corporate:
            raise ValidationError({'corporate': 'Cliente corporativo no puede tener un padre corporativo.'})

class ClientBillingFrecuency(models.Model):
    client = models.ForeignKey('Client', related_name='billing_frecuency', on_delete=models.CASCADE, related_query_name='client_billing_frecuency')
    frequency = models.CharField(max_length=50, choices=BILLING_FREQUENCY_CHOICES, default='monthly', verbose_name="Frecuencia de Facturación")
    billing_date = models.CharField(max_length=50, choices=BILLING_DATE_CHOICES, default='specific_date', verbose_name="Fecha de Facturación")
    
    # For specific_date billing
    specific_day = models.PositiveIntegerField(null=True, blank=True, help_text="ía del mes (1-31)", verbose_name="Día Específico")

    # For weekday_occurrence billing (e.g., "third Monday")
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES, null=True, blank=True, help_text="ía de la semana (0=Lunes, 6=Domingo)", verbose_name="Día de la Semana")
    occurrence = models.IntegerField(choices=OCCURRENCE_CHOICES, null=True, blank=True, help_text="Qué ocurrencia en el mes (1=Primera, -1=Última)", verbose_name="Ocurrencia")

    # Additional settings
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    notes = models.TextField(blank=True, null=True, help_text="Notas adicionales sobre el calendario de facturación", verbose_name="Notas")

    class Meta:
        verbose_name = "Frecuencia de Facturación"
        verbose_name_plural = "Frecuencias de Facturación"
        indexes = [
            models.Index(fields=['frequency'], name='clients_billing_frequency_idx'),
            models.Index(fields=['billing_date'], name='clients_billing_date_idx'),
            models.Index(fields=['is_active'], name='clients_billing_active_idx'),
        ]
        verbose_name = "Billing Frequency"
        verbose_name_plural = "Billing Frequencies"
    
    def __str__(self):
        if self.billing_date == 'specific_date' and self.specific_day:
            return f"{self.client.name} - {self.get_frequency_display()} el día {self.specific_day}"
        elif self.billing_date == 'weekday_occurrence' and self.weekday is not None and self.occurrence:
            weekday_name = self.get_weekday_display()
            occurrence_name = self.get_occurrence_display()
            return f"{self.client.name} - {self.get_frequency_display()} el {occurrence_name} {weekday_name}"
        elif self.billing_date == 'first_day':
            return f"{self.client.name} - {self.get_frequency_display()} el primer día del mes"
        elif self.billing_date == 'last_day':
            return f"{self.client.name} - {self.get_frequency_display()} el último día del mes"
        else:
            return f"{self.client.name} - {self.get_frequency_display()}"
    
    def clean(self):
        """Validate that the correct fields are filled based on billing_date type"""
        from django.core.exceptions import ValidationError
        
        if self.billing_date == 'specific_date':
            if not self.specific_day:
                raise ValidationError({'specific_day': 'Specific day is required when billing date is "specific_date".'})
            if self.specific_day < 1 or self.specific_day > 31:
                raise ValidationError({'specific_day': 'Specific day must be between 1 and 31.'})
        
        elif self.billing_date == 'weekday_occurrence':
            if self.weekday is None:
                raise ValidationError({'weekday': 'Weekday is required when billing date is "weekday_occurrence".'})
            if self.occurrence is None:
                raise ValidationError({'occurrence': 'Occurrence is required when billing date is "weekday_occurrence".'})
        
        # Clear unused fields based on billing_date type
        if self.billing_date != 'specific_date':
            self.specific_day = None
        if self.billing_date != 'weekday_occurrence':
            self.weekday = None
            self.occurrence = None
    
    def get_billing_info(self):
        """Return a human-readable description of the billing frequency"""
        first_day, last_day = get_first_last_day(date.today().year, date.today().month)
        frequency_display = self.get_frequency_display()
        
        if self.billing_date == 'specific_date' and self.specific_day:
            return f"Facturación {frequency_display.lower()} el día {self.specific_day} de cada período."
        elif self.billing_date == 'last_day':
            return f"Facturación {frequency_display.lower()} el último día de cada período. Este mes sería el día {last_day.day}."
        elif self.billing_date == 'first_day':
            return f"Facturación {frequency_display.lower()} el primer día de cada período."
        elif self.billing_date == 'weekday_occurrence' and self.weekday is not None and self.occurrence:
            weekday_name = self.get_weekday_display()
            occurrence_name = self.get_occurrence_display()
            return f"Facturación {frequency_display.lower()} el {occurrence_name.lower()} {weekday_name.lower()} de cada período."
        else:
            return f"Facturación {frequency_display.lower()} - configuración personalizada."
    
    def get_next_billing_candidates(self, start_date=None):
        """Get potential billing dates for the current and next periods"""
        from datetime import timedelta
        import calendar
        
        if start_date is None:
            start_date = date.today()
        
        candidates = []
        
        # Check current month and next few months depending on frequency
        months_to_check = 1
        if self.frequency == 'bimonthly':
            months_to_check = 2
        elif self.frequency == 'quarterly':
            months_to_check = 3
        elif self.frequency == 'semiannual':
            months_to_check = 6
        elif self.frequency == 'annual':
            months_to_check = 12
            
        current_date = start_date.replace(day=1)  # Start from first day of month
        
        for i in range(months_to_check + 1):  # Check one extra month for safety
            year = current_date.year
            month = current_date.month
            
            if self.billing_date == 'specific_date' and self.specific_day:
                # Handle specific day of month
                last_day_of_month = monthrange(year, month)[1]
                target_day = min(self.specific_day, last_day_of_month)
                candidate = date(year, month, target_day)
                candidates.append(candidate)
                
            elif self.billing_date == 'first_day':
                candidate = date(year, month, 1)
                candidates.append(candidate)
                
            elif self.billing_date == 'last_day':
                last_day_of_month = monthrange(year, month)[1]
                candidate = date(year, month, last_day_of_month)
                candidates.append(candidate)
                
            elif self.billing_date == 'weekday_occurrence' and self.weekday is not None and self.occurrence:
                # Find the nth occurrence of weekday in the month
                candidate = self._get_weekday_occurrence_date(year, month, self.weekday, self.occurrence)
                if candidate:
                    candidates.append(candidate)
            
            # Move to next month
            if month == 12:
                current_date = current_date.replace(year=year + 1, month=1)
            else:
                current_date = current_date.replace(month=month + 1)
        
        return sorted(candidates)
    
    def _get_weekday_occurrence_date(self, year, month, weekday, occurrence):
        """Find the nth occurrence of a weekday in a given month"""
        import calendar
        
        # Get all dates in the month for the specified weekday
        dates = []
        first_day, last_day = monthrange(year, month)
        
        for day in range(1, last_day + 1):
            date_obj = date(year, month, day)
            if date_obj.weekday() == weekday:
                dates.append(date_obj)
        
        if not dates:
            return None
            
        if occurrence == -1:  # Last occurrence
            return dates[-1]
        elif 1 <= occurrence <= len(dates):
            return dates[occurrence - 1]
        else:
            return None

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
    client = models.ForeignKey('Client', related_name='addresses', on_delete=models.CASCADE)
    street = models.CharField(max_length=255, verbose_name="Calle")
    number = models.CharField(max_length=20, blank=True, null=True, verbose_name="Número")
    interior_number = models.CharField(max_length=20, blank=True, null=True, verbose_name="Número Interior")
    neighborhood = models.CharField(max_length=100, blank=True, null=True, verbose_name="Colonia")
    city = models.CharField(max_length=100, default='Queretaro', verbose_name="Ciudad")
    state = models.CharField(max_length=100, default='Queretaro', verbose_name="Estado")
    zip_code = models.CharField(max_length=20, default='76000', verbose_name="Código Postal")
    country = models.CharField(max_length=100, default='Mexico', verbose_name="País")
    active = models.BooleanField(default=True, verbose_name="Activo")
    note = models.TextField(blank=True, null=True, verbose_name="Notas")
    type = models.CharField(max_length=50, choices=[('billing', 'Facturación'), ('shipping', 'Envío'), ('other', 'Otro')], default='other', verbose_name="Tipo")
    
    class Meta:
        verbose_name = 'Direccion'
        verbose_name_plural = 'Direcciones'
        indexes = [
            models.Index(fields=['city'], name='clients_address_city_idx'),
            models.Index(fields=['state'], name='clients_address_state_idx'),
            models.Index(fields=['active'], name='clients_address_active_idx'),
        ]

    def __str__(self):
        return f"{self.street}, {self.city}, {self.state}, {self.zip_code}, {self.country}"


class BillingData(TimeStampedModel):
    client = models.ForeignKey('Client', related_name='billing_data', on_delete=models.CASCADE)
    rfc = models.CharField(max_length=255, db_index=True)
    razon_social = models.TextField()
    uso_cfdi = models.CharField(max_length=255)
    metodo_pago = models.CharField(max_length=255, choices=PAYMENT_METHOD_CHOICES, default='other')
    address = models.ForeignKey('Address', related_name='billing_data', on_delete=models.CASCADE)
    
    class Meta:
        verbose_name = 'Datos de facturación'
        verbose_name_plural = 'Datos de facturación'
        indexes = [
            models.Index(fields=['rfc'], name='clients_billing_rfc_idx'),
        ]
    
    def __str__(self):
        return f"Billing data for {self.client.name}"
    
def get_first_last_day(year, month):
    # First day of the month
    first_day = date(year, month, 1)
    
    # Last day of the month
    last_day = date(year, month, monthrange(year, month)[1])
    
    return first_day, last_day