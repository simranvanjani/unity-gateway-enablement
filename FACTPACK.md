# Unity Gateway Fact Pack
*Technical Enablement Resource — September 2026*

---

## 1. DEFINITION: Unity Gateway

**Unity Gateway is a runtime governance layer for AI that enforces centralized control over LLM calls and MCP (Model Context Protocol) tool access.** It sits between client applications (Databricks Apps, external apps, coding agents) and AI assets (Databricks-hosted foundation models, external LLM providers, MCP tool servers), applying UC RBAC permissions, traffic budgeting and rate limits, content guardrails (service policies), and complete observability via system tables. Every call is authenticated via Databricks Unified Auth, evaluated against UC privileges, subjected to policy checks, routed according to traffic splitting rules with automatic fallback, and logged to `system.ai_gateway.usage` with full request/response metadata.

**Source**: `docs/overview.md`, `docs/architecture.md`, `docs/auth-networking.md` (databricks-field-eng/platform-architecture-patterns)

---

## 2. ARCHITECTURE: Four-Layer Pattern & Governed Request Lifecycle

### The Four Layers

Every Unity Gateway deployment follows the same topology:

| Layer | What it contains | Example |
|-------|-----------------|---------|
| **End User Application** | Databricks Apps or external apps — the user-facing surface | Streamlit dashboard, Next.js SPA |
| **Agent Hosting** | Custom agents in Databricks (Apps, Jobs) OR external systems (Cursor, Claude Code, Codex via `ug` CLI, Genie, any agent framework) | Claude Code IDE, Cursor, Databricks Genie |
| **Unity Gateway** | Single governance control plane: permission, budget + rate limits, service policies, tracing | `/ai-gateway/model-services/*`, `/ai-gateway/mcp-services/*` endpoints |
| **AI Assets** | Model Services (Databricks-hosted FMAPIs + external providers), MCP (managed + external), Skills, External Agents | `system.ai.claude-sonnet-4-6`, `system.ai.github`, Amazon Bedrock via provider service |

**Key invariant**: Every call to an AI asset passes through Unity Gateway, regardless of where the agent is hosted.

**Source**: `docs/architecture.md` (databricks-field-eng/platform-architecture-patterns)

### The Governed Request Lifecycle: 8 Steps

```
1. Client sends request
   POST https://<workspace>/ai-gateway/model-services/main.ai_services.prod_claude/invocations
   Authorization: Bearer <databricks-token>
   Body: { "messages": [...], "max_tokens": 1024 }

2. Databricks control plane
   a. Token validation (Unified Auth)
   b. UC privilege check (EXECUTE on service)
   c. Rate limit evaluation (QPM/TPM against service + user limits)
      └─ If exceeded → HTTP 429 returned immediately

3. Service policy evaluation (ON CALL)
   For each attached policy in rank order:
   └─ DENY → return error to client immediately
   └─ ASK  → pause, await human approval
   └─ ALLOW → continue

4. Traffic manager
   └─ Select destination (traffic split weights or fallback order)
   └─ Retrieve provider credentials from encrypted store

5. Upstream dispatch
   POST https://api.anthropic.com/v1/messages
   x-api-key: <provider-key-from-databricks-vault>

6. Response received from LLM

7. Service policy evaluation (ON RESULT)
   └─ Same policy UDF chain, now on response payload
   └─ DENY → return policy error to client
   └─ ALLOW → return response to client

8. Telemetry write (async)
   └─ Row appended to system.ai_gateway.usage (metadata)
   └─ If inference logging enabled: row appended to Delta table (full payload)
```

**Source**: `docs/auth-networking.md` (databricks-field-eng/platform-architecture-patterns), labeled as "Request Path: End to End"

### Six Deployment Patterns by Name

1. **Pattern 1: Dedicated Endpoint per Team / Use Case** — Create one model service per consumer group with independent rate limits, guardrails, and access grants. Enables separate cost attribution and grants revocable without affecting other services.

2. **Pattern 2: Environment Segregation (Dev / Staging / Prod)** — Separate services per environment (`main.ai_dev.llm_endpoint`, `main.ai_staging.llm_endpoint`, `main.ai_prod.llm_endpoint`) with environment-appropriate limits and guardrails, controlled via UC grants per environment.

3. **Pattern 3: Guardrail Topology** — Policies attached to a service in rank order; first DENY wins. Example: `block_pii` (ON CALL + ON RESULT) → `block_jailbreak` (ON CALL) → `block_unsafe_content` (ON RESULT) → custom UDF.

4. **Pattern 4: Multi-Provider Routing with Fallback** — Single endpoint abstracts multiple backends with automatic failover. Example: 70% primary Claude → 30% primary GPT-4o → fallback to Claude Haiku on 429 → fallback to GPT-4o-mini. Routing decisions recorded in `system.ai_gateway.usage`.

5. **Pattern 5: Coding Agent Integration** — Agents use OpenAI-compatible API client pointed at the AI Gateway endpoint (`https://<workspace>/ai-gateway/model-services/main.ai_services.prod_claude/invocations`) for LLM calls. For tool calls, agents connect as MCP clients to gateway MCP proxy URLs, with single Databricks authentication covering both.

6. **Pattern 6: Human-in-the-Loop for Sensitive Operations** — Use `ASK` policy decisions to pause agent operations pending human approval (e.g., `DENY` for write to prod schema, `ASK` for staging, `ALLOW` for read).

**Source**: `docs/architecture.md` (databricks-field-eng/platform-architecture-patterns), sections "Pattern 1–6"

---

## 3. GOVERNANCE DIMENSIONS: The Three Control Layers

Unity Gateway enforces governance across three dimensions:

### Dimension 1: ASSET (UC RBAC)

**Mechanism**: Standard UC privilege check on model service or MCP service

| What | Privilege | Trigger | Response |
|-----|-----------|---------|----------|
| Model Service call | `EXECUTE ON MODEL SERVICE <catalog>.<schema>.<service>` | Request arrives | HTTP 403 if missing EXECUTE (or parent USE CATALOG/USE SCHEMA) |
| MCP Service call | `EXECUTE ON MCP SERVICE <catalog>.<schema>.<service>` | Request arrives | HTTP 403 if missing EXECUTE |

**Required privilege chain** (caller must have ALL three):
```sql
GRANT USE CATALOG ON CATALOG main TO ROLE ds_team;
GRANT USE SCHEMA ON SCHEMA main.ai_services TO ROLE ds_team;
GRANT EXECUTE ON MODEL SERVICE main.ai_services.prod_claude TO ROLE ds_team;
```

**Example rejection**:
```
HTTP 403: "Caller does not have EXECUTE privilege on MODEL SERVICE main.ai_services.prod_claude"
```

