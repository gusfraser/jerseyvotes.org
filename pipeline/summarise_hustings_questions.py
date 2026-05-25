"""
LLM-polish every audience question into a one-line headline.

For each `audience_question` segment, send Claude:
  - The spliced YouTube ASR text (or the diarised text if no splice).
  - The first 2-3 candidate answers tied to the same question_index (these
    often paraphrase the question and ground the topic).
  - The moderator segments immediately before/after (where the moderator
    typically introduces the questioner or reformulates the ask).

Claude returns JSON:
  {
    "question_summary":  "one neutral sentence describing what was asked",
    "questioner_name":   "Firstname Lastname" or null,
  }

Both fields are written back to:
  - the audience_question row (question_summary, questioner_name),
  - all sibling question_answer rows with the same (event_id, question_index)
    so per-topic pages and candidate pages also surface the cleaned context.

The row's `question_summary_source` is set to 'llm_synthesised' so the
display layer knows to show an "as captured from audio" disclosure with
the raw text underneath.

Run:
  python pipeline/summarise_hustings_questions.py                          # all events
  python pipeline/summarise_hustings_questions.py --slug st-john-meeting-...
  python pipeline/summarise_hustings_questions.py --resummarise            # re-do existing
  python pipeline/summarise_hustings_questions.py --dry-run                # LLM calls only, no writes
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

MODEL = 'claude-opus-4-7'
BATCH_DELAY_SEC = 0.2

# Truncate long passages we send to the LLM. We just want enough context
# to identify what the question was about, not the full answer.
MAX_AUDIENCE_CHARS = 1200
MAX_ANSWER_CHARS = 600
MAX_MODERATOR_CHARS = 300


def parse_json_response(text: str):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    return json.loads(text)


def build_prompt(audience_text: str, mod_context: str,
                 answers: list[tuple[str, str]]) -> str:
    """Construct the LLM prompt. `answers` is a list of (candidate_name, text)
    tuples in speaking order, already truncated."""
    answers_block = '\n\n'.join(
        f'--- {name} ---\n{text}' for name, text in answers
    ) if answers else '(no candidate answers attributed to this question)'
    return f"""You are extracting the audience question asked at a Jersey election hustings.

The audience speaker's words were captured by YouTube's auto-captions. They may include moderator prompts (introducing the questioner, repeating the question), the audience member introducing themselves, and any back-and-forth before the question is fully posed. Read all the context below and return a clean summary of what was actually asked.

=== AUDIENCE / MODERATOR TRANSCRIPT (the question and surrounding cross-talk) ===
{audience_text[:MAX_AUDIENCE_CHARS]}

=== MODERATOR LEADING / FOLLOWING CONTEXT ===
{mod_context[:MAX_MODERATOR_CHARS] if mod_context else '(none)'}

=== FIRST CANDIDATE ANSWERS (use only to disambiguate what was being asked) ===
{answers_block}

Return strict JSON (no prose, no markdown fences) with these keys:
  - "question_summary": one neutral sentence, max 140 characters, describing what the audience asked. Phrase it as a question or a noun phrase (e.g. "What will candidates do about deteriorating road surfaces?" or "Road maintenance funding vs town-centre regeneration"). Do NOT include filler ("um", "you know") or the questioner's introduction.
  - "questioner_name": the questioner's name if they clearly introduced themselves in the transcript above ("My name is David Anderson…" → "David Anderson"). Just the personal name — no parish, no title. Use null if no clear introduction.

Examples of good summaries:
  - "What three measures would you take to cut red tape for small businesses?"
  - "Will government invest in another airline if Loganair pulls out?"
  - "Should civil servants change with each new government?"

If the audience text is so garbled that you cannot identify the question even with the answers' help, return question_summary as null."""


def fetch_audience_questions(cur, slug: str | None, resummarise: bool):
    where = ['s.segment_type = %s']
    params: list = ['audience_question']
    if slug:
        where.append('e.slug = %s')
        params.append(slug)
    if not resummarise:
        where.append("(s.question_summary_source IS NULL OR s.question_summary_source = 'verbatim')")
    sql = f'''
        SELECT s.segment_id, s.event_id, s.question_index, s.timestamp_seconds,
               s.position_in_event, s.text, s.text_youtube_asr, s.questioner_name
        FROM hustings_segments s
        JOIN hustings_events e ON e.event_id = s.event_id
        WHERE {' AND '.join(where)}
        ORDER BY e.slug, s.position_in_event
    '''
    cur.execute(sql, params)
    return cur.fetchall()


