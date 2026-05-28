"""Regression tests for create-property workflow session behavior."""
from __future__ import annotations

import asyncio

from backend.ai.tools import (
    _clear_workflow_session,
    _fill_create_property,
    _get_workflow_session,
    _mark_create_property_completed,
    reset_current_messages,
    reset_current_thread_id,
    set_current_messages,
    set_current_thread_id,
)
from backend.services.auth import AuthUser


def _dummy_owner() -> AuthUser:
    return AuthUser(
        id=1,
        wallet_address="0x0000000000000000000000000000000000000001",
        role="property_owner",
        email=None,
        kyc_status="verified",
        active=True,
    )


def test_fill_create_asks_name_after_list_property_quick_action():
    token = set_current_thread_id("test:create:quick-action-name-first")
    msg_token = set_current_messages(
        [
            {"type": "ai", "content": "Hi! I'm EstateChain Copilot."},
            {
                "type": "human",
                "content": "Help me list a new property for tokenization.",
            },
        ]
    )
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        res = asyncio.run(_fill_create_property({}, _dummy_owner(), None))
        assert res.ok
        filled = res.data.get("filled") or {}
        assert "name" not in filled
        assert res.data.get("next_field") == "name"
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_messages(msg_token)
        reset_current_thread_id(token)


def test_fill_create_opens_modal_when_start_was_skipped():
    token = set_current_thread_id("test:create:skip-start")
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        res = asyncio.run(_fill_create_property({"name": "SpaceX Tower"}, _dummy_owner(), None))
        assert res.ok
        assert any(a.type == "OPEN_MODAL" and a.modal == "CREATE_PROPERTY" for a in res.actions)
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_thread_id(token)


def test_fill_create_bootstraps_modal_even_with_empty_args():
    token = set_current_thread_id("test:create:empty-args-bootstrap")
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        res = asyncio.run(_fill_create_property({}, _dummy_owner(), None))
        assert res.ok
        assert any(a.type == "NAVIGATE" and a.route == "/property_owner/properties" for a in res.actions)
        assert any(a.type == "OPEN_MODAL" and a.modal == "CREATE_PROPERTY" for a in res.actions)
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_thread_id(token)


def test_fill_create_does_not_reopen_modal_mid_flow():
    token = set_current_thread_id("test:create:mid-flow")
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        first = asyncio.run(_fill_create_property({"name": "Aurum Plaza"}, _dummy_owner(), None))
        assert first.ok
        assert any(a.type == "OPEN_MODAL" and a.modal == "CREATE_PROPERTY" for a in first.actions)

        second = asyncio.run(_fill_create_property({"location": "Miami"}, _dummy_owner(), None))
        assert second.ok
        assert not any(a.type == "OPEN_MODAL" and a.modal == "CREATE_PROPERTY" for a in second.actions)
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_thread_id(token)


def test_fill_create_resets_stale_session_on_new_name():
    token = set_current_thread_id("test:create:new-name-resets")
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        first = asyncio.run(_fill_create_property({"name": "First Tower"}, _dummy_owner(), None))
        assert first.ok
        assert any(a.type == "OPEN_MODAL" and a.modal == "CREATE_PROPERTY" for a in first.actions)

        # Keep session active (simulate interrupted first workflow).
        _ = asyncio.run(_fill_create_property({"location": "Dubai"}, _dummy_owner(), None))

        # New property name in same chat should reset stale in-progress state and
        # open CREATE_PROPERTY once for the fresh workflow.
        second_property = asyncio.run(
            _fill_create_property({"name": "Second Tower"}, _dummy_owner(), None)
        )
        assert second_property.ok
        assert any(
            a.type == "OPEN_MODAL" and a.modal == "CREATE_PROPERTY"
            for a in second_property.actions
        )
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_thread_id(token)


def test_fill_create_active_session_emits_no_navigate_or_open():
    token = set_current_thread_id("test:create:active-no-bootstrap")
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        _ = asyncio.run(_fill_create_property({"name": "Alpha One"}, _dummy_owner(), None))
        second = asyncio.run(_fill_create_property({"location": "Doha"}, _dummy_owner(), None))
        assert second.ok
        assert not any(a.type == "NAVIGATE" for a in second.actions)
        assert not any(a.type == "OPEN_MODAL" and a.modal == "CREATE_PROPERTY" for a in second.actions)
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_thread_id(token)


def test_second_property_after_success_session_opens_modal_on_first_fill():
    token = set_current_thread_id("test:create:post-success-session")
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        _mark_create_property_completed("chatgpt")
        session = _get_workflow_session("CREATE_PROPERTY")
        assert session.get("awaiting_new_property") is True

        res = asyncio.run(_fill_create_property({"name": "Second Tower"}, _dummy_owner(), None))
        assert res.ok
        assert any(a.type == "OPEN_MODAL" and a.modal == "CREATE_PROPERTY" for a in res.actions)
        assert any(a.type == "NAVIGATE" and a.route == "/property_owner/properties" for a in res.actions)
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_thread_id(token)


def test_second_property_after_success_session_bootstraps_on_auto_submit():
    token = set_current_thread_id("test:create:post-success-submit")
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        _mark_create_property_completed("chatgpt")
        final = asyncio.run(
            _fill_create_property(
                {
                    "name": "Harbor Two",
                    "location": "Boston",
                    "total_value": "15",
                    "token_supply": "15000",
                    "token_symbol": "HB2",
                },
                _dummy_owner(),
                None,
            )
        )
        assert final.ok
        assert any(a.type == "SUBMIT_FORM" and a.modal == "CREATE_PROPERTY" for a in final.actions)
        assert any(a.type == "OPEN_MODAL" and a.modal == "CREATE_PROPERTY" for a in final.actions)
        assert any(a.type == "NAVIGATE" and a.route == "/property_owner/properties" for a in final.actions)
        after = _get_workflow_session("CREATE_PROPERTY")
        assert after.get("awaiting_new_property") is True
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_thread_id(token)


def test_submit_create_active_session_keeps_fill_and_submit_actions():
    token = set_current_thread_id("test:create:active-submit")
    try:
        _clear_workflow_session("CREATE_PROPERTY")
        _ = asyncio.run(_fill_create_property({"name": "Nova Plaza"}, _dummy_owner(), None))
        _ = asyncio.run(_fill_create_property({"location": "Abu Dhabi"}, _dummy_owner(), None))
        _ = asyncio.run(_fill_create_property({"total_value": "20"}, _dummy_owner(), None))
        _ = asyncio.run(_fill_create_property({"token_supply": "20000"}, _dummy_owner(), None))
        final = asyncio.run(_fill_create_property({"token_symbol": "NOVA"}, _dummy_owner(), None))
        assert final.ok
        # Auto-submit path should include form filling and submit.
        assert any(a.type == "FILL_FIELD" and a.field == "name" and a.value == "Nova Plaza" for a in final.actions)
        assert any(a.type == "FILL_FIELD" and a.field == "token_symbol" and a.value == "NOVA" for a in final.actions)
        assert any(a.type == "SUBMIT_FORM" and a.modal == "CREATE_PROPERTY" for a in final.actions)
        # Active-flow submit should not re-bootstrap route/modal.
        assert not any(a.type == "NAVIGATE" for a in final.actions)
        assert not any(a.type == "OPEN_MODAL" and a.modal == "CREATE_PROPERTY" for a in final.actions)
    finally:
        _clear_workflow_session("CREATE_PROPERTY")
        reset_current_thread_id(token)
