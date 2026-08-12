"""Checkout service.

Checkout does not compute discounts itself — it delegates all pricing to
`PricingService` and then validates the result before charging the customer.
"""

from dataclasses import dataclass

from pricing.discount import Customer, Order
from pricing.pricing_service import PricedOrder, PricingService

# Orders whose discount exceeds this rate are held for manual review.
DISCOUNT_REVIEW_THRESHOLD = 0.20


@dataclass
class CheckoutResult:
    """Outcome of a checkout attempt."""

    order_id: str
    amount_charged: float
    discount_rate: float
    requires_review: bool


class CheckoutService:
    """Runs the checkout flow for a single order."""

    def __init__(self, pricing_service: PricingService | None = None):
        self.pricing_service = pricing_service or PricingService()

    def checkout(self, customer: Customer, order: Order) -> CheckoutResult:
        """Price the order, then decide whether it can be charged directly."""
        priced: PricedOrder = self.pricing_service.price_order(customer, order)

        return CheckoutResult(
            order_id=priced.order_id,
            amount_charged=priced.total,
            discount_rate=priced.discount_rate,
            requires_review=self.needs_review(priced),
        )

    def needs_review(self, priced: PricedOrder) -> bool:
        """Unusually large discounts are held back for a human to approve."""
        return priced.discount_rate > DISCOUNT_REVIEW_THRESHOLD

    def estimate_total(self, customer: Customer, order: Order) -> float:
        """Show the customer what they would pay, without charging them."""
        return self.pricing_service.price_order(customer, order).total
