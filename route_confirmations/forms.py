from django import forms

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
