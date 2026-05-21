"""
Jersey Votes Candidate Scraper
Fetches the candidate index and individual profile pages from vote.je,
storing names, contact info, and manifesto text for later LLM classification.

Run: python pipeline/scrape_candidates.py [--election-year 2026]
"""

import argparse
import os
import re
import secrets
import time
import unicodedata
import urllib.parse
from html import unescape

import httpx
import psycopg2
from dotenv import load_dotenv

# override=True so a shell-exported DATABASE_URL/ANTHROPIC_API_KEY doesn't
# shadow the value in .env (python-dotenv defaults to NOT overriding).
load_dotenv(override=True)

INDEX_URL = 'https://www.vote.je/candidates/'
HEADERS = {
    # NOTE: vote.je's WordPress/CDN stack returns a truncated 58KB shell to
    # urllib but the full 216KB page to httpx/curl/Chrome. Using a desktop
    # Chrome UA via httpx is what works.
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-GB,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
}

# Module-level client so we keep one connection pool / TLS handshake.
_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            headers=HEADERS,
            timeout=30.0,
            follow_redirects=True,
        )
    return _client

# Anchors that bracket the manifesto on a vote.je candidate profile.
MANIFESTO_START_ANCHORS = [
    'No previous convictions',
    'Previous convictions',
]
MANIFESTO_END_ANCHORS = [
    'Names of Proposers and Seconders',
    'Proposers and Seconders',
]

LOW_CONTENT_WORDS = 150


def fetch(url: str) -> str | None:
    try:
        r = _get_client().get(url)
    except Exception as e:
        print(f'  fetch error for {url}: {e}')
        return None
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        print(f'  HTTP {r.status_code} for {url}')
        return None
    return r.text


def strip_tags(html: str) -> str:
    text = unescape(html)
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'</(p|h[1-6]|div|li|tr)>', '\n', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()


def canonicalise_name(name: str) -> str:
    """Lowercase, strip accents, collapse whitespace. Mirrors classify pipeline."""
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r'[^A-Za-z0-9\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip().lower()
    return name


def parse_index(html: str) -> list[dict]:
    """Extract per-card metadata from the candidates index page.

    Each card is a <figure data-testid="profile-card"> containing:
      - <a href=".../candidates/2026/{slug}/?from=..."> wrapping the image
      - <img src="..."> photo
      - <h5 data-testid="profile-card-heading"><a>{Name}</a></h5>
      - <ul> with 4 <li>: party / (blank) / "Standing for {role}" / constituency
    """
    cards = re.findall(
        r'<figure[^>]*data-testid="profile-card"[^>]*>(.*?)</figure>',
        html,
        re.DOTALL,
    )
    out: list[dict] = []
    for card in cards:
        # Profile link (any <a> pointing into /candidates/YYYY/{slug}/)
        link = re.search(
            r'<a[^>]+href="(https?://[^"]*?/candidates/\d+/[^"?#]+)',
            card,
        )
        if not link:
            continue
        href = link.group(1)
        parsed = urllib.parse.urlparse(href)
        clean_path = parsed.path.rstrip('/') + '/'
        full_url = f'https://www.vote.je{clean_path}'
        slug_match = re.match(r'.*/candidates/\d+/([^/]+)/?', clean_path)
        slug = slug_match.group(1) if slug_match else None
        if not slug:
            continue

        # Photo
        photo = re.search(r'<img[^>]+src="([^"]+)"', card)

        # Name lives inside <h5 data-testid="profile-card-heading"> ... <a>NAME</a>
        name = None
        h5 = re.search(
            r'<h5[^>]*data-testid="profile-card-heading"[^>]*>(.*?)</h5>',
            card,
            re.DOTALL,
        )
        if h5:
            inner = h5.group(1)
            a = re.search(r'<a[^>]*>([^<]+)</a>', inner)
            if a:
                name = unescape(a.group(1)).strip()
        if not name:
            name = slug.replace('-', ' ').title()

        # List items: extract all <li> texts in order.
        lis = re.findall(r'<li[^>]*>(.*?)</li>', card, re.DOTALL)
        li_texts = [strip_tags(li).strip() for li in lis]
        li_texts = [t for t in li_texts if t]  # drop blanks

        party = None
        role = None
        constituency = None
        for t in li_texts:
            m = re.match(r'Standing for\s+(.+?)\s*$', t, re.IGNORECASE)
            if m:
                role = m.group(1).strip().rstrip('.').title()
                # Normalise common variants
                if role.lower().startswith('connetable') or role.lower().startswith('connétable'):
                    role = 'Connétable'
                continue
            if party is None:
                party = t
                continue
            if constituency is None:
                constituency = t

        if party and party.lower() in {'none', 'n/a', '-', ''}:
            party = None
        if constituency:
            # vote.je writes "St. Helier" with the period; canonicalise to "St Helier"
            # so it matches our homepage parish picker.
            constituency = re.sub(r'\bSt\.\s*', 'St ', constituency).strip()

        out.append({
            'slug': slug,
            'profile_url': full_url,
            'full_name': name,
            'photo_url': photo.group(1) if photo else None,
            'role': role,
            'constituency': constituency,
            'party': party,  # authoritative from index — overrides profile-page guess
        })
    # De-duplicate by slug (index shows two links per card)
    seen = set()
    deduped = []
    for c in out:
        if c['slug'] in seen:
            continue
        seen.add(c['slug'])
        deduped.append(c)
    return deduped


