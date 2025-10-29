from django.contrib import admin

from billing.models import BillingOrder, BillingRecord

# Register your models here.
class BillingRecordInlineAdmin(admin.StackedInline):
    model = BillingOrder
    extra = 0
    fields = ('order', 'is_paid', 'partially_paid', 'amount_paid', 'payment_date')
    can_delete = False
    show_change_link = True

class BillingRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'identifier', 'client', 'amount', 'date', 'description')
    list_filter = ('date', 'client')
    search_fields = ('client__name', 'description', 'identifier')
    ordering = ('-date',)
    inlines = [BillingRecordInlineAdmin]

class BillingOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'billing_record', 'order', 'is_paid', 'partially_paid', 'amount_paid', 'payment_date')
    list_filter = ('is_paid', 'partially_paid', 'payment_date')
    search_fields = ('billing_record__client__name', 'order__id')
    ordering = ('-payment_date',)

admin.site.register(BillingRecord, BillingRecordAdmin)
admin.site.register(BillingOrder, BillingOrderAdmin)