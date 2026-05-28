"""Unit tests for investment_funding service."""
from __future__ import annotations

import pytest

from backend.services.investment_funding import (
    InvestmentFundingError,
    check_investor_can_fund_investment,
    investment_required_wei,
    read_sale_price_per_token_wei,
)


def test_read_sale_price_from_db_when_no_token_address():
    price = read_sale_price_per_token_wei({"token_sale_price_wei": "1500000000000000000"})
    assert price == 1500000000000000000


def test_investment_required_wei_multiplies_by_token_count():
    prop = {"token_sale_price_wei": "1000000000000000000"}
    assert investment_required_wei(prop, 3) == 3000000000000000000


def test_check_insufficient_funds_message(monkeypatch):
    monkeypatch.setattr(
        "backend.services.investment_funding.read_sale_price_per_token_wei",
        lambda _p: 10**18,
    )
    monkeypatch.setattr(
        "backend.services.wallet_funding.read_native_balance_wei",
        lambda _addr: 10**17,
    )
    out = check_investor_can_fund_investment(
        "0x0000000000000000000000000000000000000010",
        {"name": "Tower", "token_sale_price_wei": str(10**18)},
        2,
    )
    assert out.ok is False
    assert "insufficient funds" in out.speak_to_user.lower()
    assert out.required_wei == 2 * 10**18


def test_check_sufficient_funds(monkeypatch):
    monkeypatch.setattr(
        "backend.services.investment_funding.read_sale_price_per_token_wei",
        lambda _p: 10**17,
    )
    monkeypatch.setattr(
        "backend.services.wallet_funding.read_native_balance_wei",
        lambda _addr: 10**18,
    )
    out = check_investor_can_fund_investment(
        "0x0000000000000000000000000000000000000010",
        {"name": "Tower"},
        5,
    )
    assert out.ok is True


def test_read_sale_price_raises_when_missing():
    with pytest.raises(InvestmentFundingError):
        read_sale_price_per_token_wei({})
