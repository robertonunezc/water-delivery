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
	list_display = ('name', 'active','type' ,'created_at', 'updated_at')
	search_fields = ('name','type',)
	list_filter = ('active',)
	inlines = [ContactInline, AddressInline, BillingDataInline, ClientBillingFrecuencyInline]
	readonly_fields = ('created_at', 'updated_at')
	exclude = ('deleted_at',)

@admin.register(models.Contact)
class ContactAdmin(admin.ModelAdmin):
	list_display = ('name', 'client', 'email', 'phone')
	search_fields = ('name', 'client__name', 'email', 'phone')
	exclude = ('deleted_at',)


@admin.register(models.Address)
class AddressAdmin(admin.ModelAdmin):
	list_display = ('street', 'city', 'state', 'zip_code', 'client')
	search_fields = ('street', 'city', 'client__name')
	exclude = ('deleted_at',)


@admin.register(models.BillingData)
class BillingDataAdmin(admin.ModelAdmin):
	# show related client name via a callable
	list_display = ('rfc', 'razon_social', 'client_name')
	search_fields = ('razon_social', 'rfc',)

	def client_name(self, obj):
		return obj.client.name if obj.client else ''
	client_name.short_description = 'client'


@admin.register(models.ClientBillingFrecuency)
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