def fetch_answer_context(cur, event_id: int, question_index: int,
                         question_pos: int, limit: int = 3):
    """Return the first `limit` candidate answers for the same question."""
    cur.execute(
        '''
        SELECT COALESCE(c.full_name, s.speaker_name_raw), s.text
        FROM hustings_segments s
        LEFT JOIN candidates c ON c.candidate_id = s.candidate_id
        WHERE s.event_id = %s
          AND s.question_index = %s
          AND s.segment_type = 'question_answer'
        ORDER BY s.position_in_event
        LIMIT %s
        ''',
        (event_id, question_index, limit),
    )
    return [(name, (text or '')[:MAX_ANSWER_CHARS]) for name, text in cur.fetchall()]


def fetch_moderator_context(cur, event_id: int, position: int):
    """Return the closest moderator segment within +/-2 positions of the
    audience question — usually the "thank you, that goes to X" or
    "could you state your name" lines that frame the ask."""
    cur.execute(
        '''
        SELECT text
        FROM hustings_segments
        WHERE event_id = %s
          AND segment_type = 'moderator'
          AND position_in_event BETWEEN %s AND %s
        ORDER BY position_in_event
        ''',
        (event_id, position - 2, position + 2),
    )
    return ' '.join((t or '').strip() for (t,) in cur.fetchall())


def summarise_one(client, audience_text: str, mod_context: str,
                  answers: list[tuple[str, str]]) -> dict | None:
    prompt = build_prompt(audience_text, mod_context, answers)
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=400,
            messages=[{'role': 'user', 'content': prompt}],
        )
    except Exception as e:
        print(f'    LLM error: {e}')
        return None
    raw_text = ''.join(b.text for b in resp.content if getattr(b, 'type', None) == 'text')
    try:
        data = parse_json_response(raw_text)
    except json.JSONDecodeError as e:
        print(f'    json parse error: {e}; raw={raw_text[:200]!r}')
        return None
    if not isinstance(data, dict):
        return None
    summary = data.get('question_summary')
    name = data.get('questioner_name')
    if summary is not None and not isinstance(summary, str):
        summary = None
    if name is not None and not isinstance(name, str):
        name = None
    if summary:
        summary = summary.strip()[:200]
    if name:
        name = name.strip()[:80]
    return {'question_summary': summary, 'questioner_name': name}


def db_connect():
    return psycopg2.connect(
        os.environ['DATABASE_URL'],
        keepalives=1, keepalives_idle=30, keepalives_interval=10,
        keepalives_count=5, connect_timeout=15,
    )


def main():
    parser = argparse.ArgumentParser(
        description='LLM-summarise audience-question hustings segments.',
    )
    parser.add_argument('--slug', help='Process only this event slug')
    parser.add_argument('--resummarise', action='store_true',
                        help='Re-summarise rows that are already llm_synthesised')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--dry-run', action='store_true',
                        help='Run LLM calls but do not write to the DB')
    args = parser.parse_args()

    try:
        import anthropic
    except ImportError:
        sys.exit('anthropic package not installed. pip install anthropic')

    client = anthropic.Anthropic()

    conn = db_connect()
    cur = conn.cursor()

    rows = fetch_audience_questions(cur, args.slug, args.resummarise)
    if args.limit:
        rows = rows[:args.limit]
    print(f'{len(rows)} audience_question rows to summarise')

    ok = 0
    for seg_id, event_id, q_idx, ts, pos, text, asr_text, q_name in rows:
        audience_text = (asr_text or text or '').strip()
        if not audience_text:
            print(f'  [seg_id={seg_id}] empty audience text; skipping')
            continue
        answers = fetch_answer_context(cur, event_id, q_idx, pos) if q_idx else []
        mod_context = fetch_moderator_context(cur, event_id, pos)
        result = summarise_one(client, audience_text, mod_context, answers)
        if result is None or not result.get('question_summary'):
            print(f'  [seg_id={seg_id}] no summary returned')
            continue
        summary = result['question_summary']
        name = result.get('questioner_name')
        preview = summary[:80]
        print(f'  [seg_id={seg_id}, q={q_idx}] {preview!r}  (q_name={name!r})')

        if not args.dry_run:
            # Update the audience_question row.
            cur.execute(
                '''
                UPDATE hustings_segments
                   SET question_summary = %s,
                       questioner_name = COALESCE(%s, questioner_name),
                       question_summary_source = 'llm_synthesised'
                 WHERE segment_id = %s
                ''',
                (summary, name, seg_id),
            )
            # Propagate to sibling question_answer rows so per-topic /
            # per-candidate pages also see the cleaned summary.
            if q_idx is not None:
                cur.execute(
                    '''
                    UPDATE hustings_segments
                       SET question_summary = %s,
                           questioner_name = COALESCE(%s, questioner_name)
                     WHERE event_id = %s
                       AND question_index = %s
                       AND segment_type = 'question_answer'
                    ''',
                    (summary, name, event_id, q_idx),
                )
            conn.commit()
        ok += 1
        time.sleep(BATCH_DELAY_SEC)

    cur.close()
    conn.close()
    print(f'\nDone. {ok}/{len(rows)} summarised.')


if __name__ == '__main__':
    main()
