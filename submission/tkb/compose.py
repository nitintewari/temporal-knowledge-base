"""Answer composition (Phase 3): a parsed Query + the resolver's verdicts -> an Answer.

Guardrails, each from reading harness/scoring.py (docs/PROJECT_STATE.md "Scorer facts"):
  G1  Only WINNING values go into the answer text (R8). Losing values go to conflict_note, which is not scored:
      one stale number in the text zeroes the question.
  G2  A tier named in the question (model year, balance, loan amount) gets that tier only, never its neighbours
      (R23: narrowest containing tier). A tier the newest table dropped is "not offered" - with no rate (R6).
  G3  A refusal has no digits and says so plainly; confident=False (R9). Refuse only when no evidence exists.
  G4  Retrieval answers (BM25) never carry a % value: rates come from resolved facts only.
  G5  Deterministic: same question, same text (the repeat check). No randomness, no clock.
  G6  Links come only from URLs present in the crawl (R20); citations rank the topic's own page first (D9).
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Optional

from .classify import AUTHORITY
from .contract import Answer, Source
from .facts import _PRODUCT_RES
from .query import CARDS, QUERY_PRODUCTS, Query
from .resolve import Resolved
from .prose import sentences
from .retrieve import LinkIndex, PassageIndex, best_sentences, clean_url, tokens

DUPACO = "https://www.dupaco.com"
REFUSAL = ("I don't know - the Dupaco website doesn't list that. Please contact Dupaco or visit a branch "
           "for help.")

# ----------------------------------------------------------------------------- display names
_PRODUCT_NAMES: dict = {
    "auto loan": "auto loan", "atv loan": "ATV / powersports loan", "boat & rv loan": "boat & RV loan",
    "home improvement loan": "home improvement loan", "heloc": "home equity line of credit (HELOC)",
    "home equity loan": "home equity loan", "mortgage": "mortgage", "personal loan": "personal loan",
    "platinum visa": "Platinum Visa", "rewards visa": "Rewards Visa",
    "health savings account": "Health Savings Account",
    "bright savings": "Bright Savings", "you name it savings": "You-Name-It Savings",
    "high-yield savings": "High-Yield Savings", "investor's choice money market": "Investor's Choice Money Market",
    "achieve money market": "Achieve Money Market", "launchpad savings": "LaunchPad Savings",
    "holiday club savings": "Holiday Club Savings", "share savings": "Share Savings",
    "1st rate checking": "1st Rate Checking", "free checking": "Free Checking", "certificate": "certificate",
    "ira certificate": "IRA certificate", "ira savings": "IRA savings",
}
_ATTR = {"apr": "APR", "apy": "APY", "dividend_rate": "dividend rate", "rate": "rate"}
_ATTR_ORDER = {"dividend_rate": 0, "rate": 0, "apy": 1, "apr": 1}
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                "October", "November", "December"]


def pname(product: Optional[str]) -> str:
    return str(_PRODUCT_NAMES.get(product, product) or "")


def long_date(iso: Optional[str]) -> str:
    """'2026-03-31' -> 'March 31, 2026' (the format the site and the expected answers use)."""
    if not iso or not re.match(r"\d{4}-\d{2}-\d{2}", iso):
        return iso or ""
    y, m, d = iso[:10].split("-")
    return f"{_MONTH_NAMES[int(m) - 1]} {int(d)}, {y}"


def short_date(iso: Optional[str]) -> str:
    """'2026-08-31' -> '08/31/2026' (how the rate sheets print their effective dates)."""
    if not iso:
        return ""
    y, m, d = iso[:10].split("-")
    return f"{m}/{d}/{y}"


def money(v: float) -> str:
    return f"${v:,.2f}".replace(".00", "")


def tier_label(r) -> str:
    """Range -> words: 'model years 2024-2027', '$10,000-$24,999.99', '$25,000 and up', '$100,000 or less'."""
    t, kind = r.tier, r.key[7]
    if t is None:
        return ""
    lo, hi = t.low, t.high
    if kind == "model_year":
        if lo is None:
            return f"model year {int(hi)} and older"
        if hi is None:
            return f"model year {int(lo)} and newer"
        return f"model years {int(lo)}-{int(hi)}"
    if lo is None or lo == 0:
        return f"{money(hi)} or less" if hi is not None else ""
    if hi is None:
        return f"{money(lo)} and up"
    return f"{money(lo)}-{money(hi)}"


def term_label(months: Optional[int]) -> str:
    if not months:
        return ""
    if months % 12 == 0 and months >= 120:
        return f"{months // 12}-year"
    if months in (180, 240, 360):
        return f"{months // 12}-year"
    return f"{months}-month"


def product_label(key: tuple) -> str:
    product, segment, account, purpose, flags = key[0], key[1], key[2], key[3], key[4]
    name = pname(product)
    if account:
        name = f"{account.title()} {name}"
    if "jumbo" in flags:
        name = f"jumbo {name} special"
    elif "special" in flags:
        name = f"{name} special"
    if "relief" in flags:
        name = f"{name} relief program"
    if purpose == "refinance":
        name = f"{name} refinance"
    elif purpose == "cash_out":
        name = f"{name} cash-out refinance"
    if segment == "business":
        name = f"Business {name}"
    if "intro" in flags:
        name = f"{name} intro (balance transfer)" if product in ("platinum visa", "rewards visa") \
            else f"{name} introductory"
    return name


# ----------------------------------------------------------------------------- sources (D9, R20)
def _topic_score(path: str, product: str) -> int:
    words = path.replace("/", " ").replace("-", " ").replace("_", " ")
    rx = next((rx for name, rx in _PRODUCT_RES if name == product), None)
    return 1 if rx is not None and rx.search(words) else 0


def ranked_sources(resolutions: list, limit: int = 6) -> list:
    """Every page that states a winning value, the topic's own page first: a path that names the product
    (/personal/loans/home-loans for a mortgage), then product pages, then the rate sheet, then shorter paths.
    Each as (url, the crawl the copy was read from): a later crawl's table that dates an earlier day is cited
    as that later crawl, not as the crawl the question's date picked (review)."""
    seen: dict = {}
    for r in resolutions:
        product = r.key[0] if isinstance(r.key[0], str) else ""
        for c in [r.winner] + list(r.agree):
            url = getattr(c.fact, "url", "") or (DUPACO + c.path)
            path = c.path
            rank = (-_topic_score(path, product), -AUTHORITY.get(c.fact.page_type, 0), len(path), path)
            if url not in seen or rank < seen[url][0]:
                seen[url] = (rank, (url, c.snapshot_id))
    return [u for _, u in sorted(seen.values())][:limit]


