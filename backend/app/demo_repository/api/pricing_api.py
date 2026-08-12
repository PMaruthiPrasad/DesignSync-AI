"""HTTP API exposing pricing and checkout behaviour.

These endpoints are the public contract for discounting, so any change to how
discounts are calculated is visible to API consumers.
"""

from pricing.discount import Customer, Order
from pricing.pricing_service import PricingService
from checkout.service import CheckoutService

pricing_service = PricingService()
checkout_service = CheckoutService(pricing_service)


def get_discount_rate(payload: dict) -> dict:
    """GET /api/pricing/discount

    Returns the discount rate a customer currently qualifies for. The rate is
    derived from the customer's purchase history (lifetime spend + order count).
    """
    customer = _customer_from_payload(payload)
    order = _order_from_payload(payload)

    return {
        "customer_id": customer.customer_id,
        "discount_rate": pricing_service.quote_discount_rate(customer, order),
        "basis": "purchase_history",
    }


def price_order(payload: dict) -> dict:
    """POST /api/pricing/quote

    Returns a full priced quote: subtotal, discount, tax and total.
    """
    customer = _customer_from_payload(payload)
    order = _order_from_payload(payload)
    priced = pricing_service.price_order(customer, order)

    return {
        "order_id": priced.order_id,
        "subtotal": priced.subtotal,
        "discount_rate": priced.discount_rate,
        "discount_amount": priced.discount_amount,
        "tax": priced.tax,
        "total": priced.total,
    }


def checkout_order(payload: dict) -> dict:
    """POST /api/checkout

    Prices and checks out an order, flagging large discounts for review.
    """
    customer = _customer_from_payload(payload)
    order = _order_from_payload(payload)
    result = checkout_service.checkout(customer, order)

    return {
        "order_id": result.order_id,
        "amount_charged": result.amount_charged,
        "discount_rate": result.discount_rate,
        "requires_review": result.requires_review,
    }


def _customer_from_payload(payload: dict) -> Customer:
    return Customer(
        customer_id=payload["customer_id"],
        lifetime_spend=payload.get("lifetime_spend", 0.0),
        order_count=payload.get("order_count", 0),
    )


def _order_from_payload(payload: dict) -> Order:
    return Order(order_id=payload["order_id"], subtotal=payload["subtotal"])
