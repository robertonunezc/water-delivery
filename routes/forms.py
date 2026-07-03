import datetime
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import Route, RouteClient


class RouteClientForm(forms.ModelForm):
    """Custom form for RouteClient with validation for existing assignments"""

    anchor_date = forms.DateField(
        required=False,
        label='Fecha de inicio de ciclo',
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'],
    )

    class Meta:
        model = RouteClient
        fields = ['client', 'sequence', 'interval_weeks', 'anchor_date', 'is_active', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if 'anchor_date' in self.fields:
            self.fields['anchor_date'].localize = False
            # Default empty field to today
            instance = kwargs.get('instance')
            if not instance or not instance.anchor_date:
                self.fields['anchor_date'].initial = datetime.date.today()

    def clean_anchor_date(self) -> datetime.date:
        return self.cleaned_data.get('anchor_date') or datetime.date.today()


class RouteClientInlineForm(RouteClientForm):
    """Specialized form for inline admin usage"""

    confirm_duplicate_assignment = forms.BooleanField(
        required=False,
        label="Confirmar asignación",
        help_text="Cliente ya asignado a otra ruta. Marque para confirmar.",
        widget=forms.CheckboxInput(
            attrs={
                'class': 'confirm-duplicate-checkbox',
                'style': 'display: none;',  # Hidden by default, shown via JavaScript
            }
        ),
    )

    class Meta(RouteClientForm.Meta):
        fields = RouteClientForm.Meta.fields + ['confirm_duplicate_assignment']

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        # Move confirmation field to the end
        if 'confirm_duplicate_assignment' in self.fields:
            confirm_field = self.fields.pop('confirm_duplicate_assignment')
            self.fields['confirm_duplicate_assignment'] = confirm_field

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        client = cleaned_data.get('client')
        is_active = cleaned_data.get('is_active', True)
        confirmed = cleaned_data.get('confirm_duplicate_assignment')

        if not client or not is_active or confirmed:
            return cleaned_data

        existing_assignments = RouteClient.objects.filter(
            client=client,
            is_active=True,
        ).select_related('route')

        if self.instance and self.instance.pk:
            existing_assignments = existing_assignments.exclude(pk=self.instance.pk)

        current_route = self._get_current_route()
        if current_route and current_route.pk:
            existing_assignments = existing_assignments.exclude(route=current_route)

        if existing_assignments.exists():
            routes = ', '.join(
                assignment.route.name for assignment in existing_assignments
            )
            self.add_error(
                'client',
                ValidationError(
                    f"CONFLICTO DE ASIGNACIÓN: Cliente '{client.name}' "
                    f"ya está asignado a: {routes}."
                ),
            )

        return cleaned_data

    def _get_current_route(self) -> Route | None:
        formset = getattr(self, '_formset', None)
        route = getattr(formset, 'instance', None)
        return route if isinstance(route, Route) else None


class ClientRouteAssignmentForm(forms.ModelForm):
    """Form for editing a client's route assignments from the custom client form."""

    anchor_date = forms.DateField(
        required=False,
        label='Fecha de inicio de ciclo',
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={'type': 'date', 'class': 'form-control'},
        ),
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'],
    )

    class Meta:
        model = RouteClient
        fields = ['route', 'sequence', 'interval_weeks', 'anchor_date', 'is_active', 'notes']
        widgets = {
            'route': forms.Select(attrs={'class': 'form-select'}),
            'sequence': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'interval_weeks': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '4'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
        labels = {
            'interval_weeks': 'Intervalo',
            'anchor_date': 'Inicio de ciclo',
            'is_active': 'Activo',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        route_queryset = Route.objects.filter(is_active=True)
        if self.instance and self.instance.pk and self.instance.route_id:
            route_queryset = Route.objects.filter(
                Q(is_active=True) | Q(pk=self.instance.route_id)
            )
        self.fields['route'].queryset = route_queryset.order_by('weekday', 'name')

        if not self.instance or not self.instance.anchor_date:
            self.fields['anchor_date'].initial = datetime.date.today()

    def clean_anchor_date(self) -> datetime.date:
        return self.cleaned_data.get('anchor_date') or datetime.date.today()


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
