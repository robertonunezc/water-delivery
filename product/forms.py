from decimal import Decimal
from django import forms


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
