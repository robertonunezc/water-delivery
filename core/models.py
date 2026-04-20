from django.utils import timezone
from django.conf import settings
from django.db import models
# Create your models here.

class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        """By default, exclude soft-deleted records"""
        return super().get_queryset().filter(deleted_at=None)


class AllObjectsManager(models.Manager):
    """Manager to get all records including soft-deleted"""
    pass


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True )
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True )
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

EMPLOYEE_POSITIONS = [('manager', 'Administrador'), ('driver', 'Chofer'), ('staff', 'Ventas')]

class Employee(TimeStampedModel):
    # Allow employees without a linked User account (some employees don't access the system)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    nombre = models.CharField(max_length=100, default='')
    apellidos = models.CharField(max_length=100, default='')
    sexo = models.CharField(max_length=10, choices=[('M', 'Masculino'), ('F', 'Femenino')], null=True, blank=True)
    curp = models.CharField(max_length=18, unique=True)
    rfc = models.CharField(max_length=13, unique=True)
    phone = models.CharField(max_length=15, blank=True, null=True, verbose_name="Teléfono")
    street_number = models.CharField(max_length=255, verbose_name="Calle y Número")
    city = models.CharField(max_length=100, default='Queretaro', verbose_name="Ciudad")
    state = models.CharField(max_length=100, default='Queretaro', verbose_name="Estado")
    zip_code = models.CharField(max_length=20, default='76000', verbose_name="Código Postal")
    position = models.CharField(max_length=100, choices=EMPLOYEE_POSITIONS, null=True, blank=True, verbose_name="Puesto")
    contract_type = models.CharField(max_length=50, choices=[('full_time', 'Tiempo Completo'), ('part_time', 'Tiempo Parcial'), ('contract', 'Contrato')], default='full_time')

    def __str__(self):
        if self.user:
            return f"{self.user.get_full_name()} - {self.position}"
        return f"{self.nombre} {self.apellidos} - {self.position}"
    class Meta:
        verbose_name = "Empleado"
        verbose_name_plural = "Empleados"
class Transport(TimeStampedModel):
    license_plate = models.CharField(max_length=20, unique=True, verbose_name="Placa")
    model = models.CharField(max_length=50, verbose_name="Modelo")
    capacity_liters = models.PositiveIntegerField(verbose_name="Capacidad (litros)")
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    assigned_driver = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True,  verbose_name="Chofer Asignado")
    def __str__(self):
        return f"{self.license_plate} - {self.model} - {self.assigned_driver}"
    class Meta:
        verbose_name = "Vehículo"
        verbose_name_plural = "Vehículos"

class NonWorkingDay(TimeStampedModel):
    date = models.DateField(unique=True, verbose_name="Fecha")
    name = models.CharField(max_length=200, verbose_name="Nombre del Día Festivo")
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    notes = models.TextField(blank=True, verbose_name="Notas")

    class Meta:
        verbose_name = "Día No Laborable"
        verbose_name_plural = "Días No Laborables"
        ordering = ['date']
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['is_active', 'date']),
        ]

    def __str__(self):
        return f"{self.date.strftime('%d/%m/%Y')} - {self.name}"
