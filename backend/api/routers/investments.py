"""Investment lifecycle: prepare, confirm, get. Plus /portfolio/{wallet}."""
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from backend.api._helpers import (
    format_investment_row,
    get_or_create_user_id,
    get_total_minted_base,
    lock_property,
    recover_investment_from_receipt,
    require_property_token,
    sync_investors_to_contract,
)
from backend.api.deps import get_db, require_role
from backend.api.schemas import (
    InvestmentConfirmRequest,
    InvestmentCreateRequest,
    InvestmentPrepareResponse,
    InvestmentRead,
    PortfolioItem,
    PortfolioResponse,
)
from backend.services.auth import AuthUser, normalize_address
from backend.config.settings import TOKEN_DECIMALS
from backend.services.blockchain import (
    from_base_units,
    from_wei,
    get_contract,
    get_transaction,
    get_web3,
    to_base_units,
    wait_for_transaction_receipt,
)
from backend.services.investment_funding import (
    InvestmentFundingError,
    investment_required_wei,
    read_sale_price_per_token_wei,
)
from backend.services.blockchain_indexer import reconcile_transaction

router = APIRouter()
LOGGER = logging.getLogger(__name__)


def _normalize_tx_hash(tx_hash: str) -> str:
    value = (tx_hash or "").strip()
    if not value:
        return value
    if not value.lower().startswith("0x"):
        value = f"0x{value}"
    return value.lower()


def _sync_wallet_holdings_from_chain(
    cursor,
    *,
    wallet_address: str,
    user_id: int | None,
) -> tuple[int, int | None]:
    cursor.execute("SELECT id, token_address FROM properties WHERE token_address IS NOT NULL")
    properties = cursor.fetchall()
    if not properties:
        return 0, user_id

    synced_rows = 0
    resolved_user_id = user_id
    for row in properties:
        token_address = row.get("token_address")
        if not token_address:
            continue
        try:
            token_contract = get_contract("SecurityToken", token_address)
            balance_base = int(token_contract.functions.balanceOf(wallet_address).call())
        except Exception as exc:
            LOGGER.warning(
                "portfolio_sync stage=balance_failed wallet=%s property_id=%s token=%s error=%s",
                wallet_address,
                int(row["id"]),
                token_address,
                exc,
            )
            continue

        if balance_base <= 0:
            continue

        if resolved_user_id is None:
            resolved_user_id = get_or_create_user_id(cursor, wallet_address)

        cursor.execute(
            "INSERT INTO token_ownerships (user_id, property_id, token_amount) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id, property_id) DO UPDATE SET token_amount = EXCLUDED.token_amount",
            (int(resolved_user_id), int(row["id"]), int(balance_base)),
        )
        synced_rows += int(cursor.rowcount or 0)

    return synced_rows, resolved_user_id


