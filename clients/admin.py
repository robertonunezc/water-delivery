from django.contrib import admin
from django.utils.html import format_html
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import path
from django.contrib import messages
from django.http import HttpResponseRedirect, HttpResponse
from django.urls import reverse
from . import models
from .forms import (
	ManualBalanceTransactionForm, 
	ManualCreditTransactionForm, 
	BulkBalanceDepositForm,
	ClientBillingFrequencyForm
)


class ContactInline(admin.StackedInline):
	model = models.Contact
	extra = 0
	exclude = ('deleted_at',)


@admin.register(models.Address)
class AddressAdmin(admin.ModelAdmin):
	list_display = ('street', 'municipality', 'state', 'zip_code', 'client__name')
	model = models.Address
	exclude = ('deleted_at',)
class AddressInline(admin.StackedInline):
	model = models.Address
	extra = 0
	exclude = ('deleted_at',)

class ClientBillingFrecuencyInline(admin.StackedInline):
	model = models.ClientBillingFrecuency
	extra = 0
	verbose_name = "Frecuencia de Facturación"
	verbose_name_plural = "Frecuencias de Facturación"
	fields = (
		('frequency', 'is_active'),
		'billing_date',
		'specific_day',
		('weekday', 'occurrence'),
		'notes'
	)
	exclude = ('deleted_at',)


class ClientCreditConfigInline(admin.StackedInline):
	model = models.ClientCreditConfig
	extra = 0
	verbose_name = "Configuración de Crédito"
	verbose_name_plural = "Configuraciones de Crédito"
	classes = ('tab-balance-credit',)
	fields = (
		'max_payment_days',
		('first_notification_days', 'second_notification_days'),
		'overdue_notification_days'
	)
	
class ClientBillingDataInline(admin.StackedInline):
	model = models.BillingData
	display_fields = ('rfc', 'razon_social', 'curp')
	exclude = ('deleted_at',)
	extra = 0
	verbose_name = "Datos de Facturación"
	verbose_name_plural = "Datos de Facturación"
	

