"""Shared request-handler helpers for the backend API routers.

Kept in one module so every sub-router (properties, investments, rent, …)
reaches for the same normalization / locking / formatting primitives.
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException

from backend.api.schemas import PropertyCreate
from backend.config.settings import RENT_TOKEN_DECIMALS, TOKEN_DECIMALS
from backend.services.blockchain import (
    add_investors_to_rent,
    decode_contract_events_from_receipt,
    deploy_security_token,
    from_wei,
    get_contract,
    get_rent_investors,
    get_rent_property_info,
    get_transaction,
    get_transaction_receipt,
    get_web3,
    mint_security_tokens,
    register_property_for_rent,
    set_monthly_rent,
    to_base_units,
)


# ── Property row fetching ─────────────────────────────────────────────

def fetch_property(cursor, property_id: int) -> dict | None:
    cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
    return cursor.fetchone()


def _normalize_property_images(raw: object) -> list[str]:
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    return []


def lock_property(cursor, property_id: int) -> dict | None:
    """Fetch a property row with a row-level lock (``SELECT ... FOR UPDATE``).

    Serializes concurrent mutating operations (deploy, set-rent, issue-tokens,
    prepare_investment) for the same property.
    """
    cursor.execute("SELECT * FROM properties WHERE id = %s FOR UPDATE", (property_id,))
    return cursor.fetchone()


def find_existing_property(
    cursor,
    payload: PropertyCreate,
    token_price_wei: str,
    monthly_rent_wei: str | None,
    owner_wallet: str | None = None,
) -> dict | None:
    cursor.execute(
        "SELECT * FROM properties WHERE name = %s AND location = %s AND total_value = %s "
        "AND token_supply = %s AND token_symbol = %s "
        "AND COALESCE(token_price_base, '') = %s "
        "AND COALESCE(monthly_rent_wei, '') = COALESCE(%s, '') "
        "AND COALESCE(owner_wallet, '') = COALESCE(%s, '') "
        "AND COALESCE(is_active, TRUE) = TRUE "
        "ORDER BY id ASC LIMIT 1",
        (
            payload.name,
            payload.location,
            payload.total_value,
            payload.token_supply,
            payload.token_symbol,
            token_price_wei,
            monthly_rent_wei,
            owner_wallet,
        ),
    )
    return cursor.fetchone()


# ── Enrichment / formatting ───────────────────────────────────────────

def enrich_property_with_supply(cursor, property_item: dict) -> dict:
    if not property_item:
        return property_item

    property_id = int(property_item["id"])
    cursor.execute(
        "SELECT COALESCE(SUM(CASE WHEN token_amount > 0 THEN token_amount ELSE 0 END), 0) AS total_minted_base "
        "FROM token_ownerships WHERE property_id = %s",
        (property_id,),
    )
    total_minted_base = Decimal(cursor.fetchone()["total_minted_base"] or 0)
    base_divisor = Decimal(10) ** TOKEN_DECIMALS
    tokens_sold = (total_minted_base / base_divisor) if base_divisor else Decimal("0")
    token_supply = Decimal(property_item.get("token_supply") or 0)
    tokens_available = token_supply - tokens_sold
    if tokens_available < 0:
        tokens_available = Decimal("0")
    sold_percentage = (
        (tokens_sold / token_supply * Decimal(100)) if token_supply > 0 else Decimal("0")
    )

    property_item["tokens_sold"] = tokens_sold
    property_item["tokens_available"] = tokens_available
    property_item["sold_percentage"] = sold_percentage
    property_item["images"] = _normalize_property_images(property_item.get("images"))
    property_item["is_active"] = bool(property_item.get("is_active", True))
    owner_wallet = property_item.get("owner_wallet")
    if isinstance(owner_wallet, str) and owner_wallet:
        property_item["owner_wallet"] = owner_wallet.lower()

    # Sale price (wei + ETH)
    price_wei_raw = property_item.get("token_price_base")
    try:
        price_wei = int(price_wei_raw) if price_wei_raw not in (None, "", "0") else 0
    except (TypeError, ValueError):
        price_wei = 0
    property_item["token_sale_price_wei"] = str(price_wei)
    property_item["token_sale_price_eth"] = str(from_wei(price_wei)) if price_wei else "0"

    # Monthly rent (wei + ETH)
    rent_wei_raw = property_item.get("monthly_rent_wei")
    try:
        rent_wei = int(rent_wei_raw) if rent_wei_raw not in (None, "", "0") else 0
    except (TypeError, ValueError):
        rent_wei = 0
    property_item["monthly_rent_wei"] = str(rent_wei)
    property_item["monthly_rent_eth"] = str(from_wei(rent_wei)) if rent_wei else "0"
    return property_item


def get_total_minted_base(cursor, property_id: int) -> Decimal:
    cursor.execute(
        "SELECT COALESCE(SUM(CASE WHEN token_amount > 0 THEN token_amount ELSE 0 END), 0) AS total_minted_base "
        "FROM token_ownerships WHERE property_id = %s",
        (property_id,),
    )
    return Decimal(cursor.fetchone()["total_minted_base"] or 0)


# ── Token contract ────────────────────────────────────────────────────

def is_investable_token_contract(security_token_address: str) -> bool:
    if not security_token_address:
        return False
    try:
        contract = get_contract("SecurityToken", security_token_address)
        contract.functions.propertyId().call()
        contract.functions.salePricePerTokenWei().call()
        return True
    except Exception:
        return False


def require_property_token(property_item: dict) -> None:
    """Raise 400 unless the property has a deployed, investable SecurityToken.

    Deployment is an explicit admin action via POST /properties/{id}/deploy-token.
    """
    token_address = property_item.get("token_address")
    if not token_address:
        raise HTTPException(
            status_code=400,
            detail=(
                "Property token contract not deployed yet. "
                "Admin must call POST /properties/{id}/deploy-token first."
            ),
        )
    if not is_investable_token_contract(token_address):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Token contract {token_address} is not responding as a SecurityToken. "
                "Check the deployment."
            ),
        )


def ensure_security_token_sale_inventory(property_item: dict) -> None:
    """Mint the full DB token supply onto the SecurityToken contract when chain supply is still zero.

    Primary sale pulls from ``balanceOf(tokenContract)``. If deployment succeeded but the initial
    ``mint`` never landed (bad gas estimate on a manual wallet tx, transient RPC failure, etc.),
    ``totalSupply()`` stays 0 while ``token_address`` is already stored — re-clicking Deploy Token
    used to no-op. This repair only runs when ``totalSupply() == 0`` so it never doubles issuance
    after real investors hold tokens.
    """
    token_address = property_item.get("token_address")
    if not token_address or not is_investable_token_contract(token_address):
        return
    token = get_contract("SecurityToken", token_address)
    total = int(token.functions.totalSupply().call())
    if total > 0:
        return
    mint_security_tokens(
        token_address,
        token_address,
        Decimal(property_item["token_supply"]),
    )


def property_needs_token_deployment(property_item: dict) -> bool:
    """True when the property row exists but its SecurityToken is not on-chain yet."""
    token_address = property_item.get("token_address")
    if not token_address:
        return True
    return not is_investable_token_contract(token_address)


def deploy_property_token(cursor, property_item: dict, property_id: int) -> dict:
    """Explicit, admin-initiated SecurityToken deployment for a property."""
    if property_item.get("token_address") and is_investable_token_contract(
        property_item["token_address"]
    ):
        ensure_security_token_sale_inventory(property_item)
        return property_item

    sale_price_wei_raw = property_item.get("token_price_base")
    try:
        sale_price_wei = (
            int(sale_price_wei_raw) if sale_price_wei_raw not in (None, "", "0") else 0
        )
    except (TypeError, ValueError):
        sale_price_wei = 0
    if sale_price_wei <= 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot deploy token: token_sale_price_eth must be > 0 for this property.",
        )

    token_name = f"{property_item['name']} Token"
    token_address, _ = deploy_security_token(
        property_id, token_name, property_item["token_symbol"], sale_price_wei
    )
    # Mint the entire supply to the token contract so invest() can transfer out.
    mint_security_tokens(
        token_address, token_address, Decimal(property_item["token_supply"])
    )

    cursor.execute(
        "UPDATE properties SET token_address = %s WHERE id = %s",
        (token_address, property_id),
    )
    property_item["token_address"] = token_address
    return property_item


# ── Investment formatting / recovery ──────────────────────────────────

def format_investment_row(row: dict) -> dict:
    from backend.services.blockchain import from_base_units

    token_amount_base = int(Decimal(row.get("token_amount_base") or 0))
    eth_amount_wei = int(Decimal(row.get("eth_amount_wei") or 0))
    created_at = row.get("created_at")
    return {
        "id": int(row["id"]),
        "property_id": int(row["property_id"]),
        "investor_wallet": row.get("investor_wallet"),
        "token_amount": from_base_units(token_amount_base, TOKEN_DECIMALS),
        "eth_amount": from_wei(eth_amount_wei),
        "eth_amount_wei": str(eth_amount_wei),
        "escrow_deal_id": row.get("escrow_deal_id"),
        "deposit_tx_hash": row.get("deposit_tx_hash"),
        "status": row.get("status"),
        "created_at": created_at.isoformat() if created_at else None,
    }


def recover_investment_from_receipt(cursor, tx_hash: str) -> bool:
    """Best-effort fallback when indexer reconciliation fails to create a row."""
    web3 = get_web3()
    tx = get_transaction(tx_hash)
    receipt = get_transaction_receipt(tx_hash)
    if not tx or not receipt or int(receipt.get("status") or 0) != 1:
        return False

    tx_to = tx.get("to")
    tx_from = tx.get("from")
    if not tx_to or not tx_from:
        return False

    token_address = web3.to_checksum_address(tx_to)
    investor_wallet = web3.to_checksum_address(tx_from)

    cursor.execute(
        "SELECT id FROM properties WHERE LOWER(token_address) = LOWER(%s) LIMIT 1",
        (token_address,),
    )
    property_row = cursor.fetchone()
    if not property_row:
        return False

    property_id = int(property_row["id"])
    token_contract = get_contract("SecurityToken", token_address)

    token_amount_base: int | None = None
    eth_amount_wei = int(tx.get("value") or 0)

    investment_events = decode_contract_events_from_receipt(
        token_contract, "InvestmentCompleted", receipt
    )

    if investment_events:
        args = investment_events[0]["args"]
        investor_wallet = web3.to_checksum_address(args.get("investor") or investor_wallet)
        token_amount = Decimal(args.get("tokenAmount") or 0)
        token_amount_base = int(to_base_units(token_amount, TOKEN_DECIMALS))
        eth_amount_wei = int(args.get("ethSpent") or eth_amount_wei)
    else:
        transfer_events = decode_contract_events_from_receipt(token_contract, "Transfer", receipt)
        token_contract_addr = web3.to_checksum_address(token_address)
        for event in transfer_events:
            args = event["args"]
            from_addr = web3.to_checksum_address(args.get("from"))
            to_addr = web3.to_checksum_address(args.get("to"))
            if from_addr == token_contract_addr and to_addr == investor_wallet:
                token_amount_base = int(args.get("value") or 0)
                break

    if token_amount_base is None or token_amount_base <= 0:
        return False

    now = datetime.utcnow()
    cursor.execute(
        "INSERT INTO investments (property_id, investor_wallet, token_amount_base, "
        "eth_amount_wei, deposit_tx_hash, status, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (deposit_tx_hash) WHERE deposit_tx_hash IS NOT NULL DO UPDATE SET "
        "property_id = EXCLUDED.property_id, investor_wallet = EXCLUDED.investor_wallet, "
        "token_amount_base = EXCLUDED.token_amount_base, eth_amount_wei = EXCLUDED.eth_amount_wei, "
        "status = EXCLUDED.status, updated_at = EXCLUDED.updated_at",
        (
            property_id,
            investor_wallet,
            Decimal(token_amount_base),
            Decimal(eth_amount_wei),
            tx_hash,
            "funded",
            now,
            now,
        ),
    )
    return True


# ── Users / ownership / transactions (low-level writers) ─────────────

def get_or_create_user_id(cursor, wallet_address: str, email: str | None = None) -> int:
    checksum = get_web3().to_checksum_address(wallet_address)
    cursor.execute("SELECT id FROM users WHERE LOWER(wallet_address) = LOWER(%s)", (checksum,))
    row = cursor.fetchone()
    if row:
        return int(row["id"])
    cursor.execute(
        "INSERT INTO users (wallet_address, email) VALUES (%s, %s) RETURNING id",
        (checksum, email),
    )
    return int(cursor.fetchone()["id"])


def upsert_ownership(cursor, user_id: int, property_id: int, delta_base: int) -> None:
    cursor.execute(
        "INSERT INTO token_ownerships (user_id, property_id, token_amount) VALUES (%s, %s, %s) "
        "ON CONFLICT (user_id, property_id) DO UPDATE SET "
        "token_amount = token_ownerships.token_amount + EXCLUDED.token_amount",
        (user_id, property_id, int(delta_base)),
    )


def add_transaction_row(
    cursor,
    tx_hash: str,
    tx_type: str,
    amount_base: int,
    property_id: int,
    block_number: int,
    wallet_address: str | None = None,
) -> None:
    normalized_tx_hash = tx_hash.lower() if tx_hash and tx_hash.lower().startswith("0x") else tx_hash
    cursor.execute(
        "INSERT INTO transactions (tx_hash, type, amount, timestamp, property_id, "
        "block_number, wallet_address) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            normalized_tx_hash,
            tx_type,
            Decimal(amount_base),
            datetime.utcnow(),
            property_id,
            block_number,
            wallet_address,
        ),
    )


def format_transaction_row(row: dict) -> dict:
    tx_type = row.get("type", "")
    amount = Decimal(row.get("amount") or 0)
    unit = "tokens"
    divisor = Decimal(10) ** TOKEN_DECIMALS
    action_label = tx_type.replace("_", " ").title()
    description = "Blockchain transaction recorded."

    if tx_type == "ISSUE_TOKENS":
        action_label = "Investment Purchase"
        description = "Investor bought property ownership tokens."
    elif tx_type == "INVESTMENT_COMPLETED":
        action_label = "Investment Completed"
        description = "Property tokens transferred to the investor."
    elif tx_type == "INVESTMENT_FUNDED":
        action_label = "Investment Funded"
        description = "Investor deposit confirmed on-chain."
        unit = "ETH"
        divisor = Decimal(10) ** 18
    elif tx_type == "TRANSFER":
        action_label = "Token Transfer"
        description = "Ownership tokens transferred to another wallet."
    elif tx_type == "MINT_NFT":
        action_label = "Property NFT Minted"
        description = "Property NFT minted by admin."
    elif tx_type == "RENT_DISTRIBUTED":
        action_label = "Rent Distributed"
        description = "Rent payouts distributed for this property."
        unit = "rent units"
        divisor = Decimal(10) ** RENT_TOKEN_DECIMALS
    elif tx_type == "RENT_PAID":
        action_label = "Rent Payment"
        description = "Tenant paid rent for this property. Investor rewards were accrued on-chain."
        unit = "ETH"
        divisor = Decimal(10) ** 18
    elif tx_type == "REWARDS_CLAIMED":
        action_label = "Yield Claimed"
        description = "Investor claimed accrued rental yield from the smart contract."
        unit = "ETH"
        divisor = Decimal(10) ** 18

    if tx_type == "MINT_NFT":
        display_amount = Decimal("0")
        unit = "n/a"
    else:
        display_amount = (amount / divisor) if divisor else amount

    row["action_label"] = action_label
    row["display_amount"] = display_amount
    row["amount_unit"] = unit
    row["status"] = "Completed"
    row["description"] = description
    row.setdefault("gas_fee", None)
    row.setdefault("amount_spent", None)
    row.setdefault("remaining_balance", None)
    return row


# ── Rent helpers ──────────────────────────────────────────────────────

def get_or_create_tenant(cursor, wallet_address: str) -> int:
    checksum = get_web3().to_checksum_address(wallet_address)
    cursor.execute("SELECT id FROM tenants WHERE LOWER(wallet_address) = LOWER(%s)", (checksum,))
    row = cursor.fetchone()
    if row:
        return int(row["id"])
    cursor.execute(
        "INSERT INTO tenants (wallet_address) VALUES (%s) RETURNING id",
        (checksum,),
    )
    return int(cursor.fetchone()["id"])


def ensure_rent_property_registered(cursor, property_item: dict, property_id: int) -> None:
    """Register the property in the RentDistribution singleton if not already active."""
    from backend.services.blockchain import platform_deployer_mismatch

    mismatch = platform_deployer_mismatch()
    if mismatch:
        raise HTTPException(status_code=409, detail=mismatch)

    try:
        info = get_rent_property_info(property_id)
        if info["active"]:
            return
    except Exception:
        pass
    token_address = property_item.get("token_address")
    if not token_address:
        raise HTTPException(
            status_code=400, detail="Property has no token contract deployed"
        )
    try:
        register_property_for_rent(property_id, token_address)
    except Exception as exc:
        err = str(exc)
        if "not the owner" in err or "Ownable" in err:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DEPLOYER_CONTRACT_MISMATCH",
                    "message": (
                        "RentDistribution rejected registration: the deployer wallet is not the "
                        "contract owner. Redeploy platform contracts with the wallet in "
                        "DEPLOYER_PRIVATE_KEY (`npm run deploy:sepolia`), then update "
                        "INDEXER_START_BLOCK."
                    ),
                },
            ) from exc
        raise


def sync_investors_to_contract(cursor, property_id: int) -> list[str]:
    """Ensure all DB token holders are registered as investors in the RentDistribution contract.

    Best-effort:
    - Returns ``[]`` silently if the property isn't yet registered in RentDistribution (no
      rent set, contract addresses missing, RPC down). The admin must run /set-rent first.
    - Used by the explicit admin sync endpoint, by ``/investments/confirm`` (so a fresh
      buyer is auto-registered), AND by ``/properties/{id}/set-rent`` (so investors who
      bought BEFORE rent was first set get backfilled on-chain).
    - Returns the list of newly-added checksummed addresses for observability.

    Without this, ``payRent`` silently skips investors whose wallets aren't in the
    contract's ``_investors[propertyId]`` list — they get 0 ETH and the indexer emits no
    ``InvestorPaid`` event for them, so no claim row is ever written.
    """
    cursor.execute(
        "SELECT u.wallet_address FROM token_ownerships t "
        "JOIN users u ON u.id = t.user_id "
        "WHERE t.property_id = %s AND t.token_amount > 0",
        (property_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        return []

    try:
        info = get_rent_property_info(property_id)
    except Exception:
        info = {"active": False}
    if not info.get("active"):
        return []  # property not registered yet — addInvestor would revert

    web3 = get_web3()
    addresses = [web3.to_checksum_address(r["wallet_address"]) for r in rows]
    try:
        already_raw = get_rent_investors(property_id)
        already = {web3.to_checksum_address(a) for a in already_raw}
    except Exception:
        already = set()
    new_investors = [a for a in addresses if a not in already]
    if new_investors:
        add_investors_to_rent(property_id, new_investors)
    return new_investors


def sync_rent_amount_to_contract(cursor, property_item: dict, property_id: int) -> int:
    """Ensure the RentDistribution contract has the same monthly rent as the DB."""
    rent_wei = int(Decimal(property_item.get("monthly_rent_wei") or 0))
    if rent_wei <= 0:
        return 0

    try:
        info = get_rent_property_info(property_id)
    except Exception:
        info = {"active": False, "monthly_rent_wei": 0}

    if not info.get("active"):
        require_property_token(property_item)
        ensure_rent_property_registered(cursor, property_item, property_id)
        info = {"active": True, "monthly_rent_wei": 0}

    if int(info.get("monthly_rent_wei") or 0) != rent_wei:
        set_monthly_rent(property_id, rent_wei)

    return rent_wei


def build_rent_distribution_preview_from_db(
    cursor, property_id: int, rent_wei: int
) -> list[dict]:
    cursor.execute(
        "SELECT u.wallet_address, t.token_amount "
        "FROM token_ownerships t "
        "JOIN users u ON u.id = t.user_id "
        "WHERE t.property_id = %s AND t.token_amount > 0 "
        "ORDER BY t.token_amount DESC, u.wallet_address ASC",
        (property_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        return []

    total_minted_base = sum(int(Decimal(row.get("token_amount") or 0)) for row in rows)
    if total_minted_base <= 0:
        return []

    breakdown = []
    for row in rows:
        token_amount_base = int(Decimal(row.get("token_amount") or 0))
        if token_amount_base <= 0:
            continue
        payout_wei = (int(rent_wei) * token_amount_base) // total_minted_base
        ownership_bps = (token_amount_base * 10000) // total_minted_base
        if payout_wei > 0:
            share_pct = (
                float((Decimal(payout_wei) / Decimal(int(rent_wei))) * Decimal(100))
                if rent_wei > 0
                else 0.0
            )
            breakdown.append(
                {
                    "investor": row["wallet_address"],
                    "payout_wei": payout_wei,
                    "payout_eth": str(from_wei(payout_wei)),
                    "ownership_bps": ownership_bps,
                    "ownership_pct": round(share_pct, 6),
                }
            )
    return breakdown
