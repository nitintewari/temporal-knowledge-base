# NOTES: Temporal knowledge base for the Dupaco snapshots

## Setup

**Without `ANTHROPIC_API_KEY` the submission runs rules-only** (the default, no network). The LLM mode needs a key
set in the environment of the run; it is better on unseen questions (the blind sets below).

Two modes, same entry point (`submission/solution.py` -> `build()` -> `TemporalKnowledgeBase`, code in
`submission/tkb/`):

| Mode | How | What it needs |
|---|---|---|
| **Rules only** (default) | nothing to set | Python 3.9+ standard library. No key, no network, no packages. |
| **Rules + LLM** | `export ANTHROPIC_API_KEY=...` | The same, plus network access to `api.anthropic.com`. Still no packages (`urllib` / `http.client`). |

- `TKB_LLM=off` forces rules-only even with a key (for comparison). `TKB_LLM_MODEL` overrides the model
  (default `claude-haiku-5-5`). `TKB_LLM_CACHE=<file>` records every LLM reply, so a run can be replayed offline.
  `TKB_LLM_THINKING=on` lets the model think before replying (default off: see "Thinking" below).
- Ingest of all five snapshots: about 10-20 s, no LLM calls. Answering: p95 0.05 s rules-only. With the LLM
  (one call to read the question, a second for answers written from text): p95 2.1-2.9 s in the final live run
  of all six sets. Each question has a time budget: reading it gets at most 3 s, a written
  answer what is left of 6 s (skipped under 1 s, so that question gets the rules answer) - two slow API calls had
  pushed set C's p95 to 7.7 s. One kept-alive connection
  measured faster than a new request per call (`tools/latency_ab.py`, 20 calls each, alternating: median 0.67 s
  vs 0.77 s, p90 0.87 s vs 1.03 s, 0 errors).
- If the API fails, times out or returns something unusable, that question gets the rules answer. After 3
  failed calls in a row (network, timeout, HTTP error), or 5 unusable replies in a row, the LLM is switched off for
  the rest of the run, so an outage cannot stall every answer. `python tools/llm_check.py <eval file>` prints every
  failure with the API's own message.

**Thinking.** Claude Haiku 5.5 thinks before replying unless told not to, and thinking counts against the reply
limit. On blind set B1 (long multi-part questions) 13 of 51 replies were cut off before their JSON was complete;
the first version counted those as an outage, and the breaker switched the LLM off after question 23. Now thinking
is off by default and a cut-off reply is not an outage. Measured on B1: thinking off 0.6012 (p95 2.9 s), thinking on
with room for it 0.6646 (p95 7.0 s). The speed credit falls from p95 2 s to 20 s, so 7 s costs about as much as the
accuracy gains on B1. On the public set the two questions that changed between the modes were borderline readings,
since handled by rule (below). Off is the default; a set of long multi-part questions would favour on.

## Results (measured with the kit's own scorer, `harness/run_eval.py`)

**Blind first runs - the numbers that predict unseen questions.** Each set was written by someone (or a model) that
had not seen the code, its answer key was checked against the snapshots, and it was frozen by SHA-256 in a commit
before its one and only run. The first-run outputs are kept unchanged in `eval/*first_run*`.

| Blind set | Questions | Written by | First run, rules only | First run, rules + LLM |
|---|---|---|---|---|
| Independent | 25 | separately, from raw pages | **0.72** | - |
| A | 40 | an outside model, from the raw pages | **0.4958** | - |
| B | 40 | an outside model, fresh session, master prompt | **0.4042** | - |
| B1 | 40 | a second outside model, set B's prompt; it had seen the kit's scorer, not our code | **0.4179** | **0.4592** (the LLM was switched off after question 23, see "Thinking"; with only that fixed: 0.6012) |
| C | 40 | an outside model, fresh session, after the code was frozen; real stale-page traps | **0.5924** | **0.707** (p95 7.67 s: two slow API calls) |
| D | 30 | the same model, fresh session, written as real members after all earlier fixes | **0.6729** | **0.7153** (p95 2.45 s) |

