"""Tests for create-property rent sync fast path and validation."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api._helpers import (
    MAX_ONCHAIN_MONTHLY_RENT_WEI,
    sync_rent_chain_for_new_property,
    validate_monthly_rent_for_chain,
)


def test_validate_monthly_rent_rejects_above_on_chain_cap():
    with pytest.raises(HTTPException) as exc:
        validate_monthly_rent_for_chain(MAX_ONCHAIN_MONTHLY_RENT_WEI + 1)
    assert exc.value.status_code == 409
    assert "100 ETH" in str(exc.value.detail)


def test_sync_rent_new_property_skips_when_already_matches(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        "backend.api._helpers.get_rent_property_info",
        lambda _pid: {"active": True, "monthly_rent_wei": 10**18},
    )
    monkeypatch.setattr(
        "backend.api._helpers.ensure_rent_property_registered",
        lambda *_a, **_k: calls.append("register"),
    )
    monkeypatch.setattr(
        "backend.api._helpers.set_monthly_rent",
        lambda *_a, **_k: calls.append("set_rent"),
    )

    rent = sync_rent_chain_for_new_property(
        None,
        {"monthly_rent_wei": str(10**18), "token_address": "0x" + "1" * 40},
        42,
    )
    assert rent == 10**18
    assert calls == []


def test_sync_rent_new_property_registers_then_sets_rent(monkeypatch):
    calls: list[str] = []
    state = {"active": False, "monthly_rent_wei": 0}

    def _info(_pid):
        return dict(state)

    def _register(_cursor, _prop, _pid, *, fast=False):
        calls.append(f"register:fast={fast}")
        state["active"] = True

    def _set_rent(_pid, rent_wei, *, use_retry=True):
        calls.append(f"set:{rent_wei}:retry={use_retry}")
        state["monthly_rent_wei"] = rent_wei

    monkeypatch.setattr("backend.api._helpers.get_rent_property_info", _info)
    monkeypatch.setattr("backend.api._helpers.ensure_rent_property_registered", _register)
    monkeypatch.setattr("backend.api._helpers.set_monthly_rent", _set_rent)
    monkeypatch.setattr("backend.api._helpers.require_property_token", lambda _p: None)

    rent = sync_rent_chain_for_new_property(
        None,
        {"monthly_rent_wei": "5000000000000000000", "token_address": "0x" + "2" * 40},
        7,
    )
    assert rent == 5_000_000_000_000_000_000
    assert calls == ["register:fast=True", "set:5000000000000000000:retry=False"]
