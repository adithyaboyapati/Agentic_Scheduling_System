"""Natural language processing and date/time normalization utilities.

Provides deterministic parsing for clinic appointments, slot timestamps, and
user confirmation detection without requiring LLM invocations.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

AFFIRMATIVE_WORDS = {
    "ye", "yes", "y", "yeah", "yep", "yup", "ya", "sure", "ok", "okay", "k",
    "confirm", "fine", "please", "alright", "right", "correct", "perfect"
}

AFFIRMATIVE_PHRASES = re.compile(
    r"^(yes|yeah|yep|yup|sure|ok|okay|confirm|please do|go ahead|do it|"
    r"sounds good|book it|reschedule it|let's do it|that works|that's fine|proceed)\b",
    re.IGNORECASE,
)


def is_affirmative_response(text: str) -> bool:
    """Detects whether user text conveys affirmative confirmation."""
    if not text:
        return False
    clean = re.sub(r"[^\w\s]", "", text.strip().lower()).strip()
    return clean in AFFIRMATIVE_WORDS or bool(AFFIRMATIVE_PHRASES.search(clean))


def _format_iso(y: str, mo: str, d: str, h: Optional[str], mi: Optional[str], s: Optional[str], ampm: Optional[str]) -> Tuple[Optional[str], str]:
    date_str = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    if h is None:
        return None, date_str
    hour = int(h)
    if ampm:
        if ampm.lower() == "pm" and hour < 12:
            hour += 12
        elif ampm.lower() == "am" and hour == 12:
            hour = 0
    return f"{date_str}T{hour:02d}:{mi or '00'}:{s or '00'}", date_str


def normalize_slot_and_date(text: str, default_year: str = "2026") -> Tuple[Optional[str], Optional[str]]:
    """Extracts standardized (ISO slot timestamp, date string) tuples from user text."""
    clean = text.strip()

    # 1. Explicit slot keyword (preserves invalid tokens like 'invalid_time_slot' for tests)
    explicit_slot = re.search(r"(?:to slot|at slot|slot)\s+([A-Za-z0-9\-_:]+)", clean, re.IGNORECASE)
    if explicit_slot:
        val = explicit_slot.group(1)
        # Avoid matching common prepositions/adjectives as slot names
        if val.lower() not in {"at", "on", "for", "in", "is", "of", "to", "the", "a", "an", "available", "open", "time", "date"}:
            return (val, val.split("T")[0]) if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", val) else (val, None)

    # 2. ISO / standard YYYY-MM-DD
    m1 = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[T\s]+(?:at\s+)?(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)?)?\b", clean, re.IGNORECASE)
    if m1:
        y, mo, d, h, mi, s, ampm = m1.groups()
        return _format_iso(y, mo, d, h, mi, s, ampm)

    # 3. US date MM-DD-YYYY
    m2 = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?:[T\s]+(?:at\s+)?(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)?)?\b", clean, re.IGNORECASE)
    if m2:
        mo, d, y, h, mi, s, ampm = m2.groups()
        return _format_iso(y, mo, d, h, mi, s, ampm)

    # 4. Short date MM-DD
    m3 = re.search(r"\b(\d{1,2})[-/](\d{1,2})(?:[T\s]+(?:at\s+)?(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)?)?\b", clean, re.IGNORECASE)
    if m3:
        mo, d, h, mi, s, ampm = m3.groups()
        return _format_iso(default_year, mo, d, h, mi, s, ampm)

    # 5. Month name: 'September 25th at 4:00 PM' or 'September 25, 2026'
    months = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    m4 = re.search(rf"\b({months})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{{4}}))?(?:[T\s]+(?:at\s+)?(\d{{1,2}})(?::(\d{{2}}))?(?::(\d{{2}}))?\s*(am|pm)?)?\b", clean, re.IGNORECASE)
    if m4:
        mon_str, d, yr, h, mi, s, ampm = m4.groups()
        mo_num = MONTH_MAP.get(mon_str.lower()[:3], 1)
        if h is None:
            # Check if there is an isolated time elsewhere in the sentence (e.g. 'available slot at 4:00 PM' or '4pm')
            tm = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)\b", clean, re.IGNORECASE)
            if tm:
                h, mi, s, ampm = tm.group(1), tm.group(2), tm.group(3), tm.group(4)
        return _format_iso(yr or default_year, str(mo_num), d, h, mi, s, ampm)

    # 6. Explicit date keyword (e.g., 'date bad_date_filter')
    explicit_date = re.search(r"(?:on date|for date|date)\s+([A-Za-z0-9\-_:]+)", clean, re.IGNORECASE)
    if explicit_date:
        return None, explicit_date.group(1)

    return None, None
