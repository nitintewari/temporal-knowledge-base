"""Phase 0 tests: contract wiring, versioned store, as_of selection, refusal safety."""
# store.view() returns None before any ingest; these tests always ingest first, so reading
# attributes straight off the result is intended (a None would fail the test, as it should).
# pyright: reportOptionalMemberAccess=false
import re
from types import SimpleNamespace as NS

import pytest

from tkb.store import VersionStore
from tkb.system import REFUSAL, TemporalKnowledgeBase


def page(url, md, fetched="2026-01-01T00:00:00Z", title="t"):
    return NS(url=url, title=title, markdown=md, fetched_at=fetched)


def snap(sid, day, pages):
    return NS(snapshot_id=sid, taken_on=day, pages=pages)


S1 = snap("01_jan", "2026-01-05", [page("https://x.test/rates", "6-month 2.95% APY"),
                                   page("https://x.test/gone", "old page")])
S2 = snap("02_mar", "2026-03-01", [page("https://x.test/rates", "6-month 3.50% APY"),
                                   page("https://x.test/new", "new page")])


def test_answer_is_the_harness_class():
    contract = pytest.importorskip("contract")  # harness/contract.py (kit, not public)
    from tkb import contract as ours
    assert ours.Answer is contract.Answer
    assert ours.Source is contract.Source
    assert ours.Conflict is contract.Conflict


def test_refusal_has_no_digits_and_is_flagged():
    assert not re.search(r"\d", REFUSAL)
    ks = TemporalKnowledgeBase()
    assert ks.answer("What is the 7/1 ARM rate?").confident is False


def test_calls_before_ingest():
    ks = TemporalKnowledgeBase()
    assert ks.answer("anything").confident is False
    assert ks.conflicts() == []


def test_versions_are_kept_and_deduplicated():
    st = VersionStore()
    st.add_snapshot(S1)
    st.add_snapshot(S2)
    st.add_snapshot(snap("03_apr", "2026-04-01", [page("https://x.test/rates", "6-month   3.50% APY")]))
    hist = st.history["https://x.test/rates"]
    assert [v.markdown.split()[1] for v in hist] == ["2.95%", "3.50%"]   # extra spaces ≠ new version
    assert hist[1].seen_in == ["02_mar", "03_apr"]


def test_page_presence_per_snapshot():
    st = VersionStore()
    st.add_snapshot(S1)
    st.add_snapshot(S2)
    assert "https://x.test/gone" in st.view("2026-01-31").pages
    assert "https://x.test/gone" not in st.view().pages
    assert "https://x.test/new" in st.view().pages


def test_as_of_selection():
    st = VersionStore()
    st.add_snapshot(S1)
    st.add_snapshot(S2)
    assert st.view(None).snapshot_id == "02_mar"                    # no date -> latest
    assert st.view("2026-02-15").snapshot_id == "01_jan"            # between two crawls
    assert st.view("2026-03-01").snapshot_id == "02_mar"            # same day counts
    assert st.view("2025-06-01").snapshot_id == "01_jan"            # before the first crawl
    assert st.view("2027-01-01").snapshot_id == "02_mar"            # after the last crawl
    assert st.view("2026-02-15T23:59:59Z").snapshot_id == "01_jan"  # date with a time part


def test_out_of_order_and_duplicate_ingest():
    st = VersionStore()
    st.add_snapshot(S2)
    st.add_snapshot(S1)
    assert [s.snapshot_id for s in st.snapshots] == ["01_jan", "02_mar"]
    assert st.add_snapshot(S1) is None
    assert len(st.snapshots) == 2


def test_empty_page_fields():
    st = VersionStore()
    st.add_snapshot(snap("01", "2026-01-01", [NS(url="https://x.test/e", title=None, markdown=None, fetched_at=None)]))
    v = st.view().pages["https://x.test/e"]
    assert v.markdown == "" and v.title == "" and v.fetched_at == "2026-01-01"

def test_unchanged_page_keeps_each_crawls_own_fetch_date_R13_R27():
    """Phase 6 fix: same text in May and September is ONE stored version, but TWO observations. Before the fix the
    September view reported May's fetch time (408 of 705 pages in snapshot 05)."""
    contact = "# Contact Us\n\n**Routing Number:** 273974581\n"
    st = VersionStore()
    st.add_snapshot(snap("01_may", "2026-05-12", [page("https://www.dupaco.com/contact", contact, "2026-05-12T10:00:00Z")]))
    st.add_snapshot(snap("05_sep", "2026-09-28", [page("https://www.dupaco.com/contact", contact, "2026-09-28T03:00:00Z")]))
    may, sep = st.view("2026-05-31").pages, st.view().pages
    url = "https://www.dupaco.com/contact"
    assert may[url].version is sep[url].version                                   # text and facts stored once
    assert len(st.history[url]) == 1 and st.history[url][0].seen_in == ["01_may", "05_sep"]
    assert (may[url].fetched_at, sep[url].fetched_at) == ("2026-05-12T10:00:00Z", "2026-09-28T03:00:00Z")
    assert st.history[url][0].fetches == {"01_may": "2026-05-12T10:00:00Z", "05_sep": "2026-09-28T03:00:00Z"}
    assert sep[url].markdown == contact and sep[url].snapshot_id == "05_sep"     # reads like a PageVersion
    # R27: an undated official page speaks as of the day THIS crawl fetched it
    stated = st.resolutions["05_sep"].find_prose("routing_number")[0].winner.stated
    assert stated == "2026-09-28"
