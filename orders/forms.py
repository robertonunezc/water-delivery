from django import forms
from .models import Order

class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['client', 'order_date', 'total_amount', 'status', 'notes']
        widgets = {
            'order_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'notes': forms.Textarea(attrs={'rows': 4}),
            'client': forms.Select(attrs={'class': 'form-control'}),
            'total_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'status': forms.TextInput(attrs={'class': 'form-control'}),
        }