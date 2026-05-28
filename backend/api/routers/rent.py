"""Rent-distribution endpoints.

Design notes (Phase D):
* `POST /properties/{id}/set-rent`   — property_owner: on-chain set monthly rent.
* `POST /properties/{id}/sync-rent-chain` — property_owner: reconcile the on-chain
  RentDistribution state (register property, sync monthly rent, sync investor
  set) to match the DB. Idempotent.
* `GET  /tenant/pay-rent/prepare/{id}` — **read-only**: returns calldata + on-chain
  rent amount. No longer triggers on-chain syncs. If the contract isn't ready,
  returns a 409 instructing the property owner to call /sync-rent-chain.
* `POST /tenant/pay-rent/confirm/{id}` — verify and reconcile tenant tx.
"""
import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

LOGGER = logging.getLogger(__name__)

from backend.api._helpers import (
    build_rent_distribution_preview_from_db,
    ensure_rent_property_registered,
    enrich_property_with_supply,
    fetch_property,
    get_or_create_tenant,
    lock_property,
    require_property_token,
    sync_investors_to_contract,
    sync_rent_amount_to_contract,
)
from backend.api.deps import (
    get_current_user,
    get_db,
    require_property_owner,
    require_role,
)
from backend.services.auth import AuthUser, normalize_address
from backend.api.schemas import (
    ClaimableRewardsSummaryRead,
    ClaimRewardsConfirmRequest,
    ClaimRewardsConfirmResponse,
    ClaimRewardsPrepareRequest,
    ClaimRewardsPrepareResponse,
    InvestorPayoutRead,
    PayRentConfirmRequest,
    PayRentPrepareResponse,
    RentAnalytics,
    RentDistributionRead,
    RentPaymentRead,
    RewardClaimHistoryRead,
    SetMonthlyRentRequest,
)
from backend.services.blockchain import (
    calculate_rent_distribution,
    decode_contract_events_from_receipt,
    encode_claim_rewards,
    encode_pay_rent,
    from_wei,
    get_claimable_rewards,
    get_contract,
    get_property_claimable_rewards,
    get_rent_distribution_address,
    get_rent_property_info,
    get_total_claimed_rewards,
    get_transaction,
    get_web3,
    set_monthly_rent,
    to_wei,
    wait_for_transaction_receipt,
)
from backend.services.blockchain_indexer import _handle_rent_events, reconcile_transaction
from backend.api.rent_cycle import (
    compute_rent_period_status,
    get_last_confirmed_rent_payment,
    get_last_confirmed_rent_payment_by_wallet,
    serialize_period_fields,
)

router = APIRouter()


def _enforce_self_or_property_owner(user: AuthUser, wallet_address: str) -> None:
    """A user may read their own wallet-scoped data; property owners may read anyone's."""
    if user.role == "property_owner":
        return
    if normalize_address(wallet_address) != normalize_address(user.wallet_address):
        raise HTTPException(status_code=403, detail="You can only access your own wallet's data")


def _assert_owner(user: AuthUser, property_item: dict) -> None:
    owner = normalize_address(property_item.get("owner_wallet") or "")
    if not owner:
        raise HTTPException(status_code=403, detail="Property owner not assigned.")
    if owner != normalize_address(user.wallet_address):
        raise HTTPException(status_code=403, detail="You can only modify properties you own.")


def _current_rent_cycle() -> tuple[int, int, str]:
    now = datetime.utcnow()
    label = now.strftime("%B %Y")
    return now.month, now.year, label


def _tenant_rent_period_status(cursor, tenant_id: int, property_id: int) -> dict:
    last = get_last_confirmed_rent_payment(cursor, tenant_id, property_id)
    return compute_rent_period_status(last)


def _tenant_wallet_rent_period_status(cursor, tenant_wallet: str, property_id: int) -> dict:
    last = get_last_confirmed_rent_payment_by_wallet(cursor, tenant_wallet, property_id)
    return compute_rent_period_status(last)


def _ensure_rent_chain_ready_for_payment(cursor, property_item: dict, property_id: int) -> int:
    """Register property, sync rent amount, and sync investors before tenant pays."""
    ensure_rent_property_registered(cursor, property_item, property_id)
    try:
        sync_rent_amount_to_contract(cursor, property_item, property_id)
    except Exception as exc:  # noqa: BLE001
        # Tenant payments should not be blocked by a stale/oversized DB rent value
        # if the on-chain rent is already active and non-zero.
        err = str(exc).lower()
        if "rent amount too high" in err:
            info = get_rent_property_info(property_id)
            onchain_rent = int(info.get("monthly_rent_wei") or 0)
            if info.get("active") and onchain_rent > 0:
                LOGGER.warning(
                    "tenant_sync rent-too-high fallback property_id=%s db_rent=%s onchain_rent=%s",
                    property_id,
                    property_item.get("monthly_rent_wei"),
                    onchain_rent,
                )
            else:
                raise
        else:
            raise
    synced = sync_investors_to_contract(cursor, property_id)
    return len(synced)


# ══════════════════════════════════════════════════════════════════════
#  PROPERTY OWNER
# ══════════════════════════════════════════════════════════════════════

