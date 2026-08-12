"""Pricing domain: discount rules and the service that applies them."""

from pricing.discount import calculate_discount
from pricing.pricing_service import PricingService

__all__ = ["calculate_discount", "PricingService"]
