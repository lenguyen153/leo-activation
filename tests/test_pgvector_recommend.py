from __future__ import annotations

"""
PGVector-based Product Recommendation Demo
------------------------------------------
- Async FastAPI-friendly architecture
- SentenceTransformers for semantic embeddings
- pgvector for similarity search
- Retail-style profiles & products
"""

import asyncio
import hashlib
import json
import logging
import os
from typing import List, Dict, Optional, Sequence

import numpy as np
import asyncpg
from sentence_transformers import SentenceTransformer

# ============================================================
# Logging
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pgvector-reco")

# ============================================================
# Configuration
# ============================================================

DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:12345678@localhost:5435/test_pgvector"
)

POOL_MIN_SIZE = 5
POOL_MAX_SIZE = 20

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

# Load embedding model ONCE (important for prod services)
VECTOR_MODEL = SentenceTransformer(MODEL_NAME)
VECTOR_DIM = VECTOR_MODEL.get_sentence_embedding_dimension()

PROFILE_VECTOR_SIZE = VECTOR_DIM
PRODUCT_VECTOR_SIZE = VECTOR_DIM * 3

# ============================================================
# Utility Functions
# ============================================================

def pgvector_to_numpy(v) -> Optional[np.ndarray]:
    """
    Convert pgvector output to numpy array.
    asyncpg may return:
      - list[float]
      - string "[0.1,0.2,...]"
      - None
    """
    if v is None:
        return None

    if isinstance(v, list):
        return np.asarray(v, dtype=np.float32)

    if isinstance(v, str):
        return np.fromstring(v.strip("[]"), sep=",", dtype=np.float32)

    raise TypeError(f"Unsupported pgvector type: {type(v)}")


def string_to_point_id(text: str) -> int:
    """
    Deterministic numeric ID from string.
    Allows stable IDs without DB sequences.
    """
    return int(hashlib.sha256(text.encode()).hexdigest(), 16) % (10**16)


def embed_text(text: str) -> np.ndarray:
    """
    Safe text → vector embedding.
    Empty input returns zero vector.
    """
    if not text:
        return np.zeros(VECTOR_DIM, dtype=np.float32)
    return np.asarray(
        VECTOR_MODEL.encode(text, convert_to_tensor=False),
        dtype=np.float32
    )


def normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize vector for cosine similarity."""
    n = np.linalg.norm(v)
    return (v / n).astype(np.float32) if n > 0 else v


def vec_to_pg(v: np.ndarray) -> str:
    """Convert numpy vector → pgvector literal."""
    return "[" + ",".join(map(str, v.tolist())) + "]"

# ============================================================
# Vector Builders (Async-safe)
# ============================================================

async def build_profile_vector(
    page_views: List[str],
    purchases: List[str],
    interests: List[str],
) -> Optional[np.ndarray]:
    """
    Build a semantic profile vector.
    Weighting reflects intent strength.
    """

    if not any([page_views, purchases, interests]):
        return None

    def _compute():
        pv = np.mean([embed_text(x) for x in page_views], axis=0) if page_views else 0
        pu = np.mean([embed_text(x) for x in purchases], axis=0) if purchases else 0
        it = np.mean([embed_text(x) for x in interests], axis=0) if interests else 0

        combined = 0.3 * pv + 0.4 * pu + 0.3 * it
        return normalize(combined)

    return await asyncio.to_thread(_compute)


async def build_product_vector(
    name: str,
    category: str,
    keywords: List[str],
) -> np.ndarray:
    """
    Product vector = [name | category | keyword-mean]
    """

    def _compute():
        name_v = embed_text(name)
        cat_v = embed_text(category)
        kw_v = (
            np.mean([embed_text(k) for k in keywords], axis=0)
            if keywords else np.zeros(VECTOR_DIM)
        )
        return normalize(np.concatenate([name_v, cat_v, kw_v]))

    return await asyncio.to_thread(_compute)

# ============================================================
# Database Schema
# ============================================================

async def ensure_schema(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS profiles (
                id BIGINT PRIMARY KEY,
                profile_id TEXT UNIQUE,
                embedding VECTOR({PROFILE_VECTOR_SIZE}),
                payload JSONB
            );

            CREATE TABLE IF NOT EXISTS products (
                id BIGINT PRIMARY KEY,
                product_id TEXT UNIQUE,
                embedding VECTOR({PRODUCT_VECTOR_SIZE}),
                name TEXT,
                category TEXT,
                additional_info JSONB
            );
        """)

        logger.info("DB schema ready.")

# ============================================================
# Upserts
# ============================================================

