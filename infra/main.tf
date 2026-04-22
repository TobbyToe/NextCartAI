# Terraform deployments are managed per-environment.
# To deploy, navigate to the target environment and run Terraform from there:
#
#   cd infra/environments/dev
#   cp terraform.tfvars.example terraform.tfvars   # fill in values
#   export TF_VAR_db_password="your-secret"
#   terraform init
#   terraform plan
#   terraform apply
#
# Module definitions: infra/modules/
# Lambda source code: infra/lambda_handlers/
