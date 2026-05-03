"""
Bronze to Silver ETL Pipeline.

This module transforms raw Bronze layer data into cleaned, standardized Silver layer data.

Data Sources:
    - Bronze Historical: s3://<bucket>/bronze/historical/public/orders/*.csv.gz
    - Bronze Historical: s3://<bucket>/bronze/historical/public/order_products/*.csv.gz
    - Bronze API: s3://<bucket>/bronze/api/product/*.json
    - Bronze API: s3://<bucket>/bronze/api/aisle/*.json
    - Bronze API: s3://<bucket>/bronze/api/department/*.json
    - Bronze Manual: s3://<bucket>/bronze/historical/manual/order_products_train/*.csv.gz

Data Targets (Silver):
    - silver/orders/ (partitioned by user_id % 100)
    - silver/order_products/ (partitioned by order_id % 100)
    - silver/products/ (joined product catalog with aisle and department names)
    - silver/order_products_train/ (ML labels, partitioned by user_id % 100)

Usage:
    export S3_BUCKET=nextcartai-dev-123456789012
    export SPARK_MASTER=local[*]
    python -m instacart_mlops.processing.bronze_to_silver

    # Or with custom paths:
    python -m instacart_mlops.processing.bronze_to_silver \
        --s3-bucket nextcartai-dev-123456789012 \
        --bronze-prefix bronze \
        --silver-prefix silver
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, BooleanType

from instacart_mlops.config import (
    S3_BUCKET,
    BRONZE_API_PREFIX,
    BRONZE_HISTORICAL_PREFIX,
    SILVER_PREFIX,
    SILVER_ORDERS_PATH,
    SILVER_ORDER_PRODUCTS_PATH,
    SILVER_PRODUCTS_PATH,
    SILVER_ORDER_PRODUCTS_TRAIN_PATH,
    SPARK_APP_NAME,
    SPARK_MASTER,
)
from instacart_mlops.processing.validator import SchemaValidator, ContractError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Bronze paths
BRONZE_ORDERS_PATH = f"{BRONZE_HISTORICAL_PREFIX}/public/orders/*.csv.gz"
BRONZE_ORDER_PRODUCTS_PATH = f"{BRONZE_HISTORICAL_PREFIX}/public/order_products/*.csv.gz"
BRONZE_PRODUCTS_PATH = f"{BRONZE_API_PREFIX}/product/*.json"
BRONZE_AISLES_PATH = f"{BRONZE_API_PREFIX}/aisle/*.json"
BRONZE_DEPARTMENTS_PATH = f"{BRONZE_API_PREFIX}/department/*.json"
BRONZE_ORDER_PRODUCTS_TRAIN_PATH = f"{BRONZE_HISTORICAL_PREFIX}/manual/order_products_train/*.csv.gz"

# Contract paths (relative to project root)
CONTRACTS_DIR = Path(__file__).parents[3] / "contracts"


# ── Spark Session ──────────────────────────────────────────────────────────────

def create_spark_session(app_name: str = SPARK_APP_NAME, master: str = SPARK_MASTER) -> SparkSession:
    """
    Create a Spark session configured for S3 access.

    Args:
        app_name: Name of the Spark application.
        master: Spark master URL.

    Returns:
        Configured SparkSession.
    """
    spark = (
        SparkSession.builder
        .appName(app_name)
        .master(master)
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        .config("spark.sql.parquet.mergeSchema", "true")
        .config("spark.hadoop.mapreduce.input.fileinputformat.input.dir.recursive", "true")
        .getOrCreate()
    )

    # Set log level
    spark.sparkContext.setLogLevel("WARN")

    logger.info(f"Spark session created: {app_name}")
    return spark


# ── Bronze Readers ─────────────────────────────────────────────────────────────

def read_bronze_orders(spark: SparkSession, bucket: str) -> DataFrame:
    """Read raw orders from Bronze layer."""
    path = f"s3://{bucket}/{BRONZE_ORDERS_PATH}"
    logger.info(f"Reading orders from {path}")
    return (
        spark.read
        .option("header", "true")
        .option("inferSchema", "true")
        .csv(path)
    )


def read_bronze_order_products(spark: SparkSession, bucket: str) -> DataFrame:
    """Read raw order_products from Bronze layer."""
    path = f"s3://{bucket}/{BRONZE_ORDER_PRODUCTS_PATH}"
    logger.info(f"Reading order_products from {path}")
    return (
        spark.read
        .option("header", "true")
        .option("inferSchema", "true")
        .csv(path)
    )


def read_bronze_products(spark: SparkSession, bucket: str) -> DataFrame:
    """Read product JSON files from Bronze layer."""
    path = f"s3://{bucket}/{BRONZE_PRODUCTS_PATH}"
    logger.info(f"Reading products from {path}")
    return spark.read.json(path)


def read_bronze_aisles(spark: SparkSession, bucket: str) -> DataFrame:
    """Read aisle JSON files from Bronze layer."""
    path = f"s3://{bucket}/{BRONZE_AISLES_PATH}"
    logger.info(f"Reading aisles from {path}")
    return spark.read.json(path)


def read_bronze_departments(spark: SparkSession, bucket: str) -> DataFrame:
    """Read department JSON files from Bronze layer."""
    path = f"s3://{bucket}/{BRONZE_DEPARTMENTS_PATH}"
    logger.info(f"Reading departments from {path}")
    return spark.read.json(path)


def read_bronze_order_products_train(spark: SparkSession, bucket: str) -> Optional[DataFrame]:
    """Read manually uploaded order_products_train from Bronze layer (for ML labels)."""
    path = f"s3://{bucket}/{BRONZE_ORDER_PRODUCTS_TRAIN_PATH}"
    logger.info(f"Reading order_products_train from {path}")
    try:
        return (
            spark.read
            .option("header", "true")
            .option("inferSchema", "true")
            .csv(path)
        )
    except Exception as e:
        logger.warning(f"Could not read order_products_train: {e}")
        return None


# ── Transformations ────────────────────────────────────────────────────────────

def transform_orders(df: DataFrame) -> DataFrame:
    """
    Transform raw orders into Silver layer format.

    Transformations:
    - Fill NULL days_since_prior_order with 0.0 (first order)
    - Add partition bucket column (user_id % 100)
    - Remove duplicates
    - Cast types explicitly
    """
    logger.info(f"Transforming orders: {df.count()} rows")

    silver = (
        df
        # Fill NULL days_since_prior_order with 0.0
        .withColumn("days_since_prior_order", F.coalesce(F.col("days_since_prior_order"), F.lit(0.0)))
        # Add partition bucket
        .withColumn("user_id_bucket", F.col("user_id") % 100)
        # Ensure correct types
        .withColumn("order_id", F.col("order_id").cast(IntegerType()))
        .withColumn("user_id", F.col("user_id").cast(IntegerType()))
        .withColumn("order_number", F.col("order_number").cast(IntegerType()))
        .withColumn("order_dow", F.col("order_dow").cast(IntegerType()))
        .withColumn("order_hour_of_day", F.col("order_hour_of_day").cast(IntegerType()))
        # Drop duplicates
        .dropDuplicates(["order_id"])
    )

    logger.info(f"Transformed orders: {silver.count()} rows")
    return silver


def transform_order_products(df: DataFrame) -> DataFrame:
    """
    Transform raw order_products into Silver layer format.

    Transformations:
    - Cast reordered to boolean
    - Add partition bucket column (order_id % 100)
    - Remove duplicates
    """
    logger.info(f"Transforming order_products: {df.count()} rows")

    silver = (
        df
        # Cast reordered to boolean
        .withColumn("reordered", F.col("reordered").cast(BooleanType()))
        # Add partition bucket
        .withColumn("order_id_bucket", F.col("order_id") % 100)
        # Ensure correct types
        .withColumn("order_id", F.col("order_id").cast(IntegerType()))
        .withColumn("product_id", F.col("product_id").cast(IntegerType()))
        .withColumn("add_to_cart_order", F.col("add_to_cart_order").cast(IntegerType()))
        # Drop duplicates
        .dropDuplicates(["order_id", "product_id"])
    )

    logger.info(f"Transformed order_products: {silver.count()} rows")
    return silver


def transform_products(
    products_df: DataFrame,
    aisles_df: DataFrame,
    departments_df: DataFrame,
) -> DataFrame:
    """
    Create a product catalog wide table by joining products with aisles and departments.

    Note: The API sends individual JSON files per record, so we need to:
    1. Deduplicate each source (keep latest by taking distinct on ID)
    2. Join them together
    """
    logger.info(f"Transforming products: {products_df.count()} products, "
                f"{aisles_df.count()} aisles, {departments_df.count()} departments")

    # Deduplicate each source (keep first occurrence of each ID)
    products_unique = products_df.dropDuplicates(["product_id"])
    aisles_unique = aisles_df.dropDuplicates(["aisle_id"])
    departments_unique = departments_df.dropDuplicates(["department_id"])

    # Rename columns to avoid conflicts
    aisles_renamed = aisles_unique.select(
        F.col("aisle_id").alias("aisle_id"),
        F.col("aisle").alias("aisle_name"),
    )
    departments_renamed = departments_unique.select(
        F.col("department_id").alias("department_id"),
        F.col("department").alias("department_name"),
    )

    # Join
    silver = (
        products_unique
        .join(aisles_renamed, on="aisle_id", how="left")
        .join(departments_renamed, on="department_id", how="left")
        .select(
            "product_id",
            "product_name",
            "aisle_id",
            "aisle_name",
            "department_id",
            "department_name",
        )
    )

    logger.info(f"Transformed products: {silver.count()} rows")
    return silver


# ── Writers ─────────────────────────────────────────────────────────────────────

def write_silver(df: DataFrame, bucket: str, path: str, partition_cols: Optional[list[str]] = None) -> None:
    """
    Write DataFrame to Silver layer as Parquet.

    Args:
        df: The DataFrame to write.
        bucket: S3 bucket name.
        path: S3 key prefix (relative to bucket root).
        partition_cols: Optional list of columns to partition by.
    """
    s3_path = f"s3://{bucket}/{path}"
    logger.info(f"Writing to {s3_path}")

    writer = (
        df.write
        .mode("overwrite")
        .format("parquet")
    )

    if partition_cols:
        writer = writer.partitionBy(partition_cols)

    writer.save(s3_path)
    logger.info(f"Successfully wrote {df.count()} rows to {s3_path}")


# ── Validation ──────────────────────────────────────────────────────────────────

def validate_silver(df: DataFrame, contract_name: str) -> bool:
    """
    Validate a Silver DataFrame against its contract.

    Args:
        df: The DataFrame to validate.
        contract_name: Name of the contract file (in contracts/silver/).

    Returns:
        True if validation passed, False otherwise.
    """
    contract_path = CONTRACTS_DIR / "silver" / f"{contract_name}.yml"
    if not contract_path.exists():
        logger.warning(f"Contract file not found: {contract_path}")
        return True  # Skip validation if contract doesn't exist

    validator = SchemaValidator(str(contract_path))
    is_valid, errors = validator.validate(df)

    if not is_valid:
        logger.error(f"Validation failed for {contract_name}:")
        for error in errors:
            logger.error(f"  - {error}")
        raise ContractError(f"Validation failed for {contract_name}: {len(errors)} errors")

    return True


# ── Main Pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(bucket: Optional[str] = None) -> None:
    """
    Run the complete Bronze → Silver ETL pipeline.

    Args:
        bucket: S3 bucket name. If None, uses S3_BUCKET from config.
    """
    bucket = bucket or S3_BUCKET
    if not bucket:
        raise ValueError("S3_BUCKET must be set via environment variable or argument")

    logger.info(f"Starting Bronze → Silver ETL pipeline")
    logger.info(f"S3 Bucket: {bucket}")

    spark = create_spark_session()

    try:
        # ── Step 1: Process Orders ──────────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("Step 1: Processing Orders")
        logger.info("=" * 60)

        bronze_orders = read_bronze_orders(spark, bucket)
        silver_orders = transform_orders(bronze_orders)
        validate_silver(silver_orders, "orders")
        write_silver(silver_orders, bucket, SILVER_ORDERS_PATH, partition_cols=["user_id_bucket"])

        # ── Step 2: Process Order Products ──────────────────────────────────────
        logger.info("=" * 60)
        logger.info("Step 2: Processing Order Products")
        logger.info("=" * 60)

        bronze_order_products = read_bronze_order_products(spark, bucket)
        silver_order_products = transform_order_products(bronze_order_products)
        validate_silver(silver_order_products, "order_products")
        write_silver(silver_order_products, bucket, SILVER_ORDER_PRODUCTS_PATH, partition_cols=["order_id_bucket"])

        # ── Step 3: Process Product Catalog ─────────────────────────────────────
        logger.info("=" * 60)
        logger.info("Step 3: Processing Product Catalog")
        logger.info("=" * 60)

        bronze_products = read_bronze_products(spark, bucket)
        bronze_aisles = read_bronze_aisles(spark, bucket)
        bronze_departments = read_bronze_departments(spark, bucket)
        silver_products = transform_products(bronze_products, bronze_aisles, bronze_departments)
        validate_silver(silver_products, "products")
        write_silver(silver_products, bucket, SILVER_PRODUCTS_PATH)

        # ── Step 4: Process Order Products Train (ML Labels) ────────────────────
        logger.info("=" * 60)
        logger.info("Step 4: Processing Order Products Train (ML Labels)")
        logger.info("=" * 60)

        bronze_train = read_bronze_order_products_train(spark, bucket)
        if bronze_train is not None:
            silver_train = transform_order_products(bronze_train)
            write_silver(silver_train, bucket, SILVER_ORDER_PRODUCTS_TRAIN_PATH, partition_cols=["order_id_bucket"])
        else:
            logger.warning("Skipping order_products_train - source data not found")

        # ── Summary ─────────────────────────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("ETL Pipeline Complete!")
        logger.info("=" * 60)
        logger.info(f"Silver layer paths in s3://{bucket}/:")
        logger.info(f"  - {SILVER_ORDERS_PATH}/")
        logger.info(f"  - {SILVER_ORDER_PRODUCTS_PATH}/")
        logger.info(f"  - {SILVER_PRODUCTS_PATH}/")
        if bronze_train is not None:
            logger.info(f"  - {SILVER_ORDER_PRODUCTS_TRAIN_PATH}/")

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        raise
    finally:
        spark.stop()


# ── CLI Entry Point ────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bronze to Silver ETL Pipeline")
    parser.add_argument(
        "--s3-bucket",
        type=str,
        default=None,
        help="S3 bucket name (overrides S3_BUCKET env var)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(bucket=args.s3_bucket)