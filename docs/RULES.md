# What is "current"? Rules and the evidence behind them

Every rule the system applies traces back to evidence in this file. Snapshots:
01 = 2026-05-12 · 02 = 2026-05-19 · 03 = 2026-06-09 · 04 = 2026-08-27 · 05 = 2026-09-28.
Re-check any row with `python tools/explore.py track "<pattern>"`.

## Evidence

### E1. 60-month auto loan APR - stale copies on promo and calculator pages
| Snapshot | Page (type) | 60-mo top tier | Tier label | Effective |
|---|---|---|---|---|
| 01-04 | /personal/loans/auto-motorcycle-loans (product) | 5.19% | 2023–26 Model Year | 5/1/2026 |
| 01-04 | /rates (rate sheet) | 5.19% | 2023-26 Model Year | 5/1/2026 |
| 01-04 | /personal/checking-accounts (product, embedded table) | 5.34% | 2023-26 Model Year | 10/22/2025 |
| 01-05 | /switch-and-earn (promo) | 5.34% | 2023–26 Model Year | 1/1/2026 |
| 01-05 | /calculators/vehicle-affordability (calculator) | 5.34% | 2023–26 Model Year | 1/1/2026 |
| 05 | product pages, /rates | **5.39%** | **2024-27** Model Year | 08/31/2026 |

Lessons: the newest effective date identifies the current table; promo and calculator pages keep
old copies; tier labels change between crawls, so a "2025 vehicle" must be matched by year INSIDE a
range; en-dash vs hyphen in labels.

Phase 1 check (track "Model Year \| 60 Months"): /personal/checking-accounts is a PRODUCT page
but carries an auto table effective 10/22/2025 (5.34%) -> page type alone is not enough; the
effective date must be checked first. Tiers shifted in 05 (2021-22 -> 2021-23), so a 2023 car
moved from the top tier (5.19%) to the middle tier (5.64%). All three tiers rose by 0.20.

84 months: 5.39% (May, eff 5/1/2026) -> 5.59% (Sep, eff 08/31/2026); stale 5.54% on calculator and
promo. In 05, 84 months is offered only for 2024-27 and 2021-23 (not 2017-20).

Same number, different facts: 5.39% is the 84-month top-tier rate in May AND the 60-month top-tier
rate in September. Facts must be identified by key (product + term + range + attribute), never by
value; equal values with different keys are not conflicts.

### E2. 10-month jumbo certificate special - changes over time
/rates: 3.90% APY (01-04) -> **4.00% APY** in 05 (effective 09/01/2026). "As of May 2026" must answer 3.90%.
Each certificate row has two numbers: dividend rate and APY. The question decides which one.

### E3. 30-year mortgage - stale guidance page, tiers by loan amount
05 home-loans page (effective 09/25/2026): 30-yr purchase, $100k or less 7.13%; larger amounts 7.25%.
/homebuying-guidance still shows 6.037% APR (effective 04/22/2026) -> stale trap.
Dollar amounts appear with and without commas ("$832,750" / "$832750").

### E4. Branch count - only in press-release boilerplate, changes over time
Press releases up to 2026-03-17 say "23 branch office locations"; from 2026-04-03 they say **22**
(Hy-Vee branch closed 2026-03-31). Older releases say 20 or 24.
Lesson: for prose-only facts the NEWEST PUBLISH DATE wins, not the majority.

The same boilerplate also states assets, and it is NOT monotonic by date: $3.6 billion on 2026-02-27
and 03-02, $3.5 billion on 03-10, $3.6 billion again from 03-17. The Forbes sentence is present in
Jan/Feb 2026 boilerplate and absent from March on (not yet verified in detail).

### E5. Hy-Vee branch - an event with a date
Press release (June 20, 2025): "This location will close March 31, 2026". In October 2026 -> closed.

### E6. Forbes - "fourth time" (2023-07-25) vs "fifth time" (2024-06-18, newest) -> fifth.

### E7. 0.35% - right number, wrong product
0.35% is a Money Market / HSA tier. Share Savings tops out at 0.20%. Tables stay attached to their product.

### E8. Personal loan - product name only in the heading above the table (`| Term | APR |`).

