# DATA_PIPELINE_RUNBOOK.md

> **This document is designed to be given directly to Claude Code.**
> Claude can read it and execute every command end-to-end.
> Final result: raw data in S3 Bronze layer (`bronze/historical/` + `bronze/api/`).
> All billable AWS resources (except S3) are shut down at the end.

---

## What This Runbook Does

1. Deploys AWS infrastructure via Terraform (S3, RDS, Lambda, API Gateway)
2. Seeds a PostgreSQL database with 35M rows of historical order data
3. Posts 50K product catalog records through an API Gateway into S3
4. Runs a DMS full-load migration: RDS → S3 (`bronze/historical/`)
5. Verifies all data is in S3
6. Destroys all billable resources except S3

**Total runtime**: ~2–3 hours (most of it unattended waiting)

---

## Prerequisites — Do These Before Giving to Claude

### A. Get the Instacart Dataset

Download from: https://www.kaggle.com/competitions/instacart-market-basket-analysis/data

Place exactly these files into `references/imba_data/` (create the folder if it doesn't exist):

```
references/imba_data/
├── orders.csv                     (3.4M rows, ~100 MB)
├── order_products__prior.csv.gz   (32M rows, ~157 MB compressed)
├── products.csv                   (49,688 rows)
├── aisles.csv                     (134 rows)
└── departments.csv                (21 rows)
```

> This folder is in `.gitignore`. Never commit these files.

### B. Create Your `.env` File

```bash
cp .env.example .env
```

Open `.env` and fill in your AWS credentials:

```dotenv
AWS_ACCESS_KEY_ID=<your-access-key-id>
AWS_SECRET_ACCESS_KEY=<your-secret-access-key>
AWS_DEFAULT_REGION=ap-southeast-2

# Leave these blank for now — fill in after Step 1 (terraform apply)
RDS_HOST=
RDS_PORT=5432
RDS_DB=instacart
RDS_USER=instacart_admin
RDS_PASSWORD=<choose-a-password-min-8-chars>
```

> The IAM user needs these AWS permissions: `AmazonRDSFullAccess`, `AmazonS3FullAccess`, `AmazonDMSFullAccess`, `AWSLambda_FullAccess`, `AmazonAPIGatewayAdministrator`, `IAMFullAccess`.

### C. Install Dependencies

```bash
pip install -r requirements.txt
```

Verify:
```bash
python -c "import psycopg2, sqlalchemy, boto3, requests; print('OK')"
terraform version
aws --version
```

---

## Step 1 — Deploy Core Infrastructure (Terraform)

```bash
# Load credentials
export $(grep -v '^#' .env | grep -v '^$' | xargs)

# Deploy
cd infra/environments/dev
terraform init
terraform apply -auto-approve \
  -var="db_username=${RDS_USER}" \
  -var="db_password=${RDS_PASSWORD}"
```

**Wait ~5 minutes** for RDS to provision. When complete, capture the outputs:

```bash
export TF_RDS_ENDPOINT=$(terraform output -raw rds_endpoint)
export TF_API_ENDPOINT=$(terraform output -raw product_api_endpoint)
export TF_BRONZE_BUCKET=$(terraform output -raw bronze_bucket)

echo "RDS:    $TF_RDS_ENDPOINT"
echo "API:    $TF_API_ENDPOINT"
echo "Bucket: $TF_BRONZE_BUCKET"
```

Now update your `.env` — set `RDS_HOST` to the RDS endpoint **without the `:5432` port suffix**:

```bash
# Get just the hostname
RDS_HOSTNAME=$(echo $TF_RDS_ENDPOINT | cut -d':' -f1)
echo "RDS_HOST=$RDS_HOSTNAME"
```

Edit `.env` and set `RDS_HOST=<value printed above>`. Then reload:

```bash
export $(grep -v '^#' .env | grep -v '^$' | xargs)
```

---

## Step 2 — Enable RDS Public Access for Local Seeding

RDS is private by default. We need to temporarily expose it so the seeder can connect from your local machine.

### 2-A. Enable public access on RDS

```bash
aws rds modify-db-instance \
  --db-instance-identifier instacart-dev \
  --publicly-accessible \
  --apply-immediately

# Wait for status to return to 'available' (~2 min)
until aws rds describe-db-instances \
  --db-instance-identifier instacart-dev \
  --query "DBInstances[0].DBInstanceStatus" \
  --output text | grep -q "^available$"; do
  echo "Waiting for RDS..."; sleep 10
done
echo "RDS is available"
```

### 2-B. Add your local IP to the RDS security group

```bash
MY_IP=$(curl -s ifconfig.me)
RDS_SG_ID=$(aws rds describe-db-instances \
  --db-instance-identifier instacart-dev \
  --query "DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId" \
  --output text)

echo "Your IP: $MY_IP  |  SG: $RDS_SG_ID"

aws ec2 authorize-security-group-ingress \
  --group-id $RDS_SG_ID \
  --protocol tcp \
  --port 5432 \
  --cidr "${MY_IP}/32" \
  --region ap-southeast-2
```

### 2-C. Verify connection

```bash
cd /path/to/NextCartAI   # return to repo root
python -c "
import psycopg2, os
conn = psycopg2.connect(host=os.environ['RDS_HOST'], port=5432,
    dbname='instacart', user=os.environ['RDS_USER'],
    password=os.environ['RDS_PASSWORD'])
print('Connected:', conn.get_dsn_parameters())
conn.close()
"
```

---

## Step 3 — Seed RDS with Historical Data

This loads `orders` (3.4M rows) and `order_products` (32M rows) from `references/imba_data/`.

```bash
# From repo root
python -m instacart_mlops.ingestion.rds_seeder
```

**Expected output:**
```
12:00:00  INFO     Creating schema...
12:00:01  INFO     Loading orders...
12:04:30  INFO     orders: 3421083 rows loaded in 269s
12:04:30  INFO     Loading order_products...
12:22:10  INFO     order_products: 32434489 rows loaded in 1060s
12:22:11  INFO     Done. All tables populated.
```

**If you need to re-run from scratch:**
```bash
python -m instacart_mlops.ingestion.rds_seeder --force
```

Verify row counts:
```bash
python -c "
import psycopg2, os
conn = psycopg2.connect(host=os.environ['RDS_HOST'], port=5432,
    dbname='instacart', user=os.environ['RDS_USER'],
    password=os.environ['RDS_PASSWORD'])
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM orders')
print('orders:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM order_products')
print('order_products:', cur.fetchone()[0])
conn.close()
"
# Expected: orders: 3421083, order_products: 32434489
```

---

## Step 4 — Push Product Catalog via API → S3

This sends `aisles` (134), `departments` (21), and `products` (49,688) through API Gateway into `s3://bronze/api/`.

```bash
export API_ENDPOINT=$TF_API_ENDPOINT
python -m instacart_mlops.ingestion.api_simulator
```

**Expected output:**
```
12:25:00  INFO     Sending 134 aisles...
12:25:10  INFO     [100/134] 98 ok / 0 fail | 9.8 req/s
12:25:14  INFO     aisles complete: 134 ok / 0 fail
12:25:14  INFO     Sending 21 departments...
...
12:55:00  INFO     products complete: 49688 ok / 0 fail
```

Verify S3:
```bash
aws s3 ls s3://${TF_BRONZE_BUCKET}/bronze/api/ --recursive --summarize \
  | grep -E "Total Objects|aisle|department|product" | tail -5
# Expected: ~50,000 objects total
```

---

## Step 5 — Run DMS: RDS → S3 Bronze/Historical

### 5-A. Deploy DMS module

```bash
cd infra/environments/dev
terraform apply -auto-approve \
  -var="db_username=${RDS_USER}" \
  -var="db_password=${RDS_PASSWORD}"
```

This adds: DMS replication instance (`dms.t3.small`), source endpoint (RDS), target endpoint (S3), and replication task. **Wait ~7 minutes** for the replication instance to provision.

### 5-B. Test endpoint connections

```bash
RI_ARN=$(aws dms describe-replication-instances \
  --filters "Name=replication-instance-id,Values=instacart-dev" \
  --query "ReplicationInstances[0].ReplicationInstanceArn" --output text)

SRC_ARN=$(aws dms describe-endpoints \
  --filters "Name=endpoint-id,Values=instacart-rds-src-dev" \
  --query "Endpoints[0].EndpointArn" --output text)

TGT_ARN=$(aws dms describe-endpoints \
  --filters "Name=endpoint-id,Values=instacart-s3-bronze-dev" \
  --query "Endpoints[0].EndpointArn" --output text)

# Trigger tests
aws dms test-connection --replication-instance-arn $RI_ARN --endpoint-arn $SRC_ARN
aws dms test-connection --replication-instance-arn $RI_ARN --endpoint-arn $TGT_ARN

# Wait for both to succeed (~60s)
echo "Waiting for connection tests..."
until aws dms describe-connections \
  --filters "Name=replication-instance-arn,Values=$RI_ARN" \
  --query "Connections[?Status!='testing'].Status" \
  --output text | grep -v "^$"; do
  sleep 15; echo "Still testing..."
done

aws dms describe-connections \
  --filters "Name=replication-instance-arn,Values=$RI_ARN" \
  --query "Connections[*].{Endpoint:EndpointIdentifier,Status:Status}" \
  --output table
# Both should show: successful
```

If any connection shows `failed`, see **Troubleshooting** at the bottom.

### 5-C. Start the full-load task

```bash
TASK_ARN=$(aws dms describe-replication-tasks \
  --filters "Name=replication-task-id,Values=instacart-full-load-dev" \
  --query "ReplicationTasks[0].ReplicationTaskArn" --output text)

aws dms start-replication-task \
  --replication-task-arn $TASK_ARN \
  --start-replication-task-type start-replication \
  --query "ReplicationTask.Status" --output text
# Expected: starting
```

### 5-D. Monitor progress

```bash
# Check status every 2 minutes
watch -n 120 "aws dms describe-replication-tasks \
  --filters 'Name=replication-task-id,Values=instacart-full-load-dev' \
  --query 'ReplicationTasks[0].{Status:Status,Loaded:ReplicationTaskStats.TablesLoaded,Progress:ReplicationTaskStats.FullLoadProgressPercent}' \
  --output table"
```

Or check manually:
```bash
aws dms describe-replication-tasks \
  --filters "Name=replication-task-id,Values=instacart-full-load-dev" \
  --query "ReplicationTasks[0].{Status:Status,TablesLoaded:ReplicationTaskStats.TablesLoaded,Progress:ReplicationTaskStats.FullLoadProgressPercent}" \
  --output table
```

**Wait for `Status: stopped` and `TablesLoaded: 2`** (~30–60 minutes).

---

## Step 6 — Verify Final S3 Data

```bash
echo "=== bronze/historical/ (from DMS) ==="
aws s3 ls s3://${TF_BRONZE_BUCKET}/bronze/historical/ --recursive --human-readable

echo ""
echo "=== bronze/api/ (from API simulator) ==="
aws s3 ls s3://${TF_BRONZE_BUCKET}/bronze/api/ --recursive --summarize | tail -3
```

**Expected output:**
```
=== bronze/historical/ (from DMS) ===
  44.0 MiB  bronze/historical/public/orders/LOAD00000001.csv.gz
 184.7 MiB  bronze/historical/public/order_products/LOAD00000001.csv.gz
  83.8 MiB  bronze/historical/public/order_products/LOAD00000002.csv.gz

=== bronze/api/ (from API simulator) ===
Total Objects: 49843
Total Size: ...
```

Raw data is now in S3. Pipeline complete. ✅

---

## Step 7 — Shut Down All Billable Resources (Keep S3)

Run all of these in order:

### 7-A. Destroy DMS (~$39/month)

```bash
cd infra/environments/dev
terraform destroy -target=module.dms -auto-approve \
  -var="db_username=${RDS_USER}" \
  -var="db_password=${RDS_PASSWORD}"
```

### 7-B. Revert RDS to private and remove your IP

```bash
# Remove local IP from security group
aws ec2 revoke-security-group-ingress \
  --group-id $RDS_SG_ID \
  --protocol tcp \
  --port 5432 \
  --cidr "${MY_IP}/32" \
  --region ap-southeast-2

# Disable public access
aws rds modify-db-instance \
  --db-instance-identifier instacart-dev \
  --no-publicly-accessible \
  --apply-immediately
```

### 7-C. Stop RDS (~$20/month while stopped = $0, billed only when running)

```bash
aws rds stop-db-instance --db-instance-identifier instacart-dev \
  --query "DBInstance.DBInstanceStatus" --output text
# Expected: stopping
```

### 7-D. Confirm billing stops

```bash
# Verify DMS is gone
aws dms describe-replication-instances \
  --filters "Name=replication-instance-id,Values=instacart-dev" \
  --query "ReplicationInstances" --output text
# Expected: (empty)

# Verify RDS is stopped
aws rds describe-db-instances \
  --db-instance-identifier instacart-dev \
  --query "DBInstances[0].DBInstanceStatus" --output text
# Expected: stopped (or stopping)

# Confirm S3 data is intact
aws s3 ls s3://${TF_BRONZE_BUCKET}/bronze/ --recursive --summarize | tail -2
```

**After shutdown, ongoing cost = ~$0.01/month (S3 storage only).**

---

## Resuming Work Later

```bash
# Restart RDS (wait ~3 min for 'available')
aws rds start-db-instance --db-instance-identifier instacart-dev

until aws rds describe-db-instances \
  --db-instance-identifier instacart-dev \
  --query "DBInstances[0].DBInstanceStatus" \
  --output text | grep -q "^available$"; do
  echo "Starting..."; sleep 15
done
echo "RDS ready"

# Re-add your IP to security group if needed
MY_IP=$(curl -s ifconfig.me)
RDS_SG_ID=$(aws rds describe-db-instances \
  --db-instance-identifier instacart-dev \
  --query "DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId" --output text)
aws ec2 authorize-security-group-ingress \
  --group-id $RDS_SG_ID --protocol tcp --port 5432 --cidr "${MY_IP}/32"

# Enable public access temporarily
aws rds modify-db-instance \
  --db-instance-identifier instacart-dev \
  --publicly-accessible --apply-immediately
```

> ⚠️ AWS auto-restarts stopped RDS instances after **7 days**. Run `aws rds stop-db-instance` again if you see it running unexpectedly.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `pg_hba.conf` rejects DMS connection | RDS requires SSL | DMS source endpoint already set to `ssl_mode = "require"` — check it in `infra/modules/dms/main.tf` |
| DMS S3 test-connection fails | Replication instance has no public IP | `publicly_accessible = true` already set in module — re-apply terraform |
| `S3 date partition is not supported` | DMS doesn't support date partitioning for full-load | `date_partition_enabled = false` already set — re-apply terraform |
| Can't delete replication instance | Replication task still attached | `aws dms delete-replication-task --replication-task-arn <arn>` first |
| `FATAL: connection refused` from seeder | RDS not publicly accessible | Run Step 2 again |
| Seeder hangs / very slow | Normal — 32M rows takes 15–20 min | Let it run; check progress in logs |
| `API_ENDPOINT is not set` | Env var missing | `export API_ENDPOINT=$TF_API_ENDPOINT` |

---

## What's in S3 After This Runbook

```
s3://instacart-mlops-bronze-dev-<account_id>/
├── bronze/
│   ├── historical/                          ← from DMS (RDS full load)
│   │   └── public/
│   │       ├── orders/
│   │       │   └── LOAD00000001.csv.gz      (3.4M rows, 44 MB)
│   │       └── order_products/
│   │           ├── LOAD00000001.csv.gz      (32M rows part 1, 185 MB)
│   │           └── LOAD00000002.csv.gz      (32M rows part 2,  84 MB)
│   └── api/                                 ← from Lambda (API simulator)
│       ├── aisle/YYYY/MM/DD/*.json          (134 files)
│       ├── department/YYYY/MM/DD/*.json     (21 files)
│       └── product/YYYY/MM/DD/*.json        (49,688 files)
```

**Next steps (not covered in this runbook):**
- Silver layer: Glue/Spark ETL to clean and standardize the bronze data
- Gold layer: Aggregate feature tables for ML modeling
- Kinesis Stream: third data source (real-time order events)
