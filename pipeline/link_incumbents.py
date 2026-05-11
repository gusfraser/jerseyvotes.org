"""
Link scraped candidates to existing members via normalised-name match.

A candidate is treated as an incumbent if their canonical_name matches a
currently active member. Writes the match to candidates.incumbent_member_id
and prints near-miss matches (similar names that didn't pair) for manual
review — useful when accents, hyphens, or middle names vary between sources.

Run: python pipeline/link_incumbents.py [--dry-run]
"""

import argparse
import csv
import os
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

import psycopg2
from dotenv import load_dotenv

# override=True so a shell-exported DATABASE_URL/ANTHROPIC_API_KEY doesn't
# shadow the value in .env (python-dotenv defaults to NOT overriding).
load_dotenv(override=True)


def normalise(name: str) -> str:
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r'[^A-Za-z0-9\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip().lower()
    return name


def initial_lastname_key(name: str) -> str | None:
    """Returns 'r ward' for 'Robert Ward'. Used for nickname-style fuzzy match,
    e.g. 'Rob Ward' vs 'Robert Ward'. None if the name is single-token."""
    parts = name.split()
    if len(parts) < 2:
        return None
    return f'{parts[0][0]} {parts[-1]}'


def load_overrides(path: str | None) -> dict[str, str]:
    """CSV with header `candidate_slug,member_canonical_name`. Returns a dict
    mapping vote_je_slug -> member canonical_name. Used to bridge nickname
    cases that the unique-pattern auto-match refuses to commit."""
    if not path:
        return {}
    overrides: dict[str, str] = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            slug = (row.get('candidate_slug') or '').strip()
            member = (row.get('member_canonical_name') or '').strip()
            if slug and member:
                overrides[slug] = member
    return overrides


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--near-miss-threshold', type=float, default=0.85)
    parser.add_argument(
        '--overrides',
        help='CSV of candidate_slug,member_canonical_name pairs to force-link',
    )
    parser.add_argument(
        '--clear-existing',
        action='store_true',
        help='Set incumbent_member_id = NULL on all candidates before linking',
    )
    args = parser.parse_args()

    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    cur.execute('''
        SELECT member_id, canonical_name, display_name
        FROM members
        WHERE is_currently_active = TRUE
    ''')
    members = cur.fetchall()
    print(f'Active members: {len(members)}')

    cur.execute('''
        SELECT candidate_id, vote_je_slug, full_name
        FROM candidates
        WHERE election_year = 2026
    ''')
    candidates = cur.fetchall()
    print(f'Candidates: {len(candidates)}')

    overrides = load_overrides(args.overrides)
    print(f'Manual overrides: {len(overrides)}')

    if args.clear_existing and not args.dry_run:
        cur.execute('UPDATE candidates SET incumbent_member_id = NULL WHERE election_year = 2026')
        conn.commit()
        print('Cleared existing incumbent links.')

    # Index members
    by_canon = {normalise(m[1]): (m[0], m[2]) for m in members}
    members_by_initial: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for mid, canonical, display in members:
        key = initial_lastname_key(normalise(canonical))
        if key:
            members_by_initial[key].append((mid, display))

    # Pre-compute: count how many CANDIDATES share each initial+lastname key.
    # If two candidates share a key, neither is auto-linkable via the fallback —
    # too ambiguous. (Avoids the Robin/Rob → Robert Ward collision.)
    candidate_initial_counts: dict[str, int] = defaultdict(int)
    for _cid, _slug, full_name in candidates:
        key = initial_lastname_key(normalise(full_name))
        if key:
            candidate_initial_counts[key] += 1

    matches: list[tuple[int, int, str, str, str]] = []  # cid, mid, name, member, reason
    near_misses: list[tuple[str, str, str, float]] = []

    for cand_id, slug, full_name in candidates:
        norm = normalise(full_name)

        # Manual override always wins
        if slug in overrides:
            target = normalise(overrides[slug])
            if target in by_canon:
                mid, display = by_canon[target]
                matches.append((cand_id, mid, full_name, display, 'override'))
                continue
            else:
                print(f'  WARN: override for {slug} -> {overrides[slug]!r} not found in members')

        # Direct normalised match
        if norm in by_canon:
            mid, display = by_canon[norm]
            matches.append((cand_id, mid, full_name, display, 'exact'))
            continue

        # Initial+lastname fallback — only when unambiguous on BOTH sides:
        #   * exactly one MEMBER has this initial+lastname key
        #   * exactly one CANDIDATE has this initial+lastname key
        key = initial_lastname_key(norm)
        if key and len(members_by_initial.get(key, [])) == 1 and candidate_initial_counts[key] == 1:
            mid, display = members_by_initial[key][0]
            matches.append((cand_id, mid, full_name, display, 'initial-unique'))
            continue

        # Fuzzy near-miss for manual review
        best: tuple[str, str, float] | None = None
        for canon_m, (mid, display) in by_canon.items():
            ratio = SequenceMatcher(None, norm, canon_m).ratio()
            if ratio >= args.near_miss_threshold and (best is None or ratio > best[2]):
                best = (full_name, display, ratio)
        if best:
            near_misses.append((slug, best[0], best[1], best[2]))

    print(f'Auto-linked: {len(matches)} (exact={sum(1 for m in matches if m[4]=="exact")}, '
          f'initial-unique={sum(1 for m in matches if m[4]=="initial-unique")}, '
          f'override={sum(1 for m in matches if m[4]=="override")})')
    print(f'Near-misses for review: {len(near_misses)}')

    if near_misses:
        print('\nNear-miss matches (suggest adding to --overrides CSV if correct):')
        for slug, cand_name, member_name, ratio in sorted(near_misses, key=lambda x: -x[3]):
            print(f'  {ratio:.2f}  slug={slug:30s}  candidate="{cand_name}" <-> member="{member_name}"')

    # Diagnostic: collisions where multiple candidates share initial+lastname
    collisions = {k: v for k, v in candidate_initial_counts.items() if v > 1 and len(members_by_initial.get(k, [])) >= 1}
    if collisions:
        print('\nAmbiguous initial+lastname keys (multiple candidates, deliberately NOT auto-linked):')
        for key, count in collisions.items():
            names = [c[2] for c in candidates if initial_lastname_key(normalise(c[2])) == key]
            member_names = [d for _, d in members_by_initial.get(key, [])]
            print(f'  key="{key}"  candidates={names}  member(s)={member_names}')

    if args.dry_run:
        print('\nDry run — no updates written.')
        return

    for cand_id, mid, _full_name, _display, _reason in matches:
        cur.execute(
            'UPDATE candidates SET incumbent_member_id = %s WHERE candidate_id = %s',
            (mid, cand_id),
        )

    conn.commit()
    cur.close()
    conn.close()
    print(f'\nWrote {len(matches)} incumbent links.')


if __name__ == '__main__':
    main()
