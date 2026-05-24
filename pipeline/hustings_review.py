"""
Interactive reviewer tool for auto-pipeline hustings transcripts.

Walks through an event's unmapped or low-confidence speaker labels and
lets the reviewer add `speaker_overrides` entries to metadata.yaml.
After review, re-runs identify + ingest + classify so the changes land
in the DB.

Shows for each speaker label:
  * raw label (e.g. SPEAKER_07)
  * number of segments, total speaking time, longest turn
  * first 200 chars of their longest segment (so you can pattern-match
    on the candidate's name / mannerisms / topic)
  * timestamp of their first long turn (so you can scrub to that point
    in the YouTube video)

The reviewer types one of:
  * a candidate name from the roster (fuzzy-completed) → speaker_overrides
    sets this label → that candidate
  * "audience"      → tag as (Audience)
  * "drop"          → discard segments for this label
  * "skip" (or Enter) → leave as-is for now (remains unidentified)

Then offers to re-run the downstream pipeline.

Run:
  python pipeline/hustings_review.py --slug senatorial-st-lawrence-2026
  python pipeline/hustings_review.py --slug ... --no-rerun   # just edit metadata
  python pipeline/hustings_review.py --slug ... --show-all   # include known
                                                              # speakers too
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml

PIPELINE_DIR = Path(__file__).resolve().parent
HUSTINGS_DIR = PIPELINE_DIR / 'hustings'


def fmt_hms(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m:02d}:{s:02d}'


def aggregate(segs: list[dict]) -> dict[str, dict]:
    """For each speaker_label produce a summary: total time, longest turn,
    # of segments, first-seen time, sample text from longest turn."""
    summary: dict[str, dict] = defaultdict(lambda: {
        'total': 0.0, 'longest': 0.0, 'turns': 0,
        'first_start': 1e9, 'longest_text': '', 'longest_start': 0.0,
    })
    for s in segs:
        sp = s['speaker_label']
        dur = s['end'] - s['start']
        d = summary[sp]
        d['total'] += dur
        d['turns'] += 1
        d['first_start'] = min(d['first_start'], s['start'])
        if dur > d['longest']:
            d['longest'] = dur
            d['longest_text'] = s['text']
            d['longest_start'] = s['start']
    return dict(summary)


def fuzzy_complete(prompt: str, choices: list[str]) -> str | None:
    """Substring match against the candidate list. If exactly one match,
    return it; if multiple, ask which; if none, return None."""
    p = prompt.strip().lower()
    if not p:
        return None
    matches = [c for c in choices if p in c.lower()]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    print('  multiple matches:')
    for i, m in enumerate(matches, 1):
        print(f'    {i}. {m}')
    pick = input('  pick number (or blank to cancel): ').strip()
    if pick.isdigit() and 1 <= int(pick) <= len(matches):
        return matches[int(pick) - 1]
    return None


