"""Sweep all transcripts for fuzzy-match candidates and print an audit
report. Groups by decision (auto / review / skip) and category.

Use this to discover NEW garble patterns proactively. When the report
shows a high-confidence pattern that the regex layer doesn't catch
yet, either:
  1. Add it to LEXICON in jersey_lexicon.py (preferred — auto-fixes
     all future siblings of that pattern), OR
  2. Add a specific regex to normalise_local_terms.py (for very
     specific multi-word cases the fuzzy matcher can't generalise).

Run:
  python pipeline/fuzzy_audit.py                  # all events
  python pipeline/fuzzy_audit.py --slug <event>   # single event
  python pipeline/fuzzy_audit.py --decision auto  # only auto-tier
  python pipeline/fuzzy_audit.py --min-score 80   # threshold override
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jersey_lexicon import find_matches

HUSTINGS = Path(__file__).resolve().parent / 'hustings'


def audit_event(folder: Path, min_score: float, decision_filter: str | None) -> dict:
    """Produce an audit dict for one event. Returns
    {decision: [(score, category, original, canonical), ...], ...}
    """
    tx = folder / 'transcript.md'
    meta = folder / 'metadata.yaml'
    if not tx.exists():
        return {}
    roster: set[str] = set()
    if meta.exists():
        data = yaml.safe_load(meta.read_text()) or {}
        for c in (data.get('candidates') or []):
            if c.get('name'):
                roster.add(c['name'])
        for m in (data.get('moderator_names') or []):
            roster.add(m)

    text = tx.read_text()
    matches = find_matches(text, roster_names=roster)

    out: dict[str, list[tuple]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for m in matches:
        if m.score < min_score:
            continue
        if decision_filter and m.decision != decision_filter:
            continue
        key = (m.original.lower(), m.canonical)
        if key in seen:
            continue
        seen.add(key)
        out[m.decision].append((m.score, m.category, m.original, m.canonical))
    return out


def print_event_report(slug: str, audit: dict, verbose: bool = True):
    if not audit:
        return
    total = sum(len(v) for v in audit.values())
    if not total:
        return
    print(f'\n📄 {slug} ({total} matches)')
    for decision in ('auto', 'review', 'skip'):
        items = audit.get(decision, [])
        if not items:
            continue
        items.sort(key=lambda x: -x[0])  # highest score first
        print(f'  {decision.upper()} ({len(items)}):')
        for score, category, original, canonical in items:
            print(f'    [{score:5.1f}] {original!r:35s} → {canonical!r:30s}  ({category})')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--slug', help='Process only this event slug')
    ap.add_argument('--min-score', type=float, default=75.0,
                    help='Lowest similarity to include in the report')
    ap.add_argument('--decision', choices=('auto', 'review', 'skip'),
                    help='Filter to one decision tier')
    args = ap.parse_args()

    folders = sorted(
        p for p in HUSTINGS.iterdir()
        if p.is_dir() and not p.name.startswith('_')
    )
    if args.slug:
        folders = [p for p in folders if p.name == args.slug]
        if not folders:
            sys.exit(f'No folder named {args.slug!r}')

    grand: dict[str, list] = defaultdict(list)
    for folder in folders:
        audit = audit_event(folder, args.min_score, args.decision)
        print_event_report(folder.name, audit)
        for decision, items in audit.items():
            grand[decision].extend((folder.name, *it) for it in items)

    # Cross-event summary: most-frequently-seen garble patterns.
    print()
    print('===== CROSS-EVENT TALLY =====')
    counts: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for decision in ('auto', 'review'):
        for slug, score, category, original, canonical in grand.get(decision, []):
            counts[(original.lower(), canonical)].append((slug, score))
    pairs = sorted(counts.items(), key=lambda kv: -len(kv[1]))
    for (orig, canon), occurrences in pairs[:25]:
        if len(occurrences) >= 2:
            avg = sum(s for _, s in occurrences) / len(occurrences)
            print(f'  {len(occurrences):>2}× {orig:25s} → {canon:25s}  (avg score {avg:.1f})')


if __name__ == '__main__':
    main()
