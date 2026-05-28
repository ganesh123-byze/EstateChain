"""Investor copilot guards — keep chat advisory unless the user clearly requests a wallet action.

The LLM sometimes calls ``start_invest`` / ``start_claim_rewards`` during browse or Q&A
turns (e.g. "show marketplace", "what's my portfolio"). These helpers gate wallet UI
actions server-side so the frontend never opens invest/claim dialogs or MetaMask paths
by mistake.
"""
from __future__ import annotations

import re
from typing import Any

from backend.ai.schemas import AgentAction

_INVESTOR_WALLET_MODALS = frozenset({"INVEST_PROPERTY", "CLAIM_REWARDS"})

# Informational / browse phrasing — never open wallet UI when this matches alone.
_INFO_OR_BROWSE = re.compile(
    r"\b("
    r"how\s+(?:much|many|do|does|can|should|would|to)|"
    r"what(?:'s|\s+is|\s+are|\s+should|\s+can|\s+would)?|"
    r"which|where|when|why|who|"
    r"show\s+me|tell\s+me|list|summarize|summary|overview|"
    r"compare|best|worst|top|recommend|suggest|"
    r"explain|describe|help\s+me\s+understand|"
    r"marketplace|browse|available|opportunities|"
    r"portfolio|holdings|my\s+tokens|my\s+shares|"
    r"claimable|unclaimed|how\s+much\s+can\s+i\s+claim|"
    r"earned|yield|history|transactions?|activity|stats?"
    r")\b",
    re.IGNORECASE,
)

# Imperative buy / invest — user wants the invest dialog, not just research.
_INVEST_TRANSACTIONAL = re.compile(
    r"\b("
    r"(?:please\s+)?(?:buy|purchase)\s+(?:\d+\s+)?tokens?|"
    r"(?:please\s+)?invest\s+(?:\d+\s+)?(?:tokens?\s+)?(?:in|into)\b|"
    r"(?:please\s+)?invest\s+\d+\b|"
    r"open\s+(?:the\s+)?invest(?:ment)?\s+dialog|"
    r"i\s+want\s+to\s+(?:buy|invest)|"
    r"i(?:'d|\s+would)\s+like\s+to\s+(?:buy|invest)|"
    r"let(?:'s|\s+us)\s+invest|"
    r"start\s+investing\s+in|"
    r"put\s+money\s+into|"
    r"buy\s+into\b"
    r")\b",
    re.IGNORECASE,
)

# Imperative claim — user wants to withdraw yield, not just see amounts.
_CLAIM_TRANSACTIONAL = re.compile(
    r"\b("
    r"(?:please\s+)?claim\s+(?:my\s+)?(?:rewards|yield|rental\s+yield|earnings)|"
    r"(?:please\s+)?withdraw\s+(?:my\s+)?(?:rewards|yield)|"
    r"claim\s+(?:from|on|for)\b|"
    r"i\s+want\s+to\s+claim|"
    r"let(?:'s|\s+us)\s+claim"
    r")\b",
    re.IGNORECASE,
)

# User wants to start a guided invest flow (property name first, then amount).
_BEGIN_INVEST_WORKFLOW = re.compile(
    r"\b("
    r"i\s+want\s+to\s+invest|"
    r"help\s+me\s+invest|"
    r"let(?:'s|\s+us)\s+invest\b|"
    r"start\s+(?:an?\s+)?invest(?:ment|ing)?|"
    r"make\s+(?:an?\s+)?investment|"
    r"i(?:'d|\s+would)\s+like\s+to\s+invest\b|"
    r"ready\s+to\s+invest"
    r")\b",
    re.IGNORECASE,
)

# Soft "invest" mentions that are research, not orders.
_INVEST_RESEARCH = re.compile(
    r"\b("
    r"how\s+to\s+invest|"
    r"should\s+i\s+invest|"
    r"worth\s+investing|"
    r"properties?\s+to\s+invest\s+in|"
    r"investment\s+opportunities|"
    r"thinking\s+about\s+investing|"
    r"learn\s+about\s+investing"
    r")\b",
    re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split())


