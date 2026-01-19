from django.contrib import admin
from django.utils.html import format_html
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import path
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from . import models
from .forms import (
	ManualBalanceTransactionForm, 
	ManualCreditTransactionForm, 
	BulkBalanceDepositForm,
	ClientBillingDataForm,
	ClientBillingFrequencyForm
)


class ContactInline(admin.TabularInline):
	model = models.Contact
	extra = 0
	exclude = ('deleted_at',)


class AddressInline(admin.TabularInline):
	model = models.Address
	extra = 0
	exclude = ('deleted_at',)


class BillingDataInline(admin.StackedInline):
	model = models.BillingData
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
	display_fields = ('rfc', 'razon_social', 'address', 'email', 'phone')
	exclude = ('deleted_at',)
	extra = 0
	verbose_name = "Datos de Facturación"
	verbose_name_plural = "Datos de Facturación"
	

@admin.register(models.Client)
class ClientAdmin(admin.ModelAdmin):
	list_display = ('name', 'active','type','corporate', 'balance', 'current_debt', 'get_available_credit', 'requires_billing')
	search_fields = ('name','type',)
	list_filter = ('active', 'type', 'corporate', 'requires_billing')
	inlines = [ClientBillingDataInline, ContactInline, AddressInline, ClientBillingFrecuencyInline, ClientCreditConfigInline]
	readonly_fields = ('created_at', 'updated_at', 'balance', 'current_debt', 'get_available_credit', 'get_balance_status', 'get_billing_data_button')
	exclude = ('deleted_at',)
	actions = ['add_balance_action', 'add_credit_action', 'manage_billing_action']
	
	class Media:
		js = ('clients/admin/toggle_billing_inline.js',)
	
	fieldsets = (
		('Información Básica', {
			'fields': (('name', 'active'), 'type', 'corporate', 'note', 'address_link'),
			
		}),
		
		('Balance y Crédito', {
			'fields': (
				('can_pay_with_credit', 'requires_note_for_credit'),	
				('credit_limit', 'max_payment_days',),		
					
				('balance', 'current_debt', ), 
				('get_available_credit'),
				'get_balance_status',
			),
			'classes': ('tab-balance-credit',),
			'description': 'Visualización de saldo prepagado y crédito del cliente.'
		}),
		('Datos de Facturación', {
		 	'fields': ('requires_billing',),
		 	'description': 'Configure los datos de facturación y frecuencia del cliente'
		}),
	)
	
	def get_available_credit(self, obj):
		"""Display available credit for the client"""
		return f"${obj.get_available_credit():.2f}"
	get_available_credit.short_description = 'Crédito Disponible'
	
	def get_inline_instances(self, request, obj=None):
		"""Conditionally show billing inlines only if requires_billing is checked"""
		inline_instances = []
		inlines = self.get_inlines(request, obj)
		
		for inline_class in inlines:
			# Skip billing-related inlines if requires_billing is not checked
			if obj and not obj.requires_billing:
				if inline_class in [ClientBillingDataInline, ClientBillingFrecuencyInline]:
					continue
			
			inline = inline_class(self.model, self.admin_site)
			inline_instances.append(inline)
		
		return inline_instances
	
	def get_billing_data_button(self, obj):
		"""Display a button to manage billing data and frequency"""
		if obj.pk:
			url = reverse('admin:clients_client_manage_billing', args=[obj.pk])
			has_billing = hasattr(obj, 'billing_data') and obj.billing_data.exists()
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
	
	def get_urls(self):
		"""Add custom URLs for manual transactions"""
		urls = super().get_urls()
		custom_urls = [
			path('add-balance/', self.admin_site.admin_view(self.add_balance_view), name='clients_client_add_balance'),
			path('add-credit/', self.admin_site.admin_view(self.add_credit_view), name='clients_client_add_credit'),
			path('bulk-deposit/', self.admin_site.admin_view(self.bulk_deposit_view), name='clients_client_bulk_deposit'),
			path('<path:object_id>/manage-billing/', self.admin_site.admin_view(self.manage_billing_view), name='clients_client_manage_billing'),
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
	
	def manage_billing_action(self, request, queryset):
		"""Admin action to manage billing data for selected client"""
		if queryset.count() != 1:
			messages.error(request, "Seleccione exactamente un cliente para gestionar facturación.")
			return
		
		client = queryset.first()
		return HttpResponseRedirect(
			reverse('admin:clients_client_manage_billing', args=[client.id])
		)
	
	manage_billing_action.short_description = "Gestionar datos de facturación del cliente"
	
	def add_balance_view(self, request):
		"""View for manually adding balance to a client"""
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
			form = ManualBalanceTransactionForm(request.POST)
			if form.is_valid():
				client = form.cleaned_data['client']
				amount = form.cleaned_data['amount']
				transaction_type = form.cleaned_data['transaction_type']
				description = form.cleaned_data['description']
				notes = form.cleaned_data['notes']
				
				try:
					# Add balance with transaction history
					new_balance = client.add_balance(
						amount=amount,
						transaction_type=transaction_type,
						user=request.user,
						notes=f"[MANUAL] {description}. Transacción manual realizada por {request.user.username}. {notes}"
					)
					
					messages.success(
						request,
						f"Saldo agregado exitosamente. {client.name} ahora tiene ${new_balance:.2f} de saldo."
					)
					return redirect('admin:clients_client_changelist')
					
				except Exception as e:
					messages.error(request, f"Error al agregar saldo: {str(e)}")
		else:
			form = ManualBalanceTransactionForm(initial=initial_data)
		
		context = {
			'form': form,
			'title': 'Agregar Saldo Manualmente',
			'opts': self.model._meta,
			'has_view_permission': True,
		}
		return render(request, 'admin/clients/add_balance.html', context)
	
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
					if transaction_type == 'limit_change':
						# Update credit limit
						client.update_credit_limit(
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
						paid_amount = client.pay_debt(
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
						result = client.pay_debt_from_balance(
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
						paid_amount = client.pay_debt(
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
				
				successful_count = 0
				errors = []
				
				for client in clients:
					try:
						client.add_balance(
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
	
	def manage_billing_view(self, request, object_id):
		"""View for managing billing data and frequency together"""
		client = get_object_or_404(models.Client, pk=object_id)
		
		# Get or create billing data and frequency instances
		try:
			billing_data = client.billing_data.get()
		except models.BillingData.DoesNotExist:
			billing_data = None
		
		try:
			frequency = client.billing_frecuency.get()
		except models.ClientBillingFrecuency.DoesNotExist:
			frequency = None
		
		if request.method == 'POST':
			billing_form = ClientBillingDataForm(request.POST, instance=billing_data, client=client)
			frequency_form = ClientBillingFrequencyForm(request.POST, instance=frequency)
			
			if billing_form.is_valid() and frequency_form.is_valid():
				try:
					# Save billing data
					billing_instance = billing_form.save(commit=False)
					billing_instance.client = client
					billing_instance.save()
					
					# Save billing frequency
					frequency_instance = frequency_form.save(commit=False)
					frequency_instance.client = client
					frequency_instance.save()
					
					messages.success(
						request,
						f"Datos de facturación actualizados exitosamente para {client.name}."
					)
					return redirect('admin:clients_client_change', object_id=client.id)
					
				except Exception as e:
					messages.error(request, f"Error al guardar datos de facturación: {str(e)}")
		else:
			billing_form = ClientBillingDataForm(instance=billing_data, client=client)
			frequency_form = ClientBillingFrequencyForm(instance=frequency)
		
		context = {
			'billing_form': billing_form,
			'frequency_form': frequency_form,
			'client': client,
			'title': f'Gestionar Datos de Facturación - {client.name}',
			'opts': self.model._meta,
			'has_view_permission': True,
		}
		return render(request, 'admin/clients/manage_billing.html', context)


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


class ClientBillingFrecuencyAdmin(admin.ModelAdmin):
	list_display = ('client', 'frequency', 'billing_date', 'get_billing_description', 'is_active')
	search_fields = ('client__name', 'frequency')
	list_filter = ('frequency', 'billing_date', 'is_active', 'weekday')
	autocomplete_fields = ('client',)
	readonly_fields = ('get_billing_description',)
	
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
