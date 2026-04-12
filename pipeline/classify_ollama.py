"""
AgenticGov Topic Classification with Ollama
Uses local LLM to classify propositions and generate summaries.
Works with scraped full text when available, falls back to titles.
"""

import json
import os
import re
import subprocess
from collections import Counter

import psycopg2
from dotenv import load_dotenv

load_dotenv()

MODEL = 'gemma4:26b'

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


def call_ollama(prompt: str, model: str = MODEL) -> str:
    """Call Ollama HTTP API and return the response text."""
    import urllib.request
    data = json.dumps({
        'model': model,
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


def classify_proposition(ref: str, title: str, text: str | None) -> dict:
    """Classify a single proposition using Ollama."""
    categories_str = '\n'.join(f'  - {c}' for c in CATEGORIES)

    # Use scraped text if available (truncated to avoid overwhelming the model)
    context = ''
    if text and len(text) > 50:
        # Take first 2000 chars of proposition text for classification
        context = f'\n\nFull proposition text (excerpt):\n{text[:2000]}'

    prompt = f"""Classify this Jersey States Assembly proposition into a category and write a one-sentence summary for the public.

Categories:
{categories_str}

Proposition: [{ref}] {title}{context}

Respond with ONLY valid JSON (no markdown, no explanation):
{{"primary": "<category>", "secondary": "<category or null>", "tags": ["tag1", "tag2", "tag3"], "summary": "<one sentence plain-language summary>"}}"""

    response = call_ollama(prompt)

    # Try to extract JSON from response
    try:
        # Handle cases where model wraps in markdown
        cleaned = response
        if '```' in cleaned:
            cleaned = re.sub(r'```\w*\n?', '', cleaned)
        # Find first { to last }
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start >= 0 and end > start:
            cleaned = cleaned[start:end + 1]

        parsed = json.loads(cleaned)
        primary = parsed.get('primary', '')
        if primary not in CATEGORIES:
            # Try fuzzy match
            for cat in CATEGORIES:
                if primary.lower() in cat.lower() or cat.lower() in primary.lower():
                    primary = cat
                    break
            else:
                primary = 'Government & Administration'

        secondary = parsed.get('secondary')
        if secondary == 'null' or secondary == 'None':
            secondary = None
        if secondary and secondary not in CATEGORIES:
            secondary = None

        return {
            'primary': primary,
            'secondary': secondary,
            'tags': parsed.get('tags', [])[:5],
            'summary': parsed.get('summary', ''),
        }
    except (json.JSONDecodeError, KeyError):
        return {
            'primary': 'Government & Administration',
            'secondary': None,
            'tags': [],
            'summary': '',
        }


def summarize_proposition(ref: str, title: str, category: str, text: str | None) -> dict:
    """Generate tags and summary for an already-classified proposition."""
    context = ''
    if text and len(text) > 50:
        context = f'\n\nFull proposition text (excerpt):\n{text[:2000]}'

    prompt = f"""Write a one-sentence plain-language summary of this Jersey States Assembly proposition for a member of the public, and provide 2-4 short topic tags.

Proposition: [{ref}] {title}
Category: {category}{context}

Respond with ONLY valid JSON (no markdown, no explanation):
{{"tags": ["tag1", "tag2", "tag3"], "summary": "<one sentence summary>"}}"""

    response = call_ollama(prompt)

    try:
        cleaned = response
        if '```' in cleaned:
            cleaned = re.sub(r'```\w*\n?', '', cleaned)
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start >= 0 and end > start:
            cleaned = cleaned[start:end + 1]
        parsed = json.loads(cleaned)
        return {
            'tags': parsed.get('tags', [])[:5],
            'summary': parsed.get('summary', ''),
        }
    except (json.JSONDecodeError, KeyError):
        return {'tags': [], 'summary': ''}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--classify-only', action='store_true',
                        help='Only classify, skip summary generation')
    parser.add_argument('--summarize-only', action='store_true',
                        help='Only generate summaries, skip classification')
    args = parser.parse_args()

    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    print('=== Ollama Topic Classification ===\n')

    # Import keyword classifier to identify which ones are genuinely keyword-classified
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from classify import classify_by_keywords

    # Get propositions that need LLM classification
    cur.execute('''
        SELECT proposition_id, base_reference, title, scraped_text
        FROM propositions
        ORDER BY year DESC, number
    ''')
    all_props = cur.fetchall()

    needs_classification = []
    needs_summary = []

    for prop_id, ref, title, scraped_text in all_props:
        kw_category = classify_by_keywords(title)
        if kw_category is None:
            # This was not keyword-classifiable, needs LLM
            needs_classification.append((prop_id, ref, title, scraped_text))
        else:
            # Keyword classified, but may need summary
            needs_summary.append((prop_id, ref, title, kw_category, scraped_text))

    print(f'Propositions needing LLM classification: {len(needs_classification)}')
    print(f'Propositions needing summary only: {len(needs_summary)}')

    # Phase 1: Classify unclassified ones
    classified_counts = Counter()
    if not args.summarize_only:
        print(f'\nPhase 1: Classifying {len(needs_classification)} propositions with {MODEL}...')

        for i, (prop_id, ref, title, scraped_text) in enumerate(needs_classification):
            try:
                result = classify_proposition(ref, title, scraped_text)
                classified_counts[result['primary']] += 1

                cur.execute('''
                    UPDATE propositions
                    SET topic_primary = %s, topic_secondary = %s,
                        topic_tags = %s, plain_language_summary = %s
                    WHERE proposition_id = %s
                ''', (result['primary'], result['secondary'],
                      result['tags'], result['summary'], prop_id))

                if (i + 1) % 10 == 0:
                    conn.commit()
                    print(f'  Classified {i+1}/{len(needs_classification)}: [{ref}] -> {result["primary"]}')

            except Exception as e:
                print(f'  Error classifying {ref}: {e}')

        conn.commit()

    print(f'\nClassification results:')
    for cat, count in classified_counts.most_common():
        print(f'  {cat:40s} {count:4d}')

    # Phase 2: Generate summaries for keyword-classified ones
    summary_count = 0
    if not args.classify_only:
        print(f'\nPhase 2: Generating summaries for {len(needs_summary)} keyword-classified propositions...')

        for i, (prop_id, ref, title, category, scraped_text) in enumerate(needs_summary):
            try:
                result = summarize_proposition(ref, title, category, scraped_text)
                if result['summary']:
                    cur.execute('''
                        UPDATE propositions
                        SET topic_tags = %s, plain_language_summary = %s
                        WHERE proposition_id = %s
                    ''', (result['tags'], result['summary'], prop_id))
                    summary_count += 1

                if (i + 1) % 10 == 0:
                    conn.commit()
                    print(f'  Summarized {i+1}/{len(needs_summary)}')

            except Exception as e:
                print(f'  Error summarizing {ref}: {e}')

        conn.commit()
        print(f'\n  Generated {summary_count} summaries')

    # Final stats
    cur.execute('SELECT topic_primary, COUNT(*) FROM propositions GROUP BY topic_primary ORDER BY COUNT(*) DESC')
    print('\n=== Final Category Distribution ===')
    for row in cur.fetchall():
        print(f'  {(row[0] or "UNCLASSIFIED"):40s} {row[1]:4d}')

    cur.execute("SELECT COUNT(*) FROM propositions WHERE plain_language_summary IS NOT NULL AND plain_language_summary != ''")
    print(f'\nPropositions with summaries: {cur.fetchone()[0]}')

    cur.close()
    conn.close()
    print('\nDone!')


if __name__ == '__main__':
    main()
