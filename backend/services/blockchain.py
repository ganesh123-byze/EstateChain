from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from eth_utils import event_abi_to_log_topic
from web3 import Web3

from backend.config.settings import CHAIN_ID, DEPLOYER_PRIVATE_KEY, RENT_TOKEN_DECIMALS, SEPOLIA_RPC_URL, TOKEN_DECIMALS, WEB3_PROVIDER_URI
from backend.services.contract_loader import get_contract_address, load_artifact
import time

LOGGER = logging.getLogger(__name__)

DEFAULT_GAS = 5_000_000
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

_web3: Web3 | None = None
_web3_uri: str | None = None


def _provider_uri() -> str:
    return (SEPOLIA_RPC_URL or WEB3_PROVIDER_URI or "").strip()


def get_web3() -> Web3:
    global _web3, _web3_uri
    uri = _provider_uri()
    if not uri:
        raise RuntimeError("SEPOLIA_RPC_URL or WEB3_PROVIDER_URI is not set")
    if _web3 is None or _web3_uri != uri:
        _web3_uri = uri
        _web3 = Web3(Web3.HTTPProvider(uri))
    return _web3


def rpc_is_healthy() -> bool:
    """True when Sepolia RPC responds; more reliable than Web3.is_connected() alone."""
    try:
        web3 = get_web3()
        if web3.is_connected():
            return True
        web3.eth.block_number  # noqa: B018 — probe RPC
        return True
    except Exception:
        return False


def get_deployer_account():
    if not DEPLOYER_PRIVATE_KEY:
        raise RuntimeError(
            "DEPLOYER_PRIVATE_KEY is not set in .env. "
            "Add the Sepolia private key for the platform deployer wallet "
            "(must own PropertyNFT / RentDistribution and hold Sepolia ETH for gas)."
        )
    return _web3.eth.account.from_key(DEPLOYER_PRIVATE_KEY)


def get_deployer_address() -> str:
    return get_deployer_account().address


def platform_deployer_mismatch() -> dict | None:
    """Return mismatch metadata when DEPLOYER_PRIVATE_KEY is not the on-file platform owner."""
    if not DEPLOYER_PRIVATE_KEY:
        return {
            "code": "MISSING_DEPLOYER_KEY",
            "message": (
                "DEPLOYER_PRIVATE_KEY is not set. Token deployment and rent registration require "
                "the wallet that owns PropertyNFT and RentDistribution on Sepolia."
            ),
        }
    try:
        current = get_deployer_address()
    except Exception:
        return None
    from backend.config.settings import load_contract_addresses

    recorded = str(load_contract_addresses().get("Deployer") or "").strip()
    if not recorded:
        return None
    if current.lower() == recorded.lower():
        return None
    return {
        "code": "DEPLOYER_CONTRACT_MISMATCH",
        "current_deployer": current,
        "contract_owner": recorded,
        "message": (
            f"DEPLOYER_PRIVATE_KEY wallet ({current}) does not match the owner recorded in "
            f"contract-addresses.json ({recorded}). Rent sync and shared-contract admin calls "
            f"will revert. Run `npm run deploy:sepolia` with the intended wallet, update "
            f"INDEXER_START_BLOCK to the new DeployBlock, and restart the API."
        ),
    }


def to_base_units(amount: Decimal | str | int, decimals: int) -> int:
    # Use Decimal arithmetic to avoid floating point precision loss
    return int(Decimal(amount) * (Decimal(10) ** Decimal(decimals)))


def from_base_units(amount: int, decimals: int) -> Decimal:
    return Decimal(amount) / (Decimal(10) ** decimals)


def to_wei(amount: Decimal) -> int:
    return int(Decimal(amount) * (Decimal(10) ** 18))


def from_wei(amount_wei: int) -> Decimal:
    return Decimal(amount_wei) / (Decimal(10) ** 18)


def _get_dynamic_fee_fields() -> dict:
    latest_block = _web3.eth.get_block("latest")
    base_fee = int(latest_block.get("baseFeePerGas", 0) or 0)
    try:
        priority_fee = int(_web3.eth.max_priority_fee)
    except Exception:
        priority_fee = int(_web3.to_wei(1, "gwei"))
    max_fee = base_fee * 2 + priority_fee
    return {
        "type": 2,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority_fee
    }


