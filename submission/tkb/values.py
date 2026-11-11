"""Value parser: turns cell text into numbers and ranges (Phase 2B).

Each function takes one piece of text and returns a clean value, or None when the text holds no value
of that kind. Nothing here guesses: "N/A", "None" and "-" are "no value", never zero.

Examples from the real data (docs/RULES.md):
  "5.39% APR1"                  -> Percent 5.39            (footnote "1" removed, R7/E11)
  "7.29" under an APR header    -> Percent 7.29            (no % sign on Boat & RV, E18)
  "12.50% - 19.50% APR1"        -> Percent range 12.50 - 19.50
  "2024-27 Model Year"          -> years 2024 - 2027        (R6)
  "Model Year 2026-23"          -> years 2023 - 2026        (reversed, R6/E16)
  "2016 Model Year (and older)" -> years up to 2016         (open-ended)
  "$10,000-24,999"              -> money 10000 - 24999      (second end without "$", E18)
  "$832750 or less"             -> money up to 832750
  "60 Months" / "5 Years" / "30-Year Fixed" -> 60 / 60 / 360 months
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .normalize import clean_text, squash_spaces

# Cells that mean "no value here".
EMPTY_CELLS = {"", "-", "--", "n/a", "na", "none", "null", "tbd"}


@dataclass(frozen=True)
class Percent:
    """A rate. `low` == `high` for a single value; `text` is how the site writes it (footnotes removed)."""
    low: float
    high: float
    text: str

    @property
    def is_range(self) -> bool:
        return self.low != self.high


@dataclass(frozen=True)
class Range:
    """A numeric range; None on one side means open-ended ("$100,000+", "2016 and older")."""
    low: Optional[float]
    high: Optional[float]

    def contains(self, x: float) -> bool:
        return (self.low is None or x >= self.low) and (self.high is None or x <= self.high)

    def overlap(self, other: "Range") -> float:
        """Size of the overlap with another range (0 if none). Open ends count as very large."""
        lo = max(self.low if self.low is not None else -1e18, other.low if other.low is not None else -1e18)
        hi = min(self.high if self.high is not None else 1e18, other.high if other.high is not None else 1e18)
        return max(0.0, hi - lo + 1) if hi >= lo else 0.0


# ----------------------------------------------------------------------------- footnotes
# E11: footnote digits glued to a value or label: "5.39% APR1", "3.90%1", "(APY)1", "(As Low As) 2".
# Footnotes are glued directly to the value ("%1", "APR1"); a number after a SPACE is real data
# ("5.00% 12 months"), so only the parenthesis case allows a space, and never before a unit word.
_FOOTNOTE_AFTER_PERCENT = re.compile(r"%\d{1,2}(?![\d.])")
_FOOTNOTE_AFTER_WORD = re.compile(r"\b(APR|APY|Rate|Yield)\d{1,2}\b", re.I)
_FOOTNOTE_AFTER_PAREN = re.compile(r"\)\s?\d{1,2}\b(?!\s*(?:months?|mos?\b|years?|yrs?\b|%|\.\d))", re.I)
_FOOTNOTE_AT_END = re.compile(r"(?<=[A-Za-z)])\d{1,2}$")


def strip_footnotes(text: str) -> str:
    """Remove footnote markers without touching real numbers."""
    text = _FOOTNOTE_AFTER_PERCENT.sub("%", text)
    text = _FOOTNOTE_AFTER_WORD.sub(r"\1", text)
    text = _FOOTNOTE_AFTER_PAREN.sub(")", text)
    text = _FOOTNOTE_AT_END.sub("", text)
    return squash_spaces(text)


def is_empty(text: Optional[str]) -> bool:
    return squash_spaces(clean_text(text)).lower().strip("*. ") in EMPTY_CELLS


# ----------------------------------------------------------------------------- percents
_NUM = r"\d{1,3}(?:\.\d{1,4})?"
_PERCENT_RANGE = re.compile(rf"({_NUM})\s?%?\s*(?:-|to)\s*({_NUM})\s?%")
_PERCENT = re.compile(rf"({_NUM})\s?%")
_BARE_NUMBER = re.compile(rf"^({_NUM})$")


def parse_percent(text: Optional[str], bare_ok: bool = False) -> Optional[Percent]:
    """The FIRST rate in a cell, or None.

    bare_ok=True accepts a number without "%" - only for cells under a rate header (E18: "7.29").
    A range ("12.50% - 19.50%") is returned as one Percent with low/high.
    """
    if is_empty(text):
        return None
    t = strip_footnotes(clean_text(text))
    m = _PERCENT_RANGE.search(t)
    p = _PERCENT.search(t)
    if m and (p is None or m.start() <= p.start()):
        low, high = float(m.group(1)), float(m.group(2))
        if low > high:
            low, high = high, low
        return Percent(low, high, f"{m.group(1)}% - {m.group(2)}%")
    if p:
        return Percent(float(p.group(1)), float(p.group(1)), f"{p.group(1)}%")
    if bare_ok:
        b = _BARE_NUMBER.match(t.replace("APR", "").replace("APY", "").strip())
        if b:
            return Percent(float(b.group(1)), float(b.group(1)), f"{b.group(1)}%")
    return None


def all_percents(text: Optional[str]) -> list:
    """Every single rate mentioned in a cell, in order (for cells like '2.90% APR for 6 mos. (after ... 12.50%')."""
    if is_empty(text):
        return []
    t = strip_footnotes(clean_text(text))
    return [Percent(float(x), float(x), f"{x}%") for x in _PERCENT.findall(t)]


# ----------------------------------------------------------------------------- money
_MONEY = r"\$\s?(\d[\d,]*(?:\.\d+)?)"
_MONEY_RANGE = re.compile(rf"{_MONEY}\s*(?:-|to)\s*\$?\s?(\d[\d,]*(?:\.\d+)?)")
_MONEY_PLUS = re.compile(rf"{_MONEY}\s*(?:\+|or\s+more|and\s+(?:up|above|over))", re.I)
_MONEY_LESS = re.compile(rf"(?:{_MONEY}\s*(?:or\s+less|and\s+(?:under|below)))|(?:(?:up\s+to|under|below|less\s+than)\s*{_MONEY})", re.I)
_MONEY_ONE = re.compile(_MONEY)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_money(text: Optional[str]) -> Optional[float]:
    """'$10,000' -> 10000.0, '$ 575.73' -> 575.73, '$832750' -> 832750.0."""
    if is_empty(text):
        return None
    m = _MONEY_ONE.search(clean_text(text))
    return _num(m.group(1)) if m else None


def parse_money_range(text: Optional[str]) -> Optional[Range]:
    """Balance or loan-amount tiers in every format seen in the data (E18)."""
    if is_empty(text):
        return None
    t = clean_text(text)
    m = _MONEY_RANGE.search(t)
    if m:
        low, high = _num(m.group(1)), _num(m.group(2))
        return Range(min(low, high), max(low, high))
    m = _MONEY_PLUS.search(t)
    if m:
        return Range(_num(m.group(1)), None)
    m = _MONEY_LESS.search(t)
    if m:
        value = m.group(1) or m.group(2)
        return Range(None, _num(value))
    m = _MONEY_ONE.search(t)
    if m:
        v = _num(m.group(1))
        return Range(v, v)
    return None


# ----------------------------------------------------------------------------- model years
_YEAR_RANGE = re.compile(r"\b((?:19|20)\d{2})\s*-\s*((?:19|20)?\d{2})\b")
_YEAR_ONE = re.compile(r"\b((?:19|20)\d{2})\b")
_OLDER = re.compile(r"older|earlier|prior|before", re.I)
_NEWER = re.compile(r"newer|later|after", re.I)


def _expand_year(first: int, second: str) -> int:
    """'2023-26' -> 2026; '2026-23' -> 2023; '2019-18' -> 2018 (same century as the first year)."""
    if len(second) == 4:
        return int(second)
    return (first // 100) * 100 + int(second)


def parse_year_range(text: Optional[str]) -> Optional[Range]:
    """Model-year tiers: '2024-27', 'Model Year 2026-23', '2016 Model Year (and older)'."""
    if is_empty(text):
        return None
    t = clean_text(text)
    m = _YEAR_RANGE.search(t)
    if m:
        a = int(m.group(1))
        b = _expand_year(a, m.group(2))
        return Range(float(min(a, b)), float(max(a, b)))
    m = _YEAR_ONE.search(t)
    if m:
        y = float(m.group(1))
        if _OLDER.search(t):
            return Range(None, y)
        if _NEWER.search(t):
            return Range(y, None)
        return Range(y, y)
    return None


# ----------------------------------------------------------------------------- terms
# The unit must be a WHOLE word: without the final \b, "2023-26 Model Year" matched "26 Mo(del)"
# and became a 26-month term (bug found by running the parser over every cell of every crawl).
_TERM = re.compile(r"\b(\d{1,3})\s*-?\s*(months?|mos?|years?|yrs?|yr)\b", re.I)


def parse_term_months(text: Optional[str]) -> Optional[int]:
    """'60 Months' -> 60, '6 mos.' -> 6, '5 Years' -> 60, '30-Year Fixed' -> 360, '10 Month Fixed' -> 10."""
    if is_empty(text):
        return None
    m = _TERM.search(clean_text(text))
    if not m:
        return None
    n = int(m.group(1))
    return n * 12 if m.group(2).lower().startswith("y") else n
