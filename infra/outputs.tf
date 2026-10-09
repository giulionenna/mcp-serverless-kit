output "mcp_url" { value = "${trimsuffix(aws_lambda_function_url.oauth_compat.function_url, "/")}/mcp" }
output "gateway_url" { value = aws_bedrockagentcore_gateway.mcp.gateway_url }
output "oauth_client_id" { value = aws_cognito_user_pool_client.mcp.id }
output "oauth_scope" { value = local.scope }
output "user_pool_id" { value = aws_cognito_user_pool.users.id }
output "oauth_authorization_url" { value = "https://${aws_cognito_user_pool_domain.mcp.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/authorize" }
output "oauth_token_url" { value = "https://${aws_cognito_user_pool_domain.mcp.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/token" }
output "garmin_secret_arn" { value = try(aws_secretsmanager_secret.garmin[0].arn, null) }

output "oauth_issuer" {
  value = trimsuffix(aws_lambda_function_url.oauth_compat.function_url, "/")
}
output "token_issuer" {
  value = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.users.id}"
}
