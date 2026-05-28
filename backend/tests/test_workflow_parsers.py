"""Tests for spoken workflow answer normalization."""
from backend.ai.workflow_parsers import (
    normalize_create_property_accumulated,
    normalize_create_property_field,
)


def test_one_lakh_token_supply():
    assert normalize_create_property_field("token_supply", "One lakh tokens") == "100000"


def test_usd_symbol():
    assert normalize_create_property_field("token_symbol", "I want to give an USD symbol") == "USD"


def test_monthly_rent_decimal():
    assert normalize_create_property_field("monthly_rent_eth", "The monthly rent is 0.010") == "0.010"


def test_total_value_whole_number_stays_plain_decimal():
    assert normalize_create_property_field("total_value", "20") == "20"


def test_accumulated_normalization():
    out = normalize_create_property_accumulated(
        {
            "token_supply": "one lakh",
            "token_symbol": "usd symbol",
            "monthly_rent_eth": "0.5",
        }
    )
    assert out["token_supply"] == "100000"
    assert out["token_symbol"] == "USD"
