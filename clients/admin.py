from django.contrib import admin
from django.utils.html import format_html
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import path
from django.contrib import messages
from django.http import HttpResponseRedirect, HttpResponse
from django.urls import reverse
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.contrib.inlines.admin import NonrelatedTabularInline
from . import models
from .forms import (
	ManualBalanceTransactionForm, 
	ManualCreditTransactionForm, 
	BulkBalanceDepositForm,
	ClientBillingFrequencyForm
)
from .admin_mixins import BalanceDisplayMixin, BillingDisplayMixin, AdminActionsMixin
class ContactInline(TabularInline):
	model = models.Contact
	extra = 0
	exclude = ('deleted_at',)
	tab = True


@admin.register(models.Address)
class AddressAdmin(admin.ModelAdmin):
	list_display = ('street', 'municipality', 'state', 'zip_code', 'client__name')
	model = models.Address
	exclude = ('deleted_at',)
class AddressInline(StackedInline):
	model = models.Address
	extra = 0
	exclude = ('deleted_at',)
	tab = True

class ClientBillingFrecuencyInline(StackedInline):
	model = models.ClientBillingFrecuency
	extra = 0
	verbose_name = "Frecuencia de Facturación"
	verbose_name_plural = "Frecuencias de Facturación"
	classes = ('tab-billing-frequency',)
	fields = (
		('frequency', 'is_active'),
		'billing_date',
		'specific_day',
		('weekday', 'occurrence'),
		'notes'
	)
	exclude = ('deleted_at',)
	tab = True

class BillingFrecuencyInline(StackedInline):
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
	tab = True
class ClientCreditConfigInline(StackedInline):
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
	tab = True
	
class ClientBillingDataInline(StackedInline):
	model = models.BillingData
	display_fields = ('rfc', 'razon_social', 'curp')
	exclude = ('deleted_at',)
	extra = 0
	verbose_name = "Datos de Facturación"
	verbose_name_plural = "Datos de Facturación"
	tab = True
	

@admin.register(models.Client)
class ClientAdmin(BalanceDisplayMixin, BillingDisplayMixin, AdminActionsMixin, ModelAdmin):
	list_display = ('name', 'active','type','corporate', 'balance', 'current_debt','requires_billing' ,'get_available_credit')
	search_fields = ('name','type',)
	list_filter = ('active', 'type', 'corporate', 'requires_billing')
	inlines = [BillingFrecuencyInline,ClientBillingDataInline,AddressInline ,ContactInline, ClientCreditConfigInline]
	readonly_fields = (
		'created_at', 'updated_at',
		'balance', 'current_debt', 'get_available_credit',
		'get_balance_status', 'get_billing_data_button',
		'get_effective_billing_info',
		'get_billing_inheritance_status',
		'get_add_billing_frequency_button',
		'get_billing_requirement_warning'
	)
	exclude = ('deleted_at',)
	actions = ['add_balance_action', 'add_credit_action']
	change_form_template = 'admin/clients/client_change_form.html'

	class Media:
		js = (
			'clients/admin/toggle_billing_inline.js',
			'clients/admin/toggle_billing_frequency_fields.js',
			'clients/admin/toggle_corporate_field.js',
			#'clients/admin/billing_frequency_popup.js',
			'clients/admin/require_billing_update_client.js',
		)

	def get_inline_instances(self, request, obj=None):
		"""
		Conditionally show inlines based on client type and billing override settings.
		- New clients: hide all inlines
		- Corporate clients: show all inlines
		- Branch clients with billing_override_enabled=False: hide billing inlines (they inherit)
		- Branch clients with billing_override_enabled=True: show all inlines
		"""
		if obj is None:
			# Creating a new client - hide all inlines
			return []
		
		# Get all inline instances
		all_inlines = super().get_inline_instances(request, obj)
		
		# Hide billing-related inlines when billing is not required
		if not obj.requires_billing:
			filtered_inlines = [
				inline for inline in all_inlines
				if not isinstance(inline, (BillingFrecuencyInline, ClientBillingDataInline))
			]
			return filtered_inlines

		# If it's a branch client without billing override, filter out billing-related inlines
		if obj.type == 'branch' and not obj.billing_override_enabled:
			filtered_inlines = [
				inline for inline in all_inlines
				if not isinstance(inline, (BillingFrecuencyInline, ClientBillingDataInline))
			]
			return filtered_inlines
		
		# For corporate clients or branches with override enabled, show all inlines
		return all_inlines

	def get_fieldsets(self, request, obj=None):
		"""
		Show only basic fieldsets when creating a new client.
		Show all fieldsets when editing an existing client.
		"""
		# Base fieldsets for new clients
		base_fieldsets = (
			('Información Básica', {
				'fields': (('name', 'active'), ('type', 'corporate'), ('note', 'address_link'), ),
			}),
			('Balance y Crédito', {
				'fields': (
					('can_pay_with_credit', 'requires_note_for_credit'),	
					('credit_limit',),		
					('balance', 'current_debt', ), 
					('get_available_credit'),
					'get_balance_status',
				),
				'classes': ["tab"],
				'description': 'Visualización de saldo prepagado y crédito del cliente.'
			}),
		)
		
		# If creating a new client, return only base fieldsets
		if obj is None:
			return base_fieldsets
		
		# Build billing fieldsets conditionally for existing clients
		billing_fieldsets = []
		
		# Only show billing_override_enabled for branch clients
		billing_requirement_fields = ['get_billing_requirement_warning', 'requires_billing']
		if obj.type == 'branch':
			billing_requirement_fields.append('billing_override_enabled')
		
		# Build a single billing fieldset, optionally adding billing info fields
		billing_fields = list(billing_requirement_fields)
		if obj.requires_billing:
			billing_fields.extend([('get_effective_billing_info', 'get_billing_inheritance_status')])
		
		billing_fieldsets.append(
			('Información de Facturación', {
				'fields': tuple(billing_fields),
			})
		)
		
		# Return base fieldsets plus conditional billing fieldsets
		return base_fieldsets + tuple(billing_fieldsets)

	# fieldsets are managed dynamically via get_fieldsets() method
	# This ensures only relevant fieldsets are rendered based on client state


# ============================================================
# OTHER ADMIN CLASSES
# ============================================================

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
