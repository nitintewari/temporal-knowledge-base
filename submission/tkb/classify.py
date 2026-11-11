"""Page-type classification from the URL.

Authority answers: "when two pages disagree about a rate or fee, whom do we trust?"
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# Higher = more trustworthy for CURRENT rates/fees/hours.
AUTHORITY = {
    "rate_sheet": 5,   # /rates, /business-rates
    "product": 5,      # /personal/..., /business/... product pages
    "other": 3,        # /contact, /about, home page ...
    "pdf": 2,          # /hubfs/... uploaded files (often old)
    "promo": 1,        # landing pages / campaigns (often left up after they end)
    "calculator": 1,   # calculators embed copies of rate tables that go stale
    "press": 1,        # /newsroom/... dated press releases
    "blog": 0,         # /learn/..., /YYYY/MM/DD/... articles
}


def _parse(url: str):
    return urlparse(url if "//" in url else "https://" + url)


def url_path(url: str) -> str:
    """'https://www.dupaco.com/Rates/' -> '/rates' (lower-case, no trailing slash, no #fragment)."""
    return (_parse(url).path or "/").rstrip("/").lower() or "/"


def page_type(url: str) -> str:
    p = _parse(url)
    host, path = p.netloc.lower(), url_path(url)
    if (re.match(r"^/\d{4}/\d{2}/", path)
            or path.startswith(("/learn", "/business/resources", "/dupacodaily"))
            or any(seg in path for seg in ("/tag/", "/author/", "/category/"))):
        return "blog"
    if path.startswith("/newsroom"):
        return "press"
    if "calculator" in path:
        return "calculator"
    if path.startswith("/hubfs") or path.endswith((".pdf", ".xls", ".xlsx", ".csv")):
        return "pdf"
    if path in ("/rates", "/business-rates"):
        return "rate_sheet"
    if host.startswith("info.") or any(k in path for k in ("switch-and-earn", "-lp", "offer", "promo", "earn-more")):
        return "promo"
    if path.startswith(("/personal", "/business", "/checking", "/savings")):
        return "product"
    return "other"
