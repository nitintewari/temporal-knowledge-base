"""A/B timing of the two LLM transports: one kept-alive connection vs a fresh urllib request per call.

    python tools/latency_ab.py            # 20 calls each, alternating, so API speed changes hit both equally

Each call is a tiny request (a few tokens), so the time measured is network + API overhead, not model writing.
Reads ANTHROPIC_API_KEY from the environment only; never prints it. Costs a fraction of a cent.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "submission"))

from tkb.llm import API_VERSION, DEFAULT_MODEL, KEY_ENV, MODEL_ENV, _KeepAlive, _urllib_post  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20


def main() -> int:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        print("ANTHROPIC_API_KEY is not set in this terminal")
        return 1
    model = os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL
    headers = {"content-type": "application/json", "x-api-key": key, "anthropic-version": API_VERSION}
    transports = {"keep-alive": _KeepAlive(headers).post, "urllib": _urllib_post(headers)}
    times: dict = {name: [] for name in transports}
    errors: dict = {name: 0 for name in transports}
    for i in range(N):
        order = list(transports) if i % 2 == 0 else list(reversed(list(transports)))
        for name in order:
            body = json.dumps({"model": model, "max_tokens": 5, "system": "Reply with the word OK.",
                               "messages": [{"role": "user", "content": f"Say OK ({i})"}]}).encode("utf-8")
            started = time.perf_counter()
            try:
                transports[name](body)
                times[name].append(time.perf_counter() - started)
            except Exception as e:  # noqa: BLE001 - a timing tool: count and continue
                errors[name] += 1
                print(f"{name} call {i}: {type(e).__name__}")
    for name, ts in times.items():
        if not ts:
            print(f"{name:10s} no successful calls")
            continue
        ts_sorted = sorted(ts)
        p90 = ts_sorted[max(0, int(round(0.9 * len(ts_sorted))) - 1)]
        print(f"{name:10s} calls {len(ts):2d}  first {ts[0]:.2f}s  median {statistics.median(ts):.2f}s  "
              f"p90 {p90:.2f}s  max {max(ts):.2f}s  errors {errors[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
