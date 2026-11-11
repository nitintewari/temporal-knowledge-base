"""Phase 9 step 1: the optional LLM layer, tested with a FAKE model (no network, no key). Made-up text only.

  client       JSON parsing, caching per request, failures counted and returned as None (never raised)
  interpret    unknown routes / products / reasons are ignored; a decline must give its reason
  reconcile    the LLM corrects the KIND of question; the rules keep numbers, dates, terms and tiers
  end to end   "car insurance" is not an auto-loan rate; reason-specific declines; an API failure falls back
               to the rules answer; no key = the rules-only system, unchanged
"""
import json
import re
from types import SimpleNamespace as NS
from typing import Optional

import pytest

from tkb.interpret import apply, interpret
from tkb.llm import LLM, parse_json_object
from tkb.query import parse_question
from tkb.system import DECLINE_TEXTS, TemporalKnowledgeBase

D = "https://www.dupaco.com"


class FakeLLM(LLM):
    """An LLM whose model returns replies[question] for the interpretation request and answers[question] for the
    grounded-answer request (step 2), and records every request."""

    def __init__(self, replies: dict, answers: Optional[dict] = None) -> None:
        self.sent: list = []

        def send(system: str, user: str, max_tokens: int) -> str:
            self.sent.append(json.loads(user))
            table = (answers or {}) if "verified_facts" in user else replies
            reply = table.get(json.loads(user)["question"])
            if isinstance(reply, Exception):
                raise reply
            return "```json\n" + json.dumps(reply or {}) + "\n```"
        super().__init__(send, model="fake")


def fake(replies: dict, answers: Optional[dict] = None) -> FakeLLM:
    return FakeLLM(replies, answers)


# ----------------------------------------------------------------------------- client
def test_replies_are_parsed_cached_and_failures_are_counted_not_raised():
    assert parse_json_object('Sure: {"route": "rate"} done') == {"route": "rate"}
    llm = fake({"q": {"route": "explain"}, "bad": TimeoutError("slow")})
    u = json.dumps({"question": "q", "as_of": None})
    assert llm.json("interpret", "s", u) == {"route": "explain"} == llm.json("interpret", "s", u)
    assert llm.calls == 1                                                   # the second reply came from the cache
    assert llm.json("interpret", "s", json.dumps({"question": "q", "as_of": "2026-06-01"})) is not None
    assert llm.calls == 2                                                   # as_of is part of the request: no mixing
    assert llm.json("interpret", "s", json.dumps({"question": "bad"})) is None
    assert llm.failures and llm.failures[0][0] == "interpret"


def test_an_http_error_keeps_the_apis_own_message():
    import io
    import urllib.error
    from tkb.llm import describe
    body = io.BytesIO(b'{"type":"error","error":{"message":"`temperature` is deprecated for this model."}}')
    e = urllib.error.HTTPError("https://api", 400, "Bad Request", {}, body)  # type: ignore[arg-type]
    assert describe(e) == "HTTP 400: `temperature` is deprecated for this model."


def test_no_key_or_off_means_no_llm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert LLM.from_env() is None and TemporalKnowledgeBase().llm is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("TKB_LLM", "off")
    assert LLM.from_env() is None


# ----------------------------------------------------------------------------- interpret + reconcile
def test_a_reading_is_validated_before_it_is_used():
    q = parse_question("Is my car covered if I hit a deer?")
    llm = fake({q.text: {"route": "explain", "products": ["auto loan", "pet rock"], "search": "comprehensive deer"}})
    r = interpret(llm, q, None, ["2026-09-28"])
    assert r == {"route": "explain", "products": ["auto loan"], "decline": None, "search": "comprehensive deer"}
    assert interpret(fake({q.text: {"route": "teleport"}}), q, None, []) is None          # unknown route
    no_reason = interpret(fake({q.text: {"route": "decline"}}), q, None, [])
    assert no_reason is not None and no_reason["route"] == "explain"                      # a decline needs a reason


def test_the_llm_corrects_the_kind_of_question_and_the_rules_keep_the_numbers():
    car = parse_question("Would my auto insurance cover hitting a deer on a 2022 car?")
    assert car.intent == "rate" and car.products == ["auto loan"]          # the rules' misreading (set B)
    fixed = apply(car, {"route": "explain", "products": [], "decline": None, "search": "auto insurance deer"})
    assert fixed.intent == "general" and fixed.products == []
    assert fixed.terms[:len(car.terms)] == car.terms and "insurance" in fixed.terms   # member's words + rewrite
    assert fixed.x == 2022.0                                              # numbers stay with the rules

    rate = parse_question("What does a two-year certificate pay these days?")
    fixed = apply(rate, {"route": "rate", "products": ["certificate"], "decline": None, "search": ""})
    assert fixed.intent == "rate" and fixed.term_months == 24 and fixed.terms == rate.terms

    loc = parse_question("Where does the locator list the Galena, Illinois branch?")
    assert apply(loc, {"route": "branch", "products": [], "decline": None, "search": "Galena"}).intent == "address"

    free = parse_question("Would a Money Makeover cost me anything?")
    assert free.asks_fee
    assert not apply(free, {"route": "explain", "products": [], "decline": None, "search": "free"}).asks_fee


