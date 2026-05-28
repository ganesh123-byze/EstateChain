"""Regression tests for investor guided-invest auto-submit behavior."""
from __future__ import annotations

import asyncio

import backend.ai.tools as tools
from backend.services.auth import AuthUser


def _dummy_user() -> AuthUser:
    return AuthUser(
        id=10,
        wallet_address="0x0000000000000000000000000000000000000010",
        role="investor",
        email=None,
        kyc_status="verified",
        active=True,
    )


def test_invest_auto_submits_when_all_fields_arrive_same_turn(monkeypatch):
    token = tools.set_current_thread_id("test:invest:auto-submit:single-turn")
    try:
        tools._clear_workflow_session("INVEST_PROPERTY")
        monkeypatch.setattr(
            tools,
            "_resolve_property_by_name",
            lambda _db, _name: ({"id": 7, "name": "Oceanview"}, None),
        )
        res = asyncio.run(
            tools._fill_invest_property(
                {"property_name": "Oceanview", "token_amount": "5"},
                _dummy_user(),
                None,
            )
        )
        assert res.ok
        assert bool(res.data.get("submitted")) is True
        assert any(a.type == "SUBMIT_FORM" and a.modal == "INVEST_PROPERTY" for a in res.actions)
    finally:
        tools._clear_workflow_session("INVEST_PROPERTY")
        tools.reset_current_thread_id(token)


def test_invest_auto_submits_when_last_field_arrives_later(monkeypatch):
    token = tools.set_current_thread_id("test:invest:auto-submit:multi-turn")
    try:
        tools._clear_workflow_session("INVEST_PROPERTY")
        monkeypatch.setattr(
            tools,
            "_resolve_property_by_name",
            lambda _db, _name: ({"id": 11, "name": "Sunset Villas"}, None),
        )
        first = asyncio.run(
            tools._fill_invest_property({"property_name": "Sunset Villas"}, _dummy_user(), None)
        )
        assert first.ok
        assert bool(first.data.get("submitted")) is False

        second = asyncio.run(
            tools._fill_invest_property({"token_amount": "12"}, _dummy_user(), None)
        )
        assert second.ok
        assert bool(second.data.get("submitted")) is True
        assert any(a.type == "SUBMIT_FORM" and a.modal == "INVEST_PROPERTY" for a in second.actions)
    finally:
        tools._clear_workflow_session("INVEST_PROPERTY")
        tools.reset_current_thread_id(token)
