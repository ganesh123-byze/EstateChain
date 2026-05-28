"""High-value create-property confirmation in the property-owner chatbot."""
from __future__ import annotations

import asyncio

import backend.ai.tools as tools
from backend.ai.tools import (
    _clear_workflow_session,
    _fill_create_property,
    reset_current_messages,
    reset_current_thread_id,
    set_current_messages,
    set_current_thread_id,
)
from backend.ai.workflow_parsers import assess_high_value_create_property, parse_yes_no_confirmation
from backend.services.auth import AuthUser


def _owner() -> AuthUser:
    return AuthUser(
        id=1,
        wallet_address="0x0000000000000000000000000000000000000001",
        role="property_owner",
        email=None,
        kyc_status="verified",
        active=True,
    )


def test_assess_high_value_when_token_supply_large():
    out = assess_high_value_create_property(
        {
            "name": "Tower",
            "location": "NYC",
            "total_value": "10",
            "token_supply": "100000",
            "token_symbol": "TWR",
        }
    )
    assert out["is_high"] is True
    assert any("Token supply" in r for r in out["reasons"])


def test_parse_yes_no_confirmation():
    assert parse_yes_no_confirmation("Yes") is True
    assert parse_yes_no_confirmation("no thanks") is False
    assert parse_yes_no_confirmation("maybe later") is None


def test_fill_create_gates_submit_until_user_confirms_yes():
    token = set_current_thread_id("test:create:high-value-gate")
    msg_token = set_current_messages(
        [
            {"type": "ai", "content": "What's the monthly rent?"},
            {"type": "human", "content": "20"},
        ]
    )
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        filled = {
            "name": "Mega Estate",
            "location": "Dubai",
            "total_value": "100",
            "token_supply": "200000",
            "token_symbol": "MEGA",
            "monthly_rent_eth": "12",
        }
        gate = asyncio.run(
            _fill_create_property({**filled, "submit": True}, _owner(), None)
        )
        assert gate.ok
        assert gate.data.get("awaiting_high_value_confirmation") is True
        assert not gate.actions
        assert "Yes" in str(gate.data.get("speak_to_user"))

        proceed = asyncio.run(
            _fill_create_property(
                {"confirm_high_values": True, "submit": True},
                _owner(),
                None,
            )
        )
        assert proceed.ok
        assert proceed.data.get("submitted") is True
        assert any(a.type == "SUBMIT_FORM" for a in proceed.actions)
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_messages(msg_token)
        reset_current_thread_id(token)


def test_fill_create_cancels_when_user_says_no():
    token = set_current_thread_id("test:create:high-value-cancel")
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        tools._set_workflow_session(
            "CREATE_PROPERTY",
            {
                "in_progress": True,
                "filled": {
                    "name": "Big",
                    "location": "LA",
                    "total_value": "80",
                    "token_supply": "90000",
                    "token_symbol": "BIG",
                },
                "awaiting_high_value_confirmation": True,
                "high_values_confirmed": False,
            },
        )
        res = asyncio.run(
            _fill_create_property({"confirm_high_values": False}, _owner(), None)
        )
        assert res.ok
        assert res.data.get("cancelled") is True
        assert res.data.get("property_create_cancelled") is True
        assert not any(a.type == "SUBMIT_FORM" for a in res.actions)
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_thread_id(token)


def test_fill_create_yes_after_cancel_says_listing_canceled():
    token = set_current_thread_id("test:create:high-value-yes-after-cancel")
    msg_token = set_current_messages(
        [
            {"type": "ai", "content": "Do you want to proceed? Reply Yes or No."},
            {"type": "human", "content": "yes"},
        ]
    )
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        tools._set_workflow_session(
            "CREATE_PROPERTY",
            {
                "in_progress": True,
                "filled": {
                    "name": "Big",
                    "location": "LA",
                    "total_value": "80",
                    "token_supply": "90000",
                    "token_symbol": "BIG",
                    "monthly_rent_eth": "12",
                },
                "property_create_cancelled": True,
                "awaiting_high_value_confirmation": False,
                "high_values_confirmed": False,
            },
        )
        res = asyncio.run(
            _fill_create_property({"submit": True}, _owner(), None)
        )
        assert res.ok
        assert res.data.get("property_create_cancelled") is True
        assert "canceled" in str(res.data.get("speak_to_user")).lower()
        assert not any(a.type == "SUBMIT_FORM" for a in res.actions)
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_messages(msg_token)
        reset_current_thread_id(token)
