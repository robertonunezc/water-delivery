from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Optional, List
from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from core.models import TimeStampedModel
from core.utils import get_first_last_day_of_month
#Client types
CLIENT_TYPE_CHOICES = [
    ('corporate', 'Corporativo'),
    ('branch', 'Sucursal'),
]
PAYMENT_METHOD_CHOICES = [
    ('cash', 'Efectivo'),
    ('credit_card', 'Tarjeta de Crédito'),
    ('bank_transfer', 'Transferencia Bancaria'),
    ('balance', 'Saldo'),
    ('credit', 'Crédito'),
    ('other', 'Otro'),
]
BILLING_FREQUENCY_CHOICES = [
    ('when_delivery', 'Contra entrega'),
    ('weekly', 'Semanal'),
    ('biweekly', 'Quincenal'),
    ('monthly', 'Mensual'),
]
BILLING_DATE_CHOICES = [
    ('specific_date', 'Fecha específica del mes'),
    ('last_day', 'Último día del mes'),
    ('first_day', 'Primer día del mes'),
    ('weekday_occurrence', 'Día específico de la semana'),
]

WEEKDAY_CHOICES = [
    (0, 'Lunes'),
    (1, 'Martes'),
    (2, 'Miércoles'),
    (3, 'Jueves'),
    (4, 'Viernes'),
    (5, 'Sábado'),
    (6, 'Domingo'),
]

OCCURRENCE_CHOICES = [
    (1, 'Primer'),
    (2, 'Segundo'),
    (3, 'Tercer'),
    (4, 'Cuarto'),
    (-1, 'Último'),
]

REGIMEN_FISCAL_CHOICES = [
    ('601', '601 - Régimen General de Ley Personas Morales'),
    ('602', '602 - Régimen Simplificado de Ley Personas Morales'),
    ('603', '603 - Personas Morales con Fines no Lucrativos'),
    ('604', '604 - Régimen de Pequeños Contribuyentes'),
    ('605', '605 - Régimen de Sueldos y Salarios e Ingresos Asimilados a Salarios'),
    ('606', '606 - Régimen de Arrendamiento'),
    ('607', '607 - Régimen de Enajenación o Adquisición de Bienes'),
    ('608', '608 - Régimen de los Demás Ingresos'),
    ('609', '609 - Régimen de Consolidación'),
    ('610', '610 - Régimen Residentes en el Extranjero sin Establecimiento Permanente en México'),
    ('611', '611 - Régimen de Ingresos por Dividendos (socios y accionistas)'),
    ('612', '612 - Régimen de las Personas Físicas con Actividades Empresariales y Profesionales'),
    ('613', '613 - Régimen Intermedio de las Personas Físicas con Actividades Empresariales'),
    ('614', '614 - Régimen de los Ingresos por Intereses'),
    ('615', '615 - Régimen de los Ingresos por Obtención de Premios'),
    ('616', '616 - Sin Obligaciones Fiscales'),
    ('617', '617 - PEMEX'),
    ('618', '618 - Régimen Simplificado de Ley Personas Físicas'),
    ('619', '619 - Ingresos por la Obtención de Préstamos'),
    ('620', '620 - Sociedades Cooperativas de Producción que Optan por Diferir sus Ingresos'),
    ('621', '621 - Régimen de Incorporación Fiscal'),
    ('622', '622 - Régimen de Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras PM'),
    ('623', '623 - Régimen de Opcional para Grupos de Sociedades'),
    ('624', '624 - Régimen de los Coordinados'),
    ('625', '625 - Régimen de las Actividades Empresariales con Ingresos a través de Plataformas Tecnológicas'),
    ('626', '626 - Régimen Simplificado de Confianza'),
]

USO_CFDI_CHOICES = [
    ('G01', 'G01 - Adquisición de mercancías'),
    ('G02', 'G02 - Devoluciones, descuentos o bonificaciones'),
    ('G03', 'G03 - Gastos en general'),
    ('I01', 'I01 - Construcciones'),
    ('I02', 'I02 - Mobilario y equipo de oficina por inversiones'),
    ('I03', 'I03 - Equipo de transporte'),
    ('I04', 'I04 - Equipo de computo y accesorios'),
    ('I05', 'I05 - Dados, troqueles, moldes, matrices y herramental'),
    ('I06', 'I06 - Comunicaciones telefónicas'),
    ('I07', 'I07 - Comunicaciones satelitales'),
    ('I08', 'I08 - Otra maquinaria y equipo'),
    ('D01', 'D01 - Honorarios médicos, dentales y gastos hospitalarios'),
    ('D02', 'D02 - Gastos médicos por incapacidad o discapacidad'),
    ('D03', 'D03 - Gastos funerales'),
    ('D04', 'D04 - Donativos'),
    ('D05', 'D05 - Intereses reales efectivamente pagados por créditos hipotecarios (casa habitación)'),
    ('D06', 'D06 - Aportaciones voluntarias al SAR'),
    ('D07', 'D07 - Primas por seguros de gastos médicos'),
    ('D08', 'D08 - Gastos de transportación escolar obligatoria'),
    ('D09', 'D09 - Depósitos en cuentas para el ahorro, primas que tengan como base planes de pensiones'),
    ('D10', 'D10 - Pagos por servicios educativos (colegiaturas)'),
    ('P01', 'P01 - Por definir'),
]

