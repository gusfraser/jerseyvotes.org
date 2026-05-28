"""
Generate pipeline/hustings/<event-slug>/metadata.yaml automatically from a
vote.je YouTube video URL.

Parses the video title to determine role + constituency, queries the
candidates table for the matching roster, and writes the metadata file
ready for hustings_fetch + transcribe + diarise + identify + ingest.

Title patterns recognised (vote.je's house style — defensive matching):
  - "Senatorial hustings 2026 at St. Saviour"
  - "Connétable hustings 2026: Connétable of St. John"
  - "Deputies hustings 2026: Deputies of St. Helier North"
  - "Deputies hustings 2026: Deputies of St. Mary, St. Ouen and St. Peter"
  - "Deputies hustings 2026: Deputies of St. John, St. Lawrence and Trinity: St. John"

Audience members ("(Audience)" suffix) are handled by ingest at parse
time; only the candidate roster + moderator list are pre-populated here.

Run:
  python pipeline/hustings_metadata_from_youtube.py --url https://youtu.be/X98Z60MSRXs
  python pipeline/hustings_metadata_from_youtube.py --playlist https://www.youtube.com/playlist?list=...
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import psycopg2
import yaml
from dotenv import load_dotenv

load_dotenv(override=True)

HUSTINGS_DIR = Path(__file__).resolve().parent / 'hustings'


# Canonical parish names (matches PARISHES in web/src/lib/db.ts) and a
# regex tolerating both "St." and "St" (and lower-cased "st").
PARISHES = [
    'St Helier', 'St Saviour', 'St Brelade', 'St Clement', 'St Lawrence',
    'Trinity', 'Grouville', 'St Peter', 'St Ouen', 'St John', 'St Martin',
    'St Mary',
]


def normalise_parish(s: str) -> str:
    """Drop "St." → "St", collapse whitespace, "&" → "and" for canonical
    constituency names."""
    s = re.sub(r'\bSt\.\s+', 'St ', s)
    s = re.sub(r'\s*&\s*', ' and ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def derive_event_metadata(title: str) -> dict:
    """Parse a vote.je hustings video title into structured metadata.
    Returns dict with: role, constituency, event_slug, suggested_title.
    Raises ValueError on titles we can't parse."""
    t = normalise_parish(title)
    role = None
    constituency = None
    extra_suffix = ''  # for multi-meeting events ("…: St John")

    # Senatorial hustings — role=Senator, constituency=NULL (island-wide
    # candidates). We use the location of the event in the slug to keep
    # slugs unique across the 8 senatorial dates.
    m = re.search(r'\bSenatorial\s+hustings(?:\s+\d{4})?\s+at\s+(.+)$', t, re.IGNORECASE)
    if m:
        location = m.group(1).strip().rstrip('.')
        role = 'Senator'
        constituency = None  # senators are island-wide; location is informational
        slug_suffix = _slugify(location)
        event_slug = f'senatorial-{slug_suffix}-2026'
        return {
            'role': role,
            'constituency': constituency,
            'location': location,
            'event_slug': event_slug,
            'suggested_title': f'Senatorial Hustings 2026 ({location})',
        }

    # Connétable hustings — role=Connétable, constituency=<parish>.
    m = re.search(r'Conn[ée]table\s+(?:[Hh]ustings)?\s*(?:\d{4})?\s*[:\-]?\s*Conn[ée]table\s+of\s+(.+)$', t, re.IGNORECASE)
    if m:
        parish = m.group(1).strip().rstrip('.')
        parish = _canonical_parish(parish)
        role = 'Connétable'
        constituency = parish
        event_slug = f'{_slugify(parish)}-connetable-2026'
        return {
            'role': role,
            'constituency': constituency,
            'location': parish,
            'event_slug': event_slug,
            'suggested_title': f'Connétable of {parish} Hustings 2026',
        }

    # Deputy hustings — role=Deputy, constituency=<one or more districts>.
    # Watch out for the typo case "Deputies hustings: 2026:" and the
    # multi-meeting case ending with ": <parish>".
    m = re.search(
        r'\bDeputies?\s+hustings:?\s*(?:\d{4})?\s*[:\-]?\s*'
        r'(?:Deputies?\s+for\s+|Deputies?\s+of\s+|Candidates?\s+for\s+Deputy\s+of\s+)'
        r'(.+)$', t, re.IGNORECASE,
    )
    if m:
        rest = m.group(1).strip().rstrip('.')
        # Multi-meeting: "St. John, St. Lawrence and Trinity: St. John"
        # → constituency = "St John, St Lawrence and Trinity"
        #   suffix = "St John" (which meeting)
        if ':' in rest:
            constituency, _, extra_suffix = rest.partition(':')
            constituency = constituency.strip()
            extra_suffix = extra_suffix.strip().rstrip('.')
        else:
            constituency = rest
        constituency = _canonical_constituency(constituency)
        role = 'Deputy'
        slug_parts = [_slugify(constituency), 'deputy', '2026']
        if extra_suffix:
            slug_parts.insert(0, _slugify(extra_suffix) + '-meeting')
        event_slug = '-'.join(slug_parts)
        title_suffix = f' ({extra_suffix} meeting)' if extra_suffix else ''
        return {
            'role': role,
            'constituency': constituency,
            'location': extra_suffix or constituency,
            'event_slug': event_slug,
            'suggested_title': f'Deputy of {constituency} Hustings 2026{title_suffix}',
        }

    # LIVE-stream titles: vote.je posts live-streamed hustings with a
    # temporary title like "LIVE HUSTINGS: Senators, Trinity" or
    # "LIVE HUSTINGS: Deputy, St. Peter", and only renames to the
    # canonical form ("Senatorial hustings 2026 at Trinity" /
    # "Deputies hustings 2026: Deputies of St. Peter") hours or days
    # later. Matching the informal title here lets the pipeline ingest
    # the recording the morning after the live, without waiting for
    # vote.je's editor. The eventual rename produces the same event_slug
    # so subsequent --all runs are idempotent.
    m = re.search(r'\bLIVE\s+HUSTINGS\s*:\s*Senators?\s*,\s*(.+)$', t, re.IGNORECASE)
    if m:
        location = m.group(1).strip().rstrip('.')
        role = 'Senator'
        constituency = None
        event_slug = f'senatorial-{_slugify(location)}-2026'
        return {
            'role': role,
            'constituency': constituency,
            'location': location,
            'event_slug': event_slug,
            'suggested_title': f'Senatorial Hustings 2026 ({location})',
        }

    m = re.search(r'\bLIVE\s+HUSTINGS\s*:\s*Conn[ée]tables?\s*,\s*(.+)$', t, re.IGNORECASE)
    if m:
        parish = _canonical_parish(m.group(1).strip().rstrip('.'))
        role = 'Connétable'
        constituency = parish
        event_slug = f'{_slugify(parish)}-connetable-2026'
        return {
            'role': role,
            'constituency': constituency,
            'location': parish,
            'event_slug': event_slug,
            'suggested_title': f'Connétable of {parish} Hustings 2026',
        }

    m = re.search(r'\bLIVE\s+HUSTINGS\s*:\s*Deput(?:y|ies)\s*,\s*(.+)$', t, re.IGNORECASE)
    if m:
        raw = m.group(1).strip().rstrip('.')
        # The LIVE title gives a single parish like "St. Peter". For
        # standalone Deputy constituencies (St Brelade / St Clement /
        # St Saviour / St Helier {North,Central,South}) that's the
        # whole constituency; for the multi-parish constituencies the
        # parish names a separate meeting of the wider constituency
        # (e.g. "St. Peter" = St Peter meeting of "St Mary, St Ouen
        # and St Peter"). Resolve which case this is so the slug
        # mirrors the canonical multi-meeting pattern used elsewhere
        # (e.g. st-peter-meeting-st-mary-st-ouen-and-st-peter-deputy-2026).
        constituency, meeting_suffix = _resolve_deputy_constituency(raw)
        role = 'Deputy'
        slug_parts = [_slugify(constituency), 'deputy', '2026']
        if meeting_suffix:
            slug_parts.insert(0, _slugify(meeting_suffix) + '-meeting')
        event_slug = '-'.join(slug_parts)
        title_suffix = f' ({meeting_suffix} meeting)' if meeting_suffix else ''
        return {
            'role': role,
            'constituency': constituency,
            'location': meeting_suffix or constituency,
            'event_slug': event_slug,
            'suggested_title': f'Deputy of {constituency} Hustings 2026{title_suffix}',
        }

    raise ValueError(f'unrecognised hustings title pattern: {title!r}')


