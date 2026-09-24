"""eBay price validator.

Fetches an eBay product page over HTTP and extracts the current displayed
price from the server-rendered HTML.

Assumptions (documented — brief §18):
------------------------------------------------------------

* eBay item URLs are of the form
  ``https://www.ebay.com/itm/<ITEM_ID>`` (also regional variants like
  ``ebay.co.uk`` / ``ebay.in``).  A bare numeric ID may also be passed
  and will be expanded to a full URL.

* The price is rendered server-side (no JavaScript execution required)
  in one of these elements, checked in priority order:

      div.x-price-primary   — modern layout (2024-2025)
      div#prcIsum           — legacy layout
      span#prcIsum          — legacy layout variant
      meta[itemprop=price]  — JSON-LD / microdata fallback

* The price text typically contains a currency prefix
  (e.g. ``"US $201.00"``, ``"£1,234.56"``).  We strip non-numeric
  characters and parse the remainder as a float.

* We do **not** execute JavaScript.  If eBay returns a JS-only page
  (rare for item pages), the validator reports ``ok=False``.  For a
  college project this is acceptable — the extension's live page
  extraction is the primary source; the validator is a fallback for
  low-trust situations.

Known limitations:
------------------

* eBay may rate-limit or block the validator's IP after many rapid
  requests.  The validator timeout is configurable
  (``VALIDATOR_TIMEOUT``).

* eBay's DOM structure may change over time.  The selectors above are
  based on the structure observed in 2024-2025.

* Auction-style listings may show a current *bid* price rather than a
  buy-it-now price.  We pick the first matching price element found.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .base import PriceValidator, ValidationResult

logger = logging.getLogger(__name__)

# CSS selectors in priority order.
EBAY_PRICE_SELECTORS = [
    "div.x-price-primary",
    "div#prcIsum",
    "span#prcIsum",
    "[itemprop='price']",
    "meta[itemprop='price']",
]

# Currency prefix → ISO 4217 code.  Order matters: longer prefixes first.
_CURRENCY_PREFIXES: list[tuple[str, str]] = [
    ("US $", "USD"),
    ("C $", "CAD"),
    ("A $", "AUD"),
    ("AU $", "AUD"),
    ("GBP £", "GBP"),
    ("£", "GBP"),
    ("€", "EUR"),
    ("JP¥", "JPY"),
    ("₹", "INR"),
    ("R $", "BRL"),
    ("CHF", "CHF"),
]


def parse_price_text(text: str) -> tuple[Optional[float], Optional[str]]:
    """Parse a raw eBay price string like ``"US $201.00"`` or ``"£1,234.56"``.

    Returns ``(price, currency_code)``.  Either may be ``None`` if the
    text cannot be parsed.  ``currency`` may be non-None even when
    ``price`` is None (we recognised the currency but couldn't parse a
    number).
    """
    if not text:
        return None, None
    text = text.strip()

    currency: Optional[str] = None
    for prefix, code in _CURRENCY_PREFIXES:
        if prefix in text:
            currency = code
            break

    # Strip everything except digits and the decimal point.
    cleaned = re.sub(r"[^\d.]", "", text)
    if not cleaned:
        return None, currency
    # Guard against multiple dots ("1.2.3") — keep only the first.
    parts = cleaned.split(".")
    if len(parts) > 2:
        cleaned = ".".join(parts[:2])
    try:
        return float(cleaned), currency
    except ValueError:
        return None, currency


def extract_item_id(url_or_id: str) -> Optional[str]:
    """Extract the eBay item ID from a URL like ``.../itm/123456789?...``
    or return the string itself if it is already a bare numeric ID."""
    if not url_or_id:
        return None
    if url_or_id.isdigit():
        return url_or_id
    m = re.search(r"/itm/(?:[^/?#]+/)?(\d{6,})", url_or_id)
    return m.group(1) if m else None


class EbayValidator(PriceValidator):
    """Concrete validator for ``ebay.com`` (and regional variants)."""

    def __init__(
        self,
        base_url: str = "https://www.ebay.com",
        timeout: int = 10,
        user_agent: str = "TruePrice-Validator/1.0",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent

    def _normalise_url(self, product_url: str) -> str:
        """Expand a bare item ID to a full eBay URL."""
        if product_url.isdigit():
            return f"{self.base_url}/itm/{product_url}"
        return product_url

    def validate(self, product_url: str) -> ValidationResult:
        if not product_url:
            return ValidationResult(
                ok=False, price=None, currency=None,
                url=product_url, error="empty product url",
            )

        url = self._normalise_url(product_url)

        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=self.timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("eBay validator fetch failed for %s: %s", url, exc)
            return ValidationResult(
                ok=False, price=None, currency=None,
                url=url, error=f"fetch failed: {exc}",
            )

        soup = BeautifulSoup(resp.text, "html.parser")

        for selector in EBAY_PRICE_SELECTORS:
            el = soup.select_one(selector)
            if el is None:
                continue
            # ``meta`` tags store the price in the ``content`` attribute.
            raw_text = (
                el.get("content") if el.name == "meta"
                else el.get_text(" ", strip=True)
            )
            if not raw_text:
                continue
            price, currency = parse_price_text(raw_text)
            if price is not None:
                logger.info(
                    "eBay validator: url=%s price=%s currency=%s (selector=%s)",
                    url, price, currency, selector,
                )
                return ValidationResult(
                    ok=True, price=price, currency=currency,
                    url=url, error=None, raw=raw_text,
                )

        return ValidationResult(
            ok=False, price=None, currency=None,
            url=url,
            error="price element not found on page (selectors tried: "
                  + ", ".join(EBAY_PRICE_SELECTORS) + ")",
        )
