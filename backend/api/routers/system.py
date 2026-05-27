"""System / infrastructure endpoints: health, status, config, dashboard, users."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import get_db, require_property_owner
from backend.api.schemas import DashboardSummary, UserRead
from backend.config.settings import (
    CHAIN_ID,
    DEPLOY_ENV,
    EXPECTED_CHAIN_HEX,
    load_contract_addresses,
)
from backend.services.blockchain import get_web3, platform_deployer_mismatch, rpc_is_healthy

router = APIRouter()


@router.get("/health")
def health(db=Depends(get_db)):
    db_ok = False
    rpc_ok = False
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    finally:
        try:
            if cursor is not None:
                cursor.close()
        except Exception:
            pass

    rpc_ok = rpc_is_healthy()

    # DB is critical; RPC failures are often transient (rate-limit, network).
    if not db_ok:
        raise HTTPException(status_code=503, detail={"database": db_ok, "rpc": rpc_ok})
    return {"status": "ok", "database": "ok", "rpc": "ok" if rpc_ok else "degraded"}


@router.get("/status")
def status(db=Depends(get_db)):
    db_status = "ok"
    rpc_status = "ok"
    indexer_status: dict = {}
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
    except Exception:
        db_status = "failed"
    finally:
        try:
            if cursor is not None:
                cursor.close()
        except Exception:
            pass

    try:
        rpc_status = "ok" if rpc_is_healthy() else "failed"
    except Exception:
        rpc_status = "failed"

    try:
        from backend.services.blockchain_indexer import get_indexer_status
        indexer_status = get_indexer_status()
    except Exception:
        indexer_status = {"running": False}

    deployer = platform_deployer_mismatch()

    return {
        "status": "ok" if db_status == "ok" and rpc_status == "ok" else "degraded",
        "database": db_status,
        "rpc": rpc_status,
        "indexer": indexer_status,
        "env": DEPLOY_ENV,
        "chain_id": CHAIN_ID,
        "expected_chain_hex": EXPECTED_CHAIN_HEX,
        "deployer_warning": deployer,
    }


@router.get("/config")
def config():
    return {
        "chainId": CHAIN_ID,
        "expectedChainHex": EXPECTED_CHAIN_HEX,
        "explorerTxBase": "https://sepolia.etherscan.io/tx/",
        "contracts": load_contract_addresses(),
        "env": DEPLOY_ENV,
        "deployerWarning": platform_deployer_mismatch(),
    }


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) AS properties_loaded FROM properties")
        properties_loaded = int(cursor.fetchone()["properties_loaded"] or 0)

        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN token_amount > 0 THEN token_amount ELSE 0 END), 0) "
            "AS total_token_holdings FROM token_ownerships"
        )
        total_token_holdings = Decimal(cursor.fetchone()["total_token_holdings"] or 0)

        cursor.execute(
            "SELECT COALESCE(SUM((CASE WHEN t.token_amount > 0 THEN t.token_amount ELSE 0 END) "
            "* (p.total_value / NULLIF(p.token_supply, 0))), 0) "
            "AS total_portfolio_value "
            "FROM token_ownerships t "
            "JOIN properties p ON p.id = t.property_id"
        )
        total_portfolio_value = Decimal(cursor.fetchone()["total_portfolio_value"] or 0)

        cursor.execute(
            "SELECT COALESCE(AVG(total_value / NULLIF(token_supply, 0)), 0) "
            "AS avg_min_spend_per_token FROM properties"
        )
        avg_min_spend_per_token = Decimal(cursor.fetchone()["avg_min_spend_per_token"] or 0)

        return DashboardSummary(
            total_portfolio_value=total_portfolio_value,
            total_token_holdings=total_token_holdings,
            properties_loaded=properties_loaded,
            avg_min_spend_per_token=avg_min_spend_per_token,
        )
    finally:
        cursor.close()


@router.get("/users", response_model=list[UserRead], dependencies=[Depends(require_property_owner)])
def list_users(db=Depends(get_db)):
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, wallet_address, email, kyc_status FROM users ORDER BY id ASC"
        )
        return cursor.fetchall()
    finally:
        cursor.close()