def _slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s-]", '', s, flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", '-', s)
    return s.strip('-')


def _canonical_parish(s: str) -> str:
    s = normalise_parish(s)
    for p in PARISHES:
        if s.lower() == p.lower():
            return p
    return s


def _canonical_constituency(s: str) -> str:
    """Parishes are 1:1; multi-parish constituencies normalised to known
    canonical names; otherwise return cleaned input."""
    s = normalise_parish(s)
    for name in list(_CANONICAL_MULTI_DEPUTY) + PARISHES:
        if s.lower() == name.lower():
            return name
    return s


# Standalone Deputy constituencies for 2026 (single-parish or
# single-district, contested as one seat group). St Helier North/
# Central/South are *districts* of St Helier but are deputy
# constituencies in their own right.
_STANDALONE_DEPUTY = (
    'St Brelade', 'St Clement', 'St Saviour',
    'St Helier North', 'St Helier Central', 'St Helier South',
)

# Multi-parish Deputy constituencies. These run separate meetings in
# each constituent parish (e.g. "Deputies of St Mary, St Ouen and
# St Peter: St Peter") so the parish in a LIVE-stream title is a
# meeting suffix, not the constituency.
_CANONICAL_MULTI_DEPUTY = (
    'St John, St Lawrence and Trinity',
    'Grouville and St Martin',
    'St Mary, St Ouen and St Peter',
)


