"""Fix 1 after blind set A: questions that ask two things at once. Made-up text only.

  parts      two terms / two amounts / two as-of dates compared in one question -> one lookup per part, joined;
             a range ("between $10,000 and $24,999") is ONE value; a document's date is not an as-of date
  measures   "the dividend rate and ... the APY" named apart -> both measures
  minimum    a rate table's "Min. to Open / Min. to Earn" cell is kept on each fact and added when asked
  fees       "by phone, compared with online" -> two different rows (the same fee twice counts once)
  rules      "Can it pay dividends if I ...?" is a rule of the account (retrieval), not a rate lookup
"""
from types import SimpleNamespace as NS

import pytest

from tkb.facts import extract_facts
from tkb.query import parse_question, parts
from tkb.system import TemporalKnowledgeBase

D = "https://www.dupaco.com"


def certs(r12, r36, r60, effective):
    return ("Regular Certificates\n\n| Certificate | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |\n"
            "| --- | --- | --- | --- |\n"
            f"| 60 Month | {r60} | {r60} | $1,000.00 |\n| 36 Month | {r36} | {r36} | $1,000.00 |\n"
            f"| 12 Month | {r12} | {r12} | $1,000.00 |\n\nRates are effective as of {effective}.\n")


BOATS = ("Boat & RV Loans\n\n| Loan Amount | Term | APR |\n| --- | --- | --- |\n"
         "| $25,000 - $39,999 | 84 Months | 7.59% APR |\n| $40,000+ | 84 Months | 7.34% APR |\n\n"
         "Rates are effective as of 05/01/2026.\n")
FEES = ("Fee schedule\n\n| Service | Fee |\n| --- | --- |\n| Card payment taken by phone | $15.00 |\n"
        "| Card payment made online | $9.00 |\n| Paper statement copy | $3.00 |\n")
FILLER = [f"Topic {i}\n\nMembers can read about budgeting, saving for college, checking accounts, travel tips "
          f"and online banking features on page {i}.\n" for i in range(12)]


def page(path, markdown, fetched):
    return NS(url=D + path, title=path, markdown=markdown, fetched_at=fetched)


@pytest.fixture(scope="module")
def kb():
    may, jun = "2026-05-12T10:00:00Z", "2026-06-09T10:00:00Z"
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="01_2026-05-12", taken_on="2026-05-12",
                pages=[page("/rates", certs("2.90%", "2.00%", "1.70%", "03/03/2026") + "\n" + BOATS, may)]))
    k.ingest(NS(snapshot_id="03_2026-06-09", taken_on="2026-06-09",
                pages=[page("/rates", certs("3.40%", "2.10%", "1.80%", "06/02/2026") + "\n" + BOATS, jun),
                       page("/fees", FEES, jun), page("/fees.pdf", FEES, jun)]
                + [page(f"/learn/topic-{i}", t, jun) for i, t in enumerate(FILLER)]))
    return k


# ----------------------------------------------------------------------------- splitting
@pytest.mark.parametrize("question, slot, values", [
    ("Is the 60-month certificate paying more APY than the 36-month one?", "term_months", [60, 36]),
    ("For an 84-month boat loan, what APR is listed for $30,000 versus $50,000?", "x", [30000.0, 50000.0]),
    ("How did the 12-month certificate APY change from the May 12, 2026 website to the June 9, 2026 website?",
     "date_ref", ["2026-05-12", "2026-06-09"]),
])
def test_two_values_of_one_slot_become_two_parts(question, slot, values):
    assert [getattr(p, slot) for p in parts(parse_question(question))] == values


@pytest.mark.parametrize("question", [
    "What dividend rate do I earn on Share Savings with a balance between $10,000 and $24,999?",   # one range
    "What is the 60-month certificate APY?",                                                         # one value
    "In the article published July 12, 2024, what was the 12-month certificate APY on May 12, 2026?",  # doc date
])
def test_a_range_a_single_value_or_a_document_date_is_one_part(question):
    assert len(parts(parse_question(question))) == 1


def test_two_measures_named_apart_are_both_asked_for():
    assert parse_question("For Bright Savings, what is the dividend rate and what is the APY?").attribute is None
    assert parse_question("What is the Bright Savings APY?").attribute == "apy"


def test_a_rate_and_its_minimum_in_words_is_a_rate_lookup():
    q = parse_question("If I put money in the two-year certificate, what annual percentage yield is listed and what "
                       "is the opening minimum?")
    assert q.intent == "rate" and q.asks_minimum and q.term_months == 24


def test_a_conditional_yes_no_question_is_a_rule_of_the_account_not_a_rate():
    assert parse_question("Can Bright Savings pay me dividends if I stay with paper statements?").intent == "general"
    assert parse_question("What dividend rate does Bright Savings pay if I keep $500?").intent == "rate"


# ----------------------------------------------------------------------------- answers
def test_two_terms_are_answered_both(kb):
    a = kb.answer("Is the 60-month certificate paying more APY than the 36-month one? What are both yields?")
    assert a.confident and "60-month certificate rate is 1.80% APY" in a.text and "36-month" in a.text \
        and "2.10% APY" in a.text


def test_two_amounts_are_answered_both(kb):
    a = kb.answer("For an 84-month boat loan, what starting APR is listed for borrowing $30,000 versus $50,000?")
    assert "7.59% APR" in a.text and "7.34% APR" in a.text


def test_two_dates_are_answered_each_from_its_own_crawl(kb):
    a = kb.answer("How did the 12-month certificate APY change from the May 12, 2026 website to the June 9, 2026 "
                  "website?", as_of="2026-06-09")
    assert a.text.index("On May 12, 2026:") < a.text.index("2.90% APY") < a.text.index("On June 9, 2026:") \
        < a.text.index("3.40% APY")
    assert {s.snapshot_id for s in a.sources} == {"01_2026-05-12", "03_2026-06-09"}


def test_a_rates_minimum_is_kept_and_given_when_asked(kb):
    fact = next(f for f in extract_facts(certs("3.40%", "2.10%", "1.80%", "06/02/2026"), D + "/rates", "rate_sheet")
                if f.term_months == 12)
    assert fact.minimum == "$1,000.00 to earn"
    a = kb.answer("What's the APY on a 12-month certificate, and how much do I need to open one?")
    assert "3.40% APY" in a.text and "Minimum: $1,000.00 to earn" in a.text
    assert "Minimum" not in kb.answer("What's the APY on a 12-month certificate?").text      # only when asked


def test_two_fees_compared_are_two_different_rows(kb):
    a = kb.answer("What fee is listed for a card payment taken by phone, compared with a card payment made online?")
    assert "$15.00" in a.text and "$9.00" in a.text and a.text.count("$15.00") == 1


def test_a_part_the_site_does_not_answer_is_said_not_dropped():
    from types import SimpleNamespace as NS
    from tkb.system import TemporalKnowledgeBase
    rates = ("Personal Loans\n\n| Term | APR (As Low As) |\n| --- | --- |\n| 36 Months | 9.75% |\n\n"
             "Rates are effective as of 05/01/2026.\n")
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28",
                pages=[NS(url="https://www.dupaco.com/rates", title="Rates", markdown=rates,
                          fetched_at="2026-09-28T03:00:00Z")]))
    a = k.answer("Compare the APR on a 36-month personal loan vs a 120-month personal loan")
    assert "9.75%" in a.text and "For the other part of the question:" in a.text
