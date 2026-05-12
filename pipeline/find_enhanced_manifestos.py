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
from urllib.parse import urljoin, urlparse

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


MAX_INTERNAL_LINKS = 40
LINK_TEXT_MAX = 80


def _same_site(host_a: str, host_b: str) -> bool:
    a = (host_a or '').lower().lstrip('.')
    b = (host_b or '').lower().lstrip('.')
    if a.startswith('www.'): a = a[4:]
    if b.startswith('www.'): b = b[4:]
    return bool(a) and bool(b) and (a == b or a.endswith('.' + b) or b.endswith('.' + a))


def extract_internal_links(html: str, base_url: str) -> list[dict]:
    """Pull <a href> links on the same registrable site as base_url. Returns a
    deduped, capped list of {text, url} dicts in document order. Used to let
    the extractor drill into /manifesto, /policies etc. when the search step
    landed on a homepage."""
    base_host = urlparse(base_url).hostname or ''
    seen: set[str] = set()
    out: list[dict] = []
    for m in re.finditer(
        r'<a\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html, flags=re.DOTALL | re.IGNORECASE,
    ):
        href = m.group(1).strip()
        if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:')):
            continue
        try:
            absolute = urljoin(base_url, href)
        except Exception:
            continue
        parsed = urlparse(absolute)
        if parsed.scheme not in ('http', 'https'):
            continue
        if not _same_site(parsed.hostname or '', base_host):
            continue
        # Drop fragment so /policies and /policies#x dedupe to the same entry
        clean = parsed._replace(fragment='').geturl()
        if clean == base_url or clean in seen:
            continue
        # Cheap inner-text strip — good enough for the model to recognise links
        text = re.sub(r'<[^>]+>', ' ', m.group(2))
        text = re.sub(r'\s+', ' ', unescape(text)).strip()[:LINK_TEXT_MAX]
        if not text:
            continue
        seen.add(clean)
        out.append({'text': text, 'url': clean})
        if len(out) >= MAX_INTERNAL_LINKS:
            break
    return out


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
{links_block}
Extract ONLY the candidate's own platform/policy statements, copying their wording verbatim. Skip site navigation, generic party boilerplate that isn't specific to this candidate, donate buttons, cookie banners, comments by other people, and unrelated news content.

If the page above is a landing page / homepage / "about me" stub and the actual platform clearly lives at one of the internal links listed (e.g. /manifesto, /policies, /platform, /vision, /priorities), respond with that URL in `next_url` instead of extracting — we will fetch it and re-run extraction. Only set `next_url` when you are confident a listed link is the real manifesto destination; otherwise extract whatever platform content this page does contain.

If the page does not actually contain platform/policy content for this candidate AND there is no obvious better link, return manifesto_text as an empty string with a note explaining why.

