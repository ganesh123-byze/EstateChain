"""Normalize spoken / typed workflow answers before FILL_FIELD actions are emitted."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Spoken quantities common on property-owner voice flows (India / UK / US).
_WORD_NUMBERS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def _strip_noise(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _parse_spoken_integer(text: str) -> int | None:
    """Best-effort integer from phrases like 'one lakh tokens' or '10000'."""
    t = _strip_noise(text).lower()
    if not t:
        return None

    if re.search(r"\bone\s+lakh\b", t) or re.search(r"\b1\s+lakh\b", t):
        return 100_000
    if re.search(r"\btwo\s+lakh\b", t) or re.search(r"\b2\s+lakh\b", t):
        return 200_000
    m = re.search(r"([\d.,]+)\s*lakh", t)
    if m:
        try:
            return int(float(m.group(1).replace(",", "")) * 100_000)
        except (TypeError, ValueError):
            pass
    if re.search(r"\bone\s+crore\b", t) or re.search(r"\b1\s+crore\b", t):
        return 10_000_000
    m = re.search(r"([\d.,]+)\s*crore", t)
    if m:
        try:
            return int(float(m.group(1).replace(",", "")) * 10_000_000)
        except (TypeError, ValueError):
            pass
    if re.search(r"\bthousand\b", t):
        m = re.search(r"([\d.,]+)\s*thousand", t)
        if m:
            try:
                return int(float(m.group(1).replace(",", "")) * 1_000)
            except (TypeError, ValueError):
                pass
        if re.search(r"\bone\s+thousand\b", t):
            return 1_000

    # Compact suffix: 10k, 1.5m
    m = re.search(r"([\d.,]+)\s*([kKmM])\b", t)
    if m:
        base = float(m.group(1).replace(",", ""))
        mult = {"k": 1_000, "m": 1_000_000}[m.group(2).lower()]
        return int(base * mult)

    digits = re.sub(r"[^\d]", "", t)
    if digits:
        try:
            return int(digits)
        except ValueError:
            return None

    for word, val in _WORD_NUMBERS.items():
        if re.search(rf"\b{word}\b", t):
            return val
    return None


def _parse_decimal_amount(text: str) -> str | None:
    t = _strip_noise(text).lower()
    if not t or t in {"skip", "none", "no", "n/a", "zero", "0"}:
        return "0"
    m = re.search(r"([\d]+(?:[.,]\d+)?)", t)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    if "." in raw:
        return raw
    try:
        # Keep whole-number ETH values in plain decimal form (e.g. "20"),
        # never scientific notation (e.g. "2E+1"), because subsequent
        # regex-based normalization passes can truncate exponent strings.
        return str(Decimal(raw))
    except (InvalidOperation, ValueError):
        return None


_CREATE_PROPERTY_INTENT_RE = re.compile(
    r"(?i)(?:help\s+me\s+)?(?:list|create|add|register|tokenize)\s+(?:a\s+)?(?:new\s+)?propert"
)


def is_generic_create_property_intent(text: str) -> bool:
    """True when the user is starting the workflow, not answering \"property name\"."""
    t = _strip_noise(text).lower()
    if not t:
        return False
    if _CREATE_PROPERTY_INTENT_RE.search(t):
        return True
    if "tokenization" in t and "propert" in t:
        return True
    if re.search(r"(?i)^(?:i\s+)?want\s+to\s+(?:list|create|add)\b", t) and "propert" in t:
        return True
    return False


def assistant_prompted_for_create_field(assistant_text: str, field: str) -> bool:
    """True when the latest assistant turn explicitly asked for ``field``."""
    t = _strip_noise(assistant_text).lower()
    if not t:
        return False
    prompts: dict[str, tuple[str, ...]] = {
        "name": (
            "name of the property",
            "property name",
            "what's the name",
            "what is the name",
            "whats the name",
        ),
        "location": (
            "where is it located",
            "where is the property",
            "location of the property",
            "what's the location",
            "what is the location",
            "whats the location",
        ),
        "total_value": (
            "total property value",
            "total value",
            "value in eth",
        ),
        "token_supply": (
            "how many ownership tokens",
            "how many tokens",
            "token supply",
            "tokens should we mint",
        ),
        "token_symbol": (
            "ticker symbol",
            "token symbol",
            "symbol do you want",
        ),
        "monthly_rent_eth": (
            "monthly rent",
            "rent in eth",
        ),
    }
    return any(phrase in t for phrase in prompts.get(field, ()))


