variable "environment" {
  type = string
}

variable "bronze_bucket_id" {
  type = string
}

variable "bronze_bucket_arn" {
  type = string
}

variable "shard_count" {
  type    = number
  default = 1
}

variable "retention_hours" {
  type    = number
  default = 24
}

variable "buffer_interval_seconds" {
  type    = number
  default = 60
}

variable "buffer_size_mb" {
  type    = number
  default = 5
}

variable "tags" {
  type    = map(string)
  default = {}
}