Set C is the closest to the public set in style (same 9 categories, short questions, traps taken from real stale
pages), and the most telling: it scored 0.59 / 0.71 against 0.969 on the public set, which showed the rules were
fitted to the public set's wording. What it tripped on was basic - "seventy-two-month", "fifteen grand", "an APY,
not an APR", a list after "including:", a lost card - not hard reasoning. Set D, written the same way after those
fixes, is the latest honest number: 0.67 rules-only / 0.72 with the LLM on questions no fix had seen, up from C's
0.59 / 0.71. Its misses were again general (an LLM decline overriding a published APY, "eligible" read as
membership, a branch named first in the question, stand-alone ATMs, search words) and were fixed after the run.

**Development scores - after fixing what those runs found** (these measure the fixes, not generalisation). One live
run of the final code (the commit before this notes update), every set in both modes, nothing replayed:

| Set | Rules only | Rules + LLM (p95) |
|---|---|---|
| Public practice set (40, kit authors) | **0.969** (final 0.949, conflicts scored against our own key) | 0.9225 (2.1 s) |
| Blind set A (after its fixes) | 0.9208 | 0.9708 (2.1 s) |
| Blind set B (after its fixes) | 0.4292 | 0.75 (2.5 s) |
| Blind set B1 (after its fixes) | 0.5117 | 0.7029 (2.9 s) |
| Blind set C (after its fixes) | 0.8396 | 0.9788 (2.6 s) |
| Blind set D (after its fixes) | 0.7065 | 0.8406 (2.7 s) |

The LLM column moves by a question or two between runs (the model takes no temperature setting): across the last
four live runs of this code path, public 0.92-0.95, B 0.74-0.77, B1 0.68-0.71, C 0.95-0.98, D 0.83-0.87; the final
score with the LLM on the public set (with conflicts) was 0.91-0.94. Rules-only is identical on every run.
| Independent set / own held-out sets 1-5 | 1.00 / 0.98-1.00 | - |

**How to read this.** Each fresh set found question shapes nobody had written for: the independent set "rather than"
and "my balance"; set A two things in one question (a rate and its minimum, two balances, two dates); set B the long
tail beyond rate tables - insurance, account rules, business services, fee details, and questions to decline; set
B1 long multi-part questions and a cash-out refinance table read as a stale copy; set C plain wording (numbers in
words, "not an APR", lists, mailing address, branch services, payment examples, a lost card). Fixes
were general rules, each with a test that fails without it, and every older answer was re-checked word for word after
every step. Set B also showed the limit of rules: the long tail of wording. That is what the optional LLM layer is
for, and it is why the LLM is used for reading questions and wording answers, never for deciding values.

The one public miss (dup-005) has an empty answer key; the development miss ho-045 asks about content behind a
collapsed FAQ that was never crawled.

## How it works

```
ingest(snapshot)                     answer(question, as_of)                         conflicts()
  store every page version             parse the question (rules)                      every crawl's losing values
  (text once, fetch time per crawl)    [LLM: correct the KIND of question]             grouped per product + term
  extract facts from tables + prose    pick the crawl for the date                     winner + reason + sources
  resolve each fact per crawl  ----->  + later crawls' dated evidence
  build retrieval indexes              look up the resolved fact, or retrieve text
                                       [LLM: write a text answer from facts + passages,
                                        used only if every check passes]
                                       compose the answer under guardrails
```

