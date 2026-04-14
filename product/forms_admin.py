from django import forms
from .models import ProductClientPrice
from clients.models import Client

class ProductClientPriceForm(forms.ModelForm):
    class Meta:
        model = ProductClientPrice
        fields = '__all__'
        widgets = {
            'client': forms.Select(attrs={'class': 'admin-autocomplete-select'}),
        }
