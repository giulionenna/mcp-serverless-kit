# Project status

Last updated: 2026-10-10. This is the concise handoff for new coding-agent chats.
Read it with [agent instructions](../AGENTS.md) and the [runbook](../README.md).
It records project context, not a complete conversation history or live AWS state.

## Goal and priorities

The owner's primary reason for this repository is to connect Garmin to ChatGPT
through a personal MCP service. The AWS foundation and example tools support that
goal; they are not the final deliverable.

1. Complete and verify a usable Garmin MCP integration with a real account.
2. Support multiple separately registered MCP apps from the same repository.
   The current proposal shares one AWS AgentCore Gateway and module Lambdas;
   it does not require a separate Gateway deployment for each app.

## Current baseline

- The repository provides AgentCore Gateway, Lambda modules, Cognito, a public
  OAuth compatibility adapter, S3 and GitHub Actions OIDC deployment.
- The owner reported the AWS installation and ChatGPT connection working on
  2026-10-09. See [verification evidence](verification.md) for CI/deployment
  references and the distinction between reported results and captured checks.
- `config/modules.json` enables only `example`. The optional Garmin module
  already implements `daily_stats`, `sleep` and `activities` using unofficial
  `garminconnect`, with an interactive login helper and Secrets Manager session
  persistence. Real-account reads and renewal remain unverified.
- The adapter currently exposes one `/mcp` endpoint and one shared tool catalog.
  Separate endpoints, filtered catalogs and per-group authorization are not
  implemented. SmartThings is a future example, not an existing module.
- AWS CLI caller identity succeeded in the cloud environment on 2026-10-10.
  This establishes authentication for that session, not all AWS permissions or
  availability in future chats. Recheck access when needed.

## Open work

### Garmin: primary priority

Start from [the existing Garmin module guide](garmin.md) and implementation;
do not assume a new server must be written from scratch. Confirm the intended
tool coverage, enable/deploy only when authorized, complete private interactive
login, and verify real read-only calls and session renewal. Keep health data and
credentials out of public logs, issues and documentation.

The owner described a Garmin issue, but GitHub inspection on 2026-10-10 returned
only issue #5, including when listing all issue states. No Garmin issue URL is
confirmed. Locate or create the agreed tracking issue when that work is scoped.

Earlier ChatGPT discussions contain additional requirements. Recent messages from
the relevant conversation were accessible during this handoff, but the initial
Garmin requirements were not returned. Obtain the relevant excerpts or a summary
from the owner before treating tool coverage or a reference server as decided.

### Multiple MCP apps

Tracked in [issue #5](https://github.com/giulionenna/mcp-serverless-kit/issues/5),
open as of 2026-10-10. Its proposal is endpoint-to-module-group configuration
(for example `/mcp/garmin` and `/mcp/smartthings`) through one Gateway. It requires
filtering every discovery variant and pagination, rejecting cross-group calls,
designing consistent OAuth resources/scopes/audience validation, and preserving
existing `/mcp` clients through a documented migration.

Separate app registration must not be confused with authorization isolation.
Use the issue's acceptance criteria when designing and testing this extension.
Implementation is still backlog work; this handoff does not authorize it.

## Working decisions and next steps

- Work in the cloud checkout. Use branch/PR changes; code or documentation changes
  do not authorize a production deployment or a merge.
- Preserve the existing installation and configuration. Do not repeat bootstrap
  just because a new chat starts. Read current outputs before live operations.
- Keep this file current with meaningful changes and publish it through Git so
  future cloud checkouts can read it. A shared environment or sidebar project
  does not automatically supply every previous chat's history.
- Next: recover the missing Garmin requirements, agree on its tracking issue and
  a small implementation/verification task, then assess the existing module.
- Remaining baseline checks include refresh after access-token expiry, other MCP
  clients, real Garmin reads/renewal and teardown; see [verification](verification.md).
- Daily automation was discussed as a later possibility. No scheduler or budget
  controller is established by this document; do not assume one is configured.
