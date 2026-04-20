from django.db import models
from django_tenants.models import TenantMixin, DomainMixin

from core.models import TimeStampedModel
# Create your models here.
class ClientTenant(TenantMixin, TimeStampedModel):
    name = models.CharField(max_length=100)
    paid_until =  models.DateField()
    on_trial = models.BooleanField()
    created_on = models.DateField(auto_now_add=True)

    # default true, schema will be automatically created and synced when it is saved
    auto_create_schema = True

    def __str__(self):
        return self.name
    
class Domain(DomainMixin, TimeStampedModel):
    pass