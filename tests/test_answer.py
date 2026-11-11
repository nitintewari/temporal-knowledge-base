"""Phase 3 tests: question understanding and answering, on a miniature Dupaco site (copies of real page shapes)."""
# pyright: reportOptionalMemberAccess=false
import re
from types import SimpleNamespace as NS

import pytest

from tkb.query import parse_question
from tkb.system import TemporalKnowledgeBase

D = "https://www.dupaco.com"


def auto_table(rows, effective):
    body = "\n".join(f"| {label} | {term} Months | {rate}% APR1 |" for label, term, rate in rows)
    return (f"Auto & Motorcycle Loans\n\n| Loan Program | Term | Annual Percentage Rate (As Low As) 1 |\n"
            f"| --- | --- | --- |\n{body}\n\nRates are effective as of {effective}.\n")


RATES = auto_table([("2024-27 Model Year", 60, "5.39"), ("2021-23 Model Year", 60, "5.64"),
                    ("2024-27 Model Year", 84, "5.59"), ("2021-23 Model Year", 84, "6.04")], "08/31/2026")
CALC_STALE = auto_table([("2023-26 Model Year", 60, "5.34"), ("2017-20 Model Year", 84, "6.49")], "1/1/2026")
SHARE = ("Share Savings\n\n| Balance | Dividend Rate | Annual Percentage Yield (APY) |\n| --- | --- | --- |\n"
         "| $25,000+ | 0.20% | 0.20% |\n| $10,000 - $24,999.99 | 0.15% | 0.15% |\n"
         "| $100 - $9,999.99 | 0.10% | 0.10% |\n\n"
         "Rates are effective as of 06/15/2026.\n")
MORTGAGE = ("Home Loans\n\n| Program | Rate | Points | APR |\n| --- | --- | --- | --- |\n"
            "| Purchase: 30-Year Fixed Conventional $100,000 or less | 7.125% | 0.00% | 7.27% |\n"
            "| Purchase: 30-Year Fixed Conventional $300,000 or less | 7.250% | 0.00% | 7.32% |\n\n"
            "Rates are effective as of 09/25/2026.\n")
GUIDANCE_STALE = MORTGAGE.replace("7.125%", "5.750%").replace("09/25/2026", "04/22/2026")


def press(date, title, body, n=22):
    return (f"[Emily Kress]({D}/newsroom/author/emily-kress)\n{date}\n\n# {title}\n\n{body}\n\n###\n\n"
            f"**ABOUT DUPACO** It has over 600 employees and {n} branch office locations.\n\n"
            f"## Handpicked for You\n\nJune 07, 2022\n\nIt has 19 branch office locations...\n")


HYVEE = press("June 20, 2025", "Dupaco evolves with purpose, plans Hy-Vee branch closure",
              "This location will close March 31, 2026, and its staff will stay on.\n\n\"Hy-Vee branch members can access "
              "the same help at the full-service branches at Key West and Sycamore Street,\" a spokesperson said.", n=23)
CONTACT = ("# Contact Us and Find Your Closest Location\n\n**Routing Number:** 273974581\n\nCall 800-373-7600.\n\n"
           "### Dupaco Credit Union\n\nDupaco Branch\n\n11375 Oldenburg Ln., Galena, IL, 61036\n\n"
           "[Join Dupaco](https://join.dupaco.com/) [Become a member](https://join.dupaco.com/)\n")
FAQ = ("# Mobile payments\n\nCan I put both my debit and credit card in a mobile wallet?\n\n"
       "Yes. Add your Dupaco debit and credit cards to Apple Pay, Google Pay or Samsung Pay for secure checkouts.\n\n"
       "Mobile wallet promotional rates of 9.99% APR apply to new mobile wallet card holders only today.\n")
HOMESTART = press("August 15, 2025", "First-time homebuyers get a boost: Dupaco offers Home$tart grants",
                  "DUBUQUE, Iowa-Dupaco is partnering with the FHLB through the Home$tart program. This initiative "
                  "provides up to $15,000 in assistance toward down payment and closing costs.\n\n"
                  "To learn about the Home$tart program or apply, visit dupaco.com/firsthome.")


def page(path, markdown, title="", fetched="2026-09-28T03:00:00Z"):
    return NS(url=D + path, title=title or path, markdown=markdown, fetched_at=fetched)