| Module | Job |
|---|---|
| `store.py` | Every page version per URL; identical text stored once; each crawl keeps its own fetch time. |
| `tables.py`, `values.py`, `facts.py` | Markdown rate tables -> typed facts: product, segment, account, purpose, flags, measure (rate / APR / APY / dividend), term, tier (model year, balance, loan amount), effective date, the row's minimum to open / earn. |
| `prose.py` | Facts stated in text: branch count, routing number, addresses, hours, closures, assets, Forbes ranking, founding year... with the page's publish date. Boilerplate removed first. |
| `resolve.py` | Decides what is current, per crawl, with a reason code for every loser. |
| `query.py` | Question -> intent and slots (product, measure, term, tier value, date, comparison parts...). |
| `retrieve.py` | BM25 over cleaned paragraphs (and fee-schedule rows) for questions no fact answers; a link index. |
| `compose.py` | Writes the answer from the winning value only; declines when nothing supports one. |
| `conflicts.py` | Builds the conflict list from the resolver's verdicts. |
| `llm.py` | Optional: the API client (cache, timeout, circuit breaker, one kept-alive connection, record / replay). |
| `interpret.py` | Optional: the LLM's reading of the kind of question (route, products, decline reason, search words). |
| `grounded.py` | Optional: an LLM answer from verified facts + passages, with deterministic checks. |

## What "current" means (the main rules)

Full list with evidence: `docs/RULES.md` (R1-R27) and `docs/PROJECT_STATE.md` (decisions D1-D71). The core:

1. **A fact is a key, not a string**: product + measure + term + qualifiers + tier. Different tiers, rate vs APY,
   standard vs jumbo, Roth vs Traditional are different facts, never conflicts.
2. **Same fact, different values -> the latest effective date wins**; then page authority (rate sheet > product page >
   other > PDF > promo / calculator / press > blog); then an internally consistent row beats a typo (rate above APY).
3. **Text facts**: the newest publication wins; an undated official page counts as of the day it was fetched.
4. **as_of D** uses the newest crawl on or before D, corrected by later crawls whose tables were already effective on D
   with a different value (a table "effective 08/31" seen on 09-28 proves the rate on 09-01; the same value keeps the
   crawl of that day as evidence). A page the earlier crawl already saw is the record of that day: a later edit of it
   does not replace it. Before the first crawl, only evidence dated that early answers, with a note.
5. **Tiers**: the question's model year, balance or amount picks the narrowest containing tier; a tier the newest
   table dropped is "not offered", never answered with a neighbour's rate.
6. **Citations name the crawl each fact came from**; the requested date only decides which crawl is used.

## Answer guardrails

- The answer text holds only winning values; losing values (stale copies) go to `conflict_note`, never the text.
- Refusals contain no digits and set `confident=False`, with the reason: the price *varies*, the site *doesn't
  publish* it, it publishes *another measure* ("an APR, not an APY"), *member data*, a *forecast*, and - with the LLM -
  *needs your details*, *live availability*, a *personal quote*, or *the site doesn't state it*.
- A sentence quoting a rate (a % named APR / APY / rate / dividend, or a row of rates) is never quoted from text: a rate
  in prose may be stale; rates come from resolved tables. Other percentages (a fee, a down payment) are quoted.
- Links come only from URLs present in the crawl; never constructed.
- A line cut from the middle of a sentence (a PDF wrapped at the page width) is never an answer on its own.
- A question asked twice in a run gets the same answer (cached per question and date; a new crawl clears it), even
  if the LLM failed the first time. In a question with several parts, a part the site does not answer is said.
- Internal errors never crash the scorer's run: they become a refusal, but are logged and counted in `kb.errors`, and
  the test suite runs with `TKB_STRICT=1` so any exception fails a test.

### What the LLM may and may not do

| The LLM may | The LLM may not |
|---|---|
| say what KIND of question it is (rate, branch, explanation, fee, link, decline + why) | choose which value is true (the resolver does) |
| name products, only from our fixed list | override a fact the rules found (a branch closure, a link) with a decline |
| rewrite the question in the website's words (3 of the 8 evidence passages; the member's words get the first 5) | replace the member's own search words |
| write a text answer from the facts and passages it is given | state a number that is not in the cited evidence or the question (a difference of two cited amounts is allowed) |
| say a part is not stated (becomes a decline) | quote a rate that is not a verified fact - even one in a cited passage |
| | quote a verified rate under another measure (2.23% dividend rate as "2.23% APY") or from another tier: a question naming a balance, amount or model year gets only that tier's facts |

