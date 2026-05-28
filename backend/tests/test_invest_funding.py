"""Wallet balance gate for investor guided-invest chatbot."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import backend.ai.tools as tools
from backend.services.auth import AuthUser
from backend.services.investment_funding import InvestmentFundingCheck


def _investor() -> AuthUser:
    return AuthUser(
        id=10,
        wallet_address="0x0000000000000000000000000000000000000010",
        role="investor",
        email=None,
        kyc_status="verified",
        active=True,
    )


def _funded_check(token_amount: int) -> InvestmentFundingCheck:
    return InvestmentFundingCheck(
        ok=True,
        required_wei=5 * 10**17,
        balance_wei=10**18,
        required_eth="0.5",
        balance_eth="1",
        shortfall_wei=0,
        shortfall_eth="0",
        sale_price_per_token_wei=10**17,
        token_amount=token_amount,
    )


def _underfunded_check(token_amount: int) -> InvestmentFundingCheck:
    return InvestmentFundingCheck(
        ok=False,
        required_wei=10**19,
        balance_wei=10**17,
        required_eth="10",
        balance_eth="0.1",
        shortfall_wei=10**19 - 10**17,
        shortfall_eth="9.9",
        sale_price_per_token_wei=10**18,
        token_amount=token_amount,
        speak_to_user=(
            "You have insufficient funds in your account. "
            "Buying 5 token(s) in Oceanview requires 10 ETH, but your wallet balance is 0.1 ETH "
            "(about 9.9 ETH short). "
            "Add ETH to your wallet or reduce the number of tokens, then try again."
        ),
        instruction="Tell the user they have insufficient funds in your account.",
    )


def test_fill_invest_blocks_submit_when_wallet_underfunded(monkeypatch):
    token = tools.set_current_thread_id("test:invest:insufficient-funds")
    try:
        tools._clear_workflow_session("INVEST_PROPERTY")
        monkeypatch.setattr(
            tools,
            "_resolve_property_by_name",
            lambda _db, _name: (
                {
                    "id": 7,
                    "name": "Oceanview",
                    "token_address": "0x1111111111111111111111111111111111111111",
                    "tokens_available": "100",
                    "token_sale_price_wei": str(10**18),
                },
                None,
            ),
        )
        monkeypatch.setattr(
            tools,
            "_load_invest_property_row",
            lambda _db, _pid: {
                "id": 7,
                "name": "Oceanview",
                "token_address": "0x1111111111111111111111111111111111111111",
                "tokens_available": "100",
                "token_sale_price_wei": str(10**18),
            },
        )
        monkeypatch.setattr(
            tools,
            "check_investor_can_fund_investment",
            lambda _wallet, _prop, amount: _underfunded_check(amount),
        )

        res = asyncio.run(
            tools._fill_invest_property(
                {"property_name": "Oceanview", "token_amount": "5", "submit": True},
                _investor(),
                MagicMock(),
            )
        )
        assert res.ok
        assert res.data.get("insufficient_funds") is True
        assert "insufficient funds" in str(res.data.get("speak_to_user")).lower()
        assert not res.actions
        assert not res.data.get("submitted")
    finally:
        tools._clear_workflow_session("INVEST_PROPERTY")
        tools.reset_current_thread_id(token)


def test_fill_invest_proceeds_when_wallet_funded(monkeypatch):
    token = tools.set_current_thread_id("test:invest:sufficient-funds")
    try:
        tools._clear_workflow_session("INVEST_PROPERTY")
        monkeypatch.setattr(
            tools,
            "_resolve_property_by_name",
            lambda _db, _name: (
                {
                    "id": 7,
                    "name": "Oceanview",
                    "token_address": "0x1111111111111111111111111111111111111111",
                    "tokens_available": "100",
                },
                None,
            ),
        )
        monkeypatch.setattr(
            tools,
            "_load_invest_property_row",
            lambda _db, _pid: {
                "id": 7,
                "name": "Oceanview",
                "token_address": "0x1111111111111111111111111111111111111111",
                "tokens_available": "100",
            },
        )
        monkeypatch.setattr(
            tools,
            "check_investor_can_fund_investment",
            lambda _wallet, _prop, amount: _funded_check(amount),
        )

        res = asyncio.run(
            tools._fill_invest_property(
                {"property_name": "Oceanview", "token_amount": "5"},
                _investor(),
                MagicMock(),
            )
        )
        assert res.ok
        assert res.data.get("submitted") is True
        assert any(a.type == "SUBMIT_FORM" for a in res.actions)
    finally:
        tools._clear_workflow_session("INVEST_PROPERTY")
        tools.reset_current_thread_id(token)
