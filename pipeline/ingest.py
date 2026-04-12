"""
AgenticGov Data Ingestion Pipeline
Reads VotingDataCSV.csv and loads normalized data into Neon PostgreSQL.
"""

import csv
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'VotingDataCSV.csv')
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schema.sql')

# Vote category mapping
ACTIVE_VOTES = {'Pour', 'Contre', 'Abstained'}
EXCUSED_ABSENCES = {
    'Ill', 'Out of the Island', 'Excused attendance',
    'Parental responsibilities', 'Declared an interest',
    'Suspended', 'Presiding'
}
UNEXCUSED_ABSENCES = {'Not present for vote', 'En défaut'}


def classify_vote(vote_text: str) -> str:
    if vote_text in ACTIVE_VOTES:
        return 'active_vote'
    elif vote_text in EXCUSED_ABSENCES:
        return 'excused_absence'
    elif vote_text in UNEXCUSED_ABSENCES:
        return 'unexcused_absence'
    return 'unknown'


def normalize_member_name(name: str) -> str:
    """Fix double spaces and standardize whitespace."""
    return ' '.join(name.split())


def parse_reference(ref: str) -> dict:
    """Parse a reference string into base_ref, amendment info, and reissue flag."""
    # Strip GUID prefix from old 2004 records
    if '|' in ref:
        ref = ref.split('|')[-1].strip()

    # Extract base reference P.XX/YYYY
    match = re.match(r'(P\.\d+/\d{4})', ref)
    if not match:
        return {'base_ref': ref, 'amendment_number': None, 'is_reissue': False, 'clean_ref': ref}

    base_ref = match.group(1)
    remainder = ref[match.end():]

    # Check for reissue
    is_reissue = bool(re.search(r'[Rr]e-?issue', remainder))

    # Extract amendment number
    amd_match = re.search(r'\(Amd\)(?:\((\d+)\))?', remainder)
    amendment_number = None
    if amd_match:
        amendment_number = int(amd_match.group(1)) if amd_match.group(1) else 1

    return {
        'base_ref': base_ref,
        'amendment_number': amendment_number,
        'is_reissue': is_reissue,
        'clean_ref': ref
    }


def generate_source_url(base_ref: str) -> str:
    """Generate statesassembly.je URL from a base reference like P.57/2026."""
    match = re.match(r'P\.(\d+)/(\d{4})', base_ref)
    if not match:
        return None
    number, year = match.group(1), match.group(2)
    return f'https://statesassembly.je/publications/propositions/{year}/p-{number}-{year}'


def classify_division_stage(title: str, proposition_title: str) -> str:
    """Classify the legislative stage of a vote division from its title."""
    t = (title or '').lower()
    pt = (proposition_title or '').lower()
    combined = f'{t} {pt}'

    if 'principles' in t or 'principles' in pt.split(')')[-1]:
        return 'principles'
    if 'third reading' in combined:
        return 'third_reading'
    if re.search(r'articles?\s+\d', t):
        return 'articles'
    if 'amendment' in t or 'amd' in t.lower():
        return 'amendment'
    if 'paragraph' in t:
        return 'paragraph'
    if 'regulation' in t:
        return 'regulations'
    if any(kw in combined for kw in ['closure', 'motion', 'refer back', 'standing order']):
        return 'procedural'
    return 'other'


def normalize_position(position: str) -> str:
    """Map legacy position labels to standard ones."""
    mapping = {
        'Mr.': 'Deputy',
        'Mrs.': 'Deputy',
        'Miss.': 'Deputy',
        'Advocate': 'Deputy',
        'Senators': 'Senator',
    }
    return mapping.get(position, position)


def read_csv():
    """Read and parse the entire CSV, returning structured data."""
    print(f'Reading {CSV_PATH}...')
    rows = []
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    print(f'  Read {len(rows):,} rows')
    return rows


def build_members(rows):
    """Extract and normalize member data."""
    member_data = defaultdict(lambda: {
        'positions': Counter(),
        'first_date': None,
        'last_date': None,
        'years_active': set()
    })

    for row in rows:
        name = normalize_member_name(row['MemberName'])
        position = normalize_position(row['MemberPosition'])
        try:
            date = datetime.strptime(row['Date'], '%d/%m/%Y %H:%M:%S')
        except ValueError:
            continue

        md = member_data[name]
        md['positions'][position] += 1
        year = date.year

        if md['first_date'] is None or date < md['first_date']:
            md['first_date'] = date
        if md['last_date'] is None or date > md['last_date']:
            md['last_date'] = date
        md['years_active'].add(year)

    members = []
    for name, data in sorted(member_data.items()):
        is_active = 2025 in data['years_active'] or 2026 in data['years_active']
        # Build position history (simplified: most common position)
        position_history = [
            {'position': pos, 'count': count}
            for pos, count in data['positions'].most_common()
        ]
        members.append({
            'canonical_name': name,
            'display_name': name,
            'first_vote_date': data['first_date'],
            'last_vote_date': data['last_date'],
            'is_currently_active': is_active,
            'position_history': position_history
        })

    print(f'  Found {len(members)} unique members ({sum(1 for m in members if m["is_currently_active"])} active)')
    return members


