# Orders Platform (sample repository)

A small commerce backend used as the demo repository for DesignSync AI.

## Layout

```
pricing/
    discount.py           discount rules (purchase-history based)
    pricing_service.py    applies discount + tax -> priced order
checkout/
    service.py            checkout flow, consumes PricingService
api/
    pricing_api.py        HTTP endpoints for pricing and checkout
tests/
    test_discount.py
    test_pricing_service.py
docs/
    pricing.md            how discounting works
    API_REFERENCE.md      endpoint contracts
```

## Pricing model

Customers earn a discount from their **purchase history** — lifetime spend
determines the loyalty tier, and customers with 10+ orders earn an extra 2%.
See `docs/pricing.md` for the full tier table.

## Module relationships

```
pricing/discount.py
        |
        v
pricing/pricing_service.py
        |
        +--> checkout/service.py
        |
        +--> api/pricing_api.py
```

Discount rules are consumed by exactly one module (`pricing_service`), which in
turn is consumed by checkout and the API layer. Changing the discount rules
therefore has a well-defined blast radius.
