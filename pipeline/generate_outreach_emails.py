"""
Render the per-candidate outreach emails from corrections.csv into both
outreach.csv (UTF-8 with BOM, for GMass / YAMM / Mailchimp / smtplib) and
outreach.xlsx (for Microsoft 365 Word + Outlook mail merge, which is the
most reliable path on Outlook).

Two body variants are used depending on whether find_enhanced_manifestos.py
turned up a fuller manifesto on the open web:

  - "enhanced": names the enhanced URL and word count so the candidate can
    confirm it's actually theirs.
  - "vote_je_only": invites them to share a longer source if they have one.

The CSV is written with a UTF-8 BOM (encoding='utf-8-sig') so Excel and Word
on Windows read em-dashes and other smart characters correctly rather than
showing mojibake like "Äî".

Run: python pipeline/generate_outreach_emails.py
     [--in corrections.csv] [--out outreach.csv]
"""

import argparse
import csv
import sys
from pathlib import Path

import openpyxl


SUBJECT = "Quick review request — your jerseyvotes.org candidate page"


BODY_ENHANCED = """Dear {first_name},

I'm Gus Fraser, the developer behind jerseyvotes.org — a free, non-partisan site to help Jersey voters compare 2026 candidates ahead of the election.

The site is live and your candidate page is already published. I've set up a private review link so you can see exactly what we've extracted about you, and flag anything that needs correcting:

{preview_url}

What we've done:
- Read your manifesto and classified it into the topic areas voters care about
- Inferred a stance (agree / disagree / neutral / not addressed) on a fixed set of canonical policy questions
- Supplemented the vote.je text with a fuller manifesto ({enhanced_wc} words) we found here:
  {enhanced_url}

Two things would really help:
1. Check the extracted topics and stances are a fair reflection of your position. If anything looks wrong, just reply — I'll log a correction and your public profile will be updated.
2. Confirm the manifesto link above is actually yours. If it's the wrong page, or you'd rather we use a different source, let me know.

No reply needed if everything looks right.

Thanks,
Gus Fraser
gus@helix.je
"""


BODY_VOTE_JE_ONLY = """Dear {first_name},

I'm Gus Fraser, the developer behind jerseyvotes.org — a free, non-partisan site to help Jersey voters compare 2026 candidates ahead of the election.

The site is live and your candidate page is already published. I've set up a private review link so you can see exactly what we've extracted about you, and flag anything that needs correcting:

{preview_url}

What we've done:
- Read the {manifesto_wc}-word manifesto you posted on vote.je
- Classified it into the topic areas voters care about
- Inferred a stance (agree / disagree / neutral / not addressed) on a fixed set of canonical policy questions

Two things would really help:
1. Check the extracted topics and stances are a fair reflection of your position. If anything looks wrong, just reply — I'll log a correction and your public profile will be updated.
2. If you have a longer manifesto, personal site, or other public statement of your policies, send the link. The fuller the source, the more accurate the comparison.

No reply needed if everything looks right.

Thanks,
Gus Fraser
gus@helix.je
"""


def first_name(full_name: str) -> str:
    return full_name.strip().split(' ', 1)[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--in', dest='infile', default='corrections.csv')
    parser.add_argument('--out', default='outreach.csv')
    args = parser.parse_args()

    with open(args.infile, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    header = [
        'email', 'first_name', 'full_name', 'role', 'constituency',
        'variant', 'subject', 'body',
    ]
    out_rows = []

    skipped_no_email = 0
    n_enhanced = 0
    n_vote_je_only = 0

    for row in rows:
        email = row['email'].strip()
        if not email:
            skipped_no_email += 1
            continue

        fname = first_name(row['full_name'])
        ctx = {
            'first_name': fname,
            'preview_url': row['preview_url'],
            'manifesto_wc': row['manifesto_word_count'],
            'enhanced_url': row['enhanced_manifesto_url'],
            'enhanced_wc': row['enhanced_manifesto_word_count'],
        }

        if row['enhanced_manifesto_found'] == 'yes':
            variant = 'enhanced'
            body = BODY_ENHANCED.format(**ctx)
            n_enhanced += 1
        else:
            variant = 'vote_je_only'
            body = BODY_VOTE_JE_ONLY.format(**ctx)
            n_vote_je_only += 1

        out_rows.append([
            email, fname, row['full_name'], row['role'],
            row['constituency'], variant, SUBJECT, body,
        ])

    # UTF-8 with BOM so Excel / Outlook on Windows decode smart chars correctly.
    with open(args.out, 'w', newline='', encoding='utf-8-sig') as out:
        writer = csv.writer(out)
        writer.writerow(header)
        writer.writerows(out_rows)

    # XLSX twin for Word + Outlook mail merge — the most reliable Microsoft path.
    xlsx_path = Path(args.out).with_suffix('.xlsx')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'outreach'
    ws.append(header)
    for r in out_rows:
        ws.append(r)
    wb.save(xlsx_path)

    print(f'Wrote {n_enhanced + n_vote_je_only} emails to {args.out} '
          f'and {xlsx_path} ({n_enhanced} enhanced, {n_vote_je_only} vote.je only)',
          file=sys.stderr)
    if skipped_no_email:
        print(f'Skipped {skipped_no_email} candidates with no email',
              file=sys.stderr)


if __name__ == '__main__':
    main()
