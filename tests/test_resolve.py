"""Phase 2D tests: the resolver. Each page below is a miniature copy of a real page (docs/RULES.md)."""
# pyright: reportOptionalMemberAccess=false
from types import SimpleNamespace as NS

import pytest

from tkb.classify import page_type
from tkb.facts import extract_facts
from tkb.resolve import (CONSISTENT_ROW_OVER_INCONSISTENT, CURRENT, EXPLICIT_EFFECTIVE_DATE,
                         FRESHEST_COPY_OF_PAGE, OFFICIAL_RATE_TABLE_OVER_CALCULATOR, SUPERSEDED,
                         TIER_NOT_IN_NEWEST_TABLE, UNRESOLVED_TIE, changes, resolve_crawl)
from tkb.store import VersionStore

D = "https://www.dupaco.com"


def page(path: str, markdown: str, fetched: str = "2026-09-28T03:00:00Z"):
    """A page version as the resolver sees it: fetch time + extracted facts."""
    url = D + path
    return url, NS(fetched_at=fetched, facts=extract_facts(markdown, url, page_type(url)))


def crawl(*pages, snapshot_id: str = "05"):
    return resolve_crawl(snapshot_id, dict(pages))


def auto_table(rows: list, effective: str, heading: str = "Auto & Motorcycle Loans") -> str:
    body = "\n".join(f"| {label} | {term} Months | {rate}% APR1 |" for label, term, rate in rows)
    return (f"{heading}\n\n| Loan Program | Term | Annual Percentage Rate (As Low As) 1 |\n| --- | --- | --- |\n"
            f"{body}\n\nRates are effective as of {effective} and are subject to change without notice.\n")


RATES_05 = auto_table([("2024-27 Model Year", 60, "5.39"), ("2021-23 Model Year", 60, "5.64"),
                       ("2017-20 Model Year", 60, "6.34")], "08/31/2026")
CALC_STALE = auto_table([("2023–26 Model Year", 60, "5.34"), ("2021-22 Model Year", 60, "5.59"),
                         ("2017-20 Model Year", 60, "6.29")], "1/1/2026", heading="Auto Loan Rates")


def one(resolved, x=None, **want):
    hits = resolved.find(x=x, **want)
    assert len(hits) == 1, f"expected 1 resolution for {want} x={x}, got {len(hits)}"
    return hits[0]


# ----------------------------------------------------------------------------- R2 / R3
def test_newest_effective_date_wins_and_stale_copies_lose_E1():
    R = crawl(page("/rates", RATES_05), page("/calculators/vehicle-affordability", CALC_STALE),
              page("/switch-and-earn", CALC_STALE))
    r = one(R, x=2025, product="auto loan", term_months=60, attribute="apr")
    assert (r.value.text, r.winner.path, r.status) == ("5.39%", "/rates", CURRENT)
    assert sorted((l.candidate.path, l.candidate.fact.value.text, l.reason) for l in r.losers) == [
        ("/calculators/vehicle-affordability", "5.34%", EXPLICIT_EFFECTIVE_DATE),
        ("/switch-and-earn", "5.34%", EXPLICIT_EFFECTIVE_DATE)]


def test_date_beats_authority_a_trusted_page_with_an_old_table_loses_E17():
    # /personal/checking-accounts is a PRODUCT page, yet carried a mortgage table effective 10/22/2025.
    old = ("Home Loans\n\n| Program | Rate | APR |\n| --- | --- | --- |\n"
           "| Purchase: 30-Year Fixed Conventional $100,000 or less | 5.625% | 5.70% |\n\n"
           "Rates are effective as of 10/22/2025.\n")
    new = old.replace("5.625%", "7.125%").replace("5.70%", "7.27%").replace("10/22/2025", "09/25/2026")
    R = crawl(page("/personal/checking-accounts", old), page("/learn/master-your-money/homeownership", new))
    r = one(R, x=100000, product="mortgage", purpose="purchase", attribute="rate")
    assert r.value.text == "7.125%"                      # a BLOG page wins, because its table is newer
    assert r.losers[0].reason == EXPLICIT_EFFECTIVE_DATE


def test_authority_breaks_a_tie_on_the_same_date_R3():
    calc = RATES_05.replace("5.39%", "5.44%")
    R = crawl(page("/calculators/vehicle-affordability", calc), page("/rates", RATES_05))
    r = one(R, x=2025, product="auto loan", term_months=60)
    assert r.value.text == "5.39%"
    assert r.losers[0].reason == OFFICIAL_RATE_TABLE_OVER_CALCULATOR


def test_dated_table_beats_undated_table_R15():
    undated = RATES_05.split("Rates are effective")[0].replace("5.39%", "4.99%")
    R = crawl(page("/rates", undated), page("/calculators/vehicle-affordability", RATES_05))
    r = one(R, x=2025, product="auto loan", term_months=60)
    assert r.value.text == "5.39%" and r.losers[0].reason == EXPLICIT_EFFECTIVE_DATE