def _apply_fee_fields(tx: dict) -> None:
    has_dynamic = tx.get("type") == 2 or "maxFeePerGas" in tx or "maxPriorityFeePerGas" in tx
    latest_block = _web3.eth.get_block("latest")
    supports_eip1559 = latest_block.get("baseFeePerGas") is not None

    if has_dynamic or supports_eip1559:
        fields = _get_dynamic_fee_fields()
        tx.setdefault("type", fields["type"])
        tx.setdefault("maxFeePerGas", fields["maxFeePerGas"])
        tx.setdefault("maxPriorityFeePerGas", fields["maxPriorityFeePerGas"])
        tx.pop("gasPrice", None)
        return

    tx.setdefault("gasPrice", _web3.eth.gas_price)


def build_and_send(tx: dict) -> dict:
    return build_and_send_with_retry(tx, max_attempts=3, bump_pct=30)


def build_and_send_with_retry(tx: dict, max_attempts: int = 3, bump_pct: int = 30) -> dict:
    """Send a transaction with retry + fee bump on transient errors (already known, underpriced, etc.)."""
    account = get_deployer_account()
    tx.setdefault("from", account.address)
    tx.setdefault("chainId", CHAIN_ID)
    tx.setdefault("gas", DEFAULT_GAS)
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            # Fresh nonce on each attempt (to handle pending txs)
            tx["nonce"] = _web3.eth.get_transaction_count(account.address, 'pending')
            _apply_fee_fields(tx)
            # On retry, bump fees
            if attempt > 1:
                try:
                    if "maxFeePerGas" in tx:
                        tx["maxFeePerGas"] = int(int(tx["maxFeePerGas"]) * (100 + bump_pct) / 100)
                    if "maxPriorityFeePerGas" in tx:
                        tx["maxPriorityFeePerGas"] = int(int(tx["maxPriorityFeePerGas"]) * (100 + bump_pct) / 100)
                    if "gasPrice" in tx:
                        tx["gasPrice"] = int(int(tx["gasPrice"]) * (100 + bump_pct) / 100)
                except Exception:
                    pass
            signed = account.sign_transaction(tx)
            raw_tx = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
            if raw_tx is None:
                raise RuntimeError("Signed transaction missing raw payload")
            tx_hash = _web3.eth.send_raw_transaction(raw_tx)
            receipt = _web3.eth.wait_for_transaction_receipt(tx_hash)
            return receipt
        except Exception as e:
            last_exc = e
            if attempt == max_attempts:
                raise
            time.sleep(1)
            continue
    if last_exc:
        raise last_exc


def deploy_contract(contract_name: str, constructor_args: list[Any]) -> tuple[str, dict]:
    abi, bytecode = load_artifact(contract_name)
    contract = _web3.eth.contract(abi=abi, bytecode=bytecode)
    tx = contract.constructor(*constructor_args).build_transaction({"from": get_deployer_account().address})
    receipt = build_and_send(tx)
    return receipt.contractAddress, receipt


def get_contract(contract_name: str, address: str):
    abi, _ = load_artifact(contract_name)
    return _web3.eth.contract(address=address, abi=abi)


