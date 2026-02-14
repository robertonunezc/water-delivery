from .models import ProductCategory, Product, ProductClientPrice
from django.contrib import admin

from unfold.admin import ModelAdmin, StackedInline, TabularInline

class ProductClientPriceInline(admin.TabularInline):
    model = ProductClientPrice
    extra = 0
    fields = ('client', 'price', 'until_date', 'note')


@admin.register(ProductCategory)
class ProductCategoryAdmin(ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ('name', 'presentation', 'unit_of_measure', 'price', 'category', 'min_inventory', 'max_inventory')
    list_filter = ('category', 'unit_of_measure')
    search_fields = ('name', 'presentation')
    inlines = [ProductClientPriceInline]
    readonly_fields = ('created_at', 'updated_at') if hasattr(Product, 'created_at') else ()


@admin.register(ProductClientPrice)
class ProductClientPriceAdmin(ModelAdmin):
    list_display = ('product', 'client', 'price', 'until_date')
    search_fields = ('product__name', 'client__name')
    list_filter = ('until_date',)

# Register your models here.