# ----------------------------------------------------------------------------- R17
def test_same_value_on_many_pages_and_dates_agrees_and_is_not_a_conflict_R17_E19():
    redated = RATES_05.replace("08/31/2026", "06/02/2026")          # same values, older date
    R = crawl(page("/rates", RATES_05), page("/personal/loans/auto-loans", RATES_05),
              page("/personal/savings-account", redated))
    r = one(R, x=2025, product="auto loan", term_months=60)
    assert not r.has_conflict and len(r.agree) == 2
    assert r.winner.fact.effective == "2026-08-31"                         # the newest table is the winner
    assert r.sources()[0] == r.winner.path                                  # winner first; Phase 3 picks citations
    assert set(r.sources()) == {"/rates", "/personal/loans/auto-loans", "/personal/savings-account"}


def test_values_are_compared_by_number_not_by_text():
    R = crawl(page("/rates", RATES_05), page("/switch-and-earn", RATES_05.replace("5.39%", "5.390%")))
    assert not one(R, x=2025, product="auto loan", term_months=60).has_conflict


# ----------------------------------------------------------------------------- tiers (R1, R6, R23)
def test_relabelled_tiers_pair_by_largest_overlap_E1():
    # "2023-26" overlaps "2024-27" by 3 years and "2021-23" by 1, so it is the old label of the TOP tier.
    R = crawl(page("/rates", RATES_05), page("/calculators/vehicle-affordability", CALC_STALE))
    top = one(R, x=2025, product="auto loan", term_months=60)
    assert [l.candidate.fact.value.text for l in top.losers] == ["5.34%"]
    middle = one(R, x=2022, product="auto loan", term_months=60)
    assert (middle.value.text, [l.candidate.fact.value.text for l in middle.losers]) == ("5.64%", ["5.59%"])
    # A 2023 car moved from the top tier to the middle tier in snapshot 05: the answer follows the NEW labels.
    assert one(R, x=2023, product="auto loan", term_months=60).value.text == "5.64%"


MORTGAGE = ("Home Loans\n\n| Program | Rate | Points | APR | *Payment Example |\n| --- | --- | --- | --- | --- |\n"
            "| Purchase: 30-Year Fixed Conventional $832750 or less | 7.250% | 0.00% | 7.29% | $5,680.00 |\n"
            "| Purchase: 30-Year Fixed Conventional $300,000 or less | 7.250% | 0.00% | 7.32% | $2,046.53 |\n"
            "| Purchase: 30-Year Fixed Conventional $100,000 or less | 7.125% | 0.00% | 7.27% | $673.72 |\n\n"
            "Rates are effective as of 09/25/2026.\n")


def test_nested_or_less_tiers_never_merge_and_the_narrowest_comes_first_R23_E26():
    stale = MORTGAGE.replace("7.125%", "5.750%").replace("09/25/2026", "04/22/2026")
    R = crawl(page("/personal/loans/home-loans", MORTGAGE), page("/homebuying-guidance", stale))
    hits = R.find(x=100000, product="mortgage", purpose="purchase", term_months=360, attribute="rate")
    assert [h.tier.high for h in hits] == [100000, 300000, 832750]    # one slot per row, narrowest first
    assert hits[0].value.text == "7.125%"
    assert [l.candidate.fact.value.text for l in hits[0].losers] == ["5.750%"]   # paired with the EQUAL tier
    assert [h.value.text for h in R.find(x=250000, product="mortgage", purpose="purchase", attribute="rate")] \
        == ["7.250%", "7.250%"]


def test_tier_dropped_by_the_newest_table_is_superseded_R6():
    # Snapshot 05: 84 months is no longer offered for 2017-20 cars, but a stale calculator still lists it.
    new = auto_table([("2024-27 Model Year", 84, "5.59"), ("2021-23 Model Year", 84, "6.04")], "08/31/2026")
    old = auto_table([("2023-26 Model Year", 84, "5.54"), ("2017-20 Model Year", 84, "6.49")], "1/1/2026")
    R = crawl(page("/rates", new), page("/calculators/vehicle-affordability", old))
    assert R.find(x=2019, product="auto loan", term_months=84) == []           # never borrow another tier
    [gone] = R.find(x=2019, product="auto loan", term_months=84, include_superseded=True)
    assert (gone.status, gone.status_reason, gone.value.text) == (SUPERSEDED, TIER_NOT_IN_NEWEST_TABLE, "6.49%")


def test_a_table_never_competes_with_itself_duplicate_tier_row():
    # /newcard-balancetransfer-lp lists "$100,000+" twice (the second row's minimum is $25,000: a typo).
    promo = ("1st Rate Checking\n\n| Balance | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |\n"
             "| --- | --- | --- | --- |\n| $100,000+ | 0.10% | 0.10% | $100,000 |\n"
             "| $100,000+ | 0.10% | 0.10% | $25,000 |\n\nRates are effective as of 07/01/2025.\n")
    rates = promo.replace("| $100,000+ | 0.10% | 0.10% | $25,000 |\n", "").replace("07/01/2025", "06/02/2026")
    R = crawl(page("/rates", rates), page("/newcard-balancetransfer-lp", promo))
    current = R.find(x=150000, product="1st rate checking", attribute="apy")
    assert len(current) == 1 and current[0].agree[0].path == "/newcard-balancetransfer-lp"
    dup = [r for r in R.find(x=150000, product="1st rate checking", attribute="apy", include_superseded=True)
           if r.status == SUPERSEDED]
    assert len(dup) == 1 and dup[0].winner.fact.row_index == 1


