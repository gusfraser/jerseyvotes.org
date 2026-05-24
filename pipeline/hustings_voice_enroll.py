"""
Enroll candidate voices for fingerprint-based identification.

For each candidate listed in the candidates table, find their solo
vote.je YouTube intro video (typically titled "<Name>: Candidate for
<Role> of <Constituency> | 2026 Election" — a ~1-3 minute monologue),
download the audio, and compute a pyannote/embedding vector. The vector
is saved to:

    pipeline/hustings/_voice_embeddings/<vote-je-slug>.npy

The library accumulates across runs — re-running for the same candidate
overwrites their reference embedding with a fresh one (use --force to
re-download). The embeddings are used by hustings_identify.py's
voice_fingerprint() strategy: each anonymous SPEAKER_NN cluster's mean
embedding is compared to enrolled references by cosine similarity, and
high-confidence matches (≥ 0.5) are accepted as that candidate.

Hard prerequisite: HF_TOKEN with access to `pyannote/embedding`
(separately gated from `pyannote/speaker-diarization-3.1`). Accept terms
at https://hf.co/pyannote/embedding.

Run:
  python pipeline/hustings_voice_enroll.py                    # all eligible candidates
  python pipeline/hustings_voice_enroll.py --slug ian-barnes  # one candidate
  python pipeline/hustings_voice_enroll.py --slug ... --force # re-download
  python pipeline/hustings_voice_enroll.py --dry-run          # search YouTube, don't download
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import psycopg2
from dotenv import load_dotenv

load_dotenv(override=True)

PIPELINE_DIR = Path(__file__).resolve().parent
HUSTINGS_DIR = PIPELINE_DIR / 'hustings'
EMBEDDINGS_DIR = HUSTINGS_DIR / '_voice_embeddings'
# Working folder for transient audio downloads — kept gitignored.
DOWNLOAD_DIR = HUSTINGS_DIR / '_voice_audio'
USER_BIN = '/Users/gusfraser/Library/Python/3.11/bin'

# vote.je channel for candidate intro videos.
VOTE_JE_CHANNEL = 'https://www.youtube.com/@VoteJersey/videos'


def db_connect():
    return psycopg2.connect(
        os.environ['DATABASE_URL'],
        keepalives=1, keepalives_idle=30, keepalives_interval=10,
        keepalives_count=5, connect_timeout=15,
    )


def load_candidates(cur, only_slug: str | None = None) -> list[dict]:
    if only_slug:
        cur.execute(
            """SELECT vote_je_slug, full_name, role, constituency FROM candidates
                WHERE election_year = 2026 AND vote_je_slug = %s""",
            (only_slug,),
        )
    else:
        cur.execute(
            """SELECT vote_je_slug, full_name, role, constituency FROM candidates
                WHERE election_year = 2026 ORDER BY full_name""",
        )
    return [
        {'slug': r[0], 'name': r[1], 'role': r[2], 'constituency': r[3]}
        for r in cur.fetchall()
    ]


_CHANNEL_CACHE: list[tuple[str, str]] | None = None


def probe_channel() -> list[tuple[str, str]]:
    """One-shot probe of the vote.je channel. Cached for the rest of the
    process — without this, scanning 92 candidates × 10s/probe = 15+ min."""
    global _CHANNEL_CACHE
    if _CHANNEL_CACHE is not None:
        return _CHANNEL_CACHE
    cmd = [
        'yt-dlp', '--flat-playlist', '--print', '%(id)s|%(title)s',
        VOTE_JE_CHANNEL,
    ]
    env = {**os.environ, 'PATH': f"{USER_BIN}:{os.environ.get('PATH','')}"}
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if proc.returncode != 0:
        print(f'  yt-dlp channel probe failed: {proc.stderr[-200:]}')
        _CHANNEL_CACHE = []
        return _CHANNEL_CACHE
    out: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if '|' not in line:
            continue
        vid, title = line.split('|', 1)
        out.append((vid.strip(), title.strip()))
    _CHANNEL_CACHE = out
    print(f'  channel probe returned {len(out)} videos (cached)')
    return out


def find_intro_video(candidate: dict, videos: list[tuple[str, str]]) -> str | None:
    """Match candidate to their solo intro video via title heuristic:
    contains full first AND last name AND mentions 2026 AND is NOT a
    hustings video."""
    name_lower = candidate['name'].lower()
    parts = name_lower.split()
    first = parts[0]
    last = parts[-1] if len(parts) > 1 else None
    for vid, title in videos:
        t_lower = title.lower()
        if 'hustings' in t_lower:
            continue
        if last and (first not in t_lower or last not in t_lower):
            continue
        if '2026' not in title:
            continue
        return vid
    return None


def download_audio(video_id: str, candidate_slug: str) -> Path | None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    out = DOWNLOAD_DIR / f'{candidate_slug}.m4a'
    if out.exists():
        return out
    cmd = [
        'yt-dlp', '-f', 'bestaudio[ext=m4a]/bestaudio/best',
        '-o', str(out), f'https://www.youtube.com/watch?v={video_id}',
    ]
    env = {**os.environ, 'PATH': f"{USER_BIN}:{os.environ.get('PATH','')}"}
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if proc.returncode != 0 or not out.exists():
        print(f'  yt-dlp download failed: {proc.stderr[-200:]}')
        return None
    return out


def m4a_to_wav(m4a_path: Path) -> Path | None:
    wav = m4a_path.with_suffix('.wav')
    if wav.exists():
        return wav
    proc = subprocess.run(
        ['ffmpeg', '-y', '-i', str(m4a_path), '-ar', '16000', '-ac', '1',
         '-c:a', 'pcm_s16le', str(wav)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        print(f'  ffmpeg failed: {proc.stderr[-200:]}')
        return None
    return wav


def compute_embedding(wav_path: Path, token: str) -> np.ndarray | None:
    from pyannote.audio import Inference
    try:
        emb_model = Inference(
            'pyannote/embedding', use_auth_token=token, window='whole',
        )
    except Exception as e:
        print(f'  pyannote/embedding load failed (gated model — accept '
              f'terms at https://hf.co/pyannote/embedding): {e}')
        return None
    try:
        vec = emb_model(str(wav_path))
        arr = np.asarray(vec).squeeze()
        return arr
    except Exception as e:
        print(f'  embedding failed: {e}')
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Enroll candidate voice fingerprints from vote.je intro videos.',
    )
    parser.add_argument('--slug', help='Process only this candidate slug')
    parser.add_argument('--force', action='store_true',
                        help='Re-download + recompute even if embedding exists')
    parser.add_argument('--dry-run', action='store_true',
                        help='Search YouTube + report matches; do not download or embed')
    parser.add_argument('--hf-token', default=os.environ.get('HF_TOKEN'),
                        help='HuggingFace token (or set HF_TOKEN env var)')
    args = parser.parse_args()

    if not args.dry_run and not args.hf_token:
        sys.exit('HF_TOKEN required for pyannote/embedding access. '
                 'Accept terms at https://hf.co/pyannote/embedding')

    conn = db_connect()
    cur = conn.cursor()
    candidates = load_candidates(cur, only_slug=args.slug)
    conn.close()

    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)

    print('Probing vote.je channel (one-shot)…')
    videos = probe_channel()

    ok = skipped = errs = 0
    for c in candidates:
        emb_path = EMBEDDINGS_DIR / f'{c["slug"]}.npy'
        if emb_path.exists() and not args.force:
            print(f'[{c["slug"]:<25}] embedding already on disk, skipping (use --force)')
            skipped += 1
            continue
        print(f'[{c["slug"]:<25}] {c["name"]}  ({c["role"]} {c.get("constituency") or ""})')
        vid = find_intro_video(c, videos)
        if not vid:
            print(f'  no intro video found on vote.je channel')
            errs += 1
            continue
        print(f'  intro video: https://youtu.be/{vid}')
        if args.dry_run:
            ok += 1
            continue
        m4a = download_audio(vid, c['slug'])
        if not m4a:
            errs += 1
            continue
        wav = m4a_to_wav(m4a)
        if not wav:
            errs += 1
            continue
        vec = compute_embedding(wav, args.hf_token)
        if vec is None:
            errs += 1
            continue
        np.save(emb_path, vec)
        print(f'  saved {emb_path} (dim={vec.shape})')
        ok += 1

    print(f'\nDone. ok={ok}, skipped={skipped}, errors={errs}')


if __name__ == '__main__':
    main()
