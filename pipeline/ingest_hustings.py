"""
Ingest hustings transcripts into hustings_events / hustings_segments.

Reads hand-cleaned or auto-pipeline-produced markdown from

    pipeline/hustings/<event-slug>/transcript.md

with a sibling `metadata.yaml` containing the candidate roster (the
authority for mapping speaker names → candidate_id) plus event metadata
(role, constituency, YouTube URL, date).

Two transcript styles are supported in one parse:

  Style A (hand-transcribed, no timestamps; e.g. hustings1.md)
      ## Event Title
      ### Candidate Opening Speeches
      **Steve Ahier:** opening speech text spanning
      multiple paragraphs.
      ### Audience Q&A Session
      #### Question 1: Field H1219 Development
      **Allison Marshall:** question text
      * **Steve Ahier:** answer
      * **Max Andrews:** answer
      ### Closing Remarks
      **Steve Ahier:** closing

  Style B (timestamps; e.g. sthelier-connetable-hustings.md)
      **[03:55] Hannah Shellswell (Moderator):** intro
      ### Speeches Begin
      **[07:01] Alvin Aaron:** opening
      ### Questions Begin
      **[29:40] Melina Syvret (Audience):** question
      **[30:38] Alvin Aaron:** answer

Authority rules:
  - candidate_slug must resolve against metadata.yaml's `candidates` list.
    A speaker line whose name doesn't match any roster entry, moderator
    name, or audience suffix causes the script to error out (no silent
    drops).
  - The transcript_source_url in metadata.yaml is what gets stored as
    the public audit URL — the hustings_events CHECK constraint refuses
    to store a row without one.

Hustings transcripts are a separate spoken-record channel. This script
writes only to hustings_* tables. It NEVER writes to candidate_topics
or candidate_stances — that structural separation is what guarantees
hustings cannot influence the matcher quiz scoring.

Run:
  python pipeline/ingest_hustings.py                          # all events
  python pipeline/ingest_hustings.py --slug sthelier-connetable-2026
  python pipeline/ingest_hustings.py --slug ... --dry-run     # parse only
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import psycopg2
import yaml
from dotenv import load_dotenv

load_dotenv(override=True)

HUSTINGS_DIR = Path(__file__).resolve().parent / 'hustings'

SEGMENT_TYPES = {
    'opening_speech',
    'question_answer',
    'closing_speech',
    'moderator',
    'audience_question',
}

# Line-start patterns we recognise.
#   Optional leading "* " (bulleted list item)
#   Then opening **
#   Optional [timestamp] like [12:34] or [1:23:45]
#   Speaker name (no inner ** or [])
#   `:**`
#   Rest of line (may be empty when text continues on next line)
SPEAKER_RE = re.compile(
    r'^\s*'
    r'(?:\*\s+)?'                       # optional bullet marker
    r'\*\*'                             # opening bold
    r'(?:\[([\d:]+)\]\s*)?'             # optional [timestamp]
    r'([^*\[\]]+?)'                     # speaker label (lazy)
    r':\s*\*\*'                         # `:**` (allow a space before, just in case)
    r'\s*(.*)$'                         # rest of line (may be empty)
)

# Section header recognisers.
SECTION_HEADERS = {
    'opening': {
        'candidate opening speeches', 'opening speeches', 'speeches begin',
    },
    'questions': {
        'audience q&a session', 'questions begin', 'q&a session',
        'audience q & a session', 'audience q&a', 'audience q & a',
    },
    'closing': {
        'closing remarks', 'closing speeches', 'closing',
    },
}

# Matches the body of a question heading (the part AFTER the `#` prefix has
# been stripped). Examples:
#   `Question 1: Field H1219 Development`     → ('1', 'Field H1219 Development')
#   `Question 12: Artificial Intelligence`    → ('12', 'Artificial Intelligence')
#   `Quickfire Question: Statutory Definition` → (None, 'Statutory Definition')
QUESTION_HEADER_RE = re.compile(
    r'^(?:Quick(?:fire)?\s+)?Question\s*(\d+)?\s*:?\s*(.*)$',
    re.IGNORECASE,
)

AUDIENCE_SUFFIX_RE = re.compile(r'\s*\(Audience\)\s*$', re.IGNORECASE)
MODERATOR_SUFFIX_RE = re.compile(r'\s*\(Moderator\)\s*$', re.IGNORECASE)
# `<SPEAKER_07>` — a raw diarisation label the identify script
# couldn't map to anyone. The angle brackets are the disambiguator.
SPEAKER_LABEL_RE = re.compile(r'^<SPEAKER_\d+>$')
HR_RE = re.compile(r'^\s*-{3,}\s*$')
TITLE_RE = re.compile(r'^\s*#{1,3}\s+\S')
PREAMBLE_RE = re.compile(r'^Here is the.*$', re.IGNORECASE)  # the LLM-style preamble in hustings1.md


def parse_timestamp(ts: Optional[str]) -> Optional[int]:
    """`12:34` → 754, `1:23:45` → 5025, None → None."""
    if not ts:
        return None
    parts = ts.split(':')
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def is_section_header(line: str) -> Optional[str]:
    s = line.strip()
    if not s.startswith('#'):
        return None
    body = s.lstrip('#').strip().lower()
    for label, variants in SECTION_HEADERS.items():
        if body in variants:
            return label
    return None


def parse_question_header(line: str) -> Optional[tuple[Optional[str], str]]:
    """`#### Question 1: Field H1219` → ('1', 'Field H1219'). The 'Quickfire'
    variant has no number but is treated as a question."""
    s = line.strip()
    if not s.startswith('#'):
        return None
    m = QUESTION_HEADER_RE.match(s.lstrip('#').strip())
    if not m:
        return None
    qnum = m.group(1) or ''
    qlabel = (m.group(2) or '').strip()
    return (qnum or None, qlabel)


@dataclass
class Roster:
    candidates: dict[str, str]  # name → vote_je_slug
    moderator_names: set[str]

    def resolve(self, raw_speaker: str) -> tuple[str, Optional[str]]:
        """Returns (segment_type_hint, vote_je_slug_or_None).
        segment_type_hint is one of:
          'candidate', 'moderator', 'audience', 'unknown_speaker'.

        'unknown_speaker' is reserved for raw diarisation labels like
        `<SPEAKER_07>` that the identify script couldn't map to anyone.
        Those segments are stored in the DB with candidate_id NULL and
        segment_type='unknown_speaker' so the words aren't lost — a
        future manual review (speaker_overrides in metadata.yaml) can
        relabel them."""
        name = raw_speaker.strip()
        # `<SPEAKER_NN>` without any suffix → unknown speaker.
        if SPEAKER_LABEL_RE.match(name):
            return ('unknown_speaker', None)
        if AUDIENCE_SUFFIX_RE.search(name):
            return ('audience', None)
        stripped = MODERATOR_SUFFIX_RE.sub('', name).strip()
        if MODERATOR_SUFFIX_RE.search(name) or stripped in self.moderator_names \
                or name in self.moderator_names:
            return ('moderator', None)
        normalised = normalise_name(name)
        for cand_name, slug in self.candidates.items():
            if normalise_name(cand_name) == normalised:
                return ('candidate', slug)
        return ('unknown', None)


def normalise_name(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r'[‘’`´]', "'", s)
    s = re.sub(r'\s+', ' ', s)
    return s


@dataclass
class Segment:
    speaker_name_raw: str
    segment_type: str
    text: str
    timestamp_seconds: Optional[int]
    vote_je_slug: Optional[str]
    question_index: Optional[int]
    question_summary: Optional[str]
    questioner_name: Optional[str]
    position_in_event: int


@dataclass
class ParseState:
    mode: str = 'preamble'              # 'preamble' | 'opening' | 'questions' | 'closing'
    question_index: int = 0
    pending_question_label: Optional[str] = None   # from `#### Question N:` header
    current_question_summary: Optional[str] = None
    current_questioner_name: Optional[str] = None

    # accumulator for the currently-open speaker block
    speaker_raw: Optional[str] = None
    speaker_kind: Optional[str] = None  # 'candidate' / 'moderator' / 'audience'
    speaker_slug: Optional[str] = None
    speaker_timestamp: Optional[int] = None
    speaker_text_lines: list[str] = field(default_factory=list)

    out: list[Segment] = field(default_factory=list)
    position: int = 0


def parse_transcript(text: str, roster: Roster) -> list[Segment]:
    state = ParseState()

    lines = text.splitlines()
    i = 0

    def flush_speaker(s: ParseState):
        if s.speaker_raw is None:
            return
        body = '\n'.join(s.speaker_text_lines).strip()
        # collapse 3+ blank lines, preserve paragraph breaks
        body = re.sub(r'\n{3,}', '\n\n', body)
        if not body:
            # Speaker with no content — drop. (Happens when a transcript line
            # is just a name with no text, used as a sign-post.)
            _reset_speaker(s)
            return

        if s.speaker_kind == 'candidate':
            # Candidates speaking before any section header — treat as
            # opening speeches. Senatorial hustings open with 17 candidates
            # introduced alphabetically over ~50 minutes; auto-generated
            # transcripts don't emit a "## Opening Speeches" header, and
            # the old default of `question_answer` made every opening
            # speech invisible on the per-event page (which separates
            # opening vs Q&A by segment_type).
            if s.mode in ('opening', 'preamble'):
                seg_type = 'opening_speech'
            elif s.mode == 'closing':
                seg_type = 'closing_speech'
            else:
                # In questions mode → candidate is answering a question.
                seg_type = 'question_answer'
        elif s.speaker_kind == 'moderator':
            seg_type = 'moderator'
        elif s.speaker_kind == 'audience':
            seg_type = 'audience_question'
            # Audience speaker → new question begins. Their body becomes the
            # question summary for subsequent candidate answers. Also flip
            # mode to 'questions' so subsequent candidate segments get
            # tagged as question_answer rather than opening_speech (matters
            # for auto-generated transcripts that have no section headers).
            s.mode = 'questions'
            s.question_index += 1
            s.current_question_summary = body
            s.current_questioner_name = re.sub(
                AUDIENCE_SUFFIX_RE, '', s.speaker_raw,
            ).strip()
        elif s.speaker_kind == 'unknown_speaker':
            # Diarisation produced a label the identify script couldn't
            # map. Preserve the words verbatim with no candidate_id.
            # Don't bump question_index — these segments aren't questions.
            seg_type = 'unknown_speaker'
        else:
            # 'unknown' shouldn't reach here — handled earlier.
            _reset_speaker(s)
            return

        s.position += 1
        seg = Segment(
            speaker_name_raw=s.speaker_raw,
            segment_type=seg_type,
            text=body,
            timestamp_seconds=s.speaker_timestamp,
            vote_je_slug=s.speaker_slug,
            question_index=(s.question_index if seg_type in (
                'question_answer', 'audience_question',
            ) and s.question_index > 0 else None),
            question_summary=(s.current_question_summary
                              if seg_type == 'question_answer' else None),
            questioner_name=(s.current_questioner_name
                             if seg_type == 'question_answer' else None),
            position_in_event=s.position,
        )
        s.out.append(seg)
        _reset_speaker(s)

    def _reset_speaker(s: ParseState):
        s.speaker_raw = None
        s.speaker_kind = None
        s.speaker_slug = None
        s.speaker_timestamp = None
        s.speaker_text_lines = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if HR_RE.match(line):
            # No-op divider; flush current speaker so any subsequent text
            # under a new section isn't accidentally glued on.
            flush_speaker(state)
            i += 1
            continue

        if not stripped:
            # Blank line — preserve as paragraph break inside the current
            # speaker's body if a speaker is open.
            if state.speaker_raw is not None:
                state.speaker_text_lines.append('')
            i += 1
            continue

        # Section headers and question headers must be checked before the
        # generic title skip.
        section = is_section_header(line)
        if section:
            flush_speaker(state)
            state.mode = section
            # Entering questions mode resets the question counter and pending
            # question label.
            if section == 'questions':
                state.question_index = 0
                state.pending_question_label = None
                state.current_question_summary = None
                state.current_questioner_name = None
            i += 1
            continue

        qhdr = parse_question_header(line)
        if qhdr is not None:
            flush_speaker(state)
            qnum_str, qlabel = qhdr
            # Bump question index — use the header's number when it's parseable
            # and bigger than what we've seen, else just increment.
            try:
                qnum = int(qnum_str) if qnum_str else state.question_index + 1
            except (TypeError, ValueError):
                qnum = state.question_index + 1
            state.question_index = max(state.question_index + 1, qnum)
            state.pending_question_label = qlabel or None
            state.mode = 'questions'   # safe-default; some transcripts skip explicit "Q&A" header
            i += 1
            continue

        if PREAMBLE_RE.match(line):
            # Skip LLM-style preambles like "Here is the fully cleaned…"
            i += 1
            continue

        if TITLE_RE.match(line):
            # Other `# Title` or `## Title` — usually the document title.
            # Treat as no-op (we already have the title from metadata.yaml).
            i += 1
            continue

        m = SPEAKER_RE.match(line)
        if m:
            ts_raw, speaker_raw, rest = m.group(1), m.group(2).strip(), m.group(3)
            kind, slug = roster.resolve(speaker_raw)
            if kind == 'unknown':
                # In Style-A transcripts the audience-asker line under a
                # `#### Question N:` header is just `**Allison Marshall:**`
                # — no `(Audience)` suffix. While we're inside the Q&A
                # section, an unknown speaker is by definition an audience
                # member (candidates and moderators are both explicitly
                # listed). In any other section, an unknown speaker is a
                # bug worth surfacing.
                if state.mode == 'questions':
                    kind = 'audience'
                else:
                    raise ValueError(
                        f'unknown speaker on line {i+1}: {speaker_raw!r}. '
                        f'Add to metadata.yaml candidates or moderator_names, '
                        f'or suffix the name with "(Audience)" in the transcript.'
                    )
            flush_speaker(state)

            state.speaker_raw = speaker_raw
            state.speaker_kind = kind
            state.speaker_slug = slug
            state.speaker_timestamp = parse_timestamp(ts_raw)

            # If we're now in questions mode and there's a pending Style-A
            # question header label (e.g. "Field H1219 Development"), use it
            # as a fallback question_summary until an Audience speaker
            # provides a fuller version.
            if state.mode == 'questions' and state.pending_question_label \
                    and state.current_question_summary is None \
                    and kind != 'audience':
                state.current_question_summary = state.pending_question_label

            if rest.strip():
                state.speaker_text_lines.append(rest.strip())
            i += 1
            continue

        # Continuation line for the current speaker (or stray text — append
        # if a speaker is open; ignore otherwise).
        if state.speaker_raw is not None:
            state.speaker_text_lines.append(line.rstrip())
        i += 1

    flush_speaker(state)
    return state.out


def load_metadata(folder: Path) -> tuple[dict, Roster]:
    meta_path = folder / 'metadata.yaml'
    if not meta_path.exists():
        raise FileNotFoundError(f'{folder.name}: missing metadata.yaml')
    data = yaml.safe_load(meta_path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f'{folder.name}: metadata.yaml must be a YAML mapping')

    required = ('event_slug', 'title', 'transcript_source_url')
    for key in required:
        if not data.get(key):
            raise ValueError(f'{folder.name}: metadata.yaml missing {key}')

    cands = data.get('candidates') or []
    if not isinstance(cands, list) or not cands:
        raise ValueError(f'{folder.name}: metadata.yaml needs `candidates:` list')
    candidates: dict[str, str] = {}
    for c in cands:
        name = (c.get('name') or '').strip()
        slug = (c.get('vote_je_slug') or '').strip()
        if not name or not slug:
            raise ValueError(f'{folder.name}: candidate entry needs name + vote_je_slug')
        candidates[name] = slug

    mods = data.get('moderator_names') or []
    moderator_names = {m.strip() for m in mods if isinstance(m, str) and m.strip()}

    roster = Roster(candidates=candidates, moderator_names=moderator_names)
    return data, roster


def db_connect():
    return psycopg2.connect(
        os.environ['DATABASE_URL'],
        keepalives=1, keepalives_idle=30, keepalives_interval=10,
        keepalives_count=5, connect_timeout=15,
    )


def resolve_candidate_ids(cur, slugs: set[str]) -> dict[str, int]:
    if not slugs:
        return {}
    cur.execute(
        'SELECT vote_je_slug, candidate_id FROM candidates WHERE vote_je_slug = ANY(%s)',
        (list(slugs),),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def upsert_event(cur, meta: dict, source_markdown_path: str,
                 duration_seconds: int | None) -> int:
    # transcript_method: hand_cleaned / auto_pipeline / auto_pipeline_reviewed.
    # Defaults to auto_pipeline (the audio pipeline writes its outputs),
    # overridden by an explicit metadata.yaml key.
    method = (meta.get('transcript_method') or 'auto_pipeline').strip()
    if method not in {'hand_cleaned', 'auto_pipeline', 'auto_pipeline_reviewed'}:
        raise ValueError(f'invalid transcript_method: {method!r}')

    cur.execute(
        '''
        INSERT INTO hustings_events
            (slug, title, role, constituency, election_year, event_date,
             youtube_url, transcript_source_url, source_markdown_path, notes,
             duration_seconds, transcript_method, fetched_at)
        VALUES (%(slug)s, %(title)s, %(role)s, %(constituency)s,
                %(election_year)s, %(event_date)s, %(youtube_url)s,
                %(transcript_source_url)s, %(source_markdown_path)s, %(notes)s,
                %(duration_seconds)s, %(transcript_method)s, NOW())
        ON CONFLICT (slug) DO UPDATE SET
            title = EXCLUDED.title,
            role = EXCLUDED.role,
            constituency = EXCLUDED.constituency,
            election_year = EXCLUDED.election_year,
            event_date = EXCLUDED.event_date,
            youtube_url = EXCLUDED.youtube_url,
            transcript_source_url = EXCLUDED.transcript_source_url,
            source_markdown_path = EXCLUDED.source_markdown_path,
            notes = EXCLUDED.notes,
            duration_seconds = COALESCE(EXCLUDED.duration_seconds, hustings_events.duration_seconds),
            transcript_method = EXCLUDED.transcript_method,
            fetched_at = NOW()
        RETURNING event_id
        ''',
        {
            'slug': meta['event_slug'],
            'title': meta['title'],
            'role': meta.get('role'),
            'constituency': meta.get('constituency'),
            'election_year': int(meta.get('election_year', 2026)),
            'event_date': meta.get('event_date'),
            'youtube_url': meta.get('youtube_url') or None,
            'transcript_source_url': meta['transcript_source_url'],
            'source_markdown_path': source_markdown_path,
            'notes': (meta.get('notes') or '')[:1000] or None,
            'duration_seconds': duration_seconds,
            'transcript_method': method,
        },
    )
    return cur.fetchone()[0]


def write_segments(cur, event_id: int, segments: list[Segment],
                   slug_to_id: dict[str, int]):
    # Replace all segments for this event so re-runs are idempotent. The
    # CASCADE from hustings_events also cleans hustings_segment_topics.
    cur.execute(
        'DELETE FROM hustings_segments WHERE event_id = %s', (event_id,),
    )
    for seg in segments:
        cand_id = slug_to_id.get(seg.vote_je_slug) if seg.vote_je_slug else None
        cur.execute(
            '''
            INSERT INTO hustings_segments
                (event_id, candidate_id, speaker_name_raw, segment_type,
                 question_index, question_summary, questioner_name,
                 timestamp_seconds, text, position_in_event)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''',
            (
                event_id, cand_id, seg.speaker_name_raw, seg.segment_type,
                seg.question_index, seg.question_summary, seg.questioner_name,
                seg.timestamp_seconds, seg.text, seg.position_in_event,
            ),
        )


def process_event(folder: Path, dry_run: bool, conn, cur) -> tuple[int, int]:
    """Returns (num_segments, num_attributed_to_candidates)."""
    meta, roster = load_metadata(folder)
    transcript_path = folder / 'transcript.md'
    if not transcript_path.exists():
        raise FileNotFoundError(f'{folder.name}: missing transcript.md')

    raw = transcript_path.read_text(encoding='utf-8')
    segments = parse_transcript(raw, roster)
    if not segments:
        raise ValueError(f'{folder.name}: no segments parsed')

    # Sanity: at least every candidate in the roster should appear at least
    # once. Warn (not error) if not — they may have missed the event.
    seen_slugs = {s.vote_je_slug for s in segments if s.vote_je_slug}
    missing = [name for name, slug in roster.candidates.items()
               if slug not in seen_slugs]
    if missing:
        print(f'  warning: no segments for: {", ".join(missing)}')

    attributed = sum(1 for s in segments if s.vote_je_slug)
    print(f'  parsed {len(segments)} segments ({attributed} candidate-attributed)')

    if dry_run:
        # Show a small sample for visual inspection.
        sample = segments[:3] + ([segments[len(segments)//2]] if len(segments) > 5 else [])
        for s in sample:
            label = s.vote_je_slug or f'<{s.segment_type}>'
            preview = s.text.replace('\n', ' ')[:80]
            print(f'    [{s.position_in_event:>3}] {label:<25} {s.segment_type:<18} {preview}...')
        return len(segments), attributed

    needed_slugs = {s.vote_je_slug for s in segments if s.vote_je_slug}
    slug_to_id = resolve_candidate_ids(cur, needed_slugs)
    unresolved = needed_slugs - set(slug_to_id)
    if unresolved:
        raise ValueError(
            f'{folder.name}: vote_je_slug not in candidates table: '
            f'{sorted(unresolved)}'
        )

    # Duration from yt-dlp's video_metadata.json if present (audio
    # pipeline events), or a `duration_seconds:` key in metadata.yaml
    # (hand-supplied for events without an audio source).
    duration_seconds = _resolve_duration(folder, meta)

    source_md_path = str(transcript_path.relative_to(Path(__file__).resolve().parent.parent))
    event_id = upsert_event(cur, meta, source_md_path, duration_seconds)
    write_segments(cur, event_id, segments, slug_to_id)
    conn.commit()
    print(f'  upserted event_id={event_id}, {len(segments)} segments')
    return len(segments), attributed


def _resolve_duration(folder: Path, meta: dict) -> int | None:
    # Prefer the YouTube video_metadata.json (authoritative — that's the
    # actual recording duration) and fall back to metadata.yaml only when
    # there's no audio on file.
    video_meta = folder / 'video_metadata.json'
    if video_meta.exists():
        try:
            import json
            d = json.loads(video_meta.read_text())
            sec = d.get('duration')
            if sec:
                return int(sec)
        except Exception:
            pass
    if meta.get('duration_seconds'):
        try:
            return int(meta['duration_seconds'])
        except (TypeError, ValueError):
            return None
    return None


def main():
    parser = argparse.ArgumentParser(
        description='Ingest hustings transcripts (markdown) into hustings_* tables.',
    )
    parser.add_argument('--slug', help='Process only this event folder/slug')
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

    conn = cur = None
    if not args.dry_run:
        conn = db_connect()
        cur = conn.cursor()

    ok, errs = 0, 0
    try:
        for folder in folders:
            print(f'[{folder.name}]')
            try:
                process_event(folder, args.dry_run, conn, cur)
                ok += 1
            except Exception as e:
                print(f'  ERROR: {e}')
                errs += 1
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()

    print(f'\nDone. ok={ok}, errors={errs}')


if __name__ == '__main__':
    main()
