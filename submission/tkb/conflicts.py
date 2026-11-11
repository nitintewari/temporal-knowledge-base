"""conflicts(): every place the website contradicts itself, one Conflict per topic (Phase 5, evidence kept: 6).

Built from the resolver's verdicts (resolve.py), never re-deciding them: a topic's `resolution` is the value the
resolver picked, its `reason` the resolver's reason code in words. Nothing here reads pages.

What counts as a contradiction (docs/RULES.md):
    tables  a slot whose losers carry a DIFFERENT value for the same fact key and tier, in the same crawl: a
            calculator, guidance page, promo page or second rate table still showing old numbers (R2, R3, R25).
    prose   a company fact (branch count, Forbes recognition, assets) where an older publication of the last
            24 months states another value than the newest one (R4). Older statements are history.

What does not (F1-F3):
    - different tiers, rate vs APY, standard vs jumbo, personal vs business: different keys or the same topic;
    - the same value on many pages (R17), a value that changed between crawls with no page left behind
      (HISTORICAL_VERSION_CHANGE, E19), URL variants of one page (R13, same text);
    - D1 Traditional vs Roth IRA (different account = different key), D8 relabelled term with equal values.

Grouping, for precision (the score is F1 over topics): one Conflict per product + segment + purpose + term.
Tiers, rate + APY (or dividend rate + APY) and the jumbo variant of a special share it, so "60-month auto loan
APR" is one Conflict however many model-year rows disagree.

Evidence per crawl (Phase 6): every crawl that shows a topic's contradiction keeps its own CrawlEvidence (crawl
date, winning values with their pages and dates, stale values with theirs, sources). Nothing is overwritten.
The newest crawl decides `values` (its winners, then its stale values, as written) and `resolution`; the older
crawls appear in `reason` ("earlier: ...") and in `sources` (each tagged with its snapshot_id). Older values are
kept out of `values` on purpose: the scorer matches topics by values, and a past winner such as "6.000%" would
let one topic match another topic's gold entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .classify import AUTHORITY
from .compose import DUPACO, pname
from .contract import Conflict, Source
from .resolve import (CONSISTENT_ROW_OVER_INCONSISTENT, CURRENT, EXPLICIT_EFFECTIVE_DATE, NEWER_FETCH,
                      NEWEST_PUBLICATION, OFFICIAL_RATE_TABLE_OVER_CALCULATOR, Resolved)

ATTR = {"apr": "APR", "apy": "APY", "dividend_rate": "dividend rate", "rate": "rate"}
ATTR_ORDER = {"rate": 0, "dividend_rate": 0, "apr": 1, "apy": 1}

# prose kinds reported, with how a value is written and the topic's name. Members / employees are left out:
# the newest boilerplate words them differently, so their "newest" statement is years old (not a contradiction).
PROSE_TOPICS = {
    "branch_count": ("{} branches", "Number of Dupaco branches (branch count)"),
    "forbes_recognition": ("{} time", "Forbes recognition (how many times Forbes ranked Dupaco)"),
    "assets": ("{}", "Dupaco total assets"),
}
PROSE_WINDOW_DAYS = 730
PROSE_SOURCES = 4            # stale publications cited per crawl (the newest ones); branch count has 40+


def term_name(months: Optional[int]) -> str:
    if not months:
        return ""
    if months >= 120 and months % 12 == 0:
        return f"{months // 12}-year ({months}-month)"
    return f"{months}-month"


def topic_key(key: tuple) -> tuple:
    """Fact key -> topic: (product, segment, account, purpose, flags without 'jumbo', term). Attribute and tier
    kind are dropped on purpose (rate + APY and every tier share one topic)."""
    product, segment, account, purpose, flags, _attr, term = key[:7]
    return (product, segment, account, purpose, tuple(f for f in flags if f != "jumbo"), term)


def topic_name(tk: tuple, attrs: set) -> str:
    product, segment, account, purpose, flags, term = tk
    name = pname(product)
    if account:
        name = f"{account.title()} {name}"
    if "special" in flags:
        name = f"{name} special"
    if "relief" in flags:
        name = f"{name} relief program"
    if "intro" in flags:
        name = f"{name} introductory"
    if segment == "business":
        name = f"business {name}"
    if purpose:
        name = f"{name} ({purpose.replace('_', '-')})"
    what = " and ".join(ATTR[a] for a in sorted(attrs, key=lambda a: (ATTR_ORDER.get(a, 9), a)))
    return " ".join(x for x in (term_name(term), name, what) if x)


def _explain(code: str, win, lose, shown: str) -> str:
    """One loser's reason code in words (docs/RULES.md reason codes). `shown`: the winning page we name."""
    wf, lf = win.fact, lose.fact
    if code == EXPLICIT_EFFECTIVE_DATE:
        return (f"{shown} is effective {wf.effective}; {lose.path} is "
                + (f"effective {lf.effective}" if lf.effective else "undated") + " (stale copy)")
    if code == OFFICIAL_RATE_TABLE_OVER_CALCULATOR:
        return f"{shown} is the official rate table; {lose.path} ({lf.page_type}) is a stale copy"
    if code == CONSISTENT_ROW_OVER_INCONSISTENT:
        return f"{lose.path} row is impossible as written (rate above APY: a typo); {shown} is consistent"
    if code == NEWER_FETCH:
        return f"{shown} and {lose.path} are equally dated and trusted; {shown} was fetched later"
    return f"{shown} and {lose.path} disagree and nothing separates them ({code}): needs review"