def extract_between(text: str, starts: list[str], ends: list[str]) -> str:
    """Return the substring strictly between the first matching start anchor
    and the next matching end anchor. Returns '' if anchors not found."""
    lower = text.lower()
    start_idx = -1
    for a in starts:
        i = lower.find(a.lower())
        if i >= 0:
            start_idx = i + len(a)
            break
    if start_idx < 0:
        return ''
    end_idx = len(text)
    for a in ends:
        j = lower.find(a.lower(), start_idx)
        if j >= 0:
            end_idx = j
            break
    return text[start_idx:end_idx].strip()


def extract_manifesto_from_main_content(html: str) -> str:
    """Fallback extractor for candidates whose profile page doesn't include
    the 'No previous convictions' anchor (e.g. candidates who DO have prior
    convictions, where vote.je lists them under a 'Criminal Convictions'
    sidebar instead). The manifesto for every candidate lives inside the
    same WordPress block: <div class="main-content inline-col w-3/4 ...">.
    """
    match = re.search(
        r'<div class="main-content inline-col[^"]*"[^>]*>(.*?)(?=<div id="js-main-content"|<aside|Names of Proposers and Seconders)',
        html,
        re.DOTALL,
    )
    if not match:
        return ''
    inner = match.group(1)
    # Drop YouTube iframes / embeds that sometimes lead the block
    inner = re.sub(r'<iframe.*?</iframe>', '', inner, flags=re.DOTALL)
    inner = re.sub(r'<div class="embed[^"]*"[^>]*>.*?</div>', '', inner, flags=re.DOTALL)
    return strip_tags(inner).strip()


def parse_profile(html: str) -> dict:
    text = strip_tags(html)

    # PRIMARY: extract from the WordPress <div class="main-content inline-col w-3/4 ...">
    # block. This is the column to the right of the sidebar (which contains
    # contact info, convictions, and social links). The structural approach
    # avoids pulling sidebar text like "Connect Website X/Twitter ..." into
    # the manifesto for candidates with multiple linked social profiles.
    manifesto = extract_manifesto_from_main_content(html)

    # FALLBACK: text-anchor approach for any page whose markup doesn't match
    # the expected div structure.
    if not manifesto or len(manifesto.split()) < 30:
        anchored = extract_between(text, MANIFESTO_START_ANCHORS, MANIFESTO_END_ANCHORS)
        if anchored and len(anchored.split()) > len(manifesto.split()):
            manifesto = anchored

    email_match = re.search(
        r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text
    )
    phone_match = re.search(r'(\+?44[\s\d]{8,}|\(?0?1534\)?[\s\d]{6,}|07\d{2}\s?\d{6})', text)

    # Party often appears as "Party: X" or as a labelled metadata block.
    party_match = re.search(r'(?:Party|Affiliation)\s*[:\-]\s*([^\n]+)', text)
    party = party_match.group(1).strip() if party_match else None
    if party and party.lower() in {'none', 'independent', 'n/a', '-'}:
        party = 'Independent'

    return {
        'manifesto_text': manifesto,
        'email': email_match.group(0) if email_match else None,
        'phone': phone_match.group(0).strip() if phone_match else None,
        'party': party,
    }


