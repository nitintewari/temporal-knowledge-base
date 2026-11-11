"""Phase 2A tests: text cleaning and the table parser.

Every test is a small copy of a real situation found in the data study (docs/RULES.md, E-numbers).
"""
from tkb.normalize import clean_text
from tkb.tables import parse_tables, split_row, to_iso


# ----------------------------------------------------------------------------- normalize
def test_invisible_spaces_become_normal_spaces_E15():
    assert clean_text("84\xa0Months") == "84 Months"
    assert clean_text("2023\u202f26") == "2023 26"
    assert clean_text("zero\u200bwidth") == "zerowidth"


def test_dash_variants_become_hyphens_E1():
    assert clean_text("2023\u201326 Model Year") == "2023-26 Model Year"   # en-dash
    assert clean_text("$0 \u2014 $99") == "$0 - $99"                      # em-dash


def test_escaped_line_breaks_become_spaces_E21():
    raw = "without notice.\\r\\n\\r\\nSavings Rates: Dividends"
    assert clean_text(raw) == "without notice. Savings Rates: Dividends"


def test_html_breaks_markdown_escapes_and_entities():
    assert clean_text("a<br> <br/>b") == "a   b"
    assert clean_text("\\*Payment Example") == "*Payment Example"
    assert clean_text("2021&amp;#45;22") == "2021-22"          # double-escaped entity


def test_clean_text_handles_empty_input():
    assert clean_text("") == ""
    assert clean_text(None) == ""


# ----------------------------------------------------------------------------- rows and dates
def test_split_row_keeps_escaped_pipe_inside_a_cell():
    assert split_row("| a | b \\| c |") == ["a", "b | c"]
    assert split_row("| **Bold** |  spaced   out |") == ["Bold", "spaced out"]


def test_to_iso_handles_two_digit_years_and_bad_dates():
    assert to_iso("1", "1", "26") == "2026-01-01"
    assert to_iso("08", "31", "2026") == "2026-08-31"
    assert to_iso("2", "30", "2026") is None                    # impossible date -> None, not a crash


# ----------------------------------------------------------------------------- parse_tables
AUTO_PAGE = """
Auto & Motorcycle Loans

| Loan Program | Term | Annual Percentage Rate (As Low As) 1 |
| --- | --- | --- |
| 2024\u201327 Model Year | 60\xa0Months | 5.39% APR1 |
| 2021-23 Model Year | 60 Months | 5.64% APR1 |

Rates are effective as of 08/31/2026 and are subject to change without notice.
"""


def test_basic_table_header_rows_context_and_date_E1_E15():
    [t] = parse_tables(AUTO_PAGE)
    assert t.header == ["Loan Program", "Term", "Annual Percentage Rate (As Low As) 1"]
    assert t.rows[0] == ["2024-27 Model Year", "60 Months", "5.39% APR1"]   # cleaned cells
    assert t.context[0] == "Auto & Motorcycle Loans"
    assert t.effective == "2026-08-31"


def test_heading_far_above_with_blank_lines_E16():
    page = "ATV, Snowmobile & Jet Ski Loans" + "\n" * 10 + (
        "| Loan Program | Term | APR |\n| --- | --- | --- |\n| Model Year 2026-23 | 36 Months | 8.34% APR |\n"
    )
    [t] = parse_tables(page)
    assert t.context[0] == "ATV, Snowmobile & Jet Ski Loans"


def test_table_never_borrows_the_next_tables_date_E17():
    page = (
        "Free Checking\n\n| Balance | APY |\n| --- | --- |\n| N/A | N/A |\n\n"
        + "filler\n" * 5
        + "1st Rate Checking\n\n| Balance | APY |\n| --- | --- |\n| $5,000 - $24,999.99 | 3.00% |\n\n"
        + "Rates are effective as of 07/01/2025; they may change.\n"
    )
    first, second = parse_tables(page)
    assert first.effective is None            # its only nearby date belongs to the second table
    assert second.effective == "2025-07-01"


def test_context_does_not_cross_the_previous_table():
    page = (
        "Share Savings\n\n| Tier | APY |\n| --- | --- |\n| $25,000+ | 0.20% |\n\n"
        "Rates are effective as of 06/15/2026.\n\n"
        "| Tier | APY |\n| --- | --- |\n| $0.01 - $1,000,000 | 2.25% |\n"
    )
    first, second = parse_tables(page)
    assert first.context == ["Share Savings"]
    assert second.context == []               # the date line belongs to the table above, not a heading


def test_caption_date_wins_over_footnote_date_E21():
    page = (
        "| Account Type | Balance Tier | Dividend Rate | Annual Percentage Yield (APY)1 |\n"
        "| --- | --- | --- | --- |\n| Share Savings | $25,000+ | 0.20% | 0.20%1 |\n\n"
        "Rates are effective as of 06/15/2026; they may change without notice.\n\n"
        "1Rates are effective as of 03/03/2026; they may change without notice.\n"
    )
    [t] = parse_tables(page)
    assert t.effective == "2026-06-15"
    assert t.effective_all == ["2026-06-15", "2026-03-03"]   # both kept, so two-date tables can be logged


def test_footnote_date_is_used_when_it_is_the_only_date_E21():
    page = "| Term | APY |\n| --- | --- |\n| 12 Months | 3.00% |\n\n1Rates are effective as of 03/03/2026.\n"
    [t] = parse_tables(page)
    assert t.effective == "2026-03-03"


def test_empty_header_row_is_replaced_by_first_data_row():
    page = "|  |  |\n| --- | --- |\n| Session Type | Value |\n| One-Day Session | $3,000 |\n"
    [t] = parse_tables(page)
    assert t.header == ["Session Type", "Value"]
    assert t.rows == [["One-Day Session", "$3,000"]]


def test_page_without_tables_and_header_only_table():
    assert parse_tables("Just a paragraph about savings.") == []
    [t] = parse_tables("| Name | Amount |\n| --- | --- |\n")
    assert t.rows == []