# ----------------------------------------------------------------------------- end to end
INSURANCE = ("Auto insurance\n\nComprehensive coverage pays for damage from hitting a deer or other animal, hail "
             "or a falling tree. Collision coverage pays when you hit another car.\n")
AUTO = ("Auto Loans\n\n| Loan Program | Term | APR |\n| --- | --- | --- |\n| 2021-23 Model Year | 60 Months | 5.64% APR |"
        "\n\nRates are effective as of 08/31/2026.\n")
FILLER = [f"Topic {i}\n\nMembers can read about budgeting, saving for college, checking accounts, travel tips "
          f"and online banking features on page {i}.\n" for i in range(12)]


def kb_with(llm):
    k = TemporalKnowledgeBase()
    k.llm = llm
    pages = [NS(url=D + p, title=p, markdown=m, fetched_at="2026-09-28T10:00:00Z")
             for p, m in [("/insurance/auto", INSURANCE), ("/rates", AUTO)] + [(f"/t{i}", t) for i, t in
                                                                              enumerate(FILLER)]]
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=pages))
    return k


CAR = "If my car hits a deer, does auto insurance comprehensive or collision cover it?"


def test_an_insurance_question_is_answered_from_the_insurance_page_not_the_auto_loan_rates():
    k = kb_with(fake({CAR: {"route": "explain", "products": [], "search": "auto insurance comprehensive "
                                                                           "collision deer animal"}}))
    a = k.answer(CAR)
    assert a.confident and "Comprehensive" in a.text and "%" not in a.text
    assert [s.url for s in a.sources][0] == D + "/insurance/auto"
    assert "5.64%" in kb_with(None).answer("What APR is listed for a 60-month loan on a 2022 car?").text


@pytest.mark.parametrize("reason", sorted(DECLINE_TEXTS))
def test_each_decline_reason_has_its_own_reply_without_digits(reason):
    q = "Which branch is closest to my home, and can I book it at noon tomorrow?"
    a = kb_with(fake({q: {"route": "decline", "decline": reason, "products": [], "search": ""}})).answer(q)
    assert a.confident is False and DECLINE_TEXTS[reason] in a.text and not re.search(r"\d", a.text)


def test_an_api_failure_falls_back_to_the_rules_answer():
    q = "What APR is listed for a 60-month loan on a 2022 car?"
    llm = fake({q: TimeoutError("slow")})
    k = kb_with(llm)
    assert "5.64% APR" in k.answer(q).text and llm.failures
    assert llm.sent[0]["question"] == q and llm.sent[0]["website_crawls"] == ["2026-09-28"]


EQUIPMENT = ("Business equipment loans\n\nEquipment loans require a minimum 20% down payment. Terms run up to seven "
             "years, and the interest rate can be fixed for up to five years.\n")


def test_an_explanation_that_mentions_an_interest_rate_is_not_refused_as_an_unpublished_rate():
    q = "For a business equipment loan, how long can the interest rate stay fixed?"
    reply = {q: {"route": "explain", "products": [], "search": "equipment loan interest rate fixed five years"}}
    k = TemporalKnowledgeBase()
    k.llm = fake(reply)
    pages = [NS(url=D + p, title=p, markdown=m, fetched_at="2026-09-28T10:00:00Z")
             for p, m in [("/business/equipment-loans", EQUIPMENT)] + [(f"/t{i}", t) for i, t in enumerate(FILLER)]]
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=pages))
    a = k.answer(q)
    assert a.confident and "five years" in a.text
    k.llm = None
    assert k.answer(q).confident is False                  # rules only: "doesn't publish a rate" (today's reply)


# ----------------------------------------------------------------------------- step 1b: regressions on the public set
CONSTRUCTION = ("Financing new home construction\n\nWith a construction loan, your interest rate stays the same for "
                "the first year, then the construction loan converts to a regular mortgage.\n")


def test_a_question_asking_for_an_unpublished_rate_is_still_declined():
    ask = "What interest rate do you charge on a construction loan?"
    about = "How does the interest rate work on a construction loan?"
    k = TemporalKnowledgeBase()
    k.llm = fake({t: {"route": "explain", "products": [], "search": "construction loan interest rate"}
                  for t in (ask, about)})
    pages = [NS(url=D + p, title=p, markdown=m, fetched_at="2026-09-28T10:00:00Z")
             for p, m in [("/learn/construction", CONSTRUCTION)] + [(f"/t{i}", t) for i, t in enumerate(FILLER)]]
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=pages))
    assert k.answer(ask).confident is False                            # dup-147: asks FOR a rate nobody publishes
    assert k.answer(about).confident and "first year" in k.answer(about).text     # asks ABOUT it: explained


def test_a_link_the_rules_found_stands():
    joined = parse_question("How do I join Dupaco online?")
    assert joined.intent == "link"
    for route in ("explain", "company", "fee"):                       # dup-082: the join page is the answer
        assert apply(joined, {"route": route, "products": [], "decline": None, "search": "join online"}).intent \
            == "link"
    loc = parse_question("Where does the locator list the Galena, Illinois branch?")
    assert apply(loc, {"route": "branch", "products": [], "decline": None, "search": "Galena"}).intent == "address"


