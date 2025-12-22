from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.forms.models import BaseInlineFormSet
from django.http import JsonResponse
from django.urls import path
from django.contrib.admin.views.decorators import staff_member_required

from billing.models import BillingOrder, BillingRecord

# Register your models here.
class BillingRecordInlineAdmin(admin.StackedInline):
    model = BillingOrder
    extra = 0
    fields = ('order', 'is_paid', 'partially_paid', 'amount_paid', 'payment_date')
    can_delete = False
    show_change_link = True
    # Custom form and formset to enforce queryset filtering and validation
    form = None  # set below after form class definition
    formset = None  # set below after formset class definition

class BillingOrderAdminForm(forms.ModelForm):
    class Meta:
        model = BillingOrder
        fields = ['billing_record', 'order', 'is_paid', 'partially_paid', 'amount_paid', 'payment_date']
    
    class Media:
        js = (
            'admin/js/billing_order_admin.js',  # Then our script
        )

    def __init__(self, *args, **kwargs):
        # For inline forms, we inject parent BillingRecord via FormSet
        self._billing_record = kwargs.pop('billing_record', None)
        super().__init__(*args, **kwargs)

        # Determine billing_record for filtering
        billing_record = (
            self._billing_record
            or getattr(self.instance, 'billing_record', None)
        )

        if not billing_record and 'billing_record' in self.data:
            # Non-inline admin: derive from POST data if present
            try:
                br_id = int(self.data.get('billing_record'))
            except (TypeError, ValueError):
                br_id = None
            if br_id:
                billing_record = BillingRecord.objects.filter(pk=br_id).first()

        # Apply queryset filtering to the order field
        if billing_record and 'order' in self.fields:
            # Resolve current order id (editing existing record)
            current_order_id = getattr(self.instance, 'order_id', None)
            from orders.models import Order
            qs = Order.objects.filter(
                client=billing_record.client,
                order_date__gte=billing_record.date,
            ).filter(
                Q(billing_orders__isnull=True) | Q(pk=current_order_id)
            ).distinct()
            self.fields['order'].queryset = qs
        
        # Add data-client-id to billing_record select for JavaScript
        if 'billing_record' in self.fields:
            self.fields['billing_record'].widget.attrs['class'] = 'billing-record-select'
            # Store client_id mapping in widget for JS to access
            self.fields['billing_record'].widget.attrs['data-enable-dynamic-orders'] = 'true'

    def clean(self):
        cleaned = super().clean()

        billing_record = (
            self._billing_record
            or cleaned.get('billing_record')
            or getattr(self.instance, 'billing_record', None)
        )
        order = cleaned.get('order') or getattr(self.instance, 'order', None)

        if billing_record and order:
            # Sum of total_amount of already associated orders (excluding current instance)
            total_existing = BillingOrder.objects.filter(
                billing_record=billing_record
            ).exclude(pk=self.instance.pk).aggregate(
                total=Sum('order__total_amount')
            )['total'] or 0

            new_amount = order.total_amount or 0
            max_amount = billing_record.amount

            if total_existing + new_amount > max_amount:
                raise ValidationError({
                    'order': (
                        f"La suma de montos ({total_existing + new_amount}) excede el monto de la factura ({max_amount})."
                    )
                })

        return cleaned

class BillingOrderInlineFormSet(BaseInlineFormSet):
    # Inject parent BillingRecord into each form so it can filter
    def _construct_form(self, i, **kwargs):
        kwargs['billing_record'] = self.instance
        return super()._construct_form(i, **kwargs)

# Wire custom form and formset into the inline admin
BillingRecordInlineAdmin.form = BillingOrderAdminForm
BillingRecordInlineAdmin.formset = BillingOrderInlineFormSet

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
    form = BillingOrderAdminForm

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'billable-orders/<int:client_pk>/',
                self.admin_site.admin_view(self.billable_orders_json),
                name='billing_billingorder_billable_orders',
            ),
            path(
                'billing-record/<int:billing_record_pk>/client/',
                self.admin_site.admin_view(self.get_billing_record_client),
                name='billing_billingorder_get_client',
            ),
        ]
        return custom_urls + urls

    def billable_orders_json(self, request, client_pk):
        """Return billable orders for a given client as JSON"""
        from orders.models import Order
        from clients.models import Client
        from django.shortcuts import get_object_or_404

        client = get_object_or_404(Client, pk=client_pk)
        
        # Get billing_record_id from query params to filter by date
        billing_record_id = request.GET.get('billing_record_id')
        billing_record_date = None
        
        if billing_record_id:
            try:
                billing_record = BillingRecord.objects.get(pk=billing_record_id)
                billing_record_date = billing_record.date
            except BillingRecord.DoesNotExist:
                pass
        
        # Filter orders: same client, not billed, and optionally >= billing_record.date
        orders_qs = Order.objects.filter(
            client=client,
            billing_orders__isnull=True
        )
        
        if billing_record_date:
            orders_qs = orders_qs.filter(order_date__gte=billing_record_date)
        
        orders = orders_qs.order_by('-order_date')

        orders_data = [
            {
                'id': order.id,
                'order_date': order.order_date.isoformat(),
                'total_amount': str(order.total_amount),
                'display': f"Order #{order.id} - {order.order_date.strftime('%Y-%m-%d')} - ${order.total_amount}"
            }
            for order in orders
        ]

        return JsonResponse({'orders': orders_data})

    def get_billing_record_client(self, request, billing_record_pk):
        """Return the client_id for a given billing record"""
        from django.shortcuts import get_object_or_404
        billing_record = get_object_or_404(BillingRecord, pk=billing_record_pk)
        return JsonResponse({
            'client_id': billing_record.client_id,
            'client_name': billing_record.client.name,
        })

admin.site.register(BillingRecord, BillingRecordAdmin)
admin.site.register(BillingOrder, BillingOrderAdmin)