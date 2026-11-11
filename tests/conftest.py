"""Make `tkb` (submission/) and the harness `contract` module importable in tests.

Tests run with TKB_STRICT=1: an internal error raises instead of turning into a polite refusal, so a bug can never
pass a test by looking like "the website doesn't say" (Phase 6 review)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "submission", ROOT / "harness"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ["TKB_STRICT"] = "1"
os.environ["TKB_LLM"] = "off"          # Phase 9: tests never call the network, even with a key set; LLM tests inject a fake
