"""Build a clean public copy of this project and check it holds no copied website text.

    python tools/build_public.py ../dupaco-tkb-public

1. Copies an ALLOW-LIST of our own work (code, tests, docs, notes) into the target folder. Nothing else goes in:
   no snapshots, no kit datasets or answer keys, no eval outputs, no evidence file, no kit harness.
2. Scans every copied file for passages of 12+ consecutive words that also appear in any snapshot page
   (the snapshots stay local: they are read from snapshots/ or snapshots_zip/ here, never copied).
3. Prints every hit with file and line, and exits 1 if any remain, so nothing is published by accident.

The target is a NEW folder: `git init` it and make one commit, so no old history comes along (.gitignore cannot
remove what earlier commits already hold).
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW = ["submission/solution.py", "submission/tkb", "submission/NOTES.md", "tests", "docs", "tools/explore.py",
         "tools/build_public.py", "tools/llm_check.py", "tools/latency_ab.py", "requirements.txt", "requirements-dev.txt", "pyrightconfig.json", ".gitignore",
         ".python-version"]
SKIP = re.compile(r"__pycache__|\.pyc$|\.pytest_cache|\.DS_Store")
N = 12                                            # words in a row that count as a copied passage
WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")

README = """# Temporal knowledge base

Answers questions about a credit union's website from **five dated crawls of it**: what a rate, fee, branch or
policy is, what it **was** on a given day, and where the site **contradicts itself** (a calculator page with an old
rate, a press release with an old branch count). Every answer names its source page and crawl.

Python standard library only - no packages, no database. Two modes:

| Mode | How | Measured with the scorer provided |
|---|---|---|
| **Rules only** (default) | nothing to set; never calls the network | public practice set: accuracy 0.969, p95 0.04 s (final score 0.949 with conflicts scored against our own key) |
| **Rules + LLM** | `export ANTHROPIC_API_KEY=...` (Claude Haiku) | blind sets, first runs: +0.04 to +0.12 accuracy over rules-only (+0.05 to +0.32 after fixes); public set 0.92-0.95, a little below rules-only; p95 2-3 s |

No key is stored in this repository. Without one, the rules-only mode runs.

## A worked example

| Question | `as_of` | Answer (abridged) |
|---|---|---|
| What is the APY on the 10-month certificate special? | today | 3.90% APY (effective 09/01/2026) - crawl of 2026-09-28 |
| the same | 2026-05-12 | 3.80% APY (effective 03/03/2026) - crawl of 2026-05-12 |
| What's the APR on a 60-month auto loan for a 2025 car? | today | 5.39% APR (effective 08/31/2026). Not used: 5.34% on the loan calculator and a promo page, effective 2026-01-01 (stale copies) |
| How many branches does Dupaco have? | today | 22, per the newest press release (May 5, 2026). Not used: 23 in three older releases |

`conflicts()` lists 16 such contradictions, grouped by topic ("60-month auto loan APR"), each with the winning
value, the reason, and every page and crawl involved.

## How it works

```mermaid
flowchart LR
    S[Five dated crawls] --> V[Versioned page store<br/>each page per crawl]
    V --> F[Facts from rate tables and text<br/>product + measure + term + tier]
    F --> R[Resolver: which value is current<br/>effective date, then page authority,<br/>then a consistent row]
    R --> A[answer question, as_of]
    R --> C[conflicts: the losing values<br/>with their reasons]
    V --> T[Search index per crawl<br/>for questions no fact answers]
    T --> A
```

**What "current" means.** A fact is a key, not a string: a 60-month auto loan APR for model years 2024-27 is a
different fact from the 2021-23 one, and an APY is not a dividend rate. For one key, the latest effective date wins;
then page authority (rate sheet over product page over promo or calculator); then an internally consistent row over
a typo. Text facts (a branch count) go to the newest publication. For a past date, the crawl of that day is used,
corrected by later crawls whose tables were already effective that day.

### The optional LLM: it reads and words, it never decides values

```mermaid
flowchart TD
    Q[Question] --> P[Rules parse it]
    Q --> L[LLM reads the kind of question<br/>rate, branch, explanation, fee, decline]
    P --> M{Rules have a<br/>verified fact?}
    L --> M
    M -- yes --> F[Answer from the resolved fact]
    M -- explanation --> W[LLM writes an answer from<br/>verified facts + cited passages]
    W --> K[Deterministic checks: cited passages,<br/>every number grounded, each rate a verified<br/>fact of the same measure and tier]
    K --> D{All pass?}
    D -- yes --> OK[Written answer]
    D -- no --> F2[Rules answer]
```

