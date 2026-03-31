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

    def clean(self):
        cleaned_data = super().clean()
        client = cleaned_data.get('client')
        route = cleaned_data.get('route')
        
        # If we're editing an existing RouteClient, get the route from the instance
        if not route and self.instance and self.instance.pk:
            route = self.instance.route
        
        # For inline forms, try to get route from the parent formset
        if not route and hasattr(self, '_formset') and hasattr(self._formset, 'instance'):
            route = self._formset.instance
            
        if client and route:
            # Check if client is already assigned to another route (excluding current assignment)
            existing_assignments = RouteClient.objects.filter(
                client=client, 
                is_active=True
            ).exclude(
                pk=self.instance.pk if self.instance else None
            )
            
            if existing_assignments.exists():
                # Get the details of existing assignments
                existing_routes = []
                for assignment in existing_assignments:
                    route_info = f"{assignment.route.name} ({assignment.route.get_weekday_display()})"
                    existing_routes.append(route_info)
                
                routes_text = ", ".join(existing_routes)
                
                # Add a confirmation flag to the form data - check both prefixed and non-prefixed names
                confirmation = self.data.get('confirm_duplicate_assignment', False)
                if not confirmation and hasattr(self, 'prefix') and self.prefix:
                    confirmation = self.data.get(f'{self.prefix}-confirm_duplicate_assignment', False)
                
                if not confirmation:
                    # Mark that this form has a conflict - used by JavaScript and template
                    self._has_duplicate_conflict = True
                    
                    # Get the field name for the confirmation checkbox
                    confirm_field_name = f"{self.prefix}-confirm_duplicate_assignment" if hasattr(self, 'prefix') and self.prefix else 'confirm_duplicate_assignment'
                    
                    # Create a detailed error message with HTML formatting for better readability
                    error_msg = (
                        f"⚠️ <strong>CONFLICTO DE ASIGNACIÓN</strong><br>"
                        f"<strong>Cliente:</strong> {client.name}<br>"
                        f"<strong>Ya asignado a:</strong> {routes_text}<br>"
                        f"<strong>Nueva ruta:</strong> {route.name} ({route.get_weekday_display()})<br>"
                        f"<em>Esto puede causar conflictos de programación.</em>"
                    )
                    
                    # If no confirmation was provided, raise validation error with confirmation option
                    from django.utils.safestring import mark_safe
                    raise ValidationError({
                        'client': mark_safe(error_msg + "<br><br>✓ <strong>Marque la casilla de confirmación para proceder.</strong>")
                    })
                
                # If we reach here, user has confirmed the duplicate assignment
                if getattr(self, 'request', None):
                    messages.warning(
                        self.request, 
                        f"Cliente '{client.name}' asignado a múltiples rutas. "
                        f"Verifique que no haya conflictos de horarios."
                    )
        
        return cleaned_data


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