@router.post("/properties/{property_id}/set-rent")
def set_property_rent(
    property_id: int,
    payload: SetMonthlyRentRequest,
    user: AuthUser = Depends(require_property_owner),
    db=Depends(get_db),
):
    cursor = db.cursor(dictionary=True)
    try:
        property_item = lock_property(cursor, property_id)
        if not property_item:
            raise HTTPException(status_code=404, detail="Property not found")
        _assert_owner(user, property_item)
        require_property_token(property_item)
        ensure_rent_property_registered(cursor, property_item, property_id)

        rent_wei = to_wei(payload.monthly_rent_eth)
        set_monthly_rent(property_id, rent_wei)

        cursor.execute(
            "UPDATE properties SET monthly_rent_wei = %s WHERE id = %s",
            (str(rent_wei), property_id),
        )

        # Backfill any investors who bought BEFORE rent was first set. The /investments/confirm
        # auto-sync can't add them at buy time because the property wasn't active in
        # RentDistribution yet. Do it now that it is. Best-effort: failure must not block the
        # rent setup, which is already done on-chain by this point.
        synced_investors: list[str] = []
        try:
            synced_investors = sync_investors_to_contract(cursor, property_id)
        except Exception as sync_exc:
            LOGGER.warning(
                "set_rent stage=investor_sync_failed property_id=%s error=%s",
                property_id, sync_exc,
            )

        db.commit()
        return {
            "status": "ok",
            "property_id": property_id,
            "monthly_rent_wei": str(rent_wei),
            "monthly_rent_eth": str(payload.monthly_rent_eth),
            "investors_synced": len(synced_investors),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.post("/properties/{property_id}/sync-rent-chain")
def sync_rent_chain(
    property_id: int,
    user: AuthUser = Depends(require_property_owner),
    db=Depends(get_db),
):
    """Admin-initiated reconciliation of the on-chain RentDistribution state.

    Registers the property, syncs the monthly rent, and adds any DB investors
    who aren't yet on-chain. Idempotent. Call this before the first tenant
    payment, or after minting new tokens to additional investors.

    This replaces the old implicit sync that happened inside the tenant
    `/pay-rent/prepare` endpoint.
    """
    cursor = db.cursor(dictionary=True)
    try:
        property_item = lock_property(cursor, property_id)
        if not property_item:
            raise HTTPException(status_code=404, detail="Property not found")

        _assert_owner(user, property_item)

        require_property_token(property_item)
        ensure_rent_property_registered(cursor, property_item, property_id)
        rent_wei = sync_rent_amount_to_contract(cursor, property_item, property_id)
        sync_investors_to_contract(cursor, property_id)
        db.commit()

        info = get_rent_property_info(property_id)
        return {
            "status": "ok",
            "property_id": property_id,
            "registered": bool(info.get("active")),
            "monthly_rent_wei": str(info.get("monthly_rent_wei") or rent_wei or 0),
            "investor_count": int(info.get("investor_count") or 0),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Rent-chain sync failed: {e}")
    finally:
        cursor.close()


@router.get("/owner/rent-analytics", response_model=RentAnalytics, dependencies=[Depends(require_property_owner)])
def admin_rent_analytics(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT COALESCE(SUM(CAST(amount_wei AS DECIMAL(36,0))), 0) AS collected, "
            "COUNT(*) AS cnt FROM rent_payments"
        )
        payments = cursor.fetchone()

        cursor.execute(
            "SELECT COALESCE(SUM(CAST(total_distributed AS DECIMAL(36,0))), 0) AS distributed, "
            "COUNT(*) AS cnt FROM rent_distributions"
        )
        dists = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) AS cnt FROM tenant_rentals WHERE status = 'active'")
        active = cursor.fetchone()

        return RentAnalytics(
            total_rent_collected_wei=str(int(payments["collected"] or 0)),
            total_rent_distributed_wei=str(int(dists["distributed"] or 0)),
            total_payments=int(payments["cnt"] or 0),
            total_distributions=int(dists["cnt"] or 0),
            active_rentals=int(active["cnt"] or 0),
        )
    finally:
        cursor.close()


@router.get("/owner/distributions", response_model=list[RentDistributionRead], dependencies=[Depends(require_property_owner)])
def admin_distributions(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT rd.*, p.name AS property_name "
            "FROM rent_distributions rd "
            "JOIN properties p ON p.id = rd.property_id "
            "ORDER BY rd.distributed_at DESC"
        )
        rows = cursor.fetchall()
        for r in rows:
            r["distributed_at"] = (
                r["distributed_at"].isoformat() if r.get("distributed_at") else ""
            )
        return rows
    finally:
        cursor.close()


@router.get("/owner/rent-payments", response_model=list[RentPaymentRead], dependencies=[Depends(require_property_owner)])
def admin_rent_payments(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT rp.*, p.name AS property_name, t.wallet_address AS tenant_wallet "
            "FROM rent_payments rp "
            "JOIN tenants t ON t.id = rp.tenant_id "
            "JOIN properties p ON p.id = rp.property_id "
            "ORDER BY rp.payment_date DESC"
        )
        rows = cursor.fetchall()
        for r in rows:
            r["payment_date"] = (
                r["payment_date"].isoformat() if r.get("payment_date") else ""
            )
        return rows
    finally:
        cursor.close()


@router.get("/owner/active-rentals", dependencies=[Depends(require_property_owner)])
def admin_active_rentals(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT tr.*, p.name AS property_name, p.location, "
            "t.wallet_address AS tenant_wallet "
            "FROM tenant_rentals tr "
            "JOIN tenants t ON t.id = tr.tenant_id "
            "JOIN properties p ON p.id = tr.property_id "
            "ORDER BY tr.created_at DESC"
        )
        rows = cursor.fetchall()
        for r in rows:
            if r.get("rental_start_date"):
                r["rental_start_date"] = r["rental_start_date"].isoformat()
            if r.get("rental_end_date"):
                r["rental_end_date"] = r["rental_end_date"].isoformat()
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
        return rows
    finally:
        cursor.close()


# ══════════════════════════════════════════════════════════════════════
#  TENANT
# ══════════════════════════════════════════════════════════════════════

@router.get("/tenant/properties")
def tenant_list_properties(tenant_wallet: str | None = None, db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM properties p "
            "WHERE COALESCE(p.is_active, TRUE) = TRUE "
            "AND EXISTS ("
            "  SELECT 1 FROM token_ownerships t "
            "  WHERE t.property_id = p.id AND t.token_amount > 0"
            ") "
            "ORDER BY p.id DESC"
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            row = enrich_property_with_supply(cursor, row)
            rent_wei = row.get("monthly_rent_wei") or "0"
            row["rent_enabled"] = rent_wei not in (None, "", "0")
            if tenant_wallet:
                period = _tenant_wallet_rent_period_status(cursor, tenant_wallet, int(row["id"]))
                row.update(serialize_period_fields(period))
            else:
                row.update(
                    serialize_period_fields(
                        compute_rent_period_status(None),
                    )
                )
            result.append(row)
        return result
    finally:
        cursor.close()


@router.get("/tenant/pay-rent/prepare/{property_id}", response_model=PayRentPrepareResponse)
def prepare_rent_payment(
    property_id: int,
    tenant_wallet: str | None = None,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("tenant", "property_owner")),
):
    """Returns calldata + rent amount for MetaMask.

    Automatically syncs RentDistribution (register, rent amount, investors) so
    investor yield accrues when the tenant pays. Billing is anniversary-based:
    paying on May 15 blocks further payment until June 15.
    """
    cursor = db.cursor(dictionary=True)
    try:
        property_item = fetch_property(cursor, property_id)
        if not property_item:
            raise HTTPException(status_code=404, detail="Property not found")
        if not property_item.get("is_active", True):
            raise HTTPException(status_code=404, detail="Property not found")
        require_property_token(property_item)

        effective_tenant_wallet = tenant_wallet or (user.wallet_address if user.role == "tenant" else None)
        period = compute_rent_period_status(None)
        if effective_tenant_wallet:
            _enforce_self_or_property_owner(user, effective_tenant_wallet)
            web3 = get_web3()
            if not web3.is_address(effective_tenant_wallet):
                raise HTTPException(status_code=400, detail="Invalid tenant wallet")
            checksum = web3.to_checksum_address(effective_tenant_wallet)
            period = _tenant_wallet_rent_period_status(cursor, checksum, property_id)
            if period["current_cycle_paid"]:
                next_due = period["next_due_at"]
                due_label = next_due.strftime("%B %d, %Y") if hasattr(next_due, "strftime") else str(next_due)
                raise HTTPException(
                    status_code=409,
                    detail=f"Rent already paid for this period. Next due {due_label}.",
                )

        from backend.services.blockchain import platform_deployer_mismatch

        mismatch = platform_deployer_mismatch()
        if mismatch:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{mismatch.get('message')} "
                    "Tenant rent cannot be prepared until platform contracts are redeployed "
                    "with the wallet in DEPLOYER_PRIVATE_KEY."
                ),
            )

        try:
            synced_count = _ensure_rent_chain_ready_for_payment(cursor, property_item, property_id)
            if synced_count:
                LOGGER.info(
                    "prepare_rent_payment synced %s investor(s) for property_id=%s",
                    synced_count,
                    property_id,
                )
        except HTTPException as exc:
            detail = exc.detail
            if isinstance(detail, dict) and detail.get("code") == "DEPLOYER_CONTRACT_MISMATCH":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"{detail.get('message')} "
                        "Ask the property owner to run platform deploy (`npm run deploy:sepolia`) "
                        "and Sync Rent Chain on this property."
                    ),
                ) from exc
            raise
        except Exception as sync_exc:
            err = str(sync_exc)
            LOGGER.warning(
                "prepare_rent_payment stage=sync_failed property_id=%s error=%s",
                property_id,
                sync_exc,
            )
            if "not the owner" in err or "Ownable" in err:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Rent contract sync failed: the backend deployer wallet is not the owner "
                        "of RentDistribution on Sepolia. The property owner must redeploy platform "
                        "contracts with the correct DEPLOYER_PRIVATE_KEY, then open the property "
                        "and use Sync Rent Chain before tenants can pay."
                    ),
                ) from sync_exc
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Could not sync rent contract before payment: {sync_exc}. "
                    "Ask the property owner to verify rent setup."
                ),
            ) from sync_exc

        try:
            info = get_rent_property_info(property_id)
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Failed to read on-chain rent info: {exc}"
            )

        if not info.get("active"):
            raise HTTPException(
                status_code=409,
                detail="Property is not registered on RentDistribution after sync.",
            )
        rent_wei = int(info.get("monthly_rent_wei") or 0)
        if rent_wei == 0:
            raise HTTPException(
                status_code=409,
                detail="Monthly rent on-chain is zero. Property owner must set rent first.",
            )

        if effective_tenant_wallet:
            from backend.services.rent_payment_funding import check_tenant_can_pay_monthly_rent

            funding = check_tenant_can_pay_monthly_rent(
                checksum,
                rent_wei,
                str(property_item.get("name") or ""),
            )
            if not funding.ok:
                raise HTTPException(status_code=402, detail=funding.speak_to_user)

        calldata = encode_pay_rent(property_id)
        web3 = get_web3()
        now = datetime.utcnow()
        period_fields = serialize_period_fields(period)
        return PayRentPrepareResponse(
            property_id=property_id,
            property_name=property_item["name"],
            monthly_rent_wei=str(rent_wei),
            monthly_rent_eth=str(from_wei(rent_wei)),
            rent_contract_address=get_rent_distribution_address(),
            calldata=calldata,
            chain_id=web3.eth.chain_id,
            rent_month=now.month,
            rent_year=now.year,
            rent_cycle_label=period_fields["rent_cycle_label"] or now.strftime("%B %Y"),
            current_cycle_paid=period_fields["current_cycle_paid"],
            can_pay_rent=period_fields["can_pay_rent"],
            next_rent_due_at=period_fields["next_rent_due_at"],
            last_rent_paid_at=period_fields["last_rent_paid_at"],
        )
    finally:
        cursor.close()


