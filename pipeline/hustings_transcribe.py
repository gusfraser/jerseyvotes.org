"""
Transcribe pipeline/hustings/<event-slug>/audio.m4a with faster-whisper.

Uses model `large-v3` for quality on accented English. Jersey-specific
words (parish names, French loanwords, candidate surnames from
metadata.yaml) are fed to Whisper as the `initial_prompt` so the model
biases towards correct spelling — out-of-the-box Whisper consistently
garbles "Connétable", "St Hélier", and surnames like "Le Chevalier".

Outputs:
    pipeline/hustings/<event-slug>/
        words.json         — list of {start, end, text} per word
        transcript.txt     — plain transcript with no speaker labels

The diarisation pass (hustings_diarise.py) consumes words.json. The
plain transcript.txt is useful for sanity-comparing against
youtube_captions.vtt when present.

Run:
  python pipeline/hustings_transcribe.py --slug sthelier-connetable-2026
  python pipeline/hustings_transcribe.py --slug ... --model medium     # cheaper
  python pipeline/hustings_transcribe.py --slug ... --device cpu       # no GPU
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

HUSTINGS_DIR = Path(__file__).resolve().parent / 'hustings'

# Fixed vocabulary that helps Whisper not garble Jersey-specific words.
# Augmented per-event with the candidates roster from metadata.yaml.
#
# The Whisper initial_prompt is a 224-token soft bias — terms here get
# higher prior probability in decoding. It's not a hard constraint
# (Whisper can still mishear, esp. when audio is muddy), so this list
# is paired with regex fixups in normalise_local_terms.py.
#
# Coverage targets (driven by garbles found in actual transcripts):
#   * All 12 parishes including the often-mangled St Saviour
#     (→ "St Xavier"), St Ouen (→ "St Juan"), St Brelade
#     (→ "St Brelard" / "St Bralad" / etc.).
#   * St Aubin and St Aubin's Bay — coastal village in St Brelade,
#     often misheard as "St Oban".
#   * Honorary Police / Centenier / Vingtenier / Procureur — parish-
#     level law-enforcement and admin vocabulary near-unique to
#     Jersey + Guernsey + Sark, and routinely garbled
#     ("Honorary Police" → "Henry Police").
#   * Common Jersey-French surnames (Le-… prefixes) that Whisper
#     splits or anglicises.
JERSEY_VOCAB = [
    # Parishes (all 12) and constituency variants
    'Jersey', 'St Helier', 'St Helier North', 'St Helier Central',
    'St Helier South', 'St Saviour', 'St Brelade', 'St Clement',
    'St Lawrence', 'Trinity', 'Grouville', 'St Peter', 'St Ouen',
    'St John', 'St Martin', 'St Mary',
    # Place names within parishes
    'St Aubin', "St Aubin's Bay", "St Aubin's Road",
    'Gorey', 'Gorey Village', 'Mont Orgueil',
    'Beaumont', 'La Pulente', 'Plémont', 'Greve de Lecq',
    'Bouley Bay', 'Bonne Nuit', 'Rozel', 'La Hougue Bie',
    "St Catherine's", 'Elizabeth Castle', 'Archirondel',
    'Portelet', 'Ouaisné', 'Noirmont', 'La Moye', 'Les Quennevais',
    # Government roles + bodies
    'Connétable', 'Constable', 'Centenier', 'Vingtenier', 'Vingtaine',
    'Procureur', 'Procureur du Bien Public', 'Honorary Police',
    'Jurat', 'Bailiff', 'Bailiwick', 'Deputy Bailiff',
    'States Assembly', 'States Greffe', 'Judicial Greffe', 'Greffier',
    'States Member', 'Council of Ministers', 'Chief Minister',
    'Treasury Minister', 'Deputy', 'Senator', 'Reform Jersey',
    # Common Jersey-French surnames Whisper mangles
    'Le Quesne', 'Le Maistre', 'Le Sueur', 'Le Hégarat', 'Le Cornu',
    'Le Marquand', 'Le Boutillier', 'Le Pavoux',
    'Mézec', 'Crowcroft', 'Renouf', 'Pallot', 'Pinel', 'Ozouf',
    # Policy + initiatives
    'Bridging Island Plan', 'Skills Development Fund',
    'Government Plan', 'Long-Term Care',
    # Local references
    'vote.je', 'Jersey Evening Post', 'Bailiwick Express',
    'Highlands College', 'Hautlieu', 'Victoria College',
]


def build_initial_prompt(metadata: dict) -> str:
    cand_names = [c.get('name', '') for c in metadata.get('candidates', [])]
    mods = metadata.get('moderator_names', []) or []
    biased = ', '.join(
        JERSEY_VOCAB + [n for n in cand_names if n] + [m for m in mods if m]
    )
    return (
        f'This is a Jersey election hustings recording. Speakers include: '
        f'{biased}.'
    )


def main():
    parser = argparse.ArgumentParser(
        description='Transcribe a hustings audio file with Whisper.',
    )
    parser.add_argument('--slug', required=True, help='Event slug')
    parser.add_argument('--model', default='large-v3',
                        help='Whisper model size (default: large-v3)')
    parser.add_argument('--backend', default='auto',
                        choices=('auto', 'mlx', 'faster'),
                        help='Inference backend. "mlx" runs on Apple Silicon '
                             'GPU (5-15x realtime); "faster" is CPU/CUDA via '
                             'CTranslate2. "auto" picks mlx if available.')
    parser.add_argument('--device', default='auto',
                        choices=('auto', 'cpu', 'cuda', 'mps'),
                        help='Inference device (faster-whisper only)')
    parser.add_argument('--compute-type', default='auto',
                        help='Quantisation (faster-whisper only): auto / float16 / int8 / int8_float16')
    parser.add_argument('--force', action='store_true',
                        help='Re-transcribe even if words.json exists')
    parser.add_argument('--vad', action='store_true', default=True,
                        help='Use voice-activity detection (skip silences)')
    args = parser.parse_args()

    folder = HUSTINGS_DIR / args.slug
    # Prefer WAV when present (created by hustings_fetch.py) — m4a still
    # works for both backends but WAV avoids re-decoding.
    audio_path = folder / 'audio.wav'
    if not audio_path.exists():
        audio_path = folder / 'audio.m4a'
    words_path = folder / 'words.json'
    plain_path = folder / 'transcript.txt'
    meta_path = folder / 'metadata.yaml'

    if not audio_path.exists():
        sys.exit(f'No audio.wav or audio.m4a in {folder} — run hustings_fetch.py first.')
    if not meta_path.exists():
        sys.exit(f'No metadata.yaml in {folder}.')
    if words_path.exists() and not args.force:
        sys.exit(f'words.json already exists in {folder} (use --force to re-run).')

    metadata = yaml.safe_load(meta_path.read_text()) or {}
    initial_prompt = build_initial_prompt(metadata)
    print(f'initial_prompt = {initial_prompt[:160]}...')

    backend = args.backend
    if backend == 'auto':
        backend = 'mlx' if _mlx_available() else 'faster'
    print(f'backend = {backend}')

    if backend == 'mlx':
        words, plain, duration = _transcribe_mlx(audio_path, initial_prompt, args.model)
    else:
        words, plain, duration = _transcribe_faster(
            audio_path, initial_prompt, args.model, args.device, args.compute_type, args.vad,
        )

    plain_path.write_text(plain, encoding='utf-8')
    words_path.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'  wrote {len(words)} words')
    print(f'  duration={duration:.0f}s')


def _mlx_available() -> bool:
    try:
        import mlx_whisper  # noqa: F401
        import mlx.core as mx
        return 'gpu' in str(mx.default_device()).lower()
    except ImportError:
        return False


# mlx-community model repo for each canonical Whisper size. mlx-whisper
# uses HuggingFace model paths — these are pre-converted to MLX format.
_MLX_MODELS = {
    'tiny':       'mlx-community/whisper-tiny-mlx',
    'base':       'mlx-community/whisper-base-mlx',
    'small':      'mlx-community/whisper-small-mlx',
    'medium':     'mlx-community/whisper-medium-mlx',
    'large':      'mlx-community/whisper-large-v3-mlx',
    'large-v2':   'mlx-community/whisper-large-v2-mlx',
    'large-v3':   'mlx-community/whisper-large-v3-mlx',
    'turbo':      'mlx-community/whisper-large-v3-turbo',
}


def _transcribe_mlx(audio_path: Path, initial_prompt: str, model: str):
    import mlx_whisper
    repo = _MLX_MODELS.get(model)
    if repo is None:
        repo = model
    print(f'  mlx model = {repo}')
    # Anti-loop hardening:
    #   * condition_on_previous_text=False — Whisper's biggest loop trap
    #     is using the previous chunk's output as context for the next.
    #     Once a junk "Sne" token appears it gets carried forward and
    #     the next chunk happily continues the loop. Turning this off
    #     means each 30-second chunk is decoded independently, which
    #     trades a little fluency at chunk boundaries for not losing
    #     30-second spans of real speech to repetition.
    #   * compression_ratio_threshold=2.0 — tighter than default 2.4;
    #     when the decoded text compresses too well (i.e. is repetitive),
    #     fall back to the next temperature.
    #   * temperature falls back from 0 → 1 if compression_ratio or
    #     no_speech triggers, so unclear chunks get retried with
    #     stochastic sampling that escapes the loop.
    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=repo,
        language='en',
        initial_prompt=initial_prompt,
        word_timestamps=True,
        verbose=False,
        # Anti-loop hardening (cumulative):
        # * condition_on_previous_text=False — Whisper's biggest loop
        #   trap is using the previous chunk's output as context for
        #   the next. Once a junk "Sne" appears it gets carried
        #   forward. Disabling this means each 30-second chunk decodes
        #   independently — small fluency cost at boundaries, large
        #   anti-loop benefit.
        # * compression_ratio_threshold=2.0 — tighter than default
        #   2.4; falls back when output compresses too well (i.e.
        #   repetitive).
        # * logprob_threshold=-1.0 — NEW. The "Sne Sne Sne" failure
        #   mode produces tokens with logprob → -∞. This gate trips
        #   the temperature fallback BEFORE compression-ratio would,
        #   catching low-confidence runs earlier.
        # * no_speech_threshold=0.6 — when the model thinks a chunk
        #   is silence (no_speech_prob > 0.6) we DON'T emit text for
        #   it, which prevents the degenerate-on-pause failure mode
        #   that triggered Bernard Place's loop.
        # * temperature sweep — falls back through (0, 0.2, ..., 1.0)
        #   when any of the above gates trip.
        condition_on_previous_text=False,
        compression_ratio_threshold=2.0,
        logprob_threshold=-1.0,
        no_speech_threshold=0.6,
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
    )
    words = []
    plain_parts = []
    for seg in result.get('segments', []):
        plain_parts.append(seg.get('text', '').strip())
        for w in (seg.get('words') or []):
            words.append({
                'start': round(float(w['start']), 3),
                'end': round(float(w['end']), 3),
                'text': w.get('word') or w.get('text') or '',
                'prob': round(float(w['probability']), 3) if w.get('probability') is not None else None,
            })
    # mlx_whisper doesn't return duration directly; derive from last segment end.
    duration = result.get('segments', [{}])[-1].get('end', 0.0) if result.get('segments') else 0.0
    return words, '\n'.join(plain_parts), float(duration)


def _transcribe_faster(audio_path: Path, initial_prompt: str, model_size: str,
                       device_arg: str, compute_arg: str, vad: bool):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit('faster-whisper not installed. pip install faster-whisper')

    device = device_arg if device_arg != 'auto' else _autodevice()
    compute = compute_arg if compute_arg != 'auto' else _autocompute(device)
    print(f'  loading model={model_size} device={device} compute={compute}')
    model = WhisperModel(model_size, device=device, compute_type=compute)
    print(f'  transcribing {audio_path}…')
    segments, info = model.transcribe(
        str(audio_path),
        language='en',
        initial_prompt=initial_prompt,
        word_timestamps=True,
        vad_filter=vad,
        beam_size=5,
    )
    words = []
    plain_parts = []
    for seg in segments:
        plain_parts.append(seg.text.strip())
        for w in (seg.words or []):
            words.append({
                'start': round(w.start, 3),
                'end': round(w.end, 3),
                'text': w.word,
                'prob': round(w.probability, 3) if w.probability is not None else None,
            })
    return words, '\n'.join(plain_parts), float(info.duration)


def _autodevice() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return 'cuda'
        if getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available():
            print('  note: MPS available but faster-whisper falls back to CPU '
                  '(use --backend mlx for GPU acceleration on Apple Silicon)')
    except ImportError:
        pass
    return 'cpu'


def _autocompute(device: str) -> str:
    return 'float16' if device == 'cuda' else 'int8'


if __name__ == '__main__':
    main()
