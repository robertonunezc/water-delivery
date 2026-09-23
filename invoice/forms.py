from django import forms
from django.core.exceptions import ValidationError
from typing import Any

from invoice.models import Invoice, InvoiceOrderLink
from invoice.services import (
    get_invoice_fiscal_owner,
    get_invoiceable_orders_for_client,
    validate_invoice_orders_total_limit,
)
from clients.models import Client
from orders.models import Order

class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['client', 'identifier', 'folio', 'amount', 'emmited_at', 'file', 'auto_amount']
        widgets = {
            'emmited_at': forms.DateInput(attrs={'type': 'date', 'class': 'pg-input'}),
            'client': forms.Select(attrs={'class': 'pg-select'}),
            'identifier': forms.TextInput(attrs={'class': 'pg-input', 'placeholder': 'SER-XXX'}),
            'folio': forms.TextInput(attrs={'class': 'pg-input', 'placeholder': 'FOL-XXX'}),
            'amount': forms.NumberInput(attrs={'class': 'pg-input', 'step': '0.01'}),
            'file': forms.ClearableFileInput(attrs={'class': 'pg-input'}),
            'auto_amount': forms.CheckboxInput(attrs={'class': 'pg-checkbox-input'}),
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
        client = cleaned_data.get('client')
        auto_amount = cleaned_data.get('auto_amount')
        amount = cleaned_data.get('amount')

        if client and not self.instance.pk:
            cleaned_data['client'] = get_invoice_fiscal_owner(client)

        if not auto_amount and amount is None:
            raise ValidationError({'amount': 'El monto es obligatorio para facturas de cálculo manual.'})
        
        return cleaned_data


class InvoiceCreateForm(InvoiceForm):
    orders = forms.ModelMultipleChoiceField(
        queryset=Order.objects.none(),
        required=True,
        label='Ventas vinculadas',
        error_messages={
            'required': 'Debe vincular al menos una venta para crear la factura.',
        },
        widget=forms.SelectMultiple(attrs={'class': 'pg-select', 'size': 8}),
    )

    class Meta(InvoiceForm.Meta):
        fields = [*InvoiceForm.Meta.fields, 'orders']

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        client = self._selected_client()
        if client is not None:
            self.fields['orders'].queryset = get_invoiceable_orders_for_client(
                client=client,
                scope='fiscal_owner',
                as_dict=False,
            )

    def _selected_client(self) -> Client | None:
        client_value = self.data.get(self.add_prefix('client')) if self.is_bound else None
        if isinstance(client_value, Client):
            return client_value
        try:
            return Client.objects.filter(pk=int(client_value)).first()
        except (TypeError, ValueError):
            return None

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        orders = cleaned_data.get('orders')
        amount = cleaned_data.get('amount')
        auto_amount = cleaned_data.get('auto_amount')

        if orders is not None and amount is not None and not auto_amount:
            try:
                validate_invoice_orders_total_limit(
                    amount,
                    [order.total_amount for order in orders],
                )
            except ValidationError as exc:
                self.add_error('orders', exc)

        return cleaned_data


class InvoiceOrderLinkForm(forms.ModelForm):
    class Meta:
        model = InvoiceOrderLink
        fields = ['order']
        widgets = {
            'order': forms.Select(attrs={'class': 'pg-select'}),
        }

    def __init__(self, *args, **kwargs):
        client = kwargs.pop('client', None)
        exclude_order_id = kwargs.pop('exclude_order_id', None)
        scope = kwargs.pop('scope', 'exact')
        super().__init__(*args, **kwargs)
        
        if client:
            self.fields['order'].queryset = get_invoiceable_orders_for_client(
                client=client,
                include_order_id=exclude_order_id,
                scope=scope,
                as_dict=False
            )
        else:
            from orders.models import Order
            self.fields['order'].queryset = Order.objects.none()
