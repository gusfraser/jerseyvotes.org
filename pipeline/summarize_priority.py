"""
Priority summarization: current term first, then backwards.
Handles both classification (for unclassified) and summaries.
"""

import json
import os
import re
import urllib.request

import psycopg2
from dotenv import load_dotenv

load_dotenv()

MODEL = 'gemma4:26b'

CATEGORIES = [
    'Government & Administration', 'Constitutional & Electoral',
    'Finance & Taxation', 'Employment & Social Security',
    'Transport & Infrastructure', 'Planning & Environment',
    'Financial Services & Regulation', 'Health & Wellbeing',
    'Property & Land', 'Housing', 'Justice & Policing',
    'Consumer & Commercial', 'Children, Education & Families',
    'International & Trade', 'Equality & Human Rights',
    'Agriculture, Fisheries & Rural',
]

CATEGORIES_STR = ', '.join(CATEGORIES)


def call_ollama(prompt: str) -> str:
    data = json.dumps({
        'model': MODEL,
        'prompt': prompt,
        'stream': False,
        'options': {'temperature': 0.1}
    }).encode('utf-8')
    req = urllib.request.Request(
        'http://localhost:11434/api/generate',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read())
    return result['response'].strip()


def parse_json_response(response: str) -> dict:
    cleaned = response
    if '```' in cleaned:
        cleaned = re.sub(r'```\w*\n?', '', cleaned)
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def classify_and_summarize(ref: str, title: str, text: str | None, needs_category: bool) -> dict:
    """Classify (if needed) and summarize in a single LLM call."""
    context = ''
    if text and len(text) > 50:
        context = f'\n\nProposition text (excerpt):\n{text[:2000]}'

    if needs_category:
        prompt = f"""Classify this Jersey States Assembly proposition and write a one-sentence summary for the public.

Categories: {CATEGORIES_STR}

Proposition: [{ref}] {title}{context}

Respond with ONLY valid JSON:
{{"primary": "<category>", "secondary": "<category or null>", "tags": ["tag1", "tag2", "tag3"], "summary": "<one sentence plain-language summary>"}}"""
    else:
        prompt = f"""Write a one-sentence plain-language summary of this Jersey States Assembly proposition for a member of the public, and provide 2-4 short topic tags.

Proposition: [{ref}] {title}{context}

Respond with ONLY valid JSON:
{{"tags": ["tag1", "tag2", "tag3"], "summary": "<one sentence summary>"}}"""

    response = call_ollama(prompt)

    try:
        parsed = parse_json_response(response)
        result = {
            'tags': parsed.get('tags', [])[:5],
            'summary': parsed.get('summary', ''),
        }
        if needs_category:
            primary = parsed.get('primary', 'Government & Administration')
            if primary not in CATEGORIES:
                for cat in CATEGORIES:
                    if primary.lower() in cat.lower() or cat.lower() in primary.lower():
                        primary = cat
                        break
                else:
                    primary = 'Government & Administration'
            result['primary'] = primary
            secondary = parsed.get('secondary')
            if secondary == 'null' or secondary == 'None':
                secondary = None
            if secondary and secondary not in CATEGORIES:
                secondary = None
            result['secondary'] = secondary
        return result
    except (json.JSONDecodeError, KeyError):
        return {'tags': [], 'summary': '', 'primary': 'Government & Administration', 'secondary': None}


def main():
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from classify import classify_by_keywords

    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    # Get propositions that need work, ordered by year DESC (current term first)
    cur.execute('''
        SELECT proposition_id, base_reference, title, scraped_text, topic_primary,
               plain_language_summary, year
        FROM propositions
        ORDER BY year DESC, number DESC
    ''')
    all_props = cur.fetchall()

    # Split into categories
    needs_classify_and_summary = []  # No keyword match, needs LLM classification + summary
    needs_summary_only = []          # Has category, needs summary

    for prop_id, ref, title, text, topic, summary, year in all_props:
        has_summary = summary and summary.strip()
        kw_category = classify_by_keywords(title)

        if not has_summary:
            if kw_category is None:
                # Check if already LLM-classified
                if topic and topic != 'Government & Administration':
                    needs_summary_only.append((prop_id, ref, title, text, topic, year))
                else:
                    needs_classify_and_summary.append((prop_id, ref, title, text, year))
            else:
                needs_summary_only.append((prop_id, ref, title, text, kw_category, year))

    total = len(needs_classify_and_summary) + len(needs_summary_only)
    current_term_count = sum(1 for x in needs_classify_and_summary + [(p, r, t, tx, None, y) for p, r, t, tx, _, y in needs_summary_only] if x[-1] >= 2022)

    print(f'=== Priority Summarization ===')
    print(f'Need classification + summary: {len(needs_classify_and_summary)}')
    print(f'Need summary only: {len(needs_summary_only)}')
    print(f'Total remaining: {total}')
    print(f'Current term (2022+): {current_term_count}')
    print()

    # Interleave both lists, keeping year DESC order
    work_items = []
    for prop_id, ref, title, text, year in needs_classify_and_summary:
        work_items.append((prop_id, ref, title, text, year, True, None))
    for prop_id, ref, title, text, topic, year in needs_summary_only:
        work_items.append((prop_id, ref, title, text, year, False, topic))

    # Sort by year DESC so current term is processed first
    work_items.sort(key=lambda x: -x[4])

    done = 0
    for prop_id, ref, title, text, year, needs_cat, existing_topic in work_items:
        try:
            result = classify_and_summarize(ref, title, text, needs_cat)

            if needs_cat:
                cur.execute('''
                    UPDATE propositions
                    SET topic_primary = %s, topic_secondary = %s,
                        topic_tags = %s, plain_language_summary = %s
                    WHERE proposition_id = %s
                ''', (result['primary'], result.get('secondary'),
                      result['tags'], result['summary'], prop_id))
            else:
                cur.execute('''
                    UPDATE propositions
                    SET topic_tags = %s, plain_language_summary = %s
                    WHERE proposition_id = %s
                ''', (result['tags'], result['summary'], prop_id))

            done += 1
            if done % 10 == 0:
                conn.commit()
                action = "classified+summarized" if needs_cat else "summarized"
                print(f'  [{done}/{total}] {year} [{ref}] {action} -> {result.get("primary", existing_topic)}')
                print(f'    "{result["summary"][:80]}..."')

        except Exception as e:
            print(f'  Error on {ref}: {e}')

    conn.commit()
    cur.close()
    conn.close()
    print(f'\nDone! Processed {done}/{total}')


if __name__ == '__main__':
    main()
