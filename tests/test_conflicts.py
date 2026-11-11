"""Phase 5 tests: conflicts() on a miniature Dupaco site, scored with the harness's own score_conflicts."""
from types import SimpleNamespace as NS

import pytest

from tkb.system import TemporalKnowledgeBase

D = "https://www.dupaco.com"


def auto_table(rows, effective):
    body = "\n".join(f"| {label} | {term} Months | {rate}% APR1 |" for label, term, rate in rows)
    return (f"Auto & Motorcycle Loans\n\n| Loan Program | Term | Annual Percentage Rate (As Low As) 1 |\n"
            f"| --- | --- | --- |\n{body}\n\nRates are effective as of {effective}.\n")


def share_table(mid_rate, mid_apy, effective):
    return ("Share Savings\n\n| Balance | Dividend Rate | Annual Percentage Yield (APY) |\n| --- | --- | --- |\n"
            f"| $25,000+ | 0.20% | 0.20% |\n| $10,000 - $24,999.99 | {mid_rate} | {mid_apy} |\n\n"
            f"Rates are effective as of {effective}.\n")


def press(date, n):
    return (f"{date}\n\n# Release {date}\n\nBody text of the release.\n\n###\n\n"
            f"**ABOUT DUPACO** It has over 600 employees and {n} branch office locations.\n")


RATES = auto_table([("2024-27 Model Year", 60, "5.39"), ("2021-23 Model Year", 60, "5.64"),
                    ("2024-27 Model Year", 84, "5.59")], "08/31/2026")
CALC_STALE = auto_table([("2024-27 Model Year", 60, "5.34"), ("2021-23 Model Year", 60, "5.59"),
                         ("2024-27 Model Year", 84, "5.54")], "1/1/2026")
MORTGAGE = ("Home Loans\n\n| Program | Rate | Points | APR |\n| --- | --- | --- | --- |\n"
            "| Purchase: 30-Year Fixed Conventional $100,000 or less | 7.125% | 0.00% | 7.27% |\n"
            "| Purchase: 30-Year Fixed Conventional $300,000 or less | 7.250% | 0.00% | 7.32% |\n\n"
            "Rates are effective as of 09/25/2026.\n")
GUIDANCE_STALE = (MORTGAGE.replace("7.125%", "5.750%").replace("7.27%", "5.884%").replace("7.32%", "6.061%")
                  .replace("09/25/2026", "04/22/2026"))


def page(path, markdown, fetched="2026-09-28T03:00:00Z"):
    return NS(url=D + path, title=path, markdown=markdown, fetched_at=fetched)


def build(*crawls):
    k = TemporalKnowledgeBase()
    for sid, pages in crawls:
        k.ingest(NS(snapshot_id=sid, taken_on=sid[3:13], pages=pages))
    return k


@pytest.fixture(scope="module")
def kb():
    may = [page("/rates", RATES.replace("5.39%", "5.19%").replace("08/31/2026", "05/01/2026"), "2026-05-12"),
           page("/business/savings-accounts", share_table("0.15%", "0.15%", "06/02/2026"), "2026-05-12")]
    sept = [page("/rates", RATES), page("/calculators/vehicle-affordability", CALC_STALE),
            page("/personal/loans/home-loans", MORTGAGE), page("/homebuying-guidance", GUIDANCE_STALE),
            page("/business/savings-accounts", share_table("0.15%", "0.15%", "06/02/2026")),
            page("/business-rates", share_table("0.20%", "0.15%", "06/02/2026")),     # typo: rate above APY
            page("/newsroom/old", press("June 07, 2022", 19)),
            page("/newsroom/a", press("March 17, 2026", 23)),
            page("/newsroom/b", press("May 05, 2026", 22))]
    return build(("01_2026-05-12", may), ("05_2026-09-28", sept))


def by_topic(kb, word):
    hits = [c for c in kb.conflicts() if word in c.topic]
    assert len(hits) == 1, [c.topic for c in kb.conflicts()]
    return hits[0]


def test_stale_calculator_is_one_conflict_per_term_resolved_to_the_rate_table(kb):
    c = by_topic(kb, "60-month auto loan")
    assert c.values[:2] == ["5.64%", "5.39%"] and {"5.34%", "5.59%"} <= set(c.values)   # winners first, tiers merged
    assert "5.39% APR" in c.resolution and "/rates" in c.resolution and "5.34" not in c.resolution
    assert "vehicle-affordability" in c.reason and "effective 2026-08-31" in c.reason
    assert {s.url for s in c.sources} >= {D + "/rates", D + "/calculators/vehicle-affordability"}
    assert by_topic(kb, "84-month auto loan").values == ["5.59%", "5.54%"]


def test_rate_and_apr_of_a_stale_guidance_page_share_one_topic(kb):
    c = by_topic(kb, "30-year (360-month) mortgage (purchase)")
    assert "rate and APR" in c.topic
    assert {"7.27%", "7.32%", "5.884%", "6.061%", "5.750%"} <= set(c.values)
    assert "7.125% rate" in c.resolution and "7.27% APR" in c.resolution


def test_an_impossible_row_loses_as_a_typo_R25(kb):
    c = by_topic(kb, "business Share Savings")
    assert c.values == ["0.15%", "0.20%"] and c.resolution.startswith("0.15% dividend rate")
    assert "typo" in c.reason