@admin.register(models.Client)
class ClientAdmin(admin.ModelAdmin):
	list_display = ('name', 'active','type','corporate', 'balance', 'current_debt', 'get_available_credit', 'requires_billing')
	search_fields = ('name','type',)
	list_filter = ('active', 'type', 'corporate', 'requires_billing')
	inlines = [ClientBillingDataInline,AddressInline ,ContactInline, ClientCreditConfigInline]
	readonly_fields = (
		'created_at', 'updated_at',
		'balance', 'current_debt', 'get_available_credit',
		'get_balance_status', 'get_billing_data_button',
		'get_effective_billing_info',
		'get_billing_inheritance_status',
		'get_add_billing_frequency_button'
	)
	exclude = ('deleted_at',)
	actions = ['add_balance_action', 'add_credit_action', 'manage_billing_action']
	change_form_template = 'admin/clients/client_change_form.html'

	class Media:
		js = (
			'clients/admin/toggle_billing_inline.js',
			'clients/admin/toggle_billing_frequency_fields.js',
			'clients/admin/toggle_corporate_field.js',
			'clients/admin/billing_frequency_popup.js',
		)

	def get_inline_instances(self, request, obj=None):
		"""
		Only show inlines when editing an existing client.
		Hide all inlines when creating a new client.
		"""
		if obj is None:
			# Creating a new client - hide all inlines
			return []
		# Editing existing client - show all inlines
		return super().get_inline_instances(request, obj)

	fieldsets = (
		('Información Básica', {
			'fields': (('name', 'active'), 'type', 'corporate', 'note', 'address_link'),
			
		}),
		
		('Balance y Crédito', {
			'fields': (
				('can_pay_with_credit', 'requires_note_for_credit'),	
				('credit_limit',),		
					
				('balance', 'current_debt', ), 
				('get_available_credit'),
				'get_balance_status',
			),
			'classes': ('tab-balance-credit',),
			'description': 'Visualización de saldo prepagado y crédito del cliente.'
		}),
		('Datos de Facturación', {
		 	'fields': (('requires_billing', 'get_add_billing_frequency_button'),),
		 	'description': (
				'Configure los datos de facturación del cliente. '
				'Las sucursales pueden heredar datos de facturación del corporativo '
				'o tener sus propios datos de facturación.'
			)
		}),
		('Información de Facturación Heredada', {
			'fields': ('get_effective_billing_info', 'get_billing_inheritance_status'),
			'description': 'Información de facturación efectiva (propia o heredada del corporativo)'
		}),
	)
	
	def get_available_credit(self, obj):
		"""Display available credit for the client"""
		return f"${obj.get_available_credit():.2f}"
	get_available_credit.short_description = 'Crédito Disponible'
	
	def get_billing_data_button(self, obj):
		"""Display a button to manage billing data and frequency"""
		if obj.pk:
			url = reverse('admin:clients_client_manage_billing', args=[obj.pk])
			has_billing = hasattr(obj, 'billing_data')
			has_frequency = hasattr(obj, 'billing_frecuency') and obj.billing_frecuency.exists()
			
			if has_billing and has_frequency:
				status = '<span style="color: green;">✓ Configurado</span>'
			elif has_billing or has_frequency:
				status = '<span style="color: orange;">⚠ Parcialmente configurado</span>'
			else:
				status = '<span style="color: red;">✗ No configurado</span>'
			
			return format_html(
				'<div style="padding: 10px;">{}<br><br>'
				'<a href="{}" class="button" style="margin-top: 10px;">'
				'Gestionar Datos de Facturación</a></div>',
				status, url
			)
		return 'Debe crear el cliente antes de gestionar los datos de facturación.'
	get_billing_data_button.short_description = 'Gestión de Facturación'
	
	def get_balance_status(self, obj):
		"""Display balance and debt status with color coding"""
		balance_color = 'green' if obj.balance > 0 else 'orange' if obj.balance == 0 else 'red'
		debt_color = 'red' if obj.current_debt > 0 else 'green'
		
		return format_html(
			'<div><strong>Saldo:</strong> <span style="color: {};">${:.2f}</span></div>'
			'<div><strong>Deuda:</strong> <span style="color: {};">${:.2f}</span></div>'
			'<div><strong>Crédito Disponible:</strong> ${:.2f}</div>',
			balance_color, obj.balance,
			debt_color, obj.current_debt,
			obj.get_available_credit()
		)
	get_balance_status.short_description = 'Estado Financiero'

	def get_effective_billing_info(self, obj):
		"""Display effective billing data (own or inherited)"""
		if not obj.pk:
			return 'Guarde el cliente primero para ver información de facturación.'
		effective_data = obj.get_effective_billing_data()
		effective_address = obj.get_effective_billing_address()
		source = obj.get_billing_source()
		print("Effective billing data for", obj.name, ":", effective_data, effective_address, "Source:", source)
		if not effective_data and not effective_address:
			return format_html('<span style="color: red;">Sin datos de facturación</span>')

		source_label = {
			'own': '✓ Propios',
			'corporate': '⬆ Heredados del corporativo',
			'none': '✗ No disponible'
		}.get(source, 'Desconocido')
		source_color = {
			'own': 'green',
			'corporate': 'blue',
			'none': 'red'
		}.get(source, 'gray')

		result = f'<div><strong>Origen:</strong> <span style="color: {source_color};">{source_label}</span></div>'

		if effective_data:
			result += f'<div><strong>RFC:</strong> {effective_data.rfc}</div>'
			result += f'<div><strong>Razón Social:</strong> {effective_data.razon_social[:50]}...</div>'

		if effective_address:
			result += f'<div><strong>Dirección Fiscal:</strong> {str(effective_address)[:80]}...</div>'
		else:
			result += '<div style="color: orange;"><strong>⚠ Sin dirección fiscal</strong></div>'

		return format_html(result)

	get_effective_billing_info.short_description = 'Datos de Facturación Efectivos'

	def get_billing_inheritance_status(self, obj):
		"""Display billing inheritance status and warnings"""
		if not obj.pk:
			return ''
		if obj.type != 'branch':
			return format_html('<span style="color: gray;">N/A (cliente corporativo)</span>')
		
		has_own_data = hasattr(obj, 'billing_data')

		has_own_address = obj.addresses.filter(type='billing', active=True).exists()
		has_complete_own = has_own_data and has_own_address

		print("Billing inheritance status for",has_own_data, has_own_address, has_complete_own)
		if has_complete_own:
			return format_html('<span style="color: green;">✓ Usa sus propios datos de facturación</span>')

		if not obj.corporate:
			return format_html('<span style="color: red;">✗ Sin corporativo asociado</span>')

		corporate_has_data = hasattr(obj.corporate, 'billing_data')
		corporate_has_address = obj.corporate.addresses.filter(type='billing', active=True).exists()
		corporate_complete = corporate_has_data and corporate_has_address

		if corporate_complete:
			missing = []
			if not has_own_data:
				missing.append('RFC/Razón Social')
			if not has_own_address:
				missing.append('Dirección Fiscal')

			return format_html(
				'<span style="color: blue;">⬆ Hereda del corporativo: {}</span>',
				', '.join(missing)
			)

		missin_corporate_data = format_html(
			'<span style="color: orange;">⚠ Corporativo sin datos completos de facturación</span>'
		)
		add_coportate_data_btn = format_html(
			'<div style="margin-top: 5px;">'
			'<a href="/admin/clients/client/{}/change/" class="button">Agregar Datos de Facturación del Corporativo</a>'
			'</div>',
			obj.corporate.id
		)
		return format_html('{}{}', missin_corporate_data, add_coportate_data_btn)

	get_billing_inheritance_status.short_description = 'Estado de Herencia de Facturación'

	def get_add_billing_frequency_button(self, obj):
		"""Display a button to add billing frequency in a popup window"""
		if not obj.pk:
			return 'Guarde el cliente primero para agregar frecuencia de facturación.'
		if obj.has_billing_frequency():
			return format_html(
				'<span style="color: green;">✓ Frecuencia de facturación ya configurada.</span>'
			)
		add_url = f"/admin/clients/clientbillingfrecuency/add/?client={obj.pk}"
		return format_html(
			'<a href="{}" class="button add-billing-frequency-popup" '
			'data-popup="true" '
			'style="padding: 5px 10px; background-color: #417690; color: white; '
			'text-decoration: none; border-radius: 4px; display: inline-block;">'
			'+ Agregar Frecuencia de Facturación</a>',
			add_url
		)
	get_add_billing_frequency_button.short_description = ''

	def get_urls(self):
		"""Add custom URLs for manual transactions"""
		urls = super().get_urls()
		custom_urls = [
			path('add-credit/', self.admin_site.admin_view(self.add_credit_view), name='clients_client_add_credit'),
			path('bulk-deposit/', self.admin_site.admin_view(self.bulk_deposit_view), name='clients_client_bulk_deposit'),
		]
		return custom_urls + urls
	
	def add_balance_action(self, request, queryset):
		"""Admin action to add balance to selected clients"""
		if queryset.count() == 1:
			client = queryset.first()
			return HttpResponseRedirect(
				reverse('admin:clients_client_add_balance') + f'?client_id={client.id}'
			)
		else:
			return HttpResponseRedirect(reverse('admin:clients_client_bulk_deposit'))
	
	add_balance_action.short_description = "Agregar saldo a clientes seleccionados"
	
	def add_credit_action(self, request, queryset):
		"""Admin action to manage credit for selected client"""
		if queryset.count() != 1:
			messages.error(request, "Seleccione exactamente un cliente para gestionar crédito.")
			return
		
		client = queryset.first()
		return HttpResponseRedirect(
			reverse('admin:clients_client_add_credit') + f'?client_id={client.id}'
		)
	
	add_credit_action.short_description = "Gestionar crédito del cliente seleccionado"
	def add_credit_view(self, request):
		"""View for manually managing client credit"""
		client_id = request.GET.get('client_id')
		initial_data = {}
		
		if client_id:
			try:
				client = models.Client.objects.get(id=client_id)
				initial_data['client'] = client
			except models.Client.DoesNotExist:
				messages.error(request, "Cliente no encontrado.")
				return redirect('admin:clients_client_changelist')
		
		if request.method == 'POST':
			form = ManualCreditTransactionForm(request.POST)
			if form.is_valid():
				client = form.cleaned_data['client']
				amount = form.cleaned_data['amount']
				transaction_type = form.cleaned_data['transaction_type']
				description = form.cleaned_data['description']
				notes = form.cleaned_data['notes']
				new_credit_limit = form.cleaned_data.get('new_credit_limit')
				
				try:
					from clients.services import balance_service

					if transaction_type == 'limit_change':
						# Update credit limit
						balance_service.update_credit_limit(
							client=client,
							new_limit=new_credit_limit,
							user=request.user,
							notes=f"[MANUAL] {description}. Cambio manual realizado por {request.user.username}. {notes}"
						)
						messages.success(
							request,
							f"Límite de crédito actualizado. {client.name} ahora tiene ${client.credit_limit:.2f} de límite."
						)

					elif transaction_type in ['payment', 'forgiveness']:
						# Pay down debt
						paid_amount = balance_service.pay_debt(
							client=client,
							amount=amount,
							transaction_type=transaction_type,
							user=request.user,
							notes=f"[MANUAL] {description}. Transacción manual realizada por {request.user.username}. {notes}"
						)
						messages.success(
							request,
							f"Deuda reducida en ${paid_amount:.2f}. {client.name} ahora debe ${client.current_debt:.2f}."
						)

					elif transaction_type == 'payment_from_balance':
						# Pay debt using client's balance
						result = balance_service.pay_debt_from_balance(
							client=client,
							amount=amount,
							user=request.user,
							notes=f"[MANUAL] {description}. Pago con saldo realizado por {request.user.username}. {notes}"
						)
						if result['success']:
							messages.success(
								request,
								f"Pago con saldo exitoso. ${result['amount_paid']:.2f} descontados del saldo. "
								f"Saldo restante: ${result['remaining_balance']:.2f}. "
								f"Deuda restante: ${result['remaining_debt']:.2f}."
							)
						else:
							messages.error(request, f"Error en pago con saldo: {result['error']}")
							return render(request, 'admin/clients/add_credit.html', {
								'form': form,
								'title': 'Gestionar Crédito Manualmente',
								'opts': self.model._meta,
								'has_view_permission': True,
								'client': client,
							})

					elif transaction_type == 'adjustment':
						# Manual debt adjustment (could increase or decrease)
						# For simplicity, we'll treat as debt reduction
						paid_amount = balance_service.pay_debt(
							client=client,
							amount=amount,
							transaction_type=transaction_type,
							user=request.user,
							notes=f"[MANUAL] {description}. Ajuste manual realizado por {request.user.username}. {notes}"
						)
						messages.success(
							request,
							f"Ajuste aplicado. {client.name} ahora debe ${client.current_debt:.2f}."
						)
					
					return redirect('admin:clients_client_changelist')
					
				except Exception as e:
					messages.error(request, f"Error al procesar transacción: {str(e)}")
		else:
			form = ManualCreditTransactionForm(initial=initial_data)
		
		context = {
			'form': form,
			'title': 'Gestionar Crédito Manualmente',
			'opts': self.model._meta,
			'has_view_permission': True,
			'client': models.Client.objects.get(id=client_id) if client_id else None,
		}
		return render(request, 'admin/clients/add_credit.html', context)
	def bulk_deposit_view(self, request):
		"""View for bulk balance deposits to multiple clients"""
		if request.method == 'POST':
			form = BulkBalanceDepositForm(request.POST)
			if form.is_valid():
				clients = form.cleaned_data['clients']
				amount = form.cleaned_data['amount']
				description = form.cleaned_data['description']
				notes = form.cleaned_data['notes']
				
				from clients.services import balance_service

				successful_count = 0
				errors = []

				for client in clients:
					try:
						balance_service.add_balance(
							client=client,
							amount=amount,
							transaction_type='deposit',
							user=request.user,
							notes=f"[MANUAL MASIVO] {description}. Depósito masivo realizado por {request.user.username}. {notes}"
						)
						successful_count += 1
					except Exception as e:
						errors.append(f"{client.name}: {str(e)}")
				
				if successful_count > 0:
					messages.success(
						request,
						f"Depósito exitoso para {successful_count} cliente(s). ${amount:.2f} agregados a cada uno."
					)
				
				if errors:
					messages.error(
						request,
						f"Errores en {len(errors)} cliente(s): " + "; ".join(errors[:5])
					)
				
				return redirect('admin:clients_client_changelist')
		else:
			form = BulkBalanceDepositForm()
		
		context = {
			'form': form,
			'title': 'Depósito Masivo de Saldo',
			'opts': self.model._meta,
			'has_view_permission': True,
		}
		return render(request, 'admin/clients/bulk_deposit.html', context)
	
	