**Source**: `docs/auth-networking.md`, section "Authorization: UC RBAC"; `docs/architecture.md`, Pattern 2

---

### Dimension 2: TRAFFIC (Rate Limits + Budget Policies)

**Mechanism**: Per-service and per-user quotas evaluated synchronously during request evaluation (step 2c in lifecycle)

| Control | Unit | Scope | When Exceeded | Response |
|---------|------|-------|---------------|----------|
| Requests-per-minute quota | QPM | Service-wide or per-user | Count hits limit | HTTP 429 (Too Many Requests) |
| Tokens-per-minute quota | TPM | Service-wide or per-user (model services only; MCP services support QPM only) | Token count hits limit | HTTP 429 |
| Budget threshold | Total tokens | Per service or per user | Cumulative tokens exceed threshold | HTTP 429 (request blocked) |

**Non-obvious behavior — group membership**:
When a user belongs to multiple groups with different limits, they are blocked only if they exceed **all applicable group limits simultaneously**. If any group's limit isn't hit, the request passes.

**Example configuration** (via REST API):
```json
{
  "config": {
    "rate_limits": {
      "service_level": {
        "qpm_limit": 1000,
        "tpm_limit": 100000
      },
      "user_defaults": {
        "qpm_limit": 100,
        "tpm_limit": 10000
      },
      "custom_limits": [
        {
          "principal": "ds_team",
          "qpm_limit": 500,
          "tpm_limit": 50000
        }
      ]
    }
  }
}
```

**Source**: `docs/overview.md`, table "Feature Map" and "Non-Obvious Behaviors"; `docs/architecture.md`, Pattern 3

---

### Dimension 3: BEHAVIOR (Service Policies — Guardrails)

**Mechanism**: UC SQL UDFs evaluated synchronously in the request path, returning JSON decision: `{"result": "ALLOW" | "DENY" | "ASK", "message": "..."}`

| Control | Phase | Applied To | Decision Options | Response |
|---------|-------|-----------|------------------|----------|
| Built-in: `system.ai.block_pii` | ON CALL + ON RESULT | Request/response | ALLOW / DENY | HTTP 200 (ALLOW) or HTTP 400 + policy-block reason |
| Built-in: `system.ai.block_jailbreak` | ON CALL | Request only | ALLOW / DENY | HTTP 200 or HTTP 400 |
| Built-in: `system.ai.block_unsafe_content` | ON RESULT | Response only | ALLOW / DENY | HTTP 200 or HTTP 400 |
| Built-in: `system.ai.block_hallucination` | ON RESULT | Response only | ALLOW / DENY | HTTP 200 or HTTP 400 |
| Custom UDF | ON CALL and/or ON RESULT (configurable) | Request/response payload as `event VARIANT` | ALLOW / DENY / ASK | HTTP 200 or HTTP 400 (DENY/ASK) |

**Policy ranking** — first DENY wins (evaluated in rank order):
```
prod_claude_ds (model service)
 ├── [rank 1] block_pii             (ON CALL + ON RESULT)
 ├── [rank 2] block_jailbreak       (ON CALL)
 ├── [rank 3] block_unsafe_content  (ON RESULT)
 └── [rank 4] custom_compliance     (ON CALL)  ← custom SQL UDF
```

**Return format** (gateway reads only `result` field; all other fields discarded):
```json
{
  "result": "DENY",           // or "ALLOW" or "ASK"
  "message": "PII detected",  // shown in error message
  "other_fields": "ignored"   // not processed
}
```

**Custom policy example — block competitor mentions**:
```sql
CREATE OR REPLACE FUNCTION main.ai_policies.block_competitor_mentions(event VARIANT)
RETURNS VARIANT
LANGUAGE PYTHON
AS $$
import json
payload = json.loads(event)
content = str(payload.get("messages", "")).lower()
if any(c in content for c in ["snowflake", "redshift", "bigquery"]):
    return json.dumps({"decision": "DENY", "message": "Competitor references not allowed."})
return json.dumps({"decision": "ALLOW"})
$$;
```

**Attach to service via REST**:
```bash
curl -X PATCH "${WORKSPACE}/api/2.1/unity-catalog/model-services/{fqn}?update_mask=config.service_policies" \
  -d '{
    "config": {
      "service_policies": [{
        "name": "my_guard", "policy_type": "POLICY_TYPE_CUSTOM",
        "handler": "functions/catalog.schema.my_guard",
        "options": {"phases": "pre_call,post_call"}
      }]
    }
  }'
```

**Fail-closed**: If a policy UDF throws an error during evaluation, the decision defaults to `DENY`. A misconfigured policy never silently opens access.

**Status**: Service policies are currently in **Beta** (account admins can control access from account console Previews page).

**Limitation**: Payload mutation (request rewriting, response transformation) is **not currently supported** — only block/pass decisions. Tested July 2026; attempting to return `modified_message` fields is ignored. Mutation is on the product roadmap.

**Source**: `docs/guardrails.md`; `docs/architecture.md`, Pattern 3; WebFetch from https://docs.databricks.com/aws/en/data-governance/unity-catalog/service-policies/ (Beta status); `docs/guardrails.md` (mutation limitation note)

---

## 4. FM API / MODEL SERVICES

### Creating a Model Service

**Via UI**: AI Gateway → Create → Model Service → select catalog/schema → enter name → choose destination from `system.ai.*` FMAPIs → Create

**Via REST API**:
```bash
curl -X POST "https://<workspace>/api/2.1/unity-catalog/model-services" \
  -H "Authorization: Bearer $DATABRICKS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model_service_id": "prod_claude",
    "parent": "schemas/main.ai_services",
    "config": {
      "routing": {
        "destinations": [{
          "destination_type": "DESTINATION_TYPE_FOUNDATION_MODEL",
          "name": "claude_primary",
          "traffic_percentage": 100,
          "foundation_model_config": {
            "model_api": "system.ai.claude-sonnet-4-6"
          }
        }]
      }
    }
  }'
```

**Via Terraform**:
```hcl
resource "databricks_ai_gateway_model_service" "prod_claude" {
  provider = databricks.workspace

  model_service_id = "prod_claude"
  parent           = "schemas/main.ai_services"

  config {
    routing {
      destinations {
        destination_type = "DESTINATION_TYPE_FOUNDATION_MODEL"
        name             = "claude_primary"
        traffic_percentage = 100

        foundation_model_config {
          model_api = "system.ai.claude-sonnet-4-6"
        }
      }
    }
  }
}
```

### Calling via SDK

**OpenAI-compatible SDK** (Databricks SDK):
```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.ai_gateway import CreateMessageRequest

w = WorkspaceClient()
response = w.ai_gateway.create_message(
    endpoint_name="main.ai_services.prod_claude",
    request=CreateMessageRequest(
        messages=[{"role": "user", "content": "Hello"}],
        model="claude-sonnet-4-6",
        max_tokens=1024
    )
)
```

