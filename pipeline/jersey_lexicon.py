"""Jersey-specific terminology lexicon + fuzzy-match correction pass.

Whisper-large-v3 mangles Jersey-specific words in many recognisable
ways. Regex substitution (in normalise_local_terms.py) handles the
high-frequency, unambiguous cases, but it doesn't scale — every new
garble requires a new pattern, and we only learn about garbles when
a human spots them.

This module is the long-tail solution: an explicit catalogue of
Jersey-canonical terms paired with a fuzzy matcher (rapidfuzz Jaro-
Winkler, similarity-thresholded) that:
  * detects capitalised phrases in a transcript
  * compares each to the lexicon
  * applies high-confidence corrections automatically (≥ AUTO_SIM)
  * surfaces medium-confidence matches for human review (≥ REVIEW_SIM)

Adding a new canonical term to a category here means EVERY future
garble of that term gets auto-corrected, without writing a regex.

Used by:
  * pipeline/normalise_local_terms.py — runs lexicon pass AFTER regex
    substitutions (regex first, since it's unambiguous; lexicon
    second, for everything regex didn't catch)
  * scripts/fuzzy_audit.py — produces a per-transcript audit report
    of medium-confidence matches the human should review
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

# Confidence thresholds (Levenshtein-based ratio, 0-100). These are
# tuned conservatively: false-positive corrections are MUCH worse than
# missed garbles (a missed garble is just a slightly-ugly transcript,
# but a wrong correction can change candidate attribution or invent
# words they didn't say).
AUTO_SIM = 88.0       # apply this correction automatically
REVIEW_SIM = 80.0     # flag for human review, don't apply
SKIP_BELOW = 75.0     # ignore matches below this — too divergent

# Tokens shorter than this aren't fuzzy-matched (too prone to false
# positives — e.g. "tom" matching "ton").
MIN_TOKEN_LEN = 5

# Substring tokens that disqualify a phrase from fuzzy matching —
# common English filler words. If a candidate phrase contains any of
# these as a separate word, we don't try to match it. This prevents
# nonsense like "I'm Deputy of" → "Deputy" or "Many of" → "Council of
# Ministers". Lexicon entries that legitimately contain these words
# (e.g. "Council of Ministers") still match if the candidate phrase
# also contains them naturally.
DISQUALIFY_TOKENS = {
    'i', "i'm", "i've", 'me', 'my', 'we', 'us', 'our', 'you', 'your',
    'he', 'his', 'she', 'her', 'they', 'their', 'them',
    'this', 'that', 'these', 'those',
    'is', 'are', 'was', 'were', 'has', 'have', 'had', 'be', 'been',
    'will', 'would', 'should', 'could', 'can', 'may', 'might',
    'thank', 'thanks',
}


# ---------------------------------------------------------------------
# Lexicon
# ---------------------------------------------------------------------
# Categorised so we can scope matching (e.g. "St <word>" prefer parishes)
# and so audit reports can group by type.

LEXICON: dict[str, list[str]] = {
    # 12 parishes of Jersey
    'parish': [
        'St Helier', 'St Saviour', 'St Brelade', 'St Clement',
        'St Lawrence', 'Trinity', 'Grouville', 'St Peter', 'St Ouen',
        'St John', 'St Martin', 'St Mary',
    ],
    # Coastal villages, bays, landmarks, historical sites
    'place': [
        'St Aubin', "St Aubin's Bay", 'Gorey', 'Gorey Village',
        'Mont Orgueil', 'Beaumont', 'La Pulente', 'Plémont',
        'Grève de Lecq',  # canonical: accent on the grave 'è'
        'Bouley Bay', 'Bonne Nuit', 'Rozel',
        'La Hougue Bie', "St Catherine's", 'Elizabeth Castle',
        'Archirondel', 'Portelet', 'Ouaisné', 'Noirmont', 'La Moye',
        'Les Quennevais', 'Mont Pellier', 'Five Mile Road',
        "Smuggler's Inn", 'Old Court House',
    ],
    # Government bodies, public-sector organisations, and political
    # parties. Including ALL real organisations prevents the fuzzy
    # matcher from "correcting" one real name into another (e.g.
    # Jersey Sport → Jersey Post).
    'organisation': [
        'States Assembly', 'States Greffe', 'Judicial Greffe',
        'Council of Ministers', 'Honorary Police', 'Reform Jersey',
        'For Jersey',  # Mark Boleat's party — real, not a garble
        'Andium Homes', 'Andium', 'Ports of Jersey', 'Jersey Telecom',
        'Jersey Electricity', 'Jersey Post', 'Jersey Heritage',
        'Jersey Sport',  # sports council — real, not Jersey Post
        'Jersey Water',  # utility — real, not a garble
        'Statistics Jersey', 'Digital Jersey', 'Genuine Jersey',
        'Highlands College', 'Hautlieu', 'Victoria College',
        'Jersey College for Girls', 'Beaulieu', 'De La Salle',
        'Le Rocquier', 'Haute Vallée', 'Hautlieu School',
        "St Mark's", "St Luke's", "St Bernard's",  # real schools/roads
        'Bailiwick Express', 'Jersey Evening Post', 'JEP',
        'Channel Islands', 'Bailiwick of Jersey',
        'Jersey Coast Guard', 'Jersey Police',
    ],
    # Parish + States roles (these double-up with regex in
    # normalise_local_terms but the lexicon helps catch variants)
    'role': [
        'Connétable', 'Centenier', 'Vingtenier', 'Vingtaine',
        'Procureur', 'Procureur du Bien Public', 'Jurat',
        'Bailiff', 'Deputy Bailiff', 'Bailiwick', 'Greffier',
        'Chief Minister', 'Treasury Minister', 'Senator', 'Deputy',
    ],
    # Common Jersey-French surnames Whisper mangles
    'surname': [
        'Le Quesne', 'Le Maistre', 'Le Sueur', 'Le Hégarat',
        'Le Cornu', 'Le Marquand', 'Le Boutillier', 'Le Pavoux',
        'Mézec', 'Crowcroft', 'Renouf', 'Pallot', 'Pinel', 'Ozouf',
        'Jehan', 'Romerill', 'Vibert', 'Pallett', 'de Faye',
        'Le Hégarat', 'Garfield-Bennett', 'Shelswell',
    ],
    # Policy + programme names that come up across hustings.
    # NB on what's NOT here:
    #   * "Long Term Care" vs "Long-Term Care" — both forms appear in
    #     Jersey government documents. Stylistic, not a garble.
    #   * "Our Hospital Project" — candidates routinely call it
    #     "Hospital Project" without the "Our". Rewriting "the
    #     Hospital Project" → "the Our Hospital Project" is wrong
    #     grammar; we keep both forms by not having either canonical.
    'policy': [
        'Bridging Island Plan', 'Government Plan',
        'Skills Development Fund', 'Population Policy',
        'Affordable Housing Gateway', 'Closer to Home',
        'Future Hospital',
    ],
}


# ---------------------------------------------------------------------
# Index — flatten to a name → (canonical, category) mapping
# ---------------------------------------------------------------------
def _build_index() -> dict[str, tuple[str, str]]:
    """Return {lowercase_term: (canonical_form, category)}."""
    idx: dict[str, tuple[str, str]] = {}
    for category, terms in LEXICON.items():
        for term in terms:
            idx[term.lower()] = (term, category)
    return idx


INDEX = _build_index()
CANONICAL_LOWERS = list(INDEX.keys())


# ---------------------------------------------------------------------
# Matchers
# ---------------------------------------------------------------------

@dataclass
class FuzzyMatch:
    original: str           # the substring as it appears in the transcript
    canonical: str          # the lexicon entry it matched
    category: str           # 'parish', 'place', etc.
    score: float            # 0-100 Jaro-Winkler similarity
    decision: str           # 'auto' | 'review' | 'skip'
    span: tuple[int, int]   # char positions in the original text


def _decision(score: float) -> str:
    if score >= AUTO_SIM:
        return 'auto'
    if score >= REVIEW_SIM:
        return 'review'
    return 'skip'


def _is_derivable_form(phrase: str, canonical: str) -> bool:
    """Is `phrase` a legitimate inflection/possessive/plural of `canonical`?
    These shouldn't be 'corrected' — they ARE correct.

    Examples:
      St Helier's      ← possessive of St Helier
      Senators         ← plural of Senator
      Connétables      ← plural of Connétable
      Connétable's     ← possessive of Connétable
    """
    p, c = phrase.lower(), canonical.lower()
    # Possessive
    if p == c + "'s" or p == c + 's':
        return True
    # Plural (simple s; doesn't handle ies/oes etc. but those don't
    # occur in our lexicon anyway)
    if p == c + 's':
        return True
    # Substring with extra suffix words (e.g. "St Helier North"
    # contains "St Helier" — the suffix MIGHT make it more specific
    # rather than a garble of the shorter form)
    if c in p:
        return True
    return False


def _has_disqualifying_token(phrase: str) -> bool:
    """Phrase contains a common English filler that suggests it's not
    a Jersey-specific term — skip it."""
    tokens = re.split(r"\s+", phrase.lower())
    return any(t in DISQUALIFY_TOKENS for t in tokens)


def find_matches(text: str, roster_names: set[str] | None = None) -> list[FuzzyMatch]:
    """Scan `text` for capitalised phrases (1-3 words) that fuzzy-match
    a lexicon entry. Returns matches sorted by start position.

    Filters that prevent false positives:
      * Skip phrases already exact-matching a canonical form
      * Skip derivable forms (possessives, plurals, prefixed variants)
      * Skip phrases containing English filler words (I, you, the, etc.)
      * Skip phrases that contain candidate roster names (the moderator
        anchor / per-segment fingerprint pipeline handles those, not
        the lexicon)
      * Use plain `ratio` (Levenshtein) instead of WRatio, which gave
        too-confident scores for unrelated phrases that shared common
        substrings

    Pass `roster_names` (a set of canonical candidate names from this
    event's metadata.yaml) to suppress matches that include any of
    those — prevents "Mary Le Hegarat" → "St Mary".
    """
    from rapidfuzz import fuzz, process

    roster_lower = {n.lower() for n in (roster_names or set())}
    # Also build a set of every word in any candidate name, to filter
    # out matches that include a candidate's first/last name.
    roster_tokens = set()
    for n in roster_lower:
        for tok in n.split():
            if len(tok) >= 3:
                roster_tokens.add(tok)

    # Capture sequences of 1-3 capitalised tokens. Handles French-style
    # prefixes ("Le ", "La ", "Du ", "De ") and apostrophes within tokens.
    phrase_re = re.compile(
        r"\b"
        r"((?:[A-Z][a-zA-ZéàèùâêîôûÉÀÈÙ'-]+)"
        r"(?:\s+(?:[A-Z][a-zA-ZéàèùâêîôûÉÀÈÙ'-]+|de|du|le|la|of|the))"
        r"{0,2})"
        r"\b"
    )

    matches: list[FuzzyMatch] = []
    seen_spans: set[tuple[int, int]] = set()

    for m in phrase_re.finditer(text):
        phrase = m.group(1).strip()
        span = m.span(1)
        if span in seen_spans:
            continue
        seen_spans.add(span)

        # Exact lexicon match → already correct
        if phrase.lower() in INDEX:
            continue
        # Too short
        if len(phrase.replace(' ', '')) < MIN_TOKEN_LEN:
            continue
        # Contains an English filler word
        if _has_disqualifying_token(phrase):
            continue
        # Contains a candidate roster token
        phrase_lower_tokens = set(phrase.lower().split())
        if phrase_lower_tokens & roster_tokens:
            continue

        # Plain Levenshtein ratio — stricter than WRatio. We want
        # garbles to look like the canonical (high overlap) but
        # different names to NOT pass the threshold.
        best = process.extractOne(
            phrase.lower(),
            CANONICAL_LOWERS,
            scorer=fuzz.ratio,
            score_cutoff=SKIP_BELOW,
        )
        if not best:
            continue
        canonical_lower, score, _ = best
        canonical, category = INDEX[canonical_lower]

        # Derivable forms (possessive, plural, more-specific suffix) —
        # these are NOT garbles, they're valid inflections.
        if _is_derivable_form(phrase, canonical):
            continue
        # Case-only difference
        if phrase.lower() == canonical.lower():
            continue

        # Require the LENGTHS to be similar too. "Le Quesne" (8 chars)
        # vs "Le Maistre" (10) wouldn't be a garble of each other even
        # though they share "Le ". Reject if length differs by > 35%.
        len_ratio = min(len(phrase), len(canonical)) / max(len(phrase), len(canonical))
        if len_ratio < 0.65:
            continue

        matches.append(FuzzyMatch(
            original=phrase,
            canonical=canonical,
            category=category,
            score=score,
            decision=_decision(score),
            span=span,
        ))

    return matches


def apply_corrections(text: str, matches: list[FuzzyMatch]) -> tuple[str, int]:
    """Apply only `auto`-decision matches to text. Returns (new_text, n_applied).

    Applies from end to start so spans don't shift mid-edit.
    """
    auto = [m for m in matches if m.decision == 'auto']
    auto.sort(key=lambda m: m.span[0], reverse=True)
    n = 0
    for m in auto:
        start, end = m.span
        text = text[:start] + m.canonical + text[end:]
        n += 1
    return text, n


def audit_report(matches: list[FuzzyMatch]) -> str:
    """Format matches as a human-readable report for review."""
    by_decision: dict[str, list[FuzzyMatch]] = defaultdict(list)
    for m in matches:
        by_decision[m.decision].append(m)
    lines: list[str] = []
    for decision in ('auto', 'review', 'skip'):
        items = by_decision.get(decision, [])
        if not items:
            continue
        lines.append(f'\n=== {decision.upper()} ({len(items)}) ===')
        for m in items:
            lines.append(
                f'  [{m.score:5.1f}] {m.original!r:30s} → {m.canonical!r}  ({m.category})'
            )
    return '\n'.join(lines)
