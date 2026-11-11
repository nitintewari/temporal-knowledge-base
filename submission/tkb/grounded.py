"""Grounded answers by the LLM (Phase 9, step 2). Only with an LLM, only for questions answered from text.

Rules still decide every rate (resolve.py). For explanation, fee and rate-plus-conditions questions the old answer
was a few sentences picked by word overlap; the LLM writes it instead, from an evidence pack:

    facts      verified values the resolver chose for the products in the question (current for the date asked)
    passages   the best-matching paragraphs of the crawl for that date, each with an id, page and publish date

and a reply is used only if it passes deterministic checks (otherwise the rules answer stands):

    grounded   every number in the answer appears in the cited passages, the facts, or the question
    no stale   every RATE in the answer (a % named APR / APY / rate / dividend) is one of the verified facts,
               under the same measure ("2.23% APY" fails when 2.23% is the dividend rate): a rate quoted in
               prose, which may be stale, can never reach the answer (G4)
    cited      the cited passage ids exist; an answer with no citation is not used
    honest     the model may say a part is not stated; it may not fill the gap
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Optional

from .compose import _render_row, _rows, _x_matches, find_rates, ranked_sources, refuse, sources
from .contract import Answer
from .llm import LLM
from .query import Query
from .resolve import Resolved
from .retrieve import PassageIndex, clean_url

MAX_PASSAGES, PASSAGE_CHARS, MAX_FACTS = 8, 700, 24
MEMBER_FIRST = 5            # passages for the member's own words; the rest for the LLM's search words

SYSTEM = """You answer a member's question about a credit union (Dupaco Community Credit Union) using ONLY the
evidence given: verified facts and numbered passages from the website as it stood on the date asked.

Reply with ONE JSON object only:
{"answer": "...", "cited": [passage ids you used], "not_stated": ["parts of the question the evidence does not answer"]}

Rules:
- Use only the evidence. Never add numbers, dates, names or conditions that are not in it.
- Rates (APR, APY, dividend rate, interest rate) may ONLY come from the verified facts. Ignore rates in passages.
- Answer every part of the question the evidence supports, with its conditions (who qualifies, time limits,
  minimums, "only", "not"). Keep the website's exact figures and wording for amounts, terms and names.