@pytest.fixture(scope="module")
def kb():
    may = [page("/rates", RATES.replace("5.39%", "5.19%").replace("08/31/2026", "05/01/2026"), fetched="2026-05-12"),
           page("/newsroom/a", press("March 17, 2026", "Old release", "Body.", n=23), fetched="2026-05-12")]
    sept = [page("/rates", RATES), page("/calculators/vehicle-affordability", CALC_STALE),
            page("/personal/savings-account", SHARE), page("/personal/loans/home-loans", MORTGAGE),
            page("/homebuying-guidance", GUIDANCE_STALE),
            page("/newsroom/a", press("March 17, 2026", "Old", "B.", n=23)),
            page("/newsroom/b", press("April 03, 2026", "New release", "Body.", n=22)), page("/newsroom/hy-vee", HYVEE),
            page("/contact", CONTACT, "Contact Us and Find Your Closest Location"),
            page("/online-and-mobile-banking/mobile-payments", FAQ, "Mobile payments"),
            page("/newsroom/hometart", HOMESTART)]
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="00_2026-01-15", taken_on="2026-01-15", pages=[page("/newsroom/hy-vee", HYVEE)]))
    k.ingest(NS(snapshot_id="01_2026-05-12", taken_on="2026-05-12", pages=may))
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=sept))
    return k


# ----------------------------------------------------------------------------- question understanding
@pytest.mark.parametrize("question, expect", [
    ("What's the APR for a 60-month auto loan on a 2025 model-year vehicle?",
     dict(intent="rate", products=["auto loan"], term_months=60, x=2025.0, x_kind="model_year", attribute="apr")),
    ("What APR is a five year personal loan?", dict(intent="rate", products=["personal loan"], term_months=60)),
    ("Can you tell me the interest rate for a 30-year mortgage?", dict(products=["mortgage"], term_months=360,
                                                                      attribute="rate")),
    ("What is your rate on a 7/1 adjustable-rate mortgage?", dict(intent="rate", unpublished="7/1")),
    ("What credit cards do you offer and what are their APRs?", dict(intent="rate",
                                                                    products=["platinum visa", "rewards visa"])),
    ("Can you list the credit card APRs, including business cards?", dict(segment=None)),
    ("What is the Roth IRA 17-month special APY?", dict(products=["ira certificate"], account="roth",
                                                        flags=("special",))),
    ("Do any Dupaco savings tiers pay 0.35% APY?", dict(premise=0.35, products=["share savings"])),
    ("What is the total number of Dupaco branch offices?", dict(intent="branch_count")),
    ("Is the Hy-Vee branch still open today (October 2026)?", dict(intent="closure", named_branch="Hy-Vee",
                                                                   date_ref="2026-10-31")),
    ("What time do branches close on Saturday?", dict(intent="hours")),
    ("Can you give me the lobby hours for the Mullan Avenue branch?", dict(intent="hours",
                                                                           named_branch="Mullan Avenue")),
    ("Where can I find a branch or ATM near me?", dict(intent="link")),
    ("How do I change my address on my Dupaco account?", dict(intent="general")),
    ("Can I add my Dupaco debit and credit cards to a mobile wallet?", dict(intent="general")),
    ("Who is eligible to become a Dupaco member?", dict(intent="eligibility")),
])
def test_question_understanding(question, expect):
    q = parse_question(question)
    for k, v in expect.items():
        assert getattr(q, k) == v, f"{question!r}: {k}={getattr(q, k)!r}, expected {v!r}"


# ----------------------------------------------------------------------------- G1 / G2: only the winning value
def test_rate_answer_carries_the_winner_never_the_stale_copy_G1(kb):
    a = kb.answer("What's the APR for a 60-month auto loan on a 2025 model-year vehicle?")
    assert "5.39%" in a.text and "5.34" not in a.text and a.confident
    assert "5.34%" in (a.conflict_note or "")                     # the loser is explained, outside the text
    assert any(s.url.endswith("/rates") for s in a.sources)


def test_a_named_tier_gets_that_tier_only_never_its_neighbours_G2(kb):
    a = kb.answer("What's the APR for an 84-month auto loan on a 2024 vehicle?")
    assert "5.59%" in a.text and "6.04" not in a.text and "5.39" not in a.text


def test_a_tier_the_newest_table_dropped_is_not_offered_and_shows_no_rate_R6(kb):
    a = kb.answer("Can I get an 84-month auto loan on a 2019 vehicle?")
    assert "doesn't list" in a.text and "%" not in a.text and "2021" in a.text     # which years ARE offered


