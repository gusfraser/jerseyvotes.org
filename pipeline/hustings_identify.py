"""
Map anonymous SPEAKER_00..SPEAKER_N labels from diarised_segments.json to
real candidate names, and emit transcript.md in the same shape as the
hand-cleaned transcripts (so ingest_hustings.py handles auto and human
output through one path).

Two complementary strategies are run together:

1. **Moderator-intro anchor (primary).** Hustings open with the moderator
   reading each candidate's name in alphabetical order before they speak.
   We regex the transcript for the moderator's introductions and anchor
   "the next new speaker label after this name was mentioned" to that
   candidate. Cheap, robust when intros are formulaic.

2. **Voice fingerprinting (verification).** If
   pipeline/hustings/_voice_embeddings/<vote-je-slug>.npy exists for a
   candidate (built up across events), we compare each anonymous
   speaker's mean embedding against the references via cosine similarity.
   Matches above SIM_THRESHOLD reinforce or override Strategy 1.

The resulting transcript.md is written for review. Speaker lines use the
**[mm:ss] Name:** Style-B format (the diarisation gives us timestamps,
so why not preserve them). The human runs `git diff` against the
generated file and corrects any mis-attributions before committing.
Then ingest_hustings.py + classify_hustings.py do the rest.

Run:
  python pipeline/hustings_identify.py --slug sthelier-connetable-2026
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import yaml

HUSTINGS_DIR = Path(__file__).resolve().parent / 'hustings'
EMBEDDINGS_DIR = HUSTINGS_DIR / '_voice_embeddings'

SIM_THRESHOLD = 0.5      # cosine similarity threshold for voice match
INTRO_LOOKAHEAD_S = 6.0  # how far after a name-mention to claim the next speaker


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = a / (np.linalg.norm(a) + 1e-12)
    b = b / (np.linalg.norm(b) + 1e-12)
    return float(np.dot(a, b))


def fmt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m:02d}:{s:02d}'


def _fuzzy_word_in(text: str, target: str) -> bool:
    """True if any word in `text` fuzzy-matches `target`. See
    `_fuzzy_word_pos` for the matching rules."""
    return _fuzzy_word_pos(text, target) is not None


def _fuzzy_word_pos(text: str, target: str) -> int | None:
    """Return the start character position of the EARLIEST word in
    `text` that fuzzy-matches `target` (or None if no match).

    Edit tolerance scales with target length to balance false positives
    against STT-garble recovery:
      len <= 4  → exact match only (short first names collide with
                  common words: "Tom" vs "to", "Sam" vs "so", "Ian" vs
                  "in", "Roy" vs "for", etc.)
      len 5-7   → 1 edit  ("Aliga" vs "Eliga", "Warr" vs "War")
      len >= 8  → 2 edits ("Boliatt" vs "Boleat" — common with Whisper
                  doubling/splitting consonants in unusual surnames)"""
    target_l = target.lower()
    target_len = len(target_l)
    if target_len <= 4:
        effective_max = 0
    elif target_len == 5:
        effective_max = 1
    else:  # 6+
        effective_max = 2
    best: int | None = None
    for m in re.finditer(r"\b[A-Za-z']{2,}\b", text):
        word = m.group()
        w = word.lower()
        if abs(len(w) - target_len) > effective_max:
            continue
        if _edit_distance(w, target_l) <= effective_max:
            if best is None or m.start() < best:
                best = m.start()
    return best


def _matches_intro(candidate_name: str, w1: str, w2: str) -> bool:
    """True if the two-word `(w1, w2)` capture from a self-introduction
    matches `candidate_name`. Handles:
      "Steve Luce"   — first+last exact
      "Mr Luce"      — just the surname (after "I'm Mr X" or similar)
      "Martin Eliga" — last name with 1 STT edit ("Aliga" → "Eliga")
    Refuses fuzzy matches when only one word is captured (too risky)."""
    parts = candidate_name.lower().split()
    if not parts:
        return False
    first = parts[0]
    last = parts[-1]
    if w1 and w2:
        if w1 == first and _name_close(w2, last):
            return True
        if w2 == last and _name_close(w1, first):
            return True
        if w1 == last:
            return True
        return False
    if w1 and (w1 == first or w1 == last):
        return True
    return False


def _name_close(observed: str, target: str) -> bool:
    """Tolerant equality for the SURNAME check inside self-intros,
    where the first name has already exactly matched (strong signal).
    Up to 2 edits for any surname length ≥ 5 — catches "Gawst" vs
    "Gorst", "Mezek" vs "Mézec", "Eliga" vs "Aliga"."""
    if observed == target:
        return True
    L = len(target)
    if L <= 4:
        return False
    max_edits = 2
    if abs(len(observed) - L) > max_edits:
        return False
    return _edit_distance(observed, target) <= max_edits


def _edit_distance(a: str, b: str) -> int:
    """Iterative Levenshtein distance — small strings (names), so
    O(len(a)*len(b)) is fine."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # row-by-row DP
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(
                cur[-1] + 1,             # insertion
                prev[j] + 1,             # deletion
                prev[j - 1] + cost,      # substitution
            ))
        prev = cur
    return prev[-1]


