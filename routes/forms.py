import datetime
from typing import Any

from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory

from core.models import Transport
from product.models import Product
from .models import Route, RouteClient, TruckInventoryLine, TruckInventorySession
from .services import get_driver_transportation, get_inventory_routes_for_user


class RouteClientForm(forms.ModelForm):
    """Custom form for RouteClient assignments."""

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
    """Specialized form for inline admin usage."""


class ClientRouteAssignmentForm(forms.ModelForm):
    """Form for editing a client's route assignments from the custom client form."""

    anchor_date = forms.DateField(
        required=False,
        label='Fecha de inicio de ciclo',
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={'type': 'date', 'class': 'pg-input'},
        ),
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'],
    )

    class Meta:
        model = RouteClient
        fields = ['route', 'sequence', 'interval_weeks', 'anchor_date', 'is_active', 'notes']
        widgets = {
            'route': forms.Select(attrs={'class': 'pg-select'}),
            'sequence': forms.NumberInput(attrs={'class': 'pg-input', 'min': '1'}),
            'interval_weeks': forms.NumberInput(attrs={'class': 'pg-input', 'min': '1', 'max': '4'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'pg-checkbox-input'}),
            'notes': forms.Textarea(attrs={'class': 'pg-input', 'rows': 2}),
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


class TruckInventorySessionForm(forms.ModelForm):
    service_date = forms.DateField(
        label='Fecha',
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={'type': 'date', 'class': 'pg-input'},
        ),
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'],
    )

    class Meta:
        model = TruckInventorySession
        fields = ['service_date', 'route', 'transportation', 'notes']
        widgets = {
            'route': forms.Select(attrs={'class': 'pg-select'}),
            'transportation': forms.Select(attrs={'class': 'pg-select'}),
            'notes': forms.Textarea(attrs={'class': 'pg-input', 'rows': 2}),
        }

    def __init__(
        self,
        *args: Any,
        user: Any,
        service_date: datetime.date | None = None,
        **kwargs: Any,
    ) -> None:
        self.user = user
        super().__init__(*args, **kwargs)
        current_date = self._resolve_service_date(service_date)
        self.fields['service_date'].initial = current_date
        self._limit_route_choices(current_date)
        self._limit_transportation_choices()

    def _resolve_service_date(
        self,
        service_date: datetime.date | None,
    ) -> datetime.date:
        if service_date is not None:
            return service_date

        if self.is_bound:
            raw_date = self.data.get(self.add_prefix('service_date'), '')
            try:
                return datetime.date.fromisoformat(raw_date)
            except ValueError:
                return datetime.date.today()

        return datetime.date.today()

    def _limit_route_choices(self, service_date: datetime.date) -> None:
        if getattr(self.user, 'is_staff', False):
            queryset = Route.objects.filter(is_active=True).order_by('weekday', 'name')
        else:
            queryset = get_inventory_routes_for_user(self.user, service_date)
        self.fields['route'].queryset = queryset

    def _limit_transportation_choices(self) -> None:
        if getattr(self.user, 'is_staff', False):
            queryset = Transport.objects.filter(is_active=True).order_by('license_plate')
        else:
            transportation = get_driver_transportation(self.user)
            queryset = Transport.objects.none()
            if transportation is not None:
                queryset = Transport.objects.filter(pk=transportation.pk)
        self.fields['transportation'].queryset = queryset

    def clean(self):
        cleaned_data = super().clean()
        route = cleaned_data.get('route')
        transportation = cleaned_data.get('transportation')
        if route and transportation and route.transportation_id != transportation.pk:
            raise forms.ValidationError('La ruta no corresponde a la camioneta seleccionada.')
        return cleaned_data


class TruckInventoryLineForm(forms.ModelForm):
    class Meta:
        model = TruckInventoryLine
        fields = ['product', 'full_loaded', 'full_returned', 'empty_returned', 'notes']
        widgets = {
            'product': forms.Select(attrs={'class': 'pg-select'}),
            'full_loaded': forms.NumberInput(attrs={'class': 'pg-input', 'min': '0'}),
            'full_returned': forms.NumberInput(attrs={'class': 'pg-input', 'min': '0'}),
            'empty_returned': forms.NumberInput(attrs={'class': 'pg-input', 'min': '0'}),
            'notes': forms.Textarea(attrs={'class': 'pg-input', 'rows': 1}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.ordered_for_clients()


TruckInventoryLineFormSet = inlineformset_factory(
    TruckInventorySession,
    TruckInventoryLine,
    form=TruckInventoryLineForm,
    fields=['product', 'full_loaded', 'full_returned', 'empty_returned', 'notes'],
    extra=3,
    can_delete=True,
)