def test_nested_loan_amount_tiers_lead_with_the_narrowest_R23(kb):
    a = kb.answer("Can you tell me the interest rate for a 30-year mortgage?")
    assert a.text.index("7.125%") < a.text.index("7.250%") and "5.750" not in a.text
    small = kb.answer("What is the 30-year mortgage rate on a $90,000 loan?").text    # inside BOTH tiers
    assert "7.125%" in small and "7.250" not in small


def test_balance_tier_and_superlative_and_false_premise(kb):
    assert "0.15%" in kb.answer("What dividend rate do I earn on Share Savings with $15,000?").text
    top = kb.answer("What is the highest Share Savings APY?").text
    assert "0.20%" in top and "$25,000" in top and "0.15" not in top
    premise = kb.answer("Do any Dupaco savings tiers pay 0.35% APY?").text
    assert premise.startswith("No") and "0.20%" in premise and "0.35" not in premise


def test_as_of_picks_the_crawl_and_a_date_in_the_question_counts_too_R5(kb):
    assert "5.19%" in kb.answer("60-month APR for a 2025 car?", as_of="2026-05-31").text
    assert "5.19%" in kb.answer("What was the 60-month APR for a 2025 car as of May 2026?").text
    assert "5.39%" in kb.answer("60-month APR for a 2025 car?").text


# ----------------------------------------------------------------------------- G3: refusals
@pytest.mark.parametrize("question", [
    "What is your rate on a 7/1 adjustable-rate mortgage?",
    "What interest rate do you charge on a construction loan?",
    "Can you give me the lobby hours for the Mullan Avenue branch?",
    "What is the address of the Elm Street branch?",
])
def test_refusals_decline_plainly_and_contain_no_digits_G3(kb, question):
    a = kb.answer(question)
    assert not a.confident and not re.search(r"\d", a.text) and "I don't know" in a.text


# ----------------------------------------------------------------------------- prose answers
def test_prose_answers_branch_count_closure_and_where_to_go(kb):
    assert "22 branch" in kb.answer("How many branches does Dupaco have?").text
    # as_of 05-31: crawl 01 (05-12) lacks the April 3 release, crawl 05 has it - published before 05-31, so 22 counts
    assert "22 branch" in kb.answer("How many branches does Dupaco have?", as_of="2026-05-31").text
    assert "23 branch" in kb.answer("How many branches does Dupaco have?", as_of="2026-03-31").text
    today = kb.answer("Is the Hy-Vee branch still open today (October 2026)?").text
    assert today.startswith("No") and "March 31, 2026" in today
    before = kb.answer("When does the Hy-Vee branch close?", as_of="2026-02-01")     # before the closure date
    assert "is scheduled to close on March 31, 2026" in before.text
    alt = kb.answer("Where can Hy-Vee branch members go for full-service banking?").text
    assert "Key West" in alt and "Sycamore" in alt


def test_routing_address_phone(kb):
    assert "273974581" in kb.answer("Can you repeat the routing number?").text
    assert "11375 Oldenburg" in kb.answer("What is the address of the Galena Branch?").text
    assert "800-373-7600" in kb.answer("What is the phone number for Dupaco?").text


# ----------------------------------------------------------------------------- links (R20) and retrieval (G4)
def test_links_come_only_from_the_crawl_R20(kb):
    join = kb.answer("How do I join Dupaco online?").text
    assert "https://join.dupaco.com/" in join
    assert "dupaco.com/contact" in kb.answer("What's the URL for Dupaco's branch and ATM locator?").text


def test_retrieval_answers_the_faq_and_never_quotes_a_percent_G4(kb):
    a = kb.answer("Can I put both my debit and credit card in a mobile wallet?")
    assert not a.text.startswith("Can I")        # the FAQ's answer paragraph, not the question repeated back
    assert "Apple Pay" in a.text and "%" not in a.text and "9.99" not in a.text
    home = kb.answer("What is Dupaco's Home$tart program?").text
    assert "$15,000" in home                      # the lead paragraph, not the "for more information" line


# ----------------------------------------------------------------------------- G5: deterministic, never crashes
def test_same_question_same_answer_and_errors_become_refusals_G5(kb):
    q = "What are the mortgage rates right now?"
    assert kb.answer(q).text == kb.answer(q).text
    a = kb.answer("")                             # nothing to work with: decline, do not crash
    assert not a.confident and not re.search(r"\d", a.text)


