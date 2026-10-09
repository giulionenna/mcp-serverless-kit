# The public Function URL serves discovery and transports MCP requests.
# Cognito issues tokens; Gateway validates them, including the public audience.
# S3 holds only the Gateway URL, breaking the URL -> Gateway -> Lambda cycle.
resource "aws_iam_role" "oauth_compat" {
  name = "${var.project_name}-oauth-compat-lambda"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_cloudwatch_log_group" "oauth_compat" {
  name              = "/aws/lambda/${var.project_name}-oauth-compat"
  retention_in_days = 7
}

resource "aws_iam_role_policy" "oauth_compat" {
  role = aws_iam_role.oauth_compat.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.oauth_compat.arn}:*" },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.schemas.arn}/connection/gateway.json" }
    ]
  })
}

resource "aws_lambda_function" "oauth_compat" {
  function_name    = "${var.project_name}-oauth-compat"
  role             = aws_iam_role.oauth_compat.arn
  filename         = "${local.root}/dist/oauth-compat.zip"
  source_code_hash = filebase64sha256("${local.root}/dist/oauth-compat.zip")
  runtime          = "python3.12"
  handler          = "oauth_compat.lambda_handler"
  timeout          = 60
  memory_size      = 128
  environment {
    variables = {
      MCP_SCOPE            = local.scope
      COGNITO_OAUTH_ORIGIN = "https://${aws_cognito_user_pool_domain.mcp.domain}.auth.${var.aws_region}.amazoncognito.com"
      COGNITO_TOKEN_ISSUER = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.users.id}"
      COGNITO_CLIENT_ID    = aws_cognito_user_pool_client.mcp.id
      CONFIG_BUCKET        = aws_s3_bucket.schemas.id
      CONFIG_KEY           = "connection/gateway.json"
    }
  }
  depends_on = [aws_iam_role_policy.oauth_compat]
}

# Provider 6.54 adds BOTH public URL invocation permissions, including
# InvokedViaFunctionUrl=true. JWT enforcement remains on the upstream Gateway.
resource "aws_lambda_function_url" "oauth_compat" {
  function_name      = aws_lambda_function.oauth_compat.function_name
  authorization_type = "NONE"
  invoke_mode        = "BUFFERED"
}

resource "aws_s3_object" "gateway_connection" {
  bucket       = aws_s3_bucket.schemas.id
  key          = "connection/gateway.json"
  content      = jsonencode({ gateway_url = aws_bedrockagentcore_gateway.mcp.gateway_url })
  content_type = "application/json"
  depends_on   = [aws_s3_bucket_public_access_block.schemas]
}