def extract_last_human_utterance(messages: list[Any] | None) -> str:
    """Return the latest human/user line from LangGraph or API history."""
    if not messages:
        return ""
    last_human_idx: int | None = None
    for i, msg in enumerate(messages):
        role = ""
        if isinstance(msg, dict):
            role = (msg.get("type") or msg.get("role") or "").lower()
        else:
            cls = type(msg).__name__.lower()
            if "human" in cls:
                role = "human"
            elif "user" in cls:
                role = "user"
        if role in ("human", "user"):
            last_human_idx = i
    if last_human_idx is None:
        return ""
    msg = messages[last_human_idx]
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content")
    return _normalize_text(content if isinstance(content, str) else "")


def wants_to_begin_invest_workflow(text: str) -> bool:
    """True when the user asks to invest but has not necessarily named a property yet."""
    t = _normalize_text(text)
    if not t or _INVEST_RESEARCH.search(t):
        return False
    if _BEGIN_INVEST_WORKFLOW.search(t):
        return True
    return False


def has_explicit_invest_intent(text: str) -> bool:
    """True when the user is ordering a buy/invest, not researching."""
    t = _normalize_text(text)
    if not t:
        return False
    if _INVEST_RESEARCH.search(t):
        return False
    if _INVEST_TRANSACTIONAL.search(t):
        if _INFO_OR_BROWSE.search(t) and not re.search(
            r"\b(?:buy|purchase)\s+\d+|invest\s+\d+\s+tokens?",
            t,
            re.IGNORECASE,
        ):
            return False
        return True
    return wants_to_begin_invest_workflow(t)


def invest_workflow_active(session: dict | None) -> bool:
    """True while a guided invest form is being collected or submitted."""
    if not session:
        return False
    if session.get("completing_submit"):
        return True
    return bool(session.get("in_progress")) and not session.get("submitted")


def investor_invest_wallet_permitted(
    user_text: str,
    invest_session: dict | None = None,
) -> bool:
    """Whether invest modal / MetaMask submit actions may be emitted this turn."""
    if invest_workflow_active(invest_session):
        return True
    return has_explicit_invest_intent(user_text)


def has_explicit_claim_intent(text: str) -> bool:
    """True when the user wants to execute a claim, not just see claimable totals."""
    t = _normalize_text(text)
    if not t:
        return False
    if _CLAIM_TRANSACTIONAL.search(t):
        return True
    return False


def wallet_ui_allowed(modal: str, user_text: str, *, invest_session: dict | None = None) -> bool:
    if modal == "INVEST_PROPERTY":
        return investor_invest_wallet_permitted(user_text, invest_session)
    if modal == "CLAIM_REWARDS":
        return has_explicit_claim_intent(user_text)
    return True


def sanitize_investor_wallet_actions(
    messages: list[Any] | None,
    actions: list[AgentAction],
    *,
    invest_session: dict | None = None,
) -> list[AgentAction]:
    """Drop invest/claim modal actions unless permitted for this turn."""
    if not actions:
        return actions
    user_text = extract_last_human_utterance(messages)
    invest_ok = investor_invest_wallet_permitted(user_text, invest_session)
    claim_ok = has_explicit_claim_intent(user_text)
    completing = bool((invest_session or {}).get("completing_submit"))

    filtered: list[AgentAction] = []
    for action in actions:
        modal = action.modal or ""
        if modal in _INVESTOR_WALLET_MODALS:
            if modal == "INVEST_PROPERTY" and not invest_ok:
                continue
            if modal == "CLAIM_REWARDS" and not claim_ok:
                continue
        if (
            action.type == "SUBMIT_FORM"
            and modal == "INVEST_PROPERTY"
            and not (invest_ok and completing)
        ):
            continue
        if action.type == "SUBMIT_FORM" and modal == "CLAIM_REWARDS" and not claim_ok:
            continue
        filtered.append(action)
    return filtered


def invest_tool_blocked_message() -> str:
    return (
        "Blocked: the user's latest message is informational or browse-only, not an "
        "explicit buy/invest order. Do NOT open the invest dialog or mention MetaMask. "
        "Use list_properties, get_property_details, or navigate to /investor/marketplace. "
        "Tell them they can tap Invest on a property card when they are ready."
    )


def claim_tool_blocked_message() -> str:
    return (
        "Blocked: the user asked about claimable amounts or history, not to execute a "
        "claim. Do NOT open the claim dialog or mention MetaMask. Use "
        "get_my_claimable_rewards or get_my_claim_history. If they want to claim later, "
        "they can use Claim via MetaMask on the dashboard."
    )