**Native Python client**:
```python
from anthropic import Anthropic

client = Anthropic(
    base_url="https://<workspace>/ai-gateway",
    api_key="<databricks-token>",
    default_headers={
        "Databricks-Model-Provider-Service": "main.ai_services.prod_claude"
    }
)

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}]
)
```

**HTTP/cURL**:
```bash
curl -X POST "https://<workspace>/ai-gateway/model-services/main.ai_services.prod_claude/invocations" \
  -H "Authorization: Bearer $DATABRICKS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello"}],
    "model": "claude-sonnet-4-6",
    "max_tokens": 1024
  }'
```

**Source**: `docs/model-services.md`; `workshop/01-model-services/README.md`

---

### External Providers (Bedrock / OpenAI / Anthropic)

**Model Provider Service** — wraps external LLM provider with connection details and encrypted credentials. Separate UC securable from model service; both visible in Catalog Explorer as **Services**.

**Supported providers**: OpenAI, Azure OpenAI, Anthropic, Amazon Bedrock, Microsoft Foundry, Google Gemini Enterprise, Custom (bearer token + base URL)

**Model Provider Service vs. Model Service**:

| | Model Service | Model Provider Service |
|--|--------------|------------------------|
| Backends | Databricks-hosted `system.ai.*` FMAPIs | External providers (Bedrock, OpenAI, Anthropic…) |
| Traffic splitting | Yes — split % across multiple backends | No — caller specifies model per request |
| Guardrails | Yes | Yes |
| Rate limits | QPM and TPM | QPM only |
| Invocation | OpenAI-compatible `/invocations` | Native provider API format via header routing |

#### Amazon Bedrock via VPCE + `aws:sourceVpce` Restriction

**Key gotchas**:
- **Bedrock requires IAM user key (AKIA…), not IAM role** — roles produce temporary STS credentials with session tokens that expire in 1–12 hours; the provider service has no auto-refresh mechanism; UI has no session token field. Use long-term IAM user key. Required permissions: `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`.
- **Newer Bedrock models require cross-region inference profile** — e.g. `global.anthropic.claude-sonnet-5` works from any region; `au.anthropic.claude-sonnet-5` (Australia prefix) returns 400; `ap.anthropic.claude-sonnet-5` (AP profile) may not exist for this version.
- **Multiple targets = allowlist, not routing** — the targets list controls which model IDs are permitted; caller specifies the model in every request; gateway checks it against the list. No automatic load balancing. Set `allow_all_targets: false` in production.
- **Bedrock only supports `anthropic/v1/messages`, not OpenAI format** — `openai/v1/chat/completions` returns `INVALID_PARAMETER_VALUE: Native_api_type is not supported for provider Amazon Bedrock`.

**Working configuration** (Bedrock, `ap-southeast-1`):
```
main.default.bedrock_vpce
├── provider:          Amazon Bedrock
├── region:            ap-southeast-1
├── auth:              IAM user (AKIA…) with bedrock:InvokeModel + aws:sourceVpce restriction
├── allow_all_targets: false
├── targets:           [global.anthropic.claude-sonnet-5 / anthropic/v1/messages]
├── service_policies:  [block_pii]
└── usage_tracking:    enabled → system.ai_gateway.usage
```

**Private networking: NCC + `aws:sourceVpce`** — lock the Bedrock IAM credential so it only works through the Databricks-managed NCC VPCE:

```hcl
# NCC VPCE setup — infra/05_ncc.tf
resource "databricks_mws_ncc_private_endpoint_rule" "bedrock" {
  endpoint_service = "com.amazonaws.ap-southeast-1.bedrock-runtime"
  group_id         = "bedrock-runtime"
  enabled          = true   # REQUIRED — default false; without this no traffic routes through VPCE
}

# IAM Policy restricts to VPCE
resource "aws_iam_user_policy" "bedrock" {
  policy = jsonencode({
    Statement = [{
      Action    = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Condition = { StringEquals = {
        "aws:sourceVpce" = databricks_mws_ncc_private_endpoint_rule.bedrock.vpc_endpoint_id
      }}
    }]
  })
}
```

**Empirically tested July 2026**:

| Traffic path | DNS resolution | `aws:sourceVpce` | Result |
|---|---|---|---|
| Unity Gateway → Bedrock | `172.18.45.163` (private) | Satisfied | **200** |
| Serverless notebook (boto3) → Bedrock | `172.18.45.163` (private) | Satisfied | **200** |
| Classic cluster (boto3) → Bedrock | `18.x / 47.x` (public) | Not present | **403** |
| Local laptop (AWS CLI) → Bedrock | public | Not present | **403** |

**Invoke via native SDK** (with header routing):
```python
import anthropic

client = anthropic.Anthropic(
    base_url="https://<workspace>/ai-gateway",
    api_key="<databricks-token>",
    default_headers={
        "Databricks-Model-Provider-Service": "<catalog>.<schema>.<name>"
    }
)

response = client.messages.create(
    model="global.anthropic.claude-sonnet-5",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello from Bedrock via Unity Gateway"}]
)
```

**URL patterns by provider**:
| Provider | Path after `/ai-gateway/` |
|----------|--------------------------|
| Anthropic / Bedrock (Anthropic models) | `anthropic/v1/messages` |
| OpenAI / Azure OpenAI | `openai/v1/chat/completions` |
| Google Gemini | `google/v1/...` |

**Status**: Model provider services are generally available (GA). Bedrock integration is production-tested (July 2026).

**Source**: `docs/model-services.md`; Terraform reference in `infra/09_ai_gateway.tf`, `infra/05_ncc.tf`

---

## 5. MCP SERVICES & AGENTS

### MCP as UC Securable

An MCP Service is a first-class UC object addressed with three-part naming (`catalog.schema.mcp_service_name`), with:
- **Permissions** using standard UC `GRANT / REVOKE` on `EXECUTE`
- **Workspace scoping** — if a catalog is bound to specific workspaces, the MCP service inherits that scope
- **Auditing** — UC audit logs capture who was granted access and when
- **Tool restrictions** — configured on the service, not on the client

### Creating an MCP Service (3 Steps)

**Step 1: Register UC HTTP Connection to the server**
```sql
CREATE CONNECTION my_mcp_conn
  TYPE HTTP
  OPTIONS (
    url   = 'https://my-mcp-server.example.com',
    token = secret('my_scope', 'mcp_token')   -- Bearer token (optional)
  );
```

