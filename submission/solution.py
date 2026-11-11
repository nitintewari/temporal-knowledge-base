"""Entry point the scorer loads.

The harness does:  ks = build();  ks.ingest(snapshot) x5 (oldest first);  ks.answer(q, as_of);  ks.conflicts()
All real logic lives in the `tkb` package next to this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from tkb.system import TemporalKnowledgeBase  # noqa: E402


def build() -> TemporalKnowledgeBase:
    return TemporalKnowledgeBase()
