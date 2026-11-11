# Edge-case checklist

Every known edge case, where it came from, and what covers it.
Status: ☑ handled + tested · ◐ partly handled · ☐ open (phase that will handle it).
Evidence (E#) and rules (R#) refer to docs/RULES.md. When a case is closed, update its row here.

## A. Scorer and harness (from reading harness/*.py)
| ID | Edge case | Handling | Covered by | Status |
|---|---|---|---|---|
| A1 | Any stale (`must_not_include`) value in the answer text zeroes the question | Only winning values in text; losing values in `conflict_note` (R8) | Phase 3 compose | ☑ test_answer `test_rate_answer_carries_the_winner_never_the_stale_copy_G1` |
| A2 | A refusal containing ANY digit fails `should_refuse` | Digit-free refusal text | test_phase0 `test_refusal_has_no_digits_and_is_flagged` | ☑ |
| A3 | Refusal detected by `confident=False` or phrases | Always `confident=False` when refusing | test_phase0 | ☑ |
| A4 | Non-harness Answer class is turned into `str(answer)` in the repeat check | `tkb/contract.py` reuses harness classes | test_phase0 `test_answer_is_the_harness_class` | ☑ |
| A5 | Consistency compares the SET of numbers across paraphrases and repeats | Deterministic templates, no incidental numbers | Phase 3 + 6 | ☑ paraphrase + repeat consistency 1.0 on every set; `test_same_question_same_answer_and_errors_become_refusals_G5` |
| A6 | Numbers compared by value: "3.90%" = "3.9%"; "$2" ≠ "$2.50" | Print values exactly as the site writes them (`Percent.text`) | Phase 2B `Percent.text` | ☑ values printed as written (`Percent.text`) |
| A7 | A bare number in a trap matches any unit | Never print unrelated numbers | Phase 3 | ☑ refusals carry no digits (`test_refusals_decline_plainly_and_contain_no_digits_G3`) |
| A8 | Sources matched on host + path only; extra sources cost nothing | Cite 2-4 relevant URLs | Phase 3 | ☑ topic page first, 2-3 sources (D9) |
| A9 | Crash or >60 s timeout scores 0 for that question | try/except around answer -> refusal | Phase 3 | ☑ errors -> refusal, logged + counted; strict in tests (`test_internal_errors_are_counted_and_raise_in_strict_mode`) |
| A10 | p95 latency > 2 s loses speed points | No network on the main path; LLM optional with timeout | Phase 3-4 | ☑ no network, no model; p95 ≤ 0.07 s (Python 3.9 and 3.11) |
| A11 | Conflicts scored by F1; one gold item per submitted conflict | Curated list, one entry per fact key | Phase 5 | ☑ one Conflict per topic (`test_stale_calculator_is_one_conflict_per_term_resolved_to_the_rate_table`) |
| A12 | Conflict match needs ≥2 gold values, or 1 value + topic keyword | Put all values exactly as written; descriptive topic | Phase 5 | ☑ values as written + descriptive topic (`test_matches_the_harness_scorer_and_is_deterministic`) |
| A13 | Graders use their own harness, clean Python 3.11, maybe no network/API key | Stdlib only; never read files ourselves | all phases | ☑ stdlib only; fresh-copy run on Python 3.9 and 3.11 (Phase 7) |
| A14 | Ingest limit 30 min | Parser runs a full crawl in ~0.1 s | Phase 2A check (tablestats) | ☑ |

## B. Data and parsing
| ID | Edge case | Evidence | Covered by | Status |
|---|---|---|---|---|
| B1 | Invisible spaces (non-breaking, narrow, zero-width) | E15 | test_tables `test_invisible_spaces_become_normal_spaces_E15` | ☑ |
| B2 | Dash variants (en/em dash vs hyphen) | E1, E15 | test_tables `test_dash_variants_become_hyphens_E1` | ☑ |
| B3 | Literal "\\r\\n" inside sentences | E21 | test_tables `test_escaped_line_breaks_become_spaces_E21` | ☑ |
| B4 | HTML `<br>`, markdown escapes, double-escaped entities | E18 | test_tables `test_html_breaks_markdown_escapes_and_entities` | ☑ |
| B5 | Escaped pipe inside a table cell | — | test_tables `test_split_row_keeps_escaped_pipe_inside_a_cell` | ☑ |
| B6 | Empty header row, real header in first data row | Phase 2A check | test_tables `test_empty_header_row_is_replaced_by_first_data_row` | ☑ |
| B7 | Product name far above the table, blank lines between | E16 | test_tables `test_heading_far_above_with_blank_lines_E16` | ☑ |
| B8 | Table must not borrow the next table's effective date | E17 | test_tables `test_table_never_borrows_the_next_tables_date_E17` | ☑ |
| B9 | Two dates after one table (caption + footnote) | E21 | test_tables `test_caption_date_wins_over_footnote_date_E21` | ☑ |
| B10 | Footnote date as the only date | Phase 2A check | test_tables `test_footnote_date_is_used_when_it_is_the_only_date_E21` | ☑ |
| B11 | Two-digit years and impossible dates | — | test_tables `test_to_iso_handles_two_digit_years_and_bad_dates` | ☑ |
| B12 | Footnote digits glued to values and headers ("5.39% APR1", "(APY)1") | E11 | test_values `test_footnotes_glued_to_values_are_removed` | ☑ |
| B13 | Real numbers after a space are not footnotes ("5.00% 12 months") | Phase 2B review | test_values `test_real_numbers_after_a_space_are_not_footnotes` | ☑ |
| B14 | "N/A", "None", "-" are no value, never zero | E18 | test_values `test_empty_cells_are_not_zero` | ☑ |
| B15 | Rates without "%" under a rate header ("7.29") | E18 | test_values `test_bare_number_only_under_a_rate_header_E18` | ☑ |
| B16 | Rate ranges ("12.50% - 19.50%") | E18 | test_values `test_percent_range_E18` | ☑ |
| B17 | Several rates in one cell (intro rate + later range) | E18 | test_values `test_first_rate_wins_and_all_rates_are_available` | ◐ first rate wins; intro rates flagged (`intro`) |
| B18 | Money tiers in every format ("$10,000-24,999", "$100,000+", "$832750 or less") | E18 | test_values `test_money_ranges_in_every_format_seen` | ☑ |
| B19 | Model-year ranges: 2-digit end, reversed, open-ended | E1, E16 | test_values `test_year_ranges_including_reversed_and_open_ended` | ☑ |
| B20 | Terms in months, "mos.", years, "30-Year" | E18 | test_values `test_terms_in_months_and_years` | ☑ |
| B21 | "Model" must not be read as months | Phase 2B bug | test_values `test_model_is_not_a_month_regression` | ☑ |
| B22 | Header defines column meaning; non-rate columns (Payment Example, Points, Min.) | E18, R16 | test_facts `test_mortgage_purpose_term_and_nested_amount_tiers_E3` | ☑ |
| B23 | Row label is the attribute, not a tier ("Platinum Visa Rate" / "Introductory Balance Transfer Rate") | E25 | test_facts `test_card_rows_are_attributes_not_tiers_E25` | ☑ |
| B24 | One cell = purpose + term + amount ("Purchase: 30-Year Fixed Conventional $832750 or less") | E18 | test_facts `test_mortgage_purpose_term_and_nested_amount_tiers_E3` | ☑ |
| B25 | Product from a product column OR the heading (layout changed between crawls) | E20, R18 | test_facts `test_auto_rows_become_keyed_dated_facts_E1`, `test_certificates_implied_by_term_rows_under_regular_or_special` | ☑ |
| B26 | Same table layout, different product (ATV vs auto) | E16 | test_facts `test_atv_table_is_not_an_auto_loan_E16` | ☑ |
| B27 | Personal vs business variants; IRA Roth vs Traditional | E19 | test_facts `test_ira_prefixes_are_separate_keys_E19`, `test_business_segment_comes_from_the_url_when_headings_omit_it` | ☑ |
| B28 | Introductory rates ("Dividend Rate for 1st 6 Months") are not standard rates | Phase 2A check (/earn-more) | `intro` flag from header or row label (facts.py); row-label case tested in `test_card_rows_are_attributes_not_tiers_E25` | ☑ `intro` flag; intro questions use it |
| B29 | Boilerplate churn (widgets, banners, teasers) | E12, R11 | Phase 2E | ☑ test_prose `test_teaser_block_is_cut_under_both_of_its_names_R11`, `test_widget_chrome_image_data_and_chart_series_are_removed_E12_E24` |
| B30 | Numbers inside data blobs (SVG, calculator series) | E24, R11 | Phase 2E | ☑ test_prose `test_widget_chrome_image_data_and_chart_series_are_removed_E12_E24` |
| B31 | URL variants (#fragment, ?query, trailing slash) of one page | E14, R13 | test_resolve `test_older_copy_under_a_url_variant_is_shadowed_R13_E14` | ☑ |
| B32 | Pages appear/disappear; a "missing" page may have moved | E14, design review | test_phase0 `test_page_presence_per_snapshot`; facts are keyed by product, not URL (Bright Savings found on /rates and its new page) | ☑ |
| B33 | Placeholder links to google.com | E25 | Phase 3 (R20); ignored as headings (facts.py) | ☑ test_answer `test_links_come_only_from_the_crawl_R20` |
| B34 | A cell's own measure ("5.34% APR") overrides a wrong header ("Annual Percentage Yield") | E26, R22 | test_facts `test_cell_measure_overrides_a_wrong_header` | ☑ |
| B35 | Heading sits above a layout box (empty-header table) | E26 | test_facts `test_business_segment_and_heading_above_a_layout_box` | ☑ |
| B36 | Curly apostrophes ("Investor’s Choice") | E26 | test_facts `test_vocabulary_handles_curly_apostrophes_and_specific_names_first` | ☑ |
| B37 | A column headed "Account Type" holding model years | E26 | label cells read by content (facts.py `parse_labels`) | ☑ |
| B38 | Rows whose product cannot be identified (2 checking promo pages) -> no fact, logged | E26, R16 | test_facts `test_unknown_product_produces_no_facts_R16` | ☑ |
| B39 | Nested "or less" tiers ($100,000 is inside "$300,000 or less" too) -> use the narrowest | E26, R23 | test_resolve `test_nested_or_less_tiers_never_merge_and_the_narrowest_comes_first_R23_E26` (`Resolved.find` sorts narrowest first; Phase 3 takes the first) | ☑ |
| B40 | Facts parsed once per distinct page version; ingest stays fast (1.1 s for 5 crawls) | — | test_facts `test_store_extracts_facts_once_per_distinct_page_version` | ☑ |
| B41 | Newest effective date beats page authority; dated beats undated | E1, E17, R2, R15 | test_resolve `test_newest_effective_date_wins_and_stale_copies_lose_E1`, `test_date_beats_authority_a_trusted_page_with_an_old_table_loses_E17`, `test_dated_table_beats_undated_table_R15` | ☑ |
| B42 | Same date: authority decides | R3 | test_resolve `test_authority_breaks_a_tie_on_the_same_date_R3` | ☑ |
| B43 | Relabelled tiers ("2023-26" -> "2024-27") pair by largest overlap | E1, R6, R26 | test_resolve `test_relabelled_tiers_pair_by_largest_overlap_E1` | ☑ |
| B44 | Tier listed only by older tables (84 mo for 2017-20 in 05) -> superseded, never answered | R6, R26 | test_resolve `test_tier_dropped_by_the_newest_table_is_superseded_R6` | ☑ |
| B45 | Duplicate tier row inside one table ("$100,000+" twice) | E27 | test_resolve `test_a_table_never_competes_with_itself_duplicate_tier_row` | ☑ |
| B46 | Impossible row (dividend rate > APY) on a trusted page, same date as a correct copy | E27, R25 | test_resolve `test_row_with_rate_above_apy_loses_a_tie_R25_E27` | ☑ |
| B47 | Values compared by number ("5.39%" = "5.390%") | A6 | test_resolve `test_values_are_compared_by_number_not_by_text` | ☑ |
| B48 | Two values nothing separates -> deterministic answer + UNRESOLVED_TIE for review | — | test_resolve `test_nothing_separates_two_values_flags_a_tie_for_review` | ☑ |
| B49 | Resolution independent of page order (determinism) | A5 | test_resolve `test_result_does_not_depend_on_page_order` | ☑ |
| B50 | Product page relabels a term ("25 Month" vs "17 Month", same values) | E27, D8 | different keys, both kept | ☑ different keys, not a conflict (D8) |

## C. Time
| ID | Edge case | Covered by | Status |
|---|---|---|---|
| C1 | `as_of` None -> latest crawl | test_phase0 `test_as_of_selection`; resolved verdicts too: test_resolve `test_store_resolves_every_crawl_at_ingest_and_follows_as_of` | ☑ |
| C2 | `as_of` between crawls -> newest crawl on/before | test_phase0 | ☑ |
| C3 | `as_of` before the first crawl (D5: use effective dates) | test_phase0 (store level) + Phase 3 | ☑ test_answer `test_before_the_first_crawl_answers_only_from_evidence_dated_that_early_D5`, `..._without_dated_evidence_says_it_cannot_tell_D5` |
| C4 | `as_of` after the last crawl | test_phase0 | ☑ |
| C5 | `as_of` with a time part | test_phase0 | ☑ |
| C6 | Date written in the question ("as of May 2026") but `as_of` None | Phase 3 | ☑ test_answer `test_as_of_picks_the_crawl_and_a_date_in_the_question_counts_too_R5` |
| C7 | Relative time ("today (October 2026)", "last year") — E5, E22, R21, D7 | Phase 3 | ☑ test_prose `test_find_prose_lists_the_newest_year_first_R21`; year-only dates only in rate questions |
| C8 | Event date vs today (Hy-Vee closes 2026-03-31) — E5, R10 | Phase 2E + 3 | ☑ test_prose `test_branch_closure_date_and_where_members_go_E5` |
| C9 | Same value re-dated is not a change (R17) — E19 | test_resolve `test_same_value_on_many_pages_and_dates_agrees_and_is_not_a_conflict_R17_E19`, `test_changes_ignore_redating_and_pair_relabelled_tiers_R17_E20` | ☑ |
| C10 | Prose facts: newest publish date wins, not majority (R4) — E4 | Phase 2E | ☑ test_prose `test_newest_publication_wins_never_the_majority_R4_E4` |
| C11 | Prose boilerplate not monotonic by date (assets $3.5B outlier) — D6 | Phase 3 | ☑ newest publication wins (R4); D6 |
| C12 | Rate effective after the question's date (D2) | Phase 3 | ◐ between crawls a later table effective on or before the day wins (D15, `test_between_crawls_a_later_crawl_proves_an_earlier_change`); a rate effective after as_of within one crawl: not seen in the data (D2) |

## D. Understanding the question (Phase 3)
| ID | Edge case | Example | Status |
|---|---|---|---|
| D1 | Synonyms | CD = certificate = share certificate | ☑ query vocabulary; held-out h3-p31 "17 month CD special", h4-18 "6 month CD" |
| D2 | Number words and formats | "six month", "6-mo", "5 years" | ☑ test_answer `test_question_understanding` (number words, "five-year") |
| D3 | Tier as an amount | "balance between $10,000 and $24,999" | ☑ test_answer `test_balance_tier_and_superlative_and_false_premise` |
| D4 | Model year as a year | "2025 model-year vehicle" | ☑ test_answer `test_a_date_and_a_model_year_together_keep_both_constraints` |
| D5 | Under-specified | "What are the mortgage rates?" (D3) | ☑ D3: list all tiers, newest first |
| D6 | Superlatives | "highest Share Savings APY" | ☑ test_answer `test_balance_tier_and_superlative_and_false_premise` |
| D7 | False premise | "Do any savings tiers pay 0.35%?" (E7) | ☑ test_answer `test_balance_tier_and_superlative_and_false_premise` |
| D8 | List questions | "What credit cards do you offer?" | ☑ list questions answered from all matching facts |
| D9 | Chatty wording | "Can you repeat the routing number?" | ☑ test_answer `test_routing_address_phone` |
| D10 | Personal vs business ambiguity | "Prime Checking" | ☑ "including business" = both segments (test_answer `test_question_understanding`) |
| D11 | Unknown product/branch -> refuse | "7/1 ARM", "Mullan Avenue hours" (E10, R9) | ☑ test_answer `test_refusals_decline_plainly_and_contain_no_digits_G3` |
| D12 | Link questions -> current URL only | dup-008 (E23, R20) | ☑ test_answer `test_links_come_only_from_the_crawl_R20` |
| D13 | Term or tier not offered | 84 months for a 2019 car (R6) | ☑ test_answer `test_a_tier_the_newest_table_dropped_is_not_offered_and_shows_no_rate_R6` (D16) |
| D14 | Empty, nonsense or off-topic question | "", "weather?" | ☑ coverage threshold -> refusal |

## E. Composing the answer (Phase 3)
| ID | Edge case | Status |
|---|---|---|
| E1 | No prompt-leak phrasing ("in these facts", "based on the context") | ☑ fixed templates |
| E2 | Never answer with a question ("which term would you like?") | ☑ never; under-specified -> all tiers (D3) |
| E3 | No incidental numbers (years, phone numbers) unless needed | ☑ refusals digit-free; answers carry only the asked value |
| E4 | 2-4 sources: winning page first | ☑ topic page first (D9) |
| E5 | Deterministic output; cache by normalized question + as_of | ☑ deterministic; repeat consistency 1.0 |

## F. Conflicts (Phase 5)
| ID | Edge case | Status |
|---|---|---|
| F1 | Tier or metric differences are not conflicts (R1) | ☑ test_conflicts `test_history_tiers_and_equal_values_are_not_conflicts_F1_F2_E19` |
| F2 | Same value on many pages counts once (R17) | ☑ test_conflicts `test_history_tiers_and_equal_values_are_not_conflicts_F1_F2_E19` |
| F3 | Equal values with different keys are not conflicts (E1: 5.39% twice) | ☑ different keys never pair (R1) |
| F4 | Old/new ranges paired by largest overlap (R6) | ☑ test_values `test_range_contains_and_overlap_R6`; test_resolve `test_relabelled_tiers_pair_by_largest_overlap_E1` |
| F5 | Traditional IRA 3.90% vs Roth 4.00% (D1) | ☑ different keys (account), not a conflict (D1) |

## G. Robustness
| ID | Edge case | Covered by | Status |
|---|---|---|---|
| G1 | No API key / no network | Phase 4 | ☑ no API key, no network, no packages (stdlib only) |
| G2 | Page with missing title/markdown/fetched_at | test_phase0 `test_empty_page_fields`; `clean_text(None)` | ☑ |
| G3 | Snapshots ingested out of order | test_phase0 `test_out_of_order_and_duplicate_ingest` | ☑ |
| G4 | Same snapshot ingested twice | test_phase0 | ☑ |
| G5 | `answer()` / `conflicts()` before ingest | test_phase0 `test_calls_before_ingest` | ☑ |
| G6 | Harness contract file cannot be loaded | `contract.py` falls back to local types | ☑ |

## H. Found by the held-out, combined and independent sets (Phase 6)
| ID | Edge case | Covered by | Status |
|---|---|---|---|
| H1 | Unchanged page keeps each crawl's own fetch time (408/705 pages in 05 had an older one) | test_phase0 `test_unchanged_page_keeps_each_crawls_own_fetch_date_R13_R27` | ☑ |
| H2 | Conflict evidence of every crawl is kept, newest decides values | test_conflicts `test_every_crawls_evidence_is_kept_not_overwritten`, `test_a_conflict_that_disappears_and_returns_keeps_both_episodes` | ☑ |
| H3 | Date and model year in one question keep both | `test_a_date_and_a_model_year_together_keep_both_constraints` | ☑ |
| H4 | "High-Yield" is not "yield"; "minimum deposit" is not a superlative | `test_measures_and_minimums_are_read_correctly` | ☑ |
| H5 | Fees: searched first; "no fee" / "Free" are answers; "Price varies" explained; fee stays on the asked product | `test_fees_minimums_and_founding_year_are_answered_from_the_site`, `test_free_and_no_fee_are_fee_answers`, `test_a_variable_price_is_explained_without_a_number`, `test_an_amount_the_site_does_not_state_is_declined` | ☑ |
| H6 | "rather than the APY" excludes that measure | `test_a_measure_after_rather_than_is_not_the_one_asked_for` | ☑ |
| H7 | "How many volunteer hours" is a count; "how many hours is the branch open" is hours | `test_counts_fees_and_rates_are_told_apart`, `test_hours_counts_and_branch_counts_are_told_apart` | ☑ |
| H8 | Member data declined ("my balance", "approved for me"); how-to questions answered | `test_member_specific_data_is_recognised`, `test_member_data_is_declined_but_how_to_questions_are_answered` | ☑ |
| H9 | Year binding: list items keep "In 2024 alone:"; other-year passages rank lower | `test_a_list_item_keeps_its_year_and_the_asked_year_wins`, `test_a_count_takes_one_figure_from_one_passage` | ☑ |
| H10 | Address of a named place outside the branch list; Hillcrest over all of Dubuque | `test_an_address_in_the_text_answers_a_place_that_is_not_a_branch`, `test_of_several_matching_branches_the_most_specific_one_is_named` | ☑ |
| H11 | Forecasts and years before the crawls declined | `test_forecasts_prices_of_non_products_and_years_before_the_crawls_are_declined_G3` | ☑ |
| H12 | Internal errors visible (logged, counted, strict in tests) | `test_internal_errors_are_counted_and_raise_in_strict_mode` | ☑ |
| H13 | Rates stated only in prose sentences (kit self-test format) | not handled: the real crawls state rates in tables | ☐ known limitation |

## I. Third review (after Phase 7)
| ID | Edge case | Covered by | Status |
|---|---|---|---|
| I1 | "Can I see my balance?" / "Can I get the APR approved for me?" are member data; "How can I check my balance?", "Can I check my balance with the app?" are answered | test_review3 `test_requests_for_own_data_are_member_data_however_phrased`, `test_can_i_see_my_balance_is_declined_with_the_member_data_reason` | ☑ |
| I2 | The measure asked for is required: an APY question about an APR-only product says what is published, never the APR | `test_apy_on_an_apr_only_product_says_so_and_gives_no_rate`, `test_apr_on_a_savings_account_names_what_is_published`, `test_a_published_measure_and_an_unnamed_measure_are_still_answered` | ☑ |
| I3 | Between crawls, a later edit of a page the earlier crawl saw does not replace it; a page first seen later but dated earlier counts | `test_a_later_edit_of_an_observed_page_does_not_rewrite_that_day`, `test_a_page_first_seen_later_but_dated_earlier_still_counts` | ☑ |
| I4 | Citations name the crawl each fact was read from, not the crawl the date picked | `test_a_later_crawls_table_is_cited_as_that_crawl`, `test_an_answer_from_the_chosen_crawl_cites_that_crawl` | ☑ |
| I5 | A rate-only answer does not say "rate ... rate"; "dividend rate" keeps its name | `test_a_rate_only_answer_does_not_repeat_the_word_rate` | ☑ |
| I6 | The public copy holds no passage of 12+ words from any snapshot, no datasets, no kit files | `tools/build_public.py` (scan; exits 1 on any hit) | ☑ |

## J. Found by blind set A (first run 0.4958, kept)
| ID | Edge case | Covered by | Status |
|---|---|---|---|
| J1 | "the June 9, 2026 website" is a date, not a link request; "which page" / "where on the website" still links | test_blind_a `test_dated_websites_named_branches_and_24_hour_atms_are_routed_by_what_is_asked` | ☑ |
| J2 | A named branch with "locator" / "24-hour ATM" asks about the branch (address), not the locator or opening hours | (same test) | ☑ |
| J3 | A rate AND its minimum is a rate lookup; a minimum alone stays a minimum question | `test_a_rate_and_its_minimum_is_a_rate_lookup_but_a_minimum_alone_is_not` | ☑ |
| J4 | A date naming a document is not the as-of date; the answer comes from that document | `test_a_date_that_names_a_document_is_not_the_as_of_date`, `test_a_named_document_is_answered_from_that_document` | ☑ |
| J5 | "not jumbo" / "rather than the jumbo version" / "without the jumbo option" / "non-jumbo" exclude jumbo | `test_a_negated_variant_is_excluded` | ☑ |
| J6 | "the 17-month special" with no product is a certificate | `test_a_special_with_a_term_and_no_product_is_a_certificate` | ☑ |
| J7 | "the APR I personally will be approved for" is member data; "will ... on a date after the last crawl" is a forecast | `test_the_rate_i_personally_will_be_approved_for_is_member_data`, `test_will_on_a_date_after_the_last_crawl_is_a_forecast` | ☑ |
| J8 | Launchpad (mentions an IRA) is Launchpad; "what happens if" is an explanation | `test_launchpad_is_not_an_ira_and_what_happens_if_is_an_explanation` | ☑ |
| J9 | "if / into / someone" are not topic words; "how much space" is not money | `test_function_words_are_not_topic_words_and_space_is_not_money` | ☑ |
| J10 | Two things in one question: two terms / amounts / dates compared, two measures named apart, a rate + its minimum, two fees | test_two_parts (14 tests) | ☑ |
| J12 | A range ("between $10,000 and $24,999") is one value, not two to compare; a document's date is not a part | `test_a_range_a_single_value_or_a_document_date_is_one_part` | ☑ |
| J13 | A requirement in prose next to a rate ("credit score 720, 75% loan-to-value"); an account minimum stated only in a note; a second fact in another paragraph | not handled: answers give the rate only | ☐ known limitation |
| J11 | A passage saying "four" where the key says "4"; "people" vs "individuals" | not handled (wording gap) | ☐ known limitation |

## K. Optional LLM layer (Phase 9; tests use a fake model)
| ID | Edge case | Covered by | Status |
|---|---|---|---|
| K1 | No key / TKB_LLM=off: no LLM, rules-only answers unchanged | test_llm_layer `test_no_key_or_off_means_no_llm`, `test_no_llm_means_no_written_answers` | ☑ |
| K2 | A malformed or unknown reading (route, product, reason) is ignored | `test_a_reading_is_validated_before_it_is_used` | ☑ |
| K3 | "car insurance" is an explanation, not an auto-loan rate; numbers stay with the rules | `test_the_llm_corrects_the_kind_of_question_and_the_rules_keep_the_numbers` | ☑ |
| K4 | An LLM decline cannot override a found branch fact; a found link stands; asking FOR an unpublished rate is declined | `test_an_llm_decline_does_not_override_a_fact_the_rules_found`, `test_a_link_the_rules_found_stands`, `test_a_question_asking_for_an_unpublished_rate_is_still_declined` | ☑ |
| K5 | The LLM's search words only when ours find nothing | `test_the_llm_search_words_are_a_second_attempt_not_a_replacement` | ☑ |
| K6 | Grounded answers: invented number, stale prose rate, no / unknown citation, "not answered" -> rules answer | `test_a_written_answer_that_fails_a_check_is_not_used` (5 cases) | ☑ |
| K7 | Page dates, differences of cited amounts, facts-only answers pass; "doesn't state" becomes a decline | `test_page_dates_differences_and_facts_only_answers_pass_the_number_check`, `test_an_answer_that_opens_by_saying_the_site_does_not_state_it_is_a_decline` | ☑ |
| K8 | API failure falls back; 3 in a row switch the LLM off; a closed connection is reopened once | `test_an_api_failure_falls_back_to_the_rules_answer`, `test_the_breaker_switches_the_llm_off_after_three_failures_in_a_row`, `test_one_connection_is_reused_and_reopened_once_if_the_server_closed_it` | ☑ |
| K9 | Record a live run and replay it offline | `test_a_recorded_run_replays_offline` | ☑ |
| K10 | A rate cap quoted in prose ("APR ... 21.00%") is rejected even when correct | by design (stale-rate guard) | ☐ accepted |
