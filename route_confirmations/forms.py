from django import forms
from django.utils import timezone

from clients.models import Client

from .models import VisitConfirmation


class ConfirmationOverrideForm(forms.Form):
    status = forms.ChoiceField(
        choices=VisitConfirmation.Status.choices,
        label='Estatus',
    )
    note = forms.CharField(
        label='Nota',
        widget=forms.Textarea(attrs={'rows': 2}),
        min_length=3,
        required=True,
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields['status'].widget.attrs['class'] = 'pg-select'
        self.fields['note'].widget.attrs['class'] = 'pg-input'


class ManualConfirmationSendForm(forms.Form):
    clients = forms.ModelMultipleChoiceField(
        queryset=Client.objects.filter(active=True).order_by('name'),
        label='Clientes',
        widget=forms.SelectMultiple(attrs={'class': 'pg-select', 'size': 12}),
    )
    visit_date = forms.DateField(
        label='Fecha',
        widget=forms.DateInput(attrs={'class': 'pg-input', 'type': 'date'}),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields['visit_date'].initial = timezone.localdate()
