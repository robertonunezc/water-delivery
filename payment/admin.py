from django.contrib import admin
from django.apps import apps
from .models import Payment

# Custom admin for Payment model
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'client', 'order', 'amount', 'method', 'status', 'date')
    list_filter = ('method', 'status', 'date', 'client')
    search_fields = ('client__name', 'order__id', 'amount')
    readonly_fields = ('date',)
    list_per_page = 50
    ordering = ('-date',)
    
    # Make columns clickable for navigation
    list_display_links = ('id', 'amount')
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('client', 'order')

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