@router.post("/investments/prepare", response_model=InvestmentPrepareResponse)
def prepare_investment(
    payload: InvestmentCreateRequest,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("investor", "property_owner")),
):
    """Prepare an investment: validate, compute authoritative ETH cost from the
    on-chain sale price, persist an `awaiting_deposit` row, and return signing metadata.

    The recipient is the SecurityToken contract itself — the investor calls
    ``invest(propertyId, tokenAmount)`` with msg.value = salePricePerTokenWei * tokenAmount.
    """
    if payload.token_amount <= 0:
        raise HTTPException(status_code=400, detail="token_amount must be > 0")

    web3 = get_web3()
    if not web3.is_address(payload.investor_wallet):
        raise HTTPException(status_code=400, detail="Invalid wallet address")

    if user.role != "property_owner" and normalize_address(payload.investor_wallet) != normalize_address(user.wallet_address):
        raise HTTPException(status_code=403, detail="Investor wallet must match the authenticated user")

    checksum = web3.to_checksum_address(payload.investor_wallet)
    cursor = db.cursor(dictionary=True)
    try:
        property_item = lock_property(cursor, payload.property_id)
        if not property_item:
            raise HTTPException(status_code=404, detail="Property not found")
        if not property_item.get("is_active", True):
            raise HTTPException(status_code=404, detail="Property not found")

        require_property_token(property_item)

        amount_base = to_base_units(payload.token_amount, TOKEN_DECIMALS)
        max_supply_base = to_base_units(Decimal(property_item["token_supply"]), TOKEN_DECIMALS)
        total_minted_base = get_total_minted_base(cursor, payload.property_id)
        if total_minted_base + Decimal(amount_base) > Decimal(max_supply_base):
            raise HTTPException(status_code=400, detail="Token supply exceeded")

        token_contract = get_contract("SecurityToken", property_item["token_address"])
        token_checksum = web3.to_checksum_address(property_item["token_address"])
        try:
            sale_price_per_token_wei = read_sale_price_per_token_wei(property_item)
        except InvestmentFundingError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        # invest() pulls ERC20 from the token contract's own balance — not the investor's ETH balance.
        try:
            inventory_base = int(token_contract.functions.balanceOf(token_checksum).call())
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to read on-chain sale inventory (balanceOf(token)): {exc}",
            )
        if inventory_base < amount_base:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Insufficient tokens available for sale: the SecurityToken contract currently "
                    f"holds {from_base_units(inventory_base, TOKEN_DECIMALS)} tokens for primary "
                    f"sales, but this order needs {payload.token_amount}. "
                    "The deployer must mint the issuance to the token contract address itself "
                    "(inventory pool), e.g. mint(<token_address>, supply * 10**decimals)."
                ),
            )

        try:
            required_wei = investment_required_wei(property_item, int(payload.token_amount))
        except InvestmentFundingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        eth_amount = from_wei(required_wei)

        cursor.execute(
            "INSERT INTO investments (property_id, investor_wallet, token_amount_base, "
            "eth_amount_wei, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id",
            (
                payload.property_id,
                checksum,
                Decimal(amount_base),
                Decimal(required_wei),
                "awaiting_deposit",
            ),
        )
        investment_id = int(cursor.fetchone()["id"])
        db.commit()

        return InvestmentPrepareResponse(
            investment_id=investment_id,
            property_id=payload.property_id,
            investor_wallet=checksum,
            token_amount=payload.token_amount,
            eth_amount=eth_amount,
            eth_amount_wei=str(required_wei),
            recipient_address=property_item["token_address"],
            chain_id=web3.eth.chain_id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.post("/investments/{investment_id}/confirm", response_model=InvestmentRead)
def confirm_investment(
    investment_id: int,
    payload: InvestmentConfirmRequest,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("investor", "property_owner")),
):
    """Confirm investment — verify the on-chain purchase and reconcile DB state.

    1. Wait for receipt & verify success.
    2. Claim the tx_hash on the prepared `awaiting_deposit` row (so reconcile's
       ON CONFLICT(deposit_tx_hash) updates it in-place instead of inserting a duplicate).
    3. Run the indexer reconciler to decode events and populate token_ownerships.
    4. Return the canonical investment row.
    """
    web3 = get_web3()
    normalized_tx_hash = _normalize_tx_hash(payload.tx_hash)
    cursor = db.cursor(dictionary=True)
    try:
        LOGGER.info(
            "investment_confirm stage=receipt_fetch_start tx_hash=%s investment_id=%s",
            normalized_tx_hash,
            investment_id,
        )
        receipt = wait_for_transaction_receipt(normalized_tx_hash, timeout=120, poll_latency=1)
        if not receipt or receipt.get("status") != 1:
            raise HTTPException(status_code=400, detail="Transaction not confirmed or reverted")
        LOGGER.info(
            "investment_confirm stage=receipt_fetched tx_hash=%s block_number=%s status=%s",
            normalized_tx_hash,
            int(receipt.get("blockNumber") or 0),
            int(receipt.get("status") or 0),
        )

        tx = get_transaction(normalized_tx_hash)
        if not tx.get("to") or not tx.get("from"):
            raise HTTPException(status_code=400, detail="Transaction missing required sender/destination fields")
        tx_to = web3.to_checksum_address(tx["to"])
        tx_from = web3.to_checksum_address(tx["from"])

        cursor.execute("SELECT * FROM investments WHERE id = %s FOR UPDATE", (investment_id,))
        prepared_investment = cursor.fetchone()
        if not prepared_investment:
            raise HTTPException(status_code=404, detail="Investment not found")

        if user.role != "property_owner" and normalize_address(prepared_investment["investor_wallet"]) != normalize_address(user.wallet_address):
            raise HTTPException(status_code=403, detail="You can only confirm your own investments")

        cursor.execute(
            "SELECT id, token_address FROM properties WHERE id = %s",
            (prepared_investment["property_id"],),
        )
        property_row = cursor.fetchone()
        if not property_row or not property_row.get("token_address"):
            raise HTTPException(status_code=400, detail="Property token contract not configured")

        expected_to = web3.to_checksum_address(property_row["token_address"])
        if tx_to != expected_to:
            raise HTTPException(
                status_code=400,
                detail="Transaction destination does not match property SecurityToken contract",
            )

        expected_investor = web3.to_checksum_address(prepared_investment["investor_wallet"])
        if tx_from != expected_investor:
            raise HTTPException(
                status_code=400,
                detail="Transaction sender does not match prepared investor wallet",
            )

        cursor.execute(
            "UPDATE investments SET deposit_tx_hash = %s "
            "WHERE id = %s AND deposit_tx_hash IS NULL",
            (normalized_tx_hash, investment_id),
        )
        db.commit()
        LOGGER.info(
            "investment_confirm stage=prepare_claim_committed tx_hash=%s investment_id=%s updated_rows=%s commit_success=true",
            normalized_tx_hash,
            investment_id,
            int(cursor.rowcount or 0),
        )

        reconcile_summary = reconcile_transaction(normalized_tx_hash)
        LOGGER.info(
            "investment_confirm stage=reconcile_completed tx_hash=%s investment_id=%s summary=%s",
            normalized_tx_hash,
            investment_id,
            reconcile_summary,
        )

        cursor.execute(
            "SELECT * FROM investments WHERE LOWER(deposit_tx_hash) = LOWER(%s)",
            (normalized_tx_hash,),
        )
        updated_investment = cursor.fetchone()
        if not updated_investment:
            if recover_investment_from_receipt(cursor, normalized_tx_hash):
                db.commit()
                LOGGER.info(
                    "investment_confirm stage=receipt_recovery_committed tx_hash=%s investment_id=%s commit_success=true",
                    normalized_tx_hash,
                    investment_id,
                )
                cursor.execute(
                    "SELECT * FROM investments WHERE LOWER(deposit_tx_hash) = LOWER(%s)",
                    (normalized_tx_hash,),
                )
                updated_investment = cursor.fetchone()

        if not updated_investment:
            raise HTTPException(
                status_code=500, detail="Investment index not found after reconciliation"
            )

        cursor.execute(
            "SELECT COALESCE(SUM(t.token_amount), 0) AS token_amount "
            "FROM token_ownerships t "
            "JOIN users u ON u.id = t.user_id "
            "WHERE t.property_id = %s AND LOWER(u.wallet_address) = LOWER(%s) AND t.token_amount > 0",
            (updated_investment["property_id"], updated_investment["investor_wallet"]),
        )
        ownership_amount = Decimal(cursor.fetchone()["token_amount"] or 0)

        cursor.execute(
            "SELECT 1 FROM transactions WHERE LOWER(tx_hash) = LOWER(%s) LIMIT 1",
            (normalized_tx_hash,),
        )
        tx_row = cursor.fetchone()

        cursor.execute(
            "SELECT COUNT(*) AS events_count FROM blockchain_event_log WHERE LOWER(tx_hash) = LOWER(%s)",
            (normalized_tx_hash,),
        )
        events_count = int(cursor.fetchone()["events_count"] or 0)

        if ownership_amount <= 0 or not tx_row or events_count <= 0:
            raise HTTPException(
                status_code=500,
                detail="Reconciliation incomplete after confirm; blockchain state was not fully persisted",
            )
        LOGGER.info(
            "investment_confirm stage=completed tx_hash=%s property_id=%s investor_wallet=%s ownership_amount=%s events_count=%s commit_success=true",
            normalized_tx_hash,
            int(updated_investment["property_id"]),
            updated_investment["investor_wallet"],
            str(ownership_amount),
            events_count,
        )

        # Best-effort: register this investor in the on-chain RentDistribution list so future
        # tenant payments automatically include them. Skipped silently when the property isn't
        # rent-registered yet (admin must call set-rent + sync-rent-chain in that case).
        # Failure here MUST NOT fail the investment — the buy is already finalized on-chain.
        try:
            sync_investors_to_contract(cursor, int(updated_investment["property_id"]))
            db.commit()
        except Exception as sync_exc:
            db.rollback()
            LOGGER.warning(
                "investment_confirm stage=rent_sync_skipped property_id=%s investor_wallet=%s reason=%s",
                int(updated_investment["property_id"]),
                updated_investment["investor_wallet"],
                sync_exc,
            )

        return format_investment_row(updated_investment)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        LOGGER.exception(
            "investment_confirm stage=failed tx_hash=%s investment_id=%s error=%s",
            normalized_tx_hash,
            investment_id,
            e,
        )
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/investments/{investment_id}", response_model=InvestmentRead)
def get_investment(investment_id: int, db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM investments WHERE id = %s", (investment_id,))
        investment = cursor.fetchone()
        if not investment:
            raise HTTPException(status_code=404, detail="Investment not found")
        return format_investment_row(investment)
    finally:
        cursor.close()


@router.get("/portfolio/{wallet_address}", response_model=PortfolioResponse)
def get_portfolio(
    wallet_address: str,
    refresh: bool = False,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("investor", "property_owner")),
):
    web3 = get_web3()
    if not web3.is_address(wallet_address):
        raise HTTPException(status_code=400, detail="Invalid wallet address")
    if user.role != "property_owner" and normalize_address(wallet_address) != normalize_address(user.wallet_address):
        raise HTTPException(status_code=403, detail="You can only view your own portfolio")
    checksum = web3.to_checksum_address(wallet_address)
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id FROM users WHERE LOWER(wallet_address) = LOWER(%s)",
            (checksum,),
        )
        user = cursor.fetchone()
        user_id = int(user["id"]) if user else None

        items: list[PortfolioItem] = []
        if user_id is not None:
            cursor.execute(
                "SELECT t.property_id, p.name AS property_name, t.token_amount "
                "FROM token_ownerships t "
                "JOIN properties p ON p.id = t.property_id "
                "WHERE t.user_id = %s AND t.token_amount > 0",
                (user_id,),
            )
            items = [
                PortfolioItem(
                    property_id=row["property_id"],
                    property_name=row["property_name"],
                    token_amount=row["token_amount"],
                )
                for row in cursor.fetchall()
            ]

        if refresh or not items:
            synced_rows, user_id = _sync_wallet_holdings_from_chain(
                cursor,
                wallet_address=checksum,
                user_id=user_id,
            )
            if synced_rows:
                db.commit()
                cursor.execute(
                    "SELECT t.property_id, p.name AS property_name, t.token_amount "
                    "FROM token_ownerships t "
                    "JOIN properties p ON p.id = t.property_id "
                    "WHERE t.user_id = %s AND t.token_amount > 0",
                    (user_id,),
                )
                items = [
                    PortfolioItem(
                        property_id=row["property_id"],
                        property_name=row["property_name"],
                        token_amount=row["token_amount"],
                    )
                    for row in cursor.fetchall()
                ]

        return PortfolioResponse(wallet_address=checksum, holdings=items)
    finally:
        cursor.close()
