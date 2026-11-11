#!/usr/bin/env python3
"""Phase-1 data-study helper. Read-only, standard library only.

Run from the repo root after the scorer has unpacked the snapshots into snapshots/:

  python tools/explore.py overview
  python tools/explore.py track "60 Months" --url auto
  python tools/explore.py track "routing" --snap 05
  python tools/explore.py history /personal/loans/auto-motorcycle-loans
  python tools/explore.py diff /rates --old 04 --new 05
  python tools/explore.py tables /personal/loans/auto-motorcycle-loans --snap 05
  python tools/explore.py evidence            (list questions)  /  evidence <id>
  python tools/explore.py resolve --product auto --term 60 --year 2025
  python tools/explore.py resolve --conflicts --snap 04
  python tools/explore.py changes --old 04 --new 05 --product auto
  python tools/explore.py prose --kind branch_count          (prose verdicts: winner, agreeing pages, losers)
--snap / --old / --new take a snapshot-id prefix such as 01, 02 ... 05.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from dataclasses import asdict


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "submission"))
from tkb.classify import page_type, url_path  # noqa: E402  (same classifier the system uses)
from tkb.facts import extract_facts  # noqa: E402  (the system's real fact builder)
from tkb.tables import parse_tables
from tkb.resolve import changes, resolve_crawl  # noqa: E402  (the system's real resolver)
from tkb.prose import extract_prose  # noqa: E402  (the system's real prose extractor)
from types import SimpleNamespace
EFFECTIVE_RE = re.compile(r"effective\s+(?:as\s+of\s+)?(\d{1,2}/\d{1,2}/\d{2,4})", re.I)


INVISIBLE = {"\xa0": " ", "\u202f": " ", "\u2009": " ", "\u200b": ""}


@lru_cache(maxsize=None)
def read(file: str) -> str:
    text = Path(file).read_text(encoding="utf-8")
    for ch, rep in INVISIBLE.items():   # E15: invisible characters silently break text matching
        text = text.replace(ch, rep)
    return text


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
def short(url: str) -> str:
    """Path plus ?query and #fragment, so URL variants that url_path() merges stay visible."""
    p = urlparse(url)
    return (p.path or "/") + (f"?{p.query}" if p.query else "") + (f"#{p.fragment}" if p.fragment else "")

def load(root: Path) -> list:
    if not root.is_dir():
        sys.exit(f"{root} not found. Run the scorer once so it unpacks the snapshot zips.")
    snaps = []
    for d in sorted(p for p in root.iterdir() if (p / "manifest.json").exists()):
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        pages = {
            p["url"]: {
                "title": p.get("title", ""),
                "fetched_at": p.get("fetched_at", m["taken_on"]),
                "file": str(d / p["file"]),
            }
            for p in m["pages"]
        }
        snaps.append({"id": m["snapshot_id"], "taken_on": m["taken_on"], "pages": pages})
    if not snaps:
        sys.exit(f"No snapshot folders in {root}. Run the scorer once to unpack them.")
    return sorted(snaps, key=lambda s: s["taken_on"])


def pick(snaps: list, prefix, default_index: int):
    if not prefix:
        return snaps[default_index]
    found = [s for s in snaps if s["id"].startswith(prefix)]
    if not found:
        sys.exit(f"No snapshot id starts with {prefix!r}. Known: {[s['id'] for s in snaps]}")
    return found[0]


def match_url(pages: dict, frag: str):
    """Exact path match first ('/rates'), then a unique substring match ('auto-motorcycle')."""
    if frag.startswith(("/", "http")):
        want = url_path(frag)
        for u in pages:
            if url_path(u) == want:
                return u, []
    cands = sorted(u for u in pages if frag.lower() in u.lower())
    return (cands[0] if len(cands) == 1 else None), cands

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
PUB_RE = re.compile(rf"\b({MONTHS})\s+(\d{{1,2}}),\s+(20\d\d)\b")
MONTH_NUMBER = {name: number for number, name in enumerate(MONTHS.split("|"), start=1)}

