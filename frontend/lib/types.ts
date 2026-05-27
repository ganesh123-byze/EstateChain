export type Role = "property_owner" | "investor" | "tenant";

export type AuthUser = {
  id?: number;
  wallet_address: string;
  role: Role | string;
  email?: string | null;
  kyc_status?: string;
  active?: boolean;
};

export type Property = {
  id: number;
  name: string;
  location: string;
  total_value: string | number;
  token_supply: string | number;
  token_symbol: string;
  owner_wallet?: string | null;
  /** Set by API for property_owner sessions — only true for listings this wallet created. */
  can_manage?: boolean;
  token_address?: string | null;
  nft_token_id?: number | null;
  nft_contract_address?: string | null;
  images?: string[];
  is_active?: boolean;
  token_sale_price_wei?: string | null;
  token_sale_price_eth?: string | null;
  monthly_rent_wei?: string | null;
  monthly_rent_eth?: string | null;
  tokens_sold: string | number;
  tokens_available: string | number;
  sold_percentage: string | number;
  rent_enabled?: boolean;
  current_cycle_paid?: boolean;
  can_pay_rent?: boolean;
  rent_cycle_label?: string;
  next_rent_due_at?: string | null;
  last_rent_paid_at?: string | null;
};

export type Transaction = {
  id: number;
  tx_hash: string;
  type: string;
  amount: string | number;
  timestamp: string;
  property_id?: number | null;
  block_number?: number | null;
  property_name?: string | null;
  wallet_address?: string | null;
  gas_fee?: string | null;
  amount_spent?: string | null;
  remaining_balance?: string | null;
  action_label: string;
  display_amount: string | number;
  amount_unit: string;
  status: string;
  description: string;
};

export type DashboardSummary = {
  total_portfolio_value: string | number;
  total_token_holdings: string | number;
  properties_loaded: number;
  avg_min_spend_per_token: string | number;
};

export type RentAnalytics = {
  total_rent_collected_wei: string;
  total_rent_distributed_wei: string;
  total_payments: number;
  total_distributions: number;
  active_rentals: number;
};

export type RentDistribution = {
  id: number;
  property_id: number;
  property_name?: string | null;
  total_rent_collected: string;
  total_distributed: string;
  investor_count: number;
  distribution_tx_hash: string;
  distributed_at: string;
};

export type RentPayment = {
  id: number;
  tenant_wallet: string;
  property_id: number;
  property_name?: string | null;
  amount_wei: string;
  amount_eth: string;
  tx_hash: string;
  block_number?: number | null;
  payment_date: string;
  payment_status: string;
};

export type PortfolioItem = {
  property_id: number;
  property_name: string;
  token_amount: string;
};

export type PortfolioResponse = {
  wallet_address: string;
  holdings: PortfolioItem[];
};

export type WalletBalanceToken = {
  category: string;
  property_id?: number | null;
  property_name?: string | null;
  symbol?: string | null;
  token_address?: string | null;
  decimals?: number;
  balance_base?: string;
  balance: string;
};

export type WalletBalances = {
  wallet_address: string;
  native: {
    symbol: string;
    balance_wei: string;
    balance: string;
  };
  tokens: WalletBalanceToken[];
};

export type InvestorYieldSummary = {
  wallet_address: string;
  total_earned_wei: string;
  total_earned_eth: string;
  total_claimable_wei?: string;
  total_claimable_eth?: string;
  total_claimed_wei?: string;
  total_claimed_eth?: string;
  total_payouts: number;
  properties_earning: number;
};

export type InvestorDistribution = {
  property_id: number;
  property_name?: string | null;
  total_earned_wei: string;
  total_earned_eth: string;
  payment_count: number;
  current_ownership: string | number;
};

export type InvestorPayout = {
  id: number;
  investor_wallet: string;
  property_id: number;
  property_name?: string | null;
  ownership_percentage: string | number;
  payout_amount_wei: string;
  payout_amount_eth: string;
  tx_hash: string;
  distributed_at: string;
  claim_status: string;
  claim_tx_hash?: string | null;
  claimed_at?: string | null;
};

