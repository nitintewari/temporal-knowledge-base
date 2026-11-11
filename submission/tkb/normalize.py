"""Text cleaning applied before ANY parsing or matching (rules R14, R19).

Why a separate module: the same cleaning must be used everywhere - on page text at ingest time
and on questions at answer time - otherwise "84 Months" (normal space) would never match
"84\\xa0Months" (non-breaking space) and facts would silently disappear (evidence E15).
"""
from __future__ import annotations

import html
import re
from typing import Optional

# Phase 2C: curly quotes - "Investor’s Choice" and "Investor's Choice" must be the same product.
QUOTES = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}

# E15: invisible characters that look like spaces but are not.
INVISIBLE = {
    "\xa0": " ",     # non-breaking space
    "\u202f": " ",   # narrow non-breaking space
    "\u2009": " ",   # thin space
    "\u200b": "",    # zero-width space
    "\ufeff": "",    # byte-order mark
}

# E1 / E15: dash variants. "2023–26" (en-dash) and "2023-26" (hyphen) must be the same text.
DASHES = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
}

# E21: escaped line breaks that leaked into the text as literal characters, e.g.
# "...without notice.\\r\\n\\r\\nSavings Rates:". Matches backslash-r-backslash-n pairs, or two or more
# backslash-n in a row, so a lone "\n" inside normal text is left alone.
_ESCAPED_BREAKS = re.compile(r"(?:\\+r\\+n)+|(?:\\+n){2,}")

# HTML line breaks inside table cells: "- No initial deposit<br> <br> - Earn a competitive rate".
_HTML_BREAK = re.compile(r"<br\s*/?>", re.I)

# Markdown escapes such as "\*Payment Example" -> "*Payment Example". The pipe is NOT unescaped here:
# an escaped pipe inside a table cell must not become a column separator (tables.py handles it).
_MD_ESCAPE = re.compile(r"\\([*_#\[\]()`~>+!.-])")


def clean_text(text: Optional[str]) -> str:
    """Normalize invisible characters, dashes, quotes, escaped line breaks, markdown escapes, HTML entities."""
    if not text:
        return ""
    for ch, rep in INVISIBLE.items():
        text = text.replace(ch, rep)
    for ch, rep in DASHES.items():
        text = text.replace(ch, rep)
    for ch, rep in QUOTES.items():
        text = text.replace(ch, rep)
    text = _ESCAPED_BREAKS.sub(" ", text)
    text = _HTML_BREAK.sub(" ", text)
    text = _MD_ESCAPE.sub(r"\1", text)
    if "&" in text:
        # Some pages are double-escaped ("&amp;#45;" -> "&#45;" -> "-"), so unescape twice.
        text = html.unescape(html.unescape(text))
    return text


def squash_spaces(text: str) -> str:
    """Collapse runs of whitespace to one space (used for cell text and matching, not for whole pages)."""
    return re.sub(r"\s+", " ", text).strip()
