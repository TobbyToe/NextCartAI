output "api_endpoint" {
  value = "${aws_apigatewayv2_stage.default.invoke_url}/product-events"
}

output "api_id" {
  value = aws_apigatewayv2_api.this.id
}