class ContactAdmin(admin.ModelAdmin):
	list_display = ('name', 'client', 'email', 'phone')
	search_fields = ('name', 'client__name', 'email', 'phone')
	exclude = ('deleted_at',)


class AddressAdmin(admin.ModelAdmin):
	list_display = ('street', 'municipality', 'state', 'zip_code', 'client')
	search_fields = ('street', 'municipality', 'client__name')
	exclude = ('deleted_at',)


class BillingDataAdmin(admin.ModelAdmin):
	# show related client name via a callable
	list_display = ('rfc', 'razon_social', 'client_name')
	search_fields = ('razon_social', 'rfc',)

	def client_name(self, obj):
		return obj.client.name if obj.client else ''
	client_name.short_description = 'client'

@admin.register(models.ClientBillingFrecuency)
class ClientBillingFrecuencyAdmin(admin.ModelAdmin):
	list_display = ('client', 'frequency', 'billing_date', 'get_billing_description','next_billing_date', 'is_active')
	search_fields = ('client__name', 'frequency')
	list_filter = ('frequency', 'billing_date', 'is_active', 'weekday')
	autocomplete_fields = ('client',)
	readonly_fields = ('get_billing_description',)
	class Media:
		js = (
			'clients/admin/toggle_billing_frequency_fields.js',
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


@admin.register(models.BalanceTransaction)
class BalanceTransactionAdmin(admin.ModelAdmin):
	list_display = ('client', 'transaction_type', 'amount', 'balance_before', 'balance_after', 'created_at', 'created_by')
	list_filter = ('transaction_type', 'created_at', 'client')
	search_fields = ('client__name', 'notes')
	readonly_fields = ('created_at', 'updated_at', 'get_balance_change', 'get_transaction_summary')
	autocomplete_fields = ('client', 'reference_order', 'reference_payment', 'transfer_to_client', 'created_by')
	date_hierarchy = 'created_at'
	ordering = ('-created_at',)
	
	fieldsets = (
		('Información de Transacción', {
			'fields': (
				('client', 'transaction_type'),
				('amount', 'get_balance_change'),
				('balance_before', 'balance_after'),
				'description'
			)
		}),
		('Referencias', {
			'fields': (
				('reference_order', 'reference_payment'),
				'transfer_to_client'
			),
			'classes': ('collapse',)
		}),
		('Detalles Adicionales', {
			'fields': ('notes', 'get_transaction_summary'),
			'classes': ('collapse',)
		}),
		('Información del Sistema', {
			'fields': (('created_by', 'created_at'), 'updated_at'),
			'classes': ('collapse',)
		})
	)
	
	def get_balance_change(self, obj):
		"""Display the balance change with color coding"""
		change = obj.balance_after - obj.balance_before
		color = 'green' if change > 0 else 'red' if change < 0 else 'blue'
		symbol = '+' if change > 0 else ''
		return format_html(
			'<span style="color: {}; font-weight: bold;">{}{:.2f}</span>',
			color, symbol, change
		)
	get_balance_change.short_description = 'Cambio en Saldo'
	
	def get_transaction_summary(self, obj):
		"""Display a summary of the transaction"""
		summary = f"<strong>{obj.get_transaction_type_display()}</strong><br>"
		summary += f"Cliente: {obj.client.name}<br>"
		summary += f"Fecha: {obj.created_at.strftime('%d/%m/%Y %H:%M')}<br>"
		if obj.reference_order:
			summary += f"Orden: #{obj.reference_order.id}<br>"
		if obj.reference_payment:
			summary += f"Pago: #{obj.reference_payment.id}<br>"
		if obj.transfer_to_client:
			summary += f"Transferencia a: {obj.transfer_to_client.name}<br>"
		return format_html(summary)
	get_transaction_summary.short_description = 'Resumen'
	
	def has_add_permission(self, request):
		# Prevent manual creation of transactions
		return False
	
	def has_change_permission(self, request, obj=None):
		# Prevent editing of transactions
		return False
	
	def has_delete_permission(self, request, obj=None):
		# Prevent deletion of transactions
		return False


@admin.register(models.CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
	list_display = ('client', 'transaction_type', 'amount', 'debt_before', 'debt_after', 'created_at', 'created_by')
	list_filter = ('transaction_type', 'created_at', 'client')
	search_fields = ('client__name',  'notes')
	readonly_fields = ('created_at', 'updated_at', 'get_debt_change', 'get_credit_limit_change', 'get_transaction_summary')
	autocomplete_fields = ('client', 'reference_order', 'reference_payment', 'created_by')
	date_hierarchy = 'created_at'
	ordering = ('-created_at',)
	
	fieldsets = (
		('Información de Transacción', {
			'fields': (
				('client', 'transaction_type'),
				('amount', 'get_debt_change'),
				('debt_before', 'debt_after')
			)
		}),
		('Límite de Crédito', {
			'fields': (
				('credit_limit_before', 'credit_limit_after'),
				'get_credit_limit_change'
			),
			'classes': ('collapse',)
		}),
		('Referencias', {
			'fields': (
				('reference_order', 'reference_payment')
			),
			'classes': ('collapse',)
		}),
		('Detalles Adicionales', {
			'fields': ('notes', 'get_transaction_summary'),
			'classes': ('collapse',)
		}),
		('Información del Sistema', {
			'fields': (('created_by', 'created_at'), 'updated_at'),
			'classes': ('collapse',)
		})
	)
	
	def get_debt_change(self, obj):
		"""Display the debt change with color coding"""
		change = obj.debt_after - obj.debt_before
		color = 'red' if change > 0 else 'green' if change < 0 else 'blue'
		symbol = '+' if change > 0 else ''
		return format_html(
			'<span style="color: {}; font-weight: bold;">{}{:.2f}</span>',
			color, symbol, change
		)
	get_debt_change.short_description = 'Cambio en Deuda'
	
	def get_credit_limit_change(self, obj):
		"""Display credit limit change if applicable"""
		if obj.credit_limit_before is not None and obj.credit_limit_after is not None:
			change = obj.credit_limit_after - obj.credit_limit_before
			if change != 0:
				color = 'green' if change > 0 else 'red'
				symbol = '+' if change > 0 else ''
				return format_html(
					'<span style="color: {}; font-weight: bold;">{}{:.2f}</span>',
					color, symbol, change
				)
		return '-'
	get_credit_limit_change.short_description = 'Cambio en Límite'
	
	def get_transaction_summary(self, obj):
		"""Display a summary of the transaction"""
		summary = f"<strong>{obj.get_transaction_type_display()}</strong><br>"
		summary += f"Cliente: {obj.client.name}<br>"
		summary += f"Fecha: {obj.created_at.strftime('%d/%m/%Y %H:%M')}<br>"
		if obj.reference_order:
			summary += f"Orden: #{obj.reference_order.id}<br>"
		if obj.reference_payment:
			summary += f"Pago: #{obj.reference_payment.id}<br>"
		if obj.credit_limit_before is not None and obj.credit_limit_after is not None:
			summary += f"Límite: ${obj.credit_limit_before:.2f} → ${obj.credit_limit_after:.2f}<br>"
		return format_html(summary)
	get_transaction_summary.short_description = 'Resumen'
	
	def has_add_permission(self, request):
		# Prevent manual creation of transactions
		return False
	
	def has_change_permission(self, request, obj=None):
		# Prevent editing of transactions
		return False
	
	def has_delete_permission(self, request, obj=None):
		# Prevent deletion of transactions
		return False
