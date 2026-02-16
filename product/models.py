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
        ordering = ['name']
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
        permissions = [
            ("min_max_inventory", "Can control min max inventory quantity"),
        ]

    name = models.CharField(max_length=200, verbose_name="Nombre", unique=True)
    presentation = models.CharField(max_length=200, help_text="20, 1, 500", verbose_name="Presentación")
    unit_of_measure = models.IntegerField(choices=UNIT_CHOICES, default=0, verbose_name="Unidad de Medida")
    image = models.FileField(null=True, blank=True, upload_to='product_images/', verbose_name="Imagen")
    #order = models.IntegerField(default=0, verbose_name="Orden")
    #quantity = models.IntegerField(default=0, verbose_name="Cantidad")
    category = models.ForeignKey(ProductCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='products', verbose_name="Categoría")
    min_inventory = models.IntegerField(default=0, help_text='Minimum inventory quantity', verbose_name="Cantidad mínima en inventario")
    max_inventory = models.IntegerField(default=0, help_text='Maximum inventory quantity', verbose_name="Cantidad máxima en inventario")
    note = models.TextField(blank=True, null=True, verbose_name="Notas")
    price = models.FloatField(default=0.0, verbose_name="Precio base", help_text="Precio base del producto, se puede sobreescribir por cliente en la sección de clientes")
    
    def __str__(self):
        return "{} {} {}".format(self.name, self.presentation, self.get_unit_of_measure_display())

    def get_full_name(self):
        return "{} {} {}".format(self.name, self.presentation, self.get_unit_of_measure_display())
    
    def get_price_display(self):
        return self.prices.first().price if self.prices.exists() else "N/A"

    def get_presentation_display(self):
        return "{} {}".format(self.presentation, self.get_unit_of_measure_display())

class ProductClientPrice(models.Model):
    class Meta: 
        verbose_name_plural = 'Precios de productos'
        unique_together = ('product', 'client',)


    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name="product", related_name='prices')
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='product_prices', verbose_name="Cliente" )
    price = models.FloatField(default=0.0, verbose_name="Precio")
    note = models.TextField(blank=True, null=True, verbose_name="Notas")
    until_date = models.DateField(null=True, blank=True, help_text="Fecha hasta la cual es valido este precio, dejar en blanco para que sea indefinido", verbose_name="Fecha de Validez")
    def __str__(self):
        return "{} {} - ${}".format(self.product, self.client, self.price)
    def get_price_display(self):
        return "${:,.2f}".format(self.price) if hasattr(self, 'price') else "N/A"