def _resolve_deputy_constituency(raw: str) -> tuple[str, str]:
    """Resolve a parish/constituency token from a LIVE-stream Deputy
    title into (canonical_constituency, meeting_suffix).

      - "St Brelade"  → ("St Brelade", "")            standalone
      - "St Peter"    → ("St Mary, St Ouen and St Peter", "St Peter")
      - "Grouville"   → ("Grouville and St Martin", "Grouville")
      - "Trinity"     → ("St John, St Lawrence and Trinity", "Trinity")

    Falls back to the cleaned input as a standalone constituency if no
    mapping fits, to keep the parser monotonically permissive."""
    canon = _canonical_constituency(raw)
    if canon in _STANDALONE_DEPUTY:
        return canon, ''
    for multi in _CANONICAL_MULTI_DEPUTY:
        tokens = re.split(r',\s*|\s+and\s+', multi)
        if canon in tokens:
            return multi, canon
    return canon, ''


def db_connect():
    return psycopg2.connect(
        os.environ['DATABASE_URL'],
        keepalives=1, keepalives_idle=30, keepalives_interval=10,
        keepalives_count=5, connect_timeout=15,
    )


def load_roster(cur, role: str, constituency: str | None,
                election_year: int = 2026) -> list[dict]:
    """Pull candidates from the DB for the given role + constituency.
    For role='Senator', constituency is ignored (island-wide).

    NOTE: opted-out candidates ARE included here. They still spoke at
    the hustings — the transcript and ASR pipeline need every name to
    attribute speech correctly. The display layer (candidate page,
    per-event page) handles opt-out by hiding/greying their segments."""
    if role == 'Senator':
        cur.execute(
            """SELECT full_name, vote_je_slug FROM candidates
                WHERE role = 'Senator' AND election_year = %s
                ORDER BY full_name""",
            (election_year,),
        )
    else:
        cur.execute(
            """SELECT full_name, vote_je_slug FROM candidates
                WHERE role = %s AND constituency = %s AND election_year = %s
                ORDER BY full_name""",
            (role, constituency, election_year),
        )
    return [{'name': r[0], 'vote_je_slug': r[1]} for r in cur.fetchall()]


