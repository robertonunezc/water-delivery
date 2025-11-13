from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import Employee


@receiver(post_save, sender=User)
def create_employee_for_new_user(sender, instance, created, **kwargs):
    """Create a linked Employee when a new User is created (if one doesn't exist).

    We allow employees without users, so only create when necessary.
    """
    if created:
        # Only create an Employee if one doesn't already exist for this user
        if not hasattr(instance, 'employee'):
            Employee.objects.create(user=instance, curp=f"curp_{instance.pk}", rfc=f"rfc_{instance.pk}", street_number='')
