from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.http import JsonResponse, HttpResponse
from django.urls import path
from django.shortcuts import render
from django.core.paginator import Paginator, EmptyPage
from collections import Counter

from billing.models import Invoice, InvoiceOrderLink, InvoiceFrequencyReport, InvoiceSchedule, BILLING_FREQUENCY_CHOICES
from unfold.admin import ModelAdmin, StackedInline
from core.admin_mixins import SoftDeleteAdminMixin
# Register your models here.
class InvoiceOrderLinkInlineAdmin(StackedInline):
    model = InvoiceOrderLink
    extra = 0
    fields = ('order', 'is_paid', 'partially_paid')
    autocomplete_fields = ('order',)
    can_delete = False
    show_change_link = True
    # Custom form and formset to enforce queryset filtering and validation
    form = None  # set below after form class definition
    formset = None  # set below after formset class definition

class InvoiceOrderLinkAdminForm(forms.ModelForm):
    class Meta:
        model = InvoiceOrderLink
        fields = ['invoice', 'order', 'is_paid', 'partially_paid']
        search_fields = ('invoice__client', 'order__id')
        readonly_fields = ['invoice', 'order']
    class Media:
        js = (
            'admin/js/billing_order_admin.js',  # Then our script
            'admin/js/hide_add_modify_dropdown_options.js',  # Hide add/modify options for invoice and order
        )

    def __init__(self, *args, **kwargs):
        # For inline forms, we inject parent Invoice via FormSet
        self._invoice = kwargs.pop('invoice', None)
        super().__init__(*args, **kwargs)

        # Determine invoice for filtering
        invoice = (
            self._invoice
            or getattr(self.instance, 'invoice', None)
        )

        if not invoice and 'invoice' in self.data:
            # Non-inline admin: derive from POST data if present
            try:
                br_id = int(self.data.get('invoice'))
            except (TypeError, ValueError):
                br_id = None
            if br_id:
                invoice = Invoice.objects.filter(pk=br_id).first()

        # Apply queryset filtering to the order field using manager
        if invoice and 'order' in self.fields:
            # Resolve current order id (editing existing record)
            current_order_id = getattr(self.instance, 'order_id', None)
            from orders.models import Order
            # Use custom manager method to get unbilled orders for client
            self.fields['order'].queryset = Order.objects.unbilled_for_client(
                invoice.client,
                exclude_order_id=current_order_id,
                invoice_date=invoice.date,
            )
        elif 'order' in self.fields:
            # No invoice available yet - show all unbilled orders
            from orders.models import Order
            self.fields['order'].queryset = Order.objects.unbilled()

        # Add data attribute to invoice select for JavaScript
        if 'invoice' in self.fields:
            self.fields['invoice'].widget.attrs['class'] = 'invoice-select'
            # Store client_id mapping in widget for JS to access
            self.fields['invoice'].widget.attrs['data-enable-dynamic-orders'] = 'true'


    def clean(self):
        from billing.services import validate_invoice_order_total

        cleaned = super().clean()

        invoice = (
            self._invoice
            or cleaned.get('invoice')
            or getattr(self.instance, 'invoice', None)
        )
        order = cleaned.get('order') or getattr(self.instance, 'order', None)

        if invoice and order:
            # Use service layer for validation
            try:
                validate_invoice_order_total(
                    invoice=invoice,
                    order=order,
                    exclude_invoice_order_link_id=self.instance.pk
                )
            except ValidationError as e:
                raise ValidationError({'order': str(e)})

        return cleaned

class InvoiceOrderLinkInlineFormSet(BaseInlineFormSet):
    # Inject parent Invoice into each form so it can filter
    def _construct_form(self, i, **kwargs):
        kwargs['invoice'] = self.instance
        return super()._construct_form(i, **kwargs)

# Wire custom form and formset into the inline admin
InvoiceOrderLinkInlineAdmin.form = InvoiceOrderLinkAdminForm
InvoiceOrderLinkInlineAdmin.formset = InvoiceOrderLinkInlineFormSet

class InvoiceAdmin(SoftDeleteAdminMixin, ModelAdmin):
    list_display = ('id', 'identifier', 'client', 'amount', 'date', 'description')
    list_filter = ('date', 'client')
    search_fields = ('client__name', 'description', 'identifier')
    autocomplete_fields = ('client',)
    exclude = ('deleted_at',)
    ordering = ('-date',)
    inlines = [InvoiceOrderLinkInlineAdmin]


class InvoiceOrderLinkAdmin(SoftDeleteAdminMixin, ModelAdmin):
    list_display = ('id', 'invoice', 'order', 'is_paid', 'partially_paid')
    list_filter = ('is_paid', 'partially_paid', 'invoice__client', 'invoice')
    search_fields = ('invoice__client', 'order')
    autocomplete_fields = ('invoice', 'order')
    ordering = ('-created_at',)
    form = InvoiceOrderLinkAdminForm
    
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'billable-orders/<int:client_pk>/',
                self.admin_site.admin_view(self.billable_orders_json),
                name='billing_invoiceorderlink_billable_orders',
            ),
            path(
                'invoice/<int:invoice_pk>/client/',
                self.admin_site.admin_view(self.get_invoice_client),
                name='billing_invoiceorderlink_get_client',
            ),
        ]
        return custom_urls + urls

    def billable_orders_json(self, request, client_pk):
        """Return billable orders for a given client as JSON"""
        from billing.services import get_invoiceable_orders_for_client
        from clients.models import Client
        from django.shortcuts import get_object_or_404

        client = get_object_or_404(Client, pk=client_pk)

        # Use service layer to get invoiceable orders
        orders_data = get_invoiceable_orders_for_client(client, as_dict=True)

        return JsonResponse({'orders': orders_data})

    def get_invoice_client(self, request, invoice_pk):
        """Return the client_id for a given invoice"""
        from django.shortcuts import get_object_or_404
        invoice = get_object_or_404(Invoice, pk=invoice_pk)
        return JsonResponse({
            'client_id': invoice.client_id,
            'client_name': invoice.client.name,
        })

@admin.register(InvoiceFrequencyReport)
class InvoiceFrequencyReportAdmin(ModelAdmin):
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

#@admin.register(InvoiceSchedule)
class InvoiceScheduleAdmin(ModelAdmin):
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


admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(InvoiceOrderLink, InvoiceOrderLinkAdmin)