MIN_CANDIDATE_TURN_SECONDS = 30.0


def moderator_anchor(
    segments: list[dict],
    candidate_names: list[str],
    moderator_names: list[str],
) -> dict[str, str]:
    """Two-pass chronological alignment.

    Pass 1: scan moderator turns, recording the first time each candidate
    is mentioned (anywhere in any moderator turn text, multiple matches
    per turn allowed — not break-on-first).

    Pass 2: sort mentions by time. For each mention, claim the next
    unclaimed non-moderator speaker label whose longest-turn duration is
    >= MIN_CANDIDATE_TURN_SECONDS — i.e. a speaker who actually delivered
    a candidate-sized speech, not a 2-second audience interjection.

    This handles the common pattern where the moderator introduces each
    candidate just before they speak, AND the pattern where the moderator
    lists everyone in one alphabetical roll-call at the top: in the
    second pattern, mentions are clustered in time but the speakers come
    one after another, and we still get the right alignment by order."""
    speaker_first_seen: dict[str, float] = {}
    speaker_total_time: dict[str, float] = {}
    for s in segments:
        sp = s['speaker_label']
        speaker_first_seen.setdefault(sp, s['start'])
        speaker_total_time[sp] = speaker_total_time.get(sp, 0) + (s['end'] - s['start'])
    if not speaker_first_seen:
        return {}

    turn_counts: dict[str, int] = {}
    for s in segments:
        turn_counts[s['speaker_label']] = turn_counts.get(s['speaker_label'], 0) + 1
    earliest = min(speaker_first_seen, key=speaker_first_seen.get)
    most_turns = max(turn_counts, key=turn_counts.get)
    most_talk = max(speaker_total_time, key=speaker_total_time.get)

    # Preferred strategy: if metadata names a known moderator and they
    # self-introduce ("I'm Cathy Kear", "I am Hannah Shelswell"), the
    # speaker_label of that self-intro IS the moderator. This is much
    # more reliable than the "talks the most" heuristic — in single-
    # candidate events, the candidate actually talks more than the
    # moderator, so the heuristic swaps them.
    moderator_label: str | None = None
    if moderator_names:
        for mod_name in moderator_names:
            parts = mod_name.strip().split()
            if not parts:
                continue
            # Match "I'm <first> <last>" or "I am <first> <last>" or
            # "I'm <last>" / "I am <last>". We're tolerant on the
            # surname (fuzzy match against STT garbles like
            # "Cathy Keer", "Hannah Shellswell").
            first, last = parts[0], parts[-1]
            for s in segments:
                if mod_name.lower() in s['text'].lower():
                    moderator_label = s['speaker_label']
                    break
                # Fuzzy: search for "I'm" / "I am" near the surname
                m = re.search(
                    rf"\bI'?m\s+(?:[A-Z][a-zA-Z'\-]+\s+)?({re.escape(last[:5])}\w*)\b",
                    s['text'], re.IGNORECASE,
                )
                if m:
                    moderator_label = s['speaker_label']
                    break
            if moderator_label:
                break
    if moderator_label is None:
        # Fall back to the "most turns + earliest" heuristic when we
        # couldn't pin down a self-introducing moderator. Works well for
        # large-panel events where the moderator dominates airtime
        # naturally.
        moderator_label = (
            most_turns if (most_turns == earliest or most_turns == most_talk) else earliest
        )

    assignments: dict[str, str] = {moderator_label: '(Moderator)'}

    # Longest single turn per speaker label — used to gate "is this a
    # candidate-sized speaker?" vs "is this a brief interjection?"
    longest_turn: dict[str, float] = {}
    for s in segments:
        sp = s['speaker_label']
        dur = s['end'] - s['start']
        if dur > longest_turn.get(sp, 0):
            longest_turn[sp] = dur

    # Tokens to fuzzy-match per candidate: first AND last name (either may
    # survive an STT garble).
    cand_tokens: list[tuple[str, list[str]]] = []
    for name in candidate_names:
        parts = name.strip().split()
        if not parts:
            continue
        first = parts[0]
        last = parts[-1]
        tokens = [t for t in {first, last} if len(t) >= 3]
        cand_tokens.append((name, tokens))

    # PASS 1 — for each candidate, find the first (turn_start, position
    # in turn text) where they're mentioned by the moderator. The
    # position-in-text tiebreaker is what lets us handle a roll-call
    # ("in alphabetical order: A, B, C, D"): all four mentions share a
    # turn_start, but their character positions differ, so they queue up
    # in the order the moderator actually said them.
    first_mention: dict[str, tuple[float, int]] = {}
    for s in segments:
        if s['speaker_label'] != moderator_label:
            continue
        for name, tokens in cand_tokens:
            if name in first_mention:
                continue
            best_pos = None
            for t in tokens:
                p = _fuzzy_word_pos(s['text'], t)
                if p is not None and (best_pos is None or p < best_pos):
                    best_pos = p
            if best_pos is not None:
                first_mention[name] = (float(s['start']), best_pos)

    # PASS 1b — self-introductions ("My name is X Y", "I'm X Y").
    # The capture is anchored to the FIRST one or two words immediately
    # after the cue, not a broad window — otherwise "Martin" picks up
    # "Martins" (the parish) elsewhere in the speech and steals an
    # attribution. The intro check is also case-aware (Whisper
    # capitalises proper nouns reasonably well) so "St Martins" doesn't
    # leak through as a candidate first-name match.
    #
    # We aggregate per-speaker text first because Whisper sometimes
    # splits "My name's" from the actual name across two segments.
    intro_pat = re.compile(
        r"\b(?:my\s+name(?:'s|\s+is)|i'?\s*a?m|i\s+am)\s+"
        r"([A-Za-z']+)(?:[\s,.\-]+([A-Za-z']+))?",
        re.IGNORECASE,
    )
    speaker_aggregated_text: dict[str, str] = {}
    for s in segments:
        sp = s['speaker_label']
        if sp == moderator_label:
            continue
        if longest_turn.get(sp, 0) < MIN_CANDIDATE_TURN_SECONDS:
            continue
        speaker_aggregated_text.setdefault(sp, '')
        speaker_aggregated_text[sp] += ' ' + s['text']

    self_intros: dict[str, str] = {}  # speaker_label → candidate name
    for sp, text in speaker_aggregated_text.items():
        for m in intro_pat.finditer(text):
            w1 = (m.group(1) or '').lower()
            w2 = (m.group(2) or '').lower()
            for name, _tokens in cand_tokens:
                if _matches_intro(name, w1, w2):
                    self_intros[sp] = name
                    break
            if sp in self_intros:
                break

    # PASS 2 — sort by (turn_start, position_in_text) and claim the next
    # eligible speaker label for each candidate in that order.
    mentions_in_order = sorted(
        first_mention.items(),
        key=lambda kv: kv[1],  # (turn_start, position_in_text) tuple
    )
    claimed_labels = {moderator_label}

    # Self-intros are STRONGER signal than moderator anchors — apply
    # them first and lock both the speaker label and the candidate name.
    claimed_names: set[str] = set()
    for sp, name in self_intros.items():
        if name in claimed_names:
            continue
        assignments[sp] = name
        claimed_labels.add(sp)
        claimed_names.add(name)

    for name, (t_mention, _pos) in mentions_in_order:
        if name in claimed_names:
            continue
        # Find the next speaker turn that:
        #   * starts at or after this mention,
        #   * isn't the moderator,
        #   * has a speaker label not yet claimed,
        #   * and whose owning speaker has a "candidate-sized" longest turn.
        for s in segments:
            if s['start'] < t_mention:
                continue
            sp = s['speaker_label']
            if sp in claimed_labels:
                continue
            if longest_turn.get(sp, 0) < MIN_CANDIDATE_TURN_SECONDS:
                continue
            assignments[sp] = name
            claimed_labels.add(sp)
            claimed_names.add(name)
            break

    # PASS 3 — audience detection. Speaker labels that remain unmapped
    # AND look like brief audience interventions (one-or-a-few turns,
    # each long enough to be a real utterance but short overall) get
    # tagged as `<SPEAKER_NN> (Audience)`. Everything below the floor
    # — single-word interjections, mis-diarised pre-speech fragments,
    # overlapping voices — gets dropped by render_transcript_md.
    speaker_total: dict[str, float] = {}
    for s in segments:
        sp = s['speaker_label']
        speaker_total[sp] = speaker_total.get(sp, 0) + (s['end'] - s['start'])

    for sp, total in speaker_total.items():
        if sp in claimed_labels:
            continue
        n_turns = turn_counts.get(sp, 0)
        if n_turns == 0:
            continue
        avg_turn = total / n_turns
        longest = longest_turn.get(sp, 0)
        # Audience question patterns: at least one turn ≥ 6 seconds
        # (long enough to actually ask something), with an average turn
        # ≥ 4 seconds (filters out one-word fragments), and total time
        # ≤ 90 seconds (audience members ask, they don't speechify).
        if longest >= 6.0 and avg_turn >= 4.0 and total <= 90.0:
            assignments[sp] = f'<{sp}> (Audience)'
            claimed_labels.add(sp)

    return assignments


