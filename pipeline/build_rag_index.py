"""
Build the RAG chunk index that powers the /ask chat + semantic search feature.

Pulls the two content channels we already store, chunks them, embeds each chunk
with Voyage, and upserts into the rag_chunks table (migration 010):

  * manifestos — candidates.manifesto_text (vote.je, the candidate's signed
                 statement) AND candidates.enhanced_manifesto_text (party page /
                 personal site / candidate-supplied doc) when present. Both are
                 indexed separately so every chunk cites its true public URL.
  * hustings   — one chunk per candidate-attributed hustings_segments row,
                 carrying the event's transcript URL + a YouTube deep-link.

Transparency invariant (mirrors classify_candidates.py / migration 004): every
chunk MUST carry a non-empty public source_url. Opted-out candidates
(opted_out_at IS NOT NULL) are never indexed.

Idempotent: each chunk has a deterministic source_key and a content_hash. A
re-run only embeds chunks that are new or whose text changed, deletes chunks
that no longer exist, and leaves unchanged chunks alone. --force re-embeds
everything.

Run:
  python pipeline/build_rag_index.py                 # incremental build
  python pipeline/build_rag_index.py --force         # re-embed everything
  python pipeline/build_rag_index.py --dry-run       # no DB writes, no embeds
  python pipeline/build_rag_index.py --only hustings # one channel

Requires VOYAGE_API_KEY (and DATABASE_URL) in the environment. LOGFIRE_TOKEN is
optional — spans are emitted only when a token is present.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time

import psycopg2
from dotenv import load_dotenv

# override=True so an empty key pre-set in the shell can't shadow the real key
# in .env (matches classify_candidates.py).
load_dotenv(override=True)

# Optional observability. send_to_logfire='if-token-present' makes this a no-op
# when LOGFIRE_TOKEN is unset, so the builder runs fine without Logfire.
try:
    import logfire  # type: ignore

    logfire.configure(
        send_to_logfire="if-token-present",
        service_name="jerseyvotes-rag-builder",
        console=False,
    )
    _LOGFIRE = True
except Exception:  # pragma: no cover - logfire is optional
    logfire = None  # type: ignore
    _LOGFIRE = False


EMBED_MODEL = os.environ.get("VOYAGE_MODEL", "voyage-3.5-lite")  # 1024-dim; must match vector(1024) in migration 010
EMBED_DIM = 1024
# Voyage allows up to 128 inputs per request. Lower the batch and add a sleep
# to stay under the unpaid free-tier limits (3 RPM / 10K TPM); the defaults are
# for a standard (payment-method-on-file) account.
EMBED_BATCH = int(os.environ.get("VOYAGE_EMBED_BATCH", "128"))
EMBED_SLEEP_MS = int(os.environ.get("VOYAGE_SLEEP_MS", "0"))
TARGET_CHARS = 2000              # ~500 tokens per manifesto chunk
MIN_CHARS = 1                    # index whatever text exists (some manifestos are short)
HUSTINGS_SUBCHUNK_CHARS = 2600  # sub-chunk only unusually long segments (~650 tokens)


def _span(name: str, **attrs):
    """logfire.span(...) when configured, else a no-op context manager."""
    if _LOGFIRE:
        return logfire.span(name, **attrs)

    class _Noop:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Noop()


def db_connect():
    """Neon-friendly connection with TCP keepalives (see classify_candidates.py)."""
    return psycopg2.connect(
        os.environ["DATABASE_URL"],
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
        connect_timeout=15,
    )


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalise_ws(text: str) -> str:
    return re.sub(r"[ \t]+", " ", (text or "")).strip()


def chunk_text(text: str, target_chars: int = TARGET_CHARS) -> list[str]:
    """Paragraph-aware chunker. Packs paragraphs up to ~target_chars; splits an
    over-long paragraph on sentence boundaries. Good enough for manifestos —
    we are not trying to be clever, just keep chunks coherent and bounded."""
    text = (text or "").strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if len(para) > target_chars:
            # Flush, then split the long paragraph by sentences.
            if buf:
                chunks.append(buf.strip())
                buf = ""
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                if not sent.strip():
                    continue
                if len(buf) + len(sent) + 1 > target_chars and buf:
                    chunks.append(buf.strip())
                    buf = ""
                buf = (buf + " " + sent).strip()
            continue
        if len(buf) + len(para) + 2 > target_chars and buf:
            chunks.append(buf.strip())
            buf = ""
        buf = (buf + "\n\n" + para).strip()
    if buf:
        chunks.append(buf.strip())
    return [normalise_ws(c) for c in chunks if len(c.strip()) >= MIN_CHARS]


# ---------------------------------------------------------------------------
# Chunk builders: each returns a list of dicts shaped for rag_chunks.
# ---------------------------------------------------------------------------

def build_manifesto_chunks(cur) -> list[dict]:
    """One set of chunks per public manifesto source a candidate has. Both the
    vote.je text and the enhanced text are indexed when present (each with its
    own source_url) so retrieval can cite the exact origin."""
    cur.execute(
        """
        SELECT candidate_id, vote_je_slug, full_name, role, constituency,
               profile_url,
               NULLIF(manifesto_text, '')          AS voteje_text,
               NULLIF(enhanced_manifesto_text, '') AS enhanced_text,
               enhanced_manifesto_source_url,
               enhanced_manifesto_source_label
        FROM candidates
        WHERE opted_out_at IS NULL
          AND (NULLIF(manifesto_text, '') IS NOT NULL
               OR NULLIF(enhanced_manifesto_text, '') IS NOT NULL)
        ORDER BY candidate_id
        """
    )
    rows = cur.fetchall()

    # Topic tags per candidate (from candidate_topics) — attached to every
    # manifesto chunk for that candidate to aid filtering/boosting later.
    cur.execute("SELECT candidate_id, topic FROM candidate_topics")
    topics_by_cand: dict[int, list[str]] = {}
    for cid, topic in cur.fetchall():
        topics_by_cand.setdefault(cid, []).append(topic)

    out: list[dict] = []
    for (cid, slug, name, role, constituency, profile_url,
         voteje_text, enhanced_text, enh_url, enh_label) in rows:
        tags = topics_by_cand.get(cid, [])

        sources = []
        if voteje_text and profile_url:
            sources.append(("voteje", voteje_text, profile_url, "vote_je"))
        if enhanced_text and enh_url:
            label = f"enhanced:{enh_label}" if enh_label else "enhanced"
            sources.append(("enh", enhanced_text, enh_url, label))

        for origin, text, url, source_label in sources:
            for i, content in enumerate(chunk_text(text)):
                out.append({
                    "source_key": f"manifesto:{origin}:{cid}:{i}",
                    "source_type": "manifesto",
                    "candidate_id": cid,
                    "event_id": None,
                    "segment_id": None,
                    "content": content,
                    "content_hash": sha256(content),
                    "token_count": len(content) // 4,
                    "candidate_name": name,
                    "candidate_slug": slug,
                    "role": role,
                    "constituency": constituency,
                    "source_url": url,
                    "source_label": source_label,
                    "youtube_url": None,
                    "timestamp_seconds": None,
                    "segment_type": None,
                    "topic_tags": tags,
                })
    return out


def build_hustings_chunks(cur) -> list[dict]:
    """One chunk per candidate-attributed hustings segment (sub-chunked only if
    unusually long). Moderator/audience segments are skipped — they carry no
    candidate position. Mirrors the segments classify_hustings.py tags."""
    cur.execute(
        """
        SELECT s.segment_id, s.event_id, s.candidate_id, s.segment_type,
               s.question_summary, s.timestamp_seconds, s.text,
               e.slug AS event_slug, e.transcript_source_url, e.youtube_url,
               e.role AS event_role, e.constituency AS event_constituency,
               c.full_name, c.vote_je_slug, c.role AS cand_role, c.constituency AS cand_constituency
        FROM hustings_segments s
        JOIN hustings_events e   ON e.event_id = s.event_id
        JOIN candidates c        ON c.candidate_id = s.candidate_id
        WHERE s.candidate_id IS NOT NULL
          AND c.opted_out_at IS NULL
          AND s.segment_type IN ('opening_speech', 'question_answer', 'closing_speech')
          AND length(s.text) >= 40
        ORDER BY s.event_id, s.position_in_event
        """
    )
    rows = cur.fetchall()

    # Topic tags per segment (from hustings_segment_topics).
    cur.execute("SELECT segment_id, topic FROM hustings_segment_topics")
    topics_by_seg: dict[int, list[str]] = {}
    for sid, topic in cur.fetchall():
        topics_by_seg.setdefault(sid, []).append(topic)

    out: list[dict] = []
    for (seg_id, event_id, cand_id, seg_type, q_summary, ts, text,
         event_slug, transcript_url, youtube_url,
         event_role, event_constituency,
         name, slug, cand_role, cand_constituency) in rows:
        if not transcript_url:
            continue  # transparency invariant — skip anything without a public URL
        # Sub-chunk only long segments; most are a single chunk.
        pieces = (chunk_text(text, HUSTINGS_SUBCHUNK_CHARS)
                  if len(text) > HUSTINGS_SUBCHUNK_CHARS else [normalise_ws(text)])
        tags = topics_by_seg.get(seg_id, [])
        for i, content in enumerate(pieces):
            if len(content.strip()) < MIN_CHARS:
                continue
            out.append({
                "source_key": f"hustings:seg:{seg_id}:{i}",
                "source_type": "hustings",
                "candidate_id": cand_id,
                "event_id": event_id,
                "segment_id": seg_id,
                "content": content,
                "content_hash": sha256(content),
                "token_count": len(content) // 4,
                "candidate_name": name,
                "candidate_slug": slug,
                "role": cand_role or event_role,
                "constituency": cand_constituency or event_constituency,
                "source_url": transcript_url,
                "source_label": f"hustings:{event_slug}",
                "youtube_url": youtube_url,
                "timestamp_seconds": ts,
                "segment_type": seg_type,
                "topic_tags": tags,
            })
    return out


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_texts(client, texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed a list of texts in batches of EMBED_BATCH with a small retry."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        if start > 0 and EMBED_SLEEP_MS:
            time.sleep(EMBED_SLEEP_MS / 1000)
        batch = texts[start:start + EMBED_BATCH]
        for attempt in range(3):
            try:
                with _span("voyage.embed", batch_size=len(batch), offset=start):
                    resp = client.embed(batch, model=EMBED_MODEL, input_type=input_type)
                vectors.extend(resp.embeddings)
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    raise
                print(f"  voyage embed error (attempt {attempt+1}): {e}; retrying", flush=True)
                time.sleep(2.0 * (attempt + 1))
    if len(vectors) != len(texts):
        raise RuntimeError(f"embedding count mismatch: {len(vectors)} != {len(texts)}")
    return vectors


def vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(round(float(x), 8)) for x in vec) + "]"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build the RAG chunk index (rag_chunks).")
    parser.add_argument("--force", action="store_true", help="Re-embed all chunks, ignoring content_hash")
    parser.add_argument("--dry-run", action="store_true", help="Build chunks but do not embed or write")
    parser.add_argument("--only", choices=["all", "manifestos", "hustings"], default="all")
    parser.add_argument("--limit", type=int, default=0, help="Cap number of chunks (debug)")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        sys.exit("DATABASE_URL not set (see .env)")

    conn = db_connect()
    cur = conn.cursor()

    with _span("build_rag_index", only=args.only, force=args.force):
        desired: list[dict] = []
        if args.only in ("all", "manifestos"):
            desired += build_manifesto_chunks(cur)
        if args.only in ("all", "hustings"):
            desired += build_hustings_chunks(cur)
        if args.limit:
            desired = desired[: args.limit]

        n_manifesto = sum(1 for c in desired if c["source_type"] == "manifesto")
        n_hustings = sum(1 for c in desired if c["source_type"] == "hustings")
        print(f"Built {len(desired)} desired chunks (manifesto={n_manifesto}, hustings={n_hustings})")

        if args.dry_run:
            print("Dry run — no embeds, no writes.")
            cur.close(); conn.close()
            return

        # Existing chunks: source_key -> content_hash, to skip unchanged work.
        cur.execute("SELECT source_key, content_hash FROM rag_chunks")
        existing = dict(cur.fetchall())
        desired_keys = {c["source_key"] for c in desired}

        if args.force:
            to_write = desired
        else:
            to_write = [c for c in desired
                        if existing.get(c["source_key"]) != c["content_hash"]]
        # Only delete stale rows within the source_type(s) we just rebuilt, so
        # `--only hustings` never removes manifesto chunks (and vice versa).
        prefix = {"manifestos": "manifesto:", "hustings": "hustings:"}.get(args.only)
        stale_keys = [
            k for k in existing
            if k not in desired_keys and (prefix is None or k.startswith(prefix))
        ]

        print(f"  to embed/upsert: {len(to_write)}   unchanged: {len(desired) - len(to_write)}   "
              f"stale to delete: {len(stale_keys)}")

        if to_write:
            try:
                import voyageai  # type: ignore
            except ImportError:
                sys.exit("voyageai not installed. pip install voyageai (and set VOYAGE_API_KEY)")
            if not os.environ.get("VOYAGE_API_KEY"):
                sys.exit("VOYAGE_API_KEY not set — required to embed. See .env.")
            client = voyageai.Client()

            embeddings = embed_texts(client, [c["content"] for c in to_write], "document")

            written = 0
            for c, vec in zip(to_write, embeddings):
                cur.execute(
                    """
                    INSERT INTO rag_chunks (
                        source_key, source_type, candidate_id, event_id, segment_id,
                        content, content_hash, token_count,
                        candidate_name, candidate_slug, role, constituency,
                        source_url, source_label, youtube_url, timestamp_seconds,
                        segment_type, topic_tags, embedding, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s::vector, NOW()
                    )
                    ON CONFLICT (source_key) DO UPDATE SET
                        source_type = EXCLUDED.source_type,
                        candidate_id = EXCLUDED.candidate_id,
                        event_id = EXCLUDED.event_id,
                        segment_id = EXCLUDED.segment_id,
                        content = EXCLUDED.content,
                        content_hash = EXCLUDED.content_hash,
                        token_count = EXCLUDED.token_count,
                        candidate_name = EXCLUDED.candidate_name,
                        candidate_slug = EXCLUDED.candidate_slug,
                        role = EXCLUDED.role,
                        constituency = EXCLUDED.constituency,
                        source_url = EXCLUDED.source_url,
                        source_label = EXCLUDED.source_label,
                        youtube_url = EXCLUDED.youtube_url,
                        timestamp_seconds = EXCLUDED.timestamp_seconds,
                        segment_type = EXCLUDED.segment_type,
                        topic_tags = EXCLUDED.topic_tags,
                        embedding = EXCLUDED.embedding,
                        updated_at = NOW()
                    """,
                    (
                        c["source_key"], c["source_type"], c["candidate_id"], c["event_id"], c["segment_id"],
                        c["content"], c["content_hash"], c["token_count"],
                        c["candidate_name"], c["candidate_slug"], c["role"], c["constituency"],
                        c["source_url"], c["source_label"], c["youtube_url"], c["timestamp_seconds"],
                        c["segment_type"], c["topic_tags"], vec_literal(vec),
                    ),
                )
                written += 1
                if written % 200 == 0:
                    conn.commit()
                    print(f"  upserted {written}/{len(to_write)}", flush=True)
            conn.commit()
            print(f"  upserted {written} chunks")

        if stale_keys:
            for start in range(0, len(stale_keys), 500):
                batch = stale_keys[start:start + 500]
                cur.execute("DELETE FROM rag_chunks WHERE source_key = ANY(%s)", (batch,))
            conn.commit()
            print(f"  deleted {len(stale_keys)} stale chunks")

        cur.execute(
            "SELECT source_type, count(*), count(embedding) FROM rag_chunks GROUP BY source_type ORDER BY source_type"
        )
        print("\nIndex now holds:")
        for stype, total, embedded in cur.fetchall():
            print(f"  {stype:<10} {total} rows ({embedded} embedded)")

    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
