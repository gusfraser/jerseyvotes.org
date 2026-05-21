"""
Generate the per-candidate outreach CSV used to invite candidates to review
their extracted topics and stances before public launch.

Each candidate has a token (set during scrape) that gates a private preview
page at /candidates/correction/<token> — the URL emitted here points at that
page on the public site host.

This script does NOT send emails. It only produces a CSV that Gus can review
and feed into mail-merge or send manually. Email outreach is a human-loop
step on purpose: the candidate-correction process is the trust foundation
for the published scoring methodology.

Run: python pipeline/generate_correction_previews.py [--host https://jerseyvotes.org]
"""

import argparse
import csv
import os
import sys

import psycopg2
from dotenv import load_dotenv

# override=True so a shell-exported DATABASE_URL/ANTHROPIC_API_KEY doesn't
# shadow the value in .env (python-dotenv defaults to NOT overriding).
load_dotenv(override=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='https://jerseyvotes.org')
    parser.add_argument('--out', default='-', help='Output CSV path or - for stdout')
    parser.add_argument('--election-year', type=int, default=2026)
    args = parser.parse_args()

    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    cur.execute('''
        SELECT candidate_id, full_name, role, constituency, party,
               email, correction_token, correction_state,
               manifesto_word_count, classified_at,
               enhanced_manifesto_status, enhanced_manifesto_source_url,
               enhanced_manifesto_source_label, enhanced_manifesto_word_count
        FROM candidates
        WHERE election_year = %s
        ORDER BY full_name
    ''', (args.election_year,))
    rows = cur.fetchall()

    out = sys.stdout if args.out == '-' else open(args.out, 'w', newline='')
    writer = csv.writer(out)
    writer.writerow([
        'candidate_id', 'full_name', 'role', 'constituency', 'party',
        'email', 'preview_url', 'correction_state',
        'manifesto_word_count', 'classified',
        'enhanced_manifesto_found', 'enhanced_manifesto_url',
        'enhanced_manifesto_source', 'enhanced_manifesto_word_count',
    ])

    missing_email = 0
    enhanced_found = 0
    for (cand_id, name, role, constituency, party, email,
         token, state, wc, classified_at,
         enh_status, enh_url, enh_label, enh_wc) in rows:
        preview_url = f'{args.host}/candidates/correction/{token}' if token else ''
        if not email:
            missing_email += 1
        found = enh_status == 'found'
        if found:
            enhanced_found += 1
        writer.writerow([
            cand_id, name, role or '', constituency or '', party or '',
            email or '', preview_url, state or 'pending',
            wc or 0, 'yes' if classified_at else 'no',
            'yes' if found else 'no',
            enh_url or '' if found else '',
            enh_label or '' if found else '',
            enh_wc or 0 if found else 0,
        ])

    if args.out != '-':
        out.close()
        print(f'Wrote {len(rows)} rows to {args.out}', file=sys.stderr)
    print(f'{missing_email} candidates have no email on file (require manual contact)',
          file=sys.stderr)
    print(f'{enhanced_found} candidates have an enhanced manifesto found on the open web',
          file=sys.stderr)

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