def _add_once(items: list, item) -> None:
    if item not in items:
        items.append(item)


@dataclass
class CrawlEvidence:
    """What one crawl showed for one topic: who won, what was stale, where, and as of when."""
    snapshot_id: str
    taken_on: str
    winners: list = field(default_factory=list)       # (order, text): "5.39% APR (2024-27 Model Year, /rates)"
    winning_values: list = field(default_factory=list)
    stale_values: list = field(default_factory=list)
    stale_pages: list = field(default_factory=list)   # "/calculators/vehicle-affordability (effective 2026-01-01)"
    reasons: list = field(default_factory=list)
    sources: list = field(default_factory=list)       # Source(url, snapshot_id, quote)

    def add_source(self, url: str, quote: str) -> None:
        if all(s.url != url for s in self.sources):
            self.sources.append(Source(url=url, snapshot_id=self.snapshot_id, quote=quote[:200] or None))

    def summary(self) -> str:
        """Order-free, so two crawls telling the same story read (and merge) the same."""
        return (f"winning {', '.join(self.winning_values)} vs stale {', '.join(self.stale_values)} "
                f"on {', '.join(sorted(self.stale_pages))}")


@dataclass
class ConflictRecord:
    """One topic with the evidence of EVERY crawl that showed it (oldest first). `to_conflict()` -> scorer type."""
    name: str
    kind: str                                          # "table" | "prose"
    attrs: set = field(default_factory=set)
    crawls: list = field(default_factory=list)        # CrawlEvidence, oldest crawl first

    @property
    def newest(self) -> CrawlEvidence:
        return self.crawls[-1]

    def values(self) -> list:
        out: list = []
        for v in self.newest.winning_values + self.newest.stale_values:
            _add_once(out, v)
        return out

    def earlier(self) -> str:
        """Older crawls, consecutive crawls with the same story merged: "01-04 (2026-05-12..2026-08-27): ..."."""
        groups: list = []
        for ev in self.crawls[:-1]:
            if groups and groups[-1][-1].summary() == ev.summary():
                groups[-1].append(ev)
            else:
                groups.append([ev])
        parts = []
        for g in groups:
            ids = g[0].snapshot_id[:2] + (f"-{g[-1].snapshot_id[:2]}" if len(g) > 1 else "")
            days = g[0].taken_on[:10] + (f"..{g[-1].taken_on[:10]}" if len(g) > 1 else "")
            parts.append(f"{ids} ({days}): {g[0].summary()}")
        return "; ".join(parts)

    def to_conflict(self) -> Conflict:
        ev = self.newest
        reason = f"as of snapshot {ev.snapshot_id} ({ev.taken_on[:10]}): " + " | ".join(ev.reasons[:6])
        if len(self.crawls) > 1:
            reason += f". Earlier: {self.earlier()}"
        sources = list(ev.sources) + [s for old in reversed(self.crawls[:-1]) for s in old.sources]
        return Conflict(topic=self.name, values=self.values(), sources=sources,
                        resolution="; ".join(text for _, text in sorted(ev.winners)), reason=reason)


def _shown_path(r) -> str:
    """The page to name for a winning value: the most trusted page that has it (the rate sheet over a product page
    that copies the same table, D9), then the shortest path."""
    return min([r.winner] + list(r.agree), key=lambda c: (-AUTHORITY.get(c.fact.page_type, 0), len(c.path), c.path)).path


def _stale_page(c) -> str:
    when = c.fact.effective
    return f"{c.path} (effective {when})" if when else f"{c.path} (undated)"


def _evidence(rec: ConflictRecord, sid: str, taken_on: str) -> CrawlEvidence:
    if not rec.crawls or rec.crawls[-1].snapshot_id != sid:
        rec.crawls.append(CrawlEvidence(sid, taken_on))
    return rec.crawls[-1]