class Client(TimeStampedModel):
    name = models.CharField(max_length=100, db_index=True, verbose_name="Nombre del cliente")
    active = models.BooleanField(default=True, verbose_name="Activo")
    note = models.TextField(blank=True, null=True, verbose_name="Notas")
    type = models.CharField(max_length=50, choices=CLIENT_TYPE_CHOICES, default='branch', verbose_name="Tipo de cliente")
    corporate = models.ForeignKey('Client', related_name='branches', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Cliente corporativo", limit_choices_to={'type': 'corporate'})
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Saldo a favor", help_text="Monto prepagado disponible para usar en pedidos")
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Límite de crédito", help_text="Máximo monto que el cliente puede deber")
    current_debt = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Deuda actual", help_text="Monto actual que debe el cliente")
    can_pay_with_credit = models.BooleanField(default=True, verbose_name="Puede pagar con crédito", help_text="Si está deshabilitado, el cliente no podrá usar crédito para pagos cuando su saldo disponible sea 0")
    requires_note_for_credit = models.BooleanField(default=False, verbose_name="Requiere justificación para crédito", help_text="Si está habilitado, se requerirá una justificación obligatoria al realizar pagos con crédito")
    address_link = models.CharField(max_length=255, blank=True, null=True, verbose_name="Enlace de dirección", help_text="Enlace a Google Maps u otro servicio de mapas")
    requires_billing = models.BooleanField(default=False, verbose_name="Requiere facturación", help_text="Indica si el cliente necesita facturación formal")
    #Notification sent 
    last_first_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    last_second_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    last_cancellation_sent_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        indexes = [
            models.Index(fields=['name'], name='clients_client_name_idx'),
            models.Index(fields=['active'], name='clients_client_active_idx'),
            models.Index(fields=['type'], name='clients_client_type_idx'),
        ]
    
    def __str__(self):
        return self.name
    
    # Balance and Credit Management Methods
    # TODO: review if this is a good idea or if we should handle transactions outside the model
    def add_balance(self, amount, transaction_type='deposit', user=None, reference_order=None, reference_payment=None, transfer_to_client=None, notes=None, source='automatic'):
        """
        Add money to client's balance with transaction history
        
        Args:
            amount: Amount to add
            transaction_type: Type of transaction (deposit, refund, transfer_in, adjustment, correction)
            user: User performing the transaction
            reference_order: Related order (if applicable)
            reference_payment: Related payment (if applicable)
            transfer_to_client: Target client for transfers (if applicable)
            notes: Additional notes
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
        
        # Store previous balance
        balance_before = self.balance
        
        # Update balance
        self.balance += amount
        balance_after = self.balance
        
        # Save client first
        self.save()
        
        # Create transaction record
        final_notes = notes or f"{transaction_type.replace('_', ' ').title()} de ${amount:.2f}"
        BalanceTransaction.objects.create(
            client=self,
            transaction_type=transaction_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            notes=final_notes,
            reference_order=reference_order,
            reference_payment=reference_payment,
            transfer_to_client=transfer_to_client,
            created_by=user
        )
        
        return self.balance
    
    def deduct_balance(self, amount, transaction_type='payment', user=None, reference_order=None, reference_payment=None, transfer_to_client=None, notes=None):
        """
        Deduct money from client's balance with transaction history
        
        Args:
            amount: Amount to deduct
            transaction_type: Type of transaction (payment, transfer_out, adjustment, correction)
            user: User performing the transaction
            reference_order: Related order (if applicable)
            reference_payment: Related payment (if applicable)
            transfer_to_client: Target client for transfers (if applicable)
            notes: Additional notes
            
        Returns:
            True if successful, False if insufficient balance
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
            
        if self.balance < amount:
            return False
        
        # Store previous balance
        balance_before = self.balance
        
        # Update balance
        self.balance -= amount
        balance_after = self.balance
        
        # Save client first
        self.save()
        
        # Create transaction record
        final_notes = notes or f"{transaction_type.replace('_', ' ').title()} de ${amount:.2f}"
        BalanceTransaction.objects.create(
            client=self,
            transaction_type=transaction_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            notes=final_notes,
            reference_order=reference_order,
            reference_payment=reference_payment,
            transfer_to_client=transfer_to_client,
            created_by=user
        )
        
        return True
    
    def add_debt(self, amount, transaction_type='purchase', user=None, reference_order=None, reference_payment=None, notes=None):
        """
        Add to client's debt with transaction history
        
        Args:
            amount: Amount to add to debt
            transaction_type: Type of transaction (purchase, interest, fee, adjustment, correction)
            user: User performing the transaction
            reference_order: Related order (if applicable)
            reference_payment: Related payment (if applicable)
            notes: Additional notes
            
        Returns:
            True if within credit limit, False otherwise
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
            
        new_debt = self.current_debt + amount
        if new_debt > self.credit_limit:
            # Only block if client cannot pay with credit
            if not self.can_pay_with_credit:
                return False
            else:
                # Log warning but allow the transaction for clients who can pay with credit
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f'Client {self.id} ({self.name}) debt will exceed credit limit. '
                    f'New debt: ${new_debt:.2f}, Credit limit: ${self.credit_limit:.2f}. '
                    f'Allowing due to can_pay_with_credit=True.'
                )
        
        # Store previous values
        debt_before = self.current_debt
        credit_limit_before = self.credit_limit
        
        # Update debt
        self.current_debt = new_debt
        debt_after = self.current_debt
        
        # Save client first
        self.save()
        
        # Create transaction record
        combined_notes = notes or f"{transaction_type.replace('_', ' ').title()} de ${amount:.2f}"
            
        CreditTransaction.objects.create(
            client=self,
            transaction_type=transaction_type,
            amount=amount,
            debt_before=debt_before,
            debt_after=debt_after,
            credit_limit_before=credit_limit_before,
            credit_limit_after=self.credit_limit,
            notes=combined_notes,
            reference_order=reference_order,
            reference_payment=reference_payment,
            created_by=user
        )
        
        return True
    
    def pay_debt(self, amount, transaction_type='payment', user=None, reference_order=None, reference_payment=None, notes=None):
        """
        Pay down client's debt with transaction history
        
        Args:
            amount: Amount to pay towards debt
            transaction_type: Type of transaction (payment, adjustment, forgiveness, correction)
            user: User performing the transaction
            reference_order: Related order (if applicable)
            reference_payment: Related payment (if applicable)
            notes: Additional notes
            
        Returns:
            Amount actually paid (limited by current debt)
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
            
        payment_amount = min(amount, self.current_debt)
        
        if payment_amount == 0:
            return 0
        
        # Store previous values
        debt_before = self.current_debt
        credit_limit_before = self.credit_limit
        
        # Update debt
        self.current_debt -= payment_amount
        debt_after = self.current_debt
        
        # Save client first
        self.save()
        
        # Create transaction record
        final_notes = notes or f"{transaction_type.replace('_', ' ').title()} de ${payment_amount:.2f}"
        CreditTransaction.objects.create(
            client=self,
            transaction_type=transaction_type,
            amount=payment_amount,
            debt_before=debt_before,
            debt_after=debt_after,
            credit_limit_before=credit_limit_before,
            credit_limit_after=self.credit_limit,
            notes=final_notes,
            reference_order=reference_order,
            reference_payment=reference_payment,
            created_by=user
        )
        
        return payment_amount
    
    def update_credit_limit(self, new_limit, user=None, notes=None):
        """
        Update client's credit limit with transaction history
        
        Args:
            new_limit: New credit limit amount
            user: User performing the transaction
            notes: Additional notes
        """
        if new_limit < 0:
            raise ValueError("Credit limit cannot be negative")
            
        if new_limit == self.credit_limit:
            return  # No change needed
        
        # Store previous values
        debt_before = self.current_debt
        credit_limit_before = self.credit_limit
        
        # Update credit limit
        self.credit_limit = new_limit
        
        # Save client first
        self.save()
        
        # Create transaction record
        final_notes = notes or f"Cambio de límite de crédito de ${credit_limit_before:.2f} a ${new_limit:.2f}"
        CreditTransaction.objects.create(
            client=self,
            transaction_type='limit_change',
            amount=abs(new_limit - credit_limit_before),
            debt_before=debt_before,
            debt_after=self.current_debt,
            credit_limit_before=credit_limit_before,
            credit_limit_after=new_limit,
            notes=final_notes,
            created_by=user
        )
    
    def pay_debt_from_balance(self, amount, user=None, reference_order=None, reference_payment=None, notes=None):
        """
        Pay client's debt using their available balance
        
        Args:
            amount: Amount to pay towards debt using balance
            user: User performing the transaction
            reference_order: Related order (if applicable)
            reference_payment: Related payment (if applicable)
            notes: Additional notes
            
        Returns:
            dict: Result with success status and details
        """
        if amount <= 0:
            return {'success': False, 'error': 'Amount must be positive'}
        
        # Check if client has sufficient balance
        if self.balance < amount:
            return {
                'success': False,
                'error': f'Saldo insuficiente. Disponible: ${self.balance:.2f}, Requerido: ${amount:.2f}'
            }
        
        # Check if there's enough debt to pay
        if self.current_debt < amount:
            return {
                'success': False,
                'error': f'Monto excede la deuda actual. Deuda: ${self.current_debt:.2f}, Intentando pagar: ${amount:.2f}'
            }
        
        # Calculate actual payment amount (limited by debt)
        payment_amount = min(amount, self.current_debt)
        
        try:
            # Store previous values for both balance and debt
            balance_before = self.balance
            debt_before = self.current_debt
            
            # Update both balance and debt
            self.balance -= payment_amount
            self.current_debt -= payment_amount
            
            # Save client
            self.save()
            
            # Create balance transaction (deduction)
            balance_notes = notes or f"Pago de deuda con saldo - ${payment_amount:.2f}"
            BalanceTransaction.objects.create(
                client=self,
                transaction_type='payment',
                amount=payment_amount,
                balance_before=balance_before,
                balance_after=self.balance,
                notes=f"[PAGO DEUDA] {balance_notes}",
                reference_order=reference_order,
                reference_payment=reference_payment,
                created_by=user
            )
            
            # Create credit transaction (debt reduction)
            credit_notes = notes or f"Pago con saldo - ${payment_amount:.2f}"
            CreditTransaction.objects.create(
                client=self,
                transaction_type='payment_from_balance',
                amount=payment_amount,
                debt_before=debt_before,
                debt_after=self.current_debt,
                credit_limit_before=self.credit_limit,
                credit_limit_after=self.credit_limit,
                notes=f"[PAGO CON SALDO] {credit_notes}",
                reference_order=reference_order,
                reference_payment=reference_payment,
                created_by=user
            )
            
            return {
                'success': True,
                'amount_paid': payment_amount,
                'remaining_balance': self.balance,
                'remaining_debt': self.current_debt,
                'available_credit': self.get_available_credit()
            }
            
        except Exception as e:
            # Rollback client changes
            self.refresh_from_db()
            return {'success': False, 'error': f'Error processing payment: {str(e)}'}
    
    def get_available_credit(self):
        """Get remaining credit available"""
        return self.credit_limit - self.current_debt
    
    def can_use_credit_for_payment(self):
        """
        Check if client can use credit for payments based on their settings and available credit
        
        Returns:
            bool: True if client can use credit, False otherwise
        """
        # If credit payment is disabled for this client
        if not self.can_pay_with_credit:
            # Only allow if they have available credit (positive balance)
            return self.get_available_credit() > 0
        
        # If credit payment is enabled, they can use it regardless of current balance
        return True
    
    def requires_note_for_credit_payment(self):
        """
        Check if client requires a note when making credit payments
        
        Returns:
            bool: True if note is required, False otherwise
        """
        return self.requires_note_for_credit
    
    def validate_credit_payment(self, amount, note=None):
        """
        Validate if a credit payment can be processed
        
        Args:
            amount: Amount to be paid with credit
            note: Note provided for the transaction
            
        Returns:
            dict: Validation result with success status and error message if applicable
        """
        # Check if client can use credit
        if not self.can_use_credit_for_payment():
            return {
                'success': False,
                'error': 'Client is not allowed to pay with credit at this time.',
                'error_code': 'CREDIT_DISABLED'
            }
        
        # Check if note is required
        if self.requires_note_for_credit_payment() and not note:
            return {
                'success': False,
                'error': 'A note is required for credit payments for this client.',
                'error_code': 'NOTE_REQUIRED'
            }
        
        # For clients that can pay with credit, allow payments even if they exceed the credit limit
        # This allows for negative credit balances when necessary
        available_credit = self.get_available_credit()
        if available_credit < amount:
            # Log a warning but allow the payment to proceed
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f'Client {self.id} ({self.name}) credit payment of ${amount:.2f} '
                f'exceeds available credit of ${available_credit:.2f}. '
                f'This will result in exceeding credit limit.'
            )
        
        return {'success': True}
    
    def can_afford_order(self, order_amount):
        """Check if client can afford an order using balance + available credit"""
        available_balance = self.balance
        available_credit = 0
        
        # Only include available credit if client can use credit for payments
        if self.can_use_credit_for_payment():
            available_credit = self.get_available_credit()
        
        return (available_balance + available_credit) >= order_amount
    
    def process_order_payment(self, order_amount, preferred_method='auto', order=None, user=None, credit_note=None):
        """
        Process payment for an order using different strategies
        
        Args:
            order_amount: Amount to process
            preferred_method: 'auto', 'balance', 'credit', 'mixed'
            order: Order object for transaction reference
            user: User performing the operation
            credit_note: Required note when using credit if client requires it
        """
        remaining_amount = order_amount
        balance_used = 0
        credit_used = 0
        
        if preferred_method == 'balance':
            # Try to pay entirely with balance
            if self.balance >= order_amount:
                balance_used = order_amount
                remaining_amount = 0
            else:
                return {
                    'success': False,
                    'error': f'Insufficient balance. Available: ${self.balance:.2f}, Required: ${order_amount:.2f}',
                    'balance_used': 0,
                    'credit_used': 0
                }
                
        elif preferred_method == 'credit':
            # Check if client can use credit
            if not self.can_use_credit_for_payment():
                return {
                    'success': False,
                    'error': 'Client is not allowed to pay with credit at this time.',
                    'balance_used': 0,
                    'credit_used': 0
                }
            
            # Check if note is required for credit payments
            if self.requires_note_for_credit_payment() and not credit_note:
                return {
                    'success': False,
                    'error': 'A note is required for credit payments for this client.',
                    'balance_used': 0,
                    'credit_used': 0,
                    'note_required': True
                }
            
            # Try to pay entirely with credit
            available_credit = self.get_available_credit()
            if available_credit >= order_amount:
                credit_used = order_amount
                remaining_amount = 0
            else:
                return {
                    'success': False,
                    'error': f'Insufficient credit. Available: ${available_credit:.2f}, Required: ${order_amount:.2f}',
                    'balance_used': 0,
                    'credit_used': 0
                }
                
        else:  # 'auto' or 'mixed'
            # First, use available balance
            balance_used = min(self.balance, remaining_amount)
            remaining_amount -= balance_used
            
            # Then, use credit if needed and available
            if remaining_amount > 0:
                # Check if client can use credit
                if not self.can_use_credit_for_payment():
                    return {
                        'success': False,
                        'error': f'Client cannot use credit. Need additional ${remaining_amount:.2f} in balance.',
                        'balance_used': 0,
                        'credit_used': 0,
                        'balance_available': self.balance,
                        'credit_available': 0
                    }
                
                # Check if note is required for credit payments
                if self.requires_note_for_credit_payment() and not credit_note:
                    return {
                        'success': False,
                        'error': 'A note is required for credit payments for this client.',
                        'balance_used': 0,
                        'credit_used': 0,
                        'note_required': True
                    }
                
                available_credit = self.get_available_credit()
                credit_used = min(available_credit, remaining_amount)
                remaining_amount -= credit_used
        
        # Check if we can cover the full amount
        if remaining_amount > 0:
            return {
                'success': False,
                'error': f'Insufficient funds. Need additional ${remaining_amount:.2f}',
                'balance_used': 0,
                'credit_used': 0,
                'balance_available': self.balance,
                'credit_available': self.get_available_credit()
            }
        
        # Actually process the payment (deduct balance and add debt)
        if balance_used > 0:
            self.deduct_balance(
                amount=balance_used,
                transaction_type='payment',
                user=user,
                reference_order=order,
                notes=f'Pago de orden con saldo - ${balance_used:.2f}'
            )
        if credit_used > 0:
            self.add_debt(
                amount=credit_used,
                transaction_type='purchase',
                user=user,
                reference_order=order,
                notes=f'Compra a crédito - ${credit_used:.2f}. {credit_note}' if credit_note else f'Compra a crédito - ${credit_used:.2f}'
            )
        
        return {
            'success': True,
            'balance_used': balance_used,
            'credit_used': credit_used,
            'remaining_balance': self.balance,
            'current_debt': self.current_debt,
            'available_credit': self.get_available_credit()
        }
    
    def create_payment_for_order(self, order, payment_method='auto', user=None, credit_note=None):
        """
        Create payment records for an order based on how the payment was processed
        """
        from payment.models import Payment
        
        order_amount = order.total_amount
        payment_result = self.process_order_payment(order_amount, payment_method, order=order, user=user, credit_note=credit_note)
        
        if not payment_result['success']:
            return {'success': False, 'error': payment_result['error']}
        
        payments_created = []
        
        # Create balance payment if balance was used
        if payment_result['balance_used'] > 0:
            balance_payment = Payment.objects.create(
                amount=payment_result['balance_used'],
                method='balance',
                client=self,
                order=order,
                status='completed',
                balance_used=payment_result['balance_used']
            )
            payments_created.append(balance_payment)
        
        # Create credit payment if credit was used
        if payment_result['credit_used'] > 0:
            credit_payment = Payment.objects.create(
                amount=payment_result['credit_used'],
                method='credit',
                client=self,
                order=order,
                status='completed',
                credit_used=payment_result['credit_used']
            )
            payments_created.append(credit_payment)
        
        return {
            'success': True,
            'payments': payments_created,
            'payment_breakdown': payment_result
        }
    
    def send_payment_reminder(self):
        """Determine if a payment reminder should be sent based on max payment days"""
        if self.max_payment_days is None or self.requires_billing is False:
            return False
        today = date.today()
        last_payment_date = self.orders.filter(status='completed').order_by('-completed_at').first()
        if not last_payment_date:
            return True  # No payments made yet
        due_date = last_payment_date.completed_at.date() + timedelta(days=self.max_payment_days)
        client_notification_settings = self.notification_settings.all()
        
        # Logic to check if there are unpaid invoices past due_date would go here
    
    # Balance and Credit History Methods
    def get_balance_history(self, start_date=None, end_date=None, transaction_types=None):
        """
        Get balance transaction history for the client
        
        Args:
            start_date: Filter transactions after this date
            end_date: Filter transactions before this date
            transaction_types: List of transaction types to filter by
            
        Returns:
            QuerySet of BalanceTransaction objects
        """
        queryset = self.balance_transactions.all()
        
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        if transaction_types:
            queryset = queryset.filter(transaction_type__in=transaction_types)
            
        return queryset
    
    def get_credit_history(self, start_date=None, end_date=None, transaction_types=None):
        """
        Get credit transaction history for the client
        
        Args:
            start_date: Filter transactions after this date
            end_date: Filter transactions before this date
            transaction_types: List of transaction types to filter by
            
        Returns:
            QuerySet of CreditTransaction objects
        """
        queryset = self.credit_transactions.all()
        
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        if transaction_types:
            queryset = queryset.filter(transaction_type__in=transaction_types)
            
        return queryset
    
    def get_balance_at_date(self, target_date):
        """
        Calculate client's balance at a specific date by replaying transactions
        
        Args:
            target_date: Date to calculate balance for
            
        Returns:
            Decimal: Balance amount at the specified date
        """
        from django.db.models import Sum
        from decimal import Decimal
        
        # Get all balance transactions up to target date
        transactions = self.balance_transactions.filter(created_at__lte=target_date).order_by('created_at')
        
        if not transactions.exists():
            return Decimal('0.00')
        
        # Get the last transaction at or before target date
        last_transaction = transactions.last()
        return last_transaction.balance_after
    
    def get_debt_at_date(self, target_date):
        """
        Calculate client's debt at a specific date by replaying transactions
        
        Args:
            target_date: Date to calculate debt for
            
        Returns:
            Decimal: Debt amount at the specified date
        """
        from django.db.models import Sum
        from decimal import Decimal
        
        # Get all credit transactions up to target date
        transactions = self.credit_transactions.filter(created_at__lte=target_date).order_by('created_at')
        
        if not transactions.exists():
            return Decimal('0.00')
        
        # Get the last transaction at or before target date
        last_transaction = transactions.last()
        return last_transaction.debt_after
    
    def get_financial_summary(self, start_date=None, end_date=None):
        """
        Get comprehensive financial summary for the client
        
        Args:
            start_date: Filter transactions after this date
            end_date: Filter transactions before this date
            
        Returns:
            Dict with financial summary data
        """
        from django.db.models import Sum, Count
        from decimal import Decimal
        
        # Balance transactions summary
        balance_qs = self.get_balance_history(start_date, end_date)
        balance_summary = {
            'total_deposits': balance_qs.filter(
                transaction_type__in=['deposit', 'refund', 'transfer_in']
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
            'total_payments': balance_qs.filter(
                transaction_type__in=['payment', 'transfer_out']
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
            'transaction_count': balance_qs.count(),
        }
        
        # Credit transactions summary
        credit_qs = self.get_credit_history(start_date, end_date)
        credit_summary = {
            'total_purchases': credit_qs.filter(
                transaction_type__in=['purchase', 'interest', 'fee']
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
            'total_payments': credit_qs.filter(
                transaction_type='payment'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
            'transaction_count': credit_qs.count(),
        }
        
        return {
            'current_balance': self.balance,
            'current_debt': self.current_debt,
            'credit_limit': self.credit_limit,
            'available_credit': self.get_available_credit(),
            'balance_summary': balance_summary,
            'credit_summary': credit_summary,
            'period_start': start_date,
            'period_end': end_date,
        }
    
    def transfer_balance_to(self, target_client, amount, user=None, notes=None):
        """
        Transfer balance from this client to another client
        
        Args:
            target_client: Client to transfer balance to
            amount: Amount to transfer
            user: User performing the transfer
            notes: Additional notes
            
        Returns:
            Dict with success status and details
        """
        if amount <= 0:
            return {'success': False, 'error': 'Amount must be positive'}
        
        if self.balance < amount:
            return {
                'success': False, 
                'error': f'Insufficient balance. Available: ${self.balance:.2f}, Required: ${amount:.2f}'
            }
        
        try:
            # Deduct from source client
            transfer_notes = notes or f'Transferencia a {target_client.name}'
            success = self.deduct_balance(
                amount=amount,
                transaction_type='transfer_out',
                user=user,
                transfer_to_client=target_client,
                notes=transfer_notes
            )
            
            if not success:
                return {'success': False, 'error': 'Failed to deduct from source account'}
            
            # Add to target client
            receive_notes = notes or f'Transferencia de {self.name}'
            target_client.add_balance(
                amount=amount,
                transaction_type='transfer_in',
                user=user,
                transfer_to_client=self,
                notes=receive_notes
            )
            
            return {
                'success': True,
                'amount_transferred': amount,
                'source_balance': self.balance,
                'target_balance': target_client.balance
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    def has_billing_address(self):
        """Check if client has at least one billing address"""
        return self.addresses.filter(type='billing').exists()

    def has_shipping_address(self):
        """Check if client has at least one active shipping address"""
        return self.addresses.filter(type='shipping', active=True).exists()

    def can_receive_orders(self):
        """
        Check if client is ready to receive orders.
        Branches require their own shipping address (they don't inherit from corporate).

        Returns:
            tuple: (bool, str) - (can_receive, error_message)
        """
        if self.type == 'branch':
            if not self.has_shipping_address():
                return False, 'La sucursal debe tener un domicilio de envío (ubicación física) antes de recibir pedidos.'

        # Add other validations as needed
        if not self.active:
            return False, 'El cliente no está activo.'

        return True, ''

    def get_effective_billing_data(self):
        """
        Returns own BillingData or corporate's if branch without own billing data.

        Returns:
            BillingData instance or None
        """

        # First, check if this client has its own billing data
        if hasattr(self, 'billing_data'):
            return self.billing_data

        # If this is a branch and no own billing data, check corporate
        if self.type == 'branch' and self.corporate:
            return self.corporate.get_effective_billing_data()

        return None

    def get_effective_billing_address(self):
        """
        Returns own billing address or corporate's if branch without own billing address.

        Returns:
            Address instance or None
        """
        # First, check if this client has its own billing address
        own_billing = self.addresses.filter(type='billing', active=True).first()
        if own_billing:
            return own_billing

        # If this is a branch and no own billing address, check corporate
        if self.type == 'branch' and self.corporate:
            return self.corporate.get_effective_billing_address()

        return None

    def has_complete_billing_setup(self):
        """
        Check if client has complete billing setup (both BillingData and billing Address).
        For branches, checks inherited setup if own setup is incomplete.

        Returns:
            bool: True if complete billing setup exists
        """
        effective_billing_data = self.get_effective_billing_data()
        effective_billing_address = self.get_effective_billing_address()

        return effective_billing_data is not None and effective_billing_address is not None

    def get_billing_source(self):
        """
        Determine where billing data comes from (useful for admin display).

        Returns:
            str: 'own', 'corporate', or 'none'
        """
        has_own_data = hasattr(self, 'billing_data')
        has_own_address = self.addresses.filter(type='billing', active=True).exists()
        if has_own_data and has_own_address:
            return 'own'
        elif self.type == 'branch' and self.corporate:
            corporate_has_data = hasattr(self.corporate, 'billing_data')
            corporate_has_address = self.corporate.addresses.filter(type='billing', active=True).exists()
            if corporate_has_data or corporate_has_address:
                return 'corporate'

        return 'none'

    # Validate that if type is 'branch', corporate must be set
    def clean(self):
        super().clean()

        errors = {}
        from django.core.exceptions import ValidationError

        # Existing validations
        if self.type == 'branch' and not self.corporate:
            errors['corporate'] = 'Cliente sucursal debe tener un cliente corporativo asociado.'
        if self.type == 'corporate' and self.corporate:
            errors['corporate'] = 'Cliente corporativo no puede tener un padre corporativo.'

        # NEW: Validate billing setup for branches that require billing
        # Only validate if the client has been saved (has a pk)
        if self.type == 'branch' and self.requires_billing and self.corporate and self.pk:
            # Check if branch or corporate has complete billing setup
            has_own_billing = (
                hasattr(self, 'billing_data') and
                self.addresses.filter(type='billing', active=True).exists()
            )

            if not has_own_billing:
                # Branch doesn't have own billing setup, check corporate
                corporate_has_billing = (
                    hasattr(self.corporate, 'billing_data') and
                    self.corporate.addresses.filter(type='billing', active=True).exists()
                )

                if not corporate_has_billing:
                    errors['requires_billing'] = (
                        'No se puede requerir facturación: ni la sucursal ni el corporativo '
                        'tienen datos de facturación completos (RFC/razón social y dirección fiscal). '
                        'Configure primero el corporativo o agregue datos propios a esta sucursal.'
                    )

        # NOTE: Shipping address validation removed - it was too strict for admin workflow.
        # Branches must have their own shipping address (they don't inherit from corporate),
        # but this should be validated at the business logic level (e.g., when creating orders)
        # rather than at the model level, to allow proper admin inline workflow.

        # Existing credit payment constraints
        if not self.can_pay_with_credit and self.requires_note_for_credit:
            errors['can_pay_with_credit'] = 'No se puede deshabilitar el pago con crédito y requerir nota al mismo tiempo.'
            errors['requires_note_for_credit'] = 'No se puede requerir nota si el pago con crédito está deshabilitado.'

        if not self.can_pay_with_credit and self.current_debt > 0:
            errors['can_pay_with_credit'] = 'No se puede deshabilitar el pago con crédito si el cliente ya tiene deuda existente.'

        if self.current_debt > self.credit_limit:
            errors['current_debt'] = 'La deuda actual no puede exceder el límite de crédito.'

        if not self.can_pay_with_credit and self.credit_limit > 0:
            errors['can_pay_with_credit'] = 'No se puede habilitar el límite de crédito sin permitir el pago con crédito.'

        if errors:
            raise ValidationError(errors)


# NOTE: BranchClient model is deprecated - Client model handles branch/corporate relationships
# through the 'type' and 'corporate' fields. Commented out due to model conflicts.
# class BranchClient(TimeStampedModel):
#     """
#     Model to link branch clients to their corporate parent clients
#     """
#     corporate_client = models.ForeignKey('Client', related_name='branches', on_delete=models.CASCADE, verbose_name="Cliente Corporativo")
#     class Meta:
#         verbose_name = 'Cliente Sucursal'
#         verbose_name_plural = 'Clientes Sucursales'
#         unique_together = ('corporate_client', 'branch_client')
#
#     def __str__(self):
#         return f"{self.branch_client.name} (Sucursal de {self.corporate_client.name})"

class BalanceTransaction(TimeStampedModel):
    """
    Track all balance-related transactions for complete audit trail
    """
    TRANSACTION_TYPES = [
        ('deposit', 'Depósito'),           # Client adds money
        ('payment', 'Pago con saldo'),     # Using balance for order payment
        ('added_in_order', 'Saldo agregado en venta'), # Using balance for deferred payment
        ('refund', 'Reembolso'),           # Money returned to balance
        ('adjustment', 'Ajuste manual'),   # Manual adjustment
        ('transfer_in', 'Transferencia recibida'),   # Transfer from another client
        ('transfer_out', 'Transferencia enviada'),   # Transfer to another client
        ('correction', 'Corrección'),      # Error correction
    ]
    
    client = models.ForeignKey('Client', related_name='balance_transactions', on_delete=models.PROTECT, verbose_name="Cliente")
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, verbose_name="Tipo de Transacción")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto")
    balance_before = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Saldo Anterior")
    balance_after = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Saldo Posterior")
    notes = models.TextField(blank=True, null=True, verbose_name="Notas adicionales")
    
    # References to related objects
    reference_order = models.ForeignKey('orders.Order', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Orden relacionada")
    reference_payment = models.ForeignKey('payment.Payment', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Pago relacionado")
    transfer_to_client = models.ForeignKey('Client', null=True, blank=True, on_delete=models.SET_NULL, related_name='balance_transfers_received', verbose_name="Cliente destino (transferencia)")
    
    # Audit fields
    created_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Creado por")
    
    class Meta:
        verbose_name = 'Transacción de Saldo'
        verbose_name_plural = 'Transacciones de Saldo'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['client', '-created_at'], name='balance_tx_client_date_idx'),
            models.Index(fields=['transaction_type'], name='balance_tx_type_idx'),
            models.Index(fields=['created_at'], name='balance_tx_date_idx'),
            models.Index(fields=['reference_order'], name='balance_tx_order_idx'),
            models.Index(fields=['reference_payment'], name='balance_tx_payment_idx'),
        ]
    
    def __str__(self):
        return f"{self.client.name} - {self.get_transaction_type_display()} - ${self.amount:.2f} ({self.created_at.date()})"
    
    def clean(self):
        """Validate transaction data"""
        from django.core.exceptions import ValidationError
        
        # Validate amount is positive
        if self.amount <= 0:
            raise ValidationError({'amount': 'El monto debe ser mayor a cero.'})
        
        # Validate balance calculation
        if self.transaction_type in ['deposit', 'refund', 'transfer_in', 'adjustment']:
            # Additions to balance
            if self.balance_after != self.balance_before + self.amount:
                raise ValidationError('Error en cálculo de saldo: adición incorrecta.')
        else:
            # Deductions from balance
            if self.balance_after != self.balance_before - self.amount:
                raise ValidationError('Error en cálculo de saldo: deducción incorrecta.')
        
        # Validate sufficient balance for deductions
        if self.transaction_type in ['payment', 'transfer_out'] and self.balance_before < self.amount:
            raise ValidationError({'amount': f'Saldo insuficiente. Disponible: ${self.balance_before:.2f}'})


class CreditTransaction(TimeStampedModel):
    """
    Track all credit-related transactions for complete audit trail
    """
    TRANSACTION_TYPES = [
        ('purchase', 'Compra a crédito'),     # Adding debt
        ('payment', 'Pago de deuda'),         # Reducing debt
        ('payment_from_balance', 'Pago con Saldo'),  # Payment using client's balance
        ('adjustment', 'Ajuste manual'),      # Manual debt adjustment
        ('limit_change', 'Cambio de límite'), # Credit limit modification
        ('interest', 'Interés aplicado'),     # Interest charges
        ('fee', 'Cargo adicional'),           # Additional fees
        ('forgiveness', 'Condonación'),       # Debt forgiveness
        ('correction', 'Corrección'),         # Error correction
    ]
    
    client = models.ForeignKey('Client', related_name='credit_transactions', on_delete=models.PROTECT, verbose_name="Cliente")
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, verbose_name="Tipo de Transacción")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto")
    debt_before = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Deuda Anterior")
    debt_after = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Deuda Posterior")
    credit_limit_before = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Límite Anterior")
    credit_limit_after = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Límite Posterior")
    notes = models.TextField(blank=True, null=True, verbose_name="Notas adicionales")
    
    # References to related objects
    reference_order = models.ForeignKey('orders.Order', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Orden relacionada")
    reference_payment = models.ForeignKey('payment.Payment', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Pago relacionado")
    
    # Audit fields
    created_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Creado por")
    
    class Meta:
        verbose_name = 'Transacción de Crédito'
        verbose_name_plural = 'Transacciones de Crédito'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['client', '-created_at'], name='credit_tx_client_date_idx'),
            models.Index(fields=['transaction_type'], name='credit_tx_type_idx'),
            models.Index(fields=['created_at'], name='credit_tx_date_idx'),
            models.Index(fields=['reference_order'], name='credit_tx_order_idx'),
            models.Index(fields=['reference_payment'], name='credit_tx_payment_idx'),
        ]
    
    def __str__(self):
        return f"{self.client.name} - {self.get_transaction_type_display()} - ${self.amount:.2f} ({self.created_at.date()})"
    
    def clean(self):
        """Validate transaction data"""
        from django.core.exceptions import ValidationError
        
        # Validate amount is positive
        if self.amount <= 0:
            raise ValidationError({'amount': 'El monto debe ser mayor a cero.'})
        
        # Validate debt calculation
        if self.transaction_type in ['purchase', 'interest', 'fee', 'adjustment']:
            # Additions to debt
            if self.debt_after != self.debt_before + self.amount:
                raise ValidationError('Error en cálculo de deuda: adición incorrecta.')
        else:
            # Reductions from debt (including payment_from_balance)
            if self.debt_after != self.debt_before - self.amount:
                raise ValidationError('Error en cálculo de deuda: reducción incorrecta.')
        
        # Validate debt doesn't go negative
        if self.debt_after < 0:
            raise ValidationError({'amount': 'La deuda no puede ser negativa.'})
        
        # Validate balance availability for payment_from_balance transactions
        if self.transaction_type == 'payment_from_balance':
            if self.client and self.client.balance < self.amount:
                raise ValidationError({
                    'amount': f'Saldo insuficiente. Disponible: ${self.client.balance:.2f}, Requerido: ${self.amount:.2f}'
                })
        
        # Validate credit limit constraints for purchases
        if self.transaction_type == 'purchase' and self.credit_limit_after is not None:
            if self.debt_after > self.credit_limit_after:
                raise ValidationError({'amount': f'Excede límite de crédito. Límite: ${self.credit_limit_after:.2f}'})


class ClientBillingFrecuency(TimeStampedModel):
    client = models.OneToOneField('Client', related_name='billing_frecuency', on_delete=models.CASCADE, related_query_name='client_billing_frecuency')
    frequency = models.CharField(max_length=50, choices=BILLING_FREQUENCY_CHOICES, default='monthly', verbose_name="Frecuencia de Facturación")
    billing_date = models.CharField(max_length=50, choices=BILLING_DATE_CHOICES, null=True, blank=True, verbose_name="Fecha de Facturación")
    
    # For specific_date billing
    specific_day = models.PositiveIntegerField(null=True, blank=True, help_text="Día del mes (1-31)", verbose_name="Día Específico")

    # For weekday_occurrence billing (e.g., "third Monday")
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES, null=True, blank=True, help_text="ía de la semana (0=Lunes, 6=Domingo)", verbose_name="Día de la Semana")
    occurrence = models.IntegerField(choices=OCCURRENCE_CHOICES, null=True, blank=True, help_text="Qué ocurrencia en el mes (1=Primera, -1=Última)", verbose_name="Ocurrencia")

    # Additional settings
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    notes = models.TextField(blank=True, null=True, help_text="Notas adicionales sobre el calendario de facturación", verbose_name="Notas")
    next_billing_date = models.DateField(null=True, blank=True, verbose_name="Próxima Fecha de Facturación")

    class Meta:
        verbose_name = "Frecuencia de Facturación"
        verbose_name_plural = "Frecuencias de Facturación"
        indexes = [
            models.Index(fields=['frequency'], name='clients_billing_frequency_idx'),
            models.Index(fields=['billing_date'], name='clients_billing_date_idx'),
            models.Index(fields=['is_active'], name='clients_billing_active_idx'),
        ]
        verbose_name = "Frecuencia de Facturación"
        verbose_name_plural = "Frecuencias de Facturación"
    
    def __str__(self):
        if self.billing_date == 'specific_date' and self.specific_day:
            return f"{self.client.name} - {self.get_frequency_display()} el día {self.specific_day}"
        elif self.billing_date == 'weekday_occurrence' and self.weekday is not None and self.occurrence:
            weekday_name = self.get_weekday_display()
            occurrence_name = self.get_occurrence_display()
            return f"{self.client.name} - {self.get_frequency_display()} el {occurrence_name} {weekday_name}"
        elif self.billing_date == 'first_day':
            return f"{self.client.name} - {self.get_frequency_display()} el primer día del mes"
        elif self.billing_date == 'last_day':
            return f"{self.client.name} - {self.get_frequency_display()} el último día del mes"
        else:
            return f"{self.client.name} - {self.get_frequency_display()}"
    
    def clean(self):
        """Validate that the correct fields are filled based on billing_date type"""
        from django.core.exceptions import ValidationError
        # Validate a client can have only one active billing frequency
        if self.is_active:
            active_frequencies = ClientBillingFrecuency.objects.filter(client=self.client, is_active=True).exclude(id=self.id)
            if active_frequencies.exists():
                raise ValidationError({'is_active': 'El cliente ya tiene una frecuencia de facturación activa.'})
        if self.billing_date == 'specific_date':
            if not self.specific_day:
                raise ValidationError({'specific_day': 'Specific day is required when billing date is "specific_date".'})
            if self.specific_day < 1 or self.specific_day > 31:
                raise ValidationError({'specific_day': 'Specific day must be between 1 and 31.'})
        
        elif self.billing_date == 'weekday_occurrence':
            if self.weekday is None:
                raise ValidationError({'weekday': 'Weekday is required when billing date is "weekday_occurrence".'})
            if self.occurrence is None:
                raise ValidationError({'occurrence': 'Occurrence is required when billing date is "weekday_occurrence".'})
        
        # Clear unused fields based on billing_date type
        if self.billing_date != 'specific_date':
            self.specific_day = None
        if self.billing_date != 'weekday_occurrence':
            self.weekday = None
            self.occurrence = None
    
    def save(self, *args, **kwargs):
        """Override save to ensure clean is called and calculate next billing date"""
        self.clean()
        
        # Calculate next_billing_date before saving
        first_day, last_day = get_first_last_day_of_month(date.today().year, date.today().month)
        billing_dates = self.get_billing_dates_in_period(first_day, last_day)
        if billing_dates:
            self.next_billing_date = billing_dates[0]
        
        # Save once with all data
        super().save(*args, **kwargs) 
    
    def get_billing_info(self):
        """Return a human-readable description of the billing frequency"""

        return f"Facturación en la fecha  {self.next_billing_date} ."
    
    def get_next_billing_candidates(self, start_date=None):
        """Get potential billing dates for the current and next periods"""
        from datetime import timedelta
        import calendar
        
        if start_date is None:
            start_date = date.today()
        
        candidates = []
        
        # Check current month and next few months depending on frequency
        months_to_check = 1
        if self.frequency == 'bimonthly':
            months_to_check = 2
        elif self.frequency == 'quarterly':
            months_to_check = 3
        elif self.frequency == 'semiannual':
            months_to_check = 6
        elif self.frequency == 'annual':
            months_to_check = 12
            
        current_date = start_date.replace(day=1)  # Start from first day of month
        
        for i in range(months_to_check + 1):  # Check one extra month for safety
            year = current_date.year
            month = current_date.month
            
            if self.billing_date == 'specific_date' and self.specific_day:
                # Handle specific day of month
                last_day_of_month = monthrange(year, month)[1]
                target_day = min(self.specific_day, last_day_of_month)
                candidate = date(year, month, target_day)
                candidates.append(candidate)
                
            elif self.billing_date == 'first_day':
                candidate = date(year, month, 1)
                candidates.append(candidate)
                
            elif self.billing_date == 'last_day':
                last_day_of_month = monthrange(year, month)[1]
                candidate = date(year, month, last_day_of_month)
                candidates.append(candidate)
                
            elif self.billing_date == 'weekday_occurrence' and self.weekday is not None and self.occurrence:
                # Find the nth occurrence of weekday in the month
                candidate = self._get_weekday_occurrence_date(year, month, self.weekday, self.occurrence)
                if candidate:
                    candidates.append(candidate)
            
            # Move to next month
            if month == 12:
                current_date = current_date.replace(year=year + 1, month=1)
            else:
                current_date = current_date.replace(month=month + 1)
        
        return sorted(candidates)
    
    def _get_weekday_occurrence_date(self, year, month, weekday, occurrence):
        """Find the nth occurrence of a weekday in a given month"""
        import calendar

        # Get all dates in the month for the specified weekday
        dates = []
        first_day, last_day = monthrange(year, month)

        for day in range(1, last_day + 1):
            date_obj = date(year, month, day)
            if date_obj.weekday() == weekday:
                dates.append(date_obj)

        if not dates:
            return None

        if occurrence == -1:  # Last occurrence
            return dates[-1]
        elif 1 <= occurrence <= len(dates):
            return dates[occurrence - 1]
        else:
            return None

    def should_bill_in_period(self, start_date: date, end_date: date) -> bool:
        """
        Determine if client should be billed within the date range.

        Args:
            start_date: Start of billing period
            end_date: End of billing period

        Returns:
            True if client should be billed in this period
        """
        billing_dates = self.get_billing_dates_in_period(start_date, end_date)
        return len(billing_dates) > 0

    def get_billing_dates_in_period(self, start_date: date, end_date: date) -> List[date]:
        """
        Get all billing dates that fall within the specified period.

        Args:
            start_date: Start of billing period
            end_date: End of billing period

        Returns:
            List of dates when client should be billed
        """
        from core.utils import is_business_day, adjust_to_business_day

        billing_dates = []

        if self.frequency == 'when_delivery':
            # For contraentrega, check orders and add 1 business day
            # This will be handled at the service layer since it requires order data
            return []  # Service layer will handle this

        elif self.frequency == 'weekly':
            # Weekly: Check if configured weekday falls in the period
            # weekday field: 0=Monday, 6=Sunday (but only 0-4 allowed)
            if self.weekday is None or self.weekday > 4:
                return []

            current = start_date
            while current <= end_date:
                if current.weekday() == self.weekday and is_business_day(current):
                    billing_dates.append(current)
                current += timedelta(days=1)

        elif self.frequency == 'biweekly':
            # Quincenal: 15th and last day of each month
            current_month_start = start_date.replace(day=1)
            end_month = end_date.replace(day=1)

            while current_month_start <= end_month:
                # 15th of month (or next business day)
                fifteenth = current_month_start.replace(day=15)
                adjusted_15th = adjust_to_business_day(fifteenth)
                if start_date <= adjusted_15th <= end_date:
                    billing_dates.append(adjusted_15th)

                # Last business day of month
                last_day = monthrange(current_month_start.year, current_month_start.month)[1]
                last_date = current_month_start.replace(day=last_day)

                # Find last business day
                while not is_business_day(last_date):
                    last_date -= timedelta(days=1)

                if start_date <= last_date <= end_date:
                    billing_dates.append(last_date)

                # Move to next month
                if current_month_start.month == 12:
                    current_month_start = current_month_start.replace(year=current_month_start.year + 1, month=1)
                else:
                    current_month_start = current_month_start.replace(month=current_month_start.month + 1)

        elif self.frequency == 'monthly':
            # Monthly with various subtypes
            current_month_start = start_date.replace(day=1)
            end_month = end_date.replace(day=1)

            while current_month_start <= end_month:
                billing_date = self._get_monthly_billing_date(current_month_start)

                if billing_date and start_date <= billing_date <= end_date:
                    billing_dates.append(billing_date)

                # Move to next month
                if current_month_start.month == 12:
                    current_month_start = current_month_start.replace(year=current_month_start.year + 1, month=1)
                else:
                    current_month_start = current_month_start.replace(month=current_month_start.month + 1)

        return sorted(set(billing_dates))  # Remove duplicates and sort

    def _get_monthly_billing_date(self, month_start: date) -> Optional[date]:
        """
        Get the billing date for a specific month based on monthly billing configuration.

        Args:
            month_start: First day of the month to calculate for

        Returns:
            Billing date for that month, or None if invalid
        """
        from core.utils import is_business_day, adjust_to_business_day, next_business_day

        if self.billing_date == 'specific_date':
            # Specific day of month (e.g., 25th)
            if not self.specific_day:
                return None

            last_day = monthrange(month_start.year, month_start.month)[1]
            day = min(self.specific_day, last_day)  # Handle Feb 31 -> Feb 28
            target = month_start.replace(day=day)
            return adjust_to_business_day(target)

        elif self.billing_date == 'first_day':
            # First business day of month
            first_day = month_start
            return next_business_day(first_day)

        elif self.billing_date == 'last_day':
            # Last business day of month
            last_day_num = monthrange(month_start.year, month_start.month)[1]
            last_day = month_start.replace(day=last_day_num)

            while not is_business_day(last_day):
                last_day -= timedelta(days=1)

            return last_day

        elif self.billing_date == 'weekday_occurrence':
            # Nth occurrence of weekday (e.g., 3rd Thursday)
            return self._get_weekday_occurrence_date(
                month_start.year,
                month_start.month,
                self.weekday,
                self.occurrence
            )

        return None

class Contact(TimeStampedModel):
    client = models.ForeignKey('Client', related_name='contacts', on_delete=models.CASCADE)
    name = models.CharField(max_length=100, verbose_name="Nombre")
    email = models.EmailField(blank=True, null=True, verbose_name="Correo electrónico")
    phone = models.CharField(max_length=15, blank=True, null=True, db_index=True, verbose_name="Teléfono")
    position = models.CharField(max_length=100, blank=True, null=True, verbose_name="Puesto")

    class Meta:
        verbose_name = 'Contacto'
        verbose_name_plural = 'Contactos'
        indexes = [
            models.Index(fields=['phone'], name='clients_contact_phone_idx'),
            models.Index(fields=['email'], name='clients_contact_email_idx'),
        ]

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Address(TimeStampedModel):
    client = models.ForeignKey('Client', related_name='addresses', on_delete=models.PROTECT, verbose_name="Cliente")
    street = models.CharField(max_length=255, verbose_name="Calle")
    exterior_number = models.CharField(max_length=20, blank=True, null=True, verbose_name="No. Exterior")
    interior_number = models.CharField(max_length=20, blank=True, null=True, verbose_name="No. Interior")
    locality = models.CharField(max_length=100, blank=True, null=True, verbose_name="Localidad")
    municipality = models.CharField(max_length=100, blank=True, null=True, verbose_name="Delegación o Municipio")
    state = models.CharField(max_length=100, default='Queretaro', verbose_name="Estado")
    zip_code = models.CharField(max_length=20, default='76000', verbose_name="Código Postal")
    country = models.CharField(max_length=100, default='Mexico', verbose_name="País")
    reference = models.TextField(blank=True, null=True, verbose_name="Referencia")
    active = models.BooleanField(default=True, verbose_name="Activo")
    note = models.TextField(blank=True, null=True, verbose_name="Notas")
    type = models.CharField(max_length=50, choices=[('billing', 'Fiscal'), ('shipping', 'Ubicacion fisica'), ('other', 'Otro')], default='other', verbose_name="Tipo")
    
    class Meta:
        verbose_name = 'Domicilio'
        verbose_name_plural = 'Domicilios'
        indexes = [
            models.Index(fields=['municipality'], name='clients_address_munic_idx'),
            models.Index(fields=['state'], name='clients_address_state_idx'),
            models.Index(fields=['active'], name='clients_address_active_idx'),
        ]

    def __str__(self):
        return f"{self.street}, {self.municipality}, {self.state}, {self.zip_code}, {self.country}"
    
    def clean(self):
        """Validate that each client has only one address of type billing and one of type shipping"""
        from django.core.exceptions import ValidationError
        super().clean()
        errors = {}
        # Only validate for billing and shipping types
        if self.type not in ['billing', 'shipping']:
            return
        
        # Build query to find existing addresses of the same type for this client
        existing_query = Address.objects.filter(
            client=self.client,
            type=self.type
        )
        
        # Exclude current instance if updating (not creating)
        if self.pk:
            existing_query = existing_query.exclude(pk=self.pk)
        
        # Check if another address of this type exists
        if existing_query.exists():
            type_display = self.get_type_display()
            raise ValidationError({
            '__all__': f'No se puede guardar: dirección duplicada de tipo "{type_display}"',
            'type': f'El cliente ya tiene una dirección de tipo "{type_display}". '
                    f'Solo se permite una dirección por tipo (Fiscal/Ubicación física).'
        })



class BillingData(TimeStampedModel):
    client = models.OneToOneField('Client', related_name='billing_data', on_delete=models.CASCADE)
    rfc = models.CharField(max_length=255, db_index=True)
    razon_social = models.TextField()
    curp = models.CharField(max_length=255, blank=True, null=True, verbose_name="CURP")
    #uso_cfdi = models.CharField(max_length=10, choices=USO_CFDI_CHOICES, verbose_name="Uso de CFDI", null=True, blank=True)
    #metodo_pago = models.CharField(max_length=255, choices=PAYMENT_METHOD_CHOICES, default='other', verbose_name="Forma de pago")
    #address = models.ForeignKey('Address', related_name='billing_data', on_delete=models.CASCADE)
    #regimen_fiscal = models.CharField(max_length=10, choices=REGIMEN_FISCAL_CHOICES, blank=True, null=True, verbose_name="Régimen Fiscal")
    class Meta:
        verbose_name = 'Datos de facturación'
        verbose_name_plural = 'Datos de facturación'
        indexes = [
            models.Index(fields=['rfc'], name='clients_billing_rfc_idx'),
        ]
    
    def __str__(self):
        return f"Billing data for {self.client.name}"
    
class ClientCreditConfig(TimeStampedModel):
    client = models.OneToOneField(Client, related_name='credit_config', on_delete=models.CASCADE)
    max_payment_days = models.PositiveIntegerField(default=30, verbose_name="Días máximos para pagar")
    first_notification_days = models.PositiveIntegerField(default=5, verbose_name="Días antes del vencimiento para la primera notificación")
    second_notification_days = models.PositiveIntegerField(default=2, verbose_name="Días antes del vencimiento para la segunda notificación")
    overdue_notification_days = models.PositiveIntegerField(default=1, verbose_name="Días después del vencimiento para notificación de morosidad")

