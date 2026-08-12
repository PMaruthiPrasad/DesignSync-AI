"""Pricing service: turns an order into a priced quote.

This is the single entry point other modules use for pricing. It consumes the
discount rules in `pricing.discount` and adds tax on top.
"""

from dataclasses import dataclass

from pricing.discount import Customer, Order, apply_discount, calculate_discount

DEFAULT_TAX_RATE = 0.08


@dataclass
class PricedOrder:
    """The result of pricing an order."""

    order_id: str
    subtotal: float
    discount_rate: float
    discount_amount: float
    tax: float
    total: float


class PricingService:
    """Applies discounts and tax to produce a final order total."""

    def __init__(self, tax_rate: float = DEFAULT_TAX_RATE):
        self.tax_rate = tax_rate

    def price_order(self, customer: Customer, order: Order) -> PricedOrder:
        """Price a single order for a customer."""
        discount_rate = calculate_discount(customer, order)
        discounted = apply_discount(customer, order)
        discount_amount = round(order.subtotal - discounted, 2)
        tax = round(discounted * self.tax_rate, 2)

        return PricedOrder(
            order_id=order.order_id,
            subtotal=order.subtotal,
            discount_rate=discount_rate,
            discount_amount=discount_amount,
            tax=tax,
            total=round(discounted + tax, 2),
        )

    def quote_discount_rate(self, customer: Customer, order: Order) -> float:
        """Expose the discount rate on its own, for previews and the API."""
        return calculate_discount(customer, order)
