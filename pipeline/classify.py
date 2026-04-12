"""
AgenticGov Topic Classification Pipeline
Phase 1: Keyword-based pre-classification
Phase 2: Claude API for remaining unclassified propositions
"""

import json
import os
import re
import time
from collections import Counter

import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

load_dotenv()

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

# Keyword rules: each rule is (category, patterns, negative_patterns)
# Patterns are checked against the lowercased title
# Rules are evaluated in order; first match wins
KEYWORD_RULES = [
    # Budget and finance are high-confidence
    ('Finance & Taxation', [
        r'budget\b', r'government plan.*\d{4}', r'annual business plan',
        r'goods and services tax', r'\bgst\b', r'income tax',
        r'stamp dut', r'fiscal', r'finance.*budget',
        r'draft finance \(', r'tax.*amendment', r'impôt', r'impot',
        r'income support', r'community cost', r'stabilisation fund',
        r'strategic reserve', r'fiscal stimulus', r'rates of duty',
        r'draft taxation', r'revenue administration',
        r'depositor.*compensation',
    ], [r'financial services', r'financial service commission']),

    # Financial services & regulation - must come before generic finance
    ('Financial Services & Regulation', [
        r'financial service', r'alternative investment fund',
        r'limited liability partner', r'trust.*law', r'trust.*regulation',
        r'banking.*law', r'banking.*regulation', r'insurance.*law',
        r'companies.*law', r'companies.*regulation', r'companies.*amendment',
        r'financial service commission', r'jersey financial',
        r'non-profit organization', r'proceeds of crime',
        r'money laundering', r'economic substance',
        r'credit union', r'collective investment',
        r'securities', r'bank.*recovery', r'bank.*resolution',
        r'foundation.*jersey.*law', r'limited partnership',
        r'financial ombudsman', r'financial technology',
    ], []),

    # Elections and constitution
    ('Constitutional & Electoral', [
        r'election', r'electoral', r'referendum', r'senator',
        r'standing order', r'states.*composition', r'states.*reform',
        r'connétable.*in the states', r'connétable.*states',
        r'vote of (no )?confidence', r'vote of censure',
        r'privy council', r'royal commission', r'royal court',
        r'composition.*states', r'states.*member',
        r'chief minister.*elect', r'chief minister.*nomin',
        r'proxy vot', r'remote participation',
        r'appointed day.*states', r'differential pay.*minister',
        r'parish.*elect', r'public election',
        r'jersey appointments commission',
        r'suspension of (deputy|senator|connétable)',
    ], [r'police.*election']),

    # Government & Administration
    ('Government & Administration', [
        r'government plan(?!.*budget)', r'strategic plan\b',
        r'states of jersey development', r'jersey overseas aid',
        r'scrutiny', r'public accounts committee',
        r'machinery of government', r'ministerial',
        r'official report', r'hansard', r'public finances.*law',
        r'audit', r'comptroller', r'greffier',
        r'states of jersey law', r'states.*miscellaneous',
        r'freedom of information', r'data protection',
        r'public sector.*pay', r'civil servant',
        r'e-government', r'digital government',
        r'jersey.*development company', r'arm.*length',
        r'soj.*property', r'states.*property',
        r'public holiday', r'bank holiday',
        r'flag.*jersey', r'liberation day',
    ], []),

    # Employment & Social Security
    ('Employment & Social Security', [
        r'employment.*law', r'employment.*regulation', r'employment.*amendment',
        r'social security', r'minimum wage', r'pension',
        r'work permit', r'control of housing and work',
        r'parental leave', r'redundan', r'unfair dismissal',
        r'discrimination tribunal', r'employment tribunal',
        r'zero.hours', r'trade union', r'workers.? right',
        r'trainee.*wage', r'long.term care',
        r'community cost', r'income support',
        r'age.*retirement', r'old age',
    ], [r'discrimination.*race', r'discrimination.*sex', r'gender recognition']),

    # Health & Wellbeing
    ('Health & Wellbeing', [
        r'health', r'hospital', r'mental', r'medical',
        r'cannabis', r'drug', r'pharmacist', r'pharmac',
        r'organ donor', r'transplant', r'misuse.*drug',
        r'covid', r'pandemic', r'vaccination',
        r'tobacco', r'smoking', r'alcohol', r'drink',
        r'disability', r'care.*home', r'nursing',
        r'assisted dying', r'end of life',
        r'food safety', r'food.*law',
    ], [r'health and safety at work', r'drug trafficking.*proceeds']),

    # Housing
    ('Housing', [
        r'housing', r'andium', r'residential tenancy',
        r'rent.*control', r'rent.*regulation', r'rent.*increase',
        r'affordable home', r'affordable hous', r'first.time buyer',
        r'social.*rent', r'dwelling', r'habitation',
        r'lodging', r'homebuyer',
    ], [r'control of housing and work']),

    # Planning & Environment
    ('Planning & Environment', [
        r'planning', r'island plan\b', r'bridging island plan',
        r'environment', r'climate', r'carbon', r'emission',
        r'wildlife', r'conservation area', r'listed building',
        r'tree.*preservation', r'countryside',
        r'waste.*management', r'recycling', r'sewage',
        r'water.*pollution', r'pollution',
        r'shoreline', r'coastal', r'ramsar',
        r'development.*law', r'building.*regulation',
        r'dangerous building', r'construction',
    ], []),

    # Transport & Infrastructure
    ('Transport & Infrastructure', [
        r'transport', r'traffic', r'road', r'highway',
        r'airport', r'harbour', r'port', r'shipping',
        r'bus.*service', r'parking', r'speed limit',
        r'motor.*vehicle', r'motor.*traffic',
        r'civil aviation', r'aviation',
        r'telecom', r'broadband', r'fibre',
        r'electricity', r'energy.*law', r'water.*supply',
        r'gas.*law',
        r'la collette', r'st helier.*infrastructure',
        r'cable.*territorial', r'inshore safety',
    ], []),

    # Justice & Policing
    ('Justice & Policing', [
        r'criminal', r'policing', r'police\b', r'prison',
        r'court\b', r'magistrate', r'legal aid',
        r'probation', r'youth custody', r'youth justice',
        r'bail\b', r'jury\b', r'sentenc', r'offend',
        r'terrorism', r'sexual offence', r'domestic abuse',
        r'knife', r'weapon', r'firearm',
        r'human trafficking', r'modern slavery',
        r'extradition', r'mutual legal assistance',
        r'public entertainment', r'fire.*rescue',
        r'coroner', r'inquest',
    ], []),

    # Property & Land
    ('Property & Land', [
        r'conveyancing', r'property.*law', r'property.*regulation',
        r'land.*transaction', r'land.*registry', r'land.*law',
        r'stamp duty', r'enveloped property',
        r'howard davis farm', r'covenant.*abrogat',
        r'compulsory purchase',
    ], []),

    # Children, Education & Families
    ('Children, Education & Families', [
        r'school\b', r'education', r'child', r'nursery',
        r'youth', r'safeguard', r'adoption',
        r'family.*law', r'family.*court', r'matrimon',
        r'divorce', r'maintenance.*order', r'school milk',
        r'university', r'higher education', r'student',
        r'jersey music service',
    ], [r'youth custody']),

    # Consumer & Commercial
    ('Consumer & Commercial', [
        r'gambl', r'betting', r'lottery', r'licensing',
        r'supply of goods', r'consumer', r'competition',
        r'retail', r'shop.*hour', r'trading standard',
        r'intellectual property', r'trademark', r'patent',
        r'data.*protection', r'cyber',
    ], []),

    # International & Trade
    ('International & Trade', [
        r'international', r'european union', r'brexit',
        r'double taxation', r'exchange of information',
        r'international criminal court', r'ratification',
        r'treaty', r'convention', r'protocol',
        r'united kingdom exit', r'trade agreement',
        r'open border', r'common travel area',
    ], []),

    # Equality & Human Rights
    ('Equality & Human Rights', [
        r'gender recognition', r'discrimination.*law',
        r'human right', r'equal.*pay', r'civil partnership',
        r'marriage.*law', r'same.sex',
        r'race relation', r'hate crime',
        r'assisted reproduction', r'surrogacy',
    ], []),

    # Agriculture, Fisheries & Rural
    ('Agriculture, Fisheries & Rural', [
        r'fisher', r'fishing', r'fish.*law',
        r'agricultur', r'farm', r'dairy',
        r'animal welfare', r'animal.*law', r'dog.*law',
        r'veterinar', r'abattoir', r'cattle',
        r'sea fisheries', r'marine.*law',
        r'order in council.*canon',
    ], []),
]