**Step 2: Create the MCP Service**
```sql
CREATE MCP SERVICE main.default.demo_mcp
  USING CONNECTION my_mcp_conn
  TOOL_RESTRICTIONS (
    INCLUDE 'get_*',       -- allow any tool starting with get_
    INCLUDE 'calculate',   -- allow exactly this tool
    EXCLUDE '*'            -- deny anything else
  );
```

**Step 3: Grant access**
```sql
GRANT USE CATALOG ON CATALOG main TO `data-scientists`;
GRANT USE SCHEMA  ON SCHEMA main.default TO `data-scientists`;
GRANT EXECUTE ON MCP SERVICE main.default.demo_mcp TO `data-scientists`;
```

**Note**: `CREATE MCP SERVICE` SQL DDL is not available on Serverless SQL Warehouses. MCP Services must be created via the UI or REST API (`POST /api/2.1/unity-catalog/mcp-services`).

### Tool Restrictions

**Prefix-matching rules** — evaluated in order; first match wins:
```sql
TOOL_RESTRICTIONS (
  INCLUDE 'get_*',       -- allow tools starting with get_
  INCLUDE 'calculate',   -- allow exactly this tool
  EXCLUDE '*'            -- deny anything else (catch-all)
);
```

Tool name is checked against each rule. If explicitly included, it's allowed. If not explicitly included, the catch-all deny blocks it. Tool restrictions are per-service; different services can allow different tool sets.

### Per-User OAuth

When the MCP server needs to act on behalf of the caller (not a shared service account), configure the connection with `auth_type = PER_USER_OAUTH`. The gateway then performs an OAuth exchange to obtain a user-scoped token for each caller, forwarding it to the server. Requires the server to support Databricks OAuth.

### Observability Filter for MCP

In `system.ai_gateway.usage`, MCP calls are identified by:
```sql
WHERE mcp_metadata.json_rpc_method IS NOT NULL
```

Key fields in `mcp_metadata` struct:
- `json_rpc_method` — "initialize", "tools/list", "tools/call"
- `tool_name` — populated only on "tools/call" rows; NULL on initialize/tools/list
- `server_type` — "EXTERNAL" for registered external MCP servers
- `client_name` — identifying name of the MCP client

**Query example — all MCP tool calls**:
```sql
SELECT
  event_time,
  mcp_metadata.json_rpc_method  AS method,
  mcp_metadata.tool_name        AS tool,
  mcp_metadata.server_type      AS server_type,
  requester,
  status_code
FROM system.ai_gateway.usage
WHERE mcp_metadata.json_rpc_method = 'tools/call'
ORDER BY event_time DESC;
```

### Built-in MCP Services (`system.ai.*`)

Unity Gateway ships with built-in MCP services available in every workspace without registration:
- Slack
- Gmail
- GitHub
- Google Drive
- Google Calendar
- Microsoft 365
- Atlassian

### Limitations & Workarounds

**Limitation**: Registering a Databricks App URL (`*.aws.databricksapps.com`) as a UC MCP Service is not supported. Per official docs: "You can register only external MCP servers as your own MCP Service. Registering Genie, Apps, or Unity Catalog entity sources as an MCP Service is not currently supported." Empirically confirmed July 2026; standard workspaces don't expose a DCR `registration_endpoint`.

**Workaround**: Host the MCP server on a non-Databricks URL (AWS Lambda, external host). For demos, call the Databricks App MCP server directly (bypasses gateway; produces no rows in `system.ai_gateway.usage`).

**Non-obvious**: Calls bypass `system.ai_gateway.usage` if not using the gateway URL. Direct HTTP calls to the MCP server (not through AI Gateway MCP proxy) produce no rows. To get governance and observability, register as UC MCP Service and route through the gateway.

**Source**: `docs/mcp-services.md`; `workshop/07-mcp-services/README.md`

---

## 6. CODING AGENTS: UG CLI & Agent Configuration

### UG CLI Installation (Formerly ucode)

The `ug` CLI connects Databricks coding agents (Claude Code, Cursor, Codex, GitHub Copilot, Google Gemini) to Unity Gateway for centralized governance, credential management, and observability.

**Install via uv** (from unity-gateway GitHub):
```bash
uv tool install git+https://github.com/databricks/unity-gateway

# Verify
ug --version
```

**Workaround for cryptography build error** (crates.io blocked on corporate network):
```bash
uv venv ~/.local/share/unity-gateway-env --python python3.12
uv pip install --python ~/.local/share/unity-gateway-env/bin/python \
  --only-binary cryptography \
  git+https://github.com/databricks/unity-gateway
ln -sf ~/.local/share/unity-gateway-env/bin/ug ~/.local/bin/ug
```

### Configure UG

**Step 1: Point ug at the workspace** (admin, once):
```bash
ug configure --workspace https://dbc-df2a868d-b428.cloud.databricks.com
```

**Step 2: Configure specific agents** (developer, once per workspace):
```bash
ug configure --agents codex   # for Codex Desktop
```

This writes the Databricks model provider config into `~/.codex/config.toml` — the same file Codex Desktop reads.

### Publish Workspace Agent Configuration (Admin)

In workspace UI: **Unity Gateway → Governance → Agent Configuration → Edit configuration**

**Example JSON configuration** (includes models, tracing, MCP servers):
```json
{
  "default_agent": "CODING_AGENT_CODEX",
  "enabled_agents": [
    {
      "agent": "CODING_AGENT_CODEX",
      "config": {
        "models": {
          "model_services": [
            "system.ai.gpt-5-3-codex",
            "system.ai.gpt-5-5",
            "system.ai.gpt-5-5-pro",
            "system.ai.gpt-6-sol"
          ]
        },
        "default_models": {
          "default_model": "system.ai.gpt-5-3-codex"
        },
        "tracing": {
          "enabled": true
        }
      }
    }
  ],
  "mcp_servers": {
    "names": [
      "system.ai.dbsql",
      "system.ai.microsoft_365"
    ]
  }
}
```

### Supported Agents

Agents currently supported via `ug` CLI:
- **Claude Code** (IDE extension)
- **Cursor** (IDE)
- **Codex Desktop** (ChatGPT Desktop app)
- **GitHub Copilot** (VS Code / IDE)
- **Google Gemini** (in-browser)

Each agent requires `ug configure --agents <agent-name>` for workspace-specific setup.

### Central Config Publishing & Per-Developer Cost

Once configured:
- **Central publication**: Workspace admin publishes a single `Agent Configuration` JSON that applies to all developers using Unity Gateway agents in that workspace
- **Per-developer cost tracking**: Each agent's LLM calls are attributed to the developer's identity in `system.ai_gateway.usage.requester`, enabling per-developer cost dashboards and budget enforcement
- **MCP governance**: All MCP tool calls made by the agent (e.g., SharePoint file access via `system.ai.microsoft_365`) are logged with the developer's identity and subject to tool restrictions

