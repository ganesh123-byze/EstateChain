"""Authoritative ETH funding checks for primary-market token purchases.

Investors pay ``salePricePerTokenWei * tokenAmount`` in native ETH when calling
``SecurityToken.invest``. This module centralizes sale-price resolution (on-chain
when deployed) and wallet balance comparison so API routes and the investor
copilot share one source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.services.blockchain import from_wei, get_contract, get_web3
from backend.services.wallet_funding import (
    WalletFundingError,
    check_wallet_covers_required_wei,
    format_eth_display,
)


class InvestmentFundingError(WalletFundingError):
    """Raised when required investment cost cannot be determined."""


@dataclass(frozen=True)
class InvestmentFundingCheck:
    """Result of comparing wallet ETH balance to an investment order total."""

    ok: bool
    required_wei: int
    balance_wei: int
    required_eth: str
    balance_eth: str
    shortfall_wei: int
    shortfall_eth: str
    sale_price_per_token_wei: int
    token_amount: int
    speak_to_user: str = ""
    instruction: str = ""


def read_sale_price_per_token_wei(property_item: dict[str, Any]) -> int:
    """Return wei price per whole token — on-chain value wins when a token exists."""
    token_address = property_item.get("token_address")
    if token_address:
        web3 = get_web3()
        if not web3.is_address(str(token_address)):
            raise InvestmentFundingError("Property token address is invalid.")
        token_contract = get_contract("SecurityToken", str(token_address))
        try:
            price = int(token_contract.functions.salePricePerTokenWei().call())
        except Exception as exc:
            raise InvestmentFundingError(
                f"Failed to read on-chain sale price: {exc}"
            ) from exc
        if price <= 0:
            raise InvestmentFundingError("On-chain sale price is zero.")
        return price

    for key in ("token_sale_price_wei", "token_price_base"):
        raw = property_item.get(key)
        if raw in (None, "", "0"):
            continue
        try:
            price = int(raw)
        except (TypeError, ValueError) as exc:
            raise InvestmentFundingError(f"Invalid stored sale price ({key}).") from exc
        if price > 0:
            return price

    raise InvestmentFundingError("Property has no sale price configured.")


def investment_required_wei(property_item: dict[str, Any], token_amount: int) -> int:
    """Total ETH (wei) the investor must send for ``token_amount`` whole tokens."""
    amount = int(token_amount)
    if amount < 1:
        raise InvestmentFundingError("token_amount must be at least 1.")
    price = read_sale_price_per_token_wei(property_item)
    return price * amount


def check_investor_can_fund_investment(
    wallet_address: str,
    property_item: dict[str, Any],
    token_amount: int,
) -> InvestmentFundingCheck:
    """Return whether ``wallet_address`` holds enough ETH for the order."""
    sale_price_per_token_wei = read_sale_price_per_token_wei(property_item)
    amount = int(token_amount)
    required_wei = sale_price_per_token_wei * amount
    base = check_wallet_covers_required_wei(wallet_address, required_wei)

    if base.ok:
        return InvestmentFundingCheck(
            ok=True,
            required_wei=base.required_wei,
            balance_wei=base.balance_wei,
            required_eth=base.required_eth,
            balance_eth=base.balance_eth,
            shortfall_wei=0,
            shortfall_eth="0",
            sale_price_per_token_wei=sale_price_per_token_wei,
            token_amount=amount,
        )

    property_name = str(property_item.get("name") or "this property").strip()
    speak = (
        "You have insufficient funds in your account. "
        f"Buying {amount} token(s) in {property_name} requires "
        f"{base.required_eth} ETH, but your wallet balance is {base.balance_eth} ETH "
        f"(about {base.shortfall_eth} ETH short). "
        "Add ETH to your wallet or reduce the number of tokens, then try again."
    )
    return InvestmentFundingCheck(
        ok=False,
        required_wei=base.required_wei,
        balance_wei=base.balance_wei,
        required_eth=base.required_eth,
        balance_eth=base.balance_eth,
        shortfall_wei=base.shortfall_wei,
        shortfall_eth=base.shortfall_eth,
        sale_price_per_token_wei=sale_price_per_token_wei,
        token_amount=amount,
        speak_to_user=speak,
        instruction=(
            "Tell the user they have insufficient funds in their account using "
            "`speak_to_user`. Do NOT open MetaMask or submit the invest form. "
            "Ask them to add ETH or choose a smaller token amount."
        ),
    )


def required_eth_decimal(property_item: dict[str, Any], token_amount: int) -> Decimal:
    """Human-readable ETH total for an order (used by API layers)."""
    return from_wei(investment_required_wei(property_item, token_amount))
