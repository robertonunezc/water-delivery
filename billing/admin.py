from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.http import JsonResponse, HttpResponse
from django.urls import path
from django.shortcuts import render
from django.core.paginator import Paginator, EmptyPage
from collections import Counter

from billing.models import BillingOrder, BillingRecord, BillingFrequencyReport, ClientBillingFrecuency, BILLING_FREQUENCY_CHOICES
from unfold.admin import ModelAdmin, StackedInline
from core.admin_mixins import SoftDeleteAdminMixin
# Register your models here.
class BillingRecordInlineAdmin(StackedInline):
    model = BillingOrder
    extra = 0
    fields = ('order', 'is_paid', 'partially_paid')
    autocomplete_fields = ('order',)
    can_delete = False
    show_change_link = True
    # Custom form and formset to enforce queryset filtering and validation
    form = None  # set below after form class definition
    formset = None  # set below after formset class definition

class BillingOrderAdminForm(forms.ModelForm):
    class Meta:
        model = BillingOrder
        fields = ['billing_record', 'order', 'is_paid', 'partially_paid']
        search_fields = ('billing_record__client', 'order__id')
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

        # Apply queryset filtering to the order field using manager
        if billing_record and 'order' in self.fields:
            # Resolve current order id (editing existing record)
            current_order_id = getattr(self.instance, 'order_id', None)
            from orders.models import Order
            # Use custom manager method to get unbilled orders for client
            self.fields['order'].queryset = Order.objects.unbilled_for_client(
                billing_record.client,
                exclude_order_id=current_order_id
            )
        elif 'order' in self.fields:
            # No billing_record available yet - show all unbilled orders
            from orders.models import Order
            self.fields['order'].queryset = Order.objects.unbilled()

        # Add data-client-id to billing_record select for JavaScript
        if 'billing_record' in self.fields:
            self.fields['billing_record'].widget.attrs['class'] = 'billing-record-select'
            # Store client_id mapping in widget for JS to access
            self.fields['billing_record'].widget.attrs['data-enable-dynamic-orders'] = 'true'


    def clean(self):
        from billing.services import validate_billing_order_amount

        cleaned = super().clean()

        billing_record = (
            self._billing_record
            or cleaned.get('billing_record')
            or getattr(self.instance, 'billing_record', None)
        )
        order = cleaned.get('order') or getattr(self.instance, 'order', None)

        if billing_record and order:
            # Use service layer for validation
            try:
                validate_billing_order_amount(
                    billing_record=billing_record,
                    order=order,
                    exclude_billing_order_id=self.instance.pk
                )
            except ValidationError as e:
                raise ValidationError({'order': str(e)})

        return cleaned

class BillingOrderInlineFormSet(BaseInlineFormSet):
    # Inject parent BillingRecord into each form so it can filter
    def _construct_form(self, i, **kwargs):
        kwargs['billing_record'] = self.instance
        return super()._construct_form(i, **kwargs)

# Wire custom form and formset into the inline admin
BillingRecordInlineAdmin.form = BillingOrderAdminForm
BillingRecordInlineAdmin.formset = BillingOrderInlineFormSet

class BillingRecordAdmin(SoftDeleteAdminMixin, ModelAdmin):
    list_display = ('id', 'identifier', 'client', 'amount', 'date', 'description')
    list_filter = ('date', 'client')
    search_fields = ('client__name', 'description', 'identifier')
    autocomplete_fields = ('client',)
    exclude = ('deleted_at',)
    ordering = ('-date',)
    inlines = [BillingRecordInlineAdmin]


