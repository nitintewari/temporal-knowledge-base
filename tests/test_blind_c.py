"""Blind set C (written by an outside model after the code was frozen): the general rules its first run showed
missing. Question wording here is made up; no website text."""
import pytest

from tkb.query import parse_question


# ----------------------------------------------------------------------------- fix 1: numbers written as words
@pytest.mark.parametrize("question, months", [
    ("rate for a seventy-two-month car loan on a 2026 vehicle", 72),      # was read as a 2-month term
    ("APR for an eighty-four month loan on a 2023 truck", 84),
    ("a thirty-year fixed mortgage", 360),
    ("a fifteen year fixed mortgage", 180),
    ("the forty-eight-month personal loan", 48),
    ("a twenty one month certificate", 21),
    ("a 60-month auto loan", 60),
])
def test_terms_written_as_words(question, months):
    assert parse_question(question).term_months == months


@pytest.mark.parametrize("question, amount", [
    ("my IRA just hit fifteen grand, what APY", 15_000),
    ("savings tier for 25 thousand dollars", 25_000),
    ("what APY at $15k", 15_000),
    ("APY on $2,500", 2_500),
])
def test_balances_written_as_words(question, amount):
    q = parse_question(question)
    assert q.x == amount and q.x_kind == "amount"


@pytest.mark.parametrize("question, measure", [
    ("What APY applies to the 48-month personal loan? Give an APY, not an APR.", "apy"),
    ("the regular ten-month special: its dividend rate, before the APY figure", "dividend_rate"),
    ("For the jumbo special, give the Roth APY rather than the dividend rate", "apy"),
])
def test_a_measure_set_aside_with_not_or_before_is_not_asked_for(question, measure):
    assert parse_question(question).attribute == measure


def test_a_fixed_conventional_loan_is_a_mortgage_without_the_word():
    q = parse_question("APR for a $200,000 thirty-year fixed conventional purchase loan")
    assert q.products == ["mortgage"] and q.term_months == 360 and q.x == 200_000
    assert parse_question("APR on a fixed conventional purchase loan of $200,000").products == ["mortgage"]
    assert parse_question("today's APR on a 15-year fixed for $150,000").products == ["mortgage"]
    car = parse_question("lowest APR for a conventional seventy-two-month loan on a 2026 vehicle")
    assert car.products == ["auto loan"]                        # "conventional" alone is not a mortgage


# ----------------------------------------------------------------------------- fixes 3-7 on a miniature site
from types import SimpleNamespace as NS  # noqa: E402

from tkb.retrieve import PassageIndex  # noqa: E402
from tkb.system import TemporalKnowledgeBase  # noqa: E402

D = "https://www.dupaco.com"
MORTGAGE = ("Mortgage Rates\n\n| Program | Rate | Points | APR | *Payment Example |\n| --- | --- | --- | --- | --- |\n"
            "| Purchase: 15-Year Fixed Conventional | 6.50% | 0 | 6.61% | $1,111.11 |\n"
            "| Refinance: 15-Year Fixed Conventional | 6.60% | 0 | 6.70% | $1,122.22 |\n\n"
            "Rates are effective as of 09/25/2026.\n\n"
            "Cash-Out Refinance\n\n| Term | Rate | Points | APR | *Payment Example |\n| --- | --- | --- | --- | --- |\n"
            "| Refinance: 15-Year Fixed Conventional | 5.90% | 0.00% | 6.01% | $1,050.00 |\n\n"
            "Rates are effective as of 07/06/2026.\n")
CONTACT = ("# Contact Us\n\nFor general questions use the form. Or if you have an urgent need, call 800-555-0100 "
           "right away.\n\n**Address:** P.O. Box 42\n\nSpringfield, IA 52099-0042\n\n"
           "### Branches\n\nDupaco Branch\n\n12 Maple St., Springfield, IA, 52099\n\nClosed\n\n"
           "Drive Up Window · 24-hour ATM\n\n### Dupaco ATM\n\nCall 800-555-0100 for help.\n")
CARDS = ("# Credit cards\n\nWhat comes with the card?\n\nOur made-up cards include a few perks at no extra cost, including:\n\n"
         "  - Trip Help Desk\n  - Gadget Warranty Plus\n\nThat is the whole list for this example page.\n")


def page(path, markdown):
    return NS(url=D + path, title=path, markdown=markdown, fetched_at="2026-09-28T03:00:00Z")


