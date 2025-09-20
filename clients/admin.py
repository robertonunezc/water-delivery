from django.contrib import admin
from . import models


class ContactInline(admin.TabularInline):
	model = models.Contact
	extra = 0


class AddressInline(admin.TabularInline):
	model = models.Address
	extra = 0


class BillingDataInline(admin.StackedInline):
	model = models.BillingData
	extra = 0

@admin.register(models.Client)
class ClientAdmin(admin.ModelAdmin):
	list_display = ('name', 'active','type' ,'created_at', 'updated_at')
	search_fields = ('name','type',)
	list_filter = ('active',)
	inlines = [ContactInline, AddressInline, BillingDataInline]
	readonly_fields = ('created_at', 'updated_at')

@admin.register(models.Contact)
class ContactAdmin(admin.ModelAdmin):
	list_display = ('name', 'client', 'email', 'phone')
	search_fields = ('name', 'client__name', 'email', 'phone')


@admin.register(models.Address)
class AddressAdmin(admin.ModelAdmin):
	list_display = ('street', 'city', 'state', 'zip_code', 'client')
	search_fields = ('street', 'city', 'client__name')


@admin.register(models.BillingData)
class BillingDataAdmin(admin.ModelAdmin):
	# show related client name via a callable
	list_display = ('rfc', 'razon_social', 'client_name')
	search_fields = ('razon_social', 'rfc',)

	def client_name(self, obj):
		return obj.client.name if obj.client else ''
	client_name.short_description = 'client'