### Using Codex Desktop (Example)

After install + config:
1. Launch Codex Desktop
2. Sign in with ChatGPT/OpenAI account once (automatic thereafter)
3. App auto-detects `ug` configuration and switches to Unity Gateway
4. See **"Databricks AI Gateway"** label bottom-left to confirm routing
5. Every session appears in `system.ai_gateway.usage` with developer's identity; MCP calls (SharePoint, SQL) logged with tool restrictions enforced

**Verify in SQL** (after ~5 min system table lag):
```sql
-- LLM turns from agent session
SELECT event_time, requester, destination_model, input_tokens, output_tokens
FROM system.ai_gateway.usage
WHERE destination_model LIKE '%gpt%'
  AND event_time >= current_timestamp() - INTERVAL 1 HOUR
ORDER BY event_time DESC;

-- MCP tool calls from same session
SELECT event_time, requester,
       mcp_metadata.json_rpc_method AS method,
       mcp_metadata.tool_name       AS tool
FROM system.ai_gateway.usage
WHERE mcp_metadata.json_rpc_method = 'tools/call'
  AND event_time >= current_timestamp() - INTERVAL 1 HOUR
ORDER BY event_time DESC;
```

### Known Limitation: M365 MCP Cannot Read Binary Content

The M365 SharePoint connector can discover files and check permissions, but returns an error when extracting text from binary formats:
```json
{
  "content": "Unsupported file format (.pdf)",
  "truncated": false
}
```

**Workaround options**:
- Upload PDF text directly in chat
- Convert to `.txt` in SharePoint before reading
- Use custom MCP server that handles PDF extraction

**Source**: `docs/coding-agents.md`; `workshop/08-coding-agents/README.md`

---

## 7. OBSERVABILITY: System Tables & SQL Cookbook

### Two System Tables

| Table | What it captures | Latency |
|-------|-----------------|---------|
| `system.ai_gateway.usage` | Per-request metadata: tokens, latency, requester, model, MCP metadata, routing | ~5–30 min |
| `<catalog>.<schema>.<endpoint>_payload` | Full request + response JSON (only if inference logging is enabled per-endpoint) | ~5–30 min |
| `system.ai_gateway.external_model_spend` | Aggregated spend records for external model providers | Daily |

**Non-obvious**: `system.ai_gateway.usage` only captures calls made through a Unity Gateway-configured endpoint (`/ai-gateway/model-services/…` or `/ai-gateway/mcp-services/…`). Direct calls to `/serving-endpoints/…` (legacy FMAPI path) bypass the gateway and do **not** appear in this table.

### `system.ai_gateway.usage` — Full Schema

| Column | Type | Description |
|--------|------|-------------|
| `event_time` | timestamp | When the request was received |
| `account_id` | string | Databricks account |
| `workspace_id` | string | Workspace where the endpoint lives |
| `request_id` | string | Unique per-request ID — joins to payload table |
| `endpoint_id` | string | Internal endpoint ID |
| `endpoint_name` | string | UC three-part name (`catalog.schema.service`). **NULL for MCP gateway calls at protocol level** (initialize, tools/list) |
| `endpoint_metadata` | struct | `creator`, `creation_time`, `last_updated_time`, `destinations` (routing config), `inference_table` (table name if configured) |
| `endpoint_tags` | map | Tags set on the endpoint |
| `destination_type` | string | What kind of backend was called |
| `destination_name` | string | UC name of the backend |
| `destination_id` | string | Internal backend ID |
| `destination_model` | string | Model identifier (e.g. `claude-sonnet-4-5`, `gpt-5-4`) |
| `requester` | string | Email or service principal ID of the caller |
| `requester_type` | string | `USER` or `SERVICE_PRINCIPAL` |
| `ip_address` | string | Caller IP |
| `url` | string | Full request URL |
| `user_agent` | string | HTTP User-Agent header |
| `api_type` | string | API format used (e.g. `OPENAI_CHAT_COMPLETIONS`) |
| `request_tags` | map | Tags passed by the client in the request |
| `input_tokens` | bigint | Prompt tokens consumed |
| `output_tokens` | bigint | Completion tokens generated |
| `total_tokens` | bigint | Sum of input + output |
| `token_details` | struct | `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_reasoning_tokens` (Claude-specific) |
| `latency_ms` | bigint | Total round-trip latency in milliseconds |
| `time_to_first_byte_ms` | bigint | Time to first streaming token |
| `response_content_type` | string | MIME type of the response |
| `status_code` | int | HTTP status code |
| `routing_information` | struct | `attempts` array — each attempt records `action`, `destination`, `status_code`, `latency_ms` |
| `invocation_id` | string | Correlation ID across related calls |
| `invocation_metadata` | struct | `source`, `service_tier` |
| `service_type` | string | Type of AI service |
| `service_id` | string | Internal service ID |
| `service_name` | string | UC name of the service |
| `service_tags` | map | Tags on the service |
| `mcp_metadata` | struct | **Only populated for MCP service calls.** Fields: `json_rpc_method` (initialize / tools/list / tools/call), `tool_name` (NULL except on tools/call), `server_type` (EXTERNAL), `client_name` |
| `schema_version` | int | Table schema version |

**Empirically confirmed (July 2026)**: `mcp_metadata.tool_name` is NULL on `initialize` and `tools/list` calls. It is only populated when a tool is actually invoked (`tools/call`). Each MCP session generates at least two rows before any tool is called: one `initialize` and one `tools/list`.

### Inference Table (Payload Logging) Schema

Enable per-endpoint to get full request/response JSON stored to Delta.

```sql
ALTER ENDPOINT catalog.schema.my_service
  SET inference_table = 'catalog.schema.my_service_payload';
```

| Column | Type | Description |
|--------|------|-------------|
| `event_time` | timestamp | |
| `request_id` | string | Joins to `system.ai_gateway.usage` |
| `invocation_id` | string | |
| `request_tags` | map | |
| `status_code` | int | |
| `sampling_fraction` | double | If sampling < 1.0, what fraction was logged |
| `latency_ms` | bigint | |
| `request` | string | **Full JSON of the inbound request** (messages, tools array, parameters) |
| `response` | string | **Full JSON of the response** (choices, tool_calls, usage, finish_reason) |
| `destination_type`, `destination_name`, `destination_model` | string | Routing info |
| `logging_error_codes` | array | Non-empty if logging failed for this row |
| `requester` | string | |
| `time_to_first_byte_ms` | bigint | |
| `schema_version` | string | |
| `url` | string | |
| `api_type` | string | |

**Non-obvious**: Inference logs cannot be written to S3 buckets secured through private endpoints (VPCE bucket policies). Zerobus Ingest writes from the Databricks control plane — a separate network that cannot traverse a customer-controlled or NCC-managed S3 VPCE. Use an open or IAM-policy-only bucket.

