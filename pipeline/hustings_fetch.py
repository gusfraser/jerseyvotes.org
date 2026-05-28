"""
Download a vote.je hustings video (audio + metadata + captions) via yt-dlp.

The vote.je YouTube channel is at https://www.youtube.com/c/VoteJersey.
This script writes into the same event-folder layout used by
ingest_hustings.py:

    pipeline/hustings/<event-slug>/
        audio.m4a              — best-quality audio-only stream
        video_metadata.json    — title, duration, upload_date, description, chapters
        youtube_captions.vtt   — creator-uploaded captions when present (else absent)

The captions file (if present) is useful as a sanity check against the
Whisper transcript in the next stage — large divergences usually mean
either captions are auto-generated for a different language or the audio
is noisy. Either way, worth surfacing.

Polite-by-default:
  - exits cleanly if audio.m4a already exists (use --force to re-download)
  - sleeps between requests when fetching multiple videos
  - respects yt-dlp's built-in throttling

Run:
  python pipeline/hustings_fetch.py --slug sthelier-connetable-2026
  python pipeline/hustings_fetch.py --slug sthelier-connetable-2026 \\
      --url https://www.youtube.com/watch?v=VIDEO_ID
  python pipeline/hustings_fetch.py --playlist https://www.youtube.com/playlist?list=...

When --url is given, the YouTube URL is written into the event's
metadata.yaml so subsequent runs use it. When --playlist is given, each
video in the playlist is fetched into its own event folder derived from
its title — these need a metadata.yaml hand-written afterwards before
ingest_hustings.py can process them.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

HUSTINGS_DIR = Path(__file__).resolve().parent / 'hustings'


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def ytdlp_available() -> bool:
    try:
        subprocess.run(
            ['yt-dlp', '--version'], capture_output=True, check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def fetch_one(event_folder: Path, url: str, force: bool = False) -> None:
    audio_path = event_folder / 'audio.m4a'
    meta_path = event_folder / 'video_metadata.json'
    captions_path = event_folder / 'youtube_captions.vtt'

    if audio_path.exists() and not force:
        print(f'  audio.m4a already present (use --force to re-download)')
        return

    event_folder.mkdir(parents=True, exist_ok=True)

    # yt-dlp options:
    #   -f bestaudio[ext=m4a]/bestaudio/best  → smallest audio-only stream
    #   --write-info-json                     → metadata dump
    #   --write-subs --write-auto-subs        → captions if any
    #   --sub-langs en.*                      → English variants
    #   --convert-subs vtt                    → standardise to VTT
    cmd = [
        'yt-dlp',
        '-f', 'bestaudio[ext=m4a]/bestaudio/best',
        '-o', str(event_folder / '%(title)s.%(ext)s'),
        '--no-playlist',
        '--write-info-json',
        '--write-subs', '--write-auto-subs',
        '--sub-langs', 'en.*',
        '--convert-subs', 'vtt',
        '--restrict-filenames',
        url,
    ]
    print(f'  $ {" ".join(cmd)}')
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        # yt-dlp often exits non-zero on LIVE-stream recordings because
        # the DASH subtitle fragments fail mid-download even though the
        # audio download succeeded. Don't bail here — fall through to the
        # rename + audio.m4a existence check, which is the real signal.
        print(f'  yt-dlp exited with code {proc.returncode} '
              '(continuing — checking for audio file)')

    # Clean up any partial subtitle fragments left behind by a failed
    # DASH subtitle download so they don't confuse the rename loop or
    # downstream stages.
    for stale in event_folder.iterdir():
        if stale.is_file() and (
            stale.name.endswith('.vtt.part') or stale.name.endswith('.vtt.ytdl')
        ):
            stale.unlink()

    # yt-dlp writes files named after the video title — rename to the
    # canonical fixed names so downstream stages don't have to guess.
    for f in event_folder.iterdir():
        if f.is_file() and f.suffix == '.m4a' and f.name != 'audio.m4a':
            f.rename(audio_path)
        elif f.is_file() and f.suffix == '.json' and f.name != 'video_metadata.json':
            f.rename(meta_path)
        elif f.is_file() and f.suffix == '.vtt' and f.name != 'youtube_captions.vtt':
            f.rename(captions_path)

    if not audio_path.exists():
        print('  audio.m4a not produced — check yt-dlp output above')
        return

    # WAV conversion is done on-demand by hustings_diarise.py (and cleaned
    # up afterwards) so we don't store 25 × ~240MB of working files.
    # mlx-whisper reads m4a directly via its internal ffmpeg, so it
    # doesn't need a WAV either.


def fetch_playlist(playlist_url: str, force: bool = False) -> None:
    """Discover each video in the playlist and fetch into its own folder.

    The folder name is derived from the video title. Each new folder is
    seeded with a stub metadata.yaml so the user knows what to fill in
    before ingest_hustings.py can use it."""
    # Probe playlist for video titles & ids.
    cmd = [
        'yt-dlp', '--flat-playlist', '--print', '%(id)s|%(title)s',
        playlist_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f'  yt-dlp playlist probe failed (exit {proc.returncode})')
        print(proc.stderr)
        return
    lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
    print(f'  found {len(lines)} videos in playlist')
    for i, line in enumerate(lines):
        try:
            vid, title = line.split('|', 1)
        except ValueError:
            continue
        slug = slugify(title)[:60] or f'hustings-{vid}'
        folder = HUSTINGS_DIR / slug
        url = f'https://www.youtube.com/watch?v={vid}'
        print(f'[{i+1}/{len(lines)}] {slug}')
        fetch_one(folder, url, force=force)
        # Write stub metadata.yaml so the user can fill in the roster.
        stub = folder / 'metadata.yaml'
        if not stub.exists():
            stub.write_text(
                _stub_metadata(slug, title, url), encoding='utf-8',
            )
            print(f'  wrote stub metadata.yaml — fill in candidates roster before ingest')
        time.sleep(2.0)


def _stub_metadata(slug: str, title: str, url: str) -> str:
    return (
        f'# Auto-generated stub. Fill in role, constituency, candidates,\n'
        f'# moderator_names, then run hustings_transcribe.py / diarise.py /\n'
        f'# identify.py to produce transcript.md.\n\n'
        f'event_slug: {slug}\n'
        f'title: "{title}"\n'
        f'role:         # Deputy / Connétable / Senator\n'
        f'constituency: # parish or district name\n'
        f'election_year: 2026\n'
        f'event_date:   # YYYY-MM-DD (yt-dlp upload_date in video_metadata.json)\n'
        f'youtube_url: "{url}"\n'
        f'transcript_source_url: ""  # GitHub blob URL once transcript.md is committed\n\n'
        f'candidates:\n'
        f'  # - name: "Full Name"\n'
        f'  #   vote_je_slug: full-name-1\n\n'
        f'moderator_names:\n'
        f'  # - "Moderator name"\n'
    )


def update_metadata_url(event_folder: Path, url: str) -> None:
    """Write the URL into metadata.yaml so subsequent ingest runs include it."""
    meta_path = event_folder / 'metadata.yaml'
    if not meta_path.exists():
        return
    try:
        data = yaml.safe_load(meta_path.read_text()) or {}
    except yaml.YAMLError:
        return
    if data.get('youtube_url') == url:
        return
    data['youtube_url'] = url
    meta_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(
        description='Download vote.je hustings audio + metadata via yt-dlp.',
    )
    parser.add_argument('--slug', help='Event slug (folder name under pipeline/hustings/)')
    parser.add_argument('--url', help='YouTube URL for a single video')
    parser.add_argument('--playlist', help='YouTube playlist URL — fetch each video into its own folder')
    parser.add_argument('--force', action='store_true',
                        help='Re-download even if audio.m4a is present')
    args = parser.parse_args()

    if not ytdlp_available():
        sys.exit('yt-dlp is not installed or not on PATH. pip install yt-dlp')

    if args.playlist:
        fetch_playlist(args.playlist, force=args.force)
        return

    if not args.slug:
        sys.exit('Either --slug + --url, or --playlist, is required.')

    folder = HUSTINGS_DIR / args.slug
    if args.url:
        folder.mkdir(parents=True, exist_ok=True)
        fetch_one(folder, args.url, force=args.force)
        update_metadata_url(folder, args.url)
        return

    # No URL — read it from metadata.yaml.
    meta_path = folder / 'metadata.yaml'
    if not meta_path.exists():
        sys.exit(f'No metadata.yaml in {folder}; provide --url or create one.')
    try:
        data = yaml.safe_load(meta_path.read_text()) or {}
    except yaml.YAMLError as e:
        sys.exit(f'metadata.yaml parse error: {e}')
    url = (data.get('youtube_url') or '').strip()
    if not url:
        sys.exit('metadata.yaml has no youtube_url; provide --url.')
    fetch_one(folder, url, force=args.force)

    # Surface what was fetched.
    info_path = folder / 'video_metadata.json'
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text())
            print(f'  upload_date={info.get("upload_date")} '
                  f'duration={info.get("duration")}s '
                  f'title={info.get("title")!r}')
        except json.JSONDecodeError:
            pass


if __name__ == '__main__':
    main()