@router.post("/tenant/pay-rent/confirm/{property_id}")
def confirm_rent_payment(
    property_id: int,
    payload: PayRentConfirmRequest,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("tenant", "property_owner")),
):
    web3 = get_web3()
    if not web3.is_address(payload.tenant_wallet):
        raise HTTPException(status_code=400, detail="Invalid tenant wallet")
    _enforce_self_or_property_owner(user, payload.tenant_wallet)
    tenant_checksum = web3.to_checksum_address(payload.tenant_wallet)

    cursor = db.cursor(dictionary=True)
    try:
        property_item = fetch_property(cursor, property_id)
        if not property_item:
            raise HTTPException(status_code=404, detail="Property not found")
        if not property_item.get("is_active", True):
            raise HTTPException(status_code=404, detail="Property not found")

        tenant_id = get_or_create_tenant(cursor, tenant_checksum)
        period = _tenant_rent_period_status(cursor, tenant_id, property_id)
        if period["current_cycle_paid"]:
            next_due = period["next_due_at"]
            due_label = next_due.strftime("%B %d, %Y") if hasattr(next_due, "strftime") else str(next_due)
            raise HTTPException(
                status_code=409,
                detail=f"Rent already paid for this period. Next due {due_label}.",
            )

        receipt = wait_for_transaction_receipt(payload.tx_hash, timeout=120, poll_latency=1)
        if not receipt or receipt.get("status") != 1:
            raise HTTPException(status_code=400, detail="Transaction not confirmed or reverted")

        tx = get_transaction(payload.tx_hash)
        tx_from = web3.to_checksum_address(tx.get("from"))
        if tx_from != tenant_checksum:
            raise HTTPException(
                status_code=400,
                detail="Transaction sender does not match tenant wallet",
            )

        rent_contract_addr = get_rent_distribution_address()
        tx_to = tx.get("to")
        if not tx_to or web3.to_checksum_address(tx_to) != web3.to_checksum_address(
            rent_contract_addr
        ):
            raise HTTPException(
                status_code=400,
                detail="Transaction not sent to RentDistribution contract",
            )

        amount_wei = int(tx.get("value"))
        amount_eth = str(from_wei(amount_wei))
        tx_hash_normalized = tx["hash"].to_0x_hex()
        LOGGER.info("confirm_rent_payment tx=%s property=%s", tx_hash_normalized, property_id)

        # ── Deterministic rent reconciliation: decode receipt directly ──
        # Do NOT rely on background indexer timing. Process events in the same
        # DB transaction so the row is visible immediately.
        rent_contract = get_contract("RentDistribution", rent_contract_addr)
        rent_paid_events = decode_contract_events_from_receipt(rent_contract, "RentPaid", receipt)
        investor_paid_events = decode_contract_events_from_receipt(
            rent_contract, "InvestorPaid", receipt
        )
        rent_distributed_events = decode_contract_events_from_receipt(
            rent_contract, "RentDistributed", receipt
        )
        LOGGER.info(
            "Decoded events tx=%s RentPaid=%d InvestorPaid=%d RentDistributed=%d",
            tx_hash_normalized, len(rent_paid_events), len(investor_paid_events), len(rent_distributed_events)
        )

        if not rent_paid_events:
            raise HTTPException(
                status_code=400, detail="No RentPaid event found in transaction receipt"
            )

        rent_event = rent_paid_events[0]
        event_property_id = int(rent_event["args"]["propertyId"])
        LOGGER.info("RentPaid event property_id=%s endpoint_property_id=%s", event_property_id, property_id)
        if event_property_id != property_id:
            raise HTTPException(
                status_code=400,
                detail=f"Transaction paid rent for property {event_property_id}, expected {property_id}",
            )

        matching_investor_paid = [
            e for e in investor_paid_events
            if int(e["args"].get("propertyId", event_property_id)) == event_property_id
        ]
        matching_rent_distributed = [
            e for e in rent_distributed_events
            if int(e["args"].get("propertyId", event_property_id)) == event_property_id
        ]

        _handle_rent_events(
            cursor,
            web3,
            tx,
            receipt,
            property_item,
            rent_event,
            matching_investor_paid,
            matching_rent_distributed,
        )
        LOGGER.info("_handle_rent_events completed tx=%s", tx_hash_normalized)

        # Commit BEFORE querying so the rows are durable and visible to other sessions.
        db.commit()
        LOGGER.info("DB committed tx=%s", tx_hash_normalized)

        # Re-query the freshly upserted row to return canonical data
        cursor.execute(
            "SELECT rp.id, rp.amount_wei, rp.amount_eth, rp.tx_hash, rp.block_number, "
            "rp.payment_date, rp.payment_status, rp.tenant_id, rp.property_id, "
            "p.name AS property_name, t.wallet_address AS tenant_wallet "
            "FROM rent_payments rp JOIN tenants t ON t.id = rp.tenant_id "
            "JOIN properties p ON p.id = rp.property_id WHERE rp.tx_hash = %s",
            (tx_hash_normalized,),
        )
        rent_payment = cursor.fetchone()
        LOGGER.info("rent_payment select tx=%s found=%s", tx_hash_normalized, rent_payment is not None)
        if not rent_payment:
            raise HTTPException(
                status_code=500, detail="Rent payment not found after direct reconciliation"
            )

        cursor.execute(
            "SELECT id, property_id, rent_payment_id, total_rent_collected, total_distributed, "
            "investor_count, distribution_tx_hash, distributed_at "
            "FROM rent_distributions WHERE distribution_tx_hash = %s",
            (tx_hash_normalized,),
        )
        distribution = cursor.fetchone()
        investor_count = int(distribution["investor_count"] if distribution else 0)
        if investor_count == 0 and len(matching_investor_paid) == 0:
            LOGGER.warning(
                "confirm_rent_payment tx=%s property_id=%s had no InvestorPaid events — "
                "investors may not have been synced to RentDistribution before payment.",
                tx_hash_normalized,
                property_id,
            )

        return {
            "status": "ok",
            "rent_payment_id": int(rent_payment["id"]),
            "distribution_id": int(distribution["id"]) if distribution else None,
            "amount_wei": str(amount_wei),
            "amount_eth": amount_eth,
            "investors_paid": investor_count,
            "total_distributed_wei": (
                str(distribution["total_distributed"]) if distribution else "0"
            ),
            "tx_hash": payload.tx_hash,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/tenant/payment-history/{wallet_address}", response_model=list[RentPaymentRead])
def tenant_payment_history(
    wallet_address: str,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("tenant", "property_owner")),
):
    web3 = get_web3()
    if not web3.is_address(wallet_address):
        raise HTTPException(status_code=400, detail="Invalid wallet")
    _enforce_self_or_property_owner(user, wallet_address)
    checksum = web3.to_checksum_address(wallet_address)
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT rp.*, p.name AS property_name, t.wallet_address AS tenant_wallet "
            "FROM rent_payments rp "
            "JOIN tenants t ON t.id = rp.tenant_id "
            "JOIN properties p ON p.id = rp.property_id "
            "WHERE LOWER(t.wallet_address) = LOWER(%s) "
            "ORDER BY rp.payment_date DESC",
            (checksum,),
        )
        rows = cursor.fetchall()
        for r in rows:
            r["payment_date"] = (
                r["payment_date"].isoformat() if r.get("payment_date") else ""
            )
        return rows
    finally:
        cursor.close()


