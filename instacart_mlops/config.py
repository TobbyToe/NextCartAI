import os

# ── RDS Configuration ──────────────────────────────────────────────────────────
RDS_HOST = os.environ["RDS_HOST"]
RDS_PORT = os.environ.get("RDS_PORT", "5432")
RDS_DB = os.environ.get("RDS_DB", "instacart")
RDS_USER = os.environ["RDS_USER"]
RDS_PASSWORD = os.environ["RDS_PASSWORD"]

DATABASE_URL = (
    f"postgresql+psycopg2://{RDS_USER}:{RDS_PASSWORD}@{RDS_HOST}:{RDS_PORT}/{RDS_DB}"
)

# ── S3 Path Configuration ──────────────────────────────────────────────────────
# S3 bucket name (set via Terraform output or environment variable)
S3_BUCKET = os.environ.get("S3_BUCKET", "")

# Bronze layer paths
BRONZE_API_PREFIX = "bronze/api"
BRONZE_HISTORICAL_PREFIX = "bronze/historical"
BRONZE_STREAM_PREFIX = "bronze/stream"

# Silver layer paths
SILVER_PREFIX = "silver"
SILVER_ORDERS_PATH = f"{SILVER_PREFIX}/orders"
SILVER_ORDER_PRODUCTS_PATH = f"{SILVER_PREFIX}/order_products"
SILVER_PRODUCTS_PATH = f"{SILVER_PREFIX}/products"
SILVER_AISLES_PATH = f"{SILVER_PREFIX}/aisles"
SILVER_DEPARTMENTS_PATH = f"{SILVER_PREFIX}/departments"
SILVER_STREAM_EVENTS_PATH = f"{SILVER_PREFIX}/stream_events"
SILVER_ORDER_PRODUCTS_TRAIN_PATH = f"{SILVER_PREFIX}/order_products_train"

# Gold layer paths
GOLD_PREFIX = "gold"
GOLD_FEATURES_PATH = f"{GOLD_PREFIX}/features"
GOLD_PREDICTIONS_PATH = f"{GOLD_PREFIX}/predictions"

# ── Spark Configuration ────────────────────────────────────────────────────────
SPARK_APP_NAME = "nextcartai-bronze-to-silver"
SPARK_MASTER = os.environ.get("SPARK_MASTER", "local[*]")
