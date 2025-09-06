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
	inlines = [IndividualClientInline, CorporateClientInline, BranchInline, ContactInline, AddressInline, BillingDataInline]
	readonly_fields = ('created_at', 'updated_at')


@admin.register(models.IndividualClient)
class IndividualClientAdmin(admin.ModelAdmin):
	list_display = ('client', 'created_at', 'updated_at')
	readonly_fields = ('created_at', 'updated_at')


@admin.register(models.CorporateClient)
class CorporateClientAdmin(admin.ModelAdmin):
	list_display = ('company_name', 'client', 'tax_id', 'created_at', 'updated_at')
	search_fields = ('company_name', 'client__name', 'tax_id')
	inlines = [BranchInline, BillingDataInline, ContactInline]
	readonly_fields = ('created_at', 'updated_at')


@admin.register(models.Branch)
class BranchAdmin(admin.ModelAdmin):
	list_display = ('branch_name', 'client', 'corporate_client', 'created_at', 'updated_at')
	search_fields = ('branch_name', 'client__name', 'corporate_client__company_name')
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
	list_display = ('business_name', 'client', 'tax_id')
	search_fields = ('business_name', 'client__name', 'tax_id')
