"""Properties + per-property property-owner endpoints (deploy-token, mint-nft, issue, transfer, verify)."""
import asyncio
import json
import logging
from decimal import Decimal
from typing import Any, AsyncIterator, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from psycopg2.extras import Json

from backend.api._helpers import (
    add_transaction_row,
    create_property_record,
    deploy_property_token,
    enrich_property_with_supply,
    ensure_security_token_sale_inventory,
    fetch_property,
    find_existing_property,
    property_is_owned_by,
    get_total_minted_base,
    lock_property,
    property_needs_token_deployment,
    require_property_token,
    sync_rent_chain_for_new_property,
    validate_monthly_rent_for_chain,
)

LOGGER = logging.getLogger(__name__)
from backend.api.deps import get_db, get_optional_user, require_property_owner
from backend.api.schemas import (
    IssueTokensRequest,
    MintNFTRequest,
    PropertyCreate,
    PropertyRead,
    TransferTokensRequest,
)
from backend.config.settings import TOKEN_DECIMALS, load_contract_addresses
from backend.services.blockchain import (
    from_wei,
    get_contract,
    get_erc20_balance,
    mint_property_nft,
    mint_security_tokens,
    set_whitelist,
    to_base_units,
    to_wei,
    transfer_security_tokens,
)
from backend.services.blockchain_indexer import reconcile_transaction
from backend.services.auth import AuthUser, normalize_address

router = APIRouter()


def _token_sale_price_eth(payload: PropertyCreate) -> Decimal:
    if payload.token_supply <= 0:
        raise HTTPException(status_code=400, detail="token_supply must be > 0")
    if payload.total_value <= 0:
        raise HTTPException(status_code=400, detail="total_value must be > 0")
    price = payload.total_value / payload.token_supply
    if price <= 0:
        raise HTTPException(status_code=400, detail="token_sale_price_eth must be > 0")
    return price


