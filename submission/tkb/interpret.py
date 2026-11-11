"""Question interpretation by the LLM (Phase 9, step 1). Only when an LLM is configured (llm.py).

The rules parser (query.py) reads numbers, dates, terms and tiers well and stays in charge of them. What it gets
wrong on unseen wording is the KIND of question (blind set B): "car insurance" read as an auto loan, "would it
cost me anything" as a fee amount, "where does the locator list the Galena branch" as a link request, "exactly
how much will Smart Save move next week" answered instead of declined. The LLM fixes those four things only:

    route     rate | branch | company | explain | fee | link | decline
    products  names from our own vocabulary (query.QUERY_PRODUCTS), or none when the subject has no rate table
    decline   member_data | future | needs_info | live_availability | personal_quote (why it cannot be answered)
    search    the question rewritten in the website's own words, for retrieval only

Every field is validated: an unknown route / product / reason is ignored, so a bad reply can only leave the rules
reading in place, never invent a slot. Reconciliation (`apply`) changes the rules Query only where the two
disagree on the kind of question.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Optional

from .llm import LLM, READ_TIMEOUT_S
from .query import QUERY_PRODUCTS, Query, content_words

ROUTES = ("rate", "branch", "company", "explain", "fee", "link", "decline")
DECLINES = ("member_data", "future", "needs_info", "live_availability", "personal_quote")
PRODUCTS = sorted({n for names, _ in QUERY_PRODUCTS for n in names})
PROSE_BRANCH = {"address", "hours", "closure", "closure_alternatives", "branch_count", "routing_number", "phone",
                "mailing_address"}
PROSE_COMPANY = {"founded", "forbes_recognition", "vto_employees", "employees", "members", "assets", "eligibility"}

SYSTEM = f"""You classify member questions for a question-answering system over snapshots of a credit union's
public website (Dupaco Community Credit Union). You do not answer the question. Reply with ONE JSON object only:

{{"route": "...", "products": [...], "decline": null or "...", "search": "..."}}

route - what the question needs:
  "rate"     a published rate (APR, APY, dividend rate, interest rate) of a product in the products list below,
             possibly with its term, tier or minimum. Not fees, not insurance, not features.
  "branch"   a branch's address, hours, closure, phone, or the branch count / routing number.
  "company"  a fact about the credit union itself (founded, assets, members, employees, awards, eligibility).
  "explain"  how something works, rules, features, eligibility conditions, comparisons of features, anything a
             page explains in words (including insurance, services, programs, announcements, articles).
  "fee"      a fee or charge amount from the fee schedule or a product page.
  "link"     ONLY when the member asks for a page, link or URL.
  "decline"  the public website cannot answer it, for one of these reasons (field "decline"):
     "member_data"        the member's own balance, account, transactions, approval or approved rate;
     "future"             what something WILL be or a guarantee about the future;
     "needs_info"         needs details only the member has (their address or location, their situation);
     "live_availability"  real-time availability, appointments, inventory, staffing;
     "personal_quote"     an exact personal price, premium, payment, penalty or transfer amount.
  A how-to question ("How can I check my balance?") is "explain", not a decline. A question about what the site
  listed on a past date is not "future".

products - zero or more names, copied exactly, from: {json.dumps(PRODUCTS)}
  Use none when the subject is not one of these (insurance, equipment loans, programs, services...). "Business"
  products use the same names. Never guess a product the question does not name or clearly describe.

search - the question rewritten as a short search query in the website's likely wording (for example "would it
cost me anything" -> "free no fee"; "car insurance deer" -> "auto insurance comprehensive collision animal").
Keep names, numbers and dates from the question.
"""


def interpret(llm: LLM, q: Query, as_of: Optional[str], crawls: list) -> Optional[dict]:
    """The validated LLM reading of the question, or None (no reply / not usable)."""
    user = json.dumps({"question": q.text, "as_of": as_of, "website_crawls": crawls})
    raw = llm.json("interpret", SYSTEM, user, max_tokens=300, timeout=READ_TIMEOUT_S)
    if not raw:
        return None
    route = raw.get("route") if raw.get("route") in ROUTES else None
    listed = raw.get("products")
    products = [p for p in (listed if isinstance(listed, list) else []) if isinstance(p, str) and p in PRODUCTS]
    decline = raw.get("decline") if raw.get("decline") in DECLINES else None
    found = raw.get("search")
    search = found if isinstance(found, str) else ""
    if route is None:
        return None
    if route == "decline" and decline is None:
        route = "explain"                         # a decline must say why; otherwise let the evidence decide
    return {"route": route, "products": products, "decline": decline if route == "decline" else None,
            "search": search[:300]}


def apply(q: Query, reading: Optional[dict]) -> Query:
    """The rules Query, corrected where the LLM's reading of the KIND of question differs. Numbers stay."""
    if not reading:
        return q
    route, products = reading["route"], reading["products"]
    rewritten = [w for w in content_words(reading["search"]) if w not in q.terms] if reading["search"] else []
    # The member's words search first; the site's wording is a second attempt (replayed live run: adding it to the
    # first search changed which passage won on questions the member's words already answered).
    out = replace(q, llm_route=route, rules_intent=q.intent, alt_terms=rewritten)
    if route == "decline":
        if q.intent in PROSE_BRANCH | PROSE_COMPANY:
            return out                    # a fact the rules found ("still open today?" - closed March 31) stands
        if reading["decline"] in ("personal_quote", "needs_info", "member_data") and q.intent == "rate" \
                and q.products and not q.personal \
                and (q.attribute or re.search(r"\b(?:example|illustration)s?\b", q.text, re.I)):
            return out                    # a published rate the question asks for is not a personal quote or
                                          # member data ("the APR for my 2018 car", "my HSA hit $2,500 - what APY":
                                          # blind C-011, B1-002, D-005). "What will Payment Protection cost me on
                                          # my car loan?" asks no rate: the decline stands (D-027).
        return replace(out, decline=reading["decline"])
    if route == "rate":
        if products and q.intent in ("general", "link") or (products and not q.products):
            out = replace(out, products=products, intent="rate", asks_fee=False)
        return out
    if route == "branch":
        if q.intent not in PROSE_BRANCH:
            out = replace(out, intent="address", asks_fee=False)   # "where does the locator list X": the place
        return out
    if route == "company":
        return out if q.intent in PROSE_COMPANY | {"link"} else replace(out, intent="general", asks_fee=False)
    if route == "link":
        return replace(out, intent="link")
    # explain / fee: answered from the site's text, never from a rate table. A link the rules found stands ("How do
    # I join Dupaco online?" -> join.dupaco.com): only rate / prose intents are moved to text retrieval.
    # A prose fact the rules found (membership, an address) is kept as `rules_intent`: system.py uses it when the
    # written answer fails ("Who is eligible to become a member?" read as "explain": public dup-081).
    if q.intent == "rate" or q.intent in PROSE_BRANCH | PROSE_COMPANY:
        out = replace(out, intent="general")
    return replace(out, asks_fee=(route == "fee"), asks_minimum=q.asks_minimum and route == "fee",
                   products=products if route == "fee" else [p for p in q.products if p in products])
