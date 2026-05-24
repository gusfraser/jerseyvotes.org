"""Sweep candidate manifesto_text and enhanced_manifesto_text for
fuzzy-match candidates against the Jersey lexicon. Reports:

  * AUTO-tier corrections that would apply automatically
  * REVIEW-tier matches for human inspection
  * Inconsistencies (e.g. "St. Helier" vs "St Helier")

Manifesto text isn't ASR output — it's scraped from vote.je and the
candidates' own writing — so Whisper-style garbles are rare. The
common patterns are:
  * Inconsistent parish name formatting ("St. Helier" vs "St Helier")
  * Typos in Jersey-French surnames
  * Inconsistent role/body names ("Connetable" vs "Connétable")

Run:
  python pipeline/fuzzy_audit_manifestos.py
  python pipeline/fuzzy_audit_manifestos.py --apply  # apply auto-tier
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jersey_lexicon import find_matches, apply_corrections


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true',
                    help='Apply AUTO-tier corrections back to the DB')
    ap.add_argument('--min-score', type=float, default=85.0,
                    help='Lowest similarity to include in the report')
    ap.add_argument('--field', choices=('manifesto', 'enhanced', 'both'),
                    default='both')
    args = ap.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    fields = []
    if args.field in ('manifesto', 'both'):
        fields.append('manifesto_text')
    if args.field in ('enhanced', 'both'):
        fields.append('enhanced_manifesto_text')

    cur.execute(f'''
        SELECT candidate_id, full_name, {", ".join(fields)}
        FROM candidates
        WHERE election_year = 2026
          AND ({" OR ".join(f"{f} IS NOT NULL" for f in fields)})
        ORDER BY full_name
    ''')
    rows = cur.fetchall()

    grand_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    auto_applies: list[tuple[int, str, str, str, int]] = []  # (cid, name, field, new_text, n_auto)
    per_candidate_report = []

    for row in rows:
        cid = row[0]
        name = row[1]
        for i, field in enumerate(fields):
            text = row[2 + i]
            if not text:
                continue
            # Pass the candidate's own name as a roster member so we
            # don't try to fuzzy-correct their name in their own
            # manifesto (e.g. "Le Maistre" stays as-is even if it's
            # only 88% match to lexicon).
            matches = find_matches(text, roster_names={name})
            # Filter by min_score AFTER find_matches has already
            # filtered to >= SKIP_BELOW.
            useful = [m for m in matches if m.score >= args.min_score]
            if not useful:
                continue
            useful.sort(key=lambda m: -m.score)
            per_candidate_report.append((name, field, useful))

            for m in useful:
                grand_counts[(m.decision, m.original.lower(), m.canonical)] += 1

            if args.apply:
                new_text, n = apply_corrections(text, useful)
                if n:
                    auto_applies.append((cid, name, field, new_text, n))

    # Per-candidate breakdown
    print(f'\n===== PER-CANDIDATE MATCHES (>= {args.min_score}%) =====')
    for name, field, matches in per_candidate_report[:30]:
        print(f'\n📄 {name} ({field})')
        for m in matches[:10]:
            print(f'    [{m.score:5.1f}] {m.decision:6s} {m.original!r:35s} → {m.canonical!r:30s}  ({m.category})')

    # Cross-candidate tally
    print(f'\n===== CROSS-CANDIDATE TALLY =====')
    sorted_items = sorted(grand_counts.items(), key=lambda kv: (-kv[1], kv[0][0]))
    for (decision, original, canonical), n in sorted_items[:30]:
        print(f'  {n:>2}× {decision:6s} {original:25s} → {canonical:25s}')

    if args.apply and auto_applies:
        print(f'\n===== APPLYING {len(auto_applies)} CORRECTIONS =====')
        for cid, name, field, new_text, n in auto_applies:
            cur.execute(
                f'UPDATE candidates SET {field} = %s WHERE candidate_id = %s',
                (new_text, cid),
            )
            print(f'  ✓ {name} ({field}): {n} corrections')
        conn.commit()
        print(f'committed {len(auto_applies)} candidate rows updated')
    elif args.apply:
        print('\nNothing AUTO-tier to apply')


if __name__ == '__main__':
    main()
