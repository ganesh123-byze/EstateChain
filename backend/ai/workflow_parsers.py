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