def decode_contract_events_from_receipt(contract, event_name: str, receipt: dict) -> list[Any]:
    """Decode logs for one event from this contract address only.

    ``Contract.events.X().process_receipt(receipt)`` walks every log in the receipt
    and emits eth-utils ``UserWarning: MismatchedABI`` for non-matching entries.
    Rent ``payRent`` transactions emit both ``InvestorPaid`` and ``RewardsAccrued``
    (same parameter layout, different signatures), which produces noisy warnings
    and confusing production logs despite successful decoding.
    """
    event_abi = next(
        (x for x in contract.abi if x.get("type") == "event" and x.get("name") == event_name),
        None,
    )
    if event_abi is None:
        return []
    target_topic_hex = Web3.to_hex(event_abi_to_log_topic(event_abi)).lower()
    contract_addr_lower = Web3.to_checksum_address(contract.address).lower()
    event_proc = getattr(contract.events, event_name)()
    decoded: list[Any] = []
    for log in receipt.get("logs", []) or []:
        log_addr = log.get("address")
        if not log_addr:
            continue
        if Web3.to_checksum_address(log_addr).lower() != contract_addr_lower:
            continue
        topics = log.get("topics") or []
        if not topics:
            continue
        if Web3.to_hex(topics[0]).lower() != target_topic_hex:
            continue
        try:
            decoded.append(event_proc.process_log(log))
        except Exception as exc:
            LOGGER.warning(
                "decode_contract_events_from_receipt event=%s log_index=%s error=%s",
                event_name,
                log.get("logIndex"),
                exc,
            )
    return decoded


def is_contract(address: str) -> bool:
    code = _web3.eth.get_code(address)
    return bool(code and code != b"\x00" and code != b"0x")


def get_native_balance(address: str) -> int:
    return int(_web3.eth.get_balance(address))


def get_erc20_balance(contract, address: str) -> int:
    try:
        if not is_contract(contract.address):
            return 0
        return int(contract.functions.balanceOf(address).call())
    except Exception:
        return 0


def get_escrow_address() -> str:
    escrow_address = get_contract_address("Escrow")
    if not escrow_address:
        raise RuntimeError("Escrow address not found. Deploy contracts first.")
    return escrow_address


def get_escrow_contract():
    escrow_address = get_escrow_address()
    return get_contract("Escrow", escrow_address)


def create_escrow_deal(payer: str, payee: str, amount_wei: int) -> tuple[int, dict]:
    contract = get_escrow_contract()
    receipt = send_contract_tx(contract, "createDeal", [payer, payee, int(amount_wei)])
    events = decode_contract_events_from_receipt(contract, "DealCreated", receipt)
    deal_id = int(events[0]["args"]["dealId"]) if events else 0
    return deal_id, receipt


def encode_escrow_deposit(deal_id: int) -> str:
    contract = get_escrow_contract()
    return contract.functions.deposit(int(deal_id))._encode_transaction_data()


def get_transaction(tx_hash: str):
    return _web3.eth.get_transaction(tx_hash)


def get_transaction_receipt(tx_hash: str):
    return _web3.eth.get_transaction_receipt(tx_hash)


def wait_for_transaction_receipt(tx_hash: str, timeout: int = 120, poll_latency: int = 1):
    return _web3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout, poll_latency=poll_latency)


def send_contract_tx(contract, function_name: str, args: list[Any]) -> dict:
    fn = getattr(contract.functions, function_name)(*args)
    tx = fn.build_transaction({"from": get_deployer_account().address})
    return build_and_send(tx)


def send_contract_tx_once(contract, function_name: str, args: list[Any]) -> dict:
    """Single-attempt contract tx for latency-sensitive setup paths (e.g. create-property rent sync)."""
    fn = getattr(contract.functions, function_name)(*args)
    tx = fn.build_transaction({"from": get_deployer_account().address})
    return build_and_send_with_retry(tx, max_attempts=1, bump_pct=0)


