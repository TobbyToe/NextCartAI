# ── Account-level roles required by DMS (one-time per AWS account) ────────────
# If these roles already exist, import them:
#   terraform import module.dms.aws_iam_role.dms_vpc dms-vpc-role
#   terraform import module.dms.aws_iam_role.dms_logs dms-cloudwatch-logs-role

resource "aws_iam_role" "dms_vpc" {
  name = "dms-vpc-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "dms.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "dms_vpc" {
  role       = aws_iam_role.dms_vpc.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonDMSVPCManagementRole"
}

resource "aws_iam_role" "dms_logs" {
  name = "dms-cloudwatch-logs-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "dms.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "dms_logs" {
  role       = aws_iam_role.dms_logs.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonDMSCloudWatchLogsRole"
}

# ── IAM Role: DMS → S3 Bronze ─────────────────────────────────────────────────

resource "aws_iam_role" "dms_s3" {
  name = "dms-s3-bronze-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "dms.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy" "dms_s3_write" {
  name = "s3-bronze-historical-write"
  role = aws_iam_role.dms_s3.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
        Resource = "${var.bronze_bucket_arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation", "s3:ListBucket"]
        Resource = var.bronze_bucket_arn
      }
    ]
  })
}

# ── DMS Subnet Group ──────────────────────────────────────────────────────────

resource "aws_dms_replication_subnet_group" "this" {
  replication_subnet_group_id          = "instacart-${var.environment}"
  replication_subnet_group_description = "DMS subnet group for ${var.environment}"
  subnet_ids                           = var.subnet_ids
  tags                                 = var.tags

  depends_on = [aws_iam_role_policy_attachment.dms_vpc]
}

# ── DMS Replication Instance ──────────────────────────────────────────────────

resource "aws_dms_replication_instance" "this" {
  replication_instance_id     = "instacart-${var.environment}"
  replication_instance_class  = var.replication_instance_class
  replication_subnet_group_id = aws_dms_replication_subnet_group.this.replication_subnet_group_id
  vpc_security_group_ids      = [var.rds_security_group_id]
  publicly_accessible         = true
  multi_az                    = false
  tags                        = var.tags
}

# ── Source Endpoint: RDS PostgreSQL ──────────────────────────────────────────

resource "aws_dms_endpoint" "source" {
  endpoint_id   = "instacart-rds-src-${var.environment}"
  endpoint_type = "source"
  engine_name   = "postgres"
  server_name   = var.rds_host
  port          = 5432
  database_name = var.db_name
  username      = var.db_username
  password      = var.db_password
  ssl_mode      = "require"
  tags          = var.tags
}

# ── Target Endpoint: S3 Bronze ────────────────────────────────────────────────

resource "aws_dms_endpoint" "target" {
  endpoint_id   = "instacart-s3-bronze-${var.environment}"
  endpoint_type = "target"
  engine_name   = "s3"

  s3_settings {
    bucket_name              = var.bronze_bucket_id
    bucket_folder            = "bronze/historical"
    service_access_role_arn  = aws_iam_role.dms_s3.arn
    data_format              = "csv"
    compression_type         = "GZIP"
    timestamp_column_name    = "dms_load_ts"
    include_op_for_full_load = false
    date_partition_enabled   = false
  }

  tags = var.tags
}

# ── Replication Task: Full Load ───────────────────────────────────────────────

resource "aws_dms_replication_task" "full_load" {
  replication_task_id      = "instacart-full-load-${var.environment}"
  migration_type           = "full-load"
  replication_instance_arn = aws_dms_replication_instance.this.replication_instance_arn
  source_endpoint_arn      = aws_dms_endpoint.source.endpoint_arn
  target_endpoint_arn      = aws_dms_endpoint.target.endpoint_arn
  start_replication_task   = false

  table_mappings = jsonencode({
    rules = [
      {
        "rule-type"      = "selection"
        "rule-id"        = "1"
        "rule-name"      = "orders"
        "rule-action"    = "include"
        "object-locator" = { "schema-name" = "public", "table-name" = "orders" }
      },
      {
        "rule-type"      = "selection"
        "rule-id"        = "2"
        "rule-name"      = "order-products"
        "rule-action"    = "include"
        "object-locator" = { "schema-name" = "public", "table-name" = "order_products" }
      }
    ]
  })

  replication_task_settings = jsonencode({
    FullLoadSettings = {
      TargetTablePrepMode  = "DO_NOTHING"
      MaxFullLoadSubTasks  = 2
      CommitRate           = 50000
    }
    Logging = {
      EnableLogging = true
      LogComponents = [
        { Id = "SOURCE_UNLOAD", Severity = "LOGGER_SEVERITY_DEFAULT" },
        { Id = "TARGET_LOAD",   Severity = "LOGGER_SEVERITY_DEFAULT" }
      ]
    }
  })

  tags = var.tags
}
