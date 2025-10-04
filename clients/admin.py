from django.contrib import admin
from django.utils.html import format_html
from django.shortcuts import render, redirect
from django.urls import path
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from . import models
from .forms import ManualBalanceTransactionForm, ManualCreditTransactionForm, BulkBalanceDepositForm


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
	
	def get_fieldsets(self, request, obj=None):
		fieldsets = (
			('Configuración Básica', {
				'fields': (('frequency', 'is_active'), 'billing_date')
			}),
			('Fecha Específica', {
				'fields': ('specific_day',),
				'classes': ('collapse',),
				'description': 'Usar solo cuando el tipo de fecha sea "Fecha específica del mes"'
			}),
			('Día de la Semana', {
				'fields': (('weekday', 'occurrence'),),
				'classes': ('collapse',),
				'description': 'Usar solo cuando el tipo de fecha sea "Día específico de la semana"'
			}),
			('Notas', {
				'fields': ('notes',),
				'classes': ('collapse',)
			})
		)
		return fieldsets

@admin.register(models.Client)
class ClientAdmin(admin.ModelAdmin):
	list_display = ('name', 'active','type', 'balance', 'current_debt', 'get_available_credit', 'created_at', 'updated_at')
	search_fields = ('name','type',)
	list_filter = ('active', 'type')
	inlines = [ContactInline, AddressInline, BillingDataInline, ClientBillingFrecuencyInline]
	readonly_fields = ('created_at', 'updated_at', 'balance', 'current_debt', 'credit_limit', 'get_available_credit', 'get_balance_status')
	exclude = ('deleted_at',)
	actions = ['add_balance_action', 'add_credit_action']
	
	fieldsets = (
		('Información Básica', {
			'fields': (('name', 'active'), 'type', 'corporate', 'note')
		}),
		('Balance y Crédito', {
			'fields': (
				('balance', 'current_debt'), 
				('credit_limit', 'get_available_credit'),
				('can_pay_with_credit', 'requires_note_for_credit'),				
				'get_balance_status',
			),
			'description': 'Visualización de saldo prepagado y crédito del cliente.'
		}),
		('Información del Sistema', {
			'fields': (('created_at', 'updated_at'),),
			'classes': ('collapse',)
		})
	)
	
	def get_available_credit(self, obj):
		"""Display available credit for the client"""
		return f"${obj.get_available_credit():.2f}"
	get_available_credit.short_description = 'Crédito Disponible'
	
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


class ContactAdmin(admin.ModelAdmin):
	list_display = ('name', 'client', 'email', 'phone')
	search_fields = ('name', 'client__name', 'email', 'phone')
	exclude = ('deleted_at',)


class AddressAdmin(admin.ModelAdmin):
	list_display = ('street', 'city', 'state', 'zip_code', 'client')
	search_fields = ('street', 'city', 'client__name')
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
