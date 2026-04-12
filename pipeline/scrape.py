"""
AgenticGov Proposition Scraper
Fetches full proposition text from statesassembly.je for all propositions.
Stores the raw text in the database for classification and summarization.
"""

import os
import re
import time
import urllib.request
from html import unescape

import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

load_dotenv()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-GB,en;q=0.9',
}


def extract_article_text(html: str) -> str:
    """Extract clean text from the <article> tag of a proposition page."""
    match = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)
    if not match:
        return ''

    content = match.group(1)
    # Convert HTML entities
    content = unescape(content)
    # Convert line breaks and block elements to newlines
    content = re.sub(r'<br\s*/?>', '\n', content)
    content = re.sub(r'</(p|h[1-6]|div|li|tr)>', '\n', content)
    # Remove remaining tags
    content = re.sub(r'<[^>]+>', ' ', content)
    # Clean up CSS artifacts
    content = re.sub(r'body\s*\{[^}]*\}', '', content)
    content = re.sub(r'p\s*\{[^}]*\}', '', content)
    content = re.sub(r'li,\s*table\s*\{[^}]*\}', '', content)
    content = re.sub(r'\.awlist\d+[^}]*\}', '', content)
    content = re.sub(r'\.awlist\d+\s*>\s*li:before\s*\{[^}]*\}', '', content)
    # Collapse whitespace
    content = re.sub(r'[ \t]+', ' ', content)
    content = re.sub(r'\n\s*\n', '\n\n', content)
    return content.strip()


def extract_metadata(html: str) -> dict:
    """Extract metadata from the proposition page."""
    meta = {}

    # Lodged by
    match = re.search(r'Lodged by\s*:\s*([^<\n]+)', html)
    if match:
        meta['lodged_by'] = match.group(1).strip()

    # Published date
    match = re.search(r'Published on\s*:\s*([^<\n]+)', html)
    if match:
        meta['published_date'] = match.group(1).strip()

    # Debate date
    match = re.search(r'Debate date\s*:\s*([^<\n]+)', html)
    if match:
        meta['debate_date'] = match.group(1).strip()

    return meta


def fetch_proposition(url: str) -> tuple[str, dict] | None:
    """Fetch a proposition page and return (text, metadata)."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode('utf-8')
        text = extract_article_text(html)
        metadata = extract_metadata(html)
        return text, metadata
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # Page doesn't exist
        raise
    except Exception:
        return None


def main():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    # Add scraped_text column if it doesn't exist
    cur.execute('''
        ALTER TABLE propositions
        ADD COLUMN IF NOT EXISTS scraped_text TEXT,
        ADD COLUMN IF NOT EXISTS lodged_by TEXT,
        ADD COLUMN IF NOT EXISTS scrape_status TEXT DEFAULT 'pending'
    ''')
    conn.commit()

    # Get all propositions that haven't been scraped yet
    cur.execute('''
        SELECT proposition_id, base_reference, source_url
        FROM propositions
        WHERE scrape_status = 'pending' OR scrape_status IS NULL
        ORDER BY year DESC, number
    ''')
    propositions = cur.fetchall()
    print(f'Propositions to scrape: {len(propositions)}')

    success = 0
    not_found = 0
    errors = 0

    for i, (prop_id, ref, url) in enumerate(propositions):
        if not url:
            continue

        result = fetch_proposition(url)

        if result is None:
            cur.execute(
                'UPDATE propositions SET scrape_status = %s WHERE proposition_id = %s',
                ('not_found', prop_id)
            )
            not_found += 1
        else:
            text, metadata = result
            cur.execute('''
                UPDATE propositions
                SET scraped_text = %s, lodged_by = %s, scrape_status = %s
                WHERE proposition_id = %s
            ''', (text, metadata.get('lodged_by'), 'scraped', prop_id))
            success += 1

        # Commit every 50 and print progress
        if (i + 1) % 50 == 0:
            conn.commit()
            print(f'  Progress: {i+1}/{len(propositions)} '
                  f'(success={success}, not_found={not_found}, errors={errors})')

        # Polite delay
        time.sleep(0.3)

    conn.commit()
    cur.close()
    conn.close()

    print(f'\nDone! success={success}, not_found={not_found}, errors={errors}')


if __name__ == '__main__':
    main()
