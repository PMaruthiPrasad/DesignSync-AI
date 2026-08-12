# API Reference

All pricing endpoints are defined in `api/pricing_api.py`.

## GET /api/pricing/discount

Returns the discount rate a customer currently qualifies for.

**Request**

```json
{
  "customer_id": "c-1024",
  "order_id": "ord-88",
  "subtotal": 250.00,
  "lifetime_spend": 2500.00,
  "order_count": 12
}
```

**Response**

```json
{
  "customer_id": "c-1024",
  "discount_rate": 0.12,
  "basis": "purchase_history"
}
```

The `basis` field is always `"purchase_history"` — the rate is derived from the
customer's lifetime spend and order count. Callers that need to explain a
discount to an end user should describe it in those terms ("you've spent $2,500
with us across 12 orders").

`lifetime_spend` and `order_count` are **required** in the request body. Without
them the customer is treated as having no purchase history and receives 0%.

## POST /api/pricing/quote

Returns a full priced quote.

**Response**

```json
{
  "order_id": "ord-88",
  "subtotal": 250.00,
  "discount_rate": 0.12,
  "discount_amount": 30.00,
  "tax": 17.60,
  "total": 237.60
}
```

## POST /api/checkout

Prices and checks out an order.

**Response**

```json
{
  "order_id": "ord-88",
  "amount_charged": 237.60,
  "discount_rate": 0.12,
  "requires_review": false
}
```

`requires_review` is `true` when the discount rate exceeds 20%. In practice this
only happens for high-lifetime-spend frequent buyers, so review volume scales
with the size of the loyal customer base.
