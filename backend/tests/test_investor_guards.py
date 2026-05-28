"""Unit tests for investor copilot wallet-action guards."""
from backend.ai.investor_guards import (
    has_explicit_claim_intent,
    has_explicit_invest_intent,
    invest_workflow_active,
    sanitize_investor_wallet_actions,
    wants_to_begin_invest_workflow,
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


def test_wants_to_begin_invest_workflow():
    assert wants_to_begin_invest_workflow("I want to invest")
    assert has_explicit_invest_intent("Help me invest in a property")


def test_workflow_session_allows_metamask_submit():
    assert invest_workflow_active({"in_progress": True, "submitted": False})
    actions = [
        AgentAction(type="SUBMIT_FORM", modal="INVEST_PROPERTY", property_id=3),
    ]
    messages = [{"role": "user", "content": "10"}]
    session = {"completing_submit": True, "submitted": True}
    out = sanitize_investor_wallet_actions(messages, actions, invest_session=session)
    assert len(out) == 1
    assert out[0].type == "SUBMIT_FORM"
