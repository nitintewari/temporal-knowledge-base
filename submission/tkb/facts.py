"""Fact builder: rate tables -> keyed, dated facts (Phase 2C).

A Fact is one value with everything needed to decide later whether it is current:
    product   "auto loan"            what it is about           (vocabulary below, rules as data)
    attribute "apr"                  which number               (from the column header, R16)
    term / tier / qualifiers         which exact variant        (from the row's label cells, R1, R6)
    value     5.39%                  the number, as written     (values.py)
    effective 2026-08-31             when it took effect        (tables.py, R15)
    url, evidence                    where it came from          (provenance)

Design choices, each traced to evidence in docs/RULES.md:
- Column ROLES come from headers (rate / APY / APR / ignore), but each LABEL cell's meaning comes from
  its content: a column headed "Account Type" sometimes holds "2023-26 Model Year" (Phase 2C data check).
- The product is looked up in this order: the row's own labels, the first header cell
  ("Platinum Credit Card"), then the headings above the table (E8, E16, R18). First match wins.
- A deposit table whose rows have terms but no named product is a certificate table
  (headings like "Regular" / "Special" above "6 Month", "12 Month" rows).
- Rows whose product cannot be identified produce no facts (R16: never guess).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .classify import url_path
from .normalize import clean_text, squash_spaces
from .tables import Table, parse_tables
from .values import (Percent, Range, is_empty, parse_money, parse_money_range, parse_percent,
                     parse_term_months, parse_year_range, strip_footnotes)

# ----------------------------------------------------------------------------- vocabulary (rules as data)
# Order matters: more specific products first ("home equity line" before "home equity").
PRODUCTS = [
    ("atv loan", r"\batv\b|snowmobile|jet ski"),
    ("boat & rv loan", r"\bboat\b|\brv\b|recreational"),
    ("auto loan", r"\bauto\b|vehicle|motorcycle"),
    ("home improvement loan", r"home improvement"),
    ("heloc", r"home equity line|\bheloc\b"),
    ("home equity loan", r"home equity"),
    ("mortgage", r"home loan|mortgage|refinance|conventional|\bpurchase\b"),
    ("personal loan", r"personal loan"),
    ("platinum visa", r"\bplatinum\b"),
    ("rewards visa", r"\brewards (?:visa|credit)"),
    ("health savings account", r"health savings|\bhsa\b"),
    ("bright savings", r"\bbright savings\b"),
    ("you name it savings", r"you.?name.?it"),
    ("high-yield savings", r"high.?yield"),
    ("investor's choice money market", r"investor'?s choice"),
    ("achieve money market", r"\bachieve\b"),
    ("money market", r"money market"),
    ("launchpad savings", r"launchpad"),
    ("holiday club savings", r"holiday club"),
    ("share savings", r"share savings"),
    ("1st rate checking", r"1st rate"),
    ("free checking", r"free checking"),
    ("certificate", r"certificate|\bcds?\b"),
]
_PRODUCT_RES = [(name, re.compile(rx, re.I)) for name, rx in PRODUCTS]

DEPOSIT_ATTRIBUTES = {"apy", "dividend_rate"}
TIER_MODEL_YEAR, TIER_BALANCE, TIER_LOAN_AMOUNT = "model_year", "balance", "loan_amount"

_IGNORE_HEADER = re.compile(r"payment|points|min\.?\s*to|minimum|\bfee\b", re.I)
_MIN_BALANCE = re.compile(r"min\.?\s*balance", re.I)
# "Min. to Open" / "Min. to Earn": not a tier and not a rate, but the answer to "how much do I need to open one?"
# (blind set A). Kept on each fact of the row; never compared or resolved.
_MIN_OPEN = re.compile(r"min\.?\s*to\s*open|minimum (?:to open|deposit|opening)", re.I)
_MIN_EARN = re.compile(r"min\.?\s*to\s*earn|minimum to earn", re.I)
_MAX_BALANCE = re.compile(r"max\.?\s*balance", re.I)
_INTRO = re.compile(r"\bintro(?:ductory)?\b|for (?:the )?1st|first \d+ months", re.I)
_LINK_ONLY = re.compile(r"^-?\s*\[[^\]]*\]\([^)]*\)(?:\s*\[[^\]]*\]\([^)]*\))*$")
_ACCOUNT_PREFIX = re.compile(r"^(roth|traditional)\s*:\s*", re.I)
_PURPOSE = [("cash_out", re.compile(r"cash.?out", re.I)),
            ("purchase", re.compile(r"\bpurchase\b", re.I)),
            ("refinance", re.compile(r"\brefinanc", re.I))]


@dataclass(frozen=True)
class Fact:
    product: str
    attribute: str                      # apr | apy | dividend_rate | rate
    value: Percent
    term_months: Optional[int] = None
    tier_kind: Optional[str] = None     # model_year | balance | loan_amount
    tier: Optional[Range] = None
    segment: str = "personal"           # personal | business
    account: Optional[str] = None       # roth | traditional (IRA)
    purpose: Optional[str] = None       # purchase | refinance | cash_out (mortgages)
    flags: tuple = ()                   # sorted subset of: intro, jumbo, relief, special, variable
    label: str = ""                     # the row's own wording, for display
    effective: Optional[str] = None     # ISO date of the table (R15); None if undated
    url: str = ""
    page_type: str = ""
    table_index: int = 0
    row_index: int = 0
    evidence: str = ""                  # the full row as written on the page
    minimum: str = ""                   # the row's minimum, e.g. "$1,000.00 to open" (Min. to Open / Earn column)
    points: str = ""                    # the row's points, e.g. "0.00%" (mortgage tables)
    payment: str = ""                   # the row's payment example, e.g. "$1,327.36" (mortgage tables)

    def key(self) -> tuple:
        """What the fact is ABOUT. Two facts compete only when their keys match and their tiers overlap (R1)."""
        return (self.product, self.segment, self.account, self.purpose, self.flags,
                self.attribute, self.term_months, self.tier_kind)


@dataclass
class _Column:
    index: int
    role: str                           # value | label | min_balance | max_balance | ignore
    attribute: Optional[str] = None
    intro: bool = False


@dataclass
class _RowInfo:
    term: Optional[int] = None
    tier_kind: Optional[str] = None
    tier: Optional[Range] = None
    account: Optional[str] = None
    purpose: Optional[str] = None
    flags: set = field(default_factory=set)
    texts: list = field(default_factory=list)


# ----------------------------------------------------------------------------- columns (R16)
def column_role(header: str) -> _Column:
    h = strip_footnotes(clean_text(header)).lower()
    if _MIN_BALANCE.search(h):
        return _Column(0, "min_balance")
    if _MAX_BALANCE.search(h):
        return _Column(0, "max_balance")
    if _MIN_OPEN.search(h):
        return _Column(0, "min_open")
    if _MIN_EARN.search(h):
        return _Column(0, "min_earn")
    if re.search(r"\bpoints?\b", h):
        return _Column(0, "points")                    # mortgage tables: "Points" (blind B1: asked with the rate)
    if re.search(r"\bpayment\b", h):
        return _Column(0, "payment")                   # "*Payment Example" (blind C: the official example payment)
    if _IGNORE_HEADER.search(h):
        return _Column(0, "ignore")
    intro = bool(_INTRO.search(h))
    if re.search(r"\bapy\b|yield", h):
        return _Column(0, "value", "apy", intro)
    if "dividend" in h:
        return _Column(0, "value", "dividend_rate", intro)
    if re.search(r"\bapr\b|annual percentage rate", h):
        return _Column(0, "value", "apr", intro)
    if re.search(r"\brate\b", h):
        return _Column(0, "value", "rate", intro)
    return _Column(0, "label")


def cell_attribute(cell: str, header_attribute: str) -> str:
    """A cell that names its own measure overrides the header.

    The vehicle-affordability calculator's table is headed "Annual Percentage Yield" but its cells read
    "5.34% APR"; trusting the header would file a stale APR as an APY and hide it from conflict checks.
    """
    if re.search(r"\bAPR\b", cell):
        return "apr"
    if re.search(r"\bAPY\b", cell):
        return "apy"
    return header_attribute


def table_columns(table: Table) -> list:
    cols = []
    for i, h in enumerate(table.header):
        c = column_role(h)
        c.index = i
        cols.append(c)
    return cols


# ----------------------------------------------------------------------------- labels -> qualifiers
def parse_labels(cells: list, deposit: bool) -> _RowInfo:
    """Read every label cell by its CONTENT: term, model-year or money tier, IRA type, purpose, flags."""
    info = _RowInfo()
    for raw in cells:
        if is_empty(raw):
            continue
        text = squash_spaces(clean_text(raw))
        m = _ACCOUNT_PREFIX.match(text)
        if m:
            info.account = m.group(1).lower()
            text = text[m.end():]
        for name, rx in _PURPOSE:
            if rx.search(text) and info.purpose is None:
                info.purpose = name
        if info.term is None:
            info.term = parse_term_months(text)
        years = parse_year_range(text) if re.search(r"model|year", text, re.I) and "$" not in text else None
        if years and info.tier is None:
            info.tier_kind, info.tier = TIER_MODEL_YEAR, years
        elif "$" in text and info.tier is None:
            money = parse_money_range(text)
            if money:
                info.tier_kind = TIER_BALANCE if deposit else TIER_LOAN_AMOUNT
                info.tier = money
        for flag in ("special", "jumbo", "variable"):
            if re.search(rf"\b{flag}\b", text, re.I):
                info.flags.add(flag)
        if _INTRO.search(text):
            info.flags.add("intro")
        if re.search(r"\brelief\b", text, re.I):
            info.flags.add("relief")
        info.texts.append(text)
    return info


def find_product(texts: list) -> Optional[str]:
    """First vocabulary match, scanning texts in priority order (row labels, header, headings)."""
    for text in texts:
        for name, rx in _PRODUCT_RES:
            if rx.search(text):
                return name
    return None


def _usable_context(table: Table) -> list:
    """Headings above the table, without link-only lines like '[Learn More](https://google.com/)' (E25)."""
    return [c for c in table.context if not _LINK_ONLY.match(c)]


# ----------------------------------------------------------------------------- table -> facts
def facts_from_table(table: Table, url: str = "", page_type: str = "") -> list:
    cols = table_columns(table)
    value_cols = [c for c in cols if c.role == "value"]
    if not value_cols or not table.rows:
        return []
    label_cols = [c for c in cols if c.role == "label"]
    deposit = any(c.attribute in DEPOSIT_ATTRIBUTES for c in value_cols)
    context = _usable_context(table)
    header_labels = [table.header[c.index] for c in label_cols]
    table_text = " ".join(context[:1] + header_labels)
    business_table = bool(re.search(r"\bbusiness\b", table_text, re.I))
    business_page = url_path(url).startswith("/business")

    facts = []
    for r, row in enumerate(table.rows):
        cells = [row[c.index] for c in label_cols if c.index < len(row)]
        info = parse_labels(cells, deposit)
        # Min./Max. Balance columns define the tier when no label cell did.
        if info.tier is None:
            lo = next((parse_money(row[c.index]) for c in cols if c.role == "min_balance" and c.index < len(row)), None)
            hi = next((parse_money(row[c.index]) for c in cols if c.role == "max_balance" and c.index < len(row)), None)
            if lo is not None or hi is not None:
                info.tier_kind, info.tier = TIER_BALANCE, Range(lo, hi)

        product = find_product(info.texts + header_labels + context)
        ira = info.account is not None or any(re.search(r"\bira", t, re.I) for t in info.texts + context[:1])
        if ira:
            product = "ira certificate" if info.term else "ira savings"
            if info.account is None:
                info.account = "any"
        elif product is None and deposit and info.term:
            product = "certificate"           # "Regular"/"Special" headings above "6 Month" rows
        if product is None:
            continue                          # R16: unknown product -> no fact, never a guess
        if product == "mortgage" and info.purpose == "refinance" and context \
                and re.search(r"cash.?out", context[0], re.I):
            info.purpose = "cash_out"         # rows say "Refinance:", the table heading "Cash-Out Refinance" (B1)
        if product in ("certificate", "ira certificate", "ira savings") and context \
                and re.search(r"\bspecial\b", context[0], re.I):
            info.flags.add("special")
        if product not in ("certificate", "ira certificate", "ira savings"):
            info.flags.discard("special")
            info.flags.discard("variable")
        # Segment: business if the row/heading says so, or if the page is one of the bank's business
        # pages (/business..., /business-rates). The URL keeps the segment stable across crawls even when
        # a heading drops the word "business" (snapshot 01 vs 05 of /business-rates, Phase 2C check).
        segment = "business" if (business_table or business_page
                                 or any(re.search(r"\bbusiness\b", t, re.I) for t in info.texts)) else "personal"

        minimum = ""
        for role, words in (("min_open", "to open"), ("min_earn", "to earn")):
            cell = next((row[c.index] for c in cols if c.role == role and c.index < len(row)), "")
            if parse_money(cell) is not None:
                minimum = f"{clean_text(cell).strip()} {words}"
                break
        extra = {role: clean_text(row[c.index]).strip() for c in cols for role in ("points", "payment")
                 if c.role == role and c.index < len(row)}
        for c in value_cols:
            if c.index >= len(row):
                continue
            value = parse_percent(row[c.index], bare_ok=True)
            if value is None:
                continue
            flags = set(info.flags) | ({"intro"} if c.intro else set())
            facts.append(Fact(
                product=product,
                attribute=cell_attribute(row[c.index], c.attribute or "rate"),
                value=value,
                term_months=info.term,
                tier_kind=info.tier_kind,
                tier=info.tier,
                segment=segment,
                account=info.account,
                purpose=info.purpose,
                flags=tuple(sorted(flags)),
                label=" | ".join(info.texts),
                effective=table.effective,
                url=url,
                page_type=page_type,
                table_index=table.index,
                row_index=r,
                evidence=" | ".join(row),
                minimum=minimum,
                points=extra.get("points", ""),
                payment=extra.get("payment", ""),
            ))
    return facts


def extract_facts(markdown: Optional[str], url: str = "", page_type: str = "") -> list:
    """All facts on one page (every table, in page order)."""
    facts = []
    for table in parse_tables(markdown or ""):
        facts.extend(facts_from_table(table, url, page_type))
    return facts