def publish_date(lines: list) -> str:
    """Publish date of a press/blog page: the first 'Month D, YYYY' in its top 60 lines (R4).
    Checked on snapshot 05: found for 94 of the 97 pages that state a branch count."""
    for line in lines[:60]:
        m = PUB_RE.search(line)
        if m:
            name, day, year = m.groups(default="")
            return f"{year}-{MONTH_NUMBER.get(name, 0):02d}-{int(day):02d}"
    return "-"


def date_sort_key(field: str) -> str:
    """'eff=1/1/2026' or 'pub=2026-04-03' -> '2026-01-01' / '2026-04-03' so dates sort correctly."""
    value = field.split("=", 1)[1].replace("(above)", "")
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})$", value)
    if m:
        year = int(m.group(3))
        year = year + 2000 if year < 100 else year
        return f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return value          # already ISO, or "-" (undated sorts last)
def effective_near(lines: list, i: int) -> str:
    """Rate tables on this site put 'Rates are effective as of MM/DD/YYYY' just AFTER the table."""
    for k in range(i, min(len(lines), i + 25)):
        m = EFFECTIVE_RE.search(lines[k])
        if m:
            return m.group(1)
    for k in range(i - 1, max(-1, i - 10), -1):
        m = EFFECTIVE_RE.search(lines[k])
        if m:
            return m.group(1) + "(above)"
    return "-"


# ----------------------------------------------------------------------------- commands
def cmd_overview(snaps, args):
    prev = None
    for s in snaps:
        types = Counter(page_type(u) for u in s["pages"])
        fetched = sorted(p["fetched_at"][:10] for p in s["pages"].values())
        print(f"\n{s['id']}  taken_on={s['taken_on']}  pages={len(s['pages'])}  "
              f"fetched_at range {fetched[0]} .. {fetched[-1]}")
        print("   page types: " + ", ".join(f"{k}={v}" for k, v in types.most_common()))
        if prev:
            cur, old = set(s["pages"]), set(prev["pages"])
            common = cur & old
            raw = sum(read(s["pages"][u]["file"]) != read(prev["pages"][u]["file"]) for u in common)
            real = sum(norm(read(s["pages"][u]["file"])) != norm(read(prev["pages"][u]["file"])) for u in common)
            print(f"   vs {prev['id']}: new={len(cur - old)} gone={len(old - cur)} "
                  f"changed(raw)={raw} changed(ignoring whitespace)={real} of {len(common)}")
            for u in sorted(cur - old)[: args.max]:
                print(f"      + [{page_type(u)}] {short(u)}")
            for u in sorted(old - cur)[: args.max]:
                print(f"      - [{page_type(u)}] {short(u)}")      
        prev = s


def cmd_track(snaps, args):
    rx = re.compile(args.pattern, re.I)
    chosen = [s for s in snaps if not args.snap or s["id"].startswith(args.snap)]
    for s in chosen:
        hits = []
        for u, meta in sorted(s["pages"].items()):
            if args.url and args.url.lower() not in u.lower():
                continue
            lines = read(meta["file"]).splitlines()
            t = page_type(u)
            for i, line in enumerate(lines):
                m = rx.search(line)
                if not m:
                    continue
                # Prose pages have no effective date: show their publish date instead (R4).
                date = "pub=" + publish_date(lines) if t in ("press", "blog") else "eff=" + effective_near(lines, i)
                start = max(0, m.start() - 60)          # show the text AROUND the match
                snippet = ("..." if start else "") + line[start:].strip()
                hits.append((t, url_path(u), date, snippet))
        if args.by_date:
            hits.sort(key=lambda h: date_sort_key(h[2]), reverse=True)
        print(f"\n=== {s['id']}  ({len(hits)} matching lines)")
        for t, path, date, snippet in hits[: args.max]:
            print(f"  [{t:10s}] {path[:55]:55s} {date:21s} | {snippet[:150]}")
        if len(hits) > args.max:
            print(f"  ... {len(hits) - args.max} more (raise --max or narrow with --url)")