Every LLM answer is checked deterministically before use; a failed check keeps the rules answer, and a fact the
rules found in the site's text (membership, an address) stands when the written answer says the site doesn't state
it; the same for a verified rate when the written answer about its conditions says "not stated". Measured question by
question against rules-only on the previous live run: public 0 better / 1 worse, A 3 / 0, B 16 / 1, B1 12 / 0, C 7 / 0,
D 7 / 1. The worse: "How can I update my contact information?" is now declined (the site has no steps; the
rules-only answer is an unrelated sentence plus the phone number, which the key happens to want: picking text by
word overlap is the rules mode's weakest point); one answer
said "Monday through Friday" where the key wants the site's "Monday-Friday"; and "thirty grand over five years: the
monthly amount in the car-loan illustration?" was declined as a personal quote (since fixed: a question about a
published example or illustration is not a personal quote).
The model takes no temperature setting, so a borderline reading can change between runs.

## Conflicts

One `Conflict` per product + segment + purpose + term ("60-month auto loan APR"), built from the resolver's losers
in the same crawl: stale calculator and promo pages, a mortgage guidance page with April rates, press releases with
old branch counts, a typo row. A rate that simply changed between crawls is history, not a contradiction. The newest
crawl showing a conflict decides `values` and `resolution`; every earlier crawl's evidence stays in `reason` and
`sources`. The LLM is not used for conflicts.

Grouping per topic was measured, not assumed: against an answer key written per topic it scores 0.838 vs 0.477 for
one-conflict-per-tier; against a per-tier key the two tie (0.419 vs 0.417). The risk we accept: if the graders also
count plain rate changes between crawls as conflicts, recall drops.

## Known limitations

- Rules-only: a question shape nobody wrote a rule for can be misread, and explanation answers are sentences picked
  by word overlap (set B: 0.4042 first run). The LLM layer addresses this; without a key it is off.
- Questions asking several things at once (set B1: "the intro APR, how long it lasts, and the APR after") often get
  the first part only from the rules; the LLM covers some. A fee stated only inside a long footnote (the Rewards Visa
  foreign transaction fee) is not found.
- With the LLM: answers can differ slightly between runs (the model takes no temperature setting); within a run the
  same question gets the same answer. The checks reject some correct answers on purpose (a rate cap quoted in prose).
- Search is keyword-based (BM25). Measured: when the answer was crawled, the evidence is in the top 25 passages for
  most questions; insurance and credit-limit questions in set B were missed. Semantic search was not added.
- Rates stated only in prose are not extracted, so the kit's toy self-test (`harness/selftest`) scores 0.2.
- Our conflicts answer key was written by us (it is not published), so 10/10 there checks our intent only.

## Reproduce

Tests need nothing but this repository:

```bash
pip install pytest && pytest -q        # 341 tests, about 1 s; the LLM is always off in tests (fake model)
```

Scoring needs the event kit, which is not part of this repository (its website crawls belong to the event). Put this
repository's `submission/` folder in the kit's root, next to `harness/`, `snapshots_zip/` and `eval/`, then from the
kit's root:

```bash
TKB_LLM=off python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl   # rules only
python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl              # + LLM if a key is set
```

The scorer unpacks the crawls on first run. The final scores quoted above add `--conflicts-gold <file>` with a
conflicts key we wrote ourselves (not part of the kit or this repository), so their conflicts part checks our intent
only; without the option the scorer reports the other parts. With a key, `python tools/llm_check.py
eval/public_eval.jsonl` (run from the kit's root with this repository's `tools/`) prints every LLM failure with the
API's own message, and `python tools/latency_ab.py` times the two connection methods.

Design history, decisions and evidence: `docs/PROJECT_STATE.md`, `docs/RULES.md`, `docs/EDGE_CASES.md`.
