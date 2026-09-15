from django import forms
from clients.models import Client, Contact
from orders.models import ReceiptDeliveryMethod
from .models import Order, OrderProduct
from decimal import Decimal


class SplitOrderForm(forms.Form):
    """Form for splitting an order"""
    
    def __init__(self, *args, **kwargs):
        self.order = kwargs.pop('order', None)
        super().__init__(*args, **kwargs)
        
        if self.order:
            # Create a field for each order item
            for item in self.order.items.all():
                field_name = f'quantity_{item.id}'
                self.fields[field_name] = forms.IntegerField(
                    label=f'{item.product.name} (Disponible: {item.quantity})',
                    min_value=0,
                    max_value=item.quantity,
                    initial=0,
                    required=True,
                    widget=forms.NumberInput(attrs={
                        'class': 'pg-input',
                        'placeholder': f'Max: {item.quantity}'
                    }),
                    help_text=f'Precio unitario: ${item.unit_price} | Total disponible: ${item.get_total_price()}'
                )
    
    def clean(self):
        cleaned_data = super().clean()
        
        if not self.order:
            raise forms.ValidationError("No se encontró la orden a dividir.")
        
        # Check that at least one item is being moved
        total_items_to_move = 0
        for item in self.order.items.all():
            field_name = f'quantity_{item.id}'
            quantity = cleaned_data.get(field_name, 0)
            total_items_to_move += quantity
        
        if total_items_to_move == 0:
            raise forms.ValidationError("Debe mover al menos un producto a la nueva orden.")
        
        # Check that the source order will still have items
        for item in self.order.items.all():
            field_name = f'quantity_{item.id}'
            quantity_to_move = cleaned_data.get(field_name, 0)
            remaining = item.quantity - quantity_to_move
            
            # If this item will have 0 remaining, check if other items exist
            if remaining == 0:
                # Check if there are other items with remaining quantities
                has_other_items = False
                for other_item in self.order.items.all():
                    if other_item.id != item.id:
                        other_field_name = f'quantity_{other_item.id}'
                        other_remaining = other_item.quantity - cleaned_data.get(other_field_name, 0)
                        if other_remaining > 0:
                            has_other_items = True
                            break
                
                if not has_other_items and self.order.items.count() == 1:
                    raise forms.ValidationError(
                        "La orden original debe mantener al menos un producto. "
                        "No puede mover todos los productos."
                    )
        
        # Ensure source order will have at least one item with quantity > 0
        source_will_have_items = False
        for item in self.order.items.all():
            field_name = f'quantity_{item.id}'
            quantity_to_move = cleaned_data.get(field_name, 0)
            if item.quantity - quantity_to_move > 0:
                source_will_have_items = True
                break
        
        if not source_will_have_items:
            raise forms.ValidationError(
                "La orden original debe mantener al menos un producto con cantidad mayor a 0."
            )
        
        return cleaned_data


class OrderForm(forms.ModelForm):
    """Form for creating and updating orders"""
    
    cantidad_cobrada = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'pg-input',
            'step': '0.01',
            'placeholder': '0.00',
            'id': 'cantidad_cobrada'
        }),
        label='Cantidad Cobrada',
        help_text='Cantidad realmente cobrada al cliente (si es mayor al total, la diferencia se agregará al saldo)'
    )
    
    class Meta:
        model = Order
        fields = ['client', 'status', 'notes', 'total_amount', 'cantidad_cobrada']
        widgets = {
            'client': forms.HiddenInput(),
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


class OrderReceiptSignForm(forms.Form):
    contact_id = forms.ChoiceField(required=False, label="Contacto")
    method = forms.ChoiceField(
        choices=((ReceiptDeliveryMethod.EMAIL, "Email"),),
        initial=ReceiptDeliveryMethod.EMAIL,
        widget=forms.HiddenInput(),
    )
    contact_name = forms.CharField(max_length=100, label="Nombre")
    contact_email = forms.EmailField(label="Correo electronico")
    contact_phone = forms.CharField(max_length=20, required=False, label="Telefono")
    contact_position = forms.CharField(max_length=100, required=False, label="Puesto")
    signature_data = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, client: Client, **kwargs) -> None:
        self.client = client
        super().__init__(*args, **kwargs)
        contacts = list(client.contacts.all().order_by("name", "id"))
        self.fields["contact_id"].choices = [
            (contact.pk, self._contact_label(contact))
            for contact in contacts
        ]
        if len(contacts) == 1 and not self.is_bound:
            self._apply_contact_initial(contacts[0])

    def clean_contact_id(self) -> str:
        value = self.cleaned_data.get("contact_id") or ""
        if not value:
            return ""
        if not self.client.contacts.filter(pk=value).exists():
            raise forms.ValidationError("Contacto invalido para este cliente.")
        return value

    def clean_signature_data(self) -> str:
        value = self.cleaned_data.get("signature_data", "")
        if not value.startswith("data:image/png;base64,"):
            raise forms.ValidationError("Capture la firma antes de enviar el recibo.")
        return value

    def _apply_contact_initial(self, contact: Contact) -> None:
        self.fields["contact_id"].initial = contact.pk
        self.fields["contact_name"].initial = contact.name
        self.fields["contact_email"].initial = contact.email or ""
        self.fields["contact_phone"].initial = contact.phone or ""
        self.fields["contact_position"].initial = contact.position or ""

    def _contact_label(self, contact: Contact) -> str:
        email = contact.email or "sin correo"
        return f"{contact.name} - {email}"
