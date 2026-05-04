"""
Seed RDS PostgreSQL with historical Instacart data.

Data sources (references/imba_data/):
  - orders.csv            : 3.4M rows  — all orders with metadata
  - order_products__prior.csv.gz : ~32M rows — product line items for prior orders

Schema is derived from references/ERD.png (no data_dictionary.md exists).

Usage:
    export RDS_HOST=... RDS_USER=... RDS_PASSWORD=...
    python -m instacart_mlops.ingestion.rds_seeder
    python -m instacart_mlops.ingestion.rds_seeder --force   # truncate and re-seed
"""

import argparse
import gzip
import io
import logging
import time
from pathlib import Path

import pandas as pd

import psycopg2
from sqlalchemy import create_engine, text

from instacart_mlops.config import DATABASE_URL, RDS_HOST, RDS_PASSWORD, RDS_DB, RDS_PORT, RDS_USER

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

IMBA_DIR = Path(__file__).parents[2] / "references" / "imba_data"

# ── DDL ───────────────────────────────────────────────────────────────────────
# Schema derived from ERD.png.  days_since_prior_order is NULL for a user's
# very first order, so it cannot be NOT NULL.
_DDL = """
CREATE TABLE IF NOT EXISTS orders (
    order_id                INTEGER      PRIMARY KEY,
    user_id                 INTEGER      NOT NULL,
    eval_set                VARCHAR(10)  NOT NULL,
    order_number            SMALLINT     NOT NULL,
    order_dow               SMALLINT     NOT NULL,
    order_hour_of_day       SMALLINT     NOT NULL,
    days_since_prior_order  FLOAT
);

CREATE TABLE IF NOT EXISTS order_products (
    order_id          INTEGER  NOT NULL REFERENCES orders(order_id),
    product_id        INTEGER  NOT NULL,
    add_to_cart_order SMALLINT NOT NULL,
    reordered         BOOLEAN  NOT NULL,
    PRIMARY KEY (order_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_op_order_id ON order_products (order_id);
CREATE INDEX IF NOT EXISTS idx_op_product_id ON order_products (product_id);
"""

_ORDERS_COLS = [
    "order_id", "user_id", "eval_set", "order_number",
    "order_dow", "order_hour_of_day", "days_since_prior_order",
]
_ORDER_PRODUCTS_COLS = ["order_id", "product_id", "add_to_cart_order", "reordered"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pg_conn(database_url: str) -> psycopg2.extensions.connection:
    # SQLAlchemy URL → psycopg2 DSN (strip driver suffix)
    dsn = database_url.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(
        dsn,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )


def _is_populated(engine, table: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {table} LIMIT 1)")).scalar()


def _copy(cursor, sql: str, filepath: Path, compressed: bool) -> None:
    opener = gzip.open(filepath, "rt") if compressed else open(filepath, "r")
    with opener as fh:
        cursor.copy_expert(sql, fh)


def _copy_chunked(
    database_url: str,
    sql: str,
    filepath: Path,
    chunk_size: int = 2_000_000,
) -> int:
    """Stream a large CSV/gzip into Postgres in chunks via pandas, fresh connection per batch.

    pandas uses C-level CSV parsing (much faster than Python readline).
    Each chunk is its own transaction so a dropped connection only loses one batch.
    If the load fails partway, re-run with --force to truncate and restart cleanly.
    """
    compression = "gzip" if filepath.suffix == ".gz" else None
    total = 0
    for chunk_df in pd.read_csv(filepath, compression=compression, chunksize=chunk_size):
        buf = io.StringIO()
        chunk_df.to_csv(buf, index=False, header=True)
        buf.seek(0)
        conn = _pg_conn(database_url)
        try:
            with conn.cursor() as cur:
                cur.copy_expert(sql, buf)
            conn.commit()
        finally:
            conn.close()
        total += len(chunk_df)
        log.info(f"  ... {total:,} rows inserted")
    return total


# ── Schema ────────────────────────────────────────────────────────────────────

def ensure_schema(engine) -> None:
    with engine.connect() as conn:
        conn.execute(text(_DDL))
        conn.commit()
    log.info("Schema ensured (orders, order_products).")


# ── Seed functions ────────────────────────────────────────────────────────────

def seed_orders(pg_conn, engine, force: bool) -> None:
    if not force and _is_populated(engine, "orders"):
        log.info("orders already populated — skipping (use --force to re-seed).")
        return

    filepath = IMBA_DIR / "orders.csv"
    if not filepath.exists():
        raise FileNotFoundError(filepath)

    copy_sql = (
        f"COPY orders ({', '.join(_ORDERS_COLS)}) "
        "FROM STDIN WITH (FORMAT CSV, HEADER, NULL '')"
    )

    log.info(f"Loading orders from {filepath.name} …")
    t0 = time.perf_counter()
    with pg_conn.cursor() as cur:
        if force:
            cur.execute("TRUNCATE TABLE orders CASCADE")
            log.info("Truncated orders (CASCADE).")
        _copy(cur, copy_sql, filepath, compressed=False)
    pg_conn.commit()
    log.info(f"orders loaded in {time.perf_counter() - t0:.1f}s.")


def seed_order_products(database_url: str, pg_conn, engine, force: bool) -> None:
    if not force and _is_populated(engine, "order_products"):
        log.info("order_products already populated — skipping.")
        return

    filepath = IMBA_DIR / "order_products__prior.csv.gz"
    if not filepath.exists():
        raise FileNotFoundError(filepath)

    copy_sql = (
        f"COPY order_products ({', '.join(_ORDER_PRODUCTS_COLS)}) "
        "FROM STDIN WITH (FORMAT CSV, HEADER, NULL '')"
    )

    if force:
        with pg_conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE order_products")
        pg_conn.commit()
        log.info("Truncated order_products.")

    log.info(f"Loading order_products from {filepath.name} (~32M rows) in 500k-row chunks …")
    t0 = time.perf_counter()
    total = _copy_chunked(database_url, copy_sql, filepath)
    log.info(f"order_products loaded {total:,} rows in {time.perf_counter() - t0:.1f}s.")


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed RDS with Instacart historical data.")
    parser.add_argument(
        "--force", action="store_true",
        help="Truncate existing tables and re-seed from scratch.",
    )
    args = parser.parse_args()

    # Validate required environment variables
    if not RDS_HOST or not RDS_PASSWORD:
        raise ValueError(
            "RDS_HOST and RDS_PASSWORD environment variables are required. "
            f"Got: RDS_HOST={RDS_HOST!r}, RDS_PASSWORD={'***' if RDS_PASSWORD else ''!r}"
        )

    if not DATABASE_URL:
        raise ValueError(
            f"Could not construct DATABASE_URL. "
            f"RDS_HOST={RDS_HOST!r}, RDS_PORT={RDS_PORT!r}, "
            f"RDS_DB={RDS_DB!r}, RDS_USER={RDS_USER!r}"
        )

    log.info(f"Connecting to RDS at {RDS_HOST}:{RDS_PORT}/{RDS_DB} as {RDS_USER}")
    log.info(f"DATABASE_URL: {DATABASE_URL[:30]}...")  # Log first 30 chars for debugging

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    pg_conn = _pg_conn(DATABASE_URL)
    pg_conn.autocommit = False

    try:
        ensure_schema(engine)
        seed_orders(pg_conn, engine, force=args.force)
        seed_order_products(DATABASE_URL, pg_conn, engine, force=args.force)
        log.info("Seed complete.")
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        pg_conn.close()
        engine.dispose()


if __name__ == "__main__":
    main()
