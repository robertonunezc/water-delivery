from django.db import models

UNIT_CHOICES = (
    (0, 'not applicable'),
    (1, 'lt'),
    (2, 'ml'),
    (3, 'm'),
    (4, 'pulg'),
    (6, 'cm'),
    (7, 'mg'),
    (8, 'kg'),
    (9, 'g'),
    (5, 'pieza'),
)

# Create your models here.
class ProductCategory(models.Model):
    name = models.CharField(max_length=50, default="General")

    def __str__(self):
        return self.name


class Product(models.Model):
    class Meta:
        ordering = ['order']
        permissions = [
            ("min_max_inventory", "Can control min max inventory quantity"),
        ]

    name = models.CharField(max_length=200)
    presentation = models.CharField(max_length=200)
    unit_of_measure = models.IntegerField(choices=UNIT_CHOICES, default=0)
    image = models.FileField(null=True, blank=True, upload_to='product_images/')
    order = models.IntegerField(default=0)
    quantity = models.IntegerField(default=0)
    category = models.ForeignKey(ProductCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    min_inventory = models.IntegerField(default=0, help_text='Minimum inventory quantity')
    max_inventory = models.IntegerField(default=0, help_text='Maximum inventory quantity')

    def __str__(self):
        return "{} {} {}".format(self.name, self.presentation, self.get_unit_of_measure_display())

    def get_full_name(self):
        return self.__str__()

class ProductClientPrice(models.Model):
    class Meta:
        verbose_name_plural = 'Product prices'
        unique_together = ('product', 'client',)

    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, verbose_name="client")
    price = models.FloatField(default=0.0)

    def __str__(self):
        return "{} {} - ${}".format(self.product, self.client, self.price)

