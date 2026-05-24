"""
Tag every candidate-attributed hustings segment with the 16-topic taxonomy
plus a one-sentence summary and a verbatim source quote.

Mirrors the topic-classification pass in classify_candidates.py:
  - Same Claude Opus 4.7 model.
  - Same 16 categories.
  - Same verbatim-quote guard: any source_quote that doesn't substring-match
    the segment (after whitespace and smart-quote normalisation) is dropped.
    The display layer then knows to fall back to the LLM summary only.

What this script does NOT do:
  - It does NOT extract stances against canonical_questions. There is no
    code path in this file that writes candidate_stances. That structural
    separation is the published guarantee that hustings cannot influence
    matcher quiz scoring.
  - It does NOT classify moderator or audience-question segments — those
    exist only for context.

Run:
  python pipeline/classify_hustings.py                          # all events
  python pipeline/classify_hustings.py --slug sthelier-connetable-2026
  python pipeline/classify_hustings.py --slug ... --reclassify  # re-tag existing
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import psycopg2
from dotenv import load_dotenv

load_dotenv(override=True)

# Mirror classify_candidates.py — single source of truth for the taxonomy
# in pipeline-land is web/src/lib/db.ts TOPICS, but we keep this short list
# here so the file stands alone.
CATEGORIES = [
    'Government & Administration',
    'Constitutional & Electoral',
    'Finance & Taxation',
    'Employment & Social Security',
    'Transport & Infrastructure',
    'Planning & Environment',
    'Financial Services & Regulation',
    'Health & Wellbeing',
    'Property & Land',
    'Housing',
    'Justice & Policing',
    'Consumer & Commercial',
    'Children, Education & Families',
    'International & Trade',
    'Equality & Human Rights',
    'Agriculture, Fisheries & Rural',
]

MODEL = 'claude-opus-4-7'
BATCH_DELAY_SEC = 0.3

# Segments we send to the LLM. The other types (moderator, audience_question)
# are stored for context but not tagged — they don't carry candidate positions.
TAGGABLE_TYPES = ('opening_speech', 'question_answer', 'closing_speech')

# Below this length the segment is too short to extract anything meaningful
# from. ("Yes." "Yes, of course." etc.) Still stored, just not tagged.
MIN_SEGMENT_CHARS = 60


def normalise_for_match(s: str) -> str:
    """Same normalisation as classify_candidates.py — keep them in sync."""
    s = s.lower()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[‘’“”]', "'", s)
    s = re.sub(r'[–—]', '-', s)
    return s.strip()


def quote_matches(haystack: str, quote: str) -> bool:
    if not quote:
        return False
    return normalise_for_match(quote) in normalise_for_match(haystack)


def parse_json_response(text: str):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        repaired = re.sub(
            r'(:\s*"(?:[^"\\]|\\.)*?)"((?:[^"\\]|\\.)*?)("\s*[,}\]])',
            lambda m: m.group(1) + '\\"' + m.group(2) + m.group(3),
            text,
        )
        return json.loads(repaired)


def build_segment_prompt(text: str, question_summary: str | None,
                         segment_type: str, categories: list[str]) -> str:
    cats = '\n'.join(f'  - {c}' for c in categories)
    ctx = ''
    if question_summary and segment_type == 'question_answer':
        # Question is context only — quotes MUST come from the answer text,
        # never the question. Spell this out to the model.
        ctx = (
            f'The candidate was answering this audience question (for context only, '
            f'not for quoting):\n"""\n{question_summary[:500]}\n"""\n\n'
        )
    label = {
        'opening_speech': "the candidate's opening speech",
        'question_answer': "the candidate's answer to an audience question",
        'closing_speech': "the candidate's closing remarks",
    }.get(segment_type, "the candidate's words")

    return f"""You are extracting policy topics from a short spoken excerpt of {label} at a Jersey election hustings.

{ctx}Identify which of the 16 categories below this excerpt substantively addresses. A short answer usually addresses 1-3 topics; an opening speech may cover 3-6. Do NOT include categories the candidate only mentions in passing or not at all.

Categories:
{cats}

Excerpt (transcribed from audio — preserves filler words like "um" and any transcription noise):
\"\"\"
{text}
\"\"\"

Return a JSON array (no prose, no markdown fences). Each element:
- "topic": exact category name from the list above
- "salience": number in [0, 1] approximating share of the excerpt devoted to this topic (across topics returned, salience should sum to <= 1.0)
- "summary": one neutral sentence describing the candidate's position on this topic (not the topic in general)
- "source_quote": a VERBATIM excerpt (15-180 characters) from the candidate's words above that justifies the summary. Do not paraphrase. Copy exactly, including any "um" or grammatical quirks. The quote must come from the excerpt only — never from the question context.

