from decimal import Decimal
from django import forms
from django.forms import inlineformset_factory
from .models import Product, ProductClientPrice


class ProductForm(forms.ModelForm):
    add_to_all_clients = forms.BooleanField(
        required=False,
        initial=False,
        label="Agregar para todos los clientes existentes",
        help_text="Si se activa, este producto se asignará a todos los clientes existentes con el precio base configurado.",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    class Meta:
        model = Product
        fields = [
            'name',
            'presentation',
            'unit_of_measure',
            'price',
            'category',
            'note',
            'active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'presentation': forms.TextInput(attrs={'class': 'form-control'}),
            'unit_of_measure': forms.Select(attrs={'class': 'form-select'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ProductClientPriceForm(forms.ModelForm):
    class Meta:
        model = ProductClientPrice
        fields = ['client', 'price', 'active', 'note']
        widgets = {
            'client': forms.Select(attrs={'class': 'form-select'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'note': forms.TextInput(attrs={'class': 'form-control'}),
        }

ProductClientPriceFormSet = inlineformset_factory(
    Product,
    ProductClientPrice,
    form=ProductClientPriceForm,
    extra=1,
    can_delete=True
)

class BulkProductPriceUpdateForm(forms.Form):
    MODE_CHOICES = (
        ('amount', 'Incremento fijo'),
        ('percent', 'Porcentaje'),
    )

    product_id = forms.IntegerField(widget=forms.HiddenInput())
    mode = forms.ChoiceField(choices=MODE_CHOICES, label='Tipo de incremento')
    value = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), label='Valor')

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('mode')
        value = cleaned.get('value')
        if mode not in dict(self.MODE_CHOICES):
            raise forms.ValidationError('Seleccione un tipo de incremento válido.')
        if value is None or value <= 0:
            raise forms.ValidationError('El valor debe ser mayor que cero.')
        return cleaned


class ProductsCSVImportForm(forms.Form):
    """Upload form for bulk importing products and client prices from CSV."""

    csv_file = forms.FileField(
        label='Archivo CSV de productos y precios',
        help_text='Sube un archivo .csv con la plantilla de productos y precios por cliente.',
    )

    def clean_csv_file(self):
        csv_file = self.cleaned_data['csv_file']
        if not csv_file.name.lower().endswith('.csv'):
            raise forms.ValidationError('El archivo debe tener extensión .csv')
        return csv_file