@router.get("/tenant/active-rentals/{wallet_address}")
def tenant_active_rentals(
    wallet_address: str,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("tenant", "property_owner")),
):
    web3 = get_web3()
    if not web3.is_address(wallet_address):
        raise HTTPException(status_code=400, detail="Invalid wallet")
    _enforce_self_or_property_owner(user, wallet_address)
    checksum = web3.to_checksum_address(wallet_address)
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT tr.*, p.name AS property_name, p.location "
            "FROM tenant_rentals tr "
            "JOIN tenants t ON t.id = tr.tenant_id "
            "JOIN properties p ON p.id = tr.property_id "
            "WHERE LOWER(t.wallet_address) = LOWER(%s) AND tr.status = 'active' "
            "ORDER BY tr.created_at DESC",
            (checksum,),
        )
        rows = cursor.fetchall()
        for r in rows:
            if r.get("rental_start_date"):
                r["rental_start_date"] = r["rental_start_date"].isoformat()
            if r.get("rental_end_date"):
                r["rental_end_date"] = r["rental_end_date"].isoformat()
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            period = _tenant_rent_period_status(cursor, int(r["tenant_id"]), int(r["property_id"]))
            r.update(serialize_period_fields(period))
        return rows
    finally:
        cursor.close()


@router.get("/tenant/preview-distribution/{property_id}")
def preview_rent_distribution(property_id: int, db=Depends(get_db)):
    """READ-ONLY preview of how rent would be split among investors.

    Does NOT perform any on-chain sync. Falls back to a DB-based computation
    when the on-chain view function is unavailable.
    """
    cursor = db.cursor(dictionary=True)
    try:
        property_item = fetch_property(cursor, property_id)
        if not property_item:
            raise HTTPException(status_code=404, detail="Property not found")
        require_property_token(property_item)

        rent_wei = int(property_item.get("monthly_rent_wei") or 0)
        try:
            info = get_rent_property_info(property_id)
            rent_wei = int(info.get("monthly_rent_wei") or rent_wei)
        except Exception:
            pass

        if rent_wei == 0:
            raise HTTPException(status_code=400, detail="Rent not set")

        try:
            breakdown = calculate_rent_distribution(property_id, rent_wei)
        except Exception:
            breakdown = build_rent_distribution_preview_from_db(
                cursor, property_id, rent_wei
            )

        return {
            "property_id": property_id,
            "property_name": property_item["name"],
            "monthly_rent_wei": str(rent_wei),
            "monthly_rent_eth": str(from_wei(rent_wei)),
            "investor_count": len(breakdown),
            "breakdown": breakdown,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


# ══════════════════════════════════════════════════════════════════════
#  INVESTOR
# ══════════════════════════════════════════════════════════════════════

@router.post("/rewards/prepare-claim", response_model=ClaimRewardsPrepareResponse)
def prepare_claim_rewards(
    payload: ClaimRewardsPrepareRequest,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("investor", "property_owner")),
):
    web3 = get_web3()
    if not web3.is_address(payload.investor_wallet):
        raise HTTPException(status_code=400, detail="Invalid wallet")
    _enforce_self_or_property_owner(user, payload.investor_wallet)
    checksum = web3.to_checksum_address(payload.investor_wallet)
    cursor = db.cursor(dictionary=True)
    try:
        property_item = fetch_property(cursor, payload.property_id)
        if not property_item:
            raise HTTPException(status_code=404, detail="Property not found")

        claimable_wei = int(get_property_claimable_rewards(payload.property_id, checksum))
        if claimable_wei <= 0:
            cursor.execute(
                "SELECT COALESCE(SUM(CAST(payout_amount_wei AS DECIMAL(36,0))), 0) AS pending "
                "FROM investor_rent_payouts WHERE property_id = %s AND LOWER(investor_wallet) = LOWER(%s) "
                "AND COALESCE(claim_status, 'claimable') = 'claimable'",
                (payload.property_id, checksum),
            )
            db_pending = int(cursor.fetchone()["pending"] or 0)
            if db_pending > 0:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Indexed payouts show claimable rent in the database, but the RentDistribution "
                        "contract reports 0 for this wallet and property. Confirm you are using the same "
                        "wallet as in investor_rent_payouts, then check propertyClaimableRewards on-chain; "
                        "if rewards were already claimed, reconcile may not have updated rows yet."
                    ),
                )
            raise HTTPException(status_code=400, detail="No claimable rewards for this property")

        return ClaimRewardsPrepareResponse(
            property_id=payload.property_id,
            property_name=property_item["name"],
            investor_wallet=checksum,
            claimable_amount_wei=str(claimable_wei),
            claimable_amount_eth=str(from_wei(claimable_wei)),
            rent_contract_address=get_rent_distribution_address(),
            calldata=encode_claim_rewards(payload.property_id),
            chain_id=web3.eth.chain_id,
        )
    finally:
        cursor.close()


