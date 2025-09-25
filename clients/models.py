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