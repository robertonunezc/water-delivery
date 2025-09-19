from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from core.models import TimeStampedModel

class Client(TimeStampedModel):
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    def __str__(self):
        return self.name

class IndividualClient(TimeStampedModel):
    client = models.OneToOneField('Client', related_name='individual_client', on_delete=models.CASCADE)
    # individual-specific fields

    def __str__(self):
        return f"Individual: {self.client.name}"


class CorporateClient(TimeStampedModel):
    company_name = models.CharField(max_length=255)
    tax_id = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return f"{self.company_name} ({self.client.name})"


class Branch(TimeStampedModel):
    client = models.OneToOneField('Client', related_name='branch', on_delete=models.CASCADE)
    corporate_client = models.ForeignKey('CorporateClient', related_name='branches', on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.branch_name} ({self.client.name})"


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