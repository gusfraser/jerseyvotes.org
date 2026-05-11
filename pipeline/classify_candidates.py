"""
Classify each scraped candidate's manifesto into:
  (a) candidate_topics — which of the 16 categories they substantively address,
      with a salience score, one-sentence summary, and source quote.
  (b) candidate_stances — agree/disagree/neutral/not_addressed for every
      canonical question, with a verbatim source_quote when the stance is
      anything other than not_addressed.

Verbatim-quote check: any source_quote that doesn't substring-match the
manifesto (after whitespace normalisation) is rejected. This is the
primary guard against LLM hallucination — the published methodology
relies on every claimed position being traceable to the manifesto.

Run: python pipeline/classify_candidates.py [--limit N] [--reclassify]
"""

import argparse
import json
import os
import re
import time

import psycopg2
import yaml
from dotenv import load_dotenv

# override=True so an empty ANTHROPIC_API_KEY pre-set in the shell doesn't
# silently shadow the real key in .env. (python-dotenv defaults to NOT
# overriding existing env vars.)
load_dotenv(override=True)

# Mirror the existing classify.py taxonomy verbatim.
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

MODEL = 'claude-sonnet-4-5'  # see /candidates/methodology — Sonnet for nuance on free-form manifestos
BATCH_DELAY_SEC = 0.5
TOPIC_BATCH = 1   # one call per candidate; manifesto context too large to batch
STANCE_BATCH = 1


def normalise_for_match(s: str) -> str:
    """Aggressive normalisation for the verbatim-quote substring check."""
    s = s.lower()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[‘’“”]', "'", s)  # smart quotes -> straight
    s = re.sub(r'[–—]', '-', s)              # en/em dash -> hyphen
    return s.strip()


def quote_matches(manifesto: str, quote: str) -> bool:
    if not quote:
        return False
    return normalise_for_match(quote) in normalise_for_match(manifesto)


def load_canonical_questions(path: str) -> tuple[int, list[dict]]:
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get('election_year', 2026), data['questions']


def upsert_canonical_questions(cur, year: int, questions: list[dict]):
    for sort_order, q in enumerate(questions):
        if q['topic'] not in CATEGORIES:
            raise ValueError(f'Unknown topic for {q["id"]}: {q["topic"]}')
        cur.execute(
            '''
            INSERT INTO canonical_questions (question_id, topic, statement, explainer, election_year, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (question_id) DO UPDATE SET
                topic = EXCLUDED.topic,
                statement = EXCLUDED.statement,
                explainer = EXCLUDED.explainer,
                election_year = EXCLUDED.election_year,
                sort_order = EXCLUDED.sort_order
            ''',
            (q['id'], q['topic'], q['statement'], q.get('explainer'), year, sort_order),
        )


def parse_json_response(text: str):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Common failure: source_quote contains an unescaped inner quote, so a
        # quote inside the value prematurely ends the string. We fix this by
        # escaping any " that appears INSIDE a value (between an opening " and
        # the closing ", which is bounded by a delimiter — `,` `}` or `]`).
        # Heuristic but robust enough for our LLM payloads.
        repaired = re.sub(
            r'(:\s*"(?:[^"\\]|\\.)*?)"((?:[^"\\]|\\.)*?)("\s*[,}\]])',
            lambda m: m.group(1) + '\\"' + m.group(2) + m.group(3),
            text,
        )
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            # Re-raise the ORIGINAL error so the caller logs sensibly
            raise


def build_topic_prompt(manifesto: str, categories: list[str]) -> str:
    cats = '\n'.join(f'  - {c}' for c in categories)
    return f"""You are extracting policy topics from a Jersey election candidate's manifesto.

Identify which of the following 16 categories the manifesto substantively addresses. Do NOT include categories the manifesto only mentions in passing or not at all.

Categories:
{cats}

Manifesto:
\"\"\"
{manifesto}
\"\"\"

Return a JSON array (no prose, no markdown fences) where each element has:
- "topic": exact category name from the list above
- "salience": number in [0, 1] approximating share of the manifesto devoted to this topic; the salience values across all topics you return should sum to <= 1.0
- "summary": one neutral sentence describing the candidate's position on this topic (not the topic in general)
- "source_quote": a VERBATIM excerpt from the manifesto (20-200 characters) that supports your summary. Do not paraphrase. Copy the text exactly as written, including punctuation.

Only include categories the manifesto substantively addresses (typically 3-8 topics)."""


