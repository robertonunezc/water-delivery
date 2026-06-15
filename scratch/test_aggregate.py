from invoice.models import Invoice
from django.db.models import Sum, Q

invoice = Invoice.objects.first()
if invoice:
    print("Found invoice:", invoice)
    res = invoice.invoice_links.aggregate(
        total=Sum(
            'order__payments__amount',
            filter=Q(order__payments__status='completed') & ~Q(order__payments__method='pending_credit')
        )
    )
    print(res)
else:
    print("No invoice found.")
