# Unity Gateway Demo — Verified Working Facts (DEFAULT / Azure workspace)

Workspace: `https://adb-7405607317163570.10.azuredatabricks.net` (Azure)
Profile: `DEFAULT` (auth type: PAT)
User/owner: simran.vanjani@databricks.com

> These are EMPIRICALLY VERIFIED on this workspace (2026-09-28). Where they differ
> from FACTPACK.md, they win — the fact pack docs are AWS-era.

## Resources created
- Serverless SQL warehouse: `unity-gateway-demo` id=`599bb5fa4485eb2b` (2X-Small, auto-stop 5m)
- Catalog: `sv_unity_gw` (pre-existing managed catalog)
- Schemas: `sv_unity_gw.ai_services`, `sv_unity_gw.ai_policies`, `sv_unity_gw.ai_inference`
- Model service: `sv_unity_gw.ai_services.demo_llm` -> `models/system.ai.databricks-claude-sonnet-4-6`

## CLI surface (correct)
- Command group: `databricks ai-gateway` (NOT raw REST, NOT SQL DDL)
  - `create-model-service PARENT MODEL_SERVICE_ID --json @body.json`
  - `create-model-provider-service`, `create-mcp-service`, list/get/update/delete variants
- PARENT format: `schemas/{catalog}.{schema}`

## Model service create body (VERIFIED schema)
```json
{
  "config": { "routing": { "destinations": [
    { "destination_type": "DESTINATION_TYPE_PAY_PER_TOKEN_FOUNDATION_MODEL",
      "name": "claude_primary", "traffic_percentage": 100,
      "pay_per_token_config": { "model": "models/system.ai.databricks-claude-sonnet-4-6" } }
  ] } }
}
```
Note: fact pack's `foundation_model_config`/`model_api` is WRONG. Use `pay_per_token_config.model`
with the FMAPI model name (`databricks-claude-sonnet-4-6`), prefixed `models/`.

## Invocation (VERIFIED)
- Route: `POST {HOST}/ai-gateway/mlflow/v1/chat/completions`  (NOT `/model-services/{fqn}/invocations`)
- Auth: `Authorization: Bearer <PAT>`
- Body: `{"model":"<model-service-FQN>","messages":[...],"max_tokens":N}`
- The `model` field carries the model-service FQN (`sv_unity_gw.ai_services.demo_llm`).
- Returns OpenAI-style chat.completion; `usage` has prompt/completion/total + cache tokens.
- Get PAT for curl: `databricks auth env --profile DEFAULT` -> `.env.DATABRICKS_TOKEN`

## Available system.ai FMAPI chat models (this workspace)
claude-sonnet-5, claude-sonnet-4-6, claude-opus-5-5, claude-opus-4-8, claude-haiku-4-5,
gpt-oss-120b, gpt-oss-20b, llama-4-maverick, qwen3-next-80b, gemma-3-12b, meta-llama-3-3-70b, ...

## Observability
- `system.ai_gateway.usage` is populated (~993K rows). Query via warehouse `599bb5fa4485eb2b`.
- Only gateway-routed calls appear; ~5-30 min lag.

## Rate limits (VERIFIED -> 429)
- `update-model-service NAME UPDATE_MASK --json` ; NAME=`model-services/{cat}.{sch}.{svc}`, MASK=`config.rate_limits`
- rate_limits is a LIST. Per-user item (proto enums, exact):
```json
{"key":"RATE_LIMIT_KEY_USER","renewal_period":"RATE_LIMIT_RENEWAL_PERIOD_MINUTE",
 "principal":"<user-email>","requests":2}
```
- `principal` required when key=RATE_LIMIT_KEY_USER. Limit field is `requests` (RPM). `RATE_LIMIT_KEY_ENDPOINT` NOT accepted; only `RATE_LIMIT_KEY_USER` worked.
- 429 body: `{"error_code":"REQUEST_LIMIT_EXCEEDED","message":"User defined rate limit(s) exceeded ... Requests-per-minute (RPM) ..."}`
- Clear with `{"config":{"rate_limits":[]}}` (becomes null).

## TODO / to verify next
- [x] Governed call -> 200
- [x] Rate limit -> 429
- [ ] Confirm calls show in system.ai_gateway.usage (wait for lag ~5-30m)
- [ ] Service policy / guardrail attach (Beta) -> policy block
- [ ] Access control -> 403 (needs a 2nd principal w/o EXECUTE; can't revoke own owner access cleanly)
- [ ] MCP service create (create-mcp-service) + tool restrictions
- [ ] Coding agents: ug CLI local setup