def build_stance_prompt(manifesto: str, questions: list[dict]) -> str:
    qs = '\n'.join(
        f'  - id: {q["question_id"]}\n    statement: "{q["statement"]}"'
        for q in questions
    )
    return f"""You are extracting a Jersey election candidate's stance on specific policy statements from their manifesto.

For each statement below, decide whether the manifesto supports, opposes, takes a neutral or mixed view, or does not address it.

Statements:
{qs}

Manifesto:
\"\"\"
{manifesto}
\"\"\"

Return a JSON array (no prose, no markdown fences) covering ALL the statement ids above. Each element must have:
- "question_id": the id from above
- "stance": exactly one of "agree", "disagree", "neutral", "not_addressed"
- "confidence": number in [0, 1] indicating your confidence in the stance assignment
- "source_quote": a VERBATIM excerpt from the manifesto (20-200 characters) that justifies the stance — REQUIRED if stance is agree/disagree/neutral, EMPTY STRING if not_addressed. Copy the text exactly as written.

If the manifesto doesn't address a statement at all, use "not_addressed" with confidence ~0.9 and an empty source_quote. Be conservative: prefer "not_addressed" over guessing."""


def classify_topics(client, manifesto: str) -> list[dict]:
    prompt = build_topic_prompt(manifesto, CATEGORIES)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{'role': 'user', 'content': prompt}],
    )
    raw = parse_json_response(resp.content[0].text)
    cleaned = []
    for row in raw:
        topic = row.get('topic')
        if topic not in CATEGORIES:
            continue
        sal = max(0.0, min(1.0, float(row.get('salience', 0))))
        summary = (row.get('summary') or '').strip()
        quote = (row.get('source_quote') or '').strip()
        if not quote_matches(manifesto, quote):
            # Drop hallucinated quote; keep topic but blank the quote so we
            # know later this row needs human review.
            quote = ''
        cleaned.append({
            'topic': topic,
            'salience': round(sal, 2),
            'summary': summary,
            'source_quote': quote,
        })
    return cleaned


def classify_stances(client, manifesto: str, questions: list[dict]) -> list[dict]:
    prompt = build_stance_prompt(manifesto, questions)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{'role': 'user', 'content': prompt}],
    )
    raw = parse_json_response(resp.content[0].text)

    by_id = {q['question_id']: q for q in questions}
    out = []
    for row in raw:
        qid = row.get('question_id')
        if qid not in by_id:
            continue
        stance = row.get('stance', 'not_addressed')
        if stance not in {'agree', 'disagree', 'neutral', 'not_addressed'}:
            stance = 'not_addressed'
        conf = max(0.0, min(1.0, float(row.get('confidence', 0))))
        quote = (row.get('source_quote') or '').strip()

        if stance != 'not_addressed' and not quote_matches(manifesto, quote):
            # Unverified quote; demote to not_addressed to avoid bogus stance.
            stance = 'not_addressed'
            quote = ''
        if stance == 'not_addressed':
            quote = ''
        out.append({
            'question_id': qid,
            'stance': stance,
            'confidence': round(conf, 2),
            'source_quote': quote,
        })
    # Ensure every question has a row (LLM may have dropped some).
    returned_ids = {r['question_id'] for r in out}
    for q in questions:
        if q['question_id'] not in returned_ids:
            out.append({
                'question_id': q['question_id'],
                'stance': 'not_addressed',
                'confidence': 0.5,
                'source_quote': '',
            })
    return out


