from calendar import monthrange
from datetime import date, timedelta
from typing import Optional, List

from django.db import models
from django.forms import ValidationError

from core.models import TimeStampedModel
from core.utils import get_first_last_day_of_month

# Billing frequency and date choices
BILLING_FREQUENCY_CHOICES = [
    ('when_delivery', 'Contra entrega'),
    ('weekly', 'Semanal'),
  #  ('biweekly', 'Quincenal'),
    ('monthly', 'Mensual'),
]
BILLING_DATE_CHOICES = [
    ('specific_date', 'Fecha específica del mes'),
    ('last_day', 'Último día del mes'),
    ('first_day', 'Primer día del mes'),
    ('weekday_occurrence', 'Día específico de la semana'),
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

# Create your models here.
class BillingRecord(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='billing_records', verbose_name='Cliente')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto")
    identifier = models.CharField(max_length=100, unique=True, verbose_name="Serie")
    folio = models.CharField(max_length=100, unique=True, verbose_name="Folio")
    date = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True)
    file = models.FileField(upload_to='billing_files/', blank=True, null=True)
    emmited_at = models.DateTimeField(blank=True, null=True, verbose_name="Fecha de emisión")
    def __str__(self):
        return f"Factura Emitida #{self.id} para {self.client.name} - {self.amount}"
    class Meta:
        ordering = ['-date']
        verbose_name = 'Facturación'
        verbose_name_plural = 'Facturas Emitidas'
    # def clean(self):
    #     # Check if there is a billing record from this client without billing orders
    #     if self.pk is None:  # Only check for new records
    #         existing_records = BillingRecord.objects.filter(client=self.client)
    #         for record in existing_records:
    #             if not record.billing_orders.exists():
    #                 raise ValidationError(f"El cliente {self.client.name} ya tiene un registro de facturación sin ventas asociadas (ID: {record.id}). Por favor, complete ese registro antes de crear uno nuevo.")
class BillingOrder(TimeStampedModel):
    billing_record = models.ForeignKey('billing.BillingRecord', on_delete=models.CASCADE, related_name='billing_orders', verbose_name='Registro de Facturación')
    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='billing_orders', verbose_name='Venta')
    is_paid = models.BooleanField(default=False, verbose_name='Pagado Totalmente')
    partially_paid = models.BooleanField(default=False, verbose_name='Pago parcial')

    def __str__(self):
        return f"Agregar venta a factura #{self.id} para Pedido {self.order.id} - Pagado: {self.is_paid}"
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Agregar venta a factura'
        verbose_name_plural = 'Agregar ventas a factura'

