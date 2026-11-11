# Project state - handoff (Phase 9: optional LLM layer done; freeze + set C next)

Read this first in any new working session. It says what exists, why, and what comes next.

## The task in one paragraph
Build `submission/solution.py` -> `build()`
returning an object with `ingest(snapshot)` (called 5x, oldest first, 30 min limit), `answer(question, as_of=None)`
-> `Answer(text, sources, confident, conflict_note)`, and `conflicts()` -> list of `Conflict`. Data: 5 crawls of
dupaco.com (01 2026-05-12, 02 05-19, 03 06-09, 04 08-27, 05 09-28). Graded on a hidden question set with
`harness/run_eval.py`: accuracy 55%, conflicts 15% (F1 + resolution), consistency 15%, speed 15% (p95 <= 2 s);
consistency and speed are multiplied by accuracy. Graders run their own harness in clean Python 3.11.

## Scorer facts that drive the design (from reading harness/scoring.py and run_eval.py)
- Any `must_not_include` (stale) value in `text` zeroes the question -> only winning values in text,
  losing values only in `conflict_note` (not scored).
- `should_refuse` fails if the text has ANY digit -> refusal text has no digits, `confident=False`.
- Repeat check uses `isinstance(answer, harness Answer)`, else `str(answer)` -> `tkb/contract.py` reuses
  the harness classes (otherwise repeat consistency = 0).
- Sources compared on host + path; extra sources cost nothing. Conflicts: F1, match needs >= 2 gold values
  (or 1 value + topic keyword); resolution credit needs the winning value in `resolution`.
- Public practice set has NO conflicts gold; ours is `eval/conflicts_gold.json` (10 entries, Phase 5). Matching is
  greedy one-to-one and precision = matched / submitted, so every extra Conflict costs F1.

## Architecture (temporal fact store + retrieval fallback; no LLM: Phase 4 was skipped by design)
```
ingest:  pages -> store.py (every version, dedup by hash) -> tables.py -> values.py -> facts.py (per page version)
                                                           -> prose.py (byline date + prose facts, per page version)
                -> resolve.py (per crawl: table slots + prose keys -> winner, agree, losers + reason codes)
answer:  question -> query.py (intent + slots) -> crawl for as_of / a date in the question (R5)
                 -> compose.py: rate (resolved.find) | prose (find_prose) | link (LinkIndex) | BM25 (PassageIndex)
                 -> guardrails G1-G6 -> refuse (no digits) when nothing supports an answer
conflicts: every crawl's verdicts -> conflicts.py: losers with a different value, grouped per topic -> [Conflict]
```
Standard library only (no LangChain/LangGraph/SQLite FTS5/YAML/FAISS). Optional `anthropic` in Phase 4.

