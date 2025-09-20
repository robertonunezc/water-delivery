from django.db import models

# Create your models here.
class Order(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE)
    order_date = models.DateTimeField(auto_now_add=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50, default='pending')
    notes = models.TextField(blank=True, null=True)
    def __str__(self):
        return f"Order {self.id} for {self.client.name} - {self.status} ({self.total_amount})"
    class Meta:
        ordering = ['-order_date']

class OrderProduct(models.Model):
    order = models.ForeignKey('Order', related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey('products.Product', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.TextField(blank=True, null=True)
    def __str__(self):
        return f"{self.quantity} x {self.product.name} @ {self.unit_price}"
    def get_total_price(self):
        return self.quantity * self.unit_price