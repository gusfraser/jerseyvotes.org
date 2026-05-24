"""
End-to-end batch driver for all 2026 hustings videos on vote.je's YouTube.

For each video in a playlist, runs the full pipeline:
  1. metadata_from_youtube  → metadata.yaml (auto-roster from candidates DB)
  2. hustings_fetch         → audio.m4a, audio.wav, video_metadata.json
  3. hustings_transcribe    → words.json (mlx-whisper on Apple Silicon GPU)
  4. hustings_diarise       → diarised_segments.json (pyannote on MPS)
  5. hustings_identify      → transcript.md (speaker→candidate mapping)
  6. normalise_local_terms  → fixes STT garbles of local names
  7. ingest_hustings        → hustings_events + hustings_segments rows
  8. classify_hustings      → hustings_segment_topics (Claude Opus, only new segments)

Idempotent — skips events that already have transcript.md unless --force.
Failures on one event don't stop the batch — they log and continue.

Run:
  python pipeline/hustings_batch.py --playlist <senatorial-url>
  python pipeline/hustings_batch.py --all                   # all three playlists
  python pipeline/hustings_batch.py --all --skip-ingest     # just produce transcripts
  python pipeline/hustings_batch.py --all --stop-after metadata   # only generate metadata
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Local imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
import psycopg2  # noqa: E402

from hustings_metadata_from_youtube import (  # noqa: E402
    db_connect, derive_event_metadata, list_playlist_videos, load_roster,
    write_metadata,
)

HUSTINGS_DIR = Path(__file__).resolve().parent / 'hustings'
PIPELINE_DIR = Path(__file__).resolve().parent

# vote.je 2026 hustings playlists. --all expands to these.
PLAYLISTS = {
    'senatorial': 'https://www.youtube.com/playlist?list=PLvh9wd_5o5K9aRG20HhMvvX1vaTfsTGC7',
    'connetable': 'https://www.youtube.com/playlist?list=PLvh9wd_5o5K8dTOhWeYW63_XQU1GO0r21',
    'deputy':     'https://www.youtube.com/playlist?list=PLvh9wd_5o5K-padXblf3bxnptdA4MLNyY',
}

# Each stage produces a marker file. We skip stages whose marker exists,
# unless --force-stage <name>. The order here is the run order.
STAGES = ('metadata', 'fetch', 'transcribe', 'diarise', 'identify',
          'normalise', 'ingest', 'classify')


def run(cmd: list[str], *, cwd: Path | None = None, env_path: bool = True) -> int:
    """Run a subprocess, stream output, return exit code."""
    env = os.environ.copy()
    if env_path:
        # Make sure the user-installed bin (yt-dlp, mlx_whisper) is on PATH.
        user_bin = '/Users/gusfraser/Library/Python/3.11/bin'
        if user_bin not in env.get('PATH', ''):
            env['PATH'] = f"{user_bin}:{env.get('PATH', '')}"
    print(f'    $ {" ".join(cmd)}')
    proc = subprocess.run(cmd, cwd=cwd, env=env, check=False)
    return proc.returncode


def needs_stage(folder: Path, stage: str, force: bool) -> bool:
    """Return True if `stage` still needs to run.

    Stages 3-5 (transcribe / diarise / identify) all produce a
    transcript.md eventually — so if transcript.md is already on disk
    (e.g. the user supplied a hand-cleaned one, or we already processed
    this event), skip all three. This makes the batch idempotent for
    hand-supplied events without forcing the user to rename files."""
    if force:
        return True
    markers = {
        'metadata':   folder / 'metadata.yaml',
        'fetch':      folder / 'audio.m4a',
        'transcribe': folder / 'words.json',
        'diarise':    folder / 'diarised_segments.json',
        'identify':   folder / 'transcript.md',
        'normalise':  folder / '.normalised',
        'ingest':     folder / '.ingested',
        'classify':   folder / '.classified',
    }
    # Short-circuit the ASR pipeline if the canonical artefact exists.
    if stage in ('transcribe', 'diarise') and (folder / 'transcript.md').exists():
        return False
    m = markers.get(stage)
    return m is None or not m.exists()


def touch(folder: Path, name: str) -> None:
    (folder / name).write_text('')


def process_event(video_id: str, title: str, conn, cur, *,
                  force: bool, stop_after: str | None,
                  skip_stages: set[str]) -> bool:
    """Returns True on success (including idempotent skip), False on failure."""
    print(f'\n=== {title}')
    try:
        meta = derive_event_metadata(title)
    except ValueError as e:
        print(f'  parse error: {e}; skipping')
        return False
    folder = HUSTINGS_DIR / meta['event_slug']
    url = f'https://www.youtube.com/watch?v={video_id}'

    def stop_here(stage: str) -> bool:
        # stop_here is called AFTER running `stage`. We want to exit when
        # `stage` is the stop_after stage (or later, which shouldn't
        # happen but is harmless). Earlier bug used > instead of >=, which
        # let stages past stop_after sneak through.
        return stop_after is not None and STAGES.index(stage) >= STAGES.index(stop_after)

    # 1. metadata.yaml
    if 'metadata' not in skip_stages and needs_stage(folder, 'metadata', force):
        roster = load_roster(cur, meta['role'], meta['constituency'])
        if not roster:
            print(f'  WARNING: empty roster for role={meta["role"]} constituency={meta["constituency"]}')
        write_metadata(folder, meta, url, roster)
    if stop_here('metadata'):
        return True

    # 2. fetch (audio + caption + metadata json)
    if 'fetch' not in skip_stages and needs_stage(folder, 'fetch', force):
        rc = run([
            sys.executable, str(PIPELINE_DIR / 'hustings_fetch.py'),
            '--slug', meta['event_slug'], '--url', url,
        ])
        if rc != 0:
            print(f'  fetch failed (exit {rc}); skipping further stages')
            return False
    if stop_here('fetch'):
        return True

    # 3. transcribe (mlx-whisper)
    if 'transcribe' not in skip_stages and needs_stage(folder, 'transcribe', force):
        rc = run([
            sys.executable, '-u', str(PIPELINE_DIR / 'hustings_transcribe.py'),
            '--slug', meta['event_slug'], '--model', 'large-v3', '--backend', 'mlx',
        ])
        if rc != 0:
            print(f'  transcribe failed (exit {rc}); skipping further stages')
            return False
    if stop_here('transcribe'):
        return True

    # 4. diarise (pyannote on MPS). Compute per-speaker embeddings too —
    # they unlock the voice-fingerprint identify strategy that matches
    # diarised speakers against the per-candidate reference voiceprints
    # built by hustings_voice_enroll.py.
    if 'diarise' not in skip_stages and needs_stage(folder, 'diarise', force):
        rc = run([
            sys.executable, str(PIPELINE_DIR / 'hustings_diarise.py'),
            '--slug', meta['event_slug'],
            '--min-speakers', '4', '--max-speakers', '25',
        ])
        if rc != 0:
            print(f'  diarise failed (exit {rc}); skipping further stages')
            return False
    if stop_here('diarise'):
        return True

    # 5. identify (with voice fingerprinting on top of moderator-anchor +
    # self-intro). The fingerprint pass matches diarised speakers against
    # the per-candidate reference voiceprints in pipeline/hustings/
    # _voice_embeddings/ (built by hustings_voice_enroll.py from solo
    # intro videos). Don't update the reference library from hustings —
    # mis-attributed segments could pollute the clean solo refs.
    if 'identify' not in skip_stages and needs_stage(folder, 'identify', force):
        rc = run([
            sys.executable, str(PIPELINE_DIR / 'hustings_identify.py'),
            '--slug', meta['event_slug'],
            '--no-update-references', '--force',
        ])
        if rc != 0:
            print(f'  identify failed (exit {rc}); skipping further stages')
            return False
    if stop_here('identify'):
        return True

    # 6. normalise local terms (idempotent — fixes "St. Helia"→"St Helier" etc.)
    if 'normalise' not in skip_stages and needs_stage(folder, 'normalise', force):
        rc = run([
            sys.executable, str(PIPELINE_DIR / 'normalise_local_terms.py'),
            '--slug', meta['event_slug'],
        ])
        if rc != 0:
            print(f'  normalise failed (exit {rc}); skipping further stages')
            return False
        touch(folder, '.normalised')
    if stop_here('normalise'):
        return True

    # 7. ingest into DB
    if 'ingest' not in skip_stages and needs_stage(folder, 'ingest', force):
        rc = run([
            sys.executable, str(PIPELINE_DIR / 'ingest_hustings.py'),
            '--slug', meta['event_slug'],
        ])
        if rc != 0:
            print(f'  ingest failed (exit {rc}); skipping further stages')
            return False
        touch(folder, '.ingested')
    if stop_here('ingest'):
        return True

    # 8. classify topics
    if 'classify' not in skip_stages and needs_stage(folder, 'classify', force):
        rc = run([
            sys.executable, str(PIPELINE_DIR / 'classify_hustings.py'),
            '--slug', meta['event_slug'],
        ])
        if rc != 0:
            print(f'  classify failed (exit {rc}); leaving for manual rerun')
            return False
        touch(folder, '.classified')

    return True


def main():
    parser = argparse.ArgumentParser(
        description='Run the full hustings pipeline across one or more playlists.',
    )
    parser.add_argument('--playlist', action='append', default=[],
                        help='Playlist URL (can be repeated). Or use --all.')
    parser.add_argument('--all', action='store_true',
                        help='Process all three 2026 vote.je playlists.')
    parser.add_argument('--video', action='append', default=[],
                        help='Process a single video URL (can be repeated).')
    parser.add_argument('--force', action='store_true',
                        help='Re-run every stage even if outputs exist.')
    parser.add_argument('--stop-after', choices=STAGES,
                        help='Run up to and including this stage, then stop.')
    parser.add_argument('--skip', action='append', default=[],
                        choices=STAGES,
                        help='Skip these stages entirely (can be repeated).')
    parser.add_argument('--limit', type=int, default=0,
                        help='Process at most N events.')
    args = parser.parse_args()

    if args.all:
        urls = list(PLAYLISTS.values())
    else:
        urls = list(args.playlist)
    if not urls and not args.video:
        sys.exit('Use --all, --playlist, or --video.')

    # Collect (video_id, title) pairs.
    videos: list[tuple[str, str]] = []
    for u in urls:
        try:
            videos.extend(list_playlist_videos(u))
        except RuntimeError as e:
            print(f'WARN: could not probe playlist {u}: {e}')
    # And explicit --video URLs (probe each for title).
    for u in args.video:
        m = u.split('v=')[-1].split('&')[0] if 'v=' in u else u.rsplit('/', 1)[-1]
        videos.append((m, _probe_title(u)))

    # Dedup preserving order.
    seen = set()
    deduped = []
    for v in videos:
        if v[0] in seen:
            continue
        seen.add(v[0])
        deduped.append(v)
    videos = deduped

    if args.limit:
        videos = videos[: args.limit]
    print(f'Processing {len(videos)} videos')

    conn = db_connect()
    cur = conn.cursor()
    ok = errs = 0
    started = time.time()
    try:
        for i, (vid, title) in enumerate(videos, 1):
            print(f'\n========== [{i}/{len(videos)}] {vid} ==========')
            # Wrap each event in try/except + DB-reconnect logic so a
            # Neon SSL drop (or any other transient error in a subprocess)
            # doesn't kill the whole batch. Each event's state is on disk
            # (markers) so resuming is safe.
            for attempt in range(3):
                try:
                    success = process_event(
                        vid, title, conn, cur,
                        force=args.force,
                        stop_after=args.stop_after,
                        skip_stages=set(args.skip),
                    )
                    break
                except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                    print(f'  DB error (attempt {attempt+1}/3): {e}')
                    try:
                        cur.close(); conn.close()
                    except Exception:
                        pass
                    time.sleep(2)
                    conn = db_connect()
                    cur = conn.cursor()
                except Exception as e:
                    print(f'  UNEXPECTED ERROR on event {vid}: {e}')
                    success = False
                    break
            else:
                # All 3 retry attempts exhausted.
                print(f'  giving up on event {vid} after 3 DB-reconnect attempts')
                success = False

            if success:
                ok += 1
            else:
                errs += 1
            elapsed = time.time() - started
            print(f'  [running totals: ok={ok}, errs={errs}, elapsed={elapsed/60:.1f}min]')
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
    print(f'\nBatch done. ok={ok}, errs={errs}, total={ok+errs}')


def _probe_title(url: str) -> str:
    proc = subprocess.run(
        ['yt-dlp', '--print', '%(title)s', url],
        capture_output=True, text=True, check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ''


if __name__ == '__main__':
    main()
