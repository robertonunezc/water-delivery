from time import timezone
from django.db import models
from django.contrib.auth.models import User
# Create your models here.

EMPLOYEE_POSITIONS = [('manager', 'Administrador'), ('driver', 'Chofer'), ('staff', 'Ventas')]

class Employee(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    curp = models.CharField(max_length=18, unique=True)
    rfc = models.CharField(max_length=13, unique=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    street_number = models.CharField(max_length=255)
    city = models.CharField(max_length=100, default='Queretaro')
    state = models.CharField(max_length=100, default='Queretaro')
    zip_code = models.CharField(max_length=20, default='76000')
    position = models.CharField(max_length=100, choices=EMPLOYEE_POSITIONS, null=True, blank=True)
    contract_type = models.CharField(max_length=50, choices=[('full_time', 'Full Time'), ('part_time', 'Part Time'), ('contract', 'Contract')], default='full_time')

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.position}"
class Transport(models.Model):
    license_plate = models.CharField(max_length=20, unique=True)
    model = models.CharField(max_length=50)
    capacity_liters = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    assigned_driver = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, limit_choices_to={'position': 'driver'})
    def __str__(self):
        return f"{self.license_plate} - {self.model} - {self.assigned_driver}"
    
class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        """By default, exclude soft-deleted records"""
        return super().get_queryset().filter(deleted_at=None)

class AllObjectsManager(models.Manager):
    """Manager to get all records including soft-deleted"""
    pass

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Default manager excludes deleted records
    objects = SoftDeleteManager()
    # Special manager to include deleted records
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        self.deleted_at = timezone.now()
        self.save()