def normalize_create_property_field(field: str, raw: str) -> str:
    """Map a single user answer onto a form-ready string for CREATE_PROPERTY."""
    text = _strip_noise(raw)
    if not text:
        return text

    if field == "token_supply":
        n = _parse_spoken_integer(text)
        return str(n) if n is not None else re.sub(r"[^\d]", "", text) or text

    if field == "token_symbol":
        upper = text.upper()
        stop = {
            "A", "AN", "THE", "I", "TO", "FOR", "IS", "IT", "MY", "WE", "AS",
            "AT", "IN", "ON", "OR", "OF", "AND", "WANT", "GIVE", "USE", "TOKEN",
            "SYMBOL", "TICKER", "PLEASE",
        }
        m = re.search(
            r"\b(?:SYMBOL|TICKER)\s+(?:IS\s+)?([A-Z]{2,10})\b",
            upper,
        )
        if m and m.group(1) not in stop:
            return m.group(1)
        for sym in re.findall(r"\b([A-Z]{2,10})\b", upper):
            if sym not in stop:
                return sym
        cleaned = re.sub(r"[^A-Z0-9]", "", upper)
        return cleaned[:10] if cleaned else text

    if field in ("total_value", "monthly_rent_eth"):
        amt = _parse_decimal_amount(text)
        return amt if amt is not None else text

    if field == "name":
        if is_generic_create_property_intent(text):
            return ""
        # Drop leading filler: "the name is SpaceX" → SpaceX
        m = re.search(
            r"(?:name\s+is|called|property\s+is|it's|its)\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        return _strip_noise(m.group(1)) if m else text

    if field == "location":
        m = re.search(
            r"(?:located\s+in|location\s+is|in|at)\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        return _strip_noise(m.group(1)) if m else text

    return text


def normalize_create_property_accumulated(accumulated: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in accumulated.items():
        if value in (None, ""):
            continue
        out[key] = normalize_create_property_field(key, str(value))
    return out


# Thresholds for chatbot confirmation before on-chain create (deploy + mint + rent sync).
CREATE_HIGH_TOTAL_VALUE_ETH = Decimal("25")
CREATE_HIGH_TOKEN_SUPPLY = 50_000
CREATE_HIGH_MONTHLY_RENT_ETH = Decimal("5")


def _decimal_field_value(raw: str) -> Decimal | None:
    text = _strip_noise(raw)
    if not text:
        return None
    parsed = _parse_decimal_amount(text)
    if parsed is None:
        return None
    try:
        return Decimal(parsed)
    except (InvalidOperation, ValueError):
        return None


def _integer_field_value(raw: str) -> int | None:
    text = _strip_noise(raw)
    if not text:
        return None
    spoken = _parse_spoken_integer(text)
    if spoken is not None:
        return spoken
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def assess_high_value_create_property(accumulated: dict[str, str]) -> dict[str, object]:
    """Return whether create-property values warrant a Yes/No confirmation in chat."""
    reasons: list[str] = []
    total = _decimal_field_value(str(accumulated.get("total_value") or ""))
    if total is not None and total > CREATE_HIGH_TOTAL_VALUE_ETH:
        reasons.append(
            f"Total property value is {total} ETH (above {CREATE_HIGH_TOTAL_VALUE_ETH} ETH)."
        )

    supply = _integer_field_value(str(accumulated.get("token_supply") or ""))
    if supply is not None and supply > CREATE_HIGH_TOKEN_SUPPLY:
        reasons.append(
            f"Token supply is {supply:,} (above {CREATE_HIGH_TOKEN_SUPPLY:,} tokens)."
        )

    rent_raw = str(accumulated.get("monthly_rent_eth") or "").strip().lower()
    if rent_raw and rent_raw not in {"0", "skip", "none", "no", "n/a"}:
        rent = _decimal_field_value(rent_raw)
        if rent is not None and rent > CREATE_HIGH_MONTHLY_RENT_ETH:
            reasons.append(
                f"Monthly rent is {rent} ETH (above {CREATE_HIGH_MONTHLY_RENT_ETH} ETH)."
            )

    if not reasons:
        return {
            "is_high": False,
            "reasons": [],
            "speak_to_user": "",
            "instruction": "",
        }

    summary = " ".join(reasons)
    speak = (
        "These property values are on the high side, so on-chain setup "
        "(token deploy, minting the full supply, and rent sync) can take several "
        f"minutes. {summary} "
        "Do you want to proceed? Reply **Yes** to continue or **No** to cancel."
    )
    instruction = (
        "Read `speak_to_user` to the user verbatim. Do NOT submit the form yet. "
        "When they answer Yes, call fill_create_property with confirm_high_values=true "
        "(and submit=true). When they answer No, call fill_create_property with "
        "confirm_high_values=false. Do not call other tools until they choose."
    )
    return {
        "is_high": True,
        "reasons": reasons,
        "speak_to_user": speak,
        "instruction": instruction,
    }


def parse_yes_no_confirmation(text: str) -> bool | None:
    """Parse explicit yes/no answers for high-value create confirmation."""
    t = _strip_noise(text).lower()
    if not t:
        return None
    if t in {
        "yes",
        "y",
        "yeah",
        "yep",
        "sure",
        "ok",
        "okay",
        "proceed",
        "go ahead",
        "continue",
        "confirm",
        "do it",
    }:
        return True
    if t in {"no", "n", "nope", "cancel", "stop", "abort", "don't", "do not", "dont"}:
        return False
    if re.search(r"\b(yes|proceed|go ahead|continue)\b", t):
        return True
    if re.search(r"\b(no|cancel|abort|stop)\b", t):
        return False
    return None
