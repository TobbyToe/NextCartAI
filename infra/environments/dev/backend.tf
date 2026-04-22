terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # Pre-create this bucket once before first `terraform init`:
  #   aws s3 mb s3://instacart-mlops-tfstate --region <your-region>
  #   aws s3api put-bucket-versioning \
  #     --bucket instacart-mlops-tfstate \
  #     --versioning-configuration Status=Enabled
  backend "s3" {
    bucket = "instacart-mlops-tfstate"
    key    = "dev/terraform.tfstate"
    region = "ap-southeast-2"
  }
}