# ----------------------------------------------------------------------------- D5: before the first crawl (Phase 6)
@pytest.fixture(scope="module")
def may_only():
    share = SHARE.replace("06/15/2026", "03/03/2026")                    # in force since March
    pages = [page("/rates", RATES.replace("08/31/2026", "05/01/2026")),  # took effect May 1
             page("/personal/savings-account", share),
             page("/newsroom/a", press("March 17, 2026", "Old release", "Body.", n=23)),
             page("/newsroom/b", press("May 05, 2026", "New release", "Body.", n=22)),
             page("/online-and-mobile-banking/mobile-payments", FAQ, "Mobile payments")]
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="01_2026-05-12", taken_on="2026-05-12", pages=pages))
    return k


def test_before_the_first_crawl_answers_only_from_evidence_dated_that_early_D5(may_only):
    a = may_only.answer("What is the Share Savings APY for a $30,000 balance?", as_of="2026-04-15")
    assert a.confident and "0.20%" in a.text                             # table effective 03/03, still in force 05/12
    assert a.text.startswith("My earliest copy of the Dupaco website is from May 12, 2026")
    b = may_only.answer("How many branches does Dupaco have?", as_of="2026-04-15")
    assert "23" in b.text and "22" not in b.text                         # newest release published by April 15 (R4)
    c = may_only.answer("How many branches does Dupaco have?", as_of="2026-05-12")
    assert "22" in c.text and "earliest copy" not in c.text              # on the crawl day: normal answer


@pytest.mark.parametrize("question", ["What's the APR for a 60-month auto loan on a 2025 model-year vehicle?",
                                      "Can I put both my debit and credit card in a mobile wallet?"])
def test_before_the_first_crawl_without_dated_evidence_says_it_cannot_tell_D5(may_only, question):
    a = may_only.answer(question, as_of="2026-04-15")                    # auto table took effect May 1; FAQ undated
    assert a.confident is False and "taken after that date" in a.text and not re.search(r"\d", a.text)
    assert may_only.answer(question).confident                           # the same question today is answered


# ----------------------------------------------------------------------------- Phase 6: dates, forecasts, measures
def test_between_crawls_a_later_crawl_proves_an_earlier_change(kb):
    # crawl 01 (05-12) shows 5.19% effective 05/01; crawl 05 (09-28) shows 5.39% effective 08/31
    q = "What's the APR for a 60-month auto loan on a 2025 model-year vehicle?"
    assert "5.39%" in kb.answer(q, as_of="2026-09-01").text      # effective 08/31: already in force on 09-01
    assert "5.19%" in kb.answer(q, as_of="2026-08-30").text      # the day before it took effect
    assert "5.19%" in kb.answer(q, as_of="2026-05-12").text      # exactly on a crawl day


@pytest.mark.parametrize("question, date_ref, future, attribute", [
    ("What was the Share Savings rate in 2019?", "2019-12-31", False, None),       # a year alone dates a rate
    ("How many employees used VTO in 2023?", None, False, None),                     # ...but labels a fact (R21)
    ("APR for a 2019 vehicle?", None, False, "apr"),                                 # ...and a model year is not one
    ("What will the 30-year mortgage rate be next year?", None, True, "rate"),
    ("Will the Galena branch be open next Monday?", None, False, None),              # not a rate: not a forecast
    ("30-year purchase mortgage rate and APR for a $250,000 loan?", None, False, None),   # both measures
])
def test_dates_forecasts_and_measures_are_read_from_the_question(question, date_ref, future, attribute):
    q = parse_question(question)
    assert (q.date_ref, q.future, q.attribute) == (date_ref, future, attribute)


@pytest.mark.parametrize("question", ["What will the auto loan rate be next year?", "What is Dupaco's stock price?",
                                      "What was the Share Savings rate in 2019?"])
def test_forecasts_prices_of_non_products_and_years_before_the_crawls_are_declined_G3(kb, question):
    a = kb.answer(question)
    assert a.confident is False and not re.search(r"\d", a.text.replace("2019", ""))


def test_a_number_about_something_that_is_not_a_product_is_a_price_question_G3():
    for question in ("What is Dupaco's stock price?", "What is the CEO's annual salary?"):
        q = parse_question(question)
        assert q.asks_price and not q.products                     # answer_general declines these
    assert not parse_question("Does Dupaco offer student loans?").asks_price


