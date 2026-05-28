"""Tenant pay-rent wallet balance checks."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import backend.ai.tools as tools
from backend.services.auth import AuthUser
from backend.services.wallet_funding import WalletFundingCheck


def _tenant() -> AuthUser:
    return AuthUser(
        id=20,
        wallet_address="0x0000000000000000000000000000000000000020",
        role="tenant",
        email=None,
        kyc_status="verified",
        active=True,
    )


def _underfunded_rent_check() -> WalletFundingCheck:
    return WalletFundingCheck(
        ok=False,
        required_wei=10**19,
        balance_wei=10**17,
        required_eth="10",
        balance_eth="0.1",
        shortfall_wei=10**19 - 10**17,
        shortfall_eth="9.9",
        speak_to_user=(
            "You have insufficient balance in your wallet. "
            "Monthly rent for Harbor Lofts is 10 ETH, but your wallet balance is 0.1 ETH."
        ),
        instruction="Tell the user they have insufficient balance in their wallet.",
    )


def test_check_tenant_insufficient_balance_message(monkeypatch):
    monkeypatch.setattr(
        "backend.services.wallet_funding.read_native_balance_wei",
        lambda _addr: 10**17,
    )
    from backend.services.rent_payment_funding import check_tenant_can_pay_monthly_rent

    out = check_tenant_can_pay_monthly_rent(
        "0x0000000000000000000000000000000000000020",
        10**18,
        "Harbor Lofts",
    )
    assert out.ok is False
    assert "insufficient balance" in out.speak_to_user.lower()


def test_execute_pay_rent_ui_blocks_when_wallet_underfunded(monkeypatch):
    db = MagicMock()
    cursor = MagicMock()
    db.cursor.return_value = cursor

    monkeypatch.setattr(
        tools,
        "fetch_property",
        lambda _c, _pid: {"id": 3, "name": "Harbor Lofts", "is_active": True},
    )
    monkeypatch.setattr(tools, "enrich_property_with_supply", lambda _c, row: row)
    monkeypatch.setattr(tools, "_serialize_property", lambda row: {**row, "monthly_rent_eth": "10"})
    monkeypatch.setattr(tools, "_validate_property_rentable", lambda _p: None)
    monkeypatch.setattr(
        tools,
        "get_last_confirmed_rent_payment_by_wallet",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        tools,
        "compute_rent_period_status",
        lambda _lp: {"current_cycle_paid": False},
    )
    monkeypatch.setattr("backend.services.blockchain.platform_deployer_mismatch", lambda: None)
    monkeypatch.setattr(tools, "_ensure_rent_chain_ready_for_payment", lambda *_a, **_k: 0)
    monkeypatch.setattr(
        "backend.services.blockchain.get_rent_property_info",
        lambda _pid: {"active": True, "monthly_rent_wei": 10**19},
    )
    monkeypatch.setattr(
        tools,
        "check_tenant_can_pay_monthly_rent",
        lambda *_a, **_k: _underfunded_rent_check(),
    )

    res = asyncio.run(tools._execute_pay_rent_ui(3, _tenant(), db))
    assert res.ok
    assert res.data.get("insufficient_funds") is True
    assert "insufficient balance" in str(res.data.get("speak_to_user")).lower()
    assert not res.actions
