"""Tests for the pricing service."""

from pricing.discount import Customer, Order
from pricing.pricing_service import PricingService


def test_price_order_applies_discount_and_tax():
    service = PricingService(tax_rate=0.10)
    customer = Customer(customer_id="c-1", lifetime_spend=2500.0, order_count=2)
    order = Order(order_id="ord-9", subtotal=1000.0)

    priced = service.price_order(customer, order)

    assert priced.discount_rate == 0.10
    assert priced.discount_amount == 100.0
    assert priced.tax == 90.0
    assert priced.total == 990.0


def test_quote_discount_rate_matches_calculation():
    service = PricingService()
    customer = Customer(customer_id="c-2", lifetime_spend=5000.0, order_count=0)
    order = Order(order_id="ord-10", subtotal=50.0)

    assert service.quote_discount_rate(customer, order) == 0.15