def build_event_local_refs(
    segments: list[dict],
    anchor_map: dict[str, str],
    fp_map: dict[str, tuple[str, float]],
    segment_embeddings_path: Path,
    audience_label_substr: str = '(Audience)',
    min_library_sim: float = 0.45,
) -> dict[str, np.ndarray]:
    """Build per-event voice references from each candidate's OPENING
    speech in this very recording. The acoustic conditions of the
    opening speech (same mic, same venue, same distance to capture) are
    identical to the rest of the event, so cosine similarity between
    these event-local references and the rest of the segments is much
    more reliable than against the studio-recorded library.

    HOWEVER — moderator-anchor can mis-attribute a cluster, and if we
    blindly trust it the event-local reference will be the WRONG voice,
    causing per-segment matching to "confidently" propagate that error
    to every other segment in that cluster. To prevent that feedback
    loop, we only enrol a cluster when moderator-anchor and library
    cluster fingerprint AGREE on the candidate — that way at least two
    independent signals point at the same person before we trust the
    enrolment.

    For each cluster where they agree, take the longest segment
    (≈ opening speech) and use its embedding as the event-local
    reference for that candidate.

    Returns {candidate_name: embedding_array}. Empty when no segment
    embeddings exist or no clusters cleared the cross-check."""
    if not segment_embeddings_path.exists() or not anchor_map:
        return {}
    data = np.load(segment_embeddings_path)
    seg_keys = {int(k): k for k in data.files}

    # Decide which candidate identity to enrol each cluster as. Three
    # cases:
    #   (a) Anchor and library AGREE → enrol as that candidate.
    #   (b) They DISAGREE but library is highly confident (>= 0.7) →
    #       enrol as library's pick. The acoustic gap means studio→
    #       hustings cosine sims rarely top 0.85, so 0.7 is already a
    #       strong signal that this cluster is genuinely that person
    #       and the moderator-anchor was confused.
    #   (c) They DISAGREE and library is unconfident → skip enrolment;
    #       fall back to library refs at per-segment time.
    trusted: dict[str, str] = {}   # speaker_label → candidate_name
    skipped: list[tuple[str, str, str, float, str]] = []
    overrides: list[tuple[str, str, str, float]] = []
    HIGH_LIB_SIM = 0.70

    for sp_label, anchor_cand in anchor_map.items():
        if not anchor_cand or audience_label_substr in anchor_cand:
            continue
        if anchor_cand == '(Moderator)':
            continue
        lib_match = fp_map.get(sp_label)
        if lib_match is None:
            skipped.append((sp_label, anchor_cand, '(no library match)', 0.0, 'no lib match'))
            continue
        lib_cand, lib_sim = lib_match
        if lib_cand == anchor_cand:
            if lib_sim < min_library_sim:
                skipped.append((sp_label, anchor_cand, lib_cand, lib_sim, 'lib confirms but low sim'))
                continue
            trusted[sp_label] = anchor_cand
        else:
            # Anchor and library disagree. Prefer library when it's highly
            # confident; otherwise abstain (per-segment library fallback
            # will still cover this cluster).
            if lib_sim >= HIGH_LIB_SIM:
                overrides.append((sp_label, anchor_cand, lib_cand, lib_sim))
                trusted[sp_label] = lib_cand
            else:
                skipped.append((sp_label, anchor_cand, lib_cand, lib_sim, 'disagree, lib not confident'))

    if overrides:
        print('  event-local: library overrides moderator-anchor for high-confidence clusters:')
        for sp, anc, lib, sim in overrides:
            print(f'    {sp}: anchor={anc!r} → library={lib!r} (sim={sim:.2f}) [used for enrolment]')
    if skipped:
        print('  event-local: skipped clusters:')
        for sp, anc, lib, sim, reason in skipped:
            print(f'    {sp}: anchor={anc!r} lib={lib!r} sim={sim:.2f} ({reason})')

    # For each trusted cluster, find the longest segment with that
    # speaker_label that has a stored embedding.
    cand_to_best: dict[str, tuple[int, float]] = {}   # name → (seg_idx, duration)
    for i, s in enumerate(segments):
        sp_label = s['speaker_label']
        cand = trusted.get(sp_label)
        if not cand:
            continue
        if i not in seg_keys:
            continue
        dur = float(s['end']) - float(s['start'])
        prev = cand_to_best.get(cand)
        if prev is None or dur > prev[1]:
            cand_to_best[cand] = (i, dur)

    refs: dict[str, np.ndarray] = {}
    for cand, (idx, _) in cand_to_best.items():
        refs[cand] = np.asarray(data[seg_keys[idx]]).squeeze()
    return refs


