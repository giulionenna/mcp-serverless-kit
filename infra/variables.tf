variable "aws_region" {
  type    = string
  default = "us-east-1"
}
variable "project_name" {
  type    = string
  default = "personal-mcp"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.project_name))
    error_message = "Use 3–25 lowercase letters, digits, or hyphens, starting with a letter."
  }
}
variable "callback_urls" {
  type        = list(string)
  description = "Exact OAuth redirect URLs supplied by your MCP clients; no compatibility assumptions are made."
  validation {
    condition     = length(var.callback_urls) > 0 && alltrue([for u in var.callback_urls : startswith(u, "https://")])
    error_message = "Supply at least one exact HTTPS callback URL."
  }
}
variable "logout_urls" {
  type    = list(string)
  default = []
}
variable "lambda_timeout" {
  type    = number
  default = 30
  validation {
    condition     = var.lambda_timeout >= 1 && var.lambda_timeout <= 60
    error_message = "Use a timeout from 1 to 60 seconds."
  }
}
variable "lambda_memory_mb" {
  type    = number
  default = 256
  validation {
    condition     = var.lambda_memory_mb >= 128 && var.lambda_memory_mb <= 1024 && floor(var.lambda_memory_mb) == var.lambda_memory_mb
    error_message = "Use an integer memory allocation from 128 to 1024 MB for this low-cost starter."
  }
}

variable "refresh_token_days" {
  type    = number
  default = 30
  validation {
    condition     = var.refresh_token_days >= 1 && var.refresh_token_days <= 365
    error_message = "Refresh token lifetime must be 1–365 days."
  }
}

variable "garmin_reserved_concurrency" {
  type        = number
  default     = -1
  description = "Set to 1 to serialize Garmin token refresh; -1 uses account concurrency. Reservation requires at least 101 currently unreserved regional concurrency units."
  validation {
    condition     = contains([-1, 1], var.garmin_reserved_concurrency)
    error_message = "Use -1 (no reservation) or 1 (serialize Garmin)."
  }
}
