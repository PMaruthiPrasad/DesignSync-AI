"""Tests for purchase-history based discount calculation."""

from pricing.discount import (
    Customer,
    Order,
    apply_discount,
    calculate_discount,
    get_loyalty_rate,
    is_frequent_buyer,
)


def make_order(subtotal=100.0):
    return Order(order_id="ord-1", subtotal=subtotal)


def test_new_customer_gets_no_discount():
    customer = Customer(customer_id="c-1", lifetime_spend=0.0, order_count=0)
    assert calculate_discount(customer, make_order()) == 0.0


def test_loyalty_rate_uses_lifetime_spend():
    assert get_loyalty_rate(100.0) == 0.0
    assert get_loyalty_rate(600.0) == 0.05
    assert get_loyalty_rate(2500.0) == 0.10
    assert get_loyalty_rate(9000.0) == 0.15


def test_frequent_buyer_gets_bonus():
    customer = Customer(customer_id="c-2", lifetime_spend=2500.0, order_count=12)
    assert is_frequent_buyer(customer) is True
    assert calculate_discount(customer, make_order()) == 0.12


def test_discount_is_capped():
    customer = Customer(customer_id="c-3", lifetime_spend=999999.0, order_count=999)
    assert calculate_discount(customer, make_order()) <= 0.25


def test_apply_discount_reduces_total():
    customer = Customer(customer_id="c-4", lifetime_spend=600.0, order_count=1)
    assert apply_discount(customer, make_order(200.0)) == 190.0
