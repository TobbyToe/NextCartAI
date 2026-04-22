output "replication_instance_arn" {
  value = aws_dms_replication_instance.this.replication_instance_arn
}

output "task_arn" {
  value = aws_dms_replication_task.full_load.replication_task_arn
}

output "s3_target_prefix" {
  value = "s3://${var.bronze_bucket_id}/bronze/historical/"
}