## Files (submission/tkb/)
| File | Role | Phase |
|---|---|---|
| contract.py | Reuse harness Answer/Source/Conflict; local fallback | 0 |
| classify.py | URL -> page type + authority (blog/press/calculator/promo/product/rate_sheet/pdf/other) | 0, fixed in 1 |
| store.py | VersionStore: versions per URL (text + facts stored once), view per crawl of `Observation`s (shared version + THIS crawl's fetch time: 408/705 pages in 05 had carried an older one), `view(as_of)`, `facts(as_of)`, `resolved(as_of)` | 0, 2C, 2D, 2E, 6 |
| normalize.py | `clean_text`: invisible spaces, dashes, curly quotes, escaped \r\n, <br>, md escapes, entities | 2A, 2C |
| tables.py | `parse_tables`: header, rows, context (headings above, through layout boxes), effective date (R15) | 2A, 2C |
| values.py | Percent (with ranges), Range (contains/overlap), money/year/term parsers, footnote stripping | 2B |
| facts.py | Fact (product, attribute, value, term, tier, segment, account, purpose, flags, effective, url, evidence), vocabulary, `extract_facts` | 2C |
| prose.py | `clean_page` (R11: teaser block "Recent News" 01-03 / "Handpicked for You" 04-05, modal + chat widgets, image data, chart series), `is_listing`, `publish_date` (byline of the cleaned page), `extract_prose` -> ProseFact(kind, subject, value, number, qualifier, label, published, url): branch_count, employees, assets, forbes_recognition, vto_employees (year = subject), routing_number, address (by city), hours (per release, lobby / drive-up), closure, closure_alternatives | 2E |
| resolve.py | Per crawl: R13 URL variants -> slots (equal tier, else largest overlap, never same table, R26) -> winner by R2 > R3 > R25 > fetch; same value = agree (R17); losers with reason codes; superseded tiers; `Resolved.find(x=..., **key)` narrowest tier first (R23); `changes(old, new)` across crawls; prose: per (kind, subject, qualifier) newest statement wins (R4), undated page = fetch date (R27), `Resolved.find_prose(kind, subject)` newest first; `known_by(day)` (before the first crawl: winners whose table is effective <= day, R4 over statements <= day) and `as_of(day, later)` (between crawls: a later crawl's table effective <= day replaces the key's slots; later statements published <= day join R4) | 2D, 2E, 6 |
| query.py | `parse_question` -> Query(intent, products, segment, account, purpose, flags, attribute, term_months, x / x_kind, superlative, premise, unpublished, named_branch, date_ref, asks_rate / asks_price, future, terms). Rules as data: QUERY_PRODUCTS, PROSE_INTENTS, MORTGAGE_VARIANTS; Phase 6: a year alone dates a RATE question ("in 2019"), not a fact label ("VTO in 2023"); forecasts (`future`); "rate and APR" = both measures; a price / salary / revenue of a non-product is a number request | 3, 6 |
| retrieve.py | Per crawl, built at ingest: `PassageIndex` (BM25 over cleaned paragraphs; coverage, rarest word, next passage for FAQs), `LinkIndex` (crawl URLs + Dupaco links from cleaned pages, anchor counts), `main_phone`, `clean_url`, small stemmer | 3 |
| compose.py | Answers + guardrails: G1 only winning values in text (losers -> conflict_note), G2 named tier only / dropped tier = "not offered" with no rate, G3 refusals without digits, G4 retrieval never quotes a %, G5 deterministic, G6 links only from the crawl + topic-ranked citations (D9). Rate lists, superlatives, false premises, prose kinds, hours (D10), links, BM25 fallback | 3 |
| conflicts.py | `build_records` / `build_conflicts(resolved per crawl, dates)`: every crawl keeps its own CrawlEvidence (date, winners, stale values + pages + effective dates, sources) in a ConflictRecord (Phase 6); the newest crawl decides values + resolution, older crawls go to reason ("Earlier: 01-04 ...", identical crawls merged) and sources (tagged by snapshot). Built from table slots whose losers differ in value (stale calculator, guidance, promo, second rate table, R25 typo) + prose kinds branch_count / forbes_recognition / assets with losers published within 24 months. One Conflict per topic = product + segment + account + purpose + flags (jumbo merged) + term; tiers and rate + APY share it. Topic defined by the newest crawl that shows it: values (winners first, as written), resolution (each winning value + row label + rate-sheet page), reason (reason codes in words + other crawls), sources (winner + stale pages) | 5 |
| system.py | TemporalKnowledgeBase: ingest (store + resolve + per-crawl indexes), answer() routes link / prose / rate / retrieval; forecasts declined; before the first crawl -> `known_by` + a note, else "cannot tell" (D5); between crawls -> `as_of` (cached per day); conflicts() / conflict_records() over all crawls; never crashes (errors -> refusal / []) | 0, 3, 5, 6 |

Tools and docs: `tools/explore.py` (overview, track [--by-date], history, diff, tables, tablestats, evidence, facts
[--jsonl], resolve [--conflicts], changes, prose [--kind --subject]); `eval/heldout_eval.jsonl` (55) and
`eval/heldout2_eval.jsonl` (20), `eval/heldout3_eval.jsonl` (64: paraphrase groups, dates before / on / between / after crawls, tiers, unsupported, conflicts across crawls) and `eval/heldout4_eval.jsonl` (24, written after the Phase 6 fixes and scored once): our own held-out questions, same format as the public set, values read from the raw pages; `docs/RULES.md` (evidence E1-E27, rules R1-R26, open decisions D1-D9,
design review + reason codes); `docs/EDGE_CASES.md` (checklist, ~60 handled+tested); `.cursor/rules/project.mdc`; `pyrightconfig.json`.

## Status
- **Blind set D** (30 q, ChatGPT, fresh session, written as real members after all fixes; keys and quotes checked;
  frozen 460adec, SHA-256 ec054df8b5a2): **first run on d13a1a7: rules 0.6729, LLM 0.7153 (p95 2.45 s)**, kept in
  `eval/blind_D_first_run_*`. After D67-D68: rules 0.7065, LLM 0.8624. Latest live LLM runs (replayed with the
  last rule): public 0.9535, A 0.9708, B 0.7375, B1 0.7146, C 0.9812, D 0.8624; p95 2.2-3.2 s (B1 4.2 s).
- **Blind set C** (40 q, ChatGPT, fresh session, no scorer files, real stale-page traps; keys checked; frozen in
  33502c5, SHA-256 93aff33be051): **first run on a583f09: rules 0.5924, LLM 0.707 (p95 7.67 s)**, kept in
  `eval/blind_C_first_run_*` (cdc6958). Closest to the public set in style; it showed the rules fitted to the public
  wording (0.969 there). After general fixes (D63-D66): rules 0.8396, LLM 0.9671.
- **Blind set B1** (40 q, Gemini with set B's prompt; it had seen the kit's scorer, not the code; frozen 4b3b804,
  SHA-256 8be53c7ad108): **first run on 0a94f6c: rules 0.4179, LLM 0.4592** (the breaker switched the LLM off after
  question 23), kept in `eval/blind_B1_first_run_*` (7c5a23d). Cause: thinking tokens cut replies off (D61). With only
  that fixed: 0.6012. After D63-D66: rules 0.4846, LLM 0.7146. Ids reuse blind-b-0xx (separate file, never edited).
- **Latest live LLM runs (thinking off, time budget):** public 0.9535 (rules 0.969: one honest decline, one wording),
  A 0.9875, B 0.7333, B1 0.7146, C 0.9671; p95 2.5-3.2 s. Conflicts unchanged (16, 10/10 on our key).
- **Blind set B** (40 q, outside model, fresh session, master prompt; keys checked; frozen in commit ab4f105, SHA-256
  45745cf66d12): **first run 0.4042** (final 0.3923), kept in `eval/blind_B_first_run.jsonl` (22537e31) + report
  (0aa094d8). Strong on history (0.75), weak on the long tail (product distinctions 0.04): insurance, account rules,
  business services, fee details, declines. Retrieval recall@5 on B only 14/34 (on older sets search was not the
  bottleneck - corrected). The kit README allows LLMs and keys; "stdlib, no LLM" had been our own choice.
- **Phase 9, optional LLM layer** (Anthropic, Haiku; off without ANTHROPIC_API_KEY): step 1 the LLM reads the KIND of
  question (interpret.py); step 1b/1c fixed its regressions found by replaying a recorded live run; step 2 grounded
  answers from verified facts + passages with deterministic checks (grounded.py); step 2b fixed checks found by replay;
  step 3 circuit breaker + kept-alive connection. Recorded-run results: public 0.969 (= rules), A 0.9542, B 0.7583,
  **0 questions worse than rules-only on any set**; no-key answers unchanged word for word. Live p95 2.4-2.6 s.
- **Blind set A** (40 q, written by an outside model from the raw pages, keys checked against the snapshots, frozen
  in commit 7ef5077 by SHA-256 5b414740aa9c): **first run 0.4958** (final 0.4521), kept in
  `eval/blind_first_run.jsonl` (9332c285) + report (953a7dae). After quick fixes (D38-D45): 0.7542, paraphrase
  consistency 0.0 -> 1.0. Two-part answers (D46-D49): 0.9042. All other sets, conflicts (final 0.9494) and all 244
  older answers unchanged word for word. Left: 003 (coverage 0.39 vs 0.4, not tuned), 005 (credit-score / LTV
  requirement in prose), 025 (second fact in another paragraph), 031/032 ("24-hour ATM" service not in the
  address answer), 034 ("four individuals" vs key "4"). Set A is now a development set; a sealed batch B (if
  written) is the next honest number.
- **Third review (after Phase 7), all four findings confirmed and fixed:** "Can I see my balance?" was answered
  (blanket "Can I" exemption) -> declined, how-to questions still answered (D34); an APY question about an APR-only
  product silently got the APR -> the measure asked for is required, the answer says what is published (D35); a later
  edit of a page the earlier crawl saw could replace it between crawls -> only pages that crawl did not see are
  added (D36); citations named the crawl the date picked (5.39% from crawl 05 cited as 04) -> each fact carries the
  crawl it was read from (D37). Every score unchanged (public 0.969 / final 0.9494, all sets as before); 9 citations
  moved to the crawl holding the evidence; 7 mortgage answers lost a doubled "rate". 16 focused tests
  (tests/test_review3.py), each fix mutation-checked. Frozen files byte-identical. Public copy: tools/build_public.py.
- **Independent evaluation (the honest number): 0.72 on its first and only blind run** (25 questions written by the
  user from raw pages, SHA-256 checked; `eval/independent_first_run.jsonl` + report kept unchanged). Misses: a
  contrast ("rather than the APY"), "volunteer hours" read as opening hours, a fee routed to card rates, two
  member-specific questions ("my balance", "approved for me"), a blog outranking the product page, an address
  outside the branch list. After six general fixes: 1.0 - but from here on the independent set is a DEVELOPMENT
  set too. Our own sets scored 1.0 before it; the gap (1.0 vs 0.72) is the best estimate of unseen-question risk.
  Second review, manual audit: in-18 names Hillcrest only; in-21 gives 170 for 2024 alone; in-23 says the schedule
  lists "Price varies"; in-24/25 decline member data while "How can I check my balance?" is answered. Known
  limitation: in-22 names Figo but cites the blog (not /personal/insurance) and adds one loosely related sentence.
- Tests: 340 passing (incl. test_llm_layer and test_blind_c; fake model only; the LLM is forced off in tests), run with
  TKB_STRICT=1 (internal errors raise); every rule added in
  Phase 6 is mutation-checked (switching it off fails a test). Phase 6 rules each mutation-checked (between-crawl evidence,
  forecasts, year-only dates, both measures, non-product prices, per-crawl conflict evidence). Mutation-checked: switching off the FAQ rule, the narrowest-tier
  rule, the prose window or the rate + APY topic merge fails tests. test_conflicts scores with harness score_conflicts.
- basedpyright (Cursor's checker, standard mode): 0 errors in submission/, tests/, tools/.
- Scorer (real harness, Python 3.11, with `--conflicts-gold eval/conflicts_gold.json`): final public 0.949 (qa 0.969)
  | heldout 0.960 (qa 0.982) | heldout2 0.976 (qa 1.0) | heldout3 qa 0.883 -> 1.0 after the Phase 6 fixes | heldout4 (fresh) qa 1.0 | heldout5 (combined constraints, review) first run 0.4375 kept in
  `eval/heldout5_first_run.jsonl` -> 1.0; conflicts 16 submitted, 10/10 matched, precision 0.625,
  F1 0.769, resolution accuracy 1.0; 0 errors; consistency 1.0; p95 0.05 s; ingest ~10-15 s. Public misses: dup-005 only (empty must_include: 0 for anyone).
  Held-out miss: ho-045 (mobile wallets: the answer is in a collapsed FAQ that was never crawled) - left on purpose.
- HIDDEN SET: conflicts gold unknown. Our 16 topics cover every planted stale copy we found (auto calculator +
  switch-and-earn, homebuying-guidance, mortgage-refi, promo landing page, business-rates, press releases); the risk is
  precision if the hidden gold is smaller, or recall if it counts pure rate changes between crawls (D11).
- Harness self-test conflicts: 0/1 - its toy pages state rates in prose lines ("6-month certificate APY: 3.50%"),
  which we only read from tables. The real crawls have no such lines; not handled on purpose.
- Prose: 31 verdicts per crawl, 0 ties; byline dates for 420-431 articles per crawl (1 miss: a blog hub page).
  Verdicts match practice questions 073 074 075 076 087 088 054 068 (branches 22, Hy-Vee 2026-03-31 -> Key West
  and Sycamore Street, Forbes fifth, VTO 2024 = 256 / 2023 = 294, routing 273974581, Galena address).
- Facts per crawl: 730, 772, 770, 798, 862. Slots per crawl: 274, 274, 276, 283, 291; 0 unresolved ties.
- Resolver verdicts match every table-rate practice question (001 009 011 016 017 028 035 045 046 049 050 052,
  006 as of May), now end to end through answer() and the real scorer.

## Key rules (full list with evidence in docs/RULES.md)
- R1 fact key = product + segment + account + purpose + flags + attribute + term + tier kind; tiers compete only if they overlap.
- R2 newest effective date wins, BEFORE page authority (E1, E17: a trusted product page carried a year-old rate sheet).
- R3 tie-break by authority: rate_sheet = product > other > pdf > promo = calculator = press > blog.
- R4 prose facts: newest publish date wins, never majority (E4: "23 branches" x42 vs "22" x37; 22 is current).
- R5 as_of -> newest crawl on/before the date. R6 ranges by containment; term not offered -> not available.
- R8 only winning values in answer text. R9 entity mentioned but attribute missing -> refuse.
- R13 URL variants: freshest fetch wins. R17 same value re-dated is not a change. R20 links: only current Dupaco URLs.
- R21 year-labelled facts (VTO 2023 vs 2024) are different facts; ambiguous "last year" -> give newest + previous, labelled.
- R22 a cell's own measure ("5.34% APR") overrides the header. R23 nested "or less" tiers -> narrowest.
- R24 business if row/heading says so or URL starts with /business.
- R25 deposit row with dividend rate > APY loses ties (E27 typo). R26 slot pairing; tier only on older tables -> superseded.
- R27 an undated official page (/contact) speaks as of its fetch date; dated pages as of their byline (prose, R4).
- Abstain only when NO evidence exists (abstaining on an answerable question scores 0).

## Decisions (D1-D70)
Open: D2 a rate whose effective date is after as_of (not seen in the data; not handled).
Decided in Phase 3: D3 no model year -> list every tier, newest first · D4 answers use the as_of crawl (refined by D15) ·
D6 prose outliers: newest statement wins (R4), so assets = $3.6 billion · D7 "last year" -> newest year and the one
before, labelled (VTO 2024 = 256, 2023 = 294) · D9 citations: the topic's own page first; links: product page + "#rates"
· D10 hours: most common schedule + variants + "which branch?".
Decided in Phase 5: D1 Traditional vs Roth IRA = different keys, not a conflict (R1) · D8 relabelled term with equal
values = not a conflict (R17) · D11 a value that changed between crawls with no stale page left behind is history,
not a conflict (E19; costs recall if the graders count it) · D12 one Conflict per product + term (tiers, rate + APY,
jumbo merged) for precision · D13 prose conflicts only for branch count, Forbes and assets, losers within 24 months of
the newest statement (members / employees: the newest boilerplate is not extracted, so their "newest" is years old) ·
D14 URL-variant copies (R13 shadowed) are the same page, not a conflict.
Decided after the Phase 6 review: D18 a date and a model year / amount in one question are both kept (dates are
blanked before reading the model year) · D19 fee / minimum questions are searched first and answered only from a
sentence that states a $ amount without a % (short fee-schedule rows are indexed); numbers about the company
(stock price, salary, revenue) are declined · D20 internal errors are logged and counted (`kb.errors`), and raise
under TKB_STRICT=1 (the tests) · D21 conflict grouping kept per topic: against a per-topic gold 0.838 vs 0.477 for
per-slot; against a per-tier gold 0.419 vs 0.417 (never worse) · D22 heldout/heldout2/heldout3 are DEVELOPMENT sets
(tuned on); the independent check is a set written by the user before seeing answers.
Decided in Phase 6: D5 before the first crawl -> answer only from evidence dated on or before the day (with a
note), else "cannot tell" (no digits) · D15 between crawls, a later crawl's table effective on or before as_of
overrides (it proves the change already happened) · D16 "not offered" answers name where the term IS offered
(ho-006 and h3-t07 disagreed; kept the Phase 3 decision) · D17 forecasts are declined.
Decided after the independent set (first blind run 0.72): D23 a measure after "rather than / instead of / not the" is
excluded · D24 "how many ... hours" is a count, not opening hours · D25 member-specific data ("my balance", "approved
for me") is declined · D26 a product question is a fee question only when it says "fee" · D27 list items carry their
"In 2024 alone:" intro; a passage naming only other years ranks lower; the earliest-paragraph rule needs equal
coverage · D28 an address of a named place outside the branch list is read from the text (form words such as "street
address" do not count towards coverage).
Decided after the second review: D29 "how can I check my balance" is guidance, not member data · D30 opening-hours
words beat "how many ... branch" (an older bug) · D31 fee answers: "no fee" / "Free" count; "Price varies" is
explained, not a generic refusal; a fee answer must not name a different product; form words (exact, dollar, using)
do not count towards coverage · D32 of several matching branches, the one naming the most question words · D33 a
second passage must fit the year, share the key word and cover >= 0.8 of the lead. Rules with no measurable effect on
the data or the tests were removed.
Decided after the third review: D34 a request for one's own data is declined however it is phrased ("Can I see my
balance?"); only how / where / which-channel questions are guidance (supersedes the "can I" part of D29) · D35 the
measure named in the question is required; if a product lacks it, say which measure it publishes (no digits) · D36
as_of between crawls adds later prose only from pages the earlier crawl did not observe; tables still need a newer
effective date on or before the day · D37 every fact keeps the crawl it was read from, and citations use it; the
requested date only picks the crawl.
Decided after blind set A: D38 "the <date> website" is a date, not a link request · D39 a named branch with
"locator" / "24-hour ATM" is an address question; "24-hour" is not opening hours · D40 a rate AND its minimum is
a rate lookup (the minimum part waits for two-part answers) · D41 a date next to article / announcement / release /
published names a document: not the as-of date; retrieval is restricted to pages published that day, the passage
covering most of the question first · D42 a variant after not / non / without / rather than is excluded · D43 "I
personally" is member data; "will" + a date after the newest crawl is a forecast · D44 Launchpad is matched before
IRA; "what happens if" is an explanation, not a rate lookup; a term + "special" with no product is a certificate ·
D45 function words (if, into, someone, according, whole, each) and date words are not topic words; "how much
space / time" is not money. D46 a rate question comparing two values of ONE slot (two terms, two amounts, two
as-of dates) is split into one lookup per value and the answers joined (dates labelled "On <date>:", each part
cited from its own crawl); a range ("between $X and $Y") is one value · D47 two measures named anywhere in the
question (not after a contrast word) -> both measures · D48 a rate table's Min. to Open / Min. to Earn cell is kept
on each fact (never resolved or compared) and added when the question asks for a minimum · D49 two fees compared
(compared with / versus) -> two different schedule rows; the same amount twice counts once; a conditional yes/no
question ("Can it pay dividends if I ...?") is a rule of the account (retrieval). A dedupe of identical parts was
tried and removed: no case needed it once ranges counted as one value.
Decided in Phase 9 (LLM layer): D50 optional, behind ANTHROPIC_API_KEY; no key = rules-only, unchanged; TKB_LLM=off
forces it off; standard library transport (urllib / http.client), no package · D51 the LLM reads the KIND of question
(route, products from our list, decline reason, search words); rules keep numbers, dates, terms, tiers; every field
validated · D52 an LLM decline cannot override a branch/company fact the rules found; a link the rules found stands; a
question asking FOR an unpublished rate is still declined · D53 the LLM's search words are a second attempt only
(adding them to the first search changed which passage won - found by replaying the recorded live run) · D54 a rules
rate + an LLM "explain" reading gives the rate AND the text · D55 G4 narrowed: only sentences quoting a RATE (named, or
a row of 2+ percentages) are withheld; fee and down-payment percentages pass · D56 history: a later table replaces a
crawl's evidence only when its value differs (same value cites the crawl of that day) · D57 grounded answers: only for
explain / fee routes; every number in the cited passages (text, page address, publish date), the facts or the question,
or a difference of two cited amounts; every rate a verified fact; a citation required unless the answer is made of
verified facts; "doesn't state" first = a decline; "the evidence" -> "the Dupaco website" · D58 no temperature (the
model rejects it): same answer within a run via the cache, may differ between runs · D59 record / replay
(TKB_LLM_CACHE): a live run is recorded once and replayed offline for analysis, without the key · D60 circuit breaker
(3 failures in a row -> LLM off for the run), 8 s per call, one kept-alive HTTPS connection (urllib when a proxy is
set). Parallel reading + writing calls was not done: it would change the evidence and the answers before set C.
D61 thinking off by default (Haiku 5.5 thinks unless told not to; thinking counts against max_tokens and cut off 13 of
51 replies on B1); TKB_LLM_THINKING=on adds 2,000 tokens of room; measured B1 off 0.6012 p95 2.9 s / on 0.6646 p95
7.0 s · D62 an unusable reply (cut off, no JSON, a refusal) is not an outage: it does not count towards the breaker;
5 in a row switch the LLM off · D63 numbers written as words (1-99, "grand", "thousand"); "not an APR" / "before the
APY" set a measure aside; "fixed conventional" / "N-year fixed" is a mortgage · D64 a list after its lead line is
also indexed as one passage; points and payment-example columns kept and shown when asked; branch services and the
P.O. box mailing address; a cash-out refinance table is its own purpose (it had been read as a stale copy) ·
D65 LLM overrides narrowed: a personal-quote decline does not override a published rate for a named product; a prose
fact the rules found stands when the written answer is missing or says "not stated"; "does not describe" is a decline
· D66 time budget per question: reading 3 s, writing what is left of 6 s (skipped under 1 s); each call's own
timeout on the kept-alive connection. D67 an LLM decline (personal quote, needs info, member data) is overridden only
when the question names a measure (APR / APY / rate) of a named product; "eligible" means membership only with
joining words; a branch can be named first ("Flint Hill branch - address?"); stand-alone ATMs from the locator have
addresses; the member's words fill 5 evidence slots and the LLM's search words the last 3 · D68 a written answer
that says "not stated" ("does not contain") is replaced by the rules' verified fact when the rules have one (a prose
fact, or a rate for a named product on an explain reading). D69 outside review before publishing: a verified rate must be
quoted under its own measure (2.23% dividend rate is not "2.23% APY"); one answer per (question, as_of, mode) per
run, cleared by ingest; a part of a multi-part question the site does not answer is said, not dropped; model fields
of the wrong type (products, cited) are ignored. No recorded answer changed (replay and word-for-word). D70 second
review: a question naming a balance, amount or model year gives the LLM only that tier's facts (untiered products in
the question stay), so another tier's value cannot pass; a question about a published example or illustration is not
a personal quote; a mid-sentence line (PDF wrap) is never an answer. Rules-only scores unchanged on every set.
Public release: a NEW repository built by tools/build_public.py from an
allow-list, scanned for 12-word site passages (test fixtures were reworded to pass), one commit, no old history.

## Next phases
1. **Blind sets A (50) and B (30)** written by an outside model from the raw pages (prompt + page pack kept outside
   the repo), frozen by checksum; A run once after these fixes and its first run kept; B sealed until all fixes are
   done, then reported as the generalisation number.
2. **Submit** - this repository stays private (its history holds eval outputs and the evidence file, which quote
   the site). For anything public: `python tools/build_public.py ../dupaco-tkb-public`, check it prints
   `"copied_site_passages": 0`, then `git init` + one commit there. `.gitignore` alone cannot remove committed files.
   Final step: fresh-copy run of `submission/` on 3.9 and 3.11.
3. **4 LLM layer: skipped by design.** Rules are deterministic (consistency 1.0), fast (p95 0.05 s) and need no API
   key. An LLM fallback for question shapes no rule covers (the independent set's 0.72) is the natural next step if
   network access and a key were allowed.
4. **Phase 7 done:** `submission/NOTES.md` (results led by the 0.72 blind run, rules, guardrails, conflicts, limits);
   `requirements.txt` (stdlib only); fresh-copy run of `submission/` alone on Python 3.9 and 3.11 (same scores, 0
   errors, ingest ~18 s); 194 tests on 3.9 and 3.11; docs backlog folded into RULES.md (E28-E34, R27, D1-D9 decided)
   and EDGE_CASES.md (all statuses point at a test; section H for Phase 6).

## Practice-set map (40 questions)
Table rates: 001 005 006 009 011 016 017 028 035 045 046 050 052 · lists: 034 040 · ids/addresses: 054 055 068 ·
hours: 064 065 066 104 · events/time: 073 074 075 076 087 088 · links: 008 080 082 · false premise: 049 ·
explanations: 031 060 081 094 101 · refuse: 102 145 147.

## Docs backlog
Empty: everything was folded into docs/RULES.md (evidence E28-E34, rule R27, decisions D1-D9) and docs/EDGE_CASES.md
(statuses + section H) in Phase 7.

## Working agreement
- Format per phase: Goal, Learn, Build (files in order), Run, Check, Commit, Send me.
- Code is delivered in chat, step by step, as WHOLE files (also sent as files) with a command to verify each step;
  no zip files.
- The assistant tests every module in its own workspace (unit tests, all 5 crawls, basedpyright, real scorer)
  before handing it over; the user creates the files, runs everything in Cursor, and commits.
- Environment: macOS, Cursor, uv venv with Python 3.11 (`source .venv/bin/activate`), pytest.
- Every rule traces to evidence; every behaviour gets a test naming its edge case.
- PROJECT_STATE.md is updated every phase; RULES.md / EDGE_CASES.md were updated in batches (backlog now empty).