---

### Five Essential SQL Cookbook Queries

#### Query 1: Traffic overview — calls, tokens, errors, latency by model (last 7 days)

```sql
SELECT
  date_trunc('hour', event_time)                         AS hour,
  coalesce(endpoint_name, '(MCP/direct)')                AS endpoint,
  destination_model,
  count(*)                                               AS total_calls,
  count_if(status_code = 200)                            AS ok_calls,
  count_if(status_code >= 400)                           AS error_calls,
  round(100.0 * count_if(status_code >= 400)
        / count(*), 1)                                   AS error_pct,
  sum(coalesce(input_tokens,  0))                        AS total_input_tokens,
  sum(coalesce(output_tokens, 0))                        AS total_output_tokens,
  round(avg(latency_ms))                                 AS avg_latency_ms,
  round(percentile_approx(latency_ms, 0.95))             AS p95_latency_ms
FROM system.ai_gateway.usage
WHERE event_time >= current_date() - INTERVAL 7 DAYS
GROUP BY 1, 2, 3
ORDER BY hour DESC, total_calls DESC;
```

#### Query 2: Per-user / per-service-principal usage today

```sql
SELECT
  coalesce(requester, '(anonymous)')                     AS requester,
  requester_type,
  count(*)                                               AS calls,
  sum(coalesce(input_tokens,  0))                        AS input_tokens,
  sum(coalesce(output_tokens, 0))                        AS output_tokens,
  round(avg(latency_ms))                                 AS avg_latency_ms,
  count_if(status_code >= 400)                           AS errors,
  collect_set(coalesce(destination_model, endpoint_name)) AS models_used
FROM system.ai_gateway.usage
WHERE event_time >= current_date()
GROUP BY 1, 2
ORDER BY calls DESC;
```

#### Query 3: MCP method + tool frequency

```sql
SELECT
  mcp_metadata.json_rpc_method  AS method,
  mcp_metadata.tool_name        AS tool,
  mcp_metadata.server_type      AS server_type,
  count(*)                      AS calls,
  count_if(status_code = 200)   AS success,
  count_if(status_code >= 400)  AS errors,
  round(avg(latency_ms))        AS avg_ms
FROM system.ai_gateway.usage
WHERE mcp_metadata.json_rpc_method IS NOT NULL
GROUP BY 1, 2, 3
ORDER BY calls DESC;
```

#### Query 4: Cache hit rate — Claude prompt caching efficiency

```sql
SELECT
  destination_model,
  sum(input_tokens)                                                           AS total_input_tokens,
  sum(output_tokens)                                                          AS total_output_tokens,
  sum(coalesce(token_details.cache_read_input_tokens, 0))                     AS cache_read_tokens,
  sum(coalesce(token_details.cache_creation_input_tokens, 0))                 AS cache_creation_tokens,
  sum(coalesce(token_details.output_reasoning_tokens, 0))                     AS reasoning_tokens,
  round(100.0 * sum(coalesce(token_details.cache_read_input_tokens, 0))
        / nullif(sum(input_tokens), 0), 1)                                    AS cache_hit_pct
FROM system.ai_gateway.usage
WHERE event_time >= current_date() - INTERVAL 7 DAYS
  AND destination_model IS NOT NULL
GROUP BY 1
ORDER BY total_input_tokens DESC;
```

#### Query 5: Routing — fallback and multi-attempt calls

```sql
SELECT
  endpoint_name,
  destination_model,
  routing_information.attempts[0].action           AS first_action,
  routing_information.attempts[0].status_code      AS first_status,
  size(routing_information.attempts)               AS num_attempts,
  count(*)                                         AS calls
FROM system.ai_gateway.usage
WHERE event_time >= current_date() - INTERVAL 7 DAYS
  AND routing_information IS NOT NULL
GROUP BY 1, 2, 3, 4, 5
ORDER BY calls DESC;
```

**Source**: `docs/observability.md`, SQL Query Cookbook sections 1–5 (verbatim); sections 6–7, 8–12 also available in source; WebFetch from https://docs.databricks.com/aws/en/ai-gateway/inference-tables

---

## 8. DELIVERY MODEL: STS Structure & Demo Proof Points

### 2-Session STS Delivery Structure

Unity Gateway enablement follows a two-session STS (Scale Solution Engineering) model:

**Session 1: Governance Foundation** (~90 min)
- Module setup + prerequisites (15 min)
- Module 01: Create + call first model service (20 min)
- Module 02: UC RBAC — GRANT/REVOKE EXECUTE (20 min)
- Module 05: Observability — usage table + SQL cookbook (20 min)
- *Hands-on*: Build a governed model service endpoint from scratch; verify LLM calls appear in `system.ai_gateway.usage`

**Session 2: Apply to Use Case** (~90 min)
- Module 03: Rate limits, traffic splitting, budget policies (20 min)
- Module 04: Guardrails — built-in and custom service policies (20 min)
- Module 06: External providers — Amazon Bedrock + VPCE (20 min)
- Module 07: MCP services — tool governance and observability (20 min)
- *Hands-on*: Build an end-to-end AI agent platform with multi-provider routing, MCP tool access control, and guardrails

**Optional deep-dive** (full-day or 2-day format):
- Module 08: Coding agents — `ug` CLI + Codex Desktop integration
- Scenarios: enterprise-governance, cost-attribution, agent-platform (end-to-end examples)

**Source**: `workshop/README.md`, "Delivery Formats"; `workshop/setup.md`; `docs/architecture.md`, "Pattern 5–6"

---

### Three Demo Proof Points

1. **Proof Point 1: Governed LLM Calls**
   - Create a model service (`main.ai_services.demo_llm`) pointing to Claude Sonnet
   - Call via Databricks SDK with rate limit (e.g., 100 TPM)
   - Execute a call; verify it appears in `system.ai_gateway.usage` with requester identity, token counts, and latency
   - Execute 101 tokens in second call; receive HTTP 429 (rate limited)
   - Show: UC RBAC blocks unauthorized caller; observability captures every call; rate limits enforce budget

2. **Proof Point 2: Guardrails in Action**
   - Attach `system.ai.block_pii` policy to the model service (ON CALL + ON RESULT)
   - Request with "My SSN is 123-45-6789"
   - Receive HTTP 400 from policy (not from LLM) — request blocked before sending to Claude
   - Attach custom policy (e.g., block competitor mentions)
   - Request with "What's Snowflake's advantage over Databricks?"
   - Receive HTTP 400 — custom policy blocks
   - Show: Multi-layer policies enforce governance; fail-closed on policy errors; observability logs policy decisions

