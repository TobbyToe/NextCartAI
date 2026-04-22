provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "instacart-mlops"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

# Use default VPC for dev; replace with a dedicated VPC module for prod
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "archive_file" "product_api_handler" {
  type        = "zip"
  source_file = "${path.root}/../../lambda_handlers/product_api/handler.py"
  output_path = "${path.root}/../../lambda_handlers/product_api.zip"
}

# ── S3 Bronze Bucket ──────────────────────────────────────────────────────────
module "bronze_s3" {
  source      = "../../modules/s3"
  bucket_name = "instacart-mlops-bronze-${var.environment}-${data.aws_caller_identity.current.account_id}"
}

# ── RDS PostgreSQL (Historical Orders) ───────────────────────────────────────
module "rds" {
  source              = "../../modules/rds"
  identifier          = "instacart-${var.environment}"
  vpc_id              = data.aws_vpc.default.id
  subnet_ids          = data.aws_subnets.default.ids
  allowed_cidr_blocks = [data.aws_vpc.default.cidr_block]
  db_username         = var.db_username
  db_password         = var.db_password
  skip_final_snapshot = true
}

# ── Lambda + IAM (Product API Handler) ───────────────────────────────────────
module "lambda" {
  source            = "../../modules/lambda"
  function_name     = "instacart-product-api-${var.environment}"
  environment       = var.environment
  bronze_bucket_id  = module.bronze_s3.bucket_id
  bronze_bucket_arn = module.bronze_s3.bucket_arn
  source_zip_path   = data.archive_file.product_api_handler.output_path
}

# ── API Gateway (HTTP API) ────────────────────────────────────────────────────
module "api_gateway" {
  source               = "../../modules/api_gateway"
  api_name             = "instacart-product-api-${var.environment}"
  lambda_invoke_arn    = module.lambda.invoke_arn
  lambda_function_name = module.lambda.function_name
}

# ── DMS: RDS → S3 Bronze (Full Load) ─────────────────────────────────────────
module "dms" {
  source                = "../../modules/dms"
  environment           = var.environment
  subnet_ids            = data.aws_subnets.default.ids
  rds_security_group_id = module.rds.security_group_id
  rds_host              = module.rds.host
  db_username           = var.db_username
  db_password           = var.db_password
  bronze_bucket_id      = module.bronze_s3.bucket_id
  bronze_bucket_arn     = module.bronze_s3.bucket_arn
}

output "rds_endpoint" {
  value = module.rds.endpoint
}

output "product_api_endpoint" {
  value = module.api_gateway.api_endpoint
}

output "bronze_bucket" {
  value = module.bronze_s3.bucket_id
}

output "dms_s3_prefix" {
  value = module.dms.s3_target_prefix
}

output "dms_task_arn" {
  value = module.dms.task_arn
}
