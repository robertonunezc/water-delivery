from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q
from django.urls import reverse

from .models import Product, ProductClientPrice
from .forms import ProductForm, ProductClientPriceFormSet
from .services import ensure_product_for_all_clients


def _is_admin_user(user) -> bool:
    return user.is_authenticated and user.is_staff


@user_passes_test(_is_admin_user)
def list_products_admin(request):
    search_query = request.GET.get('search', '').strip()
    
    queryset = Product.all_objects.select_related('category').order_by('name')
    
    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query) |
            Q(note__icontains=search_query) |
            Q(presentation__icontains=search_query)
        ).distinct()
        
    paginator = Paginator(queryset, 10)
    page = request.GET.get('page')
    
    try:
        products = paginator.page(page)
    except PageNotAnInteger:
        products = paginator.page(1)
    except EmptyPage:
        products = paginator.page(paginator.num_pages)
        
    context = {
        'products': products,
        'search_query': search_query,
        'total_products': paginator.count,
        'has_search': bool(search_query),
    }
    return render(request, 'admin/products/list.html', context)


@user_passes_test(_is_admin_user)
def create_product_admin(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save()
            
            if form.cleaned_data.get('add_to_all_clients'):
                summary = ensure_product_for_all_clients(product, request.user)
                if summary.get('created_count', 0) > 0:
                    messages.info(request, f"Se agregó el producto a {summary['created_count']} clientes.")
                    
            messages.success(request, 'Producto creado exitosamente.')
            return redirect('admin_edit_product', pk=product.pk)
    else:
        form = ProductForm()
        
    context = {
        'form': form,
        'product': None,
        'is_create': True,
        'active_tab': 'basic',
    }
    return render(request, 'admin/products/form.html', context)


@user_passes_test(_is_admin_user)
def edit_product_admin(request, pk):
    product = get_object_or_404(Product.all_objects, pk=pk)
    active_tab = request.GET.get('tab', 'basic')
    
    if request.method == 'POST':
        section = request.POST.get('section', 'basic')
        active_tab = section
        
        if section == 'basic':
            form = ProductForm(request.POST, instance=product)
            if form.is_valid():
                form.save()
                
                if form.cleaned_data.get('add_to_all_clients'):
                    summary = ensure_product_for_all_clients(product, request.user)
                    if summary.get('created_count', 0) > 0:
                        messages.info(request, f"Se agregó el producto a {summary['created_count']} clientes adicionales.")
                        
                messages.success(request, 'Datos del producto actualizados correctamente.')
                return redirect(f"{reverse('admin_edit_product', kwargs={'pk': product.pk})}?tab=basic")
                
            formset = ProductClientPriceFormSet(instance=product)
            
        elif section == 'prices':
            form = ProductForm(instance=product)
            formset = ProductClientPriceFormSet(request.POST, instance=product)
            if formset.is_valid():
                formset.save()
                messages.success(request, 'Precios por cliente actualizados correctamente.')
                return redirect(f"{reverse('admin_edit_product', kwargs={'pk': product.pk})}?tab=prices")
                
    else:
        form = ProductForm(instance=product)
        formset = ProductClientPriceFormSet(instance=product)
        
    context = {
        'form': form,
        'formset': formset,
        'product': product,
        'is_create': False,
        'active_tab': active_tab,
    }
    return render(request, 'admin/products/form.html', context)
