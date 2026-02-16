from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.urls import path

from unfold.admin import ModelAdmin, StackedInline, TabularInline

from .forms import BulkProductPriceUpdateForm
from .models import ProductCategory, Product, ProductClientPrice
from . import services

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
    list_display = ('name', 'presentation', 'unit_of_measure', 'price', 'category','active')
    list_filter = ('category', 'unit_of_measure', 'active')
    search_fields = ('name', 'presentation')
    inlines = [ProductClientPriceInline]
    readonly_fields = ('created_at', 'updated_at') if hasattr(Product, 'created_at') else ()

    actions = ['bulk_update_client_prices']

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'bulk-update-prices/',
                self.admin_site.admin_view(self.bulk_update_prices_view),
                name='product_bulk_update_prices',
            ),
        ]
        return custom_urls + urls

    def bulk_update_client_prices(self, request, queryset):
        if queryset.count() != 1:
            messages.error(request, 'Seleccione exactamente un producto para actualizar precios.')
            return

        product = queryset.first()
        return TemplateResponse(
            request,
            'admin/product/bulk_update_prices.html',
            self._bulk_update_context(request, product),
        )

    bulk_update_client_prices.short_description = 'Actualizar precios por cliente (producto único)'

    def bulk_update_prices_view(self, request):
        product_id = request.POST.get('product_id')
        product = Product.objects.filter(pk=product_id).first()

        if product is None:
            messages.error(request, 'Producto no encontrado o no seleccionado.')
            return TemplateResponse(request, 'admin/product/bulk_update_prices.html', self._bulk_update_context(request, None))

        form = BulkProductPriceUpdateForm(request.POST)
        if not form.is_valid():
            return TemplateResponse(request, 'admin/product/bulk_update_prices.html', self._bulk_update_context(request, product, form))

        mode = form.cleaned_data['mode']
        value = float(form.cleaned_data['value'])
        note = form.cleaned_data.get('note', '')

        try:
            result = services.bulk_increase_product_client_prices(
                product=product,
                amount=value if mode == 'amount' else None,
                percent=value if mode == 'percent' else None,
                note=note,
                user=request.user,
            )
            messages.success(
                request,
                f"Precios actualizados para {result['updated_count']} cliente(s).",
            )
            return TemplateResponse(request, 'admin/product/bulk_update_prices.html', self._bulk_update_context(request, product))
        except Exception as exc:
            messages.error(request, f'Error al actualizar precios: {exc}')
            return TemplateResponse(request, 'admin/product/bulk_update_prices.html', self._bulk_update_context(request, product, form))

    def _bulk_update_context(self, request, product, form=None):
        form = form or BulkProductPriceUpdateForm(initial={'product_id': product.id if product else None})
        return {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'form': form,
            'product': product,
            'title': 'Actualizar precios por cliente',
        }


@admin.register(ProductClientPrice)
class ProductClientPriceAdmin(ModelAdmin):
    list_display = ('product', 'client', 'price','active', 'until_date')
    search_fields = ('product__name', 'client__name')
    list_filter = ('until_date', 'active'   )

# Register your models here.