def send_contract_tx_with_retry(contract, function_name: str, args: list[Any], max_attempts: int = 3, bump_pct: int = 30) -> dict:
    """Send a contract transaction with simple retry + fee bump on failure.

    Attempts to replace stuck transactions by increasing fee fields (EIP-1559 or legacy gasPrice).
    """
    account = get_deployer_account()
    fn = getattr(contract.functions, function_name)(*args)
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            tx = fn.build_transaction({"from": account.address})
            tx.setdefault("nonce", _web3.eth.get_transaction_count(account.address, 'pending'))
            tx.setdefault("chainId", CHAIN_ID)
            tx.setdefault("gas", DEFAULT_GAS)
            # Populate fee fields according to chain
            _apply_fee_fields(tx)

            # On retry attempts, bump numeric fee fields by bump_pct
            if attempt > 1:
                try:
                    if "maxFeePerGas" in tx:
                        tx["maxFeePerGas"] = int(int(tx["maxFeePerGas"]) * (100 + bump_pct) / 100)
                    if "maxPriorityFeePerGas" in tx:
                        tx["maxPriorityFeePerGas"] = int(int(tx["maxPriorityFeePerGas"]) * (100 + bump_pct) / 100)
                    if "gasPrice" in tx:
                        tx["gasPrice"] = int(int(tx["gasPrice"]) * (100 + bump_pct) / 100)
                except Exception:
                    # If type conversion fails, ignore and proceed with original fields
                    pass

            # sign and send
            account_local = account
            signed = account_local.sign_transaction(tx)
            raw_tx = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
            if raw_tx is None:
                raise RuntimeError("Signed transaction missing raw payload")
            tx_hash = _web3.eth.send_raw_transaction(raw_tx)
            receipt = _web3.eth.wait_for_transaction_receipt(tx_hash)
            return receipt
        except Exception as e:
            last_exc = e
            # If this was the last attempt, re-raise
            if attempt == max_attempts:
                raise
            # brief sleep to let mempool reset
            time.sleep(1)
            continue
    if last_exc:
        raise last_exc


def mint_property_nft(to_address: str, token_uri: str) -> tuple[int, dict]:
    property_nft_address = get_contract_address("PropertyNFT")
    if not property_nft_address:
        raise RuntimeError("PropertyNFT address not found. Deploy contracts first.")
    contract = get_contract("PropertyNFT", property_nft_address)
    receipt = send_contract_tx(contract, "mintProperty", [to_address, token_uri])
    events = decode_contract_events_from_receipt(contract, "Transfer", receipt)
    token_id = int(events[0]["args"]["tokenId"]) if events else 0
    return token_id, receipt


def deploy_security_token(property_id: int, name: str, symbol: str, sale_price_per_token_wei: int) -> tuple[str, dict]:
    return deploy_contract("SecurityToken", [int(property_id), name, symbol, int(sale_price_per_token_wei)])


def set_whitelist(security_token_address: str, wallet_address: str, approved: bool) -> dict:
    token = get_contract("SecurityToken", security_token_address)
    return send_contract_tx(token, "setWhitelisted", [wallet_address, approved])


def mint_security_tokens(security_token_address: str, to_address: str, amount: Decimal) -> dict:
    token = get_contract("SecurityToken", security_token_address)
    amount_base = to_base_units(amount, TOKEN_DECIMALS)
    return send_contract_tx(token, "mint", [to_address, amount_base])


def transfer_security_tokens(security_token_address: str, to_address: str, amount: Decimal) -> dict:
    token = get_contract("SecurityToken", security_token_address)
    amount_base = to_base_units(amount, TOKEN_DECIMALS)
    return send_contract_tx(token, "transfer", [to_address, amount_base])


def get_rent_distribution_address() -> str:
    addr = get_contract_address("RentDistribution")
    if not addr:
        raise RuntimeError("RentDistribution address not found. Deploy contracts first.")
    return addr


def get_rent_distribution_contract():
    return get_contract("RentDistribution", get_rent_distribution_address())


def register_property_for_rent(
    property_id: int, token_address: str, *, fast: bool = False
) -> dict:
    contract = get_rent_distribution_contract()
    sender = send_contract_tx_once if fast else send_contract_tx
    return sender(contract, "registerProperty", [int(property_id), token_address])


def set_monthly_rent(property_id: int, rent_wei: int, *, use_retry: bool = True) -> dict:
    contract = get_rent_distribution_contract()
    args = [int(property_id), int(rent_wei)]
    if use_retry:
        return send_contract_tx_with_retry(contract, "setMonthlyRent", args)
    return send_contract_tx(contract, "setMonthlyRent", args)


def add_investor_to_rent(property_id: int, investor_address: str) -> dict:
    contract = get_rent_distribution_contract()
    return send_contract_tx(contract, "addInvestor", [int(property_id), investor_address])


