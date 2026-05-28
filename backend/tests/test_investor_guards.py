"""Unit tests for investor copilot wallet-action guards."""
from backend.ai.investor_guards import (
    has_explicit_claim_intent,
    has_explicit_invest_intent,
    sanitize_investor_wallet_actions,
)
from backend.ai.schemas import AgentAction


def test_browse_marketplace_does_not_allow_invest():
    assert not has_explicit_invest_intent("Show me the marketplace and what's for sale")
    assert not has_explicit_invest_intent("What are the best properties to invest in?")


def test_explicit_invest_orders_allowed():
    assert has_explicit_invest_intent("Invest 10 tokens into Sunset Villas")
    assert has_explicit_invest_intent("I want to buy 5 tokens in Oceanview")


def test_claimable_lookup_not_claim_execution():
    assert not has_explicit_claim_intent("How much can I claim?")
    assert has_explicit_claim_intent("Claim my rewards on Sunset Villas")


def test_sanitize_strips_invest_modal_without_intent():
    actions = [
        AgentAction(type="NAVIGATE", route="/investor/marketplace"),
        AgentAction(type="OPEN_MODAL", modal="INVEST_PROPERTY", property_id=1),
    ]
    messages = [{"role": "user", "content": "List available properties"}]
    out = sanitize_investor_wallet_actions(messages, actions)
    assert len(out) == 1
    assert out[0].type == "NAVIGATE"
