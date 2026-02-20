"""
Admin mixins for Client admin display methods.
Separates display logic from main admin configuration for better maintainability.
"""
from django.utils.html import format_html
from django.urls import reverse, path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import HttpResponseRedirect


class BalanceDisplayMixin:
	"""Mixin for balance and credit-related display methods."""
	
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


class BillingDisplayMixin:
	"""Mixin for billing-related display methods."""
	
	def get_billing_requirement_warning(self, obj):
		"""Display warning about billing address requirement"""
		if not obj.pk:
			return ''
		missing_messages = {
			'billing_data': 'Datos de Facturacion',
			'billing_address': 'Dirección Fiscal',
			'billing_frequency': 'Frecuencia de Facturación',
		}
		billing = obj.billing_info
		if not billing.is_complete:
			missing_errors = [missing_messages.get(m, m) for m in billing.missing_components]
			return format_html(
				'<div style="background-color: #fff3cd; border: 1px solid #ffc107; '
				'border-radius: 4px; color: #856404; margin-bottom: 10px; padding: 10px;">'
				'<strong>⚠️ Importante:</strong> '
				'Para poder facturar debe agregar los sugientes datos {}:'
				'<ul>{}</ul>'
				'</div>',
				'en el corporativo' if obj.corporate else 'en el cliente si no se heredan del corporativo',
				format_html(''.join(f'<li><strong>- {item}</strong></li>' for item in missing_errors))
			)
		return 'Toda la información de facturación está completa.'
	
	get_billing_requirement_warning.short_description = ''
	
	def get_billing_data_button(self, obj):
		"""Display a button to manage billing data and frequency"""
		if obj.pk:
			url = reverse('admin:clients_client_manage_billing', args=[obj.pk])
			has_billing = hasattr(obj, 'billing_data')
			has_frequency = hasattr(obj, 'billing_frecuency') and obj.billing_frecuency.exists()
			
			if has_billing and has_frequency:
				status = '<span style="color: green;">✓ Configurado</span>'
			elif has_billing or has_frequency:
				status = '<span style="color: orange;">⚠ Parcialmente configurado</span>'
			else:
				status = '<span style="color: red;">✗ No configurado</span>'
			
			return format_html(
				'<div style="padding: 10px;">{}<br><br>'
				'<a href="{}" class="button" style="margin-top: 10px;">'
				'Gestionar Datos de Facturación</a></div>',
				status, url
			)
		return 'Debe crear el cliente antes de gestionar los datos de facturación.'
	get_billing_data_button.short_description = 'Gestión de Facturación'

	def get_effective_billing_info(self, obj):
		"""Display effective billing data (own or inherited)"""
		if not obj.pk:
			return 'Guarde el cliente primero para ver información de facturación.'
		
		billing = obj.billing_info
		
		if not billing.effective.has_any:
			return format_html('<span style="color: red;">Sin datos de facturación</span>')

		source_label = {
			'own': '✓ Propios',
			'corporate': '⬆ Heredados del corporativo',
			'none': '✗ No disponible'
		}.get(billing.source, 'Desconocido')
		source_color = {
			'own': 'green',
			'corporate': 'blue',
			'none': 'red'
		}.get(billing.source, 'gray')

		result = f'<div><strong>Origen:</strong> <span style="color: {source_color};">{source_label}</span></div>'

		if billing.effective.data:
			result += f'<div><strong>RFC:</strong> {billing.effective.data.rfc}</div>'
			result += f'<div><strong>Razón Social:</strong> {billing.effective.data.razon_social[:50]}...</div>'

		if billing.effective.address:
			result += f'<div><strong>Dirección Fiscal:</strong> {str(billing.effective.address)[:80]}...</div>'
		else:
			result += '<div style="color: orange;"><strong>⚠ Sin dirección fiscal</strong></div>'
		return format_html(result)

	get_effective_billing_info.short_description = 'Datos de Facturación Efectivos'

	def get_billing_frequency_and_address(self, obj):
		"""Display effective billing frequency and fiscal address (own or inherited)."""
		if not obj.pk:
			return ''

		billing = obj.billing_info
		effective = billing.effective

		source_label = {
			'own': '✓ Propios',
			'corporate': '⬆ Heredados del corporativo',
			'none': '✗ No disponible'
		}.get(billing.source, 'Desconocido')
		source_color = {
			'own': 'green',
			'corporate': 'blue',
			'none': 'red'
		}.get(billing.source, 'gray')

		sections = [
			f'<div><strong>Origen:</strong> <span style="color: {source_color};">{source_label}</span></div>'
		]

		if effective.frequency:
			frequency = effective.frequency
			frequency_status = 'Activo' if getattr(frequency, 'is_active', False) else 'Inactivo'
			frequency_label = frequency.get_frequency_display() if hasattr(frequency, 'get_frequency_display') else frequency.frequency
			billing_date_label = frequency.get_billing_date_display() if hasattr(frequency, 'get_billing_date_display') and frequency.billing_date else None
			specifics = ''
			if frequency.billing_date == 'specific_date' and frequency.specific_day:
				specifics = f" (día {frequency.specific_day})"
			elif frequency.billing_date == 'weekday_occurrence' and frequency.weekday is not None and frequency.occurrence is not None:
				weekday = frequency.get_weekday_display()
				occurrence = frequency.get_occurrence_display()
				specifics = f" ({occurrence} {weekday})"
			next_date = ''
			if getattr(frequency, 'next_billing_date', None):
				next_date = f" · Próxima: {frequency.next_billing_date:%d/%m/%Y}"
			date_label = f" · {billing_date_label}" if billing_date_label else ''
			frequency_color = 'green' if getattr(frequency, 'is_active', False) else 'orange'
			sections.append(
				f'<div><strong>Frecuencia:</strong> {frequency_label}{date_label}{specifics} '
				f'<span style="color: {frequency_color};">({frequency_status})</span>{next_date}</div>'
			)
		else:
			sections.append('<div style="color: red;"><strong>✗ Sin frecuencia de facturación configurada.</strong></div>')

		if effective.address:
			sections.append(f'<div><strong>Dirección Fiscal:</strong> {str(effective.address)}</div>')
		else:
			sections.append('<div style="color: orange;"><strong>⚠ Sin dirección fiscal disponible.</strong></div>')

		return format_html(''.join(sections))

	get_billing_frequency_and_address.short_description = 'Frecuencia y Dirección de Facturación'

	def get_add_billing_frequency_button(self, obj):
		"""Display a button to add billing frequency in a popup window"""
		if not obj.pk:
			return 'Guarde el cliente primero para agregar frecuencia de facturación.'
		if obj.has_billing_frequency():
			return format_html(
				'<span style="color: green;">✓ Frecuencia de facturación ya configurada.</span>'
			)
		add_url = f"/admin/billing/clientbillingfrecuency/add/?client={obj.pk}"
		return format_html(
			'<a href="{}" class="button add-billing-frequency-popup" '
			'data-popup="true" '
			'style="padding: 5px 10px; background-color: #417690; color: white; '
			'text-decoration: none; border-radius: 4px; display: inline-block;">'
			'+ Agregar Frecuencia de Facturación</a>',
			add_url
		)
	get_add_billing_frequency_button.short_description = ''