class ClientBillingFrecuency(TimeStampedModel):
    client = models.OneToOneField('clients.Client', related_name='billing_frecuency', on_delete=models.CASCADE, related_query_name='client_billing_frecuency')
    frequency = models.CharField(max_length=50, choices=BILLING_FREQUENCY_CHOICES, default='monthly', verbose_name="Frecuencia de Facturación")
    billing_date = models.CharField(max_length=50, choices=BILLING_DATE_CHOICES, null=True, blank=True, verbose_name="Fecha de Facturación")

    # For specific_date billing
    specific_day = models.PositiveIntegerField(null=True, blank=True, help_text="Día del mes (1-31)", verbose_name="Día Específico")

    # For weekday_occurrence billing (e.g., "third Monday")
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES, null=True, blank=True, help_text="ía de la semana (0=Lunes, 6=Domingo)", verbose_name="Día de la Semana")
    occurrence = models.IntegerField(choices=OCCURRENCE_CHOICES, null=True, blank=True, help_text="Qué ocurrencia en el mes (1=Primera, -1=Última)", verbose_name="Ocurrencia")

    # Additional settings
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    notes = models.TextField(blank=True, null=True, help_text="Notas adicionales sobre el calendario de facturación", verbose_name="Notas")
    next_billing_date = models.DateField(null=True, blank=True, verbose_name="Próxima Fecha de Facturación")

    class Meta:
        db_table = 'clients_clientbillingfrecuency'  # Keep existing table name to avoid migration
        verbose_name = "Frecuencia de Facturación"
        verbose_name_plural = "Frecuencias de Facturación"
        indexes = [
            models.Index(fields=['frequency'], name='clients_billing_frequency_idx'),
            models.Index(fields=['billing_date'], name='clients_billing_date_idx'),
            models.Index(fields=['is_active'], name='clients_billing_active_idx'),
        ]

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
        # Validate a client can have only one active billing frequency
        if self.is_active:
            active_frequencies = ClientBillingFrecuency.objects.filter(client=self.client, is_active=True).exclude(id=self.id)
            if active_frequencies.exists():
                raise ValidationError({'is_active': 'El cliente ya tiene una frecuencia de facturación activa.'})
        if self.client.requires_billing is False:
            raise ValidationError({'client': 'No se puede asignar una frecuencia de facturación a un cliente que no requiere facturación.'})
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

    def save(self, *args, **kwargs):
        """Override save to ensure clean is called and calculate next billing date"""
        self.clean()

        # Calculate next_billing_date before saving
        first_day, last_day = get_first_last_day_of_month(date.today().year, date.today().month)
        billing_dates = self.get_billing_dates_in_period(first_day, last_day)
        if billing_dates:
            self.next_billing_date = billing_dates[0]

        # Save once with all data
        super().save(*args, **kwargs)

    def get_billing_info(self):
        """Return a human-readable description of the billing frequency"""
        return f"Facturación en la fecha  {self.next_billing_date} ."

    def get_next_billing_candidates(self, start_date=None):
        """Get potential billing dates for the current and next periods"""
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

    def should_bill_in_period(self, start_date: date, end_date: date) -> bool:
        """
        Determine if client should be billed within the date range.

        Args:
            start_date: Start of billing period
            end_date: End of billing period

        Returns:
            True if client should be billed in this period
        """
        billing_dates = self.get_billing_dates_in_period(start_date, end_date)
        return len(billing_dates) > 0

    def get_billing_dates_in_period(self, start_date: date, end_date: date) -> List[date]:
        """
        Get all billing dates that fall within the specified period.

        Args:
            start_date: Start of billing period
            end_date: End of billing period

        Returns:
            List of dates when client should be billed
        """
        from core.utils import is_business_day, adjust_to_business_day

        billing_dates = []

        if self.frequency == 'when_delivery':
            # For contraentrega, check orders and add 1 business day
            # This will be handled at the service layer since it requires order data
            return []  # Service layer will handle this

        elif self.frequency == 'weekly':
            # Weekly: Check if configured weekday falls in the period
            # weekday field: 0=Monday, 6=Sunday (but only 0-4 allowed)
            if self.weekday is None or self.weekday > 4:
                return []

            current = start_date
            while current <= end_date:
                if current.weekday() == self.weekday and is_business_day(current):
                    billing_dates.append(current)
                current += timedelta(days=1)

        elif self.frequency == 'biweekly':
            # Quincenal: 15th and last day of each month
            current_month_start = start_date.replace(day=1)
            end_month = end_date.replace(day=1)

            while current_month_start <= end_month:
                # 15th of month (or next business day)
                fifteenth = current_month_start.replace(day=15)
                adjusted_15th = adjust_to_business_day(fifteenth)
                if start_date <= adjusted_15th <= end_date:
                    billing_dates.append(adjusted_15th)

                # Last business day of month
                last_day = monthrange(current_month_start.year, current_month_start.month)[1]
                last_date = current_month_start.replace(day=last_day)

                # Find last business day
                while not is_business_day(last_date):
                    last_date -= timedelta(days=1)

                if start_date <= last_date <= end_date:
                    billing_dates.append(last_date)

                # Move to next month
                if current_month_start.month == 12:
                    current_month_start = current_month_start.replace(year=current_month_start.year + 1, month=1)
                else:
                    current_month_start = current_month_start.replace(month=current_month_start.month + 1)

        elif self.frequency == 'monthly':
            # Monthly with various subtypes
            current_month_start = start_date.replace(day=1)
            end_month = end_date.replace(day=1)

            while current_month_start <= end_month:
                billing_date = self._get_monthly_billing_date(current_month_start)

                if billing_date and start_date <= billing_date <= end_date:
                    billing_dates.append(billing_date)

                # Move to next month
                if current_month_start.month == 12:
                    current_month_start = current_month_start.replace(year=current_month_start.year + 1, month=1)
                else:
                    current_month_start = current_month_start.replace(month=current_month_start.month + 1)

        return sorted(set(billing_dates))  # Remove duplicates and sort

    def _get_monthly_billing_date(self, month_start: date) -> Optional[date]:
        """
        Get the billing date for a specific month based on monthly billing configuration.

        Args:
            month_start: First day of the month to calculate for

        Returns:
            Billing date for that month, or None if invalid
        """
        from core.utils import is_business_day, adjust_to_business_day, next_business_day

        if self.billing_date == 'specific_date':
            # Specific day of month (e.g., 25th)
            if not self.specific_day:
                return None

            last_day = monthrange(month_start.year, month_start.month)[1]
            day = min(self.specific_day, last_day)  # Handle Feb 31 -> Feb 28
            target = month_start.replace(day=day)
            return adjust_to_business_day(target)

        elif self.billing_date == 'first_day':
            # First business day of month
            first_day = month_start
            return next_business_day(first_day)

        elif self.billing_date == 'last_day':
            # Last business day of month
            last_day_num = monthrange(month_start.year, month_start.month)[1]
            last_day = month_start.replace(day=last_day_num)

            while not is_business_day(last_day):
                last_day -= timedelta(days=1)

            return last_day

        elif self.billing_date == 'weekday_occurrence':
            # Nth occurrence of weekday (e.g., 3rd Thursday)
            return self._get_weekday_occurrence_date(
                month_start.year,
                month_start.month,
                self.weekday,
                self.occurrence
            )

        return None


class BillingFrequencyReport(models.Model):
    """
    Proxy model to create an admin menu entry for the billing frequency report.
    This model has no database table - it's just for admin navigation.
    """
    class Meta:
        managed = False  # No database table
        verbose_name = "Reporte de Frecuencia de Facturación"
        verbose_name_plural = "Reportes de Frecuencia de Facturación"
        app_label = 'billing'
        # Permissions for access control
        default_permissions = ('view',)
        permissions = [
            ('view_billing_frequency_report', 'Can view billing frequency report'),
        ]
