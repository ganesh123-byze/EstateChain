"""Tests for spoken workflow answer normalization."""
from backend.ai.workflow_parsers import (
    assistant_prompted_for_create_field,
    is_generic_create_property_intent,
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


def test_list_new_property_quick_action_is_not_a_name():
    prompt = "Help me list a new property for tokenization."
    assert is_generic_create_property_intent(prompt) is True
    assert normalize_create_property_field("name", prompt) == ""


def test_real_property_name_is_not_generic_intent():
    assert is_generic_create_property_intent("Sunset Villas") is False
    assert normalize_create_property_field("name", "Sunset Villas") == "Sunset Villas"


def test_assistant_greeting_does_not_prompt_for_name():
    assert assistant_prompted_for_create_field(
        "Hi! I'm EstateChain Copilot. Ask about your properties.",
        "name",
    ) is False


def test_assistant_name_question_is_detected():
    assert assistant_prompted_for_create_field(
        "What's the name of the property?",
        "name",
    ) is True


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