def cmd_history(snaps, args):
    for s in snaps:
        url, cands = match_url(s["pages"], args.url)
        if not url:
            extra = f" - {len(cands)} candidates, e.g. {[url_path(c) for c in cands[:5]]}" if cands else ""
            print(f"{s['id']}: not found{extra}")
            continue
        meta = s["pages"][url]
        text = read(meta["file"])
        effs = sorted(set(EFFECTIVE_RE.findall(text)))
        h = hashlib.sha1(norm(text).encode("utf-8")).hexdigest()[:8]
        print(f"{s['id']}: [{page_type(url)}] fetched_at={meta['fetched_at']} chars={len(text)} "
              f"hash={h} effective_dates={effs}")


def cmd_diff(snaps, args):
    a, b = pick(snaps, args.old, -2), pick(snaps, args.new, -1)
    ua, ca = match_url(a["pages"], args.url)
    ub, cb = match_url(b["pages"], args.url)
    if not ua or not ub:
        sys.exit(f"Page missing or ambiguous. Candidates: {[url_path(c) for c in (ca or cb)[:10]]}")
    old = read(a["pages"][ua]["file"]).splitlines()
    new = read(b["pages"][ub]["file"]).splitlines()
    out = list(difflib.unified_diff(old, new, a["id"], b["id"], n=1, lineterm=""))
    print("\n".join(out[: args.max]) if out else "identical")
    if len(out) > args.max:
        print(f"... {len(out) - args.max} more lines (raise --max)")


def cmd_tables(snaps, args):
    """Show a page's tables exactly as the system's parser (tkb/tables.py) sees them."""
    s = pick(snaps, args.snap, -1)
    url, cands = match_url(s["pages"], args.url)
    if not url:
        sys.exit(f"Page missing or ambiguous. Candidates: {[url_path(c) for c in cands[:10]]}")
    tables = parse_tables(read(s["pages"][url]["file"]))
    print(f"{s['id']}  {url}  [{page_type(url)}]  tables={len(tables)}")
    for t in tables:
        extra = f"  (other dates: {t.effective_all[1:]})" if len(set(t.effective_all)) > 1 else ""
        print(f"\n--- table {t.index + 1}: context={t.context[:2]} rows={len(t.rows)} effective={t.effective}{extra}")
        print("   HEADER: " + " | ".join(t.header))
        for row in t.rows[: args.max]:
            print("   " + " | ".join(row))
    if not tables:
        print("(no markdown tables on this page)")
def cmd_evidence(snaps, args):
    """For one practice question: on which pages do its RIGHT values and its TRAP values appear?"""
    path = ROOT / "eval" / "public_eval.jsonl"
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not args.qid:                                   # no id given -> list all questions
        for q in items:
            print(f"{q.get('id')}  [{q.get('category')}]  {q.get('question')}")
        return
    item = next((q for q in items if q.get("id") == args.qid), None)
    if item is None:
        sys.exit(f"No question {args.qid!r}. Run without an id to list them.")

    # Which crawl to search: --snap if given, else the question's as_of date, else the latest.
    if args.snap:
        s = pick(snaps, args.snap, -1)
    elif item.get("as_of"):
        day = str(item["as_of"])[:10]
        older = [x for x in snaps if x["taken_on"][:10] <= day]
        s = older[-1] if older else snaps[0]
    else:
        s = snaps[-1]

    print(f"{item.get('id')} [{item.get('category')}] {item.get('question')}")
    print(f"  searching snapshot {s['id']}" + (f"  (as_of {item['as_of']})" if item.get("as_of") else ""))
    for label, values in (("RIGHT", item.get("must_include") or []), ("TRAP ", item.get("must_not_include") or [])):
        for v in values:
            rx = re.compile(re.escape(str(v)), re.I)
            hits = []
            for u, meta in sorted(s["pages"].items()):
                lines = read(meta["file"]).splitlines()
                for i, line in enumerate(lines):
                    if rx.search(line):
                        hits.append((page_type(u), url_path(u), effective_near(lines, i)))
                        break                          # one hit per page is enough
            print(f"\n  {label} {v!r}: on {len(hits)} pages  {dict(Counter(t for t, _, _ in hits))}")
            for t, p, eff in hits[: args.max]:
                print(f"     [{t:10s}] {p[:60]:60s} eff={eff}")
    if item.get("should_refuse"):
        print("\n  This question SHOULD BE REFUSED: the answer is not on the site.")
