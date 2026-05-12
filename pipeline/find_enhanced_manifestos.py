"""
Find fuller versions of each candidate's manifesto on the open web and store
them alongside the original vote.je text in candidates.enhanced_manifesto_*.

Two-step per candidate:
  1. Claude with the web_search server-side tool picks the single best URL
     where the candidate (or their party) publishes their platform. vote.je
     and Wikipedia are blocked at the tool level — we already have vote.je.
  2. We httpx-fetch the URL ourselves, strip HTML, then ask Claude (no tools)
     to extract the candidate's own words verbatim. Keeping the fetch in our
     hands means the stored text is traceable to a real HTTP response.

Original manifesto_text is never overwritten. classify_candidates.py reads
COALESCE(enhanced_manifesto_text, manifesto_text) and reclassifies a
candidate when enhanced_manifesto_fetched_at > classified_at.

Run: python pipeline/find_enhanced_manifestos.py [--limit N] [--refind]
                                                  [--name "Full Name"]
"""

import argparse
import json
import os
import re
import time
from html import unescape

import anthropic
import httpx
import psycopg2
from dotenv import load_dotenv

load_dotenv(override=True)

MODEL = 'claude-sonnet-4-5'
FETCH_TIMEOUT = 20.0
MAX_PAGE_CHARS = 200_000   # don't feed huge pages to the LLM
EXTRACT_MAX_TOKENS = 16384
BATCH_DELAY_SEC = 1.0
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SEC = (2.0, 5.0)

SOURCE_LABELS = {
    'personal_site', 'party_page', 'facebook', 'linkedin', 'other',
}

FETCH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/126.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-GB,en;q=0.9',
}


def db_connect():
    return psycopg2.connect(
        os.environ['DATABASE_URL'],
        keepalives=1, keepalives_idle=30, keepalives_interval=10,
        keepalives_count=5, connect_timeout=15,
    )


def strip_tags(html: str) -> str:
    text = unescape(html)
    text = re.sub(r'<script\b.*?</script>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style\b.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'</(p|h[1-6]|div|li|tr)>', '\n', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()


def parse_json_response(text: str):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    # The model sometimes wraps the object in surrounding prose despite
    # instructions. Pull out the outermost {...} block.
    if not text.startswith('{'):
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            text = m.group(0)
    return json.loads(text)


def final_text(resp) -> str:
    """Concatenate text from all `text` content blocks in the response. Skips
    server-tool-use blocks emitted by the web_search agentic loop."""
    parts = []
    for block in resp.content:
        if getattr(block, 'type', None) == 'text':
            parts.append(block.text)
    return '\n'.join(parts).strip()


_TRANSIENT_API_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


def messages_create_with_retry(client, **kwargs):
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return client.messages.create(**kwargs)
        except _TRANSIENT_API_ERRORS as e:
            if attempt == RETRY_ATTEMPTS - 1:
                raise
            delay = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC) - 1)]
            print(f'    transient API error (attempt {attempt+1}/{RETRY_ATTEMPTS}): '
                  f'{type(e).__name__}; retrying in {delay}s')
            time.sleep(delay)


# Stream for calls that may take >2 min: non-streamed responses sit idle on the
# socket while Sonnet generates, and consumer-grade middleboxes (NAT, ISP) close
# the connection as idle. Streaming keeps bytes flowing every few hundred ms.
def messages_stream_text_with_retry(client, **kwargs) -> str:
    for attempt in range(RETRY_ATTEMPTS):
        try:
            with client.messages.stream(**kwargs) as stream:
                parts = list(stream.text_stream)
            return ''.join(parts).strip()
        except _TRANSIENT_API_ERRORS as e:
            if attempt == RETRY_ATTEMPTS - 1:
                raise
            delay = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC) - 1)]
            print(f'    transient API error (attempt {attempt+1}/{RETRY_ATTEMPTS}): '
                  f'{type(e).__name__}; retrying in {delay}s')
            time.sleep(delay)


