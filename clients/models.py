from calendar import monthrange
from datetime import date, datetime
from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from core.models import TimeStampedModel
#Client types
CLIENT_TYPE_CHOICES = [
    ('individual', 'Individual'),
    ('corporate', 'Corporate'),
    ('branch', 'Branch'),
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
    name = models.CharField(max_length=100, db_index=True)
    active = models.BooleanField(default=True)
    note = models.TextField(blank=True, null=True)
    type = models.CharField(max_length=50, choices=CLIENT_TYPE_CHOICES, default='individual')
    corporate = models.ForeignKey('Client', related_name='branches', on_delete=models.CASCADE, null=True, blank=True)
    class Meta:
        indexes = [
            models.Index(fields=['name'], name='clients_client_name_idx'),
            models.Index(fields=['active'], name='clients_client_active_idx'),
            models.Index(fields=['type'], name='clients_client_type_idx'),
        ]
    
    def __str__(self):
        return self.name

class ClientBillingFrecuency(models.Model):
    client = models.ForeignKey('Client', related_name='billing_frecuency', on_delete=models.CASCADE, related_query_name='client_billing_frecuency')
    frequency = models.CharField(max_length=50, choices=BILLING_FREQUENCY_CHOICES, default='monthly')
    billing_date = models.CharField(max_length=50, choices=BILLING_DATE_CHOICES, default='specific_date')
    
    # For specific_date billing
    specific_day = models.PositiveIntegerField(null=True, blank=True, help_text="Day of the month (1-31)")
    
    # For weekday_occurrence billing (e.g., "third Monday")
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES, null=True, blank=True, help_text="Day of the week (0=Monday, 6=Sunday)")
    occurrence = models.IntegerField(choices=OCCURRENCE_CHOICES, null=True, blank=True, help_text="Which occurrence in the month (1=First, -1=Last)")
    
    # Additional settings
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True, help_text="Additional notes about billing schedule")
    
    class Meta:
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
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=15, blank=True, null=True, db_index=True)
    position = models.CharField(max_length=100, blank=True, null=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['phone'], name='clients_contact_phone_idx'),
            models.Index(fields=['email'], name='clients_contact_email_idx'),
        ]

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Address(TimeStampedModel):
    client = models.ForeignKey('Client', related_name='addresses', on_delete=models.CASCADE)
    street = models.CharField(max_length=255)
    city = models.CharField(max_length=100, default='Queretaro')
    state = models.CharField(max_length=100, default='Queretaro')
    zip_code = models.CharField(max_length=20, default='76000')
    country = models.CharField(max_length=100, default='Mexico')
    active = models.BooleanField(default=True)
    note = models.TextField(blank=True, null=True)
    type = models.CharField(max_length=50, choices=[('billing', 'Billing'), ('shipping', 'Shipping'), ('other', 'Other')], default='other')
    
    class Meta:
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