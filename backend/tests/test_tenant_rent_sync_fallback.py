"""Tenant chatbot rent-sync fallback tests for oversized DB rent values."""
from __future__ import annotations

import backend.ai.tools as ai_tools


def test_tool_sync_falls_back_to_onchain_rent_when_db_value_too_high(monkeypatch):
    monkeypatch.setattr(ai_tools, "ensure_rent_property_registered", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_tools,
        "sync_rent_amount_to_contract",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(Exception("execution reverted: Rent amount too high")),
    )
    monkeypatch.setattr(
        ai_tools,
        "sync_investors_to_contract",
        lambda *_args, **_kwargs: ["0x0000000000000000000000000000000000000001", "0x0000000000000000000000000000000000000002"],
    )
    monkeypatch.setattr(
        "backend.services.blockchain.get_rent_property_info",
        lambda _property_id: {"active": True, "monthly_rent_wei": "10000000000000000"},
    )

    synced = ai_tools._ensure_rent_chain_ready_for_payment(
        cursor=None,
        property_item={"monthly_rent_wei": "999999999999999999999999999999"},
        property_id=9,
    )

    assert synced == 2


def test_tool_sync_raises_when_onchain_rent_not_available(monkeypatch):
    monkeypatch.setattr(ai_tools, "ensure_rent_property_registered", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_tools,
        "sync_rent_amount_to_contract",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(Exception("execution reverted: Rent amount too high")),
    )
    monkeypatch.setattr(
        "backend.services.blockchain.get_rent_property_info",
        lambda _property_id: {"active": False, "monthly_rent_wei": "0"},
    )

    try:
        ai_tools._ensure_rent_chain_ready_for_payment(
            cursor=None,
            property_item={"monthly_rent_wei": "999999999999999999999999999999"},
            property_id=10,
        )
        raised = False
    except Exception as exc:  # noqa: BLE001
        raised = "rent amount too high" in str(exc).lower()

    assert raised is True
