"""
Generate extended summaries for quiz-eligible propositions.
These are richer 3-paragraph summaries stored alongside the one-liner.
"""

import json
import os
import urllib.request

import psycopg2

DATABASE_URL = os.environ.get('DATABASE_URL',
    '***REDACTED***')

MODEL = 'mistral-nemo:latest'

SYSTEM = """You are a civic information assistant for Jersey (Channel Island). Your job is to explain States Assembly propositions in plain language so that ordinary voters can understand what was being voted on and why it matters.

Write for a general audience - no legal jargon, no assumptions about political knowledge. Be balanced and neutral - present both sides fairly. Be specific about what would actually change if the proposition passed."""


def call_ollama(prompt: str) -> str:
    data = json.dumps({
        'model': MODEL,
        'prompt': prompt,
        'stream': False,
        'options': {'temperature': 0.2},
        'system': SYSTEM
    }).encode('utf-8')
    req = urllib.request.Request(
        'http://localhost:11434/api/generate',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    resp = urllib.request.urlopen(req, timeout=300)
    return json.loads(resp.read())['response'].strip()


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Get quiz-eligible propositions: divisive votes in the current term
    cur.execute("""
        SELECT p.proposition_id, p.base_reference, p.title, p.scraped_text
        FROM propositions p
        WHERE p.extended_summary IS NULL
          AND p.proposition_id IN (
            SELECT DISTINCT vd.proposition_id
            FROM vote_divisions vd
            WHERE vd.division_stage IN ('principles', 'third_reading', 'amendment')
              AND vd.date >= '2022-07-01'
              AND (vd.pour_count + vd.contre_count) >= 20
              AND LEAST(vd.pour_count, vd.contre_count)::float
                  / NULLIF(vd.pour_count + vd.contre_count, 0) >= 0.25
          )
        ORDER BY p.year DESC, p.number DESC
    """)
    props = cur.fetchall()
    print(f'Propositions needing extended summaries: {len(props)}')

    done = 0
    for prop_id, ref, title, text in props:
        excerpt = text[:2500] if text else ''

        prompt = f"""Summarise this Jersey States Assembly proposition for voters. Write 3-4 short paragraphs:

1. **What it proposed**: What would actually change if this passed? Be specific.
2. **Why it was brought forward**: What problem or situation prompted this?
3. **The key arguments**: Briefly, what were the main reasons for and against?

Keep it under 200 words total. Use plain language a teenager could understand.

Proposition: [{ref}] {title}

Full text:
{excerpt}"""

        try:
            result = call_ollama(prompt)
            cur.execute(
                'UPDATE propositions SET extended_summary = %s WHERE proposition_id = %s',
                (result, prop_id)
            )
            done += 1
            if done % 5 == 0:
                conn.commit()
                print(f'  [{done}/{len(props)}] {ref}: {title[:50]}')
        except Exception as e:
            print(f'  Error on {ref}: {e}')

    conn.commit()
    cur.close()
    conn.close()
    print(f'\nDone! Generated {done}/{len(props)} extended summaries')


if __name__ == '__main__':
    main()