# ----------------------------------------------------------------------------- Phase 6 review: combined constraints
def test_a_date_and_a_model_year_together_keep_both_constraints(kb):
    """Review P2: "As of May 2026 ... a 2021 vehicle" lost the model year and listed every tier."""
    a = kb.answer("As of May 2026, what was the 60-month auto-loan APR for a 2022 vehicle?").text
    assert "5.64%" in a and "5.19%" not in a and "5.39%" not in a      # its tier only, from the May crawl
    for question, year in [("As of May 2026, what was the 60-month APR for a 2021 vehicle?", 2021),
                           ("As of September 30, 2026, what is the 84-month APR for a 2025 vehicle?", 2025),
                           ("In June 2026, what was the 72-month APR for a 2018 car?", 2018)]:
        q = parse_question(question)
        assert q.x == year and q.x_kind == "model_year" and q.date_ref


@pytest.mark.parametrize("question, attribute, minimum, superlative, intent", [
    ("What is the dividend rate on High-Yield Savings for $600,000?", "dividend_rate", False, None, "rate"),
    ("High-Yield Savings APY for $300,000?", "apy", False, None, "rate"),             # "High-Yield" is not "yield"
    ("What is the minimum deposit to open a High-Yield Savings account?", None, True, None, "general"),
    ("What's the minimum to open a 17-month jumbo certificate special?", None, True, None, "general"),
    ("What is the lowest auto loan rate?", None, False, "min", "rate"),              # a real superlative
])
def test_measures_and_minimums_are_read_correctly(question, attribute, minimum, superlative, intent):
    q = parse_question(question)
    assert (q.attribute, q.asks_minimum, q.superlative, q.intent) == (attribute, minimum, superlative, intent)


FEES = ("# Fee schedule\n\n|Stop payment (check, ACH, &amp; bill pay)|$30.00* per item|||\n"
        "|Domestic wire|$25.00 each|\n|International wire transfer|$55.00 each|\n")
HY_NOTE = ("High-Yield Savings: dividends and APY are as of the most recent declaration date. Opening AND keeping "
           "this account takes a $50,000 minimum balance. Rates can change after opening.\n")
PRICING_BLOG = "# Pricing tips\n\nSet a price your customers expect for your stock: for example, instead of $100, charge $99.\n"
FOUNDED = press("May 05, 2026", "Release", "Founded in 1948 by ten Dubuque Packing Company employees, membership has "
                "grown ever since.")                          # above the teaser block, like the real boilerplate
# Unrelated paragraphs: retrieval thresholds are calibrated on ~16,000 passages, so a 6-passage site cannot reach them.
_TOPICS = ["budgeting", "retirement", "insurance", "scholarships", "volunteering", "home buying", "car shopping",
           "fraud alerts", "mobile banking", "student life", "small business", "community events"]
FILLER = "# Learn\n\n" + "\n\n".join(f"Our {t} guide number {i} explains {t} ideas for members and families who "
                                       f"want practical help with {t} this season; check it before using ATMs."
                                       for i in range(5) for t in _TOPICS)   # "check", "using", "ATMs" common, as on
                                                                             # the real site


@pytest.fixture(scope="module")
def fees_kb():
    pages = [page("/hubfs/fee-schedule.pdf", FEES, "Fee schedule"), page("/personal/savings-account", HY_NOTE),
             page("/learn/blog/pricing", PRICING_BLOG, "Pricing tips"), page("/newsroom/founded", FOUNDED),
             page("/learn", FILLER, "Learn")]
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=pages))
    return k


def test_fees_minimums_and_founding_year_are_answered_from_the_site(fees_kb):
    assert "$30.00" in fees_kb.answer("What does Dupaco charge for a stop payment?").text   # searched, not refused
    wire = fees_kb.answer("How much is a domestic wire transfer?").text
    assert "$25.00" in wire and "$55" not in wire                                          # the row asked for
    assert "$50,000" in fees_kb.answer("What is the minimum deposit to open a High-Yield Savings account?").text
    assert "1948" in fees_kb.answer("What year was Dupaco founded?").text


@pytest.mark.parametrize("question", ["What is Dupaco's stock price?", "What does Dupaco charge for a cashier's check?"])
def test_an_amount_the_site_does_not_state_is_declined(fees_kb, question):
    a = fees_kb.answer(question)                 # a company number; a fee missing from the schedule
    assert a.confident is False and "$" not in a.text


