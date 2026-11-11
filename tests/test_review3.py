"""Third review: one focused test per fix, on a miniature site. Each fails when its fix is switched off.

  1  member data      "Can I see my balance?" is declined; "How can I check my balance?" is not (query.py)
  2  requested metric an APY question about an APR-only product says so; no silent substitution (compose.py)
  3  history          between crawls, a later edit of a page the earlier crawl saw does not replace it (resolve.py)
  4  provenance       each fact is cited with the crawl it was read from, not the crawl the date picked
"""
import re
from types import SimpleNamespace as NS

import pytest

from tkb.query import parse_question
from tkb.system import MEMBER_DATA, TemporalKnowledgeBase

D = "https://www.dupaco.com"


def auto_table(rate, effective):
    return ("Auto & Motorcycle Loans\n\n| Loan Program | Term | Annual Percentage Rate (As Low As) 1 |\n"
            f"| --- | --- | --- |\n| 2024-27 Model Year | 60 Months | {rate}% APR1 |\n\n"
            f"Rates are effective as of {effective}.\n")


SHARE = ("Share Savings\n\n| Balance | Dividend Rate | Annual Percentage Yield (APY) |\n| --- | --- | --- |\n"
         "| $25,000+ | 0.20% | 0.20% |\n| $100 - $24,999.99 | 0.10% | 0.10% |\n\n"
         "Rates are effective as of 06/15/2026.\n")
MORTGAGE15 = ("Home Loans\n\n| Program | Rate | Points | APR |\n| --- | --- | --- | --- |\n"
              "| Purchase: 15-Year Fixed Conventional | 6.750% | 0.00% | 6.89% |\n\n"
              "Rates are effective as of 09/25/2026.\n")


def press(date, n):
    return (f"{date}\n\n# Release {date}\n\nBody text of the release.\n\n###\n\n"
            f"**ABOUT DUPACO** It has over 600 employees and {n} branch office locations.\n")


def page(path, markdown, fetched):
    return NS(url=D + path, title=path, markdown=markdown, fetched_at=fetched)


@pytest.fixture(scope="module")
def kb():
    may = "2026-05-12T10:00:00Z"
    aug = "2026-08-27T10:00:00Z"
    sep = "2026-09-28T10:00:00Z"
    crawls = [
        ("01_2026-05-12", [page("/rates", auto_table("5.19", "05/01/2026"), may),
                           page("/newsroom/a", press("May 05, 2026", 22), may)]),
        ("04_2026-08-27", [page("/rates", auto_table("5.19", "05/01/2026"), aug),
                           page("/newsroom/a", press("May 05, 2026", 22), aug)]),
        ("05_2026-09-28", [page("/rates", auto_table("5.39", "08/31/2026") + "\n" + SHARE, sep),
                           page("/personal/loans/home-loans", MORTGAGE15, sep),
                           page("/newsroom/a", press("May 05, 2026", 23), sep),     # edited later, date kept
                           page("/newsroom/b", press("June 01, 2026", 24), sep)]),  # first seen in 05, dated June 1
    ]
    k = TemporalKnowledgeBase()
    for sid, pages in crawls:
        k.ingest(NS(snapshot_id=sid, taken_on=sid[3:13], pages=pages))
    return k


# ----------------------------------------------------------------------------- 1 member data
@pytest.mark.parametrize("question, personal", [
    ("Can I see my balance?", True),
    ("Can I know my current balance?", True),
    ("Can I get the APR Dupaco approved for me?", True),
    ("How can I check my balance?", False),                       # how-to: public guidance
    ("Where can I see my balance?", False),
    ("Can I check my balance with the mobile app?", False),       # asks about a channel
    ("Can I open an account online?", False),                     # not about own data at all
])
def test_requests_for_own_data_are_member_data_however_phrased(question, personal):
    assert parse_question(question).personal is personal


