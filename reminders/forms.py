from django import forms
from django.contrib.auth import get_user_model
from clients.models import Client

from .models import Reminder


class ReminderForm(forms.ModelForm):
    class Meta:
        model = Reminder
        fields = ["title", "description", "client", "reminder_date", "urgent"]
        labels = {
            "title": "Titulo",
            "description": "Descripcion",
            "client": "Cliente",
            "reminder_date": "Fecha",
            "urgent": "Urgente",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "pg-input"}),
            "description": forms.Textarea(attrs={"class": "pg-input", "rows": 4}),
            "client": forms.Select(attrs={"class": "pg-select"}),
            "reminder_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "pg-input", "type": "date"},
            ),
            "urgent": forms.CheckboxInput(attrs={"class": "pg-checkbox"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.order_by("name")
        self.fields["client"].required = False
        self.fields["client"].empty_label = "Sin cliente"
        self.fields["reminder_date"].input_formats = ["%Y-%m-%d"]


class ReminderCreateForm(ReminderForm):
    assigned_to = forms.ModelChoiceField(
        queryset=get_user_model().objects.filter(is_active=True).order_by("username"),
        required=False,
        label="Asignar a",
        empty_label="Mi usuario",
        help_text="Si no seleccionas un usuario, el recordatorio se asignara a tu usuario.",
        widget=forms.Select(attrs={"class": "pg-select"}),
    )
