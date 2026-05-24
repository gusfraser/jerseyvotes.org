"""
Run speaker diarisation on pipeline/hustings/<event-slug>/audio.m4a with
pyannote.audio's speaker-diarization-3.1 pipeline.

Aligns the resulting anonymous SPEAKER_00..SPEAKER_N intervals against the
word-level Whisper output from hustings_transcribe.py, producing one
segment per (speaker, contiguous-time-range) with the matched word text
joined in order.

Outputs:
    pipeline/hustings/<event-slug>/
        diarised_segments.json
            [{start, end, speaker_label, text}, ...]
        speaker_embeddings.npz
            {SPEAKER_00: ndarray(192), SPEAKER_01: ndarray(192), …}
            — mean embedding per anonymous speaker; used by
              hustings_identify.py to match against the per-candidate
              voice-fingerprint library.

Requires a HuggingFace access token with read access to the gated
pyannote/speaker-diarization-3.1 model. Set HF_TOKEN in .env or pass
--hf-token explicitly.

Run:
  python pipeline/hustings_diarise.py --slug sthelier-connetable-2026
  python pipeline/hustings_diarise.py --slug ... --num-speakers 5  # if known
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv(override=True)

HUSTINGS_DIR = Path(__file__).resolve().parent / 'hustings'


def align_words_to_speakers(words: list[dict], diarisation) -> list[dict]:
    """For each diarised interval, gather the Whisper words that fall
    inside it (>=50% overlap) and concatenate their text. Produces
    contiguous segments — each turn-take becomes one segment."""
    out: list[dict] = []
    for turn, _, speaker in diarisation.itertracks(yield_label=True):
        start, end = float(turn.start), float(turn.end)
        if end <= start:
            continue
        # Words within this turn.
        chunk_text = []
        for w in words:
            ws, we = w['start'], w['end']
            if we < start or ws > end:
                continue
            overlap = max(0.0, min(we, end) - max(ws, start))
            wlen = max(0.0001, we - ws)
            if overlap / wlen >= 0.5:
                chunk_text.append(w['text'])
        text = ''.join(chunk_text).strip()
        if not text:
            continue
        out.append({
            'start': round(start, 3),
            'end': round(end, 3),
            'speaker_label': str(speaker),
            'text': text,
        })

    # Merge consecutive segments by the same speaker (pyannote tends to
    # split tightly even when the same person is speaking).
    merged: list[dict] = []
    for seg in out:
        if merged and merged[-1]['speaker_label'] == seg['speaker_label'] \
                and seg['start'] - merged[-1]['end'] < 1.5:
            merged[-1]['end'] = seg['end']
            merged[-1]['text'] = (merged[-1]['text'] + ' ' + seg['text']).strip()
        else:
            merged.append(dict(seg))
    return merged


def compute_speaker_embeddings(audio_path: Path, diarisation,
                                inference_model) -> dict[str, np.ndarray]:
    """Per-speaker mean of the pyannote embedding model output across
    that speaker's intervals. Used downstream as a voice fingerprint."""
    from pyannote.audio import Audio
    from pyannote.core import Segment

    audio_io = Audio(sample_rate=16000, mono=True)

    by_speaker: dict[str, list[np.ndarray]] = {}
    for turn, _, speaker in diarisation.itertracks(yield_label=True):
        seg = Segment(float(turn.start), float(turn.end))
        if seg.duration < 0.5:
            continue
        try:
            waveform, _ = audio_io.crop(str(audio_path), seg)
            emb = inference_model({'waveform': waveform, 'sample_rate': 16000})
            arr = np.asarray(emb).squeeze()
            by_speaker.setdefault(str(speaker), []).append(arr)
        except Exception as e:
            print(f'  embedding error for {speaker} {seg}: {e}')

    return {sp: np.mean(np.stack(v), axis=0) for sp, v in by_speaker.items() if v}


def compute_per_segment_embeddings(audio_path: Path, segments: list[dict],
                                    inference_model) -> dict[int, np.ndarray]:
    """One pyannote embedding per merged segment (from segments list,
    not per pyannote turn). Returns {segment_index_in_list: 512-d array}.

    Per-segment embeddings let the identify step catch cases where two
    real speakers were merged into one pyannote cluster — the
    cluster-averaged voiceprint blends both voices, but each individual
    segment's voiceprint should still match the correct candidate."""
    from pyannote.audio import Audio
    from pyannote.core import Segment

    audio_io = Audio(sample_rate=16000, mono=True)
    out: dict[int, np.ndarray] = {}
    for i, s in enumerate(segments):
        dur = float(s['end']) - float(s['start'])
        # Need ≥ 1.5s for a meaningful embedding; below that, the model's
        # output is dominated by edge effects and unreliable. Skip — the
        # cluster-level embedding still applies for these short turns.
        if dur < 1.5:
            continue
        try:
            seg = Segment(float(s['start']), float(s['end']))
            waveform, _ = audio_io.crop(str(audio_path), seg)
            emb = inference_model({'waveform': waveform, 'sample_rate': 16000})
            out[i] = np.asarray(emb).squeeze()
        except Exception as e:
            print(f'  per-segment embedding error at {s["start"]:.1f}: {e}')
    return out


