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
import socket
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
    'party_manifesto',  # shared party-wide manifesto applied to every party member
}

REFORM_JERSEY_MANIFESTO_URL = 'https://www.reformjersey.je/manifesto'
# Standard nav across every Reform Jersey page; we strip it from each chapter
# body before concatenating so the combined manifesto isn't peppered with menu
# repeats.
REFORM_NAV_PREFIX_RE = re.compile(
    r'^\s*(HOME\s*/\s*MANIFESTO\s*/\s*NEWS\s*/\s*EVENTS\s*/\s*JOIN\s*/\s*CONTACT\s*/?\s*)+',
    re.IGNORECASE,
)

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


EXTRACT_SENTINEL = '---MANIFESTO-TEXT-FOLLOWS---'
EXTRACT_PROMPT = """You are extracting a Jersey election candidate's platform/manifesto from a web page.

Candidate: {name}
Source URL: {url}

Page content (stripped to plain text):
\"\"\"
{page_text}
\"\"\"
{links_block}
Extract ONLY the candidate's own platform/policy statements, copying their wording verbatim. Skip site navigation, generic party boilerplate that isn't specific to this candidate, donate buttons, cookie banners, comments by other people, and unrelated news content.

If the page above is a landing page / homepage / "about me" stub and the actual platform clearly lives at ONE of the internal links listed (e.g. /manifesto, /policies, /platform, /vision, /priorities), respond with that URL in `next_url` instead of extracting — we will fetch it and re-run extraction. Only set `next_url` when you are confident a listed link is the real manifesto destination; otherwise extract whatever platform content this page does contain.

If the page lists multiple sub-pages that each contain one slice of the platform (e.g. /priorities/ listing /priorities/housing, /priorities/health, /priorities/economy; or /policies/ listing per-topic policy pages; or a "Core Themes" / "Manifesto" section listing per-topic links each on its own URL), respond with `aggregate_urls` set to the list of those sub-page URLs. We will fetch every URL in that list, concatenate the bodies, and re-run extraction over the combined text.

This applies EVEN IF the current page has substantive teaser/intro text for each topic. A teaser like "A Fair Deal for Islanders — How Jersey creates wealth, shares risk..." with a link to /priorities/fair-deal/ is a signal to aggregate the full sub-pages, not to extract only the teaser. The candidate took the trouble to put each topic on its own page — extracting only the homepage teasers would underrepresent them.

Use `aggregate_urls` only when the listed sub-pages are the same kind of thing (chapters of the candidate's own platform); do not include unrelated nav links, news posts, blog entries, or other candidates' pages. Cap at ~25 URLs.

Pick at most one of `next_url` or `aggregate_urls`. If both could apply, prefer `aggregate_urls` for index/teaser pages and `next_url` for "click here for the manifesto" stubs.

If the page does not actually contain platform/policy content for this candidate AND there is no obvious better link, leave the manifesto text section empty with a note explaining why.

Output format (strict — no markdown fences, no surrounding prose):

  Line 1: a single-line JSON object with the small structured fields:
    {{"next_url": <one URL from the internal links list, or null>, "aggregate_urls": [<URLs from the internal links list>] or null, "note": "<one-sentence description>"}}

  Line 2: the literal sentinel `{sentinel}` on its own line.

  Lines 3+: the verbatim manifesto text (or nothing if there is none). May contain
  any characters including newlines and quotes — no escaping needed because we
  read everything after the sentinel as raw text.

This format means you do not need to escape quotes, newlines, or control characters
in the manifesto text — just paste it after the sentinel as-is."""


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


PLAYWRIGHT_NAV_TIMEOUT_MS = 25_000
PLAYWRIGHT_SETTLE_MS = 3000   # let client-rendered content paint after DOMContentLoaded
# Sites behind a Cloudflare/wp.com browser-check show "Checking your browser..."
# for several seconds before the real page paints. If the rendered text matches
# this pattern after the initial settle, wait again and retry the read.
CHALLENGE_RETRY_MS = 6000
CHALLENGE_MARKERS = ('checking your browser', 'just a moment', 'cf-browser-verification',
                     'attention required')


