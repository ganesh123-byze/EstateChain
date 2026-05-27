from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_PROPERTY_IMAGES = 8
MAX_PROPERTY_IMAGE_CHARS = 2_000_000


class PropertyCreate(BaseModel):
    name: str = Field(..., max_length=255)
    location: str = Field(..., max_length=255)
    total_value: Decimal
    token_supply: Decimal
    token_symbol: str = Field(..., max_length=12)
    # Backward compatible: current admin UI sends an auto-calculated value.
    token_sale_price_eth: Optional[Decimal] = None
    monthly_rent_eth: Optional[Decimal] = None
    images: list[str] = Field(default_factory=list, max_length=MAX_PROPERTY_IMAGES)

    @field_validator("images")
    @classmethod
    def validate_images(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value or []:
            image = str(raw or "").strip()
            if not image:
                continue
            if len(image) > MAX_PROPERTY_IMAGE_CHARS:
                raise ValueError("Each property image must be under 2 MB encoded.")
            if not (
                image.startswith("data:image/")
                or image.startswith("https://")
                or image.startswith("http://localhost")
                or image.startswith("http://127.0.0.1")
            ):
                raise ValueError("Property images must be data image URLs or trusted URLs.")
            cleaned.append(image)
        return cleaned[:MAX_PROPERTY_IMAGES]


class PropertyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: str
    total_value: Decimal
    token_supply: Decimal
    token_symbol: str
    owner_wallet: Optional[str] = None
    token_address: Optional[str] = None
    nft_token_id: Optional[int] = None
    nft_contract_address: Optional[str] = None
    images: list[str] = Field(default_factory=list)
    is_active: bool = True
    token_sale_price_wei: Optional[str] = None
    token_sale_price_eth: Optional[str] = None
    monthly_rent_wei: Optional[str] = None
    monthly_rent_eth: Optional[str] = None
    tokens_sold: Decimal = Decimal("0")
    tokens_available: Decimal = Decimal("0")
    sold_percentage: Decimal = Decimal("0")
    can_manage: bool = False


class MintNFTRequest(BaseModel):
    to_address: str
    token_uri: str


class IssueTokensRequest(BaseModel):
    to_address: str
    amount: Decimal
    email: Optional[str] = None


class TransferTokensRequest(BaseModel):
    to_address: str
    amount: Decimal


# ── New simplified investment schemas ──

class InvestmentCreateRequest(BaseModel):
    property_id: int
    investor_wallet: str
    token_amount: Decimal
    eth_amount: Optional[Decimal] = None  # auto-calculated if omitted


class InvestmentPrepareResponse(BaseModel):
    investment_id: int
    property_id: int
    investor_wallet: str
    token_amount: Decimal
    eth_amount: Decimal
    eth_amount_wei: str
    recipient_address: str  # SecurityToken contract — investor calls invest() on this address
    chain_id: int


class InvestmentConfirmRequest(BaseModel):
    tx_hash: str


class InvestmentRead(BaseModel):
    id: int
    property_id: int
    investor_wallet: str
    token_amount: Decimal
    eth_amount: Decimal
    eth_amount_wei: str
    escrow_deal_id: int | None = None
    deposit_tx_hash: str | None = None
    status: str
    created_at: str


class PortfolioItem(BaseModel):
    property_id: int
    property_name: str
    token_amount: Decimal


class PortfolioResponse(BaseModel):
    wallet_address: str
    holdings: list[PortfolioItem]


class TransactionRead(BaseModel):
    id: int
    tx_hash: str
    type: str
    amount: Decimal
    timestamp: str
    property_id: Optional[int] = None
    block_number: Optional[int] = None
    property_name: Optional[str] = None
    wallet_address: Optional[str] = None
    gas_fee: Optional[str] = None
    amount_spent: Optional[str] = None
    remaining_balance: Optional[str] = None
    action_label: str
    display_amount: Decimal
    amount_unit: str
    status: str
    description: str


class UserRead(BaseModel):
    id: int
    wallet_address: str
    email: Optional[str] = None
    kyc_status: str


class DashboardSummary(BaseModel):
    total_portfolio_value: Decimal
    total_token_holdings: Decimal
    properties_loaded: int
    avg_min_spend_per_token: Decimal


# ── Rental Distribution Schemas ──

class SetMonthlyRentRequest(BaseModel):
    monthly_rent_eth: Decimal


class PayRentPrepareResponse(BaseModel):
    property_id: int
    property_name: str
    monthly_rent_wei: str
    monthly_rent_eth: str
    rent_contract_address: str
    calldata: str
    chain_id: int
    rent_month: int
    rent_year: int
    rent_cycle_label: str
    current_cycle_paid: bool = False
    can_pay_rent: bool = True
    next_rent_due_at: Optional[str] = None
    last_rent_paid_at: Optional[str] = None


class PayRentConfirmRequest(BaseModel):
    tx_hash: str
    tenant_wallet: str


class ClaimRewardsPrepareRequest(BaseModel):
    property_id: int
    investor_wallet: str


class ClaimRewardsPrepareResponse(BaseModel):
    property_id: int
    property_name: str
    investor_wallet: str
    claimable_amount_wei: str
    claimable_amount_eth: str
    rent_contract_address: str
    calldata: str
    chain_id: int


class ClaimRewardsConfirmRequest(BaseModel):
    property_id: int
    investor_wallet: str
    tx_hash: str


class ClaimRewardsConfirmResponse(BaseModel):
    status: str
    property_id: int
    investor_wallet: str
    claim_tx_hash: str
    claimed_amount_wei: str
    claimed_amount_eth: str
    claimed_rows: int


class RentPaymentRead(BaseModel):
    id: int
    tenant_wallet: str
    property_id: int
    property_name: Optional[str] = None
    amount_wei: str
    amount_eth: str
    tx_hash: str
    block_number: Optional[int] = None
    payment_date: str
    payment_status: str
    rent_month: Optional[int] = None
    rent_year: Optional[int] = None


class RentDistributionRead(BaseModel):
    id: int
    property_id: int
    property_name: Optional[str] = None
    total_rent_collected: str
    total_distributed: str
    investor_count: int
    distribution_tx_hash: str
    distributed_at: str


class InvestorPayoutRead(BaseModel):
    id: int
    investor_wallet: str
    property_id: int
    property_name: Optional[str] = None
    ownership_percentage: Decimal
    payout_amount_wei: str
    payout_amount_eth: str
    tx_hash: str
    distributed_at: str
    claim_status: str = "claimable"
    claim_tx_hash: Optional[str] = None
    claimed_at: Optional[str] = None


class RentAnalytics(BaseModel):
    total_rent_collected_wei: str
    total_rent_distributed_wei: str
    total_payments: int
    total_distributions: int
    active_rentals: int


class ClaimableRewardPropertyRead(BaseModel):
    property_id: int
    property_name: Optional[str] = None
    claimable_amount_wei: str
    claimable_amount_eth: str
    pending_payouts: int
    last_distributed_at: Optional[str] = None


class ClaimableRewardsSummaryRead(BaseModel):
    wallet_address: str
    total_claimable_wei: str
    total_claimable_eth: str
    total_claimed_wei: str
    total_claimed_eth: str
    properties: list[ClaimableRewardPropertyRead]


class RewardClaimHistoryRead(BaseModel):
    property_id: int
    property_name: Optional[str] = None
    claim_tx_hash: str
    claimed_amount_wei: str
    claimed_amount_eth: str
    payout_count: int
    claimed_at: str