def per_segment_voice_fingerprint(
    segment_embeddings_path: Path,
    candidate_names: dict[str, str],
    min_sim: float = 0.55,
    event_local_refs: dict[str, np.ndarray] | None = None,
) -> dict[int, tuple[str, float]]:
    """Match each individual diarised segment to its best candidate via
    voice fingerprint. Returns {segment_index: (candidate_name, sim)}
    for confident matches (>= min_sim).

    Reference sources (used TOGETHER, not as fallback chain):
      1. event_local_refs — embeddings from THIS event's own opening
         speeches. Acoustically matched (same mic/venue/distance), so
         cosine scores are much higher when the voice matches. But the
         label depends on moderator-anchor / library being correct —
         if those were wrong about the cluster's identity, the
         event-local ref carries that mistake forward.
      2. The library at EMBEDDINGS_DIR/<slug>.npy — averages of pyannote
         embeddings from candidate intro videos on vote.je. Studio
         acoustics lower the cosine sims, but the identity is
         GUARANTEED (the file is named for the candidate's vote.je
         slug, recorded by them).

    Each candidate's score for a segment is `max(sim_to_event_local,
    sim_to_library)` — i.e. whichever ref matched best. That way:
      * The acoustic match of event-local gives a strong positive
        signal when the cluster was identified correctly.
      * The library catches the case where event-local was enrolled
        with the wrong label — the candidate's library ref will fire
        on their actual voice, beating a mislabelled event-local.

    Catches mid-cluster speaker changes when pyannote merges two real
    speakers into one label: each individual segment's voiceprint still
    cleanly matches its actual speaker."""
    if not segment_embeddings_path.exists():
        return {}
    data = np.load(segment_embeddings_path)
    seg_keys = list(data.files)

    # Build per-candidate ref list: each candidate may have 1-2
    # embeddings (event-local + library). Both are scored independently;
    # the candidate's score for a segment is the MAX across their refs.
    refs_by_cand: dict[str, list[tuple[str, np.ndarray]]] = {}
    for cand, emb in (event_local_refs or {}).items():
        refs_by_cand.setdefault(cand, []).append(('event-local', emb))
    library_used = 0
    for cand_name, slug in candidate_names.items():
        ref_path = EMBEDDINGS_DIR / f'{slug}.npy'
        if ref_path.exists():
            refs_by_cand.setdefault(cand_name, []).append(('library', np.load(ref_path)))
            library_used += 1
    if not refs_by_cand:
        return {}
    n_both = sum(1 for refs in refs_by_cand.values() if len(refs) >= 2)
    print(f'  per-segment refs: {len(event_local_refs or {})} event-local, '
          f'{library_used} library, {n_both} candidates have BOTH '
          f'({len(refs_by_cand)} candidates total)')

    matches: dict[int, tuple[str, float]] = {}
    for key in seg_keys:
        idx = int(key)
        seg_emb = data[key]
        best_name = None
        best_sim = 0.0
        for cand_name, refs in refs_by_cand.items():
            # Best score across this candidate's refs (max so the better
            # of acoustic-match vs identity-guaranteed wins).
            cand_sim = max(cosine(seg_emb, e) for _, e in refs)
            if cand_sim > best_sim:
                best_sim = cand_sim
                best_name = cand_name
        if best_name and best_sim >= min_sim:
            matches[idx] = (best_name, best_sim)
    return matches


