from django.db import models

# Modelos (nombres y campos en español)
class Cliente(models.Model):
    nombre = models.CharField(max_length=100)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre


class ClienteIndividual(Cliente):
    # Campos específicos para clientes individuales pueden añadirse aquí
    def __str__(self):
        return f"Cliente individual: {self.nombre}"


class ClienteCorporativo(Cliente):
    nombre_empresa = models.CharField(max_length=255)
    identificacion_fiscal = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return f"{self.nombre_empresa} ({self.nombre})"


class Marca(Cliente):
    cliente_corporativo = models.ForeignKey(
        'ClienteCorporativo', related_name='marcas', on_delete=models.CASCADE
    )
    nombre_marca = models.CharField(max_length=255)
    industria = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.nombre_marca} ({self.nombre})"


class Contacto(models.Model):
    cliente = models.ForeignKey('Cliente', related_name='contactos', on_delete=models.CASCADE)
    nombre = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=15, blank=True, null=True)
    cargo = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.nombre} ({self.cliente.nombre})"


class Direccion(models.Model):
    cliente = models.ForeignKey('Cliente', related_name='direcciones', on_delete=models.CASCADE)
    calle = models.CharField(max_length=255)
    ciudad = models.CharField(max_length=100)
    estado = models.CharField(max_length=100)
    codigo_postal = models.CharField(max_length=20)
    pais = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.calle}, {self.ciudad}, {self.estado}, {self.codigo_postal}, {self.pais}"


class DatosFactura(models.Model):
    cliente = models.ForeignKey('Cliente', related_name='datos_facturacion', on_delete=models.CASCADE)
    nombre_facturacion = models.CharField(max_length=255)
    direccion_facturacion = models.TextField()
    identificacion_fiscal = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"Datos de facturación para {self.cliente.nombre}"