def test_a_recorded_run_replays_offline(tmp_path):
    path = str(tmp_path / "cache.jsonl")
    live = LLM(lambda system, user, n: '{"route": "explain"}', model="m", cache_file=path)
    assert live.json("interpret", "s", "u1") == {"route": "explain"}
    replay = LLM.replay(path, model="m")
    assert replay.json("interpret", "s", "u1") == {"route": "explain"} and replay.calls == 0
    assert replay.json("interpret", "s", "unseen") is None and replay.failures      # not recorded -> fallback
    assert "key" in open(path).read() and "x-api-key" not in open(path).read()


# ----------------------------------------------------------------------------- step 1c: replayed live run + review
def test_an_llm_decline_does_not_override_a_fact_the_rules_found():
    q = parse_question("Is the Hy-Vee branch still open today?")
    assert q.intent == "closure"
    out = apply(q, {"route": "decline", "products": [], "decline": "live_availability", "search": "Hy-Vee"})
    assert out.decline is None and out.intent == "closure"                 # dup-075: it closed March 31
    member = apply(parse_question("Exactly how much will Smart Save move next week?"),
                   {"route": "decline", "products": [], "decline": "personal_quote", "search": ""})
    assert member.decline == "personal_quote"


HOMESTART = [("/newsroom/homestart", "Home$tart grants\n\nThe Home$tart program provides up to $15,000 toward a down "
                                     "payment for first-time homebuyers.\n"),
             ("/newsroom/partnership", "Partnership news\n\nA partnership with the bank makes homeownership more "
                                       "accessible for buyers who need down payment assistance.\n")]


def test_the_llm_search_words_are_a_second_attempt_not_a_replacement():
    q, miss = "What is Dupaco's Home$tart program?", "Is there help with buying my very first house?"
    reading = {"route": "explain", "products": [], "search": "partnership homeownership accessible buyers assistance"}
    k = TemporalKnowledgeBase()
    k.llm = fake({q: reading, miss: {"route": "explain", "products": [], "search": "Home$tart first-time homebuyers "
                                                                                 "down payment grants"}})
    pages = [NS(url=D + p, title=p, markdown=m, fetched_at="2026-09-28T10:00:00Z")
             for p, m in HOMESTART + [(f"/t{i}", t) for i, t in enumerate(FILLER)]]
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=pages))
    assert "$15,000" in k.answer(q).text                                 # dup-031: the member's words won
    assert "$15,000" in k.answer(miss).text                              # nothing found: the site's wording helps


HELOC = ("Home Equity Line of Credit\n\n| Product | APR |\n| --- | --- |\n| HELOC | 6.25% APR |\n\n"
         "Rates are effective as of 08/01/2026.\n\nThe lowest APR requires a credit score of 720 or higher and a "
         "combined loan-to-value of 75% or less.\n")


def test_a_rate_question_read_as_conditions_gives_the_rate_and_the_conditions():
    q = "What credit score and combined loan-to-value do I need for the lowest HELOC APR?"
    k = TemporalKnowledgeBase()
    k.llm = fake({q: {"route": "explain", "products": ["heloc"], "search": "HELOC credit score loan-to-value"}})
    pages = [NS(url=D + p, title=p, markdown=m, fetched_at="2026-09-28T10:00:00Z")
             for p, m in [("/personal/loans/heloc", HELOC)] + [(f"/t{i}", t) for i, t in enumerate(FILLER)]]
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=pages))
    a = k.answer(q)
    assert "6.25% APR" in a.text and "720" in a.text and "75%" in a.text   # A-005: rate AND requirements


@pytest.mark.parametrize("sentence, is_rate", [
    ("Cash advance fee: $10.00 or 3.00% of each cash advance, whichever is greater.", False),
    ("Equipment loans require a minimum 20% down payment.", False),
    ("Earn 4.00% APY on our certificate special.", True),
    ("Rates as low as 5.34% on new cars.", True),
    ("Saver Plus - $0.01 - $49,999.99 - 1.39% - 1.40% - $25,000.00", True),     # a row of rates
])
def test_only_sentences_quoting_a_rate_are_withheld(sentence, is_rate):
    from tkb.compose import _quotes_rate
    assert _quotes_rate(sentence) is is_rate



# ----------------------------------------------------------------------------- step 2: grounded answers
INTRO = ("Platinum Visa\n\n| Card | APR |\n| --- | --- |\n| Platinum Visa | 12.50% - 19.50% APR |\n"
         "| Platinum Visa intro (balance transfer) | 2.90% APR |\n\nRates are effective as of 01/02/2026.\n\n"
         "The introductory rate applies to balance transfers that post in the first 90 days after the account is "
         "opened. It expires six months after the first balance transfer.\n\nOld promo: balance transfers at "
         "1.90% APR for new members.\n")
Q_INTRO = "Which transactions get the Platinum Visa intro APR, and when does it end?"
READ_INTRO = {"route": "explain", "products": ["platinum visa"], "search": "platinum visa intro balance transfer"}