async def upsert_profile(pool: asyncpg.Pool, profile: Dict):
    vec = await build_profile_vector(
        profile["page_view_keywords"],
        profile["purchase_keywords"],
        profile["interest_keywords"],
    )

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO profiles (id, profile_id, embedding, payload)
            VALUES ($1, $2, $3::vector, $4::jsonb)
            ON CONFLICT (id)
            DO UPDATE SET embedding=EXCLUDED.embedding, payload=EXCLUDED.payload;
            """,
            string_to_point_id(profile["profile_id"]),
            profile["profile_id"],
            vec_to_pg(vec),
            json.dumps(profile),
        )


async def batch_upsert_products(pool: asyncpg.Pool, products: Sequence[Dict]):
    tasks = [
        build_product_vector(p["name"], p["category"], p["keywords"])
        for p in products
    ]
    vectors = await asyncio.gather(*tasks)

    rows = [
        (
            string_to_point_id(p["product_id"]),
            p["product_id"],
            vec_to_pg(v),
            p["name"],
            p["category"],
            json.dumps(p),
        )
        for p, v in zip(products, vectors)
    ]

    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO products (id, product_id, embedding, name, category, additional_info)
            VALUES ($1, $2, $3::vector, $4, $5, $6::jsonb)
            ON CONFLICT (id)
            DO UPDATE SET embedding=EXCLUDED.embedding;
            """,
            rows,
        )

# ============================================================
# Recommendation Query
# ============================================================

async def recommend_products(pool: asyncpg.Pool, profile_id: str, limit: int = 5):
    pid = string_to_point_id(profile_id)

    async with pool.acquire() as conn:
        rec = await conn.fetchrow(
            "SELECT embedding FROM profiles WHERE id=$1", pid
        )

        profile_vec = pgvector_to_numpy(rec["embedding"])
        query_vec = normalize(np.concatenate([profile_vec] * 3))

        rows = await conn.fetch(
            """
            SELECT product_id, name, category,
                   1 - (embedding <=> $1::vector) AS score
            FROM products
            ORDER BY embedding <=> $1::vector
            LIMIT $2;
            """,
            vec_to_pg(query_vec),
            limit,
        )

        return [dict(r) for r in rows]

# ============================================================
# Sample Data
# ============================================================

SAMPLE_PROFILES = [
    {
        "profile_id": "u_runner",
        "page_view_keywords": ["running shoes", "marathon training"],
        "purchase_keywords": ["nike air zoom"],
        "interest_keywords": ["fitness", "outdoor"],
    },
    {
        "profile_id": "u_yogi",
        "page_view_keywords": ["yoga mat", "stretching"],
        "purchase_keywords": ["eco yoga mat"],
        "interest_keywords": ["wellness", "mindfulness"],
    },
    {
        "profile_id": "u_gamer",
        "page_view_keywords": ["gaming mouse", "mechanical keyboard"],
        "purchase_keywords": [],
        "interest_keywords": ["esports", "rgb setup"],
    },
    {
        "profile_id": "u_traveler",
        "page_view_keywords": ["carry on luggage"],
        "purchase_keywords": ["travel backpack"],
        "interest_keywords": ["adventure"],
    },
    {
        "profile_id": "u_fashion",
        "page_view_keywords": ["streetwear hoodie"],
        "purchase_keywords": ["sneakers"],
        "interest_keywords": ["urban fashion"],
    },
]

SAMPLE_PRODUCTS = [
    {"product_id": "p1", "name": "Nike Running Shoes", "category": "Sports", "keywords": ["running", "marathon"]},
    {"product_id": "p2", "name": "Eco Yoga Mat", "category": "Fitness", "keywords": ["yoga", "eco"]},
    {"product_id": "p3", "name": "Gaming Mouse", "category": "Electronics", "keywords": ["gaming", "dpi"]},
    {"product_id": "p4", "name": "Mechanical Keyboard", "category": "Electronics", "keywords": ["keyboard", "rgb"]},
    {"product_id": "p5", "name": "Travel Backpack", "category": "Travel", "keywords": ["backpack", "carry on"]},
    {"product_id": "p6", "name": "Hard Shell Luggage", "category": "Travel", "keywords": ["luggage", "airport"]},
    {"product_id": "p7", "name": "Streetwear Hoodie", "category": "Fashion", "keywords": ["hoodie", "street"]},
    {"product_id": "p8", "name": "Sneakers", "category": "Fashion", "keywords": ["sneakers", "urban"]},
    {"product_id": "p9", "name": "Foam Roller", "category": "Fitness", "keywords": ["recovery", "muscle"]},
    {"product_id": "p10", "name": "Running Socks", "category": "Sports", "keywords": ["running", "comfort"]},
]

# ============================================================
# Main Execution
# ============================================================

async def main():
    pool = await asyncpg.create_pool(DB_DSN, min_size=POOL_MIN_SIZE, max_size=POOL_MAX_SIZE)

    try:
        await ensure_schema(pool)

        for p in SAMPLE_PROFILES:
            await upsert_profile(pool, p)

        await batch_upsert_products(pool, SAMPLE_PRODUCTS)

        # Run recommendations for 3 profiles
        for pid in ["u_runner", "u_yogi", "u_gamer"]:
            recs = await recommend_products(pool, pid)
            logger.info(f"\nRecommendations for {pid}:")
            for r in recs:
                logger.info(f"  {r['name']}  (score={r['score']:.3f})")

    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
