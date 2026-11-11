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
         "tools/build_public.py", "requirements.txt", "requirements-dev.txt", "pyrightconfig.json", ".gitignore",
         ".python-version"]
SKIP = re.compile(r"__pycache__|\.pyc$|\.pytest_cache|\.DS_Store")
N = 12                                            # words in a row that count as a copied passage
WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")

README = """# Temporal knowledge base

Answers questions about a credit union's website from five dated crawls, keeps track of what was true when,
and reports where the site contradicts itself. Python standard library only; no packages to install.

**Two modes, chosen by one environment variable:**

| Mode | How | Measured (kit scorer) |
|---|---|---|
| Rules only (default) | nothing to set | public set 0.969, p95 0.04 s; blind sets lower (see NOTES) |
| Rules + LLM | `export ANTHROPIC_API_KEY=...` (Claude Haiku via the Anthropic API) | better on unseen questions (blind sets +0.05 to +0.34); public set 0.92-0.95; p95 about 2-3.5 s |

Without a key the submission runs rules-only and never calls the network. With a key, the LLM only reads
questions and words answers from checked evidence; every value still comes from the rules, and any failure
falls back to the rules answer. No key is stored in this repository.

- How it works, results and limitations: `submission/NOTES.md`
- Rules and decisions with their evidence: `docs/`
- Tests: `pip install pytest && pytest -q` (tests that need the event's scoring harness are skipped without it)

The website snapshots and evaluation datasets belong to the event and are not included.
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