def voice_fingerprint(
    embeddings_path: Path,
    candidate_names: dict[str, str],   # name → vote_je_slug
) -> dict[str, tuple[str, float]]:
    """For each SPEAKER_NN in this event, find the best-matching enrolled
    candidate. Returns {speaker_label: (candidate_name, similarity)} for
    matches above SIM_THRESHOLD."""
    if not embeddings_path.exists():
        return {}

    data = np.load(embeddings_path)
    speakers: dict[str, np.ndarray] = {k: data[k] for k in data.files}

    matches: dict[str, tuple[str, float]] = {}
    refs: dict[str, np.ndarray] = {}
    for cand_name, slug in candidate_names.items():
        ref_path = EMBEDDINGS_DIR / f'{slug}.npy'
        if ref_path.exists():
            refs[cand_name] = np.load(ref_path)

    if not refs:
        return {}

    for sp_label, sp_emb in speakers.items():
        best_name = None
        best_sim = 0.0
        for cand_name, ref_emb in refs.items():
            sim = cosine(sp_emb, ref_emb)
            if sim > best_sim:
                best_sim = sim
                best_name = cand_name
        if best_name and best_sim >= SIM_THRESHOLD:
            matches[sp_label] = (best_name, best_sim)

    return matches


def write_voice_references(
    embeddings_path: Path,
    assignments: dict[str, str],
    candidate_names: dict[str, str],
) -> None:
    """For each SPEAKER_NN we just confidently mapped to a candidate, save
    that speaker's mean embedding into the per-candidate enrollment
    library so future events can use voice fingerprinting."""
    if not embeddings_path.exists():
        return
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    data = np.load(embeddings_path)
    for sp_label, ident in assignments.items():
        if ident == '(Moderator)' or ident.startswith('('):
            continue
        slug = candidate_names.get(ident)
        if not slug or sp_label not in data.files:
            continue
        ref_path = EMBEDDINGS_DIR / f'{slug}.npy'
        if ref_path.exists():
            # Average with the existing reference to make the library
            # more robust over time.
            existing = np.load(ref_path)
            new = (existing + data[sp_label]) / 2
        else:
            new = data[sp_label]
        np.save(ref_path, new)


