"""Abstract validator interface.

The core computation engine accepts a *callable* validator
(``Callable[[str], dict]``) rather than this class, so that tests can
inject a plain lambda.  Concrete validators (e.g. ``EbayValidator``)
subclass this ABC for structure and shared behaviour.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationResult:
    """Structured result returned by a validator."""
    ok: bool
    price: Optional[float]
    currency: Optional[str]
    url: str
    error: Optional[str]
    raw: Optional[str] = None   # raw price text, for debugging

    def as_dict(self) -> dict:
        """Convert to the plain dict shape expected by ``core.history``."""
        return {
            "ok": self.ok,
            "price": self.price,
            "currency": self.currency,
            "error": self.error,
            "raw": self.raw,
        }


class PriceValidator(ABC):
    """Interface for platform-specific price validators."""

    @abstractmethod
    def validate(self, product_url: str) -> ValidationResult:
        """Fetch the product page and extract the current price.

        Args:
            product_url: Full product URL *or* a bare product ID.

        Returns:
            A ``ValidationResult``.  ``ok=False`` means the price could
            not be determined (network error, parse failure, etc.).
        """
        ...
