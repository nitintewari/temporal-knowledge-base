"""Resolver: which value of each fact is current in one crawl, and why (Phase 2D).

Input: the facts of one crawl (every page, every table). Output: one Resolution per *slot*.

    key   ('auto loan', 'personal', None, None, (), 'apr', 60, 'model_year')   what the fact is about (R1)
    slot  one tier of that key, e.g. 2024-27 Model Year; older labels ("2023-26") pair into it
    winner, agree, losers                                                      with a reason code each

Order of precedence inside a slot, each step traced to evidence in docs/RULES.md:
    R13  URL variants of one page (#fragment, ?query): only the most recently fetched copy takes part (E14)
    R2   newest effective date first; dated beats undated (E1, E17)
    R3   then page authority: rate_sheet = product > other > pdf > promo = calculator = press > blog
    R25  then internally consistent rows: a deposit row whose dividend rate exceeds its APY is a typo (E27)
    -    then the most recent fetch, then path / table / row order, so the result is deterministic
    R17  a loser with the SAME value agrees with the winner; it is not a conflict, however old its date

Pairing tiers into slots (R1, R6, R23):
    - facts are taken in precedence order, so the newest, most trusted table defines the slots;
    - a fact joins the slot with an EQUAL tier, else the slot it overlaps most, else opens a new slot;
    - a table never competes with itself: two rows of one table are different tiers by construction.
      This is what keeps nested "or less" tiers apart ($100,000 or less vs $300,000 or less, E26).

A slot whose best fact is older than the newest table for the same key is SUPERSEDED: the newest table
dropped that tier (84 months for a 2017-20 car in snapshot 05, R6). Phase 3 must not answer from it.

Prose facts (Phase 2E, prose.py) are resolved here too, by R4: per (kind, subject, qualifier) the NEWEST
PUBLICATION wins, never the majority (E4: "23 branches" on 43 pages, "22" on 37; 22 is current). An undated
official page (/contact) speaks as of the day it was fetched (R27).

Nothing here decides how to word an answer or which conflicts to report (Phase 3 and Phase 5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .classify import AUTHORITY, url_path
from .facts import Fact
from .prose import ProseFact
from .values import Percent, Range

# ----------------------------------------------------------------------------- reason codes (docs/RULES.md)
EXPLICIT_EFFECTIVE_DATE = "EXPLICIT_EFFECTIVE_DATE"                  # R2
OFFICIAL_RATE_TABLE_OVER_CALCULATOR = "OFFICIAL_RATE_TABLE_OVER_CALCULATOR"   # R3 (more trusted source type)
FRESHEST_COPY_OF_PAGE = "FRESHEST_COPY_OF_PAGE"                      # R13
CONSISTENT_ROW_OVER_INCONSISTENT = "CONSISTENT_ROW_OVER_INCONSISTENT"  # R25: rate > APY on the loser's row
NEWER_FETCH = "NEWER_FETCH"                                          # same date + authority, fetched later
UNRESOLVED_TIE = "UNRESOLVED_TIE"                                    # nothing separates them: review
TIER_NOT_IN_NEWEST_TABLE = "TIER_NOT_IN_NEWEST_TABLE"                # R6: tier dropped by the newest table
HISTORICAL_VERSION_CHANGE = "HISTORICAL_VERSION_CHANGE"              # R17 across crawls: history, not conflict
NEWEST_PUBLICATION = "NEWEST_PUBLICATION"                            # R4: prose, newer publish date

CURRENT, SUPERSEDED = "current", "superseded"


# ----------------------------------------------------------------------------- data shapes
@dataclass(frozen=True)
class Candidate:
    """One fact as it takes part in resolution: the fact plus the page copy it came from."""
    fact: Fact
    fetched_at: str
    path: str
    inconsistent: bool = False  # R25: its table row is impossible as written (dividend rate > APY)
    snapshot_id: str = ""       # the crawl this copy was read from: an answer cites it, not the crawl it was asked for

    @property
    def source_table(self) -> tuple:
        return (self.path, self.fact.table_index)


@dataclass(frozen=True)
class Loser:
    candidate: Candidate
    reason: str


@dataclass
class Resolution:
    """The verdict for one slot (one tier of one fact key) in one crawl."""
    key: tuple
    tier: Optional[Range]
    winner: Candidate
    agree: list = field(default_factory=list)      # Candidates with the winner's value (R17)
    losers: list = field(default_factory=list)     # Losers: different value, with reason code
    status: str = CURRENT
    status_reason: Optional[str] = None

    @property
    def value(self) -> Percent:
        return self.winner.fact.value

    @property
    def has_conflict(self) -> bool:
        return bool(self.losers)

    def sources(self) -> list:
        """Winner first, then pages that agree, each path once (for answer citations)."""
        out = []
        for c in [self.winner] + list(self.agree):
            if c.path not in out:
                out.append(c.path)
        return out


@dataclass(frozen=True)
class ProseCandidate:
    """One prose fact plus the date it speaks for: its publish date, or the fetch date of an undated page (R27)."""
    fact: ProseFact
    stated: str
    fetched_at: str
    path: str
    snapshot_id: str = ""       # the crawl this statement was read from (citations, review)


@dataclass(frozen=True)
class ProseLoser:
    candidate: ProseCandidate
    reason: str


@dataclass
class ProseResolution:
    """The verdict for one prose fact key (kind, subject, qualifier) in one crawl."""
    key: tuple
    winner: ProseCandidate
    agree: list = field(default_factory=list)      # ProseCandidates with the winner's value (R17)
    losers: list = field(default_factory=list)     # ProseLosers: different value, with reason code

    @property
    def value(self) -> str:
        return self.winner.fact.value

    @property
    def has_conflict(self) -> bool:
        return bool(self.losers)

    def sources(self) -> list:
        out = []
        for c in [self.winner] + list(self.agree):
            if c.path not in out:
                out.append(c.path)
        return out


@dataclass
class Resolved:
    """All verdicts for one crawl, plus the URL-variant copies that were set aside (R13)."""
    snapshot_id: str
    resolutions: list = field(default_factory=list)
    shadowed: list = field(default_factory=list)   # Losers with FRESHEST_COPY_OF_PAGE
    prose: list = field(default_factory=list)      # ProseResolutions (Phase 2E)
    observed: frozenset = frozenset()              # every page path this crawl saw (as_of: an observed page stands)
    _by_key: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.reindex()

    def reindex(self) -> None:
        self._by_key = {}
        for r in self.resolutions:
            self._by_key.setdefault(r.key, []).append(r)

    def for_key(self, key: tuple, include_superseded: bool = False) -> list:
        return [r for r in self._by_key.get(key, []) if include_superseded or r.status == CURRENT]

    def known_by(self, day: str) -> "Resolved":
        """The verdicts this crawl can vouch for on an EARLIER day (a question dated before the first crawl, D5).

        Tables: a winner whose table is effective on or before `day` - it was still in force when the crawl was
        taken, so it was in force on every day in between. Undated winners, or tables that took effect after
        `day`, say nothing about `day`; neither do losing copies (a stale calculator is not a dated record).
        Prose: R4 again, among the statements published (or, undated, fetched: R27) on or before `day`, so a
        branch count published in March answers for April even though a May release says otherwise.
        """
        d = str(day)[:10]
        tables = [r for r in self.resolutions if r.winner.fact.effective and r.winner.fact.effective[:10] <= d]
        said = [c for p in self.prose for c in [p.winner] + list(p.agree) + [lo.candidate for lo in p.losers]
                if c.stated[:10] <= d]
        return Resolved(self.snapshot_id, tables, [], resolve_prose(said), self.observed)

    def as_of(self, day: str, later: list) -> "Resolved":
        """This crawl's verdicts for a `day` after it was taken, corrected by what LATER crawls prove (Phase 6).

        A later crawl showing a table effective on or before `day` - newer than this crawl's table for the same
        key, and with different values (same values: this crawl's own copy stays the evidence) - proves that table
        was already in force on `day` (crawl 04, 08-27, shows the 60-month auto rate at
        5.19%; crawl 05 shows 5.39% "effective 08/31/2026": on 09-01 the rate was 5.39%). Its slots replace this
        crawl's for that key (R2: the newest table defines the slots, R26). Prose: R4 over this crawl's
        statements plus later statements published on or before `day` - only from pages this crawl did NOT see
        (review): a page this crawl saw is the record of that day, and a later edit of it keeps its old publish
        date, so that date does not prove the edited text applied then. A release dated June 1 that first appears
        in a later crawl does count. Nothing later and dated early: unchanged.
        """
        d = str(day)[:10]
        newer: dict = {}                                 # key -> (effective, later crawl's slots dated <= day)
        for L in later:
            for key, rs in L._by_key.items():
                dated = [r for r in rs if r.winner.fact.effective and r.winner.fact.effective[:10] <= d]
                if not dated:
                    continue
                eff = max(r.winner.fact.effective[:10] for r in dated)
                mine = [r.winner.fact.effective[:10] for r in self._by_key.get(key, []) if r.winner.fact.effective]
                if (mine and max(mine) >= eff) or (key in newer and newer[key][0] >= eff):
                    continue
                same = {(r.tier, r.value.low, r.value.high) for r in self._by_key.get(key, [])}
                if same and {(r.tier, r.value.low, r.value.high) for r in dated} <= same:
                    continue          # same values: this crawl's own copy is the record of that day (review)
                newer[key] = (eff, dated)
        said = [c for L in later for p in L.prose for c in [p.winner] + list(p.agree) + [lo.candidate for lo in p.losers]
                if c.stated[:10] <= d and c.path not in self.observed]
        if not newer and not said:
            return self
        mine_said = [c for p in self.prose for c in [p.winner] + list(p.agree) + [lo.candidate for lo in p.losers]]
        resolutions = [r for r in self.resolutions if r.key not in newer] + [r for _, rs in newer.values() for r in rs]
        return Resolved(self.snapshot_id, resolutions, list(self.shadowed),
                        resolve_prose(mine_said + said) if said else list(self.prose), self.observed)

    def find_prose(self, kind: str, subject: Optional[str] = None, qualifier: Optional[str] = None) -> list:
        """Prose verdicts of one kind, optionally for one subject / qualifier, newest statement first.

        For "vto_employees" the subject is the year, so the result lists 2024 before 2023 (R21: give the newest
        year and the previous one when the question's "last year" is ambiguous).
        """
        hits = [r for r in self.prose if r.key[0] == kind
                and (subject is None or r.key[1] == subject) and (qualifier is None or r.key[2] == qualifier)]
        return sorted(hits, key=lambda r: (_neg(r.winner.stated), str(r.key)))

    def find(self, x: Optional[float] = None, include_superseded: bool = False, **want) -> list:
        """Current resolutions whose key fields match `want` (e.g. product='auto loan', term_months=60).

        With `x` (a model year, balance or loan amount) only slots whose tier contains it are kept,
        narrowest tier first (R23: "$100,000 or less" before "$300,000 or less").
        """
        fields = ("product", "segment", "account", "purpose", "flags", "attribute", "term_months", "tier_kind")
        bad = set(want) - set(fields)
        if bad:
            raise ValueError(f"unknown key fields: {sorted(bad)}")
        idx = {name: i for i, name in enumerate(fields)}
        hits = [r for key, rs in self._by_key.items()
                if all(key[idx[k]] == v for k, v in want.items())
                for r in rs if include_superseded or r.status == CURRENT]
        if x is not None:
            hits = [r for r in hits if r.tier is not None and r.tier.contains(x)]
            hits.sort(key=lambda r: (_width(r.tier), _sort_key(r)))
        else:
            hits.sort(key=_sort_key)
        return hits


# ----------------------------------------------------------------------------- precedence
def _authority(c: Candidate) -> int:
    return AUTHORITY.get(c.fact.page_type, 0)


def precedence(c: Candidate) -> tuple:
    """Sort key: smaller = stronger. Dated before undated, newer date, higher authority, newer fetch."""
    f = c.fact
    eff = f.effective or ""
    return (0 if eff else 1, _neg(eff), -_authority(c), int(c.inconsistent), _neg(c.fetched_at),
            c.path, f.table_index, f.row_index, f.attribute)


def _neg(s: str) -> tuple:
    """Descending order for ISO strings inside an ascending sort."""
    return tuple(-ord(ch) for ch in s)


def same_value(a: Percent, b: Percent) -> bool:
    """By number, not text: '3.90%' == '3.9%' (the scorer compares numbers the same way)."""
    return abs(a.low - b.low) < 1e-9 and abs(a.high - b.high) < 1e-9


def reason(winner: Candidate, loser: Candidate) -> str:
    """Why `winner` beats `loser` (they hold different values)."""
    we, le = winner.fact.effective, loser.fact.effective
    if we and (not le or we > le):
        return EXPLICIT_EFFECTIVE_DATE
    if (we or None) == (le or None):
        if _authority(winner) > _authority(loser):
            return OFFICIAL_RATE_TABLE_OVER_CALCULATOR
        if loser.inconsistent and not winner.inconsistent:
            return CONSISTENT_ROW_OVER_INCONSISTENT
        if winner.fetched_at > loser.fetched_at:
            return NEWER_FETCH
    return UNRESOLVED_TIE


# ----------------------------------------------------------------------------- R13: URL variants
def freshest_copies(pages: dict) -> tuple:
    """{url: page version} -> (kept versions, shadowed versions), one copy per normalized path.

    Snapshot 04 holds /personal/retirement (fetched 08-27) AND /personal/retirement#iracompare (06-15): the
    older copy must not take part (E14). Tie on fetch time -> the shorter URL (the canonical spelling).
    """
    best: dict = {}
    for url in sorted(pages):
        v = pages[url]
        path = url_path(url)
        cur = best.get(path)
        if cur is None or (v.fetched_at, -len(url)) > (cur[1].fetched_at, -len(cur[0])):
            best[path] = (url, v)
    kept_urls = {u for u, _ in best.values()}
    kept = [(u, pages[u]) for u in sorted(kept_urls)]
    shadowed = [(u, pages[u], best[url_path(u)]) for u in sorted(pages) if u not in kept_urls]
    return kept, shadowed


# ----------------------------------------------------------------------------- R25: impossible rows
def inconsistent_rows(facts: Iterable[Fact]) -> set:
    """(table_index, row_index) of deposit rows whose dividend rate is ABOVE their APY.

    APY includes compounding, so it is never below the dividend rate. Crawls 01-04 of /business-rates list
    Business Share Savings $10,000-$24,999.99 as "0.20% | 0.15%"; the product page fixed it to 0.15% / 0.15%
    in 04, /business-rates in 05 (E27). It is the only such row in all five crawls.
    """
    rows: dict = {}
    for f in facts:
        rows.setdefault((f.table_index, f.row_index), {})[f.attribute] = f.value
    return {pos for pos, d in rows.items()
            if "dividend_rate" in d and "apy" in d and d["dividend_rate"].low > d["apy"].low + 1e-9}


# ----------------------------------------------------------------------------- slots
def _same_tier(a: Optional[Range], b: Optional[Range]) -> bool:
    return a == b


def _overlap(a: Optional[Range], b: Optional[Range]) -> float:
    if a is None or b is None:
        return 0.0
    return a.overlap(b)


def _width(t: Optional[Range]) -> tuple:
    if t is None:
        return (2, 0.0, 0.0)
    if t.low is None and t.high is None:
        return (1, 0.0, 0.0)
    if t.low is None or t.high is None:
        # One open end: an "or less" tier is narrower when its top is lower; an "and up" tier when its
        # bottom is higher. Both sort after closed ranges.
        return (0, float("inf"), (t.high if t.high is not None else -(t.low or 0.0)))
    return (0, t.high - t.low, t.low)


def _sort_key(r: Resolution) -> tuple:
    t = r.tier
    lo = -1e18 if t is None or t.low is None else t.low
    hi = 1e18 if t is None or t.high is None else t.high
    return (str(r.key), lo, hi)


@dataclass
class _Slot:
    tier: Optional[Range]
    members: list = field(default_factory=list)
    tables: set = field(default_factory=set)


def assign_slots(candidates: Iterable[Candidate]) -> list:
    """Group the candidates of ONE key into slots (one per tier). Candidates must be in precedence order."""
    slots: list = []
    for c in candidates:
        tier = c.fact.tier
        open_slots = [s for s in slots if c.source_table not in s.tables]
        target = next((s for s in open_slots if _same_tier(s.tier, tier)), None)
        if target is None:
            scored = [(_overlap(s.tier, tier), -i, s) for i, s in enumerate(open_slots)]
            scored = [x for x in scored if x[0] > 0]
            if scored:
                target = max(scored, key=lambda x: (x[0], x[1]))[2]
        if target is None:
            target = _Slot(tier)
            slots.append(target)
        target.members.append(c)
        target.tables.add(c.source_table)
    return slots


def resolve_slot(key: tuple, slot: _Slot, newest_effective: Optional[str]) -> Resolution:
    winner, rest = slot.members[0], slot.members[1:]
    res = Resolution(key=key, tier=slot.tier, winner=winner)
    for c in rest:
        if same_value(c.fact.value, winner.fact.value):
            res.agree.append(c)
        else:
            res.losers.append(Loser(c, reason(winner, c)))
    w_eff = winner.fact.effective
    if newest_effective and (not w_eff or w_eff < newest_effective):
        res.status, res.status_reason = SUPERSEDED, TIER_NOT_IN_NEWEST_TABLE
    return res


# ----------------------------------------------------------------------------- prose (R4, R27)
def prose_precedence(c: ProseCandidate) -> tuple:
    """Newest statement first, then authority, then newest fetch, then path (deterministic)."""
    return (_neg(c.stated), -AUTHORITY.get(c.fact.page_type, 0), _neg(c.fetched_at), c.path, c.fact.value)


def prose_reason(winner: ProseCandidate, loser: ProseCandidate) -> str:
    if winner.stated > loser.stated:
        return NEWEST_PUBLICATION
    if AUTHORITY.get(winner.fact.page_type, 0) > AUTHORITY.get(loser.fact.page_type, 0):
        return OFFICIAL_RATE_TABLE_OVER_CALCULATOR
    return UNRESOLVED_TIE


def resolve_prose(candidates: Iterable[ProseCandidate]) -> list:
    """One ProseResolution per (kind, subject, qualifier): newest statement wins (R4); same value agrees (R17)."""
    groups: dict = {}
    for c in candidates:
        groups.setdefault(c.fact.key(), []).append(c)
    out = []
    for key in sorted(groups, key=str):
        ordered = sorted(groups[key], key=prose_precedence)
        res = ProseResolution(key, ordered[0])
        for c in ordered[1:]:
            if c.fact.value == res.winner.fact.value:
                res.agree.append(c)
            else:
                res.losers.append(ProseLoser(c, prose_reason(res.winner, c)))
        out.append(res)
    return out


# ----------------------------------------------------------------------------- one crawl
def resolve_crawl(snapshot_id: str, pages: dict) -> Resolved:
    """Resolve every fact key of one crawl. `pages` is {url: PageVersion} (store.SnapshotView.pages)."""
    kept, shadowed_pages = freshest_copies(pages)
    groups: dict = {}
    prose: list = []
    for url, v in kept:
        path = url_path(url)
        for pf in getattr(v, "prose", []):
            prose.append(ProseCandidate(pf, pf.published or v.fetched_at[:10], v.fetched_at, path, snapshot_id))
        bad = inconsistent_rows(v.facts)
        for f in v.facts:
            c = Candidate(f, v.fetched_at, path, (f.table_index, f.row_index) in bad, snapshot_id)
            groups.setdefault(f.key(), []).append(c)

    out = Resolved(snapshot_id, observed=frozenset(url_path(u) for u in pages))
    for url, v, _ in shadowed_pages:
        for f in v.facts:
            out.shadowed.append(Loser(Candidate(f, v.fetched_at, url_path(url), False, snapshot_id),
                                       FRESHEST_COPY_OF_PAGE))

    for key in sorted(groups, key=str):
        cands = sorted(groups[key], key=precedence)
        newest = max((c.fact.effective for c in cands if c.fact.effective), default=None)
        for slot in assign_slots(cands):
            out.resolutions.append(resolve_slot(key, slot, newest))
    out.resolutions.sort(key=_sort_key)
    out.prose = resolve_prose(prose)
    out.reindex()
    return out


# ----------------------------------------------------------------------------- across crawls (R17)
@dataclass(frozen=True)
class Change:
    key: tuple
    tier: Optional[Range]
    old: Optional[Resolution]       # None: the slot is new
    new: Optional[Resolution]       # None: the slot disappeared
    reason: str


def changes(old: Resolved, new: Resolved) -> list:
    """Value changes between two crawls, slot by slot (E20: compare facts, never raw text).

    Re-dating with the same value is NOT a change (R17). Slots are paired like tiers inside a crawl:
    equal tier first, then largest overlap ("2023-26" -> "2024-27"). Superseded slots are ignored.
    """
    out = []
    keys = sorted({r.key for r in old.resolutions} | {r.key for r in new.resolutions}, key=str)
    for key in keys:
        olds, news = old.for_key(key), new.for_key(key)
        unmatched = list(olds)
        for n in news:
            match = next((o for o in unmatched if _same_tier(o.tier, n.tier)), None)
            if match is None:
                scored = [(_overlap(o.tier, n.tier), -i, o) for i, o in enumerate(unmatched)]
                scored = [x for x in scored if x[0] > 0]
                match = max(scored, key=lambda x: (x[0], x[1]))[2] if scored else None
            if match is None:
                out.append(Change(key, n.tier, None, n, HISTORICAL_VERSION_CHANGE))
                continue
            unmatched.remove(match)
            if not same_value(match.value, n.value):
                out.append(Change(key, n.tier, match, n, HISTORICAL_VERSION_CHANGE))
        for o in unmatched:
            out.append(Change(key, o.tier, o, None, HISTORICAL_VERSION_CHANGE))
    return out
