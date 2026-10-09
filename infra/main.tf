data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
locals {
  root         = abspath("${path.module}/..")
  enabled      = toset(jsondecode(file("${local.root}/config/modules.json")).enabled)
  modules      = { for name in local.enabled : name => jsondecode(file("${local.root}/modules/${name}/manifest.json")) }
  prefix       = "${var.project_name}-${data.aws_caller_identity.current.account_id}"
  mcp_resource = "${trimsuffix(aws_lambda_function_url.oauth_compat.function_url, "/")}/mcp"
  scope        = "${local.mcp_resource}/tools"
}
resource "aws_s3_bucket" "schemas" {
  bucket        = "${local.prefix}-${var.aws_region}-schemas"
  force_destroy = true
}
resource "aws_s3_bucket_public_access_block" "schemas" {
  bucket                  = aws_s3_bucket.schemas.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "schemas" {
  bucket = aws_s3_bucket.schemas.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
resource "aws_s3_object" "schema" {
  for_each = local.modules
  bucket   = aws_s3_bucket.schemas.id
  # Content-addressed keys force Gateway to re-import changed tool definitions.
  key          = "schemas/${each.key}-${sha256(jsonencode(each.value.tools))}.json"
  content      = jsonencode(each.value.tools)
  content_type = "application/json"
  depends_on   = [aws_s3_bucket_public_access_block.schemas]
}
resource "aws_cognito_user_pool" "users" {
  name           = var.project_name
  user_pool_tier = "ESSENTIALS"
  admin_create_user_config { allow_admin_create_user_only = true }
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  password_policy {
    minimum_length    = 14
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }
}
resource "aws_cognito_resource_server" "mcp" {
  identifier   = var.project_name
  name         = "MCP tools"
  user_pool_id = aws_cognito_user_pool.users.id
  scope {
    scope_name        = "tools"
    scope_description = "Access personal MCP tools"
  }
}
resource "aws_cognito_user_pool_client" "mcp" {
  name                                 = "${var.project_name}-oauth"
  user_pool_id                         = aws_cognito_user_pool.users.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile", "phone", aws_cognito_resource_server.mcp_bound.scope_identifiers[0]]
  callback_urls                        = var.callback_urls
  logout_urls                          = var.logout_urls
  supported_identity_providers         = ["COGNITO"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  explicit_auth_flows                  = ["ALLOW_USER_SRP_AUTH"]
  refresh_token_rotation {
    feature                    = "ENABLED"
    retry_grace_period_seconds = 0
  }
  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = var.refresh_token_days
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
# Resource-bound custom scopes must belong to the exact requested resource.
# Keep the previous resource definition during migration; it is no longer
# enabled for the app client or accepted by Gateway.
resource "aws_cognito_resource_server" "mcp_bound" {
  identifier   = local.mcp_resource
  name         = "MCP resource-bound tools"
  user_pool_id = aws_cognito_user_pool.users.id
  scope {
    scope_name        = "tools"
    scope_description = "Access personal MCP tools"
  }
}
resource "aws_cognito_user_pool_domain" "mcp" {
  domain                = "${local.prefix}-${var.aws_region}"
  user_pool_id          = aws_cognito_user_pool.users.id
  managed_login_version = 2
}
# RFC 8707 resource binding is a Managed Login feature. API-created app clients
# also need an explicit branding style before Managed Login can serve them.
resource "aws_cognito_managed_login_branding" "mcp" {
  client_id                   = aws_cognito_user_pool_client.mcp.id
  user_pool_id                = aws_cognito_user_pool.users.id
  use_cognito_provided_values = true
  depends_on                  = [aws_cognito_user_pool_domain.mcp]
}
resource "aws_iam_role" "lambda" {
  for_each           = local.modules
  name               = "${var.project_name}-${each.key}-lambda"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.modules
  name              = "/aws/lambda/${var.project_name}-${each.key}"
  retention_in_days = 7
}
resource "aws_iam_role_policy" "lambda_logs" {
  for_each = local.modules
  role     = aws_iam_role.lambda[each.key].id
  policy   = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.lambda[each.key].arn}:*" }] })
}
resource "aws_secretsmanager_secret" "garmin" {
  count                   = contains(local.enabled, "garmin") ? 1 : 0
  name                    = "${var.project_name}/garmin"
  description             = "Populate manually; Terraform never receives credential or token values."
  recovery_window_in_days = 7
}
resource "aws_iam_role_policy" "garmin_secret" {
  count  = contains(local.enabled, "garmin") ? 1 : 0
  role   = aws_iam_role.lambda["garmin"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"], Resource = aws_secretsmanager_secret.garmin[0].arn }] })
}
resource "aws_lambda_function" "module" {
  for_each                       = local.modules
  function_name                  = "${var.project_name}-${each.key}"
  role                           = aws_iam_role.lambda[each.key].arn
  filename                       = "${local.root}/dist/${each.key}.zip"
  source_code_hash               = filebase64sha256("${local.root}/dist/${each.key}.zip")
  runtime                        = "python3.12"
  handler                        = "handler.lambda_handler"
  timeout                        = var.lambda_timeout
  memory_size                    = var.lambda_memory_mb
  reserved_concurrent_executions = each.key == "garmin" ? var.garmin_reserved_concurrency : -1
  environment {
    variables = merge({ MODULE_NAME = each.key }, each.key == "garmin" ? { GARMIN_SECRET_ARN = aws_secretsmanager_secret.garmin[0].arn } : {})
  }
  depends_on = [aws_iam_role_policy.lambda_logs, aws_iam_role_policy.garmin_secret]
}
resource "aws_iam_role" "gateway" {
  name               = "${var.project_name}-gateway"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "bedrock-agentcore.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }, ArnLike = { "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:gateway/*" } } }] })
}
resource "aws_iam_role_policy" "gateway" {
  role = aws_iam_role.gateway.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [for f in aws_lambda_function.module : f.arn] },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.schemas.arn}/schemas/*" }
  ] })
}
resource "aws_bedrockagentcore_gateway" "mcp" {
  name            = var.project_name
  role_arn        = aws_iam_role.gateway.arn
  authorizer_type = "CUSTOM_JWT"
  protocol_type   = "MCP"
  protocol_configuration {
    mcp {
      supported_versions = ["2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"]
    }
  }
  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url    = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.users.id}/.well-known/openid-configuration"
      allowed_clients  = [aws_cognito_user_pool_client.mcp.id]
      allowed_scopes   = [local.scope]
      allowed_audience = [local.mcp_resource]
    }
  }
  depends_on = [aws_iam_role_policy.gateway, aws_cognito_user_pool_domain.mcp]
}
resource "aws_bedrockagentcore_gateway_target" "module" {
  for_each           = local.modules
  name               = each.key
  description        = each.value.description
  gateway_identifier = aws_bedrockagentcore_gateway.mcp.gateway_id
  credential_provider_configuration {
    gateway_iam_role {}
  }
  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.module[each.key].arn
        tool_schema {
          s3 {
            uri                     = "s3://${aws_s3_bucket.schemas.id}/${aws_s3_object.schema[each.key].key}"
            bucket_owner_account_id = data.aws_caller_identity.current.account_id
          }
        }
      }
    }
  }
}
