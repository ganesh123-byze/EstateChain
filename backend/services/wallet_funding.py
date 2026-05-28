"""Shared native-ETH balance checks for on-chain actions (invest, pay rent, etc.)."""
from __future__ import annotations

from dataclasses import dataclass

from backend.services.blockchain import from_wei, get_native_balance, get_web3


class WalletFundingError(Exception):
    """Raised when a wallet address or required amount is invalid."""


@dataclass(frozen=True)
class WalletFundingCheck:
    """Result of comparing wallet ETH balance to a required wei amount."""

    ok: bool
    required_wei: int
    balance_wei: int
    required_eth: str
    balance_eth: str
    shortfall_wei: int
    shortfall_eth: str
    speak_to_user: str = ""
    instruction: str = ""


def format_eth_display(wei: int) -> str:
    eth = from_wei(max(0, int(wei)))
    text = format(eth, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def read_native_balance_wei(wallet_address: str) -> int:
    web3 = get_web3()
    if not wallet_address or not web3.is_address(wallet_address):
        raise WalletFundingError("No valid wallet connected.")
    checksum = web3.to_checksum_address(wallet_address)
    return int(get_native_balance(checksum))


def check_wallet_covers_required_wei(
    wallet_address: str,
    required_wei: int,
) -> WalletFundingCheck:
    """Return whether the wallet holds at least ``required_wei`` native ETH."""
    amount = int(required_wei)
    if amount < 0:
        raise WalletFundingError("required_wei must be non-negative.")
    if amount == 0:
        balance_wei = read_native_balance_wei(wallet_address)
        return WalletFundingCheck(
            ok=True,
            required_wei=0,
            balance_wei=balance_wei,
            required_eth="0",
            balance_eth=format_eth_display(balance_wei),
            shortfall_wei=0,
            shortfall_eth="0",
        )

    balance_wei = read_native_balance_wei(wallet_address)
    shortfall_wei = max(0, amount - balance_wei)
    required_eth = format_eth_display(amount)
    balance_eth = format_eth_display(balance_wei)

    if balance_wei >= amount:
        return WalletFundingCheck(
            ok=True,
            required_wei=amount,
            balance_wei=balance_wei,
            required_eth=required_eth,
            balance_eth=balance_eth,
            shortfall_wei=0,
            shortfall_eth="0",
        )

    return WalletFundingCheck(
        ok=False,
        required_wei=amount,
        balance_wei=balance_wei,
        required_eth=required_eth,
        balance_eth=balance_eth,
        shortfall_wei=shortfall_wei,
        shortfall_eth=format_eth_display(shortfall_wei),
    )
