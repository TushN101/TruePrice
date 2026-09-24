"""Tests for the eBay validator.

These tests use static HTML fixtures (no live network) to verify the
price-extraction and parsing logic.  Network behaviour is tested only
for error handling (via a mock ``requests.get``).
"""
from unittest.mock import patch, MagicMock

import pytest

from validators.ebay_validator import (
    EbayValidator,
    extract_item_id,
    parse_price_text,
)


# ─── parse_price_text ──────────────────────────────────────────────────

def test_parse_us_dollar():
    price, cur = parse_price_text("US $201.00")
    assert price == 201.0
    assert cur == "USD"


def test_parse_gbp():
    price, cur = parse_price_text("£1,234.56")
    assert price == 1234.56
    assert cur == "GBP"


def test_parse_eur():
    price, cur = parse_price_text("€99.99")
    assert price == 99.99
    assert cur == "EUR"


def test_parse_inr():
    price, cur = parse_price_text("₹15,000")
    assert price == 15000.0
    assert cur == "INR"


def test_parse_empty():
    assert parse_price_text("") == (None, None)
    assert parse_price_text(None) == (None, None)


def test_parse_no_digits():
    price, cur = parse_price_text("Price unavailable")
    assert price is None


def test_parse_multiple_dots():
    """A malformed string like '1.2.3' should still yield a number."""
    price, _ = parse_price_text("US $1.2.3")
    assert price == 1.2


# ─── extract_item_id ───────────────────────────────────────────────────

def test_extract_item_id_from_url():
    assert extract_item_id("https://www.ebay.com/itm/123456789") == "123456789"


def test_extract_item_id_from_url_with_slug():
    assert extract_item_id(
        "https://www.ebay.com/itm/Sony-Headphones/123456789?hash=abc"
    ) == "123456789"


def test_extract_item_id_bare():
    assert extract_item_id("123456789") == "123456789"


def test_extract_item_id_invalid():
    assert extract_item_id("https://www.ebay.com/str/some-store") is None
    assert extract_item_id("") is None


# ─── EbayValidator with mocked HTTP ────────────────────────────────────

MODERN_HTML = """
<html><body>
  <div class="x-price-primary"><span>US $201.00</span></div>
</body></html>
"""

LEGACY_HTML = """
<html><body>
  <div id="prcIsum">US $199.99</div>
</body></html>
"""

META_HTML = """
<html><body>
  <meta itemprop="price" content="250.00">
</body></html>
"""

NO_PRICE_HTML = """
<html><body><h1>Product</h1><p>No price here.</p></body></html>
"""


def _mock_response(html, status=200):
    resp = MagicMock()
    resp.text = html
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    return resp


def test_validator_finds_price_modern_layout():
    v = EbayValidator()
    with patch("validators.ebay_validator.requests.get",
               return_value=_mock_response(MODERN_HTML)):
        result = v.validate("https://www.ebay.com/itm/123")
    assert result.ok is True
    assert result.price == 201.0
    assert result.currency == "USD"


def test_validator_finds_price_legacy_layout():
    v = EbayValidator()
    with patch("validators.ebay_validator.requests.get",
               return_value=_mock_response(LEGACY_HTML)):
        result = v.validate("https://www.ebay.com/itm/123")
    assert result.ok is True
    assert result.price == 199.99


def test_validator_finds_price_meta_fallback():
    v = EbayValidator()
    with patch("validators.ebay_validator.requests.get",
               return_value=_mock_response(META_HTML)):
        result = v.validate("https://www.ebay.com/itm/123")
    assert result.ok is True
    assert result.price == 250.0


def test_validator_no_price_on_page():
    v = EbayValidator()
    with patch("validators.ebay_validator.requests.get",
               return_value=_mock_response(NO_PRICE_HTML)):
        result = v.validate("https://www.ebay.com/itm/123")
    assert result.ok is False
    assert result.price is None
    assert "not found" in result.error


def test_validator_network_error():
    import requests
    v = EbayValidator()
    with patch("validators.ebay_validator.requests.get",
               side_effect=requests.ConnectionError("refused")):
        result = v.validate("https://www.ebay.com/itm/123")
    assert result.ok is False
    assert result.price is None
    assert "fetch failed" in result.error


def test_validator_empty_url():
    v = EbayValidator()
    result = v.validate("")
    assert result.ok is False
    assert result.error == "empty product url"


def test_validator_bare_id_expanded():
    """A bare numeric ID is expanded to a full eBay URL."""
    v = EbayValidator(base_url="https://www.ebay.com")
    with patch("validators.ebay_validator.requests.get",
               return_value=_mock_response(MODERN_HTML)) as mock_get:
        v.validate("123456789")
        called_url = mock_get.call_args[0][0]
        assert called_url == "https://www.ebay.com/itm/123456789"


def test_validator_as_dict_shape():
    """The ``as_dict()`` method produces the shape expected by core.history."""
    v = EbayValidator()
    with patch("validators.ebay_validator.requests.get",
               return_value=_mock_response(MODERN_HTML)):
        result = v.validate("https://www.ebay.com/itm/123")
    d = result.as_dict()
    assert set(d.keys()) >= {"ok", "price", "currency", "error"}
    assert d["ok"] is True
    assert d["price"] == 201.0