def classify_by_keywords(title: str) -> str | None:
    """Attempt to classify a proposition title using keyword rules."""
    t = title.lower()

    for category, patterns, negatives in KEYWORD_RULES:
        # Check if any negative pattern matches (skip this category if so)
        if any(re.search(neg, t) for neg in negatives):
            continue
        # Check if any positive pattern matches
        if any(re.search(pat, t) for pat in patterns):
            return category

    return None


def classify_all_keywords(conn):
    """Run keyword classification on all propositions. Returns classified and unclassified."""
    cur = conn.cursor()
    cur.execute('SELECT proposition_id, base_reference, title FROM propositions ORDER BY year, number')
    props = cur.fetchall()
    cur.close()

    classified = []
    unclassified = []

    for prop_id, ref, title in props:
        category = classify_by_keywords(title)
        if category:
            classified.append((prop_id, ref, title, category))
        else:
            unclassified.append((prop_id, ref, title))

    return classified, unclassified


def classify_with_llm(unclassified: list, batch_size: int = 20) -> list:
    """Classify remaining propositions using Claude API."""
    try:
        import anthropic
    except ImportError:
        print('ERROR: anthropic package not installed. Run: pip3 install anthropic')
        return []

    client = anthropic.Anthropic()
    results = []

    categories_str = '\n'.join(f'  - {c}' for c in CATEGORIES)

    for i in range(0, len(unclassified), batch_size):
        batch = unclassified[i:i + batch_size]

        titles_str = '\n'.join(
            f'{j+1}. [{ref}] {title}'
            for j, (prop_id, ref, title) in enumerate(batch)
        )

        prompt = f"""Classify each Jersey States Assembly proposition into exactly one primary category and optionally a secondary category.

Categories:
{categories_str}

Propositions to classify:
{titles_str}

For each proposition, respond with a JSON array where each element has:
- "index": the proposition number (1-based)
- "primary": the primary category (must be one from the list above)
- "secondary": optional secondary category (null if none fits)
- "tags": 2-4 short topic tags (e.g., ["rent control", "tenants", "affordable housing"])
- "summary": a plain-language 1-sentence summary of what this vote was about, written for a member of the public (not a politician)

Respond ONLY with the JSON array, no other text."""

        try:
            response = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=4096,
                messages=[{'role': 'user', 'content': prompt}]
            )

            text = response.content[0].text.strip()
            # Extract JSON from response
            if text.startswith('```'):
                text = re.sub(r'^```\w*\n?', '', text)
                text = re.sub(r'\n?```$', '', text)

            parsed = json.loads(text)

            for item in parsed:
                idx = item['index'] - 1
                if 0 <= idx < len(batch):
                    prop_id, ref, title = batch[idx]
                    primary = item.get('primary', 'Government & Administration')
                    secondary = item.get('secondary')
                    tags = item.get('tags', [])
                    summary = item.get('summary', '')

                    # Validate category
                    if primary not in CATEGORIES:
                        primary = 'Government & Administration'
                    if secondary and secondary not in CATEGORIES:
                        secondary = None

                    results.append((prop_id, ref, title, primary, secondary, tags, summary))

            print(f'  Classified batch {i//batch_size + 1}/{(len(unclassified) + batch_size - 1)//batch_size} '
                  f'({len(parsed)} items)')

        except Exception as e:
            print(f'  Error on batch {i//batch_size + 1}: {e}')
            # Fall back to Government & Administration for failed items
            for prop_id, ref, title in batch:
                results.append((prop_id, ref, title, 'Government & Administration', None, [], ''))

        # Small delay to avoid rate limits
        if i + batch_size < len(unclassified):
            time.sleep(0.5)

    return results


