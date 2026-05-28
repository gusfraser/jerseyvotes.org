"""One-shot backfill: populate hustings_events.event_date for rows where
it's NULL by probing the recording's release_date / upload_date via
yt-dlp (no audio download — just the JSON metadata).

This exists because the original auto-pipeline never populated
event_date — only hand-cleaned events had `event_date:` in their
metadata.yaml. As of this commit, ingest_hustings.py automatically
picks up the date from video_metadata.json for new events; this script
is the one-shot to fix the 25 pre-existing rows.

Idempotent — re-running is a no-op once every row has a date.

Run:
  python pipeline/backfill_hustings_dates.py
  python pipeline/backfill_hustings_dates.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv(override=True)


def probe_dates(url: str) -> tuple[str | None, str | None]:
    """Return (release_date, upload_date) as YYYY-MM-DD strings, or
    (None, None) on any failure."""
    proc = subprocess.run(
        ['yt-dlp', '--print', '%(release_date)s|%(upload_date)s',
         '--skip-download', url],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return None, None
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ''
    parts = line.split('|', 1)
    if len(parts) != 2:
        return None, None
    rel, up = parts
    return _fmt(rel), _fmt(up)


def _fmt(raw: str) -> str | None:
    raw = (raw or '').strip()
    if raw in ('', 'NA') or len(raw) != 8 or not raw.isdigit():
        return None
    return f'{raw[0:4]}-{raw[4:6]}-{raw[6:8]}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true',
                        help='Report findings without writing to the DB')
    args = parser.parse_args()

    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()
    cur.execute(
        """SELECT event_id, slug, youtube_url
             FROM hustings_events
            WHERE event_date IS NULL AND election_year = 2026
            ORDER BY slug"""
    )
    rows = cur.fetchall()
    if not rows:
        print('No NULL-event_date rows. Nothing to backfill.')
        return
    print(f'Found {len(rows)} events to backfill.\n')

    updated = skipped = errored = 0
    for event_id, slug, url in rows:
        if not url:
            print(f'  SKIP {slug}: no youtube_url')
            skipped += 1
            continue
        rel, up = probe_dates(url)
        # release_date is the broadcast start (the actual hustings night).
        # upload_date is YouTube's processing completion — close but can
        # roll into the next UTC day. Prefer release_date when present.
        chosen = rel or up
        if not chosen:
            print(f'  ERR  {slug}: no release/upload date in yt-dlp output')
            errored += 1
            continue
        marker = f'release_date={rel}' if rel else f'upload_date={up}'
        print(f'  SET  {slug:<60} → {chosen}  ({marker})')
        if not args.dry_run:
            cur.execute(
                'UPDATE hustings_events SET event_date = %s WHERE event_id = %s',
                (chosen, event_id),
            )
        updated += 1

    if not args.dry_run:
        conn.commit()
    print(f'\nDone. updated={updated} skipped={skipped} errored={errored}'
          f'{"  (DRY RUN — no DB writes)" if args.dry_run else ""}')


if __name__ == '__main__':
    main()
