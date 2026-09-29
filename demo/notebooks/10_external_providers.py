# Databricks notebook source
# MAGIC %md
# MAGIC # 10 · External model providers (CHOICE, provider-agnostic)
# MAGIC Unity Gateway governs **external** LLM providers too — OpenAI, Azure OpenAI, Anthropic, Amazon
# MAGIC Bedrock, Microsoft Foundry, Google Gemini, or a custom endpoint — as a **Model Provider Service**
# MAGIC (a UC securable), so the same access / guardrails / cost / observability apply.
# MAGIC
# MAGIC > Reference notebook — creating a provider service needs **your provider credentials**, so the
# MAGIC > create cell is left commented. The mechanics are generic across clouds; Bedrock notes are AWS-specific.

# COMMAND ----------

import requests, json
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
HOST = ctx.apiUrl().get(); TOKEN = ctx.apiToken().get()
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# COMMAND ----------

# MAGIC %md ## Model service vs Model provider service
# MAGIC | | Model Service | Model Provider Service |
# MAGIC |--|--------------|------------------------|
# MAGIC | Backends | Databricks-hosted `system.ai.*` FMAPIs | External providers (OpenAI, Bedrock, Anthropic, …) |
# MAGIC | Traffic splitting | Yes | No — caller specifies the model per request |
# MAGIC | Guardrails | Yes | Yes |
# MAGIC | Rate limits | QPM + token budget | QPM |
# MAGIC | Invocation | OpenAI/Anthropic shape via the gateway | Native provider API shape via header routing |

# COMMAND ----------

# MAGIC %md ## Create a provider service (CLI) — template
# MAGIC ```bash
# MAGIC databricks ai-gateway create-model-provider-service \
# MAGIC   schemas/<catalog>.<schema> <name> --json @provider.json --profile DEFAULT
# MAGIC ```
# MAGIC Confirm the exact `--json` body for your provider with:
# MAGIC `databricks ai-gateway create-model-provider-service --help`.
# MAGIC You supply: provider type, region/base URL, credentials (secret-backed), and allowed target models.

# COMMAND ----------

# MAGIC %md ## Invoke via the native provider shape (header routing)
# MAGIC ```python
# MAGIC # e.g. Anthropic-shape provider service
# MAGIC r = requests.post(f"{HOST}/ai-gateway/anthropic/v1/messages", headers={
# MAGIC         "Authorization": f"Bearer {TOKEN}",
# MAGIC         "Databricks-Model-Provider-Service": "<catalog>.<schema>.<provider_service>"},
# MAGIC     json={"model": "<provider-model-id>", "max_tokens": 128, "messages": [...]})
# MAGIC ```
# MAGIC URL by shape: Anthropic/Bedrock-Anthropic → `anthropic/v1/messages`; OpenAI/Azure OpenAI →
# MAGIC `openai/v1/chat/completions`; Google → `google/v1/...`.

# COMMAND ----------

# MAGIC %md ## Amazon Bedrock notes (AWS-specific)
# MAGIC - Use a **long-term IAM user key (AKIA…)**, not an IAM role (no session-token refresh in the provider service).
# MAGIC   Needs `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream`.
# MAGIC - Newer models need a **cross-region inference profile** (e.g. `global.anthropic.claude-sonnet-5`).
# MAGIC - **Multiple targets = an allowlist**, not load balancing — the caller picks the model each request.
# MAGIC - Optional hardening: lock the credential to a Databricks-managed **NCC VPCE** via `aws:sourceVpce`.
# MAGIC - Bedrock supports the `anthropic/v1/messages` shape (not OpenAI format).

# COMMAND ----------

# MAGIC %md ## List provider services already registered here

# COMMAND ----------

r = requests.get(f"{HOST}/api/2.1/unity-catalog/model-provider-services",
                 headers=H, params={"parent": "schemas/system.ai", "view": "FULL"})
print("HTTP", r.status_code)
print(json.dumps(r.json(), indent=2)[:800])

# COMMAND ----------

# MAGIC %md
# MAGIC ✅ Same governance, any provider. Guardrails, cost tracking, and access control apply uniformly —
# MAGIC that is the **CHOICE** pillar: the org controls which providers/models are allowed, from one place.