def main():
    parser = argparse.ArgumentParser(
        description='Diarise hustings audio + align to Whisper words.',
    )
    parser.add_argument('--slug', required=True, help='Event slug')
    parser.add_argument('--hf-token', default=os.environ.get('HF_TOKEN'),
                        help='HuggingFace token (or set HF_TOKEN env var)')
    parser.add_argument('--num-speakers', type=int, default=None,
                        help='Exact speaker count when known (improves accuracy)')
    parser.add_argument('--min-speakers', type=int, default=None)
    parser.add_argument('--max-speakers', type=int, default=None)
    parser.add_argument('--device', default='auto',
                        choices=('auto', 'cpu', 'cuda', 'mps'))
    parser.add_argument('--force', action='store_true',
                        help='Re-run even if diarised_segments.json exists')
    parser.add_argument('--no-embeddings', action='store_true',
                        help='Skip the embedding pass (faster; identify.py '
                             'falls back to moderator-anchor heuristic only)')
    args = parser.parse_args()

    if not args.hf_token:
        sys.exit('HF token required (env HF_TOKEN or --hf-token); '
                 'pyannote/speaker-diarization-3.1 is gated.')

    folder = HUSTINGS_DIR / args.slug
    # pyannote (via torchaudio's soundfile backend) needs a WAV — m4a is
    # not supported. Prefer audio.wav if a previous step left one behind,
    # otherwise convert m4a → wav inline and delete the wav at the end
    # to keep disk usage low across 25+ events.
    wav_path = folder / 'audio.wav'
    m4a_path = folder / 'audio.m4a'
    delete_wav_after = False
    if wav_path.exists():
        audio_path = wav_path
    elif m4a_path.exists():
        print(f'  converting {m4a_path.name} → audio.wav (16kHz mono PCM)…')
        import subprocess as _sp
        proc = _sp.run(
            ['ffmpeg', '-y', '-i', str(m4a_path),
             '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav_path)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            sys.exit(f'ffmpeg failed ({proc.returncode}): {proc.stderr[-300:]}')
        audio_path = wav_path
        delete_wav_after = True
    else:
        sys.exit(f'No audio.wav or audio.m4a in {folder} — run hustings_fetch.py first.')

    words_path = folder / 'words.json'
    out_path = folder / 'diarised_segments.json'
    embeddings_path = folder / 'speaker_embeddings.npz'
    if not words_path.exists():
        sys.exit(f'No words.json in {folder} — run hustings_transcribe.py first.')
    if out_path.exists() and not args.force:
        sys.exit(f'{out_path.name} already exists (use --force).')

    words = json.loads(words_path.read_text())
    print(f'loaded {len(words)} words')

    try:
        from pyannote.audio import Pipeline
        from pyannote.audio import Inference
    except ImportError:
        sys.exit('pyannote.audio not installed. pip install pyannote.audio')

    device = args.device if args.device != 'auto' else _autodevice()
    print(f'loading pyannote/speaker-diarization-3.1 on {device}…')
    pipeline = Pipeline.from_pretrained(
        'pyannote/speaker-diarization-3.1', use_auth_token=args.hf_token,
    )
    try:
        import torch
        pipeline.to(torch.device(device))
    except Exception as e:
        print(f'  could not move pipeline to {device}: {e}')

    diarise_kwargs = {}
    if args.num_speakers:
        diarise_kwargs['num_speakers'] = args.num_speakers
    if args.min_speakers:
        diarise_kwargs['min_speakers'] = args.min_speakers
    if args.max_speakers:
        diarise_kwargs['max_speakers'] = args.max_speakers

    print(f'diarising… {diarise_kwargs or "(auto speaker count)"}')
    diarisation = pipeline(str(audio_path), **diarise_kwargs)

    segments = align_words_to_speakers(words, diarisation)
    out_path.write_text(
        json.dumps(segments, ensure_ascii=False, indent=1),
        encoding='utf-8',
    )
    print(f'  wrote {len(segments)} diarised segments to {out_path.name}')

    if not args.no_embeddings:
        try:
            print('computing speaker embeddings…')
            emb_model = Inference(
                'pyannote/embedding', use_auth_token=args.hf_token,
                window='whole',
            )
            embeddings = compute_speaker_embeddings(audio_path, diarisation, emb_model)
            np.savez(embeddings_path, **embeddings)
            print(f'  wrote {len(embeddings)} speaker embeddings to {embeddings_path.name}')

            # Per-segment embeddings — used by identify to catch cases
            # where two real candidates got merged into one pyannote
            # cluster. Each merged segment in `segments` gets its own
            # voiceprint so per-segment fingerprint matching can override
            # the cluster-level assignment.
            print('computing per-segment embeddings…')
            seg_embeddings = compute_per_segment_embeddings(
                audio_path, segments, emb_model,
            )
            seg_emb_path = folder / 'segment_embeddings.npz'
            # Key by index padded to 6 digits so numeric order is
            # preserved in the npz dict.
            np.savez(
                seg_emb_path,
                **{f'{i:06d}': v for i, v in seg_embeddings.items()},
            )
            print(f'  wrote {len(seg_embeddings)} per-segment embeddings '
                  f'to {seg_emb_path.name}')
        except Exception as e:
            print(f'  embedding pass failed (continuing without): {e}')

    # Delete the WAV if we created it inline (we have the m4a + outputs;
    # the WAV is purely a working file for pyannote and would bloat disk
    # by ~240MB per event across 25+ events).
    if delete_wav_after and wav_path.exists():
        wav_path.unlink()
        print(f'  cleaned up {wav_path.name}')


def _autodevice() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return 'cuda'
        if getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available():
            return 'mps'
    except ImportError:
        pass
    return 'cpu'


if __name__ == '__main__':
    main()