### E9. Lobby hours appear only in prose (press releases); /contact lists form-reply hours.

### E10. Routing 273974581 on /contact. Mullan Avenue branch is mentioned but has no address/hours -> refuse.

### E11. Footnote digits glued to values: `5.39% APR1`, `3.90%1` -> 5.39%, 3.90%.

### E12. Crawl churn is mostly boilerplate ("Third Party Plugins", "Messenger Launcher", related-post teasers).
Phase 1 overview: changed(raw) = changed(ignoring whitespace), e.g. 615 = 615 -> whitespace is not the noise.

### E13. Some pages in snapshot 05 were fetched in June/August, not September.

### E14. The same page under two URL spellings - one copy can be stale
Snapshot 04 has /personal/retirement (fetched 2026-08-27) AND /personal/retirement#iracompare
(fetched 2026-06-15). Snapshot 05 has /personal/loans/loan-protection and ...?hsLang=en.
3 normalized paths appear twice in snapshot 05. Found in the Phase 1 overview: the "gone"
/personal/retirement was really the #iracompare variant disappearing.

### E15. Invisible characters inside table rows
Raw row on the calculator: '| 2023–26 Model Year | 84\xa0Months | 5.54% APR |' - a non-breaking
space. Non-breaking and narrow spaces appear in table rows in every snapshot; en/em dashes in 155/66
rows in 05. A plain-text search for "84 Months" silently misses the row.

### E16. Same table layout, different product
Snapshots 01-04, /personal/checking-accounts: "ATV, Snowmobile & Jet Ski Loans" is 10 lines above
a "| Model Year 2026-23 | 36 Months | 8.34% APR |" table (blank lines between). Looks like an auto
table; is not. The product must come from the nearest non-empty heading, which may be far above.

### E17. A product page that is really a year-old rate sheet
Snapshots 01-04, /personal/checking-accounts: 13 rate tables for 12 products (auto, cards, mortgage,
home equity, personal, boat & RV, ATV), almost all effective 10/22/2025 - e.g. 30-yr mortgage
($100k or less) 5.625% vs 7.13% current. Each table has its own effective line ~10 lines below it.

### E18. Table layouts vary - the header defines each column
Layouts seen: Balance/Dividend Rate/APY/Min to Open/Min to Earn; Loan Program/Term/APR;
Term/Rate/Points/APR/Payment Example; Loan Amount/Term/APR; Card/APR. Boat & RV values have no %
("7.29"). Cells can hold several facts ("Purchase: 30-Year Fixed Conventional $832750 or less";
"2.90% APR for 6 mos. (after that ... 12.50% - 19.50% APR)2"). Payment Example and
Points columns are not rates. Money ranges: "$10,000-24,999", "$25,000 - $99,999.99", "$100,000+",
"$832750 or less".

### E19. 10-month jumbo certificate - re-dating, IRA split, many pages
Header: Term | Dividend Rate | APY | Min. to Earn -> "3.86% | 3.90%1" = rate 3.86%, APY 3.90%.
/rates APY 3.90% (eff 03/03 -> 06/02 -> 07/14, value unchanged) in 01-04 -> 4.00% (rate 3.96%) in 05.
Snapshot 05, same table, eff 09/01/2026, on /rates AND /personal/retirement: regular and Roth 4.00%,
Traditional IRA still 3.90%. The row appears on 6-7 pages per crawl with page-specific effective dates
(04: /business-rates 06/02 vs /rates 07/14) but equal values. Header word drifts (Term -> Certificate /
IRA Type); "$100,000" -> "$100,000.00".

### E20. /rates was rebuilt in snapshot 05 - text diffs stop working
04: 555 lines, 29 tables, checking first, product name in a heading above each table.
05: 491 lines, 27 tables, savings first, product name in a column ("Account Type", "Card Type").
A line diff shows nearly everything as removed and re-added, so rate changes are invisible in it.
-> Compare extracted FACTS between crawls, never raw text. Share Savings tops out at 0.20% ($25,000+);
Bright Savings (2.23% / 2.25% APY, eff 06/02/2026) is on /rates although /savings/bright-savings is gone.

