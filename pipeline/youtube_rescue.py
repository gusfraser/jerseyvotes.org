"""Rescue Whisper "[automated transcription failed here]" markers using
YouTube's auto-caption track for the same video.

Why this exists:
  Whisper-large-v3 occasionally loops on perfectly clear audio (post-
  pause restart bug — emits "Sne Sne Sne" with logprob ≈ 0). When we
  collapse the loop we leave a marker telling the reader to watch the
  YouTube link. But the YouTube auto-caption ASR doesn't have the same
  failure mode — it's a different model with different anti-loop
  heuristics — and it routinely captures the exact 29-second gap that
  Whisper lost. We can splice that text in directly.

Approach:
  1. Parse audio.m4a's words.json — find runs of 4+ identical short
     tokens (the Whisper loop signature). Get start/end timestamps.
  2. Parse youtube_captions.vtt — build a time-indexed deduplicated
     transcript.
  3. For each Whisper gap, extract the YouTube text covering the
     same time range with ±2s padding.
  4. Replace the "[automated transcription failed here…]" marker in
     transcript.md with `[YouTube auto-caption rescue: …]` followed
     by the YouTube text in brackets so the reader knows the source
     is a different ASR.
  5. Re-normalise + re-ingest.

YouTube auto-captions are NOISIER than Whisper output in other ways
(no diarisation, weaker punctuation, sometimes mis-spelled local
terms). So we use them ONLY for rescue, not as the primary transcript.

Run:
  python pipeline/youtube_rescue.py --slug senatorial-st-ouen-2026
  python pipeline/youtube_rescue.py --all             # every event with VTT
  python pipeline/youtube_rescue.py --slug X --dry-run  # show what would change
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HUSTINGS = Path(__file__).resolve().parent / 'hustings'

# Marker the normalise step writes for collapsed loops
LOOP_MARKER = (
    '[automated transcription failed here — watch the YouTube link '
    'above to hear what was actually said]'
)

# Minimum loop length (consecutive identical short tokens) we'll try
# to rescue. Below this it's not really a loop, it's just stuttering.
MIN_LOOP_TOKENS = 4

# How much padding (sec) to add either side of the loop window when
# extracting from YouTube — gives a bit of context that the caller
# can use to splice cleanly.
PAD_SEC = 1.5


# ---------------------------------------------------------------------
# VTT parser
# ---------------------------------------------------------------------

VTT_TS_RE = re.compile(
    r'^(\d{2}):(\d{2}):(\d{2})\.(\d+)\s+-->\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)',
    re.M,
)


@dataclass
class VTTCue:
    start: float
    end: float
    text: str


def parse_vtt(vtt_text: str) -> list[VTTCue]:
    """Parse a WebVTT file into time-indexed cues. Strips inline
    timestamp markers (`<00:08:37.000>`) and tag markup (`<c>...</c>`).
    Deduplicates the YouTube-style 'cue then immediate copy of same
    text' pattern.
    """
    cues: list[VTTCue] = []
    lines = vtt_text.split('\n')
    i = 0
    last_text = None
    while i < len(lines):
        line = lines[i]
        m = VTT_TS_RE.match(line)
        if not m:
            i += 1
            continue
        start = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/1000.0
        end = int(m.group(5))*3600 + int(m.group(6))*60 + int(m.group(7)) + int(m.group(8))/1000.0
        # Gather text lines until the next blank or next timestamp
        text_parts: list[str] = []
        j = i + 1
        while j < len(lines):
            tl = lines[j]
            if not tl.strip() or VTT_TS_RE.match(tl):
                break
            text_parts.append(tl)
            j += 1
        raw = ' '.join(text_parts)
        # Strip inline timestamp markers and HTML
        clean = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d+>', '', raw)
        clean = re.sub(r'</?c[^>]*>', '', clean)
        clean = re.sub(r'&gt;', '>', clean)
        clean = re.sub(r'&lt;', '<', clean)
        clean = re.sub(r'&amp;', '&', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        # Drop empty cues and exact-duplicate cues (YouTube emits each
        # caption block twice — once with the previous line + new
        # incoming words, once as just the new line)
        if clean and clean != last_text:
            cues.append(VTTCue(start=start, end=end, text=clean))
            last_text = clean
        i = j

    return cues


def vtt_text_between(cues: list[VTTCue], start: float, end: float) -> str:
    """Extract the YouTube text covering [start, end] seconds. Joins
    the overlapping cues, deduplicates the rolling-window output that
    YouTube emits (each new cue includes the prior cue's tail).
    """
    parts: list[str] = []
    last = ''
    for c in cues:
        if c.end < start or c.start > end:
            continue
        text = c.text
        # The most common YouTube pattern: cue N ends with phrase X,
        # cue N+1 starts with phrase X (the "rolling window"). Strip
        # the redundant prefix.
        if last:
            overlap = _longest_overlap(last, text)
            if overlap >= 10:  # at least 10 chars of overlap
                text = text[overlap:].lstrip()
        if text:
            parts.append(text)
        last = c.text
    joined = ' '.join(parts).strip()
    # Collapse double spaces
    return re.sub(r'\s+', ' ', joined)


def _longest_overlap(a: str, b: str) -> int:
    """Length of the longest suffix of `a` that is also a prefix of `b`.
    Used to deduplicate the YouTube rolling-caption format."""
    max_check = min(len(a), len(b), 120)
    for k in range(max_check, 0, -1):
        if a[-k:] == b[:k]:
            return k
    return 0


# ---------------------------------------------------------------------
# Whisper loop detector
# ---------------------------------------------------------------------

@dataclass
class WhisperLoop:
    start_s: float        # last good word end
    end_s: float          # first good word start
    n_tokens: int         # how many junk tokens emitted
    junk_token: str       # what it looped on ("Sne", " Sne", etc.)


def find_loops(words: list[dict]) -> list[WhisperLoop]:
    """Find runs of 4+ identical short tokens in words.json."""
    loops: list[WhisperLoop] = []
    n = len(words)
    i = 0
    while i < n:
        w = words[i]
        t = w['text'].strip()
        if len(t) > 6:
            i += 1
            continue
        # Count consecutive identical tokens
        j = i + 1
        while j < n and words[j]['text'].strip() == t:
            j += 1
        count = j - i
        if count >= MIN_LOOP_TOKENS:
            # The loop covers words[i:j]. The "real" gap in audio is
            # between (words[i-1] end) and (words[j] start) — that's
            # the speech Whisper FAILED to transcribe.
            prev_end = words[i-1]['end'] if i > 0 else words[i]['start']
            next_start = words[j]['start'] if j < n else words[j-1]['end']
            loops.append(WhisperLoop(
                start_s=prev_end,
                end_s=next_start,
                n_tokens=count,
                junk_token=t,
            ))
            i = j
        else:
            i += 1
    return loops


# ---------------------------------------------------------------------
# Rescue
# ---------------------------------------------------------------------

def _parse_segment_blocks(transcript: str) -> list[tuple[int, int, float, str]]:
    """Parse transcript.md into segment blocks. Returns list of
    (block_start_offset, block_end_offset, segment_start_seconds,
    block_text). Each block is one **[mm:ss] Name:** ... segment.
    """
    # Match speaker headers like `**[mm:ss] Name:**` or `**[h:mm:ss] Name:**`
    hdr_re = re.compile(r'\*\*\[(\d+):(\d{2})(?::(\d{2}))?\][^*]*:\*\*', re.M)
    matches = list(hdr_re.finditer(transcript))
    blocks: list[tuple[int, int, float, str]] = []
    for i, m in enumerate(matches):
        if m.group(3):
            # h:mm:ss format
            secs = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3))
        else:
            secs = int(m.group(1))*60 + int(m.group(2))
        block_start = m.start()
        block_end = matches[i+1].start() if i+1 < len(matches) else len(transcript)
        block_text = transcript[block_start:block_end]
        blocks.append((block_start, block_end, float(secs), block_text))
    return blocks


def rescue_event(folder: Path, dry_run: bool) -> tuple[int, int]:
    """Returns (n_markers_found, n_rescues_applied).

    Strategy: walk each segment block in transcript.md. If it contains
    the loop marker, look up the segment's time range from the
    diarised_segments.json, fetch YouTube text covering that range,
    and splice in.
    """
    vtt_path = folder / 'youtube_captions.vtt'
    tx_path = folder / 'transcript.md'
    diar_path = folder / 'diarised_segments.json'

    if not vtt_path.exists() or not tx_path.exists():
        return (0, 0)

    transcript = tx_path.read_text()
    if LOOP_MARKER not in transcript:
        return (0, 0)

    cues = parse_vtt(vtt_path.read_text())
    if not cues:
        print(f'  ⚠ no parseable cues in {vtt_path.name}')
        return (transcript.count(LOOP_MARKER), 0)

    # Build a time-range lookup from diarised segments. For each (start,
    # end) pair we'll find which segment in transcript.md it belongs to
    # by matching the start seconds against the **[mm:ss]** header.
    diar_segs: list[tuple[float, float]] = []
    if diar_path.exists():
        for s in json.loads(diar_path.read_text()):
            diar_segs.append((float(s['start']), float(s['end'])))

    def segment_end_for(start_s: float) -> float | None:
        """Find the end-time of the diarised segment that starts at this
        time (or within 2s of it)."""
        for ds, de in diar_segs:
            if abs(ds - start_s) <= 2.0:
                return de
        return None

    blocks = _parse_segment_blocks(transcript)
    n_markers = transcript.count(LOOP_MARKER)
    print(f'  {n_markers} marker(s) in transcript across {len(blocks)} segment block(s)')

    applied = 0
    out_parts: list[str] = []
    cursor = 0
    for bstart, bend, secs, btext in blocks:
        # Preserve everything between cursor and this block start
        if cursor < bstart:
            out_parts.append(transcript[cursor:bstart])
        # Process this block: if it contains the marker, splice in YouTube text
        if LOOP_MARKER not in btext:
            out_parts.append(btext)
            cursor = bend
            continue
        seg_end = segment_end_for(secs)
        if seg_end is None:
            # Fall back: assume 60s segment if we can't find a diarised match
            seg_end = secs + 60
        rescued = vtt_text_between(cues, secs - PAD_SEC, seg_end + PAD_SEC)
        mm = int(secs) // 60
        ss = int(secs) % 60
        if not rescued or len(rescued) < 20:
            print(f'    {mm:>3}:{ss:02} → no useful YT text for [{secs:.0f}-{seg_end:.0f}s]')
            out_parts.append(btext)
            cursor = bend
            continue
        replacement = (
            f'[YouTube auto-caption rescue, {seg_end - secs:.0f}s: '
            f'{rescued}]'
        )
        new_block = btext.replace(LOOP_MARKER, replacement, 1)
        out_parts.append(new_block)
        applied += 1
        preview = rescued[:120] + ('…' if len(rescued) > 120 else '')
        print(f'    {mm:>3}:{ss:02} → YT rescue ({seg_end - secs:.0f}s): {preview!r}')
        cursor = bend
    # Append anything after the last block
    if cursor < len(transcript):
        out_parts.append(transcript[cursor:])

    new_transcript = ''.join(out_parts)

    if applied and not dry_run:
        tx_path.write_text(new_transcript)
        print(f'  ✓ wrote {applied} rescues into transcript.md')
    elif applied and dry_run:
        print(f'  [dry-run] would write {applied} rescues')

    return (n_markers, applied)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--slug', help='Process one event slug')
    ap.add_argument('--all', action='store_true',
                    help='Process every event with both words.json and VTT')
    ap.add_argument('--dry-run', action='store_true',
                    help='Show planned changes without writing')
    args = ap.parse_args()

    if not args.slug and not args.all:
        ap.error('must pass --slug or --all')

    if args.slug:
        folders = [HUSTINGS / args.slug]
    else:
        folders = sorted(
            p for p in HUSTINGS.iterdir()
            if p.is_dir() and not p.name.startswith('_')
        )

    grand_loops = 0
    grand_applied = 0
    for folder in folders:
        if not folder.is_dir():
            continue
        print(f'\n[{folder.name}]')
        n_loops, n_app = rescue_event(folder, args.dry_run)
        grand_loops += n_loops
        grand_applied += n_app

    print(f'\nTotal: {grand_loops} loops detected, {grand_applied} rescued')


if __name__ == '__main__':
    main()