@router.post("/rewards/confirm-claim", response_model=ClaimRewardsConfirmResponse)
def confirm_claim_rewards(
    payload: ClaimRewardsConfirmRequest,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("investor", "property_owner")),
):
    web3 = get_web3()
    if not web3.is_address(payload.investor_wallet):
        raise HTTPException(status_code=400, detail="Invalid wallet")
    _enforce_self_or_property_owner(user, payload.investor_wallet)
    checksum = web3.to_checksum_address(payload.investor_wallet)
    cursor = db.cursor(dictionary=True)
    try:
        property_item = fetch_property(cursor, payload.property_id)
        if not property_item:
            raise HTTPException(status_code=404, detail="Property not found")

        receipt = wait_for_transaction_receipt(payload.tx_hash, timeout=120, poll_latency=1)
        if not receipt or receipt.get("status") != 1:
            raise HTTPException(status_code=400, detail="Transaction not confirmed or reverted")

        tx = get_transaction(payload.tx_hash)
        tx_from = web3.to_checksum_address(tx.get("from"))
        if tx_from != checksum:
            raise HTTPException(status_code=400, detail="Transaction sender does not match investor wallet")

        rent_contract_addr = get_rent_distribution_address()
        tx_to = tx.get("to")
        if not tx_to or web3.to_checksum_address(tx_to) != web3.to_checksum_address(rent_contract_addr):
            raise HTTPException(status_code=400, detail="Transaction not sent to RentDistribution contract")

        tx_hash_normalized = tx["hash"].to_0x_hex()
        rent_contract = get_contract("RentDistribution", rent_contract_addr)
        claim_events = decode_contract_events_from_receipt(rent_contract, "RewardsClaimed", receipt)
        matching_claims = [
            event for event in claim_events
            if int(event["args"]["propertyId"]) == int(payload.property_id)
            and web3.to_checksum_address(event["args"]["investor"]) == checksum
        ]
        if not matching_claims:
            raise HTTPException(status_code=400, detail="No matching RewardsClaimed event found in transaction receipt")

        claimed_amount_wei = sum(int(event["args"]["amount"]) for event in matching_claims)
        reconcile_transaction(tx_hash_normalized)

        cursor.execute(
            "SELECT COUNT(*) AS claimed_rows "
            "FROM investor_rent_payouts "
            "WHERE property_id = %s AND LOWER(investor_wallet) = LOWER(%s) AND LOWER(claim_tx_hash) = LOWER(%s)",
            (payload.property_id, checksum, tx_hash_normalized),
        )
        row = cursor.fetchone()
        claimed_rows = int(row["claimed_rows"] or 0)
        if claimed_rows <= 0:
            raise HTTPException(status_code=500, detail="Claim reconciliation incomplete after confirmation")

        return ClaimRewardsConfirmResponse(
            status="ok",
            property_id=payload.property_id,
            investor_wallet=checksum,
            claim_tx_hash=tx_hash_normalized,
            claimed_amount_wei=str(claimed_amount_wei),
            claimed_amount_eth=str(from_wei(claimed_amount_wei)),
            claimed_rows=claimed_rows,
        )
    finally:
        cursor.close()