### E21. One table, two effective dates; escaped line breaks
05 /rates: Share Savings table is followed by "Rates are effective as of 06/15/2026" (caption) AND
"1Rates are effective as of 03/03/2026" (footnote 1, tied to the "(APY)1" header). Credit card table:
01/02/2026 and 1/1/2026. 7 lines contain literal "\\r\\n" escape sequences inside sentences.

### E22. Volunteer Time Off - year-labelled facts and an ambiguous "last year"
/newsroom/volunteering-pays-off-...-giving-back (April 19, 2024): 294 employees used VTO in 2023.
/newsroom/volunteering-pays-off-...-giving-back-2 (April 21, 2025): 256 employees used VTO in 2024.
Both in all 5 crawls; they are different articles ("-2"), not URL variants. dup-088 expects "294 (in 2023)".
Different years are different facts (year is part of the key); "last year" is ambiguous.
The first "Month D, YYYY" near the top gives the right publish date on both pages (teaser dates sit lower).

### E23. Link questions - a trap URL that exists nowhere
dup-008: trap "info.dupaco.com/certificate_account_rates" appears in none of the 5 crawls (any case or
separator). The expected link /personal/savings-account is the product page holding the certificate table
(E19); it is linked from 47 pages, mostly blogs - link popularity is not authority.

### E24. Numbers inside data blobs
"294" also matches inside calculator chart data ("296: 15...", "259: 116493") and embedded SVG image code
on /contact. Numbers must be extracted in context (table cell or topical sentence), never by plain search.

### E25. Placeholder links and attribute-per-row tables
Many tables are preceded by "[Learn More](https://google.com/)" - placeholder links to a non-Dupaco
site. In credit-card tables each ROW is a different attribute of the same card ("Platinum Visa Rate"
vs "Introductory Balance Transfer Rate"), not a tier. Phase 2B check: the value parser reads all 4,044
rate cells in the 5 crawls (18 ranges, bare numbers under rate headers) with 0 failures.

### E26. Phase 2C findings (fact builder run over all 5 crawls)
- The vehicle-affordability calculator heads its auto table "Annual Percentage Yield"; its cells read "5.34% APR".
- A column headed "Account Type" sometimes holds "2023-26 Model Year"; "Loan Type" holds dollar tiers.
- "Business 1st Rate Checking Account" sits above a layout box (empty-header table), not directly above its rates.
- /business-rates heads Share Savings "Share Savings" in 01 and "Business Share Savings" in 05.
- Mortgage tiers are nested: "$100,000 or less" also lies inside "$300,000 or less".
- 1st Rate Checking APY ($5,000-$24,999.99): 3.00% in 01 (eff 2025-07-01) -> 2.50% in 05 (eff 2026-06-02).
- Two checking promo pages (checking-offer-lp, tax-checking-offer-lp) never name their product -> skipped.
- Bright Savings 2.25% APY: own page eff 2025-08-13, /rates eff 2026-06-02 - same value re-dated (R17).
Facts: 730 (01), 772, 770, 798, 862 (05); extraction 0.15 s per crawl.

### E27. Phase 2D findings (resolver run over all 5 crawls)
Slots (one tier of one fact key) per crawl: 274, 274, 276, 283, 291. Slots with a losing value: 33, 33, 35, 40, 35.
Resolution takes ~10 ms per crawl. Ties that no rule separates: **0** in all five crawls.
- **Impossible row.** /business-rates (01-04) and /business/savings-accounts (01-03) list Business Share Savings
  $10,000-$24,999.99 as dividend rate **0.20%**, APY **0.15%**. APY includes compounding, so it can never be
  below the rate. In 04 the product page shows 0.15% / 0.15% while /business-rates still shows the typo: same
  date (01/06/2026), same authority. Before R25 the winner was decided by a 3-minute fetch difference (luck).
  It is the only such row in all five crawls (7 page versions, one row family).
- **Duplicate tier row.** /newcard-balancetransfer-lp lists "$100,000+" twice; the second row's "Min. to Earn"
  is $25,000, so it is really the $25,000 tier mislabelled. A table never competes with itself, so the second
  row opens its own slot, which is superseded (the newest table has no such tier).
