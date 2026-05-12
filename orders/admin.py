from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse, path
from django.utils.safestring import mark_safe
from django.db.models import Sum, Count, Q
from django.http import HttpResponse
from django.shortcuts import redirect
from decimal import Decimal
import csv
from .models import Order, OrderProduct, OrderStatus, OrderSplit
from django.core.exceptions import PermissionDenied
from unfold.admin import ModelAdmin, TabularInline
from core.admin_mixins import SoftDeleteAdminMixin

class OrderAmountFilter(admin.SimpleListFilter):
    title = 'Rango de monto'
    parameter_name = 'amount_range'
    
    def lookups(self, request, model_admin):
        return (
            ('0-100', '$0 - $100'),
            ('100-500', '$100 - $500'),
            ('500-1000', '$500 - $1,000'),
            ('1000-5000', '$1,000 - $5,000'),
            ('5000+', '$5,000+'),
        )
    
    def queryset(self, request, queryset):
        if self.value() == '0-100':
            return queryset.filter(total_amount__gte=0, total_amount__lt=100)
        elif self.value() == '100-500':
            return queryset.filter(total_amount__gte=100, total_amount__lt=500)
        elif self.value() == '500-1000':
            return queryset.filter(total_amount__gte=500, total_amount__lt=1000)
        elif self.value() == '1000-5000':
            return queryset.filter(total_amount__gte=1000, total_amount__lt=5000)
        elif self.value() == '5000+':
            return queryset.filter(total_amount__gte=5000)