def kb_written(answer: dict):
    k = TemporalKnowledgeBase()
    k.llm = fake({Q_INTRO: READ_INTRO}, {Q_INTRO: answer})
    pages = [NS(url=D + p, title=p, markdown=m, fetched_at="2026-09-28T10:00:00Z")
             for p, m in [("/personal/credit-cards", INTRO)] + [(f"/t{i}", t) for i, t in enumerate(FILLER)]]
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=pages))
    return k


GOOD = {"answer": "The 2.90% APR intro rate applies to balance transfers posted in the first 90 days after opening, "
                  "and it expires six months after the first balance transfer.", "cited": [1, 2, 3], "not_stated": []}


def test_a_grounded_answer_is_used_with_its_sources_and_the_pack_holds_facts_and_passages():
    k = kb_written(GOOD)
    assert k.llm is not None
    a = k.answer(Q_INTRO)
    assert a.confident and a.text == GOOD["answer"]
    assert D + "/personal/credit-cards" in {s.url for s in a.sources}
    llm = k.llm
    assert isinstance(llm, FakeLLM)
    pack = next(r for r in llm.sent if "verified_facts" in r)
    assert any("2.90% APR" in f for f in pack["verified_facts"]) and pack["passages"][0]["id"] == 1


@pytest.mark.parametrize("bad, why", [
    ({"answer": "The intro rate lasts 12 months after opening.", "cited": [1, 2, 3]}, "a number not in the evidence"),
    ({"answer": "Balance transfers get 1.90% APR for new members.", "cited": [1, 2, 3]}, "a stale rate from prose"),
    ({"answer": "It applies to balance transfers only.", "cited": []}, "no citation"),
    ({"answer": "It applies to balance transfers in the first 90 days.", "cited": [42]}, "an unknown passage"),
    ({"answer": None, "cited": [], "not_stated": ["everything"]}, "the model says it cannot answer"),
])
def test_a_written_answer_that_fails_a_check_is_not_used(bad, why):
    a = kb_written(bad).answer(Q_INTRO)
    assert "12 months" not in a.text and "1.90%" not in a.text and "transfers only" not in a.text, why
    assert a.text != bad.get("answer"), why                                    # the rules answer is kept


def test_non_rate_percentages_from_the_evidence_are_allowed():
    from tkb.grounded import check
    p = NS(text="The lowest APR requires a credit score of 720 and a combined loan-to-value of 75% or less.",
           url=D + "/personal/loans/heloc", published=None)
    facts = ["home equity line of credit (HELOC): 6.25% APR"]
    ok = "The 6.25% APR requires a 720 credit score and 75% combined loan-to-value or less."
    assert check(ok, [1], [p], facts, "q") is True
    assert check(ok.replace("6.25%", "5.99%"), [1], [p], facts, "q") is False          # a rate not verified


def test_no_llm_means_no_written_answers():
    k = kb_written(GOOD)
    k.llm = None
    assert k.answer(Q_INTRO).text != GOOD["answer"]



# ----------------------------------------------------------------------------- step 2b: replayed live run
def test_page_dates_differences_and_facts_only_answers_pass_the_number_check():
    from tkb.grounded import check
    fee = NS(text="Domestic wire - $25.00 each | International wire transfer - $55.00 each",
             url=D + "/hubfs/fee-schedule-jan-15-2025.pdf", published=None)
    news = NS(text="The branch was expected to open in late 2021.", url=D + "/newsroom/grimes",
              published="2020-08-13")
    assert check("International wires cost $55.00, $30.00 more than a domestic wire at $25.00.", [1], [fee], [], "q")
    assert not check("International wires cost $55.00, $35.00 more.", [1], [fee], [], "q")      # not a difference
    assert check("The schedule is dated Jan 15, 2025.", [1], [fee], [], "q")                  # from the file name
    assert check("Announced August 13, 2020, it expected to open in late 2021.", [1], [news], [], "q")
    facts = ["Bright Savings ($0.01-$1,000,000): 2.23% dividend rate / 2.25% APY"]
    assert check("Bright Savings balances are capped at $1,000,000.", [], [], facts, "q")     # facts only
    assert not check("Bright Savings balances are capped.", [], [], facts, "q")               # nothing from facts


def test_an_answer_that_opens_by_saying_the_site_does_not_state_it_is_a_decline():
    q = "How much did everyone in the savings challenge save altogether?"
    reply = {"answer": "The evidence does not state a combined total saved in 2025.", "cited": [1]}
    k = TemporalKnowledgeBase()
    k.llm = fake({q: {"route": "explain", "products": [], "search": "savings challenge total saved"}}, {q: reply})
    pages = [NS(url=D + p, title=p, markdown=m, fetched_at="2026-09-28T10:00:00Z")
             for p, m in [("/newsroom/challenge", "Savings challenge\n\nParticipants in the savings challenge "
                                                  "saved money and built habits over the challenge.\n")]
             + [(f"/t{i}", t) for i, t in enumerate(FILLER)]]
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=pages))
    a = k.answer(q)
    assert a.confident is False and "doesn't state" in a.text and not re.search(r"\d", a.text)