def main():
    parser = argparse.ArgumentParser(
        description='Interactive reviewer for auto-pipeline hustings transcripts.',
    )
    parser.add_argument('--slug', required=True, help='Event slug')
    parser.add_argument('--no-rerun', action='store_true',
                        help='Skip the identify + ingest + classify rerun at the end')
    parser.add_argument('--show-all', action='store_true',
                        help='Also show already-identified speakers (default: only review unmapped)')
    args = parser.parse_args()

    folder = HUSTINGS_DIR / args.slug
    meta_path = folder / 'metadata.yaml'
    diarised_path = folder / 'diarised_segments.json'

    if not folder.exists():
        sys.exit(f'No event folder at {folder}')
    if not meta_path.exists():
        sys.exit(f'No metadata.yaml in {folder}')
    if not diarised_path.exists():
        sys.exit(f'No diarised_segments.json in {folder} — run hustings_diarise.py first')

    meta = yaml.safe_load(meta_path.read_text()) or {}
    overrides: dict[str, str] = dict(meta.get('speaker_overrides') or {})

    candidates = [c.get('name', '') for c in (meta.get('candidates') or []) if c.get('name')]
    moderator_names = list(meta.get('moderator_names') or [])

    segs = json.loads(diarised_path.read_text())
    summary = aggregate(segs)

    # Filter speakers to show. By default skip those that are clearly
    # already mapped (have a candidate name in the existing transcript.md)
    # or are tiny (< 5s total, can't usefully review).
    transcript_md = folder / 'transcript.md'
    already_mapped: set[str] = set()
    if transcript_md.exists():
        text = transcript_md.read_text()
        # Lines like `**[mm:ss] Name:**` — extract the names that appear
        # alongside any SPEAKER_NN raw label. Anything unmapped renders
        # the raw label in <angle brackets>.
        for m in re.finditer(r'\*\*\[[\d:]+\]\s+([^:]+):\*\*', text):
            name = m.group(1).strip()
            if name == '(Moderator)':
                continue
            if name.startswith('<'):
                continue
            # Map name → speaker_label is non-trivial. Just collect names.
            already_mapped.add(name)

    youtube_url = (meta.get('youtube_url') or '').strip()

    print(f'\n=== Reviewing {args.slug} ===')
    print(f'YouTube: {youtube_url or "(no URL set)"}')
    print(f'Total speaker labels: {len(summary)}')
    print(f'Roster: {len(candidates)} candidates')
    print(f'Existing overrides: {len(overrides)}')
    print()

    # Sort by total speaking time descending — review the most significant first.
    speakers_sorted = sorted(summary.items(), key=lambda kv: -kv[1]['total'])

    n_changed = 0
    for sp_label, st in speakers_sorted:
        already_overridden = sp_label in overrides
        if already_overridden and not args.show_all:
            continue
        if st['total'] < 5.0 and not args.show_all:
            # too brief to review usefully; will likely be background / drop
            continue
        # If the speaker is already mapped via transcript.md (i.e. they
        # got a name in the last identify run) AND they have a long-turn
        # signature consistent with that, skip in default mode.
        # (We don't have the speaker→name map directly here; just trust
        # the user can use --show-all for full review.)

        ts = fmt_hms(st['longest_start'])
        yt_link = f'  YouTube: {youtube_url}?t={int(st["longest_start"])}' if youtube_url else ''
        print('─' * 78)
        print(f'{sp_label}  total={st["total"]:.0f}s  longest={st["longest"]:.0f}s  turns={st["turns"]}')
        print(f'  longest-turn timestamp: {ts}{yt_link}')
        print(f'  sample text:')
        print(f'    "{st["longest_text"][:240].strip()}"')
        if already_overridden:
            print(f'  current override: {sp_label} → {overrides[sp_label]}')

        prompt = (
            '  → candidate name (substring ok), '
            '"audience", "drop", "skip" (Enter): '
        )
        try:
            ans = input(prompt).strip()
        except EOFError:
            print('  EOF — stopping review.')
            break
        if not ans or ans.lower() == 'skip':
            continue
        if ans.lower() == 'drop':
            overrides[sp_label] = 'drop'
            print(f'  set: {sp_label} → drop')
            n_changed += 1
        elif ans.lower() == 'audience':
            overrides[sp_label] = '(Audience)'
            print(f'  set: {sp_label} → (Audience)')
            n_changed += 1
        else:
            match = fuzzy_complete(ans, candidates)
            if match is None:
                print(f'  no candidate matches {ans!r} — skipped')
                continue
            overrides[sp_label] = match
            print(f'  set: {sp_label} → {match}')
            n_changed += 1

    if n_changed == 0:
        print('\nNo changes; metadata.yaml left untouched.')
        return

    # Persist overrides to metadata.yaml.
    meta['speaker_overrides'] = overrides
    meta_path.write_text(
        yaml.safe_dump(meta, sort_keys=False, allow_unicode=True),
        encoding='utf-8',
    )
    print(f'\nWrote {n_changed} override(s) to {meta_path.name}')

    # Bump transcript_method to auto_pipeline_reviewed in the metadata so
    # the UI badge flips from amber to blue. Re-run picks this up.
    if meta.get('transcript_method') != 'hand_cleaned':
        meta['transcript_method'] = 'auto_pipeline_reviewed'
        meta_path.write_text(
            yaml.safe_dump(meta, sort_keys=False, allow_unicode=True),
            encoding='utf-8',
        )
        print(f'Also flipped transcript_method → auto_pipeline_reviewed.')

    if args.no_rerun:
        print('\n(use --no-rerun off to re-run identify + normalise + ingest + classify)')
        return

    print('\nRe-running downstream pipeline…')
    user_bin = '/Users/gusfraser/Library/Python/3.11/bin'
    env_path = f"{user_bin}:" + sys.path[0]
    import os as _os
    env = {**_os.environ, 'PATH': f"{user_bin}:{_os.environ.get('PATH','')}"}
    for script, args_list in [
        ('hustings_identify.py', ['--no-fingerprint', '--no-update-references', '--force']),
        ('normalise_local_terms.py', []),
        ('ingest_hustings.py', []),
        ('classify_hustings.py', []),
    ]:
        cmd = [sys.executable, str(PIPELINE_DIR / script), '--slug', args.slug] + args_list
        print(f'  $ {" ".join(cmd[-3:])}')
        rc = subprocess.run(cmd, env=env).returncode
        if rc != 0:
            print(f'  {script} failed (exit {rc}); stopping')
            sys.exit(rc)
    print('\nReview complete.')


if __name__ == '__main__':
    main()