- If a part is not in the evidence, list it in not_stated and say so briefly in the answer; do not guess.
- If nothing in the evidence answers the question, reply {"answer": null, "cited": [], "not_stated": [...]}.
- 1 to 4 sentences. No preamble. Do not mention passage ids or "the evidence" in the answer.
"""

_NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
_EVIDENCE_WORD = re.compile(r"\b[Tt]he (?:evidence|passages?|provided (?:text|evidence))\b")
# An answer that opens by saying the site does not state it is a decline (blind B-036), never a confident answer.
_NOT_STATED_FIRST = re.compile(r"^[^.]{0,40}\b(?:does not|doesn't|do not|don't) (?:state|say|show|list|mention|"
                               r"include|explain|give|provide|specify|describe|cover|detail|outline|name|contain)\b", re.I)
# A percentage that IS a rate: "6.25% APR", "4.10% APY", "a rate of 7.13%". Not "75% loan-to-value", "20% down".
_RATE_VALUE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:\(?(?:apr|apy)\b|annual percentage|fixed\b|variable\b|intro\w*|"
                         r"dividend|interest|rate\b|yield)|\b(?:aprs?|apys?|rates?|yields?)\s+(?:of|is|at|was)\s+"
                         r"(?:as low as\s+)?(\d+(?:\.\d+)?)\s*%", re.I)


_FACT_RATE = re.compile(r"(\d+(?:\.\d+)?)%(?:\s*-\s*(\d+(?:\.\d+)?)%)?\s*(dividend rate|apy|apr|rate)", re.I)


def _measure(text: str) -> str:
    """The measure a rate is called: "apy", "apr", "dividend", or "" (a plain "rate", "fixed", "intro"...)."""
    t = text.lower()
    if "apy" in t or "yield" in t:
        return "apy"
    if "apr" in t or "annual percentage" in t:
        return "apr"
    return "dividend" if "dividend" in t else ""


def fact_rates(facts: list) -> set:
    """(value, measure) pairs of the verified facts: "2.23% dividend rate / 2.25% APY" -> (2.23, "dividend"),
    (2.25, "apy"); a range "12.50% - 19.50% APR" gives both ends with "apr"."""
    out = set()
    for m in _FACT_RATE.finditer(" ".join(facts)):
        for v in (m.group(1), m.group(2)):
            if v:
                out.add((round(float(v), 4), _measure(m.group(3))))
    return out


def _difference(n: tuple, supported: set) -> bool:
    """'$30.00 higher' when $55.00 and $25.00 are cited: a difference of two supported amounts in the same unit."""
    same = [v for u, v in supported if u == n[0]]
    return any(abs(round(a - b, 4)) == n[1] for a in same for b in same if a != b)


def numbers(text: str) -> set:
    """Numbers as written values, normalised: '$1,000.00' -> ('$', 1000.0); '3.00%' -> ('%', 3.0); '90' -> ('', 90)."""
    out = set()
    for tok in _NUMBER.findall(text or ""):
        unit = "$" if tok.startswith("$") else ("%" if tok.endswith("%") else "")
        digits = tok.strip("$%").replace(",", "").rstrip(".")
        try:
            out.add((unit, round(float(digits), 4)))
        except ValueError:
            continue
    return out


def fact_lines(q: Query, R: Resolved, limit: int = MAX_FACTS) -> tuple:
    """Verified values for the question's products (all measures): (display lines, resolutions). All tiers - unless
    the question names a balance, amount or model year: then only the tier containing it, so a value that is right
    for another tier ("2.25% APY" at $300,000) cannot pass the check (review)."""
    if not q.products:
        return [], []
    hits = find_rates(R, replace(q, attribute=None, x=None, superlative=None, premise=None))
    if q.x is not None and any(_x_matches(r, q) for r in hits):          # the same tier rule as rate answers (R23)
        inside = [r for r in hits if _x_matches(r, q) and r.tier is not None and r.tier.contains(q.x)]
        best: dict = {}
        for r in sorted(inside, key=lambda r: (r.tier.high if r.tier.high is not None else 1e18)):
            best.setdefault(r.key[:7], r.tier)                # narrowest containing tier per fact key
        if inside:                                            # untiered products in the question stay ("Free
            hits = [r for r in hits if not _x_matches(r, q)] + \
                   [r for r in inside if r.tier == best[r.key[:7]]]   # Checking versus 1st Rate Checking")
    return [_render_row(key, tier, attrs) for (key, tier), attrs in _rows(hits)][:limit], hits


def evidence(q: Query, passages: PassageIndex) -> list:
    """The best passages for the member's words, then for the LLM's search words; unique, in rank order. The
    member's words lead (their top passages always come first), but they no longer fill every slot: "a jar of
    change" or a "Christmas club" finds nothing about coin counting or the Holiday Club, while the LLM's search
    words do (blind set D)."""
    found, seen = [], set()
    for terms, limit in ((q.terms, MEMBER_FIRST if q.alt_terms else MAX_PASSAGES), (q.terms + q.alt_terms,
                                                                                     MAX_PASSAGES)):
        hits = passages.search(terms, k=MAX_PASSAGES, published=q.doc_date) if q.doc_date else []
        for _, p in hits or passages.search(terms, k=MAX_PASSAGES):
            if (p.url, p.pos) not in seen and len(found) < limit:
                seen.add((p.url, p.pos))
                found.append(p)
    return found


def grounded_answer(llm: LLM, q: Query, R: Resolved, passages: PassageIndex, snapshot_id: str,
                    day: str, timeout: Optional[float] = None) -> Optional[Answer]:
    """An LLM answer that passed every check, or None (the caller keeps the rules answer)."""
    facts, fact_hits = fact_lines(q, R)
    found = evidence(q, passages)
    if not found and not facts:
        return None
    pack = {"question": q.text, "website_as_of": day,
            "verified_facts": facts,
            "passages": [{"id": i + 1, "page": clean_url(p.url), "published": p.published,
                          "text": p.text[:PASSAGE_CHARS]} for i, p in enumerate(found)]}
    reply = llm.json("answer", SYSTEM, json.dumps(pack), max_tokens=400, timeout=timeout)
    if not reply or not isinstance(reply.get("answer"), str) or not reply["answer"].strip():
        return None
    text = _EVIDENCE_WORD.sub(lambda m: "The Dupaco website" if m.group(0)[0] == "T" else "the Dupaco website",
                              reply["answer"].strip())
    if _NOT_STATED_FIRST.match(text):                 # "The website does not state ...": a decline, not an answer
        return refuse("the Dupaco website doesn't state that.")
    listed = reply.get("cited")
    cited = [c for c in (listed if isinstance(listed, list) else [])
             if isinstance(c, int) and not isinstance(c, bool) and 1 <= c <= len(found)]
    if not check(text, cited, found, facts, q.text):
        return None
    urls = [clean_url(found[c - 1].url) for c in dict.fromkeys(cited)]
    used_facts = fact_hits if numbers(text) & numbers(" ".join(facts)) else []   # cite the rate pages it used
    return Answer(text=text, sources=sources(urls + ranked_sources(used_facts), snapshot_id), confident=True)


def check(text: str, cited: list, found: list, facts: list, question: str) -> bool:
    """The deterministic guardrails: cited (or facts only), grounded, no rate outside the verified facts."""
    fact_numbers = numbers(" ".join(facts))
    if not cited and not (numbers(text) and numbers(text) <= fact_numbers):
        return False                                  # no passage cited, and not an answer from the facts alone
    # A passage's page address and publish date are evidence too ("dated Jan 15, 2025", "published August 13, 2020").
    cited_text = " ".join(f"{found[c - 1].text} {found[c - 1].url} {found[c - 1].published or ''}" for c in cited)
    supported = numbers(question) | fact_numbers | numbers(cited_text.replace("-", " "))
    if not all(n in supported or _difference(n, supported) for n in numbers(text)):
        return False                                  # a number the evidence does not contain
    pairs = fact_rates(facts)
    values = {v for v, _ in pairs} | {n[1] for n in numbers(" ".join(facts)) if n[0] == "%"}
    for m in _RATE_VALUE.finditer(text):
        value, called = round(float(m.group(1) or m.group(2)), 4), _measure(m.group(0))
        if value not in values:
            return False                              # a rate that is not a verified fact (stale prose rate)
        if called and (value, called) not in pairs:
            return False                              # a verified value under the wrong measure: "2.23% APY" when
    return True                                       # 2.23% is the dividend rate (review)
