from django import forms
from django.core.exceptions import ValidationError
from invoice.models import Invoice, InvoiceOrderLink
from invoice.services import get_invoiceable_orders_for_client
from clients.models import Client

class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['client', 'identifier', 'folio', 'amount', 'emmited_at', 'file', 'auto_amount']
        widgets = {
            'emmited_at': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'client': forms.Select(attrs={'class': 'form-select'}),
            'identifier': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'SER-XXX'}),
            'folio': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'FOL-XXX'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'file': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'auto_amount': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If the invoice has auto_amount=True, the amount field should be read-only and not required
        if self.instance and self.instance.pk:
            # Client should be read-only for existing invoices to prevent data inconsistency
            self.fields['client'].disabled = True
            if self.instance.auto_amount:
                self.fields['amount'].disabled = True
                self.fields['amount'].required = False
                self.fields['auto_amount'].disabled = True

    def clean(self):
        cleaned_data = super().clean()
        auto_amount = cleaned_data.get('auto_amount')
        amount = cleaned_data.get('amount')

        if not auto_amount and amount is None:
            raise ValidationError({'amount': 'El monto es obligatorio para facturas de cálculo manual.'})
        
        return cleaned_data


class InvoiceOrderLinkForm(forms.ModelForm):
    class Meta:
        model = InvoiceOrderLink
        fields = ['order']
        widgets = {
            'order': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        client = kwargs.pop('client', None)
        exclude_order_id = kwargs.pop('exclude_order_id', None)
        super().__init__(*args, **kwargs)
        
        if client:
            self.fields['order'].queryset = get_invoiceable_orders_for_client(
                client=client,
                include_order_id=exclude_order_id,
                as_dict=False
            )
        else:
            from orders.models import Order
            self.fields['order'].queryset = Order.objects.none()
