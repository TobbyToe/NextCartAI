output "stream_name" {
  value = aws_kinesis_stream.this.name
}

output "stream_arn" {
  value = aws_kinesis_stream.this.arn
}

output "firehose_name" {
  value = aws_kinesis_firehose_delivery_stream.this.name
}

output "s3_prefix" {
  value = "s3://${var.bronze_bucket_id}/bronze/stream/"
}