def test_answers_say_the_dupaco_website_not_the_evidence():
    k = kb_written({**GOOD, "answer": GOOD["answer"] + " The evidence does not say more."})
    text = k.answer(Q_INTRO).text
    assert "The Dupaco website does not say more." in text and "evidence" not in text


# ----------------------------------------------------------------------------- step 3: outage + speed
def test_the_breaker_switches_the_llm_off_after_three_failures_in_a_row():
    from tkb.llm import BREAKER
    outcomes = iter([TimeoutError("slow"), TimeoutError("slow"), '{"ok": 1}', TimeoutError("slow"),
                     TimeoutError("slow"), TimeoutError("slow"), '{"ok": 2}'])

    def send(system, user, n):
        o = next(outcomes)
        if isinstance(o, Exception):
            raise o
        return o
    llm = LLM(send, model="m")
    assert llm.json("p", "s", "u0") is None and llm.json("p", "s", "u1") is None and not llm.off
    assert llm.json("p", "s", "u2") == {"ok": 1} and not llm.off               # a success resets the count
    assert [llm.json("p", "s", f"u{i}") for i in (3, 4, 5)] == [None, None, None]
    assert llm.off and llm.calls == 6 and llm.failures[-1][0] == "breaker"    # 3 in a row: off
    assert llm.json("p", "s", "u-later") is None and llm.calls == 6            # off: no further calls, no waiting
    assert llm.json("p", "s", "u2") == {"ok": 1}                               # recorded replies still served
    assert BREAKER == 3


def test_unusable_replies_fall_back_but_never_trip_the_breaker():
    """Blind set B1: 5 replies without JSON in 40 questions switched the LLM off for the last 17. A reply the
    API did send is not an outage: that one question gets the rules answer, the LLM stays on."""
    replies = iter(["Here is my reading of it", "no braces", "still none", "nor here", '{"ok": 1}'])
    llm = LLM(lambda system, user, n: next(replies), model="m")
    assert [llm.json("p", "s", f"u{i}") for i in range(4)] == [None, None, None, None]
    assert not llm.off and llm.json("p", "s", "u4") == {"ok": 1}
    assert "no JSON object in reply (starts: 'Here is my reading of it')" in llm.failures[0][1]


class _Resp:
    def __init__(self, status, body):
        self.status, self.reason, self.headers, self._body = status, "x", {}, body

    def read(self):
        return self._body


class _Sock:
    def __init__(self):
        self.timeouts: list = []

    def settimeout(self, t):
        self.timeouts.append(t)


class _Conn:
    opened = 0
    script: list = []
    last: "_Conn"

    def __init__(self, host, timeout):
        _Conn.opened += 1
        _Conn.last = self
        self.closed = False
        self.timeout = timeout
        self.sock = _Sock()

    def request(self, *a, **k):
        script = _Conn.script.pop(0)
        if isinstance(script, Exception):
            raise script
        self.next = script

    def getresponse(self):
        return _Resp(*self.next)

    def close(self):
        self.closed = True


def test_one_connection_is_reused_and_reopened_once_if_the_server_closed_it(monkeypatch):
    import http.client
    import tkb.llm as L
    monkeypatch.setattr(L.http.client, "HTTPSConnection", _Conn)
    _Conn.opened = 0
    _Conn.script = [(200, b'{"a":1}'), (200, b'{"a":2}'), http.client.RemoteDisconnected("idle"), (200, b'{"a":3}'),
                    (400, b'{"error":{"message":"bad field"}}')]
    k = L._KeepAlive({})
    assert k.post(b"1") == b'{"a":1}' and k.post(b"2") == b'{"a":2}' and _Conn.opened == 1   # reused
    assert k.post(b"3") == b'{"a":3}' and _Conn.opened == 2                                  # one fresh retry
    with pytest.raises(L.urllib.error.HTTPError) as e:
        k.post(b"4")
    assert L.describe(e.value) == "HTTP 400: bad field"


