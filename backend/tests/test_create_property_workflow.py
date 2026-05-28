"""Regression tests for create-property workflow session behavior."""
from __future__ import annotations

import asyncio

from backend.ai.tools import (
    _clear_workflow_session,
    _fill_create_property,
    set_current_thread_id,
    reset_current_thread_id,
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
