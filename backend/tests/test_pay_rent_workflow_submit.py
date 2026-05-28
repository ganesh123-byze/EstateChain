"""Regression tests for tenant guided pay-rent auto-submit behavior."""
from __future__ import annotations

import asyncio

import backend.ai.tools as tools
from backend.services.auth import AuthUser


def _tenant_user() -> AuthUser:
    return AuthUser(
        id=20,
        wallet_address="0x0000000000000000000000000000000000000020",
        role="tenant",
        email=None,
        kyc_status="verified",
        active=True,
    )


def test_pay_rent_auto_submits_when_property_name_arrives(monkeypatch):
    token = tools.set_current_thread_id("test:pay-rent:auto-submit")
    try:
        tools._clear_workflow_session("PAY_RENT")
        monkeypatch.setattr(
            tools,
            "_resolve_property_for_rent",
            lambda _db, _name: ({"id": 3, "name": "Harbor Lofts", "rent_enabled": True}, None),
        )
        async def _fake_execute(pid, _user, _db):
            return tools.ToolResult(
                ok=True,
                data={"message": "ok", "speak_to_user": "Confirm in MetaMask."},
                actions=tools._pay_rent_actions_on_submit(pid),
            )

        monkeypatch.setattr(tools, "_execute_pay_rent_ui", _fake_execute)
        res = asyncio.run(
            tools._fill_pay_rent_property({"property_name": "Harbor Lofts"}, _tenant_user(), None)
        )
        assert res.ok
        assert bool(res.data.get("submitted")) is True
        assert any(a.type == "SUBMIT_FORM" and a.modal == "PAY_RENT" for a in res.actions)
    finally:
        tools._clear_workflow_session("PAY_RENT")
        tools.reset_current_thread_id(token)


def test_start_pay_rent_resolves_property_name(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_resolve_property_for_rent",
        lambda _db, _name: ({"id": 9, "name": "Sunset Tower"}, None),
    )
    called: list[int] = []

    async def _fake_execute(pid, _user, _db):
        called.append(pid)
        return tools.ToolResult(ok=True, data={"message": "ok"}, actions=[])

    monkeypatch.setattr(tools, "_execute_pay_rent_ui", _fake_execute)
    res = asyncio.run(
        tools._start_pay_rent({"property_name": "Sunset Tower"}, _tenant_user(), None)
    )
    assert res.ok
    assert called == [9]
