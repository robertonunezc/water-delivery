from decimal import Decimal

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Product, ProductCategory, ProductClientPrice


class ProductForm(forms.ModelForm):
    add_to_all_clients = forms.BooleanField(
        required=False,
        initial=False,
        label="Agregar para todos los clientes existentes",
        help_text="Si se activa, este producto se asignará a todos los clientes existentes con el precio base configurado.",
        widget=forms.CheckboxInput(attrs={'class': 'pg-checkbox-input'})
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
            'name': forms.TextInput(attrs={'class': 'pg-input'}),
            'presentation': forms.TextInput(attrs={'class': 'pg-input'}),
            'unit_of_measure': forms.Select(attrs={'class': 'pg-select'}),
            'price': forms.NumberInput(attrs={'class': 'pg-input', 'step': '0.01'}),
            'category': forms.Select(attrs={'class': 'pg-select'}),
            'note': forms.Textarea(attrs={'class': 'pg-input', 'rows': 3}),
            'active': forms.CheckboxInput(attrs={'class': 'pg-checkbox-input'}),
        }


class ProductClientPriceForm(forms.ModelForm):
    class Meta:
        model = ProductClientPrice
        fields = ['client', 'price', 'active', 'note']
        widgets = {
            'client': forms.Select(attrs={'class': 'pg-select'}),
            'price': forms.NumberInput(attrs={'class': 'pg-input', 'step': '0.01'}),
            'active': forms.CheckboxInput(attrs={'class': 'pg-checkbox-input'}),
            'note': forms.TextInput(attrs={'class': 'pg-input'}),
        }


class ProductClientPriceBaseFormSet(BaseInlineFormSet):
    def clean(self) -> None:
        super().clean()
        seen_client_ids: set[int] = set()

        for form in self.forms:
            if not hasattr(form, 'cleaned_data') or not form.cleaned_data:
                continue
            if form.cleaned_data.get('DELETE'):
                continue

            client = form.cleaned_data.get('client')
            if client is None:
                continue

            if client.pk in seen_client_ids:
                raise forms.ValidationError(
                    'No se puede asignar el mismo cliente más de una vez para este producto.'
                )
            seen_client_ids.add(client.pk)

    def save_new(self, form: forms.ModelForm, commit: bool = True) -> ProductClientPrice:
        new_price = form.save(commit=False)
        restored_price = ProductClientPrice.all_objects.filter(
            product=self.instance,
            client=new_price.client,
            deleted_at__isnull=False,
        ).first()

        if restored_price is None:
            return super().save_new(form, commit=commit)

        restored_price.price = new_price.price
        restored_price.note = new_price.note
        restored_price.active = new_price.active
        restored_price.deleted_at = None

        if commit:
            restored_price.save(update_fields=['price', 'note', 'active', 'deleted_at', 'updated_at'])

        return restored_price


class ProductCategoryForm(forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = ['name']
        labels = {
            'name': 'Nombre',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'pg-input', 'placeholder': 'Nombre de la categoría'}),
        }

    def clean_name(self) -> str:
        name = self.cleaned_data['name'].strip()
        queryset = ProductCategory.objects.filter(name__iexact=name)

        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise forms.ValidationError('Ya existe una categoría con este nombre.')

        return name


ProductClientPriceFormSet = inlineformset_factory(
    Product,
    ProductClientPrice,
    form=ProductClientPriceForm,
    formset=ProductClientPriceBaseFormSet,
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