@router.get("/rewards/claimable/{wallet_address}", response_model=ClaimableRewardsSummaryRead)
def reward_claimable_summary(
    wallet_address: str,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("investor", "property_owner")),
):
    web3 = get_web3()
    if not web3.is_address(wallet_address):
        raise HTTPException(status_code=400, detail="Invalid wallet")
    _enforce_self_or_property_owner(user, wallet_address)
    checksum = web3.to_checksum_address(wallet_address)
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT irp.property_id, p.name AS property_name, "
            "COALESCE(SUM(CAST(irp.payout_amount_wei AS DECIMAL(36,0))), 0) AS claimable_wei, "
            "COUNT(*) AS pending_payouts, MAX(irp.distributed_at) AS last_distributed_at "
            "FROM investor_rent_payouts irp "
            "JOIN properties p ON p.id = irp.property_id "
            "WHERE LOWER(irp.investor_wallet) = LOWER(%s) AND COALESCE(irp.claim_status, 'claimable') = 'claimable' "
            "GROUP BY irp.property_id, p.name "
            "ORDER BY MAX(irp.distributed_at) DESC",
            (checksum,),
        )
        rows = cursor.fetchall()
        properties = []
        for row in rows:
            db_wei = int(row["claimable_wei"] or 0)
            chain_wei: int | None = None
            try:
                chain_wei = int(get_property_claimable_rewards(int(row["property_id"]), checksum))
            except Exception as exc:
                LOGGER.warning(
                    "reward_claimable_summary stage=chain_read_failed property_id=%s wallet=%s err=%s",
                    row["property_id"],
                    checksum,
                    exc,
                )
            # Do not replace accurate DB aggregates with chain=0 (RPC lag, wrong archive node,
            # or transient eth_call failures). Chain wins when it reports a positive balance.
            effective_wei = chain_wei if chain_wei is not None and chain_wei > 0 else db_wei
            properties.append({
                "property_id": int(row["property_id"]),
                "property_name": row.get("property_name"),
                "claimable_amount_wei": str(effective_wei),
                "claimable_amount_eth": str(from_wei(effective_wei)),
                "pending_payouts": int(row["pending_payouts"] or 0),
                "last_distributed_at": row["last_distributed_at"].isoformat() if row.get("last_distributed_at") else None,
            })

        # Indexer rows can lag behind on-chain accruals after payRent; surface claim per property from chain.
        seen_property_ids = {int(p["property_id"]) for p in properties}
        cursor.execute(
            "SELECT DISTINCT t.property_id, p.name AS property_name "
            "FROM token_ownerships t "
            "JOIN users u ON u.id = t.user_id "
            "JOIN properties p ON p.id = t.property_id "
            "WHERE LOWER(u.wallet_address) = LOWER(%s) AND t.token_amount > 0",
            (checksum,),
        )
        for row in cursor.fetchall():
            pid = int(row["property_id"])
            if pid in seen_property_ids:
                continue
            try:
                chain_wei = int(get_property_claimable_rewards(pid, checksum))
            except Exception:
                continue
            if chain_wei <= 0:
                continue
            properties.append({
                "property_id": pid,
                "property_name": row.get("property_name"),
                "claimable_amount_wei": str(chain_wei),
                "claimable_amount_eth": str(from_wei(chain_wei)),
                "pending_payouts": 1,
                "last_distributed_at": None,
            })
            seen_property_ids.add(pid)

        cursor.execute(
            "SELECT COALESCE(SUM(CAST(payout_amount_wei AS DECIMAL(36,0))), 0) AS total_claimed_wei "
            "FROM investor_rent_payouts WHERE LOWER(investor_wallet) = LOWER(%s) AND claim_status = 'claimed'",
            (checksum,),
        )
        claimed_row = cursor.fetchone()
        total_claimed_wei_db = int(claimed_row["total_claimed_wei"] or 0)

        summed_properties_wei = sum(int(p["claimable_amount_wei"]) for p in properties)
        try:
            chain_global_claimable = int(get_claimable_rewards(checksum))
        except Exception as exc:
            LOGGER.warning("reward_claimable_summary stage=global_claimable_failed wallet=%s err=%s", checksum, exc)
            chain_global_claimable = 0
        total_claimable_wei = max(summed_properties_wei, chain_global_claimable)

        try:
            chain_global_claimed = int(get_total_claimed_rewards(checksum))
        except Exception:
            chain_global_claimed = 0
        total_claimed_wei = max(total_claimed_wei_db, chain_global_claimed)
        return ClaimableRewardsSummaryRead(
            wallet_address=checksum,
            total_claimable_wei=str(total_claimable_wei),
            total_claimable_eth=str(from_wei(total_claimable_wei)),
            total_claimed_wei=str(total_claimed_wei),
            total_claimed_eth=str(from_wei(total_claimed_wei)),
            properties=properties,
        )
    finally:
        cursor.close()


