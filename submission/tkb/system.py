"""The knowledge system the scorer talks to.

    ingest(snapshot)    store every page version, extract table + prose facts, resolve them (Phases 0-2E),
                        and build this crawl's retrieval indexes (passages, links, main phone number).
    answer(q, as_of)    parse the question (query.py) -> pick the crawl for as_of (R5) -> answer from resolved
                        facts, prose verdicts or retrieval (compose.py). Deterministic and fast: no model calls.
                        A date before the first crawl (D5) is answered only from evidence dated on or before it
                        (Resolved.known_by), with a note saying so; otherwise the system says it cannot tell.
                        Between crawls, a later crawl's table effective on or before the day wins (Resolved.as_of,
                        D15). Questions about what a rate WILL be are declined (D17).
    errors              internal failures (logged; under TKB_STRICT=1 they raise): a bug never looks like
                        "the website doesn't say" without a trace.
    conflicts()         every self-contradiction of the site, one Conflict per topic, from the resolver's
                        verdicts over all crawls (conflicts.py, Phase 5); conflict_records() keeps each crawl's
                        evidence (dates, pages, values) behind every topic (Phase 6).
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import replace
from typing import Optional

from .compose import (REFUSAL, answer_general, answer_link, answer_prose, answer_rate, answer_street_address,
                      long_date, needs_text_address, refuse)
from .conflicts import build_records
from .grounded import grounded_answer
from .interpret import apply as apply_reading, interpret
from .llm import LLM, MIN_CALL_S, QUESTION_BUDGET_S
from .contract import Answer
from .query import parse_question, parts
from .retrieve import LinkIndex, PassageIndex, main_phone
from .store import VersionStore

PROSE_INTENTS = {"founded", "branch_count", "routing_number", "forbes_recognition", "vto_employees", "employees",
                 "assets", "members", "phone", "eligibility", "address", "closure", "closure_alternatives", "hours",
                 "mailing_address"}

# D5: asked about a day before the first crawl, with nothing in it dated that early. No digits (a refusal).
BEFORE_FIRST_CRAWL = ("my earliest copy of the Dupaco website was taken after that date, and nothing in it shows "
                      "what applied then.")

# A question about what a rate WILL be. No digits (a refusal).
FUTURE_RATE = ("the Dupaco website shows current and past rates only, and rates can change at any time, so I can't "
               "say what a rate will be.")

# Member-specific data (a balance, an approval). No digits (a refusal).
MEMBER_DATA = ("the public Dupaco website doesn't show individual accounts, balances or loan approvals; online "
               "banking shows your own accounts.")

# Phase 9: why a question cannot be answered, as read by the LLM (interpret.py). No digits (refusals).
DECLINE_TEXTS = {
    "member_data": MEMBER_DATA,
    "future": FUTURE_RATE,
    "needs_info": ("that depends on details only you have, such as your location or your situation, and the public "
                   "Dupaco website doesn't hold them. If you share them I can look again."),
    "live_availability": ("the public Dupaco website doesn't show live availability, appointments or staffing, so I "
                          "can't confirm that."),
    "personal_quote": ("the Dupaco website doesn't give personal quotes: the amount depends on your own account, "
                       "application or situation."),
}

__all__ = ["TemporalKnowledgeBase", "REFUSAL", "BEFORE_FIRST_CRAWL", "FUTURE_RATE", "MEMBER_DATA", "DECLINE_TEXTS"]

log = logging.getLogger("tkb")
STRICT_ENV = "TKB_STRICT"        # set to 1 (the test suite does) and internal errors raise instead of refusing


class TemporalKnowledgeBase:
    def __init__(self) -> None:
        self._started = 0.0                               # when the current question started (time budget)
        self.store = VersionStore()
        self.indexes: dict = {}          # snapshot_id -> (PassageIndex, LinkIndex, main phone)
        self._as_of_cache: dict = {}     # (snapshot_id, day) -> Resolved corrected by later crawls
        self._answers: dict = {}         # (question, as_of) -> the Answer given: a repeat gets the same answer,
                                         # even if the LLM failed the first time and would succeed now (review)
        self.errors: list = []           # (where, question, error): internal failures, kept visible (review)
        self.llm = LLM.from_env()        # Phase 9: None without ANTHROPIC_API_KEY (or with TKB_LLM=off)

    def ingest(self, snapshot) -> None:
        view = self.store.add_snapshot(snapshot)
        if view is None:                 # the same snapshot twice: already ingested and indexed
            return
        self._as_of_cache.clear()        # a new crawl can date changes for earlier days
        self._answers.clear()            # ... and can change any answer
        self.indexes[view.snapshot_id] = (PassageIndex.build(view.pages), LinkIndex.build(view.pages),
                                          main_phone(view.pages))

    def answer(self, question: str, as_of: Optional[str] = None):
        key = (question, as_of, id(self.llm))              # the mode is part of the key (tests switch it)
        if key in self._answers:
            return self._answers[key]
        try:
            out = self._answer(question, as_of)
        except Exception as e:           # a bug must not crash the scorer's run, but it must not hide either:
            self._failed("answer", question, e)   # it is logged and counted, and raises under TKB_STRICT=1
            return refuse()
        self._answers[key] = out
        return out

    def _failed(self, where: str, question: str, e: Exception) -> None:
        self.errors.append((where, question, f"{type(e).__name__}: {e}"))
        log.warning("tkb internal error in %s(%r): %s", where, question, e, exc_info=True)
        if os.environ.get(STRICT_ENV) == "1":
            raise e

    def _answer(self, question: str, as_of: Optional[str]) -> Answer:
        self._started = time.perf_counter()               # the question's time budget (llm.QUESTION_BUDGET_S)
        q = parse_question(question)
        if self.llm is not None and self.store.snapshots:     # the LLM reads the KIND of question (interpret.py)
            crawls = [s.taken_on[:10] for s in self.store.snapshots]
            q = apply_reading(q, interpret(self.llm, q, as_of, crawls))
        split = parts(q)                                   # "60-month vs 36-month": one lookup per part
        if len(split) == 1:
            return self._answer_query(q, as_of)
        by_date = len({p.date_ref for p in split}) > 1
        answers = [(p, self._answer_query(p, p.date_ref if by_date else as_of)) for p in split]
        good = [(p, a) for p, a in answers if a.confident]
        if not good:
            return answers[0][1]
        text = " ".join((f"On {long_date(p.date_ref)}: " if by_date else "") + a.text for p, a in good)
        for p, a in answers:              # a part the site does not answer is said, not silently dropped (review)
            if not a.confident:
                reason = re.sub(r"^I don't know - |\s*Please contact Dupaco or visit a branch for help\.$", "",
                                a.text)
                when = f" on {long_date(p.date_ref)}" if by_date else ""
                text += f" For the other part of the question{when}: {reason}"
        srcs, seen = [], set()
        for _, a in good:
            for s in a.sources:
                if (s.url, s.snapshot_id) not in seen:
                    seen.add((s.url, s.snapshot_id))
                    srcs.append(s)
        notes = [a.conflict_note for _, a in good if a.conflict_note]
        return Answer(text=text, sources=srcs, confident=True, conflict_note=" ".join(notes) or None)

    def _answer_query(self, q, as_of: Optional[str]) -> Answer:
        if q.future:                                       # "What will the rate be next year?": no forecasts
            return refuse(FUTURE_RATE)
        last = max((s.taken_on[:10] for s in self.store.snapshots), default="")   # the newest crawl
        if q.date_ref and last and q.date_ref > last and re.search(r"\bwill\b|\bgoing to\b", q.text.lower()):
            return refuse(FUTURE_RATE)                     # "Will it pay the same APY on September 28, 2027?"
        if q.personal:                                     # "my balance", "the APR approved for me"
            return refuse(MEMBER_DATA)
        if q.decline:                                      # Phase 9: the reason the LLM gave (interpret.py)
            return refuse(DECLINE_TEXTS[q.decline])
        when = as_of or q.date_ref                         # "as of May 2026" in the question counts too (R5)
        view = self.store.view(when)
        R = self.store.resolved(when)
        if view is None or R is None:
            return refuse()
        passages, links, phone = self.indexes[view.snapshot_id]
        ref_date = (when or view.taken_on)[:10]             # "today" for events: as_of, the question, or the crawl
        sid = view.snapshot_id
        first = self.store.snapshots[0].taken_on[:10]
        if when and str(when)[:10] < first:                 # D5: before the first crawl
            return self._before_first_crawl(q, R.known_by(ref_date), ref_date, first, links, sid, phone)
        if when:                                            # between crawls: later crawls may date a change
            R = self._as_of(R, view.snapshot_id, ref_date)

        if q.intent == "link":
            return answer_link(q, R, links, sid)
        if q.intent == "address" and needs_text_address(q, R):   # a named place that is not a branch (in-19)
            return answer_street_address(q, passages, sid)
        if q.intent in PROSE_INTENTS:
            return answer_prose(q, R, ref_date, links, sid, phone)
        if q.intent == "rate":
            return answer_rate(q, R, sid)
        if self.llm is not None and q.intent == "general" and q.llm_route in ("explain", "fee"):
            left = QUESTION_BUDGET_S - (time.perf_counter() - self._started)
            written = (grounded_answer(self.llm, q, R, passages, sid, ref_date, timeout=left)   # step 2 (checked)
                       if left >= MIN_CALL_S else None)  # too little time left: the rules answer
            rules_have_facts = (q.rules_intent in PROSE_INTENTS | {"address"}
                                or (q.rules_intent == "rate" and bool(q.products) and q.llm_route == "explain"))
            if written is not None and (written.confident or not rules_have_facts):
                return written                         # a checked answer; or "not stated" and the rules have nothing
            if q.rules_intent in PROSE_INTENTS | {"address"}:   # no written answer, or "the site doesn't state it"
                # from passages that missed the page: the prose fact the rules found stands (public dup-081)
                return self._answer_query(replace(q, intent=q.rules_intent, llm_route=None), as_of)
        if q.rules_intent == "rate" and q.products and q.llm_route == "explain":
            return self._rate_and_text(q, R, passages, sid, phone)     # "what credit score for the lowest APR?"
        return answer_general(q, passages, sid, phone)

    @staticmethod
    def _rate_and_text(q, R, passages, sid: str, phone) -> Answer:
        """The rules found a rate, the LLM read a question about its conditions: give the rate AND the text."""
        rate = answer_rate(replace(q, intent="rate"), R, sid)
        text = answer_general(q, passages, sid, phone)
        good = [a for a in (rate, text) if a.confident]
        if not good:
            return text
        seen, srcs = set(), []
        for a in good:
            for s in a.sources:
                if s.url not in seen:
                    seen.add(s.url)
                    srcs.append(s)
        return Answer(text=" ".join(a.text for a in good), sources=srcs, confident=True,
                      conflict_note=rate.conflict_note if rate.confident else None)

    def _as_of(self, R, sid: str, day: str):
        """R corrected by later crawls' evidence dated on or before `day` (Resolved.as_of), cached per day."""
        later = [self.store.resolutions[s.snapshot_id] for s in self.store.snapshots if s.taken_on[:10] > day]
        if not later:
            return R
        key = (sid, day)
        if key not in self._as_of_cache:
            self._as_of_cache[key] = R.as_of(day, later)
        return self._as_of_cache[key]

    def _before_first_crawl(self, q, R, day: str, first: str, links, sid: str, phone) -> Answer:
        """Answer only from facts the first crawl can date on or before `day`; links and retrieval passages carry
        no date, so they cannot speak for an earlier day."""
        if q.intent in PROSE_INTENTS:
            a = answer_prose(q, R, day, links, sid, phone)
        elif q.intent == "rate":
            a = answer_rate(q, R, sid)
        else:
            return refuse(BEFORE_FIRST_CRAWL)
        if not a.confident:
            return refuse(BEFORE_FIRST_CRAWL)
        note = (f"My earliest copy of the Dupaco website is from {long_date(first)}. This answer comes from "
                f"information in it dated on or before {long_date(day)}, so it already applied then. ")
        return Answer(text=note + a.text, sources=a.sources, confident=a.confident, conflict_note=a.conflict_note)

    def conflicts(self) -> list:
        try:
            return [rec.to_conflict() for rec in self.conflict_records()]
        except Exception as e:           # no list scores like an empty one; the error is logged and counted
            self._failed("conflicts", "", e)
            return []

    def conflict_records(self) -> list:
        """Every topic with the evidence of each crawl that showed it (dates, pages, values), oldest crawl first."""
        crawls = sorted(self.store.snapshots, key=lambda s: s.taken_on)
        return build_records([self.store.resolutions[s.snapshot_id] for s in crawls],
                             {s.snapshot_id: s.taken_on for s in crawls})
