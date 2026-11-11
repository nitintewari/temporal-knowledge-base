"""Phase 2C tests: tables -> facts. Each page below is a miniature copy of a real page (docs/RULES.md)."""
# Tests read attributes straight off results on purpose: a wrong None should fail the test.
# pyright: reportOptionalMemberAccess=false
from types import SimpleNamespace as NS

from tkb.facts import extract_facts, find_product
from tkb.normalize import clean_text
from tkb.store import VersionStore


def one(facts, **want):
    """The single fact matching every field in `want` (fails loudly if there are 0 or several)."""
    hits = [f for f in facts if all(getattr(f, k) == v for k, v in want.items())]
    assert len(hits) == 1, f"expected 1 match for {want}, got {len(hits)}"
    return hits[0]


AUTO = """Auto & Motorcycle Loans

| Loan Program | Term | Annual Percentage Rate (As Low As) 1 |
| --- | --- | --- |
| 2024\u201327 Model Year | 60 Months | 5.39% APR1 |
| 2021-23 Model Year | 84 Months | 6.04% APR1 |

Rates are effective as of 08/31/2026 and are subject to change without notice.
"""


def test_auto_rows_become_keyed_dated_facts_E1():
    facts = extract_facts(AUTO, "https://www.dupaco.com/rates", "rate_sheet")
    f = one(facts, term_months=60)
    assert (f.product, f.attribute, f.value.text, f.effective) == ("auto loan", "apr", "5.39%", "2026-08-31")
    assert f.tier_kind == "model_year" and f.tier.contains(2025) and not f.tier.contains(2023)
    assert f.evidence.startswith("2024-27 Model Year")         # provenance: the row as written


def test_cell_measure_overrides_a_wrong_header():
    # The vehicle-affordability calculator heads its auto table "Annual Percentage Yield",
    # but its cells read "5.34% APR". The stale value must still compete as an APR.
    page = ("Auto Loan Rates\n\n| Account Type | Balance Tier | Annual Percentage Yield |\n| --- | --- | --- |\n"
            "| 2023-26 Model Year | 60 Months | 5.34% APR |\n\nRates are effective as of 1/1/2026.\n")
    f = one(extract_facts(page), term_months=60)
    assert (f.product, f.attribute, f.value.text) == ("auto loan", "apr", "5.34%")


def test_atv_table_is_not_an_auto_loan_E16():
    page = ("ATV, Snowmobile & Jet Ski Loans" + "\n" * 10 +
            "| Loan Program | Term | Annual Percentage Rate (As Low As) 1 |\n| --- | --- | --- |\n"
            "| Model Year 2026-23 | 36 Months | 8.34% APR |\n")
    f = one(extract_facts(page), term_months=36)
    assert f.product == "atv loan"
    assert f.tier.contains(2024)                                 # reversed range "2026-23"


def test_certificates_implied_by_term_rows_under_regular_or_special():
    page = ("Special\n\n| Term | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |\n"
            "| --- | --- | --- | --- |\n| 10 Month Fixed Jumbo Certificate Special | 3.95% | 4.00%1 | $100,000.00 |\n\n"
            "Regular\n\n| Term | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |\n"
            "| --- | --- | --- | --- |\n| 12 Month | 2.47% | 2.50% | $500.00 |\n")
    facts = extract_facts(page)
    jumbo = one(facts, term_months=10, attribute="apy")
    assert (jumbo.product, jumbo.flags, jumbo.value.text) == ("certificate", ("jumbo", "special"), "4.00%")
    assert one(facts, term_months=10, attribute="dividend_rate").value.text == "3.95%"   # rate vs APY (R12)
    regular = one(facts, term_months=12, attribute="apy")
    assert (regular.product, regular.flags) == ("certificate", ())


def test_ira_prefixes_are_separate_keys_E19():
    page = ("Special IRAs\n\n| IRA Type | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |\n"
            "| --- | --- | --- | --- |\n| Roth: 10 Month Fixed Jumbo Special | 3.95% | 4.00%1 | $100,000.00 |\n"
            "| Traditional: 10 Month Fixed Jumbo Special | 3.85% | 3.90%1 | $100,000.00 |\n")
    facts = [f for f in extract_facts(page) if f.attribute == "apy"]
    roth, trad = one(facts, account="roth"), one(facts, account="traditional")
    assert roth.product == trad.product == "ira certificate"
    assert (roth.value.text, trad.value.text) == ("4.00%", "3.90%")
    assert roth.key() != trad.key()                              # never compared as the same fact


def test_card_rows_are_attributes_not_tiers_E25():
    page = ("Platinum Visa\n\n| Platinum Credit Card | Annual Percentage Rate (APR) |\n| --- | --- |\n"
            "| Platinum Visa Rate | 12.50% - 19.50% APR1 |\n"
            "| Introductory Balance Transfer Rate | 2.90% APR for 6 mos. (then the rate becomes 12.50% - 19.50% APR)2 |\n")
    facts = extract_facts(page)
    standard, intro = one(facts, flags=()), one(facts, flags=("intro",))
    assert standard.product == intro.product == "platinum visa"
    assert (standard.value.low, standard.value.high) == (12.5, 19.5)
    assert intro.value.text == "2.90%"