def render_transcript_md(
    segments: list[dict],
    assignments: dict[str, str],
    metadata: dict,
    per_seg_overrides: dict[int, str] | None = None,
) -> str:
    """Emit a transcript.md. NO segments are dropped — every diarised
    turn ends up in the output:

      * Speakers we mapped to a candidate or moderator → labelled with
        that name (e.g. `Steve Luce:`, `(Moderator):`).
      * Speakers we tagged as audience → labelled `<SPEAKER_NN> (Audience):`.
      * Anything else (typically misdiarised fragments, brief
        interjections, or candidates we couldn't ID) → labelled
        `<SPEAKER_NN>:` so the parser stores them with segment_type
        =`unknown_speaker` and candidate_id NULL.

    A human reviewer can then add a `speaker_overrides:` map to
    metadata.yaml — e.g.

        speaker_overrides:
          SPEAKER_07: Guy de Faye

    — and re-running identify will pick up the override on the next
    pass. The underlying words stay verbatim regardless."""
    title = metadata.get('title') or metadata['event_slug']
    out = [f'## {title}', '']
    counts = {'mapped': 0, 'audience': 0, 'unknown': 0, 'per_seg_override': 0}
    overrides = per_seg_overrides or {}

    # Resolve identities up front so we can detect where opening speeches
    # end and audience Q&A begins. The transition is "first segment where
    # the speaker is tagged (Audience)" — every senatorial event we've
    # observed has the moderator close opening speeches with a line like
    # "That's the speeches, now we'll open up for questions" before the
    # first audience member is heard.
    identified: list[str] = []
    for i, s in enumerate(segments):
        override = overrides.get(i)
        if override:
            ident = override
        else:
            ident = assignments.get(s['speaker_label'])
            if ident is None:
                ident = f'<{s["speaker_label"]}>'
        identified.append(ident)

    first_audience_idx = next(
        (i for i, ident in enumerate(identified) if '(Audience)' in ident),
        None,
    )

    # ## Opening Speeches header — matches SECTION_HEADERS['opening']
    # variants in ingest_hustings.py so the parser flips into 'opening'
    # mode and tags subsequent candidate segments as opening_speech.
    out.append('## Opening Speeches')
    out.append('')

    for i, s in enumerate(segments):
        # Insert the Q&A section header right before the first audience
        # speaker — matches SECTION_HEADERS['questions'] in
        # ingest_hustings.py.
        if first_audience_idx is not None and i == first_audience_idx:
            out.append('## Audience Q&A')
            out.append('')

        ident = identified[i]
        if overrides.get(i):
            counts['mapped'] += 1
            counts['per_seg_override'] += 1
        elif '<SPEAKER_' in ident and '(Audience)' not in ident:
            counts['unknown'] += 1
        elif '(Audience)' in ident:
            counts['audience'] += 1
        else:
            counts['mapped'] += 1
        ts = fmt_timestamp(s['start'])
        out.append(f'**[{ts}] {ident}:**')
        out.append(s['text'])
        out.append('')

    out.append('')
    out.append('---')
    out.append('')
    out.append(
        f'*Generated by pipeline/hustings_identify.py. '
        f'{counts["mapped"]} mapped'
        + (f' ({counts["per_seg_override"]} via per-segment fingerprint)' if counts['per_seg_override'] else '')
        + f', {counts["audience"]} audience, '
        f'{counts["unknown"]} unidentified speaker segment(s). '
        f"Add a `speaker_overrides:` map in metadata.yaml to relabel "
        f"unidentified speakers, then re-run identify + ingest.*"
    )
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(
        description='Map anonymous speaker labels to candidate names and '
                    'emit transcript.md.',
    )
    parser.add_argument('--slug', required=True, help='Event slug')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing transcript.md')
    parser.add_argument('--no-fingerprint', action='store_true',
                        help='Skip voice-fingerprint pass; moderator-anchor only')
    parser.add_argument('--no-update-references', action='store_true',
                        help="Don't write back into the voice-embedding library")
    args = parser.parse_args()

    folder = HUSTINGS_DIR / args.slug
    diarised_path = folder / 'diarised_segments.json'
    meta_path = folder / 'metadata.yaml'
    embeddings_path = folder / 'speaker_embeddings.npz'
    out_path = folder / 'transcript.md'

    if not diarised_path.exists():
        sys.exit(f'No diarised_segments.json in {folder} — run '
                 'hustings_diarise.py first.')
    if not meta_path.exists():
        sys.exit(f'No metadata.yaml in {folder}.')
    if out_path.exists() and not args.force:
        sys.exit(f'transcript.md exists in {folder} (use --force to overwrite).')

    segments = json.loads(diarised_path.read_text())
    metadata = yaml.safe_load(meta_path.read_text()) or {}
    candidates: dict[str, str] = {
        c['name']: c['vote_je_slug']
        for c in (metadata.get('candidates') or [])
        if c.get('name') and c.get('vote_je_slug')
    }
    moderator_names = list(metadata.get('moderator_names') or [])

    # Strategy 1: moderator-intro anchor
    anchor_map = moderator_anchor(
        segments,
        candidate_names=list(candidates.keys()),
        moderator_names=moderator_names,
    )
    print(f'moderator-anchor mapped {len(anchor_map)} speakers: '
          f'{ {k: v for k, v in anchor_map.items()} }')

    # Strategy 2: voice fingerprinting
    fp_map: dict[str, tuple[str, float]] = {}
    if not args.no_fingerprint:
        fp_map = voice_fingerprint(embeddings_path, candidates)
        print(f'fingerprint mapped {len(fp_map)} speakers: '
              f'{ {k: (n, round(s, 3)) for k, (n, s) in fp_map.items()} }')

    # Combine: anchor wins unless fingerprint disagrees with high confidence.
    assignments = dict(anchor_map)
    for sp_label, (cand_name, sim) in fp_map.items():
        existing = assignments.get(sp_label)
        if existing is None:
            assignments[sp_label] = cand_name
        elif existing != cand_name and sim > 0.7:
            print(f'  fingerprint overrides anchor for {sp_label}: '
                  f'{existing} -> {cand_name} (sim={sim:.3f})')
            assignments[sp_label] = cand_name

    # Strategy 3 (always wins): manual overrides from metadata.yaml.
    # Format:
    #   speaker_overrides:
    #     SPEAKER_07: Guy de Faye          # candidate full name
    #     SPEAKER_18: '(Audience)'         # explicit audience tag
    #     SPEAKER_16: drop                 # remove this label's segments
    overrides = metadata.get('speaker_overrides') or {}
    dropped_labels: set[str] = set()
    n_relabeled = 0
    for sp_label, value in overrides.items():
        v = str(value).strip()
        if v.lower() == 'drop':
            dropped_labels.add(sp_label)
            assignments.pop(sp_label, None)
            continue
        if v == '(Moderator)' or v in candidates:
            assignments[sp_label] = v
        elif v == '(Audience)':
            assignments[sp_label] = f'<{sp_label}> (Audience)'
        else:
            print(f'  WARNING: override value {v!r} for {sp_label} '
                  f'is not in the candidate roster; ignoring')
            continue
        n_relabeled += 1
    if overrides:
        print(f'  manual overrides applied: {n_relabeled} relabeled, '
              f'{len(dropped_labels)} dropped')

    # Strategy 4: per-segment voice fingerprint. Catches cases where
    # pyannote merged two real candidates into one cluster — each
    # segment within the cluster gets matched against the candidate
    # voice references independently, and high-confidence disagreements
    # override the cluster-level assignment for THAT SEGMENT ONLY.
    seg_emb_path = folder / 'segment_embeddings.npz'

    # Build event-local references from the anchored opening speeches.
    # These are acoustically matched to the rest of the event (same mic,
    # same venue) so cosine scores against them are dramatically higher
    # than scores against studio-recorded intro-video embeddings —
    # making per-segment matching much more reliable. The library
    # fingerprints are still used for any candidate the moderator didn't
    # cleanly anchor.
    event_local_refs = build_event_local_refs(
        segments, anchor_map, fp_map, seg_emb_path,
    )
    if event_local_refs:
        print(f'event-local refs from opening speeches: '
              f'{len(event_local_refs)} candidates '
              f'({sorted(event_local_refs.keys())})')

    per_seg_matches = per_segment_voice_fingerprint(
        seg_emb_path, candidates, event_local_refs=event_local_refs,
    )
    if per_seg_matches:
        print(f'per-segment fingerprint matched {len(per_seg_matches)} '
              f'of {len(segments)} segments above threshold')

    # Build per-segment overrides: when a segment's voiceprint matches
    # a DIFFERENT candidate than its cluster's assignment, AND the
    # per-segment confidence is high enough to trust, override.
    per_seg_overrides: dict[int, str] = {}
    n_overrides = 0
    for i, seg in enumerate(segments):
        match = per_seg_matches.get(i)
        if not match:
            continue
        seg_candidate, seg_sim = match
        cluster_assignment = assignments.get(seg['speaker_label'])
        # If cluster assignment is None (unmapped) → use per-segment match.
        # If cluster assignment equals per-segment match → no override needed.
        # If they differ AND per-segment is confident (>= 0.6) → override.
        if cluster_assignment is None or '(Audience)' in (cluster_assignment or ''):
            if seg_sim >= 0.6:
                per_seg_overrides[i] = seg_candidate
                n_overrides += 1
        elif cluster_assignment != seg_candidate and seg_sim >= 0.6:
            per_seg_overrides[i] = seg_candidate
            n_overrides += 1
    if n_overrides:
        print(f'  per-segment overrides: {n_overrides} segments re-attributed '
              f'(catches mid-cluster speaker changes)')

    # Filter out segments from speaker labels the user explicitly told
    # us to drop.
    visible_segments = []
    visible_overrides: dict[int, str] = {}
    for i, s in enumerate(segments):
        if s['speaker_label'] in dropped_labels:
            continue
        new_i = len(visible_segments)
        visible_segments.append(s)
        if i in per_seg_overrides:
            visible_overrides[new_i] = per_seg_overrides[i]
    transcript = render_transcript_md(
        visible_segments, assignments, metadata,
        per_seg_overrides=visible_overrides,
    )
    out_path.write_text(transcript, encoding='utf-8')
    print(f'wrote {out_path}')

    if not args.no_update_references:
        write_voice_references(embeddings_path, assignments, candidates)
        print(f'updated voice-embedding library at {EMBEDDINGS_DIR}')


if __name__ == '__main__':
    main()
