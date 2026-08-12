"""Discount calculation.

Discounts are derived from a customer's *purchase history*: how much they have
spent with us historically and how many orders they have placed. The more a
customer has bought, the larger their discount tier.
"""

from dataclasses import dataclass, field

# Purchase-history tiers: (lifetime spend threshold, discount rate)
LOYALTY_TIERS = [
    (5000.0, 0.15),
    (2000.0, 0.10),
    (500.0, 0.05),
]

# Extra reward for customers who order frequently.
FREQUENT_BUYER_ORDER_COUNT = 10
FREQUENT_BUYER_BONUS = 0.02

MAX_DISCOUNT_RATE = 0.25


@dataclass
class Customer:
    """A customer, carrying the purchase history discounting depends on."""

    customer_id: str
    lifetime_spend: float = 0.0
    order_count: int = 0
    past_orders: list = field(default_factory=list)


@dataclass
class Order:
    """A single order awaiting pricing."""

    order_id: str
    subtotal: float


def get_loyalty_rate(lifetime_spend: float) -> float:
    """Return the discount rate earned by a customer's lifetime spend."""
    for threshold, rate in LOYALTY_TIERS:
        if lifetime_spend >= threshold:
            return rate
    return 0.0


def is_frequent_buyer(customer: Customer) -> bool:
    """A customer is 'frequent' once they pass the order-count threshold."""
    return customer.order_count >= FREQUENT_BUYER_ORDER_COUNT


def calculate_discount(customer: Customer, order: Order) -> float:
    """Calculate the discount rate for `order`, based on purchase history.

    The rate is the customer's loyalty tier (from lifetime spend) plus a bonus
    for frequent buyers, capped at MAX_DISCOUNT_RATE.
    """
    rate = get_loyalty_rate(customer.lifetime_spend)

    if is_frequent_buyer(customer):
        rate += FREQUENT_BUYER_BONUS

    return min(rate, MAX_DISCOUNT_RATE)


def apply_discount(customer: Customer, order: Order) -> float:
    """Return the order total after the purchase-history discount is applied."""
    rate = calculate_discount(customer, order)
    return round(order.subtotal * (1.0 - rate), 2)