def generate_summaries_for_keywords(classified: list, batch_size: int = 30) -> dict:
    """Generate plain-language summaries for keyword-classified propositions using Claude API."""
    try:
        import anthropic
    except ImportError:
        print('ERROR: anthropic package not installed.')
        return {}

    client = anthropic.Anthropic()
    summaries = {}  # prop_id -> (tags, summary)

    for i in range(0, len(classified), batch_size):
        batch = classified[i:i + batch_size]

        titles_str = '\n'.join(
            f'{j+1}. [{ref}] (Category: {cat}) {title}'
            for j, (prop_id, ref, title, cat) in enumerate(batch)
        )

        prompt = f"""For each Jersey States Assembly proposition below, provide:
1. 2-4 short topic tags
2. A plain-language 1-sentence summary explaining what this vote was about, written for a member of the public

Propositions:
{titles_str}

Respond ONLY with a JSON array where each element has:
- "index": the proposition number (1-based)
- "tags": array of 2-4 short tags
- "summary": one sentence summary for the public"""

        try:
            response = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=4096,
                messages=[{'role': 'user', 'content': prompt}]
            )

            text = response.content[0].text.strip()
            if text.startswith('```'):
                text = re.sub(r'^```\w*\n?', '', text)
                text = re.sub(r'\n?```$', '', text)

            parsed = json.loads(text)
            for item in parsed:
                idx = item['index'] - 1
                if 0 <= idx < len(batch):
                    prop_id = batch[idx][0]
                    summaries[prop_id] = (item.get('tags', []), item.get('summary', ''))

            print(f'  Summarized batch {i//batch_size + 1}/{(len(classified) + batch_size - 1)//batch_size}')

        except Exception as e:
            print(f'  Error on batch {i//batch_size + 1}: {e}')

        if i + batch_size < len(classified):
            time.sleep(0.5)

    return summaries