def _table_records(resolved: list, dates: dict, records: dict) -> None:
    for R in resolved:                                   # oldest crawl first: each crawl adds its own evidence
        slots = sorted((r for r in R.resolutions if r.status == CURRENT),
                       key=lambda r: (ATTR_ORDER.get(r.key[5], 9), str(r.key),
                                      r.tier.high if r.tier and r.tier.high is not None else 1e18))
        for r in slots:
            losers = [lo for lo in r.losers if lo.candidate.fact.value.text != r.value.text]
            if not losers:
                continue
            tk = ("table",) + topic_key(r.key)
            rec = records.setdefault(tk, ConflictRecord(name="", kind="table"))
            rec.attrs.add(r.key[5])
            ev = _evidence(rec, R.snapshot_id, dates.get(R.snapshot_id, ""))
            wf = r.winner.fact
            order = (ATTR_ORDER.get(r.key[5], 9), r.tier.high if r.tier and r.tier.high is not None else 1e18,
                     r.tier.low if r.tier and r.tier.low is not None else -1e18)
            shown = _shown_path(r)
            ev.winners.append((order, f"{wf.value.text} {ATTR[r.key[5]]} ({wf.label or 'all'}, {shown})"))
            _add_once(ev.winning_values, wf.value.text)
            ev.add_source(DUPACO + shown, wf.evidence)
            for lo in losers:
                lf = lo.candidate.fact
                _add_once(ev.stale_values, lf.value.text)
                _add_once(ev.stale_pages, _stale_page(lo.candidate))
                ev.add_source(lf.url, lf.evidence)
                _add_once(ev.reasons, _explain(lo.reason, r.winner, lo.candidate, shown))
    for tk, rec in records.items():
        if tk[0] == "table":
            rec.name = topic_name(tk[1:], rec.attrs)


def _days(a: str, b: str) -> int:
    try:
        return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days)
    except ValueError:
        return 10 ** 6


def _prose_records(resolved: list, dates: dict, records: dict) -> None:
    for R in resolved:                                   # oldest crawl first, like tables
        for p in R.prose:
            kind = p.key[0]
            if kind not in PROSE_TOPICS:
                continue
            fmt, name = PROSE_TOPICS[kind]
            w = p.winner
            losers = [lo for lo in p.losers if lo.candidate.fact.value != w.fact.value
                      and _days(lo.candidate.stated, w.stated) <= PROSE_WINDOW_DAYS]
            if not losers:
                continue
            rec = records.setdefault(("prose", kind, p.key[1]), ConflictRecord(name=name, kind="prose"))
            ev = _evidence(rec, R.snapshot_id, dates.get(R.snapshot_id, ""))
            ev.winners = [((0,), f"{fmt.format(w.fact.value)} ({w.path}, published {w.stated[:10]})")]
            _add_once(ev.winning_values, fmt.format(w.fact.value))
            ev.add_source(w.fact.url, w.fact.evidence)
            newest_first = sorted(losers, key=lambda lo: (lo.candidate.stated, lo.candidate.path), reverse=True)
            latest: dict = {}                            # stale value -> its newest publication date
            for i, lo in enumerate(newest_first):
                c = lo.candidate
                _add_once(ev.stale_values, fmt.format(c.fact.value))
                latest.setdefault(fmt.format(c.fact.value), c.stated[:10])
                if i < PROSE_SOURCES:
                    ev.add_source(c.fact.url, c.fact.evidence)
            first, last = newest_first[-1].candidate.stated[:10], newest_first[0].candidate.stated[:10]
            ev.stale_pages = [f"{len(losers)} older publications ({first}..{last})"]
            said = ", ".join(f"{v} (latest {d})" for v, d in latest.items())
            code = NEWEST_PUBLICATION if all(lo.reason == NEWEST_PUBLICATION for lo in losers) else "MIXED"
            ev.reasons = [f"newest publication wins ({code}): {w.path} published {w.stated[:10]}; "
                          f"older pages still say {said}"]


def build_records(resolved: list, dates: Optional[dict] = None) -> list:
    """resolved: the Resolved of every crawl, oldest first; dates: snapshot_id -> taken_on.
    Returns [ConflictRecord], one per topic, tables first, each with every crawl's evidence."""
    resolved = [R for R in resolved if isinstance(R, Resolved)]
    dates = dates or {}
    records: dict = {}
    _table_records(resolved, dates, records)
    _prose_records(resolved, dates, records)
    keys = sorted(records, key=lambda k: (k[0] != "table", str(k)))
    return [records[k] for k in keys if len(records[k].values()) >= 2]


def build_conflicts(resolved: list, dates: Optional[dict] = None) -> list:
    """[Conflict] for the scorer: one per topic, newest evidence first, older crawls kept in reason + sources."""
    return [rec.to_conflict() for rec in build_records(resolved, dates)]
