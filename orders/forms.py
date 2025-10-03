from django import forms
from .models import Order
from decimal import Decimal


class OrderForm(forms.ModelForm):
    """Form for creating and updating orders"""
    
    cantidad_cobrada = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'placeholder': '0.00',
            'id': 'cantidad_cobrada'
        }),
        label='Cantidad Cobrada',
        help_text='Cantidad realmente cobrada al cliente (si es mayor al total, la diferencia se agregará al saldo)'
    )
    
    class Meta:
        model = Order
        fields = ['client', 'order_date', 'status', 'notes', 'total_amount', 'cantidad_cobrada']
        widgets = {
            'client': forms.HiddenInput(),
            'order_date': forms.HiddenInput(),
            'status': forms.HiddenInput(),
            'notes': forms.HiddenInput(),
            'total_amount': forms.HiddenInput(),
        }
    
    def clean_cantidad_cobrada(self):
        """Validate that cantidad_cobrada is not less than total_amount"""
        cantidad_cobrada = self.cleaned_data.get('cantidad_cobrada')
        total_amount = self.cleaned_data.get('total_amount')
        
        if cantidad_cobrada is not None and total_amount is not None:
            if cantidad_cobrada < total_amount:
                raise forms.ValidationError(
                    f'La cantidad cobrada (${cantidad_cobrada:.2f}) no puede ser menor al total de la orden (${total_amount:.2f})'
                )
        
        return cantidad_cobrada
    
    def get_balance_addition(self):
        """Calculate the amount to be added to client balance"""
        cantidad_cobrada = self.cleaned_data.get('cantidad_cobrada', 0) or 0
        total_amount = self.cleaned_data.get('total_amount', 0) or 0
        
        if cantidad_cobrada > total_amount:
            return cantidad_cobrada - total_amount
        return Decimal('0.00')