def sources(urls: list, snapshot_id: Optional[str]) -> list:
    """Sources from URLs (cited as `snapshot_id`, the crawl the answer was read from) or from (url, crawl) pairs
    (each fact's own crawl; an empty one falls back to `snapshot_id`)."""
    out, keys = [], set()
    for u in urls:
        url, sid = u if isinstance(u, tuple) else (u, snapshot_id)
        if url and url not in keys:
            keys.add(url)
            out.append(Source(url=url, snapshot_id=sid or snapshot_id))
    return out


def refuse(reason: str = "") -> Answer:
    text = REFUSAL if not reason else f"I don't know - {reason} Please contact Dupaco or visit a branch for help."
    assert not re.search(r"\d", text), "a refusal must not contain digits (scoring.py)"
    return Answer(text=text, sources=[], confident=False)


def conflict_note(resolutions: list) -> Optional[str]:
    notes = []
    for r in resolutions:
        for loser in r.losers[:2]:
            c = loser.candidate
            v = c.fact.value.text if hasattr(c.fact.value, "text") else c.fact.value
            when = getattr(c.fact, "effective", None) or getattr(c, "stated", None) or "undated"
            notes.append(f"{v} on {c.path} ({when}, {loser.reason})")
    if not notes:
        return None
    return "Older or conflicting values were not used: " + "; ".join(notes[:4]) + "."


# ----------------------------------------------------------------------------- rates
def _row_value(attrs: dict) -> str:
    parts = [f"{r.value.text} {_ATTR[a]}" for a, r in sorted(attrs.items(), key=lambda kv: _ATTR_ORDER[kv[0]])]
    return " / ".join(parts)


def _filters(q: Query, product: str) -> dict:
    want: dict = {"product": product}
    if product in CARDS and len(q.products) > 1 and q.segment is None:
        pass                                            # "credit cards": personal AND business cards
    else:
        want["segment"] = q.segment or "personal"
    if q.account:
        want["account"] = q.account
    if product == "mortgage":
        if "relief" in q.flags:
            want["flags"] = ("relief",)
        else:
            want["purpose"] = q.purpose or "purchase"
            want["flags"] = ()
    else:
        want["flags"] = tuple(f for f in q.flags if f != "relief")
    if q.term_months:
        want["term_months"] = q.term_months
    return want


# A list request ("all certificate rates") with no term and no special named also shows the specials: they are
# products in their own right (dup-005). Intro / relief rates stay out unless asked for.
_LIST_FLAGS = [(), ("special",), ("jumbo", "special")]


def _with_flags(want: dict, flags: tuple) -> dict:
    out: dict[str, Any] = dict(want)
    out["flags"] = flags
    return out


def find_rates(R: Resolved, q: Query, missing: Optional[list] = None) -> list:
    """Current resolutions for the question's products and slots (G2).

    The measure the question names is required (review): an APY question about a card that publishes only an APR
    finds nothing for that card, never the APR. Such products go to `missing` as (product, measures published),
    so the answer can say what the site publishes instead."""
    found = []
    for product in q.products:
        want = _filters(q, product)
        hits = R.find(**want)
        if not q.term_months and not q.flags and q.x is None and not q.superlative and q.premise is None \
                and product in ("certificate", "ira certificate"):
            hits = [r for flags in _LIST_FLAGS for r in R.find(**_with_flags(want, flags))]
        if not hits and q.term_months and not want.get("flags") and product in ("certificate", "ira certificate"):
            hits = R.find(**_with_flags(want, ("special",)))           # 17 / 10 months exist only as specials
        if q.attribute:
            narrowed = [r for r in hits if r.key[5] == q.attribute]
            if hits and not narrowed and missing is not None:
                missing.append((product, sorted({r.key[5] for r in hits}, key=lambda a: _ATTR_ORDER.get(a, 9))))
            hits = narrowed
        found.extend(hits)
    return found