export type ClaimableRewardProperty = {
  property_id: number;
  property_name?: string | null;
  claimable_amount_wei: string;
  claimable_amount_eth: string;
  pending_payouts: number;
  last_distributed_at?: string | null;
};

export type ClaimableRewardsSummary = {
  wallet_address: string;
  total_claimable_wei: string;
  total_claimable_eth: string;
  total_claimed_wei: string;
  total_claimed_eth: string;
  properties: ClaimableRewardProperty[];
};

export type RewardClaimHistory = {
  property_id: number;
  property_name?: string | null;
  claim_tx_hash: string;
  claimed_amount_wei: string;
  claimed_amount_eth: string;
  payout_count: number;
  claimed_at: string;
};

export type InvestmentPrepareResponse = {
  investment_id: number;
  property_id: number;
  investor_wallet: string;
  token_amount: string | number;
  eth_amount: string | number;
  eth_amount_wei: string;
  recipient_address: string;
  chain_id: number;
};

export type InvestmentRead = {
  id: number;
  property_id: number;
  investor_wallet: string;
  token_amount: string | number;
  eth_amount: string | number;
  eth_amount_wei: string;
  deposit_tx_hash?: string | null;
  status: string;
  created_at: string;
};

export type ClaimRewardsPrepareResponse = {
  property_id: number;
  property_name: string;
  investor_wallet: string;
  claimable_amount_wei: string;
  claimable_amount_eth: string;
  rent_contract_address: string;
  calldata: string;
  chain_id: number;
};

export type ClaimRewardsConfirmResponse = {
  status: string;
  property_id: number;
  investor_wallet: string;
  claim_tx_hash: string;
  claimed_amount_wei: string;
  claimed_amount_eth: string;
  claimed_rows: number;
};

export type UserRecord = {
  id: number;
  wallet_address: string;
  email?: string | null;
  kyc_status: string;
};

export type TenantRental = {
  id: number;
  tenant_id: number;
  property_id: number;
  property_name?: string | null;
  location?: string | null;
  rental_start_date?: string | null;
  rental_end_date?: string | null;
  status: string;
  created_at?: string | null;
  current_cycle_paid?: boolean;
  can_pay_rent?: boolean;
  rent_cycle_label?: string;
  next_rent_due_at?: string | null;
  last_rent_paid_at?: string | null;
};

export type PayRentPrepareResponse = {
  property_id: number;
  property_name: string;
  monthly_rent_wei: string;
  monthly_rent_eth: string;
  rent_contract_address: string;
  calldata: string;
  chain_id: number;
  rent_month: number;
  rent_year: number;
  rent_cycle_label: string;
  current_cycle_paid?: boolean;
  can_pay_rent?: boolean;
  next_rent_due_at?: string | null;
  last_rent_paid_at?: string | null;
};

export type PayRentConfirmRequest = {
  tx_hash: string;
  tenant_wallet: string;
};

export type PayRentConfirmResponse = {
  status: string;
  rent_payment_id: number;
  distribution_id?: number | null;
  amount_wei: string;
  amount_eth: string;
  investors_paid: number;
  total_distributed_wei?: string;
  tx_hash: string;
};

export type RentDistributionPreview = {
  property_id: number;
  property_name: string;
  monthly_rent_wei: string;
  monthly_rent_eth: string;
  investor_count: number;
  breakdown: Array<{
    investor: string;
    payout_eth: string;
    ownership_pct: string | number;
  }>;
};

export type AutonomousIntelEvent = {
  id: number;
  agent: string;
  severity: string;
  category: string;
  title: string;
  body: string;
  metadata: Record<string, unknown>;
  draft_payload?: Record<string, unknown> | null;
  read_at?: string | null;
  created_at?: string | null;
  unread: boolean;
};

