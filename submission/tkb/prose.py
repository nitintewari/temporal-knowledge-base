"""Prose facts: values that live in running text, not tables (Phase 2E).

Three jobs, each traced to evidence in docs/RULES.md:
  clean_page()     remove boilerplate before anything reads the page (R11): related-article teasers, modal
                   and chat widgets, image-only lines, embedded image data, calculator data series (E12, E24).
  publish_date()   the byline date of a press release or blog post: the first date near the top of the CLEANED
                   page, so a teaser's date can never be mistaken for it (R4, E22). Listing pages have none.
  extract_prose()  keyed prose facts: branch count, employees, assets, Forbes recognition, VTO by year,
                   routing number, branch addresses, branch hours, branch closures and where members go next.

Extraction rules are data (PATTERNS) plus three small structural readers (hours blocks, locator entries,
closure articles). Deciding which value is CURRENT is not done here: resolve.py applies R4 (newest
publication wins, never a majority vote, E4).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .classify import url_path
from .normalize import clean_text, squash_spaces

# ----------------------------------------------------------------------------- dates
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
DATE_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2}),\s+(20\d\d)\b")


def parse_date(text: str) -> Optional[str]:
    """First 'March 31, 2026' / 'Oct. 1, 2024' in the text, as ISO; None if there is none or it is invalid."""
    m = DATE_RE.search(text)
    if not m:
        return None
    month, day, year = _MONTHS[m.group(1)[:3].lower()], int(m.group(2)), int(m.group(3))
    if not 1 <= day <= 31:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


# ----------------------------------------------------------------------------- R11: boilerplate
# The related-article block: "## Recent News" in snapshots 01-03 (417 pages in 01), renamed "## Handpicked for
# You" in 04-05 (490 pages in 05). Every line after it is someone else's article, with its own date and numbers.
_TEASER_HEADING = re.compile(r"^#{1,6}\s*(?:Handpicked for You|Recent News|Related (?:Articles|Posts|Stories)|"
                             r"You (?:may|might) also like)\s*$", re.I)
# Widget and modal chrome: "✕" (667 pages), "[Continue](...) Cancel", and the chat widget that appears on
# 607 pages in snapshot 02 only ("Third Party Plugins / Messenger Launcher / Messenger", E12).
_CHROME = re.compile(r"^(?:✕|Third Party Plugins|Messenger Launcher|Messenger|Load More|\d+ min read|"
                     r"Sort By:.*|\[Continue\]\([^)]*\)\s*Cancel)$")
_IMAGE_ONLY = re.compile(r"^\[?!\[[^\]]*\]\([^)]*\)(?:\]\([^)]*\))?$")
_DATA_URI = re.compile(r"data:image/[^)\s]+")
_SERIES_ITEM = re.compile(r"\d*: \d+;")          # calculator chart data: "0: 2000; : 2107; : 2216; ..." (E24)
_LISTING_MARKS = re.compile(r"^(?:Sort By:|#### Filter$)", re.M)
_READ_MORE = re.compile(r"\[(?:Read More|Keep reading)\]\(", re.I)


def clean_page(markdown: Optional[str]) -> str:
    """Page text without boilerplate (R11). Line structure is kept: hours blocks and locators need it."""
    out = []
    for line in clean_text(markdown).splitlines():
        s = line.strip()
        if _TEASER_HEADING.match(s):
            break
        if _CHROME.match(s) or _IMAGE_ONLY.match(s) or len(_SERIES_ITEM.findall(s)) >= 10:
            continue
        out.append(_DATA_URI.sub("", line).rstrip())
    return "\n".join(out)


def is_listing(url: str, markdown: Optional[str]) -> bool:
    """Newsroom/blog index, tag, author and category pages: many teasers, each with its own date."""
    path = url_path(url)
    if any(seg in path for seg in ("/tag/", "/author/", "/category/")):
        return True
    text = _before_teasers(markdown or "")      # every article ends with 3 teaser "Keep reading" links
    return bool(_LISTING_MARKS.search(text)) or len(_READ_MORE.findall(text)) >= 3


def _before_teasers(text: str) -> str:
    lines = text.splitlines()
    cut = next((i for i, line in enumerate(lines) if _TEASER_HEADING.match(line.strip())), len(lines))
    return "\n".join(lines[:cut])


def publish_date(cleaned: str, page_type: str, listing: bool = False) -> Optional[str]:
    """Byline date of a press release or blog post: the first date in the top 15 lines of the CLEANED page.

    Bylines sit on line 2-5 ("[Emily Kress](...)" then "April 06, 2026"). Teaser dates sit below
    "Handpicked for You", which clean_page() already removed. Other page types are undated (None).
    """
    if listing or page_type not in ("press", "blog"):
        return None
    for line in cleaned.splitlines()[:15]:
        d = parse_date(line)
        if d:
            return d
    return None


# ----------------------------------------------------------------------------- facts
@dataclass(frozen=True)
class ProseFact:
    kind: str                       # branch_count | employees | assets | forbes_recognition | vto_employees |
    #                                 routing_number | address | hours | closure | closure_alternatives
    subject: str                    # what it is about: "dupaco", a year ("2023"), a city, a branch, a page path
    value: str                      # as written on the page ("22", "fifth", "11375 Oldenburg Ln., Galena, IL, 61036")
    number: Optional[float] = None  # numeric form when there is one (22, 5 for "fifth", 3.6 for "$3.6 billion")
    qualifier: Optional[str] = None  # street for addresses, lobby / drive-up for hours
    label: str = ""                 # human-readable subject for answers ("Galena", "Platteville branch")
    published: Optional[str] = None  # byline date of the page (R4); None on undated pages
    url: str = ""
    page_type: str = ""
    evidence: str = ""              # the sentence or lines as written
    extra: str = ""                 # branch services from the locator ("Drive Up Window · 24-hour ATM")

    def key(self) -> tuple:
        """Facts compete only with the same kind, subject and qualifier (R1, R21: the year is the subject)."""
        return (self.kind, self.subject, self.qualifier)


_ORDINALS = {w: i for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth".split(), start=1)}

# (kind, keywords, pattern, subject group or fixed subject, value group). Rules as data: add a row, not code.
# Keywords (lower case) are a cheap substring test run before the regex: ~150,000 sentences per crawl.
PATTERNS = [
    ("branch_count", ("branch office",), re.compile(r"\b(\d{1,3}) branch office locations\b"), "dupaco", 1),
    ("branch_count", ("full-service",), re.compile(r"\bDupaco's (\d{1,3}) full-service branches\b"), "dupaco", 1),
    ("employees", ("employees",), re.compile(r"\bover (\d{1,3}(?:,\d{3})*) employees\b"), "dupaco", 1),
    ("members", ("members",),
     re.compile(r"\b(?:serves?|serving) (?:more than|over|nearly) (\d{1,3}(?:,\d{3})+) members\b"), "dupaco", 1),
    ("assets", ("billion",),
     re.compile(r"\bassets (?:exceeding|of more than|of over|over) \$(\d+(?:\.\d+)?) billion\b"), "dupaco", 1),
    ("forbes_recognition", ("forbes",),
     re.compile(r"\b(" + "|".join(_ORDINALS) + r") time Forbes (?:has )?recognized Dupaco\b", re.I), "dupaco", 1),
    # E22: "<n> Dupaco employees used a new paid benefit in <year> called Volunteer Time Off" - year = subject (R21)
    ("vto_employees", ("volunteer time off",),
     re.compile(r"\b(\d{1,3}(?:,\d{3})*)\W{0,4}Dupaco employees\W{0,4} used (?:a )?(?:new )?"
                r"paid benefit in (20\d\d) called Volunteer Time Off", re.I), 2, 1),
    # Who can join: "Dupaco's 112-county field of membership"; "You can find us in Iowa, Illinois and Wisconsin."
    ("membership_counties", ("field of membership",),
     re.compile(r"\b(\d{1,3})-county field of membership\b", re.I), "dupaco", 1),
    ("service_states", ("find us in",),
     re.compile(r"\bfind us in ((?:[A-Z][a-z]+, )*[A-Z][a-z]+,? and [A-Z][a-z]+)\b"), "dupaco", 1),
    # Boilerplate on ~100 releases: "Founded in 1948 by ten Dubuque Packing Company employees" (Phase 6 review)
    ("founded", ("founded",), re.compile(r"\bFounded in (1[89]\d\d|20\d\d)\b", re.I), "dupaco", 1),
    # E10: "**Routing Number:** 273974581", "our routing number (273974581)", "ABA number (273974581)"
    ("routing_number", ("routing", "aba"),
     re.compile(r"\b(?:routing|ABA)(?: number)?\W{0,8}(?:is\s+)?\(?(\d{9})\b", re.I), "dupaco", 1),
]

_DISPLAY = {"assets": "${} billion"}          # how a value is shown in answers; the number stays in `number`

_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[*])")


def plain(line: str) -> str:
    """Markdown links -> their text, bold markers removed, spaces squashed (for matching and evidence)."""
    return squash_spaces(_LINK.sub(r"\1", line).replace("**", ""))


def sentences(cleaned: str) -> list:
    out = []
    for line in cleaned.splitlines():
        text = plain(line).lstrip("-#> ").strip()
        if text:
            out.extend(s.strip() for s in _SENTENCE_END.split(text) if s.strip())
    return out


def _number(kind: str, value: str) -> Optional[float]:
    if kind == "forbes_recognition":
        return float(_ORDINALS[value.lower()])
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _pattern_facts(sents: list, base: dict) -> list:
    out, seen = [], set()
    for s in sents:
        low = s.lower()
        for kind, keywords, rx, subj, grp in PATTERNS:
            if not any(k in low for k in keywords):
                continue
            for m in rx.finditer(s):
                value = m.group(grp)
                subject = m.group(subj) if isinstance(subj, int) else subj
                if (kind, subject, value) in seen:
                    continue                        # the same claim twice on one page counts once (R17)
                seen.add((kind, subject, value))
                shown = _DISPLAY.get(kind, "{}").format(value.lower() if kind == "forbes_recognition" else value)
                out.append(ProseFact(kind, subject, shown, _number(kind, value), label=subject, evidence=s, **base))
    return out


# --- branch locator entries (/contact): "Dupaco Branch" then "11375 Oldenburg Ln., Galena, IL, 61036" (E10)
_ADDRESS = re.compile(r"^(.+?),\s*([A-Za-z][A-Za-z .']+?),\s*(IA|IL|WI),?\s*(\d{5})$")


def _address_facts(lines: list, base: dict) -> list:
    out = []
    for i, line in enumerate(lines):
        if line.strip() != "Dupaco Branch":
            continue
        nxt = next((x.strip() for x in lines[i + 1:i + 4] if x.strip()), "")
        m = _ADDRESS.match(nxt)
        if m:
            street, city = m.group(1).strip(), m.group(2).strip()
            # The locator lists the branch's services a few lines below ("Drive Up Window · 24-hour ATM", blind C)
            after = [x.strip() for x in lines[i + 2:i + 9]]
            stop = next((k for k, x in enumerate(after) if x == "Dupaco Branch" or x.startswith("#")), len(after))
            services = next((x for x in after[:stop] if "·" in x), "")
            out.append(ProseFact("address", city.lower(), nxt, None, qualifier=street.lower(),
                                 label=city, evidence=nxt, extra=services.replace("·", ",").replace(" ,", ","),
                                 **base))
    for i, line in enumerate(lines):                 # "### Dupaco ATM @ Fareway Food Store" ... street line (D)
        m = _ATM.match(line.strip())
        if m:
            nxt = next((x.strip() for x in lines[i + 1:i + 5] if _ADDRESS.match(x.strip())), "")
            a = _ADDRESS.match(nxt)
            if a:
                place = m.group(1).strip()
                out.append(ProseFact("atm_address", place.lower(), nxt, None, qualifier=a.group(1).strip().lower(),
                                     label=f"Dupaco ATM at {place}", evidence=nxt, **base))
    for i, line in enumerate(lines):                 # "**Address:** P.O. Box 179" / "Dubuque, IA 52004-0179"
        m = _MAILING.match(line.strip())
        if m:
            nxt = next((x.strip() for x in lines[i + 1:i + 4] if x.strip()), "")
            value = m.group(1).strip() + (f", {nxt}" if _CITY_ZIP.match(nxt) else "")
            out.append(ProseFact("mailing_address", "dupaco", value, None, label="Dupaco", evidence=value, **base))
    return out


_ATM = re.compile(r"^#+\s*Dupaco ATM\s*@\s*(.+)$", re.I)
_MAILING = re.compile(r"^\**address:?\**:?\s*(p\.?\s?o\.?\s+box\s+\d+.*)$", re.I)
_CITY_ZIP = re.compile(r"^[A-Za-z .']+,\s*(?:IA|IL|WI)\s+\d{5}(?:-\d{4})?$")


# --- hours blocks in branch press releases: "Branch hours are:" / "**Lobby**" / "Monday-Thursday: 9 a.m.-5 p.m."
_SERVICE_NAME = {"drive-thru": "drive-up", "drive-through": "drive-up"}
_SERVICE = re.compile(r"^\*\*(Lobby|Drive-up|Drive-thru|Drive-through)\*\*\s*(.*)$", re.I)
_DAY = r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day"
_DAY_LINE = re.compile(rf"^({_DAY}(?:\s*-\s*{_DAY})?):\s*(.+)$")
# Which branch a block belongs to: the dateline city ("CEDAR RAPIDS, Iowa-") plus the branch named in the text
# ("The phone number for the East Washington branch is", "The Platteville Dupaco branch is located").
_DATELINE = re.compile(r"^([A-Z][A-Z .']+), (?:Iowa\b|Wis\.|Ill\.|Illinois\b|Wisconsin\b)")
_BRANCH_NAMED = [re.compile(r"\bphone number for the (.+?) is\b", re.I),
                 re.compile(r"\bThe (.+?) (?:Dupaco )?branch is located\b")]


def branch_label(sents: list, title: str) -> str:
    """'Madison East Washington branch', 'Platteville branch', 'Cedar Rapids Learning Lab'; else the title."""
    city = next((m.group(1).title() for s in sents[:12] for m in [_DATELINE.match(s)] if m), "")
    named = ""
    for s in sents:
        for i, rx in enumerate(_BRANCH_NAMED):
            m = rx.search(s)
            if m and not named:
                named = m.group(1) + (" branch" if i == 1 else "")
    if named and city and city.lower() not in named.lower():
        return f"{city} {named}"
    return named or city or title


def _hours_facts(lines: list, label: str, path: str, base: dict) -> list:
    out: list = []
    service: Optional[str] = None
    rows: list = []

    def flush():
        if service and rows:
            text = "; ".join(f"{d}: {h}" for d, h in rows)
            out.append(ProseFact("hours", path, text, None, qualifier=service, label=label,
                                 evidence=text, **base))

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m = _SERVICE.match(line)
        if m:
            flush()
            service, rows = _SERVICE_NAME.get(m.group(1).lower(), m.group(1).lower()), []
            line = m.group(2).strip()
            if not line:
                continue
        d = _DAY_LINE.match(line)
        if d and service:
            rows.append((d.group(1), d.group(2).strip()))
        elif service and rows:
            flush()
            service, rows = None, []
    flush()
    return out


# --- branch closures: the title names the branch, a sentence gives the date and where members can go next (E5)
_CLOSURE_TITLE = re.compile(r"\b(?:closing|close|plans)\s+(?:the\s+)?([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)\s+branch\b")
_CLOSURE_SENTENCE = re.compile(r"\b(?:will close|last day of service|closes? (?:on|its doors))\b", re.I)
_ALTERNATIVES = re.compile(r"\bbranch(?:es)? at ([A-Z].+?)(?:[,.;:\"]|-(?=[a-z])|$)")


def _closure_facts(title: str, sents: list, base: dict) -> list:
    m = _CLOSURE_TITLE.search(title)
    if not m:
        return []
    subject = m.group(1).lower()
    out = []
    when = next(((s, parse_date(s)) for s in sents if _CLOSURE_SENTENCE.search(s) and parse_date(s)), None)
    if when:
        out.append(ProseFact("closure", subject, when[1] or "", None, label=m.group(1), evidence=when[0], **base))
    alt = next(((s, a.group(1).strip()) for s in sents if re.search(r"\bcan access\b", s)
                for a in [_ALTERNATIVES.search(s)] if a), None)
    if alt:
        out.append(ProseFact("closure_alternatives", subject, alt[1], None, label=m.group(1), evidence=alt[0], **base))
    return out


def page_title(cleaned: str) -> str:
    return next((plain(line)[2:].strip() for line in cleaned.splitlines() if line.startswith("# ")), "")


def extract_prose(markdown: Optional[str], url: str = "", page_type: str = "") -> tuple:
    """(publish date, prose facts) for one page. Listing pages give (None, []): their text is teasers."""
    if is_listing(url, markdown):
        return None, []
    cleaned = clean_page(markdown)
    published = publish_date(cleaned, page_type)
    base = {"published": published, "url": url, "page_type": page_type}
    lines = cleaned.splitlines()
    sents = sentences(cleaned)
    title = page_title(cleaned)
    facts = (_pattern_facts(sents, base) + _address_facts(lines, base)
             + _hours_facts(lines, branch_label(sents, title), url_path(url), base)
             + _closure_facts(title, sents, base))
    return published, facts
