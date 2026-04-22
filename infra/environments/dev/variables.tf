variable "aws_region" {
  type    = string
  default = "ap-southeast-2"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "db_username" {
  type    = string
  default = "instacart_admin"
}

variable "db_password" {
  type      = string
  sensitive = true
}
