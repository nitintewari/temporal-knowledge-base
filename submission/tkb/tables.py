"""Markdown table parser: one page -> a list of structured tables (Phase 2A).

For each table we keep everything later steps need to turn rows into facts:
  header   - column names (they define what each column means, R16)
  rows     - data rows, as lists of cleaned cell strings
  context  - the nearest non-empty lines ABOVE the table, nearest first; the product name often
             lives there instead of in the table (E8, E16, R18)
  effective / effective_all - the table's effective date(s) (R15, E17, E21)

Nothing here knows about products or rates; it only finds tables reliably.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .normalize import clean_text, squash_spaces

# "Rates are effective as of 08/31/2026", "effective 1/1/2026", "effective as of 6/2/26"
EFFECTIVE_RE = re.compile(r"effective\s+(?:as\s+of\s+)?(\d{1,2})/(\d{1,2})/(\d{2,4})", re.I)

# E21: a footnote line starts with its footnote number glued to the text: "1Rates are effective as of ...".
FOOTNOTE_LINE_RE = re.compile(r"^\W*\d{1,2}[A-Za-z]")

# Cell separators are pipes that are NOT escaped with a backslash.
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_SEPARATOR_CELL = re.compile(r":?-{3,}:?")

# How far we look around a table. Bounded on purpose (see the docstrings below).
CONTEXT_MAX_LINES = 25     # lines scanned upwards for headings
CONTEXT_KEEP = 3           # non-empty context lines kept, nearest first
DATE_MAX_LINES = 30        # lines scanned downwards for the effective date


@dataclass
class Table:
    index: int                                   # position of the table on its page, 0-based
    header: list                                 # cleaned header cells
    rows: list                                   # cleaned data rows (list of lists of str)
    context: list = field(default_factory=list)  # nearest non-empty lines above, nearest first
    effective: Optional[str] = None              # ISO date (R15), None if undated
    effective_all: list = field(default_factory=list)  # every date found (logged if >1 distinct)
    line_start: int = 0                          # 0-based line numbers on the cleaned page
    line_end: int = 0                            # exclusive


def to_iso(month: str, day: str, year: str) -> Optional[str]:
    """('1', '1', '26') -> '2026-01-01'. Returns None for impossible dates instead of crashing."""
    y = int(year)
    if y < 100:
        y += 2000
    try:
        return date(y, int(month), int(day)).isoformat()
    except ValueError:
        return None


def split_row(line: str) -> list:
    """'| a | b \\| c |' -> ['a', 'b | c']: split on unescaped pipes, clean every cell."""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    cells = _CELL_SPLIT.split(text)
    return [squash_spaces(c.replace("\\|", "|").replace("**", "")) for c in cells]


def is_separator(cells: list) -> bool:
    """The '| --- | :---: |' line under a markdown header."""
    return bool(cells) and all(_SEPARATOR_CELL.fullmatch(c.replace(" ", "")) for c in cells)


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def find_context(lines: list, start: int, prev_end: int) -> list:
    """Nearest non-empty, non-table lines above `start`, never crossing the previous table.

    Empty lines are skipped (E16: the heading can be 10 lines above, separated by blank lines).
    The scan is bounded so a table never picks up a heading from far up the page.
    """
    found = []
    stop = max(prev_end, start - CONTEXT_MAX_LINES)
    for k in range(start - 1, stop - 1, -1):
        text = squash_spaces(lines[k].replace("**", "").lstrip("#").strip())
        if not text or _is_table_line(lines[k]):
            continue
        if EFFECTIVE_RE.search(text):        # a date line belongs to the table ABOVE, not a heading
            continue
        found.append(text)
        if len(found) == CONTEXT_KEEP:
            break
    return found


def find_effective(lines: list, end: int, next_start: int) -> list:
    """Effective dates after a table and before the next table (R15), main caption dates first.

    Stopping at the next table is what prevents a table from borrowing its neighbour's date (E17).
    The extra line limit protects the last table on a page from picking up an unrelated date far below.
    Footnote lines ("1Rates are effective as of ...", E21) come AFTER caption dates in the result, so a
    caption date wins when both exist, but a table whose only date is a footnote is still dated.
    """
    main, footnotes = [], []
    stop = min(next_start, end + DATE_MAX_LINES, len(lines))
    for k in range(end, stop):
        line = lines[k]
        bucket = footnotes if FOOTNOTE_LINE_RE.match(line.strip()) else main
        for m in EFFECTIVE_RE.finditer(line):
            iso = to_iso(*m.groups())
            if iso:
                bucket.append(iso)
    return main + footnotes


def parse_tables(markdown: str) -> list:
    """Every markdown table on a page, in page order, with context and effective date."""
    lines = clean_text(markdown).splitlines()

    # 1. Locate table blocks: runs of consecutive lines starting with "|".
    blocks = []
    i = 0
    while i < len(lines):
        if _is_table_line(lines[i]):
            j = i
            while j < len(lines) and _is_table_line(lines[j]):
                j += 1
            blocks.append((i, j))
            i = j
        else:
            i += 1

    # A "layout" block has an empty header row: a box of bullet points used for page design, not data.
    # It must not stop the heading search for the table below it ("Business 1st Rate Checking Account"
    # sits above such a box on /business/business-checking-accounts, Phase 2C check).
    layout = [not any(split_row(lines[s])) for s, _ in blocks]

    # 2. Turn each block into a Table.
    tables = []
    for n, (start, end) in enumerate(blocks):
        raw = [split_row(lines[k]) for k in range(start, end)]
        if len(raw) >= 2 and is_separator(raw[1]):
            header, body = raw[0], raw[2:]
        else:                                   # no separator line: treat the first row as the header
            header, body = raw[0], raw[1:]
        body = [r for r in body if not is_separator(r) and any(c for c in r)]
        if not any(header) and body:            # empty header row, real header in the first data row
            header, body = body[0], body[1:]

        prev = n - 1
        while prev >= 0 and layout[prev]:       # look through layout boxes for the heading
            prev -= 1
        prev_end = blocks[prev][1] if prev >= 0 else 0
        next_start = blocks[n + 1][0] if n + 1 < len(blocks) else len(lines)
        dates = find_effective(lines, end, next_start)
        tables.append(Table(
            index=n,
            header=header,
            rows=body,
            context=find_context(lines, start, prev_end),
            effective=dates[0] if dates else None,
            effective_all=dates,
            line_start=start,
            line_end=end,
        ))
    return tables
