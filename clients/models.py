from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from core.models import TimeStampedModel
#Client types
CLIENT_TYPE_CHOICES = [
    ('individual', 'Individual'),
    ('corporate', 'Corporate'),
    ('branch', 'Branch'),
]
class Client(TimeStampedModel):
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    note = models.TextField(blank=True, null=True)
    type = models.CharField(max_length=50, choices=CLIENT_TYPE_CHOICES, default='individual')
    corporate = models.ForeignKey('Client', related_name='branches', on_delete=models.CASCADE, null=True, blank=True)
    def __str__(self):
        return self.name


class Contact(TimeStampedModel):
    client = models.ForeignKey('Client', related_name='contacts', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    position = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.client.name})"


class Address(TimeStampedModel):
    client = models.ForeignKey('Client', related_name='addresses', on_delete=models.CASCADE)
    street = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    type = models.CharField(max_length=50, choices=[('billing', 'Billing'), ('shipping', 'Shipping'), ('other', 'Other')], default='other')

    def __str__(self):
        return f"{self.street}, {self.city}, {self.state}, {self.zip_code}, {self.country}"


class BillingData(TimeStampedModel):
    client = models.ForeignKey('Client', related_name='billing_data', on_delete=models.CASCADE)
    rfc = models.CharField(max_length=255)
    razon_social = models.TextField()
    uso_cfdi = models.CharField(max_length=255)
    metodo_pago = models.CharField(max_length=255)
    address = models.ForeignKey('Address', related_name='billing_data', on_delete=models.CASCADE)
    def __str__(self):
        return f"Billing data for {self.client.name}"