3. **Proof Point 3: End-to-End Agent Platform**
   - Create model service (`main.ai_services.agent_llm`) with traffic split: 70% Claude → 30% GPT-4o
   - Create MCP service (`main.ai_services.agent_tools`) wrapping GitHub MCP server with tool restrictions (allow `get_*` only)
   - Connect Databricks App agent (Streamlit): agent calls LLM via model service; LLM calls tools via MCP service
   - Execute agent query (e.g., "Find recent repos matching my query")
   - Verify in `system.ai_gateway.usage`:
     - LLM call with `destination_model = claude-sonnet-4-6`, `total_tokens = X`
     - MCP call with `mcp_metadata.json_rpc_method = 'tools/call'`, `tool_name = 'get_repos'`
   - Show full session reconstruction in **Governance → Traces** (OTel trace showing LLM → MCP → LLM sequence)
   - Show: Unified observability for agent workflows; tool access governed per-service; per-developer cost attribution

**Source**: Workshop modules 01–08, "Lab" sections; `docs/observability.md`; `docs/architecture.md` (all 6 patterns)

---

## 9. GA vs BETA / ROADMAP: Feature Status Matrix

### Generally Available (GA)

| Feature | Status | Notes |
|---------|--------|-------|
| **Model Services** | GA | Create + call Databricks-hosted FMAPIs via Unity Gateway. Supported via UI, REST API, Terraform |
| **UC RBAC (GRANT/REVOKE EXECUTE)** | GA | Standard UC privileges on model/MCP services. UC audit logs capture all access changes |
| **Rate limits (QPM/TPM)** | GA | Service-level and per-user quotas. HTTP 429 on exceed. Supported via UI and API |
| **Traffic splitting** | GA | Multi-backend routing with static % weights. Session affinity on by default (not configurable) |
| **Fallback routing** | GA | Automatic retry on 429/5xx from primary to fallback destinations. Logged in `routing_information` |
| **Built-in guardrails** | GA | `system.ai.block_pii`, `block_jailbreak`, `block_unsafe_content`, `block_hallucination` (pre-built UC functions) |
| **Custom guardrails (SQL UDF)** | GA | Define custom policies as UC SQL functions; attach via REST API PATCH. CEL transpilation constraints apply |
| **`system.ai_gateway.usage` table** | GA | Per-request metadata: tokens, latency, requester, model, MCP metadata, routing. ~5–30 min lag |
| **Inference logging (payload tables)** | GA | Enable per-service to log full request/response JSON to Delta. ~5–30 min lag. Private S3 VPCE limitation noted |
| **External model providers** | GA | OpenAI, Azure OpenAI, Anthropic, Amazon Bedrock, Microsoft Foundry, Google Gemini Enterprise, Custom. Bedrock + VPCE + `aws:sourceVpce` tested empirically |
| **MCP Services** | GA | Register external MCP servers as UC securables. Tool restrictions (prefix rules), per-user OAuth, observability in `system.ai_gateway.usage` with `mcp_metadata` |
| **Built-in MCP services (`system.ai.*`)** | GA | Slack, Gmail, GitHub, Google Drive, Google Calendar, Microsoft 365, Atlassian — available in every workspace |
| **UG CLI (coding agents)** | GA | Connect Claude Code, Cursor, Codex, GitHub Copilot, Google Gemini to Unity Gateway. Central config publish; per-developer cost tracking |
| **`system.ai_gateway.external_model_spend` table** | GA | Aggregated spend by provider/model/endpoint. Daily latency |

### Beta

| Feature | Status | Notes |
|---------|--------|-------|
| **Service policies (ALLOW/DENY/ASK)** | **Beta** | Account admins can control access from account console Previews page. Decision type `ASK` (human approval hold) is Beta. Decision types: ALLOW / DENY / ASK |
| **Smart routing** | **Roadmap** | Not yet available; listed in official docs as planned |
| **OmniAgent** | **Roadmap** | Unified agent interface; not yet GA |
| **Skills** | **Roadmap** | Reusable agent capabilities; not yet GA |

### NOT Supported (Limitations / Roadmap)

| Feature | Status | Reason |
|---------|--------|--------|
| **Custom UC ML models as backends** | Not supported | Unity Gateway only governs `system.ai.*` FMAPIs and external providers. sklearn, XGBoost, MLflow pyfunc models cannot be registered as model service backends. See `docs/overview.md` comparison table |
| **Payload mutation (request rewriting, response transformation)** | Roadmap | Custom guardrails can only block/pass; cannot modify request or response content. Tested July 2026 — mutation fields are ignored. On product roadmap for future release |
| **SQL DDL for MCP Service creation** | Not supported | `CREATE MCP SERVICE` DDL fails on Serverless SQL Warehouses. Use UI or REST API only |
| **Registering Databricks Apps as UC MCP Services** | Not supported | Per official docs: "Registering Genie, Apps, or Unity Catalog entity sources as an MCP Service is not currently supported." Empirically confirmed July 2026; DCR OAuth classification fails |
| **Inference logging to private S3 endpoints (VPCE)** | Not supported | Zerobus Ingest writes from Databricks control plane — separate network from NCC VPCEs. Use open or IAM-policy-only buckets |
| **Workspace binding at FMAPI level** | Not supported | Workspace binding (BINDING TYPE ISOLATED) applies to model services but not directly to `system.ai.*` FMAPIs. FMAPI access is mediated through model service owner's definer's rights |
| **AWS GovCloud** | Not supported | "Unity Gateway is not supported on AWS GovCloud" per official docs |
| **Model service creation via SQL** | Not supported | Model services must be created via UI, REST API, or Terraform. No `CREATE MODEL SERVICE` DDL |
| **Global search for model services** | Not supported | Workspace-scoped discovery only |
| **BROWSE privilege for model services** | Not supported | Only EXECUTE privilege is enforced; discovering services requires direct access |

### Contradictions Flagged