@router.get("/rewards/history/{wallet_address}", response_model=list[RewardClaimHistoryRead])
def reward_claim_history(
    wallet_address: str,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("investor", "property_owner")),
):
    web3 = get_web3()
    if not web3.is_address(wallet_address):
        raise HTTPException(status_code=400, detail="Invalid wallet")
    _enforce_self_or_property_owner(user, wallet_address)
    checksum = web3.to_checksum_address(wallet_address)
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT irp.property_id, p.name AS property_name, irp.claim_tx_hash, "
            "COALESCE(SUM(CAST(irp.payout_amount_wei AS DECIMAL(36,0))), 0) AS claimed_amount_wei, "
            "COUNT(*) AS payout_count, MAX(irp.claimed_at) AS claimed_at "
            "FROM investor_rent_payouts irp "
            "JOIN properties p ON p.id = irp.property_id "
            "WHERE LOWER(irp.investor_wallet) = LOWER(%s) AND irp.claim_status = 'claimed' AND irp.claim_tx_hash IS NOT NULL "
            "GROUP BY irp.property_id, p.name, irp.claim_tx_hash "
            "ORDER BY MAX(irp.claimed_at) DESC",
            (checksum,),
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            claimed_amount_wei = int(row["claimed_amount_wei"] or 0)
            result.append({
                "property_id": int(row["property_id"]),
                "property_name": row.get("property_name"),
                "claim_tx_hash": row["claim_tx_hash"],
                "claimed_amount_wei": str(claimed_amount_wei),
                "claimed_amount_eth": str(from_wei(claimed_amount_wei)),
                "payout_count": int(row["payout_count"] or 0),
                "claimed_at": row["claimed_at"].isoformat() if row.get("claimed_at") else "",
            })
        return result
    finally:
        cursor.close()


