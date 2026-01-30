# Re-export service functions for backward compatibility
from clients.services.balance_service import (
    add_balance,
    deduct_balance,
    add_debt,
    pay_debt,
    update_credit_limit,
    pay_debt_from_balance,
    transfer_balance,
    get_financial_summary,
)

# Re-export existing client service functions
from clients.services.client_service import (
    get_upcoming_route_orders,
    get_recent_completed_route_orders,
    get_clients_needing_billing,
    set_billing_date_to_clients,
)

__all__ = [
    # Balance service
    "add_balance",
    "deduct_balance",
    "add_debt",
    "pay_debt",
    "update_credit_limit",
    "pay_debt_from_balance",
    "transfer_balance",
    "get_financial_summary",
    # Client service
    "get_upcoming_route_orders",
    "get_recent_completed_route_orders",
    "get_clients_needing_billing",
    "set_billing_date_to_clients",
]