def db_connect():
    """Open a Neon-friendly connection with TCP keepalives. Neon's compute can
    drop idle SSL connections (the Sonnet calls between commits are long
    enough to trigger this); keepalives prevent the silent disconnect."""
    return psycopg2.connect(
        os.environ['DATABASE_URL'],
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
        connect_timeout=15,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--reclassify', action='store_true',
                        help='Reclassify even candidates already classified')
    parser.add_argument('--questions-file',
                        default=os.path.join(os.path.dirname(__file__), 'canonical_questions.yaml'))
    args = parser.parse_args()

    try:
        import anthropic
    except ImportError:
        raise SystemExit('anthropic package not installed. pip install anthropic')

    conn = db_connect()
    cur = conn.cursor()

    year, questions = load_canonical_questions(args.questions_file)
    print(f'Loaded {len(questions)} canonical questions for election {year}')

    upsert_canonical_questions(cur, year, questions)
    conn.commit()

    cur.execute('SELECT question_id, topic, statement FROM canonical_questions ORDER BY sort_order')
    db_questions = [{'question_id': r[0], 'topic': r[1], 'statement': r[2]} for r in cur.fetchall()]

    where = "WHERE scrape_status IN ('ok', 'low_content')"
    if not args.reclassify:
        where += ' AND classified_at IS NULL'
    cur.execute(f'''
        SELECT candidate_id, full_name, manifesto_text, manifesto_word_count
        FROM candidates
        {where}
        ORDER BY manifesto_word_count DESC NULLS LAST
    ''')
    rows = cur.fetchall()
    if args.limit:
        rows = rows[: args.limit]
    print(f'Classifying {len(rows)} candidates')

    client = anthropic.Anthropic()
    ok, errs = 0, 0

    def persist(cand_id: int, topics: list[dict], stances: list[dict]):
        """Write classification results for one candidate. Reconnect once if
        psycopg2 reports an operational error (typically Neon dropping an
        idle SSL connection during long LLM calls)."""
        nonlocal conn, cur
        for attempt in range(2):
            try:
                cur.execute('DELETE FROM candidate_topics WHERE candidate_id = %s', (cand_id,))
                for t in topics:
                    cur.execute(
                        'INSERT INTO candidate_topics (candidate_id, topic, salience, summary, source_quote) '
                        'VALUES (%s, %s, %s, %s, %s)',
                        (cand_id, t['topic'], t['salience'], t['summary'], t['source_quote']),
                    )
                cur.execute('DELETE FROM candidate_stances WHERE candidate_id = %s', (cand_id,))
                for s in stances:
                    cur.execute(
                        'INSERT INTO candidate_stances (candidate_id, question_id, stance, confidence, source_quote) '
                        'VALUES (%s, %s, %s, %s, %s)',
                        (cand_id, s['question_id'], s['stance'], s['confidence'], s['source_quote']),
                    )
                cur.execute('UPDATE candidates SET classified_at = NOW() WHERE candidate_id = %s', (cand_id,))
                conn.commit()
                return
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                print(f'  DB error on attempt {attempt+1} (will reconnect): {e}')
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
                conn = db_connect()
                cur = conn.cursor()
        raise RuntimeError(f'Failed to persist candidate {cand_id} after retry')

    for i, (cand_id, name, manifesto, wc) in enumerate(rows):
        if not manifesto or wc == 0:
            try:
                cur.execute('UPDATE candidates SET classified_at = NOW() WHERE candidate_id = %s', (cand_id,))
                conn.commit()
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                conn = db_connect()
                cur = conn.cursor()
                cur.execute('UPDATE candidates SET classified_at = NOW() WHERE candidate_id = %s', (cand_id,))
                conn.commit()
            continue
        try:
            topics = classify_topics(client, manifesto)
            time.sleep(BATCH_DELAY_SEC)
            stances = classify_stances(client, manifesto, db_questions)
        except Exception as e:
            print(f'  ERROR classifying {name}: {e}')
            errs += 1
            time.sleep(1.0)
            continue

        try:
            persist(cand_id, topics, stances)
            ok += 1
        except Exception as e:
            print(f'  PERSIST FAIL for {name}: {e}')
            errs += 1
            continue

        if (i + 1) % 5 == 0:
            print(f'  {i+1}/{len(rows)} (ok={ok}, errs={errs})  last: {name}', flush=True)

        time.sleep(BATCH_DELAY_SEC)

    cur.close()
    conn.close()
    print(f'\nDone. ok={ok}, errors={errs}')


if __name__ == '__main__':
    main()