@router.get("/investor/rental-earnings/{wallet_address}", response_model=list[InvestorPayoutRead])
def investor_rental_earnings(
    wallet_address: str,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("investor", "property_owner")),
):
    web3 = get_web3()
    if not web3.is_address(wallet_address):
        raise HTTPException(status_code=400, detail="Invalid wallet")
    _enforce_self_or_property_owner(user, wallet_address)
    checksum = web3.to_checksum_address(wallet_address)
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT irp.*, p.name AS property_name "
            "FROM investor_rent_payouts irp "
            "JOIN properties p ON p.id = irp.property_id "
            "WHERE LOWER(irp.investor_wallet) = LOWER(%s) "
            "ORDER BY irp.distributed_at DESC",
            (checksum,),
        )
        rows = cursor.fetchall()
        for r in rows:
            r["distributed_at"] = (
                r["distributed_at"].isoformat() if r.get("distributed_at") else ""
            )
            if r.get("claimed_at"):
                r["claimed_at"] = r["claimed_at"].isoformat()
        return rows
    finally:
        cursor.close()


@router.get("/investor/distributions/{wallet_address}")
def investor_distributions(
    wallet_address: str,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("investor", "property_owner")),
):
    web3 = get_web3()
    if not web3.is_address(wallet_address):
        raise HTTPException(status_code=400, detail="Invalid wallet")
    _enforce_self_or_property_owner(user, wallet_address)
    checksum = web3.to_checksum_address(wallet_address)
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT irp.property_id, p.name AS property_name, "
            "SUM(CAST(irp.payout_amount_wei AS DECIMAL(36,0))) AS total_earned_wei, "
            "COUNT(*) AS payment_count, "
            "MAX(irp.ownership_percentage) AS current_ownership "
            "FROM investor_rent_payouts irp "
            "JOIN properties p ON p.id = irp.property_id "
            "WHERE LOWER(irp.investor_wallet) = LOWER(%s) "
            "GROUP BY irp.property_id, p.name "
            "ORDER BY total_earned_wei DESC",
            (checksum,),
        )
        rows = cursor.fetchall()
        for r in rows:
            r["total_earned_wei"] = str(int(r["total_earned_wei"] or 0))
            r["total_earned_eth"] = str(from_wei(int(r["total_earned_wei"] or 0)))
        return rows
    finally:
        cursor.close()


@router.get("/investor/yield-summary/{wallet_address}")
def investor_yield_summary(
    wallet_address: str,
    db=Depends(get_db),
    user: AuthUser = Depends(require_role("investor", "property_owner")),
):
    web3 = get_web3()
    if not web3.is_address(wallet_address):
        raise HTTPException(status_code=400, detail="Invalid wallet")
    _enforce_self_or_property_owner(user, wallet_address)
    checksum = web3.to_checksum_address(wallet_address)
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT COALESCE(SUM(CAST(payout_amount_wei AS DECIMAL(36,0))), 0) AS total_earned_wei, "
            "COUNT(*) AS total_payouts "
            "FROM investor_rent_payouts WHERE LOWER(investor_wallet) = LOWER(%s)",
            (checksum,),
        )
        row = cursor.fetchone()
        total_wei = int(row["total_earned_wei"] or 0)

        cursor.execute(
            "SELECT COUNT(DISTINCT property_id) AS properties "
            "FROM investor_rent_payouts WHERE LOWER(investor_wallet) = LOWER(%s)",
            (checksum,),
        )
        props = cursor.fetchone()

        cursor.execute(
            "SELECT COALESCE(SUM(CAST(payout_amount_wei AS DECIMAL(36,0))), 0) AS total_claimable_wei "
            "FROM investor_rent_payouts WHERE LOWER(investor_wallet) = LOWER(%s) AND COALESCE(claim_status, 'claimable') = 'claimable'",
            (checksum,),
        )
        claimable = cursor.fetchone()

        cursor.execute(
            "SELECT COALESCE(SUM(CAST(payout_amount_wei AS DECIMAL(36,0))), 0) AS total_claimed_wei "
            "FROM investor_rent_payouts WHERE LOWER(investor_wallet) = LOWER(%s) AND claim_status = 'claimed'",
            (checksum,),
        )
        claimed = cursor.fetchone()

        total_claimable_wei_db = int(claimable["total_claimable_wei"] or 0)
        total_claimed_wei_db = int(claimed["total_claimed_wei"] or 0)
        try:
            chain_claimable = int(get_claimable_rewards(checksum))
        except Exception:
            chain_claimable = 0
        total_claimable_wei = max(total_claimable_wei_db, chain_claimable)
        try:
            chain_claimed = int(get_total_claimed_rewards(checksum))
        except Exception:
            chain_claimed = 0
        total_claimed_wei = max(total_claimed_wei_db, chain_claimed)

        return {
            "total_earned_wei": str(total_wei),
            "total_earned_eth": str(from_wei(total_wei)),
            "total_payouts": int(row["total_payouts"] or 0),
            "properties_earning": int(props["properties"] or 0),
            "total_claimable_wei": str(total_claimable_wei),
            "total_claimable_eth": str(from_wei(total_claimable_wei)),
            "total_claimed_wei": str(total_claimed_wei),
            "total_claimed_eth": str(from_wei(total_claimed_wei)),
        }
    finally:
        cursor.close()
