"""Data validation tests for reference CSV sources (no AWS calls)."""

import gzip
import pandas as pd
import pytest

DATA_DIR = "references/imba_data"


@pytest.fixture(scope="module")
def aisles():
    return pd.read_csv(f"{DATA_DIR}/aisles.csv")


@pytest.fixture(scope="module")
def departments():
    return pd.read_csv(f"{DATA_DIR}/departments.csv")


@pytest.fixture(scope="module")
def products():
    return pd.read_csv(f"{DATA_DIR}/products.csv")


@pytest.fixture(scope="module")
def orders():
    return pd.read_csv(f"{DATA_DIR}/orders.csv")


# ── Schema ────────────────────────────────────────────────────────────────────

def test_aisles_schema(aisles):
    assert set(aisles.columns) == {"aisle_id", "aisle"}


def test_departments_schema(departments):
    assert set(departments.columns) == {"department_id", "department"}


def test_products_schema(products):
    assert {"product_id", "product_name", "aisle_id", "department_id"}.issubset(products.columns)


def test_orders_schema(orders):
    assert {"order_id", "user_id", "eval_set", "order_number",
            "order_dow", "order_hour_of_day"}.issubset(orders.columns)


# ── No nulls in primary keys ──────────────────────────────────────────────────

def test_aisles_no_null_ids(aisles):
    assert aisles["aisle_id"].notna().all()


def test_departments_no_null_ids(departments):
    assert departments["department_id"].notna().all()


def test_products_no_null_ids(products):
    assert products["product_id"].notna().all()
    assert products["product_name"].notna().all()


def test_orders_no_null_ids(orders):
    assert orders["order_id"].notna().all()
    assert orders["user_id"].notna().all()


# ── Unique primary keys ───────────────────────────────────────────────────────

def test_aisles_unique_ids(aisles):
    assert aisles["aisle_id"].is_unique


def test_departments_unique_ids(departments):
    assert departments["department_id"].is_unique


def test_products_unique_ids(products):
    assert products["product_id"].is_unique


def test_orders_unique_ids(orders):
    assert orders["order_id"].is_unique


# ── Value ranges ──────────────────────────────────────────────────────────────

def test_orders_dow_range(orders):
    assert orders["order_dow"].between(0, 6).all(), "order_dow must be 0–6"


def test_orders_hour_range(orders):
    assert orders["order_hour_of_day"].between(0, 23).all(), "order_hour_of_day must be 0–23"


def test_orders_order_number_positive(orders):
    assert (orders["order_number"] >= 1).all()


# ── Referential integrity ─────────────────────────────────────────────────────

def test_products_aisle_ids_valid(products, aisles):
    valid = set(aisles["aisle_id"])
    assert products["aisle_id"].isin(valid).all(), "products contain unknown aisle_id"


def test_products_department_ids_valid(products, departments):
    valid = set(departments["department_id"])
    assert products["department_id"].isin(valid).all(), "products contain unknown department_id"


# ── eval_set values ───────────────────────────────────────────────────────────

def test_orders_eval_set_values(orders):
    assert orders["eval_set"].isin({"prior", "train", "test"}).all()