SEARCH_PROMPT = """You are helping a civic-transparency project find candidate manifestos for the 2026 Jersey States Assembly election (election day: 7 June 2026).

Candidate: {name}
Role: {role}
Constituency: {constituency}
Party: {party}

Use web_search to find the single best URL where THIS candidate (or their party on their behalf) publishes their platform / manifesto / policy positions for the 2026 election. The source must be authored or controlled by the candidate or their party — not third-party reporting about them.

Strongly prefer, in order:
  1. The candidate's personal campaign website
  2. The candidate's party's page for this candidate (e.g. Reform Jersey, Progress Party, Jersey Liberal Conservatives)
  3. A public Facebook page run by the candidate with a long pinned platform post
  4. A LinkedIn post by the candidate stating their platform

Avoid:
  - vote.je (we already have that text)
  - Wikipedia
  - News articles, profiles, or interviews (Jersey Evening Post, BBC, ITV, Bailiwick Express, etc.) — even when the candidate is quoted, the framing and selection is the journalist's, not the candidate's, so it isn't a fair comparison against candidates who weren't profiled
  - Hustings coverage written by third parties
  - Third-party commentary that paraphrases rather than quotes the candidate
  - Generic party homepages that aren't about this specific candidate

If you cannot find clearly candidate-owned content, return found=false. It is expected and fair for many candidates to have nothing beyond their vote.je page — do not stretch to fit a news source.

Return ONLY a single JSON object (no markdown fences, no surrounding prose). Schema:
{{
  "found": true | false,
  "url": "<string or null>",
  "source_label": "personal_site" | "party_page" | "facebook" | "linkedin" | "other" | null,
  "confidence": "low" | "medium" | "high",
  "note": "<one-sentence explanation of the source picked, or why no source was found>"
}}"""


EXTRACT_PROMPT = """You are extracting a Jersey election candidate's platform/manifesto from a web page.

Candidate: {name}
Source URL: {url}

Page content (stripped to plain text):
\"\"\"
{page_text}
\"\"\"

Extract ONLY the candidate's own platform/policy statements, copying their wording verbatim. Skip site navigation, generic party boilerplate that isn't specific to this candidate, donate buttons, cookie banners, comments by other people, and unrelated news content.

If the page does not actually contain platform/policy content for this candidate, return manifesto_text as an empty string with a note explaining why.

Return ONLY a single JSON object (no markdown fences, no surrounding prose). Schema:
{{
  "manifesto_text": "<verbatim extracted text; may be empty>",
  "note": "<one-sentence description of what was extracted or why nothing was>"
}}"""


def find_source(client, name: str, role: str | None, constituency: str | None,
                party: str | None) -> dict:
    prompt = SEARCH_PROMPT.format(
        name=name,
        role=role or 'unknown',
        constituency=constituency or 'unknown',
        party=party or 'Independent',
    )
    resp = messages_create_with_retry(
        client,
        model=MODEL,
        max_tokens=1024,
        tools=[{
            'type': 'web_search_20250305',
            'name': 'web_search',
            'max_uses': 5,
            'blocked_domains': ['vote.je', 'www.vote.je', 'en.wikipedia.org', 'wikipedia.org'],
            'user_location': {'type': 'approximate', 'country': 'GB'},
        }],
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = final_text(resp)
    data = parse_json_response(text)

    found = bool(data.get('found'))
    url = (data.get('url') or '').strip() or None
    label = data.get('source_label')
    if label not in SOURCE_LABELS:
        label = 'other' if (found and url) else None
    note = (data.get('note') or '').strip()[:500]
    if found and not url:
        found = False
        note = note or 'model claimed found but returned no URL'
    return {
        'found': found, 'url': url, 'source_label': label,
        'confidence': data.get('confidence'), 'note': note,
    }


def fetch_page(url: str) -> tuple[str, str] | None:
    """Return (kind, text) where kind is 'html'|'text'|'pdf', or None on failure."""
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True,
                          headers=FETCH_HEADERS) as c:
            r = c.get(url)
    except Exception as e:
        print(f'    fetch error: {e}')
        return None
    if r.status_code >= 400:
        print(f'    HTTP {r.status_code}')
        return None
    ctype = (r.headers.get('content-type') or '').lower()
    if 'pdf' in ctype or url.lower().endswith('.pdf'):
        # We don't extract PDFs in this iteration; a future pass can use pdftotext.
        return ('pdf', '')
    body = r.text
    if '<html' in body[:2048].lower() or '<body' in body[:2048].lower() or 'html' in ctype:
        body = strip_tags(body)
    return ('html' if 'html' in ctype else 'text', body[:MAX_PAGE_CHARS])


def extract_manifesto(client, name: str, url: str, page_text: str) -> dict:
    prompt = EXTRACT_PROMPT.format(name=name, url=url, page_text=page_text)
    text_response = messages_stream_text_with_retry(
        client,
        model=MODEL,
        max_tokens=EXTRACT_MAX_TOKENS,
        messages=[{'role': 'user', 'content': prompt}],
    )
    data = parse_json_response(text_response)
    text = (data.get('manifesto_text') or '').strip()
    note = (data.get('note') or '').strip()[:500]
    return {'manifesto_text': text, 'note': note}