class BillingAttachedFilter(admin.SimpleListFilter):
    """Filter orders by presence of related billing records (BillingOrder)."""
    title = 'Tiene facturación'
    parameter_name = 'has_billing'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Con Facturación'),
            ('no', 'Sin Facturación'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            # Orders that have at least one InvoiceOrderLink
            return queryset.filter(invoice_links__isnull=False).distinct()
        elif self.value() == 'no':
            # Orders without any InvoiceOrderLink
            return queryset.filter(invoice_links__isnull=True)


class OrderProductInline(TabularInline):
    model = OrderProduct
    extra = 1
    fields = ('product', 'quantity', 'unit_price', 'total_price_display', 'note')
    readonly_fields = ('total_price_display',)
    
    def total_price_display(self, obj):
        if obj.id:
            return format_html(
                '<strong>${}</strong>',
                obj.get_total_price()
            )
        return '-'
    total_price_display.short_description = 'Total'

    # Inline permission controls: allow adding when creating a new Order,
    # but make inline read-only when viewing an existing Order for non-superusers.
    def get_readonly_fields(self, request, obj=None):
        # If editing an existing order and user is not superuser, make all fields readonly
        if obj is not None and not request.user.is_superuser:
            return tuple(self.fields)
        return self.readonly_fields

    def has_change_permission(self, request, obj=None):
        # Allow viewing change page for everyone; only superusers can change
        if request.user.is_superuser:
            return True
        # Return True so non-superusers can open the inline in the order change view
        return True

    def has_add_permission(self, request, obj=None):
        # Allow adding inline rows when creating a new order (obj is None) for non-superusers
        if request.user.is_superuser:
            return True
        return obj is None

    def has_delete_permission(self, request, obj=None):
        # Only superusers may delete inline items from existing orders
        if request.user.is_superuser:
            return True
        return False


@admin.register(Order)
class OrderAdmin(SoftDeleteAdminMixin, ModelAdmin):
    list_display = (
        'order_id_display', 'client_link','owner', 'status_display', 'order_date_formatted', 'discount',
        'total_amount_display', 'products_summary', 'payment_status','payment_method', 'billing_status'
    )
    
    list_filter = (
        'status',
        'owner',
        'order_date',
        OrderAmountFilter,
        BillingAttachedFilter,
        ('client', admin.RelatedOnlyFieldListFilter),
        ('client__type', admin.ChoicesFieldListFilter),
        ('client__active', admin.BooleanFieldListFilter),
    )
    
    search_fields = (
        'id',
        'client__name',
        'notes',
        'owner__name',
        'items__product__name',
        'client__contacts__phone',
        'client__contacts__email',
    )
    
    readonly_fields = (
        'order_id_display', 'order_date', 'created_at', 'updated_at', 'total_items_display',
        'order_summary', 'client_info_display', 'split_history_display'
    )
    
    fieldsets = (
        ('Información del Pedido', {
            'fields': ('order_id_display', 'client', 'owner', 'status', 'order_date')
        }),
        ('Detalles', {
            'fields': ('notes', 'total_amount', 'cantidad_cobrada', 'total_items_display')
        }),
        ('Resumen del Pedido', {
            'fields': ('order_summary',),
            'classes': ('collapse',)
        }),
        ('Información del Cliente', {
            'fields': ('client_info_display',),
            'classes': ('collapse',)
        }),
        ('Historial de Divisiones', {
            'fields': ('split_history_display',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [OrderProductInline]
    
    date_hierarchy = 'order_date'
    ordering = ('-order_date', '-id')
    list_per_page = 25
    
    actions = ['split_order_action', 'export_to_csv', 'crear_factura']
    
    class Media:
        css = {
           # 'all': ('admin/css/orders_admin.css',)
        }
        js = ('admin/js/orders_admin.js',)
    
    def changelist_view(self, request, extra_context=None):
        # Add summary statistics to the changelist
        extra_context = extra_context or {}
        
        # Get filtered queryset
        changelist = self.get_changelist_instance(request)
        queryset = changelist.get_queryset(request)
        
        # Calculate statistics
        stats = queryset.aggregate(
            total_orders=Count('id'),
            total_amount=Sum('total_amount'),
            pending_count=Count('id', filter=Q(status='PENDING')),
            completed_count=Count('id', filter=Q(status='COMPLETED')),
            cancelled_count=Count('id', filter=Q(status='CANCELLED')),
        )
        
        extra_context['order_stats'] = stats
        return super().changelist_view(request, extra_context)
    def payment_method(self, obj):
        payment = next(iter(obj.payments.all()), None)
        if payment:
            return payment.get_method_display()
        return 'Sin Definir'
    # --- Permission / visibility controls ---
    def is_super(self, request):
        return request.user and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        # Everyone can view orders in the admin
        return True

    def has_add_permission(self, request):
        # Allow creating orders for all users
        return True

    def has_change_permission(self, request, obj=None):
        # Allow the change view to be opened by everyone (so they can visualize),
        # but only superusers may actually edit/save changes.
        return True

    def has_delete_permission(self, request, obj=None):
        # Only superusers may delete orders
        return self.is_super(request)

    def get_readonly_fields(self, request, obj=None):
        # If the user is not superuser and is viewing an existing object, make fields readonly
        if not self.is_super(request) and obj is not None:
            # Make all concrete model fields readonly to prevent edits
            model_fields = [f.name for f in self.model._meta.concrete_fields]
            # Include existing readonly fields (display helpers)
            model_fields += list(self.readonly_fields)
            # Remove duplicates while preserving order
            seen = set()
            readonly = []
            for f in model_fields:
                if f not in seen:
                    readonly.append(f)
                    seen.add(f)
            return tuple(readonly)
        return self.readonly_fields

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        """Adjust change form UI: hide save/delete buttons for non-superusers viewing existing orders."""
        extra_context = extra_context or {}
        if not self.is_super(request) and object_id is not None:
            # Hide save buttons and delete link in the change form
            extra_context.update({
                'show_save': False,
                'show_save_and_continue': False,
                'show_save_and_add_another': False,
                'show_delete': False,
            })
        return super().changeform_view(request, object_id, form_url, extra_context)

    def get_actions(self, request):
        # Only superusers can run admin actions which may mutate orders
        if not self.is_super(request):
            return {}
        return super().get_actions(request)

    def save_model(self, request, obj, form, change):
        # Prevent non-superusers from saving edits to existing orders
        if change and not self.is_super(request):
            raise PermissionDenied("You do not have permission to edit this order.")
        return super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        # Prevent non-superusers from saving related objects when editing
        if change and not self.is_super(request):
            raise PermissionDenied("You do not have permission to modify related items for this order.")
        return super().save_related(request, form, formsets, change)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'client'
        ).prefetch_related(
            'items__product',
            'client__contacts',
            'client__addresses',
            'payments',
        )
    
    # Custom display methods
    def order_id_display(self, obj):
        return format_html(
            '<strong>#{}</strong>',
            obj.id
        )
    order_id_display.short_description = 'ID Pedido'
    order_id_display.admin_order_field = 'id'
    
    def client_link(self, obj):
        if obj.client:
            url = reverse('admin:clients_client_change', args=[obj.client.id])
            return format_html(
                '<a href="{}" target="_blank">{}</a>',
                url,
                obj.client.name
            )
        return '-'
    client_link.short_description = 'Cliente'
    client_link.admin_order_field = 'client__name'
    
    def status_display(self, obj):
        colors = {
            'PENDING': '#ffc107',
            'COMPLETED': '#28a745',
            'CANCELLED': '#dc3545'
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = 'Estado'
    status_display.admin_order_field = 'status'
    
    def order_date_formatted(self, obj):
        return obj.order_date.strftime('%d/%m/%Y %H:%M')
    order_date_formatted.short_description = 'Fecha del Pedido'
    order_date_formatted.admin_order_field = 'order_date'
    
    def total_amount_display(self, obj):
        return format_html(
            '<strong style="color: #28a745;">${}</strong>',
            obj.total_amount
        )
    total_amount_display.short_description = 'Total'
    total_amount_display.admin_order_field = 'total_amount'
    
    def products_summary(self, obj):
        items = obj.items.select_related('product').all()
        if not items:
            return '-'

        product_lines = [
            f'{item.product.name}: {item.quantity}'
            for item in items
        ]
        return format_html(
            '<div style="line-height: 1.3;">{}</div>',
            mark_safe('<br>'.join(product_lines))
        )
    products_summary.short_description = 'Productos'
    
    def payment_status(self, obj):
        if obj.is_paid:
            return format_html('<span style="color: #28a745; font-weight: bold;">✓ Pagado</span>')
        if obj.total_paid > 0:
            return format_html('<span style="color: #ffc107; font-weight: bold;">⚠ Parcial</span>')
        return format_html('<span style="color: #dc3545; font-weight: bold;">✗ Pendiente</span>')
    payment_status.short_description = 'Pago'
    
    def billing_status(self, obj):
        """Display billing status and associated invoices"""
        try:
            from invoice.models import InvoiceOrderLink
            invoice_links = InvoiceOrderLink.objects.filter(order=obj).select_related('invoice')
            
            if not invoice_links.exists():
                return format_html('<span style="color: #6c757d;">-</span>')
            
            billing_info = []
            for invoice_link in invoice_links:
                identifier = invoice_link.invoice.identifier
                url = reverse('admin:billing_invoice_change', args=[invoice_link.invoice.id])
                
                if invoice_link.is_paid:
                    status_icon = '✓'
                    color = '#28a745'
                    status_text = 'Pagado'
                elif invoice_link.partially_paid:
                    status_icon = '⚠'
                    color = '#ffc107'
                    status_text = f'Parcial ${invoice_link.amount_paid}'
                else:
                    status_icon = '✗'
                    color = '#dc3545'
                    status_text = 'Pendiente'
                
                billing_info.append(
                    f'<div style="margin: 2px 0;">'
                    f'<a href="{url}" target="_blank" style="color: {color}; text-decoration: none;" title="{status_text}">'
                    f'{status_icon} {identifier}'
                    f'</a>'
                    f'</div>'
                )
            
            return format_html(''.join(billing_info))
        except ImportError:
            return '-'
    
    billing_status.short_description = 'Facturación'
    
    def created_display(self, obj):
        return obj.created_at.strftime('%d/%m/%Y')
    created_display.short_description = 'Creado'
    created_display.admin_order_field = 'created_at'
    
    def total_items_display(self, obj):
        items = obj.items.all()
        total_items = sum(item.quantity for item in items)
        unique_products = items.count()
        return format_html(
            '<strong>{}</strong> items ({} productos únicos)',
            total_items,
            unique_products
        )
    total_items_display.short_description = 'Total de Items'
    
    def order_summary(self, obj):
        items = obj.items.select_related('product').all()
        if not items:
            return 'Sin productos'
        
        summary = []
        for item in items:
            summary.append(
                f'• {item.quantity}x {item.product.name} - ${item.unit_price} = ${item.get_total_price()}'
            )
        
        return format_html(
            '<div style="font-family: monospace; white-space: pre-line;">{}</div>',
            '\n'.join(summary)
        )
    order_summary.short_description = 'Resumen de Productos'
    
    def client_info_display(self, obj):
        if not obj.client:
            return 'Sin cliente'
        
        info = [f'<strong>Cliente:</strong> {obj.client.name}']
        info.append(f'<strong>Tipo:</strong> {obj.client.get_type_display()}')
        info.append(f'<strong>Estado:</strong> {"Activo" if obj.client.active else "Inactivo"}')
        
        # Add contact info
        contacts = obj.client.contacts.all()
        if contacts:
            info.append('<strong>Contactos:</strong>')
            for contact in contacts:
                contact_info = f'  • {contact.name}'
                if contact.phone:
                    contact_info += f' - Tel: {contact.phone}'
                if contact.email:
                    contact_info += f' - Email: {contact.email}'
                info.append(contact_info)
        
        # Add address info
        addresses = obj.client.addresses.all()
        if addresses:
            info.append('<strong>Direcciones:</strong>')
            for addr in addresses:
                info.append(f'  • {addr.street}, {addr.city}, {addr.state}')
        
        return format_html(
            '<div style="line-height: 1.4;">{}</div>',
            '<br>'.join(info)
        )
    client_info_display.short_description = 'Información del Cliente'
    
    def split_history_display(self, obj):
        """Display split history for this order"""
        if not obj.pk:
            return 'Guarde la orden primero.'
        
        # Check if this order was split from another order
        as_child = OrderSplit.objects.filter(child_order=obj).select_related('source_order', 'split_by').first()
        
        # Check if this order was split into other orders
        as_source = OrderSplit.objects.filter(source_order=obj).select_related('child_order', 'split_by')
        
        history = []
        
        if as_child:
            source_url = reverse('admin:orders_order_change', args=[as_child.source_order.id])
            split_by_name = as_child.split_by.username if as_child.split_by else "N/A"
            split_date = as_child.created_at.strftime("%d/%m/%Y %H:%M")
            history.append(
                '<div style="padding: 10px; background: #e3f2fd; border-left: 4px solid #2196f3; margin-bottom: 10px;">'
                '<strong>📥 Derivada de:</strong> '
                '<a href="{}" target="_blank">Orden #{}</a><br>'
                '<small>Dividida por: {}</small><br>'
                '<small>Fecha: {}</small>'
                '</div>'.format(source_url, as_child.source_order.id, split_by_name, split_date)
            )
        
        if as_source.exists():
            history.append('<strong>📤 Órdenes derivadas de esta:</strong><ul>')
            for split in as_source:
                child_url = reverse('admin:orders_order_change', args=[split.child_order.id])
                split_by_name = split.split_by.username if split.split_by else "N/A"
                split_date = split.created_at.strftime("%d/%m/%Y %H:%M")
                history.append(
                    '<li>'
                    '<a href="{}" target="_blank">Orden #{}</a> '
                    '- Total: ${} '
                    '<br><small>Dividida por: {} '
                    'el {}</small>'
                    '</li>'.format(
                        child_url, 
                        split.child_order.id, 
                        split.child_order.total_amount,
                        split_by_name,
                        split_date
                    )
                )
            history.append('</ul>')
        
        if not history:
            return format_html('<p style="color: #999;">Esta orden no tiene historial de divisiones.</p>')
        
        return format_html(
            '<div style="line-height: 1.6;">{}</div>',
            ''.join(history)
        )
    split_history_display.short_description = 'Historial de Divisiones'
    
    # Custom actions
    def mark_as_completed(self, request, queryset):
        from orders.services import mark_orders_as_completed

        result = mark_orders_as_completed(queryset, user=request.user)

        message = f"{result['updated']} pedidos marcados como completados."
        if result['skipped'] > 0:
            message += f" ({result['skipped']} ya estaban completados)"

        self.message_user(request, message)
    mark_as_completed.short_description = 'Marcar como completado'

    def mark_as_cancelled(self, request, queryset):
        from orders.services import cancel_orders

        result = cancel_orders(queryset, user=request.user)

        message = f"{result['updated']} pedidos marcados como cancelados."
        if result['skipped'] > 0:
            message += f" ({result['skipped']} ya estaban cancelados)"

        self.message_user(request, message)
    mark_as_cancelled.short_description = 'Marcar como cancelado'

    def mark_as_pending(self, request, queryset):
        from orders.services import mark_orders_as_pending

        result = mark_orders_as_pending(queryset, user=request.user)

        message = f"{result['updated']} pedidos marcados como pendientes."
        if result['skipped'] > 0:
            message += f" ({result['skipped']} ya estaban pendientes)"

        self.message_user(request, message)
    mark_as_pending.short_description = 'Marcar como pendiente'
    
    def split_order_action(self, request, queryset):
        """Action to split a single order"""
        # Validate only one order is selected
        if queryset.count() != 1:
            self.message_user(
                request, 
                'Debes seleccionar exactamente una orden para dividir.',
                level='error'
            )
            return
        
        order = queryset.first()
        
        # Validate order status is COMPLETED
        if order.status != OrderStatus.COMPLETED.value:
            self.message_user(
                request,
                f'Solo se pueden dividir órdenes completadas. La orden #{order.id} tiene estado: {order.get_status_display()}',
                level='error'
            )
            return
        
        # Validate order has items
        if order.items.count() == 0:
            self.message_user(
                request,
                f'La orden #{order.id} no tiene productos para dividir.',
                level='error'
            )
            return
        
        # Redirect to the split order page
        url = reverse('orders:split_order', args=[order.id])
        return redirect(url)
    
    split_order_action.short_description = '✂️ Dividir orden (solo completadas)'
    
    def crear_factura(self, request, queryset):
        """Create an invoice from selected completed, unbilled orders."""
        from invoice.services import create_invoice_from_orders
        from invoice.models import InvoiceOrderLink

        orders = list(queryset)

        non_completed = [o for o in orders if o.status != OrderStatus.COMPLETED.value]
        if non_completed:
            ids = ', '.join(f'#{o.id}' for o in non_completed)
            self.message_user(
                request,
                f'Solo se pueden facturar pedidos completados. Pedidos no completados: {ids}',
                level='error',
            )
            return

        client_ids = {o.client_id for o in orders}
        if len(client_ids) > 1:
            self.message_user(
                request,
                'Todos los pedidos seleccionados deben pertenecer al mismo cliente.',
                level='error',
            )
            return

        already_billed_ids = list(
            InvoiceOrderLink.objects.filter(order__in=orders).values_list('order_id', flat=True)
        )
        if already_billed_ids:
            ids = ', '.join(f'#{oid}' for oid in already_billed_ids)
            self.message_user(
                request,
                f'Los siguientes pedidos ya están facturados: {ids}',
                level='error',
            )
            return

        client = orders[0].client
        invoice = create_invoice_from_orders(orders=orders, client=client)

        self.message_user(
            request,
            f'Factura #{invoice.id} creada para {client.name} por ${invoice.amount}. '
            f'Actualiza el identificador y folio antes de emitirla.',
        )
        url = reverse('admin:billing_invoice_change', args=[invoice.id])
        return redirect(url)

    crear_factura.short_description = 'Crear factura'

    def export_to_csv(self, request, queryset):
        """Export selected orders to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="pedidos.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Cliente', 'Estado', 'Fecha', 'SubTotal', 'Descuento','Total',
            'Productos', 'Metodo Pago','Pagado', 'Creado'
        ])
        
        for order in queryset:
            client_name_external_id = f"{order.client.external_id} - {order.client.name}" if order.client and order.client.external_id else (order.client.name if order.client else '')
            products = '; '.join([
                f"{item.product.name} - {item.quantity}"
                for item in order.items.select_related('product').all()
            ])
            payment_method = order.payments.first().get_method_display() if hasattr(order, 'payments') and order.payments.exists() else 'Sin Definir'
            payment_status = order.payments.first().status_display() if hasattr(order, 'payments') and order.payments.exists() else 'N/A'
            writer.writerow([
                order.id,
                client_name_external_id,
                order.get_status_display(),
                order.order_date.strftime('%d/%m/%Y %H:%M'),
                str(order.subtotal_amount),
                str(order.discount),
                str(order.total_amount),
                products,
                payment_method,
                payment_status,
                order.created_at.strftime('%d/%m/%Y')
            ])
        
        return response
    export_to_csv.short_description = 'Exportar a CSV'


class OrderProductAdmin(SoftDeleteAdminMixin, ModelAdmin):
    list_display = (
        'order_link', 'product_name', 'quantity', 'unit_price', 
        'total_price_display', 'order_status', 'order_date', 'client_name'
    )
    
    list_filter = (
        ('product', admin.RelatedOnlyFieldListFilter),
        ('order__status', admin.ChoicesFieldListFilter),
        'order__order_date',
        ('order__client', admin.RelatedOnlyFieldListFilter),
        ('product__category', admin.RelatedOnlyFieldListFilter),
    )
    
    search_fields = (
        'product__name',
        'order__id',
        'order__client__name',
        'note',
    )
    
    readonly_fields = ('total_price_display', 'order_info_display')
    
    fieldsets = (
        ('Información del Producto', {
            'fields': ('order', 'product', 'quantity', 'unit_price', 'total_price_display')
        }),
        ('Detalles', {
            'fields': ('note',)
        }),
        ('Información del Pedido', {
            'fields': ('order_info_display',),
            'classes': ('collapse',)
        }),
    )
    
    ordering = ('-order__order_date', '-order__id')
    list_per_page = 50
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'order', 'order__client', 'product'
        )

    # Restrict edit/delete actions to superusers; non-superusers can view and add new entries
    def is_super(self, request):
        return request.user and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request):
        return True

    def has_change_permission(self, request, obj=None):
        # Allow opening change view for visualization, but prevent saving for non-superusers
        return True

    def has_delete_permission(self, request, obj=None):
        return self.is_super(request)

    def get_readonly_fields(self, request, obj=None):
        if not self.is_super(request) and obj is not None:
            # Make all fields readonly for existing objects
            field_names = [f.name for f in self.model._meta.concrete_fields]
            field_names += list(self.readonly_fields)
            seen = set(); readonly = []
            for f in field_names:
                if f not in seen:
                    readonly.append(f); seen.add(f)
            return tuple(readonly)
        return self.readonly_fields

    def get_actions(self, request):
        if not self.is_super(request):
            return {}
        return super().get_actions(request)
    
    def order_link(self, obj):
        url = reverse('admin:orders_order_change', args=[obj.order.id])
        return format_html(
            '<a href="{}" target="_blank">Pedido #{}</a>',
            url,
            obj.order.id
        )
    order_link.short_description = 'Pedido'
    order_link.admin_order_field = 'order__id'
    
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Producto'
    product_name.admin_order_field = 'product__name'
    
    def total_price_display(self, obj):
        return format_html(
            '<strong>${}</strong>',
            obj.get_total_price()
        )
    total_price_display.short_description = 'Total'
    
    def order_status(self, obj):
        colors = {
            'PENDING': '#ffc107',
            'COMPLETED': '#28a745',
            'CANCELLED': '#dc3545'
        }
        color = colors.get(obj.order.status, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.order.get_status_display()
        )
    order_status.short_description = 'Estado del Pedido'
    order_status.admin_order_field = 'order__status'
    
    def order_date(self, obj):
        return obj.order.order_date.strftime('%d/%m/%Y')
    order_date.short_description = 'Fecha'
    order_date.admin_order_field = 'order__order_date'
    
    def client_name(self, obj):
        return obj.order.client.name if obj.order.client else '-'
    client_name.short_description = 'Cliente'
    client_name.admin_order_field = 'order__client__name'
    
    def order_info_display(self, obj):
        if not obj.order:
            return 'Sin pedido'
        
        info = []
        info.append(f'<strong>Pedido:</strong> #{obj.order.id}')
        info.append(f'<strong>Cliente:</strong> {obj.order.client.name if obj.order.client else "N/A"}')
        info.append(f'<strong>Estado:</strong> {obj.order.get_status_display()}')
        info.append(f'<strong>Fecha:</strong> {obj.order.order_date.strftime("%d/%m/%Y %H:%M")}')
        info.append(f'<strong>Total del Pedido:</strong> ${obj.order.total_amount}')
        
        return format_html(
            '<div style="line-height: 1.4;">{}</div>',
            '<br>'.join(info)
        )
    order_info_display.short_description = 'Información del Pedido'


@admin.register(OrderSplit)
class OrderSplitAdmin(SoftDeleteAdminMixin, ModelAdmin):
    """Admin for tracking order splits"""
    list_display = (
        'id', 'source_order_link', 'child_order_link', 'split_by',
        'created_at_display', 'source_total', 'child_total'
    )
    
    list_filter = (
        'created_at',
        ('split_by', admin.RelatedOnlyFieldListFilter),
    )
    
    search_fields = (
        'source_order__id',
        'child_order__id',
        'split_by__username',
        'notes',
    )
    
    readonly_fields = (
        'source_order', 'child_order', 'split_by', 'created_at', 'updated_at',
        'split_summary'
    )
    
    fieldsets = (
        ('Información de la División', {
            'fields': ('source_order', 'child_order', 'split_by', 'created_at')
        }),
        ('Resumen', {
            'fields': ('split_summary',)
        }),
        ('Notas', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('updated_at',),
            'classes': ('collapse',)
        }),
    )
    
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'source_order', 'child_order', 'split_by',
            'source_order__client', 'child_order__client'
        )
    
    def has_add_permission(self, request):
        """Prevent manual creation of split records"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of split records for audit trail"""
        return request.user.is_superuser
    
    def source_order_link(self, obj):
        url = reverse('admin:orders_order_change', args=[obj.source_order.id])
        return format_html(
            '<a href="{}" target="_blank">Orden #{} ({})</a>',
            url,
            obj.source_order.id,
            obj.source_order.client.name if obj.source_order.client else 'N/A'
        )
    source_order_link.short_description = 'Orden Original'
    source_order_link.admin_order_field = 'source_order__id'
    
    def child_order_link(self, obj):
        url = reverse('admin:orders_order_change', args=[obj.child_order.id])
        return format_html(
            '<a href="{}" target="_blank">Orden #{} ({})</a>',
            url,
            obj.child_order.id,
            obj.child_order.client.name if obj.child_order.client else 'N/A'
        )
    child_order_link.short_description = 'Orden Derivada'
    child_order_link.admin_order_field = 'child_order__id'
    
    def created_at_display(self, obj):
        return obj.created_at.strftime('%d/%m/%Y %H:%M')
    created_at_display.short_description = 'Fecha de División'
    created_at_display.admin_order_field = 'created_at'
    
    def source_total(self, obj):
        return format_html('${}', obj.source_order.total_amount)
    source_total.short_description = 'Total Original'
    source_total.admin_order_field = 'source_order__total_amount'
    
    def child_total(self, obj):
        return format_html('${}', obj.child_order.total_amount)
    child_total.short_description = 'Total Derivada'
    child_total.admin_order_field = 'child_order__total_amount'
    
    def split_summary(self, obj):
        """Display detailed summary of the split"""
        source_items = obj.source_order.items.select_related('product').all()
        child_items = obj.child_order.items.select_related('product').all()
        
        summary = []
        summary.append('<div style="font-family: monospace;">')
        summary.append('<h3>📦 Orden Original #{}</h3>'.format(obj.source_order.id))
        summary.append('<ul>')
        
        for item in source_items:
            summary.append(
                '<li>{}x {} - ${} = ${}</li>'.format(
                    item.quantity, 
                    item.product.name, 
                    item.unit_price, 
                    item.get_total_price()
                )
            )
        
        summary.append('</ul><strong>Total: ${}</strong>'.format(obj.source_order.total_amount))
        summary.append('<h3>📦 Orden Derivada #{}</h3><ul>'.format(obj.child_order.id))
        
        for item in child_items:
            summary.append(
                '<li>{}x {} - ${} = ${}</li>'.format(
                    item.quantity, 
                    item.product.name, 
                    item.unit_price, 
                    item.get_total_price()
                )
            )
        
        summary.append('</ul><strong>Total: ${}</strong>'.format(obj.child_order.total_amount))
        summary.append('</div>')
        
        return format_html(''.join(summary))
    split_summary.short_description = 'Resumen de la División'