def test_mortgage_purpose_term_and_nested_amount_tiers_E3():
    page = ("Home Loans\n\n| Program | Rate | Points | APR | *Payment Example |\n| --- | --- | --- | --- | --- |\n"
            "| Purchase: 30-Year Fixed Conventional $300,000 or less | 7.250% | 0.00% | 7.32% | $2,046.53 |\n"
            "| Purchase: 30-Year Fixed Conventional $100,000 or less | 7.125% | 0.00% | 7.27% | $673.72 |\n"
            "| Refinance: 15-Year Fixed Conventional | 6.750% | 0.00% | 6.88% | $884.91 |\n\n"
            "Rates are effective as of 09/25/2026.\n")
    facts = extract_facts(page)
    assert {f.attribute for f in facts} == {"rate", "apr"}            # points and payments are not facts (R16)
    small = [f for f in facts if f.tier and f.tier.high == 100000]
    assert {(f.attribute, f.value.text) for f in small} == {("rate", "7.125%"), ("apr", "7.27%")}
    assert all(f.purpose == "purchase" and f.term_months == 360 for f in small)
    refi = one(facts, purpose="refinance", attribute="rate")
    assert refi.term_months == 180 and refi.tier is None


def test_bare_rates_and_loan_amount_tiers_E18():
    page = ("Boat & RV Loans\n\n| Loan Amount | Term | Annual Percentage Rate (As Low As) 1 |\n| --- | --- | --- |\n"
            "| $10,000-24,999 | 36 Months | 7.29 |\n| $40,000+ | 180 Months | 10.04 |\n")
    facts = extract_facts(page)
    small = one(facts, term_months=36)
    assert (small.product, small.value.text, small.tier_kind) == ("boat & rv loan", "7.29%", "loan_amount")
    assert small.tier.contains(15000)
    assert one(facts, term_months=180).tier.high is None             # "$40,000+" is open-ended


def test_business_segment_and_heading_above_a_layout_box():
    page = ("Business 1st Rate Checking Account\n\nReady to put your business\u2019 cash to work?\n\n"
            "|     |     |\n| --- | --- |\n| - No initial deposit requirements<br> - Earn a rate |  |\n\n"
            "| Balance | Dividend Rate | Annual Percentage Yield (APY)1 | Min. to Earn | Min. to Open |\n"
            "| --- | --- | --- | --- | --- |\n| $5,000 - $24,999.99 | 2.47% | 2.50% | $5,000 | None |\n")
    f = one(extract_facts(page), attribute="apy")
    assert (f.product, f.segment, f.tier_kind) == ("1st rate checking", "business", "balance")


def test_unknown_product_produces_no_facts_R16():
    page = ("| Balance | Dividend Rate | Annual Percentage Yield (APY)2 |\n| --- | --- | --- |\n"
            "| $5,000 - $24,999.99 | 2.96% | 3.00% |\n")
    assert extract_facts(page) == []                                 # never guess a product


def test_vocabulary_handles_curly_apostrophes_and_specific_names_first():
    assert find_product([clean_text("Investor\u2019s Choice")]) == "investor's choice money market"
    assert find_product(["Home Equity Line of Credit (HELOC)"]) == "heloc"
    assert find_product(["Home Equity Loan"]) == "home equity loan"
    assert find_product(["Saving tips for kids"]) is None


def test_store_extracts_facts_once_per_distinct_page_version():
    page = NS(url="https://www.dupaco.com/rates", title="Rates", markdown=AUTO, fetched_at="2026-09-01")
    store = VersionStore()
    store.add_snapshot(NS(snapshot_id="04", taken_on="2026-09-01", pages=[page]))
    store.add_snapshot(NS(snapshot_id="05", taken_on="2026-09-28", pages=[page]))   # unchanged page
    [version] = store.history[page.url]                              # parsed once, shared by both crawls
    assert len(version.facts) == 2
    assert [f.value.text for f, _ in store.facts("2026-09-05")] == ["5.39%", "6.04%"]
    assert store.facts("2025-01-01")[0][1].version is version        # (fact, observation of that version)


def test_business_segment_comes_from_the_url_when_headings_omit_it():
    # /business-rates in snapshot 01 heads its table "Share Savings"; snapshot 05 says "Business Share Savings".
    # Using the URL keeps the key stable across crawls, so no fake personal-vs-business conflicts.
    page = ("Share Savings\n\n| Account Type | Balance Tier | Dividend Rate | Annual Percentage Yield (APY)1 |\n"
            "| --- | --- | --- | --- |\n| Share Savings | $25,000+ | 0.20% | 0.20%1 |\n")
    assert one(extract_facts(page, "https://www.dupaco.com/business-rates"), attribute="apy").segment == "business"
    assert one(extract_facts(page, "https://www.dupaco.com/rates"), attribute="apy").segment == "personal"