def test_a_proxy_uses_urllib_and_otherwise_one_kept_alive_connection(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("TKB_LLM", raising=False)
    for v in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(v, raising=False)
    llm = LLM.from_env()
    assert llm is not None and llm.transport == "keep-alive"
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:8080")
    llm = LLM.from_env()
    assert llm is not None and llm.transport == "urllib"


def test_five_unusable_replies_in_a_row_switch_the_llm_off():
    """A model that has stopped following the format would cost a wasted call per question: stop asking."""
    from tkb.llm import BAD_REPLIES
    llm = LLM(lambda system, user, n: "plain words, no braces", model="m")
    assert [llm.json("p", "s", f"u{i}") for i in range(BAD_REPLIES)] == [None] * BAD_REPLIES
    assert llm.off and llm.failures[-1][0] == "breaker" and llm.calls == BAD_REPLIES
    assert llm.json("p", "s", "later") is None and llm.calls == BAD_REPLIES


@pytest.mark.parametrize("setting, thinking, limit", [("", False, 300), ("on", True, 2300)])
def test_thinking_is_off_by_default_and_on_gets_more_room(monkeypatch, setting, thinking, limit):
    """Thinking counts against max_tokens (blind set B1: replies cut off before any text). Off unless asked."""
    import tkb.llm as L
    sent: list = []

    class Post:
        def __init__(self, headers):
            pass

        def post(self, body, timeout=None):
            sent.append(json.loads(body))
            return json.dumps({"content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": '{"a": 1}'}],
                               "stop_reason": "end_turn"}).encode("utf-8")
    monkeypatch.setattr(L, "_KeepAlive", Post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("TKB_LLM", raising=False)
    for v in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("TKB_LLM_THINKING", setting)
    llm = LLM.from_env()
    assert llm is not None and llm.thinking is thinking
    assert llm.json("interpret", "s", "u", max_tokens=300) == {"a": 1}       # text block chosen by type
    assert sent[0]["max_tokens"] == limit and ("thinking" in sent[0]) is not thinking
    assert "temperature" not in sent[0]


def test_a_reply_stopped_by_the_limit_or_a_refusal_is_unusable_not_an_outage(monkeypatch):
    import tkb.llm as L
    replies = iter([{"content": [{"type": "text", "text": '{"route": "ra'}], "stop_reason": "max_tokens"},
                    {"content": [], "stop_reason": "refusal"}])

    class Post:
        def __init__(self, headers):
            pass

        def post(self, body, timeout=None):
            return json.dumps(next(replies)).encode("utf-8")
    monkeypatch.setattr(L, "_KeepAlive", Post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("TKB_LLM", raising=False)
    monkeypatch.delenv("TKB_LLM_THINKING", raising=False)
    for v in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(v, raising=False)
    llm = LLM.from_env()
    assert llm is not None
    assert llm.json("p", "s", "u1") is None and llm.json("p", "s", "u2") is None and not llm.off
    assert "stopped by max_tokens" in llm.failures[0][1] and "stopped by refusal" in llm.failures[1][1]


def test_replies_with_and_without_thinking_never_share_a_cache_entry():
    on = LLM(lambda s, u, n: '{"v": "on"}', model="m", thinking=True)
    off = LLM(lambda s, u, n: '{"v": "off"}', model="m", thinking=False)
    assert on.json("p", "s", "u") == {"v": "on"} and off.json("p", "s", "u") == {"v": "off"}
    assert set(on._cache) != set(off._cache)


# ----------------------------------------------------------------------------- blind sets B1 + C: overrides, budget
AUTO_C = ("Auto Loans\n\n| Loan Program | Term | APR (As Low As) |\n| --- | --- | --- |\n"
        "| 2017-20 Model Year | 60 Months | 6.34% APR |\n\nRates are effective as of 08/31/2026.\n")
JOIN_C = ("# Join\n\nAnyone in our 112-county field of membership can join. You can find us in Iowa, Illinois "
          "and Wisconsin.\n")


def _kb(llm):
    k = TemporalKnowledgeBase()
    k.llm = llm
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28",
                pages=[NS(url=D + p, title=p, markdown=m, fetched_at="2026-09-28T10:00:00Z")
                       for p, m in [("/rates", AUTO_C), ("/about/join", JOIN_C)] + [(f"/t{i}", t) for i, t in
                                                                               enumerate(FILLER)]]))
    return k


def test_a_personal_quote_decline_does_not_override_a_published_rate():
    q = "Your calculator has a rate for my 2018 car. What lowest APR should I use today for a five-year loan?"
    k = _kb(fake({q: {"route": "decline", "products": ["auto loan"], "decline": "personal_quote", "search": ""}}))
    assert "6.34%" in k.answer(q).text                                   # blind C-011: the table row stands
    mine = parse_question("What APR was I approved for?")
    out = apply(mine, {"route": "decline", "products": [], "decline": "personal_quote", "search": ""})
    assert out.decline == "personal_quote" or mine.personal              # a member's own quote is still declined


def test_a_prose_fact_is_the_fallback_when_an_explain_reading_gets_no_written_answer():
    q = "Who is eligible to become a Dupaco member?"
    assert parse_question(q).intent == "eligibility"
    k = _kb(fake({q: {"route": "explain", "products": [], "search": "membership eligibility"}},
                 answers={q: {"answer": None, "cited": [], "not_stated": ["who can join"]}}))
    assert "Iowa, Illinois and Wisconsin" in k.answer(q).text            # public dup-081
    k2 = _kb(fake({q: {"route": "explain", "products": [], "search": "membership eligibility"}},
                  answers={q: {"answer": "The Dupaco website does not state who can join.", "cited": [1]}}))
    assert "Iowa, Illinois and Wisconsin" in k2.answer(q).text           # live run: "does not state" from passages
    k3 = _kb(fake({q: {"route": "explain", "products": [], "search": "membership eligibility"}},
                  answers={q: {"answer": "The Dupaco website does not contain a full list of requirements.",
                               "cited": [1]}}))
    assert "Iowa, Illinois and Wisconsin" in k3.answer(q).text           # "does not contain": also a decline
    r = "What monthly payment goes with the lowest APR on a 2018 car for 60 months? Explain the conditions."
    k4 = _kb(fake({r: {"route": "explain", "products": ["auto loan"], "search": "payment"}},
                  answers={r: {"answer": "The Dupaco website does not state that.", "cited": [1]}}))
    assert "6.34%" in k4.answer(r).text                                  # blind C-025: the verified rate, not a decline