- **Term label drift.** Crawl 03: /personal/retirement labels the Traditional IRA special "25 Month Fixed Special"
  (3.81% / 3.85%) while /rates labels the same values "17 Month". Different keys (term), so not paired. -> D8.
- **URL variant.** 42 facts per crawl in 02-04 sit on /personal/retirement#iracompare; in 04 that copy was fetched
  06-15 vs 08-27 for the canonical URL. R13 sets them aside (FRESHEST_COPY_OF_PAGE).
- **Changes between crawls, on resolved facts (E20):** 24 (01->02), 63 (02->03), 54 (03->04), 76 (04->05).
  04->05: every auto tier rose 0.20 (60 mo top tier 5.19% -> 5.39%); 17-mo special APY 4.05% -> 4.10%.
  02->03: the 25-month specials ended and 17-month specials began (seen as "gone" + "new" slots).
- Same date + same authority + different value happens only in the E27 typo row.

### E28. Phase 2E: prose facts and boilerplate
The teaser block was renamed "Recent News" (crawls 01-03, 417 pages in 01) -> "Handpicked for You" (04-05, 490 pages in
05); a 2020 Forbes teaser ("third year in a row") sits inside 2021 releases; a chat widget appears on 607 pages in 02
only (E12 churn). A first listing test counted teaser "Keep reading" links and flagged 542/705 pages, so listing
detection now looks above the teaser block only. The routing trap 271176899 is in no crawl (invented, like E23). Every
count, award, event and hours fact is on a dated page; only routing numbers and addresses are on undated pages, and
their values never disagree -> R27.

### E29. Phase 3: answering
Guardrails G1-G6 (compose.py). Held-out misses each became a general rule: number words ("five year"), "Main Street"
(a name) vs "main branch" (not a name), "close on Saturday" = hours, "including business" = both segments, IRA + a term
= certificate, teaser anchors inflating link scores, an FAQ question answered by the next paragraph, variant footnotes
ranking below the plain product. Held-out 45/55 -> 54/55, held-out 2 15/20 -> 20/20.

### E30. Phase 5: planted stale copies
Per crawl: the auto calculator and /switch-and-earn (+ /personal/checking-accounts in 01-04) carry 2026-01-01 auto
rates; /homebuying-guidance and /mortgage-refi carry 2026-04-22 mortgage rates; the promo landing page
/newcard-balancetransfer-lp shows 1st Rate Checking at 3.00% APY (03-05); /business-rates holds an older 17-month
special and the R25 typo row (04 only). Several public traps exist in no crawl (6.7%, 9.9%, 271176899).

### E31. Phase 6: time
A page whose text is unchanged was still fetched again: 408 of 705 pages in crawl 05 had carried an older fetch time
(fixed: one Observation per crawl). A later crawl can date an earlier change: crawl 04 (08-27) shows the 60-month auto
rate at 5.19%, crawl 05 shows 5.39% "effective 08/31/2026", so on 09-01 the rate was 5.39% (D15). Before the first crawl
only evidence dated that early can answer (D5). A year alone dates a rate question ("in 2019") but labels a fact in
others ("VTO in 2023", R21) - a regression caught by an older held-out set.

### E32. Phase 6 review: combined constraints
A date in the question switched off model-year reading ("As of May 2026 ... a 2021 vehicle" listed every tier);
"High-Yield" matched "yield"; "minimum deposit" read as "lowest rate"; fee-schedule rows under 40 characters were
never indexed; "founded" and "foundation" stemmed alike. Combined set: first run 0.4375 (kept), 1.0 after fixes.

### E33. Independent set: first blind run 0.72
Misses were question shapes never written before: a measure after "rather than", "how many volunteer hours", member
data ("my balance", "approved for me"), a fee that names a card, a blog paragraph outranking the answer, an address in
a press release. Fixed by general rules (D23-D28); the set is now a regression suite.

### E34. Second review
"How can I check my balance?" is guidance, not member data; "how many hours is the branch open" was answered with the
branch count (an older bug); "no annual fee" and "Free" are fee answers; "Price varies" deserves its own explanation;
"the Hillcrest Road branch in Dubuque" matched all four Dubuque branches. Rules with no measurable effect on data or
tests were removed; test sites were made to mirror real word frequencies so each test fails without its rule.

