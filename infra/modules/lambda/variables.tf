variable "function_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "bronze_bucket_id" {
  type = string
}

variable "bronze_bucket_arn" {
  type = string
}

variable "source_zip_path" {
  type = string
}

variable "api_key" {
  type      = string
  sensitive = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
