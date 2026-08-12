# Pricing and Discounts

## How discounts are calculated

Discounts in this system are **based on customer purchase history**. Every
customer accumulates a lifetime spend total and an order count, and those two
numbers determine the discount rate applied at checkout.

### Loyalty tiers

The discount rate is looked up from the customer's **lifetime spend**:

| Lifetime spend | Discount rate |
| -------------- | ------------- |
| $5,000 or more | 15%           |
| $2,000 – $4,999| 10%           |
| $500 – $1,999  | 5%            |
| Under $500     | 0%            |

A customer with no purchase history receives no discount. This is intentional:
discounting rewards customers who have already spent money with us.

### Frequent buyer bonus

Customers who have placed **10 or more orders** receive an additional 2% on top
of their loyalty tier. This is a purchase-history signal as well — it measures
how often the customer has bought, not who they are.

### Discount cap

The combined rate is capped at **25%**.

## Where discounting happens

`pricing/discount.py` owns the rules. `calculate_discount(customer, order)`
returns the rate, and `apply_discount(customer, order)` returns the discounted
subtotal.

`PricingService` (in `pricing/pricing_service.py`) is the only supported way to
price an order — it calls into `discount.py` and then applies tax. Checkout
consumes `PricingService` and never calculates discounts itself.

## Required customer fields

To price an order, a customer record must carry its purchase history:

- `lifetime_spend` — total historical spend, in dollars
- `order_count` — number of completed orders

Both fields are required. A customer object without purchase history cannot be
priced correctly and will fall through to the 0% tier.
