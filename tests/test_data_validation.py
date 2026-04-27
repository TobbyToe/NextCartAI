"""Data validation tests — self-contained fixtures, no external files required."""

import io
import pandas as pd
import pytest

# ── Shared helpers ────────────────────────────────────────────────────────────

def _df(csv: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(csv))


def validate_no_null_ids(df: pd.DataFrame, id_col: str) -> None:
    assert df[id_col].notna().all(), f"Null values found in {id_col}"


def validate_unique_ids(df: pd.DataFrame, id_col: str) -> None:
    assert df[id_col].is_unique, f"Duplicate values found in {id_col}"


def validate_foreign_key(df: pd.DataFrame, fk_col: str, valid_ids: set) -> None:
    assert df[fk_col].isin(valid_ids).all(), f"{fk_col} contains unknown references"


# ── Aisles ────────────────────────────────────────────────────────────────────

AISLES_CSV = """\
aisle_id,aisle
1,prepared soups salads
2,specialty cheeses
3,frozen meals
"""


def test_aisles_schema():
    df = _df(AISLES_CSV)
    assert set(df.columns) == {"aisle_id", "aisle"}


def test_aisles_no_null_ids():
    validate_no_null_ids(_df(AISLES_CSV), "aisle_id")


def test_aisles_unique_ids():
    validate_unique_ids(_df(AISLES_CSV), "aisle_id")


def test_aisles_duplicate_id_caught():
    bad = _df("aisle_id,aisle\n1,frozen\n1,frozen meals\n")
    with pytest.raises(AssertionError):
        validate_unique_ids(bad, "aisle_id")


# ── Departments ───────────────────────────────────────────────────────────────

DEPARTMENTS_CSV = """\
department_id,department
1,frozen
2,other
3,bakery
"""


def test_departments_schema():
    df = _df(DEPARTMENTS_CSV)
    assert set(df.columns) == {"department_id", "department"}


def test_departments_no_null_ids():
    validate_no_null_ids(_df(DEPARTMENTS_CSV), "department_id")


def test_departments_unique_ids():
    validate_unique_ids(_df(DEPARTMENTS_CSV), "department_id")


# ── Products ──────────────────────────────────────────────────────────────────

PRODUCTS_CSV = """\
product_id,product_name,aisle_id,department_id
1,Chocolate Sandwich Cookies,1,1
2,All-Seasons Salt,2,2
3,Robusta Coffee,3,3
"""


def test_products_schema():
    df = _df(PRODUCTS_CSV)
    assert {"product_id", "product_name", "aisle_id", "department_id"}.issubset(df.columns)


def test_products_no_null_ids():
    validate_no_null_ids(_df(PRODUCTS_CSV), "product_id")


def test_products_unique_ids():
    validate_unique_ids(_df(PRODUCTS_CSV), "product_id")


def test_products_no_null_names():
    df = _df(PRODUCTS_CSV)
    assert df["product_name"].notna().all()


def test_products_aisle_ids_valid():
    aisles = _df(AISLES_CSV)
    products = _df(PRODUCTS_CSV)
    validate_foreign_key(products, "aisle_id", set(aisles["aisle_id"]))


def test_products_department_ids_valid():
    departments = _df(DEPARTMENTS_CSV)
    products = _df(PRODUCTS_CSV)
    validate_foreign_key(products, "department_id", set(departments["department_id"]))


def test_products_invalid_aisle_caught():
    bad = _df("product_id,product_name,aisle_id,department_id\n1,Widget,999,1\n")
    with pytest.raises(AssertionError):
        validate_foreign_key(bad, "aisle_id", {1, 2, 3})


# ── Orders ────────────────────────────────────────────────────────────────────

ORDERS_CSV = """\
order_id,user_id,eval_set,order_number,order_dow,order_hour_of_day,days_since_prior_order
1,1,prior,1,2,8,
2,1,prior,2,3,7,15.0
3,2,train,1,0,23,
4,3,test,1,6,0,
"""


def test_orders_schema():
    df = _df(ORDERS_CSV)
    assert {"order_id", "user_id", "eval_set", "order_number",
            "order_dow", "order_hour_of_day"}.issubset(df.columns)


def test_orders_no_null_ids():
    df = _df(ORDERS_CSV)
    assert df["order_id"].notna().all()
    assert df["user_id"].notna().all()


def test_orders_unique_ids():
    validate_unique_ids(_df(ORDERS_CSV), "order_id")


def test_orders_dow_range():
    df = _df(ORDERS_CSV)
    assert df["order_dow"].between(0, 6).all(), "order_dow must be 0–6"


def test_orders_hour_range():
    df = _df(ORDERS_CSV)
    assert df["order_hour_of_day"].between(0, 23).all(), "order_hour_of_day must be 0–23"


def test_orders_order_number_positive():
    df = _df(ORDERS_CSV)
    assert (df["order_number"] >= 1).all()


def test_orders_eval_set_values():
    df = _df(ORDERS_CSV)
    assert df["eval_set"].isin({"prior", "train", "test"}).all()


def test_orders_invalid_dow_caught():
    bad = _df("order_id,user_id,eval_set,order_number,order_dow,order_hour_of_day\n"
              "1,1,prior,1,7,8\n")
    with pytest.raises(AssertionError):
        assert bad["order_dow"].between(0, 6).all(), "order_dow must be 0–6"


def test_orders_invalid_hour_caught():
    bad = _df("order_id,user_id,eval_set,order_number,order_dow,order_hour_of_day\n"
              "1,1,prior,1,2,24\n")
    with pytest.raises(AssertionError):
        assert bad["order_hour_of_day"].between(0, 23).all(), "order_hour_of_day must be 0–23"
