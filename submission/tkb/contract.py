"""The types that cross the boundary to the scorer (Answer, Source, Conflict).

Why not just define our own copies?  Because of one line in harness/run_eval.py, in the
repeat-consistency pass:

    text = a2.text if isinstance(a2, Answer) else (... str(a2))

If we return a look-alike class, the harness scores `str(answer)` - the dataclass repr, full of
URLs and snapshot ids like "05_2026-09-28" - and every repeat check fails. So we reuse the
harness's own `contract` module when it is loaded (it always is when the scorer runs us) or can
be found in a parent folder, and only fall back to local copies when neither is true.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _load_harness_contract():
    mod = sys.modules.get("contract")
    if mod is not None and all(hasattr(mod, n) for n in ("Answer", "Source", "Conflict")):
        return mod
    for d in Path(__file__).resolve().parents:
        path = d / "harness" / "contract.py"
        if path.exists():
            spec = importlib.util.spec_from_file_location("contract", path)
            if spec is None or spec.loader is None:      # cannot load it: use the local fallback types
                return None
            mod = importlib.util.module_from_spec(spec)
            sys.modules["contract"] = mod
            spec.loader.exec_module(mod)
            return mod
    return None


_harness = _load_harness_contract()

if _harness is not None:
    Answer = _harness.Answer
    Source = _harness.Source
    Conflict = _harness.Conflict
else:  # standalone use (unit tests, notebooks) - same fields as harness/contract.py

    @dataclass
    class Source:  # type: ignore[no-redef]
        url: str
        snapshot_id: Optional[str] = None
        quote: Optional[str] = None

    @dataclass
    class Answer:  # type: ignore[no-redef]
        text: str
        sources: list = field(default_factory=list)
        confident: bool = True
        conflict_note: Optional[str] = None

    @dataclass
    class Conflict:  # type: ignore[no-redef]
        topic: str
        values: list
        sources: list
        resolution: Optional[str] = None
        reason: Optional[str] = None
