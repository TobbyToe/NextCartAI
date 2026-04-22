data "aws_iam_policy_document" "assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "s3_write" {
  statement {
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${var.bronze_bucket_arn}/bronze/api/*"]
  }
}

resource "aws_iam_role_policy" "s3_write" {
  name   = "s3-bronze-api-write"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.s3_write.json
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "this" {
  filename         = var.source_zip_path
  function_name    = var.function_name
  role             = aws_iam_role.this.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.11"
  timeout          = 30
  source_code_hash = filebase64sha256(var.source_zip_path)

  environment {
    variables = {
      BRONZE_BUCKET = var.bronze_bucket_id
      ENVIRONMENT   = var.environment
    }
  }

  tags = var.tags
}
