"""
Configuration module for NextCartAI.

Reads configuration from environment variables with sensible defaults.

Environment variables:
    - S3_BUCKET: AWS S3 bucket name (default: nextcartai-dev-<account_id>)
    - BRONZE_PREFIX: S3 prefix for Bronze layer (default: bronze)
    - SILVER_PREFIX: S3 prefix for Silver layer (default: silver)
    - GOLD_PREFIX: S3 prefix for Gold layer (default: gold)
    - RDS_HOST: PostgreSQL host
    - RDS_PORT: PostgreSQL port (default: 5432)
    - RDS_DB: PostgreSQL database name (default: instacart)
    - RDS_USER: PostgreSQL username (default: instacart_admin)
    - RDS_PASSWORD: PostgreSQL password
    - SPARK_APP_NAME: Spark application name (default: NextCartAI-BronzeToSilver)
    - SPARK_MASTER: Spark master URL (default: local[*])
"""

import os
from pathlib import Path

# ── AWS / S3 ──────────────────────────────────────────────────────────────────

ACCOUNT_ID = os.getenv("AWS_ACCOUNT_ID", "")
S3_BUCKET = os.getenv("S3_BUCKET", f"nextcartai-dev-{ACCOUNT_ID}" if ACCOUNT_ID else "")

BRONZE_PREFIX = os.getenv("BRONZE_PREFIX", "bronze")
SILVER_PREFIX = os.getenv("SILVER_PREFIX", "silver")
GOLD_PREFIX = os.getenv("GOLD_PREFIX", "gold")

# Bronze paths
BRONZE_API_PREFIX = f"{BRONZE_PREFIX}/api"
BRONZE_HISTORICAL_PREFIX = f"{BRONZE_PREFIX}/historical"

# Silver paths
SILVER_ORDERS_PATH = f"{SILVER_PREFIX}/orders"
SILVER_ORDER_PRODUCTS_PATH = f"{SILVER_PREFIX}/order_products"
SILVER_PRODUCTS_PATH = f"{SILVER_PREFIX}/products"
SILVER_ORDER_PRODUCTS_TRAIN_PATH = f"{SILVER_PREFIX}/order_products_train"

# ── PostgreSQL / RDS ──────────────────────────────────────────────────────────

RDS_HOST = os.getenv("RDS_HOST", "")
RDS_PORT = os.getenv("RDS_PORT", "5432")
RDS_DB = os.getenv("RDS_DB", "instacart")
RDS_USER = os.getenv("RDS_USER", "instacart_admin")
RDS_PASSWORD = os.getenv("RDS_PASSWORD", "")

# Build DATABASE_URL for SQLAlchemy
DATABASE_URL = (
    f"postgresql://{RDS_USER}:{RDS_PASSWORD}@{RDS_HOST}:{RDS_PORT}/{RDS_DB}"
    if RDS_HOST and RDS_PASSWORD
    else ""
)

# ── Spark ─────────────────────────────────────────────────────────────────────

SPARK_APP_NAME = os.getenv("SPARK_APP_NAME", "NextCartAI-BronzeToSilver")
SPARK_MASTER = os.getenv("SPARK_MASTER", "local[*]")

# ── Project paths ─────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parents[1]
CONTRACTS_DIR = PROJECT_ROOT / "contracts"

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")