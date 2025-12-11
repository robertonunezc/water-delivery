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
        ('payment_from_balance', 'Pago con Saldo'),
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
        if transaction_type in ['payment', 'forgiveness', 'payment_from_balance'] and client and amount:
            if amount > client.current_debt:
                raise ValidationError({
                    'amount': f'El monto (${amount:.2f}) no puede ser mayor que la deuda actual (${client.current_debt:.2f}).'
                })
        
        # Validate balance availability for payment_from_balance
        if transaction_type == 'payment_from_balance' and client and amount:
            if amount > client.balance:
                raise ValidationError({
                    'amount': f'Saldo insuficiente. Disponible: ${client.balance:.2f}, Requerido: ${amount:.2f}'
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


class ClientBillingDataForm(forms.ModelForm):
    """Form for managing client billing data and billing frequency together"""
    
    class Meta:
        from .models import BillingData
        model = BillingData
        fields = ['rfc', 'curp', 'razon_social', 'regimen_fiscal', 'uso_cfdi', 'metodo_pago', 'address']
        widgets = {
            'rfc': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'RFC (13 caracteres)',
                'maxlength': '13'
            }),
            'curp': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'CURP (18 caracteres)',
                'maxlength': '18'
            }),
            'razon_social': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Razón social completa'
            }),
            'regimen_fiscal': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ejemplo: 601 - General de Ley Personas Morales'
            }),
            'uso_cfdi': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ejemplo: G03 - Gastos en general'
            }),
            'metodo_pago': forms.Select(attrs={'class': 'form-control'}),
            'address': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'rfc': 'RFC',
            'curp': 'CURP',
            'razon_social': 'Razón Social',
            'regimen_fiscal': 'Régimen Fiscal',
            'uso_cfdi': 'Uso de CFDI',
            'metodo_pago': 'Método de Pago',
            'address': 'Dirección de Facturación',
        }
    
    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        if client:
            # Filter addresses to only show those belonging to this client
            self.fields['address'].queryset = client.addresses.filter(deleted_at__isnull=True)
        else:
            self.fields['address'].queryset = self.fields['address'].queryset.none()


class ClientBillingFrequencyForm(forms.ModelForm):
    """Form for managing client billing frequency"""
    
    class Meta:
        from .models import ClientBillingFrecuency
        model = ClientBillingFrecuency
        fields = ['frequency', 'billing_date', 'specific_day', 'weekday', 'occurrence', 'is_active', 'notes']
        widgets = {
            'frequency': forms.Select(attrs={'class': 'form-control'}),
            'billing_date': forms.Select(attrs={'class': 'form-control'}),
            'specific_day': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '31',
                'placeholder': 'Día del mes (1-31)'
            }),
            'weekday': forms.Select(attrs={'class': 'form-control'}),
            'occurrence': forms.Select(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Notas adicionales sobre la frecuencia de facturación'
            }),
        }
        labels = {
            'frequency': 'Frecuencia de Facturación',
            'billing_date': 'Tipo de Fecha de Facturación',
            'specific_day': 'Día Específico del Mes',
            'weekday': 'Día de la Semana',
            'occurrence': 'Ocurrencia en el Mes',
            'is_active': 'Activo',
            'notes': 'Notas',
        }
    
    def clean(self):
        cleaned_data = super().clean()
        billing_date = cleaned_data.get('billing_date')
        specific_day = cleaned_data.get('specific_day')
        weekday = cleaned_data.get('weekday')
        occurrence = cleaned_data.get('occurrence')
        
        # Validate specific_day is provided when billing_date is 'specific_date'
        if billing_date == 'specific_date' and not specific_day:
            raise ValidationError({
                'specific_day': 'El día específico es obligatorio cuando se selecciona "Fecha específica del mes".'
            })
        
        # Validate weekday and occurrence are provided when billing_date is 'weekday_occurrence'
        if billing_date == 'weekday_occurrence':
            if weekday is None:
                raise ValidationError({
                    'weekday': 'El día de la semana es obligatorio cuando se selecciona "Día específico de la semana".'
                })
            if occurrence is None:
                raise ValidationError({
                    'occurrence': 'La ocurrencia es obligatoria cuando se selecciona "Día específico de la semana".'
                })
        
        return cleaned_data