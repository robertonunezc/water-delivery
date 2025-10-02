from django.contrib import admin
from django.apps import apps
from .models import Payment

# Custom admin for Payment model
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'client', 'order', 'amount', 'method', 'get_payment_breakdown_display', 'status', 'date')
    list_filter = ('method', 'status', 'date', 'client')
    search_fields = ('client__name', 'order__id', 'amount')
    readonly_fields = ('date', 'get_payment_breakdown_display', 'balance_used', 'credit_used')
    list_per_page = 50
    ordering = ('-date',)
    
    # Make columns clickable for navigation
    list_display_links = ('id', 'amount')
    
    fieldsets = (
        ('Información Básica', {
            'fields': (('client', 'order'), ('amount', 'method'), 'status')
        }),
        ('Desglose del Pago', {
            'fields': (('balance_used', 'credit_used'), 'get_payment_breakdown_display'),
            'description': 'Información sobre cómo se procesó el pago usando saldo y crédito del cliente'
        }),
        ('Información del Sistema', {
            'fields': ('date',),
            'classes': ('collapse',)
        })
    )
    
    def get_payment_breakdown_display(self, obj):
        """Display payment breakdown in a readable format"""
        from django.utils.html import format_html
        
        if obj.method in ['balance', 'credit']:
            breakdown = []
            if obj.balance_used > 0:
                breakdown.append(f'<span style="color: green;">Saldo: ${obj.balance_used:.2f}</span>')
            if obj.credit_used > 0:
                breakdown.append(f'<span style="color: orange;">Crédito: ${obj.credit_used:.2f}</span>')
            
            if breakdown:
                return format_html(' + '.join(breakdown))
            else:
                return format_html('<span style="color: gray;">No desglosado</span>')
        else:
            return format_html(f'<span style="color: blue;">{obj.get_method_display()}: ${obj.amount:.2f}</span>')
    
    get_payment_breakdown_display.short_description = 'Desglose'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('client', 'order')
    
    actions = ['reverse_selected_payments']
    
    def reverse_selected_payments(self, request, queryset):
        """Admin action to reverse selected payments"""
        reversed_count = 0
        for payment in queryset:
            if payment.reverse_payment():
                reversed_count += 1
        
        if reversed_count:
            self.message_user(
                request,
                f'Se revirtieron {reversed_count} pagos exitosamente.'
            )
        else:
            self.message_user(
                request,
                'No se pudieron revertir los pagos seleccionados.',
                level='WARNING'
            )
    
    reverse_selected_payments.short_description = 'Revertir pagos seleccionados'

# Register Payment model with custom admin
admin.site.register(Payment, PaymentAdmin)

# Register other models from the app automatically
app_models = apps.get_app_config('payment').get_models()
for model in app_models:
    if model != Payment:  # Skip Payment since we registered it manually
        try:
            admin.site.register(model)
        except admin.sites.AlreadyRegistered:
            pass