def test_an_answer_saying_the_site_does_not_describe_it_is_a_decline():
    from tkb.grounded import _NOT_STATED_FIRST
    assert _NOT_STATED_FIRST.match("The Dupaco website does not describe the steps for that.")
    assert not _NOT_STATED_FIRST.match("Dupaco describes three ways to do that: online, by phone or in a branch.")


def test_each_question_has_a_time_budget(monkeypatch):
    import tkb.system as S
    from tkb.llm import MIN_CALL_S, QUESTION_BUDGET_S, READ_TIMEOUT_S
    limits: list = []
    q = "What is the Home$tart program?"

    class Timed(FakeLLM):
        def json(self, purpose, system, user, max_tokens=500, timeout=None):
            limits.append((purpose, timeout))
            return super().json(purpose, system, user, max_tokens, timeout)
    k = _kb(Timed({q: {"route": "explain", "products": [], "search": ""}}, answers={q: {"answer": None}}))
    k.answer(q)
    assert limits[0] == ("interpret", READ_TIMEOUT_S) and limits[1][0] == "answer"
    assert 0 < limits[1][1] <= QUESTION_BUDGET_S                          # what is left of the question's budget
    clock = iter([0.0, QUESTION_BUDGET_S - MIN_CALL_S + 0.5] + [100.0] * 20)
    monkeypatch.setattr(S.time, "perf_counter", lambda: next(clock))
    limits.clear()
    k.answer(q + " ")
    assert [p for p, _ in limits] == ["interpret"]                       # too little time left: no second call
    assert READ_TIMEOUT_S <= 3.0 and QUESTION_BUDGET_S <= 6.0


def test_a_reused_connection_gets_each_call_s_own_time_limit(monkeypatch):
    import tkb.llm as L
    monkeypatch.setattr(L.http.client, "HTTPSConnection", _Conn)
    _Conn.script = [(200, b'{"a":1}'), (200, b'{"a":2}')]
    k = L._KeepAlive({})
    k.post(b"1", 3.0)
    assert _Conn.last.timeout == 3.0
    k.post(b"2", 4.5)
    assert _Conn.last.sock.timeouts == [4.5]


def test_a_decline_stands_unless_the_question_asks_for_a_published_measure():
    hsa = parse_question("My savings account just hit exactly $2,500. What APY does that put me at?")
    kept = apply(hsa, {"route": "decline", "products": [], "decline": "member_data", "search": ""})
    assert kept.decline is None and kept.intent == "rate"                 # blind D-005: a tier question
    cost = parse_question("I'm adding Payment Protection to my car loan. How many dollars a month will it cost me?")
    out = apply(cost, {"route": "decline", "products": ["auto loan"], "decline": "personal_quote", "search": ""})
    assert out.decline == "personal_quote"                                # D-027: no rate asked, decline stands


def test_the_llm_search_words_get_a_share_of_the_evidence():
    from tkb.grounded import MAX_PASSAGES, MEMBER_FIRST, evidence
    from tkb.retrieve import PassageIndex
    pages = {D + f"/t{i}": NS(markdown=t, title="t", page_type="other", published=None) for i, t in enumerate(FILLER)}
    pages[D + "/fees"] = NS(markdown="# Fees\n\nSelf-service coin counting is free for members and 5% of the total "
                                     "for non-members.\n", title="Fees", page_type="pdf", published=None)
    idx = PassageIndex.build(pages)
    q = parse_question("I have a jar of change, members read about budgeting and saving - what do you take?")
    assert not any("coin" in p.text for p in evidence(q, idx))           # the member's words alone miss it
    q2 = apply(q, {"route": "fee", "products": [], "decline": None, "search": "coin counting fee non-member"})
    found = evidence(q2, idx)
    assert any("coin counting" in p.text for p in found) and len(found) <= MAX_PASSAGES
    assert [p.url for p in found[:MEMBER_FIRST]] == [p.url for p in evidence(q, idx)[:MEMBER_FIRST]]


# ----------------------------------------------------------------------------- outside review (before publishing)
def test_a_verified_rate_under_the_wrong_measure_fails_the_check():
    from tkb.grounded import check
    facts = ["Bright Savings ($0.01-$1,000,000): 2.23% dividend rate / 2.25% APY", "Platinum Visa: 12.50% - 19.50% APR"]
    p = [NS(text="Bright Savings pays a great rate.", url=D + "/savings", published=None)]
    assert check("Bright Savings pays 2.25% APY.", [1], p, facts, "q")
    assert check("Its dividend rate is 2.23% and the APY is 2.25%.", [1], p, facts, "q")
    assert not check("Bright Savings pays 2.23% APY.", [1], p, facts, "q")            # the dividend rate as APY
    assert not check("The APY is 2.23%.", [1], p, facts, "q")
    assert check("The Platinum Visa APR is 12.50% to 19.50% APR.", [1], p, facts, "q")
    assert not check("Bright Savings has a 12.50% APY.", [1], p, facts, "q")


