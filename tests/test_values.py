"""Phase 2B tests: value parsing. Every input below is copied from a real table cell (docs/RULES.md)."""
# The parsers return None when a cell holds no value. These tests read attributes straight off the
# result on purpose: if a parser wrongly returned None, the test fails with an error, which is what we want.
# pyright: reportOptionalMemberAccess=false
from tkb.values import (Range, all_percents, is_empty, parse_money, parse_money_range, parse_percent,
                        parse_term_months, parse_year_range, strip_footnotes)


# ----------------------------------------------------------------------------- footnotes (R7, E11)
def test_footnotes_glued_to_values_are_removed():
    assert strip_footnotes("5.39% APR1") == "5.39% APR"
    assert strip_footnotes("3.90%1") == "3.90%"
    assert strip_footnotes("Annual Percentage Yield (APY)1") == "Annual Percentage Yield (APY)"
    assert strip_footnotes("Annual Percentage Rate (As Low As) 1") == "Annual Percentage Rate (As Low As)"


def test_real_numbers_after_a_space_are_not_footnotes():
    assert strip_footnotes("5.00% 12 months") == "5.00% 12 months"
    assert strip_footnotes("(HELOC) 15 years") == "(HELOC) 15 years"


def test_empty_cells_are_not_zero():
    for cell in ["N/A", "None", "-", "", "  ", None]:
        assert is_empty(cell)
        assert parse_percent(cell, bare_ok=True) is None
    assert not is_empty("0.00%")
    assert parse_percent("0.00%").low == 0.0          # a real zero rate IS a value


# ----------------------------------------------------------------------------- percents
def test_single_percent_with_footnote_E11():
    p = parse_percent("5.39% APR1")
    assert (p.low, p.high, p.text, p.is_range) == (5.39, 5.39, "5.39%", False)
    assert parse_percent("3.90%1").text == "3.90%"
    assert parse_percent("6.037%").low == 6.037       # three decimals (mortgage APR)


def test_bare_number_only_under_a_rate_header_E18():
    assert parse_percent("7.29") is None              # not a rate unless the header says so
    assert parse_percent("7.29", bare_ok=True).low == 7.29
    assert parse_percent("10.04", bare_ok=True).text == "10.04%"


def test_percent_range_E18():
    p = parse_percent("12.50% - 19.50% APR1")
    assert (p.low, p.high, p.is_range) == (12.5, 19.5, True)
    assert p.text == "12.50% - 19.50%"


def test_first_rate_wins_and_all_rates_are_available():
    cell = "2.90% APR for 6 mos. (then the rate becomes 12.50% - 19.50% APR)2"
    assert parse_percent(cell).low == 2.90
    assert [p.low for p in all_percents(cell)] == [2.90, 12.50, 19.50]


# ----------------------------------------------------------------------------- money (E18)
def test_money_values():
    assert parse_money("$10,000") == 10000.0
    assert parse_money("$ 575.73") == 575.73
    assert parse_money("$832750") == 832750.0
    assert parse_money("None") is None


def test_money_ranges_in_every_format_seen():
    assert parse_money_range("$10,000-24,999") == Range(10000, 24999)          # 2nd end without $
    assert parse_money_range("$25,000 - $99,999.99") == Range(25000, 99999.99)
    assert parse_money_range("$0.01 - $1,000,000") == Range(0.01, 1000000)
    assert parse_money_range("$100,000+") == Range(100000, None)               # open upwards
    assert parse_money_range("$832750 or less") == Range(None, 832750)         # open downwards
    assert parse_money_range("Purchase: 30-Year Fixed Conventional $832,750 or less") == Range(None, 832750)
    assert parse_money_range("Up to $50,000") == Range(None, 50000)


def test_range_contains_and_overlap_R6():
    tier = parse_money_range("$10,000 - $24,999.99")
    assert tier.contains(15000) and not tier.contains(25000)
    assert Range(100000, None).contains(5_000_000)
    old, new_top, new_mid = Range(2023, 2026), Range(2024, 2027), Range(2021, 2023)
    assert old.overlap(new_top) == 3 and old.overlap(new_mid) == 1   # pair old 2023-26 with new 2024-27


# ----------------------------------------------------------------------------- model years (R6, E1, E16)
def test_year_ranges_including_reversed_and_open_ended():
    assert parse_year_range("2024-27 Model Year") == Range(2024, 2027)
    assert parse_year_range("2023-26 Model Year") == Range(2023, 2026)
    assert parse_year_range("Model Year 2026-23") == Range(2023, 2026)      # reversed (ATV)
    assert parse_year_range("Model Year 2019-18") == Range(2018, 2019)
    assert parse_year_range("2016 Model Year (and older)") == Range(None, 2016)
    assert parse_year_range("2021-2023 Model Year") == Range(2021, 2023)


def test_tier_shift_2023_car_moves_tier_E1():
    may_top, sep_mid = parse_year_range("2023-26 Model Year"), parse_year_range("2021-23 Model Year")
    assert may_top.contains(2023) and sep_mid.contains(2023)
    assert not parse_year_range("2024-27 Model Year").contains(2023)


# ----------------------------------------------------------------------------- terms
def test_terms_in_months_and_years():
    assert parse_term_months("60 Months") == 60
    assert parse_term_months("6 mos.") == 6
    assert parse_term_months("5 Years") == 60
    assert parse_term_months("Purchase: 30-Year Fixed Conventional") == 360
    assert parse_term_months("10 Month Fixed Jumbo Certificate Special") == 10
    assert parse_term_months("Roth: 60 Months") == 60


def test_model_is_not_a_month_regression():
    # Bug found while running the parser over every cell: "26 Mo(del)" was read as 26 months.
    assert parse_term_months("2023-26 Model Year") is None
    assert parse_term_months("2016 Model Year (and older)") is None
