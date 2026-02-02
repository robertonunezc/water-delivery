from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.forms.models import BaseInlineFormSet
from django.http import JsonResponse
from django.urls import path
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.core.paginator import Paginator, EmptyPage
from datetime import date, timedelta, datetime
from calendar import monthrange

from billing.models import BillingOrder, BillingRecord, BillingFrequencyReport
from clients.models import BILLING_FREQUENCY_CHOICES

# Register your models here.
class BillingRecordInlineAdmin(admin.StackedInline):
    model = BillingOrder
    extra = 0
    fields = ('order', 'is_paid', 'partially_paid')
    can_delete = False
    show_change_link = True
    # Custom form and formset to enforce queryset filtering and validation
    form = None  # set below after form class definition
    formset = None  # set below after formset class definition

class BillingOrderAdminForm(forms.ModelForm):
    class Meta:
        model = BillingOrder
        fields = ['billing_record', 'order', 'is_paid', 'partially_paid']
        readonly_fields = ['billing_record','order']
    class Media:
        js = (
            'admin/js/billing_order_admin.js',  # Then our script
            'admin/js/hide_add_modify_dropdown_options.js',  # Hide add/modify options for billing_record and order
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
            # Filter orders: same client, not already billed (or current order if editing)
            # Note: Removed order_date__gte filter as it was too restrictive with datetime precision
            qs = Order.objects.filter(
                client=billing_record.client,
            ).filter(
                Q(billing_orders__isnull=True) | Q(pk=current_order_id)
            ).distinct()
            self.fields['order'].queryset = qs
        elif 'order' in self.fields:
            # No billing_record available yet - show all unbilled orders
            # This happens on initial form render before billing_record is selected
            from orders.models import Order
            self.fields['order'].queryset = Order.objects.filter(
                billing_orders__isnull=True
            ).distinct()
        
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
                        f"La suma de montos de las ventas associadas ({total_existing}) más el monto de la venta actual ({new_amount}) , ({total_existing + new_amount})excede el monto de la factura ({max_amount})."
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
    list_display = ('id', 'billing_record', 'order', 'is_paid', 'partially_paid')
    list_filter = ('is_paid', 'partially_paid', 'billing_record__client', 'billing_record')
    search_fields = ('billing_record__client__name', 'order__id')
    ordering = ('-created_at',)
    form = BillingOrderAdminForm
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name in ['billing_record', 'order']:
            kwargs['widget'] = admin.widgets.ForeignKeyRawIdWidget(
                db_field.remote_field,
                self.admin_site,
                using=kwargs.get('using'),
            )
            kwargs['widget'].can_add_related = False
            kwargs['widget'].can_change_related = False
            kwargs['widget'].can_delete_related = False
            # Use regular Select widget instead of raw id for cleaner dropdown
            from django.forms import Select
            formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
            formfield.widget = Select(choices=formfield.choices)
            return formfield
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

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
        if billing_record_id:
            try:
                BillingRecord.objects.get(pk=billing_record_id)
            except BillingRecord.DoesNotExist:
                pass
        
        # Filter orders: same client, not billed, and optionally >= billing_record.date
        orders_qs = Order.objects.filter(
            client=client,
            billing_orders__isnull=True
        ).order_by('-order_date')

        orders_data = [
            {
                'id': order.id,
                'order_date': order.order_date.isoformat(),
                'total_amount': str(order.total_amount),
                'display': f"Order #{order.id} - {order.order_date.strftime('%Y-%m-%d')} - ${order.total_amount}"
            }
            for order in orders_qs
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

@admin.register(BillingFrequencyReport)
class BillingFrequencyReportAdmin(admin.ModelAdmin):
    """
    Custom admin for billing frequency report.
    Overrides changelist_view to show custom report instead of model list.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        """Override changelist to show custom report"""
        return self.billing_frequency_report_view(request)

    def billing_frequency_report_view(self, request):
        """Custom report view"""
        from clients.models import ClientBillingFrecuency
        from billing.services import get_clients_needing_billing

        # Extract GET parameters
        search_query = request.GET.get('search', '').strip()
        frequency_filter = request.GET.get('frequency', '')
        date_preset = request.GET.get('date_preset', '')

        # Date range handling
        today = date.today()

        if date_preset == 'today':
            start_date = today
            end_date = today
        elif date_preset == 'this_week':
            start_date = today - timedelta(days=today.weekday())
            end_date = start_date + timedelta(days=6)
        elif date_preset == 'this_month':
            start_date = today.replace(day=1)
            last_day = monthrange(today.year, today.month)[1]
            end_date = today.replace(day=last_day)
        elif date_preset == 'next_7_days':
            start_date = today
            end_date = today + timedelta(days=7)
        else:
            # Custom date range
            start_str = request.GET.get('start_date', '')
            end_str = request.GET.get('end_date', '')

            try:
                start_date = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else today
            except ValueError:
                start_date = today

            try:
                end_date = datetime.strptime(end_str, '%Y-%m-%d').date() if end_str else today + timedelta(days=7)
            except ValueError:
                end_date = today + timedelta(days=7)

        # Get results from service layer
        results = get_clients_needing_billing(
            start_date=start_date,
            end_date=end_date,
            frequency_filter=frequency_filter if frequency_filter else None,
            search_query=search_query if search_query else None
        )

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(results, 20)

        try:
            page_obj = paginator.get_page(page_number)
        except EmptyPage:
            page_obj = paginator.get_page(1)

        # Statistics
        total_clients = len(results)
        total_amount = sum(r['total_amount'] for r in results)
        total_orders = sum(r['orders_count'] for r in results)

        # Frequency breakdown
        from collections import Counter
        frequency_breakdown = Counter(r['frequency_display'] for r in results)

        context = {
            **self.admin_site.each_context(request),
            'title': 'Reporte de Frecuencia de Facturación',
            'results': page_obj,
            'page_obj': page_obj,
            'search_query': search_query,
            'frequency_filter': frequency_filter,
            'date_preset': date_preset,
            'start_date': start_date,
            'end_date': end_date,
            'total_clients': total_clients,
            'total_amount': total_amount,
            'total_orders': total_orders,
            'frequency_breakdown': dict(frequency_breakdown),
            'frequency_choices': BILLING_FREQUENCY_CHOICES,
        }

        return render(
            request,
            'billing/admin/billing_frequency_report.html',
            context
        )

admin.site.register(BillingRecord, BillingRecordAdmin)
admin.site.register(BillingOrder, BillingOrderAdmin)