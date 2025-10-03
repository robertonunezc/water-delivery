from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal
from .models import Client, BalanceTransaction, CreditTransaction


class ManualBalanceTransactionForm(forms.Form):
    """Form for manually adding balance to a client"""
    
    BALANCE_TRANSACTION_TYPES = [
        ('deposit', 'Depósito'),
        ('refund', 'Reembolso'),
        ('adjustment', 'Ajuste manual'),
        ('correction', 'Corrección'),
    ]
    
    client = forms.ModelChoiceField(
        queryset=Client.objects.filter(active=True),
        empty_label="Seleccionar cliente",
        label="Cliente",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    transaction_type = forms.ChoiceField(
        choices=BALANCE_TRANSACTION_TYPES,
        label="Tipo de Transacción",
        initial='deposit',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
        label="Monto",
        help_text="Cantidad a agregar al saldo del cliente",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.01'
        })
    )
    
    description = forms.CharField(
        max_length=255,
        label="Descripción",
        help_text="Breve descripción de la transacción",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: Depósito bancario por transferencia'
        })
    )
    
    notes = forms.CharField(
        required=True,
        label="Notas detalladas",
        help_text="Motivo detallado para esta transacción (OBLIGATORIO)",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Explique el motivo de esta transacción manual, incluya referencias como números de transferencia, autorizaciones, etc.'
        })
    )
    
    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount <= 0:
            raise ValidationError("El monto debe ser mayor a cero.")
        return amount
    
    def clean_notes(self):
        notes = self.cleaned_data.get('notes', '').strip()
        if len(notes) < 10:
            raise ValidationError("Las notas deben tener al menos 10 caracteres para explicar el motivo de la transacción.")
        return notes


class ManualCreditTransactionForm(forms.Form):
    """Form for manually adjusting client credit/debt"""
    
    CREDIT_TRANSACTION_TYPES = [
        ('adjustment', 'Ajuste manual de deuda'),
        ('payment', 'Pago de deuda'),
        ('forgiveness', 'Condonación de deuda'),
        ('correction', 'Corrección'),
        ('limit_change', 'Cambio de límite de crédito'),
    ]
    
    client = forms.ModelChoiceField(
        queryset=Client.objects.filter(active=True),
        empty_label="Seleccionar cliente",
        label="Cliente",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    transaction_type = forms.ChoiceField(
        choices=CREDIT_TRANSACTION_TYPES,
        label="Tipo de Transacción",
        initial='adjustment',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
        label="Monto",
        help_text="Para pagos/condonaciones: reduce la deuda. Para ajustes: puede aumentar o reducir según el tipo.",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.01'
        })
    )
    
    description = forms.CharField(
        max_length=255,
        label="Descripción",
        help_text="Breve descripción de la transacción",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: Pago en efectivo recibido'
        })
    )
    
    notes = forms.CharField(
        required=True,
        label="Notas detalladas",
        help_text="Motivo detallado para esta transacción (OBLIGATORIO)",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Explique el motivo de esta transacción manual, incluya autorizaciones, referencias, etc.'
        })
    )
    
    # Only for limit_change transactions
    new_credit_limit = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.00'),
        required=False,
        label="Nuevo límite de crédito",
        help_text="Solo para cambios de límite de crédito",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.00'
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hide credit limit field initially
        self.fields['new_credit_limit'].widget.attrs['style'] = 'display: none;'
    
    def clean(self):
        cleaned_data = super().clean()
        transaction_type = cleaned_data.get('transaction_type')
        new_credit_limit = cleaned_data.get('new_credit_limit')
        client = cleaned_data.get('client')
        amount = cleaned_data.get('amount')
        
        # Validate credit limit change
        if transaction_type == 'limit_change':
            if new_credit_limit is None:
                raise ValidationError({
                    'new_credit_limit': 'El nuevo límite de crédito es obligatorio para cambios de límite.'
                })
            if client and new_credit_limit < client.current_debt:
                raise ValidationError({
                    'new_credit_limit': f'El nuevo límite (${new_credit_limit:.2f}) no puede ser menor que la deuda actual (${client.current_debt:.2f}).'
                })
        
        # Validate debt payment doesn't exceed current debt
        if transaction_type in ['payment', 'forgiveness'] and client and amount:
            if amount > client.current_debt:
                raise ValidationError({
                    'amount': f'El monto (${amount:.2f}) no puede ser mayor que la deuda actual (${client.current_debt:.2f}).'
                })
        
        return cleaned_data
    
    def clean_notes(self):
        notes = self.cleaned_data.get('notes', '').strip()
        if len(notes) < 10:
            raise ValidationError("Las notas deben tener al menos 10 caracteres para explicar el motivo de la transacción.")
        return notes


class BulkBalanceDepositForm(forms.Form):
    """Form for adding balance to multiple clients at once"""
    
    clients = forms.ModelMultipleChoiceField(
        queryset=Client.objects.filter(active=True),
        label="Clientes",
        help_text="Seleccionar múltiples clientes para depósito masivo",
        widget=forms.CheckboxSelectMultiple()
    )
    
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
        label="Monto por cliente",
        help_text="Cantidad a agregar a cada cliente seleccionado",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.01'
        })
    )
    
    description = forms.CharField(
        max_length=255,
        label="Descripción",
        initial="Depósito masivo",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    
    notes = forms.CharField(
        required=True,
        label="Notas detalladas",
        help_text="Motivo del depósito masivo (OBLIGATORIO)",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Explique el motivo del depósito masivo...'
        })
    )
    
    def clean_clients(self):
        clients = self.cleaned_data.get('clients')
        if not clients:
            raise ValidationError("Debe seleccionar al menos un cliente.")
        if len(clients) > 50:
            raise ValidationError("No se pueden procesar más de 50 clientes a la vez.")
        return clients
    
    def clean_notes(self):
        notes = self.cleaned_data.get('notes', '').strip()
        if len(notes) < 10:
            raise ValidationError("Las notas deben tener al menos 10 caracteres.")
        return notes