def test_internal_errors_are_counted_and_raise_in_strict_mode(fees_kb, monkeypatch):
    """Review P2: a bug must not look like "the website doesn't say"."""
    import tkb.system as system
    def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(system, "answer_prose", broken)
    fees_kb._answers.clear()                                             # asked earlier in this module: re-answer
    with pytest.raises(RuntimeError):                                    # tests run with TKB_STRICT=1
        fees_kb.answer("What year was Dupaco founded?")
    monkeypatch.setenv("TKB_STRICT", "0")                                # the scorer's run: refuse, but record
    before = len(fees_kb.errors)
    assert fees_kb.answer("What year was Dupaco founded?").confident is False
    assert len(fees_kb.errors) == before + 1 and "RuntimeError: boom" in fees_kb.errors[-1][2]


# ----------------------------------------------------------------------------- independent set (in-*) findings
@pytest.mark.parametrize("question, attribute", [
    ("For Bright Savings, can you give me just the dividend rate rather than the APY?", "dividend_rate"),
    ("Give me the APY, not the dividend rate, for Share Savings", "apy"),
])
def test_a_measure_after_rather_than_is_not_the_one_asked_for(question, attribute):
    assert parse_question(question).attribute == attribute


@pytest.mark.parametrize("question, intent", [
    ("How many volunteer hours did Dupaco employees log in 2024?", "general"),    # a count, not opening hours
    ("What are the lobby hours?", "hours"),
    ("What exact fixed dollar fee would my business pay for merchant Visa processing?", "general"),  # a fee
    ("What do Dupaco's Visa cards charge?", "rate"),                               # "charge" = the APR
    ("How much would $15,000 earn in a Share Savings account?", "rate"),          # "how much ... earn" = a rate
])
def test_counts_fees_and_rates_are_told_apart(question, intent):
    assert parse_question(question).intent == intent


@pytest.mark.parametrize("question, personal", [
    ("What is the current balance in my Dupaco checking account?", True),
    ("Leaving advertised starting rates aside, what exact auto-loan APR has Dupaco approved specifically for me?", True),
    ("I keep $12,000 in my Health Savings Account. What APY applies to that balance?", False),
    ("What rate would I get on my $15,000 balance in Share Savings?", False),
])
def test_member_specific_data_is_recognised(question, personal):
    assert parse_question(question).personal is personal


def test_member_specific_data_is_declined_once_and_without_numbers(kb):
    a = kb.answer("What is the current balance in my Dupaco checking account?")
    assert a.confident is False and not re.search(r"\d", a.text) and a.text.count("Please contact") == 1


VOLUNTEER = press("April 21, 2025", "Volunteering pays off", "In 2024 alone:\n\n- Dupaco's 602 employees volunteered "
                  "a total of 6,187 hours.\n- Dupaco employees served on 170 nonprofit boards and committees")
IMPACT = ("# 2025 Impact Report\n\nIn 2025, Dupaco's 627 employees gave 6,136 volunteer hours in total, many "
          "through their volunteer time off benefit.\n\nNonprofit boards and committees that staff served on to provide "
          "leadership and guidance.\n")              # a caption with no year: the second-passage rule keeps it out
PETS = ("# Pet insurance\n\nFewer pet owners carried pet insurance in the past, but more now see "
        "its value for their pets and wallets.\n\nWith coverage through providers like Figo Pet Insurance, offered by "
        "Dupaco Insurance Services, a portion of eligible vet costs can be reimbursed.\n")
LAB = press("July 12, 2024", "Learning Lab", "Dupaco's newest branch, a Learning Lab, is located at 2530 Corridor Way, "
            "just off Interstate 80 in Coralville. Members can visit the Coralville Learning Lab branch soon.")


@pytest.fixture(scope="module")
def text_kb():
    pages = [page("/newsroom/volunteering", VOLUNTEER), page("/hubfs/impact-report.pdf", IMPACT, "Impact Report"),
             page("/newsroom/learning-lab", LAB), page("/contact", CONTACT, "Contact Us"), page("/learn", FILLER, "Learn"),
             page("/learn/blog/pet-insurance", PETS, "Pet insurance"),
             page("/learn/providers", "# Providers\n\n" + "\n\n".join(
                 f"We offer a {t} provider list that helps members compare each provider before they decide."
                 for t in _TOPICS[:6]), "Providers")]   # like the real crawl: "offer" and "provider" common, "pet" rare
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=pages))
    return k


