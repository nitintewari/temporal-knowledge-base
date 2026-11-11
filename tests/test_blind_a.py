"""Rules added after blind set A's first run (qa 0.4958, kept in eval/blind_first_run.jsonl). Made-up text only.

  routing    a dated "website" is a date, not a link request; a named branch's "locator" / "24-hour ATM" question
             is about the branch, not the locator page or opening hours; a rate AND its minimum is a rate lookup
  documents  a date that names a document ("the article published July 12, 2024") is not the as-of date: the
             answer comes from that document
  variants   "not jumbo", "rather than the jumbo version", "without the jumbo option" exclude jumbo
  refusals   "the APR I personally will be approved for" is member data; "will ... on <date after the last
             crawl>" is a forecast
  products   Launchpad before IRA; "what happens if" is an explanation, not a rate lookup; "the 17-month special"
             is a certificate
  wording    small function words ("if", "into", "someone") are not topic words; "how much space" is not money
"""
import re
from types import SimpleNamespace as NS

import pytest

from tkb.query import content_words, parse_question
from tkb.system import FUTURE_RATE, TemporalKnowledgeBase

D = "https://www.dupaco.com"


# ----------------------------------------------------------------------------- routing
@pytest.mark.parametrize("question, intent", [
    ("Looking at the June 9, 2026 website, what APY did the 12-month certificate show?", "rate"),
    ("How did the 12-month certificate APY change from the May 12, 2026 website to the June 9, 2026 website?", "rate"),
    ("Which page lists the certificate rates?", "link"),                     # still a link request
    ("Where on the website can I find mortgage rates?", "link"),
    ("Where is the Peosta branch listed, and does the locator show a 24-hour ATM there?", "address"),
    ("Does the Hillcrest Road branch list a 24-hour ATM? What address is shown?", "address"),
    ("Where is the nearest ATM?", "link"),                                   # no named branch: the locator
    ("What are the lobby hours at the Galena branch?", "hours"),             # real opening hours
])
def test_dated_websites_named_branches_and_24_hour_atms_are_routed_by_what_is_asked(question, intent):
    assert parse_question(question).intent == intent


def test_a_rate_and_its_minimum_is_a_rate_lookup_but_a_minimum_alone_is_not():
    both = parse_question("What's the APY on a 24-month certificate, and how much do I need to open one?")
    assert both.intent == "rate" and both.attribute == "apy" and both.term_months == 24
    assert parse_question("What APY and minimum deposit are listed for the 17-month jumbo certificate special?"
                          ).intent == "rate"
    alone = parse_question("What's the minimum deposit to open a 24-month certificate?")
    assert alone.intent == "general" and alone.asks_minimum


# ----------------------------------------------------------------------------- dated documents
@pytest.mark.parametrize("question, date_ref, doc_date", [
    ("In the Learning Lab article published July 12, 2024, how much space did Dupaco occupy?", None, "2024-07-12"),
    ("According to the January 8, 2026 creative center grant announcement, how many people got memberships?",
     None, "2026-01-08"),
    ("What was the 12-month certificate APY on May 12, 2026?", "2026-05-12", None),     # an as-of date
    ("Back on May 19, 2026, what did the refinance table show?", "2026-05-19", None),
])
def test_a_date_that_names_a_document_is_not_the_as_of_date(question, date_ref, doc_date):
    q = parse_question(question)
    assert (q.date_ref, q.doc_date) == (date_ref, doc_date)


def release(date, n):
    return (f"{date}\n\n# Grants awarded {date}\n\nDUBUQUE, Iowa-Dupaco gave studio grants to local makers.\n\n"
            f"The credit union announced that {n} makers received studio memberships through its grant program.\n")


# Unrelated pages, so word weights look like a real site (a three-page site makes every word common).
FILLER = [f"Topic {i}\n\nMembers can read about budgeting, saving for college, checking accounts, travel tips "
          f"and online banking features on page {i}.\n" for i in range(12)]


def page(path, markdown, fetched="2026-09-28T10:00:00Z"):
    return NS(url=D + path, title=path, markdown=markdown, fetched_at=fetched)


@pytest.fixture(scope="module")
def kb():
    share = ("Bright Savings\n\n| Balance | Dividend Rate | Annual Percentage Yield (APY) |\n| --- | --- | --- |\n"
             "| $0.01 - $1,000,000 | 2.23% | 2.25% |\n\nRates are effective as of 06/02/2026.\n")
    pages = [page("/rates", share),
             page("/newsroom/grants-2025", release("January 13, 2025", 3)),
             page("/newsroom/grants-2026", release("January 08, 2026", 4))] + \
            [page(f"/learn/topic-{i}", text) for i, text in enumerate(FILLER)]
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=pages))
    return k


def test_a_named_document_is_answered_from_that_document(kb):
    a = kb.answer("According to the January 8, 2026 grant announcement, how many makers received studio memberships?")
    assert a.confident and "that 4 makers" in a.text and "that 3 makers" not in a.text
    assert [s.url for s in a.sources] == [D + "/newsroom/grants-2026"]


# ----------------------------------------------------------------------------- variants
@pytest.mark.parametrize("question, flags", [
    ("What APY did the 17-month fixed certificate special that was not jumbo show?", ("special",)),
    ("What APY could a saver see for the standard 17-month fixed special, rather than the jumbo version?",
     ("special",)),
    ("What APY was listed for the 10-month fixed certificate special, without the jumbo option?", ("special",)),
    ("What is the non-jumbo 17-month certificate special APY?", ("special",)),
    ("What is the 17-month jumbo certificate special APY?", ("jumbo", "special")),          # still jumbo
])
def test_a_negated_variant_is_excluded(question, flags):
    assert parse_question(question).flags == flags


def test_a_special_with_a_term_and_no_product_is_a_certificate():
    q = parse_question("What APY could a saver see for the standard 17-month fixed special?")
    assert q.products == ["certificate"] and q.intent == "rate"


# ----------------------------------------------------------------------------- refusals
def test_the_rate_i_personally_will_be_approved_for_is_member_data():
    assert parse_question("Can you tell me the exact APR I personally will be approved for?").personal
    assert not parse_question("What is the lowest APR for a 72-month auto loan?").personal


def test_will_on_a_date_after_the_last_crawl_is_a_forecast(kb):
    a = kb.answer("Will Bright Savings definitely pay the same APY on September 28, 2027?")
    assert a.confident is False and FUTURE_RATE in a.text and not re.search(r"\d", a.text)
    assert "2.25%" in kb.answer("What APY does Bright Savings pay?").text           # today: answered


# ----------------------------------------------------------------------------- products and wording
def test_launchpad_is_not_an_ira_and_what_happens_if_is_an_explanation():
    q = parse_question("My Launchpad Savings has reached $1,000. What happens if I do not move it to an IRA?")
    assert q.products == ["launchpad savings"] and q.intent == "general"
    assert parse_question("What is the Launchpad Savings APY?").intent == "rate"


def test_function_words_are_not_topic_words_and_space_is_not_money():
    assert {"if", "into", "someone"}.isdisjoint(content_words("If someone wires money into my account"))
    assert not parse_question("How much space did Dupaco occupy in the building?").asks_fee
    assert parse_question("How much does an incoming wire cost?").asks_fee