def fetch_reform_manifesto(browser) -> tuple[str, str] | None:
    """Reform Jersey publishes their manifesto as a multi-page set on
    reformjersey.je: the /manifesto landing is just a table of contents that
    links out to chapter pages like /Foreword, /Key Pledges, /Healthcare and
    Wellbeing, etc. Fetch the landing, follow each chapter link, strip the
    repeated nav header from each body, and concatenate. Returns
    (combined_text, note) or None on failure."""
    landing = fetch_page(browser, REFORM_JERSEY_MANIFESTO_URL)
    if not landing or not landing[1]:
        return None

    # Heuristic: chapter URLs use Title Case slugs ('/Foreword', '/Key Pledges')
    # while nav and per-candidate pages are lowercase ('/home', '/carinaalves').
    # Plus exclude /pages, /documents, the manifesto landing itself.
    chapter_links: list[dict] = []
    seen_paths: set[str] = set()
    for link in landing[2]:
        path = urlparse(link['url']).path
        if not path or path == '/' or path in seen_paths:
            continue
        if path.lower() in ('/manifesto',):
            continue
        if path.lower().startswith(('/pages/', '/documents/')):
            continue
        # Title-case marker: any uppercase letter after the leading slash, or a
        # space in the path. Catches '/Foreword' and '/Key Pledges' but excludes
        # '/carinaalves', '/agreement2018', '/newdeal'.
        slug = path[1:]
        if not (' ' in slug or '%20' in slug or any(c.isupper() for c in slug)):
            continue
        seen_paths.add(path)
        chapter_links.append(link)

    if not chapter_links:
        return None

    print(f'[setup] aggregating {len(chapter_links)} Reform manifesto chapters')
    parts: list[str] = []
    chapters_ok = 0
    for link in chapter_links:
        page = fetch_page(browser, link['url'])
        if not page or not page[1]:
            continue
        body = REFORM_NAV_PREFIX_RE.sub('', page[1]).strip()
        # Drop the chapter title duplicated as the first line if it matches the
        # link text — it'll be re-emitted as our heading line below.
        if body.lower().startswith(link['text'].lower()):
            body = body[len(link['text']):].lstrip(' /\n')
        parts.append(f'## {link["text"]}\n\n{body}')
        chapters_ok += 1

    if not parts:
        return None
    combined = '\n\n'.join(parts)[:MAX_PAGE_CHARS]
    note = (f'Aggregated {chapters_ok}/{len(chapter_links)} chapter pages from '
            f'{REFORM_JERSEY_MANIFESTO_URL}')
    return combined, note


def host_resolves(url: str) -> bool:
    """Check whether the URL's hostname has a DNS record. The search step
    occasionally hallucinates plausible-sounding domains (marklabey.com,
    mikejackson.je, richardvibert.je in our last batch) that don't exist;
    catching them here saves a Playwright launch and gives a clean
    not_found status instead of fetch_failed."""
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        socket.getaddrinfo(host, None)
        return True
    except (socket.gaierror, OSError):
        return False


def _httpx_pdf_probe(url: str) -> bool:
    """Cheap content-type check so we don't fire up the browser for a PDF."""
    if url.lower().endswith('.pdf'):
        return True
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True, headers=FETCH_HEADERS) as c:
            r = c.head(url)
        return 'pdf' in (r.headers.get('content-type') or '').lower()
    except Exception:
        return False