Return ONLY a single JSON object (no markdown fences, no surrounding prose). Schema:
{{
  "manifesto_text": "<verbatim extracted text; may be empty>",
  "next_url": "<one URL from the internal links list, or null>",
  "note": "<one-sentence description of what was extracted, why next_url was picked, or why nothing was found>"
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


def fetch_page(url: str) -> tuple[str, str, list[dict]] | None:
    """Return (kind, text, links) where kind is 'html'|'text'|'pdf'.
    links is the list of same-site <a href> targets (empty for non-HTML),
    used by extract_manifesto to drill one hop deeper when the page is a
    landing page rather than the manifesto itself. Returns None on failure."""
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
    final_url = str(r.url)
    ctype = (r.headers.get('content-type') or '').lower()
    if 'pdf' in ctype or url.lower().endswith('.pdf'):
        # We don't extract PDFs in this iteration; a future pass can use pdftotext.
        return ('pdf', '', [])
    raw = r.text
    is_html = 'html' in ctype or '<html' in raw[:2048].lower() or '<body' in raw[:2048].lower()
    if is_html:
        links = extract_internal_links(raw, final_url)
        body = strip_tags(raw)
    else:
        links = []
        body = raw
    return ('html' if is_html else 'text', body[:MAX_PAGE_CHARS], links)


def extract_manifesto(client, name: str, url: str, page_text: str,
                      links: list[dict] | None = None) -> dict:
    if links:
        rendered = '\n'.join(f'  - {l["text"]} -> {l["url"]}' for l in links)
        links_block = f'\nInternal links found on this page (same site only):\n{rendered}\n'
    else:
        links_block = '\n'
    prompt = EXTRACT_PROMPT.format(
        name=name, url=url, page_text=page_text, links_block=links_block,
    )
    text_response = messages_stream_text_with_retry(
        client,
        model=MODEL,
        max_tokens=EXTRACT_MAX_TOKENS,
        messages=[{'role': 'user', 'content': prompt}],
    )
    data = parse_json_response(text_response)
    text = (data.get('manifesto_text') or '').strip()
    next_url = (data.get('next_url') or '').strip() or None
    # Only honour next_url if it was actually one of the links we offered, so a
    # hallucinated URL or off-site redirect can't hijack the fetch.
    allowed = {l['url'] for l in (links or [])}
    if next_url and next_url not in allowed:
        next_url = None
    note = (data.get('note') or '').strip()[:500]
    return {'manifesto_text': text, 'next_url': next_url, 'note': note}


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

        # Up to one drill-down hop: if the search step landed on a homepage and
        # the model thinks the real manifesto is at a same-site link (validated
        # against the offered list inside extract_manifesto), fetch that and
        # re-extract. Capped at one hop so we can't loop.
        current_url = src['url']
        current_page = page
        hop_notes: list[str] = []
        ext = None
        for hop in range(2):
            try:
                ext = extract_manifesto(
                    client, name, current_url, current_page[1],
                    links=current_page[2],
                )
            except Exception as e:
                print(f'  extract error: {e}')
                update_candidate(cur, conn, cand_id, status='error',
                                 source_url=current_url,
                                 source_label=src['source_label'],
                                 notes=f'{src["note"]} | extract error: {e}')
                err_n += 1
                ext = None
                break

            if hop == 0 and ext['next_url'] and not ext['manifesto_text']:
                print(f'  drilling -> {ext["next_url"]}')
                hop_notes.append(f'hopped from {current_url} ({ext["note"]})')
                next_page = fetch_page(ext['next_url'])
                if not next_page or not next_page[1]:
                    print(f'    drill fetch_failed; keeping landing page extract')
                    # Re-extract the landing page without offering next_url so
                    # we get whatever content it does contain.
                    ext = extract_manifesto(
                        client, name, current_url, current_page[1], links=None,
                    )
                    break
                current_url = ext['next_url']
                current_page = next_page
                continue
            break

        if ext is None:
            time.sleep(2.0)
            continue

        text = ext['manifesto_text']
        wc = len(text.split()) if text else 0
        notes_tail = ' | '.join([src['note'], *hop_notes, ext['note']])
        if wc < 30:
            print(f'  empty ({wc} words): {ext["note"]}')
            update_candidate(cur, conn, cand_id, status='empty',
                             source_url=current_url,
                             source_label=src['source_label'],
                             notes=notes_tail)
            miss_n += 1
        else:
            print(f'  found ({wc} words) -> {current_url}')
            update_candidate(cur, conn, cand_id, status='found',
                             text=text, word_count=wc,
                             source_url=current_url,
                             source_label=src['source_label'],
                             notes=f'{src["source_label"]}/{src["confidence"]} | '
                                   f'{notes_tail}')
            found_n += 1

        time.sleep(BATCH_DELAY_SEC)

    cur.close()
    conn.close()
    print(f'\nDone. found={found_n}, not_found={miss_n}, errors={err_n}')


if __name__ == '__main__':
    main()