def save_classifications(conn, classified_kw, classified_llm, summaries_kw):
    """Save all classifications to the database."""
    cur = conn.cursor()

    # Update keyword-classified propositions
    for prop_id, ref, title, category in classified_kw:
        tags, summary = summaries_kw.get(prop_id, ([], ''))
        cur.execute('''
            UPDATE propositions
            SET topic_primary = %s, topic_tags = %s, plain_language_summary = %s
            WHERE proposition_id = %s
        ''', (category, tags, summary, prop_id))

    # Update LLM-classified propositions
    for prop_id, ref, title, primary, secondary, tags, summary in classified_llm:
        cur.execute('''
            UPDATE propositions
            SET topic_primary = %s, topic_secondary = %s, topic_tags = %s, plain_language_summary = %s
            WHERE proposition_id = %s
        ''', (primary, secondary, tags, summary, prop_id))

    conn.commit()
    cur.close()


def main():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])

    print('=== AgenticGov Topic Classification ===\n')

    # Phase 1: Keyword classification
    print('Phase 1: Keyword classification...')
    classified_kw, unclassified = classify_all_keywords(conn)

    kw_counts = Counter(c[3] for c in classified_kw)
    print(f'\n  Keyword classified: {len(classified_kw)} ({len(classified_kw)/2261*100:.1f}%)')
    print(f'  Unclassified: {len(unclassified)} ({len(unclassified)/2261*100:.1f}%)')
    print('\n  Category breakdown (keyword):')
    for cat, count in kw_counts.most_common():
        print(f'    {cat:40s} {count:4d}')

    print(f'\n  Sample unclassified titles:')
    for _, ref, title in unclassified[:15]:
        print(f'    {ref:20s} {title[:100]}')

    # Phase 2: LLM classification for the rest
    print(f'\nPhase 2: LLM classification ({len(unclassified)} propositions)...')
    classified_llm = classify_with_llm(unclassified)

    llm_counts = Counter(c[3] for c in classified_llm)
    print(f'\n  LLM classified: {len(classified_llm)}')
    print('\n  Category breakdown (LLM):')
    for cat, count in llm_counts.most_common():
        print(f'    {cat:40s} {count:4d}')

    # Phase 3: Generate summaries for keyword-classified ones
    print(f'\nPhase 3: Generating summaries for keyword-classified propositions ({len(classified_kw)})...')
    summaries_kw = generate_summaries_for_keywords(classified_kw)
    print(f'  Generated {len(summaries_kw)} summaries')

    # Save everything
    print('\nSaving to database...')
    save_classifications(conn, classified_kw, classified_llm, summaries_kw)

    # Final stats
    print('\n=== Final Classification Stats ===')
    all_counts = kw_counts + llm_counts
    for cat, count in all_counts.most_common():
        print(f'  {cat:40s} {count:4d}')
    print(f'  {"TOTAL":40s} {sum(all_counts.values()):4d}')

    conn.close()
    print('\nDone!')


if __name__ == '__main__':
    main()