def fetch_page(browser, url: str) -> tuple[str, str, list[dict]] | None:
    """Return (kind, text, links) where kind is 'html'|'pdf'. Renders the page
    with Playwright (Chromium) so JS-built sites — Reform Jersey's page builder,
    SPA campaign sites, lyndonfarnham.je's /manifesto-2/ — actually populate
    before we read them. Returns None on failure.

    links is the list of same-site <a href> targets pulled from the *rendered*
    DOM, used by extract_manifesto to drill one hop deeper when the page is a
    landing page rather than the manifesto itself."""
    if _httpx_pdf_probe(url):
        # PDFs are out of scope for this pass; a later iteration can pdftotext them.
        return ('pdf', '', [])

    from playwright.sync_api import Error as PWError, TimeoutError as PWTimeout

    context = browser.new_context(
        user_agent=FETCH_HEADERS['User-Agent'],
        locale='en-GB',
        viewport={'width': 1280, 'height': 1800},
    )
    page = context.new_page()
    try:
        try:
            # domcontentloaded over networkidle — analytics/ads pixels keep
            # many candidate sites from ever reaching idle, and we'd rather
            # take the rendered DOM after a fixed settle than time out.
            page.goto(url, wait_until='domcontentloaded', timeout=PLAYWRIGHT_NAV_TIMEOUT_MS)
        except PWTimeout:
            print('    nav timeout; continuing with whatever rendered')
        page.wait_for_timeout(PLAYWRIGHT_SETTLE_MS)

        def _read():
            html = page.content()
            try:
                visible = page.locator('body').inner_text(timeout=5_000)
            except (PWTimeout, PWError):
                visible = strip_tags(html)
            return html, visible

        rendered_html, visible_text = _read()
        if any(m in visible_text.lower() for m in CHALLENGE_MARKERS):
            print('    bot challenge detected; waiting longer')
            page.wait_for_timeout(CHALLENGE_RETRY_MS)
            rendered_html, visible_text = _read()
        final_url = page.url
    except Exception as e:
        print(f'    fetch error: {e}')
        try:
            context.close()
        except Exception:
            pass
        return None
    finally:
        try:
            context.close()
        except Exception:
            pass

    links = extract_internal_links(rendered_html, final_url)
    body = re.sub(r'\n{3,}', '\n\n', visible_text).strip()
    return ('html', body[:MAX_PAGE_CHARS], links)


def _parse_extract_response(raw: str) -> dict:
    """Split the model's response on EXTRACT_SENTINEL: header is one-line JSON
    with next_url + note; body is raw verbatim manifesto text. Avoids the
    JSON-with-embedded-newlines class of parse failures."""
    raw = raw.strip()
    if EXTRACT_SENTINEL in raw:
        header, _, body = raw.partition(EXTRACT_SENTINEL)
    else:
        # Fallback: no sentinel emitted (older prompt or model drift). Treat
        # the whole thing as a JSON header with no body.
        header, body = raw, ''
    header = header.strip()
    body = body.strip()
    try:
        meta = parse_json_response(header) if header else {}
    except Exception:
        meta = {}
    agg_raw = meta.get('aggregate_urls')
    if not isinstance(agg_raw, list):
        agg_raw = None
    return {
        'manifesto_text': body,
        'next_url': (meta.get('next_url') or None),
        'aggregate_urls': agg_raw,
        'note': (meta.get('note') or '').strip()[:500],
    }


AGGREGATE_URL_CAP = 25


def extract_manifesto(client, name: str, url: str, page_text: str,
                      links: list[dict] | None = None) -> dict:
    if links:
        rendered = '\n'.join(f'  - {l["text"]} -> {l["url"]}' for l in links)
        links_block = f'\nInternal links found on this page (same site only):\n{rendered}\n'
    else:
        links_block = '\n'
    prompt = EXTRACT_PROMPT.format(
        name=name, url=url, page_text=page_text, links_block=links_block,
        sentinel=EXTRACT_SENTINEL,
    )
    text_response = messages_stream_text_with_retry(
        client,
        model=MODEL,
        max_tokens=EXTRACT_MAX_TOKENS,
        messages=[{'role': 'user', 'content': prompt}],
    )
    data = _parse_extract_response(text_response)
    text = data['manifesto_text']
    next_url = data['next_url']
    if next_url is not None:
        next_url = str(next_url).strip() or None
    # Only honour next_url / aggregate_urls if they were actually offered, so a
    # hallucinated URL or off-site redirect can't hijack the fetch.
    allowed = {l['url'] for l in (links or [])}
    if next_url and next_url not in allowed:
        next_url = None
    aggregate_urls: list[str] = []
    if data['aggregate_urls']:
        seen: set[str] = set()
        for u in data['aggregate_urls']:
            u = (u or '').strip() if isinstance(u, str) else ''
            if u and u in allowed and u not in seen:
                seen.add(u)
                aggregate_urls.append(u)
                if len(aggregate_urls) >= AGGREGATE_URL_CAP:
                    break
    # Mutually exclusive in practice: prefer aggregate_urls for index pages.
    if aggregate_urls:
        next_url = None
    return {
        'manifesto_text': text,
        'next_url': next_url,
        'aggregate_urls': aggregate_urls,
        'note': data['note'],
    }