def test_a_list_item_keeps_its_year_and_the_asked_year_wins(text_kb):
    a = text_kb.answer("How many volunteer hours did Dupaco employees log in 2024?").text
    assert "6,187" in a and "6,136" not in a


def test_an_address_in_the_text_answers_a_place_that_is_not_a_branch(text_kb):
    a = text_kb.answer("What street address does the Coralville Learning Lab announcement give?").text
    assert "2530 Corridor Way" in a and "Oldenburg" not in a                     # not the branch list
    assert "11375 Oldenburg" in text_kb.answer("What is the address of the Galena Branch?").text   # branches unchanged


def test_an_earlier_paragraph_is_used_only_if_it_answers_as_much(text_kb):
    a = text_kb.answer("I'm looking for pet insurance. Does Dupaco offer it, and which provider does it name?").text
    assert "Figo" in a                                   # not the earlier intro paragraph that only mentions pets


# ----------------------------------------------------------------------------- second review of the in-* fixes
@pytest.mark.parametrize("question, personal", [
    ("What is my balance?", True),
    ("How can I check my balance?", False),                 # public guidance, not member data
    ("Where can I see my recent transactions?", False),
])
def test_member_data_is_declined_but_how_to_questions_are_answered(question, personal):
    assert parse_question(question).personal is personal


@pytest.mark.parametrize("question, intent", [
    ("How many hours is the branch open on Saturday?", "hours"),        # opening hours, not the branch count
    ("How many branches does Dupaco have?", "branch_count"),
    ("How many volunteer hours did Dupaco employees log in 2024?", "general"),
])
def test_hours_counts_and_branch_counts_are_told_apart(question, intent):
    assert parse_question(question).intent == intent


FEES_MORE = ("# Fee schedule\n\n|Merchant Visa processing fees|Price varies|||\n"
             "|Debit card transactions at Dupaco ATMs|Free|\n"
             "|Processing fee for payments using a card (online)|$9.00|\n")
CARDS_PAGE = ("# Rates\n\nVisa cards: purchases get a grace period, and there are no annual fees or participation "
              "fees.\n")           # like the real rates page: under the card table, without naming the Platinum card
REWARDS_BLOG = "# Rewards cards\n\nDupaco's Rewards Visa has no annual fee, and the annual fee question comes up often.\n"


@pytest.fixture(scope="module")
def fees2_kb():
    pages = [page("/hubfs/fee-schedule-2.pdf", FEES_MORE, "Fee schedule"), page("/rates", CARDS_PAGE, "Rates"),
             page("/learn/blog/rewards", REWARDS_BLOG, "Rewards cards"), page("/learn", FILLER, "Learn")]
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=pages))
    return k


def test_a_variable_price_is_explained_without_a_number(fees2_kb):
    a = fees2_kb.answer("What exact fixed dollar fee would my business pay for merchant Visa processing?")
    assert a.confident is False and "Price varies" in a.text and not re.search(r"\d", a.text)


def test_free_and_no_fee_are_fee_answers(fees2_kb):
    atm = fees2_kb.answer("Is there a fee for using Dupaco ATMs?").text
    assert "Free" in atm and "$9" not in atm             # "Free" is a fee answer; "using" is not the topic
    card = fees2_kb.answer("What's the annual fee on the Platinum Visa?").text
    assert "no annual fees" in card and "Rewards" not in card                 # the product asked about


def test_a_count_takes_one_figure_from_one_passage(text_kb):
    a = text_kb.answer("For 2024, how many nonprofit boards and committees did Dupaco employees serve on?").text
    assert "170" in a and "6,136" not in a and "2025" not in a and "leadership" not in a


def test_of_several_matching_branches_the_most_specific_one_is_named(fees2_kb):
    k = TemporalKnowledgeBase()
    two = ("# Contact Us\n\n### Dupaco Credit Union\n\nDupaco Branch\n\n3299 Hillcrest Rd., Dubuque, IA, 52001\n\n"
           "### Dupaco Credit Union\n\nDupaco Branch\n\n1465 Sycamore St., Dubuque, IA, 52001\n")
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=[page("/contact", two, "Contact Us")]))
    a = k.answer("Where is the Hillcrest Road branch in Dubuque? Please include the ZIP code.").text
    assert "3299 Hillcrest" in a and "Sycamore" not in a
