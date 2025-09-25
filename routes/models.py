from django.db import models

# Create your models here.
class Route(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class RouteEmployee(models.Model):
    route = models.ForeignKey(Route, related_name='route_employees', on_delete=models.CASCADE)
    employee = models.ForeignKey('core.Employee', related_name='employee_routes', on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=50, choices=[('active', 'Active'), ('inactive', 'Inactive')], default='active')
    class Meta:
        unique_together = ('route', 'employee')

    def __str__(self):
        return f"{self.employee} assigned to {self.route}"

class RouteClient(models.Model):
    route = models.ForeignKey(Route, related_name='route_clients', on_delete=models.CASCADE)
    client = models.ForeignKey('clients.Client', related_name='client_routes', on_delete=models.CASCADE)
    sequence = models.PositiveIntegerField()
    note = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('route', 'client')
        ordering = ['sequence']

    def __str__(self):
        return f"{self.client} in {self.route} at position {self.sequence}"