def test_prose_newest_publication_wins_and_old_history_is_left_out_R4(kb):
    c = by_topic(kb, "branch count")
    assert c.values == ["22 branches", "23 branches"]          # 19 (2022) is history, outside the window
    assert c.resolution.startswith("22 branches")


def test_history_tiers_and_equal_values_are_not_conflicts_F1_F2_E19():
    # crawl 01 -> 05: the rate changed, no page left behind; two tiers differ; the same value on two pages
    k = build(("01_2026-05-12", [page("/rates", RATES.replace("5.39%", "5.19%"), "2026-05-12")]),
              ("05_2026-09-28", [page("/rates", RATES), page("/calculators/vehicle-affordability", RATES)]))
    assert k.conflicts() == []


def test_matches_the_harness_scorer_and_is_deterministic(kb):
    score_conflicts = pytest.importorskip("scoring").score_conflicts   # harness/scoring.py (kit, not public)
    gold = [{"id": "g1", "topic_keywords": ["60-month", "auto"], "values": ["5.34%", "5.39%"], "correct_value": "5.39%"},
            {"id": "g2", "topic_keywords": ["30-year", "mortgage"], "values": ["6.061%", "7.32%"],
             "correct_value": "7.32%"},
            {"id": "g3", "topic_keywords": ["branch"], "values": ["22", "23 branch"], "correct_value": "22"}]
    s = score_conflicts(gold, kb.conflicts())
    assert s["matched"] == 3 and s["resolution_accuracy"] == 1.0
    assert s["submitted"] == 5                                  # 60m, 84m, mortgage, share savings, branches
    assert [c.topic for c in kb.conflicts()] == [c.topic for c in kb.conflicts()]


def test_every_crawls_evidence_is_kept_not_overwritten():
    """Phase 6 fix 1: crawl 01 and crawl 05 both show the stale calculator, with different winning rates. Both
    records survive with their own dates and sources; only the newest decides values + resolution. A conflict seen
    only in crawl 01 (gone by 05) is still reported, dated."""
    may = [page("/rates", RATES.replace("5.39%", "5.19%").replace("08/31/2026", "05/01/2026"), "2026-05-12T10:00:00Z"),
           page("/calculators/vehicle-affordability", CALC_STALE, "2026-05-12T10:00:00Z"),
           page("/business/savings-accounts", share_table("0.15%", "0.15%", "05/01/2026"), "2026-05-12T10:00:00Z"),
           page("/business-rates", share_table("0.20%", "0.15%", "05/01/2026"), "2026-05-12T10:00:00Z")]
    sept = [page("/rates", RATES), page("/calculators/vehicle-affordability", CALC_STALE),
            page("/business/savings-accounts", share_table("0.15%", "0.15%", "05/01/2026"))]    # typo page fixed
    k = build(("01_2026-05-12", may), ("05_2026-09-28", sept))
    rec = next(r for r in k.conflict_records() if r.name == "60-month auto loan APR")
    assert [(ev.snapshot_id, ev.taken_on) for ev in rec.crawls] == [("01_2026-05-12", "2026-05-12"),
                                                                   ("05_2026-09-28", "2026-09-28")]
    assert "5.19%" in rec.crawls[0].winning_values and "5.39%" in rec.crawls[1].winning_values
    assert rec.crawls[0].stale_pages == ["/calculators/vehicle-affordability (effective 2026-01-01)"]
    c = rec.to_conflict()
    assert "5.19%" not in c.values and "5.39% APR" in c.resolution             # newest decides what is scored
    assert "Earlier: 01 (2026-05-12): winning" in c.reason and "5.19%" in c.reason
    assert {s.snapshot_id for s in c.sources} == {"01_2026-05-12", "05_2026-09-28"}
    gone = next(r for r in k.conflict_records() if r.name == "business Share Savings dividend rate")
    assert [ev.snapshot_id for ev in gone.crawls] == ["01_2026-05-12"]          # only seen in May, still kept
    assert "as of snapshot 01_2026-05-12 (2026-05-12)" in gone.to_conflict().reason


def test_a_conflict_that_disappears_and_returns_keeps_both_episodes():
    """Stale calculator in crawl 01, fixed in crawl 02, stale again in crawl 05: two separate, dated episodes."""
    stale = page("/calculators/vehicle-affordability", CALC_STALE, "2026-05-12T10:00:00Z")
    fixed = page("/calculators/vehicle-affordability", RATES.replace("08/31/2026", "05/01/2026"), "2026-05-19T10:00:00Z")
    k = build(("01_2026-05-12", [page("/rates", RATES.replace("08/31/2026", "05/01/2026"), "2026-05-12T10:00:00Z"), stale]),
              ("02_2026-05-19", [page("/rates", RATES.replace("08/31/2026", "05/01/2026"), "2026-05-19T10:00:00Z"), fixed]),
              ("05_2026-09-28", [page("/rates", RATES), page("/calculators/vehicle-affordability", CALC_STALE)]))
    rec = next(r for r in k.conflict_records() if r.name == "60-month auto loan APR")
    assert [ev.snapshot_id for ev in rec.crawls] == ["01_2026-05-12", "05_2026-09-28"]     # not in 02
    assert "Earlier: 01 (2026-05-12)" in rec.to_conflict().reason


def test_conflicts_before_ingest_is_empty():
    assert TemporalKnowledgeBase().conflicts() == [] and TemporalKnowledgeBase().conflict_records() == []