def test_a_repeated_question_gets_the_same_answer_even_if_the_llm_failed_the_first_time():
    q = "What is the Home$tart program?"
    calls = {"n": 0}

    class Flaky(FakeLLM):
        def json(self, purpose, system, user, max_tokens=500, timeout=None):
            calls["n"] += 1
            return None if calls["n"] == 1 else super().json(purpose, system, user, max_tokens, timeout)
    k = _kb(Flaky({q: {"route": "explain", "products": [], "search": ""}}, answers={q: {"answer": None}}))
    first = k.answer(q)
    assert k.answer(q) is first and k.answer(q).text == first.text           # the scorer's repeat check
    assert k.answer(q, "2026-09-01") is not first                            # another date is another question


@pytest.mark.parametrize("bad", [{"route": "rate", "products": 7, "search": "x"},
                                 {"route": "rate", "products": "auto loan", "search": 3},
                                 {"route": "rate", "products": None, "decline": ["x"], "search": None}])
def test_reply_fields_of_the_wrong_type_are_ignored_not_crashed_on(bad):
    q = parse_question("What's the APR on a 60-month auto loan for a 2018 car?")
    llm = fake({q.text: bad})
    reading = interpret(llm, q, None, ["2026-09-28"])
    assert reading is not None and reading["products"] == [] and isinstance(reading["search"], str)


def test_written_answer_citations_of_the_wrong_type_are_ignored():
    q = "What is the Home$tart program?"
    for cited in (5, "1,2", None, [True, "1"]):
        k = _kb(fake({q: {"route": "explain", "products": [], "search": ""}},
                     answers={q: {"answer": "Home$tart helps first-time buyers.", "cited": cited}}))
        a = k.answer(q)
        assert "Home$tart helps first-time buyers." not in a.text or a.sources     # never an uncited answer


def test_a_rate_from_another_tier_is_not_offered_as_evidence_or_accepted():
    from tkb.grounded import check, fact_lines
    tiers = ("Savings Rates\n\n| Account Type | Balance Tier | Dividend Rate | APY |\n| --- | --- | --- | --- |\n"
             "| Share Savings | $0.01 - $99,999.99 | 2.23% | 2.25% |\n"
             "| Share Savings | $100,000+ | 2.03% | 2.05% |\n\nRates are effective as of 06/02/2026.\n")
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28",
                pages=[NS(url=D + "/rates", title="Rates", markdown=tiers, fetched_at="2026-09-28T10:00:00Z")]))
    q = parse_question("I have $300,000 in Share Savings - explain how the APY works for that balance")
    R = k.store.resolved()
    assert R is not None
    facts, _ = fact_lines(q, R)
    assert any("2.05%" in f for f in facts) and not any("2.25%" in f for f in facts)
    p = [NS(text="Share Savings explained.", url=D + "/rates", published=None)]
    assert check("At that balance the APY is 2.05%.", [1], p, facts, q.text)
    assert not check("At that balance the APY is 2.25%.", [1], p, facts, q.text)       # another tier's APY


def test_a_question_about_a_published_example_is_not_a_personal_quote():
    q = parse_question("What's the current table's monthly payment example for a fifteen-year fixed refinance?")
    out = apply(q, {"route": "decline", "products": ["mortgage"], "decline": "personal_quote", "search": ""})
    assert out.decline is None                                            # blind D-012: the site prints it
    mine = parse_question("What would my monthly payment be on a 15-year fixed refinance of my house?")
    out2 = apply(mine, {"route": "decline", "products": ["mortgage"], "decline": "personal_quote", "search": ""})
    assert out2.decline == "personal_quote" or mine.personal


def test_no_tiered_rate_is_offered_when_no_tier_holds_the_amount():
    from tkb.grounded import check, fact_lines
    capped = ("Checking Rates\n\n| Account Type | Balance Tier | Dividend Rate | APY |\n| --- | --- | --- | --- |\n"
              "| 1st Rate Checking | $0.01 - $9,999.99 | 3.00% | 3.04% |\n"
              "| Free Checking | | 0.10% | 0.10% |\n\nRates are effective as of 06/02/2026.\n")
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28",
                pages=[NS(url=D + "/rates", title="Rates", markdown=capped, fetched_at="2026-09-28T10:00:00Z")]))
    R = k.store.resolved()
    assert R is not None
    q = parse_question("I have $50,000 in 1st Rate Checking - explain what APY that balance earns")
    assert q.products == ["1st rate checking"] and q.x == 50_000
    facts, _ = fact_lines(q, R)
    assert not any("3.04%" in f for f in facts)                 # $50,000 is above the only tier's cap
    p = [NS(text="1st Rate Checking explained.", url=D + "/rates", published=None)]
    assert not check("At that balance the APY is 3.04%.", [1], p, facts, q.text)
    both = parse_question("With $50,000, explain how the checking APYs compare")
    assert set(both.products) == {"free checking", "1st rate checking"}
    facts, _ = fact_lines(both, R)
    assert not any("3.04%" in f for f in facts) and any("0.10%" in f for f in facts)   # untiered product stays
    inside = parse_question("I have $5,000 in 1st Rate Checking - explain what APY that balance earns")
    assert any("3.04%" in f for f in fact_lines(inside, R)[0])