## Rules

| # | Rule | Evidence |
|---|---|---|
| R1 | Fact key = product + attribute + term + qualifiers. Two facts are the SAME fact when product, attribute and term match and their ranges (model year, amount, balance) OVERLAP - labels may differ between versions. Different keys are never conflicts. | E1 E2 E3 E7 E8 |
| R2 | Same fact: the latest effective date wins. | E1 E2 |
| R3 | Tie or no effective date: authority rate_sheet = product > other > pdf > promo = calculator = press > blog. | E1 |
| R4 | Prose-only facts: the newest publish date wins (from the byline, never from teaser blocks or listing pages). | E4 E6 E12 |
| R5 | as_of = D uses the newest snapshot taken on or before D. | E2 |
| R6 | Ranges match by containment. Formats: "2023–26", "2023-26", reversed "2026-23", open-ended "2016 Model Year (and older)". For answers the question's value picks the range; for conflicts, pair the ranges with the largest overlap. A value outside every range, or a term not offered for that range (84 months for 2017-20 in 05) -> not available; never borrow another tier. | E1 E3 |
| R7 | Strip footnote digits glued to values. | E11 |
| R8 | Answer text holds only winning values; losing values go to conflict_note. | scorer |
| R9 | Entity mentioned but attribute missing -> refuse; never borrow another entity's value. | E10 |
| R10 | Compare event dates with "today". | E5 |
| R11 | Remove boilerplate before versioning and extraction: widgets, plugin banners, related-article teasers, embedded image data (data: URIs, SVG code) and calculator data series. | E12 E24 |
| R12 | Question says APY -> APY; deposits "rate" -> rate and APY; loans -> APR. | E2 E3 |
| R13 | URL variants (#fragment, ?query) of one page are grouped by normalized path; within one crawl the most recently fetched copy wins. | E14 |
| R14 | Normalize text before any parsing or matching: invisible spaces -> normal space, dash variants -> "-". | E15 |
| R15 | A table's effective date is the first "effective as of" line AFTER the table and BEFORE the next table, skipping footnote lines that start with a footnote   number ("1Rates are effective..."); none -> undated (loses to dated facts). Tables with two different dates are logged for review. | E17 E21 |
| R16 | Column meaning comes from the header (rate, APY, APR, term, amount, balance); unknown layouts are skipped and logged, never guessed. Payment-example and points columns are not facts. | E18 |
| R17 | A new effective date with the SAME value is not a change; a conflict needs different values for the same fact key. The same fact on many pages counts once. | E19 |
| R18 | Product name comes from a product column ("Account Type", "Card Type", "Loan Program") when the table has one, else from the nearest heading. Layouts change between crawls, so both must work. | E8 E16 E20 |
| R19 | Clean text before parsing: literal "\\r\\n" escape sequences -> space (with R14). Changes between crawls are detected on extracted facts, never on raw text. | E20 E21 |
| R20 | Link answers use only Dupaco URLs present in the current crawl (never placeholder links such as google.com); prefer the product page whose table covers the topic; never construct or guess a URL. | E23 E25 |
| R21 | Year-labelled facts (e.g. "VTO users in 2023" vs "in 2024") are different facts, not versions. If the question's relative time is ambiguous, give the newest year and the previous one, each labelled. Never applied to rates. | E22 |
| R22 | A cell that names its own measure ("5.34% APR") overrides the column header. | E26 |
| R23 | Nested "or less" tiers: answer with the narrowest tier containing the amount; for conflicts pair equal tiers first, then the largest overlap. | E26 E3 |
| R24 | Segment is business when the row or heading says "business" or the page URL starts with /business; otherwise personal. | E26 |
| R25 | A deposit row whose dividend rate is above its APY is internally inconsistent; it loses ties (same date, same authority) to a consistent row. Not used to discard a row on its own. | E27 |
| R26 | Tiers pair into slots in precedence order: equal tier first, then largest overlap; two rows of one table never share a slot. A slot whose best fact is older than the newest table for the same key is SUPERSEDED (tier dropped) and is not used for current answers. | E1 E26 E27 |
| R27 | An undated official page (/contact) speaks as of the day its crawl fetched it; dated pages speak as of their byline (R4). Used for prose facts and for questions before the first crawl. | E28 E31 |
## Decisions (D1-D9 were open questions here; all are now decided)

| # | Question | Decision | Phase |
|---|---|---|---|
| D1 | Traditional IRA jumbo 3.90% vs Roth 4.00% (same table, same date): a conflict? | No: different accounts are different keys (R1) | 5 |
| D2 | A rate whose effective date is AFTER as_of, within one crawl | Still open: not seen in the data. Between crawls, D15 applies | - |
| D3 | No model year in the question: which auto tier? | List every tier, newest first | 3 |
| D4 | A fact present only in older crawls | Answers use the as_of crawl, refined by later crawls' dated evidence (D15) | 3, 6 |
| D5 | as_of before the first crawl | Answer only from evidence dated on or before the day, with a note; else "cannot tell" | 6 |
| D6 | Prose outliers (assets $3.5B on 2026-03-10) | Newest statement wins (R4): $3.6 billion | 3 |
| D7 | "Last year" questions | Newest year and the one before, labelled (R21); never for rates | 3 |
| D8 | Relabelled term with equal values ("25 Month" vs "17 Month", 3.85%) | Not a conflict (R17) | 5 |
| D9 | Citation order when a rate sheet and a product page tie | Topic page first; links: product page + "#rates" | 3 |

Decisions D10-D33 (Phases 3-6) are listed with their evidence in `docs/PROJECT_STATE.md`.
## Design review (merged with docs/design_proposal_precedence.md)

Adopted from the proposal:
- Section-level authority: each table/section is judged on its own, not the whole page (E17).
- Reason codes on every resolution, and conflict statuses; historical changes and warnings are kept
  out of conflicts() (E19).
- Event dates / program cycles as a third notion of time, next to crawl date and effective date (E5).
- Unknown qualifiers stay unknown; never assume a row applies to every tier (E8, E18).
- Rules as data, in a Python dict (not YAML, to stay standard-library only).
- Topic-specific authority (fee schedule for fees, branch-specific entries for hours).
- Facts keyed by product, not page, so moved pages are handled
  (/savings/bright-savings -> /savings-account/online-savings-account).

Kept from our evidence, where the proposal suggested otherwise:
1. Among dated official tables the newest effective date ranks BEFORE authority (E1, E17).
2. Prose facts: newest publish date beats counting how many pages agree
   (E4: "23" appears 40x, "22" 35x; 22 is current).
3. Abstain only when no evidence exists; conflicting evidence -> best-supported answer + conflict_note
   (scorer: abstaining on an answerable question scores 0).
4. Standard library only: dict instead of YAML, own BM25 instead of FTS5, no FAISS/embedding download.

Reason codes:
| Code | Meaning | Rule |
|---|---|---|
| EXPLICIT_EFFECTIVE_DATE | Newer effective date on the same fact | R2 |
| OFFICIAL_RATE_TABLE_OVER_CALCULATOR | More trusted source type, same or no date | R3 |
| CONSISTENT_ROW_OVER_INCONSISTENT | Same date and authority; the loser's row has dividend rate > APY | R25 |
| NEWER_FETCH | Same date and authority, both rows consistent; the winner's page was fetched later | - |
| UNRESOLVED_TIE | Nothing separates two values (never seen; flagged for review) | - |
| TIER_NOT_IN_NEWEST_TABLE | Slot status: only older tables list this tier -> superseded | R6 R26 |
| NEWEST_PUBLICATION | Newer publish date for a prose fact | R4 |
| FRESHEST_COPY_OF_PAGE | Newer fetch of the same page under another URL | R13 |
| HISTORICAL_VERSION_CHANGE | Value changed over time - history, NOT a conflict (`resolve.changes`) | R17 |
| DIFFERENT_METRIC_NOT_A_CONFLICT | e.g. dividend rate vs APY, different tiers | R1 |
| INSUFFICIENT_EVIDENCE | Nothing supports an answer -> refuse | R9 |