def update_candidate(cur, conn, cand_id: int, *,
                     status: str,
                     text: str | None = None,
                     word_count: int | None = None,
                     source_url: str | None = None,
                     source_label: str | None = None,
                     notes: str | None = None):
    cur.execute(
        '''
        UPDATE candidates SET
            enhanced_manifesto_status = %(status)s,
            enhanced_manifesto_text = %(text)s,
            enhanced_manifesto_word_count = %(wc)s,
            enhanced_manifesto_source_url = %(url)s,
            enhanced_manifesto_source_label = %(label)s,
            enhanced_manifesto_notes = %(notes)s,
            enhanced_manifesto_fetched_at = CASE WHEN %(status)s = 'found' THEN NOW()
                                                 ELSE enhanced_manifesto_fetched_at END
        WHERE candidate_id = %(cid)s
        ''',
        {
            'status': status,
            'text': text,
            'wc': word_count,
            'url': source_url,
            'label': source_label,
            'notes': (notes or '')[:1000],
            'cid': cand_id,
        },
    )
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--refind', action='store_true',
                        help='Reprocess even candidates already searched')
    parser.add_argument('--election-year', type=int, default=2026)
    parser.add_argument('--name', type=str, default=None,
                        help='Process a single candidate by exact full_name (debugging)')
    args = parser.parse_args()

    conn = db_connect()
    cur = conn.cursor()

    where = 'WHERE election_year = %s'
    params: list = [args.election_year]
    if args.name:
        where += ' AND full_name = %s'
        params.append(args.name)
    elif not args.refind:
        where += " AND (enhanced_manifesto_status IS NULL OR enhanced_manifesto_status = 'pending')"

    cur.execute(
        f'''
        SELECT candidate_id, full_name, role, constituency, party
        FROM candidates
        {where}
        ORDER BY full_name
        ''',
        params,
    )
    rows = cur.fetchall()
    if args.limit:
        rows = rows[: args.limit]
    print(f'Processing {len(rows)} candidates')

    client = anthropic.Anthropic()
    found_n, miss_n, err_n = 0, 0, 0

    for i, (cand_id, name, role, constituency, party) in enumerate(rows):
        print(f'[{i+1}/{len(rows)}] {name}')
        try:
            src = find_source(client, name, role, constituency, party)
        except Exception as e:
            print(f'  search error: {e}')
            update_candidate(cur, conn, cand_id, status='error',
                             notes=f'search error: {e}')
            err_n += 1
            time.sleep(2.0)
            continue

        if not src['found'] or not src['url']:
            print(f'  not_found: {src["note"]}')
            update_candidate(cur, conn, cand_id, status='not_found',
                             notes=src['note'])
            miss_n += 1
            time.sleep(BATCH_DELAY_SEC)
            continue

        page = fetch_page(src['url'])
        if not page or not page[1]:
            kind = page[0] if page else 'no-response'
            print(f'  fetch_failed ({kind}): {src["url"]}')
            update_candidate(cur, conn, cand_id, status='fetch_failed',
                             source_url=src['url'],
                             source_label=src['source_label'],
                             notes=f'{src["note"]} | fetch_failed: {kind}')
            err_n += 1
            time.sleep(BATCH_DELAY_SEC)
            continue

        try:
            ext = extract_manifesto(client, name, src['url'], page[1])
        except Exception as e:
            print(f'  extract error: {e}')
            update_candidate(cur, conn, cand_id, status='error',
                             source_url=src['url'],
                             source_label=src['source_label'],
                             notes=f'{src["note"]} | extract error: {e}')
            err_n += 1
            time.sleep(2.0)
            continue

        text = ext['manifesto_text']
        wc = len(text.split()) if text else 0
        if wc < 30:
            print(f'  empty ({wc} words): {ext["note"]}')
            update_candidate(cur, conn, cand_id, status='empty',
                             source_url=src['url'],
                             source_label=src['source_label'],
                             notes=f'{src["note"]} | {ext["note"]}')
            miss_n += 1
        else:
            print(f'  found ({wc} words) -> {src["url"]}')
            update_candidate(cur, conn, cand_id, status='found',
                             text=text, word_count=wc,
                             source_url=src['url'],
                             source_label=src['source_label'],
                             notes=f'{src["source_label"]}/{src["confidence"]} | '
                                   f'{src["note"]} | {ext["note"]}')
            found_n += 1

        time.sleep(BATCH_DELAY_SEC)

    cur.close()
    conn.close()
    print(f'\nDone. found={found_n}, not_found={miss_n}, errors={err_n}')


if __name__ == '__main__':
    main()
