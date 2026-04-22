import os

RDS_HOST = os.environ["RDS_HOST"]
RDS_PORT = os.environ.get("RDS_PORT", "5432")
RDS_DB = os.environ.get("RDS_DB", "instacart")
RDS_USER = os.environ["RDS_USER"]
RDS_PASSWORD = os.environ["RDS_PASSWORD"]

DATABASE_URL = (
    f"postgresql+psycopg2://{RDS_USER}:{RDS_PASSWORD}@{RDS_HOST}:{RDS_PORT}/{RDS_DB}"
)