@pytest.fixture(scope="module")
def kb():
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28",
                pages=[page("/rates", MORTGAGE), page("/contact", CONTACT), page("/personal/credit-cards", CARDS)]))
    return k


def test_a_list_after_its_lead_line_is_one_passage_even_with_short_items():
    idx = PassageIndex.build({D + "/personal/credit-cards": page("/personal/credit-cards", CARDS)})
    whole = [p.text for p in idx.passages if "Trip Help Desk" in p.text]
    assert whole and "Gadget Warranty Plus" in whole[0] and "no extra cost" in whole[0]


def test_points_and_the_payment_example_are_given_when_asked(kb):
    a = kb.answer("What interest rate, points and APR for a 15-year fixed purchase mortgage?")
    assert "6.50%" in a.text and "Points: 0." in a.text
    b = kb.answer("What monthly payment does the official example show for a fifteen-year fixed purchase mortgage?")
    assert "$1,111.11" in b.text
    assert "Points" not in kb.answer("What is the APR on a 15-year fixed purchase mortgage?").text


def test_a_cash_out_refinance_table_is_its_own_product_not_a_stale_copy(kb):
    cash = kb.answer("What APR is listed for a 15-year fixed cash-out refinance?")
    assert "6.01%" in cash.text and "cash-out" in cash.text
    plain = kb.answer("What APR is listed for a 15-year fixed refinance?")
    assert "6.70%" in plain.text and "6.01%" not in plain.text and "6.01%" not in (plain.conflict_note or "")


@pytest.mark.parametrize("question", ["Urgent card problem - who do I ring?", "My debit card is missing, what number?",
                                      "Someone stole my card. Who do I call?"])
def test_a_lost_or_stolen_card_gets_the_number_to_call_now(kb, question):
    a = kb.answer(question)
    assert a.confident and "800-" in a.text and "right away" in a.text


def test_the_mailing_address_and_a_branch_s_services(kb):
    mail = kb.answer("What's the mailing address if I want to send Dupaco a letter?")
    assert "P.O. Box 42, Springfield, IA 52099-0042" in mail.text
    branch = kb.answer("Where is the Maple Street branch located and what services does it have?")
    assert "12 Maple St." in branch.text and "Drive Up Window, 24-hour ATM" in branch.text


# ----------------------------------------------------------------------------- blind set D (after its first run)
@pytest.mark.parametrize("question, intent", [
    ("Can you list every kind of borrowing the page says is eligible for protection?", "general"),
    ("Who is eligible to join Dupaco?", "eligibility"),
    ("Am I eligible for membership if I work in Dubuque?", "eligibility"),
])
def test_eligible_means_membership_only_with_joining_words(question, intent):
    assert parse_question(question).intent == intent


@pytest.mark.parametrize("question, name", [
    ("Maple Street branch - what's the street address?", "Maple Street"),
    ("Which Dupaco branch is closest to my home?", None),
    ("Any Dubuque branch open on Saturday?", None),
    ("What are the hours at the Oak Ridge branch?", "Oak Ridge"),
])
def test_a_branch_named_first_in_the_question(question, name):
    assert parse_question(question).named_branch == name


def test_a_stand_alone_atm_has_its_own_address():
    page_md = ("# Locations\n\nDupaco Branch\n\n12 Maple St., Springfield, IA, 52099\n\n"
               "### Dupaco ATM @ Corner Grocer\n\nSurcharge-Free ATM\n\n77 Elm Rd., Springfield, IA, 52099\n")
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28", pages=[page("/contact", page_md)]))
    a = k.answer("Where's the Dupaco ATM at Corner Grocer? Just need the address.")
    assert "77 Elm Rd." in a.text and "12 Maple" not in a.text
    assert "77 Elm" not in k.answer("What's the address of the Maple Street branch?").text


def test_a_line_cut_from_the_middle_of_a_sentence_is_not_an_answer():
    pdf = ("# Business checklist\n\nupdate your contact information, with upgrade options to purchase inside the app "
           "and more information\n\nKeep a list of every supplier and every contract you sign each year.\n")
    filler = [page(f"/blog/{i}", f"# Post {i}\n\nA story about saving money for a trip number {i}, with tips on "
                                  f"budgeting, planning ahead and avoiding fees while you travel.\n") for i in range(30)]
    k = TemporalKnowledgeBase()
    k.ingest(NS(snapshot_id="05_2026-09-28", taken_on="2026-09-28",
                pages=[page("/hubfs/checklist.pdf", pdf)] + filler))
    a = k.answer("How can I update my contact information?")
    assert "upgrade options" not in a.text
