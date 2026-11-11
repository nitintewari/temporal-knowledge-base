"""Retrieval for questions no fact key answers (Phase 3): BM25 over passages, and a link index.

Built once per crawl at ingest (store.py), so answering stays a lookup. Standard library only.

    PassageIndex   every paragraph of every non-listing page of one crawl, boilerplate removed (R11).
                   Used for explanations ("What is Home$tart?", "Who can join?"). Never used for rates: a
                   number in prose may be stale, so compose.py drops sentences with a % (R8).
    LinkIndex      every URL a member could be sent to: the crawl's own pages (title + path words) and the
                   links inside them (anchor text), Dupaco domains only, no images (R20: never invent a URL).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .classify import AUTHORITY, url_path
from .prose import clean_page, is_listing, plain, sentences

_TOKEN = re.compile(r"[a-z0-9]+")
_MONEY_CELL = re.compile(r"\|\s*\$\s?\d")
_STOP = set("a an the of for to on in at is are was were be do does did i me my you your we our us it its this go "
            "that what which who how when where why can could would should will and or but with about from by as "
            "any all some there their they them have has had get give tell know please dupaco dupaco's".split())


_SUFFIXES = ("ations", "ation", "ators", "ator", "ions", "ion", "ings", "ing", "ors", "or", "ers", "er", "ed")


def stem(word: str) -> str:
    """Tiny stemmer: plural and common suffixes off, then the first 6 letters ("locator" ~ "location" -> "locat")."""
    w = word.lower()
    for suf in ("ies", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            w = w[: -len(suf)] + ("y" if suf == "ies" else "")
            break
    for suf in _SUFFIXES:
        if len(w) - len(suf) >= 4 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return w[:6]


def tokens(text: str) -> list:
    return [stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


# ----------------------------------------------------------------------------- passages (BM25)
@dataclass(frozen=True)
class Passage:
    text: str
    url: str
    title: str
    page_type: str
    published: Optional[str]
    pos: int = 0                      # order in the index = order on the page (pages sorted by URL)


@dataclass
class PassageIndex:
    passages: list = field(default_factory=list)
    _tf: list = field(default_factory=list, repr=False)
    _df: Counter = field(default_factory=Counter, repr=False)
    _len: list = field(default_factory=list, repr=False)
    _avg: float = 1.0

    @classmethod
    def build(cls, pages: dict) -> "PassageIndex":
        """pages: {url: PageVersion} of ONE crawl. One passage per paragraph of 40+ characters."""
        idx = cls()
        for url in sorted(pages):
            v = pages[url]
            md = getattr(v, "markdown", "") or ""
            if is_listing(url, md):
                continue
            title = getattr(v, "title", "") or ""
            intro = ""                                    # "In 2024 alone:" - the context of the list below it
            lead, items = "", []                          # the line before a run of bullets, and the bullets

            def close_list() -> None:
                # A whole list as one passage, after its lead line (blind set C: "benefits at no extra cost,
                # including:" and its four short items were separate, and the items too short to be indexed).
                if 2 <= len(items) <= 12 and lead:
                    idx.passages.append(Passage(f"{lead} {'; '.join(items)}.", url, title,
                                                getattr(v, "page_type", ""), getattr(v, "published", None),
                                                len(idx.passages)))

            for line in clean_page(md).splitlines():
                if line.lstrip().startswith("#"):
                    continue                              # headings: the page title is indexed with every passage
                bullet = line.lstrip().startswith(("-", "*", "•"))
                text = plain(line).lstrip("->* ").strip()
                if not text:
                    continue
                if bullet:
                    items.append(text.rstrip(".;"))
                else:
                    close_list()
                    lead, items = (text if len(text) <= 300 else ""), []
                if not bullet and text.endswith(":") and len(text) < 60:
                    intro = text
                    continue
                if bullet and intro:
                    text = f"{intro} {text}"              # list items carry their intro ("In 2024 alone: ...")
                elif not bullet:
                    intro = ""
                # Fee schedules are tables of short rows ("|Domestic wire|$25.00 each|"): keep those (review).
                short_fee_row = text.startswith("|") and len(text) >= 12 and _MONEY_CELL.search(text)
                if (len(text) < 40 and not short_fee_row) or text.startswith("!["):
                    continue
                idx.passages.append(Passage(text, url, title, getattr(v, "page_type", ""),
                                            getattr(v, "published", None), len(idx.passages)))
            close_list()
        for p in idx.passages:
            tf = Counter(tokens(p.text) + tokens(p.title))
            idx._tf.append(tf)
            idx._len.append(sum(tf.values()))
            idx._df.update(tf.keys())
        idx._avg = (sum(idx._len) / len(idx._len)) if idx._len else 1.0
        return idx

    def search(self, query_terms: list, k: int = 5, published: Optional[str] = None) -> list:
        """[(score, Passage)] best first. BM25 (k1=1.5, b=0.75) x a small boost for trusted page types.
        With `published` (a date), only passages of pages published that day: the document the question names."""
        q = tokens(" ".join(query_terms))        # same splitting as the pages: "home$tart" -> home, tart
        n = len(self.passages) or 1
        scored = []
        for i, tf in enumerate(self._tf):
            s = 0.0
            for t in q:
                f = tf.get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                s += idf * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * self._len[i] / self._avg))
            if s > 0 and (published is None or (self.passages[i].published or "")[:10] == published):
                p = self.passages[i]
                s *= 1.0 + 0.04 * AUTHORITY.get(p.page_type, 0)
                if "/disclosures/" in p.url or "/privacy" in p.url:
                    s *= 0.5                              # legal boilerplate matches everything, answers nothing
                scored.append((s, i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [(round(s, 6), self.passages[i]) for s, i in scored[:k]]

    def next_passage(self, p: Passage) -> Optional[Passage]:
        """The paragraph after `p` on the same page (an FAQ question's answer)."""
        if p.pos + 1 < len(self.passages) and self.passages[p.pos + 1].url == p.url:
            return self.passages[p.pos + 1]
        return None

    def coverage(self, query_terms: list, p: Passage) -> float:
        """Share of the question's idf weight that the passage (with its page title) contains. "What's the
        weather in Dubuque?" finds a passage about weathering a storm: it covers "weather", not "Dubuque"."""
        q = set(tokens(" ".join(query_terms)))
        if not q:
            return 0.0
        n = len(self.passages) or 1
        w = {t: math.log(1 + n / (1 + self._df.get(t, 0))) for t in q}
        have = set(tokens(p.text + " " + p.title))
        return sum(v for t, v in w.items() if t in have) / (sum(w.values()) or 1.0)

    def rarest(self, query_terms: list, within: str) -> str:
        """The question word with the highest idf that `within` (the best passage) contains: what the question
        is really about ("tart" from "Home$tart", "student")."""
        present = set(tokens(within))
        cands = [t for t in tokens(" ".join(query_terms)) if t in present]
        return min(cands, key=lambda t: (self._df.get(t, 0), t)) if cands else ""


def best_sentences(passage: Passage, query_terms: list, limit: int = 3) -> list:
    """From the first sentence that shares a word with the question: that sentence and the ones after it.
    The sentence after a match often carries the detail ("...the Home$tart program. This initiative provides
    up to $15,000 in assistance...")."""
    q = set(tokens(" ".join(query_terms)))
    sents = sentences(passage.text) or [passage.text]
    first = next((i for i, s in enumerate(sents) if q & set(tokens(s))), 0)
    return sents[first:first + limit]


# ----------------------------------------------------------------------------- links (R20)
_LINK = re.compile(r"\[([^\]\[]{0,120})\]\((https?://[^)\s]+)\)")
_DUPACO = re.compile(r"^https?://(?:[a-z0-9-]+\.)*dupaco\.com(?:/|$)", re.I)
_ASSET = re.compile(r"\.(?:jpe?g|png|gif|svg|webp|pdf|mp4)(?:\?|$)|/hubfs/|/hs-fs/|placeholder", re.I)


@dataclass
class LinkIndex:
    texts: dict = field(default_factory=dict)        # url -> list of describing texts (title, path, anchors)

    @classmethod
    def build(cls, pages: dict) -> "LinkIndex":
        idx = cls()
        for url in sorted(pages):
            v = pages[url]
            md = getattr(v, "markdown", "") or ""
            if not is_listing(url, md):
                path_words = url_path(url).replace("/", " ").replace("-", " ")
                idx.texts.setdefault(url, []).extend([getattr(v, "title", "") or "", path_words])
            for anchor, href in _LINK.findall(clean_page(md)):    # teaser blocks would inflate counts (R11)
                if _DUPACO.match(href) and not _ASSET.search(href) and not href.endswith("#"):
                    host_words = re.sub(r"^https?://|www\.|\.com", " ", href.split("?")[0]).replace("/", " ")
                    idx.texts.setdefault(href, []).extend([anchor, host_words])
        return idx

    def search(self, query_terms: list, k: int = 3) -> list:
        """[(score, url)] best first. Each question word found in a URL's describing texts scores its idf times
        (1 + log of how many texts agree): many anchors saying "Join Dupaco" outvote one odd anchor.
        Shorter URLs win ties (the canonical spelling)."""
        q = set(tokens(" ".join(query_terms))) - {stem(w) for w in ("link", "url", "page", "website", "site", "use",
                                                                    "online", "see", "find")}
        counts: dict = {}
        df: Counter = Counter()
        for url, texts in self.texts.items():
            c: Counter = Counter()
            for t in texts:
                c.update(set(tokens(t)) & q)
            if c:
                counts[url] = c
                df.update(c.keys())
        n = len(self.texts) or 1
        scored = [(sum(math.log(1 + n / (1 + df[t])) * (1 + math.log(f)) for t, f in c.items()), url)
                  for url, c in counts.items()]
        scored.sort(key=lambda x: (-x[0], len(x[1]), x[1]))
        return [(round(s, 6), clean_url(u)) for s, u in scored[:k]]


def clean_url(url: str) -> str:
    """Drop tracking queries and machine-made fragments ("#dupaco-locator-widget_1769206785258"); keep "#rates"."""
    base, _, frag = url.partition("#")
    base = base.split("?utm_")[0]
    return base + (f"#{frag}" if frag and re.fullmatch(r"[a-z-]{2,30}", frag) else "")


_PHONE = re.compile(r"\b(8\d\d-\d{3}-\d{4})\b")


def main_phone(pages: dict) -> Optional[str]:
    """The toll-free number printed on the most pages of the crawl (800-373-7600: 234 lines in snapshot 05)."""
    c: Counter = Counter()
    for v in pages.values():
        c.update(set(_PHONE.findall(getattr(v, "markdown", "") or "")))
    return min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0] if c else None
