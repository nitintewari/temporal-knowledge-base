"""Versioned page store: keeps EVERY snapshot, not just the latest copy.

- history[url]  -> list of distinct versions of that page, oldest first
- snapshots     -> what the whole site looked like in each crawl (url -> Observation of a version)

Identical content (ignoring whitespace) is stored once and shared between snapshots,
so five crawls of ~700 pages cost little memory. What is NOT shared is the observation: a page whose text
is unchanged from May to September was still fetched again in September. Each crawl's view therefore holds
an Observation (shared content + this crawl's own fetch time), so rules that compare fetch times (R13
freshest copy, the newer-fetch tie-break, R27 undated page = its fetch date) see the real date (Phase 6:
408 of 705 pages in snapshot 05 had carried an older fetch time). Facts are extracted once per distinct
version, and each crawl's facts are resolved once at ingest (Phase 2D, resolve.py: ~10 ms per crawl), so
answering never has to decide what is current on the fly.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .classify import page_type, url_path
from .facts import extract_facts
from .prose import extract_prose
from .resolve import Resolved, resolve_crawl


def normalize(markdown: str) -> str:
    return re.sub(r"\s+", " ", markdown).strip()


@dataclass
class PageVersion:
    url: str
    path: str
    title: str
    markdown: str
    fetched_at: str          # when this content was FIRST fetched (each crawl's own time: Observation)
    first_seen: str          # snapshot_id where this content first appeared
    page_type: str
    content_hash: str
    seen_in: list = field(default_factory=list)   # snapshot_ids containing this exact content
    facts: list = field(default_factory=list)     # rate facts extracted once per distinct version (Phase 2C)
    published: Optional[str] = None                # byline date of a press/blog page (Phase 2E, R4)
    prose: list = field(default_factory=list)     # prose facts, extracted once per distinct version (Phase 2E)
    fetches: dict = field(default_factory=dict)   # snapshot_id -> fetch time of every observation (Phase 6)


@dataclass(frozen=True)
class Observation:
    """One page as seen in one crawl: the shared content (PageVersion) plus THIS crawl's fetch time.

    Reads like a PageVersion (url, markdown, facts, prose, published...), except `fetched_at`, which is when
    this crawl fetched it, and `snapshot_id`.
    """
    version: PageVersion
    snapshot_id: str
    fetched_at: str

    def __getattr__(self, name: str) -> Any:     # only called for fields Observation does not have itself
        return getattr(self.version, name)


@dataclass
class SnapshotView:
    snapshot_id: str
    taken_on: str
    pages: dict              # url -> Observation (content shared across crawls, fetch time per crawl)


class VersionStore:
    def __init__(self) -> None:
        self.snapshots: list[SnapshotView] = []
        self.history: dict[str, list[PageVersion]] = {}
        self.resolutions: dict[str, Resolved] = {}     # snapshot_id -> verdicts for that crawl (Phase 2D)

    def add_snapshot(self, snap) -> Optional[SnapshotView]:
        # The same snapshot ingested twice is ignored.
        for existing in self.snapshots:
            if existing.snapshot_id == snap.snapshot_id:
                return None
        view = SnapshotView(snap.snapshot_id, str(snap.taken_on), {})
        for p in snap.pages:
            markdown = p.markdown or ""                      # empty page -> empty text, not a crash
            h = hashlib.sha1(normalize(markdown).encode("utf-8")).hexdigest()
            versions = self.history.setdefault(p.url, [])
            if versions and versions[-1].content_hash == h:
                v = versions[-1]                             # unchanged since last crawl
            else:
                kind = page_type(p.url)
                published, prose = extract_prose(markdown, p.url, kind)
                v = PageVersion(
                    url=p.url, path=url_path(p.url), title=p.title or "", markdown=markdown,
                    fetched_at=p.fetched_at or str(snap.taken_on), first_seen=snap.snapshot_id,
                    page_type=kind, content_hash=h,
                    facts=extract_facts(markdown, p.url, kind),   # only new content is parsed
                    published=published, prose=prose,
                )
                versions.append(v)
            if not v.seen_in or v.seen_in[-1] != snap.snapshot_id:
                v.seen_in.append(snap.snapshot_id)
            fetched = p.fetched_at or str(snap.taken_on)        # THIS crawl's fetch, even if the text is unchanged
            v.fetches[snap.snapshot_id] = fetched
            view.pages[p.url] = Observation(v, snap.snapshot_id, fetched)
        self.snapshots.append(view)
        self.snapshots.sort(key=lambda s: s.taken_on)
        self.resolutions[view.snapshot_id] = resolve_crawl(view.snapshot_id, view.pages)
        return view

    def view(self, as_of: Optional[str] = None) -> Optional[SnapshotView]:
        """The website as it stood on `as_of` (ISO date).

        None -> the latest snapshot. Otherwise the newest snapshot taken on or before that day;
        a date before the first crawl falls back to the first crawl.
        """
        if not self.snapshots:
            return None
        if not as_of:
            return self.snapshots[-1]
        day = str(as_of).strip()[:10]          # tolerates "2026-05-31T00:00:00Z"
        eligible = [s for s in self.snapshots if s.taken_on[:10] <= day]
        return eligible[-1] if eligible else self.snapshots[0]

    def facts(self, as_of: Optional[str] = None) -> list:
        """(fact, observation) pairs for every page in the crawl that applies to `as_of` (R5)."""
        view = self.view(as_of)
        if view is None:
            return []
        return [(f, v) for url in sorted(view.pages) for v in [view.pages[url]] for f in v.facts]

    def resolved(self, as_of: Optional[str] = None) -> Optional[Resolved]:
        """The resolver's verdicts for the crawl that applies to `as_of` (R5), or None before any ingest."""
        view = self.view(as_of)
        return self.resolutions.get(view.snapshot_id) if view is not None else None

    def stats(self) -> dict:
        return {
            "snapshots": [(s.snapshot_id, len(s.pages)) for s in self.snapshots],
            "urls_ever_seen": len(self.history),
            "distinct_page_versions": sum(len(v) for v in self.history.values()),
            "facts_per_snapshot": [(s.snapshot_id, sum(len(v.facts) for v in s.pages.values()))
                                   for s in self.snapshots],
        }