def cmd_tablestats(snaps, args):
    """Run the parser over every page of one snapshot: tables, dates, two-date tables, layouts."""
    s = pick(snaps, args.snap, -1)
    pages_with = tables_n = rows_n = dated = 0
    multi, headers = [], Counter()
    for u, meta in sorted(s["pages"].items()):
        tables = parse_tables(read(meta["file"]))
        pages_with += bool(tables)
        for t in tables:
            tables_n += 1
            rows_n += len(t.rows)
            dated += t.effective is not None
            if len(set(t.effective_all)) > 1:
                multi.append((url_path(u), t.effective_all))
            headers[" | ".join(t.header)[:90]] += 1
    print(f"{s['id']}: pages with tables={pages_with}  tables={tables_n}  rows={rows_n}  "
          f"dated={dated}  undated={tables_n - dated}  layouts={len(headers)}")
    print(f"\ntables with two different dates ({len(multi)}):")
    for path, dates in multi:
        print(f"   {path}  {dates}")
    print(f"\nmost common layouts (top {args.max}):")
    for h, c in headers.most_common(args.max):
        print(f"   {c:4d}  {h}")

def fmt_range(r) -> str:
    """Range(2024, 2027) -> '2024..2027'; open ends stay empty: '..100000', '25000..'."""
    def num(v: float) -> str:          # 24999.99 -> "24999.99", 2024.0 -> "2024" (no rounding)
        return f"{v:.2f}".rstrip("0").rstrip(".")
    lo = "" if r.low is None else num(r.low)
    hi = "" if r.high is None else num(r.high)
    return f"{lo}..{hi}"


def cmd_facts(snaps, args):
    """Facts the system extracts from one crawl, with filters; --jsonl exports all of them for inspection."""
    s = pick(snaps, args.snap, -1)
    facts = [f for u, meta in sorted(s["pages"].items()) for f in extract_facts(read(meta["file"]), u, page_type(u))]

    def keep(f) -> bool:
        if args.product and args.product.lower() not in f.product:
            return False
        if args.attr and f.attribute != args.attr:
            return False
        if args.term is not None and f.term_months != args.term:
            return False
        if args.year is not None and not (f.tier_kind == "model_year" and f.tier is not None and f.tier.contains(args.year)):
            return False
        if args.amount is not None and not (f.tier_kind in ("balance", "loan_amount") and f.tier is not None
                                            and f.tier.contains(args.amount)):
            return False
        return not (args.url and args.url.lower() not in f.url.lower())

    hits = sorted((f for f in facts if keep(f)), key=lambda f: (f.effective or "", f.value.low), reverse=True)
    print(f"{s['id']}: {len(facts)} facts, {len(hits)} match")
    for f in hits[: args.max]:
        tier = "" if f.tier is None else f"{f.tier_kind}={fmt_range(f.tier)}"
        extra = ",".join(x for x in (f.segment if f.segment != "personal" else "", f.account or "",
                                     f.purpose or "", *f.flags) if x)
        print(f"  {f.value.text:15s} {f.product:24s} {f.attribute:13s} term={str(f.term_months):4s} {tier:26s} "
              f"{extra:18s} eff={f.effective}  [{f.page_type}] {url_path(f.url)}")
    if len(hits) > args.max:
        print(f"  ... {len(hits) - args.max} more (raise --max or add filters)")
    if args.jsonl:
        out = Path(args.jsonl)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for f in facts:
                fh.write(json.dumps(asdict(f)) + "\n")
        print(f"wrote {len(facts)} facts to {out}")        
