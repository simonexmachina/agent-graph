"""Vector search helpers for the SQLite backend.

Three modes (set at backend construction time):
- "sqlite-vec": Uses the sqlite-vec extension's vec_distance_cosine() scalar
  function (O(n) scan, SIMD-accelerated). Falls through to numpy on failure.
- "numpy":      Loads all embeddings from the DB into Python, computes cosine
  similarity with numpy. Falls through to BM25-only on ImportError.
- "bm25-only":  Skips vector search; BM25 (FTS5) ranking only.
"""

from __future__ import annotations

import struct
from typing import Any

from agentgraph.perf import timed

# ---------------------------------------------------------------------------
# Blob encoding
# ---------------------------------------------------------------------------

def pack_embedding(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_embedding(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


# ---------------------------------------------------------------------------
# Extension loading
# ---------------------------------------------------------------------------

async def load_sqlite_vec(conn: Any) -> bool:
    """Load the sqlite-vec extension into *conn*. Returns True on success."""
    try:
        import sqlite_vec  # type: ignore[import-untyped]
    except ImportError:
        return False
    try:
        # Must run on the aiosqlite background thread via _execute,
        # passing the underlying sqlite3 connection.
        def _do_load(db: Any) -> None:
            db.enable_load_extension(True)
            sqlite_vec.load(db)
            db.enable_load_extension(False)

        await conn._execute(_do_load, conn._connection)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Vector search
# ---------------------------------------------------------------------------

async def vector_ranked(
    conn: Any,
    query_vec: list[float],
    entity_types: list[str] | None,
    limit: int,
    mode: str,
    vec_loaded: bool,
    platform: str | None = None,
) -> list[tuple[str, int]]:
    """Return (entity_id, rank) pairs with rank starting at 1 (best).

    Returns an empty list when mode is "bm25-only" or when no embeddings exist.
    """
    if mode == "bm25-only":
        return []

    type_clause = ""
    type_params: list[Any] = []
    if entity_types:
        placeholders = ",".join("?" * len(entity_types))
        type_clause = f"AND entity_type IN ({placeholders})"
        type_params = list(entity_types)
    if platform:
        type_clause += " AND platform = ?"
        type_params.append(platform)

    query_blob = pack_embedding(query_vec)
    candidate_limit = limit * 5

    # ---- sqlite-vec path ----
    if mode == "sqlite-vec" and vec_loaded:
        try:
            with timed("sqlite.vector_ranked.sqlite_vec", limit=limit, platform=platform):
                cursor = await conn.execute(
                    f"""
                    SELECT id, vec_distance_cosine(content_embedding, ?) AS dist
                    FROM entities
                    WHERE content_embedding IS NOT NULL {type_clause}
                    ORDER BY dist ASC
                    LIMIT ?
                    """,
                    [query_blob, *type_params, candidate_limit],
                )
                rows = await cursor.fetchall()
            return [(row[0], i + 1) for i, row in enumerate(rows)]
        except Exception:
            pass  # fall through to numpy

    # ---- numpy path ----
    try:
        import numpy as np

        with timed("sqlite.vector_ranked.numpy", limit=limit, platform=platform):
            cursor = await conn.execute(
                f"SELECT id, content_embedding FROM entities WHERE content_embedding IS NOT NULL {type_clause}",
                type_params,
            )
            rows = await cursor.fetchall()
            if not rows:
                return []

            q = np.array(query_vec, dtype=np.float32)
            q_norm = float(np.linalg.norm(q))
            if q_norm == 0:
                return []
            q = q / q_norm

            scored: list[tuple[str, float]] = []
            for entity_id, blob in rows:
                if not blob:
                    continue
                vec = np.array(unpack_embedding(bytes(blob)), dtype=np.float32)
                norm = float(np.linalg.norm(vec))
                if norm == 0:
                    continue
                sim = float(np.dot(q, vec / norm))
                scored.append((entity_id, sim))

            scored.sort(key=lambda x: x[1], reverse=True)
            return [(eid, i + 1) for i, (eid, _) in enumerate(scored[:candidate_limit])]

    except ImportError:
        return []
