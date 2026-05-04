# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 1. 核心目标 / Project Goal

构建一个基于 **Medallion Architecture** 的端到端 Data Engineering & ML 项目，虚拟三个数据源（Kinesis Stream、Product API、历史 RDS 数据），利用 Terraform 实施 IaC，并通过 GitHub Actions 进行受控部署。

Build an end-to-end Data Engineering & ML project based on **Medallion Architecture**, simulating three data sources (Kinesis Stream, Product API, Historical RDS), using Terraform for IaC and GitHub Actions for controlled deployment.

---

## 2. Commands

```bash
# Install (Python 3.11 required)
pip install -e ".[dev]"

# Lint
flake8 instacart_mlops/          # infra/ is excluded; max-line-length=100

# Test all
pytest tests/ -v --tb=short

# Test a single file
pytest tests/test_data_validation.py -v

# Test a single case
pytest tests/test_validator.py::TestDataFrameValidation::test_valid_dataframe -v

# Run Bronze → Silver ETL (requires S3_BUCKET env var)
export S3_BUCKET=nextcartai-dev-<account_id>
python -m instacart_mlops.processing.bronze_to_silver

# Seed RDS with historical data (requires RDS_HOST, RDS_PASSWORD)
python -m instacart_mlops.ingestion.rds_seeder
python -m instacart_mlops.ingestion.rds_seeder --force   # truncate and re-seed

# Stream product events to API Gateway (requires API_ENDPOINT, API_KEY)
export API_ENDPOINT=https://<id>.execute-api.ap-southeast-2.amazonaws.com//product-events
export API_KEY=$(aws ssm get-parameter --name /instacart/dev/api-key \
    --with-decryption --query Parameter.Value --output text)
python -m instacart_mlops.ingestion.api_simulator
python -m instacart_mlops.ingestion.api_simulator --workers 20 --delay 0.005
```

### Terraform (run from `infra/environments/dev/`)

```bash
cd infra/environments/dev
terraform init
terraform plan
terraform apply          # never auto-run; always manual
terraform destroy -target=module.dms -auto-approve   # DMS only (costly to run)
```

Retrieve deployed outputs after apply:
```bash
terraform output rds_endpoint
terraform output product_api_endpoint
terraform output bronze_bucket
aws ssm get-parameter --name /instacart/dev/api-key --with-decryption \
    --query Parameter.Value --output text
```

---

## 3. Architecture

### Data Flow (Medallion)

```
[Product API CSV]  →  api_simulator.py  →  API Gateway → Lambda → s3://bronze/api/<type>/YYYY/MM/DD/
[Historical RDS]   →  rds_seeder.py     →  RDS (PostgreSQL) → DMS → s3://bronze/historical/public/
                       (manual upload)                              → s3://bronze/historical/manual/
[Kinesis Stream]   →  (not yet implemented)                        → s3://bronze/stream/

Bronze → Silver:   bronze_to_silver.py  (PySpark, writes Parquet to silver/)
Silver → Gold:     silver_to_gold.py    (not yet implemented)
```

### Bronze → Silver ETL (`instacart_mlops/processing/bronze_to_silver.py`)

The pipeline runs four sequential steps; each validates against a data contract before writing:

1. **Orders** — CSV.gz from `bronze/historical/public/orders/` → NULL `days_since_prior_order` filled to 0.0, deduplicated on `order_id`, adds `user_id_bucket = user_id % 100` for partitioning
2. **Order Products** — CSV.gz → `reordered` cast to boolean, deduplicated on `(order_id, product_id)`, adds `order_id_bucket = order_id % 100`
3. **Product Catalog** — joins three JSON sources (`bronze/api/product/`, `bronze/api/aisle/`, `bronze/api/department/`) into a single wide table at `silver/products/`
4. **Order Products Train** — optional ML labels from `bronze/historical/manual/order_products_train/`; pipeline continues if source is absent

### Data Contracts (`contracts/`)

YAML files that define field names, types, nullability, and value constraints (`min_value`, `max_value`, `allowed_values`). `SchemaValidator` (`instacart_mlops/processing/validator.py`) reads these and validates PySpark DataFrames at runtime. Bronze contracts document raw source shapes; silver contracts are enforced by `validate_silver()` before each write.

### API Ingestion Path

`api_simulator.py` reads from `references/imba_data/` and POSTs each row to API Gateway. **Order matters**: aisles → departments → products (products FK-reference both). The Lambda handler at `infra/lambda_handlers/product_api/handler.py` writes each event as `s3://bronze/api/<type>/YYYY/MM/DD/<timestamp>.json`. Terraform's `archive_file` data source auto-zips the Lambda source on each `plan/apply`.

### RDS + DMS Path

`rds_seeder.py` uses psycopg2 `COPY` (not row-by-row INSERT) to bulk-load ~3.4M orders and ~32M order_products rows from CSV/gz into RDS. DMS then replicates from RDS to `s3://bronze/historical/public/`.

### Test Suite

| File | Backend | Speed |
|------|---------|-------|
| `test_data_validation.py` | pandas | fast — inline CSV fixtures, no external deps |
| `test_validator.py` | PySpark | slow — creates a local Spark session |
| `test_api_simulator.py` | — | — |

---

## 4. Infrastructure

- **Region**: `ap-southeast-2` (Sydney)
- **Terraform root**: `infra/environments/dev/` — all `terraform` commands run here, not from repo root
- **Modules**: `infra/modules/{s3,rds,dms,lambda,api_gateway}`
- **State**: S3 backend configured in `infra/environments/dev/backend.tf`
- **Dev uses default VPC** with a free S3 VPC Gateway Endpoint so DMS can run without public access
- **API key** is auto-generated by Terraform (`random_password`) and stored in SSM Parameter Store

---

## 5. CI/CD

| Trigger | Action |
|---|---|
| Every push / PR | `flake8 instacart_mlops/` + `pytest tests/` + `terraform validate` (no backend) |
| PR touching `infra/**` | `terraform plan` — result posted as PR comment (updated if already exists) |
| Manual `workflow_dispatch` | `terraform apply` or `terraform destroy -target=module.dms` |

---

## 6. Development Standards

- **ELT**: `ingestion/` writes raw data to Bronze as-is. No cleaning until `processing/`.
- **`references/` is read-only**: sample CSVs and diagrams only; simulators and seeders may read from it at dev/test time, but never import from or write to it in production paths.
- **Code style**: PEP 8, `max-line-length=100`. All tool config in `pyproject.toml`; `flake8` also reads `.flake8`.
- **Environment variables**: copy `.env.example` → `.env`. `config.py` reads all AWS/RDS/Spark config from env vars.