def build_propositions(rows):
    """Extract unique base propositions."""
    prop_data = {}

    for row in rows:
        ref_info = parse_reference(row['Reference'])
        base_ref = ref_info['base_ref']

        if base_ref not in prop_data:
            match = re.match(r'P\.(\d+)/(\d{4})', base_ref)
            if match:
                number, year = int(match.group(1)), int(match.group(2))
            else:
                number, year = 0, 0
            prop_data[base_ref] = {
                'base_reference': base_ref,
                'year': year,
                'number': number,
                'source_url': generate_source_url(base_ref),
                'title': row['PropositionTitle'],
            }

    propositions = sorted(prop_data.values(), key=lambda p: (p['year'], p['number']))
    print(f'  Found {len(propositions)} unique base propositions')
    return propositions


def build_divisions(rows, proposition_lookup, member_lookup):
    """Build vote divisions and individual votes."""
    division_data = {}
    # Track seen (division_id, member_id) pairs for dedup.
    # When a member appears twice (e.g., Ozouf as both Deputy and Connétable),
    # keep the active vote (Pour/Contre/Abstained) over the phantom (En défaut).
    vote_seen = {}
    duplicates_resolved = 0

    for row in rows:
        div_id = int(row['ID'])
        name = normalize_member_name(row['MemberName'])
        ref_info = parse_reference(row['Reference'])
        vote_text = row['Vote']

        if div_id not in division_data:
            try:
                date = datetime.strptime(row['Date'], '%d/%m/%Y %H:%M:%S')
            except ValueError:
                continue

            prop_id = proposition_lookup.get(ref_info['base_ref'])
            stage = classify_division_stage(row['Title'], row['PropositionTitle'])

            division_data[div_id] = {
                'division_id': div_id,
                'proposition_id': prop_id,
                'title': row['Title'],
                'proposition_title': row['PropositionTitle'],
                'reference': ref_info['clean_ref'],
                'date': date,
                'division_stage': stage,
                'amendment_number': ref_info['amendment_number'],
                'is_reissue': ref_info['is_reissue'],
                'pour_count': 0,
                'contre_count': 0,
                'abstain_count': 0,
                'absent_count': 0,
                'total_eligible': 0,
            }

        member_id = member_lookup.get(name)
        if not member_id:
            continue

        key = (div_id, member_id)
        if key in vote_seen:
            # Duplicate: keep active vote over non-active
            existing = vote_seen[key]
            existing_is_active = existing['vote'] in ACTIVE_VOTES
            new_is_active = vote_text in ACTIVE_VOTES
            if new_is_active and not existing_is_active:
                vote_seen[key] = {'vote': vote_text, 'vote_category': classify_vote(vote_text)}
            duplicates_resolved += 1
            continue

        vote_seen[key] = {'vote': vote_text, 'vote_category': classify_vote(vote_text)}

    # Now build tallies and vote list from deduped data
    votes = []
    for (div_id, member_id), vote_data in vote_seen.items():
        vote_text = vote_data['vote']
        div = division_data[div_id]
        div['total_eligible'] += 1
        if vote_text == 'Pour':
            div['pour_count'] += 1
        elif vote_text == 'Contre':
            div['contre_count'] += 1
        elif vote_text == 'Abstained':
            div['abstain_count'] += 1
        else:
            div['absent_count'] += 1

        votes.append({
            'division_id': div_id,
            'member_id': member_id,
            'vote': vote_text,
            'vote_category': vote_data['vote_category'],
        })

    divisions = sorted(division_data.values(), key=lambda d: d['date'])
    print(f'  Built {len(divisions)} vote divisions and {len(votes):,} individual votes')
    print(f'  Resolved {duplicates_resolved} duplicate entries')
    return divisions, votes


