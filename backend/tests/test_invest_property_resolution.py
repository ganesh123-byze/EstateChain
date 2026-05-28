"""Tests for robust investor property resolution."""
from backend.ai.tools import _resolve_investable_property_from_items


def _prop(
    pid: int,
    name: str,
    *,
    token_address: str = "0xabc",
    tokens_available: str = "100",
    token_symbol: str = "TOK",
):
    return {
        "id": pid,
        "name": name,
        "location": "Any",
        "token_symbol": token_symbol,
        "token_address": token_address,
        "tokens_available": tokens_available,
    }


def test_resolution_rejects_weak_nonexistent_match():
    items = [
        _prop(1, "Oceanview Apartments", token_symbol="OCN"),
        _prop(2, "Sunset Villas", token_symbol="SUN"),
    ]
    prop, err = _resolve_investable_property_from_items(items, "zzzz-unknown")
    assert prop is None
    assert err and "No investable property found" in err


def test_resolution_asks_clarification_on_ambiguous_query():
    items = [
        _prop(1, "Oceanview Apartments"),
        _prop(2, "Oceanview Heights"),
    ]
    prop, err = _resolve_investable_property_from_items(items, "oceanview")
    assert prop is None
    assert err and "Several investable properties match" in err


def test_resolution_ignores_non_investable_properties():
    items = [
        _prop(1, "Green Park", token_address="", tokens_available="0"),
        _prop(2, "Blue Park", token_address="0xdef", tokens_available="50"),
    ]
    prop, err = _resolve_investable_property_from_items(items, "blue park")
    assert err is None
    assert prop and int(prop["id"]) == 2