Return an empty array `[]` if the excerpt is purely procedural (e.g. "Yes, of course." or "I agree.")."""


def classify_segment(client, text: str, question_summary: str | None,
                     segment_type: str) -> list[dict]:
    prompt = build_segment_prompt(text, question_summary, segment_type, CATEGORIES)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{'role': 'user', 'content': prompt}],
    )
    raw_text = ''.join(b.text for b in resp.content if getattr(b, 'type', None) == 'text')
    try:
        raw = parse_json_response(raw_text)
    except json.JSONDecodeError as e:
        print(f'    json parse error: {e}; raw={raw_text[:200]!r}')
        return []
    if not isinstance(raw, list):
        return []

    cleaned = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        topic = row.get('topic')
        if topic not in CATEGORIES:
            continue
        try:
            sal = max(0.0, min(1.0, float(row.get('salience', 0))))
        except (TypeError, ValueError):
            sal = 0.0
        summary = (row.get('summary') or '').strip()
        quote = (row.get('source_quote') or '').strip()
        # Verbatim guard: drop the quote if it doesn't substring-match the
        # excerpt. Topic and summary still kept — the display can render
        # the summary without an attached quote.
        if not quote_matches(text, quote):
            quote = ''
        cleaned.append({
            'topic': topic,
            'salience': round(sal, 2),
            'summary': summary,
            'source_quote': quote,
        })
    return cleaned


def db_connect():
    return psycopg2.connect(
        os.environ['DATABASE_URL'],
        keepalives=1, keepalives_idle=30, keepalives_interval=10,
        keepalives_count=5, connect_timeout=15,
    )


def main():
    parser = argparse.ArgumentParser(
        description='LLM topic-tag every candidate-attributed hustings segment.',
    )
    parser.add_argument('--slug', help='Process only this event slug')
    parser.add_argument('--reclassify', action='store_true',
                        help='Re-tag segments that already have topic rows')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--dry-run', action='store_true',
                        help='Run LLM calls but do not write to the DB')
    args = parser.parse_args()

    try:
        import anthropic
    except ImportError:
        sys.exit('anthropic package not installed. pip install anthropic')

    conn = db_connect()
    cur = conn.cursor()

    where = (
        "WHERE s.segment_type = ANY(%s)\n"
        "  AND s.candidate_id IS NOT NULL\n"
        "  AND length(s.text) >= %s\n"
    )
    params: list = [list(TAGGABLE_TYPES), MIN_SEGMENT_CHARS]
    if args.slug:
        where += "  AND e.slug = %s\n"
        params.append(args.slug)
    if not args.reclassify:
        where += (
            "  AND NOT EXISTS (SELECT 1 FROM hustings_segment_topics t "
            "WHERE t.segment_id = s.segment_id)\n"
        )

    cur.execute(
        f'''
        SELECT s.segment_id, e.slug, s.segment_type, s.question_summary, s.text,
               c.full_name
        FROM hustings_segments s
        JOIN hustings_events e ON e.event_id = s.event_id
        JOIN candidates c ON c.candidate_id = s.candidate_id
        {where}
        ORDER BY e.slug, s.position_in_event
        ''',
        params,
    )
    rows = cur.fetchall()
    if args.limit:
        rows = rows[: args.limit]

    print(f'Classifying {len(rows)} segments')
    if not rows:
        cur.close(); conn.close()
        return

    client = anthropic.Anthropic()

    ok = errs = quotes_dropped = 0
    for i, (seg_id, ev_slug, seg_type, q_summary, text, full_name) in enumerate(rows):
        try:
            tags = classify_segment(client, text, q_summary, seg_type)
        except Exception as e:
            print(f'  ERROR seg {seg_id} ({full_name}): {e}')
            errs += 1
            time.sleep(1.0)
            continue

        # Reporting only: how many of the returned tags had to drop their quote.
        quotes_dropped += sum(1 for t in tags if not t['source_quote'])

        if not args.dry_run:
            try:
                cur.execute(
                    'DELETE FROM hustings_segment_topics WHERE segment_id = %s',
                    (seg_id,),
                )
                for t in tags:
                    cur.execute(
                        '''
                        INSERT INTO hustings_segment_topics
                            (segment_id, topic, salience, summary, source_quote)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (segment_id, topic) DO UPDATE SET
                            salience = EXCLUDED.salience,
                            summary = EXCLUDED.summary,
                            source_quote = EXCLUDED.source_quote
                        ''',
                        (seg_id, t['topic'], t['salience'], t['summary'], t['source_quote']),
                    )
                conn.commit()
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                print(f'  DB error on seg {seg_id} (reconnecting): {e}')
                try:
                    cur.close(); conn.close()
                except Exception:
                    pass
                conn = db_connect()
                cur = conn.cursor()

        ok += 1
        if (i + 1) % 10 == 0:
            print(
                f'  {i+1}/{len(rows)} (ok={ok}, errs={errs}, quotes_dropped={quotes_dropped})  '
                f'last: {ev_slug} / {full_name} / {seg_type}',
                flush=True,
            )

        time.sleep(BATCH_DELAY_SEC)

    cur.close()
    conn.close()
    print(f'\nDone. ok={ok}, errors={errs}, quotes_dropped={quotes_dropped}')


if __name__ == '__main__':
    main()