def add_investors_to_rent(property_id: int, investor_addresses: list[str]) -> dict:
    contract = get_rent_distribution_contract()
    return send_contract_tx(contract, "addInvestors", [int(property_id), investor_addresses])


def get_rent_property_info(property_id: int) -> dict:
    contract = get_rent_distribution_contract()
    token_addr, rent_wei, active, inv_count = contract.functions.getPropertyInfo(int(property_id)).call()
    return {
        "token_contract": token_addr,
        "monthly_rent_wei": int(rent_wei),
        "active": active,
        "investor_count": int(inv_count)
    }


def get_rent_investors(property_id: int) -> list[str]:
    contract = get_rent_distribution_contract()
    return list(contract.functions.getInvestors(int(property_id)).call())


def rent_share_pct_from_payout(payout_wei: int, rent_wei: int) -> float:
    """Human-readable share of rent for this payout (matches on-chain wei division).

    Solidity uses integer basis points ``(balance * 10000) / supply``, which truncates to 0
    for small holders while ``(rent * balance) / supply`` can still be positive — so never
    derive UI percentages from bps alone.
    """
    if rent_wei <= 0 or payout_wei <= 0:
        return 0.0
    return float((Decimal(int(payout_wei)) / Decimal(int(rent_wei))) * Decimal(100))


def calculate_rent_distribution(property_id: int, rent_wei: int) -> list[dict]:
    contract = get_rent_distribution_contract()
    investors, payouts, bps = contract.functions.calculateDistribution(int(property_id), int(rent_wei)).call()
    result = []
    for i in range(len(investors)):
        pw = int(payouts[i])
        if pw > 0:
            result.append({
                "investor": investors[i],
                "payout_wei": pw,
                "payout_eth": str(from_wei(pw)),
                "ownership_bps": int(bps[i]),
                "ownership_pct": round(rent_share_pct_from_payout(pw, rent_wei), 6),
            })
    return result


def _hex_calldata_for_api(encoded: Any) -> str:
    """Normalize ABI-encoded call data to ``0x…`` hex for JSON clients (ethers.js / MetaMask).

    ``_encode_transaction_data()`` already returns a ``HexStr`` (str). Older code wrapped that
    in ``Web3.to_hex(...)`` which only accepts bytes/int/bool — raising ``TypeError`` for str
    and 500-ing ``/tenant/pay-rent/prepare/{id}``. Accept str / bytes / int safely.
    """
    if encoded is None:
        return "0x"
    if isinstance(encoded, str):
        value = encoded.strip()
        if not value:
            return "0x"
        return value if value.startswith("0x") else f"0x{value}"
    hx = Web3.to_hex(encoded)
    if isinstance(hx, str) and hx.startswith("0x"):
        return hx
    return f"0x{hx}" if hx else "0x"


def encode_pay_rent(property_id: int) -> str:
    contract = get_rent_distribution_contract()
    return _hex_calldata_for_api(contract.functions.payRent(int(property_id))._encode_transaction_data())


def encode_claim_rewards(property_id: int) -> str:
    contract = get_rent_distribution_contract()
    return _hex_calldata_for_api(contract.functions.claimRewards(int(property_id))._encode_transaction_data())


def get_claimable_rewards(wallet_address: str) -> int:
    contract = get_rent_distribution_contract()
    return int(contract.functions.claimableRewards(wallet_address).call())


def get_property_claimable_rewards(property_id: int, wallet_address: str) -> int:
    contract = get_rent_distribution_contract()
    return int(contract.functions.propertyClaimableRewards(int(property_id), wallet_address).call())


def get_total_claimed_rewards(wallet_address: str) -> int:
    contract = get_rent_distribution_contract()
    return int(contract.functions.totalClaimedRewards(wallet_address).call())


def get_property_claimed_rewards(property_id: int, wallet_address: str) -> int:
    contract = get_rent_distribution_contract()
    return int(contract.functions.propertyClaimedRewards(int(property_id), wallet_address).call())


# `distribute_rent` (MockUSDC + RentalYieldDistributor accumulator) retired in Phase A.
# Rent flow is now: tenant.payRent() -> RentDistribution singleton -> pushes ETH to investors.