class AdminActionsMixin:
	"""Mixin for custom admin actions and their related views."""
	
	def get_urls(self):
		"""Add custom URLs for manual transactions"""
		urls = super().get_urls()
		custom_urls = [
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
	
	def add_credit_view(self, request):
		"""View for manually managing client credit"""
		from . import models
		from .forms import ManualCreditTransactionForm
		
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
					from clients.services import balance_service

					if transaction_type == 'limit_change':
						# Update credit limit
						balance_service.update_credit_limit(
							client=client,
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
						paid_amount = balance_service.pay_debt(
							client=client,
							amount=amount,
							transaction_type=transaction_type,
							user=request.user,
							notes=f"[MANUAL] {description}. Transacción manual realizada por {request.user.username}. {notes}"
						)
						messages.success(
							request,
							f"Deuda reducida en ${paid_amount:.2f}. {client.name} ahora debe ${client.current_debt:.2f}."
						)

					elif transaction_type == 'payment_from_balance':
						# Pay debt using client's balance
						result = balance_service.pay_debt_from_balance(
							client=client,
							amount=amount,
							user=request.user,
							notes=f"[MANUAL] {description}. Pago con saldo realizado por {request.user.username}. {notes}"
						)
						if result['success']:
							messages.success(
								request,
								f"Pago con saldo exitoso. ${result['amount_paid']:.2f} descontados del saldo. "
								f"Saldo restante: ${result['remaining_balance']:.2f}. "
								f"Deuda restante: ${result['remaining_debt']:.2f}."
							)
						else:
							messages.error(request, f"Error en pago con saldo: {result['error']}")
							return render(request, 'admin/clients/add_credit.html', {
								'form': form,
								'title': 'Gestionar Crédito Manualmente',
								'opts': self.model._meta,
								'has_view_permission': True,
								'client': client,
							})

					elif transaction_type == 'adjustment':
						# Manual debt adjustment (could increase or decrease)
						# For simplicity, we'll treat as debt reduction
						paid_amount = balance_service.pay_debt(
							client=client,
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
		from . import models
		from .forms import BulkBalanceDepositForm
		
		if request.method == 'POST':
			form = BulkBalanceDepositForm(request.POST)
			if form.is_valid():
				clients = form.cleaned_data['clients']
				amount = form.cleaned_data['amount']
				description = form.cleaned_data['description']
				notes = form.cleaned_data['notes']
				
				from clients.services import balance_service

				successful_count = 0
				errors = []

				for client in clients:
					try:
						balance_service.add_balance(
							client=client,
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
        
