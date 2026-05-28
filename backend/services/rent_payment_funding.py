"""ETH funding checks for tenant monthly rent (RentDistribution.payRent)."""
from __future__ import annotations

from backend.services.wallet_funding import (
    WalletFundingCheck,
    WalletFundingError,
    check_wallet_covers_required_wei,
)


class RentPaymentFundingError(Exception):
    """Raised when monthly rent amount cannot be validated."""


def check_tenant_can_pay_monthly_rent(
    wallet_address: str,
    monthly_rent_wei: int,
    property_name: str,
) -> WalletFundingCheck:
    """Return whether the tenant wallet can cover one month of on-chain rent."""
    rent_wei = int(monthly_rent_wei)
    if rent_wei <= 0:
        raise RentPaymentFundingError("Monthly rent amount is not configured.")

    base = check_wallet_covers_required_wei(wallet_address, rent_wei)
    if base.ok:
        return base

    name = (property_name or "this property").strip()
    speak = (
        "You have insufficient balance in your wallet. "
        f"Monthly rent for {name} is {base.required_eth} ETH, "
        f"but your wallet balance is {base.balance_eth} ETH "
        f"(about {base.shortfall_eth} ETH short). "
        "Add ETH to your wallet and try again."
    )
    return WalletFundingCheck(
        ok=False,
        required_wei=base.required_wei,
        balance_wei=base.balance_wei,
        required_eth=base.required_eth,
        balance_eth=base.balance_eth,
        shortfall_wei=base.shortfall_wei,
        shortfall_eth=base.shortfall_eth,
        speak_to_user=speak,
        instruction=(
            "Tell the user they have insufficient balance in their wallet using "
            "`speak_to_user`. Do NOT open MetaMask or submit the pay-rent form."
        ),
    )
