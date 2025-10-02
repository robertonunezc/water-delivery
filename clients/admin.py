from django.contrib import admin
from . import models


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
	readonly_fields = ('created_at', 'updated_at', 'get_available_credit', 'get_balance_status')
	exclude = ('deleted_at',)
	
	fieldsets = (
		('Información Básica', {
			'fields': (('name', 'active'), ('type', 'corporate'), 'note')
		}),
		('Balance y Crédito', {
			'fields': (
				('balance', 'current_debt'), 
				('credit_limit', 'get_available_credit'),
				'get_balance_status'
			),
			'description': 'Gestión de saldo prepagado y crédito del cliente'
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
		from django.utils.html import format_html
		
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