@lru_cache(maxsize=None)
def resolved_for(snapshot_id: str, root: str):
    """Run the system's resolver over one crawl (the explorer's page dicts carry fetched_at + facts)."""
    snap = next(s for s in load(Path(root)) if s["id"] == snapshot_id)
    pages = {u: SimpleNamespace(fetched_at=m["fetched_at"],
                                facts=extract_facts(read(m["file"]), u, page_type(u)),
                                prose=extract_prose(read(m["file"]), u, page_type(u))[1])
             for u, m in snap["pages"].items()}
    return resolve_crawl(snapshot_id, pages)


def _keep_key(key: tuple, args) -> bool:
    product, _seg, _acct, _purpose, _flags, attribute, term, _kind = key
    if args.product and args.product.lower() not in product:
        return False
    if args.attr and attribute != args.attr:
        return False
    return args.term is None or term == args.term


def _where(c) -> str:
    return f"{c.path} eff={c.fact.effective} [{c.fact.page_type}]"


def cmd_resolve(snaps, args):
    """The resolver's verdict per slot: winner, how many pages agree, and every loser with its reason code."""
    s = pick(snaps, args.snap, -1)
    R = resolved_for(s["id"], str(args.snapshots))
    rows = [r for r in R.resolutions if _keep_key(r.key, args)
            and (args.year is None and args.amount is None
                 or (r.tier is not None and r.tier.contains(args.year if args.year is not None else args.amount)))
            and (not args.conflicts or r.losers or r.status != "current")]
    print(f"{s['id']}: {len(R.resolutions)} slots, {sum(bool(r.losers) for r in R.resolutions)} with losers, "
          f"{len(R.shadowed)} facts on stale URL variants (R13); showing {len(rows)}")
    for r in rows[: args.max]:
        key = "/".join(str(x) for x in r.key if x not in (None, ()))
        tier = "" if r.tier is None else fmt_range(r.tier)
        flag = "" if r.status == "current" else f"  ** {r.status.upper()} ({r.status_reason})"
        print(f"\n  {key} {tier}{flag}")
        print(f"    WIN  {r.value.text:10s} {_where(r.winner)}  (+{len(r.agree)} agreeing)")
        for loser in r.losers:
            print(f"    lose {loser.candidate.fact.value.text:10s} {_where(loser.candidate)}  {loser.reason}")
    if len(rows) > args.max:
        print(f"\n  ... {len(rows) - args.max} more (raise --max or add filters)")


def cmd_changes(snaps, args):
    """Value changes between two crawls, compared on resolved facts (E20), never on raw text."""
    old, new = pick(snaps, args.old, -2), pick(snaps, args.new, -1)
    found = [c for c in changes(resolved_for(old["id"], str(args.snapshots)),
                                resolved_for(new["id"], str(args.snapshots))) if _keep_key(c.key, args)]
    print(f"{old['id']} -> {new['id']}: {len(found)} changes")
    for c in found[: args.max]:
        key = "/".join(str(x) for x in c.key if x not in (None, ()))
        tier = "" if c.tier is None else fmt_range(c.tier)
        print(f"  {key} {tier}: {c.old.value.text if c.old else '(new)'} -> {c.new.value.text if c.new else '(gone)'}")


