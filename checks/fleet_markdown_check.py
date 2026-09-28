#!/usr/bin/env python3
"""Fleet markdown deliverable checker.

Verifies a markdown deliverable against the requirements a Ringer manifest
check encodes: a required H1 title, an ordered list of ``##`` sections, a set
of required terms, and a minimum word count. This is the executable
Adversarial-Reviewer gate for docs/research lanes.

The fleet's markdown-lane manifests invoke it as:

    python3 fleet_markdown_check.py \\
        --file <file.md> \\
        --title '<H1 title>' \\
        --sections '<A|B|C|D>' \\
        --terms '<t1|t2|t3>' \\
        --min-words <N>

Exit codes (mirrors the Ringer check contract):
    0  PASS — every requirement satisfied
    1  FAIL — one or more requirements unmet (each reported on stderr)
    2  ERROR — the checker could not run (missing file, bad args)

Deliberately strict, deliberately simple: headings must match exactly (H1 is
``# <title>``, sections are ``## <name>``), sections must appear in the given
order, terms are case-insensitive substrings anywhere in the document, and
the word count is whitespace-split tokens of the whole file. A worker cannot
pass by writing filler — every axis is a real, checkable property.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


def split_pipe(value: str) -> list[str]:
    """Split a pipe-separated manifest field, dropping empty segments."""
    return [part.strip() for part in value.split("|") if part.strip()]


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fleet_markdown_check.py",
        description="Check a markdown deliverable for a required H1 title, "
        "ordered ## sections, required terms, and a minimum word count.",
    )
    parser.add_argument("--file", required=True, help="path to the markdown file (absolute or taskdir-relative)")
    parser.add_argument("--title", required=True, help="required H1 title text")
    parser.add_argument("--sections", required=True, help="pipe-separated ## section names, in required order")
    parser.add_argument("--terms", required=True, help="pipe-separated terms that must each appear")
    parser.add_argument("--min-words", type=int, default=0, help="minimum whitespace-split word count")
    args = parser.parse_args(argv)

    path = Path(args.file)
    if not path.is_file():
        fail(f"deliverable not found: {args.file}")
        return EXIT_ERROR
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {args.file}: {exc}")
        return EXIT_ERROR
    except UnicodeDecodeError as exc:
        fail(f"{args.file} is not valid UTF-8: {exc}")
        return EXIT_ERROR

    errors: list[str] = []
    lines = text.splitlines()

    # --- H1 title: a line that is exactly '# <title>' ---
    wanted_h1 = f"# {args.title}".strip()
    h1_present = any(line.strip() == wanted_h1 for line in lines)
    if not h1_present:
        errors.append(f"missing H1 title heading '{wanted_h1}'")

    # --- Sections: '## <name>' headings, each after the previous one ---
    h2_headings = [line.strip()[3:].strip() for line in lines if line.strip().startswith("## ")]
    sections = split_pipe(args.sections)
    cursor = 0
    for name in sections:
        found = None
        for idx in range(cursor, len(h2_headings)):
            if h2_headings[idx] == name:
                found = idx
                break
        if found is None:
            errors.append(
                f"missing '## {name}' section (absent or out of order; "
                f"found headings: {h2_headings or 'none'})"
            )
        else:
            cursor = found + 1

    # --- Terms: case-insensitive substring anywhere in the document ---
    lowered = text.lower()
    for term in split_pipe(args.terms):
        if term.lower() not in lowered:
            errors.append(f"missing term '{term}'")

    # --- Word count ---
    word_count = len(text.split())
    if args.min_words and word_count < args.min_words:
        errors.append(f"word count {word_count} is below the required {args.min_words}")

    if errors:
        for error in errors:
            fail(error)
        return EXIT_FAIL

    print(
        f"OK: {args.file} — H1 '{args.title}', {len(sections)} section(s) in order, "
        f"all terms present, {word_count} words (min {args.min_words})"
    )
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())