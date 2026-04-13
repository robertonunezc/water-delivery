import datetime
from django import forms
from django.core.exceptions import ValidationError
from django.contrib import messages
from .models import RouteClient, Route


class RouteClientForm(forms.ModelForm):
    """Custom form for RouteClient with validation for existing assignments"""

    anchor_date = forms.DateField(
        required=False,
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'],
    )

    class Meta:
        model = RouteClient
        fields = ['client', 'sequence', 'interval_weeks', 'anchor_date', 'is_active', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'anchor_date' in self.fields:
            self.fields['anchor_date'].localize = False
            # Default empty field to today
            instance = kwargs.get('instance')
            if not instance or not instance.anchor_date:
                self.fields['anchor_date'].initial = datetime.date.today()

    def clean_anchor_date(self):
        return self.cleaned_data.get('anchor_date') or datetime.date.today()


class RouteClientInlineForm(RouteClientForm):
    """Specialized form for inline admin usage"""
    
    confirm_duplicate_assignment = forms.BooleanField(
        required=False,
        label="Confirmar asignación",
        help_text="Cliente ya asignado a otra ruta. Marque para confirmar.",
        widget=forms.CheckboxInput(attrs={
            'class': 'confirm-duplicate-checkbox',
            'style': 'display: none;'  # Hidden by default, shown via JavaScript
        })
    )
    
    class Meta(RouteClientForm.Meta):
        fields = RouteClientForm.Meta.fields + ['confirm_duplicate_assignment']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Move confirmation field to the end
        if 'confirm_duplicate_assignment' in self.fields:
            confirm_field = self.fields.pop('confirm_duplicate_assignment')
            self.fields['confirm_duplicate_assignment'] = confirm_field


class RouteForm(forms.ModelForm):
    """Custom form for Route model with enhanced validation"""
    
    class Meta:
        model = Route
        fields = ['name', 'description', 'transportation', 'weekday', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        transportation_field = self.fields.get('transportation')
        if not transportation_field:
            return

        widget = transportation_field.widget

        # Keep only the "view" related-object action for vehicle selection.
        for attr_name, attr_value in (
            ('can_add_related', False),
            ('can_change_related', False),
            ('can_delete_related', False),
            ('can_view_related', True),
        ):
            if hasattr(widget, attr_name):
                setattr(widget, attr_name, attr_value)
    
    def clean(self):
        cleaned_data = super().clean()
        transportation = cleaned_data.get('transportation')
        weekday = cleaned_data.get('weekday')
        return cleaned_data