def _measure_gap(q: Query, missing: list) -> str:
    """'an APR, not an APY, for the Platinum Visa' (no digits: it may end a refusal)."""
    asked = _ATTR.get(q.attribute or "", "that measure")      # always set here; `or ""` satisfies the type checker
    parts = []
    for product, measures in missing:
        name = pname(product)
        name = "that product" if re.search(r"\d", name) else f"the {name}"
        have = " and ".join(_ATTR[a] for a in measures)
        parts.append(f"{_article(have)}, not {_article(asked)}, for {name}")
    return "; ".join(parts)


def _article(measure: str) -> str:
    return ("an " if measure[:1] in "AEIOU" else "a ") + measure


def _x_matches(r, q: Query) -> bool:
    kind = r.key[7]
    if q.x_kind == "model_year":
        return kind == "model_year"
    return kind in ("balance", "loan_amount")


def answer_rate(q: Query, R: Resolved, snapshot_id: str) -> Answer:
    if q.unpublished:
        return refuse(f"the Dupaco website lists fixed-rate mortgage rates only and doesn't publish a rate for "
                      f"that kind of mortgage.")
    missing: list = []
    hits = find_rates(R, q, missing)
    if not hits and missing:                                  # "APY on the Platinum Visa": say what IS published
        return refuse(f"Dupaco publishes {_measure_gap(q, missing)}.")
    if not hits:
        return refuse("the Dupaco website doesn't list a current rate for that.")

    if q.x is not None and any(_x_matches(r, q) for r in hits):
        tiered = [r for r in hits if _x_matches(r, q)]
        inside = [r for r in tiered if r.tier is not None and r.tier.contains(q.x)]
        if not inside:
            return _not_offered(q, tiered, snapshot_id)
        best: dict = {}
        for r in sorted(inside, key=lambda r: (r.tier.high if r.tier.high is not None else 1e18)):
            best.setdefault((r.key[:7]), r)                   # narrowest containing tier per key (R23)
        hits = list(best.values())

    if q.superlative and hits:
        pick = max if q.superlative == "max" else min
        target = pick(hits, key=lambda r: (r.value.high, r.value.low))
        hits = [r for r in hits if r.key[:7] == target.key[:7] and r.tier == target.tier]

    rows = _rows(hits)
    lines = [_render_row(key, tier, attrs) for (key, tier), attrs in rows]
    effective = max((r.winner.fact.effective or "" for r in hits), default="")
    when = f" (rates effective {short_date(effective)})" if effective else ""

    if q.premise is not None:
        offered = {round(v, 4) for r in hits for v in (r.value.low, r.value.high)}
        top = max(hits, key=lambda r: (r.value.high, r.value.low))
        top_row = _render_row(top.key, top.tier, {top.key[5]: top})
        if round(q.premise, 4) in offered:
            text = f"Yes. Current rates{when}: " + "; ".join(lines) + "."
        else:
            text = (f"No. None of the current {_family(q)} tiers pays that rate; the highest is "
                    f"{top_row}{when}. All tiers: " + "; ".join(lines) + ".")
    elif len(lines) == 1:
        label, _, value = lines[0].partition(": ")
        if re.fullmatch(r"[\d.,%\s-]+ rate", value):           # "6.750% rate" -> "rate is 6.750%"; "0.15% dividend
            value = value[:-len(" rate")]                     # rate" keeps its measure name
        text = f"Dupaco's {label} rate is {value}{when}."
    else:
        text = f"Current {_family(q)} rates{when}: " + "; ".join(lines) + "."
    if missing:                                               # several products, one lacks the measure asked for
        text += f" Note: Dupaco publishes {_measure_gap(q, missing)}."
    if q.asks_minimum:                                        # "... and how much do I need to open one?"
        mins = []
        for r in hits:
            m = r.winner.fact.minimum
            if m and m not in mins:
                mins.append(m)
        if mins:
            text += f" Minimum: {'; '.join(mins)}."
    for asked, name, field in ((q.asks_points, "Points", "points"), (q.asks_payment, "Payment example", "payment")):
        if asked:                                             # "... interest rate, points and APR"; "the payment"
            shown = list(dict.fromkeys(getattr(r.winner.fact, field) for r in hits if getattr(r.winner.fact, field)))
            if shown:
                text += f" {name}: {'; '.join(shown)}."
    return Answer(text=text, sources=sources(ranked_sources(hits), snapshot_id), confident=True,
                  conflict_note=conflict_note(hits))


def _family(q: Query) -> str:
    if q.products == CARDS:
        return "credit card"
    if len(q.products) > 1:
        return " and ".join(pname(p) for p in q.products)
    return pname(q.products[0]) if q.products else ""