def cmd_prose(snaps, args):
    """Prose verdicts (R4): newest publication wins; every losing value with its date and reason code."""
    s = pick(snaps, args.snap, -1)
    R = resolved_for(s["id"], str(args.snapshots))
    kinds = sorted({r.key[0] for r in R.prose})
    if not args.kind:
        print(f"{s['id']}: {len(R.prose)} prose verdicts. Kinds: {', '.join(kinds)}")
        return
    rows = R.find_prose(args.kind, args.subject)
    print(f"{s['id']}: {len(rows)} verdicts for {args.kind}")
    for r in rows[: args.max]:
        w = r.winner
        sub = "/".join(x for x in r.key[1:] if x)
        print(f"\n  {sub}  [{w.fact.label}]")
        print(f"    WIN  {w.fact.value[:70]:30s} stated={w.stated} {w.path}  (+{len(r.agree)} agreeing)")
        for loser in r.losers[:8]:
            c = loser.candidate
            print(f"    lose {c.fact.value[:70]:30s} stated={c.stated} {c.path}  {loser.reason}")
        if len(r.losers) > 8:
            print(f"    ... {len(r.losers) - 8} more losers")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshots", type=Path, default=ROOT / "snapshots")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("overview", help="pages, page types, churn between crawls")
    p.add_argument("--max", type=int, default=15)

    p = sub.add_parser("track", help="follow a regex across every snapshot")
    p.add_argument("pattern")
    p.add_argument("--url", help="only URLs containing this text")
    p.add_argument("--snap", help="only snapshots whose id starts with this")
    p.add_argument("--max", type=int, default=40)
    p.add_argument("--by-date", action="store_true", help="newest date first")

    p = sub.add_parser("history", help="one page across all snapshots")
    p.add_argument("url")

    p = sub.add_parser("diff", help="what changed on one page between two snapshots")
    p.add_argument("url")
    p.add_argument("--old")
    p.add_argument("--new")
    p.add_argument("--max", type=int, default=80)

    p = sub.add_parser("tables", help="markdown tables on a page, with their effective dates")
    p.add_argument("url")
    p.add_argument("--snap")
    p.add_argument("--max", type=int, default=30)

    p = sub.add_parser("evidence", help="where a practice question's right and trap values appear")
    p.add_argument("qid", nargs="?", help="question id; omit to list all questions")
    p.add_argument("--snap")
    p.add_argument("--max", type=int, default=12)
    p = sub.add_parser("tablestats", help="parser summary for one snapshot: tables, dates, layouts")
    p.add_argument("--snap")
    p.add_argument("--max", type=int, default=15)
    p = sub.add_parser("facts", help="facts the system extracts from one crawl (filters, JSONL export)")
    p.add_argument("--snap")
    p.add_argument("--product", help="substring of the product, e.g. auto, certificate, mortgage")
    p.add_argument("--attr", help="apr, apy, dividend_rate or rate")
    p.add_argument("--term", type=int, help="term in months")
    p.add_argument("--year", type=int, help="model year that must fall inside the tier")
    p.add_argument("--amount", type=float, help="balance or loan amount that must fall inside the tier")
    p.add_argument("--url", help="only facts from URLs containing this text")
    p.add_argument("--max", type=int, default=25)
    p.add_argument("--jsonl", help="also write ALL facts of the crawl to this file")
    for name, helptext in (("resolve", "the resolver's winner and losers per fact slot"),
                           ("changes", "resolved values that changed between two crawls")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--product")
        p.add_argument("--attr")
        p.add_argument("--term", type=int)
        p.add_argument("--max", type=int, default=40)
        if name == "resolve":
            p.add_argument("--snap")
            p.add_argument("--year", type=int)
            p.add_argument("--amount", type=float)
            p.add_argument("--conflicts", action="store_true", help="only slots with losers or not current")
        else:
            p.add_argument("--old")
            p.add_argument("--new")
    p = sub.add_parser("prose", help="prose verdicts: branch count, Forbes, VTO, routing, addresses, hours, closures")
    p.add_argument("--kind", help="omit to list the kinds")
    p.add_argument("--subject", help="e.g. galena, hy-vee, 2023")
    p.add_argument("--snap")
    p.add_argument("--max", type=int, default=20)
    args = ap.parse_args()
    snaps = load(args.snapshots)
    {"overview": cmd_overview, "track": cmd_track, "history": cmd_history,
     "diff": cmd_diff, "tables": cmd_tables, "evidence": cmd_evidence,
     "tablestats": cmd_tablestats, "facts": cmd_facts, "resolve": cmd_resolve,
     "changes": cmd_changes, "prose": cmd_prose}[args.cmd](snaps, args)

if __name__ == "__main__":
    main()
