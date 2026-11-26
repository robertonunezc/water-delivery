from django.apps import apps
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import Payment, PaymentCollection
from core.admin_mixins import SoftDeleteAdminMixin


class PaymentAdmin(SoftDeleteAdminMixin, ModelAdmin):
    list_display = (
        'id',
        'entry_kind',
        'client',
        'order',
        'signed_amount_display',
        'method',
        'status',
        'reversal_action_link',
        'date',
    )
    list_filter = ('entry_kind', 'method', 'status', 'date', 'client')
    search_fields = ('client__name', 'order__id', 'amount', 'reversal_reason')
    readonly_fields = (
        'client',
        'order',
        'amount',
        'method',
        'status',
        'entry_kind',
        'reversal_of',
        'collection',
        'reversal_reason',
        'date',
        'created_by',
        'get_payment_breakdown_display',
        'balance_used',
        'credit_used',
    )
    list_per_page = 50
    ordering = ('-date',)
    list_display_links = ('id', 'signed_amount_display')
    actions = None

    class Media:
        css = {
            'all': ('core/css/design-system.css',)
        }

    fieldsets = (
        ('Información Básica', {
            'fields': (
                ('client', 'order'),
                ('amount', 'method'),
                ('entry_kind', 'status'),
                ('reversal_of', 'collection'),
                'reversal_reason',
            )
        }),
        ('Desglose del Pago', {
            'fields': (('balance_used', 'credit_used'), 'get_payment_breakdown_display'),
            'description': 'Información sobre cómo se procesó el pago usando saldo y crédito del cliente'
        }),
        ('Información del Sistema', {
            'fields': ('date', 'created_by'),
            'classes': ('collapse',)
        })
    )

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def signed_amount_display(self, obj):
        signed = obj.signed_amount
        if obj.is_reversal:
            return format_html('<span class="pg-text-danger pg-fw-semibold">-${}</span>', f'{obj.amount:.2f}')
        return format_html('<span class="pg-text-success pg-fw-semibold">${}</span>', f'{signed:.2f}')

    signed_amount_display.short_description = 'Monto Neto'

    def reversal_action_link(self, obj):
        if obj.is_reversal and obj.reversal_of_id:
            return format_html('<span class="pg-text-muted">Reversión de #{}</span>', obj.reversal_of_id)
        if obj.has_reversal:
            return format_html('<span class="pg-badge pg-badge-warning">Con reversión</span>')
        if obj.is_real_payment and obj.status == 'completed':
            url = reverse('payment:reverse_payment_preview', args=[obj.pk])
            return format_html('<a href="{}">Revertir pago</a>', url)
        return '-'

    reversal_action_link.short_description = 'Acción'

    def get_payment_breakdown_display(self, obj):
        """Display payment breakdown in a readable format"""
        if obj.method in ['balance', 'credit']:
            breakdown = []
            if obj.balance_used > 0:
                breakdown.append(f'<span class="pg-text-success pg-fw-semibold">Saldo: ${obj.balance_used:.2f}</span>')
            if obj.credit_used > 0:
                breakdown.append(f'<span class="pg-text-warning pg-fw-semibold">Crédito: ${obj.credit_used:.2f}</span>')
            if breakdown:
                return format_html(' + '.join(breakdown))
            return format_html('<span class="pg-text-muted">No desglosado</span>')
        return format_html(
            '<span class="pg-text-info pg-fw-semibold">{}: ${}</span>',
            obj.get_method_display(),
            f'{obj.amount:.2f}',
        )

    get_payment_breakdown_display.short_description = 'Desglose'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('client', 'order', 'reversal_of', 'collection')


class PaymentCollectionAdmin(SoftDeleteAdminMixin, ModelAdmin):
    list_display = ('id', 'payer', 'excess_balance_transaction', 'excess_reversal_transaction', 'created_by', 'created_at')
    readonly_fields = ('payer', 'excess_balance_transaction', 'excess_reversal_transaction', 'created_by', 'notes', 'created_at')
    actions = None

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(Payment, PaymentAdmin)
admin.site.register(PaymentCollection, PaymentCollectionAdmin)

app_models = apps.get_app_config('payment').get_models()
for model in app_models:
    if model not in (Payment, PaymentCollection):
        try:
            admin.site.register(model)
        except admin.sites.AlreadyRegistered:
            pass