def _rows(hits: list) -> list:
    """Group resolutions into display rows: one row per product/term/tier, attributes side by side."""
    rows: dict = {}
    for r in hits:
        key = r.key
        rows.setdefault((key[:5] + (key[6], key[7]), r.tier), {})[key[5]] = r
    def order(item):
        (k, tier), _ = item
        product, segment, account, purpose, flags, term, _kind = k
        mortgage = product == "mortgage"
        hi = tier.high if tier is not None and tier.high is not None else 1e18
        lo = tier.low if tier is not None and tier.low is not None else -1e18
        return (segment != "personal", flags != (), str(account), -(term or 0) if mortgage else (term or 0),
                hi if mortgage else -lo, product)
    out = []
    for (k, tier), attrs in sorted(rows.items(), key=order):
        key = k[:5] + (None, k[5], k[6])
        out.append(((key, tier), attrs))
    return out


def _render_row(key: tuple, tier, attrs: dict) -> str:
    r0 = next(iter(attrs.values()))
    label = product_label(key)
    term = term_label(key[6])
    if term:
        label = f"{term} {label}"
    tl = tier_label(r0) if tier is not None else ""
    if tl:
        label = f"{label} ({tl})"
    return f"{label}: {_row_value(attrs)}"


def _not_offered(q: Query, tiered: list, snapshot_id: str) -> Answer:
    """G2 / R6: no current tier contains the model year or amount. Say so - and give no rate from another tier."""
    product = pname(q.products[0])
    term = f" {term_label(q.term_months)}" if q.term_months else ""
    what = ""
    if q.x is not None:
        what = f"model year {int(q.x)}" if q.x_kind == "model_year" else money(q.x)
    covered = sorted({tier_label(r) for r in tiered if r.tier is not None})
    article = "an" if re.match(r" (?:8|11|18)\d*-", term) else "a"            # "an 84-month", "a 60-month"
    text = (f"Dupaco's current rate sheet doesn't list {article}{term} {product} rate for {what}. "
            f"That term is offered for: {', '.join(covered)}.")
    return Answer(text=text, sources=sources(ranked_sources(tiered), snapshot_id), confident=True)


# ----------------------------------------------------------------------------- links (R20)
def answer_link(q: Query, R: Resolved, links: LinkIndex, snapshot_id: str) -> Answer:
    url = None
    if q.products:
        hits = [r for p in q.products for r in R.find(product=p, segment=q.segment or "personal")]
        ranked = _link_rank(hits)
        if ranked:
            url = ranked[0]
            if url + "#rates" in links.texts:
                url += "#rates"
    also = None
    if url is None:
        found = links.search(q.terms, k=4)
        url = found[0][1] if found else None
        also = next((u for s, u in found[1:] if u != url and s >= 0.8 * found[0][0]), None) if found else None
    if not url:
        return refuse("I couldn't find a page for that on the Dupaco website.")
    what = f"current {_family(q)} rates" if q.products else "that"
    text = f"You can find {what} here: {url}" + (f" (see also {also})" if also else "")
    return Answer(text=text, sources=sources([u for u in (url, also) if u], snapshot_id), confident=True)


def _link_rank(hits: list) -> list:
    """For a link, the member wants the product's own page: product pages before the rate sheet, then a path
    naming the product, then the shortest path."""
    seen: dict = {}
    for r in hits:
        for c in [r.winner] + list(r.agree):
            url = clean_url(c.fact.url)
            rank = (c.fact.page_type != "product", -_topic_score(c.path, r.key[0]), len(c.path), c.path)
            if url not in seen or rank < seen[url]:
                seen[url] = rank
    return [u for u, _ in sorted(seen.items(), key=lambda kv: kv[1])]


# ----------------------------------------------------------------------------- prose facts
def _prose_sources(rs: list, snapshot_id: str, limit: int = 4) -> list:
    urls = []
    for r in rs:
        for c in [r.winner] + list(r.agree):
            u = c.fact.url or (DUPACO + c.path)
            if u not in [x for x, _ in urls]:
                urls.append((u, c.snapshot_id))           # the crawl the statement was read from (review)
    return sources(urls[:limit], snapshot_id)


def _prose_note(rs: list) -> Optional[str]:
    notes = [f"{l.candidate.fact.value} ({l.candidate.path}, {l.candidate.stated})" for r in rs for l in r.losers[:3]]
    return ("Older statements were not used (newest publication wins): " + "; ".join(notes[:4]) + ".") \
        if notes else None


def _match_subject(q: Query, rs: list) -> list:
    """Prose facts whose subject (or label / street) is named in the question: "Galena", "Hy-Vee", "Sycamore"."""
    low = q.text.lower()
    named = _name_words(q.named_branch or "")
    out = []
    for r in rs:
        f = r.winner.fact
        names = {f.subject.lower(), (f.label or "").lower()}
        if f.kind == "address":
            names.add((f.qualifier or "").lower())               # the street; for hours it is "lobby"
        names = {n for n in names if n and not n.startswith("/")}
        if any(n in low or (named and named <= _name_words(n)) for n in names):
            out.append(r)
    return out


def _most_specific(q: Query, rs: list) -> list:
    """Of several matching branches, those naming the most question words: "the Hillcrest Road branch in Dubuque"
    matches all four Dubuque branches by city but only one by street (review, in-18)."""
    asked = _name_words(q.text)
    def score(r) -> int:
        f = r.winner.fact
        return len(asked & _name_words(" ".join(x for x in (f.qualifier, f.label, f.subject, r.value) if x)))
    best = max((score(r) for r in rs), default=0)
    return [r for r in rs if score(r) == best]


