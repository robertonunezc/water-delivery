from time import timezone
from django.db import models

# Create your models here.
class User(models.Model):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.username
    
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