# ----------------------------------------------------------------------------- R13 / R25
def test_older_copy_under_a_url_variant_is_shadowed_R13_E14():
    stale = RATES_05.replace("5.39%", "5.19%").replace("08/31/2026", "05/01/2026")
    R = crawl(page("/personal/retirement", RATES_05, fetched="2026-08-27T13:00:00Z"),
              page("/personal/retirement#iracompare", stale, fetched="2026-06-15T10:00:00Z"))
    r = one(R, x=2025, product="auto loan", term_months=60)
    assert r.value.text == "5.39%" and not r.losers and not r.agree           # the variant never competes
    assert R.shadowed and {l.reason for l in R.shadowed} == {FRESHEST_COPY_OF_PAGE}


SHARE = ("Share Savings Account\n\n| Account Type | Balance Tier | Dividend Rate | Annual Percentage Yield (APY)1 |\n"
         "| --- | --- | --- | --- |\n| Share Savings | $10,000 - $24,999.99 | {rate} | 0.15% |\n\n"
         "Rates are effective as of 01/06/2026.\n")


def test_row_with_rate_above_apy_loses_a_tie_R25_E27():
    # Crawl 04: /business-rates "0.20% | 0.15%" (impossible) vs /business/savings-accounts "0.15% | 0.15%".
    R = crawl(page("/business-rates", SHARE.format(rate="0.20%"), fetched="2026-08-27T13:10:00Z"),
              page("/business/savings-accounts", SHARE.format(rate="0.15%"), fetched="2026-08-27T13:00:00Z"))
    r = one(R, x=15000, product="share savings", segment="business", attribute="dividend_rate")
    assert r.value.text == "0.15%" and r.losers[0].reason == CONSISTENT_ROW_OVER_INCONSISTENT
    apy = one(R, x=15000, product="share savings", segment="business", attribute="apy")
    assert not apy.has_conflict                                                # the APY cells agree


def test_nothing_separates_two_values_flags_a_tie_for_review():
    # Never seen in the five crawls (0 ties); if it happens the system still answers, deterministically,
    # and the reason code makes the case visible for Phase 5 instead of hiding a coin flip.
    R = crawl(page("/personal/loans/auto-loans", RATES_05),
              page("/personal/loans/auto-motorcycle-loans", RATES_05.replace("5.39%", "5.49%")))
    r = one(R, x=2025, product="auto loan", term_months=60)
    assert r.value.text == "5.39%" and r.losers[0].reason == UNRESOLVED_TIE


# ----------------------------------------------------------------------------- determinism, API
def test_result_does_not_depend_on_page_order():
    pages = [page("/rates", RATES_05), page("/calculators/vehicle-affordability", CALC_STALE),
             page("/switch-and-earn", CALC_STALE), page("/personal/loans/auto-loans", RATES_05)]

    def summary(R):
        return [(str(r.key), r.tier, r.value.text, r.winner.path, [c.path for c in r.agree],
                 [(l.candidate.path, l.reason) for l in r.losers]) for r in R.resolutions]
    assert summary(crawl(*pages)) == summary(crawl(*reversed(pages)))


def test_find_rejects_unknown_key_fields():
    with pytest.raises(ValueError):
        crawl(page("/rates", RATES_05)).find(prodcut="auto loan")


def test_changes_ignore_redating_and_pair_relabelled_tiers_R17_E20():
    may = auto_table([("2023-26 Model Year", 60, "5.19"), ("2021-22 Model Year", 60, "5.44")], "5/1/2026")
    june = may.replace("5/1/2026", "6/2/2026")                            # re-dated, same values
    sept = auto_table([("2024-27 Model Year", 60, "5.39"), ("2021-23 Model Year", 60, "5.44")], "08/31/2026")
    a, b, c = (crawl(page("/rates", m), snapshot_id=i) for i, m in (("01", may), ("03", june), ("05", sept)))
    assert changes(a, b) == []
    found = changes(b, c)
    assert [(x.old.value.text, x.new.value.text) for x in found] == [("5.19%", "5.39%")]   # middle tier unchanged


def test_store_resolves_every_crawl_at_ingest_and_follows_as_of():
    def snap(sid, day, md):
        return NS(snapshot_id=sid, taken_on=day,
                  pages=[NS(url=D + "/rates", title="Rates", markdown=md, fetched_at=day)])
    store = VersionStore()
    store.add_snapshot(snap("01", "2026-05-12", auto_table([("2023-26 Model Year", 60, "5.19")], "5/1/2026")))
    store.add_snapshot(snap("05", "2026-09-28", RATES_05))
    assert set(store.resolutions) == {"01", "05"}
    assert one(store.resolved("2026-05-31"), x=2025, product="auto loan").value.text == "5.19%"   # R5
    assert one(store.resolved(), x=2025, product="auto loan").value.text == "5.39%"
    assert VersionStore().resolved() is None