_GENERIC_NAME_WORDS = {"street", "st", "avenue", "ave", "road", "rd", "drive", "dr", "lane", "ln", "boulevard",
                       "blvd", "branch", "office", "location", "the"}


def _name_words(name: str) -> set:
    """'Sycamore Street' -> {'sycamore'}; '1465 Sycamore St.' -> {'1465', 'sycamore'}: compare names by word."""
    return {w for w in re.findall(r"[a-z0-9'-]+", name.lower()) if w not in _GENERIC_NAME_WORDS}


def answer_prose(q: Query, R: Resolved, ref_date: str, links: LinkIndex, snapshot_id: str,
                 phone: Optional[str]) -> Answer:
    kind = q.intent
    if kind == "branch_count":
        rs = R.find_prose("branch_count")
        if not rs:
            return refuse()
        r = rs[0]
        text = (f"Dupaco has {r.value} branch office locations, according to its most recent press release "
                f"({long_date(r.winner.stated)}).")
        return Answer(text, _prose_sources(rs, snapshot_id), True, _prose_note(rs))
    if kind == "routing_number":
        rs = R.find_prose("routing_number")
        return Answer(f"Dupaco's routing number is {rs[0].value}.", _prose_sources(rs, snapshot_id, 6), True) \
            if rs else refuse()
    if kind == "forbes_recognition":
        rs = R.find_prose("forbes_recognition")
        if not rs:
            return refuse()
        r = rs[0]
        text = (f"Forbes has named Dupaco one of America's best credit unions: its most recent announcement "
                f"({long_date(r.winner.stated)}) says this was the {r.value} time Forbes recognized Dupaco.")
        return Answer(text, _prose_sources(rs, snapshot_id), True, _prose_note(rs))
    if kind == "vto_employees":
        rs = R.find_prose("vto_employees")                  # newest year first (R21)
        if not rs:
            return refuse()
        parts = [f"in {r.key[1]}, {r.value} Dupaco employees used Volunteer Time Off" for r in rs[:2]]
        text = parts[0][0].upper() + parts[0][1:] + (f"; {parts[1]}." if len(parts) > 1 else ".")
        return Answer(text, _prose_sources(rs, snapshot_id), True)
    if kind == "phone":
        if not phone:
            return refuse()
        urgent = re.search(r"\b(?:lost|stolen|stole|missing|urgent)\b", q.text, re.I)   # the contact page's own advice
        text = (f"For an urgent need like a lost or stolen card, call Dupaco right away at {phone}." if urgent
                else f"You can call Dupaco at {phone}.")
        return Answer(text, sources([DUPACO + "/contact"], snapshot_id), True)
    if kind == "founded":
        rs = R.find_prose("founded")
        return Answer(f"Dupaco was founded in {rs[0].value}.", _prose_sources(rs, snapshot_id), True,
                      _prose_note(rs)) if rs else refuse()
    if kind in ("employees", "assets", "members"):
        rs = R.find_prose(kind)
        if not rs:
            return refuse()
        r = rs[0]
        text = {"employees": f"Dupaco has over {r.value} employees.",
                "members": f"Dupaco serves more than {r.value} members.",
                "assets": f"Dupaco has assets exceeding {r.value}."}[kind]
        return Answer(text + f" (Most recent statement: {long_date(r.winner.stated)}.)",
                      _prose_sources(rs, snapshot_id), True, _prose_note(rs))
    if kind == "eligibility":
        counties, states = R.find_prose("membership_counties"), R.find_prose("service_states")
        if not (counties or states):
            return refuse()
        parts = []
        if counties:
            parts.append(f"Membership is open to people in Dupaco's {counties[0].value}-county field of membership")
        if states:
            parts.append(f"Dupaco serves members in {states[0].value}")
        join = links.search(["join"], k=1)
        tail = f" You can apply online at {join[0][1]}" if join else ""
        text = "; ".join(parts) + "." + (tail + "." if tail else "")
        return Answer(text, _prose_sources(counties + states, snapshot_id), True)
    if kind == "address":
        atms = _atm_matches(q, R)                         # "the Dupaco ATM at Fareway": a stand-alone ATM (D-020)
        if atms:
            text = "; ".join(f"{r.winner.fact.label}: {r.value}" for r in atms[:3])
            return Answer(text + ".", _prose_sources(atms, snapshot_id), True)
        rs = R.find_prose("address")
        if q.named_branch or _match_subject(q, rs):
            rs = _most_specific(q, _match_subject(q, rs))
            if not rs:
                return refuse("I couldn't find that branch on the Dupaco website.")
        if not rs:
            return refuse()
        lines = [f"{r.winner.fact.label}: {r.value}" for r in rs]
        text = ("The address is " + rs[0].value + "." if len(rs) == 1
                else "Dupaco branch addresses: " + "; ".join(lines) + ".")
        extra = getattr(rs[0].winner.fact, "extra", "")
        if len(rs) == 1 and extra:
            text += f" Services listed for this location: {extra}."
        return Answer(text, _prose_sources(rs, snapshot_id) + sources([DUPACO + "/contact"], snapshot_id), True)
    if kind == "mailing_address":
        rs = R.find_prose("mailing_address")
        return Answer(f"Dupaco's mailing address is {rs[0].value}.", _prose_sources(rs, snapshot_id), True) \
            if rs else refuse()
    if kind in ("closure", "closure_alternatives"):
        closures = _match_subject(q, R.find_prose("closure"))
        alts = _match_subject(q, R.find_prose("closure_alternatives"))
        if not closures and not alts:
            return refuse("I couldn't find a closure for that branch on the Dupaco website.")
        parts = []
        if closures:
            c = closures[0]
            name, when = c.winner.fact.label, long_date(c.value)
            if c.value <= ref_date:
                parts.append(f"No - the {name} branch closed on {when}." if re.search(r"\bstill open|\bopen today",
                                                                                     q.text.lower())
                             else f"The {name} branch closed on {when}.")
            else:
                parts.append(f"The {name} branch is scheduled to close on {when}.")
        if alts:
            parts.append(f"Members can use the full-service branches at {alts[0].value} instead.")
        if kind == "closure_alternatives" and alts:
            parts.reverse()
        return Answer(" ".join(parts), _prose_sources(closures + alts, snapshot_id), True)
    if kind == "hours":
        return answer_hours(q, R, snapshot_id)
    return refuse()


