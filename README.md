# Instacart MLOps

End-to-end Data Engineering & ML project built on **Medallion Architecture**, using the [Instacart Market Basket Analysis](https://www.kaggle.com/c/instacart-market-basket-analysis) dataset as the source of truth. The project simulates three realistic data sources, ingests them into AWS S3 (Bronze layer), and progressively transforms data through Silver → Gold layers for downstream ML modeling.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Simulated Data Sources                       │
│                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│  │  Historical RDS │  │   Product API   │  │   Kinesis Stream    │ │
│  │  (orders +      │  │  (API Gateway + │  │  (real-time order   │ │
│  │  order_products)│  │   Lambda)       │  │   events)  [WIP]    │ │
│  └────────┬────────┘  └────────┬────────┘  └──────────┬──────────┘ │
└───────────┼────────────────────┼─────────────────────┼─────────────┘
            │                    │                      │
            ▼                    ▼                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    S3 Bronze Layer (raw, as-is)                     │
│   bronze/historical/   bronze/api/          bronze/stream/          │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │ Glue / Spark ETL
                                  ▼
                    S3 Silver Layer (cleaned, standardised)
                                  │
                                  ▼
                    S3 Gold Layer (aggregated feature tables)
                                  │
                                  ▼
                            ML Modeling
```

**Infrastructure:** Terraform (IaC) · **CI/CD:** GitHub Actions · **Cloud:** AWS ap-southeast-2

---

## Data Source

All three simulated sources are derived from the Instacart Market Basket Analysis dataset (`references/imba_data/`):

| Table | Rows | Description |
|---|---|---|
| `orders` | 3.4M | Order metadata (user, day-of-week, hour, days since prior) |
| `order_products` | 32M+ | Product line items per order (prior split) |
| `products` | 50k | Product catalogue with aisle and department |
| `aisles` | 134 | Aisle lookup |
| `departments` | 21 | Department lookup |

See `references/ERD.png` for the full entity-relationship diagram.

**Source mapping:**

| Simulated Source | Tables | Destination |
|---|---|---|
| Historical RDS (PostgreSQL) | `orders`, `order_products` | `s3://bronze/historical/` |
| Product API (API Gateway + Lambda) | `products`, `aisles`, `departments` | `s3://bronze/api/` |
| Kinesis Stream *(WIP)* | real-time order events | `s3://bronze/stream/` |

---

## Prerequisites

- Python 3.11+
- Terraform >= 1.6
- AWS CLI configured (`aws configure` or environment variables)
- psycopg2-binary, sqlalchemy, boto3 (`pip install -e ".[dev]"`)

---

## Quickstart

### 1. Clone and configure environment

```bash
cp .env.example .env
# Fill in AWS credentials and RDS connection details
```

### 2. Deploy infrastructure (dev)

```bash
# Pre-create Terraform state bucket (one-time only)
aws s3 mb s3://instacart-mlops-tfstate --region ap-southeast-2

cd infra/environments/dev
cp terraform.tfvars.example terraform.tfvars   # fill in values
export TF_VAR_db_password="your-secret"

terraform init
terraform plan
terraform apply
```

Outputs after apply:

| Output | Value |
|---|---|
| `bronze_bucket` | `instacart-mlops-bronze-dev-<account_id>` |
| `rds_endpoint` | `instacart-dev.<id>.ap-southeast-2.rds.amazonaws.com:5432` |
| `product_api_endpoint` | `https://<id>.execute-api.ap-southeast-2.amazonaws.com//product-events` |

### 3. Seed RDS with historical data

```bash
export RDS_HOST=<rds_endpoint_without_port>
export RDS_USER=instacart_admin
export RDS_PASSWORD=<your-password>

python -m instacart_mlops.ingestion.rds_seeder
# To force re-seed: python -m instacart_mlops.ingestion.rds_seeder --force
```

Expected duration: ~4 min for `orders` (3.4M rows), ~15 min for `order_products` (32M rows) over public internet.

### 4. Test the Product API

```bash
curl -X POST <product_api_endpoint> \
  -H "Content-Type: application/json" \
  -d '{"type": "product", "product_id": 1, "product_name": "Chocolate Sandwich Cookies", "aisle_id": 61, "department_id": 19}'
# Returns: {"status": "ok", "s3_key": "bronze/api/product/YYYY/MM/DD/...json"}
```

---

## Infrastructure Modules

| Module | Resources |
|---|---|
| `infra/modules/s3` | Bronze bucket, versioning, public access block |
| `infra/modules/rds` | PostgreSQL db.t3.micro, subnet group, security group |
| `infra/modules/lambda` | Lambda (Python 3.11), IAM role (least-privilege: `s3:PutObject` to `bronze/api/*` only) |
| `infra/modules/api_gateway` | HTTP API Gateway, `POST /product-events` route |

---

## CI/CD

| Trigger | Action |
|---|---|
| Push / PR | Auto-run `flake8` + `pytest` |
| PR | `terraform plan` runs automatically and posts output as PR comment |
| Manual (`workflow_dispatch`) | `terraform apply` — never auto-deployed |

GitHub Actions uses **OIDC** authentication. No long-lived AWS keys are stored in the repository.

---

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Lint
flake8 instacart_mlops/

# Format
black instacart_mlops/

# Test
pytest
```

---

## Security Notes

- `.env` and `*.tfvars` are gitignored — never commit secrets.
- RDS is `publicly_accessible = false` by default. For local dev, temporarily add your IP to the security group (`sg-08bf27d115b12d932`) on port 5432 — remember to remove it afterwards.
- Lambda IAM role is scoped to `s3:PutObject` on `bronze/api/*` only.


####     cloud formation allen