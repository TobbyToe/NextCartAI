"""
Unit tests for the Schema Validator module.
"""

import pytest
from pathlib import Path
import tempfile
import yaml

from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, IntegerType, StringType, DoubleType

from instacart_mlops.processing.validator import SchemaValidator, validate_contract


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def spark():
    """Create a local Spark session for testing."""
    spark = (
        SparkSession.builder
        .appName("test-validator")
        .master("local[1]")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .getOrCreate()
    )
    yield spark
    spark.stop()


@pytest.fixture
def valid_contract_file():
    """Create a temporary valid contract YAML file."""
    contract = {
        "name": "test_table",
        "description": "A test table",
        "fields": [
            {"name": "id", "type": "integer", "nullable": False},
            {"name": "name", "type": "string", "nullable": False},
            {"name": "score", "type": "double", "nullable": True, "min_value": 0, "max_value": 100},
        ]
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        yaml.dump(contract, f)
        return f.name


@pytest.fixture
def sample_dataframe(spark):
    """Create a sample DataFrame that matches the valid contract."""
    data = [
        (1, "Alice", 85.5),
        (2, "Bob", 92.0),
        (3, "Charlie", 78.3),
    ]
    schema = StructType([
        StructField("id", IntegerType(), False),
        StructField("name", StringType(), False),
        StructField("score", DoubleType(), True),
    ])
    return spark.createDataFrame(data, schema)


# ── Tests: Contract File Validation ───────────────────────────────────────────

class TestContractFileValidation:
    """Tests for validate_contract_file() method."""

    def test_valid_contract_file(self, valid_contract_file):
        is_valid, errors = validate_contract(valid_contract_file)
        assert is_valid is True
        assert len(errors) == 0

    def test_missing_name(self):
        contract = {
            "fields": [
                {"name": "id", "type": "integer"},
            ]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(contract, f)
            is_valid, errors = validate_contract(f.name)
        assert is_valid is False
        assert any("name" in e for e in errors)

    def test_missing_fields(self):
        contract = {"name": "test"}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(contract, f)
            is_valid, errors = validate_contract(f.name)
        assert is_valid is False
        assert any("fields" in e for e in errors)

    def test_unknown_type(self):
        contract = {
            "name": "test",
            "fields": [
                {"name": "id", "type": "unknown_type"},
            ]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(contract, f)
            is_valid, errors = validate_contract(f.name)
        assert is_valid is False
        assert any("unknown_type" in e for e in errors)

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            SchemaValidator("/nonexistent/path.yml")


# ── Tests: DataFrame Validation ───────────────────────────────────────────────

class TestDataFrameValidation:
    """Tests for validate() method on DataFrames."""

    def test_valid_dataframe(self, spark, valid_contract_file, sample_dataframe):
        validator = SchemaValidator(valid_contract_file)
        is_valid, errors = validator.validate(sample_dataframe)
        assert is_valid is True
        assert len(errors) == 0

    def test_missing_required_field(self, spark):
        # Create DataFrame missing the 'name' field
        data = [(1, 85.5), (2, 92.0)]
        schema = StructType([
            StructField("id", IntegerType(), False),
            StructField("score", DoubleType(), True),
        ])
        df = spark.createDataFrame(data, schema)

        validator = SchemaValidator("contracts/silver/orders.yml")
        # orders contract requires user_id, eval_set, etc.
        is_valid, errors = validator.validate(df)
        assert is_valid is False
        assert any("Missing required field" in e for e in errors)

    def test_wrong_data_type(self, spark):
        data = [("1", "Alice"), ("2", "Bob")]
        schema = StructType([
            StructField("id", StringType(), False),  # Should be integer
            StructField("name", StringType(), False),
        ])
        df = spark.createDataFrame(data, schema)

        contract = {
            "name": "test",
            "fields": [
                {"name": "id", "type": "integer", "nullable": False},
                {"name": "name", "type": "string", "nullable": False},
            ]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(contract, f)
            validator = SchemaValidator(f.name)
            is_valid, errors = validator.validate(df)

        assert is_valid is False
        assert any("has type" in e and "expected integer" in e for e in errors)

    def test_null_in_non_nullable_field(self, spark):
        data = [(1, "Alice"), (None, "Bob")]
        schema = StructType([
            StructField("id", IntegerType(), True),  # Allows null
            StructField("name", StringType(), False),
        ])
        df = spark.createDataFrame(data, schema)

        contract = {
            "name": "test",
            "fields": [
                {"name": "id", "type": "integer", "nullable": False},
                {"name": "name", "type": "string", "nullable": False},
            ]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(contract, f)
            validator = SchemaValidator(f.name)
            is_valid, errors = validator.validate(df)

        assert is_valid is False
        assert any("NULL values" in e and "NOT NULL" in e for e in errors)

    def test_min_value_constraint_violation(self, spark):
        data = [(1, -5), (2, 50), (3, 100)]
        schema = StructType([
            StructField("id", IntegerType(), False),
            StructField("score", IntegerType(), False),
        ])
        df = spark.createDataFrame(data, schema)

        contract = {
            "name": "test",
            "fields": [
                {"name": "id", "type": "integer", "nullable": False},
                {"name": "score", "type": "integer", "nullable": False, "min_value": 0},
            ]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(contract, f)
            validator = SchemaValidator(f.name)
            is_valid, errors = validator.validate(df)

        assert is_valid is False
        assert any("below minimum" in e for e in errors)

    def test_max_value_constraint_violation(self, spark):
        data = [(1, 150), (2, 50)]
        schema = StructType([
            StructField("id", IntegerType(), False),
            StructField("score", IntegerType(), False),
        ])
        df = spark.createDataFrame(data, schema)

        contract = {
            "name": "test",
            "fields": [
                {"name": "id", "type": "integer", "nullable": False},
                {"name": "score", "type": "integer", "nullable": False, "max_value": 100},
            ]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(contract, f)
            validator = SchemaValidator(f.name)
            is_valid, errors = validator.validate(df)

        assert is_valid is False
        assert any("above maximum" in e for e in errors)

    def test_allowed_values_constraint_violation(self, spark):
        data = [(1, "invalid_status"), (2, "active")]
        schema = StructType([
            StructField("id", IntegerType(), False),
            StructField("status", StringType(), False),
        ])
        df = spark.createDataFrame(data, schema)

        contract = {
            "name": "test",
            "fields": [
                {"name": "id", "type": "integer", "nullable": False},
                {"name": "status", "type": "string", "nullable": False, "allowed_values": ["active", "inactive"]},
            ]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(contract, f)
            validator = SchemaValidator(f.name)
            is_valid, errors = validator.validate(df)

        assert is_valid is False
        assert any("not in allowed values" in e for e in errors)


# ── Tests: Get Spark Schema ───────────────────────────────────────────────────

class TestGetSparkSchema:
    """Tests for get_spark_schema() method."""

    def test_generates_correct_schema(self, valid_contract_file):
        validator = SchemaValidator(valid_contract_file)
        schema = validator.get_spark_schema()

        assert isinstance(schema, StructType)
        assert len(schema.fields) == 3

        field_names = [f.name for f in schema.fields]
        assert "id" in field_names
        assert "name" in field_names
        assert "score" in field_names