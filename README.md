<img width="663" height="358" alt="image" src="https://github.com/user-attachments/assets/d40f0d58-bf1b-4c7c-82dc-8dec4ba8cd97" />


# NextCartAI — Instacart MLOps

End-to-end Data Engineering & ML project built on **Medallion Architecture**, using the [Instacart Market Basket Analysis](https://www.kaggle.com/competitions/instacart-market-basket-analysis/data) dataset as the source of truth. The project simulates three realistic data sources, ingests them into AWS S3 (Bronze layer), and progressively transforms data through Silver → Gold layers for downstream ML modeling.

> **详细操作手册 / Full step-by-step guide** → [DATA_PIPELINE_RUNBOOK.md](DATA_PIPELINE_RUNBOOK.md)

---

## Architecture

```
references/imba_data/  (local truth data, read-only)
        │
        ├── orders.csv + order_products__prior.csv.gz
        │        └─[rds_seeder.py]──→ RDS PostgreSQL (instacart-dev)
        │                                      │
        │                             [DMS Full Load]
        │                                      │
        ├── products.csv + aisles.csv + departments.csv
        │        └─[api_simulator.py]──→ API Gateway → Lambda
        │                                      │
        │                                      ↓
        │                          S3 Bronze Bucket
        │                      ├── bronze/historical/   ← DMS
        │                      └── bronze/api/          ← Lambda
        │
        └── (WIP) Kinesis Stream → bronze/stream/
                                      │
                               [Glue/Spark ETL]
                                      │
                              S3 Silver (cleaned)
                                      │
                               S3 Gold (features)
                                      │
                              ML Model Training
```

**Cloud:** AWS ap-southeast-2 (Sydney) · **IaC:** Terraform · **CI/CD:** GitHub Actions (OIDC)

---

## Current Build Status

| Layer | Source | Status | S3 Path |
|-------|--------|--------|---------|
| Bronze | Historical RDS → DMS | ✅ Complete | `bronze/historical/` |
| Bronze | Product API → Lambda | ✅ Complete | `bronze/api/` |
| Bronze | Kinesis Stream | 🔲 WIP | `bronze/stream/` |
| Silver | Glue/Spark ETL | 🔲 WIP | `silver/` |
| Gold | Feature tables | 🔲 WIP | `gold/` |

---

## Data

All three simulated sources derive from the Instacart dataset (`references/imba_data/` — local only, gitignored):

| File | Rows | Used by |
|------|------|---------|
| `orders.csv` | 3.4M | RDS seeder → DMS → `bronze/historical/` |
| `order_products__prior.csv.gz` | 32M | RDS seeder → DMS → `bronze/historical/` |
| `products.csv` | 49,688 | API simulator → `bronze/api/` |
| `aisles.csv` | 134 | API simulator → `bronze/api/` |
| `departments.csv` | 21 | API simulator → `bronze/api/` |

Download from Kaggle → place in `references/imba_data/` → see [RUNBOOK Phase 0](DATA_PIPELINE_RUNBOOK.md).

---

## Quick Setup

```bash
# 1. Clone & install
git clone <repo-url> && cd NextCartAI
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env: fill AWS credentials + RDS connection

# 3. Deploy infrastructure
cd infra/environments/dev
export TF_VAR_db_username=instacart_admin
export TF_VAR_db_password="<your-password>"
terraform init && terraform apply -auto-approve

# 4. Seed RDS with historical data (~20 min)
export $(cat ../../.env | xargs)
python -m instacart_mlops.ingestion.rds_seeder

# 5. Push product catalog to API → S3 (~30 min)
export API_ENDPOINT=$(cd infra/environments/dev && terraform output -raw product_api_endpoint)
python -m instacart_mlops.ingestion.api_simulator

# 6. Run DMS full load: RDS → S3 bronze/historical/ (~45 min)
#    See DATA_PIPELINE_RUNBOOK.md Phase 4 for full CLI steps
```

---

## Infrastructure Modules

| Module | Key Resources |
|--------|---------------|
| `infra/modules/s3` | Bronze bucket, versioning, public-access block |
| `infra/modules/rds` | PostgreSQL db.t3.micro, subnet group, security group |
| `infra/modules/lambda` | Python 3.11 function, IAM role scoped to `bronze/api/*` |
| `infra/modules/api_gateway` | HTTP API, `POST /product-events` route |
| `infra/modules/dms` | Replication instance (dms.t3.small), source/target endpoints, full-load task |

---

## Cost Management

Running costs (ap-southeast-2):

| Resource | Cost | Notes |
|----------|------|-------|
| RDS db.t3.micro | ~$20/mo | Stop when not developing |
| DMS dms.t3.small | ~$39/mo | **Destroy immediately after full-load** |
| S3 (~300 MB) | ~$0.01/mo | Keep |
| Lambda / API GW | $0 idle | Keep |

```bash
# Stop RDS (pause dev work)
aws rds stop-db-instance --db-instance-identifier instacart-dev

# Destroy DMS after load completes
cd infra/environments/dev && terraform destroy -target=module.dms -auto-approve

# Resume RDS
aws rds start-db-instance --db-instance-identifier instacart-dev
```

---

## CI / CD

Two GitHub Actions workflows run automatically.

### `ci.yml` — Lint & Test

Triggers on **every push** to any branch and on **every PR to `main`**.

1. Checks out the code and installs all dev dependencies via `pip install -e ".[dev]"`.
2. Runs **flake8** on `instacart_mlops/` to enforce PEP 8 style (config in `.flake8`).
3. Runs **pytest** on `tests/` with verbose output.

A PR cannot be considered ready to merge until this job is green.

```bash
# Run the same checks locally before pushing
flake8 instacart_mlops/
pytest tests/ -v --tb=short
```

---

### `terraform.yml` — Infrastructure

Triggers on two events:

| Event | When | What runs |
|-------|------|-----------|
| **Pull Request** to `main` (paths: `infra/**`) | Any PR touching infra | `terraform fmt -check` + `terraform validate` + `terraform plan`, then posts the plan output as a PR comment so reviewers can see what will change before approving. |
| **Manual dispatch** (`workflow_dispatch`) | You click "Run workflow" in GitHub Actions | Choose one of the three options below. |

**Manual dispatch options:**

| Option | What it does |
|--------|-------------|
| `plan` | Runs `terraform plan` and prints the output — a dry run with no changes applied. Use this to preview what will change without touching AWS. |
| `apply` | Runs `terraform apply` against the saved plan — **actually provisions or updates AWS resources**. Only run this after reviewing the plan output. |
| `destroy-dms` | Runs `terraform destroy -target=module.dms` — tears down **only the DMS replication instance and task** to stop the ~$39/mo charge after a full-load completes. All other resources (RDS, S3, Kinesis, Lambda) are left untouched. |

> AWS credentials are stored as GitHub Secrets (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `TF_VAR_DB_PASSWORD`) and are never committed to the repo.

---

## Security

- `.env` and `*.tfvars` are gitignored — never commit secrets.
- GitHub Actions authenticates via **OIDC** — no long-lived AWS keys in the repo.
- RDS is `publicly_accessible = false` by default. For local dev, temporarily enable it via `aws rds modify-db-instance --publicly-accessible`.
- Lambda IAM role is scoped to `s3:PutObject` on `bronze/api/*` only.