def test_can_i_see_my_balance_is_declined_with_the_member_data_reason(kb):
    a = kb.answer("Can I see my balance?")
    assert a.confident is False and MEMBER_DATA in a.text and not re.search(r"\d", a.text)


# ----------------------------------------------------------------------------- 2 requested metric
def test_apy_on_an_apr_only_product_says_so_and_gives_no_rate(kb):
    a = kb.answer("What's the APY on a 60-month auto loan?")
    assert a.confident is False and "an APR, not an APY, for the auto loan" in a.text
    assert "%" not in a.text and "5.39" not in a.text


def test_apr_on_a_savings_account_names_what_is_published(kb):
    a = kb.answer("What is the APR on Share Savings?")
    assert a.confident is False and "a dividend rate and APY, not an APR" in a.text and "0.10" not in a.text


def test_a_published_measure_and_an_unnamed_measure_are_still_answered(kb):
    assert "0.10% dividend rate" in kb.answer("What is the dividend rate on Share Savings?").text
    assert "5.39% APR" in kb.answer("What is the 60-month auto loan rate?").text


def test_a_rate_only_answer_does_not_repeat_the_word_rate(kb):
    a = kb.answer("What's the interest rate on a 15-year mortgage?").text
    assert "6.750%" in a and "% rate" not in a
    assert "0.10% dividend rate" in kb.answer("What dividend rate does Share Savings pay on $500?").text


# ----------------------------------------------------------------------------- 3 history between crawls
def test_a_later_edit_of_an_observed_page_does_not_rewrite_that_day(kb):
    # /newsroom/a says 22 in crawl 01; crawl 05's copy says 23 with the same "May 05" date. On 05-20 the
    # record is crawl 01's copy.
    a = kb.answer("How many branches does Dupaco have?", as_of="2026-05-20")
    assert "22" in a.text and "23" not in a.text


def test_a_page_first_seen_later_but_dated_earlier_still_counts(kb):
    # /newsroom/b (June 01) first appears in crawl 05; crawl 04 (08-27) did not see it, so on 06-15 it counts.
    a = kb.answer("How many branches does Dupaco have?", as_of="2026-06-15")
    assert "24" in a.text and {s.snapshot_id for s in a.sources} == {"05_2026-09-28"}


# ----------------------------------------------------------------------------- 4 provenance
def test_a_later_crawls_table_is_cited_as_that_crawl(kb):
    # 09-01 picks crawl 04 (08-27); the 5.39% comes from crawl 05's table effective 08/31.
    a = kb.answer("What's the 60-month auto loan APR on a 2025 car?", as_of="2026-09-01")
    assert "5.39%" in a.text
    assert {s.snapshot_id for s in a.sources} == {"05_2026-09-28"}


def test_an_answer_from_the_chosen_crawl_cites_that_crawl(kb):
    a = kb.answer("What's the 60-month auto loan APR on a 2025 car?", as_of="2026-06-01")
    assert "5.19%" in a.text and {s.snapshot_id for s in a.sources} == {"01_2026-05-12"}
    b = kb.answer("How many branches does Dupaco have?", as_of="2026-05-20")
    assert {s.snapshot_id for s in b.sources} == {"01_2026-05-12"}



def test_a_later_table_with_the_same_value_keeps_the_crawl_of_that_day_as_evidence():
    """Review: crawl 04 shows 5.19% (older table), crawl 05 shows 5.19% dated 06/01: on 08-27 cite crawl 04."""
    aug, sep = "2026-08-27T10:00:00Z", "2026-09-28T10:00:00Z"
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="04_2026-08-27", taken_on="2026-08-27",
                pages=[page("/rates", auto_table("5.19", "01/02/2026"), aug)]))
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28",
                pages=[page("/rates", auto_table("5.19", "06/01/2026"), sep)]))
    a = k.answer("What's the 60-month auto loan APR on a 2025 car?", as_of="2026-08-27")
    assert "5.19%" in a.text and {s.snapshot_id for s in a.sources} == {"04_2026-08-27"}