class BillingOrderAdmin(SoftDeleteAdminMixin, ModelAdmin):
    list_display = ('id', 'billing_record', 'order', 'is_paid', 'partially_paid')
    list_filter = ('is_paid', 'partially_paid', 'billing_record__client', 'billing_record')
    search_fields = ('billing_record__client', 'order')
    autocomplete_fields = ('billing_record', 'order')
    ordering = ('-created_at',)
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
        from billing.services import get_billable_orders_for_client
        from clients.models import Client
        from django.shortcuts import get_object_or_404

        client = get_object_or_404(Client, pk=client_pk)

        # Use service layer to get billable orders
        orders_data = get_billable_orders_for_client(client, as_dict=True)

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
class BillingFrequencyReportAdmin(ModelAdmin):
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
        from billing.services import get_clients_needing_billing, get_date_range_from_preset

        # Extract GET parameters
        search_query = request.GET.get('search', '').strip()
        frequency_filter = request.GET.get('frequency', '')
        date_preset = request.GET.get('date_preset', '')

        # Use service layer for date range calculation
        start_date, end_date = get_date_range_from_preset(
            preset=date_preset,
            custom_start=request.GET.get('start_date', ''),
            custom_end=request.GET.get('end_date', '')
        )

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

#@admin.register(ClientBillingFrecuency)
class ClientBillingFrecuencyAdmin(ModelAdmin):
    list_display = ('client', 'frequency', 'billing_date', 'get_billing_description','next_billing_date', 'is_active')
    search_fields = ('client__name', 'frequency')
    list_filter = ('frequency', 'billing_date', 'is_active', 'weekday')
    autocomplete_fields = ('client',)
    readonly_fields = ('get_billing_description',)

    class Media:
        js = (
            'billing/admin/toggle_billing_frequency_fields.js',
        )

    fieldsets = (
        ('Información Básica', {
            'fields': (('client', 'is_active'), 'frequency', 'billing_date')
        }),
        ('Configuración de Fecha Específica', {
            'fields': ('specific_day',),
            'classes': ('collapse',),
            'description': 'Usar solo cuando el tipo de fecha sea "Fecha específica del mes". Ejemplo: día 15 de cada mes.'
        }),
        ('Configuración de Día de la Semana', {
            'fields': (('weekday', 'occurrence'),),
            'classes': ('collapse',),
            'description': 'Usar solo cuando el tipo de fecha sea "Día específico de la semana". Ejemplo: tercer lunes de cada mes.'
        }),
        ('Información Adicional', {
            'fields': ('notes', 'get_billing_description'),
            'classes': ('collapse',)
        })
    )

    def get_billing_description(self, obj):
        """Display a human-readable description of the billing schedule"""
        return obj.__str__()
    get_billing_description.short_description = 'Descripción de Facturación'

    def response_add(self, request, obj, post_url_continue=None):
        """Custom response for popup mode - show success message"""
        if "_popup" in request.GET or "_popup" in request.POST:
            return HttpResponse('''
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Frecuencia de Facturación Agregada</title>
                    <style>
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            height: 100vh;
                            margin: 0;
                            background-color: #f5f5f5;
                        }
                        .success-container {
                            text-align: center;
                            padding: 40px;
                            background: white;
                            border-radius: 8px;
                            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                            max-width: 400px;
                        }
                        .success-icon {
                            font-size: 64px;
                            color: #28a745;
                            margin-bottom: 20px;
                        }
                        h2 {
                            color: #333;
                            margin-bottom: 10px;
                        }
                        p {
                            color: #666;
                            margin-bottom: 25px;
                        }
                        .close-btn {
                            background-color: #417690;
                            color: white;
                            border: none;
                            padding: 12px 30px;
                            font-size: 16px;
                            border-radius: 4px;
                            cursor: pointer;
                        }
                        .close-btn:hover {
                            background-color: #205067;
                        }
                    </style>
                </head>
                <body>
                    <div class="success-container">
                        <div class="success-icon">&#10004;</div>
                        <h2>Frecuencia de Facturación Agregada</h2>
                        <p>La frecuencia de facturación ha sido guardada exitosamente. Puede cerrar esta ventana.</p>
                        <button class="close-btn" onclick="window.close();">Cerrar Ventana</button>
                    </div>
                </body>
                </html>
            ''')
        return super().response_add(request, obj, post_url_continue)


admin.site.register(BillingRecord, BillingRecordAdmin)
admin.site.register(BillingOrder, BillingOrderAdmin)