def write_metadata(folder: Path, meta: dict, youtube_url: str,
                   roster: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    body = {
        'event_slug': meta['event_slug'],
        'title': meta['suggested_title'],
        'role': meta['role'],
        'constituency': meta['constituency'],
        'election_year': 2026,
        'event_date': None,        # populated by ingest from video_metadata.json
        'youtube_url': youtube_url,
        'transcript_source_url': (
            f'https://github.com/gusfraser/jerseyvotes.org/blob/main/'
            f'pipeline/hustings/{meta["event_slug"]}/transcript.md'
        ),
        'candidates': roster,
        'moderator_names': [],     # populated manually after listening to the opening
        # Reviewer overrides: relabel raw pyannote SPEAKER_NN labels by
        # listening to a sample (or scanning transcript.md) and adding
        # entries here, then re-running identify + ingest. Example:
        #
        # speaker_overrides:
        #   SPEAKER_07: Guy de Faye        # candidate full name (must
        #                                  # exist in `candidates` above)
        #   SPEAKER_18: '(Audience)'       # mark as audience question
        #   SPEAKER_16: drop               # drop these segments entirely
        'speaker_overrides': {},
    }
    meta_path = folder / 'metadata.yaml'
    meta_path.write_text(
        yaml.safe_dump(body, sort_keys=False, allow_unicode=True),
        encoding='utf-8',
    )
    print(f'  wrote {meta_path} ({len(roster)} candidates)')


def list_playlist_videos(playlist_url: str) -> list[tuple[str, str]]:
    proc = subprocess.run(
        ['yt-dlp', '--flat-playlist', '--print', '%(id)s|%(title)s', playlist_url],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f'yt-dlp playlist probe failed: {proc.stderr}')
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or 'NA' in line.split('|', 1)[0]:
            continue
        try:
            vid, title = line.split('|', 1)
        except ValueError:
            continue
        # Skip placeholders + test videos
        if 'test' in title.lower() and len(title) < 30:
            print(f'  skipping (looks like a test): {title!r}')
            continue
        out.append((vid.strip(), title.strip()))
    return out


def video_title(video_url: str) -> str:
    proc = subprocess.run(
        ['yt-dlp', '--print', '%(title)s', video_url],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f'yt-dlp title probe failed: {proc.stderr}')
    return proc.stdout.strip()


def process_video(video_url: str, title: str | None, conn, cur, *,
                  overwrite: bool = False) -> str | None:
    """Returns the event_slug on success, None on skip / failure."""
    if not title:
        try:
            title = video_title(video_url)
        except RuntimeError as e:
            print(f'  title probe failed: {e}')
            return None
    print(f'\n[{title}]')
    try:
        meta = derive_event_metadata(title)
    except ValueError as e:
        print(f'  parse error: {e}')
        return None

    folder = HUSTINGS_DIR / meta['event_slug']
    meta_path = folder / 'metadata.yaml'
    if meta_path.exists() and not overwrite:
        print(f'  metadata.yaml already exists at {folder.name} (use --overwrite)')
        return meta['event_slug']

    roster = load_roster(cur, meta['role'], meta['constituency'])
    if not roster:
        print(f'  WARNING: no candidates in DB for role={meta["role"]!r} '
              f'constituency={meta["constituency"]!r}')
    write_metadata(folder, meta, video_url, roster)
    return meta['event_slug']


def main():
    parser = argparse.ArgumentParser(
        description='Auto-generate hustings metadata.yaml from YouTube URLs.',
    )
    parser.add_argument('--url', help='Process a single video URL')
    parser.add_argument('--playlist', help='Process every video in a playlist')
    parser.add_argument('--overwrite', action='store_true',
                        help='Overwrite existing metadata.yaml files')
    args = parser.parse_args()

    if not args.url and not args.playlist:
        sys.exit('Either --url or --playlist is required.')

    conn = db_connect()
    cur = conn.cursor()
    try:
        if args.playlist:
            videos = list_playlist_videos(args.playlist)
            print(f'found {len(videos)} videos in playlist')
            for vid, title in videos:
                process_video(
                    f'https://www.youtube.com/watch?v={vid}', title,
                    conn, cur, overwrite=args.overwrite,
                )
        else:
            process_video(args.url, None, conn, cur, overwrite=args.overwrite)
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
