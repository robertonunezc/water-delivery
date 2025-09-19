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


class IndividualClientInline(admin.StackedInline):
	model = models.IndividualClient
	extra = 0


class CorporateClientInline(admin.StackedInline):
	model = models.CorporateClient
	extra = 0


class BranchInline(admin.StackedInline):
	model = models.Branch
	extra = 0


@admin.register(models.Client)
class ClientAdmin(admin.ModelAdmin):
	list_display = ('name', 'active', 'created_at', 'updated_at')
	search_fields = ('name',)
	list_filter = ('active',)
	inlines = [IndividualClientInline, BranchInline, ContactInline, AddressInline, BillingDataInline]
	readonly_fields = ('created_at', 'updated_at')


@admin.register(models.IndividualClient)
class IndividualClientAdmin(admin.ModelAdmin):
	list_display = ('client', 'created_at', 'updated_at')
	readonly_fields = ('created_at', 'updated_at')


@admin.register(models.CorporateClient)
class CorporateClientAdmin(admin.ModelAdmin):
	# CorporateClient does not have a direct FK to Client in models; show company_name and tax_id
	list_display = ('company_name', 'tax_id', 'created_at', 'updated_at')
	search_fields = ('company_name', 'tax_id')
	# Only BranchInline is valid here because Branch has a FK to CorporateClient.
	inlines = [BranchInline]
	readonly_fields = ('created_at', 'updated_at')


@admin.register(models.Branch)
class BranchAdmin(admin.ModelAdmin):
	# Branch model defines no field `branch_name` in models.py; use `pk` or __str__ instead.
	list_display = ('pk', 'client', 'corporate_client', 'created_at', 'updated_at')
	search_fields = ('client__name', 'corporate_client__company_name')
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
