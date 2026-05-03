"""
Schema Validator for Data Contracts.

This module provides a lightweight validator that reads YAML contract files
and validates Spark DataFrames against the defined schema.

Usage:
    from instacart_mlops.processing.validator import SchemaValidator

    validator = SchemaValidator("contracts/silver/orders.yml")
    is_valid, errors = validator.validate(df)
    if not is_valid:
        for error in errors:
            logger.error(error)
"""

import logging
from pathlib import Path
from typing import Any

import yaml
from pyspark.sql import DataFrame
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    FloatType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Type mapping from YAML to Spark types
TYPE_MAPPING = {
    "integer": IntegerType,
    "int": IntegerType,
    "long": LongType,
    "double": DoubleType,
    "float": FloatType,
    "string": StringType,
    "boolean": BooleanType,
    "bool": BooleanType,
}

# Type mapping from YAML to Python types for constraint checking
PYTHON_TYPE_MAPPING = {
    "integer": (int,),
    "int": (int,),
    "long": (int,),
    "double": (float, int),
    "float": (float, int),
    "string": (str,),
    "boolean": (bool,),
    "bool": (bool,),
}


class ContractError(Exception):
    """Exception raised when a data contract validation fails."""
    pass


class SchemaValidator:
    """Validates Spark DataFrames against YAML data contract definitions."""

    def __init__(self, contract_path: str | Path):
        """
        Initialize the validator with a YAML contract file.

        Args:
            contract_path: Path to the YAML contract file.
        """
        self.contract_path = Path(contract_path)
        if not self.contract_path.exists():
            raise FileNotFoundError(f"Contract file not found: {contract_path}")

        with open(self.contract_path, "r") as f:
            self.contract = yaml.safe_load(f)

        self.name = self.contract.get("name", "unknown")
        self.fields = self.contract.get("fields", [])
        logger.info(f"Loaded contract '{self.name}' from {contract_path}")

    def validate(self, df: DataFrame) -> tuple[bool, list[str]]:
        """
        Validate a Spark DataFrame against the contract schema.

        Args:
            df: The Spark DataFrame to validate.

        Returns:
            A tuple of (is_valid, errors) where:
            - is_valid: True if the DataFrame matches the contract.
            - errors: List of validation error messages.
        """
        errors = []

        # Get DataFrame field names (lowercase for case-insensitive comparison)
        df_fields = {field.name.lower(): field for field in df.schema.fields}

        # 1. Check required fields exist
        for field_def in self.fields:
            field_name = field_def["name"].lower()
            nullable = field_def.get("nullable", True)

            if field_name not in df_fields:
                if not nullable:
                    error = f"[{self.name}] Missing required field: {field_def['name']}"
                    errors.append(error)
                    logger.error(error)
                else:
                    logger.warning(f"[{self.name}] Missing optional field: {field_def['name']}")

        # 2. Check data types
        for field_def in self.fields:
            field_name = field_def["name"].lower()
            expected_type = field_def.get("type", "string").lower()

            if field_name in df_fields:
                actual_type = df_fields[field_name].dataType
                expected_spark_type = TYPE_MAPPING.get(expected_type)

                if expected_spark_type and not isinstance(actual_type, expected_spark_type):
                    error = (
                        f"[{self.name}] Field '{field_def['name']}' has type "
                        f"{type(actual_type).__name__}, expected {expected_type}"
                    )
                    errors.append(error)
                    logger.error(error)

        # 3. Check constraints (min_value, max_value, allowed_values)
        for field_def in self.fields:
            field_name = field_def["name"].lower()
            if field_name in df_fields:
                self._check_constraints(df, field_def, errors)

        # 4. Check for unexpected null values in non-nullable fields
        for field_def in self.fields:
            field_name = field_def["name"].lower()
            nullable = field_def.get("nullable", True)

            if not nullable and field_name in df_fields:
                null_count = df.filter(f"{field_def['name']} IS NULL").count()
                if null_count > 0:
                    error = (
                        f"[{self.name}] Field '{field_def['name']}' has {null_count} "
                        f"NULL values but is defined as NOT NULL"
                    )
                    errors.append(error)
                    logger.error(error)

        if not errors:
            logger.info(f"[{self.name}] Validation passed successfully.")
        else:
            logger.error(f"[{self.name}] Validation failed with {len(errors)} error(s).")

        return len(errors) == 0, errors

    def _check_constraints(
        self, df: DataFrame, field_def: dict[str, Any], errors: list[str]
    ) -> None:
        """
        Check value constraints for a field.

        Args:
            df: The Spark DataFrame.
            field_def: The field definition from the contract.
            errors: List to append error messages to.
        """
        field_name = field_def["name"]
        col_name_lower = field_name.lower()
        df_fields = {f.name.lower(): f for f in df.schema.fields}

        if col_name_lower not in df_fields:
            return

        # Check min_value constraint
        if "min_value" in field_def:
            min_val = field_def["min_value"]
            violations = df.filter(f"{field_name} < {min_val}").count()
            if violations > 0:
                error = (
                    f"[{self.name}] Field '{field_name}' has {violations} values "
                    f"below minimum {min_val}"
                )
                errors.append(error)
                logger.error(error)

        # Check max_value constraint
        if "max_value" in field_def:
            max_val = field_def["max_value"]
            violations = df.filter(f"{field_name} > {max_val}").count()
            if violations > 0:
                error = (
                    f"[{self.name}] Field '{field_name}' has {violations} values "
                    f"above maximum {max_val}"
                )
                errors.append(error)
                logger.error(error)

        # Check allowed_values constraint
        if "allowed_values" in field_def:
            allowed = field_def["allowed_values"]
            # Build a filter for values not in the allowed list
            allowed_str = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in allowed)
            violations = df.filter(f"{field_name} NOT IN ({allowed_str})").count()
            if violations > 0:
                error = (
                    f"[{self.name}] Field '{field_name}' has {violations} values "
                    f"not in allowed values: {allowed}"
                )
                errors.append(error)
                logger.error(error)

    def get_spark_schema(self) -> StructType:
        """
        Generate a Spark StructType schema from the contract.

        Returns:
            A Spark StructType schema.
        """
        struct_fields = []
        for field_def in self.fields:
            field_name = field_def["name"]
            field_type_str = field_def.get("type", "string").lower()
            nullable = field_def.get("nullable", True)

            spark_type = TYPE_MAPPING.get(field_type_str, StringType)
            struct_fields.append(StructField(field_name, spark_type(), nullable))

        return StructType(struct_fields)

    def validate_contract_file(self) -> tuple[bool, list[str]]:
        """
        Validate the contract file itself for completeness and correctness.

        Returns:
            A tuple of (is_valid, errors).
        """
        errors = []

        # Check required top-level fields
        if "name" not in self.contract:
            errors.append("Contract missing required field: name")
        if "fields" not in self.contract:
            errors.append("Contract missing required field: fields")
        elif not isinstance(self.contract["fields"], list):
            errors.append("Contract 'fields' must be a list")
        else:
            for i, field in enumerate(self.contract["fields"]):
                if not isinstance(field, dict):
                    errors.append(f"Field {i} must be a dictionary")
                    continue
                if "name" not in field:
                    errors.append(f"Field {i} missing required attribute: name")
                if "type" not in field:
                    errors.append(f"Field '{field.get('name', i)}' missing required attribute: type")
                elif field["type"].lower() not in TYPE_MAPPING:
                    errors.append(
                        f"Field '{field['name']}' has unknown type: {field['type']}. "
                        f"Valid types: {list(TYPE_MAPPING.keys())}"
                    )

        if errors:
            logger.error(f"Contract file validation failed: {errors}")
        else:
            logger.info(f"Contract file '{self.contract_path}' is valid.")

        return len(errors) == 0, errors


def validate_contract(contract_path: str | Path) -> tuple[bool, list[str]]:
    """
    Convenience function to validate a contract file.

    Args:
        contract_path: Path to the YAML contract file.

    Returns:
        A tuple of (is_valid, errors).
    """
    validator = SchemaValidator(contract_path)
    return validator.validate_contract_file()