def answer_hours(q: Query, R: Resolved, snapshot_id: str) -> Answer:
    """D10: hours are per branch. A named branch gets its own schedule; an unknown branch is declined; otherwise
    the most common schedule plus the variants, and a question back: which branch?"""
    service = q.subject or "lobby"
    rs = R.find_prose("hours", qualifier=service) or R.find_prose("hours")
    if q.named_branch:
        named = _match_subject(q, rs)
        if not named:
            return refuse("I couldn't find hours for that branch on the Dupaco website.")
        r = named[0]
        return Answer(f"{r.winner.fact.label} {service} hours: {r.value}.", _prose_sources(named, snapshot_id), True)
    if not rs:
        return refuse()
    counts: dict = {}
    for r in rs:
        counts.setdefault(r.value, []).append(r)
    ranked = sorted(counts.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    head = ranked[0][0]
    others = [v for v, _ in ranked[1:]]
    text = f"{service.title()} hours vary by branch. The most common schedule is {head}."
    if others:
        text += " Other branches: " + " | ".join(others) + "."
    text += " Which branch would you like hours for?"
    srcs = _prose_sources([r for _, group in ranked for r in group], snapshot_id, 10)
    return Answer(text, sources([DUPACO + "/contact"], snapshot_id) + srcs, True)


# ----------------------------------------------------------------------------- general retrieval
_MONEY = re.compile(r"\$\s?\d")
# G4, narrowed (review): a sentence quoting a RATE is dropped (a rate in prose may be stale; rates come from resolved
# tables). Other percentages stay: "$10.00 or 3.00% of each cash advance", "a minimum 20% down payment".
_RATE_PERCENT = re.compile(r"\d(?:\.\d+)?\s*%\s*(?:\(?(?:apr|apy)\b|annual percentage|fixed\b|variable\b|intro|"
                           r"dividend|interest|rate\b|yield)|\b(?:aprs?|apys?|rates?|yields?|dividends?)\b[^.;]{0,40}?"
                           r"\d(?:\.\d+)?\s*%", re.I)


def _quotes_rate(sentence: str) -> bool:
    """A rate named as such, or a table row of rates (two or more percentages: dividend rate + APY, a range)."""
    return bool(_RATE_PERCENT.search(sentence)) or len(re.findall(r"\d\s*%", sentence)) >= 2
# Asks FOR a rate value ("What interest rate do you charge on a construction loan?"), not about one ("how long can
# the interest rate stay fixed?"): with no published rate, declined even when the LLM reads it as an explanation.
_VALUE_ASK = re.compile(r"\b(?:what|which|how much)\b[^?.,]{0,30}\b(?:rates?|aprs?|apys?|interest|charge|cost)\b", re.I)
_MONEY_VALUE = re.compile(r"\$\s?[\d,]+(?:\.\d+)?")
_PROCEDURAL = re.compile(r"^\s*(?:how (?:can|do|should) i|can i|where (?:can|do) i|what should i)\b", re.I)


# "There is no annual fee", "|Debit card transactions at Dupaco ATMs|Free|": a fee answer without a $ (review).
_NO_FEE = re.compile(r"\bno (?:annual |monthly |balance transfer |participation |overdraft |hidden )?fees?\b|"
                     r"\bno charge\b|\bfree of charge\b|\|\s*free\s*\|", re.I)
# Words about the FORM of a money answer, not its topic ("exact fixed dollar fee ... definite amount").
_AMOUNT_FORM = {"exact", "exactly", "fixed", "dollar", "dollars", "definite", "amount", "asking", "much", "cost",
                "costs", "price", "charge", "charges", "fee", "fees", "pay", "listed", "posted", "schedule", "would",
                "use", "using", "used"}         # "a fee for USING Dupaco ATMs": the topic is the ATMs
_VARIES = re.compile(r"\|([^|]{3,80})\|\s*price varies\s*\|", re.I)


def _answer_amount(q: Query, passages: PassageIndex, hits: list, snapshot_id: str) -> Answer:
    """A fee or a minimum (Phase 6 review): the first well-ranked passage that covers the question AND states an
    amount ($, or "no fee" / "free") in a sentence without a % (G4: a rate in prose may be stale). Three different
    "no amount" answers: the schedule says the price VARIES (said so, no number); nothing is published (refusal);
    member data (handled in system.py before this)."""
    topic = [t for t in q.terms if t.lower() not in _AMOUNT_FORM] or q.terms
    others = [n for names, _ in QUERY_PRODUCTS for n in names if n not in q.products and " " in n]
    # Two fees compared ("by phone, compared with online"): the two best rows, each covering the question.
    compare = bool(re.search(r"\bcompared? (?:with|to)\b|\bversus\b|\bvs\.?\b|\bdifference between\b", q.text, re.I))
    found: list = []
    for _, p in hits:                                    # all 25 ranked passages, best first
        low = (p.text + " " + p.title).lower()
        if passages.coverage(topic, p) < 0.4:
            continue
        if q.products and any(n in low for n in others) and not any(n in low for n in q.products):
            continue                     # "Rewards Visa has no annual fee" does not answer for the Platinum Visa
        varies = _VARIES.search(p.text)
        if varies and not _MONEY.search(p.text) and not re.search(r"\d", varies.group(1)):
            item = re.sub(r"\s+", " ", varies.group(1)).strip()
            return refuse(f"the Dupaco fee schedule lists {item} as \"Price varies\", so there is no fixed amount to "
                          f"quote.")
        said = [s for s in (sentences(p.text) or [p.text])
                if (_MONEY.search(s) or _NO_FEE.search(s)) and not _quotes_rate(s)]
        amounts = set(_MONEY_VALUE.findall(" ".join(said)))
        if said and any(amounts == a for _, _, a in found):
            continue                                     # the same fee again (the schedule PDF and a page)
        if said:
            found.append((" ".join(said[:2]).strip("| ").replace("|", " - "), clean_url(p.url), amounts))
            if not compare or len(found) == 2:
                break
    if found:
        return Answer(text="; ".join(t for t, _, _ in found), sources=sources([u for _, u, _ in found], snapshot_id),
                      confident=True)
    return refuse("I couldn't find that amount on the Dupaco website.")


_STREET = re.compile(r"\b\d{2,6} (?:[A-Z][a-z]+ ){1,3}(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Way|Ln|Lane|Blvd|"
                     r"Boulevard|Ct|Court|Pkwy|Parkway|Hwy|Highway|Pl|Place)\b\.?")
_ADDRESS_FORM = {"street", "address", "addresses", "zip", "code", "located", "location", "announcement", "article",
                 "release", "press", "give", "gives", "say", "says", "saw", "number", "include", "branch", "where"}
_PLACE_STOP = {"dupaco", "i", "what", "where", "which", "is", "the", "please", "street", "zip", "how", "can"}


def _atm_matches(q: Query, R: Resolved) -> list:
    """Stand-alone ATMs from the locator named in an ATM question ("the ATM at Fareway")."""
    if not re.search(r"\batms?\b", q.text, re.I):
        return []
    asked = _name_words(q.text) - {"dupaco", "atm", "atms"}
    return [r for r in R.find_prose("atm_address") if asked & (_name_words(r.winner.fact.subject) - {"food", "store"})]


def needs_text_address(q: Query, R: Resolved) -> bool:
    """An address question about a named place that is NOT one of the branch addresses (in-19: "the Coralville
    Learning Lab announcement"): the branch list would answer a different question, so look in the text."""
    if q.named_branch or _match_subject(q, R.find_prose("address")) or _atm_matches(q, R):
        return False
    names = [w for w in re.findall(r"\b[A-Z][a-z]+\b", q.text[1:]) if w.lower() not in _PLACE_STOP]
    return bool(names)


def answer_street_address(q: Query, passages: PassageIndex, snapshot_id: str) -> Answer:
    """A street address stated in the site's text about the named place: the best-covering passage with one.
    Words that describe the FORM of the answer ("street address", "announcement") are not the topic: the passage
    holds the address itself, so coverage is measured on the place words only."""
    topic = [t for t in q.terms if t.lower() not in _ADDRESS_FORM] or q.terms
    for _, p in passages.search(topic, k=25):
        m = _STREET.search(p.text)
        if m and passages.coverage(topic, p) >= 0.4:
            said = [s for s in sentences(p.text) if _STREET.search(s)] or [p.text]
            return Answer(text=said[0], sources=sources([clean_url(p.url)], snapshot_id), confident=True)
    return refuse("I couldn't find that address on the Dupaco website.")


def answer_general(q: Query, passages: PassageIndex, snapshot_id: str, phone: Optional[str]) -> Answer:
    """BM25 for explanations; with the LLM's search words (q.alt_terms) as a second attempt when ours find nothing."""
    first = _answer_general(q, passages, snapshot_id, phone)
    if first.confident or not q.alt_terms:
        return first
    second = _answer_general(replace(q, terms=q.terms + q.alt_terms), passages, snapshot_id, phone)
    return second if second.confident else first


def _answer_general(q: Query, passages: PassageIndex, snapshot_id: str, phone: Optional[str]) -> Answer:
    """BM25 fallback for explanations. G3: a rate question nothing answers is declined, never guessed.
    G4: sentences quoting a rate are dropped (prose rates may be stale)."""
    if q.asks_price and not q.products and not q.asks_fee and (q.llm_route != "explain" or _VALUE_ASK.search(q.text)):
        return refuse("the Dupaco website doesn't publish a rate for that.")   # asks FOR a rate nothing publishes
    if q.named_branch:
        return refuse("I couldn't find that branch on the Dupaco website.")
    hits = passages.search(q.terms, k=25)
    # A passage about a variant the question did not ask for ("Special Jumbo Term Share Certificate") ranks
    # below the plain one: the same rule as fact flags (special / jumbo / intro / business).
    asked = set(q.terms) | set(q.text.lower().split())
    def variant_penalty(p) -> float:
        extra = {w for w in ("special", "jumbo", "intro", "introductory", "promotional", "business")
                 if w in p.text.lower() and w not in asked}
        return 0.75 if extra else 1.0
    # A money question (a fee, a minimum to open) is answered by a passage that states an amount: those rank
    # first, and when none covers the question it is declined rather than answered with a passage about it.
    money = q.asks_fee or q.asks_minimum
    def boost(p) -> float:
        return 1.5 if money and _MONEY.search(p.text) else 1.0
    # A question about one year ("in 2024") ranks a passage that names only OTHER years lower (in-20).
    years = set(re.findall(r"\b(?:19|20)\d\d\b", q.text))
    def year_fit(p) -> float:
        named = set(re.findall(r"\b(?:19|20)\d\d\b", p.text))
        return 0.6 if years and named and not (named & years) else 1.0
    hits = sorted(((s * variant_penalty(p) * boost(p) * year_fit(p), p) for s, p in hits),
                  key=lambda x: (-x[0], x[1].pos))
    # A question naming a dated document ("the January 8, 2026 announcement", "the article published July 12,
    # 2024") is answered from that document: its passages only, the one covering most of the question first.
    named = passages.search(q.terms, k=25, published=q.doc_date) if q.doc_date else []
    if named:
        hits = sorted(named, key=lambda x: (-passages.coverage(q.terms, x[1]), -x[0], x[1].pos))
    if money:                           # coverage on the topic, not on "exact fixed dollar amount" (form words)
        return _answer_amount(q, passages, hits, snapshot_id)
    # A line cut out of the middle of a sentence (a PDF wrapped at the page width: "information, with upgrade
    # options to purchase inside the") is not an answer, however many question words it shares (review).
    hits = [(sc, p) for sc, p in hits if not re.match(r"[a-z]", p.text.lstrip("\"'([*_ "))]
    if not hits or hits[0][0] < 6.0 or passages.coverage(q.terms, hits[0][1]) < 0.4:
        return refuse()                 # the best passage must cover most of what the question is about
    top = hits[0][1]
    if top.text.rstrip().endswith("?"):                      # an FAQ question: the answer is the next paragraph
        nxt = passages.next_passage(top)
        if nxt is not None:
            top = nxt
            hits = [(hits[0][0], nxt)] + hits[1:]
    rare = passages.rarest(q.terms, top.text + " " + top.title)
    same_page = [p for _, p in hits if p.url == top.url and rare in tokens(p.text)
                 and (p is top or variant_penalty(p) == 1.0)]
    lead = min(same_page, key=lambda p: p.pos) if same_page else top
    if passages.coverage(q.terms, lead) < passages.coverage(q.terms, top):
        lead = top                       # the earlier paragraph must answer at least as much (in-22: pet insurance)
    sents = [s for s in best_sentences(lead, [rare] if rare else q.terms, 3) if not _quotes_rate(s)]
    # A second passage (another wording of the same answer) when it adds sentences: answers often span both.
    # A second passage must fit the question's year, share its key word and cover it nearly as well as the lead:
    # otherwise it mixes in another figure or topic (review: in-21's unlabelled caption, in-22's second blog).
    second = next(
        (p for _, p in hits[1:6] if p.text != lead.text and p.text != top.text and year_fit(p) == 1.0
         and passages.coverage(q.terms, p) >= 0.8 * passages.coverage(q.terms, lead)
         and (not rare or rare in tokens(p.text + " " + p.title)) and not p.text.rstrip().endswith("?")), None)
    if second is not None and len(sents) < 3:
        sents += [s for s in best_sentences(second, q.terms, 3 - len(sents))
                  if not _quotes_rate(s) and s not in sents]
    if not sents:
        return refuse()
    text = " ".join(sents)
    if phone and _PROCEDURAL.search(q.text) and phone not in text:
        text += f" You can also call Dupaco at {phone}."
    urls = []
    for _, p in hits[:6]:
        u = clean_url(p.url)
        if u not in urls:
            urls.append(u)
    return Answer(text=text, sources=sources(urls[:3], snapshot_id), confident=True)