def _finalize_step_deploy_token(db, property_id: int) -> None:
    cursor = db.cursor(dictionary=True)
    try:
        prop = lock_property(cursor, property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        deploy_property_token(cursor, prop, property_id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Property was saved but setup failed while deploying token: {exc}",
        ) from exc
    finally:
        cursor.close()


def _finalize_step_finalize_inventory(db, property_id: int) -> None:
    cursor = db.cursor(dictionary=True)
    try:
        prop = lock_property(cursor, property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        ensure_security_token_sale_inventory(prop)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Property was saved but setup failed while finalizing sale inventory: {exc}",
        ) from exc
    finally:
        cursor.close()


def _finalize_step_sync_rent(db, property_id: int) -> None:
    cursor = db.cursor(dictionary=True)
    try:
        prop = lock_property(cursor, property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        sync_rent_chain_for_new_property(cursor, prop, property_id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Property was saved but setup failed while syncing rent chain: {exc}",
        ) from exc
    finally:
        cursor.close()


def _finalize_new_property(db, property_id: int) -> None:
    """Run the standard 3-stage finalize pipeline after a property INSERT.

    Kept as a single sync entrypoint for the non-streaming POST /properties
    handler. The streaming variant calls each ``_finalize_step_*`` helper
    individually so it can yield SSE progress between stages.
    """
    _finalize_step_deploy_token(db, property_id)
    _finalize_step_finalize_inventory(db, property_id)
    _finalize_step_sync_rent(db, property_id)


def _property_has_activity(cursor, property_item: dict) -> bool:
    if property_item.get("token_address") or property_item.get("nft_token_id"):
        return True
    property_id = int(property_item["id"])
    queries = [
        "SELECT 1 FROM token_ownerships WHERE property_id = %s AND token_amount > 0 LIMIT 1",
        "SELECT 1 FROM investments WHERE property_id = %s LIMIT 1",
        "SELECT 1 FROM transactions WHERE property_id = %s LIMIT 1",
        "SELECT 1 FROM rent_payments WHERE property_id = %s LIMIT 1",
        "SELECT 1 FROM rent_distributions WHERE property_id = %s LIMIT 1",
        "SELECT 1 FROM investor_rent_payouts WHERE property_id = %s LIMIT 1",
    ]
    for query in queries:
        cursor.execute(query, (property_id,))
        if cursor.fetchone():
            return True
    return False


def _assert_owner(user: AuthUser, property_item: dict) -> None:
    owner = normalize_address(property_item.get("owner_wallet") or "")
    if not owner:
        raise HTTPException(status_code=403, detail="Property owner not assigned.")
    if not property_is_owned_by(property_item, user.wallet_address):
        raise HTTPException(status_code=403, detail="You can only modify properties you own.")


@router.post("/properties", response_model=PropertyRead)
def create_property(
    payload: PropertyCreate,
    user: AuthUser = Depends(require_property_owner),
    db=Depends(get_db),
):
    """Create a property and run the standard on-chain setup pipeline.

    After the DB row is inserted, ``_finalize_new_property`` deploys the SecurityToken,
    repairs sale inventory, and syncs rent chain state when monthly rent is set.
    """
    try:
        return create_property_record(db, user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _sse(event: dict[str, Any]) -> str:
    """Format a JSON dict as a single Server-Sent-Event line."""
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/properties/stream")
async def create_property_stream(
    payload: PropertyCreate,
    user: AuthUser = Depends(require_property_owner),
    db=Depends(get_db),
):
    """SSE-stream variant of ``POST /properties``.

    Emits one ``{"step": "..."}`` event before each stage so the UI can
    light up the matching row on the progress card. Steps in order:
        creating          → DB insert started
        created           → DB insert finished, property_id known
        deploying_token   → SecurityToken deploy in flight
        token_deployed    → token deploy committed
        finalizing_inventory → ensure_security_token_sale_inventory
        inventory_done    → inventory committed
        syncing_rent      → sync_rent_amount_to_contract
        rent_synced       → rent commit done
        done              → final property row attached
        error             → terminal error; ``detail`` carries the message
        duplicate         → idempotent path: existing property returned
    """
    # Eagerly validate so the client gets a 400 (not an empty stream) for
    # bad input.
    if payload.token_supply <= 0:
        raise HTTPException(status_code=400, detail="token_supply must be > 0")

    token_price_wei = str(to_wei(_token_sale_price_eth(payload)))
    monthly_rent_wei = (
        str(to_wei(payload.monthly_rent_eth)) if payload.monthly_rent_eth is not None else None
    )
    owner_wallet = normalize_address(user.wallet_address)

    # Fail fast before token deploy / mint when rent exceeds the on-chain cap.
    rent_wei_for_create = 0
    if monthly_rent_wei not in (None, "", "0"):
        try:
            rent_wei_for_create = int(monthly_rent_wei)
        except (TypeError, ValueError):
            rent_wei_for_create = 0
        if rent_wei_for_create > 0:
            validate_monthly_rent_for_chain(rent_wei_for_create)

    async def gen() -> AsyncIterator[str]:
        property_id: int | None = None
        cursor = db.cursor(dictionary=True)
        try:
            existing = find_existing_property(
                cursor, payload, token_price_wei, monthly_rent_wei, owner_wallet
            )
            if existing:
                if property_needs_token_deployment(existing):
                    property_id = int(existing["id"])
                    yield _sse({"step": "created", "property_id": property_id, "resuming_setup": True})
                else:
                    final = enrich_property_with_supply(cursor, existing, viewer=user)
                    yield _sse({"step": "done", "duplicate": True, "property": _json_safe_property(final)})
                    return

            yield _sse({"step": "creating"})
            cursor.execute(
                "INSERT INTO properties (name, location, total_value, token_supply, token_symbol, "
                "token_price_base, monthly_rent_wei, owner_wallet, images) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    payload.name, payload.location, payload.total_value,
                    payload.token_supply, payload.token_symbol,
                    token_price_wei, monthly_rent_wei, owner_wallet, Json(payload.images),
                ),
            )
            property_id = int(cursor.fetchone()["id"])
            db.commit()
            yield _sse({"step": "created", "property_id": property_id})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            LOGGER.exception("create_property_stream insert failed")
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)[:300]
            yield _sse({"step": "error", "detail": str(detail)})
            return
        finally:
            cursor.close()

        # Each stage runs in a worker thread because the underlying RPC
        # calls are blocking. We yield the *intent* event before kicking
        # off the thread so the UI advances right away, and the *done*
        # event after — which lets the client mark the row as completed.
        def _rent_sync_skippable(exc: HTTPException) -> str | None:
            detail = exc.detail
            if isinstance(detail, dict):
                if detail.get("code") == "DEPLOYER_CONTRACT_MISMATCH":
                    return str(detail.get("message") or detail)
                return None
            text = str(detail)
            if "rent amount too high" in text.lower() or "exceeds the on-chain limit" in text.lower():
                return text
            if "DEPLOYER_CONTRACT_MISMATCH" in text or "not the owner" in text or "Ownable" in text:
                return text
            return None

        async def run_stage(
            intent: str,
            completed: str,
            work: Callable[[], None],
            *,
            allow_rent_sync_skip: bool = False,
        ):
            yield _sse({"step": intent})
            try:
                await asyncio.to_thread(work)
            except HTTPException as exc:
                skip_msg = _rent_sync_skippable(exc) if allow_rent_sync_skip else None
                if skip_msg:
                    LOGGER.warning("create_property_stream stage %s skipped: %s", intent, skip_msg)
                    yield _sse({"step": "rent_sync_skipped", "detail": skip_msg})
                    yield _sse({"step": "rent_synced"})
                    return
                LOGGER.warning("create_property_stream stage %s failed: %s", intent, exc.detail)
                yield _sse({"step": "error", "detail": str(exc.detail)})
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("create_property_stream stage %s failed", intent)
                yield _sse({"step": "error", "detail": str(exc)[:300]})
                raise
            yield _sse({"step": completed})

        try:
            async for ev in run_stage("deploying_token", "token_deployed",
                                      lambda: _finalize_step_deploy_token(db, property_id)):
                yield ev
            async for ev in run_stage("finalizing_inventory", "inventory_done",
                                      lambda: _finalize_step_finalize_inventory(db, property_id)):
                yield ev

            # Fast path: no monthly rent — skip blocking RPC work entirely.
            if rent_wei_for_create <= 0:
                yield _sse({"step": "syncing_rent"})
                yield _sse({"step": "rent_synced"})
            else:
                async for ev in run_stage(
                    "syncing_rent",
                    "rent_synced",
                    lambda: _finalize_step_sync_rent(db, property_id),
                    allow_rent_sync_skip=True,
                ):
                    yield ev
        except Exception:
            return  # error event was already yielded inside run_stage

        cursor = db.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
            final = enrich_property_with_supply(cursor, cursor.fetchone(), viewer=user)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("create_property_stream final fetch failed")
            yield _sse({"step": "error", "detail": str(exc)[:300]})
            return
        finally:
            cursor.close()

        yield _sse({"step": "done", "property": _json_safe_property(final)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            # Disable proxy buffering — we want each chunk to flush
            # immediately so the UI updates as soon as the backend stage
            # transitions on-chain.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _json_safe_property(prop: dict[str, Any]) -> dict[str, Any]:
    """Convert Decimal / datetime values in a property row to JSON primitives."""
    out: dict[str, Any] = {}
    for k, v in (prop or {}).items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


@router.get("/properties", response_model=list[PropertyRead])
def list_properties(
    db=Depends(get_db),
    user: Optional[AuthUser] = Depends(get_optional_user),
):
    """List active properties.

    All property owners see every listing. ``apply_property_visibility`` clears
    ``owner_wallet`` on rows the viewer does not own so the admin UI hides
    edit/delete without blocking catalog visibility.
    """
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM properties WHERE COALESCE(is_active, TRUE) = TRUE ORDER BY id DESC",
        )
        rows = cursor.fetchall()
        return [enrich_property_with_supply(cursor, row, viewer=user) for row in rows]
    finally:
        cursor.close()


@router.get("/properties/{property_id}", response_model=PropertyRead)
def get_property(
    property_id: int,
    db=Depends(get_db),
    user: Optional[AuthUser] = Depends(get_optional_user),
):
    cursor = db.cursor(dictionary=True)
    try:
        property_item = fetch_property(cursor, property_id)
        if not property_item:
            raise HTTPException(status_code=404, detail="Property not found")
        return enrich_property_with_supply(cursor, property_item, viewer=user)
    finally:
        cursor.close()


@router.put("/properties/{property_id}", response_model=PropertyRead)
def update_property(
    property_id: int,
    payload: PropertyCreate,
    user: AuthUser = Depends(require_property_owner),
    db=Depends(get_db),
):
    """Update a property record. DB-only.

    token_sale_price_eth is rejected if the SecurityToken is already deployed
    (the on-chain sale price is immutable after deploy).
    """
    cursor = db.cursor(dictionary=True)
    try:
        prop = lock_property(cursor, property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        _assert_owner(user, prop)

        new_price_wei = (
            str(prop.get("token_price_base") or "")
            if prop.get("token_address")
            else str(to_wei(_token_sale_price_eth(payload)))
        )
        if prop.get("token_address") and (prop.get("token_price_base") or "") != new_price_wei:
            raise HTTPException(
                status_code=400,
                detail="Cannot change token_sale_price_eth after the SecurityToken contract is deployed.",
            )

        monthly_rent_wei = (
            str(to_wei(payload.monthly_rent_eth)) if payload.monthly_rent_eth is not None else None
        )

        cursor.execute(
            "UPDATE properties SET name = %s, location = %s, total_value = %s, token_supply = %s, "
            "token_symbol = %s, token_price_base = %s, monthly_rent_wei = %s, images = %s WHERE id = %s",
            (
                payload.name, payload.location, payload.total_value,
                payload.token_supply, payload.token_symbol,
                new_price_wei, monthly_rent_wei, Json(payload.images), property_id,
            ),
        )
        db.commit()
        cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
        return enrich_property_with_supply(cursor, cursor.fetchone(), viewer=user)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.delete("/properties/{property_id}")
def delete_or_archive_property(
    property_id: int,
    user: AuthUser = Depends(require_property_owner),
    db=Depends(get_db),
):
    cursor = db.cursor(dictionary=True)
    try:
        prop = lock_property(cursor, property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        _assert_owner(user, prop)

        if _property_has_activity(cursor, prop):
            cursor.execute("UPDATE properties SET is_active = FALSE WHERE id = %s", (property_id,))
            mode = "archived"
        else:
            cursor.execute("DELETE FROM properties WHERE id = %s", (property_id,))
            mode = "deleted"

        db.commit()
        return {"status": "ok", "property_id": property_id, "mode": mode}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.post(
    "/properties/{property_id}/deploy-token",
    response_model=PropertyRead,
)
def deploy_property_token_endpoint(
    property_id: int,
    user: AuthUser = Depends(require_property_owner),
    db=Depends(get_db),
):
    """Explicit admin action: deploy the SecurityToken contract for this property.

    Idempotent — if an investable token already exists for the property, returns it.
    """
    cursor = db.cursor(dictionary=True)
    try:
        prop = lock_property(cursor, property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        _assert_owner(user, prop)

        prop = deploy_property_token(cursor, prop, property_id)
        db.commit()

        cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
        return enrich_property_with_supply(cursor, cursor.fetchone(), viewer=user)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Token deployment failed: {e}")
    finally:
        cursor.close()


@router.post(
    "/properties/{property_id}/repair-sale-inventory",
    response_model=PropertyRead,
)
def repair_sale_inventory(
    property_id: int,
    user: AuthUser = Depends(require_property_owner),
    db=Depends(get_db),
):
    """Mint the full token supply onto the SecurityToken contract when on-chain totalSupply is zero.

    Primary sale pulls from ``balanceOf(tokenContract)``. Use this if deployment succeeded but the
    initial mint to the sale pool never landed (RPC/gas issues). No-op when ``totalSupply() > 0``.
    """
    cursor = db.cursor(dictionary=True)
    try:
        prop = lock_property(cursor, property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        _assert_owner(user, prop)
        require_property_token(prop)
        ensure_security_token_sale_inventory(prop)
        db.commit()
        cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
        return enrich_property_with_supply(cursor, cursor.fetchone(), viewer=user)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/properties/{property_id}/verify-contract")
def verify_contract(property_id: int, db=Depends(get_db)):
    """Verify the token contract is properly deployed and responsive."""
    cursor = db.cursor(dictionary=True)
    try:
        property_item = fetch_property(cursor, property_id)
        if not property_item:
            raise HTTPException(status_code=404, detail="Property not found")

        token_address = property_item.get("token_address")
        if not token_address:
            raise HTTPException(status_code=400, detail="Token contract not deployed yet")

        try:
            contract = get_contract("SecurityToken", token_address)
            prop_id = contract.functions.propertyId().call()
            sale_price_wei = contract.functions.salePricePerTokenWei().call()
            contract_balance = get_erc20_balance(contract, token_address)
            owner = contract.functions.owner().call()
            return {
                "token_address": token_address,
                "property_id_on_chain": int(prop_id),
                "sale_price_wei": str(sale_price_wei),
                "sale_price_eth": str(from_wei(int(sale_price_wei))),
                "contract_token_balance": str(contract_balance),
                "contract_token_balance_formatted": (
                    str(contract_balance / (10 ** 18)) if contract_balance else "0"
                ),
                "owner": owner,
                "token_supply_base": str(
                    to_base_units(Decimal(property_item["token_supply"]), TOKEN_DECIMALS)
                ),
                "status": "ok",
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Contract verification failed: {e}")
    finally:
        cursor.close()


@router.post(
    "/properties/{property_id}/mint-nft",
    response_model=PropertyRead,
)
def mint_nft(
    property_id: int,
    payload: MintNFTRequest,
    user: AuthUser = Depends(require_property_owner),
    db=Depends(get_db),
):
    cursor = db.cursor(dictionary=True)
    try:
        property_item = lock_property(cursor, property_id)
        if not property_item:
            raise HTTPException(status_code=404, detail="Property not found")
        _assert_owner(user, property_item)

        addresses = load_contract_addresses()
        property_nft_address = addresses.get("PropertyNFT")
        if not property_nft_address:
            raise HTTPException(status_code=400, detail="PropertyNFT not deployed")

        token_id, receipt = mint_property_nft(payload.to_address, payload.token_uri)
        cursor.execute(
            "UPDATE properties SET nft_token_id = %s, nft_contract_address = %s WHERE id = %s",
            (token_id, property_nft_address, property_id),
        )
        add_transaction_row(
            cursor,
            receipt.transactionHash.to_0x_hex(),
            "MINT_NFT",
            0,
            property_id,
            receipt.blockNumber,
            payload.to_address,
        )
        db.commit()
        cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
        return enrich_property_with_supply(cursor, cursor.fetchone(), viewer=user)
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


@router.post(
    "/properties/{property_id}/issue-tokens",
    response_model=PropertyRead,
)
def issue_tokens(
    property_id: int,
    payload: IssueTokensRequest,
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

        amount_base = to_base_units(payload.amount, TOKEN_DECIMALS)
        max_supply_base = to_base_units(Decimal(property_item["token_supply"]), TOKEN_DECIMALS)
        total_minted_base = get_total_minted_base(cursor, property_id)
        if total_minted_base + Decimal(amount_base) > Decimal(max_supply_base):
            raise HTTPException(status_code=400, detail="Token supply exceeded")

        set_whitelist(property_item["token_address"], payload.to_address, True)
        mint_receipt = mint_security_tokens(
            property_item["token_address"], payload.to_address, payload.amount
        )
        reconcile_transaction(mint_receipt.transactionHash.to_0x_hex())

        db.commit()
        cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
        return enrich_property_with_supply(cursor, cursor.fetchone(), viewer=user)
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


@router.post(
    "/properties/{property_id}/transfer",
    response_model=PropertyRead,
)
def transfer_tokens(
    property_id: int,
    payload: TransferTokensRequest,
    user: AuthUser = Depends(require_property_owner),
    db=Depends(get_db),
):
    cursor = db.cursor(dictionary=True)
    try:
        property_item = lock_property(cursor, property_id)
        if not property_item or not property_item.get("token_address"):
            raise HTTPException(status_code=404, detail="Property/token not found")
        _assert_owner(user, property_item)

        set_whitelist(property_item["token_address"], payload.to_address, True)
        transfer_receipt = transfer_security_tokens(
            property_item["token_address"], payload.to_address, payload.amount
        )
        reconcile_transaction(transfer_receipt.transactionHash.to_0x_hex())

        db.commit()
        cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
        return enrich_property_with_supply(cursor, cursor.fetchone(), viewer=user)
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
