"""Diagnostic: answer every question of an eval file with the LLM on, then print what the LLM layer did.

    python tools/llm_check.py eval/blind_eval_B1.jsonl

Prints the number of calls, every failure with the API's own message (never the key), and whether the circuit
breaker tripped. This is a diagnostic re-run only; first-run results are never replaced by it.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "submission"))
sys.path.insert(0, str(ROOT / "harness"))

from run_eval import load_snapshots  # noqa: E402
from solution import build  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/llm_check.py <eval.jsonl>")
        return 1
    items = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
    kb = build()
    for snap in load_snapshots(ROOT / "snapshots"):
        kb.ingest(snap)
    llm = getattr(kb, "llm", None)
    if llm is None:
        print("the LLM is off (no ANTHROPIC_API_KEY in this terminal, or TKB_LLM=off)")
        return 1
    seen = 0
    for i, it in enumerate(items, 1):
        started = time.perf_counter()
        kb.answer(it["question"], it.get("as_of"))
        took = time.perf_counter() - started
        new = llm.failures[seen:]
        seen = len(llm.failures)
        for purpose, error in new:
            print(f"q{i:02d} {it['id']}: {purpose} failed after {took:.2f}s: {error}")
    print(f"transport {llm.transport}, calls {llm.calls}, failures {len(llm.failures)}, "
          f"breaker {'TRIPPED' if llm.off else 'not tripped'}, seconds waiting {llm.seconds:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
