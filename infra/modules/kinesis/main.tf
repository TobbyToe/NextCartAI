# ── Kinesis Data Stream ───────────────────────────────────────────────────────

resource "aws_kinesis_stream" "this" {
  name             = "instacart-stream-${var.environment}"
  shard_count      = var.shard_count
  retention_period = var.retention_hours

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  tags = var.tags
}

# ── IAM Role: Firehose → KDS + S3 ────────────────────────────────────────────

resource "aws_iam_role" "firehose" {
  name = "firehose-instacart-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "firehose.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy" "firehose" {
  name = "firehose-kds-s3"
  role = aws_iam_role.firehose.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:DescribeStream",
          "kinesis:ListShards",
          "kinesis:SubscribeToShard",
        ]
        Resource = aws_kinesis_stream.this.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetBucketLocation",
          "s3:ListBucket",
        ]
        Resource = [
          var.bronze_bucket_arn,
          "${var.bronze_bucket_arn}/*",
        ]
      }
    ]
  })
}

# ── Kinesis Firehose: KDS → S3 Bronze ────────────────────────────────────────

resource "aws_kinesis_firehose_delivery_stream" "this" {
  name        = "instacart-firehose-${var.environment}"
  destination = "extended_s3"

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.this.arn
    role_arn           = aws_iam_role.firehose.arn
  }

  extended_s3_configuration {
    bucket_arn          = var.bronze_bucket_arn
    role_arn            = aws_iam_role.firehose.arn
    prefix              = "bronze/stream/!{timestamp:yyyy}/!{timestamp:MM}/!{timestamp:dd}/!{timestamp:HH}/"
    error_output_prefix = "bronze/stream-errors/!{firehose:error-output-type}/!{timestamp:yyyy}/!{timestamp:MM}/!{timestamp:dd}/"
    buffering_interval  = var.buffer_interval_seconds
    buffering_size      = var.buffer_size_mb
    compression_format  = "GZIP"
  }

  tags = var.tags
}
