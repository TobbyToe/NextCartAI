variable "environment" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "rds_security_group_id" {
  type        = string
  description = "RDS security group — replication instance joins it so RDS's ingress rule already permits access."
}

variable "rds_host" {
  type = string
}

variable "db_name" {
  type    = string
  default = "instacart"
}

variable "db_username" {
  type = string
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "bronze_bucket_id" {
  type = string
}

variable "bronze_bucket_arn" {
  type = string
}

variable "replication_instance_class" {
  type    = string
  default = "dms.t3.small"
}

variable "tags" {
  type    = map(string)
  default = {}
}