class DB:
    """Auto-reconnecting wrapper. Long extract calls (>10 minutes for the
    aggregated Reform manifesto, multi-minute for any large page) leave the
    Postgres connection idle long enough that Neon's pooler closes it. The
    next write fails with `SSL connection has been closed unexpectedly`."""

    def __init__(self):
        self.conn = db_connect()
        self.cur = self.conn.cursor()

    def reconnect(self):
        try: self.cur.close()
        except Exception: pass
        try: self.conn.close()
        except Exception: pass
        self.conn = db_connect()
        self.cur = self.conn.cursor()

    def close(self):
        try: self.cur.close()
        except Exception: pass
        try: self.conn.close()
        except Exception: pass


def update_candidate(db: DB, cand_id: int, *,
                     status: str,
                     text: str | None = None,
                     word_count: int | None = None,
                     source_url: str | None = None,
                     source_label: str | None = None,
                     notes: str | None = None):
    sql = '''
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
    '''
    params = {
        'status': status, 'text': text, 'wc': word_count,
        'url': source_url, 'label': source_label,
        'notes': (notes or '')[:1000], 'cid': cand_id,
    }
    for attempt in range(2):
        try:
            db.cur.execute(sql, params)
            db.conn.commit()
            return
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            if attempt == 1:
                raise
            print(f'    DB write failed ({type(e).__name__}); reconnecting')
            db.reconnect()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--refind', action='store_true',
                        help='Reprocess even candidates already searched')
    parser.add_argument('--election-year', type=int, default=2026)
    parser.add_argument('--name', type=str, default=None,
                        help='Process specific candidates by exact full_name. '
                             'Comma- or newline-separated for multiple, e.g. '
                             '--name "Alex Curtis, Bernard Place". Implies --refind.')
    args = parser.parse_args()

    db = DB()

    # --name can be a single name, comma-separated, or newline-separated (the
    # latter so a workflow_dispatch multi-line input pastes through cleanly).
    requested_names: list[str] = []
    if args.name:
        for chunk in re.split(r'[,\n]', args.name):
            chunk = chunk.strip()
            if chunk:
                requested_names.append(chunk)

    where = 'WHERE election_year = %s'
    params: list = [args.election_year]
    if requested_names:
        where += ' AND full_name = ANY(%s)'
        params.append(requested_names)
    elif not args.refind:
        where += " AND (enhanced_manifesto_status IS NULL OR enhanced_manifesto_status = 'pending')"

    db.cur.execute(
        f'''
        SELECT candidate_id, full_name, role, constituency, party
        FROM candidates
        {where}
        ORDER BY full_name
        ''',
        params,
    )
    rows = db.cur.fetchall()
    if args.limit:
        rows = rows[: args.limit]
    if requested_names:
        matched = {r[1] for r in rows}
        missing = [n for n in requested_names if n not in matched]
        if missing:
            print(f'Warning: no candidate row matched: {", ".join(missing)}')
    print(f'Processing {len(rows)} candidates')

    client = anthropic.Anthropic()
    found_n, miss_n, err_n = 0, 0, 0

    # One headless Chromium for the whole run — launching per-candidate would
    # add ~1s of overhead per page and exhaust the runner's file descriptors.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            # Reform Jersey publishes a single party manifesto that covers every
            # member candidate. Fetch it once and apply to all Reform candidates
            # in this batch — saves search/extract calls and avoids the search
            # step landing on per-candidate stub pages with thin content.
            reform_text, reform_note = None, None
            if any((p or '').lower() == 'reform jersey' for *_, p in rows):
                print(f'[setup] fetching shared Reform Jersey manifesto')
                rj = fetch_reform_manifesto(browser)
                if rj:
                    reform_text, reform_note = rj
                    print(f'[setup] Reform manifesto: {len(reform_text.split())} words')
                else:
                    print(f'[setup] Reform manifesto aggregation failed')

            for i, (cand_id, name, role, constituency, party) in enumerate(rows):
                print(f'[{i+1}/{len(rows)}] {name}')

                # Reform Jersey candidates: apply the shared party manifesto and
                # skip the per-candidate search/fetch pipeline entirely.
                if (party or '').lower() == 'reform jersey' and reform_text:
                    wc = len(reform_text.split())
                    print(f'  reform party manifesto ({wc} words) -> {REFORM_JERSEY_MANIFESTO_URL}')
                    update_candidate(db, cand_id, status='found',
                                     text=reform_text, word_count=wc,
                                     source_url=REFORM_JERSEY_MANIFESTO_URL,
                                     source_label='party_manifesto',
                                     notes=f'Applied shared Reform Jersey party manifesto. '
                                           f'{reform_note or ""}')
                    found_n += 1
                    continue

                try:
                    src = find_source(client, name, role, constituency, party)
                except Exception as e:
                    print(f'  search error: {e}')
                    update_candidate(db, cand_id, status='error',
                                     notes=f'search error: {e}')
                    err_n += 1
                    time.sleep(2.0)
                    continue

                if not src['found'] or not src['url']:
                    print(f'  not_found: {src["note"]}')
                    update_candidate(db, cand_id, status='not_found',
                                     notes=src['note'])
                    miss_n += 1
                    time.sleep(BATCH_DELAY_SEC)
                    continue

                # DNS pre-check: search step occasionally invents domains. Skip
                # the Playwright launch when the host doesn't resolve.
                if not host_resolves(src['url']):
                    print(f'  not_found (dns): {src["url"]}')
                    update_candidate(db, cand_id, status='not_found',
                                     source_url=src['url'],
                                     source_label=src['source_label'],
                                     notes=f'{src["note"]} | host did not resolve')
                    miss_n += 1
                    time.sleep(BATCH_DELAY_SEC)
                    continue

                page = fetch_page(browser, src['url'])
                if not page or not page[1]:
                    kind = page[0] if page else 'no-response'
                    print(f'  fetch_failed ({kind}): {src["url"]}')
                    update_candidate(db, cand_id, status='fetch_failed',
                                     source_url=src['url'],
                                     source_label=src['source_label'],
                                     notes=f'{src["note"]} | fetch_failed: {kind}')
                    err_n += 1
                    time.sleep(BATCH_DELAY_SEC)
                    continue

                # Up to MAX_NAVIGATIONS navigations away from the source URL:
                # at each step the model can return next_url (drill once) or
                # aggregate_urls (fetch many sub-pages and concatenate). 2
                # navigations covers cases like bernardplace2026.com where the
                # search lands on / and the platform is at /priorities/<topic>/
                # (one drill from / to /priorities/, then aggregate the topic
                # pages). After MAX_NAVIGATIONS, we accept whatever the extract
                # produced even if it's still wanting to drill further.
                MAX_NAVIGATIONS = 2
                current_url = src['url']
                current_page = page
                hop_notes: list[str] = []
                ext = None
                navigations = 0
                aggregated_combined: str | None = None  # set if we ever ran aggregation
                while True:
                    # Once we've exhausted our navigation budget, stop offering
                    # links — otherwise the model returns next_url/aggregate_urls
                    # again instead of committing to extracting from the
                    # synthetic combined doc.
                    offer_links = current_page[2] if navigations < MAX_NAVIGATIONS else None
                    try:
                        ext = extract_manifesto(
                            client, name, current_url, current_page[1],
                            links=offer_links,
                        )
                    except Exception as e:
                        print(f'  extract error: {e}')
                        update_candidate(db, cand_id, status='error',
                                         source_url=current_url,
                                         source_label=src['source_label'],
                                         notes=f'{src["note"]} | extract error: {e}')
                        err_n += 1
                        ext = None
                        break

                    if ext['manifesto_text'] or navigations >= MAX_NAVIGATIONS:
                        break

                    if ext['next_url']:
                        print(f'  drilling -> {ext["next_url"]}')
                        hop_notes.append(f'hopped from {current_url} ({ext["note"]})')
                        next_page = fetch_page(browser, ext['next_url'])
                        if not next_page or not next_page[1]:
                            print(f'    drill fetch_failed; keeping prior extract')
                            ext = extract_manifesto(
                                client, name, current_url, current_page[1], links=None,
                            )
                            break
                        current_url = ext['next_url']
                        current_page = next_page
                        navigations += 1
                        continue

                    if ext['aggregate_urls']:
                        agg = ext['aggregate_urls']
                        print(f'  aggregating {len(agg)} sub-pages from {current_url}')
                        hop_notes.append(f'aggregated {len(agg)} sub-pages from {current_url} ({ext["note"]})')
                        parts: list[str] = []
                        merged_links: list[dict] = []
                        seen_link_urls: set[str] = set()
                        ok = 0
                        for sub_url in agg:
                            sub_page = fetch_page(browser, sub_url)
                            if not sub_page or not sub_page[1]:
                                continue
                            heading = urlparse(sub_url).path.rstrip('/').rsplit('/', 1)[-1] or sub_url
                            parts.append(f'## {heading}\n\n{sub_page[1]}')
                            ok += 1
                            # Carry links from sub-pages forward — when the
                            # aggregated page is itself an index (e.g. Bernard's
                            # /priorities/ which lists /priorities/<topic>/),
                            # the next extract needs to see the deeper links so
                            # it can drill again on the next navigation.
                            for l in sub_page[2]:
                                if l['url'] not in seen_link_urls:
                                    seen_link_urls.add(l['url'])
                                    merged_links.append(l)
                                    if len(merged_links) >= MAX_INTERNAL_LINKS:
                                        break
                            if len(merged_links) >= MAX_INTERNAL_LINKS:
                                break
                        if not parts:
                            print(f'    aggregate fetch_failed for all sub-pages; keeping prior extract')
                            ext = extract_manifesto(
                                client, name, current_url, current_page[1], links=None,
                            )
                            break
                        combined = '\n\n'.join(parts)[:MAX_PAGE_CHARS]
                        hop_notes.append(f'fetched {ok}/{len(agg)} sub-pages')
                        aggregated_combined = combined
                        current_url = src['url']  # keep the index page as the canonical source
                        current_page = ('html', combined, merged_links)
                        navigations += 1
                        continue

                    break

                if ext is None:
                    time.sleep(2.0)
                    continue

                text = ext['manifesto_text']
                # If we did aggregation work but the final extract came back
                # empty (the model wanted to navigate further or got confused
                # by the synthetic combined doc), fall back to the raw combined
                # text. We'd rather store the aggregated bodies verbatim than
                # throw away the fetches and call it empty.
                if not text and aggregated_combined and len(aggregated_combined.split()) >= 200:
                    print(f'  fallback: using raw aggregated text ({len(aggregated_combined.split())} words)')
                    text = aggregated_combined
                    hop_notes.append('used raw aggregated text (final extract was empty)')
                wc = len(text.split()) if text else 0
                notes_tail = ' | '.join([src['note'], *hop_notes, ext['note']])
                if wc < 30:
                    print(f'  empty ({wc} words): {ext["note"]}')
                    update_candidate(db, cand_id, status='empty',
                                     source_url=current_url,
                                     source_label=src['source_label'],
                                     notes=notes_tail)
                    miss_n += 1
                else:
                    print(f'  found ({wc} words) -> {current_url}')
                    update_candidate(db, cand_id, status='found',
                                     text=text, word_count=wc,
                                     source_url=current_url,
                                     source_label=src['source_label'],
                                     notes=f'{src["source_label"]}/{src["confidence"]} | '
                                           f'{notes_tail}')
                    found_n += 1

                time.sleep(BATCH_DELAY_SEC)
        finally:
            browser.close()

    db.close()
    print(f'\nDone. found={found_n}, not_found={miss_n}, errors={err_n}')


if __name__ == '__main__':
    main()