The LLM never chooses which value is true, cannot override a fact the rules found, and cannot quote a rate from
prose (it may be stale). If the API is slow, fails or replies badly, that question gets the rules answer; repeated
failures switch the LLM off for the run. Each question has a time budget, and a repeated question gets the same
answer.

## How it was evaluated

Beyond the 40-question practice set, the system was tested on **blind sets written by outside models that had not
seen the code**. Each set's answer key was checked against the crawls, and the set was frozen by SHA-256 in a commit
**before its one and only first run**; those first runs are kept unchanged. Fixes came after, as general rules with a
test that fails without them, and every older answer was re-compared word for word after each change.

| Blind set | First run, rules only | First run, rules + LLM | After its fixes (rules / LLM) |
|---|---|---|---|
| A (40) | 0.50 | - | 0.92 / 0.97 |
| B (40, rare topics) | 0.40 | - | 0.43 / 0.75 |
| B1 (40, multi-part) | 0.42 | 0.46 | 0.51 / 0.70 |
| C (40, practice-set style) | 0.59 | 0.71 | 0.84 / 0.98 |
| D (30, written after all earlier fixes) | **0.67** | **0.72** | 0.71 / 0.84 |

The first-run columns are the honest estimate for questions nobody tuned for; the last column measures the fixes.
Set D, written after C's fixes, scored higher on its first run than C did - the fixes carried over to new questions.

## Limitations

- Rules-only text answers are chosen by word overlap: where the site has no answer, the chosen text can be unrelated.
- Questions asking several things at once often get only the first part from the rules.
- With the LLM, an answer can differ slightly between runs (the model takes no temperature setting).

## More

- `submission/NOTES.md` - setup, all results, guardrails, limitations
- `docs/RULES.md`, `docs/PROJECT_STATE.md`, `docs/EDGE_CASES.md` - every rule and decision, with its evidence
- Tests: `pip install pytest && pytest -q` (the two that need the scoring harness are skipped without it)

The website crawls and evaluation datasets were provided for the event and are not included.
"""


def words(text: str) -> list:
    return WORD.findall(text.lower())


def snapshot_texts():
    for d in sorted((ROOT / "snapshots").glob("0*")):
        for f in sorted((d / "pages").glob("*")):
            yield f.read_text(encoding="utf-8", errors="ignore")
    if not any((ROOT / "snapshots").glob("0*")):
        for z in sorted((ROOT / "snapshots_zip").glob("*.zip")):
            with zipfile.ZipFile(z) as zf:
                for n in zf.namelist():
                    if n.endswith(".md"):
                        yield zf.read(n).decode("utf-8", errors="ignore")


def site_shingles() -> set:
    seen: set = set()
    for text in snapshot_texts():
        w = words(text)
        seen.update(hash(tuple(w[i:i + N])) for i in range(len(w) - N + 1))
    if not seen:
        sys.exit("No snapshots found in snapshots/ or snapshots_zip/: cannot check. Nothing was built.")
    return seen


def copy(target: Path) -> list:
    out = []
    for item in ALLOW:
        src = ROOT / item
        if not src.exists():
            continue
        files = [src] if src.is_file() else sorted(p for p in src.rglob("*") if p.is_file())
        for f in files:
            rel = f.relative_to(ROOT)
            if SKIP.search(str(rel)):
                continue
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            out.append(dst)
    (target / "README.md").write_text(README, encoding="utf-8")
    out.append(target / "README.md")
    return out


def scan(files: list, site: set, target: Path) -> list:
    hits = []
    for f in files:
        for no, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            w = words(line)
            if any(hash(tuple(w[i:i + N])) in site for i in range(len(w) - N + 1)):
                hits.append(f"{f.relative_to(target)}:{no}: {line.strip()[:110]}")
    return hits


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    target = Path(sys.argv[1]).expanduser().resolve()
    if target == ROOT or ROOT in target.parents:
        sys.exit("The target must be OUTSIDE this repository (a new folder).")
    if target.exists() and any(target.iterdir()):
        sys.exit(f"{target} is not empty. Use a new folder.")
    site = site_shingles()
    files = copy(target)
    hits = scan(files, site, target)
    print(f"Copied {len(files)} files to {target}")
    print(json.dumps({"files": len(files), "copied_site_passages": len(hits)}))
    for h in hits:
        print("  HIT", h)
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
