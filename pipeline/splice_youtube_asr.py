"""
Splice YouTube ASR captions into hustings_segments.text_youtube_asr.

The Whisper+pyannote pipeline often captures audience questions as short
fragments ("things", "so yeah okay") because audience mics are distant
and pyannote splits the turn across speakers. YouTube's caption model
handles those moments materially better. Every event already has the
full `youtube_captions.vtt` on disk from yt-dlp.

For every `audience_question` row in `hustings_segments` (on events that
aren't `transcript_method = 'hand_cleaned'`), we:

  1. Determine the time window: from the segment's `timestamp_seconds`
     to the next non-audience segment's `timestamp_seconds` (or +120s,
     whichever is sooner).
  2. Pull all settled YouTube caption lines whose start time falls in
     that window.
  3. Write the concatenated text to `text_youtube_asr`.

The display layer reads `text_youtube_asr` in preference to `text` when
rendering the "as captured from audio" disclosure on each question card.

The diarised `text` field is never overwritten — this script is purely
additive and idempotent.

Run:
  python pipeline/splice_youtube_asr.py                          # all events
  python pipeline/splice_youtube_asr.py --slug st-john-meeting-...
  python pipeline/splice_youtube_asr.py --slug ... --dry-run     # parse only
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(override=True)

HUSTINGS_DIR = Path(__file__).resolve().parent / 'hustings'

# `<00:01:23.456><c> word</c>` — YouTube's word-timing tag inside a growing
# caption line. Stripping these turns a growing line into the settled text.
WORD_TAG_RE = re.compile(r'<\d{2}:\d{2}:\d{2}\.\d{3}><c>[^<]*</c>')

# `00:01:23.456 --> 00:01:24.789 align:start position:0%` — a VTT cue header.
CUE_HEADER_RE = re.compile(
    r'^(\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}\.\d{3})\b'
)


@dataclass
class Cue:
    start: float        # seconds
    end: float          # seconds
    lines: list[str]    # raw text lines (post-trim, may include tags / entities)


def parse_vtt_timestamp(ts: str) -> float:
    h, m, rest = ts.split(':')
    s, ms = rest.split('.')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_vtt(path: Path) -> list[Cue]:
    """Walk the VTT file and return a list of Cue objects. Lines that are
    entirely whitespace are still preserved within a cue (so we can tell
    one-line settled cues from two-line growth cues)."""
    cues: list[Cue] = []
    current: Cue | None = None
    for raw in path.read_text(encoding='utf-8').splitlines():
        m = CUE_HEADER_RE.match(raw.strip())
        if m:
            if current is not None:
                cues.append(current)
            current = Cue(
                start=parse_vtt_timestamp(m.group(1)),
                end=parse_vtt_timestamp(m.group(2)),
                lines=[],
            )
            continue
        if current is None:
            continue
        if raw.strip() == '' and not current.lines:
            # leading blank inside the cue; skip
            continue
        if raw.strip() == '':
            # blank line ends the cue
            cues.append(current)
            current = None
            continue
        current.lines.append(raw)
    if current is not None:
        cues.append(current)
    return cues


def settled_lines(cues: list[Cue]) -> list[tuple[float, str]]:
    """From the cue stream, emit `(start_seconds, text)` for each distinct
    settled caption line, in order. De-dupes consecutive duplicates."""
    out: list[tuple[float, str]] = []
    last_text: str | None = None
    for cue in cues:
        for line in cue.lines:
            # A line containing `<c>` is still growing — skip.
            if '<c>' in line or '<' in WORD_TAG_RE.sub('', line):
                continue
            cleaned = html.unescape(line).strip()
            if not cleaned:
                continue
            if cleaned == last_text:
                continue
            out.append((cue.start, cleaned))
            last_text = cleaned
    return out


def text_in_window(
    lines: list[tuple[float, str]],
    start: float,
    end: float,
) -> str:
    """Concatenate settled lines whose start time falls in [start, end).
    Trims duplicate `>>` speaker markers and collapses whitespace."""
    in_window = [text for t, text in lines if start <= t < end]
    if not in_window:
        return ''
    joined = ' '.join(in_window)
    # Collapse runs of whitespace and `>>` artefacts.
    joined = re.sub(r'\s+', ' ', joined).strip()
    return joined


def db_connect():
    return psycopg2.connect(
        os.environ['DATABASE_URL'],
        keepalives=1, keepalives_idle=30, keepalives_interval=10,
        keepalives_count=5, connect_timeout=15,
    )


def process_event(folder: Path, conn, cur, dry_run: bool) -> int:
    """Splice ASR text into audience_question rows for one event. Returns
    number of rows updated."""
    slug = folder.name
    vtt = folder / 'youtube_captions.vtt'
    if not vtt.exists():
        print(f'  no youtube_captions.vtt; skipping')
        return 0

    cur.execute(
        '''
        SELECT event_id, transcript_method, duration_seconds
        FROM hustings_events WHERE slug = %s
        ''',
        (slug,),
    )
    row = cur.fetchone()
    if row is None:
        print(f'  no hustings_events row for slug={slug}; skipping')
        return 0
    event_id, method, duration = row
    if method == 'hand_cleaned':
        print(f'  transcript_method=hand_cleaned; skipping (authoritative)')
        return 0

    cues = parse_vtt(vtt)
    settled = settled_lines(cues)
    if not settled:
        print(f'  VTT produced no settled lines; skipping')
        return 0

    # Pull every audience_question for this event plus the position of the
    # next non-audience segment, so we know the time window of each
    # question.
    cur.execute(
        '''
        SELECT segment_id, timestamp_seconds, position_in_event, text
        FROM hustings_segments
        WHERE event_id = %s AND segment_type = 'audience_question'
        ORDER BY position_in_event
        ''',
        (event_id,),
    )
    questions = cur.fetchall()
    if not questions:
        print(f'  no audience_question rows; nothing to splice')
        return 0

    # Get the timestamps of every non-audience-question segment in order,
    # so we can determine each question's end time.
    cur.execute(
        '''
        SELECT timestamp_seconds, position_in_event
        FROM hustings_segments
        WHERE event_id = %s
          AND segment_type <> 'audience_question'
          AND timestamp_seconds IS NOT NULL
        ORDER BY position_in_event
        ''',
        (event_id,),
    )
    other_segs = cur.fetchall()

    video_end = float(duration) if duration else (settled[-1][0] + 30)
    updates: list[tuple[int, str]] = []
    for seg_id, q_start, q_pos, q_text in questions:
        if q_start is None:
            continue
        # End time = next non-audience segment after this question's
        # position, or +120s, whichever is sooner. Cap at video_end.
        next_other_ts = next(
            (ts for ts, pos in other_segs if pos > q_pos and ts > q_start),
            None,
        )
        window_end = min(
            float(q_start) + 120.0,
            float(next_other_ts) if next_other_ts is not None else video_end,
            video_end,
        )
        spliced = text_in_window(settled, float(q_start), window_end)
        if spliced:
            updates.append((seg_id, spliced))

    if dry_run:
        for seg_id, spliced in updates:
            preview = spliced[:140].replace('\n', ' ')
            print(f'    seg_id={seg_id} [{len(spliced)} chars] {preview!r}')
        return len(updates)

    for seg_id, spliced in updates:
        cur.execute(
            'UPDATE hustings_segments SET text_youtube_asr = %s WHERE segment_id = %s',
            (spliced, seg_id),
        )
    conn.commit()
    print(f'  updated {len(updates)} audience_question rows')
    return len(updates)


def main():
    parser = argparse.ArgumentParser(
        description='Splice YouTube ASR captions into hustings_segments.text_youtube_asr.',
    )
    parser.add_argument('--slug', help='Process only this event slug')
    parser.add_argument('--dry-run', action='store_true',
                        help='Parse and report but do not write to the DB')
    args = parser.parse_args()

    if not HUSTINGS_DIR.exists():
        sys.exit(f'No hustings directory at {HUSTINGS_DIR}')

    folders = sorted(
        p for p in HUSTINGS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith('_') and not p.name.startswith('.')
    )
    if args.slug:
        folders = [p for p in folders if p.name == args.slug]
        if not folders:
            sys.exit(f'No folder named {args.slug!r} under {HUSTINGS_DIR}')

    if not folders:
        print(f'No event folders to process under {HUSTINGS_DIR}')
        return

    conn = db_connect()
    cur = conn.cursor()
    total = 0
    try:
        for folder in folders:
            print(f'[{folder.name}]')
            try:
                total += process_event(folder, conn, cur, args.dry_run)
            except Exception as e:
                print(f'  ERROR: {e}')
    finally:
        cur.close()
        conn.close()

    print(f'\nDone. {total} audience_question rows spliced.')


if __name__ == '__main__':
    main()
