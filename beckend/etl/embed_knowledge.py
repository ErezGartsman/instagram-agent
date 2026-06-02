#!/usr/bin/env python3
"""
RAG ETL: Chunk company knowledge files → embed with Gemini → store in Supabase.

Usage:
    SUPABASE_DIRECT_URL="postgresql://..." GEMINI_API_KEY="..." \\
    python etl/embed_knowledge.py

    # Re-run safely — uses TRUNCATE + re-insert for idempotency.
    # To add a single file without clearing others, pass --source <filename>:
    python etl/embed_knowledge.py --source services.txt

Input:  beckend/knowledge/*.txt  (plain text, UTF-8)
Output: Supabase knowledge_base table (content, embedding, source, chunk_index)
"""

import os
import sys
import time
import argparse
import logging
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from google import genai
from google.genai import types as genai_types

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("embed")

# ─── Config ───────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("SUPABASE_DIRECT_URL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not DATABASE_URL:
    sys.exit("ERROR: Set SUPABASE_DIRECT_URL to the direct PostgreSQL connection URL.")
if not GEMINI_API_KEY:
    sys.exit("ERROR: Set GEMINI_API_KEY.")

KNOWLEDGE_DIR  = Path(__file__).parent.parent / "knowledge"
EMBEDDING_MODEL   = "gemini-embedding-001"   # stable embedding model
EMBEDDING_DIM     = 768                      # must match VECTOR(768) in Supabase schema
                                             # gemini-embedding-001 defaults to 3072;
                                             # we truncate to 768 via output_dimensionality
CHUNK_SIZE      = 1800    # characters (~450 tokens) — fits well within context
CHUNK_OVERLAP   = 200     # characters — enough for sentence continuity
EMBED_BATCH     = 5       # embed N chunks per API call (rate-limit friendly)
RATE_LIMIT_WAIT = 0.5     # seconds between batches


# ─── Chunking ─────────────────────────────────────────────────────────────────

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split text into overlapping character-window chunks.

    Overlap ensures that a sentence split across a boundary still appears
    fully in at least one chunk, so the LLM always gets complete context.
    """
    text   = text.strip()
    chunks = []
    start  = 0

    while start < len(text):
        end   = min(start + size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap  # step back by overlap to get continuity

    return chunks


# ─── Embedding ────────────────────────────────────────────────────────────────

def embed_chunks(client: genai.Client, chunks: list[str]) -> list[list[float]]:
    """
    Embed a list of text chunks using Gemini text-embedding-004.

    Processes in batches of EMBED_BATCH with a small delay to stay within
    the free-tier rate limit (1,500 RPM / 100 requests per minute per project).
    Returns a list of 768-dimensional float vectors in the same order as input.
    """
    all_vectors = []

    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i:i + EMBED_BATCH]
        log.info(f"  Embedding chunks {i + 1}–{i + len(batch)} …")

        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=batch,
            config=genai_types.EmbedContentConfig(
                output_dimensionality=EMBEDDING_DIM,
            ),
        )
        vectors = [emb.values for emb in response.embeddings]
        all_vectors.extend(vectors)

        if i + EMBED_BATCH < len(chunks):
            time.sleep(RATE_LIMIT_WAIT)

    return all_vectors


# ─── Loader ───────────────────────────────────────────────────────────────────

def load_file(cur, client: genai.Client, path: Path) -> int:
    """Chunk, embed, and INSERT one knowledge file. Returns row count inserted."""
    log.info(f"Processing {path.name} …")
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        log.warning(f"  {path.name} is empty — skipping.")
        return 0

    chunks  = chunk_text(text)
    log.info(f"  {len(chunks)} chunks from {len(text):,} characters")

    vectors = embed_chunks(client, chunks)

    rows = [
        (chunk, vector, path.name, idx)
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]

    # pgvector expects the embedding as a string like "[0.1, 0.2, ...]"
    rows_pg = [
        (content, f"[{','.join(str(v) for v in embedding)}]", source, chunk_idx)
        for content, embedding, source, chunk_idx in rows
    ]

    execute_values(
        cur,
        """
        INSERT INTO knowledge_base (content, embedding, source, chunk_index)
        VALUES %s
        """,
        rows_pg,
        template="(%s, %s::vector, %s, %s)",
        page_size=50,
    )
    return len(rows_pg)


# ─── Main ─────────────────────────────────────────────────────────────────────

def run(source_filter: str = None):
    client = genai.Client(api_key=GEMINI_API_KEY)

    if not KNOWLEDGE_DIR.exists():
        sys.exit(f"ERROR: Knowledge directory not found: {KNOWLEDGE_DIR}\n"
                 "Create beckend/knowledge/ and add your .txt files there.")

    txt_files = sorted(KNOWLEDGE_DIR.glob("*.txt"))
    if source_filter:
        txt_files = [f for f in txt_files if f.name == source_filter]

    if not txt_files:
        sys.exit(f"ERROR: No .txt files found in {KNOWLEDGE_DIR}")

    log.info(f"Found {len(txt_files)} file(s): {[f.name for f in txt_files]}")

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            if source_filter:
                # Partial re-run: remove only the rows for this source file
                log.info(f"Clearing existing rows for source={source_filter!r} …")
                cur.execute(
                    "DELETE FROM knowledge_base WHERE source = %s",
                    (source_filter,),
                )
            else:
                # Full re-run: clear everything for idempotency
                log.info("Clearing all existing knowledge_base rows …")
                cur.execute("TRUNCATE knowledge_base RESTART IDENTITY")

            total = 0
            for path in txt_files:
                n = load_file(cur, client, path)
                log.info(f"  ✓ {n:,} chunks from {path.name}")
                total += n

        conn.commit()
        log.info(f"✓ Done — {total:,} total chunks committed to Supabase.")

    except Exception:
        conn.rollback()
        log.exception("ETL failed — rolled back.")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Embed company knowledge into Supabase.")
    parser.add_argument(
        "--source",
        metavar="FILENAME",
        help="Process only this file (e.g. services.txt). Omit to re-embed everything.",
    )
    args = parser.parse_args()
    run(source_filter=args.source)