None detected between repo docs and public Databricks docs. All key facts verified consistent across sources (repo docs `docs/`, workshop modules, public https://docs.databricks.com/aws/en/ai-gateway/).

### Items Not Verified (Could Not Confirm)

1. **Exact QPS/QPM/TPM limits** — Public docs do not specify concrete maximum rate limit values; only describe how to configure limits at different levels. Repository docs also do not cite exact thresholds.
2. **Pricing for external model provider invocations** — System table `system.ai_gateway.external_model_spend` is GA, but pricing formulas not detailed in available docs.
3. **Custom ML model RBAC path** — While docs confirm custom UC ML models are not supported as backends, the exact error message or denial mechanism is not explicitly documented (only stated as unsupported).

**Source**: `docs/overview.md` (feature map + comparison table), `docs/guardrails.md` (payload mutation limitation), `docs/mcp-services.md` (MCP limitations), `docs/coding-agents.md` (Codex Desktop note), WebFetch from https://docs.databricks.com/aws/en/data-governance/unity-catalog/service-policies/ (Beta status), https://docs.databricks.com/aws/en/ai-gateway/model-services (unsupported capabilities), https://docs.databricks.com/aws/en/ai-gateway/inference-tables (private endpoint limitation)

---

## 10. PREREQUISITES: What Must Be in Place to Run Any of This

### Workspace & UC Setup

| Requirement | How to verify | Critical? |
|-------------|--------------|-----------|
| **Unity Catalog enabled** | `SHOW CATALOGS` returns results | YES — foundational |
| **Account or Metastore Admin role** | User properties in workspace UI | YES — required for system tables + rate limit APIs |
| **AWS workspace** | Workspace UI under workspace name | YES — currently AWS only; not on AWS GovCloud |
| **Region** | Workspace URL or settings | No — all AWS regions supported; Bedrock requires matching region (e.g., `ap-southeast-1`) for Bedrock provider service |

### Authentication & Tokens

| Requirement | How to verify | Type |
|-------------|--------------|------|
| **Databricks Unified Auth** | `DATABRICKS_HOST` + `DATABRICKS_TOKEN` set or `~/.databrickscfg` configured | Standard |
| **PAT or OAuth M2M for agents** | Generate via workspace Settings → Developer → Access tokens (PAT) or Service Principal (OAuth) | PAT OK for dev; OAuth M2M recommended for production (auto-expires, auto-rotates) |
| **UC HTTP Connection (for external MCP servers)** | `SHOW CONNECTIONS` | Required if registering external MCP servers with auth (e.g., bearer token) |
| **IAM credentials for external providers** | AWS IAM key (Bedrock: long-term user key AKIA…), OpenAI API key, Anthropic API key, etc. | Required per external provider registered |

### Networking & Egress

| Requirement | Details |
|-------------|---------|
| **Outbound HTTPS to LLM providers** | AI Gateway control plane initiates requests to OpenAI, Anthropic, Bedrock, etc. Customer-side firewall rules don't apply (outbound originates from Databricks control plane, not customer VPC) |
| **NCC Private Link (for VPCE-locked credentials)** | Optional but recommended for production Bedrock access. Requires `databricks_mws_ncc_private_endpoint_rule` with `enabled=true` |
| **Customer VPC egress blocked for inference logging?** | Inference logs written by Zerobus Ingest from Databricks control plane — cannot traverse customer S3 VPCE. Use open or IAM-only buckets |

### Entitlements & Feature Access

| Requirement | Details |
|-------------|---------|
| **Unity Gateway enabled** | Default in workspaces; no preview flag to enable. Check: `SELECT COUNT(*) FROM system.ai_gateway.usage LIMIT 1;` |
| **Service policies (Beta)** | If using ALLOW/DENY/ASK policies, account admins enable via Previews page in account console |
| **Account admin access** | Required to: publish Agent Configuration, set up NCC VPCE rules, enable/disable Beta features |
| **Inference logging permissions** | Must have MODIFY on UC tables. Auto-created Delta table must be writable by AI Gateway service principal |

### Catalog & Schema Prep

```sql
-- Create working schemas for labs (run once per workspace)
CREATE SCHEMA IF NOT EXISTS main.ai_services 
  COMMENT 'Workshop model and MCP services';
CREATE SCHEMA IF NOT EXISTS main.ai_policies 
  COMMENT 'Workshop guardrail UDFs';
CREATE SCHEMA IF NOT EXISTS main.ai_inference 
  COMMENT 'Workshop inference log tables';
```

### Python Environment (for SDKs)

```bash
pip install databricks-sdk>=0.20.0 openai>=1.30.0 anthropic>=0.30.0
```

**Confirm installation**:
```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
print(w.current_user.me().user_name)
```

### Verification Queries (System Tables Active)

```sql
-- Verify Unity Gateway system tables exist and are populated
SELECT COUNT(*) FROM system.ai_gateway.usage LIMIT 1;

-- List all Databricks-hosted FMAPIs visible in Unity Catalog
SHOW SERVICES IN CATALOG system SCHEMA ai;
```

**Source**: `workshop/setup.md` (all requirements); `docs/overview.md` (comparison + limitations); `docs/auth-networking.md` (networking details); `docs/model-services.md` (Bedrock region gotchas)

---

## Cross-References & Official Documentation

**Primary sources** (databricks-field-eng/platform-architecture-patterns):
- `docs/overview.md` — feature map, behaviors, vs legacy AI Gateway
- `docs/architecture.md` — 4 layers, 6 patterns, schema organization
- `docs/auth-networking.md` — authentication, UC RBAC, request lifecycle (8 steps), policy execution model
- `docs/model-services.md` — model services, external providers, Bedrock + VPCE + `aws:sourceVpce`
- `docs/guardrails.md` — custom guardrails, built-in policies, CEL constraints, mutation limitations
- `docs/mcp-services.md` — MCP as UC securable, tool restrictions, observability, limitations
- `docs/observability.md` — system tables (`system.ai_gateway.usage`, payload table, spend table), SQL cookbook (12 queries)
- `docs/coding-agents.md` — `ug` CLI, Codex Desktop integration, tracing
- `workshop/README.md` — delivery format (half-day, full-day, 2-day), modules 01–08 + 3 scenarios
- `workshop/setup.md` — prerequisites, auth, catalog setup, verification

**Public Databricks documentation** (verified via WebFetch):
- https://docs.databricks.com/aws/en/ai-gateway/ — overview (no explicit GA/Beta labels in main page)
- https://docs.databricks.com/aws/en/ai-gateway/model-services — unsupported capabilities (SQL, BROWSE, global search)
- https://docs.databricks.com/aws/en/ai-gateway/rate-limits — rate limit configuration (no concrete QPM/TPM maximums listed)
- https://docs.databricks.com/aws/en/data-governance/unity-catalog/service-policies/ — **Beta** status, ALLOW/DENY/ASK decisions
- https://docs.databricks.com/aws/en/ai-gateway/inference-tables — payload logging, 10 MB limit, private VPCE limitation, at-least-once delivery
- https://docs.databricks.com/aws/en/agents/mcp/mcp-services — MCP creation, tool restrictions, UC HTTP connections
- https://docs.databricks.com/aws/en/ai-gateway/usage-tracking — usage table reference

---

**Fact pack compiled**: September 28, 2026
**Source repository**: databricks-field-eng/platform-architecture-patterns (ai-components/unity-gateway/)
**Repository commit hash**: Not explicitly recorded; docs dated July 2026, some empirical validation September 2026
**Verification method**: GitHub API (`gh api`), WebFetch, direct file read