def load_to_database(members, propositions, divisions, votes):
    """Load all data into Neon PostgreSQL."""
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print('ERROR: DATABASE_URL not set. Create a .env file with your Neon connection string.')
        return

    print(f'Connecting to database...')
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    # Run schema
    print('  Creating schema...')
    with open(SCHEMA_PATH, 'r') as f:
        cur.execute(f.read())
    conn.commit()

    # Insert members
    print(f'  Inserting {len(members)} members...')
    import json
    member_rows = [
        (m['canonical_name'], m['display_name'], m['first_vote_date'],
         m['last_vote_date'], m['is_currently_active'],
         json.dumps(m['position_history']))
        for m in members
    ]
    execute_values(cur,
        '''INSERT INTO members (canonical_name, display_name, first_vote_date,
           last_vote_date, is_currently_active, position_history)
           VALUES %s''',
        member_rows
    )
    conn.commit()

    # Build member_id lookup
    cur.execute('SELECT member_id, canonical_name FROM members')
    member_id_map = {name: mid for mid, name in cur.fetchall()}

    # Insert propositions
    print(f'  Inserting {len(propositions)} propositions...')
    prop_rows = [
        (p['base_reference'], p['year'], p['number'], p['source_url'], p['title'])
        for p in propositions
    ]
    execute_values(cur,
        '''INSERT INTO propositions (base_reference, year, number, source_url, title)
           VALUES %s''',
        prop_rows
    )
    conn.commit()

    # Build proposition_id lookup
    cur.execute('SELECT proposition_id, base_reference FROM propositions')
    prop_id_map = {ref: pid for pid, ref in cur.fetchall()}

    # Insert divisions
    print(f'  Inserting {len(divisions)} vote divisions...')
    div_rows = [
        (d['division_id'], prop_id_map.get(parse_reference(d['reference'])['base_ref']),
         d['title'], d['proposition_title'], d['reference'], d['date'],
         d['division_stage'], d['amendment_number'], d['is_reissue'],
         d['pour_count'], d['contre_count'], d['abstain_count'],
         d['absent_count'], d['total_eligible'])
        for d in divisions
    ]
    execute_values(cur,
        '''INSERT INTO vote_divisions (division_id, proposition_id, title,
           proposition_title, reference, date, division_stage, amendment_number,
           is_reissue, pour_count, contre_count, abstain_count, absent_count,
           total_eligible)
           VALUES %s''',
        div_rows
    )
    conn.commit()

    # Insert votes in batches
    print(f'  Inserting {len(votes):,} votes (in batches)...')
    vote_rows = [
        (v['division_id'], v['member_id'], v['vote'], v['vote_category'])
        for v in votes
    ]
    batch_size = 50000
    for i in range(0, len(vote_rows), batch_size):
        batch = vote_rows[i:i + batch_size]
        execute_values(cur,
            '''INSERT INTO votes (division_id, member_id, vote, vote_category)
               VALUES %s''',
            batch
        )
        conn.commit()
        print(f'    Inserted {min(i + batch_size, len(vote_rows)):,} / {len(vote_rows):,}')

    cur.close()
    conn.close()
    print('Done! All data loaded.')


def main():
    print('=== AgenticGov Data Ingestion ===\n')

    # Step 1: Read CSV
    rows = read_csv()

    # Step 2: Build normalized entities
    print('\nBuilding members...')
    members = build_members(rows)

    print('\nBuilding propositions...')
    propositions = build_propositions(rows)

    print('\nBuilding divisions and votes...')
    # Need lookups for building divisions
    # Temporary: use name->index for member lookup, ref->index for proposition lookup
    member_lookup = {m['canonical_name']: i + 1 for i, m in enumerate(members)}
    proposition_lookup = {p['base_reference']: i + 1 for i, p in enumerate(propositions)}
    divisions, votes = build_divisions(rows, proposition_lookup, member_lookup)

    # Step 3: Load to database
    print('\nLoading to database...')
    load_to_database(members, propositions, divisions, votes)

    # Print summary
    print('\n=== Summary ===')
    print(f'Members: {len(members)} ({sum(1 for m in members if m["is_currently_active"])} active)')
    print(f'Propositions: {len(propositions)}')
    print(f'Vote divisions: {len(divisions)}')
    print(f'Individual votes: {len(votes):,}')

    # Division stage breakdown
    stage_counts = Counter(d['division_stage'] for d in divisions)
    print('\nDivision stages:')
    for stage, count in stage_counts.most_common():
        print(f'  {stage}: {count}')

    # Vote category breakdown
    cat_counts = Counter(v['vote_category'] for v in votes)
    print('\nVote categories:')
    for cat, count in cat_counts.most_common():
        print(f'  {cat}: {count:,}')


if __name__ == '__main__':
    main()