def ensure_correction_token(existing: str | None) -> str:
    return existing or secrets.token_urlsafe(24)


def upsert_candidate(cur, election_year: int, c: dict, p: dict):
    word_count = len(c['manifesto_text_value'].split()) if c.get('manifesto_text_value') else 0
    status = 'ok'
    if word_count == 0:
        status = 'error'
    elif word_count < LOW_CONTENT_WORDS:
        status = 'low_content'

    cur.execute(
        '''
        INSERT INTO candidates (
            vote_je_slug, profile_url, full_name, canonical_name,
            role, constituency, party, photo_url, email, phone,
            manifesto_text, manifesto_word_count, scrape_status,
            correction_token, election_year, scraped_at
        ) VALUES (
            %(slug)s, %(profile_url)s, %(full_name)s, %(canonical_name)s,
            %(role)s, %(constituency)s, %(party)s, %(photo_url)s, %(email)s, %(phone)s,
            %(manifesto)s, %(words)s, %(status)s,
            %(token)s, %(year)s, NOW()
        )
        -- opted_out_at MUST NOT appear in this SET clause: re-scraping an
        -- opted-out candidate must not silently re-enable them.
        ON CONFLICT (vote_je_slug) DO UPDATE SET
            profile_url = EXCLUDED.profile_url,
            full_name = EXCLUDED.full_name,
            canonical_name = EXCLUDED.canonical_name,
            role = COALESCE(EXCLUDED.role, candidates.role),
            constituency = COALESCE(EXCLUDED.constituency, candidates.constituency),
            party = COALESCE(EXCLUDED.party, candidates.party),
            photo_url = COALESCE(EXCLUDED.photo_url, candidates.photo_url),
            email = COALESCE(EXCLUDED.email, candidates.email),
            phone = COALESCE(EXCLUDED.phone, candidates.phone),
            manifesto_text = EXCLUDED.manifesto_text,
            manifesto_word_count = EXCLUDED.manifesto_word_count,
            scrape_status = EXCLUDED.scrape_status,
            scraped_at = NOW()
        ''',
        {
            'slug': c['slug'],
            'profile_url': c['profile_url'],
            'full_name': c['full_name'],
            'canonical_name': canonicalise_name(c['full_name']),
            'role': c.get('role'),
            'constituency': c.get('constituency'),
            'party': c.get('party') or p.get('party'),
            'photo_url': c.get('photo_url'),
            'email': p.get('email'),
            'phone': p.get('phone'),
            'manifesto': c['manifesto_text_value'],
            'words': word_count,
            'status': status,
            'token': ensure_correction_token(None),
            'year': election_year,
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--election-year', type=int, default=2026)
    parser.add_argument('--limit', type=int, default=0,
                        help='Limit number of profiles scraped (0 = all)')
    args = parser.parse_args()

    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    print(f'Fetching index: {INDEX_URL}')
    index_html = fetch(INDEX_URL)
    if not index_html:
        raise SystemExit('Failed to fetch index page')

    cards = parse_index(index_html)
    print(f'Found {len(cards)} candidate cards')

    if args.limit:
        cards = cards[: args.limit]

    success, low, errors = 0, 0, 0
    for i, c in enumerate(cards):
        html = fetch(c['profile_url'])
        if not html:
            errors += 1
            time.sleep(0.5)
            continue

        profile = parse_profile(html)
        c['manifesto_text_value'] = profile['manifesto_text']

        upsert_candidate(cur, args.election_year, c, profile)

        wc = len(profile['manifesto_text'].split()) if profile['manifesto_text'] else 0
        if wc == 0:
            errors += 1
        elif wc < LOW_CONTENT_WORDS:
            low += 1
        else:
            success += 1

        if (i + 1) % 10 == 0:
            conn.commit()
            print(f'  {i+1}/{len(cards)} (ok={success}, low={low}, err={errors})')

        time.sleep(0.3)  # politeness

    conn.commit()
    cur.close()
    conn.close()
    print(f'\nDone. ok={success}, low_content={low}, errors={errors}')


if __name__ == '__main__':
    main()
